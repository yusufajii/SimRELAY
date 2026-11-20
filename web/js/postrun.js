// SimRelay 34: Post-Run analysis page (renders batch/postrun_summary.json)
const $ = s => document.querySelector(s);
const f1 = v => (v === null || v === undefined || Number.isNaN(v)) ? "N/A" : Number(v).toFixed(1);
const f0 = v => (v === null || v === undefined || Number.isNaN(v)) ? "N/A" : Number(v).toFixed(0);
const pct = v => (v === null || v === undefined) ? "N/A" : (v * 100).toFixed(1) + "%";
const PENS = [0, 20, 40, 60, 80, 100, 120];
const CODES = ["F-1", "F-2", "F-3", "F-4", "F-5", "NT"];
const CLS = { OCR: "OCR 50/51", DOCR: "DOCR 67", DIST: "Distance 21", DIFF: "Differential 87L" };

const table = (head, rows) => `<table class="tbl"><thead><tr>${head.map(h => `<th>${h}</th>`).join("")}</tr></thead><tbody>${rows.map(r => `<tr>${r.map(c => `<td>${c}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
const dl = name => `<div class="dl"><a href="/batch/figures/${name}.png" download>PNG</a><a href="/batch/figures/${name}.pdf" download>PDF</a></div>`;
const section = (n, title, tag, file, why, finding, tbl) => `
  <section class="sec" id="fig${n}">
    <div class="sec-h"><span class="n">Figure ${n}</span><h2>${title}</h2><span class="tag2">${tag}</span>${dl(file)}</div>
    <div class="why">${why}</div>
    <img src="/batch/figures/${file}.png?v=${Date.now()}" alt="${title}" loading="lazy">
    <div class="finding">${finding}</div>
    <details><summary>Show data table</summary>${tbl}</details>
  </section>`;

async function main() {
  let S;
  try {
    const r = await fetch("/batch/postrun_summary.json", { cache: "no-store" });
    if (!r.ok) throw new Error();
    S = await r.json();
  } catch (e) {
    $("#pr").innerHTML = `<div class="wait">No post-run results yet. Run <code>python batch.py</code> and then <code>python postrun.py</code>.</div>`;
    return;
  }
  const C = S.confusion, H = S.heatmap, T = S.tcc, E = S.escalation, X = S.rx, RO = S.rose;
  const failShare = S.failed_runs / S.runs * 100;
  const depDrop = (C.baseline.dependability - C.der.dependability) * 100;
  const secDrop = (C.baseline.security - C.der.security) * 100;
  const tiles = [
    ["Simulated cases", S.runs.toLocaleString("en-US"), `H1 ${S.by_campaign.H1}, H2 ${S.by_campaign.H2}, E ${S.by_campaign.E}, I ${S.by_campaign.I}`],
    ["Cases with a misoperation", f1(failShare) + "%", `${S.failed_runs.toLocaleString("en-US")} cases with F-1 to F-5 or a nuisance trip (NT)`],
    ["Baseline failure rate", f0(H.baseline_rate) + "%", "No DER, evening peak load, OCR (87L: one lateral case)"],
    ["Tipping point", H.tipping_point_pen === null ? "Not reached" : H.tipping_point_pen + "% DER", "First penetration 10 points above baseline"],
    ["Dependability, with DER", pct(C.der.dependability), `Baseline ${pct(C.baseline.dependability)}, change ${depDrop >= 0 ? "-" : "+"}${f1(Math.abs(depDrop))} points`],
    ["Security, with DER", pct(C.der.security), `Baseline ${pct(C.baseline.security)}, change ${secDrop >= 0 ? "-" : "+"}${f1(Math.abs(secDrop))} points`],
  ];
  const codeTot = CODES.map(c => `${c}: ${S.totals[c] || 0}`).join(", ");

  // Figure 1
  const tccRows = PENS.map(p => [p + "%", T.cases_by_pen[p], T.violations_by_pen[p], f1(T.cases_by_pen[p] ? 100 * T.violations_by_pen[p] / T.cases_by_pen[p] : null) + "%",
    ...["None", "SG", "IBR"].map(t => T.cti_by_pen[p][t] === null ? "N/A" : T.cti_by_pen[p][t].toFixed(3))]);
  const worstPen = PENS.reduce((a, p) => (T.cases_by_pen[p] && T.violations_by_pen[p] / T.cases_by_pen[p] > (T.cases_by_pen[a] ? T.violations_by_pen[a] / T.cases_by_pen[a] : -1)) ? p : a, 0);
  const f1txt = `${T.cti_violations} of ${T.cti_cases} coordination cases (${f1(100 * T.cti_violations / Math.max(T.cti_cases, 1))}%) violate the 0.2 s CTI between A2 and A3, with the highest share at ${worstPen}% DER. `
    + `${T.a3_no_trip} SLG cases leave A3 below its ${T.pickup_A3_51N} A ground pickup, so the primary relay never trips (F-1); in ${T.a3_upstream_first} more, A2 trips first through its 50N element (F-3).`;

  // Figure 2
  const loadNames = { 40: "Daytime minimum 40%", 70: "Intermediate 70%", 100: "Evening peak 100%" };
  const hmTbl = table(["Load level", ...PENS.map(p => p + "%")], H.load.rows.map((L, i) => [loadNames[L], ...H.load.rate[i].map(v => f0(v) + "%")]))
    + `<div style="height:10px"></div>` + table(["Rf (Ω)", ...PENS.map(p => p + "%")], H.rf.rows.map((rf, i) => [rf, ...H.rf.rate[i].map(v => f0(v) + "%")]));
  const peakRow = H.load.rate[2];
  const f2txt = `Under evening peak load the failure rate rises from ${f0(peakRow[0])}% without DER to ${f0(peakRow[peakRow.length - 1])}% at 120% penetration`
    + (H.tipping_point_pen !== null ? `, with the tipping point at ${H.tipping_point_pen}% DER.` : ".")
    + ` Higher fault resistance shifts the failure region: at 120% DER the rate is ${H.rf.rate.map((r, i) => `${f0(r[r.length - 1])}% at ${H.rf.rows[i]} Ω`).join(", ")}.`;

  // Figure 3
  const escRows = [];
  for (const p of [0, 40, 80, 120]) for (const c of ["OCR", "DOCR", "DIST", "DIFF"]) {
    const d = E[`${c}|${p}`]; if (!d) continue;
    escRows.push([`${p}%`, CLS[c], d.n, ...CODES.map(k => f1(d[k] || 0) + "%"), f1(d.any) + "%"]);
  }
  const dom = cls => { const d = E[`${cls}|120`]; if (!d) return "N/A"; const k = CODES.reduce((a, b) => (d[b] || 0) > (d[a] || 0) ? b : a); return d[k] > 0 ? `${k} (${f0(d[k])}%)` : "none"; };
  const f3txt = `At 120% DER the dominant failure type changes with the relay class: OCR ${dom("OCR")}, DOCR ${dom("DOCR")}, Distance ${dom("DIST")}, Differential ${dom("DIFF")}. `
    + `Share of failed cases at 120%: ${["OCR", "DOCR", "DIST", "DIFF"].map(c => `${CLS[c]} ${f0(E[`${c}|120`]?.any)}%`).join(", ")}.`;

  // Figure 4
  const rxTbl = table(["DER penetration", `Median |Z| measured at ${X.ied} (Ω)`], PENS.filter(p => X.by_pen[p] !== null && X.by_pen[p] !== undefined).map(p => [p + "%", X.by_pen[p].toFixed(2)]))
    + `<div style="height:10px"></div>` + table(["DER technology", "Reverse-fault samples", "Declared FORWARD"], ["SG", "IBR"].map(t => [t, RO[t].n, f1(RO[t].forward_pct) + "%"]));
  const f4txt = `The fault at ${X.bus} lies at |Z| = ${X.z_true.toFixed(2)} Ω, inside Zone 1 of ${X.ied} (${X.zreach[0].toFixed(2)} Ω). `
    + `${X.f5_cases} of ${X.cases} distance cases are flagged as under-reach (F-5). For faults behind a DOCR relay, ${f1(RO.IBR.forward_pct)}% of IBR samples are declared FORWARD against ${f1(RO.SG.forward_pct)}% with SG (F-4).`;

  // Figure 5
  const cmTbl = table(["DER penetration", "Dependability", "Security"], PENS.map(p => [p + "%", f1(C.by_pen[p].dependability) + "%", f1(C.by_pen[p].security) + "%"]))
    + `<div style="height:10px"></div>` + table(["", "TP", "FN", "FP", "TN", "Dependability", "Security"],
      [["Baseline", C.baseline.TP, C.baseline.FN, C.baseline.FP, C.baseline.TN, pct(C.baseline.dependability), pct(C.baseline.security)],
       ["With DER", C.der.TP, C.der.FN, C.der.FP, C.der.TN, pct(C.der.dependability), pct(C.der.security)]]);
  const f5txt = `Across all grid-connected OCR cases, dependability changes from ${pct(C.baseline.dependability)} to ${pct(C.der.dependability)} and security from ${pct(C.baseline.security)} to ${pct(C.der.security)} once DER is connected. `
    + `At 120% DER the values are ${f1(C.by_pen[120].dependability)}% and ${f1(C.by_pen[120].security)}%.`;

  $("#pr").innerHTML = `
    <h1>Post-Run Analysis: Proof of Urgency</h1>
    <p class="intro">Batch results of the frozen conventional relay settings (computed once at 0% DER, evening peak load) under DER penetration from 0% to 120% of the Feeder A peak load.
      Every cell pools 10 single-DER placements (synchronous generator or grid-following inverter at buses 806, 828, 840, 848 and B03) and 11 fault cases
      (SLG and three-phase at 812, 830, 834, 848, B04, and SLG at the 822 lateral). Total findings: ${codeTot}.</p>
    <div class="tiles">${tiles.map(([l, v, s]) => `<div class="tile"><div class="l">${l}</div><div class="v">${v}</div><div class="s">${s}</div></div>`).join("")}</div>
    <div class="files"><a href="/batch/postrun_tables.csv" download>All runs (CSV)</a><a href="/batch/batch_results.mat" download>All runs (MATLAB .mat)</a><a href="/batch/batch_results.json" download>All runs (JSON)</a><a href="/batch/postrun_summary.json" download>Figure data (JSON)</a></div>
    ${section(1, "Dynamic TCC Overlay", "F-1, F-3", "fig1_tcc_overlay", "Relay operating points stacked on the frozen time-current curves. CTI narrowing below 0.2 s proves F-3; points shifting left of the pickup line prove F-1.", f1txt,
      table(["DER penetration", "Cases", "CTI < 0.2 s", "Share", "Median CTI no DER (s)", "Median CTI SG (s)", "Median CTI IBR (s)"], tccRows))}
    ${section(2, "Failure Rate Heatmap", "All codes", "fig2_failure_heatmap", "Share of cases with at least one misoperation by DER penetration against load level and fault resistance, showing where conventional relays start to fail.", f2txt, hmTbl)}
    ${section(3, "Relay Class Escalation", "F-1 to F-5", "fig3_relay_class_escalation", "Frequency of F-1 to F-5 for OCR, DOCR, Distance and Differential relays at the same protection points with fixed settings.", f3txt,
      table(["DER", "Relay class", "Cases", ...CODES, "Any"], escRows))}
    ${section(4, "R-X Envelope and Polar Rose", "F-4, F-5", "fig4_rx_envelope_polar_rose", "Geometric evidence: apparent-impedance trajectories against the mho zones (F-5) and the distribution of fault-current angles seen by the directional element (F-4).", f4txt, rxTbl)}
    ${section(5, "Protection Confusion Matrix", "Dependability, security", "fig5_confusion_matrix", "Every relay decision classified as TP, TN, FP or FN, with dependability (eroded by F-1 and F-4) and security (eroded by F-2 and F-3).", f5txt, cmTbl)}`;
}
main();
