"""
Top main scenarios: presets verified to trigger their target failure
(found with a fault-hunting sweep; see README). All use the frozen baseline
relay settings.
"""
from .network import BUSES, LINES

DER_BUSES = [b[0] for b in BUSES if b[2] == "abc" and b[1] > 20 and b[0] != "800"]
FAULT_BUSES = [b[0] for b in BUSES]
LINES_FOR_FAULT = [f"L{f}-{t}" for f, t, L, c in LINES if L >= 1000]


def _sc(der=None, load=None, grid=None, faults=None, relays="OCR", classes=None, events=None, dur=2.5):
    return {
        "der": {"units": der or []},
        "load": load or {"level": "puncak_malam"},
        "grid": grid or {"mode": "grid"},
        "faults": faults or [],
        "relays": {"default": relays, "classes": classes or {}},
        "events": events or [],
        "sim": {"duration": dur, "t_cb": 0.05},
    }


PRESETS = [
    {"id": "S0", "code": "OK", "name": "Baseline 0% DER",
     "desc": "Control case: no DER, SLG A-G fault at bus 834. Conventional relays must operate correctly (A3 is primary).",
     "scenario": _sc(faults=[{"bus": "834", "type": "SLG", "phases": "a", "rf": 0, "t_on": 0.5}])},

    {"id": "S1", "code": "F-1", "name": "Blinding in IBR Microgrid",
     "desc": "Islanded mode: 1.5 MVA IBR-GFM at 824 and 800 kVA PV at 806 (daytime load). Three-phase fault at 844: IBR current is limited to about 1.3 pu, so A3 barely detects the fault.",
     "scenario": _sc(der=[{"id": "DER1", "bus": "824", "type": "IBR-GFM", "kva": 1500, "xfmr": "YgD"},
                          {"id": "DER2", "bus": "806", "type": "IBR-GFL", "kva": 800, "xfmr": "DYg", "frt": "Q"}],
                     load={"level": "min_siang"}, grid={"mode": "island", "t_island": 0.0},
                     faults=[{"bus": "844", "type": "3PH", "phases": "abc", "rf": 0, "t_on": 0.5}], dur=3.0)},

    {"id": "S2", "code": "F-2", "name": "Sympathetic Trip on Feeder B",
     "desc": "800 kVA SG at B03 with a Yg-Delta transformer (zero-sequence source). SLG A-G fault with Rf 5 Ω at 824 (Feeder A): CB-B also trips on 51N.",
     "scenario": _sc(der=[{"id": "DER1", "bus": "B03", "type": "SG", "kva": 800, "xfmr": "YgD"}],
                     faults=[{"bus": "824", "type": "SLG", "phases": "a", "rf": 5, "t_on": 0.5}])},

    {"id": "S3", "code": "F-3", "name": "Miscoordination by 50N Overreach",
     "desc": "1.5 MVA Yg-Delta SG at 828 (upstream of A2) raises ground current through A2 for a fault at 834. The A2 50N element overreaches and trips before A3.",
     "scenario": _sc(der=[{"id": "DER1", "bus": "828", "type": "SG", "kva": 1500, "xfmr": "YgD"}],
                     faults=[{"bus": "834", "type": "SLG", "phases": "a", "rf": 0, "t_on": 0.5}])},

    {"id": "S4", "code": "F-4", "name": "Directional Error with DOCR 67 and IBR",
     "desc": "All IEDs set to DOCR. 2 MVA PV/IBR at 848 (downstream of A3). SLG fault at 830 (behind A3): the healthy-phase 67P element of A3 declares FORWARD and a healthy line is tripped.",
     "scenario": _sc(der=[{"id": "DER1", "bus": "848", "type": "IBR-GFL", "kva": 2000, "xfmr": "YgD", "frt": "Q"}],
                     relays="DOCR", faults=[{"bus": "830", "type": "SLG", "phases": "a", "rf": 0, "t_on": 0.5}])},

    {"id": "S5", "code": "F-5", "name": "Distance 21 Under-reach",
     "desc": "All IEDs set to Distance 21. 2 MVA Yg-Delta SG at 808 provides infeed between A1 and an SLG fault at 812 (within Zone 1). A1 measures a larger impedance and operates in Zone 2 (0.3 s delay).",
     "scenario": _sc(der=[{"id": "DER1", "bus": "808", "type": "SG", "kva": 2000, "xfmr": "YgD"}],
                     relays="DIST", faults=[{"bus": "812", "type": "SLG", "phases": "a", "rf": 0, "t_on": 0.5}])},

    {"id": "S6", "code": "NT", "name": "Cold Load Pickup",
     "desc": "CB-A is reclosed after an extended outage: load rises threefold and decays with τ = 8 s. With no fault present, the conventional 51P element still trips (nuisance).",
     "scenario": _sc(load={"level": "puncak_malam", "clpu": {"enable": True, "factor": 3.0, "tau": 8.0, "t_energize": 0.3, "feeders": ["A"]}},
                     grid={"mode": "grid", "cb_init": {"A1": False}},
                     events=[{"t": 0.3, "type": "CB_CLOSE", "id": "A1", "_clpu": True}], dur=5.0)},

    {"id": "S7", "code": "MG", "name": "Passing Cloud with Fault",
     "desc": "1.5 MVA PV at 840 under a passing cloud (1000 to 200 W/m² at t = 0.4 s), followed by an SLG fault at 858 at t = 1.5 s. Demonstrates DoF-1 intermittency.",
     "scenario": _sc(der=[{"id": "DER1", "bus": "840", "type": "IBR-GFL", "kva": 1500, "xfmr": "YgD", "frt": "Q",
                           "irr_ui": {"kind": "cloud", "g0": 1000, "gmin": 200, "ts": 0.4, "ramp": 0.4, "dur": 3.0},
                           "irradiance": [[0, 1000], [0.4, 1000], [0.8, 200], [3.8, 200], [4.2, 1000]]}],
                     faults=[{"bus": "858", "type": "SLG", "phases": "a", "rf": 5, "t_on": 1.5}], dur=3.5)},
]
