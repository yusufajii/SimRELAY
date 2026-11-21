// Output phasor: polar diagram and table for the channels shown in the output waveform.
// Phasors are RMS fundamentals from the simulator; angles are referred to phase A of the first
// channel that carries a signal, like a disturbance-record viewer.
import { bisect } from "./scope.js";

const PH = ["#e8590c", "#2f9e44", "#1c7ed6", "#475569"];
const PL = ["A", "B", "C", "N"];
const DASH = ["", "6 4", "2 3", "8 3 2 3"];
const NS = "http://www.w3.org/2000/svg";
const fmt = (v, d = 1) => (v === null || v === undefined || Number.isNaN(v)) ? "N/A" : Number(v).toFixed(d);

export class PhasorView {
  constructor(app) { this.app = app; this.cache = {}; this.chans = []; this.sig = ""; }

  host(id) { return this.app.q(id); }

  // Called when the waveform channels change or a new run is loaded.
  async refresh() {
    const run = this.app.run, sc = this.app.scope;
    if (!run) return;
    this.cache[run.id] = this.cache[run.id] || {};
    const C = this.cache[run.id];
    const want = sc.rows.map((r, i) => ({ no: i + 1, sig: r.sig, name: sc.label(r.sig).split(":")[0] })).filter(c => !c.sig.startsWith("tl:"));
    this.chans = want;
    await Promise.all(want.map(async c => {
      if (C[c.sig]) return;
      try {
        const j = await (await fetch(`/api/wave?id=${encodeURIComponent(run.id)}&sig=${encodeURIComponent(c.sig)}&mode=phasor`)).json();
        if (!j.error) C[c.sig] = j;
      } catch (e) { /* drawn as unavailable */ }
    }));
    this._k = null;
    this.draw();
  }

  draw() {
    const run = this.app.run;
    const svg = this.host("#ph-polar"), tb = this.host("#ph-table tbody");
    if (!run || !svg || !tb) return;
    const C = this.cache[run.id] || {};
    const t = this.app.t;
    const first = this.chans.map(c => C[c.sig]).find(Boolean);
    const k = first ? bisect(first.t, t) : -1;
    const sig = `${run.id}|${k}|${this.chans.map(c => c.sig).join(",")}`;
    if (sig === this._k) return;
    this._k = sig;
    this.host("#ph-time").textContent = k >= 0 ? `t = ${first.t[k].toFixed(3)} s` : "";
    // phasors at the cursor; N is the sum of the three phases (3I0 or 3V0)
    const rows = [];
    for (const c of this.chans) {
      const d = C[c.sig];
      if (!d) continue;
      const kk = bisect(d.t, t), th = d.th[kk];
      const ph = [0, 1, 2].map(i => [d.re[i][kk], d.im[i][kk]]);
      ph.push([ph[0][0] + ph[1][0] + ph[2][0], ph[0][1] + ph[1][1] + ph[2][1]]);
      ph.forEach(([re, im], i) => rows.push({ c, i, re, im, th, unit: d.unit }));
    }
    const live = rows.find(r => r.i === 0 && Math.hypot(r.re, r.im) > 1e-6);
    const ref = live ? Math.atan2(live.im, live.re) : 0;
    this.refText = live ? `channel ${live.c.no} phase A (${live.c.name})` : "";
    // table
    tb.innerHTML = rows.map(r => {
      const mag = Math.hypot(r.re, r.im);
      const ang = mag > 1e-9 ? ((Math.atan2(r.im, r.re) - ref) * 180 / Math.PI % 360 + 360) % 360 : null;
      const inst = Math.SQRT2 * (r.re * Math.cos(r.th) - r.im * Math.sin(r.th));
      const d = r.unit === "kV" ? 3 : 1;
      return `<tr class="${r.i === 0 ? "first" : ""}"><td class="ch"><i style="background:${PH[r.i]}"></i>${r.c.no}${PL[r.i]}</td><td>${r.i === 0 ? `${r.c.name}` : ""}</td>` +
        `<td class="r">${fmt(mag, d)} ${r.unit}</td><td class="r">${fmt(mag * Math.SQRT2, d)}</td><td class="r">${ang === null ? "N/A" : fmt(ang, 1) + "°"}</td><td class="r">${fmt(inst, d)}</td></tr>`;
    }).join("");
    // polar diagram: each channel scaled to its own largest phasor
    svg.innerHTML = "";
    const el = (tag, a, p = svg) => { const e = svg.ownerDocument.createElementNS(NS, tag); for (const [x, y] of Object.entries(a)) e.setAttribute(x, y); p.appendChild(e); return e; };
    const R = 100;
    for (const f of [0.25, 0.5, 0.75, 1]) el("circle", { r: R * f, fill: "none", stroke: f === 1 ? "#cbd5e1" : "#eef1f5" });
    for (let a = 0; a < 360; a += 30) {
      const x = Math.cos(a * Math.PI / 180), y = -Math.sin(a * Math.PI / 180);
      el("line", { x1: 0, y1: 0, x2: R * x, y2: R * y, stroke: a % 90 ? "#eef1f5" : "#dbe1e8" });
      const tx = el("text", { x: (R + 13) * x, y: (R + 13) * y + 3.5, "text-anchor": "middle", class: "pdeg" }); tx.textContent = a;
    }
    const byCh = {};
    for (const r of rows) (byCh[r.c.no] = byCh[r.c.no] || []).push(r);
    Object.values(byCh).forEach((list, ci) => {
      const max = Math.max(...list.filter(r => r.i < 3).map(r => Math.hypot(r.re, r.im)), 1e-9);
      for (const r of list) {
        const mag = Math.hypot(r.re, r.im);
        if (mag < max * 0.02) continue;
        const a = Math.atan2(r.im, r.re) - ref, len = Math.min(mag / max, 1.15) * R * 0.92;
        const x = len * Math.cos(a), y = -len * Math.sin(a);
        el("line", { x1: 0, y1: 0, x2: x, y2: y, stroke: PH[r.i], "stroke-width": 1.8, "stroke-dasharray": DASH[ci % DASH.length] });
        const u = 7 / Math.max(len, 1), bx = x - x * u, by = y - y * u, nx = -y * u * 0.45, ny = x * u * 0.45;
        el("path", { d: `M${x},${y} L${bx + nx},${by + ny} L${bx - nx},${by - ny} Z`, fill: PH[r.i] });
        const lt = el("text", { x: x * 1.08 + (x >= 0 ? 3 : -3), y: y * 1.08 + 3, "text-anchor": x >= 0 ? "start" : "end", class: "plab", fill: PH[r.i] });
        lt.textContent = `${r.c.no}${PL[r.i]}`;
      }
    });
  }
}
