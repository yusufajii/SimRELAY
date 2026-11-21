// SCADA alarm annunciator (tile grid) and relay characteristic plots (TCC, R-X, 87L).
import { bisect } from "./scope.js";

const NS = "http://www.w3.org/2000/svg";
const fmt = (v, d = 0) => (v === null || v === undefined || Number.isNaN(v) || !Number.isFinite(v)) ? "N/A" : Number(v).toFixed(d);
const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const FN = { OCR: "50/51", DOCR: "67", DIST: "21", DIFF: "87L" };
const CURVES = { IEC_SI: [0.14, 0.02, 0], IEC_VI: [13.5, 1, 0], IEC_EI: [80, 2, 0], IEEE_MI: [0.0515, 0.02, 0.114], IEEE_VI: [19.61, 2, 0.491], IEEE_EI: [28.2, 2, 0.1217] };
export function tOp(curve, tms, M) {
  const [k, a, c] = CURVES[curve] || CURVES.IEC_SI;
  if (M <= 1) return Infinity;
  return curve.startsWith("IEC") ? tms * k / (M ** a - 1) : tms * (k / (M ** a - 1) + c);
}

// ------------------------------------------------------------------ annunciator
// State per tile: "" normal, "warn" (blinks), "alarm", "off" (no voltage or out of service).
// Annunciator states. Blinking states are still developing (a warning, or a trip signal waiting
// for the breaker); steady states are established.
export const ANN_KEY = [
  ["pick", "PU", "Relay pickup: a protection element has started timing", true],
  ["trip", "TRIP", "Trip signal sent, breaker still closed", true],
  ["tripped", "OPEN", "Tripped by the relay, breaker open", false],
  ["open", "OPEN", "Breaker open without a trip", false],
  ["isl", "ISL", "Substation breaker open, network islanded", false],
  ["uvc", "UV", "Undervoltage, below 0.90 pu", false],
  ["uvm", "UV", "Low voltage, 0.90 to 0.95 pu", true],
  ["ovc", "OV", "Overvoltage, above 1.10 pu", false],
  ["ovm", "OV", "High voltage, 1.05 to 1.10 pu", true],
  ["lov", "LOV", "Loss of voltage", false],
  ["off", "OFF", "DER disconnected", false],
];
const ALARM = new Set(["trip", "tripped", "uvc", "ovc", "lov"]), WARN = new Set(["pick", "uvm", "ovm"]);

