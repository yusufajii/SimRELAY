// SCADA single-line diagram (SVG): IEEE 34 with equivalent Feeder B
const NS = "http://www.w3.org/2000/svg";
const VB = { x: 0, y: 6, w: 2360, h: 794 };
const BUSBAR = { x: 130, y1: 270, y2: 680 };
const SRC_Y = 470;

const C = {
  mv: "#334155", lv: "#64748b", off: "#cbd5e1",
  text: "#0f172a", text2: "#475569", muted: "#94a3b8",
  flow: "#2563eb", rev: "#d97706",
  der: "#b45309", gfm: "#0f766e",
};

function el(tag, attrs = {}, parent) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== undefined && v !== null) e.setAttribute(k, v);
  if (parent) parent.appendChild(e);
  return e;
}
const fmt = (v, d = 0) => (v === null || v === undefined || Number.isNaN(v)) ? "N/A" : Number(v).toFixed(d);

export function vStatus(v) {
  if (v === null || v === undefined || Number.isNaN(v)) return "nodata";
  if (v < 0.05) return "dead";
  if (v < 0.90 || v > 1.10) return "crit";
  if (v < 0.95 || v > 1.05) return "warn";
  return "good";
}
export const VCOL = { good: "#16a34a", warn: "#d97706", crit: "#dc2626", dead: "#a3adbb", nodata: "#a3adbb" };

export class SLD {
  constructor(svg, host, app) {
    this.svg = svg; this.host = host; this.app = app;
    this.vb = { ...VB };
    this._panzoom();
  }

  // geometry
  pos(id, other) {
    const b = this.bus[id];
    if (id === "800") {
      const o = other ? this.bus[other] : null;
      return { x: BUSBAR.x, y: o ? o.y : SRC_Y };
    }
    return { x: b.x, y: b.y };
  }

  build(topo, run, layout) {
    this.topo = topo; this.run = run;
    // Display coordinates come from the live layout so cached runs follow layout changes.
    this.bus = Object.fromEntries(topo.buses.map(b => {
      const L = layout && layout[b.id];
      return [b.id, L ? { ...b, x: L.x, y: L.y } : b];
    }));
    for (const b of topo.buses) if (b.virtual) this._placeVirtual(b, topo);
    const s = this.svg;
    s.innerHTML = "";
    this.root = el("g", {}, s);
    const G = n => el("g", { id: "g-" + n }, this.root);
    this.gFrame = G("frame"); this.gLines = G("lines"); this.gFlow = G("flow"); this.gAux = G("aux");
    this.gBus = G("bus"); this.gDev = G("dev"); this.gGod = G("god");
    this._frame();
    this._dirs();
    this._lines();
    this._substation();
    this._buses();
    this._ders(run ? run.der : []);     // DERs claim a free side first; loads and capacitors fit around them
    this._loads();
    this._caps();
    this._ieds();
    this._god(run);
    this.applyVB();
  }

  // A fault placed mid-line creates a virtual bus; keep it on the (re-laid-out) line.
  _placeVirtual(vb, topo) {
    const parts = topo.branches.filter(br => br.from === vb.id || br.to === vb.id);
    const ends = parts.map(br => br.from === vb.id ? br.to : br.from).filter(id => this.bus[id] && !this.bus[id].virtual);
    const sc = this.run && this.run.faults ? this.run.faults.find(f => f.node === vb.id) : null;
    if (ends.length === 2) {
      const [a, c] = ends.map(id => this.bus[id]);
      const f = sc && sc.frac != null ? sc.frac : 0.5;
      this.bus[vb.id] = { ...vb, x: a.x + (c.x - a.x) * f, y: a.y + (c.y - a.y) * f };
    }
  }

