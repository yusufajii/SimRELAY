function y = sr34_ctrl(u, cmd)
%SR34_CTRL SimRELAY controller, called by the Simulink model once per time step.
%   u = [tau; real(V); imag(V); real(Imeas); imag(Imeas)] with V and Imeas in peak phasors.
%   Runs, in this order (same order as the app's Python engine):
%     1. virtual IEDs (OCR 50/51, DOCR 67, Distance 21, Differential 87L) on the measured phasors,
%     2. DER controls and DER protection (IEEE 1547 ride-through, anti-islanding),
%     3. breaker logic (opening delay, direct transfer trip), scheduled events, islanding and faults,
%   and returns the breaker states and source phasors applied at the next step (Unit Delay).
%   sr34_ctrl([], 'reset') clears the state before a run; st = sr34_ctrl([], 'state') returns it.
%   The state is a persistent variable updated in place (no per-step copy of the run log).
global SR34 %#ok<GVMIS>
persistent st
if nargin > 1
    switch cmd
        case 'reset', st = [];
        case 'state', y = st;
    end
    if strcmp(cmd, 'reset'), y = []; end
    return
end
cfg = SR34;
if isempty(st), st = sr34_ctrl_state0(cfg); end
pk = sqrt(2);
N = cfg.N; M = cfg.n_meas;
tau = u(1);
V = (u(2:N + 1) + 1i * u(N + 2:2 * N + 1)) / pk;                 % RMS phasors
Im = (u(2 * N + 2:2 * N + M + 1) + 1i * u(2 * N + M + 2:2 * N + 2 * M + 1)) / pk;
dt = cfg.dt;
t = tau - cfg.t_init;                                             % app time (t < 0: initialisation)
init = t < -1e-9;
st.k = st.k + 1;
if mod(st.k, 48) == 0, sr34_progress(cfg, 'sim', tau, cfg.T + cfg.t_init); end
nI = numel(cfg.ieds); nD = numel(cfg.ders); nF = numel(cfg.faults);
trip_code = zeros(1, nI); dtt = zeros(1, nI);
any_fault = any(st.fault_on);

% ------------------------------------------------------------------ topology (islands)
key = sum(st.cb .* 2 .^ (0:nI - 1)) + 2 ^ nI * st.sub;
if key ~= st.topo_key
    [st.grid, st.comp] = islands(cfg, st);
    st.topo_key = key;
end

% ------------------------------------------------------------------ 1. IEDs
if ~init
    for j = 1:nI
        I = branch_I(cfg, Im, cfg.ieds{j}.meas);
        Vr = node_V(V, cfg.ieds{j}.vnodes);
        Ir = [];
        if cfg.ieds{j}.cls == 4 && cfg.ieds{j}.partner > 0
            Ir = branch_I(cfg, Im, cfg.ieds{cfg.ieds{j}.partner}.meas);
        end
        [st.relay(j), code] = ied_step(st.relay(j), cfg.ieds{j}, I, Vr, Ir, st, dt);
        if code > 0
            trip_code(j) = code;
            targets = j;
            if cfg.ieds{j}.cls == 4 && cfg.ieds{j}.partner > 0, targets = [j cfg.ieds{j}.partner]; end
            for q = targets
                if st.cb(q) && isinf(st.pend(q))
                    st.pend(q) = t + cfg.t_cb;
                    if q ~= j, dtt(q) = j; end
                end
            end
        end
    end
end

% ------------------------------------------------------------------ 2. DER
Pe = 0;
for j = 1:nD
    d = cfg.ders{j}; s = st.der(j);
    Vd = node_V(V, d.vnodes);
    Iout = -branch_I(cfg, Im, d.meas);                            % measured into the DER: negate
    if init
        s = der_init(d, s, Vd, st, cfg);
    else
        s = der_update(d, s, Vd, Iout, t, dt, any_fault, st);
        if s.online
            Pe = Pe + real(sum(Vd .* conj(Iout)));
            v1 = st.Ainv * Vd;
            unintentional = ~ismember(cfg.der_bus(j), st.grid) && cfg.mode_grid == 1;
            s = der_protection(d, s, abs(v1(2)) / d.vbase, unintentional, t, dt);
        end
    end
    s = der_command(d, s, Vd, t, st);
    s.Vprev = Vd;
    st.der(j) = s;
end
% island frequency (swing equation with 5 % droop), for display only
if st.sub || init
    st.freq = cfg.f0; st.Pm = NaN;
else
    Stot = 0; Hs = 0;
    for j = 1:nD
        if st.der(j).online && cfg.ders{j}.type ~= 2
            Stot = Stot + cfg.ders{j}.S; Hs = Hs + cfg.ders{j}.H * cfg.ders{j}.S;
        end
    end
    if Stot > 0
        Htot = Hs / Stot;
        if isnan(st.Pm), st.Pm = Pe; end
        Pm = min(max(st.Pm - Stot / 0.05 * (st.freq - cfg.f0) / cfg.f0, 0), Stot * 1.1);
        st.freq = min(max(st.freq + cfg.f0 / (2 * Htot * Stot) * (Pm - Pe) * dt, 55), 65);
    end
end

% ------------------------------------------------------------------ 3. events for the next step
tn = t + dt;
manual = 0; island = 0;
while st.ev_i <= numel(cfg.events) && cfg.events{st.ev_i}.t <= tn + 1e-9
    ev = cfg.events{st.ev_i};
    st.cb(ev.ied) = ev.type;
    manual = ev.ied * (2 * ev.type - 1);
    st.ev_i = st.ev_i + 1;
end
if cfg.sub.t_island >= 0 && tn >= cfg.sub.t_island && st.sub
    st.sub = 0; island = 1;
end
for q = 1:nI
    if tn >= st.pend(q) - 1e-9
        st.cb(q) = 0; st.pend(q) = inf;
    end
end
fclr = zeros(1, nF);
for f = 1:nF
    fl = cfg.faults{f};
    on = fl.t_on <= tn + 1e-9 && (isempty(fl.t_off) || tn < fl.t_off) && isinf(st.fault_clear(f));
    % a fault left without any source (isolated, no DER in its island) extinguishes
    if st.fault_on(f) && ~ismember(cfg.fault_bus(f), st.grid)
        fed = false;
        for j = 1:nD
            if st.der(j).online && same_island(st, cfg.der_bus(j), cfg.fault_bus(f)), fed = true; end
        end
        If = max(abs(Im(fl.mch(fl.mch > 0))));
        if isempty(If), If = 0; end
        if ~fed && If < 1.0
            st.fault_clear(f) = t; on = false; fclr(f) = 1;
        end
    end
    st.fault_on(f) = on;
end
% cold load pickup: extra current drawn by each load while the multiplier decays
if ~isempty(cfg.clpu) && isstruct(cfg.clpu)
    c = cfg.clpu; st.clpu_i = zeros(numel(c.loads), 1);
    if tn >= c.t0
        kf = 1 + (c.factor - 1) * exp(-(tn - c.t0) / c.tau);
        for q = 1:numel(c.loads)
            L = c.loads(q);
            va = node_V(V, L.a); vb = 0; if L.b > 0, vb = node_V(V, L.b); end
            st.clpu_i(q) = -(kf - 1) * (L.y(1) + 1i * L.y(2)) * (va - vb);
        end
    end
end

% ------------------------------------------------------------------ log and output
n = st.log.n + 1; st.log.n = n;
st.log.t(n) = t; st.log.cb(n, :) = st.cb; st.log.sub(n) = st.sub; st.log.trip(n, :) = trip_code;
st.log.dtt(n, :) = dtt; st.log.freq(n) = st.freq; st.log.manual(n) = manual; st.log.island(n) = island;
for j = 1:nD
    st.log.der_on(n, j) = st.der(j).online; st.log.der_reason(n, j) = st.der(j).reason;
    st.log.irr(n, j) = irradiance(cfg.ders{j}, max(t, 0));
end
for f = 1:nF, st.log.fault(n, f) = st.fault_on(f); st.log.fclear(n, f) = fclr(f); end
y = sr34_ctrl_outputs(cfg, st);
end

% =================================================================== helpers
function v = node_V(V, nodes)
v = zeros(3, 1);
for k = 1:numel(nodes)
    if nodes(k) > 0, v(k) = V(nodes(k)); end
end
v = v(1:numel(nodes));
end

function I = branch_I(~, Im, chans)
I = zeros(3, 1);
for k = 1:3
    if chans(k) > 0, I(k) = Im(chans(k)); end
end
end

function [grid, comp] = islands(cfg, st)
% bus connectivity with open protection breakers removed; comp(b) = island label
nb = cfg.n_bus; adj = cell(nb, 1);
for e = 1:numel(cfg.topo)
    tp = cfg.topo(e);
    if tp.ied > 0 && ~st.cb(tp.ied), continue; end
    adj{tp.f}(end + 1) = tp.t; adj{tp.t}(end + 1) = tp.f;
end
comp = zeros(1, nb); lab = 0;
for s = 1:nb
    if comp(s), continue; end
    lab = lab + 1; stack = s; comp(s) = lab;
    while ~isempty(stack)
        x = stack(end); stack(end) = [];
        for y = adj{x}
            if ~comp(y), comp(y) = lab; stack(end + 1) = y; end %#ok<AGROW>
        end
    end
end
if st.sub, grid = find(comp == comp(cfg.sub.bus)); else, grid = []; end
end

function ok = same_island(st, b1, b2)
ok = st.comp(b1) == st.comp(b2);
end

function g = irradiance(d, t)
irr = d.irr;
if isempty(irr), g = 1000; return; end
if size(irr, 2) ~= 2, irr = reshape(irr, [], 2); end
irr = sortrows(irr, 1);
if size(irr, 1) == 1, g = irr(1, 2); return; end
g = interp1(irr(:, 1), irr(:, 2), t, 'linear', 'extrap');
g = min(max(g, min(irr(:, 2))), max(irr(:, 2)));
end

function p = p_avail(d, t)
if d.pv, p = d.p_set * irradiance(d, t) / 1000; else, p = d.p_set; end
end

% ------------------------------------------------------------------ DER
function s = der_init(d, s, Vd, st, cfg)
v = st.Ainv * Vd; V1 = v(2);
if ~s.online, return; end
if cfg.sub.closed0 == 0 && d.type ~= 2
    s.E1 = 1.03 * d.vbase;                       % island at t = 0: grid-forming source is the swing
    return
end
S = complex(p_avail(d, 0), d.q_set) * d.S;
if abs(V1) > 1, I1 = conj(S / (3 * V1)); else, I1 = 0; end
if d.type == 2
    s.I1 = I1; s.I2 = 0;
else
    s.E1 = V1 + complex(d.z1(1), d.z1(2)) * I1;
end
end

function z = sg_z1(d, s, t)
if isnan(s.tf0), x = d.xdpp;
else
    tt = max(t - s.tf0, 0);
    x = d.xd + (d.xdp - d.xd) * exp(-tt / d.tdp) + (d.xdpp - d.xdp) * exp(-tt / d.tdpp);
end
z = complex(d.ra, x) * d.Zbase + complex(d.ztx(1), d.ztx(2));
end

function s = der_update(d, s, Vd, Iout, t, dt, any_fault, st)
if ~s.online, s.I1 = 0; s.I2 = 0; return; end
switch d.type
    case 1                                         % SG: subtransient -> transient -> synchronous
        if any_fault && isnan(s.tf0), s.tf0 = t; end
        if ~any_fault, s.tf0 = NaN; end
    case 2                                         % IBR grid-following
        [I1t, I2t, s] = gfl_target(d, s, Vd, t);
        kf = 1 - exp(-dt / d.tau);
        s.I1 = s.I1 + (I1t - s.I1) * kf;
        s.I2 = s.I2 + (I2t - s.I2) * kf;
        Iabc = st.A * [0; s.I1; s.I2];
        m = max(abs(Iabc)) / (d.imax * d.Ibase);
        if m > 1, s.I1 = s.I1 / m; s.I2 = s.I2 / m; end
    case 3                                         % IBR grid-forming with current limit
        if s.limited && ~any_fault, s.limited = false; end
        if ~s.limited
            m = max(abs(Iout)) / (d.imax * d.Ibase);
            if m > 1
                s.limited = true; s.Ilim = Iout / m;
            end
        end
end
end

function [I1, I2, s] = gfl_target(d, s, Vd, t)
v = (1 / 3) * [1 1 1; 1 exp(2i*pi/3) exp(-2i*pi/3); 1 exp(-2i*pi/3) exp(2i*pi/3)] * Vd;
V1 = v(2); V2 = v(3);
v1pu = abs(V1) / d.vbase;
if abs(V1) > 1e-3 * d.vbase, ang = angle(V1); else, ang = 0; end
if d.mc
    if v1pu < d.mc_v, s.ceased = true; elseif v1pu > d.mc_v + 0.05, s.ceased = false; end
end
if s.ceased, I1 = 0; I2 = 0; return; end
P = p_avail(d, t);
if v1pu >= 0.9
    ip = P / max(v1pu, 0.5); iq = -d.q_set / max(v1pu, 0.5);
elseif ~d.frt_q
    ip = min(P / max(v1pu, 0.05), d.imax); iq = 0;
else
    iqm = min(d.imax, d.kq * (0.9 - v1pu) + max(d.q_set, 0));
    ip = min(P / max(v1pu, 0.05), sqrt(max(d.imax ^ 2 - iqm ^ 2, 0)));
    iq = -iqm;
end
mag = hypot(ip, iq);
if mag > d.imax, ip = ip * d.imax / mag; iq = iq * d.imax / mag; end
I1 = complex(ip, iq) * d.Ibase * exp(1i * ang);
I2 = 0;
if d.neg_seq && v1pu < 0.9
    v2pu = abs(V2) / d.vbase;
    i2 = min(d.k2 * v2pu, max(d.imax - abs(complex(ip, iq)), 0));
    I2 = 1i * i2 * d.Ibase * exp(1i * angle(V2));
end
end

function s = der_command(d, s, Vd, t, st)
if ~s.online, s.Iinj = zeros(3, 1); s.Eeff = Vd; return; end
switch d.type
    case 1
        z1pp = complex(d.z1(1), d.z1(2));
        zt = sg_z1(d, s, max(t, 0));
        E = s.E1 * st.POS;
        s.Eeff = Vd + (E - Vd) * (z1pp / zt);     % same current as E behind the time-varying reactance
    case 2
        s.Iinj = st.A * [0; s.I1; s.I2];
    case 3
        if s.limited
            s.Eeff = Vd + complex(d.z1(1), d.z1(2)) * s.Ilim;
        else
            s.Eeff = s.E1 * st.POS;
        end
end
end

function s = der_protection(d, s, v1pu, unintentional, t, dt)
if d.trip_at >= 0 && t >= d.trip_at
    s.online = false; s.reason = 1; return
end
lv = {d.uv2, d.uv1}; nm = {'uv2', 'uv1'};
for q = 1:2
    lvl = lv{q}(1); tmax = lv{q}(2);
    if v1pu < lvl
        s.(nm{q}) = s.(nm{q}) + dt;
        if s.(nm{q}) >= tmax
            s.online = false; s.reason = 1 + q; s.vtrip = v1pu; return
        end
    else
        s.(nm{q}) = 0;
    end
end
if unintentional
    s.isl = s.isl + dt;
    if s.isl >= d.t_anti_island, s.online = false; s.reason = 4; end
else
    s.isl = 0;
end
end

% ------------------------------------------------------------------ IED (virtual relay)
function t = t_op(curve, tms, M)
K = [0.14 0.02 0; 13.5 1 0; 80 2 0; 0.0515 0.02 0.114; 19.61 2 0.491; 28.2 2 0.1217];
if M <= 1, t = inf; return; end
k = K(curve, 1); al = K(curve, 2); c = K(curve, 3);
if curve <= 3, t = tms * k / (M ^ al - 1); else, t = tms * (k / (M ^ al - 1) + c); end
end

function [buf, avg, n, p] = mavg(buf, x, n, p)
p = mod(p, size(buf, 1)) + 1;
buf(p, :) = x.';
n = min(n + 1, size(buf, 1));
idx = mod((p - n:p - 1), size(buf, 1)) + 1;
avg = mean(buf(idx, :), 1).';
end

function d = dir_phase(r, s, Iph, V, k)
j = mod(k, 3) + 1; l = mod(k + 1, 3) + 1;
Vpol = V(j) - V(l);
if abs(Vpol) < 0.05 * s.vbase * sqrt(3)
    if isempty(r.vmem), d = 0; return; end
    Vpol = r.vmem(j) - r.vmem(l);
end
if abs(Iph) < 1e-6, d = 0; return; end
c = cos(angle(Iph) - angle(Vpol) - deg2rad(s.mta));
if c > 0.05, d = 1; elseif c < -0.05, d = -1; else, d = 0; end
end

function d = dir_ground(s, I, V)
a = exp(2i*pi/3); Ai = (1 / 3) * [1 1 1; 1 a a^2; 1 a^2 a];
v = Ai * V; i = Ai * I; vb = s.vbase;
d = 0;
if abs(i(3)) >= s.i2min && abs(v(3)) >= 0.005 * vb
    z2 = real(v(3) * conj(i(3) * exp(1i * s.ang1))) / abs(i(3)) ^ 2;
    if z2 < -s.zthr, d = 1; return; end
    if z2 > s.zthr, d = -1; return; end
end
if abs(i(1)) >= s.i2min && abs(v(1)) >= 0.005 * vb
    z0 = real(v(1) * conj(i(1) * exp(1i * s.ang0))) / abs(i(1)) ^ 2;
    if z0 < -s.zthr, d = 1; return; end
    if z0 > s.zthr, d = -1; return; end
end
end

function [r, code] = ied_step(r, ied, Iraw, Vraw, Rraw, st, dt)
% Element codes: 1 51P, 2 50P, 3 51N, 4 50N, 5 67P, 6 67P inst, 7 67N, 8 67N inst,
%                9..11 21 zone 1..3, 12 87L
code = 0; s = ied.s;
Vraw3 = zeros(3, 1); Vraw3(1:numel(Vraw)) = Vraw;
[r.bufI, I, ~, ~] = mavg(r.bufI, Iraw, r.nbuf, r.pbuf);
[r.bufV, V, nb, pb] = mavg(r.bufV, Vraw3, r.nbuf, r.pbuf);
if ied.cls == 4 && ~isempty(Rraw)
    [r.bufR, Rf, ~, ~] = mavg(r.bufR, Rraw, r.nbuf, r.pbuf);
end
r.nbuf = nb; r.pbuf = pb;
ph = find(s.ph(:).' > 0);
if min(abs(V(ph))) > 0.8 * s.vbase, r.vmem = V; end
if r.tripped, return; end
switch ied.cls
    case {1, 2}
        dirl = ied.cls == 2;
        mags = abs(I); I3 = abs(sum(I));
        dP = [1 1 1]; dN = 1;
        if dirl
            dP = [dir_phase(r, s, I(1), V, 1) dir_phase(r, s, I(2), V, 2) dir_phase(r, s, I(3), V, 3)];
            dN = dir_ground(s, I, V);
        end
        for k = ph
            M = mags(k) / s.p51;
            en = ~dirl || dP(k) > 0;
            if M > 1 && en
                r.p51(k) = r.p51(k) + dt / t_op(s.curve, s.tp, M);
                if r.p51(k) >= 1, code = 1 + 4 * dirl; break; end
            else
                r.p51(k) = 0;
            end
            if s.p50 > 0 && mags(k) > s.p50 && en, code = 2 + 4 * dirl; break; end
        end
        if code == 0 && s.n51 > 0
            M = I3 / s.n51;
            en = ~dirl || dN > 0;
            if M > 1 && en
                r.p51n = r.p51n + dt / t_op(s.curve, s.tn, M);
                if r.p51n >= 1, code = 3 + 4 * dirl; end
            else
                r.p51n = 0;
            end
            if code == 0 && s.n50 > 0 && I3 > s.n50 && en, code = 4 + 4 * dirl; end
        end
    case 3
        k0 = complex(s.k0(1), s.k0(2)); I0x3 = sum(I);
        hit = false(1, 3);
        for k = ph
            den = I(k) + k0 * I0x3;
            if abs(den) > 1e-3 && abs(I(k)) > s.fd_ph && abs(I0x3) > s.fd_g
                hit = zone_hit(hit, V(k) / den, s);
            end
        end
        pr = [1 2; 2 3; 3 1];
        for q = 1:3
            p = pr(q, 1); qq = pr(q, 2);
            if any(ph == p) && any(ph == qq)
                den = I(p) - I(qq);
                if abs(den) > 1e-3 && abs(den) > s.fd_ph
                    hit = zone_hit(hit, (V(p) - V(qq)) / den, s);
                end
            end
        end
        for z = 1:3
            if hit(z) || any(hit(1:z - 1))
                r.zt(z) = r.zt(z) + dt;
                if r.zt(z) >= s.ztime(z) - 1e-9, code = 8 + z; break; end
            else
                r.zt(z) = 0;
            end
        end
    case 4
        if isempty(Rraw), Rf = zeros(3, 1); end
        nd = st.nd; r.nh = min(r.nh + 1, nd + 1);
        r.rh = [r.rh(2:end, :); Rf.']; r.lh = [r.lh(2:end, :); I.'];
        if r.nh > nd, Ir = r.rh(1, :).'; Il = r.lh(1, :).';
        else, Ir = r.rh(end - r.nh + 1, :).'; Il = r.lh(end - r.nh + 1, :).'; end
        Id = abs(Il - Ir); Irest = (abs(Il) + abs(Ir)) / 2;
        op = Id > max(s.d87, s.slope87 * Irest);
        if any(op(ph))
            r.dtim = r.dtim + dt;
            if r.dtim >= s.t87, code = 12; end
        else
            r.dtim = 0;
        end
end
if code > 0
    r.tripped = true; r.elem = code;
end
end

function hit = zone_hit(hit, Z, s)
if ~isfinite(Z), return; end
for z = 1:3
    Zr = s.zreach(z) * exp(1i * s.ang1);
    if abs(Z - Zr / 2) <= abs(Zr) / 2
        hit(z) = true; return
    end
end
end
