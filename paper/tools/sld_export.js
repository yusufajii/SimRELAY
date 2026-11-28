// Fig. 1 of the paper: export the SimRELAY single-line diagram with candidate markers.
//
// How to use (SimRELAY must be running at http://127.0.0.1:8034 with any run loaded):
//   1. Start the receiver:  python paper/tools/recv.py <output folder>      (listens on 127.0.0.1:8099)
//   2. Open the app, open the browser console (or the Claude browser pane javascript tool),
//      paste this whole file, then run:   await sldPaperExport("sld_ui3")
//   3. Copy <output folder>/sld_ui3.png to paper/figures/sld_ui_raw.png and run
//      python paper/figures_stats.py network_ui      (adds the legend, writes fig1_network.png)
//
// The function changes the diagram only in memory (layers, labels, markers). It restores the view
// layers afterwards and never calls the view-settings save, so the user's saved SLD view is untouched.

window._exportSLD = async (name, scale, recolor) => {
  const svg = document.querySelector("#sld");
  const clone = svg.cloneNode(true);
  const src = svg.querySelectorAll("*"), dst = clone.querySelectorAll("*");
  const props = ["fill", "stroke", "stroke-width", "stroke-dasharray", "font-size", "font-weight", "opacity", "display",
    "paint-order", "stroke-linejoin", "stroke-linecap", "fill-opacity", "stroke-opacity", "visibility"];
  src.forEach((e, i) => {
    const cs = getComputedStyle(e), d = dst[i];
    let st = "";
    for (const p of props) st += `${p}:${cs.getPropertyValue(p)};`;
    if (e.tagName === "text" || e.tagName === "tspan") st += "font-family:'Courier New',Courier,monospace;";
    d.setAttribute("style", st); d.removeAttribute("class");
  });
  const v = window.app.sld.full, pad = 10;
  const vb = { x: v.x - pad, y: v.y - pad, w: v.w + 2 * pad, h: v.h + 2 * pad };
  clone.setAttribute("viewBox", `${vb.x} ${vb.y} ${vb.w} ${vb.h}`);
  clone.setAttribute("width", vb.w * scale); clone.setAttribute("height", vb.h * scale);
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  clone.removeAttribute("style");
  let txt = new XMLSerializer().serializeToString(clone);
  for (const [k, val] of Object.entries(recolor || {})) txt = txt.split(k).join(val);
  await fetch("http://127.0.0.1:8099/" + name + ".svg", { method: "POST", body: txt });
  const img = new Image(), url = URL.createObjectURL(new Blob([txt], { type: "image/svg+xml" }));
  await new Promise((res, rej) => { img.onload = res; img.onerror = rej; img.src = url; });
  const c = document.createElement("canvas"); c.width = vb.w * scale; c.height = vb.h * scale;
  const g = c.getContext("2d"); g.fillStyle = "#fff"; g.fillRect(0, 0, c.width, c.height); g.drawImage(img, 0, 0, c.width, c.height);
  await fetch("http://127.0.0.1:8099/" + name + ".png", { method: "POST", body: c.toDataURL("image/png") });
  return [c.width, c.height];
};

// Neutral grey palette instead of the slate (blue-grey) UI ink.
const NEUTRAL = {
  "rgb(30, 41, 59)": "rgb(38, 38, 38)", "rgb(217, 119, 6)": "rgb(38, 38, 38)", "rgb(15, 23, 42)": "rgb(20, 20, 20)",
  "rgb(100, 116, 139)": "rgb(110, 110, 110)", "rgb(71, 85, 105)": "rgb(80, 80, 80)", "rgb(148, 163, 184)": "rgb(150, 150, 150)",
  "rgb(138, 151, 168)": "rgb(140, 140, 140)", "rgb(51, 65, 85)": "rgb(60, 60, 60)", "rgb(185, 28, 28)": "rgb(190, 50, 50)",
};

