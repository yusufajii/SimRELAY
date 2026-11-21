#!/usr/bin/env python3
"""
SimRelay IEEE-34: Software-in-the-Loop Proof-of-Urgency Test Bench
Local server (requires only Python 3.9+ and numpy).

    python server.py                 open http://127.0.0.1:8034
    python server.py --port 9000
    python server.py --precompute    simulate every preset into ./cache and exit

Every simulated scenario is stored in ./cache/runs/<key>/ (result.json, wave.npz,
wave.json). The key is a hash of the scenario, so a scenario that has already been
simulated is served straight from disk and never re-run. All presets are
precomputed in the background on startup if they are not already cached.
"""
from __future__ import annotations
import os
# The engine works on small matrices; multithreaded BLAS only adds overhead (about 7x slower)
# and stalls when several simulations run in parallel. Must be set before numpy is imported.
for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")
import argparse
import copy
import glob
import hashlib
import json
import os
import pickle
import sys
import threading
import time
import traceback
import webbrowser
from collections import OrderedDict
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from engine.settings import compute_settings, settings_public          # noqa: E402
from engine.sim import Simulator, Model                                 # noqa: E402
from engine.hunter import analyze, CODES                                # noqa: E402
from engine.results import pack, waveform, save_run, topology, WaveSource  # noqa: E402
from engine.scenarios import PRESETS, DER_BUSES, FAULT_BUSES, LINES_FOR_FAULT  # noqa: E402
from engine.relays import CURVE_LABEL, CLASS_LABEL                      # noqa: E402

CACHE = os.path.join(ROOT, "cache")
RUN_CACHE = os.path.join(CACHE, "runs")


def _engine_fingerprint():
    h = hashlib.sha1()
    for p in sorted(glob.glob(os.path.join(ROOT, "engine", "*.py"))):
        if os.path.basename(p) in ("layout.py", "matlab_bridge.py"):   # display / MATLAB-only code
            continue
        with open(p, "rb") as f:
            h.update(f.read())
    return h.hexdigest()[:16]


FINGERPRINT = _engine_fingerprint()


def _matlab_fingerprint():
    """MATLAB engine results also depend on matlab/*.m and the bridge."""
    h = hashlib.sha1(FINGERPRINT.encode())
    for p in sorted(glob.glob(os.path.join(ROOT, "matlab", "*.m"))) + [os.path.join(ROOT, "engine", "matlab_bridge.py")]:
        with open(p, "rb") as f:
            h.update(f.read())
    return h.hexdigest()[:16]


MATLAB_FP = _matlab_fingerprint()
try:
    import importlib.util
    MATLAB_AVAILABLE = importlib.util.find_spec("matlab.engine") is not None
except Exception:
    MATLAB_AVAILABLE = False


def _load_settings():
    """Baseline relay settings, cached on disk until the engine source changes."""
    os.makedirs(CACHE, exist_ok=True)
    meta_p = os.path.join(CACHE, "engine.json")
    set_p = os.path.join(CACHE, "settings.pkl")
    meta = {}
    if os.path.exists(meta_p):
        with open(meta_p) as f:
            meta = json.load(f)
    if meta.get("fingerprint") == FINGERPRINT and os.path.exists(set_p):
        with open(set_p, "rb") as f:
            print("[SimRelay] Baseline relay settings loaded from cache.")
            return pickle.load(f)
    # Engine changed: every cached run is stale.
    if os.path.isdir(RUN_CACHE):
        import shutil
        shutil.rmtree(RUN_CACHE, ignore_errors=True)
    print("[SimRelay] Computing baseline relay settings (0% DER, peak load)...")
    out = compute_settings()
    with open(set_p, "wb") as f:
        pickle.dump(out, f)
    with open(meta_p, "w") as f:
        json.dump({"fingerprint": FINGERPRINT}, f)
    return out


SETTINGS, COORD_LOG = _load_settings()
print("[SimRelay] Settings frozen.")

WAVES: "OrderedDict[str, WaveSource]" = OrderedDict()
WAVE_LOCK = threading.Lock()
KEY_LOCKS: "dict[str, threading.Lock]" = {}
KEY_LOCKS_LOCK = threading.Lock()
MAX_WAVES = 16


