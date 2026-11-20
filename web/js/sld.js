// SCADA single-line diagram (SVG): IEEE 34 with equivalent Feeder B.
// Symbols follow IEC 60617 (breakers are kept as SCADA squares). Equipment is drawn in a neutral
// ink by default; colour is used only to report a state change during the simulation.
const NS = "http://www.w3.org/2000/svg";
const VB = { x: 0, y: 4, w: 1817, h: 568 };
const BUSBAR = { x: 130, y1: 268, y2: 538 };
const SRC_Y = 410;
const LH = 15;                       // text line height
// protection assembly geometry (along / across the protected line)
const RS = 55, RN = 57, RH = 14;     // relay centre and half size
const SCB = 39, SVT = 15, SVTV = 23, SCT = 69, SCTV = 64;

export const C = {
  ink: "#1e293b", ink2: "#475569", mute: "#94a3b8", dead: "#c3cad5", wire: "#8a97a8",
  warn: "#d97706", crit: "#dc2626", flow: "#64748b", rev: "#d97706",
  warnBg: "#fef3c7", critBg: "#fee2e2", pick: "#7c3aed", pickBg: "#f3efff",
};
export const VCOL = { good: C.ink, warn: C.warn, crit: C.crit, dead: C.dead, nodata: C.dead };

// Relay function: IEC 60617 qualifying symbol and ANSI/IEEE C37.2 device number.
export const FUNC = { OCR: ["I>", "50/51"], DOCR: ["I>→", "67"], DIST: ["Z<", "21"], DIFF: ["ΔI", "87L"] };

export const LAYERS = {
  comp: [
    { id: "net", label: "Power system: lines, buses, transformers and breakers", locked: true },
    { id: "shunt", label: "Loads and shunt capacitors" },
    { id: "der", label: "Distributed energy resources" },
    { id: "inst", label: "Instrument transformers (CT and VT)" },
    { id: "prot", label: "Protection relays and trip circuits" },
    { id: "flow", label: "Power flow direction" },
    { id: "god", label: "Ground truth: fault location, fault current and its path" },
  ],
  text: [
    { id: "id", label: "Equipment identifiers" },
    { id: "rate", label: "Nameplate ratings" },
    { id: "in", label: "Inputs: measured quantities" },
    { id: "out", label: "Outputs: device status" },
  ],
};

// Quantities that each kind of element can display on the diagram: [id, label, text layer, default].
export const QTY = {
  bus: [["id", "Bus identifier", "id", 1], ["vmin", "Lowest phase voltage (pu)", "in", 1], ["vabc", "Phase voltages A, B, C (pu)", "in", 0],
    ["vkv", "Lowest phase voltage (kV, line to neutral)", "in", 0], ["st", "Supply status", "out", 0]],
  line: [["id", "Line identifier", "id", 0], ["iabc", "Phase currents A, B, C (A)", "in", 0], ["pq", "Active and reactive power", "in", 0]],
  xfmr: [["id", "Transformer identifier", "id", 1], ["rate", "Rating (kVA)", "rate", 1], ["iabc", "Primary phase currents (A)", "in", 0], ["pq", "Active and reactive power", "in", 0]],
  reg: [["id", "Regulator identifier", "id", 1], ["rate", "Tap positions A, B, C", "rate", 0], ["iabc", "Phase currents (A)", "in", 0], ["pq", "Active and reactive power", "in", 0]],
  src: [["rate", "Source and transformer ratings", "rate", 1], ["pq", "Power supplied by the grid", "in", 0], ["f", "Frequency (Hz)", "in", 0]],
  load: [["rate", "Nominal demand (kW)", "rate", 1], ["st", "Supply status", "out", 0]],
  cap: [["id", "Capacitor identifier", "id", 1], ["rate", "Rating (kvar per phase)", "rate", 0], ["st", "Supply status", "out", 0]],
  der: [["id", "DER identifier", "id", 1], ["rate", "Technology and rating", "rate", 1], ["pq", "Active and reactive power", "in", 1],
    ["iabc", "Output currents A, B, C (A)", "in", 0], ["irr", "Irradiance (W/m²)", "in", 0], ["st", "Operating status", "out", 1]],
  ct: [["id", "CT identifier", "id", 0], ["iabc", "Phase currents A, B, C (A)", "in", 1], ["i0", "Residual current 3I0 (A)", "in", 0]],
  vt: [["id", "VT identifier", "id", 0], ["vabc", "Phase voltages A, B, C (pu)", "in", 0]],
  relay: [["id", "Relay identifier and function", "id", 1], ["st", "Relay status (normal, pickup, trip)", "out", 1], ["prog", "51P and 51N timer progress", "out", 0]],
  cb: [["id", "Breaker identifier", "id", 1], ["st", "Breaker position", "out", 0]],
  fault: [["id", "Fault identifier and type", "id", 1], ["if", "Fault current (A)", "in", 1], ["st", "Fault status", "out", 1]],
};

const STORE = "sr34-sld-view";

function el(tag, attrs = {}, parent) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== undefined && v !== null) e.setAttribute(k, v);
  if (parent) parent.appendChild(e);
  return e;
}
const fmt = (v, d = 0) => (v === null || v === undefined || Number.isNaN(v)) ? "N/A" : Number(v).toFixed(d);
const tri = (a, d = 0) => a.filter(x => x !== null && x !== undefined).map(x => fmt(x, d)).join(" / ");

// Group per-phase elements: ["67N", "67P-A", "67P-B"] becomes "67N, 67P-AB".
export function compactPicks(picks) {
  const out = [], ph = {};
  for (const p of picks) {
    const m = p.match(/^(.+)-([ABC])$/);
    if (m) { if (!ph[m[1]]) { ph[m[1]] = []; out.push(m[1]); } ph[m[1]].push(m[2]); }
    else out.push(p);
  }
  return out.map(x => ph[x] ? `${x}-${ph[x].sort().join("")}` : x).join(", ");
}

export function vStatus(v) {
  if (v === null || v === undefined || Number.isNaN(v)) return "nodata";
  if (v < 0.05) return "dead";
  if (v < 0.90 || v > 1.10) return "crit";
  if (v < 0.95 || v > 1.05) return "warn";
  return "good";
}

export class SLD {
  constructor(svg, host, app) {
    this.svg = svg; this.host = host; this.app = app;
    this.vb = { ...VB };
    this.layers = Object.fromEntries([...LAYERS.comp, ...LAYERS.text].map(l => [l.id, true]));
    this.disp = {};
    try {
      const s = JSON.parse(localStorage.getItem(STORE) || "{}");
      Object.assign(this.layers, s.layers || {});
      this.disp = s.disp || {};
    } catch (e) { /* storage unavailable */ }
    this.layers.net = true;
    this._panzoom();
  }

  // view settings
  _save() { try { localStorage.setItem(STORE, JSON.stringify({ layers: this.layers, disp: this.disp })); } catch (e) { /* storage unavailable */ } }
  setLayer(id, on) { if (id === "net") return; this.layers[id] = on; this._save(); this._applyLayers(); this._dirty(); this._needPlace = true; }
  isOn(key, q) {
    const o = this.disp[key];
    if (o && q in o) return o[q];
    const kind = key.split(":")[0];
    const d = (QTY[kind] || []).find(x => x[0] === q);
    return d ? !!d[3] : true;
  }
  setOn(key, q, on) { (this.disp[key] = this.disp[key] || {})[q] = on; this._save(); this._dirty(); }
  _dirty() { for (const b of this.blocks || []) b.sig = null; }
  _applyLayers() {
    if (!this.root) return;
    for (const g of this.root.querySelectorAll("[data-layer]")) g.style.display = this.layers[g.dataset.layer] ? "" : "none";
  }

  // geometry
  pos(id, other) {
    const b = this.bus[id];
    const sl = this.barSlots && this.barSlots[id] && other && this.barSlots[id].all.find(x => x.key === "line:" + other);
    if (sl) return { x: b.x, y: b.y + sl.dy };
    if (id === "800") {
      const o = other ? this.bus[other] : null;
      return { x: BUSBAR.x, y: o ? o.y : SRC_Y };
    }
    return { x: b.x, y: b.y };
  }

