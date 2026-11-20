// Scenario editor: DoF 1 to DoF 4 and simulation timing
const h = (tag, attrs = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "on") for (const [ev, fn] of Object.entries(v)) e.addEventListener(ev, fn);
    else if (k === "cls") e.className = v;
    else if (k === "html") e.innerHTML = v;
    else if (v !== undefined && v !== null && v !== false) e.setAttribute(k, v === true ? "" : v);
  }
  for (const c of kids.flat()) if (c !== null && c !== undefined) e.append(c.nodeType ? c : document.createTextNode(c));
  return e;
};
const row = (label, ...ctl) => h("div", { cls: "frow" }, h("label", {}, label), h("div", {}, ...ctl));
const fmt = (v, d = 0) => Number(v).toFixed(d);
const plus = () => h("span", { style: "display:inline-flex", html: '<svg class="ic"><use href="#i-plus"/></svg>' });

function select(opts, val, onchange) {
  const s = h("select", { on: { change: e => onchange(e.target.value) } });
  for (const o of opts) { const [v, l] = Array.isArray(o) ? o : [o, o]; const op = h("option", { value: v }, l); if (String(v) === String(val)) op.selected = true; s.append(op); }
  return s;
}
function num(val, onchange, attrs = {}) {
  return h("input", { type: "number", value: val ?? "", step: attrs.step || "any", min: attrs.min, max: attrs.max, placeholder: attrs.ph,
    on: { change: e => onchange(e.target.value === "" ? null : Number(e.target.value)) } });
}
function slider(val, min, max, step, onchange, show) {
  const out = h("span", { cls: "val" }, show(val));
  const r = h("input", { type: "range", min, max, step, value: val, on: { input: e => { out.textContent = show(Number(e.target.value)); onchange(Number(e.target.value)); } } });
  return h("div", { cls: "inl" }, r, out);
}
function seg(opts, val, onchange) {
  const w = h("div", { cls: "seg" });
  for (const [v, l] of opts) {
    const b = h("button", { cls: String(v) === String(val) ? "on" : "", on: { click: () => { [...w.children].forEach(x => x.classList.remove("on")); b.classList.add("on"); onchange(v); } } }, l);
    w.append(b);
  }
  return w;
}
function check(val, label, onchange) {
  return h("label", { cls: "tg" }, h("input", { type: "checkbox", checked: !!val, on: { change: e => onchange(e.target.checked) } }), label);
}

export class Editor {
  constructor(app) {
    this.app = app;
    this.el = document.getElementById("drawer");
    this.body = document.getElementById("dr-body");
    this.tab = "dof1";
    document.getElementById("dr-close").onclick = () => this.close();
    document.getElementById("dr-run").onclick = () => { this.close(); app.edited = true; app.runScenario(); };
    document.getElementById("dr-reset").onclick = async () => { await app.loadPreset(app.presetId, false); this.app.edited = true; this.render(); };
    document.querySelectorAll("#dr-tabs button").forEach(b => b.onclick = () => {
      document.querySelectorAll("#dr-tabs button").forEach(x => x.classList.remove("on")); b.classList.add("on");
      this.tab = b.dataset.d; this.render();
    });
  }
  // Opening the editor marks the scenario as user-defined. The server still serves it
  // from cache when it is identical to a scenario that has already been simulated.
  open() { this.app.edited = true; this.el.classList.add("open"); this.render(); }
  close() { this.el.classList.remove("open"); }
  get sc() { return this.app.scenario; }

  render() {
    document.getElementById("dr-name").textContent = this.sc.name || "Custom scenario";
    this.body.innerHTML = "";
    this.body.append(this["r_" + this.tab]());
  }

