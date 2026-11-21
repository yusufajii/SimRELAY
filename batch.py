#!/usr/bin/env python3
"""
SimRELAY: batch simulation campaign (parsim equivalent) for the Post-Run analysis.

    python batch.py                 run the full campaign (resumes where it stopped)
    python batch.py --pilot         small pilot subset
    python batch.py --workers 8     number of parallel workers (default: CPU count - 1)
    python batch.py --engine matlab MATLAB Simulink engine, MATLAB parfor on a worker pool;
                                    results go to batch_matlab/ unless --outdir is given

Each case is simulated with the frozen baseline relay settings and analysed by the
Fault Hunter. One compact record per case is appended to batch/results.jsonl, and the
whole campaign is exported to batch/batch_results.json and batch/batch_results.mat
(MATLAB) when the run finishes.

Design
  Each case places ONE DER, sized as a percentage of the Feeder A peak load, at one of the
  candidate buses (806, 828, 840, 848 on Feeder A, B03 on Feeder B) with one technology
  (synchronous generator with a Yg-Delta transformer, or grid-following inverter), and
  applies one of 11 fault cases. A cell's failure rate is the share of
  (placement, fault) cases with at least one misoperation (F-1 to F-5).

Campaign
  H1  Penetration x load level     OCR, Rf = 0
  H2  Penetration x fault Rf       OCR, evening peak load
  E   Relay class escalation       DOCR / DIST / DIFF (OCR taken from H1)
  I   Islanded microgrid           IBR-GFM at 824 plus IBR-GFL at a candidate bus
"""
from __future__ import annotations
import os
# The engine works on small matrices; multithreaded BLAS only adds overhead (about 7x slower)
# and stalls when several simulations run in parallel. Must be set before numpy is imported.
for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")
import argparse
import copy
import hashlib
import json
import pickle
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, "batch")
JSONL = os.path.join(OUT, "results.jsonl")

PEAK_LOAD_KW = 1769.0            # Feeder A peak load (sum of IEEE 34 spot and distributed loads)
PENS = [0, 20, 40, 60, 80, 100, 120]
LOADS = [("min_siang", 40), ("menengah", 70), ("puncak_malam", 100)]
RFS = [0, 5, 20, 50]
FAULTS = [("812", "SLG"), ("812", "3PH"), ("830", "SLG"), ("830", "3PH"), ("834", "SLG"), ("834", "3PH"),
          ("848", "SLG"), ("848", "3PH"), ("822", "SLG"), ("B04", "SLG"), ("B04", "3PH")]
T_ON = 0.3
DURATION = 1.6

SITES = ["806", "828", "840", "848", "B03"]
TECHS = [("SG", "YgD"), ("IBR-GFL", "YgD")]
PLACEMENTS = [f"{t}@{b}" for b in SITES for t, _ in TECHS]
ISL_SITES = ["806", "840", "848"]


def der_units(place, pen):
    """place: 'SG@828', 'IBR-GFL@848' or 'ISL@848' (islanded: GFM at 824 plus GFL at the site)."""
    if pen <= 0 or place == "none":
        return []
    kva = PEAK_LOAD_KW * pen / 100
    tech, bus = place.split("@")
    if tech == "ISL":
        return [{"id": "DER1", "bus": "824", "type": "IBR-GFM", "kva": round(kva * 0.6), "xfmr": "YgD"},
                {"id": "DER2", "bus": bus, "type": "IBR-GFL", "kva": round(kva * 0.4), "xfmr": "DYg", "frt": "Q"}]
    u = {"id": "DER1", "bus": bus, "type": tech, "kva": round(kva), "xfmr": dict(TECHS)[tech]}
    if tech == "IBR-GFL":
        u["frt"] = "Q"
    return [u]


def scenario(place, pen, load, rf, bus, ftype, cls):
    grid = {"mode": "island", "t_island": 0.0} if place.startswith("ISL") else {"mode": "grid"}
    return {
        "der": {"units": der_units(place, pen)}, "load": {"level": load}, "grid": grid,
        "faults": [{"bus": bus, "type": ftype, "phases": "abc" if ftype == "3PH" else "a", "rf": rf, "t_on": T_ON}],
        "relays": {"default": cls, "classes": {}}, "events": [],
        "sim": {"duration": DURATION, "t_cb": 0.05, "save": False},
    }


