// SimRelay 34: main application
import { SLD, vStatus, VCOL } from "./sld.js";
import { Scope } from "./scope.js";
import { Editor } from "./editor.js";

const $ = s => document.querySelector(s);
const fmt = (v, d = 0) => (v === null || v === undefined || Number.isNaN(v)) ? "N/A" : Number(v).toFixed(d);
const icon = id => `<svg class="ic"><use href="#i-${id}"/></svg>`;
const clone = o => JSON.parse(JSON.stringify(o));
const CLS_SHORT = { OCR: "OCR", DOCR: "67", DIST: "21", DIFF: "87L" };
const CODE_DESC = {
  "F-1": "Blinding", "F-2": "Sympathetic trip", "F-3": "Miscoordination (CTI)", "F-4": "Wrong direction", "F-5": "Impedance under-reach", "NT": "Nuisance trip",
};

class App {
  constructor() {
    this.t = 0; this.playing = false; this.speed = 0.25; this.markers = [];
    this.insp = null;
    this.runCache = new Map();      // run payloads already downloaded in this session
    this.engine = "python";         // simulation engine: "python" or "matlab" (MATLAB Simulink)
    try { this.engine = localStorage.getItem("sr34-engine") || "python"; } catch (e) { /* storage unavailable */ }
    this.sld = new SLD($("#sld"), $("#sld-host"), this);
    this.scope = new Scope($("#scope"), this);
    this.editor = new Editor(this);
    this._wire();
    this.boot();
  }

  async boot() {
    this.busy(true, "Loading the IEEE 34 network and baseline settings");
    const r = await fetch("/api/init");
    this.init = await r.json();
    this.layout = Object.fromEntries(this.init.topology.buses.map(b => [b.id, { x: b.x, y: b.y }]));
    this.ready = this.init.ready || {};
    const sel = $("#engine");
    if (!this.init.matlab_available) {
      sel.querySelector('option[value="matlab"]').disabled = true;
      this.engine = "python";
    }
    sel.value = this.engine;
    sel.onchange = () => this.setEngine(sel.value);
    this.baseLoadKW = this.init.topology.loads.filter(l => l.feeder === "A").reduce((s, l) => s + l.P.reduce((a, c) => a + c, 0), 0);
    this.renderChips();
    this.busy(false);
    await this.loadPreset(this.init.presets[0].id, true);
    this.prefetch();
  }

  setEngine(eng) {
    this.engine = eng;
    try { localStorage.setItem("sr34-engine", eng); } catch (e) { /* storage unavailable */ }
    this.renderChips();
    this.runScenario();
  }
  cacheKey() {
    return this.engine + "|" + (this.edited ? "custom:" + JSON.stringify(this.scenario) : "preset:" + this.presetId);
  }

  // Download every precomputed preset (Python engine) in the background so switching is instant.
  async prefetch() {
    for (const p of this.init.presets) {
      if (this.runCache.has("python|preset:" + p.id)) continue;
      try {
        const st = await (await fetch("/api/status")).json();
        this.ready = st.ready; this.renderChips();
        const j = await (await fetch(`/api/preset?id=${p.id}`)).json();
        if (!j.error) { this.runCache.set("python|preset:" + p.id, j); this.ready[p.id] = true; this.renderChips(); }
      } catch (e) { /* retried on demand */ }
    }
  }

  // skenario
  renderChips() {
    const host = $("#scen-chips"); host.innerHTML = "";
    for (const p of this.init.presets) {
      const c = document.createElement("div");
      c.className = "chip" + (p.id === this.presetId ? " on" : "");
      const ready = this.engine === "python" ? (this.ready[p.id] || this.runCache.has("python|preset:" + p.id))
                                             : this.runCache.has("matlab|preset:" + p.id) || true;
      c.title = p.desc + (ready ? "" : " (precomputing in the background)");
      c.innerHTML = `<span class="code ${p.code}">${p.code}</span>${p.name}${ready ? "" : '<span class="pend"></span>'}`;
      c.onclick = () => this.loadPreset(p.id, true);
      host.appendChild(c);
    }
  }
  async loadPreset(id, run) {
    const p = this.init.presets.find(x => x.id === id);
    this.presetId = id;
    this.scenario = clone(p.scenario);
    this.scenario.name = p.name;
    this.edited = false;
    this.renderChips();
    if (run) await this.runScenario();
  }

