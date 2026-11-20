"""
Setting relai konvensional — dihitung SEKALI pada kondisi baseline
(0% DER, beban puncak malam, grid-connected, kapasitor ON, tap default)
lalu DIBEKUKAN untuk semua skenario. Inilah inti 'relai konvensional':
setting tidak tahu adanya DER.

Aturan desain (praktik umum IEEE C37.230 / IEC 60255):
  51P pickup = 1.5 x arus beban maksimum yang lewat titik relai
  51N pickup = maks(2 x 3I0 akibat ketidakseimbangan beban, 0.3 x 51P, 6 A)
  TMS        : koordinasi dari hilir ke hulu, CTI desain 0.3 s pada arus
               gangguan maksimum (3PH untuk fasa, SLG untuk tanah) di lokasi relai hilir
  50P/50N    : hanya pada relai yang memiliki relai hilir; 1.25 x arus maksimum
               untuk gangguan di lokasi relai hilir (tidak overreach)
  21         : Z1 = 80%, Z2 = 120% (0.3 s), Z3 = cakupan seksi berikut (0.8 s)
  87L        : pickup = maks(1.5 x Idiff beban-tap baseline, 0.2 x 51P, 5 A), slope 30%
"""
from __future__ import annotations
import copy
import numpy as np

from .network import base_network, path_from_source, branch_Zabc, seq_from_abc, LINE_CONFIGS, FT_PER_MILE
from .relays import t_op, CURVES

CTI_DESIGN = 0.30
CURVE = "IEC_SI"

BASELINE = {
    "der": {"units": []},
    "load": {"level": "puncak_malam"},
    "grid": {"mode": "grid"},
    "faults": [],
    "relays": {"default": "OCR"},
    "sim": {"duration": 0.1},
}


def _zline(net, frm, to):
    """Impedansi urutan positif & nol (ohm) saluran dari bus 'frm' ke 'to' (to di hilir frm)."""
    pb, pbr = path_from_source(net, to)
    if frm not in pb:
        return 0j, 0j, None
    i0 = pb.index(frm)
    brs = pbr[i0:]
    Z1 = 0j; Z0 = 0j; Zs = 0j
    for bid in brs:
        br = next(b for b in net["branches"] if b["id"] == bid)
        if br["kind"] != "line":
            continue
        Z = branch_Zabc(br)
        if br["phases"] == "abc":
            S = seq_from_abc(Z)
            Z1 += S[1, 1]; Z0 += S[0, 0]
        else:
            k = "abc".index(br["phases"])
            Zs += Z[k, k]
            Z1 += Z[k, k]; Z0 += Z[k, k]
    return Z1, Z0, brs


def downstream_buses(net, frm, to):
    """Semua bus di hilir cabang frm->to."""
    adj = {b: [] for b in net["buses"]}
    for br in net["branches"]:
        adj[br["from"]].append(br["to"]); adj[br["to"]].append(br["from"])
    seen = {frm, to}; st = [to]
    while st:
        u = st.pop()
        for v in adj[u]:
            if v not in seen:
                seen.add(v); st.append(v)
    seen.discard(frm)
    return seen


