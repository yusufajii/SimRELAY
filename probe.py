"""
Probe campaign: look for misoperations that escape Fault Hunter or that the 5,247-case sweep never
exercises, while staying inside the scenario degrees of freedom of the test bench.

Every probe case is run on the Python engine with a longer duration than the sweep (4 s instead of
1.6 s) and is checked twice:
  * Fault Hunter (engine/hunter.py), exactly as in the sweep;
  * an independent oracle that looks only at physical outcomes:
      DELAY    the primary relay trips, but more than twice as slowly as in the same fault without
               DER and at least 0.2 s (one coordination interval) later;
      NOTRIP   the fault is present and no relay trips during the whole run;
      BACKFEED the fault stays energized by a DER for more than 0.1 s after the last relay breaker
               on the fault path has opened (cleared later by DER protection, or not at all).
A case flagged by the oracle but carrying no Fault Hunter label is a blind spot.

Each DER case is paired with the same case without DER (baseline) for the DELAY check.

    python probe.py              run all probe cases (2 processes) and write probe/
    python probe.py --list       list the cases only
"""
from __future__ import annotations
import os
for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")
import argparse
import collections
import copy
import hashlib
import json
import pickle
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, "probe")          # per set: probe/set1, probe/set2
PEAK_LOAD_KW = 1769.0
T_ON = 0.3
DURATION = 4.0
PHASES = {"SLG": "a", "LL": "ab", "DLG": "ab", "3PH": "abc"}

# ------------------------------------------------------------------ hypotheses
HYP = {
    "A1": ("Delayed clearing is not labelled",
           "A DER between the substation and the fault (806) takes over part of the fault current, so A1 "
           "trips much later than without DER or loses its instantaneous reach. Fault Hunter only labels a "
           "primary that never trips (F-1), so these cases are recorded as normal."),
    "A2": ("A fault that no relay clears is not labelled",
           "With high fault resistance and infeed, the primary picks up but its timer is too slow to finish "
           "inside the run. Fault Hunter labels F-1 only when the current is above pickup for less than 60% "
           "of the time, so a relay that stays picked up without tripping is recorded as normal."),
    "A3": ("Fault kept alive by a DER after the relay opens",
           "A DER downstream of the opened breaker keeps feeding the fault in an unintentional island until "
           "its own undervoltage or anti-islanding protection acts (up to 2 s). Fault Hunter stops at the "
           "relay trip and never checks that the fault is extinguished."),
    "B1": ("Line-to-line and double line-to-ground faults",
           "The sweep only applies SLG and 3PH faults. LL faults have no zero-sequence current and lower "
           "current than 3PH; with an IBR they may blind 51P or upset 67P. DLG faults combine both "
           "mechanisms of SLG with the zero-sequence source of the Yg-D transformer."),
    "B2": ("Fault locations outside the sweep",
           "Faults at the end of Feeder A (840), on the 4.16 kV side of XFM1 (890), on branch 864, on the "
           "single-phase lateral (820) and at the end of Feeder B (B05) are never applied. Low fault current "
           "at 890 and 820 may already be close to the pickups without DER."),
    "B3": ("IBR interconnection transformer",
           "The sweep connects the IBR through a Yg-D transformer, which is a zero-sequence source. With a "
           "D-Yg transformer (no zero-sequence path to the feeder) the 3I0-driven F-2 and F-3 should vanish, "
           "which isolates the grounding transformer as their root cause."),
    "B4": ("Two DER at once",
           "The sweep places one DER per case. A DER upstream of a relay (infeed, blinding) combined with one "
           "downstream (backfeed) may produce failures that neither causes alone."),
    "B5": ("IBR fault ride-through control",
           "The sweep uses reactive-priority ride-through only. Negative-sequence injection may correct the "
           "directional decision of 67 (F-4); momentary cessation removes the IBR contribution and so may "
           "remove its backfeed (F-2) but cause blinding instead."),
    "C1": ("Distance relays with fault resistance",
           "F-5 is judged only for bolted faults (Rf up to 1 ohm). With fault resistance and infeed a fault inside "
           "Zone 1 may be seen in Zone 2 or 3, and the relay is then slower than the same fault without DER."),
    "C2": ("Faulted phase B or C, and single-phase laterals",
           "Every sweep fault is on phase A at a three-phase bus. Phase B and C see different loads and laterals; "
           "laterals 810, 826, 856, 838 and 864 have no relay of their own and are far from the one that must act."),
    "C3": ("Temporary faults",
           "Fault Hunter judges trips only until 50 ms after the fault ends. A relay that trips later, when no fault "
           "is left, would carry no label."),
    "C4": ("Islanded microgrid",
           "The ground truth takes the substation as the source. In an island the source is the grid-forming inverter "
           "at 824, so for a fault between 824 and the substation no relay is placed to clear it."),
    "C5": ("Mixed relay classes on one feeder",
           "The coordination checks (CTI margin) are written for overcurrent backups. A distance or directional relay "
           "downstream of an overcurrent relay may coordinate differently."),
    "C6": ("Faults at breaker terminals and at the substation bus",
           "A fault at 800 has no relay upstream, so there is no primary to judge; faults at 802, 828, 858 and 816 sit "
           "exactly at a relay terminal, where the primary and backup roles change."),
    "C7": ("Two faults at once",
           "Fault Hunter judges each fault on its own, so a correct trip for one fault may be labelled against the other."),
    "C8": ("Grid-forming inverter in grid-connected mode",
           "The sweep uses grid-forming inverters only in the island. Grid-connected, a grid-forming inverter is a "
           "voltage source with a larger fault contribution than a grid-following one."),
    "C10": ("Reverse power flow without a fault",
            "The sweep always applies a fault, so a relay that trips on reverse load current from a large DER is "
            "labelled against the fault (F-2) instead of as a nuisance trip. Here no fault is applied."),
    "C9": ("DER on the 4.16 kV side of XFM1",
           "No DER is placed behind XFM1 (Yg-Yg, 500 kVA) in the sweep. Its zero-sequence contribution passes through "
           "the transformer to the 24.9 kV feeder."),
}


