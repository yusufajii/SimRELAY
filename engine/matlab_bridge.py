"""
Bridge between the SimRelay app and the MATLAB/Simulink (Simscape Electrical) engine.

The app keeps ownership of every input: network topology and parameters, relay logic and
settings, DER configuration, irradiance, load level and simulation events. This module turns a
scenario into a generic netlist (``export_config``) that matlab/sr34_build.m converts into a
Simscape Electrical phasor model, runs the model through the MATLAB Engine API, and wraps the
results in an object with the same interface as ``engine.sim.Simulator`` so the Fault Hunter,
the result packer and the UI work unchanged.

Node numbering in the netlist: 0 = ground, 1..N = the node-phases of engine.sim.Model (same
order as Model.idx), N+1.. = internal nodes created here.
"""
from __future__ import annotations
import copy
import json
import os
import threading
import time
import numpy as np

from .network import branch_Zabc, LOAD_LEVELS
from .sim import Model, PH
from .der import POS, Yabc_from_seq

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MATLAB_DIR = os.path.join(ROOT, "matlab")
CLS_CODE = {"OCR": 1, "DOCR": 2, "DIST": 3, "DIFF": 4}
DER_CODE = {"SG": 1, "IBR-GFL": 2, "IBR-GFM": 3}
FAULT_CODE = {"SLG": 1, "LL": 2, "DLG": 3, "3PH": 4}
CURVE_CODE = {"IEC_SI": 1, "IEC_VI": 2, "IEC_EI": 3, "IEEE_MI": 4, "IEEE_VI": 5, "IEEE_EI": 6}
T_INIT = 0.1          # seconds simulated before t = 0 so DER outputs settle on their setpoints
R_MIN = 1e-4          # smallest resistance used for ideal switches and series elements


def _c(z):
    return [float(np.real(z)), float(np.imag(z))]


class Netlist:
    def __init__(self, n_nodes):
        self.n = n_nodes
        self.el = []
        self.n_ctrl_brk = 0     # breaker control channels
        self.n_ctrl_v = 0       # controlled voltage source channels
        self.n_ctrl_i = 0       # controlled current source channels
        self.n_imeas = 0
        self.groups = []        # diagram groups: one Simulink subsystem each (layout only)
        self.g = 0              # group of the elements added next (1-based)

    def node(self):
        self.n += 1
        return self.n

    def group(self, name, left="", right="", x=0.0, y=0.0, kind="", info=None):
        """Start a diagram group. LEFT is the bus whose nodes enter on the left side of the
        subsystem (the group hangs downstream of it), RIGHT the bus on the right side (the group
        feeds it from upstream). X, Y place the subsystem in single-line diagram coordinates.
        KIND selects the composite block icon and INFO lines go to its parameter dialog."""
        name = name.replace("/", "-")
        for i, g in enumerate(self.groups):
            if g["name"] == name:
                self.g = i + 1
                for line in info or []:
                    if line not in g["info"]:
                        g["info"].append(line)
                return
        self.groups.append({"name": name, "left": left, "right": right, "x": float(x), "y": float(y),
                            "kind": kind, "info": list(info or [])})
        self.g = len(self.groups)

    def add(self, **kw):
        kw["g"] = self.g
        self.el.append(kw)
        return kw

    def imeas(self, a, b=None):
        """Series current measurement from node a; returns (new node, measurement channel)."""
        b = b or self.node()
        self.n_imeas += 1
        self.add(type="imeas", a=a, b=b, ch=self.n_imeas)
        return b, self.n_imeas

    def breaker(self, a, b, ron=R_MIN, closed=True):
        self.n_ctrl_brk += 1
        self.add(type="brk", a=a, b=b, ron=float(max(ron, R_MIN)), init=int(bool(closed)), ch=self.n_ctrl_brk)
        return self.n_ctrl_brk

    def rl(self, a, b, z):
        """Series impedance z (ohm, complex) between nodes a and b (b = 0: ground)."""
        z = complex(z)
        self.add(type="rl", a=a, b=b, r=float(max(z.real, 0.0)), x=float(z.imag))

    def vsrc(self, a, b):
        self.n_ctrl_v += 1
        self.add(type="vsrc", a=a, b=b, ch=self.n_ctrl_v)
        return self.n_ctrl_v

    def isrc(self, a, b=0):
        """Current source injecting into node a (returning through b).

        SPS models current sources as ideal; a 1 Mohm shunt keeps every topology solvable
        (otherwise some cut sets contain only current sources and inductances)."""
        self.n_ctrl_i += 1
        self.add(type="isrc", a=a, b=b, ch=self.n_ctrl_i)
        self.rl(a, b, 1e6)
        return self.n_ctrl_i


