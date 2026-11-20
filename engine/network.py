"""
IEEE 34 Node Test Feeder (Penyulang A) + Penyulang B ekuivalen.

Sumber data: IEEE PES Distribution Test Feeders, "34-node Test Feeder"
(konfigurasi saluran 300-304, panjang dalam feet, beban spot & terdistribusi,
kapasitor 844/848, regulator 814-850 & 852-832, trafo GI 69/24.9 kV 2.5 MVA,
XFM-1 24.9/4.16 kV 500 kVA).

Penyederhanaan yang disengaja (didokumentasikan di README):
  * Kapasitansi shunt saluran diabaikan (orde < 0.1 A di 24.9 kV).
  * Beban terdistribusi dibagi 50/50 ke kedua ujung segmen.
  * Semua beban dimodelkan impedansi konstan (dihitung dari tegangan nominal),
    standar untuk studi hubung-singkat fasor.
  * Regulator = trafo ideal per-fasa (wye) dengan tap tetap per skenario.
  * Penyulang B = penyulang ekuivalen sederhana (bukan bagian IEEE 34) untuk
    menguji F-2 (sympathetic trip) di busbar 800 yang sama.
"""
from __future__ import annotations
import copy
import numpy as np

FT_PER_MILE = 5280.0
F_NOM = 60.0                      # IEEE test feeder: 60 Hz
KV_LL_MV = 24.9
KV_LL_LV = 4.16

# ---------------------------------------------------------------- impedansi
# Matriks impedansi seri (ohm/mile), fasa a,b,c
def _sym(z11, z12, z13, z22, z23, z33):
    return np.array([[z11, z12, z13], [z12, z22, z23], [z13, z23, z33]], dtype=complex)

LINE_CONFIGS = {
    "300": {"phases": "abc", "cond": "1/0 ACSR",
            "Z": _sym(1.3368 + 1.3343j, 0.2101 + 0.5779j, 0.2130 + 0.5015j,
                      1.3238 + 1.3569j, 0.2066 + 0.4591j, 1.3294 + 1.3471j)},
    "301": {"phases": "abc", "cond": "#2 6/1 ACSR",
            "Z": _sym(1.9300 + 1.4115j, 0.2327 + 0.6442j, 0.2359 + 0.5691j,
                      1.9157 + 1.4281j, 0.2288 + 0.5238j, 1.9219 + 1.4209j)},
    "302": {"phases": "a", "cond": "#4 6/1 ACSR", "Zs": 2.7995 + 1.4855j},
    "303": {"phases": "b", "cond": "#4 6/1 ACSR", "Zs": 2.7995 + 1.4855j},
    "304": {"phases": "b", "cond": "#2 6/1 ACSR", "Zs": 1.9217 + 1.4212j},
}

PH = "abc"

def config_Z(cfg: str, phases: str):
    """Matriks 3x3 ohm/mile (nol untuk fasa yang tidak ada)."""
    c = LINE_CONFIGS[cfg]
    Z = np.zeros((3, 3), dtype=complex)
    if "Z" in c:
        Z[:, :] = c["Z"]
    else:
        k = PH.index(c["phases"])
        Z[k, k] = c["Zs"]
    return Z