def unit(tech, bus, pen, uid="DER1", **kw):
    kva = round(PEAK_LOAD_KW * pen / 100)
    xf = kw.pop("xfmr", "YgD")
    u = {"id": uid, "bus": bus, "type": tech, "kva": kva, "xfmr": xf}
    if tech == "IBR-GFL":
        u["frt"] = "Q"
    u.update(kw)
    return u


def case(h, label, units, bus, ftype, rf=0, load="puncak_malam", cls="OCR", phases=None, t_off=None,
         classes=None, island=False, extra=None):
    f = {"bus": bus, "type": ftype, "phases": phases or PHASES[ftype], "rf": rf, "t_on": T_ON}
    if t_off is not None:
        f["t_off"] = t_off
    grid = {"mode": "island", "t_island": 0.0} if island else {"mode": "grid"}
    sc = {"der": {"units": units}, "load": {"level": load}, "grid": grid,
          "faults": [f] + list(extra or []),
          "relays": {"default": cls, "classes": dict(classes or {})}, "events": [],
          "sim": {"duration": DURATION, "t_cb": 0.05, "save": False}}
    return {"hyp": h, "label": label, "bus": bus, "ftype": ftype, "rf": rf, "load": load, "cls": cls, "sc": sc}


def isl(site, pen):
    kva = PEAK_LOAD_KW * pen / 100
    return [{"id": "DER1", "bus": "824", "type": "IBR-GFM", "kva": round(kva * 0.6), "xfmr": "YgD"},
            {"id": "DER2", "bus": site, "type": "IBR-GFL", "kva": round(kva * 0.4), "xfmr": "DYg", "frt": "Q"}]


def build(which=1):
    C = build2() if which == 2 else build1()
    for c in C:
        c["key"] = hashlib.sha1(json.dumps(c["sc"], sort_keys=True).encode()).hexdigest()[:12]
    return C


