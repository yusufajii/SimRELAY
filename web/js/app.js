// SimRelay 34: main application
import { SLD, vStatus, LAYERS, QTY, FUNC } from "./sld.js";
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
    this.sld.update({ run: r, k, kGod: kG, t, iedState, iedClass: this.iedClass });
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
    const r = this.run;
    const al = r.events_scada.filter(a => a.t <= tOp + 1e-9);
    const key = `${r.id}|${al.length}`;
    if (key === this._alKey) return; this._alKey = key;
    $("#al-cnt").textContent = al.length ? `(${al.length})` : "";
    const PRI = { hi: "High", mid: "Medium", lo: "Low", ok: "Normal" };
    $("#alarm-list tbody").innerHTML = al.slice().reverse().map(a =>
      `<tr class="p-${a.sev}"><td>${clock(a.t)}</td><td>${esc(this.alarmPoint(a.id))}</td><td>${esc(alarmText(a))}</td><td><span class="pri ${a.sev}">${PRI[a.sev] || a.sev}</span></td></tr>`
    ).join("") || `<tr><td colspan="4" class="empty">No alarms up to t = ${tOp.toFixed(2)} s</td></tr>`;
  }
  alarmPoint(id) {
    const T = this.run.topology;
    if (T.buses.some(b => b.id === id)) return `Bus ${id}`;
    if (T.ieds.some(x => x.id === id)) return `Relay ${id}`;
    return id;
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

  // inspector: a static part (title, display options, actions) and a body refreshed every frame
  inspect(kind, id, ev) {
    if (this.sld.dragMoved) return;
    this.insp = { kind, id };
    const box = $("#inspector"), host = $("#sld-host").getBoundingClientRect();
    box.classList.remove("hidden");
    const W = 384;
    if (ev) {
      let x = ev.clientX - host.left + 16, y = ev.clientY - host.top - 20;
      if (x + W + 8 > host.width) x = ev.clientX - host.left - W - 16;
      x = Math.max(8, x);
      y = Math.max(8, Math.min(y, host.height - 320));
      box.style.left = x + "px"; box.style.top = y + "px";
    } else { box.style.left = Math.max(8, host.width - W - 12) + "px"; box.style.top = "12px"; }
    this.buildInspector();
  }
  // What each colour of the selected element means, with the colour shown now marked as current.
  colourInfo(kind, id) {
    const S = this.sld, INK = "#1e293b", DEAD = "#c3cad5", AMB = "#d97706", RED = "#dc2626", VIO = "#7c3aed", GRN = "#16a34a";
    const sw = (type, c) => {
      const svg = inner => `<svg viewBox="0 0 30 16" width="30" height="16">${inner}</svg>`;
      if (type === "line") return svg(`<path d="M2,8H28" stroke="${c}" stroke-width="2.6"/>`);
      if (type === "thick") return svg(`<path d="M2,8H28" stroke="${c}" stroke-width="4"/>`);
      if (type === "dash") return svg(`<path d="M2,8H28" stroke="${c}" stroke-width="2.4" stroke-dasharray="5 4"/>`);
      if (type === "dot") return svg(`<circle cx="15" cy="8" r="5" fill="${c}"/>`);
      if (type === "box") return svg(`<rect x="9" y="2" width="12" height="12" fill="${c}" stroke="${c === "#fff" ? GRN : "#991b1b"}" stroke-width="2"/>`);
      if (type === "relay") return svg(`<rect x="8" y="1.5" width="14" height="13" fill="${c[1]}" stroke="${c[0]}" stroke-width="1.6"/>`);
      if (type === "wire") return svg(`<path d="M2,8H28" stroke="${c}" stroke-width="${c === RED ? 1.8 : 1.1}" stroke-dasharray="3 2"/>`);
      return svg(`<path d="M2,8H28" stroke="${c}" stroke-width="2"/>`);
    };
    let rows = [], cur = -1;
    const r = this.run, k = this.kOp;
    if (kind === "line" || kind === "reg" || kind === "xfmr") {
      const e = S.lineEls[id];
      const stroke = e ? e.p.getAttribute("stroke") : INK, dashed = e && e.p.getAttribute("stroke-dasharray");
      rows = [["line", INK, "Dark grey: energized, the line has voltage or carries current"],
        ["dash", DEAD, "Light grey, dashed: de-energized, no voltage and no current"],
        ["thick", RED, "Red, heavier: carries fault current from a connected source to the fault (ground truth layer only)"]];
      cur = dashed ? 1 : stroke === RED ? 2 : 0;
      rows.push(["flow", "#64748b", "Grey arrows: direction of active power flow; amber arrows: reverse flow towards the source"]);
    } else if (kind === "bus") {
      const st = S.busEls[id] ? S.busEls[id].st : "good";
      rows = [["dot", INK, "Dark grey: voltage within 0.95 to 1.05 pu"], ["dot", AMB, "Amber: marginal voltage, 0.90 to 0.95 or 1.05 to 1.10 pu"],
        ["dot", RED, "Red: critical voltage, below 0.90 or above 1.10 pu (also a bus near a fault that still carries current)"], ["dot", DEAD, "Light grey: de-energized"]];
      cur = { good: 0, warn: 1, crit: 2, dead: 3 }[st] ?? 0;
    } else if (kind === "ied") {
      const st = this.iedStateAt(r.t[k])[id] || {};
      rows = [["relay", [INK, "#fff"], "Dark outline: normal, no protection element has started"], ["relay", [VIO, "#f3efff"], "Violet: pickup, an element has started timing but has not tripped"],
        ["relay", [RED, "#fee2e2"], "Red: trip, the relay has issued a trip command (blinks until the breaker opens)"],
        ["wire", "#8a97a8", "Grey dashed wires: CT and VT measurement inputs, and the trip circuit at rest"], ["wire", RED, "Red trip circuit: trip command sent to the breaker"]];
      cur = st.trip ? 2 : st.pick ? 1 : 0;
    } else if (kind === "cb") {
      const closed = id === "SUB" ? r.sub[k] : r.ied[this.iedIdx[id]].cb[k];
      rows = [["box", "#dc2626", "Red, filled: closed (SCADA convention)"], ["box", "#fff", "Green outline: open"]];
      cur = closed ? 0 : 1;
    } else if (kind === "der") {
      const on = r.der[this.derIdx[id]].on[k];
      rows = [["line", INK, "Dark grey: in service"], ["dash", DEAD, "Light grey, dashed: disconnected by its own protection (IEEE 1547) or by the scenario"]];
      cur = on ? 0 : 1;
    } else if (kind === "load" || kind === "cap") {
      const e = kind === "load" ? S.loadEls[id] : S.capEls[id];
      const live = e && e.parts[0].getAttribute("stroke") !== DEAD;
      rows = [["line", INK, kind === "load" ? "Dark grey: supplied" : "Dark grey: in service and energized"], ["line", DEAD, kind === "load" ? "Light grey: not supplied" : "Light grey: out of service or de-energized"]];
      cur = live ? 0 : 1;
    } else if (kind === "ct" || kind === "vt") {
      const e = S.iedEls[id];
      const live = e && e.ctc.getAttribute("stroke") !== DEAD;
      rows = [["line", INK, "Dark grey: the measured point is energized"], ["line", DEAD, "Light grey: the measured point is de-energized"]];
      cur = live ? 0 : 1;
    } else return "";
    return `<h5>Colour on the diagram</h5><div class="cmean">${rows.map(([t, c, txt], i) => `<div class="cr${i === cur ? " cur" : ""}">${sw(t, c)}<span>${txt}</span>${i === cur ? "<em>Current</em>" : "<i></i>"}</div>`).join("")}</div>`;
  }
  dispGroups(kind, id) {
    return ({
      bus: [["Bus", "bus:" + id]], load: [["Load", "load:" + id]], line: [["Line", "line:" + id]], reg: [["Regulator", "reg:" + id]],
      xfmr: [["Transformer", "xfmr:" + id]], cap: [["Capacitor bank", "cap:" + id]], sub: [["Grid source", "src:SUB"], ["Breaker CB-GI", "cb:SUB"]],
      der: [["Distributed energy resource", "der:" + id]], ct: [["Current transformer", "ct:" + id]], vt: [["Voltage transformer", "vt:" + id]],
      cb: [["Breaker", "cb:" + id]], ied: [["Relay", "relay:" + id], ["Current transformer", "ct:" + id], ["Voltage transformer", "vt:" + id]],
    })[kind] || [];
  }
  buildInspector() {
    const { kind, id } = this.insp;
    const box = $("#inspector");
    const CAT = { id: "Identifier", rate: "Rating", in: "Input", out: "Output" };
    const groups = this.dispGroups(kind, id);
    const disp = groups.map(([title, key]) => {
      const qk = key.split(":")[0];
      const rows = (QTY[qk] || []).map(([q, label, cat]) => {
        const off = !this.sld.layers[cat];
        return `<label class="chk${off ? " off" : ""}"${off ? ' title="This text layer is hidden. Enable it under Layers."' : ""}><input type="checkbox" data-key="${key}" data-q="${q}" ${this.sld.isOn(key, q) ? "checked" : ""}><span>${label}</span><em>${CAT[cat]}</em></label>`;
      }).join("");
      return `${groups.length > 1 ? `<div class="disp-t">${title}</div>` : ""}${rows}`;
    }).join("");
    const sig = kind === "ct" ? `ied:${id}:I` : kind === "vt" ? `ied:${id}:V` : null;
    const act = sig ? `<div class="insp-act"><button class="btn tiny" id="insp-scope">${icon("plus")}Show on oscilloscope</button></div>` : "";
    box.innerHTML = `<div class="insp-h"><span class="ic2" id="insp-ic"></span><span class="nm" id="insp-nm"></span><span class="x" id="insp-x" title="Close">${icon("close")}</span></div>
      <div class="insp-b"><div id="insp-body"></div>${act}${disp ? `<details class="disp"${this._dispOpen ? " open" : ""}><summary>Show on diagram</summary><div class="disp-b">${disp}</div></details>` : ""}</div>`;
    $("#insp-x").onclick = () => { this.insp = null; box.classList.add("hidden"); };
    box.querySelectorAll(".disp input").forEach(cb => cb.onchange = () => { this.sld.setOn(cb.dataset.key, cb.dataset.q, cb.checked); this.render(); });
    const d = box.querySelector("details.disp");
    if (d) d.ontoggle = () => { this._dispOpen = d.open; };
    if (sig) $("#insp-scope").onclick = () => { this.scope.addRow(sig, "inst"); this.toastInfo(`${kind === "ct" ? "CT" : "VT"}-${id} has been added to the oscilloscope.`); };
    this._inspHTML = null;
    this.renderInspector();
  }
  renderInspector() {
    const { kind, id } = this.insp, r = this.run, k = this.kOp, kg = this.kG;
    const T = r.topology;
    const ph3 = rows => `<table class="pht"><thead><tr><th></th>${["A", "B", "C"].map(p => `<th><i class="sw" style="background:var(--ph${p})"></i>${p}</th>`).join("")}</tr></thead><tbody>${rows.map(([lab, arr, d]) => `<tr><th>${lab}</th>${[0, 1, 2].map(i => `<td>${arr[i] === null || arr[i] === undefined ? "" : fmt(arr[i], d ?? 2)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
    const kv = pairs => `<table class="kvt">${pairs.map(([a, b]) => `<tr><th>${a}</th><td>${b}</td></tr>`).join("")}</table>`;
    const pill = (cls, txt) => `<span class="pill ${cls}">${txt}</span>`;
    const h = t => `<h5>${t}</h5>`;
    let ic = kind.toUpperCase(), nm = id, body = "";
    const iedShort = m => m.name.split(" (")[0];
    if (kind === "bus") {
      const b = T.buses.find(x => x.id === id), i = this.busIdx[id];
      const loads = T.loads.filter(l => l.bus === id);
      nm = `Bus ${id}`;
      body = kv([["Nominal voltage", `${b.kv} kV line to line`], ["Phases", b.phases.toUpperCase()], ["Feeder", b.feeder]]) +
        h("Measurements (SCADA)") + ph3([["|V| (pu)", r.Vpu[k][i], 4], ["Angle (°)", r.Vang[k][i], 1]]) +
        (loads.length ? h("Connected load (nominal multiplied by load level)") + kv(loads.map(l => [`${l.id}, ${l.conn}, ${l.model}`, `${fmt(l.P.reduce((a, c) => a + c, 0), 1)} kW, ${fmt(l.Q.reduce((a, c) => a + c, 0), 1)} kvar`])) : "");
    } else if (kind === "load") {
      const ls = T.loads.filter(l => l.bus === id), i = this.busIdx[id];
      ic = "LOAD"; nm = `Load at Bus ${id}`;
      body = kv([["Supply", r.energized[k][i] ? pill("ok", "Energized") : pill("mute", "De-energized")], ["Engine model", "Constant impedance"]]) +
        ls.map(l => h(`${l.id}, ${l.conn === "Y" ? "wye" : "delta"}, IEEE model ${l.model}`) + ph3([["P (kW)", l.P, 1], ["Q (kvar)", l.Q, 1]])).join("");
    } else if (kind === "line" || kind === "reg" || kind === "xfmr") {
      const br = T.branches.find(x => x.id === id), j = this.brIdx[id];
      nm = kind === "reg" ? `Voltage regulator ${id}` : kind === "xfmr" ? `Transformer ${id}` : `Line ${br.from} to ${br.to}`;
      const P = r.Pbr[k][j];
      const info = kind === "line" ? [["From bus", br.from], ["To bus", br.to], ["Length", `${fmt(br.len_ft, 0)} ft (${fmt(br.len_ft / 5280, 2)} mi)`], ["Configuration", `${br.cfg}, phases ${br.phases.toUpperCase()}`]]
        : kind === "reg" ? [["From bus", br.from], ["To bus", br.to], ["Tap A / B / C", br.taps.join(" / ")], ["Ratio", br.taps.map(x => (1 + 0.00625 * x).toFixed(4)).join(" / ")]]
        : [["From bus", br.from], ["To bus", br.to], ["Rating", `${br.kva} kVA, ${br.kv1}/${br.kv2} kV`], ["Impedance", `${br.r_pct} + j${br.x_pct} %`]];
      body = kv(info) + h("Flow at the sending end (SCADA)") + ph3([["|I| (A)", r.Ibr[k][j], 1]]) +
        kv([["Active power", `${fmt(P[0], 1)} kW ${P[0] < -1 ? pill("warn", "Reverse flow") : ""}`], ["Reactive power", `${fmt(P[1], 1)} kvar`]]);
    } else if (kind === "cap") {
      const c = T.caps.find(x => x.id === id);
      nm = `Capacitor bank ${id}`;
      body = kv([["Bus", c.bus], ["Rating", c.kvar.join(" / ") + " kvar per phase"], ["Status", c.on ? pill("ok", "In service") : pill("mute", "Out of service")]]);
    } else if (kind === "sub") {
      ic = "SUB"; nm = "Substation 69/24.9 kV";
      const s = T.substation;
      body = kv([["Transformer", `${s.kva} kVA, ${s.kv_hv}/${s.kv_lv} kV, ${s.conn}`], ["Transformer impedance", `${s.r_pct} + j${s.x_pct} %`], ["Source voltage", `${s.v_pu} pu`],
        ["Breaker CB-GI", r.sub[k] ? pill("crit", "Closed") : pill("ok", "Open (islanded)")], ["Frequency", `${fmt(r.freq[k], 3)} Hz`]]);
    } else if (kind === "der") {
      const j = this.derIdx[id], d = r.der[j], c = d.cfg;
      ic = d.type; nm = `${id} at Bus ${d.bus}`;
      body = kv([["Technology", d.type === "SG" ? "Synchronous generator" : d.type === "IBR-GFM" ? "Grid-forming inverter" : "Grid-following inverter (PV)"],
        ["Capacity", `${fmt(d.kva, 0)} kVA (${fmt(d.kva / this.baseLoadKW * 100, 0)}% of Feeder A peak load)`],
        ["Interconnection transformer", d.xfmr === "YgD" ? "Yg-delta (zero-sequence source)" : "Delta-Yg (no zero-sequence path)"],
        ...(d.type === "IBR-GFL" ? [["Fault ride-through", c.frt === "P" ? "Active power priority" : "Reactive power priority (IEEE 2800)"], ["Current limit", `${c.imax ?? 1.2} pu`], ["Negative-sequence injection", c.neg_seq ? "Enabled" : "Disabled (conventional)"]] : []),
        ...(d.type === "SG" ? [["X''d / X'd / Xd", `${c.xdpp ?? 0.15} / ${c.xdp ?? 0.25} / ${c.xd ?? 1.0} pu`]] : []),
        ["Status", d.on[k] ? pill("ok", "In service") : pill("warn", "Disconnected")]]) +
        h("Measurements") + kv([["Active power", `${fmt(d.P[k], 1)} kW`], ["Reactive power", `${fmt(d.Q[k], 1)} kvar`], ...(d.irr ? [["Irradiance", `${fmt(d.irr[k], 0)} W/m²`]] : [])]) + ph3([["|I| (A)", d.I[k], 1]]);
    } else if (kind === "ied" || kind === "ct" || kind === "vt" || kind === "cb") {
      if (kind === "cb" && id === "SUB") {
        nm = "Breaker CB-GI (substation)"; ic = "CB";
        body = kv([["Position", r.sub[k] ? pill("crit", "Closed") : pill("ok", "Open")], ["Location", "Substation, 24.9 kV side"], ["Operated by", "Scheduled switching events (islanding studies)"]]);
      } else {
        const j = this.iedIdx[id], d = r.ied[j], m = T.ieds.find(x => x.id === id), s = this.init.settings[id];
        const st = this.iedStateAt(r.t[k])[id];
        const fn = FUNC[d.cls] || [d.cls, d.cls];
        const cbName = iedShort(m);
        const cbPos = d.cb[k] ? pill("crit", "Closed") : pill("ok", "Open");
        if (kind === "ied") {
          ic = "RELAY"; nm = `Relay ${id}, ${m.name}`;
          const status = st.trip ? pill("crit", "Trip") : st.pick ? pill("pick", "Pickup " + st.picks.join(", ")) : pill("ok", "Normal");
          body = kv([["Location", `Bus ${m.from} to Bus ${m.to} (forward is toward the load)`], ["Active function", `${this.init.classes[d.cls]}`], ["Device function", `${fn[1]} (IEEE C37.2)`],
            ["Inputs", `CT-${id} (currents), VT-${id} (voltages)`], ["Trip output", cbName], ...(d.fallback ? [["Note", d.fallback]] : []),
            ["Breaker", cbPos], ["Relay status", status]]) +
            h("Measurements (one-cycle filtered phasors)") + ph3([["|I| (A)", d.I[k], 1], ["|V| (pu)", d.Vpu[k], 3]]) + kv([["3I0", `${fmt(d.I0x3[k], 1)} A`], ["51P / 51N progress", `${fmt(d.prog[k][0] * 100, 0)}% / ${fmt(d.prog[k][1] * 100, 0)}%`]]) +
            h("Frozen settings (baseline, 0% DER)") + kv([["51P", `${s["51P_pu"]} A, TMS ${s["51P_tms"]}, IEC SI`], ["50P", s["50P_pu"] ? `${s["50P_pu"]} A` : "Not set"], ["51N", s["51N_pu"] ? `${s["51N_pu"]} A, TMS ${s["51N_tms"]}` : "Not set (single-phase)"], ["50N", s["50N_pu"] ? `${s["50N_pu"]} A` : "Not set"],
              ["21 Z1 / Z2 / Z3", s.zreach.map(z => fmt(z, 1)).join(" / ") + " Ω"], ["87L", s["87_pu"] ? `${s["87_pu"]} A, slope 30%` : "Not set"]]);
        } else if (kind === "ct") {
          ic = "CT"; nm = `Current transformer CT-${id}`;
          body = kv([["Location", `Line ${m.from} to ${m.to}, load side of ${cbName}`], ["Connected relay", `${id} (${fn[1]})`], ["Quantity", "Phase currents, in primary amperes"]]) +
            h("Measured currents (one-cycle filtered)") + ph3([["|I| (A)", d.I[k], 1]]) + kv([["Residual current 3I0", `${fmt(d.I0x3[k], 1)} A`]]);
        } else if (kind === "vt") {
          ic = "VT"; nm = `Voltage transformer VT-${id}`;
          const b = T.buses.find(x => x.id === m.from);
          body = kv([["Location", `Bus ${m.from}, source side of ${cbName}`], ["Connected relay", `${id} (${fn[1]})`], ["Quantity", "Phase-to-neutral voltages"]]) +
            h("Measured voltages (one-cycle filtered)") + ph3([["|V| (pu)", d.Vpu[k], 4], ["|V| (kV)", d.Vpu[k].map(v => v === null ? null : v * (b ? b.kv : 24.9) / Math.sqrt(3)), 2]]);
        } else {
          ic = "CB"; nm = `${m.kind === "CB" ? "Circuit breaker" : "Recloser"} ${cbName}`;
          body = kv([["Position", cbPos], ["Location", `Bus ${m.from} to Bus ${m.to}`], ["Tripped by", `Relay ${id} (${fn[1]})`], ["Trip command", st.trip ? pill("crit", "Issued") : pill("mute", "Not issued")]]);
        }
      }
    }
    let god = "";
    if (this.sld.layers.god && r.faults.length && (kind === "bus" || kind === "ied")) {
      const f = r.faults[0];
      if (kind === "bus" && f.node === id) god = `<div class="god-note">Ground truth: fault ${f.id} (${f.type}) is located here from t = ${f.t_on} s. |If| = ${(f.I[kg] || []).map(x => fmt(x, 0)).join(" / ")} A.</div>`;
      if (kind === "ied") { const hf = r.hunter.faults[0]; if (hf) god = `<div class="god-note">Ground truth: for ${hf.fault} at ${hf.node}, this relay is ${hf.primary === id ? "the primary relay" : hf.backup === id ? "the backup relay" : hf.upstream.includes(id) ? "upstream (remote backup)" : "outside the fault path and must not trip"}.</div>`; }
    }
    const html = body + this.colourInfo(kind, id) + god;
    if (html !== this._inspHTML) { this._inspHTML = html; $("#insp-body").innerHTML = html; }
    $("#insp-ic").textContent = ic; $("#insp-nm").textContent = nm;
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
    for (const id of ["#scan-rate", "#soe-all", "#soe-filter"]) $(id).onchange = () => { this._soeKey = null; this.render(); };
    document.querySelectorAll("#rec-tabs .tab").forEach(b => b.onclick = () => {
      document.querySelectorAll("#rec-tabs .tab").forEach(x => x.classList.toggle("on", x === b));
      document.querySelectorAll(".rec-host .tabpane").forEach(p => p.classList.toggle("on", p.id === "tab-" + b.dataset.tab));
    });
    this._popovers();
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
      if (ev.code === "Escape") { this.editor.close(); this.insp = null; $("#inspector").classList.add("hidden"); this._closePops(); }
    });
    window.addEventListener("resize", () => this.scope.drawAll());
  }

  // Layers and Key popovers
  _popovers() {
    const pairs = [["#btn-layers", "#pop-layers"], ["#btn-key", "#pop-key"]];
    for (const [b, p] of pairs) $(b).onclick = ev => {
      ev.stopPropagation();
      const open = $(p).classList.contains("hidden");
      this._closePops();
      if (open) {
        // fixed positioning keeps the popover above the panel edges
        const rc = $(b).getBoundingClientRect(), pop = $(p);
        pop.style.top = (rc.bottom + 6) + "px";
        pop.style.right = Math.max(8, window.innerWidth - rc.right) + "px";
        pop.style.maxHeight = (window.innerHeight - rc.bottom - 18) + "px";
        pop.classList.remove("hidden"); $(b).classList.add("on");
      }
    };
    document.addEventListener("mousedown", ev => { if (!ev.target.closest(".pop-wrap")) this._closePops(); });
    this._buildLayers();
    $("#pop-key").innerHTML = keyHTML();
  }
  _closePops() {
    document.querySelectorAll(".pop").forEach(p => p.classList.add("hidden"));
    document.querySelectorAll(".pop-wrap .btn").forEach(b => b.classList.remove("on"));
  }
  _buildLayers() {
    const L = this.sld.layers;
    const row = l => `<label class="chk${l.locked ? " dis" : ""}"><input type="checkbox" data-layer="${l.id}" ${L[l.id] ? "checked" : ""} ${l.locked ? "disabled" : ""}><span>${l.label}</span></label>`;
    $("#pop-layers").innerHTML = `<div class="pop-h">Component layers</div>${LAYERS.comp.map(row).join("")}
      <div class="pop-h">Text layers</div>${LAYERS.text.map(row).join("")}
      <div class="pop-f"><button class="lnk" data-all="1">Show all text</button><button class="lnk" data-all="0">Hide all text</button></div>
      <div class="pop-note">The quantities shown for an individual element are chosen in its information panel, under Show on diagram.</div>`;
    $("#pop-layers").querySelectorAll("input[data-layer]").forEach(cb => cb.onchange = () => {
      this.sld.setLayer(cb.dataset.layer, cb.checked); this.render(); if (this.insp) this.buildInspector();
    });
    $("#pop-layers").querySelectorAll("[data-all]").forEach(b => b.onclick = () => {
      for (const l of LAYERS.text) this.sld.setLayer(l.id, b.dataset.all === "1");
      this._buildLayers(); this.render(); if (this.insp) this.buildInspector();
    });
  }

  toastInfo(m) {
    const t = $("#toast"); t.textContent = m; t.classList.remove("hidden"); t.classList.add("info");
    clearTimeout(this._tt); this._tt = setTimeout(() => { t.classList.add("hidden"); t.classList.remove("info"); }, 2500);
  }
  busy(on, txt) { $("#busy").classList.toggle("hidden", !on); if (txt) $("#busy-t").textContent = txt; }
  toast(m) { const t = $("#toast"); t.textContent = m; t.classList.remove("hidden"); clearTimeout(this._tt); this._tt = setTimeout(() => t.classList.add("hidden"), 6000); }
}

function clock(t) {
  const ms = Math.round(t * 1000), s = Math.floor(ms / 1000);
  return `14:00:${String(s).padStart(2, "0")}.${String(ms % 1000).padStart(3, "0")}`;
}
// SCADA alarm text in sentence case, without the point name (shown in its own column).
const KEEP = new Set(["DER", "CB", "IED", "SLG", "DLG", "LL", "DTT", "CT", "VT", "GFM", "GFL", "IBR", "SG", "PV", "RTU"]);
function alarmText(a) {
  let s = a.text;
  if (s.startsWith("Bus " + a.id + " ")) s = s.slice(a.id.length + 5);
  else if (s.startsWith(a.id + " ")) s = s.slice(a.id.length + 1);
  let m;
  if ((m = s.match(/^TRIP (\S+) t_op=([\d.]+)s/))) return `Trip by ${m[1]}, operating time ${m[2]} s`;
  if (/^52b: CB OPEN/.test(s)) return "Breaker open (52b contact)";
  s = s.split(" ").map(w => /^[A-Z]{2,}$/.test(w) && !KEEP.has(w) ? w.toLowerCase() : w).join(" ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

// Key: IEC 60617 symbols used on the diagram and the colour convention.
function keyHTML() {
  const sv = (inner, w = 34) => `<svg viewBox="0 0 ${w} 22" width="${w}" height="22" class="ksym">${inner}</svg>`;
  const ink = 'stroke="#1e293b" fill="none" stroke-width="1.5"';
  const sym = [
    [sv(`<path d="M2,11H32" stroke="#1e293b" stroke-width="2.6"/><circle cx="17" cy="11" r="4.5" fill="#1e293b" stroke="#fff" stroke-width="1.5"/>`), "Line and bus (thin line: single-phase lateral)"],
    [sv(`<path d="M2,11H32" stroke="#1e293b" stroke-width="2"/><rect x="10" y="4" width="14" height="14" fill="#dc2626" stroke="#991b1b" stroke-width="2"/>`), "Circuit breaker or recloser, closed"],
    [sv(`<path d="M2,11H32" stroke="#1e293b" stroke-width="2"/><rect x="10" y="4" width="14" height="14" fill="#fff" stroke="#16a34a" stroke-width="2"/>`), "Circuit breaker or recloser, open"],
    [sv(`<path d="M0,11H8M26,11H34" stroke="#1e293b" stroke-width="2"/><circle cx="13" cy="11" r="7" fill="#fff" ${ink}/><circle cx="21" cy="11" r="7" ${ink}/>`), "Transformer"],
    [sv(`<path d="M0,11H8M26,11H34" stroke="#1e293b" stroke-width="2"/><circle cx="13" cy="11" r="7" fill="#fff" ${ink}/><circle cx="21" cy="11" r="7" ${ink}/><path d="M7,19L27,2" ${ink} stroke-width="1.2"/><path d="M27,2L21,3.5L25,7.5Z" fill="#1e293b"/>`), "Step-voltage regulator"],
    [sv(`<path d="M2,11H22" ${ink}/><path d="M32,11L22,6V16Z" fill="#1e293b"/>`), "Load"],
    [sv(`<path d="M2,11H13M19,11H26" ${ink}/><path d="M13,3V19M19,3V19" ${ink} stroke-width="2"/><path d="M26,4V18M29,6.5V15.5M32,9V13" ${ink}/>`), "Shunt capacitor bank, earthed"],
    [sv(`<circle cx="17" cy="11" r="9" fill="#fff" ${ink}/><text x="17" y="12.5" text-anchor="middle" font-size="9" font-weight="700" fill="#1e293b">G</text><path d="M14,16q1.5,-2 3,0t3,0" ${ink} stroke-width="1"/>`), "Synchronous generator (DER)"],
    [sv(`<rect x="8" y="2" width="18" height="18" fill="#fff" ${ink}/><path d="M8,20L26,2M10.5,6.5H15.5" ${ink} stroke-width="1"/><path d="M10.5,9H15.5" ${ink} stroke-width="1" stroke-dasharray="1.5 1"/><path d="M17.5,15.5q1.25,-2 2.5,0t2.5,0" ${ink} stroke-width="1"/>`), "Inverter-based resource (PV or grid-forming)"],
    [sv(`<path d="M0,11H34" stroke="#1e293b" stroke-width="2"/><circle cx="17" cy="11" r="6" fill="none" ${ink}/>`), "Current transformer (CT)"],
    [sv(`<path d="M3,20H31M17,20V14" stroke="#1e293b" stroke-width="1.5"/><circle cx="17" cy="10" r="4.5" fill="#fff" ${ink}/><circle cx="17" cy="4" r="4.5" ${ink}/>`), "Voltage transformer (VT)"],
    [sv(`<rect x="9" y="3" width="16" height="16" fill="#fff" ${ink}/><text x="17" y="14.5" text-anchor="middle" font-size="10" font-weight="700" fill="#1e293b">R</text>`), "Protection relay; the label gives the IEEE C37.2 function, for example 50/51 overcurrent, 67 directional, 21 distance, 87L line differential"],
    [sv(`<path d="M2,11H32" stroke="#8a97a8" stroke-width="1" stroke-dasharray="3 2"/>`), "Measurement circuit (CT or VT to relay)"],
    [sv(`<path d="M2,11H26" stroke="#8a97a8" stroke-width="1.2" stroke-dasharray="3 2"/><path d="M32,11L25,7.5V14.5Z" fill="#8a97a8"/>`), "Trip circuit (relay to breaker), red when a trip is issued"],
    [sv(`<path d="M18,1L10,12H15L11,21L23,8H17L22,1Z" fill="#dc2626"/>`), "Fault location (ground truth layer only)"],
  ];
  const col = [
    ["#1e293b", "", "Energized, within normal limits"],
    ["#c3cad5", "dash", "De-energized"],
    ["#d97706", "", "Marginal voltage (0.90 to 0.95 or 1.05 to 1.10 pu), reverse power flow, DER disconnected"],
    ["#7c3aed", "", "Relay pickup: a protection element has started timing but has not tripped"],
    ["#dc2626", "", "Critical voltage (below 0.90 or above 1.10 pu), relay trip, and with the ground truth layer on, the lines carrying fault current from each connected source to the fault"],
    ["#64748b", "", "Direction of active power flow (arrows)"],
  ];
  return `<div class="pop-h">Symbols (IEC 60617)</div><div class="key-grid">${sym.map(([s, t]) => `<div class="krow">${s}<span>${t}</span></div>`).join("")}</div>
    <div class="pop-h">Colour convention</div><div class="key-grid">${col.map(([c, d, t]) => `<div class="krow"><svg viewBox="0 0 34 22" width="34" height="22" class="ksym"><path d="M3,11H31" stroke="${c}" stroke-width="3" ${d === "dash" ? 'stroke-dasharray="5 4"' : ""}/></svg><span>${t}</span></div>`).join("")}</div>
    <div class="pop-note">Breakers follow the SCADA convention: red is closed and green is open. All other equipment is drawn in neutral colours and changes colour only when its state changes during the simulation.</div>`;
}

function esc(s) { return String(s).replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c])); }

window.app = new App();