  _frame() {
    const g = this.gFrame;
    const box = (x, y, w, h, t, top = false) => {
      el("rect", { x, y, width: w, height: h, rx: 14, fill: "#ffffff", "fill-opacity": .55, stroke: "#dbe2ea", "stroke-width": 1.2 }, g);
      el("text", { x: x + 16, y: top ? y + 24 : y + h - 12, fill: "#64748b", "font-size": 13, "font-weight": 600 }, g).textContent = t;
    };
    box(178, 48, 2160, 532, "Feeder A: IEEE 34-Node Test Feeder, 24.9 kV");
    box(178, 596, 742, 198, "Feeder B: Equivalent Feeder for F-2 Testing");
    box(8, 232, 158, 470, "Substation", true);
  }

  _dirs() {
    this.used = {};
    for (const b of this.topo.buses) this.used[b.id] = new Set();
    for (const br of this.topo.branches) {
      const a = this.pos(br.from, br.to), c = this.pos(br.to, br.from);
      const d = (p, q) => Math.abs(q.x - p.x) > Math.abs(q.y - p.y) ? (q.x > p.x ? "R" : "L") : (q.y > p.y ? "D" : "U");
      this.used[br.from]?.add(d(a, c)); this.used[br.to]?.add(d(c, a));
    }
    this.slot = {};
  }
  freeDir(bid, pref = ["D", "U", "R", "L"]) {
    const u = this.used[bid]; this.slot[bid] = this.slot[bid] || new Set();
    for (const d of pref) if (!u.has(d) && !this.slot[bid].has(d)) { this.slot[bid].add(d); return d; }
    for (const d of ["DR", "UR", "DL", "UL"]) if (!this.slot[bid].has(d)) { this.slot[bid].add(d); return d; }
    return "D";
  }
  off(dir, r) {
    const m = { U: [0, -r], D: [0, r], L: [-r, 0], R: [r, 0], DR: [r * .75, r * .75], UR: [r * .75, -r * .75], DL: [-r * .75, r * .75], UL: [-r * .75, -r * .75] };
    return m[dir] || [0, r];
  }

  _lines() {
    this.lineEls = {};
    for (const br of this.topo.branches) {
      const a = this.pos(br.from, br.to), c = this.pos(br.to, br.from);
      let d = `M${a.x},${a.y} L${c.x},${c.y}`;
      if (a.x !== c.x && a.y !== c.y) d = `M${a.x},${a.y} L${c.x},${a.y} L${c.x},${c.y}`;
      const len = Math.abs(c.x - a.x) + Math.abs(c.y - a.y);
      const w = br.phases.length === 3 ? 3 : 1.8;
      const isLV = (this.bus[br.from].kv < 10 && this.bus[br.to].kv < 10);
      const p = el("path", { d, class: "sld-line", "stroke-width": w, stroke: isLV ? C.lv : C.mv }, this.gLines);
      const hit = el("path", { d, class: "sld-hit" }, this.gLines);
      const kind = br.kind === "line" ? "line" : br.kind;
      hit.addEventListener("click", ev => this.app.inspect(kind, br.id, ev));
      const mid = { x: (a.x + c.x) / 2, y: (a.y + c.y) / 2 };
      const fl = el("g", {}, this.gFlow);
      this.lineEls[br.id] = { p, br, d, len, fl, w, state: "" };
      if (br.kind === "reg") this._regSym(mid, br);
      if (br.kind === "xfmr") this._xfSym(mid, br, a, c);
    }
  }

  // Animated arrows travelling along the line in the direction of active power flow.
  _setFlow(e, state) {
    if (e.state === state) return;
    e.state = state;
    e.fl.innerHTML = "";
    if (!state) return;
    const [dir, lvl] = state.split(":");
    const rev = dir === "r";
    const speed = [45, 75, 110][+lvl];          // px per second, scaled by |P|
    const n = Math.max(1, Math.round(e.len / 90));
    const dur = Math.max(e.len / speed, 0.6);
    const size = e.w > 2 ? 1 : 0.8;
    for (let i = 0; i < n; i++) {
      const g = el("g", {}, e.fl);
      el("path", { d: `M${-5 * size},${-4.5 * size} L${5 * size},0 L${-5 * size},${4.5 * size} Z`, fill: rev ? C.rev : C.flow, stroke: "#fff", "stroke-width": 1 }, g);
      el("animateMotion", {
        path: e.d, dur: dur.toFixed(2) + "s", repeatCount: "indefinite", rotate: rev ? "auto-reverse" : "auto",
        keyPoints: rev ? "1;0" : "0;1", keyTimes: "0;1", calcMode: "linear",
        begin: (-(i / n) * dur).toFixed(2) + "s",
      }, g);
    }
  }

