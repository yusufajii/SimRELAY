"""Additional figures for the revised paper: UI-based network diagram and statistical plots.

Uses the style, data and helpers of figures.py. Run:
    python figures_stats.py [network_ui conf site matrix delay backfeed]
figures/sld_ui_raw.png is the single-line diagram exported from the SimRELAY interface
(candidate DER sites, GFM site and fault locations highlighted).
"""
import os
import sys

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.lines import Line2D

from figures import (R, OUT, COL, DCOL, P, D, CODES, CODE_COL, HEAT, CAMP, legend_below, save, rate)

SITES = ["806", "828", "840", "848", "B03"]
GRID_SETS = ("H1", "H2")


# ------------------------------------------------------------------ Fig. 1: SLD exported from the SimRELAY interface
def fig_network_ui():
    img = plt.imread(os.path.join(OUT, "sld_ui_raw.png"))
    h, w = img.shape[:2]
    leg = 0.32
    H = DCOL * h / w + leg
    fig = plt.figure(figsize=(DCOL, H))
    ax = fig.add_axes([0, leg / H, 1, 1 - leg / H])
    ax.imshow(img, interpolation="lanczos")
    ax.axis("off")
    from matplotlib.patches import Circle, Rectangle
    from matplotlib.legend_handler import HandlerPatch

    class Ring(HandlerPatch):
        def create_artists(self, legend, orig, xd, yd, w, h, fs, trans):
            c = Circle((w / 2 - xd, h / 2 - yd), h * 0.75, fill=False, ec=orig.get_edgecolor(), lw=1.0, ls=(0, (2.5, 1.6)),
                       transform=trans)
            return [c]

    hs = [Circle((0, 0), 1, fill=False, ec="#5fae72"), Circle((0, 0), 1, fill=False, ec="#9a7cc9"),
          Circle((0, 0), 1, fill=False, ec="#e07272"),
          Rectangle((0, 0), 1, 1, fc="white", ec="#c9a04a", lw=0.9), Rectangle((0, 0), 1, 1, fc="#6b6b6b", ec="#333333")]
    hmap = {hs[0]: Ring(), hs[1]: Ring(), hs[2]: Ring()}
    fig.legend(hs, ["candidate DER site", "GFM site (islanded set)", "candidate fault location", "relay (IED)",
                    "breaker or recloser"], loc="lower center", ncol=5, frameon=False, bbox_to_anchor=(0.5, 0.0),
               handlelength=1.4, handleheight=1.0, columnspacing=1.6, handletextpad=0.5, handler_map=hmap)
    fig.savefig(os.path.join(OUT, "fig1_network.png"), dpi=450)
    plt.close(fig)
    print("wrote fig1_network (UI)")


# ------------------------------------------------------------------ confusion matrices
def fig_conf():
    grid = [r for r in R if r["campaign"] != "I"]
    fig, axs = plt.subplots(1, 2, figsize=(COL, 1.8))
    fig.subplots_adjust(left=0.17, right=0.98, top=0.87, bottom=0.2, wspace=0.55)
    cmap = LinearSegmentedColormap.from_list("pc", ["#FFFFFF", "#F3DCC8", "#E7B49B"])
    for ax, S, tag in ((axs[0], [r for r in grid if r["fleet"] == "none"], "(a) without DER"),
                       (axs[1], [r for r in grid if r["fleet"] != "none"], "(b) with DER")):
        cm = {"TP": 0, "TN": 0, "FP": 0, "FN": 0}
        for r in S:
            for k, v in (r.get("confusion") or {}).items():
                cm[k] += v
        M = np.array([[cm["TP"], cm["FN"]], [cm["FP"], cm["TN"]]], float)
        Rn = M / M.sum(axis=1, keepdims=True) * 100
        ax.imshow(Rn, cmap=cmap, vmin=0, vmax=100)
        for i in range(2):
            for j in range(2):
                ax.text(j, i, f"{int(M[i, j]):,}\n{Rn[i, j]:.1f}%", ha="center", va="center", fontsize=5.8)
        ax.set_xticks([0, 1], ["trip", "no trip"])
        ax.set_yticks([0, 1], ["should\ntrip", "should\nnot trip"])
        ax.set_xlabel("relay decision", fontsize=6.2)
        ax.set_title(tag, fontsize=6.5, pad=3)
        for s in ax.spines.values():
            s.set_color("#999999")
        print(tag, cm)
    save(fig, "fig9_conf")


