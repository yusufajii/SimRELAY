"""
SimRELAY: storage of the Proof of Urgencies campaign (PoU), shared by batch.py and server.py.

A campaign folder (campaigns/<name>/, outside cache/ so it is never wiped when the engine changes):

    campaign.json        definition, MATLAB fingerprint, frozen relay settings summary, dates, workers
    results.jsonl        one Fault Hunter summary per case (same format as batch/results.jsonl,
                         plus run_id and topology)
    models/T001.slx ...  one Simulink model per identical network topology
    models/index.json    structure_key -> {"id": "T001", "fleet", "bus", "ftype", "runs": [...]}
    runs/PoU-0001/       scenario.json, cfg.json.gz, result.json.gz, wave.npz, wave.json,
                         sim.mat (raw Simulink output), topology.txt

Run IDs follow the order of the full campaign definition (batch.build_cases), so a case has the
same ID in the pilot and in the full sweep.
"""
from __future__ import annotations
import glob
import gzip
import hashlib
import json
import os
import threading
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
CAMPAIGNS = os.path.join(ROOT, "campaigns")
NAME = "PoU-TA-Proteksi-Adaptif"
PILOT_NAME = "PoU-pilot"
TITLE = "Proof of Urgencies TA Proteksi Adaptif"
RUN_PREFIX = "PoU-"

# MATLAB files that never change simulation results (editor and storage only).
_ML_NOT_RESULTS = ("sr34_open.m", "sr34_editor.m", "sr34_store_model.m")


def engine_fingerprint():
    h = hashlib.sha1()
    for p in sorted(glob.glob(os.path.join(ROOT, "engine", "*.py"))):
        if os.path.basename(p) in ("layout.py", "matlab_bridge.py"):   # display / MATLAB-only code
            continue
        with open(p, "rb") as f:
            h.update(f.read())
    return h.hexdigest()[:16]


def matlab_fingerprint(base=None):
    """MATLAB engine results also depend on matlab/*.m and the bridge."""
    h = hashlib.sha1((base or engine_fingerprint()).encode())
    for p in sorted(glob.glob(os.path.join(ROOT, "matlab", "*.m"))) + [os.path.join(ROOT, "engine", "matlab_bridge.py")]:
        if os.path.basename(p) in _ML_NOT_RESULTS:
            continue
        with open(p, "rb") as f:
            h.update(f.read())
    return h.hexdigest()[:16]


def run_label(n):
    return f"{RUN_PREFIX}{n:04d}"