def build_cases(pilot=False):
    cases = []

    def add(camp, place, pen, load, rf, bus, ftype, cls):
        tech, site = place.split("@") if "@" in place else ("none", "none")
        p = {"campaign": camp, "fleet": place, "tech": tech, "site": site, "pen": pen, "load": load,
             "load_pct": dict(LOADS)[load], "rf": rf, "bus": bus, "ftype": ftype, "cls": cls}
        p["key"] = hashlib.sha1(json.dumps(p, sort_keys=True).encode()).hexdigest()[:12]
        cases.append(p)

    def places(pen):
        return ["none"] if pen == 0 else PLACEMENTS

    if pilot:
        for pen in (0, 120):
            for pl in places(pen):
                for bus, ft in FAULTS:
                    add("H1", pl, pen, "puncak_malam", 0, bus, ft, "OCR")
        return cases
    for pen in PENS:
        for pl in places(pen):
            for bus, ft in FAULTS:
                for load, _ in LOADS:
                    add("H1", pl, pen, load, 0, bus, ft, "OCR")
                for rf in RFS[1:]:
                    add("H2", pl, pen, "puncak_malam", rf, bus, ft, "OCR")
    for cls in ("DOCR", "DIST", "DIFF"):
        for pen in (0, 40, 80, 120):
            for pl in places(pen):
                for bus, ft in FAULTS:
                    add("E", pl, pen, "puncak_malam", 0, bus, ft, cls)
    for cls in ("OCR", "DOCR"):
        for pen in (60, 90, 120):
            for site in ISL_SITES:
                for bus, ft in FAULTS:
                    add("I", f"ISL@{site}", pen, "min_siang", 0, bus, ft, cls)
    return cases


# ------------------------------------------------------------------ worker
_S = None


def _init():
    global _S
    with open(os.path.join(ROOT, "cache", "settings.pkl"), "rb") as f:
        _S = pickle.load(f)[0]


def _wrap(a):
    return float((a + 180.0) % 360.0 - 180.0)


def run_case(p):
    from engine.sim import Simulator
    from engine.hunter import analyze
    t0 = time.time()
    sc = scenario(p["fleet"], p["pen"], p["load"], p["rf"], p["bus"], p["ftype"], p["cls"])
    sim = Simulator(copy.deepcopy(sc), _S).run()
    return record(p, sc, sim, analyze(sim), t0)


def post_matlab_case(p, cfgfile, matfile):
    """Turn one MATLAB result file into a case record (runs in a Python worker process)."""
    import scipy.io
    from engine.sim import Simulator
    from engine.hunter import analyze
    from engine.matlab_bridge import load_results as load_matlab
    t0 = time.time()
    sc = scenario(p["fleet"], p["pen"], p["load"], p["rf"], p["bus"], p["ftype"], p["cls"])
    with open(cfgfile) as f:
        cfg = json.load(f)
    mat = scipy.io.loadmat(matfile, squeeze_me=True, struct_as_record=False)
    sim = load_matlab(Simulator, sc, _S, cfg, mat)
    r = record(p, sc, sim, analyze(sim), t0)
    r["engine"] = "matlab"
    r["replay_mismatch"] = int(sim.replay_mismatch)
    r["matlab_wall"] = round(float(np.asarray(mat.get("wall", 0.0))), 2)
    for fn in (cfgfile, matfile):
        try:
            os.remove(fn)
        except OSError:
            pass
    return r