def export_config(scenario, settings, f0=60.0):
    """Scenario (app format) to engine netlist + controller configuration (JSON-serialisable)."""
    sc = copy.deepcopy(scenario)
    m = Model(sc)
    net = m.net
    simc = sc.get("sim", {})
    dt = simc.get("dt", 1.0 / 960.0)
    T = simc.get("duration", 3.0)
    w = 2 * np.pi * f0
    nl = Netlist(m.N)
    nodes = [None] * m.N
    for (b, p), i in m.idx.items():
        nodes[i] = {"bus": b, "ph": p, "vbase": float(net["buses"][b]["vbase"])}

    def nid(bus, p):
        i = m.idx.get((bus, p))
        return -1 if i is None else i + 1

    # Diagram layout (does not change the circuit): positions follow the web single-line diagram.
    def xy(bus):
        b = net["buses"][bus]
        return float(b.get("x") or 0.0), float(b.get("y") or 0.0)
    n_shunt = {}

    def shunt(name, bus, kind, info):
        """Group hanging below and to the right of its bus (loads, capacitors, DER, faults)."""
        x, y = xy(bus)
        if name.replace("/", "-") not in [g["name"] for g in nl.groups]:
            n_shunt[bus] = n_shunt.get(bus, 0) + 1
        j = n_shunt.get(bus, 1) - 1
        nl.group(name, left=bus, x=x + 22 + 24 * j, y=y + 24, kind=kind, info=info)
    KIND = {"line": "Line", "reg": "Regulator", "xfmr": "Transformer"}

    # ---------------------------------------------------------------- IED breakers
    ied_of_branch = {}
    for meta in net["ieds"]:
        br = next(b for b in m.br_list if b["from"] == meta["from"] and b["to"] == meta["to"])
        ied_of_branch[br["id"]] = meta["id"]
    ied_ids = [d["id"] for d in net["ieds"]]
    cb_init = sc.get("grid", {}).get("cb_init", {})
    cb_channels = {i: [] for i in ied_ids}

    # ---------------------------------------------------------------- branches
    br_meas = []                       # per branch: 3 measurement channels (0 = phase absent)
    for bi, br in enumerate(m.br_list):
        ph = br["phases"]
        kk = [PH.index(p) for p in ph]
        fi = [nid(br["from"], p) for p in ph]
        ti = [nid(br["to"], p) for p in ph]
        (x1, y1), (x2, y2) = xy(br["from"]), xy(br["to"])
        gname = f"{KIND.get(br['kind'], 'Branch')} {br['from']}-{br['to']}"
        if br["id"] in ied_of_branch:
            gname += f" (CB {ied_of_branch[br['id']]})"
        info = [f"From bus {br['from']} to bus {br['to']}, phases {''.join(ph)}"]
        if br["kind"] == "line":
            info.append(f"IEEE 34 line configuration {br.get('cfg')}, length {br.get('len_ft', 0):,.0f} ft; "
                        "full 3x3 phase impedance matrix (no transposition assumed)")
        elif br["kind"] == "reg":
            info.append("Single-phase regulators, ratio 1 + 0.00625 x tap; taps "
                        + ", ".join(f"{p}: {br['taps'][PH.index(p)]:+d}" for p in ph)
                        + "; series impedance 0.01 + j0.05 ohm")
        else:
            info.append(f"{br['kva']:.0f} kVA, {br['kv1']} / {br['kv2']} kV, R = {br['r_pct']} %, X = {br['x_pct']} %")
        if br["id"] in ied_of_branch:
            info.append(f"Protection point {ied_of_branch[br['id']]}: circuit breaker and current transformers "
                        "(relay logic runs in the Measurements and control block)")
        nl.group(gname, left=br["from"], right=br["to"], x=(x1 + x2) / 2, y=(y1 + y2) / 2,
                 kind=br["kind"] + ("_cb" if br["id"] in ied_of_branch else ""), info=info)
        chans = [0, 0, 0]
        start = []
        for a_, k in enumerate(kk):
            a = fi[a_]
            if br["id"] in ied_of_branch:                     # breaker of the protection point
                iid = ied_of_branch[br["id"]]
                b = nl.node()
                cb_channels[iid].append(nl.breaker(a, b, closed=cb_init.get(iid, True)))
                a = b
            a, ch = nl.imeas(a)
            chans[k] = ch
            start.append(a)
        br_meas.append(chans)
        if br["kind"] == "line":
            Z = branch_Zabc(br)[np.ix_(kk, kk)]
            if len(kk) == 1:
                nl.rl(start[0], ti[0], Z[0, 0])
            else:
                nl.add(type="mutual", a=start, b=ti, R=np.real(Z).tolist(), L=(np.imag(Z) / w).tolist())
        else:
            if br["kind"] == "reg":
                ratios = [1 + 0.00625 * br["taps"][k] for k in kk]
                zs = complex(0.01, 0.05)
            else:
                ratios = [br["kv2"] / br["kv1"]] * len(kk)
                zb = (br["kv2"] ** 2) / (br["kva"] / 1e3)
                zs = complex(br["r_pct"], br["x_pct"]) / 100 * zb
            vb1 = net["buses"][br["from"]]["vbase"]
            for a_, k in enumerate(kk):
                mid = nl.node()
                nl.add(type="xf", a=start[a_], b=mid, v1=float(vb1), ratio=float(ratios[a_]))
                nl.rl(mid, ti[a_], zs)

    # ---------------------------------------------------------------- loads (constant Z)
    load = sc.get("load", {})
    lvl = load.get("level", "puncak_malam")
    scale = LOAD_LEVELS.get(lvl, lvl if isinstance(lvl, (int, float)) else 1.0)
    unb = load.get("phase_scale", [1.0, 1.0, 1.0])
    clpu = load.get("clpu", {}) if load.get("clpu", {}).get("enable") else None
    clpu_loads = []                    # (feeder, node a, node b, admittance) for the CLPU extra current
    for ld in net["loads"]:
        bus = net["buses"][ld["bus"]]
        fd = "B" if bus["feeder"] == "B" else "A"
        vph = bus["vbase"]
        for k in range(3):
            S = complex(ld["P"][k], ld["Q"][k]) * 1e3 * scale * unb[k]
            if abs(S) < 1e-9:
                continue
            if ld["conn"] == "Y":
                a, b = nid(ld["bus"], PH[k]), 0
                y = np.conj(S) / vph ** 2
            else:
                a, b = nid(ld["bus"], PH[k]), nid(ld["bus"], PH[(k + 1) % 3])
                y = np.conj(S) / (3 * vph ** 2)
            if a < 0 or b < 0:
                continue
            shunt(f"Load {ld['bus']}", ld["bus"], "load",
                  [f"{ld['id']} ({ld['conn']}-connected, {ld.get('model', 'PQ')} in IEEE 34): modelled as constant impedance",
                   f"Phase {PH[k]}: P = {S.real / 1e3:.1f} kW, Q = {S.imag / 1e3:.1f} kvar at the scenario load level"])
            nl.rl(a, b, 1.0 / y)
            if clpu and fd in clpu.get("feeders", ["A"]):
                # extra load current during cold load pickup, drawn from a to b by a controlled source
                clpu_loads.append({"fd": fd, "a": a, "b": b, "y": _c(y), "ch": nl.isrc(a, b)})
    # ---------------------------------------------------------------- capacitors
    caps_on = sc.get("grid", {}).get("caps", {"C844": True, "C848": True})
    for c in net["caps"]:
        if not caps_on.get(c["id"], True):
            continue
        vph = net["buses"][c["bus"]]["vbase"]
        shunt(f"Capacitor {c['id']}", c["bus"], "cap",
              [f"Shunt capacitor bank, " + ", ".join(f"{PH[k]}: {c['kvar'][k]:.0f} kvar" for k in range(3))])
        for k, p in enumerate(PH):
            yc = 1j * c["kvar"][k] * 1e3 / vph ** 2
            nl.add(type="cap", a=nid(c["bus"], p), b=0, c=float(yc.imag / w))

    # ---------------------------------------------------------------- substation source
    sub = net["substation"]
    g = sc.get("grid", {})
    island_t0 = g.get("mode", "grid") != "grid" and (g.get("t_island") in (None, 0, 0.0))
    sub_brk, sub_src = [], []
    vph = net["buses"]["800"]["vbase"]
    x800, y800 = xy("800")
    nl.group("Substation source", right="800", x=x800 - 50, y=y800, kind="source",
             info=[f"Grounded Thevenin source behind the substation breaker, E = {sub['v_pu']:.3f} pu",
                   f"Source impedance {m.Zsub.real:.3f} + j{m.Zsub.imag:.3f} ohm per phase (Z0 = Z1)",
                   "Breaker opens to island the feeder when the scenario asks for it"])
    for k, p in enumerate(PH):
        n1, n2 = nl.node(), nl.node()
        sub_src.append(nl.vsrc(n1, 0))
        nl.rl(n1, n2, m.Zsub)
        sub_brk.append(nl.breaker(n2, nid("800", p), closed=not island_t0))
    # Python models the substation as a grounded Thevenin source (Z0 = Z1); identical here.

    # ---------------------------------------------------------------- faults
    faults = []
    for fi_, f in enumerate(sc.get("faults", [])):
        node = f["_node"]
        bphs = net["buses"][node]["phases"]
        k = [PH.index(p) for p in f.get("phases", "a") if p in bphs] or [PH.index(p) for p in bphs]
        rf = max(float(f.get("rf", 0.0)), 1e-3)
        typ = f["type"]
        pairs = []
        if typ == "SLG":
            pairs = [(k[0], None, rf)]
        elif typ == "LL" and len(k) >= 2:
            pairs = [(k[0], k[1], rf)]
        elif typ == "DLG":
            pairs = [(i, None, rf) for i in k[:2]] + ([(k[0], k[1], 1e-3)] if len(k) >= 2 else [])
        elif typ == "3PH":
            pairs = [(PH.index(p), None, rf) for p in bphs]
        brks, meas, mch = [], [0, 0, 0], []
        shunt(f"Fault F{fi_+1} at {node}", node, "fault",
              [f"{typ} fault on phases {f.get('phases', 'a')}, Rf = {rf:.3g} ohm",
               f"Applied at t = {float(f['t_on']):.3f} s" + ("" if f.get("t_off") is None else f", cleared by itself at t = {float(f['t_off']):.3f} s"),
               "Fault breakers with on-resistance Rf; current transformers measure the fault current"])
        for (i, j, r) in pairs:
            a = nid(node, PH[i])
            a2, ch = nl.imeas(a)
            mch.append(ch)
            if j is None:
                meas[i] = ch
            brks.append(nl.breaker(a2, 0 if j is None else nid(node, PH[j]), ron=r, closed=False))
        faults.append({"id": f"F{fi_+1}", "node": node, "type": FAULT_CODE[typ], "t_on": float(f["t_on"]),
                       "t_off": None if f.get("t_off") is None else float(f["t_off"]), "brk": brks, "meas": meas, "mch": mch,
                       "nodes": [nid(node, p) for p in PH]})

    # ---------------------------------------------------------------- DER
    from .sim import Simulator
    dsim = Simulator.__new__(Simulator)
    dsim.sc, dsim.model, dsim.f0 = sc, m, f0
    Simulator._init_ders(dsim)
    ders = []
    for d in dsim.ders:
        c = d.cfg
        n3 = [nid(d.bus, p) for p in PH]
        z1 = complex(getattr(d, "ra", 0.0), getattr(d, "xdpp", 0.0)) * d.Zbase + d.ztx if d.type == "SG" else \
            (d.zv * d.Zbase + d.ztx if d.type == "IBR-GFM" else 0j)
        e = {"id": d.id, "bus": d.bus, "vnodes": n3, "type": DER_CODE[d.type], "S": float(d.S), "vbase": float(d.vbase),
             "Zbase": float(d.Zbase), "Ibase": float(d.Ibase), "ztx": _c(d.ztx), "z1": _c(z1), "yg": int(d.ground == "YgD"),
             "p_set": float(d.p_set), "q_set": float(d.q_set), "pv": int(d.type.startswith("IBR") and c.get("source", "PV") == "PV"),
             "irr": np.array(sorted(d.irr) if d.irr else [[0.0, 1000.0]], float).tolist(),
             "imax": float(getattr(d, "imax", 1.2)), "frt_q": int(getattr(d, "frt", "Q") == "Q"), "kq": float(getattr(d, "kq", 2.0)),
             "neg_seq": int(bool(getattr(d, "neg_seq", False))), "k2": float(getattr(d, "k2", 2.0)),
             "mc": int(bool(getattr(d, "mc", False))), "mc_v": float(getattr(d, "mc_v", 0.5)), "tau": float(getattr(d, "tau", 1 / 60)),
             "ra": float(getattr(d, "ra", 0.01)), "xdpp": float(getattr(d, "xdpp", 0.15)), "xdp": float(getattr(d, "xdp", 0.25)),
             "xd": float(getattr(d, "xd", 1.0)), "tdpp": float(getattr(d, "tdpp", 0.03)), "tdp": float(getattr(d, "tdp", 0.6)),
             "H": float(getattr(d, "H", 1.0)), "uv1": list(d.rt["uv1"]), "uv2": list(d.rt["uv2"]),
             "t_anti_island": float(d.t_anti_island), "trip_at": -1.0 if d.trip_at is None else float(d.trip_at),
             "online": int(bool(d.online)), "feeder": "B" if net["buses"][d.bus]["feeder"] == "B" else "A"}
        # connection: DER breaker -> current measurement -> sources
        shunt(f"DER {d.id} ({d.type}) at {d.bus}", d.bus, {"SG": "der_sg", "IBR-GFL": "der_gfl", "IBR-GFM": "der_gfm"}[d.type],
              [f"{d.type}, S = {d.S / 1e3:.0f} kVA, P setpoint {d.p_set:.2f} pu, Q setpoint {d.q_set:.2f} pu",
               f"Interconnection transformer {d.ground}" + (" (zero-sequence source)" if d.ground == "YgD" else ""),
               {"SG": "Voltage E'' behind X''(t) decaying to X' and Xd (IEC 60909)",
                "IBR-GFL": f"Current source with PLL and 1-cycle lag, current limit {getattr(d, 'imax', 1.2):.2f} pu (IEEE 2800)",
                "IBR-GFM": f"Voltage source behind virtual impedance, current limit {getattr(d, 'imax', 1.3):.2f} pu"}[d.type],
               "Breaker and current transformers at the point of connection; control runs in the Measurements and control block"])
        conn, meas, brk = [], [], []
        for k in range(3):
            n_b = nl.node()
            brk.append(nl.breaker(n3[k], n_b, closed=bool(d.online)))
            n_m, ch = nl.imeas(n_b)
            meas.append(ch)
            conn.append(n_m)
        e["brk"], e["meas"] = brk, meas
        if d.type == "IBR-GFL":
            e["isrc"] = [nl.isrc(conn[k], 0) for k in range(3)]
        else:
            neutral = nl.node()
            nl.rl(neutral, 0, 1e6)                           # floating neutral: no zero-sequence path
            e["vsrc"] = []
            for k in range(3):
                n_s = nl.node()
                e["vsrc"].append(nl.vsrc(n_s, neutral))
                nl.rl(n_s, conn[k], z1)
        if d.ground == "YgD":                                 # zero-sequence path of the Yg-Delta transformer
            z0, zbig = complex(d.ztx), complex(d.ztx) * 1e4
            Zs = np.array([[z0 + 2 * zbig, z0 - zbig, z0 - zbig], [z0 - zbig, z0 + 2 * zbig, z0 - zbig],
                           [z0 - zbig, z0 - zbig, z0 + 2 * zbig]]) / 3
            nl.add(type="mutual", a=conn, b=[0, 0, 0], R=np.real(Zs).tolist(), L=(np.imag(Zs) / w).tolist())
        ders.append(e)

    # ---------------------------------------------------------------- IEDs
    cls_map = sc.get("relays", {}).get("classes", {})
    default = sc.get("relays", {}).get("default", "OCR")
    ieds = []
    for meta in net["ieds"]:
        br = next(b for b in m.br_list if b["from"] == meta["from"] and b["to"] == meta["to"])
        bi = m.br_index[br["id"]]
        s = settings[meta["id"]]
        cls = cls_map.get(meta["id"], default)
        if cls == "DIFF" and not meta.get("partner"):
            cls = "DIST"
        ieds.append({
            "id": meta["id"], "cls": CLS_CODE[cls], "branch": bi + 1, "meas": br_meas[bi],
            "vnodes": [nid(meta["from"], p) for p in PH], "cb": cb_channels[meta["id"]],
            "partner": (ied_ids.index(meta["partner"]) + 1) if meta.get("partner") else 0,
            "cb_init": int(bool(cb_init.get(meta["id"], True))),
            "s": {"vbase": float(s["vbase"]), "curve": CURVE_CODE[s["curve"]], "p51": float(s["51P_pu"]),
                  "n51": float(s.get("51N_pu") or 0), "tp": float(s["51P_tms"]), "tn": float(s["51N_tms"]),
                  "p50": float(s.get("50P_pu") or 0), "n50": float(s.get("50N_pu") or 0), "mta": float(s["mta"]),
                  "zthr": float(s["zthr"]), "i2min": float(s["i2min"]), "k0": _c(s["k0"]), "ang1": float(s["ang1"]),
                  "ang0": float(s["ang0"]), "fd_ph": float(s["fd_ph"]), "fd_g": float(s["fd_g"]),
                  "zreach": [float(z) for z in s["zreach"]], "ztime": [float(z) for z in s["ztime"]],
                  "d87": float(s.get("87_pu") or 0), "slope87": float(s["87_slope"]), "t87": float(s["87_delay"]),
                  "ph": [int(k in s["ph_idx"]) for k in range(3)]},
        })
    # bus-level topology for island / energisation logic
    buses = list(m.bus_list)
    topo = [{"f": buses.index(br["from"]) + 1, "t": buses.index(br["to"]) + 1,
             "ied": (ied_ids.index(ied_of_branch[br["id"]]) + 1) if br["id"] in ied_of_branch else 0} for br in m.br_list]
    bus_nodes = [[nid(b, p) for p in PH] for b in buses]
    der_bus = [buses.index(d["bus"]) + 1 for d in ders]
    fault_bus = [buses.index(f["node"]) + 1 for f in faults]

    cfg = {
        "structure_key": "",
        "dt": float(dt), "T": float(T), "f0": float(f0), "t_init": T_INIT, "t_cb": float(simc.get("t_cb", 0.05)),
        "N": m.N, "n_nodes": nl.n, "nodes": nodes, "elements": nl.el,
        "n_brk": nl.n_ctrl_brk, "n_v": nl.n_ctrl_v, "n_i": nl.n_ctrl_i, "n_meas": nl.n_imeas,
        "br_meas": br_meas, "sub": {"src": sub_src, "brk": sub_brk, "E": _c(sub["v_pu"] * vph), "bus": buses.index("800") + 1,
                                     "t_island": -1.0 if g.get("t_island") is None or g.get("mode", "grid") == "grid" else float(g["t_island"]),
                                     "closed0": int(not island_t0)},
        "faults": faults, "ders": ders, "ieds": ieds, "topo": topo, "bus_nodes": bus_nodes, "n_bus": len(buses),
        "bus_ids": [str(b) for b in buses], "bus_xy": [list(xy(b)) for b in buses], "groups": nl.groups,
        "der_bus": der_bus, "fault_bus": fault_bus, "mode_grid": int(g.get("mode", "grid") == "grid"),
        "events": [{"t": float(e["t"]), "type": 1 if e["type"] == "CB_CLOSE" else 0, "ied": ied_ids.index(e["id"]) + 1}
                   for e in sorted(sc.get("events", []), key=lambda e: e["t"]) if e.get("type") in ("CB_OPEN", "CB_CLOSE")],
        "clpu": None if not clpu else {"factor": float(clpu.get("factor", 2.5)), "tau": float(clpu.get("tau", 2.0)),
                                      "t0": float(clpu.get("t_energize", 0.5)), "loads": clpu_loads},
    }
    # Model structure (which blocks exist and their values) for reusing an already built model.
    import hashlib
    def shape(e):
        """Element without its values: what decides which blocks exist and how they connect."""
        k = {x: e[x] for x in ("type", "a", "b", "ch", "g") if x in e}
        if e["type"] == "rl":
            k["bt"] = "R" if e["x"] == 0 else ("L" if e["x"] > 0 else "C") + ("R" if e["r"] > 0 else "")
        return k
    cfg["structure_key"] = hashlib.sha1(json.dumps({"el": [shape(e) for e in nl.el], "N": m.N, "T": T},
                                                   sort_keys=True).encode()).hexdigest()[:16]
    return cfg, m