  // DoF 1: distributed energy resources
  r_dof1() {
    const sc = this.sc, init = this.app.init;
    sc.der = sc.der || { units: [] };
    const units = sc.der.units;
    const base = this.app.baseLoadKW;
    const wrap = h("div");
    const tot = units.reduce((s, u) => s + (u.kva || 0), 0);
    wrap.append(h("div", { cls: "fs" },
      h("div", { cls: "fh" }, "Total DER Penetration"),
      h("div", { cls: "fhint" }, `Feeder A peak load is ${fmt(base)} kW. Penetration equals total DER kVA divided by peak load.`),
      row("Penetration", h("b", { style: "font-family:var(--mono)" }, `${fmt(tot)} kVA (${fmt(tot / base * 100)}%)`)),
      row("Scale all units", seg([[0, "0%"], [0.5, "0.5x"], [2, "2x"]], null, v => { units.forEach(u => u.kva = Math.round((u.kva || 0) * v)); this.render(); }))));
    units.forEach((u, i) => {
      const isIBR = u.type !== "SG";
      const fs = h("div", { cls: "fs" },
        h("div", { cls: "fh" }, `${u.id || "DER" + (i + 1)}: ${u.type}`, h("span", { cls: "rm", on: { click: () => { units.splice(i, 1); this.render(); } } }, "Remove")),
        row("Bus location", select(init.der_buses, u.bus, v => { u.bus = v; })),
        row("Technology", seg([["IBR-GFL", "Grid-following inverter"], ["IBR-GFM", "Grid-forming inverter"], ["SG", "Synchronous generator"]], u.type, v => { u.type = v; this.render(); })),
        row("Capacity", slider(u.kva || 0, 0, Math.round(base * 1.5), 10, v => { u.kva = v; }, v => `${fmt(v)} kVA (${fmt(v / base * 100)}%)`)),
        row("Active power setpoint", slider(u.p_pu ?? 1, 0, 1, 0.05, v => { u.p_pu = v; }, v => `${fmt(v * 100)}%`)),
        row("Interconnection transformer", select([["YgD", "Yg (network) and Delta (DER), zero-sequence source"], ["DYg", "Delta (network) and Yg, no zero sequence"]], u.xfmr || "YgD", v => { u.xfmr = v; })),
        row("IEEE 1547 ride-through", select([["III", "Category III (UV2 0.5 pu, 2 s)"], ["II", "Category II (0.45 pu, 0.16 s)"], ["I", "Category I"]], u.rt_cat || "III", v => { u.rt_cat = v; })),
        row("DER trip at t (s)", num(u.trip_at, v => { u.trip_at = v; }, { ph: "Leave empty for no trip", min: 0 })),
      );
      if (isIBR && u.type === "IBR-GFL") {
        fs.append(
          row("FRT mode", seg([["Q", "Q priority (IEEE 2800)"], ["P", "P priority"]], u.frt || "Q", v => { u.frt = v; })),
          row("Current limit", slider(u.imax ?? 1.2, 1.0, 2.0, 0.05, v => { u.imax = v; }, v => `${fmt(v, 2)} pu`)),
          row("Options", h("div", { cls: "inl" },
            check(u.neg_seq, "Negative-sequence injection (IEEE 2800)", v => { u.neg_seq = v; }),
            check(u.momentary_cessation, "Momentary cessation below 0.5 pu", v => { u.momentary_cessation = v; }))),
        );
      }
      if (isIBR) {
        const ir = u.irr_ui || { kind: "const", g0: 1000, gmin: 250, ts: 1.0, ramp: 0.3, dur: 1.0 };
        u.irr_ui = ir;
        const apply = () => { u.irradiance = irrProfile(ir); };
        fs.append(row("Irradiance profile", seg([["const", "Constant"], ["cloud", "Passing cloud"], ["drop", "Sudden drop"]], ir.kind, v => { ir.kind = v; apply(); this.render(); })));
        fs.append(row("Initial irradiance (W/m²)", num(ir.g0, v => { ir.g0 = v; apply(); }, { min: 0, max: 1200 })));
        if (ir.kind !== "const") {
          fs.append(row("Minimum irradiance (W/m²)", num(ir.gmin, v => { ir.gmin = v; apply(); }, { min: 0, max: 1200 })),
            row("Drop starts at t (s)", num(ir.ts, v => { ir.ts = v; apply(); }, { min: 0 })),
            row("Ramp duration (s)", num(ir.ramp, v => { ir.ramp = v; apply(); }, { min: 0.01 })));
          if (ir.kind === "cloud") fs.append(row("Shading duration (s)", num(ir.dur, v => { ir.dur = v; apply(); }, { min: 0 })));
        }
        apply();
      }
      wrap.append(fs);
    });
    wrap.append(h("button", { cls: "addbtn", on: { click: () => {
      units.push({ id: `DER${units.length + 1}`, bus: "848", type: "IBR-GFL", kva: Math.round(base * 0.5), xfmr: "YgD", frt: "Q", p_pu: 1 });
      this.render();
    } } }, plus(), "Add DER Unit"));
    return wrap;
  }