def record(p, sc, sim, hunt, t0):
    dt, f0 = sim.dt, sim.f0
    t = sim.t
    # evaluation window: one cycle after inception until the first breaker opens (max 250 ms)
    opens = []
    for j in range(len(sim.ieds)):
        c = sim.cb_t[:, j]
        if c[0] and not c.all():
            opens.append(float(t[int(np.argmax(~c))]))
    opens = [x for x in opens if x > T_ON]
    t_end = min(min(opens) if opens else T_ON + 0.25, T_ON + 0.25)
    w0 = int(round((T_ON + 1.0 / f0 + 2 * dt) / dt))
    w1 = max(int(round(t_end / dt)) - 1, w0 + 2)
    hf = hunt["faults"][0] if hunt["faults"] else {}
    upstream = set(hf.get("upstream", []))
    ph = 0                                      # faulted phase used for angles (phase A in every case)
    ieds = {}
    rx = {}
    for j, d in enumerate(sim.ieds):
        s = d.s
        I = sim.relay_Imeas[w0:w1 + 1, j]
        V = sim.relay_Vmeas[w0:w1 + 1, j]
        Iabs = np.abs(I)
        Iph = float(np.max(Iabs[:, s["ph_idx"]])) if Iabs.size else 0.0
        I3 = float(np.max(np.abs(np.sum(I, axis=1)))) if I.size else 0.0
        # Angle seen by the quadrature 67P element of each phase (Ia vs Vbc, Ib vs Vca, Ic vs Vab, minus MTA),
        # with the phase current at the same instant (mid-window).
        ang = None
        ang3, i3m = [None, None, None], [0.0, 0.0, 0.0]
        if len(I):
            km = len(I) // 2
            for k in s["ph_idx"]:
                jj, ll = (k + 1) % 3, (k + 2) % 3
                Vpol = V[km, jj] - V[km, ll]
                i3m[k] = round(float(abs(I[km, k])), 2)
                if abs(Vpol) > 0.05 * s["vbase"] * np.sqrt(3) and abs(I[km, k]) > 1e-3:
                    ang3[k] = round(_wrap(np.degrees(np.angle(I[km, k]) - np.angle(Vpol)) - s["mta"]), 1)
            ang = ang3[0]
        # Apparent impedance of the faulted loop (sampled every 2 ms).
        if d.id in ("A1", "A2", "A3") and len(I):
            loop = "AG" if p["ftype"] == "SLG" else "AB"
            pts = []
            for k in range(0, len(I), 2):
                z = d.loops(I[k], V[k]).get(loop)
                if z is not None and np.isfinite(z) and abs(z) < 400:
                    pts.append([round(float(z.real), 3), round(float(z.imag), 3)])
            rx[d.id] = pts
        ieds[d.id] = {
            "cls": d.cls, "tripped": bool(d.tripped), "elem": d.trip_elem,
            "t_trip": None if not d.tripped else round(float(d.trip_time) - T_ON, 4),
            "Iph": round(Iph, 2), "I3I0": round(I3, 2), "ang": ang, "ang3": ang3, "i3m": i3m,
            "fwd": d.id in upstream,
            "pu51P": s["51P_pu"], "pu51N": s.get("51N_pu"), "tms51P": s["51P_tms"], "tms51N": s["51N_tms"],
            "zreach": [float(z) for z in s["zreach"]],
        }
    counts, conf = dict(hunt["counts"]), dict(hunt["confusion"])
    findings = [{"code": f["code"], "ied": f["ied"], "t": f["t"], "title": f["title"]} for f in hunt["findings"]]
    # A relay that trips before the fault is applied is a nuisance trip; once it has opened, the
    # later fault classification is meaningless, so the case is recorded as NT only.
    pre = [d for d in sim.ieds if d.tripped and d.trip_time < T_ON]
    if pre:
        counts = {c: 0 for c in counts}
        counts["NT"] = len(pre)
        findings = [{"code": "NT", "ied": d.id, "t": float(d.trip_time),
                     "title": f"{d.id} tripped before the fault ({d.trip_elem}); the DER output is seen as an internal fault"} for d in pre]
        conf = {"TP": 0, "TN": len(sim.ieds) - len(pre), "FP": len(pre), "FN": 0}
    return {
        **p,
        "wall": round(time.time() - t0, 2),
        "counts": counts, "confusion": conf, "prefault_trip": [d.id for d in pre],
        "dependability": hunt["dependability"], "security": hunt["security"],
        "findings": findings,
        "primary": hf.get("primary"), "backup": hf.get("backup"), "If": round(float(hf.get("If_A", 0)), 1),
        "ieds": ieds, "rx": rx,
        "der_kva": sum(u["kva"] for u in sc["der"]["units"]),
    }


def _clean(o):
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def load_results():
    out = {}
    os.makedirs(OUT, exist_ok=True)
    if os.path.exists(JSONL):
        with open(JSONL) as f:
            for line in f:
                try:
                    r = json.loads(line)
                    out[r["key"]] = r
                except Exception:
                    pass
    return out


