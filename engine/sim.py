"""
Engine fasor quasi-steady-state (QSS) 3-fasa untuk IEEE 34 + Penyulang B.

Setiap langkah dt (default 1/960 s = 16 langkah/siklus):
  1. Rakit matriks admitansi nodal 3-fasa Y (cache per topologi/gangguan).
  2. Tambah admitansi & injeksi Norton sumber (GI, SG, GFM) + injeksi arus IBR.
  3. Solve V = Y^-1 I, hitung arus semua cabang.
  4. Virtual IED membaca fasor (filter 1 siklus), memutuskan trip; CB membuka
     setelah waktu CB (default 50 ms).
  5. DER memperbarui keadaan (PLL/lag/limit, peluruhan X'', proteksi DER).
"""
from __future__ import annotations
import copy
import time as _time
import numpy as np

from .network import (base_network, branch_Zabc, split_line_for_fault, path_from_source,
                      LOAD_LEVELS, config_Z, seq_from_abc)
from .der import make_der, seq, Yabc_from_seq, POS, A as SEQA, IBR_GFM, SG
from .relays import IED

PH = "abc"
Y_TINY = 1e-6


class Model:
    """Topologi + pemetaan node untuk satu skenario."""

    def __init__(self, scenario):
        self.sc = scenario
        net = base_network()
        # --- parameter grid
        sub = scenario.get("grid", {})
        net["substation"].update({k: v for k, v in sub.get("substation", {}).items()})
        for br in net["branches"]:
            if br["kind"] == "reg":
                taps = sub.get("reg_taps", {}).get(br["id"])
                if taps:
                    br["taps"] = list(taps)
        # --- sisipkan bus gangguan di tengah saluran bila perlu
        self.fault_nodes = []
        for i, f in enumerate(scenario.get("faults", [])):
            if f.get("line"):
                fb = f"F{i+1}"
                net = split_line_for_fault(net, f["line"], f.get("frac", 0.5), fb)
                f["_node"] = fb
            else:
                f["_node"] = f["bus"]
            self.fault_nodes.append(f["_node"])
        self.net = net
        # --- indeks node-fasa
        self.idx = {}
        n = 0
        for b, bus in net["buses"].items():
            for p in bus["phases"]:
                self.idx[(b, p)] = n
                n += 1
        self.N = n
        self.bus_list = list(net["buses"].keys())
        # matriks pemilih V per bus (3 kolom)
        self.bus_sel = np.full((len(self.bus_list), 3), -1, dtype=int)
        for i, b in enumerate(self.bus_list):
            for k, p in enumerate(PH):
                if (b, p) in self.idx:
                    self.bus_sel[i, k] = self.idx[(b, p)]
        self.bus_index = {b: i for i, b in enumerate(self.bus_list)}
        self._build_branches()
        self._build_shunts()

    # ---------------------------------------------------------------- cabang
    def _build_branches(self):
        net = self.net
        self.br_list = net["branches"]
        self.br_index = {br["id"]: i for i, br in enumerate(self.br_list)}
        self.br_stamps = []
        nb = len(self.br_list)
        self.M_from = np.zeros((nb * 3, self.N), complex)    # I_from = M V
        self.M_to = np.zeros((nb * 3, self.N), complex)      # I_to (masuk node 'to' -> keluar cabang)
        for i, br in enumerate(self.br_list):
            ph = br["phases"]
            fi = [self.idx[(br["from"], p)] for p in ph]
            ti = [self.idx[(br["to"], p)] for p in ph]
            kk = [PH.index(p) for p in ph]
            if br["kind"] == "line":
                Z = branch_Zabc(br)[np.ix_(kk, kk)]
                Yl = np.linalg.inv(Z)
                Yff, Yft, Ytf, Ytt = Yl, -Yl, -Yl, Yl
            elif br["kind"] == "reg":
                n = np.array([1 + 0.00625 * br["taps"][k] for k in kk])
                y = 1.0 / complex(0.01, 0.05)
                Yff = np.diag(n * n * y); Yft = np.diag(-n * y)
                Ytf = np.diag(-n * y); Ytt = np.diag(np.full(len(kk), y))
            elif br["kind"] == "xfmr":
                n = br["kv2"] / br["kv1"]
                zb = (br["kv2"] ** 2) / (br["kva"] / 1e3)
                y = 1.0 / (complex(br["r_pct"], br["x_pct"]) / 100 * zb)
                m = len(kk)
                Yff = np.eye(m) * n * n * y; Yft = -np.eye(m) * n * y
                Ytf = -np.eye(m) * n * y; Ytt = np.eye(m) * y
            self.br_stamps.append((fi, ti, Yff, Yft, Ytf, Ytt))
            for a_, k in enumerate(kk):
                r = i * 3 + k
                self.M_from[r, fi] += Yff[a_, :]
                self.M_from[r, ti] += Yft[a_, :]
                self.M_to[r, fi] += -Ytf[a_, :]
                self.M_to[r, ti] += -Ytt[a_, :]

    # ---------------------------------------------------------------- shunt
    def _build_shunts(self):
        net = self.net
        sc = self.sc
        load = sc.get("load", {})
        lvl = load.get("level", "puncak_malam")
        scale = LOAD_LEVELS.get(lvl, lvl if isinstance(lvl, (int, float)) else 1.0)
        unb = load.get("phase_scale", [1.0, 1.0, 1.0])
        self.load_scale_static = scale
        N = self.N
        self.YL = {"A": np.zeros((N, N), complex), "B": np.zeros((N, N), complex)}
        self.load_info = []
        for ld in net["loads"]:
            bus = net["buses"][ld["bus"]]
            fd = "B" if bus["feeder"] == "B" else "A"
            vph = bus["vbase"]
            Y = np.zeros((N, N), complex)
            for k in range(3):
                S = complex(ld["P"][k], ld["Q"][k]) * 1e3 * scale * unb[k]
                if abs(S) < 1e-9:
                    continue
                if ld["conn"] == "Y":
                    p = PH[k]
                    if (ld["bus"], p) not in self.idx:
                        continue
                    i = self.idx[(ld["bus"], p)]
                    Y[i, i] += np.conj(S) / vph ** 2
                else:
                    p, q = PH[k], PH[(k + 1) % 3]
                    if (ld["bus"], p) not in self.idx or (ld["bus"], q) not in self.idx:
                        continue
                    i, j = self.idx[(ld["bus"], p)], self.idx[(ld["bus"], q)]
                    y = np.conj(S) / (3 * vph ** 2)
                    Y[i, i] += y; Y[j, j] += y; Y[i, j] -= y; Y[j, i] -= y
            self.YL[fd] += Y
            self.load_info.append({"id": ld["id"], "bus": ld["bus"], "feeder": fd,
                                   "P": [p * scale * u for p, u in zip(ld["P"], unb)],
                                   "Q": [q * scale * u for q, u in zip(ld["Q"], unb)],
                                   "conn": ld["conn"], "model": ld["model"]})
        # kapasitor
        caps_on = sc.get("grid", {}).get("caps", {"C844": True, "C848": True})
        self.Ycap = np.zeros((N, N), complex)
        self.cap_info = []
        for c in net["caps"]:
            on = caps_on.get(c["id"], True)
            self.cap_info.append({**c, "on": on})
            if not on:
                continue
            vph = net["buses"][c["bus"]]["vbase"]
            for k, p in enumerate(PH):
                i = self.idx[(c["bus"], p)]
                self.Ycap[i, i] += 1j * c["kvar"][k] * 1e3 / vph ** 2
        # gardu induk (Thevenin di bus 800)
        sub = net["substation"]
        zb = sub["kv_lv"] ** 2 / (sub["kva"] / 1e3)
        Zs = complex(sub["r_pct"], sub["x_pct"]) / 100 * zb
        self.Zsub = Zs
        self.Ysub = Yabc_from_seq(1 / Zs, 1 / Zs, 1 / Zs)
        vph = net["buses"]["800"]["vbase"]
        self.Esub = sub["v_pu"] * vph * POS
        self.sub_idx = [self.idx[("800", p)] for p in PH]

    def fault_Y(self, f, node):
        """Admitansi gangguan (3x3 pada node) + indeks."""
        bus = self.net["buses"][node]
        rf = max(float(f.get("rf", 0.0)), 1e-3)
        y = 1.0 / rf
        typ = f["type"]
        phs = f.get("phases", "a")
        Y = np.zeros((3, 3), complex)
        k = [PH.index(p) for p in phs if p in bus["phases"]]
        if not k:                       # lateral 1-fasa: pakai fasa yang ada
            k = [PH.index(p) for p in bus["phases"]]
        if typ == "SLG":
            for i in k[:1]:
                Y[i, i] += y
        elif typ == "LL":
            if len(k) >= 2:
                i, j = k[0], k[1]
                Y[i, i] += y; Y[j, j] += y; Y[i, j] -= y; Y[j, i] -= y
        elif typ == "DLG":
            for i in k[:2]:
                Y[i, i] += y
            if len(k) >= 2:
                i, j = k[0], k[1]
                yp = 1.0 / 1e-3
                Y[i, i] += yp; Y[j, j] += yp; Y[i, j] -= yp; Y[j, i] -= yp
        elif typ == "3PH":
            for i in [PH.index(p) for p in bus["phases"]]:
                Y[i, i] += y
        idx = [self.idx.get((node, p), -1) for p in PH]
        return Y, idx