def scenario_key(sc):
    s = {k: v for k, v in sc.items() if k != "name"}
    s["sim"] = {k: v for k, v in (s.get("sim") or {}).items() if k != "save"}
    if s.get("engine", "python") == "python":
        s.pop("engine", None)
    else:
        s["_engine_fp"] = MATLAB_FP
    blob = json.dumps(s, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha1(blob.encode()).hexdigest()[:16]


def _key_lock(key):
    with KEY_LOCKS_LOCK:
        return KEY_LOCKS.setdefault(key, threading.Lock())


def _remember_wave(key, src):
    with WAVE_LOCK:
        WAVES[key] = src
        WAVES.move_to_end(key)
        while len(WAVES) > MAX_WAVES:
            WAVES.popitem(last=False)


def get_result(sc, save_log=False):
    """Return the result.json bytes for a scenario, simulating only on a cache miss."""
    key = scenario_key(sc)
    folder = os.path.join(RUN_CACHE, key)
    res_p = os.path.join(folder, "result.json")
    with _key_lock(key):
        if not os.path.exists(res_p):
            t0 = time.time()
            eng = sc.get("engine", "python")
            if eng == "matlab":
                if not MATLAB_AVAILABLE:
                    raise RuntimeError("MATLAB Engine API for Python is not installed.")
                from engine.matlab_bridge import SESSION
                sim = SESSION.run(copy.deepcopy(sc), SETTINGS)
            else:
                sim = Simulator(copy.deepcopy(sc), SETTINGS).run()
            hunt = analyze(sim)
            payload = pack(sim, hunt, key)
            payload["engine"] = eng
            payload["engine_label"] = ("MATLAB Simulink (Simscape Electrical, phasor)" if eng == "matlab"
                                       else "Python phasor engine")
            src = WaveSource.from_sim(sim)
            src.save(folder)
            tmp = res_p + ".tmp"
            with open(tmp, "w") as f:
                json.dump(payload, f, allow_nan=False, default=str)
            os.replace(tmp, res_p)
            _remember_wave(key, src)
            print(f"[SimRelay] Simulated {sc.get('name') or key} with the {eng} engine in {time.time() - t0:.1f} s (cached as {key}).")
            if save_log:
                try:
                    rid = time.strftime("%Y%m%d-%H%M%S-") + key[:4]
                    save_run(sim, payload, os.path.join(ROOT, "runs", rid))
                except Exception:
                    traceback.print_exc()
        with open(res_p, "rb") as f:
            return f.read()


def get_wave(key):
    with WAVE_LOCK:
        if key in WAVES:
            WAVES.move_to_end(key)
            return WAVES[key]
    folder = os.path.join(RUN_CACHE, key)
    if not os.path.exists(os.path.join(folder, "wave.npz")):
        return None
    src = WaveSource.load(folder)
    _remember_wave(key, src)
    return src


def preset_scenario(pid, engine="python"):
    p = next(x for x in PRESETS if x["id"] == pid)
    sc = copy.deepcopy(p["scenario"])
    sc["name"] = p["name"]
    if engine != "python":
        sc["engine"] = engine
    return sc


def preset_ready(pid):
    return os.path.exists(os.path.join(RUN_CACHE, scenario_key(preset_scenario(pid)), "result.json"))


# ------------------------------------------------------------------ phasors
def phasor_series(src, sig):
    """RMS phasors (fundamental) of a three-phase signal at 5 ms steps, with the angle of the
    rotating reference so the client can also reconstruct the instantaneous fundamental value."""
    import numpy as np
    kind, ident, q = sig.split(":")
    if kind == "bus":
        i = src.bus_index[ident]
        P = np.zeros((len(src.t), 3), complex)
        for k in range(3):
            j = src.bus_sel[i, k]
            if j >= 0:
                P[:, k] = src.V[:, j]
        unit, scale = "kV", 1e-3
    elif kind == "br":
        bi = src.br_index[ident]
        P, unit, scale = src.Ib[:, bi * 3: bi * 3 + 3].astype(complex), "A", 1.0
    elif kind == "ied":
        j = src.ied_ids.index(ident)
        if q == "V":
            P, unit, scale = src.relay_Vmeas[:, j].astype(complex), "kV", 1e-3
        else:
            br = src.ied_br[j]
            P, unit, scale = src.Ib[:, br * 3: br * 3 + 3].astype(complex), "A", 1.0
    elif kind == "der":
        P, unit, scale = src.Ider[:, src.der_ids.index(ident)].astype(complex), "A", 1.0
    elif kind == "fault":
        P, unit, scale = src.Ifault[:, int(ident[1:]) - 1].astype(complex), "A", 1.0
    else:
        raise ValueError(sig)
    step = max(int(round(0.01 / src.dt / 2)), 1)
    ks = np.arange(0, len(src.t), step)
    theta = 2 * np.pi * np.cumsum(src.freq_t.astype(float)) * src.dt
    Q = P[ks] * scale
    return {"unit": unit, "mode": "phasor", "t": np.round(src.t[ks], 5).tolist(),
            "re": [np.round(Q[:, k].real, 4).tolist() for k in range(3)],
            "im": [np.round(Q[:, k].imag, 4).tolist() for k in range(3)],
            "th": np.round(np.mod(theta[ks], 2 * np.pi), 5).tolist()}


# ------------------------------------------------------------------ run catalogue
LABELS_P = os.path.join(ROOT, "runs", "labels.json")          # first format (labels only), migrated once
NOTES_P = os.path.join(ROOT, "runs", "annotations.json")     # {key: {"labels": [...], "notes": "..."}}
INDEX_P = os.path.join(ROOT, "runs", "index.json")           # {key: run number}, assigned once in run order
LABELS_LOCK = threading.Lock()
LOAD_LABEL = {"min_siang": "Minimum (day)", "menengah": "Medium", "puncak_malam": "Peak (night)"}


def _preset_keys():
    out = {}
    for p in PRESETS:
        for eng in ("python", "matlab"):
            out[scenario_key(preset_scenario(p["id"], eng))] = (p, eng)
    return out


def run_id(key, preset=None, engine="python"):
    if preset:
        return f"PRE-{preset['id']}" + ("-ML" if engine == "matlab" else "")
    return "RUN-" + key[:6].upper()


def run_meta(key, pkeys):
    """Small summary of a cached run, kept next to result.json so the catalogue stays fast."""
    folder = os.path.join(RUN_CACHE, key)
    meta_p = os.path.join(folder, "meta.json")
    if os.path.exists(meta_p):
        with open(meta_p) as f:
            return json.load(f)
    with open(os.path.join(folder, "result.json")) as f:
        j = json.load(f)
    sc = j.get("scenario") or {}
    eng = j.get("engine", "python")
    pre = pkeys.get(key)
    preset = pre[0] if pre else None
    H = j.get("hunter") or {}
    rel = sc.get("relays") or {}
    meta = {
        "key": key, "run_id": run_id(key, preset, eng), "source": "preset" if preset else "custom",
        "preset": preset["id"] if preset else None, "code": preset["code"] if preset else None,
        "name": sc.get("name") or (preset["name"] if preset else "Custom scenario"),
        "desc": preset["desc"] if preset else "",
        "engine": eng, "created": time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(os.path.join(folder, "result.json")))),
        "der": [{"type": u.get("type"), "bus": u.get("bus"), "kva": u.get("kva")} for u in (sc.get("der") or {}).get("units", [])],
        "grid": (sc.get("grid") or {}).get("mode", "grid"),
        "load": LOAD_LABEL.get((sc.get("load") or {}).get("level"), (sc.get("load") or {}).get("level")),
        "faults": [{"type": f.get("type"), "phases": f.get("phases"), "at": f.get("bus") or f.get("line"), "rf": f.get("rf", 0)} for f in sc.get("faults", [])],
        "relay": rel.get("default", "OCR"), "relay_overrides": rel.get("classes") or {},
        "counts": {c: n for c, n in (H.get("counts") or {}).items() if n},
        "dependability": H.get("dependability"), "security": H.get("security"),
    }
    with open(meta_p, "w") as f:
        json.dump(meta, f)
    return meta


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=1)
    os.replace(tmp, path)


