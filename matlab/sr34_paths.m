function P = sr34_paths(cfg, mdl)
%SR34_PATHS Full Simulink path of the block of every netlist element.
%   P = sr34_paths(cfg, mdl) returns a cell array with one block path per element of
%   cfg.elements. Elements live in the subsystem of their diagram group (cfg.groups), so the
%   builder (sr34_build) and the value updater (sr34_update) address the same blocks.
els = cfg.elements;
G = cfg.groups;
P = cell(1, numel(els));
for k = 1:numel(els)
    e = els{k};
    switch e.type
        case 'imeas', b = sprintf('Im%d', e.ch);
        case 'brk',   b = sprintf('Brk%d', e.ch);
        case 'rl',    b = sprintf('Z%d', k);
        case 'cap',   b = sprintf('C%d', k);
        case 'mutual', b = sprintf('M%d', k);
        case 'xf',    b = sprintf('T%d', k);
        case 'vsrc',  b = sprintf('Vs%d', e.ch);
        case 'isrc',  b = sprintf('Is%d', e.ch);
        otherwise, error('sr34_paths:element', 'Unknown element type %s', e.type);
    end
    P{k} = [mdl '/' G{e.g}.name '/' b];
end
end
