function st = sr34_ctrl_state0(cfg)
%SR34_CTRL_STATE0 Initial state of the SimRELAY controller (relays, DER, breakers, events, log).
a = exp(2i*pi/3);
st.A = [1 1 1; 1 a^2 a; 1 a a^2];          % abc = A * [0;1;2]
st.Ainv = inv(st.A);
st.POS = [1; a^2; a];
st.k = 0;
st.ncyc = max(round(1 / (cfg.f0 * cfg.dt)), 1);
st.nd = max(round(0.005 / cfg.dt), 1);
nsteps = round((cfg.T + cfg.t_init) / cfg.dt) + 3;
nI = numel(cfg.ieds); nD = numel(cfg.ders); nF = numel(cfg.faults);

% breakers and substation
st.cb = ones(1, nI); st.pend = inf(1, nI);
for j = 1:nI, st.cb(j) = cfg.ieds{j}.cb_init; end
st.sub = cfg.sub.closed0;
st.ev_i = 1;
st.fault_on = false(1, nF); st.fault_clear = inf(1, nF);
st.topo_key = -1; st.grid = []; st.comp = [];

% relays
for j = 1:nI
    r.bufI = zeros(st.ncyc, 3); r.bufV = zeros(st.ncyc, 3); r.bufR = zeros(st.ncyc, 3); r.nbuf = 0; r.pbuf = 0;
    r.p51 = zeros(1, 3); r.p51n = 0; r.pick = false(1, 8); r.zt = zeros(1, 3); r.dtim = 0;
    r.vmem = []; r.tripped = false; r.ttrip = NaN; r.elem = 0;
    r.rh = zeros(st.nd + 1, 3); r.lh = zeros(st.nd + 1, 3); r.nh = 0;
    st.relay(j) = r; %#ok<AGROW>
end

% DER
st.der = struct([]);
for j = 1:nD
    d = cfg.ders{j};
    s.online = logical(d.online); s.E1 = d.vbase; s.I1 = 0; s.I2 = 0; s.limited = false; s.Ilim = zeros(3, 1);
    s.tf0 = NaN; s.uv1 = 0; s.uv2 = 0; s.isl = 0; s.ceased = false; s.reason = 0; s.vtrip = NaN;
    s.Eeff = d.vbase * st.POS; s.Iinj = zeros(3, 1); s.Vprev = d.vbase * st.POS; s.Iprev = zeros(3, 1);
    if isempty(st.der), st.der = s; else, st.der(j) = s; end
end
st.freq = cfg.f0; st.Pm = NaN;

% log (one row per step)
st.log.t = zeros(nsteps, 1);
st.log.cb = zeros(nsteps, nI); st.log.sub = zeros(nsteps, 1);
st.log.trip = zeros(nsteps, nI);          % element code at the trip step
st.log.der_on = zeros(nsteps, max(nD, 1)); st.log.irr = zeros(nsteps, max(nD, 1));
st.log.der_reason = zeros(nsteps, max(nD, 1));
st.log.fault = zeros(nsteps, max(nF, 1)); st.log.fclear = zeros(nsteps, max(nF, 1));
st.log.freq = zeros(nsteps, 1);
st.log.manual = zeros(nsteps, 1); st.log.island = zeros(nsteps, 1);
st.log.dtt = zeros(nsteps, nI);
st.log.n = 0;
end
