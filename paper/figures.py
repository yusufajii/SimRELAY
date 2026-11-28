"""Figures for the IEEE conference paper (PoU campaign, MATLAB Simulink phasor engine).

Style rules: white background, Courier New for every text, no blue base theme, pastel colours,
legend below each figure in one horizontal row, no overlapping elements.
"""
import gzip
import json
import os
import pickle
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Circle, Polygon
from matplotlib.colors import LinearSegmentedColormap

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
CAMP = os.path.join(ROOT, "campaigns", "PoU-TA-Proteksi-Adaptif")
OUT = os.path.join(ROOT, "paper", "figures")
os.makedirs(OUT, exist_ok=True)

plt.rcParams.update({
    "font.family": "Courier New", "font.size": 7, "axes.titlesize": 7, "axes.labelsize": 7,
    "xtick.labelsize": 6.5, "ytick.labelsize": 6.5, "legend.fontsize": 6.5,
    "figure.facecolor": "white", "axes.facecolor": "white", "savefig.facecolor": "white",
    "axes.edgecolor": "#555555", "axes.linewidth": 0.6, "grid.color": "#DDDDDD", "grid.linewidth": 0.5,
    "xtick.color": "#333333", "ytick.color": "#333333", "text.color": "#222222", "axes.labelcolor": "#222222",
    "mathtext.fontset": "custom", "mathtext.rm": "Courier New", "mathtext.it": "Courier New:italic",
})
COL = 3.5     # single IEEE column (in)
DCOL = 7.16   # double column

# pastel palette without blue
P = {"coral": "#E8907E", "peach": "#F2BE8C", "sand": "#E6D49A", "sage": "#A8CC95", "mint": "#9CCFB8",
     "lav": "#BFA8DC", "mauve": "#D79CC0", "clay": "#C4A184", "grey": "#A5A5A5", "rose": "#EDB0B0"}
D = {"coral": "#C4604D", "sage": "#5E9450", "mauve": "#A0628A", "clay": "#946B4C", "grey": "#6E6E6E", "amber": "#C98B2E"}
CODE_COL = {"F-1": P["coral"], "F-2": P["peach"], "F-3": P["sand"], "F-4": P["sage"], "F-5": P["lav"],
            "F-6": P["mauve"], "NT": P["clay"]}
CODES = ["F-1", "F-2", "F-3", "F-4", "F-5", "F-6", "NT"]
HEAT = LinearSegmentedColormap.from_list("pastel_heat", ["#FFFFFF", "#F6D7C3", "#EDA48F", "#D9786A"])


def legend_below(fig, handles, labels, ncol=None, y=0.0):
    fig.legend(handles, labels, loc="lower center", ncol=ncol or len(labels), frameon=False,
               bbox_to_anchor=(0.5, y), handlelength=1.8, columnspacing=1.4, handletextpad=0.5)


def save(fig, name):
    fig.savefig(os.path.join(OUT, name + ".png"), dpi=300)
    plt.close(fig)
    print("wrote", name)


# ------------------------------------------------------------------ data
def load_results():
    R = {}
    with open(os.path.join(CAMP, "results.jsonl"), encoding="utf-8") as f:
        for l in f:
            r = json.loads(l)
            R[r["key"]] = r
    return list(R.values())


R = load_results()
BYID = {r["run_id"]: r for r in R}


def failed(r, ex=()):
    return any(r["counts"].get(c, 0) for c in CODES if c not in ex)


def rate(S, ex=()):
    return 100.0 * sum(failed(r, ex) for r in S) / max(len(S), 1)


def anchor_of(r):
    for a in R:
        if a["fleet"] == "none" and (a["load"], a["rf"], a["bus"], a["ftype"], a["cls"]) == (
                r["load"], r["rf"], r["bus"], r["ftype"], r["cls"]):
            return a
    return None


def run_files(rid):
    rd = os.path.join(CAMP, "runs", rid)
    p = json.load(gzip.open(os.path.join(rd, "result.json.gz")))
    w = json.load(open(os.path.join(rd, "wave.json")))
    z = np.load(os.path.join(rd, "wave.npz"))
    return p, w, z


with open(os.path.join(ROOT, "cache", "settings.pkl"), "rb") as f:
    SET = pickle.load(f)[0]


