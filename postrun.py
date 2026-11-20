#!/usr/bin/env python3
"""
SimRelay 34: Post-Run visualization (Proof of Urgency).

    python postrun.py

Reads batch/results.jsonl produced by batch.py and writes
  batch/figures/fig1_tcc_overlay.(png|pdf)
  batch/figures/fig2_failure_heatmap.(png|pdf)
  batch/figures/fig3_relay_class_escalation.(png|pdf)
  batch/figures/fig4_rx_envelope_polar_rose.(png|pdf)
  batch/figures/fig5_confusion_matrix.(png|pdf)
  batch/postrun_summary.json      numbers behind every figure (used by the Post-Run page)
  batch/postrun_tables.csv        long-format table of every run
"""
from __future__ import annotations
import csv
import json
import os
import sys
from collections import defaultdict

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, ListedColormap, BoundaryNorm
from matplotlib.lines import Line2D
from matplotlib.patches import Circle, Wedge

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from engine.relays import t_op                       # noqa: E402
from engine.network import base_network             # noqa: E402
from engine.settings import _zline                  # noqa: E402

BATCH = os.path.join(ROOT, "batch")
FIG = os.path.join(BATCH, "figures")

# Reference palette (validated: adjacent CVD dE >= 9.1, normal-vision >= 19.6 on the light surface)
SURFACE = "#fcfcfb"
INK, INK2, MUTED = "#0b0b0b", "#52514e", "#898781"
GRID, AXIS = "#e1e0d9", "#c3c2b7"
CAT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#6250d6"]
SEQ = ["#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7", "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b"]
ORD7 = ["#86b6ef", "#5598e7", "#3987e5", "#256abf", "#1c5cab", "#104281", "#0d366b"]   # ordinal, starts at step 250
CRIT, GOOD = "#d03b3b", "#0ca30c"
CODES = ["F-1", "F-2", "F-3", "F-4", "F-5"]
ALL = CODES + ["NT"]          # NT: nuisance trip before the fault (DER seen as an internal fault)
CODE_NAME = {"F-1": "Blinding", "F-2": "Sympathetic trip", "F-3": "Miscoordination (CTI)",
             "F-4": "Directional error", "F-5": "Impedance under-reach", "NT": "Nuisance trip"}
CLASS_LABEL = {"OCR": "OCR 50/51", "DOCR": "DOCR 67", "DIST": "Distance 21", "DIFF": "Differential 87L"}
PENS = [0, 20, 40, 60, 80, 100, 120]

plt.rcParams.update({
    "font.family": ["Segoe UI", "DejaVu Sans"], "font.size": 9.5,
    "axes.edgecolor": AXIS, "axes.labelcolor": INK2, "axes.titlecolor": INK, "axes.titlesize": 11,
    "axes.titleweight": "semibold", "axes.titlelocation": "left", "axes.titlepad": 10,
    "xtick.color": MUTED, "ytick.color": MUTED, "xtick.labelcolor": INK2, "ytick.labelcolor": INK2,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.7, "axes.axisbelow": True,
    "axes.spines.top": False, "axes.spines.right": False,
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "legend.frameon": False, "legend.fontsize": 8.5, "lines.linewidth": 2,
})


def load():
    rows = {}
    with open(os.path.join(BATCH, "results.jsonl")) as f:
        for line in f:
            try:
                r = json.loads(line)
                rows[r["key"]] = r
            except Exception:
                pass
    return list(rows.values())


def failed(r):
    return any(r["counts"].get(c, 0) for c in ALL)


def save(fig, name):
    """Save with the English caption (web, figures/) and without it (figures/report/, for the PDF report)."""
    os.makedirs(os.path.join(FIG, "report"), exist_ok=True)
    for ext in ("png", "pdf"):
        fig.savefig(os.path.join(FIG, f"{name}.{ext}"), dpi=220, bbox_inches="tight")
    cap = getattr(fig, "_caption", None)
    if cap is not None:
        cap.remove()
    fig.savefig(os.path.join(FIG, "report", f"{name}.png"), dpi=220, bbox_inches="tight")
    plt.close(fig)


def caption(fig, text, y=-0.02):
    fig._caption = fig.text(0.01, y, text, ha="left", va="top", fontsize=8.5, color=INK2, wrap=True)


def tech_of(r):
    return "IBR" if r["tech"] in ("IBR-GFL", "ISL") else "SG" if r["tech"] == "SG" else "None"


