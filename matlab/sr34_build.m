function info = sr34_build(cfg, mdl)
%SR34_BUILD Build a Simscape Electrical (Specialized Power Systems) phasor model from a netlist.
%   info = sr34_build(cfg, mdl) creates the Simulink model MDL from the configuration produced by
%   the SimRelay app (engine/matlab_bridge.py). The model contains only the power network,
%   measurements, breakers and controlled sources; all relay, DER and event logic runs in the
%   controller block (sr34_ctrl.m) that closes the loop each time step.
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

anchor = cell(1, cfg.n_nodes);
nblk = 0;
brkIn = zeros(1, cfg.n_brk); vIn = zeros(1, cfg.n_v); iIn = zeros(1, cfg.n_i);
measOut = zeros(1, cfg.n_meas);

    function p = place(col)
        nblk = nblk + 1;
        r = floor((nblk - 1) / 40); c = mod(nblk - 1, 40);
        x = 200 + c * 90 + col; y = 120 + r * 90;
        p = [x y x + 50 y + 40];
    end
    function h = blk(lib, name, varargin)
        h = add_block(lib, [mdl '/' name], 'Position', place(0), varargin{:});
    end
    function connect(ph, node)
        if node == 0
            g = blk('spsGroundLib/Ground', sprintf('G%d', nblk + 1));
            gp = get_param(g, 'PortHandles');
            add_line(mdl, ph, gp.LConn(1), 'autorouting', 'off');
        elseif isempty(anchor{node})
            anchor{node} = ph;
        else
            add_line(mdl, anchor{node}, ph, 'autorouting', 'off');
        end
    end