  _regSym(m, br) {
    const g = el("g", { class: "clickable", transform: `translate(${m.x},${m.y})` }, this.gAux);
    el("circle", { r: 11, fill: "#fff", stroke: C.der, "stroke-width": 1.8 }, g);
    el("path", { d: "M-6,6 L6,-6 M1,-6 L6,-6 L6,-1", stroke: C.der, "stroke-width": 1.6, fill: "none" }, g);
    el("text", { x: 0, y: -18, "text-anchor": "middle", fill: C.der, "font-size": 11.5, "font-weight": 600 }, g).textContent = br.id;
    g.addEventListener("click", ev => this.app.inspect("reg", br.id, ev));
  }
  _xfSym(m, br, a, c) {
    const vert = a.x === c.x;
    const g = el("g", { class: "clickable", transform: `translate(${m.x},${m.y})` }, this.gAux);
    const dx = vert ? 0 : 7, dy = vert ? 7 : 0;
    el("circle", { cx: -dx, cy: -dy, r: 10, fill: "#fff", stroke: C.mv, "stroke-width": 1.7 }, g);
    el("circle", { cx: dx, cy: dy, r: 10, fill: "none", stroke: C.lv, "stroke-width": 1.7 }, g);
    el("text", { x: 18, y: 4, fill: C.text2, "font-size": 11 }, g).textContent = `${br.id}, ${br.kva} kVA`;
    g.addEventListener("click", ev => this.app.inspect("xfmr", br.id, ev));
  }

  _substation() {
    const g = this.gAux;
    el("line", { x1: BUSBAR.x, y1: BUSBAR.y1, x2: BUSBAR.x, y2: BUSBAR.y2, stroke: C.mv, "stroke-width": 7, "stroke-linecap": "round" }, g);
    el("text", { x: BUSBAR.x, y: BUSBAR.y1 - 12, "text-anchor": "middle", fill: C.text, "font-size": 13, "font-weight": 700 }, g).textContent = "800";
    const y = SRC_Y;
    el("line", { x1: 30, y1: y, x2: BUSBAR.x, y2: y, stroke: C.mv, "stroke-width": 3 }, g);
    const src = el("g", { class: "clickable", transform: `translate(30,${y})` }, g);
    el("circle", { r: 14, fill: "#fff", stroke: C.der, "stroke-width": 1.8 }, src);
    el("path", { d: "M-8,0 C-4,-8 0,-8 0,0 C0,8 4,8 8,0", stroke: C.der, "stroke-width": 1.8, fill: "none" }, src);
    el("text", { x: 0, y: 32, "text-anchor": "middle", fill: C.der, "font-size": 11, "font-weight": 600 }, src).textContent = "69 kV";
    src.addEventListener("click", ev => this.app.inspect("sub", "SUB", ev));
    this.subCB = el("rect", { x: 50, y: y - 7, width: 14, height: 14, rx: 2, class: "clickable" }, g);
    this.subCB.addEventListener("click", ev => this.app.inspect("sub", "SUB", ev));
    el("text", { x: 57, y: y - 15, "text-anchor": "middle", fill: C.text2, "font-size": 10.5 }, g).textContent = "CB-GI";
    const tx = el("g", { class: "clickable", transform: `translate(92,${y})` }, g);
    el("circle", { cx: -7, r: 10, fill: "#fff", stroke: C.der, "stroke-width": 1.7 }, tx);
    el("circle", { cx: 7, r: 10, fill: "none", stroke: C.mv, "stroke-width": 1.7 }, tx);
    el("text", { x: 0, y: 30, "text-anchor": "middle", fill: C.text2, "font-size": 10.5 }, tx).textContent = "2.5 MVA";
    tx.addEventListener("click", ev => this.app.inspect("sub", "SUB", ev));
  }