# ------------------------------------------------------------------ Fig. 1  network
def fig_network():
    from engine.network import base_network
    net = base_network()
    B = net["buses"]
    fig, ax = plt.subplots(figsize=(DCOL, 2.75))
    fig.subplots_adjust(left=0.01, right=0.99, top=0.99, bottom=0.15)
    xy = {k: (v["x"], -v["y"]) for k, v in B.items()}
    for br in net["branches"]:
        a, b = br["from"], br["to"]
        if a not in xy or b not in xy:
            continue
        (x0, y0), (x1, y1) = xy[a], xy[b]
        if br["kind"] == "line":
            lw = 1.3 if br.get("phases", "abc") == "abc" else 0.7
            ls = "-" if br.get("phases", "abc") == "abc" else (0, (3, 1.5))
            ax.plot([x0, x1], [y0, y1], color="#4A4A4A", lw=lw, ls=ls, zorder=1, solid_capstyle="round")
        else:
            ax.plot([x0, x1], [y0, y1], color="#4A4A4A", lw=1.3, zorder=1)
            mx, my = (x0 + x1) / 2, (y0 + y1) / 2
            if br["kind"] == "reg":
                ax.add_patch(FancyBboxPatch((mx - 22, my - 16), 44, 32, boxstyle="round,pad=2",
                                            fc=P["sand"], ec="#7A6A3A", lw=0.6, zorder=3))
                ax.text(mx, my, "R", ha="center", va="center", fontsize=5.5, zorder=4)
            else:
                for dd in (-9, 9):
                    ax.add_patch(Circle((mx, my + dd) if x0 == x1 else (mx + dd, my), 13,
                                        fc="white", ec="#4A4A4A", lw=0.7, zorder=3))
    # buses
    for k, (x, y) in xy.items():
        ax.plot(x, y, "s", ms=2.2, color="#333333", zorder=5)
    # source
    x8, y8 = xy["800"]
    ax.add_patch(Circle((x8 - 75, y8), 26, fc="white", ec="#333333", lw=0.8, zorder=4))
    ax.text(x8 - 75, y8, "~", ha="center", va="center", fontsize=8, zorder=5)
    ax.plot([x8 - 49, x8], [y8, y8], color="#4A4A4A", lw=1.3, zorder=1)
    ax.text(x8 - 75, y8 + 48, "69/24.9 kV\n2.5 MVA", ha="center", va="bottom", fontsize=5)
    # bus labels (offsets chosen to avoid lines and symbols)
    off = {k: (0, 26, "center", "bottom") for k in xy}
    for k in ("810", "826", "856", "838", "888", "890", "862", "B05"):
        off[k] = (22, 0, "left", "center")
    for k in ("818", "820", "822", "864", "842", "844", "846", "848"):
        off[k] = (0, 26, "center", "bottom")
    for k in ("B01", "B02", "B04"):
        off[k] = (0, 26, "center", "bottom")
    off["B03"] = (-14, 26, "right", "bottom")
    for k in ("818", "842"):
        off[k] = (-22, 0, "right", "center")
    for k in ("816", "858"):
        off[k] = (0, -26, "center", "top")
    off["834"] = (14, -24, "left", "top")
    off["800"] = (-10, 26, "right", "bottom")
    for k, (x, y) in xy.items():
        dx, dy, ha, va = off[k]
        ax.text(x + dx, y + dy, k, fontsize=4.8, ha=ha, va=va, color="#333333", zorder=6)
    # IEDs (breaker or recloser) at 30 % of their branch from the source side
    for d in net["ieds"]:
        (x0, y0), (x1, y1) = xy[d["from"]], xy[d["to"]]
        f = 0.62 if d["id"] == "L1" else 0.4
        x, y = x0 + f * (x1 - x0), y0 + f * (y1 - y0)
        ax.add_patch(FancyBboxPatch((x - 20, y - 20), 40, 40, boxstyle="square,pad=0", fc=P["coral"],
                                    ec="#8A3F33", lw=0.7, zorder=7))
        lab = {"L1": (30, 0, "left", "center"), "B1": (30, 0, "left", "center"), "A1": (0, 34, "center", "bottom"), "A2": (0, 34, "center", "bottom")}
        lab_dx, lab_dy, ha, va = lab.get(d["id"], (0, -34, "center", "top"))
        ax.text(x + lab_dx, y + lab_dy, d["id"], fontsize=5.6, fontweight="bold", ha=ha, va=va, zorder=8)
    # DER candidate sites and the grid-forming unit of the islanded campaign
    for s in ("806", "828", "840", "848", "B03"):
        x, y = xy[s]
        ax.add_patch(Circle((x + 34, y - 40), 17, fc=P["sage"], ec="#4F7A44", lw=0.7, zorder=7))
        ax.plot([x, x + 34], [y, y - 23], color="#4F7A44", lw=0.6, zorder=6)
    x, y = xy["824"]
    ax.add_patch(Polygon([[x + 34, y - 20], [x + 52, y - 40], [x + 34, y - 60], [x + 16, y - 40]],
                         fc=P["lav"], ec="#6E5A92", lw=0.7, zorder=7))
    ax.plot([x, x + 34], [y, y - 20], color="#6E5A92", lw=0.6, zorder=6)
    # fault locations
    for s in ("812", "822", "830", "834", "848", "B04"):
        x, y = xy[s]
        ax.plot(x - 30, y - 38, marker=(7, 1, 0), ms=6.5, color=P["mauve"], mec="#7A3E66", mew=0.5, zorder=7)
        ax.plot([x, x - 30], [y, y - 30], color="#7A3E66", lw=0.5, zorder=6)
    ax.text(xy["B01"][0] + 60, xy["B01"][1] - 95, "Feeder B (equivalent)", fontsize=5.5, style="italic")
    ax.text(xy["802"][0] - 40, xy["802"][1] + 140, "Feeder A (IEEE 34-bus test feeder)", fontsize=5.5, style="italic")
    ax.set_aspect("equal")
    ax.axis("off")
    xs = [p[0] for p in xy.values()]; ys = [p[1] for p in xy.values()]
    ax.set_xlim(min(xs) - 130, max(xs) + 70)
    ax.set_ylim(min(ys) - 125, max(ys) + 60)
    h = [plt.Line2D([], [], color="#4A4A4A", lw=1.3), plt.Line2D([], [], color="#4A4A4A", lw=0.7, ls=(0, (3, 1.5))),
         plt.Line2D([], [], marker="s", ls="", ms=6, mfc=P["coral"], mec="#8A3F33"),
         plt.Line2D([], [], marker="o", ls="", ms=6, mfc=P["sage"], mec="#4F7A44"),
         plt.Line2D([], [], marker="D", ls="", ms=5, mfc=P["lav"], mec="#6E5A92"),
         plt.Line2D([], [], marker=(7, 1, 0), ls="", ms=7, mfc=P["mauve"], mec="#7A3E66"),
         plt.Line2D([], [], marker="s", ls="", ms=6, mfc=P["sand"], mec="#7A6A3A"),
         plt.Line2D([], [], marker="o", ls="", ms=6, mfc="white", mec="#4A4A4A")]
    legend_below(fig, h, ["3-phase line", "1-phase lateral", "relay and breaker", "DER site",
                          "GFM unit (islanded)", "fault location", "voltage regulator", "transformer"], ncol=4, y=0.0)
    save(fig, "fig1_network")


