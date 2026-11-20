"""
Model DER (DoF-1) untuk engine fasor.

  SG      : Generator sinkron, sumber E'' konstan di belakang reaktansi X(t)
            (X'' -> X' -> Xd) selama gangguan — komponen AC meluruh ala IEC 60909.
  IBR-GFL : Inverter grid-following = sumber arus terbatas (Imax ~1.1-1.5 pu),
            referensi sudut dari PLL (tegangan urutan positif langkah sebelumnya),
            dinamika orde-1 (tau ~ 1 siklus). Mode FRT: prioritas P atau prioritas Q
            (IEEE 2800). Arus urutan negatif opsional, momentary cessation opsional.
  IBR-GFM : Inverter grid-forming = sumber tegangan di belakang impedansi virtual,
            dengan pembatas arus (beralih ke sumber arus saat > Imax).

Jalur urutan nol ditentukan trafo interkoneksi:
  'YgD'  -> sisi jaringan Y-grounded / sisi DER delta  => sumber arus urutan nol
  'DYg' / 'ungrounded' -> tidak ada jalur urutan nol dari DER.
"""
from __future__ import annotations
import numpy as np

a = np.exp(2j * np.pi / 3)
A = np.array([[1, 1, 1], [1, a * a, a], [1, a, a * a]])
Ainv = np.linalg.inv(A)
POS = np.array([1, a * a, a])           # vektor fasa urutan positif


def seq(v):
    return Ainv @ v


def abc_from_seq(v012):
    return A @ v012


def Yabc_from_seq(y0, y1, y2):
    return A @ np.diag([y0, y1, y2]) @ Ainv


# Kategori ride-through IEEE 1547-2018 (disederhanakan: UV1/UV2, OV)
RIDE_THROUGH = {
    "I":   {"uv2": (0.45, 0.16), "uv1": (0.70, 2.0)},
    "II":  {"uv2": (0.45, 0.16), "uv1": (0.70, 10.0)},
    "III": {"uv2": (0.50, 2.0),  "uv1": (0.88, 21.0)},
}


class DER:
    """Basis umum."""

    def __init__(self, cfg, vbase_ph, f0):
        self.cfg = cfg
        self.id = cfg["id"]
        self.bus = cfg["bus"]
        self.type = cfg["type"]
        self.S = cfg["kva"] * 1e3                       # VA
        self.vbase = vbase_ph
        self.Zbase = (3 * vbase_ph ** 2) / max(self.S, 1.0)
        self.Ibase = self.S / (3 * vbase_ph)
        self.p_set = cfg.get("p_pu", 1.0)               # pu dari S
        self.q_set = cfg.get("q_pu", 0.0)
        self.online = cfg.get("online", True) and self.S > 0
        self.trip_reason = None
        self.ground = cfg.get("xfmr", "YgD")
        self.ztx = complex(cfg.get("ztx_r", 0.01), cfg.get("ztx_x", 0.06)) * self.Zbase
        self.rt = RIDE_THROUGH.get(cfg.get("rt_cat", "III"), RIDE_THROUGH["III"])
        self.uv_timer = {"uv1": 0.0, "uv2": 0.0}
        self.island_timer = 0.0
        self.t_anti_island = cfg.get("t_anti_island", 2.0)
        self.trip_at = cfg.get("trip_at")               # trip manual (detik)
        self.irr = cfg.get("irradiance")                # [[t, G], ...] W/m2
        # log keluaran terakhir
        self.I_abc = np.zeros(3, complex)
        self.mode_txt = "normal"

    # --- urutan nol dari trafo interkoneksi (shunt admitansi)
    def y0(self):
        if self.ground == "YgD" and self.online:
            return 1.0 / self.ztx
        return 0.0

    def irradiance(self, t):
        if not self.irr:
            return 1000.0
        pts = sorted(self.irr)
        ts = [p[0] for p in pts]
        gs = [p[1] for p in pts]
        return float(np.interp(t, ts, gs))

    def p_avail(self, t):
        if self.type.startswith("IBR") and self.cfg.get("source", "PV") == "PV":
            return self.p_set * self.irradiance(t) / 1000.0
        return self.p_set

    def protection(self, t, dt, v1pu, islanded_unintentional, events):
        """Proteksi DER (UV ride-through, anti-islanding, trip manual)."""
        if not self.online:
            return
        if self.trip_at is not None and t >= self.trip_at:
            self._trip(t, "Manual trip or internal DER fault (scenario)", events)
            return
        for key in ("uv2", "uv1"):
            lvl, tmax = self.rt[key]
            if v1pu < lvl:
                self.uv_timer[key] += dt
                if self.uv_timer[key] >= tmax:
                    self._trip(t, f"Undervoltage protection {key.upper()} (V1={v1pu:.2f} pu < {lvl} pu for {tmax} s)", events)
                    return
            else:
                self.uv_timer[key] = 0.0
        if islanded_unintentional:
            self.island_timer += dt
            if self.island_timer >= self.t_anti_island:
                self._trip(t, f"Anti-islanding (unintentional island > {self.t_anti_island} s)", events)
        else:
            self.island_timer = 0.0

    def _trip(self, t, reason, events):
        self.online = False
        self.trip_reason = reason
        events.append({"t": t, "src": "DER", "id": self.id, "type": "DER_TRIP",
                       "text": f"{self.id} at bus {self.bus} TRIP: {reason}"})