  // DoF 2: load and grid
  r_dof2() {
    const sc = this.sc;
    sc.load = sc.load || { level: "puncak_malam" };
    sc.grid = sc.grid || { mode: "grid" };
    const L = sc.load, G = sc.grid;
    L.phase_scale = L.phase_scale || [1, 1, 1];
    G.caps = G.caps || { C844: true, C848: true };
    G.reg_taps = G.reg_taps || { REG1: [12, 5, 5], REG2: [13, 11, 12] };
    G.substation = G.substation || {};
    const w = h("div");
    const lvl = typeof L.level === "number" ? "custom" : L.level;
    w.append(h("div", { cls: "fs" }, h("div", { cls: "fh" }, "Load Level"),
      row("Condition", seg([["min_siang", "Daytime minimum 40%"], ["menengah", "Intermediate 70%"], ["puncak_malam", "Evening peak 100%"], ["custom", "Custom"]], lvl, v => { L.level = v === "custom" ? 0.85 : v; this.render(); })),
      typeof L.level === "number" ? row("Custom level", slider(L.level, 0.1, 1.5, 0.05, v => { L.level = v; }, v => `${fmt(v * 100)}%`)) : null,
      h("div", { cls: "fhint" }, "Phase unbalance (load multiplier per phase):"),
      ...[0, 1, 2].map(k => row(`Phase ${"ABC"[k]}`, slider(L.phase_scale[k], 0.3, 1.7, 0.05, v => { L.phase_scale[k] = v; }, v => `${fmt(v, 2)}x`)))));
    const cl = L.clpu || { enable: false, factor: 2.5, tau: 2.0, t_energize: 0.3, feeders: ["A"] };
    L.clpu = cl;
    const syncCL = () => {
      sc.events = (sc.events || []).filter(e => !e._clpu);
      G.cb_init = G.cb_init || {};
      if (cl.enable) { G.cb_init.A1 = false; sc.events.push({ t: cl.t_energize, type: "CB_CLOSE", id: "A1", _clpu: true }); }
      else delete G.cb_init.A1;
    };
    w.append(h("div", { cls: "fs" }, h("div", { cls: "fh" }, "Cold Load Pickup (CLPU)"),
      h("div", { cls: "fhint" }, "CB-A starts open after an outage and closes at the energization time. Load briefly rises by the surge factor and then decays."),
      row("Enabled", check(cl.enable, "Simulate Feeder A energization", v => { cl.enable = v; syncCL(); })),
      row("Surge factor", slider(cl.factor, 1, 4, 0.1, v => { cl.factor = v; }, v => `${fmt(v, 1)}x`)),
      row("Decay time constant", slider(cl.tau, 0.2, 10, 0.1, v => { cl.tau = v; }, v => `${fmt(v, 1)} s`)),
      row("Energization time (s)", num(cl.t_energize, v => { cl.t_energize = v; syncCL(); }, { min: 0 }))));
    w.append(h("div", { cls: "fs" }, h("div", { cls: "fh" }, "Operating Mode and Source"),
      row("Mode", seg([["grid", "Grid-connected"], ["island", "Islanded microgrid"]], G.mode || "grid", v => { G.mode = v; if (v === "island" && G.t_island == null) G.t_island = 0; if (v === "grid") G.t_island = null; this.render(); })),
      (G.mode === "island") ? row("Substation breaker opens at t (s)", num(G.t_island ?? 0, v => { G.t_island = v; }, { min: 0 })) : null,
      (G.mode === "island") ? h("div", { cls: "fhint" }, "Islanded mode requires at least one grid-forming source (IBR-GFM or SG). A time of 0 starts the simulation already islanded.") : null,
      row("Substation transformer (kVA)", num(G.substation.kva ?? 2500, v => { G.substation.kva = v; }, { min: 500 })),
      row("Source voltage (pu)", num(G.substation.v_pu ?? 1.075, v => { G.substation.v_pu = v; }, { step: 0.005 }))));
    w.append(h("div", { cls: "fs" }, h("div", { cls: "fh" }, "Capacitors and Regulators"),
      row("Capacitors", h("div", { cls: "inl" }, check(G.caps.C844, "C844 (300 kvar)", v => { G.caps.C844 = v; }), check(G.caps.C848, "C848 (450 kvar)", v => { G.caps.C848 = v; }))),
      ...["REG1", "REG2"].map(r => row(`${r} tap (A, B, C)`, h("div", { cls: "inl" }, ...[0, 1, 2].map(k => num(G.reg_taps[r][k], v => { G.reg_taps[r][k] = v; }, { min: -16, max: 16, step: 1 }))))),
      h("div", { cls: "fhint" }, "Tap range is 16 steps in either direction at 0.625% per step. IEEE 34 defaults: REG1 12/5/5, REG2 13/11/12.")));
    return w;
  }

