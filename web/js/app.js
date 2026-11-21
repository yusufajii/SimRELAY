// SimRelay 34: main application
import { SLD, vStatus, LAYERS, QTY, FUNC } from "./sld.js";
import { Scope } from "./scope.js";
import { PhasorView } from "./phasor.js";
import { AlarmTiles, RelayChart, ANN_KEY } from "./protect.js";
import { EV, kindOf } from "./icons.js";
import { Editor } from "./editor.js";

// Panels can live in detached windows, so lookups search the main document and every detached one.
const DOCS = [document];
const $ = s => { for (const d of DOCS) { const e = d.querySelector(s); if (e) return e; } return null; };
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
    this.detached = {};
    this.scope = new Scope($("#scope"), this);
    this.phasor = new PhasorView(this);
    this.tiles = new AlarmTiles(this);
    this.relayChart = new RelayChart(this);
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
    await this.loadCatalog();
    this.busy(false);
    await this.loadPreset(this.init.presets[0].id, true);
    this.prefetch();
  }

  setEngine(eng) {
    this.engine = eng;
    try { localStorage.setItem("sr34-engine", eng); } catch (e) { /* storage unavailable */ }
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
        this.ready = st.ready;
        const j = await (await fetch(`/api/preset?id=${p.id}`)).json();
        if (!j.error) { this.runCache.set("python|preset:" + p.id, j); this.ready[p.id] = true; }
      } catch (e) { /* retried on demand */ }
    }
  }

  // ---- stored runs (View mode)
  async loadCatalog() {
    try { this.catalog = (await (await fetch("/api/catalog")).json()).runs || []; }
    catch (e) { this.catalog = this.catalog || []; }
    return this.catalog;
  }
  currentMeta() {
    if (!this.run) return null;
    return (this.catalog || []).find(m => m.key === this.run.id) || null;
  }
  renderRunSel() {
    const m = this.currentMeta();
    $("#rs-id").textContent = m ? m.run_id : "";
    $("#rs-lab").textContent = m && m.labels.length ? m.labels.join(", ") : "";
    $("#rs-name").textContent = m ? m.notes || "" : "";
    $("#run-sel").title = m ? `Run ${m.run_id}${m.labels.length ? ", " + m.labels.join(", ") : ""}${m.notes ? "\n" + m.notes : ""}` : "Choose a stored run";
  }
  async openCatalog() {
    $("#catalog").classList.remove("hidden");
    this._catOpen = true;
    if (!this._catFilters) this._catFilters = { q: "", source: "", engine: "", outcome: "", der: "", ftype: "", relay: "", label: "" };
    this.renderCatalog();
    await this.loadCatalog();
    this.renderCatalog();
    setTimeout(() => $("#cat-q").focus(), 0);
  }
  closeCatalog() { $("#catalog").classList.add("hidden"); this._catOpen = false; }
  derText(m) {
    if (!m.der.length) return "None";
    return m.der.map(d => `${d.type} ${Math.round(d.kva)} kVA at ${d.bus}`).join("; ") + (m.grid === "island" ? " (islanded)" : "");
  }
  faultText(m) {
    if (!m.faults.length) return "None";
    return m.faults.map(f => `${f.type}${f.type === "3PH" ? "" : "-" + String(f.phases || "").toUpperCase()} at ${f.at}, Rf ${f.rf} Ω`).join("; ");
  }
  outcomeOf(m) { const c = Object.keys(m.counts || {}); return c.length ? c : ["OK"]; }
  renderCatalog() {
    const F = this._catFilters, runs = this.catalog || [];
    const uniq = a => [...new Set(a)].filter(x => x !== undefined && x !== null && x !== "").sort();
    const opts = {
      source: [["", "All sources"], ["preset", "Preset"], ["custom", "Custom"]],
      engine: [["", "All engines"], ["python", "Python"], ["matlab", "MATLAB Simulink"]],
      outcome: [["", "All outcomes"], ["OK", "Correct operation"], ...["F-1", "F-2", "F-3", "F-4", "F-5", "NT"].map(c => [c, `${c} ${CODE_DESC[c]}`])],
      der: [["", "All DER types"], ["none", "No DER"], ...uniq(runs.flatMap(m => m.der.map(d => d.type))).map(t => [t, t])],
      ftype: [["", "All fault types"], ["none", "No fault"], ...uniq(runs.flatMap(m => m.faults.map(f => f.type))).map(t => [t, t])],
      relay: [["", "All relay classes"], ...uniq(runs.map(m => m.relay)).map(c => [c, c])],
      label: [["", "All labels"], ...uniq(runs.flatMap(m => m.labels || [])).map(l => [l, l])],
    };
    const host = $("#cat-filters");
    if (host.dataset.sig !== JSON.stringify(opts)) {
      host.innerHTML = Object.entries(opts).map(([k, o]) => `<select data-f="${k}" title="Filter">${o.map(([v, l]) => `<option value="${esc(v)}">${esc(l)}</option>`).join("")}</select>`).join("")
        + `<button class="lnk" id="cat-reset">Clear filters</button>`;
      host.dataset.sig = JSON.stringify(opts);
      host.querySelectorAll("select").forEach(s => { s.value = F[s.dataset.f] || ""; s.onchange = () => { F[s.dataset.f] = s.value; this.renderCatalog(); }; });
      $("#cat-reset").onclick = () => { for (const k of Object.keys(F)) F[k] = ""; $("#cat-q").value = ""; host.dataset.sig = ""; this.renderCatalog(); };
    }
    host.querySelectorAll("select").forEach(s => s.classList.toggle("set", !!F[s.dataset.f]));
    const q = F.q.trim().toLowerCase();
    const list = runs.filter(m => {
      if (F.source && m.source !== F.source) return false;
      if (F.engine && m.engine !== F.engine) return false;
      if (F.outcome && !this.outcomeOf(m).includes(F.outcome)) return false;
      if (F.der && (F.der === "none" ? m.der.length : !m.der.some(d => d.type === F.der))) return false;
      if (F.ftype && (F.ftype === "none" ? m.faults.length : !m.faults.some(f => f.type === F.ftype))) return false;
      if (F.relay && m.relay !== F.relay) return false;
      if (F.label && !(m.labels || []).includes(F.label)) return false;
      if (q) {
        const hay = [m.run_id, String(m.run_no), m.notes, ...(m.labels || []), this.derText(m), m.load, this.faultText(m), m.relay, ...this.outcomeOf(m)].join(" ").toLowerCase();
        if (!q.split(/\s+/).every(w => hay.includes(w))) return false;
      }
      return true;
    });
    const cur = this.run ? this.run.id : null;
    const out = m => this.outcomeOf(m).map(c => c === "OK" ? `<span class="st ok">Correct operation</span>` : `<span class="st bad">${c}${m.counts[c] > 1 ? " (" + m.counts[c] + ")" : ""}</span>`).join(" ");
    const edit = (key, f, html, empty) => `<td class="ed" data-key="${key}" data-f="${f}"><span class="ed-v">${html || `<span class="none">${empty}</span>`}</span><button class="lnk ed-e" title="Edit">Edit</button></td>`;
    $("#cat-table tbody").innerHTML = list.map(m => `<tr data-key="${m.key}" class="${m.key === cur ? "cur" : ""}">
        <td class="rid">${esc(m.run_id)}</td>
        ${edit(m.key, "labels", (m.labels || []).map(esc).join(", "), "No label")}
        ${edit(m.key, "notes", esc(m.notes || ""), "No notes")}
        <td>${esc(this.derText(m))}<div class="meta">${esc(m.load || "")} load</div></td>
        <td>${esc(this.faultText(m))}</td>
        <td>${esc(m.relay)}${Object.keys(m.relay_overrides || {}).length ? " (mixed)" : ""}</td>
        <td>${out(m)}</td>
        <td>${m.engine === "matlab" ? "MATLAB" : "Python"}</td>
        <td class="dt">${esc(m.created)}</td></tr>`).join("")
      || `<tr><td colspan="9" class="empty">${runs.length ? "No stored run matches the search and filters." : "Loading stored runs"}</td></tr>`;
    $("#cat-count").textContent = runs.length ? `${list.length} of ${runs.length} runs` : "";
    $("#cat-table tbody").querySelectorAll("tr[data-key]").forEach(tr => tr.onclick = ev => {
      if (ev.target.closest(".ed")) return;
      this.openRun(tr.dataset.key);
    });
    $("#cat-table tbody").querySelectorAll(".ed-e").forEach(b => b.onclick = ev => { ev.stopPropagation(); this.editField(b.closest(".ed")); });
  }
  // Inline editing of labels (comma separated) or notes (free text); Enter saves, Esc cancels.
  editField(td) {
    const key = td.dataset.key, f = td.dataset.f, m = this.catalog.find(x => x.key === key);
    const val = f === "labels" ? (m.labels || []).join(", ") : m.notes || "";
    td.innerHTML = `<input class="ed-in" value="${esc(val).replace(/"/g, "&quot;")}" placeholder="${f === "labels" ? "Label, another label" : "Notes for this run"}"><div class="hint">Enter to save, Esc to cancel.${f === "labels" ? " Separate labels with commas." : ""}</div>`;
    const inp = td.querySelector("input"); inp.focus(); inp.select();
    inp.onkeydown = async ev => {
      ev.stopPropagation();
      if (ev.key === "Escape") { this.renderCatalog(); return; }
      if (ev.key !== "Enter") return;
      const body = { key };
      if (f === "labels") body.labels = inp.value.split(",").map(x => x.trim()).filter(Boolean);
      else body.notes = inp.value.trim();
      try {
        const j = await (await fetch("/api/labels", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })).json();
        if (j.error) throw new Error(j.error);
        m.labels = j.labels; m.notes = j.notes;
      } catch (e) { this.toast("The change could not be saved."); }
      this.renderCatalog(); this.renderRunSel();
    };
    inp.onblur = () => setTimeout(() => { if (td.isConnected && td.querySelector(".ed-in")) this.renderCatalog(); }, 150);
  }
  async openRun(key) {
    const m = this.catalog.find(x => x.key === key);
    if (!m) return;
    this.closeCatalog();
    if (m.source === "preset") {
      if (m.engine !== this.engine && (m.engine === "python" || this.init.matlab_available)) {
        this.engine = m.engine; $("#engine").value = m.engine;
      }
      await this.loadPreset(m.preset, true);
      return;
    }
    this.pause();
    const ck = "key:" + key;
    let j = this.runCache.get(ck);
    if (!j) {
      this.busy(true, "Loading the stored run");
      try {
        j = await (await fetch(`/api/result?key=${key}`)).json();
        if (j.error) throw new Error(j.error);
        this.runCache.set(ck, j);
      } catch (e) { this.busy(false); this.toast("The run could not be loaded: " + e.message); return; }
      this.busy(false);
    }
    this.presetId = null;
    this.scenario = clone(j.scenario); delete this.scenario._node;
    this.edited = true;
    this.engine = j.engine || "python"; $("#engine").value = this.engine;
    this.runCache.set(this.cacheKey(), j);
    this.setRun(j);
  }

  async loadPreset(id, run) {
    const p = this.init.presets.find(x => x.id === id);
    this.presetId = id;
    this.scenario = clone(p.scenario);
    this.scenario.name = p.name;
    this.edited = false;
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
    try {
      const body = Object.assign({}, this.scenario, { engine: this.engine });
      const r = this.edited
        ? await fetch("/api/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
        : await fetch(`/api/preset?id=${this.presetId}&engine=${this.engine}`);
      const j = await r.json();
      if (j.error) throw new Error(j.error);
      this.runCache.set(key, j);
      if (!this.edited && !ml) { this.ready[this.presetId] = true; }
      if (!(this.catalog || []).some(m => m.key === j.id)) await this.loadCatalog();
      this.setRun(j);
    } catch (e) {
      this.toast("Simulation failed: " + e.message);
    } finally {
      this.busy(false);
    }
  }

  setRun(run) {
    this.run = run;
    this.renderRunSel();
    this._kpiStatic = null;
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
    const pri = hf && hf.primary ? hf.primary : "A1";
    const rows = [[`ied:${pri}:I`, "inst"], [`ied:${pri}:V`, "inst"]];
    if (run.faults.length) rows.push([`fault:F1:I`, "inst"]);
    if (run.der.length) rows.push([`der:${run.der[0].id}:I`, "inst"]);
    this.scope.setRun(run, rows);
    // SOE filter
    const f = $("#soe-filter"); f.innerHTML = `<option value="">All IEDs</option>` + run.ied.map(d => `<option>${d.id}</option>`).join("");
    this.tiles.build(run);
    this.relayChart.setRun(run);
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
    this.render(false);
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

  // full = false during playback: panels whose data frame has not changed are left as they are.
  render(full = true) {
    const r = this.run; if (!r) return;
    const t = this.t;
    const scan = Number($("#scan-rate").value);
    const tOp = scan > 0.011 ? Math.floor(t / scan) * scan : t;
    const k = this.frameAt(tOp), kG = this.frameAt(t);
    this.kOp = k; this.kG = kG;
    const fkey = `${r.id}|${k}|${kG}`, changed = full || fkey !== this._fkey;
    this._fkey = fkey;
    const iedState = changed ? this.iedStateAt(tOp) : this._iedState;
    this._iedState = iedState;
    if (changed) this.sld.update({ run: r, k, kGod: kG, t, iedState, iedClass: this.iedClass });
    // waktu
    $("#pl-t").textContent = t.toFixed(3);
    $("#pl-cyc").textContent = `Cycle ${Math.floor(t * r.f0)}`;
    const pct = t / r.T * 100;
    $("#pl-fill").style.width = pct + "%"; $("#pl-head").style.left = pct + "%";
    if (changed) {
      this.renderKPI(k);
      this.tiles.update(r, k, iedState, !full && this.playing);
      this.relayChart.draw();
      this.renderSOE(t);
      this.phasor.draw();
      if (this.insp) this.renderInspector();
    }
    const now = performance.now();
    if (full || now - (this._scopeAt || 0) > 32) { this._scopeAt = now; this.scope.drawAll(); }
  }

  renderKPI(k) {
    const r = this.run;
    // Scenario parameters are fixed for a run; only the frequency changes during playback.
    if (!this._kpiStatic) {
      const sc = r.scenario || {};
      // one variable per field; every DER and every fault gets its own fields
      const LOAD_PCT = { min_siang: 40, menengah: 70, puncak_malam: 100 };
      const ld = sc.load || {};
      const loadPct = typeof ld.level === "number" ? ld.level * 100 : LOAD_PCT[ld.level] ?? 100;   // same rule as the engine
      const f = [];
      const ders = (sc.der && sc.der.units) || [];
      if (!ders.length) f.push(["DER", "None", ""]);
      ders.forEach((d, i) => {
        const n = ders.length > 1 ? `DER${i + 1} ` : "DER ";
        f.push([n + "type", d.type, ""], [n + "loc", d.bus, ""], [n + "size", fmt(d.kva, 0), "kVA"]);
      });
      f.push(["Load", loadPct != null ? fmt(loadPct, 0) : "N/A", "% peak"]);
      f.push(["Grid", sc.grid && sc.grid.mode === "island" ? "Islanded" : "Connected", ""]);
      const faults = sc.faults || [];
      if (!faults.length) f.push(["Fault", "None", ""]);
      faults.forEach((x, i) => {
        const n = faults.length > 1 ? `Fault${i + 1} ` : "Fault ";
        f.push([n + "type", `${x.type}${x.type === "3PH" ? "" : "-" + String(x.phases || "").toUpperCase()}`, ""], [n + "loc", x.bus || x.line, ""],
          [n + "Rf", fmt(x.rf ?? 0, 1), "Ω"], [n + "time", fmt(x.t_on, 2), "s"]);
      });
      const rel = sc.relays || {};
      f.push(["Relay class", (rel.default || "OCR") + (Object.keys(rel.classes || {}).length ? " (mixed)" : ""), ""]);
      this._kpiStatic = f.map(([l, v, u]) => `<div class="k t"><div class="l">${l}</div><div class="v">${esc(v)}${u ? `<small>${u}</small>` : ""}</div></div>`).join("");
      $("#kpi").innerHTML = `<div class="k"><div class="l">Frequency</div><div class="v" id="kpi-f"></div></div>` + this._kpiStatic;
    }
    $("#kpi-f").innerHTML = `${fmt(r.freq[k], 3)}<small>Hz</small>`;
  }
  brForIED(id) {
    const m = this.run.topology.ieds.find(x => x.id === id);
    const br = this.run.topology.branches.find(b => b.from === m.from && b.to === m.to);
    return br ? br.id : null;
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
    tb.innerHTML = rows.map(e => `<tr class="k-${e.kind}${e.t > t ? " future" : ""}"><td>${clock(e.t)}</td><td><span class="iedtag">${e.id}</span></td><td><span class="evc" title="${EV[kindOf(e, "relay")].label}">${EV[kindOf(e, "relay")].svg}</span>${esc(e.text.replace(e.id + " ", ""))}</td></tr>`).join("")
      || `<tr><td colspan="3" class="empty">No IED records up to t = ${t.toFixed(3)} s</td></tr>`;
  }

  renderMarks() {
    const r = this.run, host = $("#pl-marks"); host.innerHTML = "";
    const evs = [
      ...r.events_sim.map(e => ({ t: e.t, k: kindOf(e, "sim"), text: e.text })),
      ...r.events_relay.map(e => ({ t: e.t, k: kindOf(e, "relay"), text: e.text })),
    ].sort((a, b) => a.t - b.t);
    const W = Math.max(host.clientWidth || $("#pl-track").clientWidth || 600, 100), gap = 16;
    const groups = [];
    for (const e of evs) {
      const x = e.t / r.T * W, g = groups[groups.length - 1];
      if (g && x - g.x0 < gap) g.items.push(e); else groups.push({ x0: x, items: [e] });
    }
    for (const g of groups) {
      const top = g.items.reduce((a, b) => EV[b.k].pri > EV[a.k].pri ? b : a);
      const d = document.createElement("div");
      d.className = "pl-ev"; d.style.left = (g.items[0].t / r.T * 100) + "%";
      d.innerHTML = EV[top.k].svg + (g.items.length > 1 ? `<span class="pl-n">${g.items.length}</span>` : "");
      d.dataset.tip = g.items.slice(0, 14).map(e => `${e.t.toFixed(3)} s  ${EV[e.k].label}: ${e.text}`).join("\n") + (g.items.length > 14 ? `\n${g.items.length - 14} more` : "");
      d.onclick = ev => { ev.stopPropagation(); this.pause(); this.seek(g.items[0].t); };
      d.onmouseenter = () => { const tip = $("#pl-evtip"); tip.textContent = d.dataset.tip; tip.style.display = "block"; tip.style.left = d.style.left; };
      d.onmouseleave = () => { $("#pl-evtip").style.display = "none"; };
      host.appendChild(d);
    }
  }

  // ---- output waveform and phasor panels
  q(sel) { return $(sel); }
  onScopeChange() { this.updateAddBtn(); this.phasor.refresh(); }
  updateAddBtn() { const b = $("#btn-addrow"); if (b) { b.disabled = !this.scope.canAdd(); b.title = b.disabled ? "Two channels fit in the main window. Open the panel in a separate window for more." : "Add a channel"; } }
  isDetached(id) { return !!this.detached[id]; }
  redrawPanels() { this.scope.drawAll(); this.phasor._k = null; this.phasor.draw(); }

  // Panel sizes: the waveform and phasor row height, the phasor width and the alarms width.
  _layout() {
    const grid = $("#grid");
    const L = { bh: 300, pw: 460, rw: 380 };
    try { Object.assign(L, JSON.parse(localStorage.getItem("sr34-layout") || "{}")); } catch (e) { /* storage unavailable */ }
    const apply = () => { grid.style.setProperty("--bh", L.bh + "px"); grid.style.setProperty("--pw", L.pw + "px"); grid.style.setProperty("--rw", L.rw + "px"); };
    const save = () => { try { localStorage.setItem("sr34-layout", JSON.stringify(L)); } catch (e) { /* storage unavailable */ } };
    apply();
    const drag = (id, onMove) => $(id).addEventListener("mousedown", ev => {
      ev.preventDefault();
      const start = { x: ev.clientX, y: ev.clientY, ...L };
      document.body.classList.add("resizing");
      const mv = e => { onMove(e.clientX - start.x, e.clientY - start.y, start); apply(); this.redrawPanels(); };
      const up = () => { window.removeEventListener("mousemove", mv); window.removeEventListener("mouseup", up); document.body.classList.remove("resizing"); save(); this.redrawPanels(); };
      window.addEventListener("mousemove", mv); window.addEventListener("mouseup", up);
    });
    const H = () => grid.clientHeight, W = () => grid.clientWidth;
    drag("#split-h", (dx, dy, s0) => { L.bh = Math.min(Math.max(s0.bh - dy, 140), H() - 220); });
    drag("#split-r", (dx, dy, s0) => { L.rw = Math.min(Math.max(s0.rw - dx, 260), W() - 520); });
    drag("#split-v", (dx, dy, s0) => { L.pw = Math.min(Math.max(s0.pw - dx, 300), $("#bottom").clientWidth - 320); });
  }

  // Explanations live behind the round "i" buttons and appear on hover or focus.
  infoHTML(key) {
    const sw = c => `<i class="tile-sw ${c}"></i>`;
    if (key === "alarm") return `<b>SCADA alarm states</b>${ANN_KEY.map(([c, code, t, bl]) => `<div class="ir">${sw(c)}<span><b>${code}</b> ${t}${bl ? ", blinking" : ""}</span></div>`).join("")}<div class="ir">${sw("")}<span>Normal</span></div><p>States follow the RTU scan rate. Click a tile to open its information panel.</p>`;
    if (key === "soe") return `<b>Sequence of events</b><p>Records downloaded from field IEDs, time-stamped by each IED. The operator receives them only after the event.</p>${["fault", "pickup", "dir", "trip", "cbopen", "cbclose", "dropout", "dertrip", "island", "cleared"].map(k => `<div class="ir">${EV[k].svg}<span>${EV[k].label}</span></div>`).join("")}`;
    if (key === "phasor") return `<b>Output phasor</b><p>Phasors of the channels shown in the output waveform, at the playback cursor. Angles are referred to ${this.phasor.refText || "phase A of the first channel"}. N is the phasor sum of A, B and C (3I0 or 3V0). Values are fundamental components; Inst is the instantaneous fundamental value.</p>`;
    if (key === "catalog") return `<b>Stored runs</b><p>Runs are numbered in the order they were produced. Labels and notes are saved on this computer; labels can also be used as a filter.</p>`;
    if (key === "chart") {
      const d = this.run && this.run.ied[this.iedIdx[this.relayChart.sel]];
      const cls = d ? d.cls : "OCR";
      if (cls === "DIST") return `<b>Mho distance characteristic</b><p>Impedance plane, primary ohms. Z1 solid, Z2 dashed and Z3 dotted circles; the dotted ray is the line angle. Red points are phase-ground loops (with k0 compensation), violet points are phase-phase loops, and the red trace is the closest loop over the last 150 ms. Points outside the plot are load impedances.</p>`;
      if (cls === "DIFF") return `<b>Line differential characteristic</b><p>Differential current against restraint current per phase. The relay operates above the line (pickup, then 30% slope).</p>`;
      return `<b>Time-current characteristic</b><p>Log-log plot of operating time against primary current. Solid curve: 51P of the selected relay; dashed curve: 51N; light curves: other relays of the same feeder, for coordination. The vertical marker is the measured current at the cursor and the point is its operating time (violet at pickup, red at trip).</p>`;
    }
    return "";
  }
  _infoTips(doc) {
    let tip = null;
    const show = el => {
      if (!tip) { tip = doc.createElement("div"); tip.className = "info-tip"; doc.body.appendChild(tip); }
      tip.innerHTML = this.infoHTML(el.dataset.info);
      tip.style.display = "block";
      const r = el.getBoundingClientRect(), vw = doc.defaultView.innerWidth, vh = doc.defaultView.innerHeight;
      const w = tip.offsetWidth, h = tip.offsetHeight;
      tip.style.left = Math.max(8, Math.min(r.left - 12, vw - w - 8)) + "px";
      tip.style.top = (r.bottom + 6 + h > vh ? Math.max(8, r.top - h - 6) : r.bottom + 6) + "px";
    };
    const hide = () => { if (tip) tip.style.display = "none"; };
    doc.addEventListener("mouseover", ev => { const el = ev.target.closest && ev.target.closest(".info"); if (el) show(el); });
    doc.addEventListener("mouseout", ev => { const el = ev.target.closest && ev.target.closest(".info"); if (el && !el.contains(ev.relatedTarget)) hide(); });
    doc.addEventListener("focusin", ev => { if (ev.target.classList && ev.target.classList.contains("info")) show(ev.target); });
    doc.addEventListener("focusout", ev => { if (ev.target.classList && ev.target.classList.contains("info")) hide(); });
  }

  // A panel moves into its own browser window and stays in sync; Attach or closing the window brings it back.
  detach(id) {
    if (this.detached[id]) return this.attach(id);
    const panel = $("#" + id), slot = panel.parentNode;
    const r = panel.getBoundingClientRect();
    const w = window.open("", "sr34-" + id, `width=${Math.round(Math.max(r.width, 640))},height=${Math.round(Math.max(r.height, 420))}`);
    if (!w) { this.toast("The browser blocked the new window. Allow pop-ups for this page and try again."); return; }
    const title = panel.querySelector(".ttl").textContent;
    const fonts = document.querySelector('link[href*="fonts.googleapis.com/css2"]');
    w.document.open();
    w.document.write(`<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>SimRelay 34: ${title}</title><link rel="icon" href="${location.origin}/img/logo-stei.png">${fonts ? `<link rel="stylesheet" href="${fonts.href}">` : ""}<link rel="stylesheet" href="${location.origin}/css/app.css"></head><body class="detached"></body></html>`);
    w.document.close();
    w.document.body.appendChild(w.document.importNode(document.querySelector("svg[aria-hidden]"), true));
    w.document.body.appendChild(w.document.adoptNode(panel));
    DOCS.push(w.document);
    this.detached[id] = { w, slot };
    this._detUI(id, true);
    w.addEventListener("pagehide", () => { if (this.detached[id]) this.attach(id, true); });
    w.addEventListener("resize", () => this.redrawPanels());
    w.addEventListener("keydown", ev => this._onKey(ev));
    this._infoTips(w.document);
    if (id === "p-wave") this.updateAddBtn();
    setTimeout(() => this.redrawPanels(), 60);
  }
  attach(id, closing) {
    const d = this.detached[id]; if (!d) return;
    const panel = d.w.document.getElementById(id);
    delete this.detached[id];
    const i = DOCS.indexOf(d.w.document); if (i > 0) DOCS.splice(i, 1);
    if (panel) d.slot.appendChild(document.adoptNode(panel));
    if (!closing) d.w.close();
    this._detUI(id, false);
    if (id === "p-wave") this.scope.trim();
    setTimeout(() => this.redrawPanels(), 30);
  }
  _detUI(id, on) {
    const b = $(`.det-btn[data-panel="${id}"]`);
    if (b) { b.innerHTML = `<svg class="ic"><use href="#i-${on ? "attach" : "detach"}"/></svg>`; b.title = on ? "Return to the main window" : "Open in a separate window"; }
    const g = $("#grid");
    g.classList.toggle("no-wave", this.isDetached("p-wave"));
    g.classList.toggle("no-phasor", this.isDetached("p-phasor"));
    g.classList.toggle("no-field", this.isDetached("p-field"));
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
    $("#run-sel").onclick = () => this.openCatalog();
    $("#cat-x").onclick = () => this.closeCatalog();
    $("#catalog").addEventListener("mousedown", ev => { if (ev.target.id === "catalog") this.closeCatalog(); });
    $("#cat-q").oninput = e => { this._catFilters.q = e.target.value; this.renderCatalog(); };
    $("#pl-play").onclick = () => this.playing ? this.pause() : this.play();
    $("#pl-start").onclick = () => this.seek(0);
    $("#pl-end").onclick = () => this.seek(this.run.T);
    $("#pl-back").onclick = () => this.seek(this.t - 1 / 60);
    $("#pl-fwd").onclick = () => this.seek(this.t + 1 / 60);
    $("#pl-speed").onchange = e => this.speed = Number(e.target.value);
    $("#btn-fit").onclick = () => this.sld.fit();
    for (const id of ["#scan-rate", "#soe-all", "#soe-filter"]) $(id).onchange = () => { this._soeKey = null; this.render(); };
    document.querySelectorAll("#rec-tabs .tab").forEach(b => b.onclick = () => {
      const panel = b.closest(".panel");
      panel.querySelectorAll("#rec-tabs .tab").forEach(x => x.classList.toggle("on", x === b));
      panel.querySelectorAll(".rec-host .tabpane").forEach(p => p.classList.toggle("on", p.id === "tab-" + b.dataset.tab));
    });
    document.querySelectorAll(".det-btn").forEach(b => b.onclick = () => this.detach(b.dataset.panel));
    this._layout();
    this._infoTips(document);
    window.addEventListener("beforeunload", () => { for (const d of Object.values(this.detached)) d.w.close(); });
    this._popovers();
    $("#scope-win").onchange = e => { this.scope.win = Number(e.target.value); this.scope.drawAll(); };
    $("#btn-addrow").onclick = () => this.scope.addRow("ied:A1:V", "inst");
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
    window.addEventListener("keydown", ev => this._onKey(ev));
    window.addEventListener("resize", () => { this.redrawPanels(); if (this.run) this.renderMarks(); });
  }
  _onKey(ev) {
    {
      if (ev.code === "Escape" && this._catOpen) { this.closeCatalog(); return; }
      if (ev.target.tagName === "INPUT" || ev.target.tagName === "SELECT" || this._catOpen) return;
      if (ev.code === "Space") { ev.preventDefault(); this.playing ? this.pause() : this.play(); }
      if (ev.code === "ArrowLeft") this.seek(this.t - (ev.shiftKey ? 0.1 : 1 / 60));
      if (ev.code === "ArrowRight") this.seek(this.t + (ev.shiftKey ? 0.1 : 1 / 60));
      if (ev.code === "Home") this.seek(0);
      if (ev.code === "End") this.seek(this.run.T);
      if (ev.code === "Escape") { if (this._catOpen) { this.closeCatalog(); return; } this.editor.close(); this.insp = null; $("#inspector").classList.add("hidden"); this._closePops(); }
    }
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