# ------------------------------------------------------------------ codes by DER site
def fig_site():
    S0 = [r for r in R if r["campaign"] in GRID_SETS and r["fleet"] != "none"]
    fig, ax = plt.subplots(figsize=(COL, 2.25))
    fig.subplots_adjust(left=0.13, right=0.99, top=0.97, bottom=0.3)
    x = np.arange(len(SITES))
    for k, tech in enumerate(("SG", "IBR-GFL")):
        bottom = np.zeros(len(SITES))
        for c in CODES:
            v = np.array([100 * sum(1 for r in S0 if r["site"] == s and r["tech"] == tech and r["counts"].get(c, 0))
                          / max(1, sum(1 for r in S0 if r["site"] == s and r["tech"] == tech)) for s in SITES])
            ax.bar(x + (k - 0.5) * 0.4, v, 0.38, bottom=bottom, color=CODE_COL[c], edgecolor="white", lw=0.3)
            bottom += v
        for xi, b in zip(x, bottom):
            ax.text(xi + (k - 0.5) * 0.4, b + 3, "SG" if k == 0 else "GFL", ha="center", va="bottom",
                    fontsize=4.8, rotation=90)
    ax.set_xticks(x, SITES)
    ax.set_xlabel("DER bus")
    ax.set_ylabel("share of cases (%)")
    ax.set_ylim(0, 100)
    ax.grid(True, axis="y"); ax.set_axisbelow(True)
    h = [plt.Rectangle((0, 0), 1, 1, fc=CODE_COL[c]) for c in CODES]
    legend_below(fig, h, CODES, ncol=7, y=0.0)
    save(fig, "fig10_site")


# ------------------------------------------------------------------ fault case x DER site
def fig_matrix():
    S0 = [r for r in R if r["campaign"] in GRID_SETS and r["fleet"] != "none"]
    cases = [(b, t) for b in ("812", "830", "834", "848", "B04") for t in ("SLG", "3PH")] + [("822", "SLG")]
    M = np.array([[rate([r for r in S0 if r["site"] == s and r["bus"] == b and r["ftype"] == t], ("F-6",))
                   for s in SITES] for b, t in cases])
    fig, ax = plt.subplots(figsize=(COL, 2.7))
    fig.subplots_adjust(left=0.2, right=0.84, top=0.98, bottom=0.14)
    im = ax.imshow(M, cmap=HEAT, vmin=0, vmax=100, aspect="auto")
    for i in range(M.shape[0]):
        for j in range(M.shape[1]):
            ax.text(j, i, f"{M[i, j]:.0f}", ha="center", va="center", fontsize=5.8)
    ax.set_xticks(range(len(SITES)), SITES)
    ax.set_yticks(range(len(cases)), [f"{b} {t}" for b, t in cases])
    ax.set_xlabel("DER bus"); ax.set_ylabel("fault case")
    cax = fig.add_axes([0.87, 0.14, 0.025, 0.84])
    cb = fig.colorbar(im, cax=cax)
    cb.set_label("misoperation without F-6 (%)", fontsize=6); cb.ax.tick_params(labelsize=5.5)
    save(fig, "fig11_matrix")