  // DoF 3: faults
  r_dof3() {
    const sc = this.sc, init = this.app.init;
    sc.faults = sc.faults || [];
    const w = h("div");
    sc.faults.forEach((f, i) => {
      const mode = f.line ? "line" : "bus";
      const phOpts = f.type === "SLG" ? [["a", "A-G"], ["b", "B-G"], ["c", "C-G"]] : f.type === "3PH" ? [["abc", "ABC"]] : [["ab", "AB"], ["bc", "BC"], ["ca", "CA"]];
      if (!phOpts.some(o => o[0] === f.phases)) f.phases = phOpts[0][0];
      const fs = h("div", { cls: "fs" },
        h("div", { cls: "fh" }, `Fault F${i + 1}`, h("span", { cls: "rm", on: { click: () => { sc.faults.splice(i, 1); this.render(); } } }, "Remove")),
        row("Location", seg([["bus", "At a bus"], ["line", "Along a line"]], mode, v => { if (v === "line") { delete f.bus; f.line = init.fault_lines[0]; f.frac = 0.5; } else { delete f.line; delete f.frac; f.bus = "834"; } this.render(); })),
        mode === "bus" ? row("Bus", select(init.fault_buses, f.bus, v => { f.bus = v; })) :
          h("div", {}, row("Line", select(init.fault_lines, f.line, v => { f.line = v; })),
            row("Position from sending end", slider(f.frac ?? 0.5, 0.01, 0.99, 0.01, v => { f.frac = v; }, v => `${fmt(v * 100)}%`))),
        row("Fault type", seg([["SLG", "SLG"], ["LL", "LL"], ["DLG", "DLG"], ["3PH", "Three-phase"]], f.type, v => { f.type = v; this.render(); })),
        row("Phases", select(phOpts, f.phases, v => { f.phases = v; })),
        row("Fault resistance Rf", slider(f.rf ?? 0, 0, 100, 0.5, v => { f.rf = v; }, v => `${fmt(v, 1)} Ω`)),
        row("Inception time (s)", num(f.t_on, v => { f.t_on = v ?? 0.5; }, { min: 0 })),
        row("Self-clearing time (s)", num(f.t_off, v => { f.t_off = v; }, { ph: "Leave empty for a permanent fault", min: 0 })));
      w.append(fs);
    });
    w.append(h("div", { cls: "fhint" }, "Note: a single-phase fault on a single-phase lateral automatically uses the available phase."));
    w.append(h("button", { cls: "addbtn", on: { click: () => { sc.faults.push({ bus: "834", type: "SLG", phases: "a", rf: 0, t_on: 0.5 }); this.render(); } } }, plus(), "Add Fault"));
    return w;
  }