  _buses() {
    this.busEls = {};
    for (const b0 of this.topo.buses) {
      const b = this.bus[b0.id];
      if (b.id === "800" || b.virtual) continue;
      const g = el("g", { class: "clickable", transform: `translate(${b.x},${b.y})` }, this.gBus);
      const r = b.phases.length === 3 ? 6 : 4.5;
      const c = el("circle", { r, fill: VCOL.dead, stroke: "#fff", "stroke-width": 2 }, g);
      g.addEventListener("click", ev => this.app.inspect("bus", b.id, ev));
      const t = el("text", { x: 9, y: -9, fill: C.text, "font-size": 13, "font-weight": 600 }, g);
      t.textContent = b.id;
      if (b.phases.length < 3) {
        const ph = el("tspan", { fill: C.muted, "font-size": 10.5, "font-weight": 500, dx: 4 }, t);
        ph.textContent = b.phases.toUpperCase();
      }
      const v = el("text", { x: 9, y: 19, fill: C.text2, "font-size": 11, class: "mono" }, g);
      this.busEls[b.id] = { c, v, b };
    }
  }

  _loads() {
    this.loadEls = {};
    const byBus = {};
    for (const l of this.topo.loads) (byBus[l.bus] = byBus[l.bus] || []).push(l);
    for (const [bid, ls] of Object.entries(byBus)) {
      if (!this.bus[bid] || bid === "800" || this.bus[bid].virtual) continue;
      const b = this.bus[bid];
      const d = this.freeDir(bid, ["D", "U", "R", "L"]);
      const [ox, oy] = this.off(d, d === "U" || d === "D" ? 44 : 50);
      const kw = ls.reduce((s, l) => s + l.P.reduce((a, c) => a + c, 0), 0);
      const g = el("g", { class: "clickable", transform: `translate(${b.x + ox},${b.y + oy})` }, this.gDev);
      el("line", { x1: -ox, y1: -oy, x2: 0, y2: 0, stroke: "#cbd5e1", "stroke-width": 1.2 }, g);
      const house = el("path", { d: "M-7,1 L0,-6 L7,1 L5,1 L5,7 L-5,7 L-5,1 Z", fill: "#fff", stroke: C.text2, "stroke-width": 1.4, "stroke-linejoin": "round" }, g);
      const left = d === "L";
      const tx = el("text", { x: left ? -11 : 11, y: 5, "text-anchor": left ? "end" : "start", fill: C.muted, "font-size": 10.5 }, g);
      tx.textContent = `${Math.round(kw)} kW`;
      g.addEventListener("click", ev => this.app.inspect("load", bid, ev));
      this.loadEls[bid] = { house, tx, kw };
    }
  }

  _caps() {
    this.capEls = {};
    for (const c of this.topo.caps) {
      const b = this.bus[c.bus];
      const d = this.freeDir(c.bus, ["U", "L", "R", "D"]);
      const [ox, oy] = this.off(d, 40);
      const vert = d === "U" || d === "D";
      const g = el("g", { class: "clickable", transform: `translate(${b.x + ox},${b.y + oy})` }, this.gDev);
      el("line", { x1: -ox, y1: -oy, x2: 0, y2: 0, stroke: "#cbd5e1", "stroke-width": 1.2 }, g);
      const s = el("g", { transform: vert ? "" : "rotate(90)" }, g);
      el("line", { x1: -8, y1: -2.5, x2: 8, y2: -2.5, "stroke-width": 2.2 }, s);
      el("line", { x1: -8, y1: 2.5, x2: 8, y2: 2.5, "stroke-width": 2.2 }, s);
      // Label beside the plates: right of a vertical stub, above a horizontal one.
      el("text", vert ? { x: 12, y: 4, fill: C.muted, "font-size": 10.5 } : { x: 0, y: -13, "text-anchor": "middle", fill: C.muted, "font-size": 10.5 }, g).textContent = c.id;
      s.setAttribute("stroke", c.on ? C.flow : C.off);
      g.addEventListener("click", ev => this.app.inspect("cap", c.id, ev));
      this.capEls[c.id] = s;
    }
  }

