"""
Virtual IED modular (DoF-4). Setting TETAP (dihitung sekali pada baseline 0% DER).

  Kelas 1  OCR   : 50P/51P (fasa) + 50N/51N (tanah, 3I0)        IEC 60255-151
  Kelas 2  DOCR  : 67P (polarisasi kuadratur 90°, MTA 45°, memori tegangan)
                   67N (polarisasi urutan negatif 32Q, fallback urutan nol 32V)
  Kelas 3a DIST  : 21P/21G mho 3 zona, kompensasi k0, supervisi arus
  Kelas 3b DIFF  : 87L persentase-restraint dua ujung (dengan partner hilir),
                   kanal komunikasi 5 ms. Tanpa partner -> fallback DIST.

Semua elemen membaca fasor terfilter (moving-average 1 siklus = respon DFT penuh).
"""
from __future__ import annotations
import numpy as np
from .der import seq

CURVES = {
    "IEC_SI": (0.14, 0.02, 0.0), "IEC_VI": (13.5, 1.0, 0.0), "IEC_EI": (80.0, 2.0, 0.0),
    "IEEE_MI": (0.0515, 0.02, 0.114), "IEEE_VI": (19.61, 2.0, 0.491), "IEEE_EI": (28.2, 2.0, 0.1217),
}
CURVE_LABEL = {"IEC_SI": "IEC Standard Inverse", "IEC_VI": "IEC Very Inverse",
               "IEC_EI": "IEC Extremely Inverse", "IEEE_MI": "IEEE Moderately Inverse",
               "IEEE_VI": "IEEE Very Inverse", "IEEE_EI": "IEEE Extremely Inverse"}
CLASS_LABEL = {"OCR": "Class 1: OCR 50/51", "DOCR": "Class 2: DOCR 67",
               "DIST": "Class 3: Distance 21", "DIFF": "Class 3: Differential 87L"}


def t_op(curve, tms, M):
    k, alpha, c = CURVES[curve]
    if M <= 1.0:
        return np.inf
    if curve.startswith("IEC"):
        return tms * k / (M ** alpha - 1)
    return tms * (k / (M ** alpha - 1) + c)


def mho_inside(Z, reach, ang):
    if not np.isfinite(Z):
        return False
    Zr = reach * np.exp(1j * ang)
    return abs(Z - Zr / 2) <= abs(Zr) / 2


