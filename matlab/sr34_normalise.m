function cfg = sr34_normalise(cfg)
%SR34_NORMALISE Make jsondecode output uniform (cell arrays for lists, row vectors for indices).
cfg.elements = as_cell(cfg.elements);
cfg.faults = as_cell(cfg.faults);
cfg.ders = as_cell(cfg.ders);
cfg.ieds = as_cell(cfg.ieds);
cfg.events = as_cell(cfg.events);
if ~isfield(cfg, 'structure_key'), cfg.structure_key = 'none'; end
end

function c = as_cell(x)
if isempty(x)
    c = {};
elseif iscell(x)
    c = x;
elseif isstruct(x)
    c = num2cell(x);
else
    c = {x};
end
end