  _ders(ders) {
    this.derEls = {};
    for (const d of ders || []) {
      const b = this.bus[d.bus];
      if (!b) continue;
      const dir = this.freeDir(d.bus, ["U", "D", "R", "L"]);
      const [ox, oy] = this.off(dir, 70);
      const g = el("g", { class: "clickable", transform: `translate(${b.x + ox},${b.y + oy})` }, this.gDev);
      el("line", { x1: -ox, y1: -oy, x2: 0, y2: 0, stroke: C.der, "stroke-width": 1.4, "stroke-dasharray": "4 3" }, g);
      let body;
      if (d.type === "SG") {
        body = el("circle", { r: 13, fill: "#fffbeb", "stroke-width": 1.8 }, g);
        el("text", { x: 0, y: 4, "text-anchor": "middle", "font-size": 11, "font-weight": 700, fill: C.der }, g).textContent = "G";
      } else if (d.type === "IBR-GFM") {
        body = el("rect", { x: -15, y: -11, width: 30, height: 22, rx: 4, fill: "#f0fdfa", "stroke-width": 1.8 }, g);
        el("text", { x: 0, y: 4, "text-anchor": "middle", "font-size": 9.5, "font-weight": 700, fill: C.gfm }, g).textContent = "GFM";
      } else {
        body = el("rect", { x: -15, y: -10, width: 30, height: 20, rx: 3, fill: "#eff6ff", "stroke-width": 1.8 }, g);
        el("path", { d: "M-15,-3 L15,-3 M-15,3 L15,3 M-5,-10 L-5,10 M5,-10 L5,10", stroke: "#93c5fd", "stroke-width": 1 }, g);
      }
      // Labels sit beside the unit (right side, or left when the unit is placed to the left).
      const left = ox < 0 && oy === 0;
      const lx = left ? -22 : 22;
      const anchor = left ? "end" : "start";
      const lab = el("text", { x: lx, y: -2, "text-anchor": anchor, "font-size": 11.5, fill: C.der, "font-weight": 600 }, g);
      lab.textContent = `${d.id} ${d.type === "SG" ? "SG" : d.type === "IBR-GFM" ? "IBR-GFM" : "PV"} ${Math.round(d.kva)} kVA`;
      const val = el("text", { x: lx, y: 12, "text-anchor": anchor, "font-size": 10.5, fill: C.text2, class: "mono" }, g);
      g.addEventListener("click", ev => this.app.inspect("der", d.id, ev));
      this.derEls[d.id] = { body, val, d };
    }
  }

