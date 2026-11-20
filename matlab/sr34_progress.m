function sr34_progress(cfg, stage, k, n)
%SR34_PROGRESS Write the current stage and progress to the file the SimRelay server polls.
%   Does nothing when the configuration has no progress file (batch runs).
if ~isfield(cfg, 'progress_file') || isempty(cfg.progress_file), return; end
fid = fopen(cfg.progress_file, 'w');
if fid < 0, return; end
fprintf(fid, '%s %.6g %.6g', stage, k, n);
fclose(fid);
end