def load_annotations():
    """Labels and notes per run key. A preset starts with its identifier as label and its name as note."""
    with LABELS_LOCK:
        if os.path.exists(NOTES_P):
            with open(NOTES_P) as f:
                return json.load(f)
        ann = {}
        pk = _preset_keys()
        old = {}
        if os.path.exists(LABELS_P):
            with open(LABELS_P) as f:
                old = json.load(f)
        for key, (p, eng) in pk.items():
            seeded = {"Baseline", f"{p['code']}: {p['name']}"}
            extra = [x for x in old.get(key, []) if x not in seeded]
            ann[key] = {"labels": [f"PRE-{p['id']}" + ("-ML" if eng == "matlab" else "")] + extra, "notes": p["name"] if p["code"] == "OK" else f"{p['code']}: {p['name']}"}
        for key, labs in old.items():
            if key not in ann:
                ann[key] = {"labels": labs, "notes": ""}
        _write_json(NOTES_P, ann)
        return ann


def save_annotation(key, labels=None, notes=None):
    ann = load_annotations()
    with LABELS_LOCK:
        cur = ann.get(key) or {"labels": [], "notes": ""}
        if labels is not None:
            clean = []
            for x in labels:
                x = str(x).strip()[:60]
                if x and x not in clean:
                    clean.append(x)
            cur["labels"] = clean
        if notes is not None:
            cur["notes"] = str(notes).strip()[:300]
        ann[key] = cur
        _write_json(NOTES_P, ann)
        return cur