# ------------------------------------------------------------------ Fig. 2  method
def fig_method():
    fig, ax = plt.subplots(figsize=(COL, 3.35))
    fig.subplots_adjust(left=0.01, right=0.99, top=0.99, bottom=0.01)
    ax.set_xlim(0, 100); ax.set_ylim(5, 112); ax.axis("off")

    def box(x, y, w, h, title, body, fc):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.6,rounding_size=1.6", fc=fc,
                                    ec="#6A6A6A", lw=0.6))
        ax.text(x + w / 2, y + h - 2.4, title, ha="center", va="top", fontsize=6.2, fontweight="bold")
        ax.text(x + w / 2, y + h - 8.2, body, ha="center", va="top", fontsize=5.4, linespacing=1.25)

    def arrow(x0, y0, x1, y1):
        ax.annotate("", xy=(x1, y1), xytext=(x0, y0),
                    arrowprops=dict(arrowstyle="-|>", lw=0.7, color="#555555", shrinkA=0, shrinkB=0))

    box(3, 92, 94, 18, "Scenario space S",
        "DER type x site x size  |  load level x Rf\nfault bus x fault type  |  relay class\n5,247 cases in four campaigns", P["sand"])
    box(3, 66, 45, 21, "Phasor simulation",
        "IEEE 34-bus + feeder B\nSimscape Electrical\nphasor mode, dt=1/960 s\nfault at 0.3 s, T=1.6 s", P["peach"])
    box(52, 66, 45, 21, "Conventional relays",
        "settings frozen at\n0 % DER, peak load\n50/51, 67, 21, 87L\none-cycle phasor filter", P["peach"])
    box(3, 38, 45, 22, "Ground-truth oracle",
        "radial path 800 to fault\nprimary P, backup B\nhealthy relays outside\nthe path must not trip", P["sage"])
    box(52, 38, 45, 22, "No-DER anchor",
        "same load, Rf, fault and\nrelay class at 0 % DER\nreference clearing time\n(phase-1 MATLAB cases)", P["sage"])
    box(3, 7, 94, 25, "Fault Hunter classification",
        "F-1 blinding (missing or delayed trip)\nF-2 sympathetic trip   F-3 CTI violation\nF-4 directional error   F-5 under-reach\nF-6 sustained DER backfeed   NT nuisance trip\nconfusion matrix: dependability, security", P["mauve"])
    arrow(50, 92, 25.5, 87.8); arrow(50, 92, 74.5, 87.8)
    arrow(25.5, 66, 25.5, 60.8); arrow(74.5, 66, 74.5, 60.8)
    arrow(48.6, 76.5, 51.4, 76.5)
    arrow(25.5, 38, 35, 32.8); arrow(74.5, 38, 65, 32.8)
    save(fig, "fig2_method")


