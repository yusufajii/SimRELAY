function sr34_run(cfgfile, outfile, mdl)
%SR34_RUN Build (or reuse) the Simscape model for a SimRelay scenario, simulate it, save results.
%   sr34_run(cfgfile, outfile) reads the JSON configuration written by the SimRelay app, builds
%   the phasor model, runs it and writes the measured node voltages, branch currents and the
%   controller log to the MAT file OUTFILE (read back by engine/matlab_bridge.py).
if nargin < 3, mdl = 'sr34_model'; end
global SR34 %#ok<GVMIS>
cfg = jsondecode(fileread(cfgfile));
cfg = sr34_normalise(cfg);
SR34 = cfg; sr34_ctrl([], 'reset');
t0 = tic;
key = cfg.structure_key;
sr34_progress(cfg, 'build', 0, 1);
if ~bdIsLoaded(mdl) || ~strcmp(get_param(mdl, 'Tag'), key)
    sr34_build(cfg, mdl);                % new structure: build the Simscape model
    set_param(mdl, 'Tag', key);
else
    sr34_update(cfg, mdl);               % same structure: only update block values
end
tb = toc(t0);
sr34_progress(cfg, 'sim', 0, cfg.T + cfg.t_init);
so = sim(mdl);
simV = so.simV; simI = so.simI; %#ok<NASGU>
st = sr34_ctrl([], 'state');
log = st.log; %#ok<NASGU>
wall = toc(t0); %#ok<NASGU>
save(outfile, 'simV', 'simI', 'log', 'wall', 'tb', '-v7');
end
