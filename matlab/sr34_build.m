function info = sr34_build(cfg, mdl)
%SR34_BUILD Build a Simscape Electrical (Specialized Power Systems) phasor model from a netlist.
%   info = sr34_build(cfg, mdl) creates the Simulink model MDL from the configuration produced by
%   the SimRelay app (engine/matlab_bridge.py). The model contains only the power network,
%   measurements, breakers and controlled sources; all relay, DER and event logic runs in the
%   controller block (sr34_ctrl.m) that closes the loop each time step.
%
%   Diagram: the top level follows the single-line diagram of the web app. Every bus is a black
%   busbar subsystem at its SLD position (it holds the bus voltage measurements). Every line,
%   regulator and transformer is a subsystem between its two buses (with the breaker and current
%   transformers of a protection point), and loads, capacitors, DER, faults and the substation
%   source are subsystems attached to their bus. Measurement and command signals travel through
%   global Goto/From tags to the "Measurements and control" subsystem: V<n> bus node voltages,
%   I<ch> measured currents, B<ch> breaker commands, U<ch> and J<ch> source commands.
%   The grouping changes only the drawing; the electrical circuit is the same netlist.
%
%   Node convention: 0 = ground, 1..cfg.N = bus node-phases, above that = internal nodes.

if bdIsLoaded(mdl), close_system(mdl, 0); end
new_system(mdl);
load_system('spspowerguiLib'); load_system('spsGroundLib');
libs = {'spsMutualInductanceLib','spsSeriesRLCBranchLib','spsLinearTransformerLib','spsBreakerLib', ...
        'spsVoltageMeasurementLib','spsCurrentMeasurementLib','spsControlledCurrentSourceLib','spsControlledVoltageSourceLib'};
for i = 1:numel(libs), load_system(libs{i}); end
load_system('simulink');

dt = cfg.dt; T = cfg.T + cfg.t_init; w = 2*pi*cfg.f0;
set_param(mdl, 'SolverType','Fixed-step', 'Solver','FixedStepDiscrete', 'FixedStep', num2str(dt, 17), ...
    'StopTime', num2str(T, 17), 'SaveOutput','off', 'SaveTime','off', 'SignalLogging','off', ...
    'ReturnWorkspaceOutputs','on', 'AlgebraicLoopMsg','error');
add_block('spspowerguiLib/powergui', [mdl '/powergui'], 'SimulationMode','Phasor', 'frequency', num2str(cfg.f0), 'Position',[20 20 90 60]);

N = cfg.N;
G = cfg.groups; nG = numel(G);
els = cfg.elements;
P = sr34_paths(cfg, mdl);
PHN = 'abc';

% ---------------------------------------------------------------- bus of every bus node
busOf = zeros(1, N); phOf = zeros(1, N);
for bi = 1:cfg.n_bus
    for p = 1:3
        n = cfg.bus_nodes(bi, p);
        if n > 0, busOf(n) = bi; phOf(n) = p; end
    end
end
if any(busOf == 0), error('sr34_build:nodes', 'Some bus nodes belong to no bus.'); end

% ---------------------------------------------------------------- members and ports of every group
mem = cell(1, nG); gL = cell(1, nG); gR = cell(1, nG);
for k = 1:numel(els)
    e = els{k};
    mem{e.g}(end + 1) = k;
    nd = [e.a(:); e.b(:)]';
    for n = nd(nd >= 1 & nd <= N)
        b = cfg.bus_ids{busOf(n)};
        if strcmp(b, G{e.g}.left)
            gL{e.g}(end + 1) = n;
        elseif strcmp(b, G{e.g}.right)
            gR{e.g}(end + 1) = n;
        else
            error('sr34_build:group', 'Element %d of group %s touches bus %s.', k, G{e.g}.name, b);
        end
    end
end
byPhase = @(v) sortby(unique(v), phOf);

% ---------------------------------------------------------------- busbar ports and bus tree
% Every bus is a busbar with one port per phase on each side it needs: the left side for the
% group that feeds it, the right side for everything it supplies (lines, loads, DER, faults).
% Several groups on the same busbar port branch outside the busbar, like taps on a busbar.
nb = cfg.n_bus;
bidx = containers.Map(cfg.bus_ids, num2cell(1:nb));
busL = cell(1, nb); busR = cell(1, nb);
upg = zeros(1, nb); par = zeros(1, nb);
for g = 1:nG
    if ~isempty(G{g}.right)
        bi = bidx(G{g}.right); busL{bi} = [busL{bi} gR{g}];
        if ~isempty(G{g}.left), upg(bi) = g; par(bi) = bidx(G{g}.left); end
    end
    if ~isempty(G{g}.left)
        bi = bidx(G{g}.left); busR{bi} = [busR{bi} gL{g}];
    end
end
for bi = 1:nb, busL{bi} = byPhase(busL{bi}); busR{bi} = byPhase(busR{bi}); end

% ---------------------------------------------------------------- layout
% Rows and order come from the web single-line diagram. A branch on the same row as its parent
% bus is drawn as a straight run (busbar ports, branch block and next busbar aligned port to
% port). A lateral sits on its own row with its branch block just left of the child busbar.
% Loads, capacitors, DER and faults hang below their busbar, facing down.
PS = 20; BW = 8;   % PS: port pitch, a multiple of 5 px because Simulink snaps port spacing
 GW = 64; GAP = 150; SX = 3; SY = 2.4;
