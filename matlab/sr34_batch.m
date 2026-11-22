function sr34_batch(listfile, nworkers)
%SR34_BATCH Run a list of SimRELAY scenarios (MATLAB sweep engine).
%   sr34_batch(listfile, nworkers) reads a JSON list of {cfg, out} file pairs written by batch.py
%   and runs sr34_run on each of them.
%     nworkers <= 1 : serial, in this MATLAB session (lowest memory use).
%     nworkers  > 1 : parfor on a Parallel Computing Toolbox pool of NWORKERS workers.
%   Each session keeps its Simscape model in memory and only rebuilds it when the network
%   structure changes (batch.py sends cases sorted by structure). A failed case writes its error
%   report next to the output file as <out>.err.
L = jsondecode(fileread(listfile));
if ~iscell(L), L = num2cell(L); end
cfgs = cellfun(@(x) x.cfg, L, 'UniformOutput', false);
outs = cellfun(@(x) x.out, L, 'UniformOutput', false);
here = fileparts(mfilename('fullpath'));
if nworkers <= 1
    persistent ready %#ok<TLEV>
    if isempty(ready), sr34_worker_init(here); ready = true; end
    for i = 1:numel(cfgs)
        run_one(cfgs{i}, outs{i});
    end
    return
end
pool = gcp('nocreate');
if isempty(pool) || pool.NumWorkers ~= nworkers
    if ~isempty(pool), delete(pool); end
    % The Processes profile allows one worker per physical core by default; raise the limit for
    % this session only (the saved profile is not changed) when more workers are requested.
    cl = parcluster('Processes');
    if cl.NumWorkers < nworkers, cl.NumWorkers = nworkers; end
    pool = parpool(cl, nworkers, 'IdleTimeout', 120);
    wait(parfevalOnAll(pool, @sr34_worker_init, 0, here));
end
parfor i = 1:numel(cfgs)
    run_one(cfgs{i}, outs{i});
end
end

function run_one(cfg, out)
try
    sr34_run(cfg, out);
catch err
    fid = fopen([out '.err'], 'w');
    fprintf(fid, '%s', getReport(err, 'basic', 'hyperlinks', 'off'));
    fclose(fid);
end
end