def build2():
    """Set 2: one hypothesis per premise of the Fault Hunter rules (see HYP, C1 to C9)."""
    C = []
    SG848, GFL848 = [unit("SG", "848", 120)], [unit("IBR-GFL", "848", 120)]
    SG828, GFL828 = [unit("SG", "828", 120)], [unit("IBR-GFL", "828", 120)]
    # C1 distance relays with fault resistance (F-5 is only judged for Rf up to 1 ohm)
    for rf in (5, 20):
        for bus in ("848", "840"):
            for lab, u in (("SG@848", SG848), ("IBR-GFL@848", GFL848)):
                C.append(case("C1", f"{lab} 120%, SLG at {bus}, Rf {rf}", u, bus, "SLG", rf=rf, cls="DIST"))
    # C2 faulted phase B or C, and single-phase laterals
    for ph in ("b", "c"):
        for bus in ("830", "834", "848"):
            for lab, u in (("SG@828", SG828), ("IBR-GFL@848", GFL848)):
                C.append(case("C2", f"{lab} 120%, SLG {ph.upper()}-G at {bus}", u, bus, "SLG", phases=ph))
    for bus, ph in (("810", "b"), ("826", "b"), ("856", "b"), ("838", "b"), ("864", "a")):
        for lab, u in (("SG@806", [unit("SG", "806", 120)]), ("SG@848", SG848)):
            C.append(case("C2", f"{lab} 120%, SLG {ph.upper()}-G on lateral {bus}", u, bus, "SLG", phases=ph))
    # C3 temporary faults (trips are judged only until 50 ms after the fault ends)
    for t_off in (0.40, 0.55):
        for lab, u, bus in (("SG@828", SG828, "834"), ("IBR-GFL@848", GFL848, "830"), ("SG@B03", [unit("SG", "B03", 120)], "830")):
            C.append(case("C3", f"{lab} 120%, SLG at {bus} cleared by itself at {t_off:.2f} s", u, bus, "SLG", t_off=t_off))
    # C4 islanded microgrid: the ground truth assumes the source is the substation
    for site, pen in (("848", 120), ("806", 60)):
        for bus in ("812", "830", "834", "848"):
            C.append(case("C4", f"Island GFM@824 + GFL@{site} {pen}%, SLG at {bus}", isl(site, pen), bus, "SLG",
                          load="min_siang", island=True))
    for bus in ("812", "830", "834", "848"):
        C.append(case("C4", f"Island GFM@824 + GFL@848 120%, SLG at {bus}", isl("848", 120), bus, "SLG",
                      load="min_siang", island=True, cls="DOCR"))
    # C5 mixed relay classes on one feeder (coordination rules written for one class)
    for lab_c, cl in (("A3 DIST", {"A3": "DIST"}), ("A3 DOCR", {"A3": "DOCR"}), ("A2 DIST", {"A2": "DIST"})):
        for bus in ("834", "848"):
            for lab, u in (("SG@828", SG828), ("IBR-GFL@848", GFL848)):
                C.append(case("C5", f"{lab} 120%, {lab_c}, others OCR, SLG at {bus}", u, bus, "SLG", classes=cl))
    # C6 faults at breaker terminals and at the substation bus
    for bus in ("800", "802", "828", "858", "816"):
        for lab, u in (("SG@828", SG828), ("IBR-GFL@848", GFL848)):
            C.append(case("C6", f"{lab} 120%, SLG at {bus}", u, bus, "SLG"))
    # C7 two faults at once
    for lab, u in (("SG@828", SG828), ("IBR-GFL@848", GFL848)):
        C.append(case("C7", f"{lab} 120%, SLG at 830 and SLG at B04", u, "830", "SLG",
                      extra=[{"bus": "B04", "type": "SLG", "phases": "a", "rf": 0, "t_on": T_ON}]))
        C.append(case("C7", f"{lab} 120%, SLG at 834 and SLG at 812", u, "834", "SLG",
                      extra=[{"bus": "812", "type": "SLG", "phases": "a", "rf": 0, "t_on": T_ON}]))
        C.append(case("C7", f"{lab} 120%, SLG at 834, then SLG at 848 at 0.50 s", u, "834", "SLG",
                      extra=[{"bus": "848", "type": "SLG", "phases": "a", "rf": 0, "t_on": 0.50}]))
    # C8 grid-forming inverter in grid-connected mode
    for site in ("848", "828"):
        for bus in ("830", "834", "848", "B04"):
            C.append(case("C8", f"IBR-GFM@{site} 120% grid-connected, SLG at {bus}", [unit("IBR-GFM", site, 120)], bus, "SLG"))
    # C10 no fault at all: reverse power flow from a large DER against non-directional pickups
    for tech in ("SG", "IBR-GFL"):
        for site in ("806", "828", "840", "848", "B03"):
            for pen in (90, 120):
                c = case("C10", f"{tech}@{site} {pen}%, no fault, light load", [unit(tech, site, pen)], "830", "SLG", load="min_siang")
                c["sc"]["faults"] = []
                c["bus"], c["ftype"] = "none", "none"
                C.append(c)
    # C9 DER on the 4.16 kV side of XFM1 (20%: the transformer is rated 500 kVA)
    for tech in ("SG", "IBR-GFL"):
        for bus in ("830", "834", "890"):
            C.append(case("C9", f"{tech}@890 20%, SLG at {bus}", [unit(tech, "890", 20)], bus, "SLG"))
    return C