class Simulator:
    def __init__(self, scenario, settings, verbose=False):
        self.sc = copy.deepcopy(scenario)
        self.model = Model(self.sc)
        self.settings = settings
        simc = self.sc.get("sim", {})
        self.f0 = self.model.net["f0"]
        self.dt = simc.get("dt", 1.0 / 960.0)
        self.T = simc.get("duration", 3.0)
        self.t_cb = simc.get("t_cb", 0.05)
        self.verbose = verbose
        self.events_sim = []       # God SOE
        self._init_ders()
        self._init_ieds()
        self._init_state()

    # ---------------------------------------------------------------- DER
    def _init_ders(self):
        m = self.model
        dercfg = self.sc.get("der", {})
        units = dercfg.get("units", [])
        pen = dercfg.get("penetration", None)
        base_kw = sum(sum(l["P"]) for l in base_network()["loads"]
                      if base_network()["buses"][l["bus"]]["feeder"] != "B")
        self.base_load_kw = base_kw
        wtot = sum(u.get("weight", 1.0) for u in units) or 1.0
        self.ders = []
        for i, u in enumerate(units):
            u = dict(u)
            u.setdefault("id", f"DER{i+1}")
            fd = "B" if m.net["buses"][u["bus"]]["feeder"] == "B" else "A"
            if pen is not None and "kva" not in u:
                u["kva"] = pen / 100.0 * base_kw * u.get("weight", 1.0) / wtot
            u.setdefault("kva", 0.0)
            d = make_der(u, m.net["buses"][u["bus"]]["vbase"], self.f0)
            d.idx = [m.idx[(u["bus"], p)] for p in PH]
            d.feeder = fd
            self.ders.append(d)

    def _init_ieds(self):
        m = self.model
        cls_map = self.sc.get("relays", {}).get("classes", {})
        default = self.sc.get("relays", {}).get("default", "OCR")
        self.ieds = []
        self.cb_state = {}
        self.cb_pending = {}
        for meta in m.net["ieds"]:
            br = next(b for b in m.br_list if b["from"] == meta["from"] and b["to"] == meta["to"])
            meta = dict(meta, branch=br["id"])
            cls = cls_map.get(meta["id"], default)
            ied = IED(meta, self.settings[meta["id"]], cls, self.dt, self.f0)
            ied.br_i = m.br_index[br["id"]]
            ied.v_idx = m.bus_sel[m.bus_index[meta["from"]]]
            self.ieds.append(ied)
            self.cb_state[meta["id"]] = True
        self.ied_by_id = {d.id: d for d in self.ieds}
        # status awal CB dari skenario
        for k, v in self.sc.get("grid", {}).get("cb_init", {}).items():
            self.cb_state[k] = v

    def _init_state(self):
        g = self.sc.get("grid", {})
        self.mode = g.get("mode", "grid")
        self.sub_connected = self.mode == "grid"
        self.t_island = g.get("t_island")          # pembukaan CB GI terjadwal
        self.manual_ops = sorted(self.sc.get("events", []), key=lambda e: e["t"])
        clpu = self.sc.get("load", {}).get("clpu", {})
        self.clpu = clpu if clpu.get("enable") else None
        self.freq = self.f0
        self.Pm_island = None
        self.Y_cache = {}

    # ---------------------------------------------------------------- topologi
    def open_branches(self):
        return frozenset(self.ied_by_id[k].meta["branch"] for k, v in self.cb_state.items() if not v)

    def connectivity(self):
        """Kembalikan set bus yang terhubung ke GI (bila GI terhubung)."""
        m = self.model
        opened = self.open_branches()
        adj = {b: [] for b in m.bus_list}
        for br in m.br_list:
            if br["id"] in opened:
                continue
            adj[br["from"]].append(br["to"]); adj[br["to"]].append(br["from"])
        def bfs(s):
            seen = {s}; st = [s]
            while st:
                u = st.pop()
                for v in adj[u]:
                    if v not in seen:
                        seen.add(v); st.append(v)
            return seen
        grid = bfs("800") if self.sub_connected else set()
        comps = []
        left = set(m.bus_list) - grid
        while left:
            s = next(iter(left)); c = bfs(s); comps.append(c); left -= c
        return grid, comps

    def static_Y(self, active_faults):
        key = (self.open_branches(), tuple(sorted(active_faults)), self.sub_connected)
        if key in self.Y_cache:
            return self.Y_cache[key]
        m = self.model
        Y = np.zeros((m.N, m.N), complex)
        Y[np.diag_indices(m.N)] += Y_TINY
        opened = key[0]
        for i, br in enumerate(m.br_list):
            if br["id"] in opened:
                continue
            fi, ti, Yff, Yft, Ytf, Ytt = m.br_stamps[i]
            Y[np.ix_(fi, fi)] += Yff; Y[np.ix_(fi, ti)] += Yft
            Y[np.ix_(ti, fi)] += Ytf; Y[np.ix_(ti, ti)] += Ytt
        Y += m.Ycap
        if self.sub_connected:
            si = m.sub_idx
            Y[np.ix_(si, si)] += m.Ysub
        for fi_ in active_faults:
            f = self.sc["faults"][fi_]
            Yf, idx = m.fault_Y(f, f["_node"])
            for a_ in range(3):
                for b_ in range(3):
                    if idx[a_] >= 0 and idx[b_] >= 0 and Yf[a_, b_] != 0:
                        Y[idx[a_], idx[b_]] += Yf[a_, b_]
        self.Y_cache[key] = Y
        return Y

    def load_scale(self, t, feeder):
        if self.clpu and feeder in self.clpu.get("feeders", ["A"]):
            t0 = self.clpu.get("t_energize", 0.5)
            if t >= t0:
                return 1 + (self.clpu.get("factor", 2.5) - 1) * np.exp(-(t - t0) / self.clpu.get("tau", 2.0))
        return 1.0

    def assemble(self, t, active_faults):
        m = self.model
        Y = self.static_Y(active_faults).copy()
        Y += m.YL["A"] * self.load_scale(t, "A") + m.YL["B"] * self.load_scale(t, "B")
        Iinj = np.zeros(m.N, complex)
        if self.sub_connected:
            Iinj[m.sub_idx] += m.Ysub @ m.Esub
        for d in self.ders:
            if not d.online:
                continue
            Yd = d.admittance(t)
            if Yd is not None:
                Y[np.ix_(d.idx, d.idx)] += Yd
            Iinj[d.idx] += d.injection(t)
        return Y, Iinj

    def solve(self, t, active_faults):
        Y, I = self.assemble(t, active_faults)
        V = np.linalg.solve(Y, I)
        # pembatas arus GFM
        redo = False
        for d in self.ders:
            if isinstance(d, IBR_GFM) and d.check_limit(t, V[d.idx]):
                redo = True
        if redo:
            Y, I = self.assemble(t, active_faults)
            V = np.linalg.solve(Y, I)
        return V

    # ---------------------------------------------------------------- inisialisasi
    def initialize(self):
        for d in self.ders:
            if hasattr(d, "E1"):
                d.E1 = d.vbase * POS[0]
            d.I1 = 0j if hasattr(d, "I1") else None
        V = None
        island0 = not self.sub_connected
        for it in range(25):
            V = self.solve(0.0, [])
            for d in self.ders:
                if not d.online:
                    continue
                if island0 and isinstance(d, (SG, IBR_GFM)):
                    # mode pulau: sumber grid-forming = swing (|E| tetap, P mengikuti beban)
                    d.E1 = 1.03 * d.vbase + 0j
                else:
                    d.init_from(V[d.idx], 0.0)
        self.V0 = V
        return V

    # ---------------------------------------------------------------- loop
    def run(self):
        t_wall = _time.time()
        m = self.model
        faults = self.sc.get("faults", [])
        dt = self.dt
        nsteps = int(round(self.T / dt)) + 1
        nb = len(m.br_list)
        self.t = np.arange(nsteps) * dt
        self.V = np.zeros((nsteps, m.N), np.complex64)
        self.Ib = np.zeros((nsteps, nb * 3), np.complex64)
        self.Ider = np.zeros((nsteps, len(self.ders), 3), np.complex64)
        self.Pder = np.zeros((nsteps, len(self.ders), 2), np.float32)
        self.der_on = np.zeros((nsteps, len(self.ders)), bool)
        self.Ifault = np.zeros((nsteps, max(len(faults), 1), 3), np.complex64)
        self.freq_t = np.zeros(nsteps, np.float32)
        self.cb_t = np.zeros((nsteps, len(self.ieds)), bool)
        self.sub_t = np.zeros(nsteps, bool)
        self.irr_t = np.zeros((nsteps, len(self.ders)), np.float32)
        self.relay_dir = {d.id: [] for d in self.ieds}
        self.relay_Z = {d.id: [] for d in self.ieds}
        self.relay_prog = np.zeros((nsteps, len(self.ieds), 2), np.float32)
        self.relay_Imeas = np.zeros((nsteps, len(self.ieds), 3), np.complex64)
        self.relay_Vmeas = np.zeros((nsteps, len(self.ieds), 3), np.complex64)

        # sinkronkan status CB awal
        self.initialize()
        grid, comps = self.connectivity()
        fault_on_prev = [False] * len(faults)
        self.fault_clear_t = [None] * len(faults)
        self.tau_dc = [0.0] * len(faults)
        last_topo = None
        mop_i = 0

        for k in range(nsteps):
            t = k * dt
            # --- kejadian manual / terjadwal
            while mop_i < len(self.manual_ops) and self.manual_ops[mop_i]["t"] <= t + 1e-9:
                ev = self.manual_ops[mop_i]; mop_i += 1
                if ev["type"] in ("CB_OPEN", "CB_CLOSE"):
                    self.cb_state[ev["id"]] = ev["type"] == "CB_CLOSE"
                    self.events_sim.append({"t": t, "src": "SIM", "type": ev["type"], "id": ev["id"],
                                            "text": f"Manual operation: {ev['id']} {'CLOSE' if ev['type']=='CB_CLOSE' else 'OPEN'}"
                                                    + (" (energization, cold load pickup)" if self.clpu and ev['type']=='CB_CLOSE' else "")})
            if self.t_island is not None and t >= self.t_island and self.sub_connected:
                self.sub_connected = False
                self.events_sim.append({"t": t, "src": "SIM", "type": "ISLAND", "id": "SUB",
                                        "text": "Substation 69 kV breaker opened; islanded microgrid mode"})
            # --- CB yang sedang membuka
            for cid, tdue in list(self.cb_pending.items()):
                if t >= tdue - 1e-9:
                    self.cb_state[cid] = False
                    del self.cb_pending[cid]
                    self.events_sim.append({"t": t, "src": "SIM", "type": "CB_OPEN", "id": cid,
                                            "text": f"{cid} contacts separated, current interrupted"})
                    self.ied_by_id[cid].events.append({"t": round(t, 4), "src": "IED", "id": cid, "type": "52B",
                                                       "kind": "cb", "text": f"{cid} 52b: CB OPEN"})
            # --- gangguan aktif
            active = []
            for i, f in enumerate(faults):
                on = f["t_on"] <= t + 1e-9 and (f.get("t_off") is None or t < f["t_off"]) and self.fault_clear_t[i] is None
                if on:
                    active.append(i)
                if on and not fault_on_prev[i]:
                    self.events_sim.append({"t": t, "src": "SIM", "type": "FAULT_ON", "id": f"F{i+1}",
                                            "text": self._fault_text(f), "node": f["_node"]})
                if not on and fault_on_prev[i] and self.fault_clear_t[i] is None:
                    self.events_sim.append({"t": t, "src": "SIM", "type": "FAULT_OFF", "id": f"F{i+1}",
                                            "text": f"Fault F{i+1} self-extinguished (transient)"})
                fault_on_prev[i] = on
            any_fault = len(active) > 0
            # --- topologi & pulau
            topo = (self.open_branches(), self.sub_connected)
            if topo != last_topo:
                grid, comps = self.connectivity()
                last_topo = topo
                for c in comps:
                    srcs = [d for d in self.ders if d.online and d.bus in c]
                    if srcs and not any(isinstance(d, (SG, IBR_GFM)) for d in srcs) and self.mode != "grid":
                        pass
            # --- solve
            V = self.solve(t, active)
            # --- fault yang padam karena ter-isolasi (tak ada sumber)
            for i in active:
                f = faults[i]
                Yf, idx = m.fault_Y(f, f["_node"])
                vf = np.array([V[j] if j >= 0 else 0 for j in idx])
                If = Yf @ vf
                self.Ifault[k, i] = If
                if f["_node"] not in grid:
                    fed = [d for d in self.ders if d.online and any(d.bus in c and f["_node"] in c for c in comps)]
                    if not fed and np.max(np.abs(If)) < 1.0 and self.fault_clear_t[i] is None:
                        self.fault_clear_t[i] = t
                        self.events_sim.append({"t": t, "src": "SIM", "type": "FAULT_CLEARED", "id": f"F{i+1}",
                                                "text": f"Fault F{i+1} isolated and extinguished (no remaining source)"})
                if self.tau_dc[i] == 0.0 and np.max(np.abs(If)) > 0:
                    self.tau_dc[i] = self._tau_at(f["_node"], active)
            # --- simpan
            self.V[k] = V
            Ib = m.M_from @ V
            opened = self.open_branches()
            for bid in opened:
                bi = m.br_index[bid]
                Ib[bi * 3:bi * 3 + 3] = 0
            self.Ib[k] = Ib
            self.sub_t[k] = self.sub_connected
            # --- DER
            v_isl = set().union(*comps) if comps else set()
            for j, d in enumerate(self.ders):
                Vd = V[d.idx]
                d.update(t, dt, Vd, any_fault)
                Iout = d.current_out(t, Vd)
                self.Ider[k, j] = Iout
                S = np.sum(Vd * np.conj(Iout))
                self.Pder[k, j] = [S.real / 1e3, S.imag / 1e3]
                self.der_on[k, j] = d.online
                self.irr_t[k, j] = d.irradiance(t) if d.type.startswith("IBR") else np.nan
                v1pu = abs(seq(Vd)[1]) / d.vbase
                unintentional = (d.bus in v_isl) and self.mode == "grid"
                d.protection(t, dt, v1pu, unintentional, self.events_sim)
            # --- frekuensi (pulau)
            self._freq_step(t, dt, grid, comps)
            self.freq_t[k] = self.freq
            # --- IED
            for j, ied in enumerate(self.ieds):
                Iraw = Ib[ied.br_i * 3: ied.br_i * 3 + 3]
                Vraw = np.array([V[x] if x >= 0 else 0 for x in ied.v_idx])
                remote = None
                if ied.cls == "DIFF":
                    p = self.ied_by_id[ied.meta["partner"]]
                    remote = Ib[p.br_i * 3: p.br_i * 3 + 3]
                trip = ied.step(t, Iraw, Vraw, remote)
                self.relay_Imeas[k, j] = ied.last["I"]
                self.relay_Vmeas[k, j] = ied.last["V"]
                self.relay_prog[k, j] = [max(ied.prog["51P"]), ied.prog["51N"]]
                if ied.cls == "DIST" and "Z" in ied.last:
                    self.relay_Z[ied.id].append((k, ied.last["Z"], ied.last.get("zone")))
                if ied.cls == "DOCR" and ied.dir_state:
                    self.relay_dir[ied.id].append((k, ied.dir_state.get("P"), ied.dir_state.get("N"), ied.dir_state.get("Nmeth")))
                if trip:
                    targets = [ied.id]
                    if ied.cls == "DIFF" and ied.meta.get("partner"):
                        targets.append(ied.meta["partner"])
                    for cid in targets:
                        if self.cb_state.get(cid, True) and cid not in self.cb_pending:
                            self.cb_pending[cid] = t + self.t_cb
                            if cid != ied.id:
                                self.ied_by_id[cid].events.append({"t": round(t, 4), "src": "IED", "id": cid,
                                                                   "type": "DTT", "kind": "trip",
                                                                   "text": f"{cid} received Direct Transfer Trip from {ied.id} (87L)"})
            self.cb_t[k] = [self.cb_state[d.id] for d in self.ieds]
        self.wall = _time.time() - t_wall
        return self

    def _tau_at(self, node, active):
        """Konstanta waktu DC offset = X/(wR) Thevenin di titik gangguan."""
        m = self.model
        try:
            Y = self.static_Y([]).copy() + m.YL["A"] + m.YL["B"]
            for d in self.ders:
                Yd = d.admittance(0.0)
                if Yd is not None:
                    Y[np.ix_(d.idx, d.idx)] += Yd
            i = m.idx.get((node, m.net["buses"][node]["phases"][0]))
            e = np.zeros(m.N, complex); e[i] = 1
            Zth = np.linalg.solve(Y, e)[i]
            return float(max(Zth.imag, 1e-3) / (2 * np.pi * self.f0 * max(Zth.real, 1e-3)))
        except Exception:
            return 0.01

    def _freq_step(self, t, dt, grid, comps):
        if self.sub_connected:
            self.freq = self.f0
            self.Pm_island = None
            return
        srcs = [d for d in self.ders if d.online and isinstance(d, (SG, IBR_GFM))]
        if not srcs:
            self.freq = self.f0 if not any(d.online for d in self.ders) else self.freq
            return
        Pe = sum(float(self.Pder[int(round(t / dt)), j, 0]) * 1e3 for j, d in enumerate(self.ders) if d.online)
        Stot = sum(d.S for d in srcs)
        Htot = sum(getattr(d, "H", 1.0) * d.S for d in srcs) / max(Stot, 1)
        if self.Pm_island is None:
            self.Pm_island = Pe
        R = 0.05
        Pm = self.Pm_island - Stot / R * (self.freq - self.f0) / self.f0
        Pm = min(max(Pm, 0), Stot * 1.1)
        dfdt = self.f0 / (2 * Htot * Stot) * (Pm - Pe)
        self.freq = float(np.clip(self.freq + dfdt * dt, 55.0, 65.0))

    def _fault_text(self, f):
        typ = f["type"]
        ph = f.get("phases", "a").upper()
        lbl = {"SLG": f"SLG {ph}-G", "LL": f"LL {ph}", "DLG": f"DLG {ph}-G", "3PH": "Three-phase (3PH)"}[typ]
        loc = f"line {f['line']} at {f.get('frac',0.5)*100:.0f}%" if f.get("line") else f"bus {f['bus']}"
        return f"Fault inception: {lbl} at {loc}, Rf = {f.get('rf',0)} Ω"