# ------------------------------------------------------------------ F-1 primary trip delay
def fig_delay():
    A = {}
    for a in R:
        if a["fleet"] == "none":
            A[(a["campaign"], a["load"], a["rf"], a["bus"], a["ftype"], a["cls"])] = a
    pts = {"SG": [], "IBR-GFL": []}
    for r in R:
        if r["campaign"] not in GRID_SETS or r["fleet"] == "none" or not r["counts"].get("F-1", 0):
            continue
        a = A.get((r["campaign"], r["load"], r["rf"], r["bus"], r["ftype"], r["cls"]))
        p = r.get("primary")
        if not a or not p or a["ieds"][p]["t_trip"] is None:
            continue
        d1 = r["ieds"][p]["t_trip"]
        pts[r["tech"]].append((r["pen"], a["ieds"][p]["t_trip"], d1 if d1 is not None else 1.3))
    fig, ax = plt.subplots(figsize=(COL, 2.2))
    fig.subplots_adjust(left=0.14, right=0.98, top=0.97, bottom=0.3)
    hs = []
    rng = np.random.default_rng(1)
    for tech, c, mk, dx in (("SG", D["coral"], "o", -2.5), ("IBR-GFL", D["sage"], "o", 2.5)):
        arr = np.array(pts[tech])
        jit = (rng.random(len(arr)) - 0.5) * 3
        hs.append(ax.scatter(arr[:, 0] + dx + jit, arr[:, 2], s=7, color=c, marker=mk, alpha=0.7, lw=0))
    a0 = np.array([q[1] for v in pts.values() for q in v])
    hs.append(ax.axhline(np.median(a0), color=D["grey"], lw=0.8, ls=(0, (4, 2))))
    ax.axhline(1.3, color="#BBBBBB", lw=0.6, ls=(0, (1, 2)))
    ax.text(12, 1.34, "no trip within the run", fontsize=5.2, color="#666666")
    ax.set_xticks([20, 40, 60, 80, 100, 120]); ax.set_xlim(8, 132); ax.set_ylim(0, 1.45)
    ax.set_xlabel("DER penetration (%)"); ax.set_ylabel("primary trip delay (s)"); ax.grid(True)
    legend_below(fig, hs, ["SG", "GFL", "median without DER"], ncol=3, y=0.0)
    save(fig, "fig12_delay")
    allp = [q for v in pts.values() for q in v]
    print("F-1 points", {k: len(v) for k, v in pts.items()}, "median anchor", float(np.median(a0)),
          "median DER", float(np.median([q[2] for q in allp])), "no trip", sum(q[2] >= 1.3 for q in allp))


# ------------------------------------------------------------------ F-6 backfeed current
def fig_backfeed():
    data = {}
    for r in R:
        if r["campaign"] not in GRID_SETS or not r["counts"].get("F-6", 0):
            continue
        try:
            z = np.load(os.path.join(CAMP, "runs", r["run_id"], "wave.npz"))
        except Exception:
            continue
        t = z["t"]
        If = np.abs(z["Ifault"][:, 0, :]).max(axis=1)
        data.setdefault((r["tech"], r["pen"]), []).append(float(If[t >= t[-1] - 0.1].mean()))
    pens = [20, 40, 60, 80, 100, 120]
    fig, ax = plt.subplots(figsize=(COL, 2.2))
    fig.subplots_adjust(left=0.14, right=0.98, top=0.97, bottom=0.3)
    hs = []
    for k, (tech, c) in enumerate((("SG", P["coral"]), ("IBR-GFL", P["sage"]))):
        vals = [np.maximum(np.array(data.get((tech, p), [np.nan])), 0.1) for p in pens]
        bp = ax.boxplot(vals, positions=np.arange(len(pens)) + (k - 0.5) * 0.36, widths=0.3, patch_artist=True,
                        showfliers=False, medianprops=dict(color="#333333", lw=0.8),
                        whiskerprops=dict(lw=0.6, color="#666666"), capprops=dict(lw=0.6, color="#666666"))
        for b in bp["boxes"]:
            b.set_facecolor(c); b.set_edgecolor("#666666"); b.set_linewidth(0.6)
        hs.append(bp["boxes"][0])
    ax.set_yscale("log"); ax.set_ylim(0.1, 300)
    ax.set_yticks([0.1, 1, 10, 100], ["0.1", "1", "10", "100"])
    ax.set_xticks(range(len(pens)), [str(p) for p in pens])
    ax.set_xlabel("DER penetration (%)"); ax.set_ylabel("backfeed current (A)")
    ax.grid(True, axis="y")
    legend_below(fig, hs, ["SG", "GFL"], ncol=2, y=0.0)
    save(fig, "fig13_backfeed")
    allv = np.concatenate([np.array(v) for v in data.values()])
    print("F-6 n", len(allv), "median", float(np.median(allv)), ">5A", float((allv > 5).mean()))
    for p in pens:
        print(p, {t: round(float(np.median(data.get((t, p), [np.nan]))), 1) for t in ("SG", "IBR-GFL")})


if __name__ == "__main__":
    for n in sys.argv[1:] or ["network_ui", "conf", "site", "matrix", "delay", "backfeed"]:
        globals()["fig_" + n]()