def export(results):
    rows = list(results.values())
    with open(os.path.join(OUT, "batch_results.json"), "w") as f:
        json.dump({"generated": time.strftime("%Y-%m-%d %H:%M:%S"), "n": len(rows), "t_on": T_ON,
                   "peak_load_kw": PEAK_LOAD_KW, "placements": PLACEMENTS, "isl_sites": ISL_SITES, "runs": rows}, f)
    try:
        import scipy.io
        codes = ["F-1", "F-2", "F-3", "F-4", "F-5", "NT"]
        tab = {
            "campaign": np.array([r["campaign"] for r in rows], dtype=object),
            "der_placement": np.array([r["fleet"] for r in rows], dtype=object),
            "der_tech": np.array([r["tech"] for r in rows], dtype=object),
            "der_site": np.array([r["site"] for r in rows], dtype=object),
            "relay_class": np.array([r["cls"] for r in rows], dtype=object),
            "fault_bus": np.array([r["bus"] for r in rows], dtype=object),
            "fault_type": np.array([r["ftype"] for r in rows], dtype=object),
            "der_penetration_pct": np.array([r["pen"] for r in rows], float),
            "load_pct": np.array([r["load_pct"] for r in rows], float),
            "rf_ohm": np.array([r["rf"] for r in rows], float),
            "fault_current_A": np.array([r["If"] for r in rows], float),
            "counts": np.array([[r["counts"].get(c, 0) for c in codes] for r in rows], float),
            "confusion_TP_TN_FP_FN": np.array([[r["confusion"][k] for k in ("TP", "TN", "FP", "FN")] for r in rows], float),
            "code_names": np.array(codes, dtype=object),
        }
        for iid in ("A1", "A2", "A3", "L1", "B1"):
            tab[f"{iid}_t_trip"] = np.array([np.nan if r["ieds"][iid]["t_trip"] is None else r["ieds"][iid]["t_trip"] for r in rows], float)
            tab[f"{iid}_Iph_A"] = np.array([r["ieds"][iid]["Iph"] for r in rows], float)
            tab[f"{iid}_3I0_A"] = np.array([r["ieds"][iid]["I3I0"] for r in rows], float)
        scipy.io.savemat(os.path.join(OUT, "batch_results.mat"), {"batch": tab}, do_compression=True)
    except Exception:
        traceback.print_exc()


def structure_of(c):
    """Cases with the same DER placement and fault share one Simscape model structure."""
    return (c["fleet"], c["bus"], c["ftype"])


def run_matlab(todo, done, workers, f, t0):
    """Simulate with the MATLAB Simulink engine (parfor), post-process in Python worker processes."""
    import matlab.engine
    from engine.matlab_bridge import export_config, MATLAB_DIR
    io_dir = os.path.join(OUT, "io")
    os.makedirs(io_dir, exist_ok=True)
    todo = sorted(todo, key=structure_of)
    print(f"[batch] starting MATLAB and a pool of {workers} workers (first start takes a minute or two)", flush=True)
    eng = matlab.engine.start_matlab("-nodesktop -nosplash")
    eng.addpath(MATLAB_DIR, nargout=0)
    chunk = max(workers * 15, 30)
    n_done = [0]
    post = ProcessPoolExecutor(max_workers=2, initializer=_init)

    def collect(futs):
        for fu in as_completed(futs):
            c = futs[fu]
            n_done[0] += 1
            try:
                r = _clean(fu.result())
                f.write(json.dumps(r) + "\n"); f.flush()
                done[r["key"]] = r
                hits = ",".join(k for k, v in r["counts"].items() if v) or "ok"
                msg = (f"{c['campaign']} {c['fleet']} {c['cls']} pen={c['pen']} load={c['load_pct']} rf={c['rf']} "
                       f"{c['bus']} {c['ftype']}: {hits}" + (f" (replay mismatch {r['replay_mismatch']})" if r["replay_mismatch"] else ""))
            except Exception as e:
                msg = f"FAILED {c['key']}: {e}"
            el = time.time() - t0
            print(f"[{n_done[0]}/{len(todo)}] {el/60:5.1f} min, eta {el/n_done[0]*(len(todo)-n_done[0])/60:5.1f} min  {msg}", flush=True)

    pending = {}
    for i0 in range(0, len(todo), chunk):
        part = todo[i0:i0 + chunk]
        items = []
        for c in part:
            sc = scenario(c["fleet"], c["pen"], c["load"], c["rf"], c["bus"], c["ftype"], c["cls"])
            cfg, _ = export_config(sc, _S)
            cf, of = os.path.join(io_dir, c["key"] + ".json"), os.path.join(io_dir, c["key"] + ".mat")
            with open(cf, "w") as g:
                json.dump(cfg, g)
            items.append({"cfg": cf, "out": of})
        lst = os.path.join(io_dir, f"list_{i0}.json")
        with open(lst, "w") as g:
            json.dump(items, g)
        job = eng.sr34_batch(lst, float(workers), nargout=0, background=True)
        if pending:                                      # post-process the previous chunk meanwhile
            collect(pending)
        job.result()
        pending = {}
        for c, it in zip(part, items):
            if os.path.exists(it["out"]):
                pending[post.submit(post_matlab_case, c, it["cfg"], it["out"])] = c
            else:
                err = it["out"] + ".err"
                why = open(err).read()[:300] if os.path.exists(err) else "no output"
                n_done[0] += 1
                print(f"[{n_done[0]}/{len(todo)}] FAILED in MATLAB {c['key']}: {why}", flush=True)
        os.remove(lst)
    if pending:
        collect(pending)
    post.shutdown()
    eng.quit()