export class AlarmTiles {
  constructor(app) {
    this.app = app; this.sig = null; this.txt = []; this.fkey = null;
    this.BLINK_MS = 500;      // one full cycle: 250 ms fading down, 250 ms fading up
    this.HOLD_MS = 500;       // shortest time a tile shows one state during playback
  }
  build(run) {
    const T = run.topology;
    const busA = T.buses.filter(b => !b.virtual && b.feeder === "A").map(b => b.id);
    const busB = T.buses.filter(b => !b.virtual && b.feeder === "B").map(b => b.id);
    this.groups = [
      ["Protection", [["CB-GI", "sub", "SUB"], ...T.ieds.map(m => [m.id, "ied", m.id])]],
      ...(run.der.length ? [["DER", run.der.map(d => [d.id, "der", d.id])]] : []),
      ["Feeder A buses", ["800", ...busA].map(b => [b, "bus", b])],
      ["Feeder B buses", busB.map(b => [b, "bus", b])],
    ];
    const host = this.app.q("#ann");
    host.innerHTML = this.groups.map(([g, tiles]) => `<div class="ann-g"><div class="ann-gt">${g}</div><div class="ann-tiles">${tiles.map(([lab, kind, id]) => `<button class="tile" data-kind="${kind}" data-id="${id}"><b>${esc(lab)}</b><span></span><i class="veil"></i></button>`).join("")}</div></div>`).join("");
    host.querySelectorAll(".tile").forEach((b, i) => {
      b.onclick = () => { const k = b.dataset.kind; this.app.inspect(k === "sub" ? "cb" : k === "ied" ? "ied" : k, b.dataset.id, null); };
      b.onmouseenter = () => { b.title = `${b.querySelector("b").textContent}: ${this.txt[i] || ""}`; };
    });
    this.sig = null; this.shown = null; this.sumHTML = null;
  }
  state(kind, id, run, k, iedState) {
    if (kind === "bus") {
      const i = this.app.busIdx[id]; if (i === undefined) return ["", "", ""];
      const v = (run.Vpu[k][i] || []).filter(x => x !== null);
      const vmin = v.length ? Math.min(...v) : 0, vmax = v.length ? Math.max(...v) : 0;
      if (vmax < 0.05) return ["lov", "LOV", "Loss of voltage"];
      if (vmin < 0.9) return ["uvc", "UV", `Undervoltage ${fmt(vmin, 3)} pu`];
      if (vmax > 1.1) return ["ovc", "OV", `Overvoltage ${fmt(vmax, 3)} pu`];
      if (vmin < 0.95) return ["uvm", "UV", `Low voltage ${fmt(vmin, 3)} pu`];
      if (vmax > 1.05) return ["ovm", "OV", `High voltage ${fmt(vmax, 3)} pu`];
      return ["", "", `Normal ${fmt(vmin, 3)} pu`];
    }
    if (kind === "ied") {
      const d = run.ied[this.app.iedIdx[id]], st = iedState[id] || {};
      if (st.trip) return d.cb[k] ? ["trip", "TRIP", "Trip signal sent, breaker still closed"] : ["tripped", "OPEN", "Tripped, breaker open"];
      if (!d.cb[k]) return ["open", "OPEN", "Breaker open"];
      if (st.pick) return ["pick", "PU", "Pickup " + st.picks.join(", ")];
      return ["", "", "Normal, breaker closed"];
    }
    if (kind === "der") {
      const d = run.der[this.app.derIdx[id]];
      return d.on[k] ? ["", "", `In service, ${fmt(d.P[k], 0)} kW`] : ["off", "OFF", "Disconnected"];
    }
    return run.sub[k] ? ["", "", "Breaker CB-GI closed"] : ["isl", "ISL", "Breaker CB-GI open, network islanded"];
  }
  // Opacity animations run on the compositor, so the rhythm stays exact while playback is busy.
  // startTime 0 ties every tile to the same document clock, so they all blink in phase.
  blink(b, on) {
    if (on && !b._anim) {
      try {
        // balanced, sine-like fade: half a cycle dimming, half a cycle brightening
        b._anim = b.querySelector(".veil").animate([{ opacity: 0 }, { opacity: 0.7 }],
          { duration: this.BLINK_MS / 2, iterations: Infinity, direction: "alternate", easing: "cubic-bezier(0.37, 0, 0.63, 1)" });
        b._anim.startTime = 0;
      } catch (e) { b._anim = null; }
    } else if (!on && b._anim) { b._anim.cancel(); b._anim = null; }
  }
  // During playback each tile keeps the state it shows for at least one blink cycle, like an HMI
  // refresh, so a burst of changes at fault inception does not look like fast blinking. When the
  // playback is paused, stepped or sought (hold = false) the true state is shown at once.
  update(run, k, iedState, hold = false) {
    const host = this.app.q("#ann"); if (!host || !this.groups) return;
    const fkey = `${run.id}|${k}|${JSON.stringify(iedState)}|${hold}`;
    if (fkey === this.fkey && !this.pending) return;
    this.fkey = fkey;
    const out = [];
    for (const [, tiles] of this.groups) for (const [, kind, id] of tiles) out.push(this.state(kind, id, run, k, iedState));
    this.txt = out.map(s => s[2]);
    const now = performance.now(), tiles = [...host.querySelectorAll(".tile")];
    if (!this.shown || this.shown.length !== tiles.length || this.shownRun !== run.id) { this.shown = tiles.map(() => ({ s: null, at: 0 })); this.shownRun = run.id; }
    let wait = Infinity;
    tiles.forEach((b, i) => {
      const [c, code] = out[i], cur = this.shown[i], key = c + "|" + code;
      if (key === cur.s) return;
      const left = this.HOLD_MS - (now - cur.at);
      if (hold && cur.s !== null && left > 0) { wait = Math.min(wait, left); return; }
      const blink = ANN_KEY.some(x => x[0] === c && x[3]);
      b.className = "tile" + (c ? " " + c : "") + (blink ? " flash" : "");   // not "blink": that class name has its own fast animation (SLD)
      this.blink(b, blink);
      b.querySelector("span").textContent = code;
      cur.s = key; cur.at = now;
    });
    // a held change is shown as soon as its hold time is over, even if the frame does not change
    clearTimeout(this.timer);
    this.pending = wait < Infinity;
    if (this.pending) this.timer = setTimeout(() => this.update(this.app.run, this.app.kOp, this.app.iedStateAt(this.app.run.t[this.app.kOp]), true), wait + 5);
    let nA = 0, nW = 0;
    for (const x of this.shown) { const c = (x.s || "").split("|")[0]; if (ALARM.has(c)) nA++; else if (WARN.has(c)) nW++; }
    const sum = (nA ? `<span class="st bad">${nA} alarm${nA > 1 ? "s" : ""}</span>` : "") + (nW ? `<span class="st warn">${nW} warning${nW > 1 ? "s" : ""}</span>` : "") + (!nA && !nW ? `<span class="st ok">No active alarm</span>` : "");
    if (sum !== this.sumHTML) { this.sumHTML = sum; this.app.q("#al-sum").innerHTML = sum; }
  }
}

