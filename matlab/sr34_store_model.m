function sr34_store_model(mdl, slx)
%SR34_STORE_MODEL Keep a copy of a freshly built model as SLX (one file per network topology).
%   sr34_store_model(mdl, slx) saves the model MDL to the file SLX unless that file already exists.
%   Campaign runs (batch.py --campaign) call it through sr34_run right after sr34_build, so every
%   topology of the campaign is stored once and the Simulink button of the web app can open it
%   without building it again.
%
%   save_system with a different file name would rename the model in memory, and sr34_run looks
%   the model up by its name. The model is therefore saved under its own name in a folder private
%   to this MATLAB process and then copied to SLX (Simulink names a loaded model after its file).
%   The private copy is kept: after save_system the model in memory refers to that file, and
%   sim() fails when it has been deleted. The final move is atomic, so parallel workers that
%   build the same topology cannot leave a partial file behind.
if isfile(slx), return; end
d = fileparts(slx);
if ~isempty(d) && ~exist(d, 'dir'), mkdir(d); end
own = fullfile(tempdir, sprintf('sr34_store_%d', feature('getpid')));
if ~exist(own, 'dir'), mkdir(own); end
f = fullfile(own, [mdl '.slx']);
save_system(mdl, f);
part = sprintf('%s.part%d', slx, feature('getpid'));
copyfile(f, part, 'f');
movefile(part, slx, 'f');
end