  // DoF 4: relays
  r_dof4() {
    const sc = this.sc, init = this.app.init;
    sc.relays = sc.relays || { default: "OCR", classes: {} };
    sc.relays.classes = sc.relays.classes || {};
    const R = sc.relays;
    const opts = Object.entries(init.classes);
    const na = v => v ?? "N/A";
    const w = h("div");
    w.append(h("div", { cls: "fs" }, h("div", { cls: "fh" }, "Relay Hierarchy (Modular Virtual IED)"),
      h("div", { cls: "fhint" }, "Change the relay class at the same protection point. Settings are computed once at the baseline (0% DER, peak load) and then frozen."),
      row("Apply to all IEDs", seg([["OCR", "OCR"], ["DOCR", "DOCR"], ["DIST", "21"], ["DIFF", "87L"]], R.default, v => { R.default = v; R.classes = {}; this.render(); })),
      ...init.topology.ieds.map(m => row(`${m.id}: ${m.name.split("(")[0].trim()}`, select(opts, R.classes[m.id] || R.default, v => { R.classes[m.id] = v; }))),
      h("div", { cls: "fhint" }, "87L requires a downstream partner (A1 with A2, A2 with A3). IEDs without a partner fall back to 21 automatically.")));
    const S = init.settings;
    const t = h("table", { cls: "stbl" });
    t.innerHTML = `<tr><th>IED</th><th>51P (A)</th><th>TMS</th><th>50P (A)</th><th>51N (A)</th><th>TMS</th><th>50N (A)</th><th>Z1/Z2/Z3 (Ω)</th><th>87L (A)</th></tr>` +
      Object.entries(S).map(([k, s]) => `<tr><td>${k}</td><td>${s["51P_pu"]}</td><td>${s["51P_tms"]}</td><td>${na(s["50P_pu"])}</td><td>${na(s["51N_pu"])}</td><td>${s["51N_pu"] ? s["51N_tms"] : "N/A"}</td><td>${na(s["50N_pu"])}</td><td>${s.zreach.map(z => z.toFixed(1)).join("/")}</td><td>${na(s["87_pu"])}</td></tr>`).join("");
    w.append(h("div", { cls: "fs" }, h("div", { cls: "fh" }, "Frozen Baseline Settings (IEC Standard Inverse, design CTI 0.3 s)"), t,
      h("div", { cls: "fhint", style: "margin-top:6px" }, "67: quadrature polarization with 45° MTA and memory. 67N: 32Q with 32V fallback. 21: mho, Z1 80% (instantaneous), Z2 120% (0.3 s), Z3 (0.8 s). 87L: 30% slope, 5 ms channel.")));
    return w;
  }

  r_sim() {
    const sc = this.sc;
    sc.sim = sc.sim || {};
    const S = sc.sim;
    return h("div", {}, h("div", { cls: "fs" }, h("div", { cls: "fh" }, "Simulation Timing"),
      row("Duration (s)", slider(S.duration ?? 3, 0.5, 8, 0.1, v => { S.duration = v; }, v => `${fmt(v, 1)} s`)),
      row("Breaker opening time", slider((S.t_cb ?? 0.05) * 1000, 20, 150, 5, v => { S.t_cb = v / 1000; }, v => `${fmt(v)} ms`)),
      row("Engine time step", h("span", { style: "font-family:var(--mono)" }, "dt = 1/960 s (16 steps per cycle, one-cycle DFT filter)")),
      row("Save log", check(S.save !== false, "runs/<id>/result.json and data.npz (plus .mat when SciPy is available)", v => { S.save = v; })),
      row("Scenario name", h("input", { type: "text", value: sc.name || "", on: { change: e => { sc.name = e.target.value; } } }))));
  }
}

export function irrProfile(ir) {
  if (ir.kind === "const") return [[0, ir.g0]];
  if (ir.kind === "drop") return [[0, ir.g0], [ir.ts, ir.g0], [ir.ts + ir.ramp, ir.gmin]];
  return [[0, ir.g0], [ir.ts, ir.g0], [ir.ts + ir.ramp, ir.gmin], [ir.ts + ir.ramp + ir.dur, ir.gmin], [ir.ts + 2 * ir.ramp + ir.dur, ir.g0]];
}
