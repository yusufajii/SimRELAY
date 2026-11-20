// Multi-channel oscilloscope (ground truth), canvas based
const PH = ["#e8590c", "#2f9e44", "#1c7ed6"];
const PHL = ["A", "B", "C"];
const fmt = (v, d = 1) => (v === null || v === undefined || Number.isNaN(v)) ? "N/A" : Number(v).toFixed(d);

export class Scope {
  constructor(host, app) {
    this.host = host; this.app = app; this.rows = []; this.cache = {}; this.byRun = {};
    this.win = 0.25;
  }

  catalog(run) {
    const g = [];
    const ieds = run.ied.map(d => d.id);
    g.push({ label: "Instrument transformers (relay inputs)", items: ieds.flatMap(i => [[`ied:${i}:I`, `CT-${i}: phase currents`], [`ied:${i}:V`, `VT-${i}: phase voltages`]]) });
    if (run.faults.length) g.push({ label: "Fault (ground truth only)", items: run.faults.map(f => [`fault:${f.id}:I`, `${f.id}: fault point current (${f.node})`]) });
    if (run.der.length) g.push({ label: "DER", items: run.der.flatMap(d => [[`der:${d.id}:I`, `${d.id}: output current`], [`tl:derpq:${d.id}`, `${d.id}: P and Q (kW, kvar)`]].concat(d.irr ? [[`tl:irr:${d.id}`, `${d.id}: irradiance (W/m²)`]] : [])) });
    g.push({ label: "System", items: [["tl:freq", "Frequency (Hz)"]].concat(ieds.map(i => [`tl:prog:${i}`, `${i}: 51P and 51N integrator progress`])) });
    g.push({ label: "Simulator probe: bus voltage", items: run.buses.filter(b => !b.startsWith("F")).map(b => [`bus:${b}:V`, `Bus ${b}`]) });
    g.push({ label: "Simulator probe: branch current", items: run.branches.map(b => [`br:${b}:I`, b]) });
    return g;
  }

  setRun(run, defaults) {
    this.run = run;
    this.byRun = this.byRun || {};                       // waveforms stay cached per run
    this.cache = this.byRun[run.id] = this.byRun[run.id] || {};
    this.cat = this.catalog(run);
    this.host.innerHTML = "";
    this.rows = [];
    this._ready = false;
    for (const d of defaults) this.addRow(d[0], d[1] || "inst");
    this._ready = true;
  }

  addRow(sig, mode = "inst") {
    if (!this.run) return;
    const row = { sig, mode, data: null };
    const div = document.createElement("div"); div.className = "srow";
    const h = document.createElement("div"); h.className = "srow-h";
    const sel = document.createElement("select");
    for (const grp of this.cat) {
      const og = document.createElement("optgroup"); og.label = grp.label;
      for (const [v, l] of grp.items) { const o = document.createElement("option"); o.value = v; o.textContent = l; og.appendChild(o); }
      sel.appendChild(og);
    }
    sel.value = sig;
    const ms = document.createElement("select");
    for (const [v, l] of [["inst", "Instantaneous"], ["rms", "RMS"], ["seq", "Sequence 1/2/0"]]) { const o = document.createElement("option"); o.value = v; o.textContent = l; ms.appendChild(o); }
    ms.value = mode;
    const rd = document.createElement("span"); rd.className = "rd";
    const rm = document.createElement("span"); rm.className = "rm"; rm.innerHTML = '<svg class="ic"><use href="#i-close"/></svg>'; rm.title = "Remove channel";
    h.append(sel, ms, rd, rm);
    const cv = document.createElement("canvas");
    const tip = document.createElement("div"); tip.className = "stip";
    div.append(h, cv, tip);
    this.host.appendChild(div);
    Object.assign(row, { div, sel, ms, rd, cv, tip });
    sel.onchange = () => { row.sig = sel.value; this.load(row); };
    ms.onchange = () => { row.mode = ms.value; this.load(row); };
    rm.onclick = () => { div.remove(); this.rows = this.rows.filter(r => r !== row); };
    cv.addEventListener("mousemove", ev => { row.hover = ev.offsetX; this.draw(row); });
    cv.addEventListener("mouseleave", () => { row.hover = null; tip.style.display = "none"; this.draw(row); });
    cv.addEventListener("click", ev => { const t = this.xToT(row, ev.offsetX); this.app.seek(t); });
    this.rows.push(row);
    this.load(row);
    if (this.run && this._ready) div.scrollIntoView({ block: "nearest", behavior: "smooth" });
    return row;
  }

  async load(row) {
    const tl = row.sig.startsWith("tl:");
    row.ms.disabled = tl;
    if (tl) { row.data = this.timeline(row.sig); this.draw(row); return; }
    const key = row.sig + "|" + row.mode;
    if (!this.cache[key]) {
      row.data = null; this.draw(row);
      const r = await fetch(`/api/wave?id=${encodeURIComponent(this.run.id)}&sig=${encodeURIComponent(row.sig)}&mode=${row.mode}`);
      const j = await r.json();
      if (j.error) { row.data = { err: j.error }; this.draw(row); return; }
      this.cache[key] = this.prep(j);
    }
    row.data = this.cache[key];
    this.draw(row);
  }

