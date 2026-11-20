"""Serialization of simulation results for the UI and run logs (.json, .npz, .mat)."""
from __future__ import annotations
import json
import os
import numpy as np

from .der import seq

SCADA_DT = 0.01   # resolusi timeline UI (10 ms)


def _r(x, n=4):
    return float(np.round(x, n))


def topology(model, settings):
    net = model.net
    buses = [{"id": b, "kv": v["kv"], "phases": v["phases"], "x": v["x"], "y": v["y"],
              "feeder": v["feeder"], "virtual": v.get("virtual", False)} for b, v in net["buses"].items()]
    brs = []
    for br in net["branches"]:
        d = {"id": br["id"], "kind": br["kind"], "from": br["from"], "to": br["to"], "phases": br["phases"]}
        if br["kind"] == "line":
            d.update({"len_ft": br["len_ft"], "cfg": br["cfg"], "parent": br.get("parent")})
        if br["kind"] == "reg":
            d["taps"] = br["taps"]
        if br["kind"] == "xfmr":
            d.update({"kva": br["kva"], "kv1": br["kv1"], "kv2": br["kv2"], "r_pct": br["r_pct"], "x_pct": br["x_pct"]})
        brs.append(d)
    return {"buses": buses, "branches": brs, "loads": model.load_info, "caps": model.cap_info,
            "ieds": net["ieds"], "substation": net["substation"], "f0": net["f0"]}


def pack(sim, hunt, run_id):
    m = sim.model
    dt = sim.dt
    step = max(int(round(SCADA_DT / dt)), 1)
    ks = np.arange(0, len(sim.t), step)
    nb = len(m.br_list)
    # --- bus
    Vb = np.zeros((len(ks), len(m.bus_list), 3), complex)
    for i, b in enumerate(m.bus_list):
        for k in range(3):
            j = m.bus_sel[i, k]
            if j >= 0:
                Vb[:, i, k] = sim.V[ks, j]
    vbase = np.array([m.net["buses"][b]["vbase"] for b in m.bus_list])
    Vpu = np.abs(Vb) / vbase[None, :, None]
    Vang = np.degrees(np.angle(Vb))
    for i, b in enumerate(m.bus_list):
        for k in range(3):
            if m.bus_sel[i, k] < 0:
                Vpu[:, i, k] = np.nan; Vang[:, i, k] = np.nan
    # --- cabang
    Ib = sim.Ib[ks].reshape(len(ks), nb, 3)
    Imag = np.abs(Ib)
    Pbr = np.zeros((len(ks), nb, 2))
    for i, br in enumerate(m.br_list):
        fi = m.bus_index[br["from"]]
        S = np.nansum(np.where(np.isnan(Vpu[:, fi, :]), 0, Vb[:, fi, :] * np.conj(Ib[:, i, :])), axis=1)
        Pbr[:, i, 0] = S.real / 1e3
        Pbr[:, i, 1] = S.imag / 1e3
    # --- energized: |V| > 0.05 pu
    energized = np.nan_to_num(np.nanmax(Vpu, axis=2)) > 0.05

    def arr(x, n=3):
        a = np.round(np.asarray(x, float), n)
        return np.where(np.isnan(a), None, a).tolist()

    ied = []
    for j, d in enumerate(sim.ieds):
        I = sim.relay_Imeas[ks, j]
        V = sim.relay_Vmeas[ks, j]
        i3 = np.abs(np.sum(I, axis=1))
        ied.append({"id": d.id, "cls": d.cls, "fallback": d.fallback_note, "I": arr(np.abs(I), 1), "I0x3": arr(i3, 1),
                    "Vpu": arr(np.abs(V) / d.s["vbase"], 4), "cb": sim.cb_t[ks, j].tolist(),
                    "prog": arr(sim.relay_prog[ks, j], 3)})
    ders = []
    for j, d in enumerate(sim.ders):
        ders.append({"id": d.id, "bus": d.bus, "type": d.type, "kva": round(d.S / 1e3, 1),
                     "xfmr": d.ground, "cfg": {k: v for k, v in d.cfg.items() if isinstance(v, (int, float, str, bool, list))},
                     "P": arr(sim.Pder[ks, j, 0], 1), "Q": arr(sim.Pder[ks, j, 1], 1),
                     "I": arr(np.abs(sim.Ider[ks, j]), 1), "on": sim.der_on[ks, j].tolist(),
                     "irr": arr(sim.irr_t[ks, j], 0) if d.type.startswith("IBR") else None})
    faults = []
    for i, f in enumerate(sim.sc.get("faults", [])):
        faults.append({"id": f"F{i+1}", "node": f["_node"], "type": f["type"], "phases": f.get("phases"),
                       "rf": f.get("rf", 0), "t_on": f["t_on"], "t_off": f.get("t_off"),
                       "bus": f.get("bus"), "line": f.get("line"), "frac": f.get("frac"),
                       "I": arr(np.abs(sim.Ifault[ks, i]), 1)})
    # --- SOE
    sim_ev = sorted(sim.events_sim, key=lambda e: e["t"])
    relay_ev = sorted([e for d in sim.ieds for e in d.events], key=lambda e: e["t"])
    scada = scada_alarms(sim, ks, Vpu, relay_ev)
    out = {
        "id": run_id,
        "scenario": sim.sc,
        "dt": dt, "T": float(sim.t[-1]), "f0": sim.f0, "wall": round(sim.wall, 3),
        "t": arr(sim.t[ks], 4),
        "buses": m.bus_list,
        "branches": [br["id"] for br in m.br_list],
        "Vpu": arr(Vpu, 4), "Vang": arr(Vang, 1),
        "Ibr": arr(Imag, 1), "Pbr": arr(Pbr, 1), "energized": energized.tolist(),
        "freq": arr(sim.freq_t[ks], 4), "sub": sim.sub_t[ks].tolist(),
        "ied": ied, "der": ders, "faults": faults,
        "events_sim": sim_ev, "events_relay": relay_ev, "events_scada": scada,
        "hunter": _clean(hunt),
        "topology": topology(m, sim.settings),
    }
    return out