  _ieds() {
    this.iedEls = {};
    for (const m of this.topo.ieds) {
      const br = this.topo.branches.find(b => b.from === m.from && (b.to === m.to || b.parent === `L${m.from}-${m.to}`)) ||
                 this.topo.branches.find(b => b.from === m.from);
      const a = this.pos(m.from, br.to), c = this.pos(br.to, m.from);
      const L = Math.hypot(c.x - a.x, c.y - a.y) || 1;
      const t = Math.min(52 / L, 0.45);
      const x = a.x + (c.x - a.x) * t, y = a.y + (c.y - a.y) * t;
      const vert = Math.abs(c.x - a.x) < Math.abs(c.y - a.y);
      const g = el("g", { class: "clickable", transform: `translate(${x},${y})` }, this.gDev);
      const ring = el("rect", { x: -12, y: -12, width: 24, height: 24, rx: 5, fill: "none", stroke: VCOL.warn, "stroke-width": 2, opacity: 0 }, g);
      const box = el("rect", { x: -7, y: -7, width: 14, height: 14, rx: 2.5, "stroke-width": 2 }, g);
      const tag = el("text", { x: vert ? 16 : 0, y: vert ? -2 : -17, "font-size": 12, "font-weight": 700, fill: C.text, "text-anchor": vert ? "start" : "middle" }, g);
      tag.textContent = m.id;
      const cls = el("tspan", { fill: "#7c3aed", "font-size": 10.5, "font-weight": 600, dx: 4 }, tag);
      const cur = el("text", { x: vert ? 16 : 0, y: vert ? 12 : -31, "font-size": 10.5, fill: "#1d4ed8", "text-anchor": vert ? "start" : "middle", class: "mono" }, g);
      g.addEventListener("click", ev => this.app.inspect("ied", m.id, ev));
      this.iedEls[m.id] = { ring, box, cls, cur };
    }
  }

  _god(run) {
    this.godEls = [];
    if (!run) return;
    for (const f of run.faults || []) {
      const b = this.bus[f.node];
      if (!b) continue;
      const g = el("g", { transform: `translate(${b.x},${b.y})`, opacity: 0, "pointer-events": "none" }, this.gGod);
      el("circle", { r: 10, fill: "none", stroke: "#dc2626", "stroke-width": 2, class: "fault-ring" }, g);
      el("path", { d: "M3,-20 L-5,-3 L1,-3 L-4,12 L7,-7 L1,-7 L6,-20 Z", fill: "#dc2626", stroke: "#fff", "stroke-width": 1.2 }, g);
      // Label card on a white background, placed where it covers the fewest diagram labels.
      const tail = el("line", { stroke: "#fca5a5", "stroke-width": 1.2 }, g);
      const card = el("g", {}, g);
      const bg = el("rect", { y: -16, height: 36, rx: 7, fill: "#fff", stroke: "#fca5a5", "stroke-width": 1.2 }, card);
      const lab = el("text", { y: -1, fill: "#b91c1c", "font-size": 12, "font-weight": 700 }, card);
      const lab2 = el("text", { y: 13, fill: "#92400e", "font-size": 10.5 }, card);
      lab.textContent = `${f.id} ${f.type}${f.type === "3PH" ? "" : "-" + (f.phases || "").toUpperCase()}, Rf ${f.rf} Ω`;
      const ge = { g, f, lab2, bg, lab, card, tail, side: "l" };
      this._placeCard(ge);
      this.godEls.push(ge);
    }
  }

  _cardLayout(ge, dx, dy, side, w) {
    ge.side = side;
    ge.card.setAttribute("transform", `translate(${dx},${dy})`);
    const left = side === "l";
    ge.bg.setAttribute("x", left ? -w : 0); ge.bg.setAttribute("width", w);
    for (const t of [ge.lab, ge.lab2]) { t.setAttribute("x", left ? -10 : 10); t.setAttribute("text-anchor", left ? "end" : "start"); }
    const ty = dy < 0 ? dy + 20 : dy - 16;
    const len = Math.hypot(dx, ty) || 1;
    ge.tail.setAttribute("x1", dx); ge.tail.setAttribute("y1", ty);
    ge.tail.setAttribute("x2", dx * 14 / len); ge.tail.setAttribute("y2", ty * 14 / len);
  }