  prep(j) {
    let ymin = Infinity, ymax = -Infinity;
    for (const ch of j.ch) for (const v of ch) { if (v === null) continue; if (v < ymin) ymin = v; if (v > ymax) ymax = v; }
    if (j.mode === "inst") { const m = Math.max(Math.abs(ymin), Math.abs(ymax), 1e-6) * 1.08; ymin = -m; ymax = m; }
    else { ymin = Math.min(0, ymin); ymax = Math.max(ymax * 1.1, 1e-6); }
    return { ...j, ymin, ymax, labels: j.labels || PHL };
  }

  timeline(sig) {
    const r = this.run, p = sig.split(":");
    let ch, labels, unit;
    if (p[1] === "freq") { ch = [r.freq]; labels = ["f"]; unit = "Hz"; }
    else if (p[1] === "derpq") { const d = r.der.find(x => x.id === p[2]); ch = [d.P, d.Q]; labels = ["P", "Q"]; unit = "kW/kvar"; }
    else if (p[1] === "irr") { const d = r.der.find(x => x.id === p[2]); ch = [d.irr]; labels = ["G"]; unit = "W/m²"; }
    else if (p[1] === "prog") { const d = r.ied.find(x => x.id === p[2]); ch = [d.prog.map(x => x[0]), d.prog.map(x => x[1])]; labels = ["51P", "51N"]; unit = "1.0 = trip"; }
    let ymin = Infinity, ymax = -Infinity;
    for (const c of ch) for (const v of c) { if (v === null) continue; ymin = Math.min(ymin, v); ymax = Math.max(ymax, v); }
    if (p[1] === "freq") { const m = Math.max(Math.abs(ymax - 60), Math.abs(ymin - 60), 0.2) * 1.2; ymin = 60 - m; ymax = 60 + m; }
    else if (p[1] === "prog") { ymin = 0; ymax = 1.1; }
    else { const pad = (ymax - ymin) * 0.1 || 1; ymin = Math.min(ymin - pad, 0); ymax = ymax + pad; }
    return { mode: "series", t: r.t, ch, labels, unit, ymin, ymax, colors: p[1] === "derpq" || p[1] === "prog" ? ["#b45309", "#7c3aed"] : ["#b45309"] };
  }

  range() {
    const T = this.run ? this.run.T : 1;
    if (!this.win) return [0, T];
    const t = this.app.t;
    let t0 = t - this.win * 0.75, t1 = t + this.win * 0.25;
    if (t0 < 0) { t1 -= t0; t0 = 0; }
    if (t1 > T) { t0 -= (t1 - T); t1 = T; t0 = Math.max(t0, 0); }
    return [t0, t1];
  }
  xToT(row, x) { const [t0, t1] = this.range(); const W = row.cv.clientWidth - 70; return t0 + (x - 46) / W * (t1 - t0); }

  drawAll() { for (const r of this.rows) this.draw(r); }

  valueAt(d, t) {
    if (d.mode === "inst") { const i = Math.round(t * d.fs); return d.ch.map(c => c[Math.min(Math.max(i, 0), c.length - 1)]); }
    const i = bisect(d.t, t); return d.ch.map(c => c[i]);
  }