# ---------------------------------------------------------------- data bus
# (name, kV LL, phases, x, y, feeder)  -- SLD coordinates (viewBox 2360 x 880)
_Y0 = 330
BUSES = [
    ("800", KV_LL_MV, "abc", 130, _Y0, "SUB"),
    ("802", KV_LL_MV, "abc", 240, _Y0, "A"),
    ("806", KV_LL_MV, "abc", 340, _Y0, "A"),
    ("808", KV_LL_MV, "abc", 450, _Y0, "A"),
    ("810", KV_LL_MV, "b",   450, _Y0 + 130, "A"),
    ("812", KV_LL_MV, "abc", 570, _Y0, "A"),
    ("814", KV_LL_MV, "abc", 690, _Y0, "A"),
    ("850", KV_LL_MV, "abc", 820, _Y0, "A"),
    ("816", KV_LL_MV, "abc", 930, _Y0, "A"),
    ("818", KV_LL_MV, "a",   930, _Y0 - 120, "A"),
    ("820", KV_LL_MV, "a",   930, _Y0 - 230, "A"),
    ("822", KV_LL_MV, "a",   1060, _Y0 - 230, "A"),
    ("824", KV_LL_MV, "abc", 1060, _Y0, "A"),
    ("826", KV_LL_MV, "b",   1060, _Y0 + 130, "A"),
    ("828", KV_LL_MV, "abc", 1170, _Y0, "A"),
    ("830", KV_LL_MV, "abc", 1290, _Y0, "A"),
    ("854", KV_LL_MV, "abc", 1400, _Y0, "A"),
    ("856", KV_LL_MV, "b",   1400, _Y0 + 130, "A"),
    ("852", KV_LL_MV, "abc", 1520, _Y0, "A"),
    ("832", KV_LL_MV, "abc", 1660, _Y0, "A"),
    ("888", KV_LL_LV, "abc", 1660, _Y0 + 130, "A"),
    ("890", KV_LL_LV, "abc", 1660, _Y0 + 240, "A"),
    ("858", KV_LL_MV, "abc", 1780, _Y0, "A"),
    ("864", KV_LL_MV, "a",   1780, _Y0 - 130, "A"),
    ("834", KV_LL_MV, "abc", 1900, _Y0, "A"),
    ("842", KV_LL_MV, "abc", 1900, _Y0 - 120, "A"),
    ("844", KV_LL_MV, "abc", 1900, _Y0 - 230, "A"),
    ("846", KV_LL_MV, "abc", 2020, _Y0 - 230, "A"),
    ("848", KV_LL_MV, "abc", 2140, _Y0 - 230, "A"),
    ("860", KV_LL_MV, "abc", 2020, _Y0, "A"),
    ("836", KV_LL_MV, "abc", 2140, _Y0, "A"),
    ("840", KV_LL_MV, "abc", 2260, _Y0, "A"),
    ("862", KV_LL_MV, "abc", 2140, _Y0 + 120, "A"),
    ("838", KV_LL_MV, "b",   2140, _Y0 + 230, "A"),
    # ---- Equivalent Feeder B (not part of IEEE 34)
    ("B01", KV_LL_MV, "abc", 270, 730, "B"),
    ("B02", KV_LL_MV, "abc", 440, 730, "B"),
    ("B03", KV_LL_MV, "abc", 610, 730, "B"),
    ("B04", KV_LL_MV, "abc", 780, 730, "B"),
    ("B05", KV_LL_MV, "abc", 610, 830, "B"),
]

# (dari, ke, panjang ft, konfigurasi)
LINES = [
    ("800", "802", 2580, "300"), ("802", "806", 1730, "300"),
    ("806", "808", 32230, "300"), ("808", "810", 5804, "303"),
    ("808", "812", 37500, "300"), ("812", "814", 29730, "300"),
    ("850", "816", 310, "301"),
    ("816", "818", 1710, "302"), ("818", "820", 48150, "302"),
    ("820", "822", 13740, "302"), ("816", "824", 10210, "301"),
    ("824", "826", 3030, "303"), ("824", "828", 840, "301"),
    ("828", "830", 20440, "301"), ("830", "854", 520, "301"),
    ("854", "856", 23330, "303"), ("854", "852", 36830, "301"),
    ("832", "858", 4900, "301"), ("858", "864", 1620, "302"),
    ("858", "834", 5830, "301"), ("834", "842", 280, "301"),
    ("842", "844", 1350, "301"), ("844", "846", 3640, "301"),
    ("846", "848", 530, "301"), ("834", "860", 2020, "301"),
    ("860", "836", 2680, "301"), ("836", "840", 860, "301"),
    ("836", "862", 280, "301"), ("862", "838", 4860, "304"),
    ("888", "890", 10560, "300"),
    # ---- Penyulang B ekuivalen
    ("800", "B01", 5280, "301"), ("B01", "B02", 10560, "301"),
    ("B02", "B03", 10560, "301"), ("B03", "B04", 7920, "301"),
    ("B03", "B05", 5280, "301"),
]
# Catatan: config 300 aslinya fasa "B A C N"; di sini dipetakan langsung a,b,c.

REGULATORS = [
    # id, dari, ke, tap default per fasa (step 0.625 %)
    {"id": "REG1", "from": "814", "to": "850", "taps": [12, 5, 5]},
    {"id": "REG2", "from": "852", "to": "832", "taps": [13, 11, 12]},
]

TRANSFORMERS = [
    {"id": "XFM1", "from": "832", "to": "888", "kva": 500, "kv1": KV_LL_MV,
     "kv2": KV_LL_LV, "r_pct": 1.9, "x_pct": 4.08, "conn": "Yg-Yg"},
]

SUBSTATION = {"kva": 2500, "kv_hv": 69.0, "kv_lv": KV_LL_MV, "r_pct": 1.0,
              "x_pct": 8.0, "v_pu": 1.075, "conn": "D-Yg"}

