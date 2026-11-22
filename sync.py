"""
SimRELAY: move campaign results between computers (for example through Google Drive) without
simulating again.

    python sync.py export                 view package of the PoU campaign into sync/
    python sync.py export --raw           also the raw package (sim.mat of every run, Simulink models)
    python sync.py import                 newest package(s) found in sync/ or the Downloads folder
    python sync.py import FILE.zip ...    the given package(s)
    python sync.py list                   packages found, and the campaigns present here

Two packages per export, both plain .zip files with a manifest (_simrelay_manifest.json):

  view  everything the app, postrun.py and report.py read: campaign.json, results.jsonl,
        batch_results.*, logs, models/index.json and every run folder without sim.mat
        (scenario, configuration, Fault Hunter result, waveforms). About 3.6 GB for 5,247 runs.
  raw   runs/*/sim.mat (raw Simulink output) and models/*.slx. Only needed to relabel the runs
        with a newer Fault Hunter or to open a topology in Simulink (needs MATLAB). About 9.5 GB.

Import extracts into campaigns/<name>/ of this project. results.jsonl is written last, so a running
app sees either the old or the new campaign, never half of it. A package never silently replaces
local results that it does not contain: those are kept as results.jsonl.bak-<time> and the import
stops unless --force is given. Paths inside a campaign folder are relative, so any project folder
location works.
"""
from __future__ import annotations
import argparse
import datetime
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
CAMPAIGNS = os.path.join(ROOT, "campaigns")
SYNC_DIR = os.path.join(ROOT, "sync")
DEFAULT = "PoU-TA-Proteksi-Adaptif"
MANIFEST = "_simrelay_manifest.json"
FORMAT = 1
PREFIX = "SimRELAY_"
STORED = (".npz", ".mat", ".gz", ".slx", ".zip", ".png")      # already compressed
SKIP_DIRS = ("io",)                                          # MATLAB queue of a running sweep
SKIP_FILES = ("sweep.lock",)


# ------------------------------------------------------------------ helpers
def _git(*a):
    try:
        return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, timeout=20).stdout.strip()
    except Exception:
        return ""


