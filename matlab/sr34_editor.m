function sr34_editor(cmd, cfgfile, url)
%SR34_EDITOR Model callbacks that let the SimRELAY model run from the Simulink Editor (Run button).
%   sr34_open installs them on the model:
%     InitFcn  sr34_editor('init', cfgfile)        load the scenario configuration, reset the controller
%     StopFcn  sr34_editor('stop', cfgfile, url)   send the measured phasors and controller log to the
%                                                  SimRELAY server, which processes them exactly like an
%                                                  engine run and shows the result in the web app
%   Runs started by the app itself (sr34_run, batch) set the global SR34_ENGINE and are left alone.
global SR34 SR34_ENGINE %#ok<GVMIS>
if ~isempty(SR34_ENGINE) && SR34_ENGINE
    return
end
switch cmd
    case 'init'
        SR34 = sr34_normalise(jsondecode(fileread(cfgfile)));
        sr34_ctrl([], 'reset');
        evalin('base', 'clear simV simI');
        fprintf('SimRELAY: simulating "%s" from the Simulink Editor.\n', char(string(SR34.name)));
    case 'stop'
        % simV and simI reach the base workspace only when the simulation has fully ended, after
        % StopFcn, so they are collected by a timer that re-arms itself without blocking MATLAB.
        arm(cfgfile, url, 1);
end
end

function arm(cfgfile, url, attempt)
t = timer('StartDelay', 0.5, 'ExecutionMode', 'singleShot', ...
    'TimerFcn', @(tm, ~) collect(tm, cfgfile, url, attempt));
start(t);
end

function collect(tm, cfgfile, url, attempt)
stop(tm); delete(tm);
try
    if ~evalin('base', 'exist(''simV'', ''var'') && exist(''simI'', ''var'')')
        if attempt < 240
            arm(cfgfile, url, attempt + 1);
        else
            warning('SimRELAY: the simulation output (simV, simI) did not appear in the workspace.');
        end
        return
    end
    simV = evalin('base', 'simV'); simI = evalin('base', 'simI'); %#ok<NASGU>
    st = sr34_ctrl([], 'state');
    log = st.log; wall = 0; tb = 0; %#ok<NASGU>
    f = fullfile(fileparts(cfgfile), 'editor_run.mat');
    save(f, 'simV', 'simI', 'log', 'wall', 'tb', '-v7');
    fprintf('SimRELAY: sending the result to the web app...\n');
    r = webwrite([url '/api/simulink/import'], struct('mat', f), ...
        weboptions('MediaType', 'application/json', 'Timeout', 180));
    if isfield(r, 'error')
        warning('SimRELAY: the web app could not process the run: %s', r.error);
    else
        fprintf('SimRELAY: done. The web app now shows this run as %s.\n', r.run_id);
    end
catch err
    warning('SimRELAY: the run result could not be sent to the web app: %s', err.message);
end
end