def run_numbers(metas):
    """Native run number: the order in which runs were produced, fixed once assigned."""
    with LABELS_LOCK:
        idx = {}
        if os.path.exists(INDEX_P):
            with open(INDEX_P) as f:
                idx = json.load(f)
        new = [m for m in metas if m["key"] not in idx]
        if new:
            order = {p["id"]: i for i, p in enumerate(PRESETS)}
            new.sort(key=lambda m: (m["created"], m["source"] != "preset", order.get(m["preset"], 99), m["engine"] != "python"))
            n = max(idx.values(), default=0)
            for m in new:
                n += 1
                idx[m["key"]] = n
            _write_json(INDEX_P, idx)
        return idx


def catalogue():
    pkeys = _preset_keys()
    ann = load_annotations()
    runs = []
    if os.path.isdir(RUN_CACHE):
        for key in os.listdir(RUN_CACHE):
            if not os.path.exists(os.path.join(RUN_CACHE, key, "result.json")):
                continue
            try:
                runs.append(dict(run_meta(key, pkeys)))
            except Exception:
                traceback.print_exc()
    idx = run_numbers(runs)
    for m in runs:
        a = ann.get(m["key"]) or {}
        m["run_no"] = idx[m["key"]]
        m["run_id"] = f"{idx[m['key']]:04d}"
        m["labels"] = a.get("labels", [])
        m["notes"] = a.get("notes", "")
    runs.sort(key=lambda m: m["run_no"], reverse=True)
    return {"runs": runs}


