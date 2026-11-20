function y = sr34_ctrl_outputs(cfg, st)
%SR34_CTRL_OUTPUTS Pack controller state into the output vector
%   y = [breaker states; real(V cmd); imag(V cmd); real(I cmd); imag(I cmd)], phasors in peak values.
pk = sqrt(2);
brk = zeros(cfg.n_brk, 1);
vc = zeros(cfg.n_v, 1); ic = zeros(cfg.n_i, 1);
for j = 1:numel(cfg.ieds)
    brk(cfg.ieds{j}.cb) = st.cb(j);
end
brk(cfg.sub.brk) = st.sub;
for f = 1:numel(cfg.faults)
    brk(cfg.faults{f}.brk) = double(st.fault_on(f));
end
E = (cfg.sub.E(1) + 1i * cfg.sub.E(2)) * st.POS;
vc(cfg.sub.src) = pk * E;
for j = 1:numel(cfg.ders)
    d = cfg.ders{j}; s = st.der(j);
    brk(d.brk) = double(s.online);
    if d.type == 2
        ic(d.isrc) = pk * s.Iinj;
    else
        vc(d.vsrc) = pk * s.Eeff;
    end
end
if isfield(st, 'clpu_i') && ~isempty(st.clpu_i)
    for q = 1:numel(cfg.clpu.loads)
        ic(cfg.clpu.loads(q).ch) = pk * st.clpu_i(q);
    end
end
y = [brk; real(vc); imag(vc); real(ic); imag(ic)];
end
