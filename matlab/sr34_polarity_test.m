function r = sr34_polarity_test()
%SR34_POLARITY_TEST Check terminal polarity conventions of the SPS blocks used by sr34_build.
%   Source (input 100) LConn->n1, RConn->gnd; 10 ohm n1->gnd; voltage meas LConn1->n1, LConn2->gnd.
%   Current source (input 10) LConn->n2, RConn->gnd; 10 ohm n2->gnd; voltage meas at n2.
%   Current measurement LConn->n1 side of the 10 ohm resistor.
mdl = 'sr34_pol';
if bdIsLoaded(mdl), close_system(mdl, 0); end
new_system(mdl);
cellfun(@load_system, {'spspowerguiLib','spsGroundLib','spsSeriesRLCBranchLib','spsVoltageMeasurementLib', ...
    'spsCurrentMeasurementLib','spsControlledCurrentSourceLib','spsControlledVoltageSourceLib'});
set_param(mdl, 'SolverType','Fixed-step', 'Solver','FixedStepDiscrete', 'FixedStep','1/960', 'StopTime','0.01', 'ReturnWorkspaceOutputs','on');
add_block('spspowerguiLib/powergui', [mdl '/pg'], 'SimulationMode','Phasor', 'frequency','60');
P = @(h) get_param(h, 'PortHandles');
L = @(a, b) add_line(mdl, a, b, 'autorouting', 'off');
g = @(n) P(add_block('spsGroundLib/Ground', [mdl '/' n]));
vs = P(add_block('spsControlledVoltageSourceLib/Controlled Voltage Source', [mdl '/vs'], 'Initialize','off'));
cs = P(add_block('spsControlledCurrentSourceLib/Controlled Current Source', [mdl '/cs'], 'Initialize','off'));
r1 = P(add_block('spsSeriesRLCBranchLib/Series RLC Branch', [mdl '/r1'], 'BranchType','R', 'Resistance','10'));
r2 = P(add_block('spsSeriesRLCBranchLib/Series RLC Branch', [mdl '/r2'], 'BranchType','R', 'Resistance','10'));
vm1 = P(add_block('spsVoltageMeasurementLib/Voltage Measurement', [mdl '/vm1'], 'OutputType','Complex'));
vm2 = P(add_block('spsVoltageMeasurementLib/Voltage Measurement', [mdl '/vm2'], 'OutputType','Complex'));
im = P(add_block('spsCurrentMeasurementLib/Current Measurement', [mdl '/im'], 'OutputType','Complex'));
c1 = P(add_block('simulink/Sources/Constant', [mdl '/c1'], 'Value','100'));
c2 = P(add_block('simulink/Sources/Constant', [mdl '/c2'], 'Value','10'));
L(c1.Outport(1), vs.Inport(1)); L(c2.Outport(1), cs.Inport(1));
% voltage source circuit: vs + at LConn -> im -> r1 -> ground
L(vs.LConn(1), im.LConn(1)); L(im.RConn(1), r1.LConn(1)); G1 = g('g1'); L(r1.RConn(1), G1.LConn(1));
G2 = g('g2'); L(vs.RConn(1), G2.LConn(1));
L(vm1.LConn(1), im.LConn(1)); G3 = g('g3'); L(vm1.LConn(2), G3.LConn(1));
% current source circuit
L(cs.LConn(1), r2.LConn(1)); G4 = g('g4'); L(r2.RConn(1), G4.LConn(1)); G5 = g('g5'); L(cs.RConn(1), G5.LConn(1));
L(vm2.LConn(1), cs.LConn(1)); G6 = g('g6'); L(vm2.LConn(2), G6.LConn(1));
names = {'v_src_meas','i_meas','v_isrc_meas'}; outs = {vm1.Outport(1), im.Outport(1), vm2.Outport(1)};
for k = 1:3
    tw = P(add_block('simulink/Sinks/To Workspace', [mdl '/' names{k}], 'VariableName', names{k}, 'SaveFormat','Array'));
    L(outs{k}, tw.Inport(1));
end
so = sim(mdl);
r = struct('v_src_meas', so.v_src_meas(end), 'i_meas', so.i_meas(end), 'v_isrc_meas', so.v_isrc_meas(end));
close_system(mdl, 0);
end