# ====================================================================== results adapter
ELEM_NAME = {1: "51P", 2: "50P (inst)", 3: "51N", 4: "50N (inst)", 5: "67P", 6: "67P (inst)", 7: "67N",
             8: "67N (inst)", 9: "21-Z1", 10: "21-Z2", 11: "21-Z3", 12: "87L"}
DER_REASON = {1: "Manual trip or internal DER fault (scenario)", 2: "Undervoltage protection UV2",
              3: "Undervoltage protection UV1", 4: "Anti-islanding (unintentional island)"}


def _rows(x):
    a = np.asarray(x)
    return a.reshape(len(a), -1) if a.ndim == 1 else a


def load_results(sim_cls, scenario, settings, cfg, mat, progress=None):
    """Wrap MATLAB outputs into an object compatible with engine.sim.Simulator.

    Relay event logs (pickup, direction, trip) are rebuilt by replaying the app's IED logic on the
    exact phasors measured in the Simscape model. Trip instants are taken from the MATLAB run; any
    disagreement with the replay is counted in ``sim.replay_mismatch``.
    """
    sim = sim_cls(copy.deepcopy(scenario), settings)
    m = sim.model
    dt = sim.dt
    off = int(round(cfg["t_init"] / dt))
    nsteps = int(round(sim.T / dt)) + 1
    pk = np.sqrt(2)
    V = _rows(mat["simV"])[off:off + nsteps] / pk
    Im = _rows(mat["simI"])[off:off + nsteps] / pk
    nsteps = len(V)
    log = mat["log"]
    nl = int(log.n)
    lt = np.atleast_1d(log.t)[:nl]
    r0 = int(np.argmin(np.abs(lt - 0.0)))               # controller row of t = 0
    nI, nD = len(sim.ieds), len(sim.ders)
    faults = sim.sc.get("faults", [])
    nF = len(faults)

    def L(name, cols):
        a = np.asarray(getattr(log, name), float)
        return a.reshape(len(a), -1)[:nl, :max(cols, 1)]
    lcb, ltrip, ldtt = L("cb", nI), L("trip", nI), L("dtt", nI)
    lsub, lfreq = L("sub", 1)[:, 0], L("freq", 1)[:, 0]
    lman, lisl = L("manual", 1)[:, 0], L("island", 1)[:, 0]
    lder, lirr, lreason = L("der_on", nD), L("irr", nD), L("der_reason", nD)
    lf, lfc = L("fault", nF), L("fclear", nF)

    def prev(arr, k, init):                # state applied at step k = controller output of row k-1
        r = r0 + k - 1
        return init if r < 0 else arr[r]

    sim.t = np.arange(nsteps) * dt
    sim.V = V.astype(np.complex64)
    nb = len(m.br_list)
    Ib = np.zeros((nsteps, nb * 3), np.complex64)
    for bi, chans in enumerate(cfg["br_meas"]):
        for k, ch in enumerate(chans):
            if ch:
                Ib[:, bi * 3 + k] = Im[:, ch - 1]
    sim.Ib = Ib
    cb0 = np.array([d["cb_init"] for d in cfg["ieds"]])
    sim.cb_t = np.array([prev(lcb, k, cb0) for k in range(nsteps)]) > 0.5
    sim.sub_t = np.array([prev(lsub, k, cfg["sub"]["closed0"]) for k in range(nsteps)]) > 0.5
    sim.freq_t = lfreq[r0:r0 + nsteps].astype(np.float32)
    # ---- DER
    sim.Ider = np.zeros((nsteps, nD, 3), np.complex64)
    sim.Pder = np.zeros((nsteps, nD, 2), np.float32)
    sim.der_on = np.zeros((nsteps, nD), bool)
    sim.irr_t = np.full((nsteps, nD), np.nan, np.float32)
    for j, (d, e) in enumerate(zip(sim.ders, cfg["ders"])):
        Iout = -np.stack([Im[:, ch - 1] for ch in e["meas"]], axis=1)
        Vd = np.stack([V[:, n - 1] for n in e["vnodes"]], axis=1)
        sim.Ider[:, j] = Iout
        S = np.sum(Vd * np.conj(Iout), axis=1)
        sim.Pder[:, j, 0] = S.real / 1e3
        sim.Pder[:, j, 1] = S.imag / 1e3
        sim.der_on[:, j] = lder[r0:r0 + nsteps, j] > 0.5
        if d.type.startswith("IBR"):
            sim.irr_t[:, j] = lirr[r0:r0 + nsteps, j]
        d.online = bool(sim.der_on[-1, j])
    # ---- faults
    sim.Ifault = np.zeros((nsteps, max(nF, 1), 3), np.complex64)
    for i, f in enumerate(faults):
        Yf, idx = m.fault_Y(f, f["_node"])
        on = np.array([prev(lf, k, np.zeros(max(nF, 1)))[i] for k in range(nsteps)]) > 0.5
        vf = np.stack([V[:, j] if j >= 0 else np.zeros(nsteps) for j in idx], axis=1)
        sim.Ifault[on, i] = vf[on] @ Yf.T
    sim.tau_dc = []
    for f in faults:
        try:
            sim.tau_dc.append(sim._tau_at(f["_node"], []))
        except Exception:
            sim.tau_dc.append(0.01)
    # ---- simulator events (same texts as the Python engine)
    ev = []
    ied_ids = [d.id for d in sim.ieds]
    clpu = sim.sc.get("load", {}).get("clpu", {}).get("enable")
    for r in range(max(r0 - 1, 0), min(r0 + nsteps, nl)):
        t_next = round(float(lt[r]) + dt, 6)
        if t_next < -1e-9 or t_next > sim.T + 1e-9:
            continue
        man = int(lman[r])
        if man:
            j, close = abs(man) - 1, man > 0
            ev.append({"t": t_next, "src": "SIM", "type": "CB_CLOSE" if close else "CB_OPEN", "id": ied_ids[j],
                       "text": f"Manual operation: {ied_ids[j]} {'CLOSE' if close else 'OPEN'}"
                               + (" (energization, cold load pickup)" if clpu and close else "")})
        if lisl[r]:
            ev.append({"t": t_next, "src": "SIM", "type": "ISLAND", "id": "SUB",
                       "text": "Substation 69 kV breaker opened; islanded microgrid mode"})
        for j in range(nI):
            was = lcb[r - 1, j] if r > 0 else cb0[j]
            if was > 0.5 and lcb[r, j] < 0.5 and not (man and abs(man) - 1 == j):
                ev.append({"t": t_next, "src": "SIM", "type": "CB_OPEN", "id": ied_ids[j],
                           "text": f"{ied_ids[j]} contacts separated, current interrupted"})
                sim.ieds[j].events.append({"t": round(t_next, 4), "src": "IED", "id": ied_ids[j], "type": "52B",
                                           "kind": "cb", "text": f"{ied_ids[j]} 52b: CB OPEN"})
        for i, f in enumerate(faults):
            was = lf[r - 1, i] if r > 0 else 0
            if lf[r, i] > 0.5 and was < 0.5:
                ev.append({"t": t_next, "src": "SIM", "type": "FAULT_ON", "id": f"F{i+1}",
                           "text": sim._fault_text(f), "node": f["_node"]})
            if lfc[r, i] > 0.5:
                ev.append({"t": round(float(lt[r]), 6), "src": "SIM", "type": "FAULT_CLEARED", "id": f"F{i+1}",
                           "text": f"Fault F{i+1} isolated and extinguished (no remaining source)"})
            elif lf[r, i] < 0.5 and was > 0.5:
                ev.append({"t": t_next, "src": "SIM", "type": "FAULT_OFF", "id": f"F{i+1}",
                           "text": f"Fault F{i+1} self-extinguished (transient)"})
        for j, d in enumerate(sim.ders):
            if r > 0 and lreason[r, j] and not lreason[r - 1, j]:
                why = DER_REASON.get(int(lreason[r, j]), "protection")
                ev.append({"t": round(float(lt[r]), 6), "src": "DER", "id": d.id, "type": "DER_TRIP",
                           "text": f"{d.id} at bus {d.bus} TRIP: {why}"})
    sim.events_sim = sorted(ev, key=lambda e: e["t"])
    # ---- relay replay on the measured phasors
    trip_row = {}
    for j in range(nI):
        rows = np.where(ltrip[r0:r0 + nsteps, j] > 0)[0]
        if len(rows):
            trip_row[j] = (int(rows[0]), int(ltrip[r0 + rows[0], j]))
    sim.relay_dir = {d.id: [] for d in sim.ieds}
    sim.relay_Z = {d.id: [] for d in sim.ieds}
    sim.relay_prog = np.zeros((nsteps, nI, 2), np.float32)
    sim.relay_Imeas = np.zeros((nsteps, nI, 3), np.complex64)
    sim.relay_Vmeas = np.zeros((nsteps, nI, 3), np.complex64)
    sim.replay_mismatch = 0
    for k in range(nsteps):
        t = k * dt
        if progress and k % 64 == 0:
            progress("Rebuilding the relay event log from the Simulink phasors", 100.0 * k / nsteps)
        for j, ied in enumerate(sim.ieds):
            Iraw = Ib[k, ied.br_i * 3: ied.br_i * 3 + 3]
            Vraw = np.array([V[k, x] if x >= 0 else 0 for x in ied.v_idx])
            remote = None
            if ied.cls == "DIFF":
                p = sim.ied_by_id[ied.meta["partner"]]
                remote = Ib[k, p.br_i * 3: p.br_i * 3 + 3]
            was = ied.tripped
            ied.step(t, Iraw, Vraw, remote)
            want = trip_row.get(j)
            if ied.tripped and not was and (want is None or want[0] != k):
                if ied.events and ied.events[-1]["type"] == "TRIP":        # replay tripped, MATLAB did not
                    ied.events.pop()
                ied.tripped, ied.trip_time, ied.trip_elem = False, None, None
                sim.replay_mismatch += 1
            if want is not None and want[0] == k and not ied.tripped:        # MATLAB tripped at this step
                ied._trip(t, ELEM_NAME.get(want[1], "TRIP"))
                sim.replay_mismatch += 1
            sim.relay_Imeas[k, j] = ied.last["I"]
            sim.relay_Vmeas[k, j] = ied.last["V"]
            sim.relay_prog[k, j] = [max(ied.prog["51P"]), ied.prog["51N"]]
            if ied.cls == "DIST" and "Z" in ied.last:
                sim.relay_Z[ied.id].append((k, ied.last["Z"], ied.last.get("zone")))
            if ied.cls == "DOCR" and ied.dir_state:
                sim.relay_dir[ied.id].append((k, ied.dir_state.get("P"), ied.dir_state.get("N"), ied.dir_state.get("Nmeth")))
        if r0 + k < nl:
            for j in range(nI):                                               # direct transfer trip (87L)
                src = int(ldtt[r0 + k, j])
                if src:
                    sim.ieds[j].events.append({"t": round(t, 4), "src": "IED", "id": ied_ids[j], "type": "DTT", "kind": "trip",
                                               "text": f"{ied_ids[j]} received Direct Transfer Trip from {ied_ids[src - 1]} (87L)"})
    sim.wall = float(np.asarray(mat.get("wall", 0.0)))
    sim.engine = "matlab"
    return sim