# ---------------------------------------------------------------- relay times
def curve_time(ied, I, elem):
    pu = ied["pu51P"] if elem == "P" else ied["pu51N"]
    tms = ied["tms51P"] if elem == "P" else ied["tms51N"]
    if not pu or I <= pu * 1.0001:
        return np.inf
    return float(t_op("IEC_SI", tms, I / pu))


def op_time(ied):
    """Actual trip time if tripped, otherwise the curve time the relay would reach (inf if below pickup)."""
    if ied["t_trip"] is not None:
        return ied["t_trip"], True
    return min(curve_time(ied, ied["Iph"], "P"), curve_time(ied, ied["I3I0"], "N")), False


# ================================================================ Figure 1: TCC
def fig_tcc(R, S):
    sel = [r for r in R if r["cls"] == "OCR" and r["bus"] in ("834", "848") and r["ftype"] == "3PH"
           and (r["campaign"] in ("H2", "I") or (r["campaign"] == "H1" and r["load_pct"] == 100))]
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(12.5, 4.9), gridspec_kw={"width_ratios": [1.15, 1]})
    a3 = sel[0]["ieds"]["A3"] if sel else None
    a2 = sel[0]["ieds"]["A2"] if sel else None
    I = np.logspace(0.6, 3.3, 400)
    for ied, nm, ls in ((a3, "A3 51P (primary)", "-"), (a2, "A2 51P (backup)", "--")):
        t = [curve_time(ied, x, "P") for x in I]
        ax.plot(I, t, ls, color=INK, lw=1.6, zorder=3)
        k = np.searchsorted(I, ied["pu51P"] * 6)
        ax.text(I[k], t[k] * 1.12, nm, color=INK, fontsize=8.5, ha="left", va="bottom")
        ax.axvline(ied["pu51P"], color=MUTED, lw=0.9, ls=":", zorder=2)
    ax.text(a3["pu51P"] * 0.97, 9.0, f"A3 pickup {a3['pu51P']:.0f} A", rotation=90, ha="right", va="top", fontsize=8, color=INK2)
    ax.text(a2["pu51P"] * 0.97, 9.0, f"A2 pickup {a2['pu51P']:.0f} A", rotation=90, ha="right", va="top", fontsize=8, color=INK2)
    ax.axvspan(1, a3["pu51P"], color="#f0efec", zorder=0)
    ax.text(5.5, 2.5, "Below A3 pickup\n(blinding zone, F-1)", ha="center", fontsize=8, color=INK2)
    nt_y = 14
    blind = 0          # A3 never tripped and its current stayed below pickup (F-1)
    upstream_first = 0 # A3 above pickup but an upstream relay cleared the fault first
    for r in sel:
        c = ORD7[PENS.index(r["pen"])] if r["pen"] in PENS else ORD7[-1]
        d3, d2 = r["ieds"]["A3"], r["ieds"]["A2"]
        mk = "D" if r["campaign"] == "I" else "o"
        if d3["t_trip"] is not None and "P" not in (d3["elem"] or ""):
            pass                                   # tripped on a ground element: not a point of the phase TCC
        elif d3["t_trip"] is not None:
            ax.scatter(d3["Iph"], d3["t_trip"], s=22, marker=mk, color=c, edgecolor=SURFACE, linewidth=0.6, zorder=4)
        else:
            ax.scatter(max(d3["Iph"], 1.3), nt_y, s=26, marker="x", color=c, linewidth=1.4, zorder=4)
            if d3["Iph"] < d3["pu51P"]:
                blind += 1
            else:
                upstream_first += 1
        t2, real = op_time(d2)
        if real and "P" not in (d2["elem"] or ""):
            continue
        if np.isfinite(t2):
            ax.scatter(d2["Iph"], t2, s=24, marker="^", facecolor=c if real else "none", edgecolor=c, linewidth=1.0, zorder=4)
    ax.axhline(nt_y, color=AXIS, lw=0.8)
    ax.text(1.25, nt_y * 1.08, "No trip issued", fontsize=8, color=INK2, va="bottom")
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlim(1.2, 2000); ax.set_ylim(0.005, 25)
    ax.set_xlabel("Phase current seen by the relay (A)"); ax.set_ylabel("Operating time after fault inception (s)")
    ax.set_title("a. Phase TCC overlay, three-phase faults at 834 and 848")
    h = [Line2D([], [], marker="s", ls="", color=ORD7[i], markersize=7, label=f"{p}%") for i, p in enumerate(PENS)]
    leg1 = ax.legend(handles=h, title="DER penetration", loc="upper right", bbox_to_anchor=(1.0, 0.86), ncol=2, fontsize=8, title_fontsize=8.5)
    ax.add_artist(leg1)
    h2 = [Line2D([], [], marker="o", ls="", color=INK2, label="A3 trip (grid-connected)"),
          Line2D([], [], marker="D", ls="", color=INK2, label="A3 trip (islanded)"),
          Line2D([], [], marker="x", ls="", color=INK2, label="A3 no trip"),
          Line2D([], [], marker="^", ls="", color=INK2, label="A2 trip"),
          Line2D([], [], marker="^", ls="", mfc="none", color=INK2, label="A2 curve time (not reached)")]
    ax.legend(handles=h2, loc="lower left", fontsize=8)

    # CTI margin versus penetration
    cti_rows = []
    for r in R:
        if r["cls"] != "OCR" or r["bus"] not in ("834", "848") or r["campaign"] not in ("H1", "H2"):
            continue
        d3, d2 = r["ieds"]["A3"], r["ieds"]["A2"]
        t3, _ = op_time(d3)
        t2, _ = op_time(d2)
        if not (np.isfinite(t2) and np.isfinite(t3)):
            continue                                # one of the relays never reaches pickup (covered by F-1)
        cti_rows.append((r["pen"], tech_of(r), t2 - t3, r["counts"].get("F-3", 0) > 0))
    rng = np.random.default_rng(3)
    for tech, col, off in (("None", INK2, 0), ("SG", CAT[0], -3), ("IBR", CAT[1], 3)):
        pts = [x for x in cti_rows if x[1] == tech]
        if not pts:
            continue
        xs = np.array([p[0] for p in pts]) + off + rng.uniform(-1.6, 1.6, len(pts))
        ys = np.array([p[2] for p in pts])
        bx.scatter(xs, np.clip(ys, -0.45, 2.0), s=14, color=col, alpha=0.55, edgecolor="none", zorder=3)
        med = [(p, np.median([q[2] for q in pts if q[0] == p])) for p in PENS if any(q[0] == p for q in pts)]
        if len(med) > 1:
            bx.plot([m[0] + off for m in med], [m[1] for m in med], color=col, lw=2, zorder=4)
            dy = {"None": 0, "SG": 0.09, "IBR": -0.09}[tech]
            bx.text(med[-1][0] + off + 10, med[-1][1] + dy, {"None": "No DER", "SG": "SG median", "IBR": "IBR median"}[tech],
                    color=INK, fontsize=8.5, va="center")
    bx.axhline(0.2, color=CRIT, lw=1.4, ls="--", zorder=2)
    bx.text(-4, 0.215, "CTI limit 0.2 s", color=CRIT, fontsize=8.5, va="bottom")
    bx.axhspan(-0.5, 0.2, color="#fbe9e8", zorder=0)
    bx.set_xlim(-8, 168); bx.set_ylim(-0.5, 2.0); bx.set_xticks(PENS)
    bx.set_xlabel("DER penetration (% of Feeder A peak load)"); bx.set_ylabel("CTI margin, backup A2 minus primary A3 (s)")
    bx.set_title("b. Coordination margin A2 to A3, faults at 834 and 848")
    n_v = sum(1 for x in cti_rows if x[2] < 0.2)
    S["tcc"] = {"points": len(sel), "a3_no_trip": blind, "a3_upstream_first": upstream_first, "cti_cases": len(cti_rows), "cti_violations": n_v,
                "cti_by_pen": {str(p): {t: (float(np.median([x[2] for x in cti_rows if x[0] == p and x[1] == t]))
                                            if any(x[0] == p and x[1] == t for x in cti_rows) else None)
                                        for t in ("None", "SG", "IBR")} for p in PENS},
                "violations_by_pen": {str(p): sum(1 for x in cti_rows if x[0] == p and x[2] < 0.2) for p in PENS},
                "cases_by_pen": {str(p): sum(1 for x in cti_rows if x[0] == p) for p in PENS},
                "pickup_A3_51P": a3["pu51P"], "pickup_A2_51P": a2["pu51P"]}
    caption(fig, f"Figure 1. Left: IEC Standard Inverse 51P curves of A3 (primary) and A2 (backup) with the operating points of {len(sel)} three-phase cases (phase-element trips only). "
                 f"Points move left toward the pickup as DER penetration rises; {blind} cases, all in the islanded microgrid, fall below the A3 pickup and never trip (F-1); in {upstream_first} cases A3 is above pickup but another relay clears the fault first. "
                 f"Right: margin between the A2 and A3 operating times (actual trip, or curve time when the relay was not first) for {len(cti_rows)} cases; {n_v} fall below the 0.2 s CTI limit (F-3).")
    save(fig, "fig1_tcc_overlay")