class SG(DER):
    def __init__(self, cfg, vbase_ph, f0):
        super().__init__(cfg, vbase_ph, f0)
        self.xdpp = cfg.get("xdpp", 0.15)
        self.xdp = cfg.get("xdp", 0.25)
        self.xd = cfg.get("xd", 1.0)
        self.tdpp = cfg.get("tdpp", 0.03)
        self.tdp = cfg.get("tdp", 0.6)
        self.ra = cfg.get("ra", 0.01)
        self.H = cfg.get("H", 1.0)
        self.E1 = 0j
        self.t_fault0 = None

    def x_t(self, t):
        if self.t_fault0 is None:
            return self.xdpp
        tau = max(t - self.t_fault0, 0.0)
        return (self.xd + (self.xdp - self.xd) * np.exp(-tau / self.tdp)
                + (self.xdpp - self.xdp) * np.exp(-tau / self.tdpp))

    def z1(self, t):
        return complex(self.ra, self.x_t(t)) * self.Zbase + self.ztx

    def admittance(self, t):
        if not self.online:
            return None
        y1 = 1.0 / self.z1(t)
        return Yabc_from_seq(self.y0(), y1, y1)

    def injection(self, t):
        if not self.online:
            return np.zeros(3, complex)
        return (self.E1 / self.z1(t)) * POS

    def init_from(self, V_abc, t):
        V1 = seq(V_abc)[1]
        S = complex(self.p_set, self.q_set) * self.S
        I1 = np.conj(S / (3 * V1)) if abs(V1) > 1 else 0
        self.E1 = V1 + (complex(self.ra, self.xdpp) * self.Zbase + self.ztx) * I1

    def update(self, t, dt, V_abc, fault_active):
        if fault_active and self.t_fault0 is None:
            self.t_fault0 = t
        if not fault_active:
            self.t_fault0 = None
        self.mode_txt = "subtransient/transient" if self.t_fault0 is not None else "normal"

    def current_out(self, t, V_abc):
        if not self.online:
            return np.zeros(3, complex)
        Y = self.admittance(t)
        return self.injection(t) - Y @ V_abc