# Beban spot: bus, koneksi, model, [P_a,Q_a,P_b,Q_b,P_c,Q_c] (kW/kvar)
SPOT_LOADS = [
    ("860", "Y", "PQ", [20, 16, 20, 16, 20, 16]),
    ("840", "Y", "I",  [9, 7, 9, 7, 9, 7]),
    ("844", "Y", "Z",  [135, 105, 135, 105, 135, 105]),
    ("848", "D", "PQ", [20, 16, 20, 16, 20, 16]),
    ("890", "D", "I",  [150, 75, 150, 75, 150, 75]),
    ("830", "D", "Z",  [10, 5, 10, 5, 25, 10]),
]
# Beban terdistribusi: dari, ke, koneksi, model, [Pa,Qa,Pb,Qb,Pc,Qc]
DIST_LOADS = [
    ("802", "806", "Y", "PQ", [0, 0, 30, 15, 25, 14]),
    ("808", "810", "Y", "I",  [0, 0, 16, 8, 0, 0]),
    ("818", "820", "Y", "Z",  [34, 17, 0, 0, 0, 0]),
    ("820", "822", "Y", "PQ", [135, 70, 0, 0, 0, 0]),
    ("816", "824", "D", "I",  [0, 0, 5, 2, 0, 0]),
    ("824", "826", "Y", "I",  [0, 0, 40, 20, 0, 0]),
    ("824", "828", "Y", "PQ", [0, 0, 0, 0, 4, 2]),
    ("828", "830", "Y", "PQ", [7, 3, 0, 0, 0, 0]),
    ("854", "856", "Y", "PQ", [0, 0, 4, 2, 0, 0]),
    ("832", "858", "D", "Z",  [7, 3, 2, 1, 6, 3]),
    ("858", "864", "Y", "PQ", [2, 1, 0, 0, 0, 0]),
    ("858", "834", "D", "PQ", [4, 2, 15, 8, 13, 7]),
    ("834", "860", "D", "Z",  [16, 8, 20, 10, 110, 55]),
    ("860", "836", "D", "PQ", [30, 15, 10, 6, 42, 22]),
    ("836", "840", "D", "I",  [18, 9, 22, 11, 0, 0]),
    ("862", "838", "Y", "PQ", [0, 0, 28, 14, 0, 0]),
    ("842", "844", "Y", "PQ", [9, 5, 0, 0, 0, 0]),
    ("844", "846", "Y", "PQ", [0, 0, 25, 12, 20, 11]),
    ("846", "848", "Y", "PQ", [0, 0, 23, 11, 0, 0]),
]
# Penyulang B ekuivalen
FEEDER_B_LOADS = [
    ("B02", "Y", "Z", [50, 22, 50, 22, 50, 22]),
    ("B03", "Y", "Z", [40, 18, 40, 18, 40, 18]),
    ("B04", "Y", "Z", [35, 15, 35, 15, 35, 15]),
    ("B05", "Y", "Z", [30, 13, 30, 13, 30, 13]),
]

CAPACITORS = [
    {"id": "C844", "bus": "844", "kvar": [100, 100, 100]},
    {"id": "C848", "bus": "848", "kvar": [150, 150, 150]},
]

# Titik proteksi (Virtual IED). Arah 'forward' = dari 'from' ke 'to' (menuju beban).
IEDS = [
    {"id": "A1", "name": "CB-A (Feeder A Head)", "kind": "CB",
     "from": "800", "to": "802", "feeder": "A", "partner": "A2"},
    {"id": "A2", "name": "REC-A2 (Midline Recloser)", "kind": "REC",
     "from": "828", "to": "830", "feeder": "A", "partner": "A3"},
    {"id": "A3", "name": "REC-A3 (Downstream Recloser)", "kind": "REC",
     "from": "858", "to": "834", "feeder": "A", "partner": None},
    {"id": "L1", "name": "REC-L1 (Single-Phase Lateral 818)", "kind": "REC",
     "from": "816", "to": "818", "feeder": "A", "partner": None},
    {"id": "B1", "name": "CB-B (Feeder B Head)", "kind": "CB",
     "from": "800", "to": "B01", "feeder": "B", "partner": None},
]

LOAD_LEVELS = {"min_siang": 0.40, "menengah": 0.70, "puncak_malam": 1.00}