class MatlabSession:
    """One MATLAB engine kept open for the life of the process (MATLAB start-up takes ~10 s)."""

    def __init__(self):
        self.eng = None
        self.lock = threading.Lock()
        self.tmp = os.path.join(ROOT, "cache", "matlab_io")

    def start(self):
        if self.eng is None:
            import matlab.engine
            os.makedirs(self.tmp, exist_ok=True)
            self.eng = matlab.engine.start_matlab("-nodesktop -nosplash")
            self.eng.addpath(MATLAB_DIR, nargout=0)
            self.eng.sr34_worker_init(MATLAB_DIR, nargout=0)      # private Simulink cache folder
        return self.eng

    def run(self, scenario, settings, progress=None):
        """Simulate one scenario in Simulink. progress(stage, percent or None) reports each stage."""
        from .sim import Simulator
        import scipy.io
        say = progress or (lambda *a: None)
        say("Exporting the network, relay logic and events to MATLAB", None)
        cfg, _ = export_config(scenario, settings)
        with self.lock:
            if self.eng is None:
                say("Starting MATLAB (first simulation only, about 10 to 30 s)", None)
            eng = self.start()
            tag = f"{os.getpid()}"
            cf, of = os.path.join(self.tmp, f"cfg_{tag}.json"), os.path.join(self.tmp, f"out_{tag}.mat")
            pf = os.path.join(self.tmp, f"progress_{tag}.txt")
            cfg["progress_file"] = pf
            if os.path.exists(pf):
                os.remove(pf)
            with open(cf, "w") as f:
                json.dump(cfg, f)
            job = eng.sr34_run(cf, of, nargout=0, background=True)
            while not job.done():
                time.sleep(0.4)
                try:
                    stage, k, n = open(pf).read().split()
                    k, n = float(k), max(float(n), 1e-9)
                    if stage == "build":
                        say("Building the Simscape Electrical model in Simulink" if k > 0 else
                            "Preparing the Simulink model", 100.0 * k / n if k > 0 else None)
                    else:
                        say(f"Simulating in Simulink (phasor mode), t = {k - cfg['t_init']:.2f} of {cfg['T']:.2f} s", 100.0 * k / n)
                except Exception:
                    pass
            job.result()
            say("Reading the Simulink results", None)
            mat = scipy.io.loadmat(of, squeeze_me=True, struct_as_record=False)
        return load_results(Simulator, scenario, settings, cfg, mat, progress=say)


SESSION = MatlabSession()