def main():
    global OUT, JSONL
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", action="store_true")
    ap.add_argument("--workers", type=int, default=max((os.cpu_count() or 2) - 1, 1))
    ap.add_argument("--engine", choices=["python", "matlab"], default="python")
    ap.add_argument("--outdir", default=None, help="output folder (default: batch, or batch_matlab for --engine matlab)")
    a = ap.parse_args()
    OUT = os.path.join(ROOT, a.outdir or ("batch_matlab" if a.engine == "matlab" else "batch"))
    JSONL = os.path.join(OUT, "results.jsonl")
    os.makedirs(OUT, exist_ok=True)
    if not os.path.exists(os.path.join(ROOT, "cache", "settings.pkl")):
        sys.exit("cache/settings.pkl not found. Start server.py once to compute the baseline settings.")
    cases = build_cases(a.pilot)
    done = load_results()
    todo = [c for c in cases if c["key"] not in done]
    if a.engine == "matlab" and not any(x.startswith("--workers") for x in sys.argv):
        # one Simulink + Simscape session needs about 1.5 to 2 GB of RAM; two workers is the safe
        # default on an 8 GB machine (use --workers 1 for a serial run in a single MATLAB session)
        a.workers = 2
    print(f"[batch] {len(cases)} cases, {len(cases) - len(todo)} already done, {len(todo)} to run on {a.workers} "
          f"workers with the {a.engine} engine", flush=True)
    t0 = time.time()
    n = 0
    if a.engine == "matlab":
        _init()
        with open(JSONL, "a") as f:
            run_matlab(todo, done, a.workers, f, t0)
        export({k: v for k, v in done.items() if k in {c['key'] for c in cases} or not a.pilot})
        print(f"[batch] finished in {(time.time()-t0)/60:.1f} min. Results in {OUT}", flush=True)
        return
    with ProcessPoolExecutor(max_workers=a.workers, initializer=_init) as ex, open(JSONL, "a") as f:
        futs = {ex.submit(run_case, c): c for c in todo}
        for fu in as_completed(futs):
            c = futs[fu]
            n += 1
            try:
                r = _clean(fu.result())
                f.write(json.dumps(r) + "\n"); f.flush()
                done[r["key"]] = r
                hits = ",".join(k for k, v in r["counts"].items() if v) or "ok"
                msg = f"{c['campaign']} {c['fleet']} {c['cls']} pen={c['pen']} load={c['load_pct']} rf={c['rf']} {c['bus']} {c['ftype']}: {hits}"
            except Exception as e:
                msg = f"FAILED {c}: {e}"
            el = time.time() - t0
            print(f"[{n}/{len(todo)}] {el/60:5.1f} min, eta {el/n*(len(todo)-n)/60:5.1f} min  {msg}", flush=True)
    export({k: v for k, v in done.items() if k in {c['key'] for c in cases} or not a.pilot})
    print(f"[batch] finished in {(time.time()-t0)/60:.1f} min. Results in {OUT}", flush=True)


if __name__ == "__main__":
    main()