// ------------------------------------------------------------------ relay characteristic
export class RelayChart {
  constructor(app) { this.app = app; this.cache = {}; this.sel = null; this.sig = null; }

  setRun(run) {
    const s = this.app.q("#rc-sel");
    const ids = run.ied.map(d => d.id);
    // each run opens on the relay that should clear its fault
    const hf = run.hunter.faults[0];
    this.sel = hf && hf.primary && ids.includes(hf.primary) ? hf.primary : ids[0];
    s.innerHTML = run.ied.map(d => `<option value="${d.id}">${d.id}, ${d.cls} ${FN[d.cls] || ""}</option>`).join("");
    s.value = this.sel;
    s.onchange = () => { this.sel = s.value; this.sig = null; this.load(); };
    this.sig = null;
    this.load();
  }
  async phasors(sig) {
    const run = this.app.run;
    const C = this.cache[run.id] = this.cache[run.id] || {};
    if (!C[sig]) {
      try { const j = await (await fetch(`/api/wave?id=${encodeURIComponent(run.id)}&sig=${encodeURIComponent(sig)}&mode=phasor`)).json(); if (!j.error) C[sig] = j; } catch (e) { /* plotted without operating point */ }
    }
    return C[sig];
  }
  async load() {
    const run = this.app.run, id = this.sel; if (!run) return;
    const d = run.ied[this.app.iedIdx[id]];
    if (d.cls === "DIST") await Promise.all([this.phasors(`ied:${id}:I`), this.phasors(`ied:${id}:V`)]);
    if (d.cls === "DIFF") { const m = run.topology.ieds.find(x => x.id === id); await Promise.all([this.phasors(`ied:${id}:I`), m.partner ? this.phasors(`ied:${m.partner}:I`) : null]); }
    this.sig = null;
    this.draw();
  }

