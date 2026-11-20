function sr34_worker_init(here)
%SR34_WORKER_INIT Prepare one MATLAB session (pool worker or main) for SimRelay simulations.
%   Every session gets its own working, cache and code-generation folder; Simulink sessions that
%   share these folders corrupt each other's files when they run in parallel.
addpath(here);
d = fullfile(tempdir, sprintf('sr34_%d', feature('getpid')));
if ~exist(d, 'dir'), mkdir(d); end
cd(d);
Simulink.fileGenControl('set', 'CacheFolder', d, 'CodeGenFolder', d, 'createDir', true);
end