def scada_alarms(sim, ks, Vpu, relay_ev):
    """Alarm yang benar-benar sampai ke layar operator (dari IED & sensor)."""
    al = []
    for e in relay_ev:
        if e["type"] in ("TRIP", "52B", "DTT"):
            al.append({"t": e["t"], "id": e["id"], "sev": "hi", "text": e["text"]})
        elif e["type"] == "PICKUP":
            al.append({"t": e["t"], "id": e["id"], "sev": "lo", "text": e["text"].split(" |")[0].split(" 3I0")[0]})
    m = sim.model
    t = sim.t[ks]
    for i, b in enumerate(m.bus_list):
        if m.net["buses"][b].get("virtual"):
            continue
        v = np.nan_to_num(np.nanmin(Vpu[:, i, :], axis=1), nan=1.0)
        state = None
        for k, vv in enumerate(v):
            s = "dead" if vv < 0.05 else "uv" if vv < 0.90 else "ov" if vv > 1.10 else None
            if s != state:
                if s == "uv":
                    al.append({"t": _r(t[k]), "id": b, "sev": "mid", "text": f"Bus {b} UNDERVOLTAGE {vv:.2f} pu"})
                elif s == "dead":
                    al.append({"t": _r(t[k]), "id": b, "sev": "mid", "text": f"Bus {b} LOSS OF VOLTAGE"})
                elif s == "ov":
                    al.append({"t": _r(t[k]), "id": b, "sev": "mid", "text": f"Bus {b} OVERVOLTAGE {vv:.2f} pu"})
                elif state in ("uv", "dead", "ov"):
                    al.append({"t": _r(t[k]), "id": b, "sev": "ok", "text": f"Bus {b} voltage restored to normal"})
                state = s
    for e in sim.events_sim:
        if e["type"] == "DER_TRIP":
            al.append({"t": e["t"], "id": e["id"], "sev": "mid", "text": f"{e['id']} OFFLINE (DER communication status)"})
    return sorted(al, key=lambda e: e["t"])


def _clean(o):
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, complex):
        return [o.real, o.imag]
    return o


class WaveSource:
    """Arrays needed to rebuild waveforms, detached from the Simulator so they can be cached on disk."""
    ARRAYS = ("t", "V", "Ib", "Ider", "Ifault", "relay_Vmeas", "freq_t")

    @classmethod
    def from_sim(cls, sim):
        w = cls()
        m = sim.model
        for k in cls.ARRAYS:
            setattr(w, k, np.asarray(getattr(sim, k)))
        w.dt, w.f0 = float(sim.dt), float(sim.f0)
        w.tau_dc = [float(x) for x in getattr(sim, "tau_dc", [0.01])]
        w.bus_index = dict(m.bus_index)
        w.bus_sel = np.asarray(m.bus_sel)
        w.br_index = dict(m.br_index)
        w.ied_ids = [d.id for d in sim.ieds]
        w.ied_br = [int(d.br_i) for d in sim.ieds]
        w.der_ids = [d.id for d in sim.ders]
        return w

    def save(self, folder):
        os.makedirs(folder, exist_ok=True)
        np.savez_compressed(os.path.join(folder, "wave.npz"), bus_sel=self.bus_sel,
                            **{k: getattr(self, k) for k in self.ARRAYS})
        meta = {k: getattr(self, k) for k in ("dt", "f0", "tau_dc", "bus_index", "br_index", "ied_ids", "ied_br", "der_ids")}
        with open(os.path.join(folder, "wave.json"), "w") as f:
            json.dump(meta, f)

    @classmethod
    def load(cls, folder):
        w = cls()
        with np.load(os.path.join(folder, "wave.npz")) as z:
            for k in cls.ARRAYS + ("bus_sel",):
                setattr(w, k, z[k])
        with open(os.path.join(folder, "wave.json")) as f:
            for k, v in json.load(f).items():
                setattr(w, k, v)
        return w