def _sha1(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _keys(path):
    """Case keys in a results.jsonl (the last line of a key wins, as in batch.py)."""
    out = set()
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                out.add(json.loads(line)["key"])
            except Exception:
                pass
    return out


def _codes():
    try:
        sys.path.insert(0, ROOT)
        from engine.hunter import CODES
        return sorted(CODES)
    except Exception:
        return []


def _gb(n):
    return f"{n / 1e9:.2f} GB"


def _sweep_running(cdir):
    lock = os.path.join(cdir, "sweep.lock")
    if not os.path.exists(lock):
        return False
    try:
        pid = int(open(lock).read().split()[0])
        out = subprocess.run(["tasklist", "/fi", f"PID eq {pid}", "/nh"], capture_output=True, text=True).stdout
        return str(pid) in out
    except Exception:
        return False


class _Progress:
    def __init__(self, total_bytes, label):
        self.total, self.label, self.done, self.t0, self.last = max(total_bytes, 1), label, 0, time.time(), 0

    def add(self, n):
        self.done += n
        now = time.time()
        if now - self.last >= 2 or self.done >= self.total:
            self.last = now
            rate = self.done / max(now - self.t0, 1e-3)
            eta = (self.total - self.done) / max(rate, 1)
            w = 30
            fill = int(w * self.done / self.total)
            print(f"\r  {self.label} [{'#' * fill}{'.' * (w - fill)}] {100 * self.done / self.total:5.1f}%  "
                  f"{_gb(self.done)} of {_gb(self.total)}  {rate / 1e6:5.1f} MB/s  {eta / 60:4.1f} min left ",
                  end="", flush=True)

    def end(self):
        print(f"\r  {self.label}: {_gb(self.done)} in {(time.time() - self.t0) / 60:.1f} min" + " " * 50, flush=True)


# ------------------------------------------------------------------ export
def _files(cdir, kind):
    """(absolute path, path inside the campaign folder) of one package kind."""
    out = []
    for dp, dns, fns in os.walk(cdir):
        rel_dir = os.path.relpath(dp, cdir)
        top = rel_dir.split(os.sep)[0]
        if top in SKIP_DIRS:
            dns[:] = []
            continue
        for fn in fns:
            if fn in SKIP_FILES or fn.endswith(".tmp") or ".bak-" in fn:
                continue
            rel = os.path.normpath(os.path.join(rel_dir, fn)).replace(os.sep, "/")
            raw = (top == "runs" and fn == "sim.mat") or (top == "models" and fn.endswith(".slx"))
            if raw == (kind == "raw"):
                out.append((os.path.join(dp, fn), rel))
    # results.jsonl last, so an interrupted import never shows rows without their run folders
    out.sort(key=lambda x: (x[1] == "results.jsonl", x[1]))
    return out


def export(name, raw, out_dir):
    cdir = os.path.join(CAMPAIGNS, name)
    res = os.path.join(cdir, "results.jsonl")
    if not os.path.exists(res):
        sys.exit(f"Campaign {name} not found in {CAMPAIGNS}.")
    if _sweep_running(cdir):
        sys.exit("A sweep is still writing to this campaign. Export after it has finished.")
    os.makedirs(out_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M")
    camp = json.load(open(os.path.join(cdir, "campaign.json"))) if os.path.exists(os.path.join(cdir, "campaign.json")) else {}
    keys = _keys(res)
    base = {
        "format": FORMAT, "campaign": name, "title": camp.get("title", name), "exported": time.strftime("%Y-%m-%d %H:%M:%S"),
        "stamp": stamp, "n_cases": len(keys), "results_sha1": _sha1(res),
        "code_commit": _git("rev-parse", "HEAD"), "code_branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "code_uncommitted": [l for l in _git("status", "--short").splitlines() if l.strip()],
        "fault_codes": _codes(), "engine_fp": camp.get("engine_fp"), "matlab_fp": camp.get("matlab_fp"),
    }
    made = []
    for kind in ("view", "raw") if raw else ("view",):
        files = _files(cdir, kind)
        total = sum(os.path.getsize(p) for p, _ in files)
        zpath = os.path.join(out_dir, f"{PREFIX}{name}_{kind}_{stamp}.zip")
        print(f"[sync] {kind} package: {len(files):,} files, {_gb(total)}")
        man = dict(base, kind=kind, n_files=len(files), bytes=total)
        pr = _Progress(total, kind)
        tmp = zpath + ".part"
        with zipfile.ZipFile(tmp, "w", allowZip64=True) as z:
            z.writestr(MANIFEST, json.dumps(man, indent=1))
            for p, rel in files:
                ct = zipfile.ZIP_STORED if rel.lower().endswith(STORED) else zipfile.ZIP_DEFLATED
                z.write(p, f"{name}/{rel}", compress_type=ct, compresslevel=6 if ct == zipfile.ZIP_DEFLATED else None)
                pr.add(os.path.getsize(p))
        pr.end()
        os.replace(tmp, zpath)
        made.append(zpath)
        print(f"[sync] wrote {zpath} ({_gb(os.path.getsize(zpath))})")
    if base["code_uncommitted"]:
        print("[sync] NOTE: this computer has code changes that are not committed. Commit and push them, "
              "otherwise the other computer may not know every Fault Hunter code (for example F-6).")
    return made


# ------------------------------------------------------------------ import
def _read_manifest(zpath):
    with zipfile.ZipFile(zpath) as z:
        try:
            return json.loads(z.read(MANIFEST))
        except KeyError:
            raise SystemExit(f"{zpath} is not a SimRELAY package (no manifest).")


def find_packages():
    dl = os.path.join(os.path.expanduser("~"), "Downloads")
    seen, out = set(), []
    for d in (SYNC_DIR, dl, ROOT):
        for p in glob.glob(os.path.join(d, f"{PREFIX}*.zip")):
            rp = os.path.realpath(p)
            if rp in seen:
                continue
            seen.add(rp)
            try:
                out.append((p, _read_manifest(p)))
            except (SystemExit, zipfile.BadZipFile, OSError):
                pass
    return sorted(out, key=lambda x: x[1]["stamp"], reverse=True)


def _check_code(man):
    local = set(_codes())
    miss = [c for c in man.get("fault_codes", []) if c not in local]
    if miss:
        print(f"[sync] WARNING: the code here does not know the Fault Hunter codes {', '.join(miss)}. "
              f"Update the code (git pull) so the app shows them.")
    head = _git("rev-parse", "HEAD")
    if man.get("code_commit") and head and head != man["code_commit"]:
        print(f"[sync] note: the package was made with commit {man['code_commit'][:7]}, this folder is on {head[:7]}.")


def import_one(zpath, force=False):
    man = _read_manifest(zpath)
    if man.get("format", 0) > FORMAT:
        sys.exit(f"{zpath} was made by a newer SimRELAY. Update the code first.")
    name, kind = man["campaign"], man["kind"]
    cdir = os.path.join(CAMPAIGNS, name)
    print(f"[sync] {os.path.basename(zpath)}: {kind} package of {name}, {man['n_cases']:,} cases, "
          f"exported {man['exported']}")
    if _sweep_running(cdir):
        sys.exit("A sweep is writing to this campaign here. Import after it has finished.")
    _check_code(man)
    res = os.path.join(cdir, "results.jsonl")
    if kind == "view" and os.path.exists(res):
        if _sha1(res) == man["results_sha1"]:
            print("[sync] the results here are already identical; run folders are checked and completed")
        else:
            with zipfile.ZipFile(zpath) as z:
                theirs = set()
                for line in z.read(f"{name}/results.jsonl").decode("utf-8").splitlines():
                    try:
                        theirs.add(json.loads(line)["key"])
                    except Exception:
                        pass
            extra = _keys(res) - theirs
            if extra and not force:
                sys.exit(f"[sync] {len(extra):,} cases here are not in the package. Nothing was changed. "
                         f"Use --force to replace them anyway.")
            bak = res + ".bak-" + time.strftime("%Y%m%d-%H%M%S")
            shutil.copy2(res, bak)
            print(f"[sync] the previous results here were kept as {os.path.basename(bak)}")
    with zipfile.ZipFile(zpath) as z:
        infos = [i for i in z.infolist() if i.filename != MANIFEST and not i.is_dir()]
        for i in infos:                                   # refuse paths that leave the campaign folder
            parts = i.filename.split("/")
            if parts[0] != name or ".." in parts or i.filename.startswith("/") or ":" in i.filename:
                sys.exit(f"Unexpected path in the package: {i.filename}")
        infos.sort(key=lambda i: i.filename == f"{name}/results.jsonl")
        todo = [i for i in infos if not _same(os.path.join(CAMPAIGNS, *i.filename.split("/")), i)]
        total = sum(i.file_size for i in todo)
        print(f"[sync] {len(todo):,} of {len(infos):,} files to write ({_gb(total)}), the rest are already here")
        pr = _Progress(total, kind)
        for i in todo:
            dst = os.path.join(CAMPAIGNS, *i.filename.split("/"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            tmp = dst + ".tmp"
            with z.open(i) as src, open(tmp, "wb") as f:      # z.open checks the CRC of every file
                shutil.copyfileobj(src, f, 1 << 20)
            os.replace(tmp, dst)
            t = datetime.datetime(*i.date_time).timestamp()
            os.utime(dst, (t, t))
            pr.add(i.file_size)
        pr.end()
    if kind == "view":
        n = len(_keys(res))
        ok = _sha1(res) == man["results_sha1"]
        print(f"[sync] {name}: {n:,} cases here now" + ("" if ok else " (WARNING: results.jsonl differs from the package)"))
    print(f"[sync] done: {cdir}")


def _same(dst, info):
    """A file already present with the same size and time stamp is not written again."""
    try:
        st = os.stat(dst)
    except OSError:
        return False
    t = datetime.datetime(*info.date_time).timestamp()
    return st.st_size == info.file_size and abs(st.st_mtime - t) <= 2


def do_import(paths, force):
    if not paths:
        found = find_packages()
        if not found:
            sys.exit(f"No {PREFIX}*.zip found in {SYNC_DIR} or the Downloads folder.")
        newest = found[0][1]["stamp"]
        paths = [p for p, m in found if m["stamp"] == newest and m["campaign"] == found[0][1]["campaign"]]
        print(f"[sync] newest export {newest}: " + ", ".join(os.path.basename(p) for p in paths))
    paths = sorted(paths, key=lambda p: _read_manifest(p)["kind"] != "view")    # view before raw
    for p in paths:
        import_one(p, force)


def do_list():
    print("Packages found:")
    for p, m in find_packages():
        print(f"  {os.path.basename(p)}  {m['kind']}, {m['n_cases']:,} cases, {_gb(os.path.getsize(p))}, in {os.path.dirname(p)}")
    print("Campaigns here:")
    for r in sorted(glob.glob(os.path.join(CAMPAIGNS, "*", "results.jsonl"))):
        cdir = os.path.dirname(r)
        n_raw = len(glob.glob(os.path.join(cdir, "runs", "*", "sim.mat")))
        print(f"  {os.path.basename(cdir)}: {len(_keys(r)):,} cases, raw sim.mat for {n_raw:,} runs")


def main():
    ap = argparse.ArgumentParser(description="Move SimRELAY campaign results between computers.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("--campaign", default=DEFAULT)
    e.add_argument("--raw", action="store_true", help="also the raw package (sim.mat, Simulink models)")
    e.add_argument("--out", default=SYNC_DIR)
    i = sub.add_parser("import")
    i.add_argument("files", nargs="*")
    i.add_argument("--force", action="store_true", help="replace local results that the package does not contain")
    sub.add_parser("list")
    a = ap.parse_args()
    if a.cmd == "export":
        export(a.campaign, a.raw, a.out)
    elif a.cmd == "import":
        do_import(a.files, a.force)
    else:
        do_list()


if __name__ == "__main__":
    main()
