"""
Fault Hunter — membandingkan 'kebenaran fisika' (God view) dengan apa yang
dilakukan relai konvensional, lalu memberi label kegagalan F-1 .. F-5.

Kebenaran dasar (ground truth) radial dari GI:
  * Lintasan GI -> titik gangguan menentukan IED 'hulu' (forward).
  * Primary  = IED hulu terdekat ke gangguan; Backup = IED hulu berikutnya.
  * IED di luar lintasan (penyulang tetangga / hilir gangguan) -> fault REVERSE,
    seharusnya TIDAK trip.

Jendela evaluasi 'pra-clearing': dari t_on + 1 siklus sampai CB pertama terbuka
(atau gangguan padam / akhir simulasi).
"""
from __future__ import annotations
import copy
import glob
import hashlib
import json
import os
import numpy as np

from .network import path_from_source
from .settings import _zline
from .relays import t_op, mho_inside

CTI_MIN = 0.20
BACKFEED_MIN = 0.10        # fault still fed this long after the grid side has opened (s)
I_LIVE = 1.0               # fault current above this is a live fault (A)
CODES = {
    "F-1": "Blinding of Protection",
    "F-2": "Sympathetic Tripping",
    "F-3": "Miscoordination / CTI Violation",
    "F-4": "Directional Misidentification",
    "F-5": "Impedance Under-reach",
    "F-6": "Sustained DER Backfeed",
    "NT":  "Nuisance Trip (No Fault)",
}

# ------------------------------------------------------------------ baseline (same case without DER)
# Delayed clearing (F-1) is judged against the same fault without DER. The baseline is simulated
# once with the Python engine and cached per engine version; the MATLAB and Python engines agree
# on trip times within one or two steps (pilot of 121 cases), so it serves both engines.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FP = None


def _engine_fp():
    global _FP
    if _FP is None:
        h = hashlib.sha1()
        for p in sorted(glob.glob(os.path.join(_ROOT, "engine", "*.py"))):
            with open(p, "rb") as f:
                h.update(f.read())
        _FP = h.hexdigest()[:16]
    return _FP