els = cfg.elements;
if ~iscell(els), els = num2cell(els); end
for k = 1:numel(els)
    e = els{k};
    if mod(k, 20) == 0, sr34_progress(cfg, 'build', k, numel(els) + cfg.N); end
    switch e.type
        case 'imeas'
            h = blk('spsCurrentMeasurementLib/Current Measurement', sprintf('Im%d', e.ch), 'OutputType','Complex');
            p = get_param(h, 'PortHandles');
            connect(p.LConn(1), e.a); connect(p.RConn(1), e.b);
            measOut(e.ch) = p.Outport(1);
        case 'brk'
            h = blk('spsBreakerLib/Breaker', sprintf('Brk%d', e.ch), 'External','on', 'InitialState', num2str(e.init), ...
                'BreakerResistance', num2str(e.ron, 17), 'SnubberResistance','1e6', 'SnubberCapacitance','inf');
            p = get_param(h, 'PortHandles');
            connect(p.LConn(1), e.a); connect(p.RConn(1), e.b);
            brkIn(e.ch) = p.Inport(1);
        case 'rl'
            if e.x == 0
                h = blk('spsSeriesRLCBranchLib/Series RLC Branch', sprintf('Z%d', k), 'BranchType', 'R', ...
                    'Resistance', num2str(max(e.r, 1e-6), 17));
            elseif e.x > 0
                if e.r > 0, bt = 'RL'; else, bt = 'L'; end
                h = blk('spsSeriesRLCBranchLib/Series RLC Branch', sprintf('Z%d', k), 'BranchType', bt, ...
                    'Resistance', num2str(e.r, 17), 'Inductance', num2str(max(e.x, 1e-9) / w, 17));
            else
                if e.r > 0, bt = 'RC'; else, bt = 'C'; end
                h = blk('spsSeriesRLCBranchLib/Series RLC Branch', sprintf('Z%d', k), 'BranchType', bt, ...
                    'Resistance', num2str(e.r, 17), 'Capacitance', num2str(-1 / (w * e.x), 17));
            end
            p = get_param(h, 'PortHandles');
            connect(p.LConn(1), e.a); connect(p.RConn(1), e.b);
        case 'cap'
            h = blk('spsSeriesRLCBranchLib/Series RLC Branch', sprintf('C%d', k), 'BranchType','C', 'Capacitance', num2str(e.c, 17));
            p = get_param(h, 'PortHandles');
            connect(p.LConn(1), e.a); connect(p.RConn(1), e.b);
        case 'mutual'
            n = numel(e.a);
            R = reshape(e.R, n, n); L = reshape(e.L, n, n);
            h = blk('spsMutualInductanceLib/Mutual Inductance', sprintf('M%d', k), 'TypeOfMutual','Generalized mutual inductance', ...
                'NumberOfWindings', num2str(n), 'ResistanceMatrix', mat2str(R, 17), 'InductanceMatrix', mat2str(L, 17));
            p = get_param(h, 'PortHandles');
            for j = 1:n
                connect(p.LConn(j), e.a(j)); connect(p.RConn(j), e.b(j));
            end
        case 'xf'
            v1 = e.v1; v2 = e.v1 * e.ratio;
            h = blk('spsLinearTransformerLib/Linear Transformer', sprintf('T%d', k), 'UNITS','pu', 'NominalPower','[1e6 60]', ...
                'winding1', sprintf('[%.17g 1e-6 1e-6]', v1), 'winding2', sprintf('[%.17g 1e-6 1e-6]', v2), ...
                'ThreeWindings','off', 'RmLm','[1e6 1e6]');
            p = get_param(h, 'PortHandles');
            connect(p.LConn(1), e.a); connect(p.LConn(2), 0);
            connect(p.RConn(1), e.b); connect(p.RConn(2), 0);
        case 'vsrc'
            % SPS sources have their positive terminal on the RConn side (see sr34_polarity_test):
            % RConn goes to node a so that V(a) - V(b) equals the commanded phasor.
            h = blk('spsControlledVoltageSourceLib/Controlled Voltage Source', sprintf('Vs%d', e.ch), 'Initialize','off');
            p = get_param(h, 'PortHandles');
            connect(p.RConn(1), e.a); connect(p.LConn(1), e.b);
            vIn(e.ch) = p.Inport(1);
        case 'isrc'
            % positive command injects current into node a (RConn side), returning through node b
            h = blk('spsControlledCurrentSourceLib/Controlled Current Source', sprintf('Is%d', e.ch), 'Initialize','off');
            p = get_param(h, 'PortHandles');
            connect(p.RConn(1), e.a); connect(p.LConn(1), e.b);
            iIn(e.ch) = p.Inport(1);
        otherwise
            error('sr34_build:element', 'Unknown element type %s', e.type);
    end
end

% ---------------------------------------------------------------- bus voltage measurements
N = cfg.N;
vmOut = zeros(1, N);
for i = 1:N
    h = blk('spsVoltageMeasurementLib/Voltage Measurement', sprintf('Vm%d', i), 'OutputType','Complex');
    p = get_param(h, 'PortHandles');
    connect(p.LConn(1), i); connect(p.LConn(2), 0);
    vmOut(i) = p.Outport(1);
end