window.sldPaperExport = async (name = "sld_ui3") => {
  const a = window.app, s = a.sld, NS = "http://www.w3.org/2000/svg";
  a.pause();
  // synthetic run: every candidate DER site and fault location at once (display only, nothing is simulated)
  const r0 = a.run, nt = r0.t.length;
  const R2 = Object.assign({}, r0);
  const mkD = (id, bus, type, kva) => ({ id, bus, type, kva, on: Array(nt).fill(true), P: Array(nt).fill(100),
    Q: Array(nt).fill(0), I: Array(nt).fill([1, 1, 1]) });
  R2.der = [mkD("DER-806", "806", "SG", 2123), mkD("DER-828", "828", "IBR-GFL", 2123), mkD("DER-840", "840", "SG", 2123),
    mkD("DER-848", "848", "IBR-GFL", 2123), mkD("DER-B03", "B03", "SG", 2123), mkD("GFM-824", "824", "IBR-GFM", 1061)];
  R2.faults = ["812", "822", "830", "834", "848", "B04"].map(n => Object.assign({}, r0.faults[0], { id: "F" + n, node: n }));
  a.setRun(R2); a.pause();
  for (const l of ["in", "out", "flow"]) s.layers[l] = false;
  s._applyLayers();
  const fl = { "812": "SLG, 3PH", "822": "SLG", "830": "SLG, 3PH", "834": "SLG, 3PH", "848": "SLG, 3PH", "B04": "SLG, 3PH" };
  const saved = JSON.parse(JSON.stringify(s.disp));
  for (const b of s.blocks) for (const it of b.items) {
    if (it.key && it.key.startsWith("load:")) s.disp[it.key] = Object.assign(s.disp[it.key] || {}, { [it.q]: false });
    if (it.key && it.key.startsWith("der:") && it.q === "rate") { const id = it.key.slice(4); it.fn = () => id.startsWith("GFM") ? "GFM, islanded set" : "SG or GFL"; }
    if (it.key && it.key.startsWith("fault:") && it.q === "id") { const bus = it.key.slice(7); it.fn = () => `F${bus}: ${fl[bus]}`; }
  }
  s._dirty(); s._needPlace = true; a.seek(0.2); a.pause();
  for (const ge of s.godEls) for (const e of [ge.g, ge.blk.t, ge.tail]) e.setAttribute("opacity", 1);
  for (const t of s.root.querySelectorAll("tspan"))
    if (/^Feeder B: equivalent/.test(t.textContent)) t.textContent = "Feeder B: equivalent adjacent feeder, 24.9 kV";
  for (const t of s.root.querySelectorAll("text")) {
    const m = t.textContent.match(/^(A1|A2|A3|L1|B1) \(50\/51\)$/);
    if (m) { const sp = t.querySelector("tspan"); (sp || t).textContent = m[1]; }
  }
  // candidate markers: dashed circles without fill, behind everything
  const hal = document.createElementNS(NS, "g"); s.root.insertBefore(hal, s.root.firstChild);
  const ring = (bus, r, col) => {
    const p = s.bus[bus], c = document.createElementNS(NS, "circle");
    for (const [k, v] of Object.entries({ cx: p.x, cy: p.y, r, fill: "none", stroke: col, "stroke-width": 1.8, "stroke-dasharray": "5 3.5" })) c.setAttribute(k, v);
    hal.appendChild(c);
  };
  for (const b of ["806", "828", "840", "848", "B03"]) ring(b, 26, "#5fae72");
  ring("824", 26, "#9a7cc9");
  for (const b of Object.keys(fl)) ring(b, 19, "#e07272");
  // relay: outline only; breaker: grey
  for (const e of Object.values(s.iedEls)) {
    e.box.setAttribute("fill", "#ffffff"); e.box.setAttribute("stroke", "#c9a04a");
    e.cb.setAttribute("fill", "#6b6b6b"); e.cb.setAttribute("stroke", "#333333");
  }
  s.subCB.setAttribute("fill", "#6b6b6b"); s.subCB.setAttribute("stroke", "#333333");
  const out = await window._exportSLD(name, 2.2, NEUTRAL);
  s.disp = saved;
  for (const l of ["in", "out", "flow"]) s.layers[l] = true;
  s._applyLayers();
  return out;   // reload the page afterwards to return to the real run
};
