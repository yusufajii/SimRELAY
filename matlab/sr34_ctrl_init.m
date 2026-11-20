function y0 = sr34_ctrl_init()
%SR34_CTRL_INIT Initial controller output (breaker states and source phasors) for the Unit Delay.
global SR34 %#ok<GVMIS>
cfg = SR34;
y0 = sr34_ctrl_outputs(cfg, sr34_ctrl_state0(cfg));
end
