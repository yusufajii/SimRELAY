function sr34_update(cfg, mdl)
%SR34_UPDATE Write element values into an already built model with the same structure.
%   Used when only parameter values change between runs (load level, DER size, fault resistance,
%   regulator taps, breaker initial states), which avoids rebuilding the Simscape model.
w = 2 * pi * cfg.f0;
els = cfg.elements;
P = sr34_paths(cfg, mdl);
for k = 1:numel(els)
    e = els{k};
    b = P{k};
    switch e.type
        case 'brk'
            set_param(b, 'InitialState', num2str(e.init), 'BreakerResistance', num2str(e.ron, 17));
        case 'rl'
            if e.x == 0
                set_param(b, 'Resistance', num2str(max(e.r, 1e-6), 17));
            elseif e.x > 0
                set_param(b, 'Resistance', num2str(e.r, 17), 'Inductance', num2str(max(e.x, 1e-9) / w, 17));
            else
                set_param(b, 'Resistance', num2str(e.r, 17), 'Capacitance', num2str(-1 / (w * e.x), 17));
            end
        case 'cap'
            set_param(b, 'Capacitance', num2str(e.c, 17));
        case 'mutual'
            n = numel(e.a);
            set_param(b, 'ResistanceMatrix', mat2str(reshape(e.R, n, n), 17), ...
                'InductanceMatrix', mat2str(reshape(e.L, n, n), 17));
        case 'xf'
            set_param(b, 'winding1', sprintf('[%.17g 1e-6 1e-6]', e.v1), ...
                'winding2', sprintf('[%.17g 1e-6 1e-6]', e.v1 * e.ratio));
    end
end
set_param(mdl, 'StopTime', num2str(cfg.T + cfg.t_init, 17));
end