# ================================================================ Figure 2: heatmaps
def fig_heatmap(R, S):
    def rate(rows):
        return 100.0 * sum(failed(r) for r in rows) / len(rows) if rows else np.nan
    loads = [40, 70, 100]
    rfs = [0, 5, 20, 50]
    H1 = [r for r in R if r["campaign"] == "H1" and r["cls"] == "OCR"]
    H2 = [r for r in R if r["campaign"] in ("H1", "H2") and r["cls"] == "OCR" and r["load_pct"] == 100]
    M1 = np.array([[rate([r for r in H1 if r["pen"] == p and r["load_pct"] == L]) for p in PENS] for L in loads])
    M2 = np.array([[rate([r for r in H2 if r["pen"] == p and r["rf"] == rf]) for p in PENS] for rf in rfs])
    N1 = np.array([[len([r for r in H1 if r["pen"] == p and r["load_pct"] == L]) for p in PENS] for L in loads])
    cmap = LinearSegmentedColormap.from_list("seq", [SURFACE] + SEQ[1:], N=256)
    fig, axs = plt.subplots(1, 2, figsize=(12.5, 4.2), gridspec_kw={"width_ratios": [1, 1]})
    vmax = max(np.nanmax(M1), np.nanmax(M2), 1)
    vmax = float(np.ceil(vmax / 10) * 10)
    for ax, M, ylabels, ttl, ylab in ((axs[0], M1, ["Daytime minimum 40%", "Intermediate 70%", "Evening peak 100%"], "a. Failure rate by DER penetration and load level", "Load level"),
                                       (axs[1], M2, ["0", "5", "20", "50"], "b. Failure rate by DER penetration and fault resistance", "Fault resistance Rf (Ω)")):
        im = ax.imshow(M, cmap=cmap, vmin=0, vmax=vmax, aspect="auto", origin="lower")
        ax.grid(False)
        for i in range(M.shape[0]):
            for j in range(M.shape[1]):
                v = M[i, j]
                if np.isnan(v):
                    continue
                ax.add_patch(plt.Rectangle((j - 0.5, i - 0.5), 1, 1, fill=False, edgecolor=SURFACE, lw=2))
                ax.text(j, i, f"{v:.0f}%", ha="center", va="center", fontsize=9,
                        color="#ffffff" if v > vmax * 0.55 else INK, fontweight="semibold")
        ax.set_xticks(range(len(PENS)), [f"{p}%" for p in PENS]); ax.set_yticks(range(len(ylabels)), ylabels)
        ax.set_xlabel("DER penetration (% of Feeder A peak load)"); ax.set_ylabel(ylab)
        ax.set_title(ttl)
        for s in ax.spines.values():
            s.set_visible(False)
    cb = fig.colorbar(im, ax=axs, fraction=0.025, pad=0.02)
    cb.set_label("Cases with at least one misoperation (%)", color=INK2); cb.outline.set_visible(False)
    # tipping point: first penetration where the evening-peak failure rate exceeds the baseline by 10 points
    base = M1[2, 0]
    tip = next((p for j, p in enumerate(PENS) if M1[2, j] - base >= 10), None)
    S["heatmap"] = {"load": {"rows": loads, "cols": PENS, "rate": M1.round(1).tolist(), "n": N1.tolist()},
                    "rf": {"rows": rfs, "cols": PENS, "rate": M2.round(1).tolist()},
                    "tipping_point_pen": tip, "baseline_rate": float(base)}
    caption(fig, f"Figure 2. Share of cases with at least one F-1 to F-5 misoperation (OCR, frozen baseline settings). Each cell pools "
                 f"10 DER placements (SG or IBR at 806, 828, 840, 848, B03) and 11 fault cases; the 0% column is the no-DER baseline. "
                 + (f"Under evening peak load the failure rate first exceeds the baseline by 10 points at {tip}% penetration (tipping point)." if tip is not None else ""), y=-0.03)
    save(fig, "fig2_failure_heatmap")