% ---------------------------------------------------------------- signal side
ybase = 120 + (ceil(nblk / 40) + 1) * 90;
sig = @(name, lib, pos, varargin) add_block(lib, [mdl '/' name], 'Position', pos, varargin{:});
muxV = sig('MuxV', 'simulink/Signal Routing/Mux', [200 ybase 205 ybase + 400], 'Inputs', num2str(N));
muxI = sig('MuxI', 'simulink/Signal Routing/Mux', [260 ybase 265 ybase + 400], 'Inputs', num2str(max(cfg.n_meas, 1)));
for i = 1:N, mp = get_param(muxV, 'PortHandles'); add_line(mdl, vmOut(i), mp.Inport(i), 'autorouting','off'); end
for i = 1:cfg.n_meas, mp = get_param(muxI, 'PortHandles'); add_line(mdl, measOut(i), mp.Inport(i), 'autorouting','off'); end
sig('LogV', 'simulink/Sinks/To Workspace', [330 ybase 400 ybase + 30], 'VariableName','simV', 'SaveFormat','Array', 'SampleTime', num2str(dt, 17));
sig('LogI', 'simulink/Sinks/To Workspace', [330 ybase + 60 400 ybase + 90], 'VariableName','simI', 'SaveFormat','Array', 'SampleTime', num2str(dt, 17));
add_line(mdl, 'MuxV/1', 'LogV/1'); add_line(mdl, 'MuxI/1', 'LogI/1');
sig('ReImV', sprintf('simulink/Math\nOperations/Complex to\nReal-Imag'), [330 ybase + 130 360 ybase + 170]);
sig('ReImI', sprintf('simulink/Math\nOperations/Complex to\nReal-Imag'), [330 ybase + 190 360 ybase + 230]);
add_line(mdl, 'MuxV/1', 'ReImV/1'); add_line(mdl, 'MuxI/1', 'ReImI/1');
sig('Clock', 'simulink/Sources/Digital Clock', [330 ybase + 260 370 ybase + 290], 'SampleTime', num2str(dt, 17));
sig('MuxU', 'simulink/Signal Routing/Mux', [430 ybase + 120 435 ybase + 300], 'Inputs', '5');
add_line(mdl, 'Clock/1', 'MuxU/1'); add_line(mdl, 'ReImV/1', 'MuxU/2'); add_line(mdl, 'ReImV/2', 'MuxU/3');
add_line(mdl, 'ReImI/1', 'MuxU/4'); add_line(mdl, 'ReImI/2', 'MuxU/5');

nout = cfg.n_brk + 2 * cfg.n_v + 2 * cfg.n_i;
sig('Controller', sprintf('simulink/User-Defined\nFunctions/Interpreted MATLAB\nFunction'), [480 ybase + 180 600 ybase + 240], ...
    'MATLABFcn', 'sr34_ctrl(u)', 'OutputDimensions', num2str(nout), 'SampleTime', num2str(dt, 17));
add_line(mdl, 'MuxU/1', 'Controller/1');
sig('Delay', 'simulink/Discrete/Unit Delay', [640 ybase + 190 680 ybase + 230], 'SampleTime', num2str(dt, 17), ...
    'InitialCondition', 'sr34_ctrl_init()');
add_line(mdl, 'Controller/1', 'Delay/1');
dmx = sig('Demux', 'simulink/Signal Routing/Demux', [720 ybase 725 ybase + 900], 'Outputs', num2str(nout));
add_line(mdl, 'Delay/1', 'Demux/1');
dp = get_param(dmx, 'PortHandles');
for i = 1:cfg.n_brk
    add_line(mdl, dp.Outport(i), brkIn(i), 'autorouting','off');
end
off = cfg.n_brk;
for i = 1:cfg.n_v
    c = sig(sprintf('CV%d', i), sprintf('simulink/Math\nOperations/Real-Imag to\nComplex'), [800 ybase + 40 * i 830 ybase + 40 * i + 30]);
    cp = get_param(c, 'PortHandles');
    add_line(mdl, dp.Outport(off + i), cp.Inport(1), 'autorouting','off');
    add_line(mdl, dp.Outport(off + cfg.n_v + i), cp.Inport(2), 'autorouting','off');
    add_line(mdl, cp.Outport(1), vIn(i), 'autorouting','off');
end
off = cfg.n_brk + 2 * cfg.n_v;
for i = 1:cfg.n_i
    c = sig(sprintf('CI%d', i), sprintf('simulink/Math\nOperations/Real-Imag to\nComplex'), [900 ybase + 40 * i 930 ybase + 40 * i + 30]);
    cp = get_param(c, 'PortHandles');
    add_line(mdl, dp.Outport(off + i), cp.Inport(1), 'autorouting','off');
    add_line(mdl, dp.Outport(off + cfg.n_i + i), cp.Inport(2), 'autorouting','off');
    add_line(mdl, cp.Outport(1), iIn(i), 'autorouting','off');
end
info = struct('blocks', nblk, 'nout', nout);
end