def precompute_all():
    for p in PRESETS:
        if preset_ready(p["id"]):
            continue
        try:
            get_result(preset_scenario(p["id"]))
        except Exception:
            traceback.print_exc()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=os.path.join(ROOT, "web"), **kw)

    def log_message(self, fmt, *args):
        if args and "/api/" in str(args[0]):
            sys.stderr.write("[api] " + (fmt % args) + "\n")

    def end_headers(self):
        if not self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def _bytes(self, body, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._bytes(json.dumps(obj, allow_nan=False, default=str).encode(), code)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        try:
            if u.path == "/api/init":
                model = Model({"faults": []})
                return self._json({
                    "topology": topology(model, SETTINGS),
                    "settings": _jsonable(settings_public(SETTINGS)),
                    "coord_log": _jsonable(COORD_LOG),
                    "presets": PRESETS, "der_buses": DER_BUSES, "fault_buses": FAULT_BUSES,
                    "fault_lines": LINES_FOR_FAULT, "curves": CURVE_LABEL, "classes": CLASS_LABEL,
                    "codes": CODES, "ready": {p["id"]: preset_ready(p["id"]) for p in PRESETS},
                    "matlab_available": MATLAB_AVAILABLE,
                })
            if u.path == "/api/status":
                return self._json({"ready": {p["id"]: preset_ready(p["id"]) for p in PRESETS},
                                   "matlab_available": MATLAB_AVAILABLE})
            if u.path == "/api/preset":
                eng = q.get("engine", ["python"])[0]
                return self._bytes(get_result(preset_scenario(q["id"][0], eng)))
            if u.path == "/api/wave":
                rid = q["id"][0]; sig = q["sig"][0]; mode = q.get("mode", ["inst"])[0]
                src = get_wave(rid)
                if src is None:
                    return self._json({"error": "Run data not found in cache. Please run the scenario again."}, 404)
                return self._json(phasor_series(src, sig) if mode == "phasor" else waveform(src, sig, mode))
            if u.path == "/api/catalog":
                return self._json(catalogue())
            if u.path == "/api/result":
                key = q["key"][0]
                if not all(c in "0123456789abcdef" for c in key):
                    return self._json({"error": "invalid key"}, 400)
                res_p = os.path.join(RUN_CACHE, key, "result.json")
                if not os.path.exists(res_p):
                    return self._json({"error": "This run is no longer in the cache."}, 404)
                with open(res_p, "rb") as f:
                    return self._bytes(f.read())
            if u.path == "/api/runs":
                d = os.path.join(ROOT, "runs")
                items = sorted(os.listdir(d)) if os.path.isdir(d) else []
                return self._json({"runs": items[-50:]})
            if u.path.startswith("/batch/"):
                return self._batch_file(u.path[len("/batch/"):])
        except Exception as e:
            traceback.print_exc()
            return self._json({"error": str(e)}, 500)
        return super().do_GET()

    BATCH_TYPES = {".png": "image/png", ".pdf": "application/pdf", ".json": "application/json",
                   ".csv": "text/csv", ".mat": "application/octet-stream"}

    def _batch_file(self, rel):
        """Serve post-run outputs (figures, tables, .mat) from ./batch."""
        base = os.path.realpath(os.path.join(ROOT, "batch"))
        path = os.path.realpath(os.path.join(base, rel))
        ext = os.path.splitext(path)[1].lower()
        if not path.startswith(base + os.sep) or ext not in self.BATCH_TYPES or not os.path.isfile(path):
            return self._json({"error": "not found"}, 404)
        with open(path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", self.BATCH_TYPES[ext])
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        u = urlparse(self.path)
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        try:
            if u.path == "/api/run":
                save = (body.get("sim") or {}).get("save", True)
                return self._bytes(get_result(body, save_log=save))
            if u.path == "/api/labels":
                key = str(body["key"])
                if not all(c in "0123456789abcdef" for c in key):
                    return self._json({"error": "invalid key"}, 400)
                return self._json(save_annotation(key, body.get("labels"), body.get("notes")))
        except Exception as e:
            traceback.print_exc()
            return self._json({"error": f"{type(e).__name__}: {e}"}, 500)
        self._json({"error": "unknown"}, 404)


def _jsonable(o):
    import numpy as np
    if isinstance(o, dict):
        return {k: _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if isinstance(o, complex):
        return [o.real, o.imag]
    if isinstance(o, (np.floating, float)):
        return float(o) if np.isfinite(o) else None
    if isinstance(o, np.integer):
        return int(o)
    return o


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8034)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--precompute", action="store_true", help="simulate all presets into ./cache and exit")
    a = ap.parse_args()
    if a.precompute:
        precompute_all()
        print("[SimRelay] All presets are cached.")
        return
    threading.Thread(target=precompute_all, daemon=True).start()
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    url = f"http://{a.host}:{a.port}"
    print(f"[SimRelay] Ready at {url}  (Ctrl+C to stop)")
    if not a.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