# ------------------------------------------------------------------ Fig. 3  rate and reliability indices
def fig_rate():
    H1 = [r for r in R if r["campaign"] == "H1"]
    pens = [0, 20, 40, 60, 80, 100, 120]
    fig, (a, b) = plt.subplots(1, 2, figsize=(DCOL, 2.25))
    fig.subplots_adjust(left=0.07, right=0.985, top=0.95, bottom=0.30, wspace=0.28)
    hs = []
    for tech, c, c2 in (("SG", D["coral"], "#E9A595"), ("IBR-GFL", D["sage"], "#A9D39A")):
        ya = [rate([r for r in H1 if r["pen"] == p and (p == 0 or r["tech"] == tech)]) for p in pens]
        yb = [rate([r for r in H1 if r["pen"] == p and (p == 0 or r["tech"] == tech)], ("F-6",)) for p in pens]
        hs.append(a.plot(pens, ya, color=c, marker="o", ms=3, lw=1.1)[0])
        hs.append(a.plot(pens, yb, color=c2, marker="o", ms=3, lw=1.1, ls=(0, (4, 2)))[0])
    a.set_xlabel("DER penetration (% of feeder A peak load)")
    a.set_ylabel("cases with misoperation (%)")
    a.set_xticks(pens); a.set_ylim(0, 75); a.grid(True)
    a.text(0.02, 0.97, "(a) OCR, campaign H1", transform=a.transAxes, va="top", fontsize=6.5)
    grid = [r for r in R if r["tech"] != "ISL"]
    dep, sec = [], []
    for p in pens:
        cm = {"TP": 0, "TN": 0, "FP": 0, "FN": 0}
        for r in grid:
            if r["pen"] == p:
                for k, v in (r.get("confusion") or {}).items():
                    cm[k] += v
        dep.append(100 * cm["TP"] / (cm["TP"] + cm["FN"])); sec.append(100 * cm["TN"] / (cm["TN"] + cm["FP"]))
    hd = b.plot(pens, dep, color=D["mauve"], marker="o", ms=3, lw=1.1)[0]
    hsx = b.plot(pens, sec, color=D["amber"], marker="o", ms=3, lw=1.1)[0]
    b.set_xlabel("DER penetration (% of feeder A peak load)")
    b.set_ylabel("index (%)"); b.set_xticks(pens); b.set_ylim(94, 100.5); b.grid(True)
    b.text(0.98, 0.97, "(b) all grid-connected cases", transform=b.transAxes, va="top", ha="right", fontsize=6.5)
    legend_below(fig, hs + [hd, hsx], ["SG, all codes", "SG, without F-6", "GFL, all codes", "GFL, without F-6",
                                       "dependability", "security"], ncol=6, y=0.0)
    save(fig, "fig3_rate")