  draw(row) {
    const cv = row.cv, dpr = window.devicePixelRatio || 1;
    const W = cv.clientWidth, H = cv.clientHeight;
    if (cv.width !== W * dpr || cv.height !== H * dpr) { cv.width = W * dpr; cv.height = H * dpr; }
    const g = cv.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.fillStyle = "#ffffff"; g.fillRect(0, 0, W, H);
    const L = 46, R = 24, T = 8, B = 16;
    const pw = W - L - R, ph = H - T - B;
    const d = row.data;
    g.font = "10px JetBrains Mono, Consolas, monospace";
    if (!d) { g.fillStyle = "#94a3b8"; g.fillText("Loading waveform", L + 8, H / 2); return; }
    if (d.err) { g.fillStyle = "#b91c1c"; g.fillText(d.err, L + 8, H / 2); return; }
    const [t0, t1] = this.range();
    const X = t => L + (t - t0) / (t1 - t0) * pw;
    const Y = v => T + (d.ymax - v) / (d.ymax - d.ymin) * ph;
    // grid
    g.strokeStyle = "#eef1f5"; g.lineWidth = 1;
    for (let i = 0; i <= 4; i++) { const y = T + ph * i / 4; g.beginPath(); g.moveTo(L, y); g.lineTo(L + pw, y); g.stroke(); }
    const span = t1 - t0;
    const steps = [0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1];
    const st = steps.find(s => span / s <= 10) || 1;
    g.fillStyle = "#94a3b8"; g.textAlign = "center";
    for (let t = Math.ceil(t0 / st) * st; t <= t1 + 1e-9; t += st) {
      const x = X(t); g.beginPath(); g.moveTo(x, T); g.lineTo(x, T + ph); g.stroke();
      g.fillText(t.toFixed(st < 0.01 ? 3 : 2), x, H - 4);
    }
    // nol & skala
    if (d.ymin < 0 && d.ymax > 0) { g.strokeStyle = "#cbd5e1"; g.beginPath(); g.moveTo(L, Y(0)); g.lineTo(L + pw, Y(0)); g.stroke(); }
    g.textAlign = "right"; g.fillStyle = "#475569";
    g.fillText(fmt(d.ymax, d.ymax < 10 ? 2 : 0), L - 4, T + 8);
    g.fillText(fmt(d.ymin, Math.abs(d.ymin) < 10 ? 2 : 0), L - 4, T + ph);
    g.fillStyle = "#94a3b8"; g.fillText(d.unit || "", L - 4, T + ph / 2 + 3);
    // penanda kejadian
    for (const m of this.app.markers) {
      if (m.t < t0 || m.t > t1) continue;
      g.strokeStyle = m.kind === "fault" ? "#dc2626" : m.kind === "trip" ? "#d97706" : m.kind === "der" ? "#7c3aed" : "#94a3b8";
      g.setLineDash([3, 3]); g.beginPath(); g.moveTo(X(m.t), T); g.lineTo(X(m.t), T + ph); g.stroke(); g.setLineDash([]);
    }
    // jejak
    g.save(); g.beginPath(); g.rect(L, T, pw, ph); g.clip();
    const cols = d.colors || PH;
    g.lineWidth = 1.6;
    d.ch.forEach((c, ci) => {
      g.strokeStyle = cols[ci % cols.length]; g.beginPath();
      if (d.mode === "inst") {
        const i0 = Math.max(Math.floor(t0 * d.fs), 0), i1 = Math.min(Math.ceil(t1 * d.fs), c.length - 1);
        const n = i1 - i0, per = Math.max(1, Math.floor(n / pw / 1.5));
        let first = true;
        if (per <= 1) {
          for (let i = i0; i <= i1; i++) { const x = X(i / d.fs), y = Y(c[i]); if (first) { g.moveTo(x, y); first = false; } else g.lineTo(x, y); }
        } else {
          for (let i = i0; i <= i1; i += per) {
            let mn = Infinity, mx = -Infinity;
            for (let j = i; j < Math.min(i + per, i1 + 1); j++) { const v = c[j]; if (v < mn) mn = v; if (v > mx) mx = v; }
            const x = X(i / d.fs);
            if (first) { g.moveTo(x, Y(mn)); first = false; } else g.lineTo(x, Y(mn));
            g.lineTo(x, Y(mx));
          }
        }
      } else {
        let first = true;
        for (let i = 0; i < d.t.length; i++) {
          const t = d.t[i]; if (t < t0 - 0.02 || t > t1 + 0.02) continue;
          const v = c[i]; if (v === null) { first = true; continue; }
          const x = X(t), y = Y(v);
          if (first) { g.moveTo(x, y); first = false; } else g.lineTo(x, y);
        }
      }
      g.stroke();
    });
    g.restore();
    // kursor playback
    const xc = X(this.app.t);
    if (xc >= L && xc <= L + pw) { g.strokeStyle = "#0f172a"; g.lineWidth = 1.2; g.beginPath(); g.moveTo(xc, T); g.lineTo(xc, T + ph); g.stroke(); }
    // label langsung (kanan)
    const vals = this.valueAt(d, this.app.t);
    g.textAlign = "left";
    d.labels.forEach((lb, i) => {
      const y = T + 10 + i * 13;
      g.fillStyle = cols[i % cols.length]; g.fillRect(L + pw + 4, y - 7, 8, 8);
      g.fillStyle = "#334155"; g.fillText(lb.split(" ")[0], L + pw + 14, y);
    });
    row.rd.textContent = d.labels.map((lb, i) => `${lb.split(" ")[0]}:${fmt(vals[i], d.mode === "inst" ? 1 : 2)}`).join("  ") + (d.unit ? " " + d.unit : "");
    // hover crosshair
    if (row.hover !== null && row.hover !== undefined && row.hover >= L && row.hover <= L + pw) {
      const th = t0 + (row.hover - L) / pw * (t1 - t0);
      g.strokeStyle = "#94a3b8"; g.setLineDash([2, 3]); g.beginPath(); g.moveTo(row.hover, T); g.lineTo(row.hover, T + ph); g.stroke(); g.setLineDash([]);
      const hv = this.valueAt(d, th);
      row.tip.style.display = "block";
      row.tip.innerHTML = `t = ${th.toFixed(4)} s<br>` + d.labels.map((lb, i) => `<span class="sw" style="background:${cols[i % cols.length]}"></span>${lb}: ${fmt(hv[i], 2)} ${d.unit || ""}`).join("<br>");
      const left = row.hover + 14 + 170 > W ? row.hover - 180 : row.hover + 14;
      row.tip.style.left = left + "px"; row.tip.style.top = "26px";
    }
  }
}

function bisect(a, x) {
  let lo = 0, hi = a.length - 1;
  while (lo < hi) { const m = (lo + hi + 1) >> 1; if (a[m] <= x) lo = m; else hi = m - 1; }
  return lo;
}