  // Presets come from the precomputed cache; edited scenarios are simulated once and then cached too.
  async runScenario() {
    this.pause();
    const key = this.cacheKey();
    const hit = this.runCache.get(key);
    if (hit) { this.setRun(hit); return; }
    const ml = this.engine === "matlab";
    const slow = this.edited || !this.ready[this.presetId] || ml;
    this.busy(true, ml ? "Running MATLAB Simulink (Simscape Electrical). The first run starts MATLAB and builds the model, about 1 to 2 minutes; cached results load instantly."
                       : slow ? "Running the three-phase phasor engine (dt = 1/960 s)" : "Loading precomputed results");
    $("#btn-run").disabled = true;
    try {
      const body = Object.assign({}, this.scenario, { engine: this.engine });
      const r = this.edited
        ? await fetch("/api/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
        : await fetch(`/api/preset?id=${this.presetId}&engine=${this.engine}`);
      const j = await r.json();
      if (j.error) throw new Error(j.error);
      this.runCache.set(key, j);
      if (!this.edited && !ml) { this.ready[this.presetId] = true; }
      this.renderChips();
      this.setRun(j);
    } catch (e) {
      this.toast("Simulation failed: " + e.message);
    } finally {
      this.busy(false);
      $("#btn-run").disabled = false;
    }
  }

  setRun(run) {
    this.run = run;
    const eb = $("#engine-badge");
    eb.textContent = run.engine === "matlab" ? "MATLAB Simulink" : "Python engine";
    eb.className = "engine-badge" + (run.engine === "matlab" ? " ml" : "");
    eb.title = run.engine_label || "";
    this.busIdx = Object.fromEntries(run.buses.map((b, i) => [b, i]));
    this.brIdx = Object.fromEntries(run.branches.map((b, i) => [b, i]));
    this.iedIdx = Object.fromEntries(run.ied.map((d, i) => [d.id, i]));
    this.derIdx = Object.fromEntries(run.der.map((d, i) => [d.id, i]));
    this.iedClass = Object.fromEntries(run.ied.map(d => [d.id, CLS_SHORT[d.cls] || d.cls]));
    // garis waktu status IED dari SOE relai
    this.iedTL = {};
    for (const d of run.ied) this.iedTL[d.id] = [];
    for (const e of run.events_relay) this.iedTL[e.id]?.push(e);
    // penanda
    this.markers = [];
    for (const e of run.events_sim) {
      if (e.type === "FAULT_ON") this.markers.push({ t: e.t, kind: "fault", label: e.id });
      if (e.type === "CB_OPEN") this.markers.push({ t: e.t, kind: "cb", label: e.id + " open" });
      if (e.type === "DER_TRIP") this.markers.push({ t: e.t, kind: "der", label: e.id + " trip" });
      if (e.type === "ISLAND") this.markers.push({ t: e.t, kind: "der", label: "Island" });
    }
    for (const e of run.events_relay) if (e.type === "TRIP") this.markers.push({ t: e.t, kind: "trip", label: e.id + " TRIP" });
    this.sld.build(run.topology, run, this.layout);
    // kanal default osiloskop
    const hf = run.hunter.faults[0];
    const rows = [["ied:A1:I", "inst"]];
    if (hf && hf.primary && hf.primary !== "A1") rows.push([`ied:${hf.primary}:I`, "inst"]);
    if (run.faults.length) rows.push([`fault:F1:I`, "inst"], [`bus:${run.faults[0].node}:V`, "inst"]);
    else rows.push(["ied:A1:V", "inst"], ["tl:prog:A1", "series"]);
    if (run.der.length && rows.length < 5) rows.push([`der:${run.der[0].id}:I`, "inst"]);
    this.scope.setRun(run, rows);
    // SOE filter
    const f = $("#soe-filter"); f.innerHTML = `<option value="">All IEDs</option>` + run.ied.map(d => `<option>${d.id}</option>`).join("");
    this.renderHunter();
    this.renderMarks();
    $("#pl-T").textContent = run.T.toFixed(3) + " s";
    const t0 = run.faults.length ? Math.max(run.faults[0].t_on - 0.08, 0) : 0;
    this.insp = null; $("#inspector").classList.add("hidden");
    this.seek(t0);
    this.play();
  }

  // playback
  frameAt(t) { const r = this.run; return Math.min(Math.max(Math.round(t / 0.01), 0), r.t.length - 1); }
  seek(t) {
    if (!this.run) return;
    this.t = Math.min(Math.max(t, 0), this.run.T);
    this.render();
  }
  play() { if (!this.run) return; if (this.t >= this.run.T - 1e-6) this.t = 0; if (this.playing) return; this.playing = true; $("#pl-play").innerHTML = icon("pause"); this.last = performance.now(); requestAnimationFrame(ts => this.tick(ts)); }
  pause() { this.playing = false; $("#pl-play").innerHTML = icon("play"); }
  tick(ts) {
    if (!this.playing) return;
    const dt = Math.min((ts - this.last) / 1000, 0.1); this.last = ts;
    this.t += dt * this.speed;
    if (this.t >= this.run.T) { this.t = this.run.T; this.render(); this.pause(); return; }
    this.render();
    requestAnimationFrame(x => this.tick(x));
  }

  iedStateAt(t) {
    const st = {};
    for (const [id, evs] of Object.entries(this.iedTL)) {
      const picks = new Set(); let trip = false;
      for (const e of evs) {
        if (e.t > t + 1e-9) break;
        const key = e.text.split(" ")[1];
        if (e.type === "PICKUP") picks.add(key);
        else if (e.type === "DROPOUT") picks.delete(key);
        else if (e.type === "TRIP" || e.type === "DTT") trip = true;
      }
      st[id] = { pick: picks.size > 0, picks: [...picks], trip };
    }
    return st;
  }

  render() {
    const r = this.run; if (!r) return;
    const t = this.t;
    const scan = Number($("#scan-rate").value);
    const tOp = scan > 0.011 ? Math.floor(t / scan) * scan : t;
    const k = this.frameAt(tOp), kG = this.frameAt(t);
    this.kOp = k; this.kG = kG;
    const iedState = this.iedStateAt(tOp);
    this.sld.update({ run: r, k, kGod: kG, t, iedState, iedClass: this.iedClass,
      showGod: $("#ov-god").checked, showFlow: $("#ov-flow").checked, showVal: $("#ov-val").checked });
    // waktu
    $("#pl-t").textContent = t.toFixed(3);
    $("#pl-cyc").textContent = `Cycle ${Math.floor(t * r.f0)}`;
    const pct = t / r.T * 100;
    $("#pl-fill").style.width = pct + "%"; $("#pl-head").style.left = pct + "%";
    $("#scada-clock").textContent = `RTU t = ${tOp.toFixed(2)} s, ${clock(tOp)}`;
    this.renderKPI(k);
    this.renderAlarms(tOp);
    this.renderSOE(t);
    this.scope.drawAll();
    if (this.insp) this.renderInspector();
  }

  renderKPI(k) {
    const r = this.run;
    const pA = r.Pbr[k][this.brIdx[this.brForIED("A1")]]?.[0];
    const pB = r.Pbr[k][this.brIdx[this.brForIED("B1")]]?.[0];
    const pd = r.der.reduce((s, d) => s + (d.on[k] ? (d.P[k] || 0) : 0), 0);
    let vmin = 9, vb = "";
    r.buses.forEach((b, i) => { if (b.startsWith("F")) return; for (const v of r.Vpu[k][i]) if (v !== null && v < vmin && v > 0.05) { vmin = v; vb = b; } });
    const st = vStatus(vmin);
    $("#kpi").innerHTML = [
      ["Frequency", fmt(r.freq[k], 3), "Hz"],
      ["Feeder A Power", fmt(pA, 0), "kW"],
      ["Feeder B Power", fmt(pB, 0), "kW"],
      ["Total DER Power", fmt(pd, 0), "kW"],
      ["Minimum Voltage (energized)", `<span style="color:${st === "crit" ? "#b91c1c" : st === "warn" ? "#b45309" : "inherit"}">${fmt(vmin === 9 ? null : vmin, 3)}</span>`, `pu at ${vb}`],
    ].map(([l, v, u]) => `<div class="k"><div class="l">${l}</div><div class="v">${v}<small>${u}</small></div></div>`).join("");
  }
  brForIED(id) {
    const m = this.run.topology.ieds.find(x => x.id === id);
    const br = this.run.topology.branches.find(b => b.from === m.from && b.to === m.to);
    return br ? br.id : null;
  }

  renderAlarms(tOp) {
    const al = this.run.events_scada.filter(a => a.t <= tOp + 1e-9).slice(-7).reverse();
    $("#alarm-strip").innerHTML = `<span class="al-h">SCADA Alarms</span>` + (al.length ? al.map(a => `<span class="al ${a.sev}"><b>${a.t.toFixed(3)}</b>${a.text}</span>`).join("") : `<span class="al">No active alarms</span>`);
  }

  renderSOE(t) {
    const r = this.run;
    const all = $("#soe-all").checked, flt = $("#soe-filter").value;
    const key = `${r.id}|${all}|${flt}|${Math.round(t * 1000)}`;
    if (key === this._soeKey) return; this._soeKey = key;
    const rows = r.events_relay.filter(e => (!flt || e.id === flt) && e.type !== "DROPOUT" && (all || e.t <= t + 1e-9));
    const tb = $("#soe-relay tbody");
    tb.innerHTML = rows.map(e => `<tr class="k-${e.kind}${e.t > t ? " future" : ""}"><td>${clock(e.t)}</td><td><span class="iedtag">${e.id}</span></td><td>${esc(e.text.replace(e.id + " ", ""))}</td></tr>`).join("")
      || `<tr><td colspan="3" class="empty">No IED records up to t = ${t.toFixed(3)} s</td></tr>`;
    const srows = r.events_sim.filter(e => all || e.t <= t + 1e-9);
    $("#soe-sim tbody").innerHTML = srows.map(e => `<tr class="s-${e.type}${e.t > t ? " future" : ""}"><td>${e.t.toFixed(4)}</td><td>${esc(e.text)}</td></tr>`).join("")
      || `<tr><td colspan="2" class="empty">No physical events yet</td></tr>`;
  }

  renderMarks() {
    const r = this.run, host = $("#pl-marks"); host.innerHTML = "";
    const seen = new Set();
    for (const m of this.markers) {
      const d = document.createElement("div"); d.className = "pl-mark " + m.kind; d.style.left = (m.t / r.T * 100) + "%";
      const key = m.kind + Math.round(m.t * 50);
      if ((m.kind === "fault" || m.kind === "trip") && !seen.has(key)) { const l = document.createElement("span"); l.className = "ml"; l.textContent = m.label; d.appendChild(l); seen.add(key); }
      d.title = `${m.label} at ${m.t.toFixed(3)} s`;
      host.appendChild(d);
    }
  }

  renderHunter() {
    const r = this.run, H = r.hunter;
    const codes = ["F-1", "F-2", "F-3", "F-4", "F-5", "NT"];
    $("#verdict-mini").innerHTML = codes.slice(0, 5).map(c => `<span class="vchip ${H.counts[c] ? "hit" : ""}" title="${H.codes[c]}">${c}${H.counts[c] ? " (" + H.counts[c] + ")" : ""}</span>`).join("")
      + (H.findings.length ? "" : `<span class="vchip okk">Correct Operation</span>`);
    const cm = H.confusion;
    const pct = v => v === null || v === undefined ? "N/A" : (v * 100).toFixed(0) + "%";
    const gts = H.faults.map(f => `<div><b>${f.fault}</b> ${f.type}${f.type === "3PH" ? "" : "-" + (f.phases || "").toUpperCase()} at <b>${f.node}</b> (Feeder ${f.feeder}), Rf ${f.rf} Ω, peak |If| ${fmt(f.If_A, 0)} A. Primary: <b>${f.primary || "none"}</b>, backup: <b>${f.backup || "none"}</b>.</div>`).join("");
    $("#tab-hunter").innerHTML = `<div class="hunt">
      ${H.faults.length ? `<div class="gt">${gts}</div>` : `<div class="gt">No fault is applied in this scenario. Any trip is therefore a security failure (nuisance trip).</div>`}
      ${H.findings.length ? "" : `<div class="ok-banner">Conventional relays operated correctly in this scenario (no F-1 to F-5 findings).</div>`}
      <div class="codes">${codes.map(c => `<div class="cd ${H.counts[c] ? "hit" : ""}"><div class="c">${c}</div><div class="n">${H.counts[c] || 0}</div><div class="d">${CODE_DESC[c]}</div></div>`).join("")}</div>
      <div class="metric"><div><div class="l">Dependability</div><div class="v">${pct(H.dependability)}</div></div><div><div class="l">Security</div><div class="v">${pct(H.security)}</div></div></div>
      <div class="cm"><div></div><div class="lb">Tripped</div><div class="lb">Not tripped</div>
        <div class="lb">Should trip</div><div class="cell tp">TP ${cm.TP}</div><div class="cell fn">FN ${cm.FN}</div>
        <div class="lb">Should not trip</div><div class="cell fp">FP ${cm.FP}</div><div class="cell tn">TN ${cm.TN}</div></div>
      ${H.findings.map((f, i) => `<div class="find ${f.code}" data-i="${i}"><div class="fh"><span class="fc">${f.code}</span><span class="ft">${esc(f.title)}</span><span class="tt">${f.t != null ? f.t.toFixed(3) + " s" : ""}</span></div><div class="fx">${esc(f.text)}</div></div>`).join("")}
    </div>`;
    $("#tab-hunter").querySelectorAll(".find").forEach(d => d.onclick = () => {
      const f = H.findings[+d.dataset.i];
      if (f.t != null) this.seek(Math.max(f.t - 0.03, 0));
      if (f.ied) this.inspect("ied", f.ied, null);
    });
    if (H.findings.length) this.showTab("hunter");
  }
  showTab(n) {
    document.querySelectorAll("#god-tabs .tab").forEach(b => b.classList.toggle("on", b.dataset.tab === n));
    document.querySelectorAll(".god-side .tabpane").forEach(p => p.classList.toggle("on", p.id === "tab-" + n));
  }

  // inspector
  inspect(kind, id, ev) {
    if (this.sld.dragMoved) return;
    this.insp = { kind, id };
    const box = $("#inspector"), host = $("#sld-host").getBoundingClientRect();
    box.classList.remove("hidden");
    if (ev) {
      let x = ev.clientX - host.left + 14, y = ev.clientY - host.top - 20;
      if (x + 350 > host.width) x = ev.clientX - host.left - 360;
      y = Math.max(8, Math.min(y, host.height - 300));
      box.style.left = x + "px"; box.style.top = y + "px";
    } else { box.style.left = (host.width - 352) + "px"; box.style.top = "60px"; }
    this.renderInspector();
  }
  renderInspector() {
    const { kind, id } = this.insp, r = this.run, k = this.kOp, kg = this.kG;
    const T = r.topology;
    const ph3 = (vals, d = 2) => `<div class="ph3"><span class="hd"></span>${["A", "B", "C"].map(p => `<span class="hd c"><i class="sw" style="background:var(--ph${p})"></i>${p}</span>`).join("")}${vals.map(([lab, arr, dd]) => `<span class="r">${lab}</span>${[0, 1, 2].map(i => `<span class="c">${fmt(arr[i], dd ?? d)}</span>`).join("")}`).join("")}</div>`;
    const kv = pairs => `<div class="kv">${pairs.map(([a, b]) => `<span class="k">${a}</span><span class="v">${b}</span>`).join("")}</div>`;
    const pill = (cls, txt) => `<span class="pill ${cls}">${txt}</span>`;
    let ic = kind.toUpperCase(), nm = id, body = "";
    if (kind === "bus") {
      const b = T.buses.find(x => x.id === id), i = this.busIdx[id];
      const loads = T.loads.filter(l => l.bus === id);
      nm = `Bus ${id}`;
      body = kv([["Nominal voltage", `${b.kv} kV LL`], ["Phases", b.phases.toUpperCase()], ["Feeder", b.feeder]]) +
        `<h5>Measurements (SCADA)</h5>` + ph3([["|V| pu", r.Vpu[k][i], 4], ["Angle (°)", r.Vang[k][i], 1]]) +
        (loads.length ? `<h5>Connected Load (nominal times load level)</h5>` + loads.map(l => kv([[`${l.id} (${l.conn}, ${l.model})`, `${fmt(l.P.reduce((a, c) => a + c, 0), 1)} kW, ${fmt(l.Q.reduce((a, c) => a + c, 0), 1)} kvar`]])).join("") : "");
    } else if (kind === "load") {
      const ls = T.loads.filter(l => l.bus === id), i = this.busIdx[id];
      ic = "LOAD"; nm = `Load at Bus ${id}`;
      body = ls.map(l => `<h5>${l.id}, ${l.conn === "Y" ? "Wye" : "Delta"}, model ${l.model} (engine: constant Z)</h5>` + ph3([["P (kW)", l.P, 1], ["Q (kvar)", l.Q, 1]])).join("") +
        `<h5>Status</h5>` + kv([["Energized", r.energized[k][i] ? pill("ok", "Yes") : pill("crit", "De-energized")]]);
    } else if (kind === "line" || kind === "reg" || kind === "xfmr") {
      const br = T.branches.find(x => x.id === id), j = this.brIdx[id];
      nm = id;
      const P = r.Pbr[k][j];
      const info = kind === "line" ? [["From bus", br.from], ["To bus", br.to], ["Length", `${fmt(br.len_ft, 0)} ft (${fmt(br.len_ft / 5280, 2)} mi)`], ["Configuration", `${br.cfg}, phases ${br.phases.toUpperCase()}`]]
        : kind === "reg" ? [["From bus", br.from], ["To bus", br.to], ["Tap A / B / C", br.taps.join(" / ")], ["Ratio", br.taps.map(x => (1 + 0.00625 * x).toFixed(4)).join(" / ")]]
        : [["From bus", br.from], ["To bus", br.to], ["Rating", `${br.kva} kVA, ${br.kv1}/${br.kv2} kV`], ["Impedance", `${br.r_pct} + j${br.x_pct} %`]];
      body = kv(info) + `<h5>Flow (SCADA, sending end)</h5>` + ph3([["|I| A", r.Ibr[k][j], 1]]) +
        kv([["Total P", `${fmt(P[0], 1)} kW ${P[0] < -1 ? pill("warn", "Reverse flow") : ""}`], ["Total Q", `${fmt(P[1], 1)} kvar`]]);
    } else if (kind === "cap") {
      const c = T.caps.find(x => x.id === id);
      body = kv([["Bus", c.bus], ["Rating", c.kvar.join(" / ") + " kvar per phase"], ["Status", c.on ? pill("ok", "In service") : pill("mute", "Out of service")]]);
    } else if (kind === "sub") {
      ic = "SUB"; nm = "Substation 69/24.9 kV";
      const s = T.substation;
      body = kv([["Transformer", `${s.kva} kVA, ${s.kv_hv}/${s.kv_lv} kV, ${s.conn}`], ["Transformer impedance", `${s.r_pct} + j${s.x_pct} %`], ["Source voltage", `${s.v_pu} pu`],
        ["CB-GI", r.sub[k] ? pill("crit", "Closed") : pill("ok", "Open (islanded)")], ["Frequency", `${fmt(r.freq[k], 3)} Hz`]]);
    } else if (kind === "der") {
      const j = this.derIdx[id], d = r.der[j], c = d.cfg;
      ic = d.type; nm = `${id} at Bus ${d.bus}`;
      body = kv([["Technology", d.type === "SG" ? "Synchronous generator" : d.type === "IBR-GFM" ? "Grid-forming inverter" : "Grid-following inverter (PV)"],
        ["Capacity", `${fmt(d.kva, 0)} kVA (${fmt(d.kva / this.baseLoadKW * 100, 0)}% of Feeder A peak load)`], ["Interconnection transformer", d.xfmr === "YgD" ? "Yg-Delta (zero-sequence source)" : "Delta-Yg (no zero sequence)"],
        ...(d.type === "IBR-GFL" ? [["FRT mode", c.frt === "P" ? "P priority" : "Q priority (IEEE 2800)"], ["Current limit", `${c.imax ?? 1.2} pu`], ["Negative-sequence injection", c.neg_seq ? "Enabled" : "Disabled (conventional)"]] : []),
        ...(d.type === "SG" ? [["X''d / X'd / Xd", `${c.xdpp ?? 0.15} / ${c.xdp ?? 0.25} / ${c.xd ?? 1.0} pu`]] : []),
        ["Status", d.on[k] ? pill("ok", "Online") : pill("crit", "Offline")]]) +
        `<h5>Measurements</h5>` + kv([["Active power", `${fmt(d.P[k], 1)} kW`], ["Reactive power", `${fmt(d.Q[k], 1)} kvar`], ...(d.irr ? [["Irradiance", `${fmt(d.irr[k], 0)} W/m²`]] : [])]) + ph3([["|I| A", d.I[k], 1]]);
    } else if (kind === "ied") {
      const j = this.iedIdx[id], d = r.ied[j], m = T.ieds.find(x => x.id === id), s = this.init.settings[id];
      const st = this.iedStateAt(r.t[k])[id];
      ic = CLS_SHORT[d.cls]; nm = m.name;
      const status = st.trip ? pill("crit", "Trip") : st.pick ? pill("warn", "Pickup " + st.picks.join(", ")) : pill("ok", "Normal");
      body = kv([["Location", `Bus ${m.from} to Bus ${m.to} (forward is toward the load)`], ["Active class", this.init.classes[d.cls]], ...(d.fallback ? [["Note", d.fallback]] : []),
        ["Breaker", d.cb[k] ? pill("crit", "Closed") : pill("ok", "Open")], ["Relay status", status]]) +
        `<h5>Measurements (one-cycle filtered phasors)</h5>` + ph3([["|I| A", d.I[k], 1], ["|V| pu", d.Vpu[k], 3]]) + kv([["3I0", `${fmt(d.I0x3[k], 1)} A`], ["51P / 51N progress", `${fmt(d.prog[k][0] * 100, 0)}% / ${fmt(d.prog[k][1] * 100, 0)}%`]]) +
        `<h5>Frozen Settings (baseline, 0% DER)</h5>` + kv([["51P", `${s["51P_pu"]} A, TMS ${s["51P_tms"]}, IEC SI`], ["50P", s["50P_pu"] ? `${s["50P_pu"]} A` : "Not set"], ["51N", s["51N_pu"] ? `${s["51N_pu"]} A, TMS ${s["51N_tms"]}` : "Not set (single-phase)"], ["50N", s["50N_pu"] ? `${s["50N_pu"]} A` : "Not set"],
          ["21 Z1 / Z2 / Z3", s.zreach.map(z => fmt(z, 1)).join(" / ") + " Ω"], ["87L", s["87_pu"] ? `${s["87_pu"]} A, slope 30%` : "Not set"]]);
    }
    let god = "";
    if ($("#ov-god").checked && r.faults.length && (kind === "bus" || kind === "ied")) {
      const f = r.faults[0];
      if (kind === "bus" && f.node === id) god = `<div class="god-note">Ground truth: fault ${f.id} (${f.type}) is located here from t = ${f.t_on} s. |If| = ${(f.I[kg] || []).map(x => fmt(x, 0)).join(" / ")} A.</div>`;
      if (kind === "ied") { const hf = r.hunter.faults[0]; if (hf) god = `<div class="god-note">Ground truth: for ${hf.fault} at ${hf.node}, this IED is ${hf.primary === id ? "the primary relay" : hf.backup === id ? "the backup relay" : hf.upstream.includes(id) ? "upstream (remote backup)" : "outside the fault path and must not trip"}.</div>`; }
    }
    $("#inspector").innerHTML = `<div class="insp-h"><span class="ic2">${ic}</span><span class="nm">${esc(nm)}</span><span class="x" id="insp-x" title="Close">${icon("close")}</span></div><div class="insp-b">${body}${god}</div>`;
    $("#insp-x").onclick = () => { this.insp = null; $("#inspector").classList.add("hidden"); };
  }

  // wiring
  _wire() {
    $("#btn-run").onclick = () => this.runScenario();
    $("#btn-editor").onclick = () => this.editor.open();
    $("#pl-play").onclick = () => this.playing ? this.pause() : this.play();
    $("#pl-start").onclick = () => this.seek(0);
    $("#pl-end").onclick = () => this.seek(this.run.T);
    $("#pl-back").onclick = () => this.seek(this.t - 1 / 60);
    $("#pl-fwd").onclick = () => this.seek(this.t + 1 / 60);
    $("#pl-speed").onchange = e => this.speed = Number(e.target.value);
    $("#btn-fit").onclick = () => this.sld.fit();
    for (const id of ["#ov-god", "#ov-flow", "#ov-val", "#scan-rate", "#soe-all", "#soe-filter"]) $(id).onchange = () => { this._soeKey = null; this.render(); };
    $("#scope-win").onchange = e => { this.scope.win = Number(e.target.value); this.scope.drawAll(); };
    $("#btn-addrow").onclick = () => this.scope.addRow("ied:A1:V", "inst");
    document.querySelectorAll("#god-tabs .tab").forEach(b => b.onclick = () => this.showTab(b.dataset.tab));
    const track = $("#pl-track");
    let drag = false;
    const tAt = ev => { const rc = track.getBoundingClientRect(); return Math.min(Math.max((ev.clientX - rc.left) / rc.width, 0), 1) * (this.run?.T || 0); };
    track.addEventListener("mousedown", ev => { drag = true; this.pause(); this.seek(tAt(ev)); });
    window.addEventListener("mousemove", ev => {
      const tip = $("#pl-tip"), rc = track.getBoundingClientRect();
      if (ev.clientY > rc.top - 10 && ev.clientY < rc.bottom + 10 && ev.clientX >= rc.left && ev.clientX <= rc.right && this.run) {
        tip.style.display = "block"; tip.style.left = (ev.clientX - rc.left) + "px"; tip.textContent = tAt(ev).toFixed(3) + " s";
      } else tip.style.display = "none";
      if (drag) this.seek(tAt(ev));
    });
    window.addEventListener("mouseup", () => drag = false);
    window.addEventListener("keydown", ev => {
      if (ev.target.tagName === "INPUT" || ev.target.tagName === "SELECT") return;
      if (ev.code === "Space") { ev.preventDefault(); this.playing ? this.pause() : this.play(); }
      if (ev.code === "ArrowLeft") this.seek(this.t - (ev.shiftKey ? 0.1 : 1 / 60));
      if (ev.code === "ArrowRight") this.seek(this.t + (ev.shiftKey ? 0.1 : 1 / 60));
      if (ev.code === "Home") this.seek(0);
      if (ev.code === "End") this.seek(this.run.T);
      if (ev.code === "Escape") { this.editor.close(); this.insp = null; $("#inspector").classList.add("hidden"); }
    });
    window.addEventListener("resize", () => this.scope.drawAll());
    this._legend();
  }
  _legend() {
    const dot = (c, l) => `<span class="lg"><i style="background:${c}"></i>${l}</span>`;
    $("#sld-legend").innerHTML =
      dot(VCOL.good, "Voltage normal (0.95 to 1.05 pu)") + dot(VCOL.warn, "Voltage marginal") + dot(VCOL.crit, "Voltage critical (below 0.90 or above 1.10 pu)") + dot(VCOL.dead, "De-energized") +
      `<span class="lg"><i class="sq" style="background:var(--cb-closed)"></i>Breaker closed</span><span class="lg"><i class="sq" style="border:2px solid var(--cb-open);background:#fff"></i>Breaker open</span>` +
      `<span class="lg"><i class="ln" style="background:#2563eb"></i>Power flow</span><span class="lg"><i class="ln" style="background:#d97706"></i>Reverse power flow</span>`;
  }

  busy(on, txt) { $("#busy").classList.toggle("hidden", !on); if (txt) $("#busy-t").textContent = txt; }
  toast(m) { const t = $("#toast"); t.textContent = m; t.classList.remove("hidden"); clearTimeout(this._tt); this._tt = setTimeout(() => t.classList.add("hidden"), 6000); }
}

function clock(t) {
  const ms = Math.round(t * 1000), s = Math.floor(ms / 1000);
  return `14:00:${String(s).padStart(2, "0")}.${String(ms % 1000).padStart(3, "0")}`;
}
function esc(s) { return String(s).replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c])); }

window.app = new App();
