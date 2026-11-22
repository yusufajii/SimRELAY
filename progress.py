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


# ------------------------------------------------------------------ live view
SPIN = "|/-\\"


def _mtimes(pattern):
    out = []
    for f in glob.glob(pattern):
        try:
            out.append(os.path.getmtime(f))
        except OSError:
            pass
    return out


def _bar(parts, width=50):
    """parts: [(count, char)], scaled to width with the remainder as '░'."""
    total = sum(n for n, _ in parts)
    return "".join(ch * int(round(width * n / total)) for n, ch in parts) if total else ""


def _ram_available_gb():
    if os.name != "nt":
        return None
    import ctypes

    class MS(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    m = MS()
    m.dwLength = ctypes.sizeof(MS)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return m.ullAvailPhys / 2 ** 30, m.ullTotalPhys / 2 ** 30


def _matlab_procs():
    """(count, GB) of MATLAB.exe processes."""
    if os.name != "nt":
        return None
    import subprocess
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq MATLAB.exe", "/FO", "CSV", "/NH"],
                         capture_output=True, text=True).stdout
    n, kb = 0, 0
    for line in out.splitlines():
        cols = [c.strip('"') for c in line.split('","')]
        if len(cols) >= 5 and cols[0].lower().startswith("matlab"):
            n += 1
            kb += int("".join(ch for ch in cols[4] if ch.isdigit()) or 0)
    return n, kb / 2 ** 20


def _pid_alive(pid):
    import subprocess
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
    return str(pid) in out


def _part_keys(camp):
    """Keys of the cases of the part being run (from campaign.json), or None."""
    import re
    starts = [camp.get("started", "")] + list(camp.get("resumed") or [])
    m = re.search(r"\(part (\d+)\)", starts[-1] or "")
    if not m:
        return None, None
    part = int(m.group(1))
    try:
        import sys
        sys.path.insert(0, ROOT)
        import batch
        cases = batch.build_cases(False)
        parts = batch.split_parts(cases, 5)
        keys = {c["key"] for c in cases if c["fleet"] == "none"} | {c["key"] for c in parts[part - 1]}
        return part, keys
    except Exception:
        return part, None