SH0 = 56;                              % first load/DER block starts this far right of its busbar (clear of the phase columns)
shuntw = @(g) PS * max(numel(unique(gL{g})), 1) + 8 + ceil(6.5 * numel(G{g}.name)) + 8;   % block plus its name on the right
xy = cfg.bus_xy;
X = zeros(1, nb); Yt = zeros(1, nb); H = zeros(1, nb);
for bi = 1:nb, H(bi) = PS * max([numel(busL{bi}), numel(busR{bi}), 1]); end
gpos = zeros(nG, 4); grot = false(1, nG);
gkind = zeros(1, nG);                  % 1 straight run, 2 lateral up, 3 lateral down, 4 shunt, 0 source
SHW = zeros(1, nb);                    % width taken below each busbar by its loads, DER, faults
for g = 1:nG
    if ~isempty(G{g}.left) && isempty(G{g}.right)
        bi = bidx(G{g}.left);
        SHW(bi) = SHW(bi) + shuntw(g) + 20;
    end
end
order = find(par == 0); q = 1;
while q <= numel(order)
    order = [order find(par == order(q))]; %#ok<AGROW>
    q = q + 1;
end
occ = zeros(0, 4);                     % rectangles already taken (blocks with their names)
for bi = order
    if par(bi) == 0
        X(bi) = xy(bi, 1) * SX; Yt(bi) = xy(bi, 2) * SY - H(bi) / 2;
        occ = [occ; footprint(bi, 0)]; %#ok<AGROW>
        continue
    end
    p = par(bi); g = upg(bi);
    X(bi) = max(xy(bi, 1) * SX, X(p) + max(GAP, SH0 + SHW(p) + 30));
    Lg = byPhase(gL{g}); Rg = byPhase(gR{g});
    hg = PS * max(numel(Lg), numel(Rg));
    same = abs(xy(bi, 2) - xy(p, 2)) < 1;
    for tries = 1:400
        if same
            gt = pY(p, busR{p}, Lg(1)) - PS / 2;
            Yt(bi) = gt + PS / 2 - (find(busL{bi} == Rg(1), 1) - 0.5) * H(bi) / numel(busL{bi});
            gx = (X(p) + X(bi)) / 2;
            gkind(g) = 1;
        else
            Yt(bi) = xy(bi, 2) * SY - H(bi) / 2;
            gt = pY(bi, busL{bi}, Rg(1)) - PS / 2;
            gx = X(bi) - BW / 2 - 34 - GW / 2;
            gkind(g) = 2 + (xy(bi, 2) > xy(p, 2));
        end
        gpos(g, :) = [gx - GW / 2, gt, gx + GW / 2, gt + hg];
        fp = footprint(bi, g);
        if ~any(overlaps(fp, occ)), break; end
        X(bi) = X(bi) + 20;               % blocked by a block of another row: move this bus right
    end
    occ = [occ; fp]; %#ok<AGROW>
end
nsh = zeros(1, nb); shx = zeros(1, nb);
for g = 1:nG
    if isempty(G{g}.left) && ~isempty(G{g}.right)            % substation source, left of its bus
        bi = bidx(G{g}.right); Rg = byPhase(gR{g});
        gt = pY(bi, busL{bi}, Rg(1)) - PS / 2;
        gx = X(bi) - BW / 2 - 50 - GW / 2;
        gpos(g, :) = [gx - GW / 2, gt, gx + GW / 2, gt + PS * numel(Rg)];
    elseif ~isempty(G{g}.left) && isempty(G{g}.right)        % shunt group, below its bus, facing down
        bi = bidx(G{g}.left); Lg = byPhase(gL{g});
        wd = PS * max(numel(Lg), 1) + 8;
        if nsh(bi) == 0, shx(bi) = X(bi) + SH0; end
        gpos(g, :) = [shx(bi), Yt(bi) + H(bi) + 34, shx(bi) + wd, Yt(bi) + H(bi) + 34 + 40];
        shx(bi) = shx(bi) + shuntw(g) + 20; nsh(bi) = nsh(bi) + 1;
        grot(g) = true; gkind(g) = 4;
    end