def build1():
    C = []
    # A1 delayed clearing: infeed at 806, fault at 812 (A1 is the primary)
    for tech in ("SG", "IBR-GFL"):
        for pen in (60, 120):
            for ft, load in (("SLG", "min_siang"), ("SLG", "puncak_malam"), ("3PH", "puncak_malam")):
                C.append(case("A1", f"{tech}@806 {pen}%, {ft} at 812, {load}", [unit(tech, "806", pen)], "812", ft, load=load))
    # A2 no relay clears: high Rf with infeed
    for tech in ("SG", "IBR-GFL"):
        for pen in (100, 120):
            C.append(case("A2", f"{tech}@806 {pen}%, Rf 50", [unit(tech, "806", pen)], "812", "SLG", rf=50))
    C.append(case("A2", "IBR-GFL@828 120%, Rf 50", [unit("IBR-GFL", "828", 120)], "812", "SLG", rf=50))
    # A3 backfeed after the relay opens: DER downstream of the opened breaker
    for tech in ("SG", "IBR-GFL"):
        for site, bus in (("848", "834"), ("848", "830"), ("840", "834"), ("848", "858")):
            C.append(case("A3", f"{tech}@{site} 120%, fault {bus}", [unit(tech, site, 120)], bus, "SLG"))
        C.append(case("A3", f"{tech}@848 120%, 3PH at 834", [unit(tech, "848", 120)], "834", "3PH"))
    # B1 LL and DLG faults
    for ft in ("LL", "DLG"):
        for bus in ("830", "834", "848"):
            for pl, u in (("SG@828", [unit("SG", "828", 120)]), ("IBR-GFL@848", [unit("IBR-GFL", "848", 120)])):
                for cls in ("OCR", "DOCR"):
                    C.append(case("B1", f"{pl} 120%, {ft} at {bus}", u, bus, ft, cls=cls))
    # B2 fault locations outside the sweep
    for bus, ft in (("840", "SLG"), ("840", "3PH"), ("890", "SLG"), ("890", "3PH"), ("864", "SLG"),
                    ("820", "SLG"), ("B05", "SLG")):
        for pl, u in (("SG@848", [unit("SG", "848", 120)]), ("IBR-GFL@828", [unit("IBR-GFL", "828", 120)])):
            C.append(case("B2", f"{pl} 120%, {ft} at {bus}", u, bus, ft))
    # B3 IBR transformer D-Yg instead of Yg-D
    for site, bus in (("828", "834"), ("828", "830"), ("B03", "830"), ("848", "830")):
        for xf in ("YgD", "DYg"):
            C.append(case("B3", f"IBR-GFL@{site} 120% {xf}, SLG at {bus}",
                          [unit("IBR-GFL", site, 120, xfmr=xf)], bus, "SLG"))
    # B4 two DER at once (60% + 60%)
    pairs = (("SG@806 + IBR-GFL@848", [unit("SG", "806", 60), unit("IBR-GFL", "848", 60, uid="DER2")]),
             ("SG@828 + SG@B03", [unit("SG", "828", 60), unit("SG", "B03", 60, uid="DER2")]),
             ("IBR-GFL@806 + SG@840", [unit("IBR-GFL", "806", 60), unit("SG", "840", 60, uid="DER2")]))
    for lab, u in pairs:
        for bus, ft in (("812", "SLG"), ("830", "SLG"), ("834", "SLG"), ("B04", "SLG")):
            C.append(case("B4", f"{lab}, {ft} at {bus}", u, bus, ft))
    # B5 IBR ride-through control, DOCR
    for lab, kw in (("Q priority", {}), ("negative sequence", {"neg_seq": True}),
                    ("momentary cessation", {"momentary_cessation": True}), ("P priority", {"frt": "P"})):
        for bus, ft in (("830", "SLG"), ("834", "LL"), ("B04", "SLG")):
            C.append(case("B5", f"IBR-GFL@848 120% {lab}, {ft} at {bus}",
                          [unit("IBR-GFL", "848", 120, **kw)], bus, ft, cls="DOCR"))
    return C