  build(topo, run, layout) {
    this.topo = topo; this.run = run;
    this.barSlots = {};
    this.bus = Object.fromEntries(topo.buses.map(b => {
      const L = layout && layout[b.id];
      return [b.id, L ? { ...b, x: L.x, y: L.y } : b];
    }));
    const s = this.svg;
    s.innerHTML = "";
    this.root = el("g", {}, s);
    this.blocks = [];
    const mk = n => el("g", { "data-layer": n }, this.root);
    this.G = { net: mk("net"), flow: mk("flow"), shunt: mk("shunt"), der: mk("der"), prot: mk("prot"), inst: mk("inst"), top: mk("net"), god: mk("god") };
    this.T = {};
    for (const n of ["net", "shunt", "der", "inst", "prot", "god"]) this.T[n] = el("g", { "data-layer": n, class: "lbl-layer" }, this.root);
    this._dirs();
    this._planBars(run);
    for (const b of topo.buses) if (b.virtual) this._placeVirtual(b, topo);
    this._iedPlan();
    this._labelSides();
    this._captions();
    this._lines();
    this._substation();
    this._buses();
    this._ieds();
    this._ders(run ? run.der : []);     // DERs claim a free side first; loads and capacitors fit around them
    this._loads();
    this._caps();
    for (const id of Object.keys(this.barSlots)) this._drawBar(id);   // every busbar is drawn once
    this._god(run);
    this._applyLayers();
    this._needPlace = true;
    const atFull = !this.full || (this.vb.x === this.full.x && this.vb.y === this.full.y && this.vb.w === this.full.w && this.vb.h === this.full.h);
    this.full = { ...VB, w: this.vbW };
    if (atFull) this.vb = { ...this.full };
    this.applyVB();
  }

