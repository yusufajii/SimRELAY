function slx = sr34_open(cfgfile, slxdir, url, mdl)
%SR34_OPEN Build (or reuse) the Simscape model for a SimRELAY scenario and open it in Simulink.
%   slx = sr34_open(cfgfile, slxdir, url) reads the JSON configuration written by the SimRELAY
%   app, builds the phasor model exactly as sr34_run does, saves it as <slxdir>/<mdl>.slx and
%   opens the Simulink Editor.
%
%   The model can be simulated from the editor (Run button): its InitFcn loads the scenario
%   configuration (kept next to the .slx) and resets the controller, and its StopFcn sends the
%   result to the SimRELAY server at URL, which processes it like an engine run and shows it in
%   the web app (see sr34_editor).
if nargin < 4, mdl = 'sr34_model'; end
global SR34 %#ok<GVMIS>
cfg = jsondecode(fileread(cfgfile));
cfg = sr34_normalise(cfg);
SR34 = cfg; sr34_ctrl([], 'reset');
key = cfg.structure_key;
if ~bdIsLoaded(mdl) || ~strcmp(strtok(get_param(mdl, 'Tag'), ':'), key)
    sr34_build(cfg, mdl);
    set_param(mdl, 'Tag', key);
else
    sr34_update(cfg, mdl);
end
% The layout (top level and inside every composite block) is drawn by sr34_build itself.
% Run from the editor: configuration next to the model, callbacks to load it and report back.
if ~exist(slxdir, 'dir'), mkdir(slxdir); end
cfgcopy = fullfile(slxdir, [mdl '_cfg.json']);
copyfile(cfgfile, cfgcopy);
here = fileparts(mfilename('fullpath'));
% Editor runs write simV and simI straight to the base workspace (engine runs ask for a
% SimulationOutput explicitly in sr34_run).
set_param(mdl, 'ReturnWorkspaceOutputs', 'off', ...
    'InitFcn', sprintf('addpath(''%s''); sr34_editor(''init'', ''%s'');', here, cfgcopy), ...
    'StopFcn', sprintf('sr34_editor(''stop'', ''%s'', ''%s'');', cfgcopy, url));
if isfield(cfg, 'name') && ~isempty(cfg.name)
    set_param(mdl, 'Description', sprintf('SimRELAY scenario: %s', char(string(cfg.name))));
end
slx = fullfile(slxdir, [mdl '.slx']);
save_system(mdl, slx, 'OverwriteIfChangedOnDisk', true);
open_system(mdl);
set_param(mdl, 'ZoomFactor', 'FitSystem');
end