def waveform(src, sig, mode="inst", spc=64):
    """Rebuild the instantaneous waveform from the phasor series (with current DC offset)."""
    dt = src.dt
    kind, ident, q = sig.split(":")
    if kind == "bus":
        i = src.bus_index[ident]
        P = np.zeros((len(src.t), 3), complex)
        for k in range(3):
            j = src.bus_sel[i, k]
            if j >= 0:
                P[:, k] = src.V[:, j]
        unit, scale, is_i = "kV", 1e-3, False
    elif kind == "br":
        bi = src.br_index[ident]
        P = src.Ib[:, bi * 3: bi * 3 + 3].astype(complex)
        unit, scale, is_i = "A", 1.0, True
    elif kind == "ied":
        j = src.ied_ids.index(ident)
        if q == "V":
            P = src.relay_Vmeas[:, j].astype(complex)
            unit, scale, is_i = "kV", 1e-3, False
        else:
            br = src.ied_br[j]
            P = src.Ib[:, br * 3: br * 3 + 3].astype(complex)
            unit, scale, is_i = "A", 1.0, True
    elif kind == "der":
        j = src.der_ids.index(ident)
        P = src.Ider[:, j].astype(complex)
        unit, scale, is_i = "A", 1.0, True
    elif kind == "fault":
        j = int(ident[1:]) - 1
        P = src.Ifault[:, j].astype(complex)
        unit, scale, is_i = "A", 1.0, True
    else:
        raise ValueError(sig)
    if mode == "rms":
        step = max(int(round(SCADA_DT / dt / 2)), 1)
        ks = np.arange(0, len(src.t), step)
        return {"unit": unit, "mode": "rms", "t": np.round(src.t[ks], 5).tolist(),
                "ch": [np.round(np.abs(P[ks, k]) * scale, 3).tolist() for k in range(3)]}
    if mode == "seq":
        step = max(int(round(SCADA_DT / dt / 2)), 1)
        ks = np.arange(0, len(src.t), step)
        S = np.array([seq(P[k]) for k in ks])
        return {"unit": unit, "mode": "seq", "t": np.round(src.t[ks], 5).tolist(),
                "ch": [np.round(np.abs(S[:, k]) * scale, 3).tolist() for k in (1, 2, 0)],
                "labels": ["1 (pos)", "2 (neg)", "0 (zero)"]}
    fs = src.f0 * spc
    ts = np.arange(0, src.t[-1], 1.0 / fs)
    kidx = np.minimum((ts / dt).astype(int), len(src.t) - 1)
    theta = 2 * np.pi * np.cumsum(src.freq_t.astype(float)) * dt
    th = np.interp(ts, src.t, theta)
    w = np.sqrt(2) * np.exp(1j * th)
    out = []
    for k in range(3):
        y = np.real(P[kidx, k] * w)
        if is_i:
            # DC offset: each current step is compensated by a decaying DC component.
            dP = np.diff(P[:, k], prepend=P[0, k])
            prev = np.abs(np.concatenate([[P[0, k]], P[:-1, k]]))
            # Current increases only (fault inception / energization). Breakers interrupt
            # at current zero, so opening produces no DC component.
            big = np.where((np.abs(dP) > 0.02 * (np.max(np.abs(P[:, k])) + 1e-9))
                           & (np.abs(P[:, k]) > 1.05 * prev))[0]
            tau = max([x for x in (src.tau_dc or [0.01]) if x] or [0.01])
            for kk in big:
                t0 = src.t[kk]
                di = np.real(dP[kk] * np.sqrt(2) * np.exp(1j * theta[kk]))
                msk = ts >= t0
                y[msk] -= di * np.exp(-(ts[msk] - t0) / tau)
        out.append(np.round(y * scale, 3).tolist())
    return {"unit": unit, "mode": "inst", "fs": fs, "t0": 0.0, "ch": out}


def save_run(sim, payload, folder):
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "result.json"), "w") as f:
        json.dump(payload, f)
    data = {"t": sim.t, "V": sim.V, "Ibr": sim.Ib, "Ider": sim.Ider, "Pder": sim.Pder,
            "freq": sim.freq_t, "cb": sim.cb_t, "Ifault": sim.Ifault,
            "relay_I": sim.relay_Imeas, "relay_V": sim.relay_Vmeas, "relay_prog": sim.relay_prog}
    np.savez_compressed(os.path.join(folder, "data.npz"), **data)
    try:
        import scipy.io
        scipy.io.savemat(os.path.join(folder, "data.mat"), {k: np.asarray(v) for k, v in data.items()},
                         do_compression=True)
    except Exception:
        pass
