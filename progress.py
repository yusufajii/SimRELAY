#!/usr/bin/env python3
"""
SimRELAY: progress of a running (or finished) Proof of Urgencies campaign.

    python progress.py              every campaign folder, once
    python progress.py --watch      refresh every 10 s (Ctrl+C to stop)
    python progress.py PoU-pilot    one campaign folder only

Reads only the campaign folder (campaign.json, results.jsonl, runs/, models/, io/), so it can run
at any time next to batch.py without disturbing it.
"""
from __future__ import annotations
import argparse
import glob
import json
import os
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
CAMPAIGNS = os.path.join(ROOT, "campaigns")


def fmt_min(m):
    if m is None:
        return "unknown"
    h, mm = divmod(int(round(m)), 60)
    return f"{h} h {mm:02d} min" if h else f"{mm} min"


def report(cdir):
    name = os.path.basename(cdir)
    cj = os.path.join(cdir, "campaign.json")
    camp = json.load(open(cj)) if os.path.exists(cj) else {}
    total = camp.get("n_cases")
    rows = []
    p = os.path.join(cdir, "results.jsonl")
    if os.path.exists(p):
        with open(p) as f:
            for line in f:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    pass
    done = len({r["key"] for r in rows})
    # time each stored run was written (result.json.gz), to measure the speed
    stamps = sorted(os.path.getmtime(f) for f in glob.glob(os.path.join(cdir, "runs", "*", "result.json.gz")))
    failed = len(glob.glob(os.path.join(cdir, "io", "*.err")))
    # simulated by MATLAB, waiting for Python post-processing (batch.py sends chunks of 30 cases)
    waiting = len(glob.glob(os.path.join(cdir, "io", "*.mat")))
    cfgs = [f for f in glob.glob(os.path.join(cdir, "io", "*.json")) if not os.path.basename(f).startswith("list_")]
    queued = len(cfgs) - waiting - failed
    topo = len(glob.glob(os.path.join(cdir, "models", "*.slx")))
    hits = {}
    for r in rows:
        for c, n in (r.get("counts") or {}).items():
            if n:
                hits[c] = hits.get(c, 0) + 1
    mism = sum(1 for r in rows if r.get("replay_mismatch"))
    # Speed over the whole session (results arrive in bursts of one chunk, so a short window misleads).
    # Cases simulated by MATLAB but not yet post-processed count as progress too.
    rate = None
    start = (camp.get("resumed") or [None])[-1] or camp.get("started")
    if start and not camp.get("finished"):
        try:
            mins = (time.time() - time.mktime(time.strptime(start, "%Y-%m-%d %H:%M:%S"))) / 60
            new_runs = sum(1 for s in stamps if s >= time.time() - mins * 60) + waiting
            rate = new_runs / mins if mins > 1 and new_runs else None
        except ValueError:
            rate = None
    idle = (time.time() - stamps[-1]) / 60 if stamps else None
    pct = 100.0 * done / total if total else None

    print(f"\n{camp.get('title', name)}  [{name}]")
    if total:
        bar = int(round(40 * done / total))
        print(f"  [{'#' * bar}{'.' * (40 - bar)}] {done} of {total} cases ({pct:.1f} %)")
    else:
        print(f"  {done} cases done")
    if waiting or queued > 0:
        print(f"  In MATLAB    {waiting} simulated and waiting for post-processing, {max(queued, 0)} still in the current chunk")
    print(f"  Started      {camp.get('started', 'unknown')}" + (f", finished {camp['finished']}" if camp.get("finished") else ""))
    if rate:
        left = (total - done - waiting) if total else 0
        print(f"  Speed        {rate:.2f} cases per minute since the start of this session")
        if total and left > 0:
            eta = time.strftime("%H:%M", time.localtime(time.time() + left / rate * 60))
            print(f"  Remaining    {left} cases, about {fmt_min(left / rate)} (done around {eta})")
    if idle is not None and not camp.get("finished"):
        print(f"  Last result  {idle:.1f} min ago (results are written once per chunk of 30 cases)"
              + ("  (no new result for a while: is batch.py still running?)" if idle > 20 else ""))
    print(f"  Topologies   {topo} Simulink models stored")
    print(f"  Failed       {failed} cases (see io/*.err)" if failed else "  Failed       none")
    print(f"  Replay       {mism} cases with a relay replay mismatch" if mism else "  Replay       no relay replay mismatch")
    print("  Findings     " + (", ".join(f"{c}: {n} cases" for c, n in sorted(hits.items())) if hits else "none yet"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name", nargs="?", help="campaign folder name (default: all)")
    ap.add_argument("--watch", action="store_true", help="refresh every 10 s")
    a = ap.parse_args()
    while True:
        dirs = [os.path.join(CAMPAIGNS, a.name)] if a.name else sorted(
            d for d in glob.glob(os.path.join(CAMPAIGNS, "*")) if os.path.isdir(d))
        if a.watch:
            os.system("cls" if os.name == "nt" else "clear")
            print(time.strftime("SimRELAY campaign progress, %H:%M:%S (Ctrl+C to stop)"))
        if not dirs:
            print("No campaign folder yet (campaigns/).")
        for d in dirs:
            report(d)
        if not a.watch:
            break
        try:
            time.sleep(10)
        except KeyboardInterrupt:
            break


if __name__ == "__main__":
    main()