# ================================================================ Figure 3: stacked bars
def fig_escalation(R, S):
    pens = [0, 40, 80, 120]
    classes = ["OCR", "DOCR", "DIST", "DIFF"]

    def subset(cls, p):
        if cls == "OCR":
            return [r for r in R if r["campaign"] == "H1" and r["cls"] == "OCR" and r["load_pct"] == 100 and r["pen"] == p]
        return [r for r in R if r["campaign"] == "E" and r["cls"] == cls and r["pen"] == p]
    data = {}
    fig, ax = plt.subplots(figsize=(12.5, 4.8))
    gap, bw = 1.0, 0.8
    x = 0
    ticks, tlabels, groups = [], [], []
    for p in pens:
        x0 = x
        for cls in classes:
            rows = subset(cls, p)
            n = len(rows) or 1
            bottom = 0
            vals = {c: 100.0 * sum(1 for r in rows if r["counts"].get(c, 0)) / n for c in ALL}
            data[f"{cls}|{p}"] = {"n": len(rows), **{c: round(v, 1) for c, v in vals.items()},
                                  "any": round(100.0 * sum(failed(r) for r in rows) / n, 1)}
            for i, c in enumerate(ALL):
                v = vals[c]
                if v <= 0:
                    continue
                ax.bar(x, v, bw, bottom=bottom, color=CAT[i], edgecolor=SURFACE, linewidth=1.5, zorder=3)
                bottom += v
            ax.text(x, bottom + 1.2, f"{bottom:.0f}", ha="center", va="bottom", fontsize=8.5, color=INK)
            ticks.append(x); tlabels.append({"OCR": "OCR", "DOCR": "67", "DIST": "21", "DIFF": "87L"}[cls])
            x += 1
        groups.append(((x0 + x - 1) / 2, f"{p}% DER"))
        x += gap
    ax.set_xticks(ticks, tlabels)
    for gx, gl in groups:
        ax.text(gx, -0.13, gl, transform=ax.get_xaxis_transform(), ha="center", va="top", fontsize=9.5, color=INK, fontweight="semibold")
    ax.set_ylabel("Misoperation incidences per 100 cases")
    ax.set_title("Misoperation type by relay class: OCR 50/51, DOCR 67, Distance 21, Differential 87L")
    ax.grid(axis="x", visible=False)
    ax.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=CAT[i]) for i in range(6)],
              labels=[f"{c} {CODE_NAME[c]}" for c in ALL], loc="upper left", ncol=6, fontsize=8.5, bbox_to_anchor=(0, 1.0))
    ymax = max([sum(v[c] for c in ALL) for v in data.values()] + [10])
    ax.set_ylim(0, ymax * 1.25)
    S["escalation"] = data
    caption(fig, "Figure 3. Each bar stacks the share of cases showing each failure type (a case may show more than one, so totals can exceed the share of failed cases). "
                 "Same 10 DER placements x 11 fault cases per bar, evening peak load, Rf = 0. Raising the relay class changes which failure appears rather than removing it.", y=-0.06)
    save(fig, "fig3_relay_class_escalation")