def compute_settings(verbose=False):
    from .sim import Simulator
    net = base_network()
    ieds = {d["id"]: d for d in net["ieds"]}

    def run_static(faults):
        sc = copy.deepcopy(BASELINE)
        sc["faults"] = faults
        dummy = {k: _dummy_setting() for k in ieds}
        sim = Simulator(sc, dummy)
        V = sim.initialize()
        if faults:
            for f in sc["faults"]:
                f.setdefault("t_on", 0.0)
            V = sim.solve(0.0, list(range(len(faults))))
        Ib = sim.model.M_from @ V
        out = {}
        for ied in sim.ieds:
            out[ied.id] = Ib[ied.br_i * 3: ied.br_i * 3 + 3]
        return out, sim, V

    # --- beban baseline
    I_load, sim0, V0 = run_static([])
    S = {}
    for iid, meta in ieds.items():
        I = I_load[iid]
        ph = [k for k, p in enumerate("abc") if (meta["to"], p) in sim0.model.idx]
        ilmax = float(np.max(np.abs(I[ph])))
        i0 = float(abs(np.sum(I)))
        vb = net["buses"][meta["from"]]["vbase"]
        S[iid] = {
            "vbase": vb, "ph_idx": ph, "curve": CURVE,
            "I_load_max": ilmax, "I0_unbal": i0,
            "51P_pu": max(round(1.5 * ilmax + 0.5), 10.0),
            "51N_pu": max(round(2.0 * i0 + 0.5), round(0.5 * 1.5 * ilmax), 6.0),
            "51P_tms": 0.05, "51N_tms": 0.05, "50P_pu": None, "50N_pu": None,
            "mta": 45.0, "zthr": 0.5, "i2min": 1.0,
        }
    # --- koordinasi: periksa semua bus di zona primary relai hilir (3PH & SLG)
    def fault_currents(bus, typ, ph="a"):
        out, _, _ = run_static([{"bus": bus, "type": typ, "phases": ph, "rf": 0.0, "t_on": 0.0}])
        return out

    def zone_buses(d):
        meta = ieds[d]
        zb = downstream_buses(net, meta["from"], meta["to"])
        # buang bus di hilir IED lain (zona relai berikutnya)
        for o, om in ieds.items():
            if o != d and om["from"] in zb:
                zb -= downstream_buses(net, om["from"], om["to"])
        return sorted(zb)

    pairs = [("A2", "A3"), ("A1", "A2"), ("A1", "L1")]
    order = ["A3", "L1", "B1", "A2", "A1"]
    S["B1"]["51P_tms"] = 0.10
    S["B1"]["51N_tms"] = 0.10
    cache = {}
    coord_log = []
    for up in order:
        for (u, d) in pairs:
            if u != up:
                continue
            buses = zone_buses(d)
            # 50 elemen hulu: tidak boleh overreach melewati lokasi relai hilir
            loc = ieds[d]["to"]
            for elem in ("P", "N"):
                three = net["buses"][loc]["phases"] == "abc"
                typ = ("3PH" if three else "SLG") if elem == "P" else "SLG"
                key = (loc, typ)
                if key not in cache:
                    cache[key] = fault_currents(loc, typ, "abc" if typ == "3PH" else net["buses"][loc]["phases"][0])
                fc = cache[key]
                Iu = float(np.max(np.abs(fc[u]))) if elem == "P" else float(abs(np.sum(fc[u])))
                S[u][f"50{elem}_pu"] = float(np.ceil(1.25 * Iu))
            for b in buses:
                three = net["buses"][b]["phases"] == "abc"
                for elem, typ in (("P", "3PH" if three else "SLG"), ("P", "SLG"), ("N", "SLG")):
                    if elem == "N" and not S[d].get("51N_pu"):
                        continue
                    ph = "abc" if typ == "3PH" else net["buses"][b]["phases"][0]
                    key = (b, typ)
                    if key not in cache:
                        cache[key] = fault_currents(b, typ, ph)
                    fc = cache[key]
                    if elem == "P":
                        Iu = float(np.max(np.abs(fc[u]))); Id = float(np.max(np.abs(fc[d])))
                    else:
                        Iu = float(abs(np.sum(fc[u]))); Id = float(abs(np.sum(fc[d])))
                    pu_u, pu_d = S[u][f"51{elem}_pu"], S[d][f"51{elem}_pu"]
                    if Id <= pu_d or Iu <= pu_u:
                        continue
                    inst_d = S[d].get(f"50{elem}_pu")
                    td = 0.02 if (inst_d and Id > inst_d) else t_op(CURVE, S[d][f"51{elem}_tms"], Id / pu_d)
                    need = td + CTI_DESIGN
                    tms_u = need / t_op(CURVE, 1.0, Iu / pu_u)
                    tms_u = float(np.ceil(max(tms_u, 0.05) * 100) / 100)
                    k = f"51{elem}_tms"
                    if tms_u > S[u][k]:
                        S[u][k] = tms_u
                    coord_log.append({"up": u, "down": d, "bus": b, "elem": elem, "fault": typ,
                                      "I_up": Iu, "I_down": Id, "t_down": td, "tms_req": tms_u})
    # --- distance & 87L
    for iid, meta in ieds.items():
        s = S[iid]
        frm = meta["from"]
        partner = meta.get("partner")
        if partner:
            Z1, Z0, _ = _zline(net, frm, ieds[partner]["from"])
        else:
            far = None; best = 0
            for b in downstream_buses(net, frm, meta["to"]):
                if net["buses"][b]["kv"] < 20:
                    continue
                z, _, _ = _zline(net, frm, b)
                if abs(z) > best:
                    best, far = abs(z), b
            Z1, Z0, _ = _zline(net, frm, far)
            s["dist_far_bus"] = far
        single = len(s["ph_idx"]) == 1
        if single:
            k0 = 0j
        else:
            k0 = (Z0 - Z1) / (3 * Z1)
        s["k0"] = complex(k0)
        s["ang1"] = float(np.angle(Z1))
        s["ang0"] = float(np.angle(Z0)) if abs(Z0) > 0 else float(np.angle(Z1))
        z3 = 2.0 * abs(Z1)
        if iid == "A1":
            z3n, _, _ = _zline(net, frm, ieds["A3"]["from"])
            z3 = 1.2 * abs(z3n)
        elif iid == "A2":
            far = None; best = 0
            for b in downstream_buses(net, ieds["A3"]["from"], ieds["A3"]["to"]):
                z, _, _ = _zline(net, frm, b)
                if abs(z) > best and net["buses"][b]["kv"] > 20:
                    best = abs(z)
            z3 = 1.2 * best
        s["zline"] = [float(Z1.real), float(Z1.imag)]
        s["zreach"] = [0.8 * abs(Z1), 1.2 * abs(Z1), max(z3, 1.25 * 1.2 * abs(Z1))]
        s["ztime"] = [0.0, 0.3, 0.8]
        s["fd_ph"] = 0.5 * s["51P_pu"]
        s["fd_g"] = 0.5 * s["51N_pu"]
        # 87L
        if partner:
            Id = np.abs(I_load[iid] - I_load[partner])
            s["87_pu"] = float(max(np.ceil(1.5 * np.max(Id)), 0.2 * s["51P_pu"], 5.0))
            s["Idiff_base"] = float(np.max(Id))
        else:
            s["87_pu"] = None
        s["87_slope"] = 0.3
        s["87_delay"] = 0.01
    # IED 1-fasa: elemen tanah tidak dipakai (3I0 = arus fasa)
    for s in S.values():
        if len(s["ph_idx"]) == 1:
            s["51N_pu"] = None; s["50N_pu"] = None
    # bulatkan
    for s in S.values():
        for k in ("51P_pu", "51N_pu"):
            if s[k] is not None:
                s[k] = float(s[k])
    return S, coord_log


def _dummy_setting():
    return {"vbase": 14376.0, "ph_idx": [0, 1, 2], "curve": CURVE, "51P_pu": 1e9, "51N_pu": 1e9,
            "51P_tms": 1, "51N_tms": 1, "50P_pu": None, "50N_pu": None, "mta": 45.0, "zthr": 0.5,
            "i2min": 1.0, "k0": 0j, "ang1": 0.6, "ang0": 0.6, "zreach": [0, 0, 0], "ztime": [0, 0, 0],
            "fd_ph": 1e9, "fd_g": 1e9, "87_pu": 1e9, "87_slope": 0.3, "87_delay": 0.01}


def settings_public(S):
    """Versi ramah-JSON."""
    out = {}
    for k, s in S.items():
        d = {}
        for kk, v in s.items():
            if isinstance(v, complex):
                d[kk] = [v.real, v.imag]
            elif isinstance(v, (np.floating,)):
                d[kk] = float(v)
            else:
                d[kk] = v
        out[k] = d
    return out