def baseline_of(c):
    if c["sc"]["grid"].get("mode") != "grid":
        return None
    b = copy.deepcopy(c)
    b["hyp"], b["label"] = "base", f"no DER, {c['ftype']} at {c['bus']}"
    b["sc"]["der"]["units"] = []
    b["key"] = hashlib.sha1(json.dumps(b["sc"], sort_keys=True).encode()).hexdigest()[:12]
    return b


# ------------------------------------------------------------------ worker
_S = None


def _init():
    global _S
    with open(os.path.join(ROOT, "cache", "settings.pkl"), "rb") as f:
        _S = pickle.load(f)[0]


def run_one(c):
    from engine.sim import Simulator
    from engine.hunter import analyze
    from engine.network import path_from_source
    t0 = time.time()
    sim = Simulator(copy.deepcopy(c["sc"]), _S).run()
    hunt = analyze(sim)
    hf = hunt["faults"][0] if hunt["faults"] else {}
    trips = {d.id: round(float(d.trip_time), 4) for d in sim.ieds if d.tripped}
    elems = {d.id: d.trip_elem for d in sim.ieds if d.tripped}
    opens = {}
    for j, d in enumerate(sim.ieds):
        cl = sim.cb_t[:, j]
        if cl[0] and not cl.all():
            opens[d.id] = round(float(sim.t[int(np.argmax(~cl))]), 4)
    clear = sim.fault_clear_t[0] if sim.fault_clear_t else None
    If = np.abs(sim.Ifault[:, 0, :]).max(axis=1)
    der_trips = [{"t": e["t"], "id": e["id"], "text": e["text"]} for e in sim.events_sim if e["type"] == "DER_TRIP"]
    return {"key": c["key"], "hyp": c["hyp"], "label": c["label"], "bus": c["bus"], "ftype": c["ftype"],
            "rf": c["rf"], "load": c["load"], "cls": c["cls"], "ders": c["sc"]["der"]["units"],
            "primary": hf.get("primary"), "backup": hf.get("backup"), "upstream": hf.get("upstream", []),
            "counts": hunt["counts"], "findings": [{"code": f["code"], "ied": f["ied"], "title": f["title"]} for f in hunt["findings"]],
            "confusion": hunt["confusion"], "trips": trips, "elems": elems, "opens": opens,
            "fault_clear_t": None if clear is None else round(float(clear), 4),
            "t_off": c["sc"]["faults"][0].get("t_off") if c["sc"]["faults"] else None,
            "If_end_A": round(float(If[-1]), 2), "der_trips": der_trips, "wall": round(time.time() - t0, 2)}