  draw() {
    const run = this.app.run, svg = this.app.q("#rc-svg"); if (!run || !svg) return;
    const id = this.sel, k = this.app.kOp ?? 0;
    const cls0 = run.ied[this.app.iedIdx[id]].cls;
    const ssig = `${run.id}|${id}|${cls0}|${!!(this.cache[run.id] || {})[`ied:${id}:I`]}`;
    const sig = `${ssig}|${k}`;
    if (sig === this.sig) return;
    this.sig = sig;
    if (ssig !== this.ssig || !svg.querySelector("g.dyn")) {
      this.ssig = ssig;
      svg.innerHTML = "";
      this.gS = svg.ownerDocument.createElementNS(NS, "g"); this.gS.setAttribute("class", "sta"); svg.appendChild(this.gS);
      this.gD = svg.ownerDocument.createElementNS(NS, "g"); this.gD.setAttribute("class", "dyn"); svg.appendChild(this.gD);
      this.full = true;
    } else this.full = false;
    this.gD.innerHTML = "";
    const d = run.ied[this.app.iedIdx[id]], s = this.app.init.settings[id], m = run.topology.ieds.find(x => x.id === id);
    const cls = d.cls;
    const info = this.app.q("#rc-info");
    const curveName = (this.app.init.curves || {})[s.curve] || s.curve;
    // settings as a table, same style as the phasor table
    const tab = (head, rows) => `<table class="pht2 rc-tab"><thead><tr>${head.map((h, j) => `<th${j ? ' class="r"' : ""}>${h}</th>`).join("")}</tr></thead><tbody>${rows.map(r => `<tr>${r.map((c, j) => `<td${j ? ' class="r"' : ' class="ch"'}>${c}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
    if (cls === "OCR" || cls === "DOCR") info.innerHTML = tab(["Element", "Pickup", "TMS", "Curve", ...(cls === "DOCR" ? ["Direction"] : [])], [
      ["51P", `${s["51P_pu"]} A`, s["51P_tms"], esc(curveName), ...(cls === "DOCR" ? ["Forward"] : [])],
      ...(s["51N_pu"] ? [["51N", `${s["51N_pu"]} A`, s["51N_tms"], esc(curveName), ...(cls === "DOCR" ? ["Forward"] : [])]] : []),
      ...(s["50P_pu"] ? [["50P", `${s["50P_pu"]} A`, "", "Instantaneous", ...(cls === "DOCR" ? ["Forward"] : [])]] : []),
      ...(s["50N_pu"] ? [["50N", `${s["50N_pu"]} A`, "", "Instantaneous", ...(cls === "DOCR" ? ["Forward"] : [])]] : []),
    ]);
    else if (cls === "DIST") info.innerHTML = tab(["Zone", "Reach", "Angle", "Time"], s.zreach.map((z, j) => [`Z${j + 1}`, `${fmt(z, 2)} Ω`, `${fmt(s.ang1 * 180 / Math.PI, 1)}°`, `${fmt(s.ztime[j], 1)} s`]));
    else info.innerHTML = s["87_pu"] ? tab(["Element", "Pickup", "Slope", "Partner"], [["87L", `${s["87_pu"]} A`, `${fmt(s["87_slope"] * 100, 0)}%`, m.partner || "None"]]) : tab(["Element", "Pickup", "Slope", "Partner"], [["87L", "Not set", "", "None"]]);
    if (cls === "DIST") this.rx(d, s, k);
    else if (cls === "DIFF") this.diff(d, s, m, k);
    else this.tcc(d, s, m, k, cls);
  }

  _el(g) { return (tag, a, txt) => { const e = g.ownerDocument.createElementNS(NS, tag); for (const [x, y] of Object.entries(a)) e.setAttribute(x, y); if (txt !== undefined) e.textContent = txt; g.appendChild(e); return e; }; }
  // static drawing goes to the static layer only when it is rebuilt
  _els() { const sta = this._el(this.gS), dyn = this._el(this.gD), full = this.full; return [full ? sta : () => null, dyn]; }

  // time-current characteristic, log-log, with the other relays of the feeder for coordination
  tcc(d, s, m, k, cls) {
    const [el, dl] = this._els(), W = 360, H = 250, L = 44, R = 10, T = 10, B = 30;
    const x0 = 1, x1 = 1e4, y0 = 0.01, y1 = 100;
    const X = i => L + (Math.log10(i) - Math.log10(x0)) / (Math.log10(x1) - Math.log10(x0)) * (W - L - R);
    const Y = t => T + (Math.log10(y1) - Math.log10(t)) / (Math.log10(y1) - Math.log10(y0)) * (H - T - B);
    for (let e = 0; e <= 4; e++) for (const f of [1, 2, 5]) { const i = f * 10 ** e; if (i > x1) continue; el("line", { x1: X(i), y1: T, x2: X(i), y2: H - B, class: f === 1 ? "g1" : "g2" }); if (f === 1) el("text", { x: X(i), y: H - B + 12, class: "ax", "text-anchor": "middle" }, i >= 1000 ? i / 1000 + "k" : i); }
    for (const t of [0.01, 0.1, 1, 10, 100]) { el("line", { x1: L, y1: Y(t), x2: W - R, y2: Y(t), class: "g1" }); el("text", { x: L - 4, y: Y(t) + 3, class: "ax", "text-anchor": "end" }, t); }
    el("text", { x: (L + W - R) / 2, y: H - 4, class: "axl", "text-anchor": "middle" }, "Current (A, primary)");
    el("text", { x: 10, y: (T + H - B) / 2, class: "axl", "text-anchor": "middle", transform: `rotate(-90 10 ${(T + H - B) / 2})` }, "Time (s)");
    const curve = (pu, tms, inst, cl) => {
      if (!pu) return;
      let p = "";
      for (let j = 0; j <= 80; j++) {
        const M = 1.03 * (40 / 1.03) ** (j / 80), i = M * pu; if (i > x1) break;
        let t = tOp(s.curve, tms, M); if (inst && i >= inst) t = Math.min(t, 0.02);
        if (t > y1 || t < y0) continue;
        p += (p ? "L" : "M") + X(i).toFixed(1) + "," + Y(t).toFixed(1);
      }
      el("path", { d: p, class: cl });
    };
    // other relays on the same feeder, faint
    for (const o of this.app.run.topology.ieds) {
      if (o.id === m.id || o.feeder !== m.feeder) continue;
      const so = this.app.init.settings[o.id];
      curve(so["51P_pu"], so["51P_tms"], so["50P_pu"], "c-other");
      const lab = so["51P_pu"] * 6; const to = tOp(so.curve, so["51P_tms"], 6);
      if (to > y0 && to < y1) el("text", { x: X(lab) + 3, y: Y(to) - 3, class: "c-otl" }, o.id);
    }
    curve(s["51N_pu"], s["51N_tms"], s["50N_pu"], "c-n");
    curve(s["51P_pu"], s["51P_tms"], s["50P_pu"], "c-p");
    // operating point at the RTU time: highest phase current and 3I0
    const st = (this.app.iedStateAt(this.app.run.t[k]) || {})[m.id] || {};
    const col = st.trip ? "#dc2626" : st.pick ? "#7c3aed" : "#475569";
    const Iph = Math.max(0, ...d.I[k].filter(x => x !== null)), I0 = d.I0x3[k] || 0;
    const mark = (i, pu, tms, lab, dash) => {
      if (!(i > x0)) return;
      dl("line", { x1: X(Math.min(i, x1)), y1: T, x2: X(Math.min(i, x1)), y2: H - B, stroke: col, "stroke-width": 1.2, "stroke-dasharray": dash });
      const t = pu ? tOp(s.curve, tms, i / pu) : Infinity;
      if (t > y0 && t < y1) dl("circle", { cx: X(i), cy: Y(t), r: 3.6, fill: col });
      dl("text", { x: X(Math.min(i, x1)) + 3, y: T + 10 + (dash ? 12 : 0), class: "opl", fill: col }, `${lab} ${fmt(i, 0)} A`);
    };
    mark(Iph, s["51P_pu"], s["51P_tms"], "I", "");
    if (s["51N_pu"]) mark(I0, s["51N_pu"], s["51N_tms"], "3I0", "4 3");
  }

  // impedance plane with mho zones and the measured loop impedances
  rx(d, s, k) {
    const [el, dl] = this._els(), W = 360, H = 250;
    const Z3 = s.zreach[2], ang = s.ang1;
    const span = Z3 * 1.25, cx = W / 2 - 40, cy = H / 2 + 25, sc = (H / 2 - 18) / span;
    const X = r => cx + r * sc, Y = x => cy - x * sc;
    const step = [0.5, 1, 2, 5, 10, 20, 50].find(v => span / v <= 6) || 50;
    for (let v = -Math.ceil(span / step) * step; v <= span * 1.6; v += step) {
      if (X(v) > 8 && X(v) < W - 8) { el("line", { x1: X(v), y1: 8, x2: X(v), y2: H - 18, class: v === 0 ? "g0" : "g1" }); if (v !== 0) el("text", { x: X(v), y: cy + 11, class: "ax", "text-anchor": "middle" }, v); }
      if (Y(v) > 8 && Y(v) < H - 18) { el("line", { x1: 8, y1: Y(v), x2: W - 8, y2: Y(v), class: v === 0 ? "g0" : "g1" }); if (v !== 0) el("text", { x: cx - 4, y: Y(v) + 3, class: "ax", "text-anchor": "end" }, v); }
    }
    el("text", { x: W - 10, y: cy - 4, class: "axl", "text-anchor": "end" }, "R (Ω)");
    el("text", { x: cx + 4, y: 16, class: "axl" }, "X (Ω)");
    s.zreach.forEach((zr, i) => {
      const c = { r: zr / 2 * Math.cos(ang), x: zr / 2 * Math.sin(ang) };
      el("circle", { cx: X(c.r), cy: Y(c.x), r: zr / 2 * sc, class: "zone z" + (i + 1) });
      el("text", { x: X(zr * Math.cos(ang)) + 4, y: Y(zr * Math.sin(ang)) - 2, class: "zl" }, "Z" + (i + 1));
    });
    el("line", { x1: X(0), y1: Y(0), x2: X(Z3 * 1.1 * Math.cos(ang)), y2: Y(Z3 * 1.1 * Math.sin(ang)), class: "lang" });
    // loop impedances from the CT and VT phasors (same loops as the relay)
    const C = this.cache[this.app.run.id] || {}, I = C[`ied:${d.id}:I`], V = C[`ied:${d.id}:V`];
    const t = this.app.run.t[k];
    if (!I || !V) return;
    const k0 = { re: s.k0[0], im: s.k0[1] };
    const loopsAt = kk => {
      const v = [0, 1, 2].map(i => ({ re: V.re[i][kk] * 1000, im: V.im[i][kk] * 1000 })), c = [0, 1, 2].map(i => ({ re: I.re[i][kk], im: I.im[i][kk] }));
      const i0 = { re: c[0].re + c[1].re + c[2].re, im: c[0].im + c[1].im + c[2].im };
      const div = (a, b) => { const q = b.re * b.re + b.im * b.im; return q < 1e-6 ? null : { re: (a.re * b.re + a.im * b.im) / q, im: (a.im * b.re - a.re * b.im) / q }; };
      const out = {};
      for (const p of s.ph_idx) out["ABC"[p] + "G"] = div(v[p], { re: c[p].re + k0.re * i0.re - k0.im * i0.im, im: c[p].im + k0.re * i0.im + k0.im * i0.re });
      for (const [p, q] of [[0, 1], [1, 2], [2, 0]]) if (s.ph_idx.includes(p) && s.ph_idx.includes(q)) out["ABC"[p] + "ABC"[q]] = div({ re: v[p].re - v[q].re, im: v[p].im - v[q].im }, { re: c[p].re - c[q].re, im: c[p].im - c[q].im });
      return out;
    };
    const kk = bisect(I.t, t), now = loopsAt(kk);
    const inside = z => z && X(z.re) > 8 && X(z.re) < W - 8 && Y(z.im) > 8 && Y(z.im) < H - 18;
    // trail of the last 150 ms for the loop closest to the zones
    let best = null;
    for (const [n, z] of Object.entries(now)) if (z && (!best || Math.hypot(z.re, z.im) < Math.hypot(best[1].re, best[1].im))) best = [n, z];
    if (best) {
      let p = "";
      for (let j = Math.max(0, kk - 30); j <= kk; j++) { const z = loopsAt(j)[best[0]]; if (inside(z)) p += (p ? "L" : "M") + X(z.re).toFixed(1) + "," + Y(z.im).toFixed(1); }
      if (p) dl("path", { d: p, class: "trail" });
    }
    for (const [n, z] of Object.entries(now)) {
      if (!inside(z)) continue;
      dl("circle", { cx: X(z.re), cy: Y(z.im), r: 3.2, class: n.length === 2 && n[1] === "G" ? "zpg" : "zpp" });
      dl("text", { x: X(z.re) + 5, y: Y(z.im) - 4, class: "opl" }, n);
    }
  }

  // percentage-restraint characteristic with the measured operating points
  diff(d, s, m, k) {
    const [el, dl] = this._els(), W = 360, H = 250, L = 44, R = 10, T = 10, B = 30;
    if (!s["87_pu"] || !m.partner) return;
    const C = this.cache[this.app.run.id] || {}, A = C[`ied:${d.id}:I`], P = C[`ied:${m.partner}:I`];
    const t = this.app.run.t[k];
    let pts = [];
    if (A && P) {
      const ka = bisect(A.t, t), kb = bisect(P.t, t);
      pts = [0, 1, 2].map(i => {
        const dr = A.re[i][ka] - P.re[i][kb], di = A.im[i][ka] - P.im[i][kb];
        return { ph: "ABC"[i], id: Math.hypot(dr, di), ir: (Math.hypot(A.re[i][ka], A.im[i][ka]) + Math.hypot(P.re[i][kb], P.im[i][kb])) / 2 };
      });
    }
    if (this.full || !this.dmax) {
      let mx = s["87_pu"] * 8;
      if (A && P) for (let i = 0; i < 3; i++) for (let j = 0; j < A.t.length; j++) { const jb = Math.min(j, P.t.length - 1); mx = Math.max(mx, Math.hypot(A.re[i][j], A.im[i][j]), Math.hypot(P.re[i][jb], P.im[i][jb])); }
      this.dmax = mx * 1.15;
    }
    const max = this.dmax;
    const X = v => L + v / max * (W - L - R), Y = v => H - B - v / max * (H - T - B);
    const step = [10, 20, 50, 100, 200, 500, 1000, 2000].find(v => max / v <= 6) || 5000;
    for (let v = 0; v <= max; v += step) { el("line", { x1: X(v), y1: T, x2: X(v), y2: H - B, class: "g1" }); el("text", { x: X(v), y: H - B + 12, class: "ax", "text-anchor": "middle" }, v); el("line", { x1: L, y1: Y(v), x2: W - R, y2: Y(v), class: "g1" }); el("text", { x: L - 4, y: Y(v) + 3, class: "ax", "text-anchor": "end" }, v); }
    el("text", { x: (L + W - R) / 2, y: H - 4, class: "axl", "text-anchor": "middle" }, "Restraint current Ir (A)");
    el("text", { x: 10, y: (T + H - B) / 2, class: "axl", "text-anchor": "middle", transform: `rotate(-90 10 ${(T + H - B) / 2})` }, "Differential current Id (A)");
    const knee = s["87_pu"] / s["87_slope"];
    el("path", { d: `M${X(0)},${Y(s["87_pu"])} L${X(knee)},${Y(s["87_pu"])} L${X(max)},${Y(s["87_slope"] * max)}`, class: "c-p" });
    el("text", { x: X(max) - 4, y: Y(s["87_slope"] * max) - 6, class: "zl", "text-anchor": "end" }, "Operate above");
    const col = ["#e8590c", "#2f9e44", "#1c7ed6"];
    pts.forEach((p, i) => { dl("circle", { cx: X(Math.min(p.ir, max)), cy: Y(Math.min(p.id, max)), r: 3.6, fill: col[i] }); dl("text", { x: X(Math.min(p.ir, max)) + 5, y: Y(Math.min(p.id, max)) - 4, class: "opl", fill: col[i] }, p.ph); });
  }

  legend(el, x, y, items, right) {
    items.forEach(([cls, t], i) => {
      const yy = y + i * 12;
      if (cls === "zpg" || cls === "zpp") el("circle", { cx: x - 4, cy: yy, r: 3, class: cls });
      else el("line", { x1: x - 14, y1: yy, x2: x, y2: yy, class: cls });
      el("text", { x: x - 18, y: yy + 3, class: "lg", "text-anchor": "end" }, t);
    });
  }
}