# ------------------------------------------------------------------ Fig. 4  heat maps
def fig_heat():
    H1 = [r for r in R if r["campaign"] == "H1"]; H2 = [r for r in R if r["campaign"] == "H2"]
    pens = [0, 20, 40, 60, 80, 100, 120]
    A = np.array([[rate([r for r in H1 if r["pen"] == p and r["load_pct"] == l], ("F-6",)) for p in pens] for l in (40, 70, 100)])
    Bm = np.array([[rate([r for r in (H1 if rf == 0 else H2) if r["pen"] == p and r["rf"] == rf and r["load_pct"] == 100], ("F-6",))
                    for p in pens] for rf in (0, 5, 20, 50)])
    fig, axs = plt.subplots(1, 2, figsize=(DCOL, 1.95))
    fig.subplots_adjust(left=0.075, right=0.92, top=0.93, bottom=0.25, wspace=0.22)
    for ax, M, ylab, yt, tag in ((axs[0], A, "load level (%)", ["40", "70", "100"], "(a) penetration x load, Rf = 0"),
                                 (axs[1], Bm, "fault resistance (ohm)", ["0", "5", "20", "50"], "(b) penetration x Rf, peak load")):
        im = ax.imshow(M, cmap=HEAT, vmin=0, vmax=45, aspect="auto", origin="lower")
        ax.set_xticks(range(len(pens)), [str(p) for p in pens]); ax.set_yticks(range(len(yt)), yt)
        ax.set_xlabel("DER penetration (%)"); ax.set_ylabel(ylab)
        for i in range(M.shape[0]):
            for j in range(M.shape[1]):
                ax.text(j, i, f"{M[i, j]:.0f}", ha="center", va="center", fontsize=6)
        ax.set_title(tag, fontsize=6.5, pad=3)
    cax = fig.add_axes([0.935, 0.25, 0.012, 0.68])
    cb = fig.colorbar(im, cax=cax); cb.set_label("misoperation without F-6 (%)", fontsize=6); cb.ax.tick_params(labelsize=5.5)
    save(fig, "fig4_heat")


# ------------------------------------------------------------------ Fig. 5  relay classes
def fig_class():
    H1 = [r for r in R if r["campaign"] == "H1"]; E = [r for r in R if r["campaign"] == "E"]
    fig, ax = plt.subplots(figsize=(COL, 2.45))
    fig.subplots_adjust(left=0.13, right=0.99, top=0.97, bottom=0.33)
    labels, x = [], 0
    xs = []
    for cls in ("OCR", "DOCR", "DIST", "DIFF"):
        for pen in (40, 80, 120):
            S = [r for r in (H1 if cls == "OCR" else E) if r["cls"] == cls and r["pen"] == pen
                 and r["load_pct"] == 100 and r["rf"] == 0]
            bottom = 0
            for c in CODES:
                n = 100 * sum(1 for r in S if r["counts"].get(c, 0)) / len(S)
                ax.bar(x, n, 0.75, bottom=bottom, color=CODE_COL[c], edgecolor="white", lw=0.3)
                bottom += n
            xs.append(x); labels.append(str(pen)); x += 1
        x += 0.6
    ax.set_xticks(xs, labels, fontsize=6)
    for i, cls in enumerate(("OCR", "DOCR", "DIST", "DIFF")):
        ax.text(xs[3 * i + 1], -0.125, cls, transform=ax.get_xaxis_transform(), ha="center", va="top", fontsize=6.5, fontweight="bold")
    ax.set_ylabel("share of cases (%)"); ax.set_ylim(0, 80)
    ax.set_xlabel("DER penetration (%) per relay class", labelpad=17)
    ax.grid(True, axis="y"); ax.set_axisbelow(True)
    h = [plt.Rectangle((0, 0), 1, 1, fc=CODE_COL[c]) for c in CODES]
    legend_below(fig, h, CODES, ncol=7, y=0.0)
    save(fig, "fig5_class")


