import json, collections, numpy as np
R = {}
for l in open("campaigns/PoU-TA-Proteksi-Adaptif/results.jsonl", encoding="utf-8"):
    r = json.loads(l); R[r["key"]] = r
R = list(R.values())
C = ["F-1", "F-2", "F-3", "F-4", "F-5", "F-6", "NT"]
fail = lambda r, ex=(): any(r["counts"].get(c, 0) for c in C if c not in ex)
def rate(S, ex=()): return 100 * sum(fail(r, ex) for r in S) / max(len(S), 1)
H1 = [r for r in R if r["campaign"] == "H1"]; H2 = [r for r in R if r["campaign"] == "H2"]
E = [r for r in R if r["campaign"] == "E"]; I = [r for r in R if r["campaign"] == "I"]
print("== H1 by pen x tech (all / noF6)")
for pen in (0, 20, 40, 60, 80, 100, 120):
    row = []
    for t in ("SG", "IBR-GFL"):
        S = [r for r in H1 if r["pen"] == pen and (pen == 0 or r["tech"] == t)]
        row.append(f"{t}: {rate(S):5.1f}/{rate(S,('F-6',)):5.1f} n={len(S)}")
    print(pen, row)
print("== H1 pen x load (noF6 / all)")
for pen in (0, 20, 40, 60, 80, 100, 120):
    print(pen, [f"{lp}:{rate([r for r in H1 if r['pen']==pen and r['load_pct']==lp],('F-6',)):.1f}/{rate([r for r in H1 if r['pen']==pen and r['load_pct']==lp]):.1f}" for lp in (40, 70, 100)])
print("== OCR peak (H1 load100 rf0 + H2) pen x rf (noF6 / all)")
for pen in (0, 20, 40, 60, 80, 100, 120):
    out = []
    for rf in (0, 5, 20, 50):
        S = [r for r in (H1 if rf == 0 else H2) if r["pen"] == pen and r["rf"] == rf and r["load_pct"] == 100]
        out.append(f"{rf}:{rate(S,('F-6',)):.1f}/{rate(S):.1f}")
    print(pen, out)
print("== codes by campaign")
for nm, S in (("H1", H1), ("H2", H2), ("E", E), ("I", I)):
    print(nm, len(S), {c: sum(1 for r in S if r["counts"].get(c, 0)) for c in C}, f"fail {rate(S):.1f} noF6 {rate(S,('F-6',)):.1f}")
print("== E (+ OCR from H1 peak rf0) class x pen: noF6 / all, codes")
for cls in ("OCR", "DOCR", "DIST", "DIFF"):
    for pen in (0, 40, 80, 120):
        S = [r for r in (H1 if cls == "OCR" else E) if r["cls"] == cls and r["pen"] == pen and r["load_pct"] == 100 and r["rf"] == 0]
        print(cls, pen, len(S), f"{rate(S,('F-6',)):.1f}/{rate(S):.1f}", {c: sum(1 for r in S if r["counts"].get(c, 0)) for c in C if any(r["counts"].get(c, 0) for r in S)})
print("== by site (DER cases, grid) noF6/all")
for s in ("806", "828", "840", "848", "B03"):
    S = [r for r in R if r["site"] == s and r["tech"] != "ISL"]
    print(s, len(S), f"{rate(S,('F-6',)):.1f}/{rate(S):.1f}", {c: sum(1 for r in S if r["counts"].get(c, 0)) for c in C})
print("== by fault location (DER grid cases)")
for b in ("812", "822", "830", "834", "848", "B04"):
    for ft in ("SLG", "3PH"):
        S = [r for r in R if r["bus"] == b and r["ftype"] == ft and r["fleet"] != "none" and r["tech"] != "ISL"]
        if S: print(b, ft, len(S), f"{rate(S,('F-6',)):.1f}/{rate(S):.1f}", {c: sum(1 for r in S if r["counts"].get(c, 0)) for c in C if any(r["counts"].get(c,0) for r in S)})
print("== confusion by pen (grid OCR H1+H2+E)")
for pen in (0, 20, 40, 60, 80, 100, 120):
    S = [r for r in R if r["pen"] == pen and r["tech"] != "ISL"]
    cm = collections.Counter()
    for r in S:
        for k, v in (r.get("confusion") or {}).items(): cm[k] += v
    dep = cm["TP"] / max(cm["TP"] + cm["FN"], 1); sec = cm["TN"] / max(cm["TN"] + cm["FP"], 1)
    print(pen, dict(cm), f"dep {dep:.3f} sec {sec:.3f}")
print("== islanded")
for cls in ("OCR", "DOCR"):
    for pen in (60, 90, 120):
        S = [r for r in I if r["cls"] == cls and r["pen"] == pen]
        print(cls, pen, len(S), f"{rate(S):.1f}", {c: sum(1 for r in S if r["counts"].get(c, 0)) for c in C if any(r["counts"].get(c,0) for r in S)})