def base_network():
    """Kembalikan dict jaringan dasar (bisa dimodifikasi per skenario)."""
    buses = {}
    from .layout import COORDS
    for name, kv, ph, x, y, fd in BUSES:
        x, y = COORDS.get(name, (x, y))
        buses[name] = {"name": name, "kv": kv, "phases": ph, "x": x, "y": y,
                       "feeder": fd, "vbase": kv * 1e3 / np.sqrt(3)}
    branches = []
    for f, t, L, cfg in LINES:
        ph = LINE_CONFIGS[cfg]["phases"]
        branches.append({"id": f"L{f}-{t}", "kind": "line", "from": f, "to": t,
                         "len_ft": float(L), "cfg": cfg, "phases": ph})
    for r in REGULATORS:
        branches.append({"id": r["id"], "kind": "reg", "from": r["from"], "to": r["to"],
                         "taps": list(r["taps"]), "phases": "abc"})
    for x in TRANSFORMERS:
        branches.append({"id": x["id"], "kind": "xfmr", "from": x["from"], "to": x["to"],
                         "phases": "abc", **{k: v for k, v in x.items() if k not in ("id", "from", "to")}})

    loads = []
    def _add(bus, conn, model, pq, scale=1.0, tag=""):
        loads.append({"id": f"LD{bus}{tag}", "bus": bus, "conn": conn, "model": model,
                      "P": [pq[0] * scale, pq[2] * scale, pq[4] * scale],
                      "Q": [pq[1] * scale, pq[3] * scale, pq[5] * scale]})
    for bus, conn, model, pq in SPOT_LOADS:
        _add(bus, conn, model, pq, 1.0, "")
    for f, t, conn, model, pq in DIST_LOADS:
        _add(f, conn, model, pq, 0.5, f"_d{t}")
        _add(t, conn, model, pq, 0.5, f"_d{f}")
    for bus, conn, model, pq in FEEDER_B_LOADS:
        _add(bus, conn, model, pq, 1.0, "")
    # gabungkan beban per bus (untuk ikon rumah & tampilan)
    merged = {}
    for ld in loads:
        b = ld["bus"]
        key = (b, ld["conn"])
        if key not in merged:
            merged[key] = {"id": f"LD{b}" + ("" if ld["conn"] == "Y" else "D"),
                           "bus": b, "conn": ld["conn"], "model": ld["model"],
                           "P": [0.0, 0.0, 0.0], "Q": [0.0, 0.0, 0.0]}
        for k in range(3):
            merged[key]["P"][k] += ld["P"][k]
            merged[key]["Q"][k] += ld["Q"][k]
    loads = list(merged.values())

    return {
        "buses": buses, "branches": branches, "loads": loads,
        "caps": copy.deepcopy(CAPACITORS), "ieds": copy.deepcopy(IEDS),
        "substation": dict(SUBSTATION), "f0": F_NOM,
    }


def branch_Zabc(br):
    """Impedansi seri 3x3 (ohm) untuk saluran."""
    return config_Z(br["cfg"], br["phases"]) * (br["len_ft"] / FT_PER_MILE)


def seq_from_abc(Z):
    a = np.exp(2j * np.pi / 3)
    A = np.array([[1, 1, 1], [1, a * a, a], [1, a, a * a]])
    return np.linalg.inv(A) @ Z @ A


def build_adjacency(net, closed_only=False, open_set=()):
    adj = {b: [] for b in net["buses"]}
    for br in net["branches"]:
        if br["id"] in open_set:
            continue
        adj[br["from"]].append((br["to"], br["id"]))
        adj[br["to"]].append((br["from"], br["id"]))
    return adj


def path_from_source(net, target, source="800"):
    """Lintasan (list id cabang & bus) dari bus sumber ke target pada topologi radial."""
    adj = build_adjacency(net)
    prev = {source: None}
    stack = [source]
    while stack:
        u = stack.pop()
        for v, bid in adj[u]:
            if v not in prev:
                prev[v] = (u, bid)
                stack.append(v)
    if target not in prev:
        return None, None
    buses, brs = [target], []
    cur = target
    while prev[cur] is not None:
        u, bid = prev[cur]
        brs.append(bid)
        buses.append(u)
        cur = u
    return list(reversed(buses)), list(reversed(brs))


def split_line_for_fault(net, line_id, frac, fault_bus="F1"):
    """Sisipkan bus gangguan di tengah saluran (frac 0..1 dari 'from')."""
    net = copy.deepcopy(net)
    br = next(b for b in net["branches"] if b["id"] == line_id)
    if br["kind"] != "line":
        raise ValueError("Gangguan di tengah hanya untuk saluran")
    frac = min(max(frac, 0.01), 0.99)
    bf, bt = net["buses"][br["from"]], net["buses"][br["to"]]
    net["buses"][fault_bus] = {
        "name": fault_bus, "kv": bf["kv"], "phases": br["phases"],
        "x": bf["x"] + (bt["x"] - bf["x"]) * frac, "y": bf["y"] + (bt["y"] - bf["y"]) * frac,
        "feeder": bt["feeder"], "vbase": bf["vbase"], "virtual": True}
    L = br["len_ft"]
    b1 = dict(br, id=br["id"] + "a", to=fault_bus, len_ft=L * frac, parent=br["id"])
    b2 = dict(br, id=br["id"] + "b", **{"from": fault_bus}, len_ft=L * (1 - frac), parent=br["id"])
    idx = net["branches"].index(br)
    net["branches"][idx:idx + 1] = [b1, b2]
    # IED yang berada di saluran ini tetap di ujung 'from'
    for ied in net["ieds"]:
        if ied["from"] == br["from"] and ied["to"] == br["to"]:
            ied["to"] = fault_bus
    return net
