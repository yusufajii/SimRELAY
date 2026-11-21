function slx = sr34_open(cfgfile, slxdir, url, mdl, stored)
%SR34_OPEN Open the Simscape model of a SimRELAY scenario in the Simulink Editor.
%   slx = sr34_open(cfgfile, slxdir, url, mdl, stored) reads the JSON configuration written by
%   the SimRELAY app and opens the phasor model in the Simulink Editor.
%
%   STORED is the SLX file kept for the network topology of the scenario (models/T###.slx of a
%   campaign, or the topology cache of the app). When it exists, it is opened directly and only
%   the element values of this scenario are written into it (sr34_update), so nothing is built.
%   When it does not exist yet, the model is built exactly as sr34_run does and a copy is kept
%   as STORED for the next time. Without STORED (older callers) the model is built and saved as
%   <slxdir>/<mdl>.slx.
%
%   The model can be simulated from the editor (Run button): its InitFcn loads the scenario
%   configuration (kept in SLXDIR) and resets the controller, and its StopFcn sends the result
%   to the SimRELAY server at URL, which processes it like an engine run and shows it in the web
%   app (see sr34_editor).
if nargin < 4 || isempty(mdl), mdl = 'sr34_model'; end
if nargin < 5, stored = ''; end
global SR34 %#ok<GVMIS>
cfg = jsondecode(fileread(cfgfile));
cfg = sr34_normalise(cfg);
SR34 = cfg; sr34_ctrl([], 'reset');
key = cfg.structure_key;
slx = '';
if ~isempty(stored)
    [~, mdl] = fileparts(stored);          % a model loaded from a file is named after the file
    if bdIsLoaded(mdl) && ~strcmpi(get_param(mdl, 'FileName'), stored)
        close_system(mdl, 0);              % same name from another folder (pilot and full campaign)
    end
end
if ~isempty(stored) && isfile(stored)
    load_system(stored);                   % stored topology: no build, only this scenario's values
    sr34_update(cfg, mdl);
    slx = stored;
else
    if ~bdIsLoaded(mdl) || ~strcmp(strtok(get_param(mdl, 'Tag'), ':'), key)
        sr34_build(cfg, mdl);
        set_param(mdl, 'Tag', key);
    else
        sr34_update(cfg, mdl);
    end
    if ~isempty(stored)                    % keep it for the next time this topology is opened
        d = fileparts(stored);
        if ~exist(d, 'dir'), mkdir(d); end
        save_system(mdl, stored);          % same name as the file, so the model is not renamed
        slx = stored;
    end
end
% Run from the editor: configuration next to the model, callbacks to load it and report back.
if ~exist(slxdir, 'dir'), mkdir(slxdir); end
cfgcopy = fullfile(slxdir, [mdl '_cfg.json']);
copyfile(cfgfile, cfgcopy, 'f');
here = fileparts(mfilename('fullpath'));
% Editor runs write simV and simI straight to the base workspace (engine runs ask for a
% SimulationOutput explicitly in sr34_run).
set_param(mdl, 'ReturnWorkspaceOutputs', 'off', ...
    'InitFcn', sprintf('addpath(''%s''); sr34_editor(''init'', ''%s'');', here, cfgcopy), ...
    'StopFcn', sprintf('sr34_editor(''stop'', ''%s'', ''%s'');', cfgcopy, url));
if isfield(cfg, 'name') && ~isempty(cfg.name)
    set_param(mdl, 'Description', sprintf('SimRELAY scenario: %s', char(string(cfg.name))));
end
if isempty(slx)
    slx = fullfile(slxdir, [mdl '.slx']);
    save_system(mdl, slx, 'OverwriteIfChangedOnDisk', true);
end
open_system(mdl);
set_param(mdl, 'ZoomFactor', 'FitSystem');
end