# ------------------------------------------------------------------ Fig. 6  waveform of a delayed and backfed fault
def fig_wave(rid="PoU-3369"):
    r = BYID[rid]; a = anchor_of(r)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(DCOL, 2.2))
    fig.subplots_adjust(left=0.07, right=0.985, top=0.95, bottom=0.30, wspace=0.25)
    hs = []
    for run, c, ls, lab in ((r, D["coral"], "-", "with DER"), (a, D["grey"], (0, (4, 2)), "without DER")):
        p, w, z = run_files(run["run_id"])
        t = z["t"]
        j = w["ied_ids"].index("A1"); br = w["ied_br"][j]
        I = z["Ib"][:, br * 3:(br + 1) * 3] if z["Ib"].shape[1] == 114 else None
        k = w["br_index"]["L800-802"]
        I = z["Ib"][:, 3 * k:3 * k + 3]
        I3 = np.abs(I.sum(axis=1))
        If = np.abs(z["Ifault"][:, 0, :]).max(axis=1)
        hs.append(ax1.plot(t, I3, color=c, lw=1.0, ls=ls)[0])
        ax2.plot(t, If, color=c, lw=1.0, ls=ls)
    s = SET["A1"]
    hp = ax1.axhline(s["51N_pu"], color=D["amber"], lw=0.8, ls=(0, (1, 1.5)))
    hi = ax1.axhline(s["50N_pu"], color=D["mauve"], lw=0.8, ls=(0, (1, 1.5)))
    for ax in (ax1, ax2):
        ax.set_xlim(0.2, 1.6); ax.grid(True); ax.set_xlabel("time (s)")
    ax1.set_ylabel("A1 3I0 (A rms)"); ax2.set_ylabel("fault current (A rms)")
    ax1.set_ylim(0, 420); ax2.set_yscale("log"); ax2.set_ylim(1, 1000)
    ax1.text(0.98, 0.97, "(a) relay A1", transform=ax1.transAxes, ha="right", va="top", fontsize=6.5)
    ax2.text(0.98, 0.97, "(b) fault at 812", transform=ax2.transAxes, ha="right", va="top", fontsize=6.5)
    t_open = 0.3 + r["ieds"]["A1"]["t_trip"] + 0.05      # trip from inception plus breaker time
    ax1.annotate("delayed 51N trip", xy=(t_open - 0.005, 150), xytext=(1.18, 250), fontsize=5.6, va="center",
                 arrowprops=dict(arrowstyle="-|>", lw=0.5, color="#555555"))
    ax2.annotate("A1 opens", xy=(t_open - 0.005, 200), xytext=(0.62, 40), fontsize=5.6, va="center",
                 arrowprops=dict(arrowstyle="-|>", lw=0.5, color="#555555"))
    ax2.annotate("DER backfeed", xy=(1.32, 66), xytext=(1.2, 12), fontsize=5.6, va="center",
                 arrowprops=dict(arrowstyle="-|>", lw=0.5, color="#555555"))
    legend_below(fig, hs + [hp, hi], [f"with DER ({r['tech'].replace('IBR-', '')} {r['pen']} % at {r['site']})", "without DER (anchor)",
                                      "51N pickup", "50N pickup"], ncol=4, y=0.0)
    save(fig, "fig6_wave")