  _placeCard(ge) {
    const W = 215;
    const cands = [[-18, -74, "l"], [18, -74, "r"], [-18, 58, "l"], [18, 58, "r"], [-30, -110, "l"], [30, -110, "r"], [-30, 96, "l"], [30, 96, "r"]];
    const obs = [...this.root.querySelectorAll("#g-bus text, #g-dev text, #g-aux text, #g-frame text, #g-dev rect, #g-dev circle, #g-dev path, #g-aux circle")]
      .map(e => e.getBoundingClientRect()).filter(r => r.width > 0);
    const b = this.bus[ge.f.node];
    let best = null;
    for (const [dx, dy, side] of cands) {
      this._cardLayout(ge, dx, dy, side, W);
      const c = ge.bg.getBoundingClientRect();
      let cost = 0;
      for (const o of obs) {
        const ix = Math.min(c.right, o.right) - Math.max(c.left, o.left), iy = Math.min(c.bottom, o.bottom) - Math.max(c.top, o.top);
        if (ix > 0 && iy > 0) cost += ix * iy;
      }
      // Keep the card inside the full diagram extent.
      const x0 = b.x + dx - (side === "l" ? W : 0), y0 = b.y + dy - 16;
      if (y0 < VB.y || x0 < VB.x || x0 + W > VB.x + VB.w || y0 + 36 > VB.y + VB.h) cost += 1e9;
      if (!best || cost < best.cost) best = { cost, dx, dy, side };
    }
    this._cardLayout(ge, best.dx, best.dy, best.side, W);
    ge.dx = best.dx; ge.dy = best.dy;
  }

  // update
  update(S) {
    const r = S.run; if (!r) return;
    const k = S.k;
    const bi = this.app.busIdx, bri = this.app.brIdx;
    for (const [id, e] of Object.entries(this.busEls)) {
      const i = bi[id]; if (i === undefined) continue;
      const v = r.Vpu[k][i].filter(x => x !== null);
      const vmin = v.length ? Math.min(...v) : null;
      const vmax = v.length ? Math.max(...v) : null;
      const st = vmax !== null && vmax < 0.05 ? "dead" : vStatus(Math.max(vmin, 0.051));
      e.c.setAttribute("fill", VCOL[st]);
      e.v.textContent = S.showVal ? (st === "dead" ? "0 pu" : fmt(vmin, 3) + " pu") : "";
      e.v.setAttribute("fill", st === "crit" ? "#b91c1c" : st === "warn" ? "#b45309" : C.text2);
    }
    for (const [id, e] of Object.entries(this.lineEls)) {
      const i = bri[id];
      const br = e.br;
      const fe = r.energized[k][bi[br.from]] && r.energized[k][bi[br.to]];
      const isLV = this.bus[br.from].kv < 10;
      e.p.setAttribute("stroke", fe ? (isLV ? C.lv : C.mv) : C.off);
      e.p.setAttribute("stroke-dasharray", fe ? "" : "6 6");
      const P = r.Pbr[k][i][0];
      if (S.showFlow && fe && Math.abs(P) > 3) {
        const lvl = Math.abs(P) > 800 ? 2 : Math.abs(P) > 150 ? 1 : 0;
        this._setFlow(e, `${P < 0 ? "r" : "f"}:${lvl}`);
      } else this._setFlow(e, "");
    }
    for (const [id, e] of Object.entries(this.iedEls)) {
      const j = this.app.iedIdx[id];
      const d = r.ied[j];
      const closed = d.cb[k];
      e.box.setAttribute("fill", closed ? "var(--cb-closed)" : "#fff");
      e.box.setAttribute("stroke", closed ? "#991b1b" : "var(--cb-open)");
      const st = S.iedState[id] || {};
      e.ring.setAttribute("opacity", st.trip && closed ? 1 : st.pick ? 0.9 : 0);
      e.ring.setAttribute("stroke", st.trip ? VCOL.crit : VCOL.warn);
      e.ring.classList.toggle("blink", !!(st.trip && closed));
      e.cls.textContent = S.iedClass[id] || "";
      const I = d.I[k];
      e.cur.textContent = S.showVal ? `${I.map(x => fmt(x, 0)).join("/")} A` : "";
    }
    const subOn = r.sub[k];
    this.subCB.setAttribute("fill", subOn ? "var(--cb-closed)" : "#fff");
    this.subCB.setAttribute("stroke", subOn ? "#991b1b" : "var(--cb-open)");
    this.subCB.setAttribute("stroke-width", 2);
    for (const [id, e] of Object.entries(this.derEls)) {
      const j = this.app.derIdx[id];
      const d = r.der[j];
      const on = d.on[k];
      e.body.setAttribute("stroke", on ? (d.type === "IBR-GFM" ? C.gfm : d.type === "SG" ? C.der : C.flow) : C.muted);
      e.body.setAttribute("opacity", on ? 1 : 0.5);
      const irr = d.irr ? `, ${fmt(d.irr[k], 0)} W/m²` : "";
      e.val.textContent = S.showVal ? (on ? `${fmt(d.P[k], 0)} kW, ${fmt(d.Q[k], 0)} kvar${irr}` : "OFFLINE") : "";
    }
    for (const [bid, e] of Object.entries(this.loadEls)) {
      const live = r.energized[k][bi[bid]];
      e.house.setAttribute("stroke", live ? C.text2 : C.off);
    }
    // Ground-truth layer (not visible to a real operator)
    for (const ge of this.godEls) {
      const f = ge.f;
      const kg = S.kGod;
      const t = r.t[kg];
      const on = t >= f.t_on && (f.I[kg] || []).some(x => x > 0.5);
      const past = t >= f.t_on && !on;
      ge.g.setAttribute("opacity", !S.showGod ? 0 : on ? 0.9 : past ? 0.3 : 0);
      const I = f.I[kg] || [];
      const txt = on ? `Ground truth: |If| ${I.map(x => fmt(x, 0)).join(" / ")} A` : past ? "Ground truth: cleared or isolated" : "";
      if (txt !== ge.txt) {
        ge.txt = txt; ge.lab2.textContent = txt;
        const w = Math.max(ge.lab.getComputedTextLength(), ge.lab2.getComputedTextLength()) + 20;
        ge.bg.setAttribute("x", ge.side === "l" ? -w : 0); ge.bg.setAttribute("width", w);
      }
    }
  }