# ------------------------------------------------------------------ oracle
def oracle(r, base):
    flags = []
    P = r["primary"]
    tP = r["trips"].get(P)
    tB = base["trips"].get(P) if base else None
    if tP is not None and tB is not None:
        dP, dB = tP - T_ON, tB - T_ON
        if dP > max(2 * dB, dB + 0.2):
            flags.append(("DELAY", f"{P} trips {dP:.3f} s after inception, against {dB:.3f} s without DER"))
    if not r["trips"] and r["t_off"] is None:
        flags.append(("NOTRIP", f"No relay trips within {DURATION - T_ON:.1f} s; fault current {r['If_end_A']:.0f} A at the end"))
    path_opens = [t for i, t in r["opens"].items() if i in r["upstream"]]
    if path_opens:
        t_open = max(path_opens)
        t_clear = r["fault_clear_t"]
        if t_clear is None and r["If_end_A"] <= 1.0:
            pass                                  # extinguished (temporary fault, or under 1 A)
        elif t_clear is None:
            flags.append(("BACKFEED", f"Fault still energized at the end of the run ({r['If_end_A']:.0f} A), "
                                      f"relay breaker open since {t_open:.3f} s"))
        elif t_clear - t_open > 0.1:
            who = "; ".join(f"{d['id']} at {d['t']:.3f} s" for d in r["der_trips"]) or "none"
            flags.append(("BACKFEED", f"Fault fed for {t_clear - t_open:.3f} s after the relay breaker opened; "
                                      f"cleared at {t_clear:.3f} s (DER trips: {who})"))
    # NOTCLEARED: the fault is still energized at the end of the run and no breaker on its path opened
    if not path_opens and r["If_end_A"] > 1.0 and r["t_off"] is None:
        flags.append(("NOTCLEARED", f"Fault still energized at the end of the run ({r['If_end_A']:.0f} A) and no breaker on its path opened"))
    # POSTTRIP: a relay trips more than 50 ms after a temporary fault has ended
    if r["t_off"] is not None:
        late = {i: t for i, t in r["trips"].items() if t > r["t_off"] + 0.05}
        if late:
            flags.append(("POSTTRIP", "Trip after the fault had ended: " + ", ".join(f"{i} at {t:.3f} s" for i, t in late.items())))
    # ZONE: a distance primary trips in Zone 1 without DER but in a slower zone with DER
    if P and base and str(base["elems"].get(P, "")).startswith("21-Z1") and P in r["elems"]             and not str(r["elems"][P]).startswith("21-Z1"):
        flags.append(("ZONE", f"{P} trips with {r['elems'][P]} instead of Zone 1 (Zone 1 without DER)"))
    return flags


def summarize(cases, res):
    by = {r["key"]: r for r in res}
    rows = []
    for c in cases:
        r = by.get(c["key"])
        if not r:
            continue
        bc = baseline_of(c)
        b = by.get(bc["key"]) if bc else None
        fl = oracle(r, b)
        hunt = {k: v for k, v in r["counts"].items() if v}
        # one simulation can serve several hypotheses (identical scenario); label it per hypothesis
        rows.append({**r, "hyp": c["hyp"], "label": c["label"], "oracle": fl, "hunter": hunt, "blind": bool(fl) and not hunt,
                     "base_counts": {k: v for k, v in b["counts"].items() if v} if b else None,
                     "base_trips": b["trips"] if b else None})
    return rows