  // A bus that needs more connections than it has free sides is drawn as a vertical busbar. The
  // feeder trunk enters and leaves at its centre (horizontal connections only). Every other
  // connection (lateral, DER, load, capacitor) also leaves the bar horizontally, to the right, at its
  // own height and then turns up or down; the column nearest the bar leaves furthest from the centre
  // so no conductors cross. Buses further along the feeder move right to make room, and each lateral
  // subtree moves right with its column.
  _planBars(run) {
    this.ext = {}; this.barSlots = {};
    const need = {};
    const add = id => { const b = this.bus[id]; if (b && id !== "800" && !b.virtual) need[id] = (need[id] || 0) + 1; };
    const ders = run ? run.der : [];
    for (const d of ders) add(d.bus);
    for (const id of new Set(this.topo.loads.map(l => l.bus))) add(id);
    for (const c of this.topo.caps) add(c.bus);
    const reservedUp = {}, reserved = {};
    for (const m of this.topo.ieds) {
      if (m.from === "800") continue;
      const a = this.bus[m.from], c = this.bus[m.to] || a;
      const side = Math.abs(c.x - a.x) < Math.abs(c.y - a.y) ? "L" : "U";
      if (side === "U") reservedUp[m.from] = 1;
      if (!this.used[m.from].has(side)) reserved[m.from] = 1;
    }
    const adj = {};
    for (const br of this.topo.branches) { (adj[br.from] = adj[br.from] || []).push(br.to); (adj[br.to] = adj[br.to] || []).push(br.from); }
    const subtree = (root, block) => { const seen = new Set([root]), q = [root]; while (q.length) { const v = q.shift(); for (const w of adj[v] || []) if (w !== block && !seen.has(w)) { seen.add(w); q.push(w); } } return seen; };
    const x0 = Object.fromEntries(Object.entries(this.bus).map(([k, b]) => [k, b.x]));
    const maxX = () => Math.max(...Object.values(this.bus).map(b => b.x));
    const before = maxX();
    const COL = 42, DX0 = 26, STEP = 16, DY0 = 16;
    for (const [id, n] of Object.entries(need)) {
      const u = this.used[id], b = this.bus[id];
      if (!(u.has("L") || u.has("R"))) continue;          // vertical-only buses keep the simple fallback
      if (n - (4 - u.size - (reserved[id] || 0)) <= 0) continue;
      const up = [], down = [], upL = [], downL = [];
      for (const o of adj[id] || []) {
        const ob = this.bus[o]; if (!ob || o === "800") continue;
        if (Math.abs(ob.x - b.x) < 1 && ob.y < b.y) upL.push({ key: "line:" + o, other: o });
        else if (Math.abs(ob.x - b.x) < 1 && ob.y > b.y) downL.push({ key: "line:" + o, other: o });
      }
      // equipment goes to the side of the bar that has no lateral where possible (and never above a relay)
      const upOK = !reservedUp[id], onlyUpL = upL.length && !downL.length, onlyDownL = downL.length && !upL.length;
      for (const d of ders.filter(d => d.bus === id)) (upOK && !onlyUpL ? up : down).push({ key: "der:" + d.id });
      if (this.topo.loads.some(l => l.bus === id)) (upOK && onlyDownL ? up : down).push({ key: "load" });
      for (const c of this.topo.caps.filter(c => c.bus === id)) (upOK && !onlyUpL ? up : down).push({ key: "cap:" + c.id });
      up.unshift(...upL); down.unshift(...downL);     // laterals take the inner columns so their subtrees move least
      const lay = (L, sign) => L.forEach((it, i) => { it.side = sign < 0 ? "up" : "down"; it.dx = DX0 + COL * i; it.dy = sign * (DY0 + STEP * (L.length - 1 - i)); });
      lay(up, -1); lay(down, 1);
      const cols = Math.max(up.length, down.length, 1);
      const last = DX0 + COL * (cols - 1);
      const slot = { up, down, all: [...up, ...down], labelDx: last + 14, ext: last + 74 };
      this.barSlots[id] = slot;
      this.ext[id] = slot.ext;
      // lateral subtrees move with their column; everything else further along moves by the bar width
      const moved = new Set();
      for (const it of slot.all) if (it.other) for (const k of subtree(it.other, id)) { if (this.bus[k]) { this.bus[k].x += it.dx; moved.add(k); } }
      const f = b.feeder;
      for (const [k, bb] of Object.entries(this.bus)) if (k !== "800" && !moved.has(k) && bb.feeder === f && x0[k] > x0[id]) bb.x += slot.ext;
    }
    this.vbW = VB.w + (maxX() - before);
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

  // Text block: a <text> with one line per enabled quantity, refreshed only when its content changes.
  _block(layer, x, y, anchor, grow, items) {
    const t = el("text", { x, y, "text-anchor": anchor, class: "lbl" }, this.T[layer]);
    const b = { t, x, y, anchor, grow, items, sig: null, layer };
    this.blocks.push(b);
    return b;
  }
  _renderBlock(b) {
    const lines = [];
    for (const it of b.items) {
      if (!this.layers[it.cat]) continue;
      if (it.layer && !this.layers[it.layer]) continue;
      if (it.key && !this.isOn(it.key, it.q)) continue;
      let v = it.fn();
      if (v === null || v === undefined || v === "") continue;
      if (typeof v === "string") v = { t: v };
      lines.push({ t: v.t, c: v.c, cls: it.cls || "v" });
    }
    const sig = lines.map(l => `${l.t}|${l.c || ""}|${l.cls}`).join("\n") + `@${b.x},${b.y},${b.anchor},${b.grow}`;
    if (sig === b.sig) return;
    b.sig = sig;
    b.t.textContent = "";
    const n = lines.length;
    const y0 = b.grow === "up" ? b.y - (n - 1) * LH : b.grow === "mid" ? b.y - (n - 1) * LH / 2 + 4 : b.y;
    lines.forEach((l, i) => {
      const ts = el("tspan", { x: b.x, y: y0 + i * LH, class: l.cls, style: l.c ? `fill:${l.c}` : null }, b.t);
      ts.textContent = l.t;
    });
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
    this.bars = {};
    this.barEls = {};
  }
  // Rough area an element hung from a bus will occupy, label included.
  _foot(x, y, d, kind) {
    const L = { load: 50, cap: 46, der: 88 }[kind] || 50, w = { load: 8, cap: 11, der: 17 }[kind] || 8, lab = kind === "der" ? 0 : 44;
    if (d === "U") return { x1: x - w, x2: x + w + lab, y1: y - L, y2: y - 6 };
    if (d === "D") return { x1: x - w, x2: x + w + lab, y1: y + 6, y2: y + L };
    if (d === "R") return { x1: x + 6, x2: x + L + lab, y1: y - w, y2: y + w };
    return { x1: x - L - lab, x2: x - 6, y1: y - w, y2: y + w };
  }
  _hits(r) { return (this.feet || []).some(f => r.x1 < f.x2 && r.x2 > f.x1 && r.y1 < f.y2 && r.y2 > f.y1); }

  // Where a shunt element connects. On a busbar it uses its planned slot (a horizontal connector
  // from the bar); otherwise a free side of the bus node whose area is clear of placed equipment.
  tap(bid, pref, kind, key) {
    const b = this.bus[bid];
    const S = this.barSlots[bid];
    if (S) {
      const it = S.all.find(x => x.key === key);
      const layer = kind === "der" ? this.G.der : this.G.shunt;
      const conn = el("line", { x1: b.x, y1: b.y + it.dy, x2: b.x + it.dx, y2: b.y + it.dy, "stroke-width": 1.7 }, layer);
      return { dir: it.side === "up" ? "U" : "D", ax: it.dx, ay: it.dy, bar: false, onBar: true, conn };
    }
    const u = this.used[bid]; const sl = this.slot[bid] = this.slot[bid] || new Set();
    const free = pref.filter(d => !u.has(d) && !sl.has(d));
    const pick = free.find(d => !this._hits(this._foot(b.x, b.y, d, kind))) || free[0];
    if (pick) {
      sl.add(pick);
      this.feet.push(this._foot(b.x, b.y, pick, kind));
      return { dir: pick, ax: 0, ay: 0, bar: false, onBar: false };
    }
    // vertical-only bus with no free side: short bar along the lateral
    const n = this.bars[bid] = (this.bars[bid] || 0) + 1;
    const T = { dir: pref.find(d => d === "L" || d === "R") || "R", ax: 0, ay: -40 * n, bar: true };
    this._drawSideBar(bid, T.ay);
    return T;
  }
  _drawSideBar(bid, ay) {
    const b = this.bus[bid];
    const y1 = b.y + ay - 7;
    const e = this.barEls[bid];
    if (e) { e.setAttribute("y1", Math.min(+e.getAttribute("y1"), y1)); return; }
    this.barEls[bid] = el("line", { x1: b.x, y1, x2: b.x, y2: b.y + 4, stroke: C.ink, "stroke-width": 5, "stroke-linecap": "butt" }, this.G.top);
  }
  _drawBar(bid) {
    const b = this.bus[bid], S = this.barSlots[bid];
    if (this.barEls[bid]) return;
    const up = Math.max(10, ...S.up.map(x => -x.dy)) + 6, down = Math.max(10, ...S.down.map(x => x.dy)) + 6;
    const bar = this.barEls[bid] = el("line", { x1: b.x, y1: b.y - up, x2: b.x, y2: b.y + down, stroke: C.ink, "stroke-width": 7, "stroke-linecap": "butt", class: "clickable" }, this.G.top);
    bar.addEventListener("click", ev => this.app.inspect("bus", bid, ev));
  }
  off(dir, r) {
    const m = { U: [0, -r], D: [0, r], L: [-r, 0], R: [r, 0] };
    return m[dir] || [0, r];
  }

  // Each protection point: breaker, CT, VT and relay are laid out along the protected line.
  // The relay sits above a horizontal line or to the left of a vertical one.
  _iedPlan() {
    this.iedGeo = {};
    this.feet = [];
    for (const m of this.topo.ieds) {
      const br = this.topo.branches.find(b => b.from === m.from && (b.to === m.to || b.parent === `L${m.from}-${m.to}`)) ||
                 this.topo.branches.find(b => b.from === m.from);
      const a = this.pos(m.from, br.to), c = this.pos(br.to, m.from);
      const L = Math.hypot(c.x - a.x, c.y - a.y) || 1;
      const ux = (c.x - a.x) / L, uy = (c.y - a.y) / L;
      const vert = Math.abs(uy) > Math.abs(ux);
      const nx = vert ? -1 : 0, ny = vert ? 0 : -1;
      // Start the assembly clear of the bus labels (busbar 800 has none beside it).
      const s0 = (m.from === "800" ? 14 : vert ? 0 : 34) + (this.ext[m.from] || 0);
      const P = (s, n) => ({ x: a.x + ux * (s + s0) + nx * n, y: a.y + uy * (s + s0) + ny * n });
      this.iedGeo[m.id] = { m, br, a, c, ux, uy, nx, ny, vert, P };
      const rcf = P(RS, RN);
      this.feet.push(vert ? { x1: rcf.x - 115, x2: rcf.x + 16, y1: rcf.y - 26, y2: rcf.y + 26 }
                          : { x1: rcf.x - 70, x2: rcf.x + 70, y1: rcf.y - 78, y2: rcf.y + 16 });
      if (m.from !== "800") {
        // keep the relay side of the bus free for the VT and the relay
        const sides = vert ? ["L"] : ["U"];
        this.slot[m.from] = this.slot[m.from] || new Set();
        for (const sd of sides) this.slot[m.from].add(sd);
      }
    }
  }

  _labelSides() {
    this.labelLeft = new Set();
    const rc = Object.values(this.iedGeo).map(g => g.P(RS, RN));
    for (const b of Object.values(this.bus)) {
      if (rc.some(c => c.x > b.x && c.x - b.x < 130 && c.y > b.y && c.y - b.y < 100)) this.labelLeft.add(b.id);
    }
  }

  _captions() {
    const cap = (x, y, t) => this._block("net", x, y, "start", "down", [{ cat: "id", cls: "cap", fn: () => t }]);
    cap(186, 92, "Feeder A: IEEE 34-node test feeder, 24.9 kV");
    const bx = Math.max(...Object.values(this.bus).filter(b => b.feeder === "B").map(b => b.x));
    cap(bx + 60, 520, "Feeder B: equivalent feeder for F-2 testing, 24.9 kV");
    cap(10, 478, "Substation");
    cap(10, 495, "69/24.9 kV");
  }

  _lines() {
    this.lineEls = {};
    for (const br of this.topo.branches) {
      const a = this.pos(br.from, br.to), c = this.pos(br.to, br.from);
      let d = `M${a.x},${a.y} L${c.x},${c.y}`;
      if (a.x !== c.x && a.y !== c.y) d = `M${a.x},${a.y} L${c.x},${a.y} L${c.x},${c.y}`;
      const len = Math.abs(c.x - a.x) + Math.abs(c.y - a.y);
      const w = br.phases.length === 3 ? 3 : 1.9;
      const p = el("path", { d, class: "sld-line", "stroke-width": w, stroke: C.ink }, this.G.net);
      const hit = el("path", { d, class: "sld-hit" }, this.G.net);
      const kind = br.kind === "line" ? "line" : br.kind;
      hit.addEventListener("click", ev => this.app.inspect(kind, br.id, ev));
      const mid = { x: (a.x + c.x) / 2, y: (a.y + c.y) / 2 };
      const fl = el("g", {}, this.G.flow);
      const e = { p, br, d, len, fl, w, state: "", syms: [] };
      this.lineEls[br.id] = e;
      if (br.kind === "reg") this._regSym(mid, br, a, c, e);
      else if (br.kind === "xfmr") this._xfSym(mid, br, a, c, e);
      else if (br.kind === "line") {
        const key = "line:" + br.id;
        const vert = a.x === c.x;
        this._block("net", mid.x + (vert ? 8 : 0), mid.y + (vert ? 0 : 16), vert ? "start" : "middle", vert ? "mid" : "down", [
          { key, q: "id", cat: "id", cls: "v", fn: () => br.id },
          ...this._branchItems(key, br),
        ]);
      }
    }
  }
  _branchItems(key, br) {
    const j = () => this.app.brIdx[br.id];
    return [
      { key, q: "iabc", cat: "in", fn: () => this.S ? `I ${tri(this.S.run.Ibr[this.S.k][j()], 0)} A` : null },
      { key, q: "pq", cat: "in", fn: () => { if (!this.S) return null; const P = this.S.run.Pbr[this.S.k][j()]; return `P ${fmt(P[0], 0)} kW, Q ${fmt(P[1], 0)} kvar`; } },
    ];
  }

  // Animated arrows travelling along the line in the direction of active power flow.
  _setFlow(e, state) {
    if (e.state === state) return;
    e.state = state;
    e.fl.innerHTML = "";
    if (!state) return;
    const [dir, lvl] = state.split(":");
    const rev = dir === "r";
    const speed = [45, 75, 110][+lvl];
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

  // IEC 60617: transformer with variable ratio (oblique arrow) for the step-voltage regulator.
  _regSym(m, br, a, c, e) {
    const vert = a.x === c.x;
    const g = el("g", { class: "clickable sym", transform: `translate(${m.x},${m.y})` }, this.G.top);
    const dx = vert ? 0 : 7, dy = vert ? 7 : 0;
    e.syms.push(el("circle", { cx: -dx, cy: -dy, r: 10.5, fill: "#fff", "stroke-width": 1.6 }, g), el("circle", { cx: dx, cy: dy, r: 10.5, fill: "none", "stroke-width": 1.6 }, g));
    e.syms.push(el("path", { d: "M-15,13 L14,-14", fill: "none", "stroke-width": 1.5 }, g));
    e.syms.push(el("path", { d: "M14,-14 L6.5,-12.3 L12.3,-6.5 Z", "stroke-width": 1, "stroke-linejoin": "round" }, g));
    g.addEventListener("click", ev => this.app.inspect("reg", br.id, ev));
    const key = "reg:" + br.id;
    this._block("net", m.x, m.y - 20, "middle", "up", [
      { key, q: "id", cat: "id", cls: "id", fn: () => br.id },
      { key, q: "rate", cat: "rate", cls: "r", fn: () => `Tap ${br.taps.join(" / ")}` },
      ...this._branchItems(key, br),
    ]);
  }
  _xfSym(m, br, a, c, e) {
    const vert = a.x === c.x;
    const g = el("g", { class: "clickable sym", transform: `translate(${m.x},${m.y})` }, this.G.top);
    const dx = vert ? 0 : 8, dy = vert ? 8 : 0;
    e.syms.push(el("circle", { cx: -dx, cy: -dy, r: 11.5, fill: "#fff", "stroke-width": 1.6 }, g), el("circle", { cx: dx, cy: dy, r: 11.5, fill: "none", "stroke-width": 1.6 }, g));
    g.addEventListener("click", ev => this.app.inspect("xfmr", br.id, ev));
    const key = "xfmr:" + br.id;
    this._block("net", m.x - 21, m.y, "end", "mid", [
      { key, q: "id", cat: "id", cls: "id", fn: () => br.id },
      { key, q: "rate", cat: "rate", cls: "r", fn: () => `${br.kva} kVA, ${br.kv1}/${br.kv2} kV` },
      ...this._branchItems(key, br),
    ]);
  }

  _substation() {
    const g = this.G.top, y = SRC_Y;
    el("line", { x1: BUSBAR.x, y1: BUSBAR.y1, x2: BUSBAR.x, y2: BUSBAR.y2, stroke: C.ink, "stroke-width": 6, "stroke-linecap": "butt" }, g);
    this._block("net", BUSBAR.x, BUSBAR.y1 - 10, "middle", "up", [{ key: "bus:800", q: "id", cat: "id", cls: "id", fn: () => "800" }]);
    el("line", { x1: 30, y1: y, x2: BUSBAR.x, y2: y, stroke: C.ink, "stroke-width": 3 }, this.G.net);
    // Network infeed: IEC generator circle with an AC sine
    const src = el("g", { class: "clickable sym", transform: `translate(30,${y})` }, g);
    el("circle", { r: 16, fill: "#fff", "stroke-width": 1.6 }, src);
    el("path", { d: "M-9,0 C-4.5,-9 0,-9 0,0 C0,9 4.5,9 9,0", fill: "none", "stroke-width": 1.6 }, src);
    src.addEventListener("click", ev => this.app.inspect("sub", "SUB", ev));
    this.subCB = el("rect", { x: 49, y: y - 8, width: 16, height: 16, class: "clickable", "stroke-width": 2 }, g);
    this.subCB.addEventListener("click", ev => this.app.inspect("cb", "SUB", ev));
    const tx = el("g", { class: "clickable sym", transform: `translate(92,${y})` }, g);
    el("circle", { cx: -8, r: 11.5, fill: "#fff", "stroke-width": 1.6 }, tx);
    el("circle", { cx: 8, r: 11.5, fill: "none", "stroke-width": 1.6 }, tx);
    tx.addEventListener("click", ev => this.app.inspect("sub", "SUB", ev));
    const S = () => this.S;
    this._block("net", 30, y + 34, "middle", "down", [
      { key: "src:SUB", q: "rate", cat: "rate", cls: "r", fn: () => "69 kV" },
      { key: "src:SUB", q: "pq", cat: "in", fn: () => { if (!S()) return null; const a = this.app.brIdx[this.app.brForIED("A1")], b = this.app.brIdx[this.app.brForIED("B1")]; const P = (S().run.Pbr[S().k][a]?.[0] || 0) + (S().run.Pbr[S().k][b]?.[0] || 0); return `P ${fmt(P, 0)} kW`; } },
      { key: "src:SUB", q: "f", cat: "in", fn: () => S() ? `${fmt(S().run.freq[S().k], 2)} Hz` : null },
    ]);
    this._block("net", 57, y - 18, "middle", "up", [
      { key: "cb:SUB", q: "id", cat: "id", cls: "id", fn: () => "CB-GI" },
      { key: "cb:SUB", q: "st", cat: "out", fn: () => S() ? (S().run.sub[S().k] ? "Closed" : { t: "Open", c: C.warn }) : null },
    ]);
    this._block("net", 92, y + 34, "middle", "down", [{ key: "src:SUB", q: "rate", cat: "rate", cls: "r", fn: () => `${this.topo.substation?.kva ?? 2500} kVA` }]);
  }

  _buses() {
    this.busEls = {};
    for (const b0 of this.topo.buses) {
      const b = this.bus[b0.id];
      if (b.id === "800" || b.virtual) continue;
      const g = el("g", { class: "clickable", transform: `translate(${b.x},${b.y})` }, this.G.top);
      const r = b.phases.length === 3 ? 6 : 4.8;
      const c = el("circle", { r, fill: C.ink, stroke: "#fff", "stroke-width": 1.5 }, g);
      const onBar = !!this.barSlots[b.id];
      if (onBar) g.style.display = "none";
      g.addEventListener("click", ev => this.app.inspect("bus", b.id, ev));
      const left = this.labelLeft.has(b.id);
      const ax = left ? -12 : onBar ? this.barSlots[b.id].labelDx : 12, anc = left ? "end" : "start";
      const key = "bus:" + b.id;
      const ph = b.phases.length < 3 ? ` (${b.phases.toUpperCase()})` : "";
      const e = { c, b, st: "good" };
      const V = () => this.S ? this.S.run.Vpu[this.S.k][this.app.busIdx[b.id]] : null;
      const idItem = { key, q: "id", cat: "id", cls: "id", fn: () => b.id + ph };
      if (!onBar) this._block("net", b.x + ax, b.y - 10, anc, "up", [idItem]);
      this._block("net", b.x + ax, onBar ? b.y - 10 : b.y + 23, anc, onBar ? "up" : "down", [...(onBar ? [idItem] : []),
        { key, q: "vmin", cat: "in", fn: () => this.S ? (e.st === "dead" ? { t: "0 pu", c: C.mute } : { t: fmt(e.vmin, 3) + " pu", c: e.st === "crit" ? C.crit : e.st === "warn" ? C.warn : undefined }) : null },
        { key, q: "vabc", cat: "in", fn: () => V() ? `V ${tri(V(), 3)} pu` : null },
        { key, q: "vkv", cat: "in", fn: () => this.S && e.vmin != null ? `${fmt(e.vmin * b.kv / Math.sqrt(3), 2)} kV` : null },
        { key, q: "st", cat: "out", fn: () => this.S ? (e.st === "dead" ? { t: "De-energized", c: C.mute } : "Energized") : null },
      ]);
      this.busEls[b.id] = e;
    }
  }

  // IEC 60617 load: an arrow leaving the bus.
  _loads() {
    this.loadEls = {};
    const byBus = {};
    for (const l of this.topo.loads) (byBus[l.bus] = byBus[l.bus] || []).push(l);
    for (const [bid, ls] of Object.entries(byBus)) {
      if (!this.bus[bid] || bid === "800" || this.bus[bid].virtual) continue;
      const b = this.bus[bid];
      const T = this.tap(bid, ["D", "U", "R", "L"], "load", "load"), d = T.dir;
      const X = b.x + T.ax, Y = b.y + T.ay;
      const len = d === "U" || d === "D" ? 42 : 46;
      const [ox, oy] = this.off(d, len);
      const L = Math.hypot(ox, oy), ux = ox / L, uy = oy / L, nx = -uy, ny = ux;
      const kw = ls.reduce((s, l) => s + l.P.reduce((a, c) => a + c, 0), 0);
      const g = el("g", { class: "clickable sym", transform: `translate(${X},${Y})` }, this.G.shunt);
      const bx = ox - ux * 12, by = oy - uy * 12, s0 = T.bar || T.onBar ? 0 : 7;
      const stub = el("path", { d: `M${ux * s0},${uy * s0} L${bx},${by}`, fill: "none", "stroke-width": 1.7 }, g);
      const head = el("path", { d: `M${ox},${oy} L${bx + nx * 6},${by + ny * 6} L${bx - nx * 6},${by - ny * 6} Z`, "stroke-width": 1, "stroke-linejoin": "round" }, g);
      el("path", { d: `M0,0 L${ox},${oy}`, stroke: "transparent", "stroke-width": 12, fill: "none" }, g);
      g.addEventListener("click", ev => this.app.inspect("load", bid, ev));
      const key = "load:" + bid;
      let lx, ly, anc, grow;
      if (d === "L" || d === "R") { lx = X + ox + ux * 7; ly = Y; anc = d === "L" ? "end" : "start"; grow = "mid"; }
      else if (T.bar) { lx = X + ox; ly = Y + oy + (uy > 0 ? 15 : -7); anc = "middle"; grow = uy > 0 ? "down" : "up"; }
      else { lx = X + ox + 9; ly = Y + oy - uy * 6; anc = "start"; grow = "mid"; }
      this._block("shunt", lx, ly, anc, grow, [
        { key, q: "rate", cat: "rate", cls: "r", fn: () => `${Math.round(kw)} kW` },
        { key, q: "st", cat: "out", fn: () => this.S ? (this.S.run.energized[this.S.k][this.app.busIdx[bid]] ? "Energized" : { t: "De-energized", c: C.mute }) : null },
      ]);
      this.loadEls[bid] = { g, parts: [stub, head, ...(T.conn ? [T.conn] : [])], kw };
    }
  }

  // IEC 60617 capacitor (two plates) connected to earth.
  _caps() {
    this.capEls = {};
    for (const c of this.topo.caps) {
      const b = this.bus[c.bus];
      const T = this.tap(c.bus, ["U", "L", "R", "D"], "cap", "cap:" + c.id), d = T.dir;
      const X = b.x + T.ax, Y = b.y + T.ay;
      const [ox, oy] = this.off(d, 30);
      const L = Math.hypot(ox, oy), ux = ox / L, uy = oy / L;
      const g = el("g", { class: "clickable sym", transform: `translate(${X},${Y})` }, this.G.shunt);
      const parts = [];
      parts.push(el("path", { d: `M${ux * (T.onBar ? 0 : 7)},${uy * (T.onBar ? 0 : 7)} L${ox - ux * 3.5},${oy - uy * 3.5} M${ox + ux * 3.5},${oy + uy * 3.5} L${ox + ux * 14},${oy + uy * 14}`, fill: "none", "stroke-width": 1.7 }, g));
      const ang = Math.atan2(uy, ux) * 180 / Math.PI;
      const pl = el("g", { transform: `translate(${ox},${oy}) rotate(${ang})` }, g);
      parts.push(el("path", { d: "M-3.5,-9.5 L-3.5,9.5 M3.5,-9.5 L3.5,9.5", fill: "none", "stroke-width": 2.3 }, pl));
      // earth: three bars of decreasing width
      const eg = el("g", { transform: `translate(${ox + ux * 14},${oy + uy * 14}) rotate(${ang})` }, g);
      parts.push(el("path", { d: "M0,-8 L0,8 M3.5,-5 L3.5,5 M7,-2.2 L7,2.2", fill: "none", "stroke-width": 1.7 }, eg));
      el("path", { d: `M0,0 L${ox + ux * 14},${oy + uy * 14}`, stroke: "transparent", "stroke-width": 14, fill: "none" }, g);
      g.addEventListener("click", ev => this.app.inspect("cap", c.id, ev));
      const vert = d === "U" || d === "D";
      const key = "cap:" + c.id;
      const lx = vert ? X + ox + (T.bar ? -14 : 14) : X + ox + ux * 25, ly = vert ? Y + oy + uy * 11 : Y;
      this._block("shunt", lx, ly, vert ? (T.bar ? "end" : "start") : ux < 0 ? "end" : "start", "mid", [
        { key, q: "id", cat: "id", cls: "id2", fn: () => c.id },
        { key, q: "rate", cat: "rate", cls: "r", fn: () => `${c.kvar[0]} kvar/ph` },
        { key, q: "st", cat: "out", fn: () => !c.on ? { t: "Out of service", c: C.mute } : this.S ? (this.S.run.energized[this.S.k][this.app.busIdx[c.bus]] ? "In service" : { t: "De-energized", c: C.mute }) : null },
      ]);
      if (T.conn) parts.push(T.conn);
      this.capEls[c.id] = { parts, c };
    }
  }

  // DER: interconnection transformer, then IEC generator (SG) or inverter (IBR) symbol.
  _ders(ders) {
    this.derEls = {};
    for (const d of ders || []) {
      const b = this.bus[d.bus];
      if (!b) continue;
      const T = this.tap(d.bus, ["U", "D", "R", "L"], "der", "der:" + d.id), dir = T.dir;
      const X = b.x + T.ax, Y = b.y + T.ay;
      const [ox, oy] = this.off(dir, 86);
      const L = Math.hypot(ox, oy), ux = ox / L, uy = oy / L;
      const g = el("g", { class: "clickable sym", transform: `translate(${X},${Y})` }, this.G.der);
      const parts = [];
      const T1 = 30, T2 = 42, BODY = 86 - 16;
      parts.push(el("path", { d: `M${ux * (T.onBar ? 0 : 7)},${uy * (T.onBar ? 0 : 7)} L${ux * (T1 - 7)},${uy * (T1 - 7)} M${ux * (T2 + 7)},${uy * (T2 + 7)} L${ux * (BODY - 15)},${uy * (BODY - 15)}`, fill: "none", "stroke-width": 1.7 }, g));
      parts.push(el("circle", { cx: ux * T1, cy: uy * T1, r: 7, fill: "#fff", "stroke-width": 1.5 }, g));
      parts.push(el("circle", { cx: ux * T2, cy: uy * T2, r: 7, fill: "none", "stroke-width": 1.5 }, g));
      const bx = ux * BODY, by = uy * BODY;
      const body = el("g", { transform: `translate(${bx},${by})` }, g);
      if (d.type === "SG") {
        parts.push(el("circle", { r: 15, fill: "#fff", "stroke-width": 1.8 }, body));
        const tG = el("text", { x: 0, y: 1.5, "text-anchor": "middle", class: "symtxt" }, body); tG.textContent = "G";
        parts.push(el("path", { d: "M-5,8 q2.5,-3.4 5,0 t5,0", fill: "none", "stroke-width": 1.3 }, body));
        parts.push(tG);
      } else {
        // IEC inverter: square with a diagonal, DC mark top left and AC mark bottom right
        parts.push(el("rect", { x: -14, y: -14, width: 28, height: 28, fill: "#fff", "stroke-width": 1.8 }, body));
        parts.push(el("path", { d: "M-14,14 L14,-14", fill: "none", "stroke-width": 1.3 }, body));
        parts.push(el("path", { d: "M-10.5,-8 L-2.5,-8", fill: "none", "stroke-width": 1.3 }, body));
        parts.push(el("path", { d: "M-10.5,-4.5 L-2.5,-4.5", fill: "none", "stroke-width": 1.3, "stroke-dasharray": "2.2 1.6" }, body));
        parts.push(el("path", { d: "M2,7 q2,-3.4 4,0 t4,0", fill: "none", "stroke-width": 1.3 }, body));
      }
      g.addEventListener("click", ev => this.app.inspect("der", d.id, ev));
      const left = dir === "L" || (dir !== "R" && X + 190 > this.vbW);
      const lx = X + bx + (left ? -23 : 23), ly = Y + by;
      const key = "der:" + d.id;
      const j = () => this.app.derIdx[d.id];
      const R = () => this.S ? this.S.run.der[j()] : null;
      const tech = d.type === "SG" ? "SG" : d.type === "IBR-GFM" ? "GFM" : "PV, GFL";
      this._block("der", lx, ly, left ? "end" : "start", "mid", [
        { key, q: "id", cat: "id", cls: "id", fn: () => d.id },
        { key, q: "rate", cat: "rate", cls: "r", fn: () => `${tech}, ${Math.round(d.kva)} kVA` },
        { key, q: "pq", cat: "in", fn: () => R() && R().on[this.S.k] ? `P ${fmt(R().P[this.S.k], 0)} kW, Q ${fmt(R().Q[this.S.k], 0)} kvar` : null },
        { key, q: "iabc", cat: "in", fn: () => R() ? `I ${tri(R().I[this.S.k], 0)} A` : null },
        { key, q: "irr", cat: "in", fn: () => R() && R().irr ? `${fmt(R().irr[this.S.k], 0)} W/m²` : null },
        { key, q: "st", cat: "out", fn: () => R() ? (R().on[this.S.k] ? "In service" : { t: "Disconnected", c: C.warn }) : null },
      ]);
      const blk = this.blocks[this.blocks.length - 1];
      blk.base = { x: X + bx, y: Y + by };
      blk.owner = g;
      const side = [[23, 0, "start", "mid"], [-23, 0, "end", "mid"], [23, -24, "start", "up"], [-23, -24, "end", "up"], [23, 24, "start", "down"], [-23, 24, "end", "down"]];
      const along = dir === "U" ? [[0, -26, "middle", "up"]] : dir === "D" ? [[0, 34, "middle", "down"]] : [];
      blk.cands = left ? [side[1], side[0], ...along, ...side.slice(2)] : [side[0], side[1], ...along, ...side.slice(2)];
      if (T.conn) parts.push(T.conn);
      this.derEls[d.id] = { parts, d };
    }
  }

  // Protection point: CB on the line, CT downstream of it, VT on the bus side, relay wired to all three.
  _ieds() {
    this.iedEls = {};
    for (const m of this.topo.ieds) {
      const G = this.iedGeo[m.id];
      const { P, vert } = G;
      const j = () => this.app.iedIdx[m.id];
      const R = () => this.S ? this.S.run.ied[j()] : null;
      const cls = this.run ? this.run.ied.find(x => x.id === m.id)?.cls : "OCR";
      const fn = FUNC[cls] || [cls, cls];
      const hw = RH, hn = RH;
      const rc = P(RS, RN);
      const sCB = SCB, sCT = vert ? SCTV : SCT, sVT = vert ? SVTV : SVT;
      // wiring (protection layer)
      const wires = el("g", { class: "wires" }, this.G.prot);
      const pts = (...a) => a.map(p => `${p.x},${p.y}`).join(" ");
      const ctW = el("polyline", { points: pts(P(sCT, 8), P(sCT, RN - hn)), fill: "none" }, wires);
      const vtW = el("polyline", { points: pts(P(sVT, 39), P(sVT, RN), P(RS - hw, RN)), fill: "none" }, wires);
      const tripW = el("polyline", { points: pts(P(sCB + 4, RN - hn), P(sCB + 4, 13)), fill: "none", class: "trip" }, this.G.prot);
      const tip = P(sCB + 4, 8.5), tb = P(sCB + 4, 15);
      const tdx = (tb.x - tip.x), tdy = (tb.y - tip.y);
      const arrow = el("path", { d: `M${tip.x},${tip.y} L${tb.x + tdy * 0.6},${tb.y - tdx * 0.6} L${tb.x - tdy * 0.6},${tb.y + tdx * 0.6} Z`, class: "trip-head" }, this.G.prot);
      // relay (IEC: rectangle with qualifying symbol)
      const rg = el("g", { class: "clickable", transform: `translate(${rc.x},${rc.y})` }, this.G.prot);
      const box = el("rect", { x: -hn, y: -hw, width: 2 * hn, height: 2 * hw, fill: "#fff", stroke: C.ink, "stroke-width": 1.6 }, rg);
      const ft = el("text", { x: 0, y: 4.5, "text-anchor": "middle", class: "symtxt fn" }, rg); ft.textContent = "R";
      rg.addEventListener("click", ev => this.app.inspect("ied", m.id, ev));
      // CT: IEC ring threaded by the primary conductor
      const ctp = P(sCT, 0);
      const ctg = el("g", { class: "clickable sym", transform: `translate(${ctp.x},${ctp.y})` }, this.G.inst);
      const ctc = el("circle", { r: 7.5, fill: "none", "stroke-width": 1.7 }, ctg);
      el("circle", { r: 12, fill: "transparent", stroke: "none" }, ctg);
      ctg.addEventListener("click", ev => this.app.inspect("ct", m.id, ev));
      // VT: two coupled windings tapped from the bus side of the breaker
      const vt0 = P(sVT, 0), vt1 = P(sVT, 16), va = P(sVT, 22), vb = P(sVT, 32);
      const vtg = el("g", { class: "clickable sym" }, this.G.inst);
      const vtl = el("line", { x1: vt0.x, y1: vt0.y, x2: vt1.x, y2: vt1.y, "stroke-width": 1.5 }, vtg);
      el("circle", { cx: vt0.x, cy: vt0.y, r: 2.4, stroke: "none", class: "dotfill" }, vtg);
      el("circle", { cx: va.x, cy: va.y, r: 6.3, fill: "#fff", "stroke-width": 1.5 }, vtg);
      el("circle", { cx: vb.x, cy: vb.y, r: 6.3, fill: "none", "stroke-width": 1.5 }, vtg);
      el("rect", { x: Math.min(vt0.x, vb.x) - 8, y: Math.min(vt0.y, vb.y) - 8, width: Math.abs(vb.x - vt0.x) + 16, height: Math.abs(vb.y - vt0.y) + 16, fill: "transparent", stroke: "none" }, vtg);
      vtg.addEventListener("click", ev => this.app.inspect("vt", m.id, ev));
      // bus side of the breaker stays live with the bus even when the protected line is dead
      const cbp = P(sCB, 0);
      const stub = el("path", { d: `M${G.a.x},${G.a.y} L${cbp.x},${cbp.y}`, class: "sld-line", "stroke-width": G.br.phases.length === 3 ? 3 : 1.9 }, this.G.net);
      // breaker (SCADA square)
      const cb = el("rect", { x: cbp.x - 8, y: cbp.y - 8, width: 16, height: 16, "stroke-width": 2.2, class: "clickable" }, this.G.top);
      cb.addEventListener("click", ev => this.app.inspect("cb", m.id, ev));
      // labels
      const short = m.name.split(" (")[0];
      const cbl = P(sCB, -17);
      this._block("net", vert ? cbl.x + 2 : cbl.x, vert ? cbl.y : cbl.y + 20, vert ? "start" : "middle", vert ? "mid" : "down", [
        { key: "cb:" + m.id, q: "id", cat: "id", cls: "id2", fn: () => short },
        { key: "cb:" + m.id, q: "st", cat: "out", fn: () => R() ? (R().cb[this.S.k] ? "Closed" : { t: "Open", c: C.warn }) : null },
      ]);
      const lp = P(RS, RN + hn + 8);
      const st = () => this.S ? (this.S.iedState[m.id] || {}) : null;
      this._block("prot", lp.x, lp.y, vert ? "end" : "middle", vert ? "mid" : "up", [
        { key: "relay:" + m.id, q: "id", cat: "id", cls: "id", fn: () => `${m.id} (${fn[1]})` },
        { key: "relay:" + m.id, q: "st", cat: "out", fn: () => { const s = st(); if (!s) return null; return s.trip ? { t: "Trip", c: C.crit } : s.pick ? { t: "Pickup " + compactPicks(s.picks), c: C.pick } : { t: "Normal", c: C.ink2 }; } },
        { key: "relay:" + m.id, q: "prog", cat: "out", fn: () => R() ? `51P ${fmt(R().prog[this.S.k][0] * 100, 0)}%, 51N ${fmt(R().prog[this.S.k][1] * 100, 0)}%` : null },
        { key: "ct:" + m.id, q: "id", cat: "id", layer: "inst", cls: "v", fn: () => `CT-${m.id}` },
        { key: "ct:" + m.id, q: "iabc", cat: "in", layer: "inst", fn: () => R() ? `I ${tri(R().I[this.S.k], 0)} A` : null },
        { key: "ct:" + m.id, q: "i0", cat: "in", layer: "inst", fn: () => R() ? `3I0 ${fmt(R().I0x3[this.S.k], 0)} A` : null },
        { key: "vt:" + m.id, q: "id", cat: "id", layer: "inst", cls: "v", fn: () => `VT-${m.id}` },
        { key: "vt:" + m.id, q: "vabc", cat: "in", layer: "inst", fn: () => R() ? `V ${tri(R().Vpu[this.S.k], 3)} pu` : null },
      ]);
      this.iedEls[m.id] = { box, ft, ctW, vtW, tripW, arrow, cb, ctc, vtg, rg, cls, stub };
    }
    // Line differential (87L): pilot channel between partner relays
    for (const m of this.topo.ieds) {
      const a = this.iedEls[m.id], pm = m.partner && this.iedEls[m.partner];
      if (!pm || a.cls !== "DIFF" || pm.cls !== "DIFF") continue;
      const p = this.iedGeo[m.id].P(RS + RH, RN), q = this.iedGeo[m.partner].P(RS - RH, RN);
      const pl = el("path", { d: `M${p.x},${p.y} L${q.x},${q.y}`, class: "pilot" });
      this.G.prot.insertBefore(pl, this.G.prot.firstChild);
      this._block("prot", (p.x + q.x) / 2, p.y - 5, "middle", "up", [{ cat: "id", cls: "v", fn: () => "87L communication channel" }]);
    }
  }

  // Ground truth (not visible to a real operator): fault position, fault current and status.
  _god(run) {
    this.godEls = [];
    if (!run) return;
    for (const f of run.faults || []) {
      const b = this.bus[f.node];
      if (!b) continue;
      const g = el("g", { transform: `translate(${b.x},${b.y})`, opacity: 0, "pointer-events": "none" }, this.G.god);
      el("circle", { r: 12, fill: "none", stroke: C.crit, "stroke-width": 2, class: "fault-ring" }, g);
      // IEC 60617 fault symbol: lightning arrow
      el("path", { d: "M3,-24 L-5,-8 L1,-8 L-3,-2 L-6,-2 L0,4 L3,-3 L0,-3 L6,-14 L0,-14 L6,-24 Z", fill: C.crit, stroke: "#fff", "stroke-width": 1, transform: "scale(1.15)" }, g);
      const tail = el("line", { stroke: "#f1a3a3", "stroke-width": 1 }, this.G.god);
      const ty = f.type === "3PH" ? "3PH" : `${f.type}-${(f.phases || "").toUpperCase()}`;
      const ge = { g, f, tail, on: false, past: false };
      const key = "fault:" + f.id;
      const blk = this._block("god", b.x + 14, b.y - 30, "start", "down", [
        { key, q: "id", cat: "id", cls: "fid", fn: () => `${f.id} ${ty}, Rf ${f.rf} Ω` },
        { key, q: "if", cat: "in", fn: () => ge.on ? `If ${tri(f.I[this.S.kGod] || [], 0)} A` : null },
        { key, q: "st", cat: "out", fn: () => ge.on ? { t: "Fault active", c: C.crit } : ge.past ? { t: "Cleared or isolated", c: C.ink2 } : null },
      ]);
      ge.blk = blk;
      blk.base = { x: b.x, y: b.y };
      blk.cands = [[16, -34, "start", "down"], [-16, -34, "end", "down"], [16, 30, "start", "down"], [-16, 30, "end", "down"], [26, -62, "start", "down"], [-26, -62, "end", "down"],
        [26, 54, "start", "down"], [-26, 54, "end", "down"], [44, -8, "start", "down"], [-44, -8, "end", "down"], [60, -90, "start", "down"], [-60, -90, "end", "down"], [60, 80, "start", "down"], [-60, 80, "end", "down"]];
      blk.pre = () => { blk._was = ge.on; ge.on = true; };
      blk.post = best => {
        ge.on = blk._was;
        const far = Math.hypot(best[0], best[1]) > 40;
        ge.tail.setAttribute("x1", b.x); ge.tail.setAttribute("y1", b.y);
        ge.tail.setAttribute("x2", b.x + best[0] * 0.92); ge.tail.setAttribute("y2", b.y + best[1] + (best[1] < 0 ? 8 : -10));
        ge.tail.style.display = far ? "" : "none";
      };
      this.godEls.push(ge);
    }
  }

  // Movable labels (DER and fault): try each candidate position and keep the one that covers
  // the least of the other labels and symbols.
  _placeMovable() {
    for (const b of this.blocks.filter(x => x.cands)) {
      const obs = [...this.root.querySelectorAll("text, .sym, rect, circle")]
        .filter(e => e !== b.t && !(b.owner && b.owner.contains(e)) && !e.closest("[data-layer=god]"))
        .map(e => e.getBoundingClientRect()).filter(r => r.width > 0 && r.width < 400);
      if (b.pre) b.pre();
      let best = null;
      for (const cd of b.cands) {
        const [dx, dy, anc, grow] = cd;
        b.x = b.base.x + dx; b.y = b.base.y + dy; b.anchor = anc; b.grow = grow;
        b.t.setAttribute("text-anchor", anc); b.sig = null;
        this._renderBlock(b);
        const c = b.t.getBoundingClientRect();
        let cost = Math.hypot(dx, dy) * 0.3;
        const bb = b.t.getBBox();          // keep the label inside the diagram extent
        if (bb.x < VB.x + 2 || bb.y < VB.y + 2 || bb.x + bb.width > this.vbW - 2 || bb.y + bb.height > VB.y + VB.h - 2) cost += 150;
        for (const o of obs) {
          const ix = Math.min(c.right, o.right) - Math.max(c.left, o.left), iy = Math.min(c.bottom, o.bottom) - Math.max(c.top, o.top);
          if (ix > 0 && iy > 0) cost += ix * iy * 4;
        }
        if (!best || cost < best.cost - 1e-6) best = { cost, cd };
      }
      const [dx, dy, anc, grow] = best.cd;
      b.x = b.base.x + dx; b.y = b.base.y + dy; b.anchor = anc; b.grow = grow;
      b.t.setAttribute("text-anchor", anc); b.sig = null;
      if (b.post) b.post(best.cd);
    }
  }

  // update
  // Ground truth: branches that carry fault current. A branch qualifies only while a fault is active,
  // when it lies on the path from a connected source (grid through a closed CB-GI, or a DER in
  // service) to the fault through closed breakers, and when it actually carries current. A heavy load
  // never qualifies, because it is not on a source-to-fault path.
  _faultPath(r, kg, imax, IMIN) {
    const out = new Set();
    const faults = (r.faults || []).filter(f => r.t[kg] >= f.t_on && (f.I[kg] || []).some(x => x > 0.5));
    if (!faults.length) return out;
    const bri = this.app.brIdx;
    const blocked = new Set();
    for (const [id, g] of Object.entries(this.iedGeo)) { const d = r.ied[this.app.iedIdx[id]]; if (d && !d.cb[kg]) blocked.add(g.br.id); }
    const adj = {};
    for (const br of this.topo.branches) {
      if (blocked.has(br.id)) continue;
      (adj[br.from] = adj[br.from] || []).push([br.to, br.id]);
      (adj[br.to] = adj[br.to] || []).push([br.from, br.id]);
    }
    const sources = [];
    if (r.sub[kg]) sources.push("800");
    for (const d of r.der) if (d.on[kg]) sources.push(d.bus);
    for (const f of faults) {
      const prev = { [f.node]: null }, q = [f.node];
      while (q.length) { const v = q.shift(); for (const [w, b] of adj[v] || []) if (!(w in prev)) { prev[w] = [v, b]; q.push(w); } }
      for (const src of sources) {
        if (!(src in prev)) continue;
        for (let v = src; prev[v]; v = prev[v][0]) { const b = prev[v][1]; if (bri[b] !== undefined && imax(kg, bri[b]) > IMIN) out.add(b); }
      }
    }
    return out;
  }

  update(S) {
    const r = S.run; if (!r) return;
    this.S = S;
    const k = S.k;
    const bi = this.app.busIdx, bri = this.app.brIdx;
    // A conductor is live when it has voltage or carries current: a bolted fault can pull the
    // voltage close to zero while current still flows towards it.
    const IMIN = 1.0;
    const imax = (kk, i) => Math.max(0, ...((r.Ibr[kk][i] || []).filter(x => x !== null)));
    const carry = new Set();
    for (const br of this.topo.branches) { const i = bri[br.id]; if (i !== undefined && imax(k, i) > IMIN) { carry.add(br.from); carry.add(br.to); } }
    const en = id => r.energized[k][bi[id]] || carry.has(id);
    const fpath = this.layers.god ? this._faultPath(r, S.kGod, imax, IMIN) : new Set();
    for (const [id, e] of Object.entries(this.busEls)) {
      const i = bi[id]; if (i === undefined) continue;
      const v = r.Vpu[k][i].filter(x => x !== null);
      const vmin = v.length ? Math.min(...v) : null;
      const vmax = v.length ? Math.max(...v) : null;
      e.vmin = vmin;
      const noV = vmax !== null && vmax < 0.05;
      e.st = noV && !carry.has(id) ? "dead" : noV ? "crit" : vStatus(Math.max(vmin, 0.051));
      e.c.setAttribute("fill", VCOL[e.st]);
      if (this.barEls[id]) this.barEls[id].setAttribute("stroke", VCOL[e.st]);
    }
    for (const [id, e] of Object.entries(this.lineEls)) {
      const i = bri[id];
      const br = e.br;
      const fe = (r.energized[k][bi[br.from]] && r.energized[k][bi[br.to]]) || imax(k, i) > IMIN;
      const over = fe && fpath.has(id);
      const col = !fe ? C.dead : over ? C.crit : C.ink;
      e.p.setAttribute("stroke", col);
      e.p.setAttribute("stroke-width", over ? e.w + 1.2 : e.w);
      e.p.setAttribute("stroke-dasharray", fe ? "" : "6 5");
      for (const s of e.syms) { s.setAttribute("stroke", fe ? C.ink : C.dead); if (s.tagName === "path" && s.getAttribute("d").endsWith("Z")) s.setAttribute("fill", fe ? C.ink : C.dead); }
      const P = r.Pbr[k][i][0];
      if (this.layers.flow && fe && Math.abs(P) > 3) {
        const lvl = Math.abs(P) > 800 ? 2 : Math.abs(P) > 150 ? 1 : 0;
        this._setFlow(e, `${P < 0 ? "r" : "f"}:${lvl}`);
      } else this._setFlow(e, "");
    }
    for (const [id, e] of Object.entries(this.iedEls)) {
      const d = r.ied[this.app.iedIdx[id]];
      const closed = d.cb[k];
      e.cb.setAttribute("fill", closed ? "var(--cb-closed)" : "#fff");
      e.cb.setAttribute("stroke", closed ? "#991b1b" : "var(--cb-open)");
      const st = S.iedState[id] || {};
      const col = st.trip ? C.crit : st.pick ? C.pick : C.ink;
      e.box.setAttribute("stroke", col);
      e.box.setAttribute("fill", st.trip ? C.critBg : st.pick ? C.pickBg : "#fff");
      e.box.classList.toggle("blink", !!(st.trip && closed));
      e.ft.setAttribute("fill", col);
      e.tripW.classList.toggle("on", !!st.trip);
      e.arrow.classList.toggle("on", !!st.trip);
      const g = this.iedGeo[id];
      const live = en(g.m.from);
      const le = this.lineEls[g.br.id];
      const lineLive = le && le.p.getAttribute("stroke-dasharray") === "";
      e.stub.style.display = live && !lineLive ? "" : "none";
      e.stub.setAttribute("stroke", C.ink);
      e.ctc.setAttribute("stroke", live ? C.ink : C.dead);
      e.vtg.setAttribute("stroke", live ? C.ink : C.dead);
      e.vtg.querySelector(".dotfill").setAttribute("fill", live ? C.ink : C.dead);
    }
    const subOn = r.sub[k];
    this.subCB.setAttribute("fill", subOn ? "var(--cb-closed)" : "#fff");
    this.subCB.setAttribute("stroke", subOn ? "#991b1b" : "var(--cb-open)");
    for (const [id, e] of Object.entries(this.derEls)) {
      const d = r.der[this.app.derIdx[id]];
      const on = d.on[k];
      for (const p of e.parts) {
        if (p.tagName === "text") p.setAttribute("fill", on ? C.ink : C.dead);
        else p.setAttribute("stroke", on ? C.ink : C.dead);
      }
      e.parts[0].setAttribute("stroke-dasharray", on ? "" : "5 4");
    }
    for (const [bid, e] of Object.entries(this.loadEls)) {
      const live = en(bid);
      for (const p of e.parts) p.setAttribute("stroke", live ? C.ink : C.dead);
      e.parts[1].setAttribute("fill", live ? C.ink : C.dead);
    }
    for (const e of Object.values(this.capEls)) {
      const live = e.c.on && en(e.c.bus);
      for (const p of e.parts) p.setAttribute("stroke", live ? C.ink : C.dead);
    }
    // ground truth (instantaneous, not delayed by the RTU scan)
    for (const ge of this.godEls) {
      const f = ge.f, kg = S.kGod, t = r.t[kg];
      ge.on = t >= f.t_on && (f.I[kg] || []).some(x => x > 0.5);
      ge.past = t >= f.t_on && !ge.on;
      const op = ge.on ? 1 : ge.past ? 0.4 : 0;
      ge.g.setAttribute("opacity", op);
      ge.blk.t.setAttribute("opacity", op);
      ge.tail.setAttribute("opacity", op);
    }
    for (const b of this.blocks) this._renderBlock(b);
    if (this._needPlace) {
      this._needPlace = false; this._placeMovable(); for (const b of this.blocks) this._renderBlock(b);
      // the full view always contains everything that is drawn
      const was = this.vb.x === this.full.x && this.vb.y === this.full.y && this.vb.w === this.full.w && this.vb.h === this.full.h;
      const bb = this.root.getBBox();
      const x0 = Math.min(VB.x, bb.x - 8), y0 = Math.min(VB.y, bb.y - 8);
      this.full = { x: x0, y: y0, w: Math.max(this.vbW, bb.x + bb.width + 8) - x0, h: Math.max(VB.y + VB.h, bb.y + bb.height + 8) - y0 };
      if (was) { this.vb = { ...this.full }; this.applyVB(); }
    }
  }

  // pan and zoom
  applyVB() {
    const v = this.vb;
    this.svg.setAttribute("viewBox", `${v.x} ${v.y} ${v.w} ${v.h}`);
  }
  fit() {
    if (this.full) { this.vb = { ...this.full }; this.applyVB(); return; }
    let bb = null;
    try { bb = this.root.getBBox(); } catch (e) { /* not rendered yet */ }
    this.vb = bb && bb.width > 0 ? { x: bb.x - 16, y: bb.y - 16, w: bb.width + 32, h: bb.height + 32 } : { ...VB };
    this.applyVB();
  }
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