def write_json(path, obj, gz=False, indent=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    data = json.dumps(obj, indent=indent, allow_nan=False, default=str).encode()
    if gz:
        with gzip.open(tmp, "wb", compresslevel=6) as f:
            f.write(data)
    else:
        with open(tmp, "wb") as f:
            f.write(data)
    os.replace(tmp, path)


def read_json(path):
    if path.endswith(".gz"):
        with gzip.open(path, "rb") as f:
            return json.loads(f.read())
    with open(path, "rb") as f:
        return json.loads(f.read())


# ------------------------------------------------------------------ topologies
class Topologies:
    """structure_key -> T### for one campaign folder (assigned in the order topologies appear)."""

    def __init__(self, folder):
        self.folder = os.path.join(folder, "models")
        self.path = os.path.join(self.folder, "index.json")
        self.idx = read_json(self.path) if os.path.exists(self.path) else {}

    def get(self, structure_key, case):
        t = self.idx.get(structure_key)
        if t is None:
            t = {"id": f"T{len(self.idx) + 1:03d}", "fleet": case["fleet"], "bus": case["bus"],
                 "ftype": case["ftype"], "runs": []}
            self.idx[structure_key] = t
        if case["run_id"] not in t["runs"]:
            t["runs"].append(case["run_id"])
        return t["id"]

    def slx(self, tid):
        return os.path.join(self.folder, tid + ".slx")

    def save(self):
        write_json(self.path, self.idx, indent=1)


# ------------------------------------------------------------------ one stored run
def save_run(folder, sc, cfg, sim, hunt, record, matfile, topo_id, topo_slx):
    """Store everything about one campaign case (runs in a Python post-processing worker)."""
    from engine.results import pack, WaveSource
    os.makedirs(folder, exist_ok=True)
    payload = pack(sim, hunt, record["key"])
    payload["engine"] = "matlab"
    payload["engine_label"] = "MATLAB Simulink (Simscape Electrical, phasor)"
    payload["origin"] = "campaign"
    payload["campaign_run"] = record["run_id"]
    payload["scenario"]["name"] = f"{record['run_id']} ({record['campaign']})"
    write_json(os.path.join(folder, "result.json.gz"), payload, gz=True)
    write_json(os.path.join(folder, "scenario.json"), sc, indent=1)
    write_json(os.path.join(folder, "cfg.json.gz"), cfg, gz=True)
    WaveSource.from_sim(sim).save(folder)
    os.replace(matfile, os.path.join(folder, "sim.mat"))
    with open(os.path.join(folder, "topology.txt"), "w") as f:
        f.write(f"{topo_id}\n{os.path.relpath(topo_slx, os.path.dirname(os.path.dirname(folder)))}\n"
                f"structure_key {cfg['structure_key']}\n")


# ------------------------------------------------------------------ server side
def run_key(name, case_key):
    """Key of a campaign run in the app (16 hex digits, unique across campaign folders)."""
    return hashlib.sha1(f"{name}:{case_key}".encode()).hexdigest()[:16]


class Store:
    """Read-only view of every campaign folder for the web server (reloaded when files change)."""

    def __init__(self):
        self.lock = threading.Lock()
        self._sig = None
        self.camps = {}        # name -> campaign.json
        self.rows = {}         # key -> catalogue row
        self.where = {}        # key -> (campaign name, run folder)

    def _signature(self):
        sig = []
        for p in sorted(glob.glob(os.path.join(CAMPAIGNS, "*", "results.jsonl"))):
            st = os.stat(p)
            sig.append((p, st.st_mtime_ns, st.st_size))
        return tuple(sig)

    def refresh(self):
        with self.lock:
            sig = self._signature()
            if sig == self._sig:
                return
            camps, rows, where = {}, {}, {}
            for p, _, _ in sig:
                cdir = os.path.dirname(p)
                name = os.path.basename(cdir)
                cj = os.path.join(cdir, "campaign.json")
                camp = read_json(cj) if os.path.exists(cj) else {"name": name, "title": name}
                camps[name] = camp
                with open(p) as f:
                    for line in f:
                        try:
                            r = json.loads(line)
                        except Exception:
                            continue
                        rid = r.get("run_id")
                        if not rid:
                            continue
                        rdir = os.path.join(cdir, "runs", rid)
                        if not os.path.exists(os.path.join(rdir, "result.json.gz")):
                            continue
                        # The case key is the same in every campaign folder (pilot, full sweep), so the
                        # app addresses a campaign run by a key that also contains the folder name.
                        k = run_key(name, r["key"])
                        rows[k] = self._row(r, camp, name, rdir, k)
                        where[k] = (name, rdir)
            self.camps, self.rows, self.where, self._sig = camps, rows, where, sig

    @staticmethod
    def _row(r, camp, name, rdir, key):
        load = {"min_siang": "Minimum (day)", "menengah": "Medium", "puncak_malam": "Peak (night)"}
        der = []
        if r["pen"] > 0 and r["fleet"] != "none":
            tech, bus = r["fleet"].split("@")
            kva = 1769.0 * r["pen"] / 100
            if tech == "ISL":
                der = [{"type": "IBR-GFM", "bus": "824", "kva": round(kva * 0.6)},
                       {"type": "IBR-GFL", "bus": bus, "kva": round(kva * 0.4)}]
            else:
                der = [{"type": tech, "bus": bus, "kva": round(kva)}]
        try:
            created = time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(os.path.join(rdir, "result.json.gz"))))
        except OSError:
            created = ""
        return {
            "key": key, "case_key": r["key"], "run_id": r["run_id"], "run_no": 0, "source": "campaign",
            "campaign": name, "campaign_title": camp.get("title", name), "part": r["campaign"],
            "name": f"{r['run_id']} ({r['campaign']})", "engine": "matlab", "created": created,
            "der": der, "grid": "island" if r["fleet"].startswith("ISL") else "grid",
            "load": load.get(r["load"], r["load"]), "pen": r["pen"], "rf": r["rf"],
            "faults": [{"type": r["ftype"], "phases": "abc" if r["ftype"] == "3PH" else "a", "at": r["bus"], "rf": r["rf"]}],
            "relay": r["cls"], "relay_overrides": {},
            "counts": {c: n for c, n in (r.get("counts") or {}).items() if n},
            "dependability": r.get("dependability"), "security": r.get("security"),
            "topology": r.get("topology"), "labels": [], "notes": "",
        }

    def folder(self, key):
        self.refresh()
        w = self.where.get(key)
        return w[1] if w else None

    def catalogue_rows(self):
        self.refresh()
        return [dict(r) for r in self.rows.values()]

    def campaign_dir(self, key):
        self.refresh()
        w = self.where.get(key)
        return os.path.join(CAMPAIGNS, w[0]) if w else None


STORE = Store()


def topology_of(run_dir):
    """(topology id, absolute .slx path) of a stored campaign run."""
    with open(os.path.join(run_dir, "topology.txt")) as f:
        lines = f.read().splitlines()
    camp_dir = os.path.dirname(os.path.dirname(run_dir))
    return lines[0], os.path.normpath(os.path.join(camp_dir, lines[1]))