def baseline_trips(sim):
    """Trip time of every relay, from fault inception, for the same scenario without DER.

    None when the scenario has no DER (it is its own baseline) or is islanded (no source without DER)."""
    sc = sim.sc
    if not sc.get("der", {}).get("units") or sc.get("grid", {}).get("mode", "grid") != "grid" or not sc.get("faults"):
        return None
    base = copy.deepcopy(sc)
    base["der"] = {"units": []}
    base["events"] = [e for e in base.get("events", []) if not str(e.get("id", "")).startswith("DER")]
    base["faults"] = [{k: v for k, v in f.items() if not k.startswith("_")} for f in base["faults"]]
    base.setdefault("sim", {})["save"] = False
    key = hashlib.sha1(json.dumps({"sc": base, "dt": sim.dt}, sort_keys=True, default=str).encode()).hexdigest()[:16]
    folder = os.path.join(_ROOT, "cache", "baseline", _engine_fp())
    path = os.path.join(folder, key + ".json")
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except (OSError, ValueError):
            pass
    from .sim import Simulator
    b = Simulator(base, sim.settings).run()
    t_on = base["faults"][0]["t_on"]
    out = {d.id: float(d.trip_time) - t_on for d in b.ieds if d.tripped and d.trip_time >= t_on}
    os.makedirs(folder, exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w") as f:
        json.dump(out, f)
    os.replace(tmp, path)
    return out


def analyze(sim, baseline="auto"):
    """baseline: relay trip times without DER ({ied: s from inception}), None to skip the
    delayed-clearing check, or "auto" to simulate (and cache) it."""
    if baseline == "auto":
        try:
            baseline = baseline_trips(sim)
        except Exception:
            baseline = None
    m = sim.model
    net = m.net
    faults = sim.sc.get("faults", [])
    dt = sim.dt
    T = sim.t[-1]
    ied_ids = [d.id for d in sim.ieds]
    trips = {d.id: d.trip_time for d in sim.ieds if d.tripped}
    trip_elem = {d.id: d.trip_elem for d in sim.ieds if d.tripped}
    findings = []
    conf = {"TP": 0, "TN": 0, "FP": 0, "FN": 0}
    per_ied = {i: {"TP": 0, "TN": 0, "FP": 0, "FN": 0} for i in ied_ids}
    fault_info = []

    # waktu CB pertama terbuka
    cb_open_times = {}
    for j, d in enumerate(sim.ieds):
        closed = sim.cb_t[:, j]
        if not closed.all() and closed[0]:
            k = int(np.argmax(~closed))
            cb_open_times[d.id] = float(sim.t[k])

    # Trips not caused by a fault, in a scenario that has one:
    #  * the tripping element was already picked up on load current before the first fault, and
    #    stayed picked up until the trip (typically reverse power flow from a DER above a
    #    non-directional pickup frozen at the baseline);
    #  * the trip comes more than 50 ms after every fault has ended (temporary faults).
    # Such trips are nuisance trips (NT), not sympathetic trips or miscoordination.
    load_trips = {}
    if faults:
        t_first = min(f["t_on"] for f in faults)
        ends = [f.get("t_off") for f in faults]
        t_all_off = max(ends) if all(e is not None for e in ends) else None
        # a relay on the path of a fault is judged against that fault (a late trip there is F-1)
        on_path = set()
        for f in faults:
            if f.get("_node"):
                on_path |= set(path_from_source(net, f["_node"])[1] or [])
        for d in sim.ieds:
            if not d.tripped or d.meta["branch"] in on_path:
                continue
            key = str(d.trip_elem or "").split(" ")[0]
            since = None
            for e in sorted(d.events, key=lambda x: x["t"]):      # MATLAB replays are not in time order
                if e["t"] > d.trip_time + 1e-9:
                    break
                k2 = e["text"].split(" ")[1] if len(e["text"].split(" ")) > 1 else ""
                if k2 != key:
                    continue
                if e["type"] == "PICKUP":
                    since = e["t"]
                elif e["type"] == "DROPOUT":
                    since = None
            if since is not None and since < t_first and "(inst)" not in str(d.trip_elem):
                load_trips[d.id] = f"{key} picked up on load current at t={since:.3f} s, before the fault at t={t_first:.3f} s"
            elif t_all_off is not None and d.trip_time > t_all_off + 0.05:
                load_trips[d.id] = f"tripped at t={d.trip_time:.3f} s, after the fault had ended at t={t_all_off:.3f} s"
        for iid, why in load_trips.items():
            findings.append({"code": "NT", "ied": iid, "fault": None, "t": trips[iid],
                             "title": f"{iid} tripped on load current, not on the fault ({trip_elem[iid]})",
                             "text": f"{iid} {why}. The trip would happen without the fault. Typical cause: reverse power flow "
                                     "from a DER that exceeds a non-directional pickup frozen at the baseline.",
                             "evidence": {"t_trip": trips[iid], "elem": trip_elem[iid]}})

    if not faults:
        for iid, tt in trips.items():
            findings.append({"code": "NT", "ied": iid, "fault": None, "t": tt,
                             "title": f"{iid} tripped without a fault ({trip_elem[iid]})",
                             "text": "No fault is present in the network, yet the relay tripped. Typical cause: cold load "
                                     "pickup, where load current exceeds the pickup frozen at the baseline.",
                             "evidence": {"t_trip": tt, "elem": trip_elem[iid]}})
            conf["FP"] += 1; per_ied[iid]["FP"] += 1
        for iid in ied_ids:
            if iid not in trips:
                conf["TN"] += 1; per_ied[iid]["TN"] += 1
        return _pack(findings, conf, per_ied, fault_info)

    for fi, f in enumerate(faults):
        node = f["_node"]
        t_on = f["t_on"]
        pb, pbr = path_from_source(net, node)
        path_set = set(pbr or [])
        upstream = [d for d in sim.ieds if d.meta["branch"] in path_set]
        upstream.sort(key=lambda d: pbr.index(d.meta["branch"]))
        P = upstream[-1] if upstream else None
        B = upstream[-2] if len(upstream) > 1 else None
        fault_feeder = net["buses"][node]["feeder"]
        t_end = f.get("t_off") or T
        opens_after = [t for t in cb_open_times.values() if t > t_on]
        t_first_open = min(opens_after) if opens_after else t_end
        w0 = int(round((t_on + 1.0 / sim.f0 + 2 * dt) / dt))
        w1 = max(int(round(min(t_first_open, t_end) / dt)) - 1, w0 + 1)
        w1 = min(w1, len(sim.t) - 1)
        win_trips = {i: tt for i, tt in trips.items() if t_on <= tt <= t_end + 0.05 and i not in load_trips}
        If_peak = float(np.max(np.abs(sim.Ifault[w0:w1 + 1, fi]))) if w1 > w0 else 0.0
        info = {"fault": f"F{fi+1}", "node": node, "type": f["type"], "phases": f.get("phases", ""),
                "rf": f.get("rf", 0), "t_on": t_on, "feeder": fault_feeder,
                "primary": P.id if P else None, "backup": B.id if B else None,
                "upstream": [d.id for d in upstream], "If_A": If_peak, "trips": win_trips}
        fault_info.append(info)

        def picked_in_window(ied):
            for e in ied.events:
                if e["type"] == "PICKUP" and t_on <= e["t"] <= (min(t_first_open, t_end) + 1e-6):
                    return True
            return False

        ground = f["type"] in ("SLG", "DLG")
        fph = [("abc".index(p)) for p in f.get("phases", "abc") if p in "abc"]
        if f["type"] == "3PH":
            fph = [0, 1, 2]

        # ---------------------------------------------- F-1 / F-4 / F-5 pada primary
        if P is not None:
            s = P.s
            j = ied_ids.index(P.id)
            Iw = np.abs(sim.relay_Imeas[w0:w1 + 1, j]) if w1 > w0 else np.zeros((1, 3))
            Imax_ph = float(np.max(Iw[:, s["ph_idx"]])) if Iw.size else 0.0
            I3 = np.abs(np.sum(sim.relay_Imeas[w0:w1 + 1, j], axis=1)) if w1 > w0 else np.zeros(1)
            I3max = float(np.max(I3)) if I3.size else 0.0
            picked = picked_in_window(P)
            if P.cls in ("OCR", "DOCR"):
                pk_ph = s["51P_pu"]; pk_n = s.get("51N_pu") or np.inf
                Mser = np.maximum(np.max(Iw[:, s["ph_idx"]], axis=1) / pk_ph, I3 / pk_n) if Iw.size else np.zeros(1)
                frac_above = float(np.mean(Mser > 1.0)) if Mser.size else 0.0
                cleared_by_other = any(i != P.id and tt <= (w1 * dt + 0.06) for i, tt in win_trips.items())
                if picked and P.id not in win_trips and not cleared_by_other and frac_above < 0.6:
                    findings.append({"code": "F-1", "ied": P.id, "fault": f"F{fi+1}", "t": t_on,
                        "title": f"{P.id} nearly blinded: current only briefly above pickup, no trip issued",
                        "text": f"Fault current through {P.id} exceeded pickup for only {frac_above*100:.0f}% of the fault "
                                f"duration (max phase {Imax_ph:.1f} A against pickup {pk_ph:.0f} A; 3I0 {I3max:.1f} A). The 51 integrator "
                                f"kept resetting, so the fault remained energized. Typical of current-limited IBR sources (about 1.1 to 1.5 pu).",
                        "evidence": {"I_ph_max": Imax_ph, "pickup_51P": pk_ph, "I3I0_max": I3max, "frac_above": frac_above}})
                if not picked:
                    findings.append({"code": "F-1", "ied": P.id, "fault": f"F{fi+1}", "t": t_on,
                        "title": f"{P.id} blinded to fault F{fi+1} at {node}",
                        "text": f"Current measured by {P.id} (max phase {Imax_ph:.1f} A, 3I0 {I3max:.1f} A) remained below "
                                f"pickup 51P {pk_ph:.0f} A and 51N {pk_n:.0f} A. Operator impact: no alarm and no trip.",
                        "evidence": {"I_ph_max": Imax_ph, "pickup_51P": pk_ph, "I3I0_max": I3max,
                                     "pickup_51N": None if pk_n == np.inf else pk_n,
                                     "M_ph": Imax_ph / pk_ph, "M_n": I3max / pk_n if pk_n != np.inf else None}})
            elif P.cls == "DIFF":
                if not picked:
                    findings.append({"code": "F-1", "ied": P.id, "fault": f"F{fi+1}", "t": t_on,
                        "title": f"87L {P.id} did not detect internal fault F{fi+1}",
                        "text": "Differential current remained below the pickup and slope restraint (weak infeed or high Rf).",
                        "evidence": {"pickup_87": s.get("87_pu")}})
        # ---------------------------------------------- F-1 delayed or missing clearing (any relay class)
        # Blinding also means a slower trip: infeed between the relay and the fault reduces the current
        # it sees. Judged against the same fault without DER, so a slow trip that the frozen settings
        # already give without DER is not attributed to the DER.
        if P is not None and baseline is not None and not any(
                x["code"] == "F-1" and x["ied"] == P.id and x["fault"] == f"F{fi+1}" for x in findings):
            tPn = win_trips.get(P.id)
            if tPn is not None and P.id in baseline:
                dB = baseline[P.id]
                dP = tPn - t_on
                if dP > max(2 * dB, dB + CTI_MIN):
                    findings.append({"code": "F-1", "ied": P.id, "fault": f"F{fi+1}", "t": tPn,
                        "title": f"{P.id} partly blinded: trip delayed to {dP:.3f} s (without DER {dB:.3f} s)",
                        "text": f"{P.id} cleared the fault at {node} {dP:.3f} s after inception, against {dB:.3f} s for the same "
                                f"fault without DER. DER infeed between the relay and the fault reduces the current it measures "
                                f"(or takes it below the instantaneous setting). Operator impact: longer voltage dip and more fault energy.",
                        "evidence": {"t_trip": dP, "t_baseline": dB, "ratio": dP / dB if dB > 0 else None, "elem": trip_elem.get(P.id)}})
            elif not win_trips and baseline and f.get("t_off") is None:
                # nothing trips with DER, while at least one relay clears the same fault without DER
                first = min(baseline, key=baseline.get)
                findings.append({"code": "F-1", "ied": P.id, "fault": f"F{fi+1}", "t": t_on,
                    "title": f"No relay tripped within the run (without DER {first} trips at {baseline[first]:.3f} s)",
                    "text": f"No relay tripped for the fault at {node} within {T - t_on:.2f} s, while without DER "
                            + ", ".join(f"{i} trips at {v:.3f} s" for i, v in sorted(baseline.items(), key=lambda x: x[1]))
                            + " after inception. DER infeed hides the fault from the protection. Operator impact: the fault stays energized.",
                    "evidence": {"baseline": baseline, "picked": picked_in_window(P)}})
        # ---------------------------------------------- F-6 sustained DER backfeed
        # Once a breaker on the fault path has opened, the grid no longer feeds the fault. A fault
        # current that remains after that comes from a DER in an unintentional island, until the
        # DER's own undervoltage or anti-islanding protection acts (up to 2 s under IEEE 1547).
        path_opens = [cb_open_times[d.id] for d in upstream if d.id in cb_open_times and cb_open_times[d.id] > t_on]
        if path_opens:
            t_cut = min(path_opens)
            k0 = int(round((t_cut + BACKFEED_MIN) / dt))
            k1 = min(int(round(t_end / dt)), len(sim.t) - 1)
            if k0 <= k1:
                live = np.max(np.abs(sim.Ifault[k0:k1 + 1, fi]), axis=1) > I_LIVE
                if live[0]:
                    stop = np.flatnonzero(~live)
                    t_last = float(sim.t[k0 + stop[0]]) if stop.size else None
                    dur = (t_last if t_last is not None else float(sim.t[k1])) - t_cut
                    Ib = float(np.max(np.abs(sim.Ifault[k0, fi])))
                    findings.append({"code": "F-6", "ied": None, "fault": f"F{fi+1}", "t": t_cut,
                        "title": f"Fault F{fi+1} at {node} fed by DER for {dur:.2f} s{'' if t_last is not None else ' or more'} after the grid side opened",
                        "text": f"The breaker on the fault path opened at t={t_cut:.3f} s, yet the fault kept drawing {Ib:.0f} A from DER "
                                f"in an unintentional island" + (f" until t={t_last:.3f} s." if t_last is not None else " until the end of the run.")
                                + " No relay separates the DER from the fault; it stops only when the DER's own protection acts. "
                                  "Operator impact: the arc persists and a reclose onto the fault fails.",
                        "evidence": {"t_cut": t_cut, "t_last": t_last, "duration": dur, "I_backfeed": Ib, "until_end": t_last is None}})
        # ---------------------------------------------- F-5 distance
        for d in upstream:
            if d.cls != "DIST":
                continue
            s = d.s
            Z1t, Z0t, _ = _zline(net, d.meta["from"], node)
            if f.get("line"):
                pass
            ztrue = abs(Z1t)
            expected_z1 = ztrue <= s["zreach"][0] and f.get("rf", 0) <= 1.0
            if not expected_z1:
                continue
            zone_pick = set()
            for e in d.events:
                if e["type"] == "PICKUP" and e["text"].find("21-Z") >= 0 and t_on <= e["t"] <= min(t_first_open, t_end) + 1e-6:
                    zone_pick.add(int(e["text"].split("21-Z")[1][0]))
            ok = (d.id in win_trips and trip_elem.get(d.id) == "21-Z1") or (1 in zone_pick)
            if not ok:
                zm = _measured_loop(sim, d, f, w0, w1)
                reached = min(zone_pick) if zone_pick else None
                findings.append({"code": "F-5", "ied": d.id, "fault": f"F{fi+1}", "t": t_on,
                    "title": f"{d.id} under-reach: Zone 1 fault measured {'in Zone '+str(reached) if reached else 'outside all zones'}",
                    "text": f"Physical impedance to the fault |Z|={ztrue:.2f} Ω (below Z1 {s['zreach'][0]:.2f} Ω), but the relay "
                            f"measured |Z|≈{abs(zm) if zm is not None else float('nan'):.2f} Ω. DER infeed between the relay and the "
                            f"fault increases the apparent impedance. Operator impact: delayed trip and prolonged voltage dip.",
                    "evidence": {"Z_true": ztrue, "Z1_reach": s["zreach"][0],
                                 "Z_meas": [zm.real, zm.imag] if zm is not None else None,
                                 "zone": reached, "t_trip": win_trips.get(d.id), "elem": trip_elem.get(d.id)}})
        # ---------------------------------------------- F-4 directional
        for d in sim.ieds:
            if d.cls != "DOCR":
                continue
            truth = 1 if d in upstream else -1
            recs = [r for r in sim.relay_dir[d.id] if w0 <= r[0] <= w1]
            if not recs:
                continue
            j = ied_ids.index(d.id)
            Iw = np.abs(sim.relay_Imeas[w0:w1 + 1, j])
            I3 = np.abs(np.sum(sim.relay_Imeas[w0:w1 + 1, j], axis=1))
            picked_ph = [k for k in d.s["ph_idx"] if np.max(Iw[:, k]) > d.s["51P_pu"]]
            picked_n = bool(d.s.get("51N_pu")) and np.max(I3) > d.s["51N_pu"]
            mid = recs[len(recs) // 2]
            decl_P = mid[1]; decl_N = mid[2]; meth = mid[3]
            bad = []
            def wrong(dcl):
                # forward: blok (reverse/indeterminate) = salah; reverse: hanya 'forward' yang salah
                return dcl <= 0 if truth > 0 else dcl > 0
            for k in picked_ph:
                if (k in fph or truth < 0) and wrong(decl_P[k]):
                    bad.append(("67P-" + "ABC"[k], decl_P[k]))
            if picked_n and ground and wrong(decl_N):
                bad.append((f"67N ({meth})", decl_N))
            if bad:
                lbl = {1: "FORWARD", -1: "REVERSE", 0: "INDETERMINATE"}
                findings.append({"code": "F-4", "ied": d.id, "fault": f"F{fi+1}", "t": t_on,
                    "title": f"{d.id} direction misread: {'FORWARD' if truth > 0 else 'REVERSE'} fault declared as "
                             + ", ".join(f"{e}={lbl[v]}" for e, v in bad),
                    "text": ("A fault in front of the relay was blocked and remained energized. " if truth > 0 else
                             "A fault behind the relay was treated as forward, putting a healthy line at risk of tripping. ")
                            + "Cause: distorted phase-angle reference (controlled IBR current, I2 near zero, weak polarization).",
                    "evidence": {"truth": lbl[truth], "declared": {e: lbl[v] for e, v in bad},
                                 "tripped": d.id in win_trips}})
        # ---------------------------------------------- F-2 sympathetic / backfeed
        for iid, tt in win_trips.items():
            d = sim.ied_by_id[iid]
            if d in upstream:
                continue
            if trip_elem.get(iid, "").startswith("87L") or any(
                    e["type"] == "DTT" for e in d.events if abs(e["t"] - tt) < 0.02):
                pass
            if any(x["code"] == "F-4" and x["ied"] == iid and x["fault"] == f"F{fi+1}" for x in findings):
                continue          # trip akibat salah arah sudah dicatat sebagai F-4
            same = net["buses"][d.meta["to"]]["feeder"] == fault_feeder
            findings.append({"code": "F-2", "ied": iid, "fault": f"F{fi+1}", "t": tt,
                "title": f"{iid} sympathetic trip ({trip_elem[iid]}) for a fault on {'the same feeder (downstream or another branch)' if same else 'an adjacent feeder'}",
                "text": f"{d.meta['name']} is healthy but tripped at t={tt:.3f} s due to reverse current contribution "
                        f"(load-side DER or zero-sequence source of the interconnection transformer). Operator impact: two feeders de-energized simultaneously.",
                "evidence": {"t_trip": tt, "elem": trip_elem[iid], "feeder": d.meta["feeder"]}})
        # ---------------------------------------------- F-3 koordinasi
        if P is not None and B is not None:
            tP = win_trips.get(P.id)
            P_picked = picked_in_window(P)
            for U in upstream[:-1][::-1]:
                tU = win_trips.get(U.id)
                if tU is None:
                    # estimasi margin CTI dari integrator saat primary trip
                    if tP is not None and U.cls in ("OCR", "DOCR"):
                        k = int(round(tP / dt))
                        j = ied_ids.index(U.id)
                        prog = sim.relay_prog[k, j]
                        I = sim.relay_Imeas[k, j]
                        cands = []
                        for elem, p, Ival, pk, tms in (
                                ("51P", prog[0], float(np.max(np.abs(I))), U.s["51P_pu"], U.s["51P_tms"]),
                                ("51N", prog[1], float(abs(np.sum(I))), U.s.get("51N_pu"), U.s["51N_tms"])):
                            if pk and Ival > pk and p > 0:
                                cands.append((elem, (1 - p) * t_op(U.s["curve"], tms, Ival / pk) + sim.t_cb * 0))
                        if cands:
                            elem, rem = min(cands, key=lambda x: x[1])
                            cti = rem
                            if cti < CTI_MIN and U is B:
                                findings.append({"code": "F-3", "ied": U.id, "fault": f"F{fi+1}", "t": tP,
                                    "title": f"CTI between {U.id} and {P.id} reduced: {cti*1000:.0f} ms < {CTI_MIN*1000:.0f} ms",
                                    "text": f"Primary {P.id} tripped at t={tP:.3f} s; backup {U.id} ({elem}) was {cti*1000:.0f} ms "
                                            f"from tripping. The coordination margin is below the limit, so the backup may also operate.",
                                    "evidence": {"cti": cti, "t_primary": tP, "elem_backup": elem, "near_miss": True}})
                    continue
                if not P_picked and tP is None and U is B:
                    continue          # backup yang sah ketika primary buta (dicatat di F-1)
                if tP is None or tU < tP or (tU - tP) < CTI_MIN:
                    findings.append({"code": "F-3", "ied": U.id, "fault": f"F{fi+1}", "t": tU,
                        "title": f"{U.id} (upstream) tripped {'before' if (tP is None or tU < tP) else 'almost simultaneously with'} {P.id} (downstream)",
                        "text": f"The fault at {node} should have been cleared by {P.id}. {U.id} tripped at t={tU:.3f} s ({trip_elem[U.id]})"
                                + (f", {P.id} at t={tP:.3f} s, Δt={1000*(tU-tP):.0f} ms." if tP is not None else f", {P.id} did not trip.")
                                + " Operator impact: wider outage area and an ambiguous fault location in the SOE.",
                        "evidence": {"t_up": tU, "t_down": tP, "cti": (tU - tP) if tP is not None else None,
                                     "elem_up": trip_elem[U.id]}})
        # ---------------------------------------------- confusion matrix
        P_failed = P is not None and P.id not in win_trips
        for d in sim.ieds:
            should = (d is P) or (P_failed and d is B)
            if d.cls == "DIFF" and P is not None and d.meta.get("partner") == P.id:
                pass
            did = d.id in win_trips
            key = "TP" if (should and did) else "FN" if should else "FP" if did else "TN"
            if d in upstream and did and not should and key == "FP":
                key = "FP"
            conf[key] += 1
            per_ied[d.id][key] += 1
    return _pack(findings, conf, per_ied, fault_info)


def _measured_loop(sim, d, f, w0, w1):
    recs = [r for r in sim.relay_Z[d.id] if w0 <= r[0] <= w1]
    if not recs:
        return None
    typ = f["type"]; ph = f.get("phases", "a").upper()
    if typ == "SLG":
        loop = ph[0] + "G"
    elif typ in ("LL", "DLG"):
        loop = ph[0] + ph[1] if len(ph) > 1 else "AB"
    else:
        loop = "AB"
    k, Z, _ = recs[-1]
    z = Z.get(loop) if Z else None
    if z is None:
        vals = [complex(*v) for v in Z.values() if v]
        if not vals:
            return None
        return min(vals, key=abs)
    return complex(*z)


def _pack(findings, conf, per_ied, fault_info):
    tp, tn, fp, fn = conf["TP"], conf["TN"], conf["FP"], conf["FN"]
    dep = tp / (tp + fn) if (tp + fn) else None
    sec = tn / (tn + fp) if (tn + fp) else None
    counts = {c: sum(1 for x in findings if x["code"] == c) for c in CODES}
    return {"findings": sorted(findings, key=lambda x: x["t"] or 0), "confusion": conf, "per_ied": per_ied,
            "dependability": dep, "security": sec, "counts": counts, "faults": fault_info,
            "codes": CODES}