def write_report(rows):
    lines = [f"# Probe campaign {os.path.basename(OUT)}: results", "",
             f"{len(rows)} probe cases, Python engine, run length {DURATION:.1f} s, fault at {T_ON:.1f} s.",
             "Blind spot = flagged by the oracle but no Fault Hunter label.", ""]
    for h, (title, text) in HYP.items():
        R = [r for r in rows if r["hyp"] == h]
        if not R:
            continue
        nb = sum(r["blind"] for r in R)
        nl = sum(bool(r["hunter"]) for r in R)
        no = sum(bool(r["oracle"]) for r in R)
        lines += [f"## {h}. {title}", "", text, "",
                  f"Cases {len(R)}, Fault Hunter label {nl}, oracle flag {no}, blind spot {nb}.", "",
                  "| Case | Fault Hunter | Oracle | Trips (s) |", "|---|---|---|---|"]
        for r in R:
            fh = ", ".join(f"{k} {v}" for k, v in r["hunter"].items()) or "normal"
            if r["base_counts"]:
                fh += " (baseline: " + ", ".join(r["base_counts"]) + ")"
            orc = "; ".join(f"{k}: {t}" for k, t in r["oracle"]) or ""
            tr = ", ".join(f"{i} {t - T_ON:.3f} {r['elems'][i]}" for i, t in sorted(r["trips"].items(), key=lambda x: x[1])) or "none"
            mark = "**" if r["blind"] else ""
            lines.append(f"| {mark}{r['label']} ({r['cls']}){mark} | {fh} | {orc} | {tr} |")
        lines.append("")
    with open(os.path.join(OUT, "PROBE_RESULTS.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--report", action="store_true", help="rebuild the report from the stored results without simulating")
    ap.add_argument("--set", type=int, default=1, choices=(1, 2), help="1: hypotheses A and B, 2: premises C1 to C9")
    a = ap.parse_args()
    global OUT
    OUT = os.path.join(ROOT, "probe", f"set{a.set}")
    cases = build(a.set)
    if a.report:
        with open(os.path.join(OUT, "results.jsonl"), encoding="utf-8") as f:
            res = [json.loads(l) for l in f]
        rows = summarize(cases, res)
        with open(os.path.join(OUT, "summary.json"), "w", encoding="utf-8") as f:
            json.dump(rows, f, indent=1)
        write_report(rows)
        for h in HYP:
            R = [r for r in rows if r["hyp"] == h]
            print(f"{h}: {len(R)} cases, hunter {sum(bool(r['hunter']) for r in R)}, oracle {sum(bool(r['oracle']) for r in R)}, blind {sum(r['blind'] for r in R)}")
        return
    bases = {}
    for c in cases:
        b = baseline_of(c)
        if b and c["sc"]["der"]["units"]:
            bases[b["key"]] = b
    todo = cases + [b for k, b in bases.items() if k not in {c["key"] for c in cases}]
    print(f"{len(cases)} probe cases ({dict(collections.Counter(c['hyp'] for c in cases))}) plus {len(todo) - len(cases)} baselines")
    if a.list:
        for c in cases:
            print(f"  {c['hyp']}  {c['label']}  {c['cls']}")
        return
    os.makedirs(OUT, exist_ok=True)
    res, t0 = [], time.time()
    with ProcessPoolExecutor(max_workers=a.workers, initializer=_init) as ex:
        futs = [ex.submit(run_one, c) for c in todo]
        for i, fu in enumerate(as_completed(futs), 1):
            res.append(fu.result())
            if i % 10 == 0 or i == len(todo):
                print(f"  {i}/{len(todo)} done, {time.time() - t0:.0f} s", flush=True)
    with open(os.path.join(OUT, "results.jsonl"), "w", encoding="utf-8") as f:
        for r in res:
            f.write(json.dumps(r) + "\n")
    rows = summarize(cases, res)
    with open(os.path.join(OUT, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=1)
    write_report(rows)
    for h in HYP:
        R = [r for r in rows if r["hyp"] == h]
        print(f"{h}: {len(R)} cases, hunter {sum(bool(r['hunter']) for r in R)}, oracle {sum(bool(r['oracle']) for r in R)}, blind {sum(r['blind'] for r in R)}")


if __name__ == "__main__":
    main()