  // pan and zoom
  applyVB() {
    const v = this.vb;
    this.svg.setAttribute("viewBox", `${v.x} ${v.y} ${v.w} ${v.h}`);
  }
  fit() { this.vb = { ...VB }; this.applyVB(); }
  _panzoom() {
    const s = this.svg;
    let drag = null;
    s.addEventListener("wheel", ev => {
      ev.preventDefault();
      const r = s.getBoundingClientRect();
      const k = ev.deltaY > 0 ? 1.12 : 1 / 1.12;
      const sc = Math.max(this.vb.w / r.width, this.vb.h / r.height);
      const ox = (r.width - this.vb.w / sc) / 2, oy = (r.height - this.vb.h / sc) / 2;
      const mx = this.vb.x + (ev.clientX - r.left - ox) * sc, my = this.vb.y + (ev.clientY - r.top - oy) * sc;
      const nw = Math.min(Math.max(this.vb.w * k, 300), 3600);
      const f = nw / this.vb.w;
      this.vb = { x: mx - (mx - this.vb.x) * f, y: my - (my - this.vb.y) * f, w: nw, h: this.vb.h * f };
      this.applyVB();
    }, { passive: false });
    s.addEventListener("mousedown", ev => { drag = { x: ev.clientX, y: ev.clientY, vb: { ...this.vb }, moved: false }; s.classList.add("dragging"); });
    window.addEventListener("mousemove", ev => {
      if (!drag) return;
      const r = s.getBoundingClientRect();
      const sc = Math.max(this.vb.w / r.width, this.vb.h / r.height);
      const dx = (ev.clientX - drag.x) * sc, dy = (ev.clientY - drag.y) * sc;
      if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
      this.vb = { ...drag.vb, x: drag.vb.x - dx, y: drag.vb.y - dy };
      this.applyVB();
    });
    window.addEventListener("mouseup", () => { if (drag) { this.dragMoved = drag.moved; setTimeout(() => this.dragMoved = false, 0); } drag = null; s.classList.remove("dragging"); });
  }
}
