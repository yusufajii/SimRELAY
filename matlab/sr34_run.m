function sr34_run(cfgfile, outfile, mdl)
%SR34_RUN Build (or reuse) the Simscape model for a SimRELAY scenario, simulate it, save results.
%   sr34_run(cfgfile, outfile) reads the JSON configuration written by the SimRELAY app, builds
%   the phasor model, runs it and writes the measured node voltages, branch currents and the
%   controller log to the MAT file OUTFILE (read back by engine/matlab_bridge.py).
if nargin < 3, mdl = 'sr34_model'; end
global SR34 SR34_ENGINE %#ok<GVMIS>
cfg = jsondecode(fileread(cfgfile));
cfg = sr34_normalise(cfg);
SR34 = cfg; sr34_ctrl([], 'reset');
t0 = tic;
key = cfg.structure_key;
sr34_progress(cfg, 'build', 0, 1);
if ~bdIsLoaded(mdl) || ~strcmp(strtok(get_param(mdl, 'Tag'), ':'), key)   % Tag may end in ':arranged' (sr34_open)
    sr34_build(cfg, mdl);                % new structure: build the Simscape model
    set_param(mdl, 'Tag', key);
else
    sr34_update(cfg, mdl);               % same structure: only update block values
end
tb = toc(t0);
sr34_progress(cfg, 'sim', 0, cfg.T + cfg.t_init);
SR34_ENGINE = true;                      % the editor callbacks (sr34_editor) stay out of engine runs
try
    so = sim(mdl, 'ReturnWorkspaceOutputs', 'on');   % the model itself is set to 'off' for editor runs
catch err
    SR34_ENGINE = false;
    rethrow(err);
end
SR34_ENGINE = false;
simV = so.simV; simI = so.simI; %#ok<NASGU>
st = sr34_ctrl([], 'state');
log = st.log; %#ok<NASGU>
wall = toc(t0); %#ok<NASGU>
save(outfile, 'simV', 'simI', 'log', 'wall', 'tb', '-v7');
end