class IED:
    """Satu titik proteksi; kelas relai dapat diganti, setting tetap."""

    def __init__(self, meta, settings, cls, dt, f0):
        self.meta = meta
        self.id = meta["id"]
        self.s = settings
        self.cls = cls
        if cls == "DIFF" and not meta.get("partner"):
            self.cls = "DIST"
            self.fallback_note = "87L unavailable (no downstream partner); fallback to 21"
        else:
            self.fallback_note = None
        self.dt = dt
        self.ncyc = max(int(round(1.0 / (f0 * dt))), 1)
        self.buf_I = []
        self.buf_V = []
        self.prog = {"51P": [0.0, 0.0, 0.0], "51N": 0.0}
        self.pick = {}
        self.ztimer = [0.0, 0.0, 0.0]
        self.diff_timer = 0.0
        self.vmem = None
        self.tripped = False
        self.trip_time = None
        self.trip_elem = None
        self.events = []
        self.dir_state = {}
        self.last = {}
        self.remote_hist = []
        self.local_hist = []
        self.buf_R = []          # remote current goes through the same one-cycle filter as the local current

    # ---------------------------------------------------------- filter DFT
    def _filt(self, buf, x):
        buf.append(x)
        if len(buf) > self.ncyc:
            buf.pop(0)
        return np.mean(buf, axis=0)

    def _ev(self, t, code, text, kind="info"):
        self.events.append({"t": round(t, 4), "src": "IED", "id": self.id,
                            "type": code, "kind": kind, "text": f"{self.id} {text}"})

    def _set_pick(self, t, key, val, text):
        old = self.pick.get(key, False)
        if val and not old:
            self._ev(t, "PICKUP", f"{key} PICKUP {text}", "pickup")
        elif old and not val:
            self._ev(t, "DROPOUT", f"{key} dropout", "dropout")
        self.pick[key] = val

    # ---------------------------------------------------------- arah
    def dir_phase(self, Iph, V, k):
        """67P kuadratur: Ia vs Vbc, Ib vs Vca, Ic vs Vab. Return +1/-1/0."""
        j, l = (k + 1) % 3, (k + 2) % 3
        Vpol = V[j] - V[l]
        vnom_ll = self.s["vbase"] * np.sqrt(3)
        if abs(Vpol) < 0.05 * vnom_ll:
            if self.vmem is None:
                return 0
            Vpol = self.vmem[j] - self.vmem[l]
        if abs(Iph) < 1e-6:
            return 0
        ang = np.angle(Iph) - np.angle(Vpol) - np.deg2rad(self.s["mta"])
        c = np.cos(ang)
        if c > 0.05:
            return 1
        if c < -0.05:
            return -1
        return 0

    def dir_ground(self, I, V):
        """67N: 32Q (V2,I2) lalu fallback 32V (V0,I0). Return (+1/-1/0, metode, z)."""
        v012, i012 = seq(V), seq(I)
        thL1, thL0 = self.s["ang1"], self.s["ang0"]
        vb = self.s["vbase"]
        if abs(i012[2]) >= self.s["i2min"] and abs(v012[2]) >= 0.005 * vb:
            z2 = np.real(v012[2] * np.conj(i012[2] * np.exp(1j * thL1))) / abs(i012[2]) ** 2
            if z2 < -self.s["zthr"]:
                return 1, "32Q", z2
            if z2 > self.s["zthr"]:
                return -1, "32Q", z2
        if abs(i012[0]) >= self.s["i2min"] and abs(v012[0]) >= 0.005 * vb:
            z0 = np.real(v012[0] * np.conj(i012[0] * np.exp(1j * thL0))) / abs(i012[0]) ** 2
            if z0 < -self.s["zthr"]:
                return 1, "32V", z0
            if z0 > self.s["zthr"]:
                return -1, "32V", z0
        return 0, "indeterminate", np.nan

    # ---------------------------------------------------------- langkah
    def step(self, t, I_raw, V_raw, remote_I=None):
        """Kembalikan True bila IED mengeluarkan perintah trip di langkah ini."""
        I = self._filt(self.buf_I, I_raw)
        V = self._filt(self.buf_V, V_raw)
        vnom = self.s["vbase"]
        if np.min(np.abs(V[self.s["ph_idx"]])) > 0.8 * vnom:
            self.vmem = V.copy()
        self.last = {"I": I, "V": V}
        if self.tripped:
            return False
        c = self.cls
        if c in ("OCR", "DOCR"):
            return self._step_oc(t, I, V, directional=(c == "DOCR"))
        if c == "DIST":
            return self._step_dist(t, I, V)
        if c == "DIFF":
            return self._step_diff(t, I, V, remote_I)
        return False

    def _trip(self, t, elem, detail=""):
        self.tripped = True
        self.trip_time = t
        self.trip_elem = elem
        self._ev(t, "TRIP", f"TRIP {elem} {detail}".strip(), "trip")
        return True

    def _step_oc(self, t, I, V, directional):
        s = self.s
        dt = self.dt
        mags = np.abs(I)
        I3 = np.abs(np.sum(I))
        pfx = "67" if directional else "5"
        # arah
        dP = [1, 1, 1]
        dN, meth, z = 1, "-", np.nan
        if directional:
            dP = [self.dir_phase(I[k], V, k) for k in range(3)]
            dN, meth, z = self.dir_ground(I, V)
        self.dir_state = {"P": dP, "N": dN, "Nmeth": meth, "Nz": z}
        # ---- fasa
        for k in s["ph_idx"]:
            M = mags[k] / s["51P_pu"]
            picked = M > 1.0
            name = f"{'67' if directional else '51'}P-{'ABC'[k]}"
            if picked and directional:
                d = dP[k]
                key = f"DIR-P{'ABC'[k]}"
                prev = self.dir_state.get(key)
                if self.pick.get(name + "_dir") != d:
                    self._ev(t, "DIR", f"67P-{'ABC'[k]} direction: {'FORWARD' if d > 0 else 'REVERSE' if d < 0 else 'INDETERMINATE'}"
                             f"{' (blocked)' if d <= 0 else ''}", "dir")
                    self.pick[name + "_dir"] = d
            enable = (dP[k] > 0) if directional else True
            self._set_pick(t, name, picked, f"|I{'abc'[k]}|={mags[k]:.0f} A (M={M:.2f})")
            if picked and enable:
                self.prog["51P"][k] += dt / t_op(s["curve"], s["51P_tms"], M)
                if self.prog["51P"][k] >= 1.0:
                    return self._trip(t, name, f"t_op={t_op(s['curve'], s['51P_tms'], M):.3f}s")
            else:
                self.prog["51P"][k] = 0.0
            if s.get("50P_pu") and mags[k] > s["50P_pu"] and enable:
                return self._trip(t, f"{'67' if directional else '50'}P-{'ABC'[k]} (inst)", f"|I|={mags[k]:.0f} A > {s['50P_pu']:.0f} A")
        # ---- tanah
        if not s.get("51N_pu"):
            return False
        M = I3 / s["51N_pu"]
        picked = M > 1.0
        nameN = f"{'67' if directional else '51'}N"
        self._set_pick(t, nameN, picked, f"3I0={I3:.1f} A (M={M:.2f})")
        if picked and directional and self.pick.get("N_dir") != dN:
            self._ev(t, "DIR", f"67N direction ({meth}): {'FORWARD' if dN > 0 else 'REVERSE' if dN < 0 else 'INDETERMINATE'}"
                     f"{' (blocked)' if dN <= 0 else ''}", "dir")
            self.pick["N_dir"] = dN
        enN = (dN > 0) if directional else True
        if picked and enN:
            self.prog["51N"] += dt / t_op(s["curve"], s["51N_tms"], M)
            if self.prog["51N"] >= 1.0:
                return self._trip(t, nameN, f"t_op={t_op(s['curve'], s['51N_tms'], M):.3f}s")
        else:
            self.prog["51N"] = 0.0
        if s.get("50N_pu") and I3 > s["50N_pu"] and enN:
            return self._trip(t, f"{'67' if directional else '50'}N (inst)", f"3I0={I3:.0f} A")
        return False

    def loops(self, I, V):
        s = self.s
        k0 = s["k0"]
        I0x3 = np.sum(I)
        out = {}
        phs = s["ph_idx"]
        for k in phs:
            den = I[k] + k0 * I0x3
            out["ABC"[k] + "G"] = V[k] / den if abs(den) > 1e-3 else complex(np.inf)
        for (p, q) in ((0, 1), (1, 2), (2, 0)):
            if p in phs and q in phs:
                den = I[p] - I[q]
                out["ABC"[p] + "ABC"[q]] = (V[p] - V[q]) / den if abs(den) > 1e-3 else complex(np.inf)
        return out

    def _step_dist(self, t, I, V):
        s = self.s
        dt = self.dt
        Z = self.loops(I, V)
        I0x3 = abs(np.sum(I))
        zones_hit = [False, False, False]
        loop_zone = {}
        for name, z in Z.items():
            if len(name) == 2 and name[1] == "G":
                k = "ABC".index(name[0])
                sup = abs(I[k]) > s["fd_ph"] and I0x3 > s["fd_g"]
            else:
                p, q = "ABC".index(name[0]), "ABC".index(name[1])
                sup = abs(I[p] - I[q]) > s["fd_ph"]
            zl = 0
            if sup:
                for zi in range(3):
                    if mho_inside(z, s["zreach"][zi], s["ang1"]):
                        zones_hit[zi] = True
                        zl = zi + 1
                        break
            loop_zone[name] = zl
        self.last["Z"] = {k: [float(np.real(v)), float(np.imag(v))] if np.isfinite(v) else None for k, v in Z.items()}
        self.last["zone"] = loop_zone
        for zi in range(3):
            key = f"21-Z{zi+1}"
            inzone = zones_hit[zi] or any(zones_hit[:zi])
            self._set_pick(t, key, zones_hit[zi], "loop " + ",".join([n for n, zz in loop_zone.items() if zz == zi + 1]))
            if inzone:
                self.ztimer[zi] += dt
                if self.ztimer[zi] >= s["ztime"][zi] - 1e-9:
                    return self._trip(t, key, f"(t_zone={s['ztime'][zi]:.2f}s)")
            else:
                self.ztimer[zi] = 0.0
        return False

    def _step_diff(self, t, I, V, remote_I):
        s = self.s
        # Both ends must use the same phasor filter; comparing a filtered local current with a raw
        # remote current creates a false differential current during every fault transient.
        Rf = self._filt(self.buf_R, remote_I if remote_I is not None else np.zeros(3, complex))
        self.remote_hist.append(Rf)
        nd = max(int(round(0.005 / self.dt)), 1)
        Ir = self.remote_hist[-nd - 1] if len(self.remote_hist) > nd else self.remote_hist[0]
        if len(self.remote_hist) > nd + 2:
            self.remote_hist.pop(0)
        # Time alignment: the remote sample arrives one channel delay late, so it is compared with
        # the local sample taken at the same instant (as line differential relays do), not the newest one.
        self.local_hist.append(I)
        Il = self.local_hist[-nd - 1] if len(self.local_hist) > nd else self.local_hist[0]
        if len(self.local_hist) > nd + 2:
            self.local_hist.pop(0)
        I = Il
        Idiff = I - Ir
        Irest = (np.abs(I) + np.abs(Ir)) / 2
        op = [abs(Idiff[k]) > max(s["87_pu"], s["87_slope"] * Irest[k]) for k in range(3)]
        self.last["Idiff"] = np.abs(Idiff)
        self.last["Irest"] = Irest
        anyop = any(op[k] for k in s["ph_idx"])
        self._set_pick(t, "87L", anyop, "Idiff=" + "/".join(f"{abs(Idiff[k]):.0f}" for k in range(3)) + " A")
        if anyop:
            self.diff_timer += self.dt
            if self.diff_timer >= s["87_delay"]:
                return self._trip(t, "87L", "(transfer trip ke ujung partner)")
        else:
            self.diff_timer = 0.0
        return False

    def status(self):
        st = {"cls": self.cls, "tripped": self.tripped, "pick": {k: v for k, v in self.pick.items() if isinstance(v, bool)}}
        if self.cls == "DOCR":
            st["dir"] = {"P": self.dir_state.get("P"), "N": self.dir_state.get("N"), "Nmeth": self.dir_state.get("Nmeth")}
        if self.cls == "DIST" and "Z" in self.last:
            st["Z"] = self.last["Z"]
            st["zone"] = self.last.get("zone")
        return st