# ================================================================ Figure 4: R-X + rose
def infeed(net, ied_meta, fault_bus, der_bus):
    """True when the DER connects to the relay-to-fault path strictly between the relay and the fault."""
    from engine.network import path_from_source
    if der_bus in ("none", None):
        return False
    pf, _ = path_from_source(net, fault_bus)
    pd, _ = path_from_source(net, der_bus)
    if not pf or not pd:
        return False
    j = 0
    while j < min(len(pf), len(pd)) and pf[j] == pd[j]:
        j += 1
    junction = j - 1
    try:
        ir = pf.index(ied_meta["to"])
    except ValueError:
        return False
    return ir <= junction < len(pf) - 1

def fig_rx_rose(R, S):
    dist = [r for r in R if r["cls"] == "DIST" and r["campaign"] == "E"]
    f5 = defaultdict(int)
    for r in dist:
        for f in r["findings"]:
            if f["code"] == "F-5":
                f5[(f["ied"], r["bus"])] += 1
    ied, bus = max(f5, key=f5.get) if f5 else ("A1", "812")
    rows = [r for r in dist if r["bus"] == bus and ied in r["rx"]]
    fig = plt.figure(figsize=(13.5, 4.9))
    ax = fig.add_axes([0.04, 0.1, 0.36, 0.8])
    zr = rows[0]["ieds"][ied]["zreach"] if rows else [1, 2, 3]
    meta = {d["id"]: d for d in base_network()["ieds"]}
    net = base_network()
    Z1t, _, _ = _zline(net, meta[ied]["from"], bus)
    ang = np.angle(Z1t)
    for i, (reach, nm) in enumerate(zip(zr, ("Zone 1", "Zone 2", "Zone 3"))):
        c = reach / 2 * np.exp(1j * ang)
        ax.add_patch(Circle((c.real, c.imag), reach / 2, fill=False, edgecolor=INK if i == 0 else MUTED, lw=1.4 if i == 0 else 1.0, ls="-" if i == 0 else "--", zorder=2))
        top = c + 1j * reach / 2
        ax.text(top.real, top.imag + 0.12, nm, fontsize=8.5, color=INK2, ha="center", va="bottom", bbox=dict(boxstyle="round,pad=0.15", fc=SURFACE, ec="none"))
    ax.plot([0, Z1t.real], [0, Z1t.imag], color=INK, lw=1, zorder=3)
    ax.scatter([Z1t.real], [Z1t.imag], marker="*", s=110, color=CRIT, zorder=6)
    ax.annotate(f"Actual fault location ({bus})\n|Z| = {abs(Z1t):.1f} Ω", (Z1t.real, Z1t.imag), xytext=(-75, -62), textcoords="offset points", fontsize=8.5, color=INK, arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.8), bbox=dict(boxstyle="round,pad=0.2", fc=SURFACE, ec="none"))
    ends = []
    for r in sorted(rows, key=lambda r: infeed(net, meta[ied], bus, r["site"])):
        pts = np.array(r["rx"][ied])
        if len(pts) < 3:
            continue
        inf = infeed(net, meta[ied], bus, r["site"])
        col = ORD7[PENS.index(r["pen"])] if inf else "#c9c8c2"
        ax.plot(pts[:, 0], pts[:, 1], color=col, lw=1.0 if inf else 0.7, alpha=0.8 if inf else 0.5, zorder=4 if inf else 3)
        e = pts[len(pts) // 2:].mean(axis=0)
        ax.scatter(e[0], e[1], s=20 if inf else 10, color=col, edgecolor=SURFACE, linewidth=0.6, zorder=5 if inf else 3)
        ends.append((r["pen"], r["tech"], float(np.hypot(*e)), r["counts"].get("F-5", 0) > 0, inf))
    lim = max(zr)
    ax.set_xlim(-lim * 0.25, lim * 1.02); ax.set_ylim(-lim * 0.42, lim * 0.8); ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("R (Ω)"); ax.set_ylabel("X (Ω)")
    ax.set_title(f"a. Apparent impedance at {ied}, faults at {bus} (Distance 21)")
    ax.legend(handles=[Line2D([], [], marker="o", ls="", color=ORD7[PENS.index(p)], label=f"{p}% DER, infeed between relay and fault") for p in (40, 80, 120)]
              + [Line2D([], [], marker="o", ls="", color="#c9c8c2", label="No DER or DER elsewhere")], loc="lower right", fontsize=7.5,
              frameon=True, facecolor=SURFACE, edgecolor="none", framealpha=0.9)
    # polar rose: phase angle seen by 67P for reverse faults with current above pickup
    groups = {"SG": [], "IBR": []}
    for r in R:
        if r["cls"] != "DOCR":
            continue
        t = tech_of(r)
        if t not in groups:
            continue
        for iid, d in r["ieds"].items():
            if d["fwd"]:
                continue
            for k in range(3):                      # every phase whose current exceeds the 67P pickup
                a_ = (d.get("ang3") or [None] * 3)[k]
                if a_ is not None and (d.get("i3m") or [0] * 3)[k] > d["pu51P"]:
                    groups[t].append(a_)
    S["rose"] = {}
    for k, (t, col) in enumerate((("SG", CAT[0]), ("IBR", CAT[1]))):
        px = fig.add_axes([0.47 + k * 0.28, 0.1, 0.2, 0.68], projection="polar")
        a = np.array(groups[t])
        bins = np.radians(np.arange(-180, 181, 15))
        hst, _ = np.histogram(np.radians(a), bins=bins)
        frac = hst / max(len(a), 1) * 100
        px.bar(bins[:-1] + np.radians(7.5), frac, width=np.radians(15) * 0.92, color=col, edgecolor=SURFACE, linewidth=1, zorder=3)
        rmax = max(frac.max() if len(frac) else 1, 5) * 1.1
        px.bar(0, rmax, width=np.pi, color="#fbe9e8", zorder=0)
        px.set_ylim(0, rmax)
        px.set_theta_zero_location("E"); px.set_theta_direction(1)
        px.set_thetagrids(range(0, 360, 45), ["0°", "45°", "90°", "135°", "±180°", "-135°", "-90°", "-45°"], color=INK2, fontsize=8)
        px.tick_params(axis="y", labelsize=7, labelcolor=MUTED)
        px.grid(color=GRID)
        fwd = float(np.mean(np.cos(np.radians(a)) > 0.05) * 100) if len(a) else 0.0
        px.set_title(f"{'b' if k == 0 else 'c'}. {('Synchronous generator' if t == 'SG' else 'Inverter-based (IBR)')} DER\n"
                     f"{fwd:.0f}% of {len(a)} reverse-fault phase samples read FORWARD", fontsize=10, loc="center", pad=16)
        S["rose"][t] = {"n": int(len(a)), "forward_pct": round(fwd, 1), "hist_pct": frac.round(2).tolist(), "bins_deg": list(range(-180, 180, 15))}
    fig.text(0.59, 0.02, "Shaded half-plane: angle region declared FORWARD by the quadrature 67P element (MTA 45°). Correct reverse readings sit near ±180°.",
             ha="left", fontsize=8.5, color=INK2)
    S["rx"] = {"ied": ied, "bus": bus, "z_true": float(abs(Z1t)), "zreach": zr,
               "by_pen": {str(p): (float(np.median([e[2] for e in ends if e[0] == p and (e[4] or p == 0)])) if any(e[0] == p and (e[4] or p == 0) for e in ends) else None) for p in PENS},
               "f5_cases": int(sum(1 for e in ends if e[3])), "cases": len(ends),
               "infeed_cases": int(sum(1 for e in ends if e[4])), "f5_infeed": int(sum(1 for e in ends if e[3] and e[4]))}
    caption(fig, f"Figure 4. a: {len(ends)} apparent-impedance trajectories of {ied} (faulted loop, sampled every 2 ms) for faults at {bus}, with the mho zones of the frozen settings; colored traces have DER infeed between relay and fault; "
                 f"DER infeed between the relay and the fault pushes the measured impedance outward and out of Zone 1 (F-5). b, c: angle of each phase current above pickup relative to its "
                 f"quadrature polarizing voltage for faults BEHIND the relay with current above pickup; inverter-controlled current scatters into the forward half-plane (F-4).", y=-0.01)
    save(fig, "fig4_rx_envelope_polar_rose")


# ================================================================ Figure 5: confusion
def fig_confusion(R, S):
    rows = [r for r in R if r["cls"] == "OCR" and r["campaign"] in ("H1", "H2")]

    def agg(rs):
        c = {"TP": 0, "TN": 0, "FP": 0, "FN": 0}
        for r in rs:
            for k in c:
                c[k] += r["confusion"][k]
        dep = c["TP"] / (c["TP"] + c["FN"]) if c["TP"] + c["FN"] else np.nan
        sec = c["TN"] / (c["TN"] + c["FP"]) if c["TN"] + c["FP"] else np.nan
        return c, dep, sec
    base = agg([r for r in rows if r["pen"] == 0])
    der = agg([r for r in rows if r["pen"] > 0])
    fig = plt.figure(figsize=(13, 4.4))
    for k, ((c, dep, sec), ttl) in enumerate(((base, "a. Baseline, no DER"), (der, "b. With DER, 20% to 120%"))):
        ax = fig.add_axes([0.06 + k * 0.25, 0.12, 0.19, 0.68])
        cells = [["TP", "FN"], ["FP", "TN"]]
        tot = sum(c.values())
        for i in range(2):
            for j in range(2):
                key = cells[i][j]
                good = key in ("TP", "TN")
                ax.add_patch(plt.Rectangle((j, 1 - i), 1, 1, facecolor="#e3eefb" if good else "#fbe3e2", edgecolor=SURFACE, lw=3))
                ax.text(j + 0.5, 1 - i + 0.58, f"{c[key]:,}", ha="center", va="center", fontsize=15, fontweight="semibold", color=INK)
                ax.text(j + 0.5, 1 - i + 0.3, f"{key}  ({100 * c[key] / tot:.1f}%)", ha="center", va="center", fontsize=8.5, color=INK2)
        ax.set_xlim(0, 2); ax.set_ylim(0, 2); ax.grid(False)
        ax.set_xticks([0.5, 1.5], ["Tripped", "Did not trip"]); ax.set_yticks([1.5, 0.5], ["Should trip", "Should not trip"] if k == 0 else ["", ""])
        ax.tick_params(length=0)
        for s in ax.spines.values():
            s.set_visible(False)
        ax.xaxis.set_label_position("top"); ax.xaxis.tick_top()
        ax.set_title(f"{ttl}\nDependability {dep * 100:.1f}%, Security {sec * 100:.1f}%", pad=24, fontsize=10.5)
    bx = fig.add_axes([0.6, 0.14, 0.38, 0.66])
    deps, secs = [], []
    for p in PENS:
        _, d, s_ = agg([r for r in rows if r["pen"] == p])
        deps.append(d * 100); secs.append(s_ * 100)
    bx.plot(PENS, deps, color=CAT[0], marker="o", markersize=5, markeredgecolor=SURFACE)
    bx.plot(PENS, secs, color=CAT[1], marker="o", markersize=5, markeredgecolor=SURFACE)
    bx.text(PENS[-1] + 3, deps[-1], f"Dependability {deps[-1]:.0f}%", color=INK, fontsize=8.5, va="center")
    bx.text(PENS[-1] + 3, secs[-1], f"Security {secs[-1]:.0f}%", color=INK, fontsize=8.5, va="center")
    bx.set_xlim(-5, 150); bx.set_xticks(PENS); lo = min(deps + secs)
    bx.set_ylim(max(0, np.floor(lo / 10) * 10 - 5), 101)
    bx.set_xlabel("DER penetration (% of Feeder A peak load)"); bx.set_ylabel("Ratio (%)")
    bx.set_title("c. Dependability and security versus DER penetration")
    bx.legend(handles=[Line2D([], [], color=CAT[0], label="Dependability TP/(TP+FN)"), Line2D([], [], color=CAT[1], label="Security TN/(TN+FP)")], loc="lower left")
    S["confusion"] = {"baseline": {**base[0], "dependability": base[1], "security": base[2]},
                      "der": {**der[0], "dependability": der[1], "security": der[2]},
                      "by_pen": {str(p): {"dependability": deps[i], "security": secs[i]} for i, p in enumerate(PENS)}}
    caption(fig, f"Figure 5. Relay decisions over all OCR grid-connected cases ({len(rows):,} runs, 5 relays each). TP: relay that should trip tripped; FN: it did not (F-1, F-4 erode dependability); "
                 f"FP: a relay that should not trip tripped (F-2, F-3 erode security).", y=0.0)
    save(fig, "fig5_confusion_matrix")


def write_table(R):
    with open(os.path.join(BATCH, "postrun_tables.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["campaign", "der_placement", "der_tech", "der_site", "der_penetration_pct", "load_pct", "rf_ohm", "fault_bus", "fault_type",
                    "relay_class", "primary", "backup", "fault_current_A", *ALL, "TP", "TN", "FP", "FN", "findings"])
        for r in sorted(R, key=lambda r: (r["campaign"], r["cls"], r["fleet"], r["pen"], r["load_pct"], r["rf"], r["bus"], r["ftype"])):
            w.writerow([r["campaign"], r["fleet"], r["tech"], r["site"], r["pen"], r["load_pct"], r["rf"], r["bus"], r["ftype"], r["cls"],
                        r["primary"], r["backup"], r["If"], *[r["counts"].get(c, 0) for c in ALL],
                        *[r["confusion"][k] for k in ("TP", "TN", "FP", "FN")], " | ".join(f"{x['code']} {x['title']}" for x in r["findings"])])


def main():
    R = load()
    print(f"[postrun] {len(R)} runs loaded")
    S = {"runs": len(R), "by_campaign": {c: sum(1 for r in R if r["campaign"] == c) for c in ("H1", "H2", "E", "I")}}
    tot = defaultdict(int)
    for r in R:
        for c in ALL:
            tot[c] += r["counts"].get(c, 0)
    S["totals"] = dict(tot)
    S["failed_runs"] = sum(failed(r) for r in R)
    isl = [r for r in R if r["campaign"] == "I"]
    S["islanded"] = {"runs": len(isl), "failed": sum(failed(r) for r in isl),
                     **{c: sum(1 for r in isl if r["counts"].get(c, 0)) for c in ALL}}
    fig_tcc(R, S)
    fig_heatmap(R, S)
    fig_escalation(R, S)
    fig_rx_rose(R, S)
    fig_confusion(R, S)
    write_table(R)

    def clean(o):
        if isinstance(o, dict):
            return {str(k): clean(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [clean(v) for v in o]
        if isinstance(o, (float, np.floating)):
            return None if not np.isfinite(o) else round(float(o), 4)
        if isinstance(o, np.integer):
            return int(o)
        return o
    with open(os.path.join(BATCH, "postrun_summary.json"), "w") as f:
        json.dump(clean(S), f, indent=1)
    print(f"[postrun] figures written to {FIG}")


if __name__ == "__main__":
    main()