end
bx = [X - BW / 2, gpos(:, 1)']; by = [Yt, gpos(:, 2)'];
dx = 120 - min(bx); dy = 110 - min(by);
X = round(X + dx); Yt = round(Yt + dy);
gpos = round(gpos + [dx dy dx dy]);
ymax = max([Yt + H, gpos(:, 4)']);

% ---------------------------------------------------------------- busbars
% Inside a busbar: one row per phase, left port, voltage measurement (to tag V<n>), right port.
portLh = zeros(1, N); portRh = zeros(1, N);
sys = ''; anchor = {}; isport = []; nblk = 0; cur = []; nside = 0;
for bi = 1:nb
    nodes = cfg.bus_nodes(bi, :); nodes = byPhase(nodes(nodes > 0));
    sp = [mdl '/Bus ' cfg.bus_ids{bi}];
    bh = add_block('built-in/Subsystem', sp, 'Position', [X(bi) - BW / 2, Yt(bi), X(bi) + BW / 2, Yt(bi) + H(bi)], ...
        'BackgroundColor', 'black', 'ShowPortLabels', 'none', 'NamePlacement', 'alternate');
    sys = sp; anchor = cell(1, max(cfg.n_nodes, N)); isport = false(1, max(cfg.n_nodes, N)); nblk = 0;
    for n = nodes
        yc = 60 + (phOf(n) - 1) * 110;
        cur = [200, yc - 20, 240, yc + 20]; nside = 0;
        h = add_block('spsVoltageMeasurementLib/Voltage Measurement', sprintf('%s/Vm%d', sp, n), ...
            'OutputType', 'Complex', 'Position', cur);
        p = get_param(h, 'PortHandles');
        connect(p.LConn(1), n); connect(p.LConn(2), 0);
        t = add_block('simulink/Signal Routing/Goto', sprintf('%s/V%d', sp, n), 'GotoTag', sprintf('V%d', n), ...
            'TagVisibility', 'global', 'Position', [300, yc - 10, 350, yc + 10]);
        tp = get_param(t, 'PortHandles');
        add_line(sp, p.Outport(1), tp.Inport(1), 'autorouting', 'on');
        if any(busL{bi} == n)
            h = add_block('built-in/PMIOPort', sprintf('%s/in_%s', sp, PHN(phOf(n))), 'Side', 'Left', 'Position', [40, yc - 7, 70, yc + 7]);
            connect(cport(h), n);
        end
        if any(busR{bi} == n)
            h = add_block('built-in/PMIOPort', sprintf('%s/out_%s', sp, PHN(phOf(n))), 'Side', 'Right', 'Position', [430, yc - 7, 460, yc + 7]);
            connect(cport(h), n);
        end
    end
    % Simulink grows a subsystem while ports are added: restore the planned size so the port
    % pitch matches the composites (port order follows the order of creation, phase order)
    set_param(bh, 'Position', [X(bi) - BW / 2, Yt(bi), X(bi) + BW / 2, Yt(bi) + H(bi)]);
    ph = get_param(bh, 'PortHandles');
    for j = 1:numel(busL{bi}), portLh(busL{bi}(j)) = ph.LConn(j); end
    for j = 1:numel(busR{bi}), portRh(busR{bi}(j)) = ph.RConn(j); end
    if iscell(cfg.nodes), vb = cfg.nodes{nodes(1)}.vbase; else, vb = cfg.nodes(nodes(1)).vbase; end
    kv = sqrt(3) * vb / 1e3;
    set_param(bh, 'Mask', 'on', 'MaskType', 'SimRelay 34 Busbar', 'MaskIconOpaque', 'transparent', ...
        'MaskDescription', sprintf(['Bus %s, phases %s, %.2f kV nominal (line to line).\n' ...
        'Holds the voltage measurement of every phase (Goto tags %s), read by the Measurements and control block.'], ...
        cfg.bus_ids{bi}, PHN(phOf(nodes)), kv, strjoin(arrayfun(@(n) sprintf('V%d', n), nodes, 'UniformOutput', false), ', ')));
end

% ---------------------------------------------------------------- composites (lines, loads, DER, ...)
for g = 1:nG
    L = byPhase(gL{g}); R = byPhase(gR{g});
    sp = [mdl '/' G{g}.name];
    gh = add_block('built-in/Subsystem', sp, 'Position', gpos(g, :));
    sys = sp; anchor = cell(1, max(cfg.n_nodes, N)); isport = false(1, max(cfg.n_nodes, N)); nblk = 0;
    [EP, rowY, xR, ord] = glayout(g);
    for n = L
        y = rowY(phOf(n));
        h = add_block('built-in/PMIOPort', sprintf('%s/%s%s', sp, cfg.bus_ids{busOf(n)}, PHN(phOf(n))), 'Side', 'Left', 'Position', [20, y - 7, 50, y + 7]);
        anchor{n} = cport(h); isport(n) = true;
    end
    for n = R
        y = rowY(phOf(n));
        h = add_block('built-in/PMIOPort', sprintf('%s/%s%s', sp, cfg.bus_ids{busOf(n)}, PHN(phOf(n))), 'Side', 'Right', 'Position', [xR, y - 7, xR + 30, y + 7]);
        anchor{n} = cport(h); isport(n) = true;
    end
    for k = ord
        cur = EP(k, :); nside = 0;
        add_element(k);
    end
    composite_mask(gh, G{g});
    if grot(g)
        set_param(gh, 'Orientation', 'down', 'Position', gpos(g, :));
    else
        set_param(gh, 'NamePlacement', 'alternate', 'Position', gpos(g, :));   % name above; planned size restored
    end
    ph = get_param(gh, 'PortHandles');
    % the composite port is new, so it goes first; the busbar port may already carry other taps
    for j = 1:numel(L)
        lh = add_line(mdl, ph.LConn(j), portRh(L(j)), 'autorouting', 'off');
        route(lh, ph.LConn(j), portRh(L(j)), gkind(g), phOf(L(j)), bidx(G{g}.left));
    end
    for j = 1:numel(R), add_line(mdl, ph.RConn(j), portLh(R(j)), 'autorouting', 'off'); end
end

% ---------------------------------------------------------------- title block with the logo
scen = 'custom scenario';
if isfield(cfg, 'name') && ~isempty(cfg.name), scen = char(string(cfg.name)); end
logo = fullfile(fileparts(fileparts(mfilename('fullpath'))), 'web', 'img', 'logo-stei.png');
tb = add_block('built-in/Subsystem', [mdl '/SimRelay 34'], 'Position', [110 14 470 74], 'ShowName', 'off');
set_param(tb, 'Mask', 'on', 'MaskType', 'SimRelay 34', 'MaskIconUnits', 'normalized', 'MaskIconOpaque', 'opaque', ...
    'MaskInitialization', sprintf('try, logo = imread(''%s''); catch, logo = uint8(255 * ones(8, 8, 3)); end', logo), ...
    'MaskDisplay', strjoin({ ...
        'image(logo, [0.01 0.06 0.13 0.88]);', ...
        'patch([0.16 0.26 0.26 0.16], [0.12 0.12 0.88 0.88], [0.15 0.39 0.92]);', ...
        'patch([0.225 0.185 0.212 0.195 0.24 0.212], [0.80 0.47 0.47 0.20 0.55 0.55], [1 1 1]);', ...
        'text(0.30, 0.62, ''\bf\fontsize{15}SimRelay 34'', ''texmode'', ''on'');', ...
        'text(0.30, 0.25, ''\fontsize{9}IEEE 34 SIL test bench, Simscape Electrical phasor model'', ''texmode'', ''on'');'}, newline), ...
    'MaskDescription', sprintf(['SimRelay 34: Software-in-the-Loop proof-of-urgency test bench on the IEEE 34 Node Test Feeder.\n' ...
        'Built by the SimRelay app from the scenario "%s". Every composite block contains standard Simscape Electrical ' ...
        '(Specialized Power Systems) blocks; double-click a block to see its parameters and Look Under Mask to see its circuit.'], ...
        scen));

% ---------------------------------------------------------------- measurements and controller
cs = [mdl '/Measurements and control'];
add_block('built-in/Subsystem', cs, 'Position', [40 ymax + 120 420 ymax + 200]);
sig = @(name, lib, pos, varargin) add_block(lib, [cs '/' name], 'Position', pos, varargin{:});
muxV = sig('MuxV', 'simulink/Signal Routing/Mux', [200 20 205 20 + 12 * N], 'Inputs', num2str(N));
mp = get_param(muxV, 'PortHandles');
for i = 1:N
    f = sig(sprintf('fV%d', i), 'simulink/Signal Routing/From', [100 12 * i 150 12 * i + 10], 'GotoTag', sprintf('V%d', i));
    fp = get_param(f, 'PortHandles'); add_line(cs, fp.Outport(1), mp.Inport(i));
end
nI = max(cfg.n_meas, 1);
yI = 60 + 12 * N;
muxI = sig('MuxI', 'simulink/Signal Routing/Mux', [200 yI 205 yI + 12 * nI], 'Inputs', num2str(nI));
mp = get_param(muxI, 'PortHandles');
for i = 1:cfg.n_meas
    f = sig(sprintf('fI%d', i), 'simulink/Signal Routing/From', [100 yI + 12 * (i - 1) 150 yI + 12 * (i - 1) + 10], 'GotoTag', sprintf('I%d', i));
    fp = get_param(f, 'PortHandles'); add_line(cs, fp.Outport(1), mp.Inport(i));
end
yb = 40;
sig('LogV', 'simulink/Sinks/To Workspace', [330 yb 400 yb + 30], 'VariableName','simV', 'SaveFormat','Array', 'SampleTime', num2str(dt, 17));
sig('LogI', 'simulink/Sinks/To Workspace', [330 yb + 60 400 yb + 90], 'VariableName','simI', 'SaveFormat','Array', 'SampleTime', num2str(dt, 17));
add_line(cs, 'MuxV/1', 'LogV/1'); add_line(cs, 'MuxI/1', 'LogI/1');
sig('ReImV', sprintf('simulink/Math\nOperations/Complex to\nReal-Imag'), [330 yb + 130 360 yb + 170]);
sig('ReImI', sprintf('simulink/Math\nOperations/Complex to\nReal-Imag'), [330 yb + 190 360 yb + 230]);
add_line(cs, 'MuxV/1', 'ReImV/1'); add_line(cs, 'MuxI/1', 'ReImI/1');
sig('Clock', 'simulink/Sources/Digital Clock', [330 yb + 260 370 yb + 290], 'SampleTime', num2str(dt, 17));
sig('MuxU', 'simulink/Signal Routing/Mux', [430 yb + 120 435 yb + 300], 'Inputs', '5');
add_line(cs, 'Clock/1', 'MuxU/1'); add_line(cs, 'ReImV/1', 'MuxU/2'); add_line(cs, 'ReImV/2', 'MuxU/3');
add_line(cs, 'ReImI/1', 'MuxU/4'); add_line(cs, 'ReImI/2', 'MuxU/5');
nout = cfg.n_brk + 2 * cfg.n_v + 2 * cfg.n_i;
sig('Controller', sprintf('simulink/User-Defined\nFunctions/Interpreted MATLAB\nFunction'), [480 yb + 180 600 yb + 240], ...
    'MATLABFcn', 'sr34_ctrl(u)', 'OutputDimensions', num2str(nout), 'SampleTime', num2str(dt, 17));
add_line(cs, 'MuxU/1', 'Controller/1');
sig('Delay', 'simulink/Discrete/Unit Delay', [640 yb + 190 680 yb + 230], 'SampleTime', num2str(dt, 17), ...
    'InitialCondition', 'sr34_ctrl_init()');
add_line(cs, 'Controller/1', 'Delay/1');
dmx = sig('Demux', 'simulink/Signal Routing/Demux', [720 yb 725 yb + 14 * nout], 'Outputs', num2str(nout));
add_line(cs, 'Delay/1', 'Demux/1');
dp = get_param(dmx, 'PortHandles');
for i = 1:cfg.n_brk
    y = yb + 14 * (i - 1);
    t = sig(sprintf('gB%d', i), 'simulink/Signal Routing/Goto', [800 y 850 y + 10], 'GotoTag', sprintf('B%d', i), 'TagVisibility', 'global');
    tp = get_param(t, 'PortHandles'); add_line(cs, dp.Outport(i), tp.Inport(1));
end
off = cfg.n_brk;
for i = 1:cfg.n_v
    y = yb + 14 * off + 40 * (i - 1);
    c = sig(sprintf('CV%d', i), sprintf('simulink/Math\nOperations/Real-Imag to\nComplex'), [800 y 830 y + 30]);
    cp = get_param(c, 'PortHandles');
    add_line(cs, dp.Outport(off + i), cp.Inport(1));
    add_line(cs, dp.Outport(off + cfg.n_v + i), cp.Inport(2));
    t = sig(sprintf('gU%d', i), 'simulink/Signal Routing/Goto', [870 y + 10 920 y + 20], 'GotoTag', sprintf('U%d', i), 'TagVisibility', 'global');
    tp = get_param(t, 'PortHandles'); add_line(cs, cp.Outport(1), tp.Inport(1));
end
off2 = cfg.n_brk + 2 * cfg.n_v;
for i = 1:cfg.n_i
    y = yb + 14 * off + 40 * (cfg.n_v + i - 1);
    c = sig(sprintf('CI%d', i), sprintf('simulink/Math\nOperations/Real-Imag to\nComplex'), [800 y 830 y + 30]);
    cp = get_param(c, 'PortHandles');
    add_line(cs, dp.Outport(off2 + i), cp.Inport(1));
    add_line(cs, dp.Outport(off2 + cfg.n_i + i), cp.Inport(2));
    t = sig(sprintf('gJ%d', i), 'simulink/Signal Routing/Goto', [870 y + 10 920 y + 20], 'GotoTag', sprintf('J%d', i), 'TagVisibility', 'global');
    tp = get_param(t, 'PortHandles'); add_line(cs, cp.Outport(1), tp.Inport(1));
end
set_param(cs, 'Mask', 'on', 'MaskType', 'SimRelay 34 Measurements and control', 'BackgroundColor', 'white', ...
    'ForegroundColor', 'blue', 'MaskIconUnits', 'normalized', 'MaskIconOpaque', 'opaque', ...
    'MaskDisplay', ['text(0.5, 0.66, ''\bfMeasurements and control'', ''horizontalAlignment'', ''center'', ''texmode'', ''on''); ' ...
                    'text(0.5, 0.30, ''Virtual IEDs, DER control and scenario events'', ''horizontalAlignment'', ''center'');'], ...
    'MaskDescription', sprintf(['Collects every bus voltage (tags V<n>) and measured current (tags I<ch>), runs the controller ' ...
        'sr34_ctrl once per time step (virtual IEDs: 50/51, 67, 21, 87L; DER control and protection; breaker events) and ' ...
        'returns breaker commands (tags B<ch>) and source phasors (tags U<ch>, J<ch>) through a one-step delay.\n' ...
        'simV and simI log the measured phasors for the SimRelay app.']));
info = struct('groups', nG, 'nout', nout);

% ================================================================ helpers (share sys, anchor, nblk)
    function route(lh, gp, bp, kind, k, bi)
        % Orthogonal route from a group port GP to busbar port BP (phase K of bus BI). Each phase
        % has its own vertical column beside the busbar and its own horizontal row below it, ordered
        % so that different phases never overlap; equal phases of one bus share them (same node).
        if kind < 2, return; end            % straight runs need no bends
        s = get_param(gp, 'Position'); d = get_param(bp, 'Position');
        if kind == 2                        % lateral above: phase a column closest to the busbar
            xc = d(1) + 28 + 5 * k;
            pts = [s; xc s(2); xc d(2); d];
        elseif kind == 3                    % lateral below: phase a column farthest out
            xc = d(1) + 6 + 5 * (4 - k);
            pts = [s; xc s(2); xc d(2); d];
        else                                % load, DER, fault below the busbar
            xc = d(1) + 6 + 5 * (4 - k);
            yr = Yt(bi) + H(bi) + 6 + 5 * k;
            pts = [s; s(1) yr; xc yr; xc d(2); d];
        end
        try
            set_param(lh, 'Points', pts);
        catch
        end
    end
    function [EP, rowY, xR, ord] = glayout(g)
        % Layout inside composite G: one row per phase (a, b, c, then a neutral row), elements
        % left to right in the order the current passes through them (breaker, CT, impedance, ...).
        % EP(k, :) = [x, centre y of first row, centre y of last row] of element k.
        ks = mem{g}; nn = max(cfg.n_nodes, N);
        RH = 110; X0 = 110; CW = 150; SW = 74;
        rowY = 60 + (0:3) * RH;
        phn = zeros(1, nn); fixed = false(1, nn);
        bn = unique([gL{g} gR{g}]); phn(bn) = phOf(bn); fixed(bn) = true;
        prs = zeros(0, 3);                                    % [element, node u, node v]
        for kk = ks
            ee = els{kk}; A = ee.a(:)'; B = ee.b(:)';
            for jj = 1:numel(A), prs(end + 1, :) = [kk A(jj) B(jj)]; end %#ok<AGROW>
        end
        for it = 1:40                                         % phase of internal nodes
            chg = false;
            for i = 1:size(prs, 1)
                u = prs(i, 2); v = prs(i, 3);
                if u == 0 || v == 0, continue; end
                for uv = [u v; v u]'
                    a1 = uv(1); b1 = uv(2);
                    if phn(a1) >= 1 && phn(a1) <= 3 && ~fixed(b1)
                        if phn(b1) == 0, phn(b1) = phn(a1); chg = true;
                        elseif phn(b1) ~= phn(a1) && phn(b1) ~= 4, phn(b1) = 4; chg = true; end
                    end
                end
            end
            if ~chg, break; end
        end
        seeds = byPhase(gL{g}); mirror = isempty(seeds);
        if mirror, seeds = byPhase(gR{g}); end
        dep = inf(1, nn); dep(seeds) = 0;
        for it = 1:60                                         % hops from the entry ports
            chg = false;
            for i = 1:size(prs, 1)
                u = prs(i, 2); v = prs(i, 3);
                if u == 0 || v == 0, continue; end
                if dep(u) + 1 < dep(v), dep(v) = dep(u) + 1; chg = true; end
                if dep(v) + 1 < dep(u), dep(u) = dep(v) + 1; chg = true; end
            end
            if ~chg, break; end
        end
        ecol = zeros(1, numel(els)); er1 = ecol; er2 = ecol; eo = ecol; dl = false(1, numel(els));
        for kk = ks
            ee = els{kk}; nd = [ee.a(:); ee.b(:)]'; nd = nd(nd > 0);
            dd = dep(nd); dd = dd(isfinite(dd));
            if ~isempty(dd), ecol(kk) = min(dd); end
            A = ee.a(:)'; B = ee.b(:)'; rws = zeros(1, numel(A));
            for jj = 1:numel(A)
                cand = [A(jj) B(min(jj, numel(B)))]; cand = cand(cand > 0);
                pr = phn(cand); pr = pr(pr >= 1 & pr <= 3);
                if isempty(pr), rws(jj) = 4; else, rws(jj) = pr(1); end
            end
            er1(kk) = min(rws); er2(kk) = max(rws);
            if numel(A) == 1 && A(1) > 0 && B(1) > 0
                pa = phn(A(1)); pb = phn(B(1));
                if pa >= 1 && pa <= 3 && pb >= 1 && pb <= 3 && pa ~= pb      % delta branch
                    dl(kk) = true; er1(kk) = min(pa, pb); er2(kk) = max(pa, pb);
                    eo(kk) = 1 + (pa > pb);       % 1: terminal a on top (down), 2: terminal a below (up)
                end
            end
        end
        ks = [ks(dl(ks)) ks(~dl(ks))];
        ord = ks;
        if mirror, ecol(ks) = max(ecol(ks)) - ecol(ks); end
        used = zeros(max(ecol(ks)) + 1, 4); sl = zeros(1, numel(els));
        for kk = ks
            cc = ecol(kk) + 1; rr = er1(kk):er2(kk);
            s0 = max(used(cc, rr)); sl(kk) = s0; used(cc, rr) = s0 + 1;
        end
        wcol = max(max(used, [], 2)', 1);
        xs = X0 + [0 cumsum(wcol * SW + (CW - SW))];
        EP = zeros(numel(els), 4);
        for kk = ks
            EP(kk, :) = [xs(ecol(kk) + 1) + sl(kk) * SW, rowY(er1(kk)), rowY(er2(kk)), eo(kk)];
        end
        xR = xs(end) + 10;
    end
    function composite_mask(gh, grp)
        % Composite block: SLD symbol as its icon, parameters in its dialog, circuit under the mask.
        tok = regexp(grp.name, 'CB (\w+)', 'tokens', 'once');
        [dsp, fg, label] = icon(grp.kind, tok);
        inf_ = grp.info;
        if isempty(inf_), inf_ = {}; elseif ischar(inf_), inf_ = {inf_}; end
        set_param(gh, 'BackgroundColor', 'white', 'ForegroundColor', fg, 'Mask', 'on', ...
            'MaskType', ['SimRelay 34 ' label], ...
            'MaskDescription', strjoin([inf_(:)', {'Look Under Mask to see the circuit: standard Simscape Electrical (Specialized Power Systems) blocks, one row per phase.'}], newline), ...
            'MaskIconUnits', 'normalized', 'MaskIconOpaque', 'opaque', 'MaskIconRotate', 'none', ...
            'MaskInitialization', 't = linspace(0, 2*pi, 60);', 'MaskDisplay', dsp);
    end
    function r = footprint(bi, g)
        % rectangles taken by busbar BI (with its name above), the loads below it and branch block G
        r = [X(bi) - 32, Yt(bi) - 20, X(bi) + 32, Yt(bi) + H(bi) + 4];
        if SHW(bi) > 0
            r(end + 1, :) = [X(bi) + SH0 - 6, Yt(bi) + H(bi) + 28, X(bi) + SH0 + SHW(bi), Yt(bi) + H(bi) + 80];
        end
        if g > 0
            r(end + 1, :) = gpos(g, :) + [-6 -20 6 4];
        end
    end
    function y = pY(bi, list, n)
        % vertical centre of the busbar port of node N among the ports LIST of bus BI
        y = Yt(bi) + (find(list == n, 1) - 0.5) * H(bi) / numel(list);
    end
    function p = slot(col)
        nblk = nblk + 1;
        y = 30 + (nblk - 1) * 70;
        p = [col + 40, y, col + 90, y + 40];
    end
    function connect(ph, node)
        if node == 0
            if isempty(cur)
                gpz = slot(300);
            else
                gpz = [cur(1) + 6 + 26 * nside, cur(4) + 14, cur(1) + 26 + 26 * nside, cur(4) + 30];
                nside = nside + 1;
            end
            nblk = nblk + 1;
            gnd = add_block('spsGroundLib/Ground', sprintf('%s/G%d', sys, nblk), 'Position', gpz);
            gp = get_param(gnd, 'PortHandles');
            add_line(sys, ph, gp.LConn(1), 'autorouting', 'off');
        elseif isempty(anchor{node})
            anchor{node} = ph;
        elseif isport(node)
            % a Connection Port takes exactly one line: join it to this element terminal and let
            % the terminal (which may branch) carry the node from now on
            add_line(sys, ph, anchor{node}, 'autorouting', 'off');
            anchor{node} = ph; isport(node) = false;
        else
            add_line(sys, anchor{node}, ph, 'autorouting', 'off');
        end
    end
    function tag_out(h, tag)
        % measured signal of block H to a global Goto tag
        p = get_param(h, 'PortHandles');
        t = add_block('simulink/Signal Routing/Goto', [sys '/' tag], 'GotoTag', tag, 'TagVisibility', 'global', ...
            'Position', [cur(3) + 14, cur(2) - 32, cur(3) + 54, cur(2) - 16]);
        tp = get_param(t, 'PortHandles');
        add_line(sys, p.Outport(1), tp.Inport(1), 'autorouting', 'on');
    end
    function tag_in(h, tag, side)
        % command signal of block H from a global Goto tag (above the block, left or right)
        p = get_param(h, 'PortHandles');
        if nargin > 2 && strcmp(side, 'right')
            fpos = [cur(3) + 10, cur(2) - 32, cur(3) + 50, cur(2) - 16];
        else
            fpos = [cur(1) - 50, cur(2) - 32, cur(1) - 10, cur(2) - 16];
        end
        f = add_block('simulink/Signal Routing/From', [sys '/' tag], 'GotoTag', tag, 'Position', fpos);
        fp = get_param(f, 'PortHandles');
        add_line(sys, fp.Outport(1), p.Inport(1), 'autorouting', 'on');
    end
    function add_element(k)
        e = els{k};
        bp = P{k};
        orient = '';                       % cur = [x, first row centre, last row centre, delta] from glayout
        switch e.type
            case 'mutual', pos = [cur(1), cur(2) - 55, cur(1) + 50, cur(3) + 55];   % one winding per row
            case 'xf',     pos = [cur(1), cur(2) - 10, cur(1) + 46, cur(2) + 30];   % terminal 1 on the row
            case {'vsrc', 'isrc'}                                                   % terminals left and right
                orient = 'left'; pos = [cur(1), cur(2) - 23, cur(1) + 50, cur(2) + 13];   % + terminal (RConn) on the left, on the row
            otherwise
                if numel(cur) > 3 && cur(4) > 0                                     % delta branch, vertical
                    orient = 'down'; if cur(4) == 2, orient = 'up'; end
                    pos = [cur(1), cur(2), cur(1) + 30, cur(3)];
                else
                    pos = [cur(1), cur(2) - 16, cur(1) + 44, cur(2) + 16];
                end
        end
        cur = pos;
        switch e.type
            case 'imeas'
                h = add_block('spsCurrentMeasurementLib/Current Measurement', bp, 'OutputType','Complex', 'Position', pos);
                reorient(h, orient, pos); p = get_param(h, 'PortHandles');
                connect(p.LConn(1), e.a); connect(p.RConn(1), e.b);
                tag_out(h, sprintf('I%d', e.ch));
            case 'brk'
                h = add_block('spsBreakerLib/Breaker', bp, 'External','on', 'InitialState', num2str(e.init), ...
                    'BreakerResistance', num2str(e.ron, 17), 'SnubberResistance','1e6', 'SnubberCapacitance','inf', 'Position', pos);
                reorient(h, orient, pos); p = get_param(h, 'PortHandles');
                connect(p.LConn(1), e.a); connect(p.RConn(1), e.b);
                tag_in(h, sprintf('B%d', e.ch));
            case 'rl'
                if e.x == 0
                    h = add_block('spsSeriesRLCBranchLib/Series RLC Branch', bp, 'BranchType', 'R', ...
                        'Resistance', num2str(max(e.r, 1e-6), 17), 'Position', pos);
                elseif e.x > 0
                    if e.r > 0, bt = 'RL'; else, bt = 'L'; end
                    h = add_block('spsSeriesRLCBranchLib/Series RLC Branch', bp, 'BranchType', bt, ...
                        'Resistance', num2str(e.r, 17), 'Inductance', num2str(max(e.x, 1e-9) / w, 17), 'Position', pos);
                else
                    if e.r > 0, bt = 'RC'; else, bt = 'C'; end
                    h = add_block('spsSeriesRLCBranchLib/Series RLC Branch', bp, 'BranchType', bt, ...
                        'Resistance', num2str(e.r, 17), 'Capacitance', num2str(-1 / (w * e.x), 17), 'Position', pos);
                end
                reorient(h, orient, pos); p = get_param(h, 'PortHandles');
                connect(p.LConn(1), e.a); connect(p.RConn(1), e.b);
            case 'cap'
                h = add_block('spsSeriesRLCBranchLib/Series RLC Branch', bp, 'BranchType','C', 'Capacitance', num2str(e.c, 17), 'Position', pos);
                reorient(h, orient, pos); p = get_param(h, 'PortHandles');
                connect(p.LConn(1), e.a); connect(p.RConn(1), e.b);
            case 'mutual'
                n = numel(e.a);
                Rm = reshape(e.R, n, n); Lm = reshape(e.L, n, n);
                h = add_block('spsMutualInductanceLib/Mutual Inductance', bp, 'TypeOfMutual','Generalized mutual inductance', ...
                    'NumberOfWindings', num2str(n), 'ResistanceMatrix', mat2str(Rm, 17), 'InductanceMatrix', mat2str(Lm, 17), ...
                    'Position', pos);
                reorient(h, orient, pos); p = get_param(h, 'PortHandles');
                for j = 1:n
                    connect(p.LConn(j), e.a(j)); connect(p.RConn(j), e.b(j));
                end
            case 'xf'
                v1 = e.v1; v2 = e.v1 * e.ratio;
                h = add_block('spsLinearTransformerLib/Linear Transformer', bp, 'UNITS','pu', 'NominalPower','[1e6 60]', ...
                    'winding1', sprintf('[%.17g 1e-6 1e-6]', v1), 'winding2', sprintf('[%.17g 1e-6 1e-6]', v2), ...
                    'ThreeWindings','off', 'RmLm','[1e6 1e6]', 'Position', pos);
                reorient(h, orient, pos); p = get_param(h, 'PortHandles');
                connect(p.LConn(1), e.a); connect(p.LConn(2), 0);
                connect(p.RConn(1), e.b); connect(p.RConn(2), 0);
            case 'vsrc'
                % SPS sources have their positive terminal on the RConn side (see sr34_polarity_test):
                % RConn goes to node a so that V(a) - V(b) equals the commanded phasor.
                h = add_block('spsControlledVoltageSourceLib/Controlled Voltage Source', bp, 'Initialize','off', 'Position', pos);
                reorient(h, orient, pos); p = get_param(h, 'PortHandles');
                connect(p.RConn(1), e.a); connect(p.LConn(1), e.b);
                tag_in(h, sprintf('U%d', e.ch), 'right');
            case 'isrc'
                % positive command injects current into node a (RConn side), returning through node b
                h = add_block('spsControlledCurrentSourceLib/Controlled Current Source', bp, 'Initialize','off', 'Position', pos);
                reorient(h, orient, pos); p = get_param(h, 'PortHandles');
                connect(p.RConn(1), e.a); connect(p.LConn(1), e.b);
                tag_in(h, sprintf('J%d', e.ch), 'right');
        end
    end
end

function reorient(h, o, pos)
% turn a block (sources: terminals left and right; delta branches: vertical between two phase rows)
if ~isempty(o), set_param(h, 'Orientation', o, 'Position', pos); end
end

function v = sortby(v, phOf)
% bus nodes ordered by phase, always a row (a 0x1 empty would run a for loop once)
v = reshape(v, 1, []);
[~, i] = sort(phOf(v));
v = v(i);
end

function [d, fg, label] = icon(kind, cb)
% Mask icon (single-line diagram symbol), icon colour and type label of a composite block.
% Coordinates are normalised to the block (0..1); t = linspace(0, 2*pi, 60) comes from the mask
% initialisation.
gnd = 'plot([0.34 0.66], [0.16 0.16]); plot([0.41 0.59], [0.10 0.10]); plot([0.47 0.53], [0.04 0.04]);';
switch kind
    case {'line', 'line_cb'}
        fg = 'black'; label = 'Line';
        d = ['plot([0 0.30], [0.5 0.5]); plot([0.30 0.72 0.72 0.30 0.30], [0.36 0.36 0.64 0.64 0.36]); ' ...
             'plot([0.72 1], [0.5 0.5]); plot([0.36 0.66], [0.5 0.5]);'];
        if strcmp(kind, 'line_cb')
            label = 'Line with protection point';
            d = ['plot([0 0.08], [0.5 0.5]); patch([0.08 0.22 0.22 0.08], [0.38 0.38 0.62 0.62], [0.85 0.12 0.12]); ' ...
                 'plot([0.22 0.34], [0.5 0.5]); plot([0.34 0.74 0.74 0.34 0.34], [0.36 0.36 0.64 0.64 0.36]); ' ...
                 'plot([0.74 1], [0.5 0.5]); plot([0.40 0.68], [0.5 0.5]);'];
            if ~isempty(cb), d = [d sprintf(' text(0.54, 0.10, ''CB %s'', ''horizontalAlignment'', ''center'');', cb{1})]; end
        end
    case 'reg'
        fg = 'blue'; label = 'Voltage regulator';
        d = ['plot([0 0.22], [0.5 0.5]); plot(0.40 + 0.17*cos(t), 0.5 + 0.30*sin(t)); ' ...
             'plot(0.60 + 0.17*cos(t), 0.5 + 0.30*sin(t)); plot([0.78 1], [0.5 0.5]); ' ...
             'plot([0.26 0.74], [0.10 0.90]); patch([0.74 0.66 0.71], [0.90 0.85 0.78], [0 0 1]);'];
    case 'xfmr'
        fg = 'blue'; label = 'Transformer';
        d = ['plot([0 0.22], [0.5 0.5]); plot(0.40 + 0.17*cos(t), 0.5 + 0.30*sin(t)); ' ...
             'plot(0.60 + 0.17*cos(t), 0.5 + 0.30*sin(t)); plot([0.78 1], [0.5 0.5]);'];
    case 'load'
        fg = 'black'; label = 'Load';
        d = 'plot([0.5 0.5], [1 0.55]); patch([0.28 0.72 0.5], [0.55 0.55 0.12], [0.35 0.35 0.35]);';
    case 'cap'
        fg = 'blue'; label = 'Capacitor bank';
        d = ['plot([0.5 0.5], [1 0.60]); plot([0.24 0.76], [0.60 0.60]); plot([0.24 0.76], [0.46 0.46]); ' ...
             'plot([0.5 0.5], [0.46 0.16]); ' gnd];
    case 'der_sg'
        fg = 'darkGreen'; label = 'DER (synchronous generator)';
        d = ['plot([0.5 0.5], [1 0.74]); plot(0.5 + 0.30*cos(t), 0.42 + 0.30*sin(t)); ' ...
             'text(0.5, 0.42, ''G'', ''horizontalAlignment'', ''center'');'];
    case {'der_gfl', 'der_gfm'}
        fg = 'darkGreen';
        if strcmp(kind, 'der_gfl'), label = 'DER (grid-following inverter)';
        else, label = 'DER (grid-forming inverter)'; end
        d = ['plot([0.5 0.5], [1 0.80]); plot([0.18 0.82 0.82 0.18 0.18], [0.14 0.14 0.80 0.80 0.14]); ' ...
             'plot([0.18 0.82], [0.14 0.80]); text(0.36, 0.60, ''~'', ''horizontalAlignment'', ''center''); ' ...
             'text(0.64, 0.30, ''='', ''horizontalAlignment'', ''center'');'];
    case 'fault'
        fg = 'red'; label = 'Fault';
        d = ['plot([0.5 0.5], [1 0.80]); plot([0.5 0.36 0.62 0.48], [0.80 0.50 0.50 0.22]); ' ...
             'patch([0.42 0.54 0.47], [0.28 0.26 0.16], [0.85 0.1 0.1]); ' gnd];
    case 'source'
        fg = 'black'; label = 'Substation source';
        d = ['plot(0.42 + 0.30*cos(t), 0.5 + 0.38*sin(t)); ' ...
             'plot(linspace(0.22, 0.62, 40), 0.5 + 0.14*sin(linspace(0, 2*pi, 40))); ' ...
             'plot([0.72 1], [0.5 0.5]);'];
    otherwise
        fg = 'black'; label = 'Component';
        d = 'disp(''Component'');';
end
end

function hit = overlaps(a, b)
% true for every rectangle of A ([l t r b] rows) that intersects any rectangle of B
hit = false(size(a, 1), 1);
for i = 1:size(a, 1)
    hit(i) = any(a(i, 1) < b(:, 3) & a(i, 3) > b(:, 1) & a(i, 2) < b(:, 4) & a(i, 4) > b(:, 2));
end
end

function h = cport(blk)
% the single connection port of a Connection Port (PMIOPort) block
p = get_param(blk, 'PortHandles');
h = [p.LConn p.RConn];
h = h(1);
end