def live(cdir, every=3.0):
    """Full-screen view refreshed every EVERY seconds: per-case bar, current chunk, heartbeat."""
    if os.name == "nt":
        os.system("")                                   # turn on ANSI escape handling in the console
        # QuickEdit off: a click in the window would otherwise start a text selection that freezes the view
        import ctypes
        k = ctypes.windll.kernel32
        h = k.GetStdHandle(-10)
        mode = ctypes.c_uint32()
        if k.GetConsoleMode(h, ctypes.byref(mode)):
            k.SetConsoleMode(h, (mode.value & ~0x0040) | 0x0080)
    try:
        import sys
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    part_cache = {}
    tick = 0
    while True:
        cj = os.path.join(cdir, "campaign.json")
        camp = json.load(open(cj)) if os.path.exists(cj) else {}
        sig = (camp.get("started"), tuple(camp.get("resumed") or []))
        if sig not in part_cache:
            part_cache = {sig: _part_keys(camp)}
        part, pkeys = part_cache[sig]
        pid = None
        keys = set()
        p = os.path.join(cdir, "results.jsonl")
        hits = {}
        if os.path.exists(p):
            with open(p) as f:
                for line in f:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    keys.add(r["key"])
                    for c, n in (r.get("counts") or {}).items():
                        if n:
                            hits[c] = hits.get(c, 0) + 1
        io = os.path.join(cdir, "io")
        mats = glob.glob(os.path.join(io, "*.mat"))
        errs = glob.glob(os.path.join(io, "*.err"))
        cfgs = [f for f in glob.glob(os.path.join(io, "*.json")) if not os.path.basename(f).startswith("list_")]
        waiting = len(mats)
        in_chunk = len(cfgs)
        total_all = 5247
        done_all = len(keys)
        if pkeys:
            total_p, done_p = len(pkeys), len(keys & pkeys)
        else:
            total_p, done_p = camp.get("n_cases") or total_all, done_all
        sim_p = min(waiting, max(total_p - done_p, 0))
        # MATLAB finish times: queued outputs plus stored sim.mat (moved with their time stamps)
        now = time.time()
        sim_t = _mtimes(os.path.join(io, "*.mat")) + _mtimes(os.path.join(cdir, "runs", "*", "sim.mat"))
        recent = [t for t in sim_t if t >= now - 900]
        rate = len(recent) / (min(15.0, (now - min(recent)) / 60) or 1) if len(recent) >= 3 else None
        last_act = max(sim_t + _mtimes(os.path.join(cdir, "models", "*.slx")) +
                       _mtimes(os.path.join(cdir, "logs", "*.log")) + [0])
        idle = (now - last_act) / 60 if last_act else None
        lock = os.path.join(cdir, "sweep.lock")
        pid = None
        if os.path.exists(lock):
            try:
                pid = int(open(lock).read().split()[0])
            except (OSError, ValueError, IndexError):
                pid = None
        ram = _ram_available_gb()
        # process checks cost CPU that the sweep needs: refresh them every 5th view only
        if tick % 5 == 0 or "proc" not in part_cache:
            alive_ = pid is not None and _pid_alive(pid)
            frozen_ = False
            if alive_ and os.name == "nt":
                import subprocess
                out = subprocess.run(["tasklist", "/V", "/FI", "IMAGENAME eq cmd.exe", "/FO", "CSV", "/NH"],
                                     capture_output=True, text=True).stdout
                frozen_ = any("Select SimRELAY Sweep" in ln or "Mark SimRELAY Sweep" in ln for ln in out.splitlines())
            part_cache["proc"] = (alive_, _matlab_procs(), frozen_)
        alive, ml, frozen = part_cache["proc"]
        if frozen:
            state = "PAUSED BY A TEXT SELECTION: click the sweep window and press Esc"
        elif alive and idle is not None and idle > 15:
            state = "STALLED?  no new file for %.0f min" % idle
        elif alive:
            state = "RUNNING"
        else:
            state = "STOPPED  (no sweep process; run 'Jalankan Sweep.bat N' to continue)"
        logs = sorted(glob.glob(os.path.join(cdir, "logs", "part*.log")), key=os.path.getmtime)
        last_case, last_line = "", ""
        if logs:
            try:
                with open(logs[-1], encoding="utf-8", errors="replace") as f:
                    tail = f.readlines()[-40:]
                for ln in reversed(tail):
                    if ln.startswith("[") and "/" in ln.split("]")[0] and not last_case:
                        last_case = ln.strip()
                    if ln.strip() and not last_line:
                        last_line = ln.strip()
            except OSError:
                pass
        lines = []
        spin = SPIN[tick % 4] if alive else " "
        lines.append(f"SimRELAY sweep  {camp.get('title', os.path.basename(cdir))}   {time.strftime('%H:%M:%S')}  {spin}")
        lines.append("")
        lines.append(f"  Status   {state}")
        w = 50
        b = _bar([(done_p, "█"), (sim_p, "▒"), (max(total_p - done_p - sim_p, 0), "░")], w)
        pct = 100.0 * (done_p + sim_p) / total_p if total_p else 0
        lines.append(f"  Part {part or '?'}   [{b}] {pct:5.1f} %")
        lines.append(f"           {done_p} stored, {sim_p} simulated and waiting, {total_p - done_p - sim_p} to go (of {total_p})")
        if in_chunk:
            cb = _bar([(waiting, "▒"), (max(in_chunk - waiting, 0), "░")], 30)
            lines.append(f"  Queue    [{cb}] {waiting} of {in_chunk} queued cases already simulated in MATLAB")
        bo = _bar([(done_all, "█"), (max(total_all - done_all, 0), "░")], w)
        lines.append(f"  Campaign [{bo}] {done_all} of {total_all} ({100.0 * done_all / total_all:.1f} %)")
        lines.append("")
        if rate:
            left = max(total_p - done_p - sim_p, 0)
            eta = time.strftime("%H:%M", time.localtime(now + left / rate * 60)) if left else "now"
            lines.append(f"  Speed    {rate:.2f} cases/min over the last {min(15, int((now - min(recent)) / 60) or 1)} min, "
                         f"part done in about {fmt_min(left / rate)} (around {eta})")
        else:
            lines.append("  Speed    measuring (needs a few simulated cases)")
        lines.append(f"  Activity last file written {idle * 60:.0f} s ago" if idle is not None and idle < 1 else
                     (f"  Activity last file written {idle:.1f} min ago" if idle is not None else "  Activity none yet"))
        if ml:
            lines.append(f"  MATLAB   {ml[0]} processes using {ml[1]:.1f} GB" + ("" if ml[0] else "  (none running)"))
        if ram:
            lines.append(f"  RAM      {ram[0]:.2f} GB available of {ram[1]:.1f} GB" + ("  (low: the PC is paging)" if ram[0] < 0.8 else ""))
        lines.append(f"  Failed   {len(errs)} cases (io/*.err)" if errs else "  Failed   none")
        lines.append("  Findings " + (", ".join(f"{c} {n}" for c, n in sorted(hits.items())) if hits else "none yet"))
        lines.append("")
        lines.append("  Last case  " + (last_case[:110] if last_case else "none yet"))
        if last_line and last_line != last_case:
            lines.append("  Last line  " + last_line[:110])
        lines.append("")
        lines.append("  █ stored   ▒ simulated, waiting for post-processing   ░ to go        Ctrl+C closes this view only")
        print("\x1b[H\x1b[J" + "\n".join(lines), flush=True)
        tick += 1
        try:
            time.sleep(every)
        except KeyboardInterrupt:
            return


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name", nargs="?", help="campaign folder name (default: all)")
    ap.add_argument("--watch", action="store_true", help="refresh every 10 s")
    ap.add_argument("--live", action="store_true",
                    help="live view of one campaign (default: the main campaign), refreshed every 2 s")
    a = ap.parse_args()
    if a.live:
        try:
            live(os.path.join(CAMPAIGNS, a.name or "PoU-TA-Proteksi-Adaptif"))
        except KeyboardInterrupt:
            pass
        return
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