class IBR_GFL(DER):
    def __init__(self, cfg, vbase_ph, f0):
        super().__init__(cfg, vbase_ph, f0)
        self.imax = cfg.get("imax", 1.2)
        self.frt = cfg.get("frt", "Q")                  # 'P' prioritas aktif, 'Q' prioritas reaktif
        self.kq = cfg.get("kq", 2.0)
        self.neg_seq = cfg.get("neg_seq", False)
        self.k2 = cfg.get("k2", 2.0)
        self.mc = cfg.get("momentary_cessation", False)
        self.mc_v = cfg.get("mc_v", 0.5)
        self.tau = cfg.get("tau", 1.0 / 60.0)
        self.I1 = 0j                                    # arus urutan positif aktual (A, generator conv.)
        self.I2 = 0j
        self.ceased = False

    def admittance(self, t):
        if not self.online:
            return None
        y0 = self.y0()
        if y0 == 0:
            return None
        return Yabc_from_seq(y0, 0, 0)

    def init_from(self, V_abc, t):
        V1 = seq(V_abc)[1]
        S = complex(self.p_avail(t), self.q_set) * self.S
        self.I1 = np.conj(S / (3 * V1)) if abs(V1) > 1 else 0j
        self.I2 = 0j

    def target(self, t, V_abc):
        v012 = seq(V_abc)
        V1, V2 = v012[1], v012[2]
        v1pu = abs(V1) / self.vbase
        ang = np.angle(V1) if abs(V1) > 1e-3 * self.vbase else 0.0
        if self.mc:
            if v1pu < self.mc_v:
                self.ceased = True
            elif v1pu > self.mc_v + 0.05:
                self.ceased = False
        if self.ceased:
            self.mode_txt = "momentary cessation"
            return 0j, 0j
        P = self.p_avail(t)                                  # pu
        if v1pu >= 0.9:
            ip = P / max(v1pu, 0.5)
            iq = -self.q_set / max(v1pu, 0.5)               # Q>0 => arus tertinggal
            self.mode_txt = "normal (PQ)"
        else:
            if self.frt == "P":
                ip = min(P / max(v1pu, 0.05), self.imax)
                iq = 0.0
                self.mode_txt = "FRT prioritas-P"
            else:
                iq_mag = min(self.imax, self.kq * (0.9 - v1pu) + max(self.q_set, 0))
                ip = min(P / max(v1pu, 0.05), np.sqrt(max(self.imax ** 2 - iq_mag ** 2, 0)))
                iq = -iq_mag
                self.mode_txt = "FRT prioritas-Q (IEEE 2800)"
        mag = np.hypot(ip, iq)
        if mag > self.imax:
            ip, iq = ip * self.imax / mag, iq * self.imax / mag
        I1 = complex(ip, iq) * self.Ibase * np.exp(1j * ang)
        I2 = 0j
        if self.neg_seq and v1pu < 0.9:
            v2pu = abs(V2) / self.vbase
            i2 = min(self.k2 * v2pu, max(self.imax - abs(complex(ip, iq)), 0.0))
            I2 = 1j * i2 * self.Ibase * np.exp(1j * np.angle(V2))    # I2 mendahului V2 90° (perilaku induktif seperti SG)
        return I1, I2

    def update(self, t, dt, V_abc, fault_active):
        if not self.online:
            self.I1 = self.I2 = 0j
            return
        I1t, I2t = self.target(t, V_abc)
        k = 1 - np.exp(-dt / self.tau)
        self.I1 += (I1t - self.I1) * k
        self.I2 += (I2t - self.I2) * k
        # batas arus per fasa
        Iabc = abc_from_seq(np.array([0, self.I1, self.I2]))
        m = np.max(np.abs(Iabc)) / (self.imax * self.Ibase)
        if m > 1:
            self.I1 /= m
            self.I2 /= m

    def injection(self, t):
        if not self.online:
            return np.zeros(3, complex)
        return abc_from_seq(np.array([0, self.I1, self.I2]))

    def current_out(self, t, V_abc):
        if not self.online:
            return np.zeros(3, complex)
        I = self.injection(t)
        Y = self.admittance(t)
        if Y is not None:
            I = I - Y @ V_abc
        return I


class IBR_GFM(DER):
    def __init__(self, cfg, vbase_ph, f0):
        super().__init__(cfg, vbase_ph, f0)
        self.imax = cfg.get("imax", 1.3)
        self.zv = complex(cfg.get("rv", 0.02), cfg.get("xv", 0.15))
        self.E1 = 0j
        self.limited = False
        self.Ilim = np.zeros(3, complex)
        self.H = cfg.get("H", 0.5)   # inersia virtual

    def z1(self):
        return self.zv * self.Zbase + self.ztx

    def admittance(self, t):
        if not self.online:
            return None
        if self.limited:
            y0 = self.y0()
            return Yabc_from_seq(y0, 0, 0) if y0 else None
        y1 = 1.0 / self.z1()
        return Yabc_from_seq(self.y0(), y1, y1)

    def injection(self, t):
        if not self.online:
            return np.zeros(3, complex)
        if self.limited:
            return self.Ilim
        return (self.E1 / self.z1()) * POS

    def init_from(self, V_abc, t):
        V1 = seq(V_abc)[1]
        S = complex(self.p_avail(t), self.q_set) * self.S
        I1 = np.conj(S / (3 * V1)) if abs(V1) > 1 else 0
        self.E1 = V1 + self.z1() * I1

    def check_limit(self, t, V_abc):
        """Kembalikan True bila perlu solve ulang dengan mode terbatas."""
        if not self.online:
            return False
        if self.limited:
            return False
        I = (self.E1 / self.z1()) * POS - Yabc_from_seq(0, 1 / self.z1(), 1 / self.z1()) @ V_abc
        m = np.max(np.abs(I)) / (self.imax * self.Ibase)
        if m > 1.0:
            self.limited = True
            self.Ilim = I / m
            self.mode_txt = "batas arus (current-limited)"
            return True
        return False

    def update(self, t, dt, V_abc, fault_active):
        # kembali ke mode tegangan saat gangguan hilang
        if self.limited and not fault_active:
            self.limited = False
        if not self.limited:
            self.mode_txt = "grid-forming"

    def current_out(self, t, V_abc):
        if not self.online:
            return np.zeros(3, complex)
        I = self.injection(t)
        Y = self.admittance(t)
        if Y is not None:
            I = I - Y @ V_abc
        return I


def make_der(cfg, vbase_ph, f0):
    t = cfg["type"]
    if t == "SG":
        return SG(cfg, vbase_ph, f0)
    if t == "IBR-GFM":
        return IBR_GFM(cfg, vbase_ph, f0)
    return IBR_GFL(cfg, vbase_ph, f0)