# ------------------------------------------------------------------ Fig. 7  TCC
def fig_tcc(rid="PoU-0951"):
    from engine.relays import t_op
    r = BYID[rid]; a = anchor_of(r)
    fig, ax = plt.subplots(figsize=(COL, 2.75))
    fig.subplots_adjust(left=0.15, right=0.97, top=0.97, bottom=0.33)
    I = np.logspace(1, 3.6, 600)
    cols = {"A1": D["grey"], "A2": D["coral"], "A3": D["sage"]}
    T_INST = 0.0146          # measured instantaneous operating time (one-cycle filter)
    hs, labs = [], []
    for iid in ("A1", "A2", "A3"):
        s = SET[iid]
        t = np.array([t_op("IEC_SI", s["51N_tms"], x / s["51N_pu"]) for x in I])
        if s.get("50N_pu"):
            t = np.where(I >= s["50N_pu"], T_INST, t)
        hs.append(ax.plot(I, t, color=cols[iid], lw=1.1)[0])
        labs.append(f"{iid} 51N" + ("/50N" if s.get("50N_pu") else ""))
    # A3 has no 50N; markers: measured trips, and the time A3 would have needed with DER
    da, dr = a["ieds"], r["ieds"]
    m1 = ax.plot(da["A3"]["I3I0"], da["A3"]["t_trip"], "o", ms=5, mfc=cols["A3"], mec=cols["A3"])[0]
    m2 = ax.plot(dr["A2"]["I3I0"], dr["A2"]["t_trip"], "o", ms=5, mfc=cols["A2"], mec=cols["A2"])[0]
    t3 = t_op("IEC_SI", SET["A3"]["51N_tms"], dr["A3"]["I3I0"] / SET["A3"]["51N_pu"])
    m3 = ax.plot(dr["A3"]["I3I0"], t3, "o", ms=5, mfc=P["mauve"], mec=D["mauve"])[0]
    ax.annotate("", xy=(dr["A2"]["I3I0"], dr["A2"]["t_trip"] * 1.15), xytext=(da["A2"]["I3I0"], 0.55),
                arrowprops=dict(arrowstyle="-|>", lw=0.5, color="#555555", ls=(0, (2, 1.5))))
    ax.plot(da["A2"]["I3I0"], 0.55, "o", ms=3, color=cols["A2"])
    hs += [m1, m2, m3]
    labs += ["A3 trip, no DER", "A2 trip, GFL 40 % at 828", "A3 needed time, with DER"]
    ax.set_xscale("log"); ax.set_yscale("log"); ax.set_xlim(10, 4000); ax.set_ylim(0.01, 20)
    ax.set_xlabel("residual current 3I0 (A rms)"); ax.set_ylabel("operating time (s)")
    ax.grid(True, which="both")
    legend_below(fig, hs, labs, ncol=2, y=0.0)
    save(fig, "fig7_tcc")


# ------------------------------------------------------------------ Fig. 8  R-X plane
def fig_rx(rid="PoU-4440", iid="A3"):
    r = BYID[rid]; a = anchor_of(r)
    s = SET[iid]
    ang = s["ang1"]
    fig, ax = plt.subplots(figsize=(COL, 3.0))
    fig.subplots_adjust(left=0.15, right=0.97, top=0.97, bottom=0.27)
    th = np.linspace(0, 2 * np.pi, 300)
    zc = [P["sage"], P["sand"], P["peach"]]
    hs, labs = [], []
    for k, reach in enumerate(s["zreach"]):
        c = reach / 2 * np.exp(1j * ang)
        z = c + reach / 2 * np.exp(1j * th)
        hs.append(ax.plot(z.real, z.imag, color=[D["sage"], D["amber"], D["clay"]][k], lw=0.9)[0])
        labs.append(f"Z{k+1} ({reach:.1f} ohm)")
    zl = complex(*s["zline"])
    ax.plot([0, zl.real], [0, zl.imag], color="#777777", lw=0.6, ls=(0, (3, 2)))
    from engine.settings import _zline
    from engine.network import base_network
    Z1t, _, _ = _zline(base_network(), "858", "848")
    ht = ax.plot(Z1t.real, Z1t.imag, marker="o", ms=5, ls="", mfc=D["mauve"], mec=D["mauve"])[0]
    for run, c, mk, lab in ((a, D["grey"], "o", "measured Z, no DER"), (r, D["coral"], "o", "measured Z, GFL 40 % at 840")):
        tr = np.array(run["rx"][iid])
        tr = tr[np.isfinite(tr).all(axis=1)]
        ax.plot(tr[:, 0], tr[:, 1], color=c, lw=0.6, alpha=0.8)
        hs.append(ax.plot(tr[-1, 0], tr[-1, 1], marker=mk, ms=4.5, ls="", mfc=c, mec=c)[0]); labs.append(lab)
    hs.append(ht); labs.append("true fault impedance")
    ax.set_aspect("equal"); ax.grid(True)
    ax.set_xlabel("R (ohm)"); ax.set_ylabel("X (ohm)")
    ax.set_xlim(-2, 12); ax.set_ylim(-3.5, 9.5)
    ax.axhline(0, color="#999999", lw=0.5); ax.axvline(0, color="#999999", lw=0.5)
    legend_below(fig, hs, labs, ncol=2, y=0.0)
    save(fig, "fig8_rx")


if __name__ == "__main__":
    # fig_network is the old hand-drawn topology; Fig. 1 now comes from figures_stats.py network_ui
    want = sys.argv[1:] or ["method", "rate", "heat", "class", "wave", "tcc", "rx"]
    for n in want:
        globals()["fig_" + n]()
