#!/usr/bin/env python3
"""
SimRELAY: laporan PDF Post-Run (Proof of Urgency), bahasa Indonesia.

    python report.py        menulis batch/Laporan_PostRun_SimRELAY.pdf

Membaca batch/results.jsonl, batch/postrun_summary.json dan batch/figures/report/*.png
(jalankan batch.py lalu postrun.py terlebih dahulu). Semua angka di dalam teks dihitung
langsung dari data, sehingga laporan selalu konsisten dengan hasil simulasi.
"""
from __future__ import annotations
import json
import os
import pickle
import re
import sys
import time
from collections import Counter, defaultdict

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Frame, Image, KeepTogether, NextPageTemplate, PageBreak,
                                PageTemplate, Paragraph, Spacer, Table, TableStyle, CondPageBreak)
from reportlab.platypus.tableofcontents import TableOfContents

ROOT = os.path.dirname(os.path.abspath(__file__))
BATCH = os.path.join(ROOT, "batch")
FIGR = os.path.join(BATCH, "figures", "report")
OUT = os.path.join(BATCH, "Laporan_PostRun_SimRELAY.pdf")

CODES = ["F-1", "F-2", "F-3", "F-4", "F-5"]
ALL = CODES + ["NT"]
PENS = [0, 20, 40, 60, 80, 100, 120]
NAMA = {"F-1": "Blinding of Protection", "F-2": "Sympathetic Tripping", "F-3": "Miscoordination dan pelanggaran CTI",
        "F-4": "Directional Misidentification", "F-5": "Impedance Under-reach", "NT": "Nuisance trip sebelum gangguan"}
KELAS = {"OCR": "OCR 50/51", "DOCR": "DOCR 67", "DIST": "Distance 21", "DIFF": "Differential 87L"}
BULAN = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November", "Desember"]

# ------------------------------------------------------------------ fonts & styles
FD = "C:/Windows/Fonts"
pdfmetrics.registerFont(TTFont("Arial", os.path.join(FD, "arial.ttf")))
pdfmetrics.registerFont(TTFont("Arial-Bold", os.path.join(FD, "arialbd.ttf")))
pdfmetrics.registerFont(TTFont("Arial-Italic", os.path.join(FD, "ariali.ttf")))
pdfmetrics.registerFont(TTFont("Arial-BoldItalic", os.path.join(FD, "arialbi.ttf")))
from reportlab.pdfbase.pdfmetrics import registerFontFamily  # noqa: E402
registerFontFamily("Arial", normal="Arial", bold="Arial-Bold", italic="Arial-Italic", boldItalic="Arial-BoldItalic")

INK = colors.HexColor("#0f172a")
INK2 = colors.HexColor("#475569")
MUTED = colors.HexColor("#64748b")
LINE = colors.HexColor("#d9dee6")
ACC = colors.HexColor("#2563eb")
SOFT = colors.HexColor("#eff4ff")
ZEBRA = colors.HexColor("#f6f8fb")

ST = {
    "body": ParagraphStyle("body", fontName="Arial", fontSize=10.5, leading=15.5, textColor=INK, alignment=TA_JUSTIFY, spaceAfter=7),
    "bullet": ParagraphStyle("bullet", fontName="Arial", fontSize=10.5, leading=15, textColor=INK, alignment=TA_JUSTIFY,
                             leftIndent=14, bulletIndent=3, spaceAfter=3),
    "h1": ParagraphStyle("h1", fontName="Arial-Bold", fontSize=15, leading=20, textColor=INK, spaceBefore=6, spaceAfter=10),
    "h2": ParagraphStyle("h2", fontName="Arial-Bold", fontSize=12, leading=16, textColor=INK, spaceBefore=10, spaceAfter=6),
    "cap": ParagraphStyle("cap", fontName="Arial", fontSize=9, leading=12.5, textColor=INK2, alignment=TA_JUSTIFY, spaceBefore=4, spaceAfter=12),
    "tcap": ParagraphStyle("tcap", fontName="Arial-Bold", fontSize=9.5, leading=13, textColor=INK, spaceBefore=6, spaceAfter=4),
    "cell": ParagraphStyle("cell", fontName="Arial", fontSize=8.6, leading=11, textColor=INK),
    "cellb": ParagraphStyle("cellb", fontName="Arial-Bold", fontSize=8.6, leading=11, textColor=INK),
    "note": ParagraphStyle("note", fontName="Arial", fontSize=9.5, leading=13.5, textColor=INK, backColor=SOFT,
                           borderPadding=(7, 9, 7, 9), spaceBefore=6, spaceAfter=12, alignment=TA_JUSTIFY),
    "toc1": ParagraphStyle("toc1", fontName="Arial-Bold", fontSize=10.5, leading=17, textColor=INK),
    "toc2": ParagraphStyle("toc2", fontName="Arial", fontSize=10, leading=15, leftIndent=16, textColor=INK2),
}


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def P(text, st="body"):
    return Paragraph(text, ST[st])


def bullets(items):
    return [Paragraph(t, ST["bullet"], bulletText="•") for t in items]


def pct(v, d=1):
    return "N/A" if v is None else f"{v:.{d}f}%".replace(".", ",")


def num(v, d=2):
    return "N/A" if v is None else f"{v:.{d}f}".replace(".", ",")


def ribu(n):
    return f"{n:,}".replace(",", ".")


def tbl(head, rows, widths, align_right_from=1, font=8.6):
    data = [[Paragraph(f"<b>{h}</b>", ST["cell"]) for h in head]] + [[Paragraph(str(c), ST["cell"]) for c in r] for r in rows]
    t = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    style = [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2f7")),
             ("LINEBELOW", (0, 0), (-1, 0), 0.8, LINE), ("LINEBELOW", (0, -1), (-1, -1), 0.8, LINE),
             ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
             ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5)]
    for i in range(1, len(data)):
        if i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), ZEBRA))
    t.setStyle(TableStyle(style))
    return t


class Counters:
    fig = 0
    tab = 0


def figure(name, caption, width=170 * mm):
    path = os.path.join(FIGR, f"{name}.png")
    from reportlab.lib.utils import ImageReader
    iw, ih = ImageReader(path).getSize()
    Counters.fig += 1
    img = Image(path, width=width, height=width * ih / iw)
    return KeepTogether([img, P(f"<b>Gambar {Counters.fig}.</b> {caption}", "cap")])


def table_block(title, head, rows, widths, note=None):
    Counters.tab += 1
    items = [P(f"Tabel {Counters.tab}. {title}", "tcap"), tbl(head, rows, widths)]
    if note:
        items.append(P(note, "cap"))
    else:
        items.append(Spacer(1, 8))
    return KeepTogether(items)


# ------------------------------------------------------------------ document
class Doc(BaseDocTemplate):
    def __init__(self, path, **kw):
        super().__init__(path, pagesize=A4, leftMargin=22 * mm, rightMargin=22 * mm, topMargin=22 * mm, bottomMargin=20 * mm,
                         title="Laporan Post-Run SimRELAY: Proof of Urgency", author="SimRELAY",
                         subject="Hasil simulasi batch relai konvensional pada IEEE 34 Bus dengan penetrasi DER", **kw)
        fr = Frame(self.leftMargin, self.bottomMargin, self.width, self.height, id="f")
        self.addPageTemplates([PageTemplate("cover", [fr], onPage=self._cover), PageTemplate("body", [fr], onPage=self._page)])
        self._h = 0

    def _cover(self, c, d):
        c.saveState()
        c.setFillColor(ACC)
        c.rect(0, A4[1] - 14 * mm, A4[0], 14 * mm, stroke=0, fill=1)
        c.rect(0, 0, A4[0], 6 * mm, stroke=0, fill=1)
        c.restoreState()

    def _page(self, c, d):
        c.saveState()
        c.setFont("Arial", 8.5)
        c.setFillColor(MUTED)
        c.drawString(self.leftMargin, A4[1] - 13 * mm, "Laporan Post-Run SimRELAY: Proof of Urgency")
        c.drawRightString(A4[0] - self.rightMargin, A4[1] - 13 * mm, "Tugas Akhir 18023047")
        c.setStrokeColor(LINE)
        c.setLineWidth(0.6)
        c.line(self.leftMargin, A4[1] - 15 * mm, A4[0] - self.rightMargin, A4[1] - 15 * mm)
        c.drawCentredString(A4[0] / 2, 11 * mm, f"{d.page}")
        c.restoreState()

    def afterFlowable(self, f):
        if isinstance(f, Paragraph) and f.style.name in ("h1", "h2"):
            txt = f.getPlainText()
            lvl = 0 if f.style.name == "h1" else 1
            key = "h" + re.sub(r"[^A-Za-z0-9]", "", txt)[:40]     # stable across multiBuild passes
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(txt, key, level=lvl, closed=False)
            self.notify("TOCEntry", (lvl, txt, self.page, key))


def H1(t):
    return P(t, "h1")


def H2(t):
    return P(t, "h2")


# ------------------------------------------------------------------ data
def load():
    rows = {}
    with open(os.path.join(BATCH, "results.jsonl")) as f:
        for line in f:
            try:
                r = json.loads(line)
                rows[r["key"]] = r
            except Exception:
                pass
    R = list(rows.values())
    with open(os.path.join(BATCH, "postrun_summary.json")) as f:
        S = json.load(f)
    with open(os.path.join(ROOT, "cache", "settings.pkl"), "rb") as f:
        SET = pickle.load(f)[0]
    wall = None
    for log in (os.path.join(BATCH, "batch_log.txt"), os.path.join(BATCH, "batch_log2.txt")):
        if os.path.exists(log):
            m = re.findall(r"finished in ([\d.]+) min", open(log, encoding="utf-8", errors="ignore").read())
            if m:
                wall = (wall or 0) + float(m[-1])
    return R, S, SET, wall


def failed(r):
    return any(r["counts"].get(c, 0) for c in ALL)


def rate(rows):
    return 100.0 * sum(failed(r) for r in rows) / len(rows) if rows else None


def build():
    R, S, SET, wall = load()
    story = []
    today = time.localtime()
    tanggal = f"{today.tm_mday} {BULAN[today.tm_mon - 1]} {today.tm_year}"
    C, H, T, E, X, RO = S["confusion"], S["heatmap"], S["tcc"], S["escalation"], S["rx"], S["rose"]
    n = S["runs"]
    nfail = S["failed_runs"]
    camp = S["by_campaign"]
    ocr_grid = [r for r in R if r["cls"] == "OCR" and r["campaign"] in ("H1", "H2")]
    peak = H["load"]["rate"][2]
    tip = H["tipping_point_pen"]
    by_code_runs = {c: sum(1 for r in R if r["counts"].get(c, 0)) for c in ALL}
    diff0 = E.get("DIFF|0", {}).get("any", 0)
    esc_any = {k: E.get(f"{k}|120", {}).get("any") for k in ("OCR", "DOCR", "DIST", "DIFF")}

    # ============================================================ cover
    story += [Spacer(1, 38 * mm),
              Paragraph("LAPORAN HASIL SIMULASI BATCH", ParagraphStyle("k", fontName="Arial-Bold", fontSize=11, textColor=ACC, leading=14)),
              Spacer(1, 6),
              Paragraph("Pembuktian Urgensi Relai Adaptif: Kegagalan Relai Konvensional akibat Penetrasi DER pada IEEE 34 Node Test Feeder",
                        ParagraphStyle("t", fontName="Arial-Bold", fontSize=22, leading=29, textColor=INK)),
              Spacer(1, 10),
              Paragraph("Post-Run Visualization dari pengujian Software-in-the-Loop (SIL) menggunakan test bench SimRELAY",
                        ParagraphStyle("s", fontName="Arial", fontSize=12.5, leading=18, textColor=INK2)),
              Spacer(1, 26 * mm)]
    meta = [["Dokumen", "Laporan Post-Run (Proof of Urgency)"], ["Konteks", "Tugas Akhir 18023047"],
            ["Jaringan uji", "IEEE 34 Node Test Feeder dan Penyulang B ekuivalen, 24,9 kV, 60 Hz"],
            ["Jumlah kasus", f"{ribu(n)} simulasi"], ["Tanggal", tanggal]]
    mt = Table([[Paragraph(f"<b>{a}</b>", ST["cell"]), Paragraph(b, ST["cell"])] for a, b in meta], colWidths=[38 * mm, 120 * mm], hAlign="LEFT")
    mt.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, 0), 0.8, LINE), ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
                            ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    story += [mt, NextPageTemplate("body"), PageBreak()]

    # ============================================================ TOC
    toc = TableOfContents()
    toc.levelStyles = [ST["toc1"], ST["toc2"]]
    toc.dotsMinLevel = 0
    story += [Paragraph("Daftar Isi", ST["h1"].clone("tochead")), Spacer(1, 4), toc, PageBreak()]

    # ============================================================ ringkasan
    story.append(H1("Ringkasan Eksekutif"))
    base_rate = H["baseline_rate"]
    story.append(P(f"Laporan ini menyajikan hasil {ribu(n)} simulasi batch yang menguji relai proteksi konvensional dengan setting beku "
                   f"(dihitung satu kali pada kondisi 0% DER dan beban puncak malam) terhadap variasi penetrasi Distributed Energy Resources (DER) "
                   f"dari 0% hingga 120% beban puncak Penyulang A. Tujuannya adalah membuktikan secara kuantitatif bahwa relai berlogika konvensional "
                   f"tidak lagi andal ketika DER terhubung, sehingga relai adaptif menjadi kebutuhan yang mendesak."))
    story += bullets([
        f"Tanpa DER, relai OCR, DOCR 67, dan Distance 21 bekerja benar pada seluruh kasus (laju kegagalan <b>{pct(base_rate, 0)}</b>). Setting baseline "
        f"terbukti terkoordinasi dengan benar, sehingga kegagalan yang muncul berasal dari kondisi DER dan jaringan, bukan dari setting yang buruk. "
        f"Satu-satunya kegagalan baseline terjadi pada kelas 87L ({pct(diff0, 1)}, satu kasus) karena lateral 822 berada di dalam zona diferensial A1 ke A2.",
        f"Secara keseluruhan <b>{ribu(nfail)} dari {ribu(n)} kasus ({pct(100 * nfail / n)})</b> mengalami minimal satu salah kerja (F-1 sampai F-5, atau "
        f"trip sebelum gangguan/NT).",
        f"Pada beban puncak malam, laju kegagalan naik dari {pct(peak[0], 0)} (0% DER) menjadi <b>{pct(peak[-1], 0)}</b> pada 120% DER"
        + (f", dengan titik kritis (tipping point) pada penetrasi <b>{tip}%</b>." if tip is not None else "."),
        f"Dependability relai OCR turun dari {pct(100 * C['baseline']['dependability'])} menjadi <b>{pct(100 * C['der']['dependability'])}</b>, "
        f"dan security turun dari {pct(100 * C['baseline']['security'])} menjadi <b>{pct(100 * C['der']['security'])}</b> setelah DER terhubung.",
        f"Menaikkan kelas relai dengan setting tetap tidak menghilangkan kegagalan. Pada 120% DER, laju kegagalan per kelas adalah "
        + ", ".join(f"{KELAS[k]} {pct(esc_any[k], 1)}" for k in ("OCR", "DOCR", "DIST", "DIFF"))
        + ". Distance 21 menurunkan laju kegagalan paling besar tetapi tetap mengalami under-reach (F-5), DOCR 67 memunculkan salah arah (F-4), "
          "dan 87L memunculkan trip sebelum gangguan (NT) ketika DER berada di dalam zona diferensial.",
        f"Bukti geometris: dengan infeed DER di antara relai dan gangguan, median impedansi terukur relai {X['ied']} naik dari "
        f"{num(X['by_pen']['0'])} Ω menjadi {num(X['by_pen']['120'])} Ω, melewati jangkauan Zona 1 ({num(X['zreach'][0])} Ω) (F-5). Untuk gangguan di "
        f"belakang relai berarah, {pct(RO['IBR']['forward_pct'], 0)} sampel fasa dengan DER berbasis inverter terbaca FORWARD, dibandingkan "
        f"{pct(RO['SG']['forward_pct'], 0)} dengan generator sinkron (F-4).",
    ])
    story.append(P("Kesimpulan utama: penetrasi DER menyebabkan salah kerja relai konvensional yang terukur dan meningkat seiring penetrasi. "
                   "Kegagalan tersebut tidak dapat dihilangkan hanya dengan mengganti kelas relai bersetting tetap, sehingga diperlukan relai yang "
                   "mampu menyesuaikan setting dan logikanya terhadap kondisi DER dan jaringan secara waktu nyata.", "note"))
    story.append(PageBreak())

    # ============================================================ 1 pendahuluan
    story.append(H1("1. Pendahuluan"))
    story.append(H2("1.1 Latar Belakang dan Tujuan"))
    story.append(P("Pengembangan relai adaptif untuk sistem distribusi dengan penetrasi DER memerlukan bukti awal bahwa relai berlogika konvensional "
                   "benar-benar gagal pada kondisi tersebut. Bukti ini (Proof of Urgency) diperoleh melalui pengujian Software-in-the-Loop (SIL) "
                   "sebelum dilanjutkan ke pengujian Hardware-in-the-Loop. Pengujian dilakukan pada IEEE 34 Node Test Feeder dengan tujuan "
                   "memburu salah kerja relai konvensional secara sistematis, kemudian mengolah hasil batch menjadi bukti kuantitatif "
                   "perbandingan kondisi baseline dan kondisi dengan penetrasi DER."))
    story.append(H2("1.2 Mode Kegagalan yang Diburu"))
    story.append(P("Lima mode kegagalan yang diburu didefinisikan sebagai berikut. Setiap kasus simulasi diklasifikasikan oleh modul Fault Hunter "
                   "ke dalam satu atau lebih mode ini dengan membandingkan respons relai terhadap kebenaran fisik (ground truth) jaringan."))
    story.append(table_block("Definisi mode kegagalan relai konvensional", ["Kode", "Nama", "Definisi inti", "Sudut pandang operator"], [
        ["F-1", "Blinding of Protection", "Relai gagal mendeteksi gangguan di wilayah kerjanya karena arus yang melewati sensor lebih kecil dari pickup.",
         "Tidak ada alarm maupun trip; relai tampak tertidur sementara gangguan terus menyala."],
        ["F-2", "Sympathetic Tripping", "Pemutus pada penyulang atau seksi yang sehat ikut terbuka akibat gangguan di tempat lain pada busbar yang sama.",
         "Dua atau lebih area padam bersamaan padahal gangguan hanya pada satu jalur."],
        ["F-3", "Miscoordination dan CTI", "Urutan atau selisih waktu kerja relai utama (hilir) dan cadangan (hulu) dilanggar; CTI di bawah 0,2 s.",
         "Gangguan lokal memadamkan pemutus hulu, wilayah padam meluas dan titik gangguan kabur di SOE."],
        ["F-4", "Directional Misidentification", "Relai berarah salah menentukan arah gangguan akibat referensi sudut fasa yang hilang atau terdistorsi.",
         "SOE bertolak belakang dengan lapangan; gangguan di depan diblokir atau saluran sehat diputus."],
        ["F-5", "Impedance Under-reach", "Relai jarak mengukur impedansi lebih besar dari jarak fisik sehingga gangguan Zona 1 bergeser ke Zona 2 atau 3.",
         "Gangguan dekat gardu tidak diputus seketika; kedip tegangan berkepanjangan."],
    ], [12 * mm, 30 * mm, 64 * mm, 60 * mm]))
    story.append(H2("1.3 Ruang Lingkup"))
    story.append(P("Laporan ini mencakup tahap Post-Run Visualization: desain kampanye batch, eksekusi, dan lima visualisasi pembuktian, yaitu "
                   "Dynamic TCC Overlay, Failure Rate Heatmap, Stacked Bar Escalation, R-X Envelope dan Polar Rose, serta Protection Confusion Matrix. "
                   "Visualisasi waktu nyata (SCADA dan osiloskop) tersedia di situs lokal SimRELAY dan tidak dibahas di sini."))

    # ============================================================ 2 metodologi
    story.append(PageBreak())
    story.append(H1("2. Metodologi"))
    story.append(H2("2.1 Test Bench Software-in-the-Loop"))
    story.append(P("Simulasi dijalankan dengan engine fasor tiga fasa quasi-steady-state SimRELAY. Solver nodal menghitung tegangan dan arus "
                   "setiap langkah waktu dt = 1/960 s (16 langkah per siklus 60 Hz). Setiap Intelligent Electronic Device (IED) virtual membaca fasor "
                   "yang difilter DFT satu siklus, dan pemutus membutuhkan 50 ms untuk membuka setelah perintah trip. Jaringan uji terdiri atas "
                   "IEEE 34 Node Test Feeder (Penyulang A, konfigurasi saluran 300 sampai 304, regulator REG1 dan REG2, kapasitor C844 dan C848, "
                   "trafo XFM-1) serta Penyulang B ekuivalen yang terhubung ke busbar 800 yang sama untuk menguji F-2."))
    story.append(P("Lima titik proteksi dimodelkan: A1 (CB kepala Penyulang A, 800 ke 802), A2 (recloser tengah, 828 ke 830), A3 (recloser hilir, "
                   "858 ke 834), L1 (recloser lateral satu fasa 816 ke 818), dan B1 (CB kepala Penyulang B). Model DER mencakup generator sinkron "
                   "(SG) dengan reaktansi subtransien, transien, dan sinkron; inverter grid-following (IBR-GFL) sebagai sumber arus terbatas dengan "
                   "PLL dan mode FRT prioritas Q sesuai IEEE 2800; serta inverter grid-forming (IBR-GFM) sebagai sumber tegangan dengan pembatas arus. "
                   "Relai 87L menyelaraskan waktu sampel kedua ujung terhadap tunda kanal komunikasi 5 ms dan memakai filter fasor yang sama di kedua ujung. "
                   "Hasil setiap kasus diekspor ke format .mat agar dapat diolah lebih lanjut di MATLAB."))
    story.append(H2("2.2 Setting Relai Baseline (Dibekukan)"))
    story.append(P("Setting relai dihitung otomatis satu kali pada kondisi baseline (0% DER, beban puncak malam, terhubung grid), lalu dibekukan "
                   "untuk seluruh kasus. Kondisi inilah yang mendefinisikan relai konvensional dalam pengujian ini. Pickup elemen 51 ditetapkan 1,5 kali "
                   "arus beban maksimum, kurva IEC Standard Inverse digunakan dengan CTI desain 0,3 s terhadap seluruh bus zona primer hilir, dan elemen "
                   "50 ditetapkan 1,25 kali arus gangguan maksimum di lokasi relai hilir. Setting lengkap disajikan pada Lampiran A."))
    story.append(H2("2.3 Desain Kampanye Batch"))
    story.append(P("Setiap kasus menempatkan satu unit DER dengan kapasitas sebesar persentase penetrasi terhadap beban puncak Penyulang A "
                   "(1.769 kW) pada salah satu bus kandidat, yaitu 806, 828, 840, dan 848 di Penyulang A serta B03 di Penyulang B. Dua teknologi diuji: "
                   "generator sinkron dengan trafo interkoneksi Yg-Δ (sumber urutan nol) dan inverter grid-following. Dengan demikian terdapat 10 "
                   "penempatan DER untuk setiap tingkat penetrasi. Setiap penempatan diuji terhadap 11 kasus gangguan: SLG fasa A dan tiga fasa pada "
                   "bus 812, 830, 834, 848, dan B04, serta SLG pada lateral satu fasa 822. Gangguan masuk pada t = 0,3 s dan simulasi berlangsung 1,6 s."))
    story.append(table_block("Kampanye simulasi batch", ["Kode", "Tujuan", "Variabel", "Kasus"], [
        ["H1", "Penetrasi terhadap langgam beban", "Penetrasi 0 sampai 120%, beban 40/70/100%, OCR, Rf = 0", ribu(camp["H1"])],
        ["H2", "Penetrasi terhadap tahanan gangguan", "Penetrasi 0 sampai 120%, Rf = 5/20/50 Ω, OCR, beban puncak", ribu(camp["H2"])],
        ["E", "Eskalasi kelas relai", "DOCR 67, Distance 21, Differential 87L; penetrasi 0/40/80/120%", ribu(camp["E"])],
        ["I", "Microgrid terisolasi", "IBR-GFM di 824 dan IBR-GFL di 806/840/848; penetrasi 60/90/120%; OCR dan DOCR", ribu(camp["I"])],
        ["", "<b>Total</b>", "", f"<b>{ribu(n)}</b>"],
    ], [14 * mm, 52 * mm, 82 * mm, 18 * mm]))
    story.append(H2("2.4 Klasifikasi Kegagalan dan Metrik"))
    story.append(P("Modul Fault Hunter menentukan kebenaran dasar secara radial dari gardu induk. IED pada lintasan gardu ke titik gangguan merupakan "
                   "IED hulu; IED hulu terdekat ke gangguan adalah relai utama (primary), dan IED hulu berikutnya adalah relai cadangan (backup). "
                   "IED di luar lintasan seharusnya tidak trip. Respons relai dievaluasi dalam jendela dari satu siklus setelah gangguan masuk "
                   "hingga pemutus pertama membuka. Metrik yang digunakan adalah sebagai berikut."))
    story += bullets([
        "<b>Laju kegagalan</b>: persentase kasus dengan minimal satu temuan F-1 sampai F-5 atau NT.",
        "<b>NT (nuisance trip)</b>: relai trip sebelum gangguan diterapkan. Kasus seperti ini dicatat sebagai NT saja, karena setelah pemutus terbuka "
        "klasifikasi terhadap gangguan berikutnya tidak lagi bermakna.",
        "<b>Margin CTI</b>: selisih waktu kerja relai cadangan A2 dan relai utama A3. Bila relai tidak menjadi yang pertama trip, waktu yang dipakai "
        "adalah waktu kurva pada arus terukurnya. Margin di bawah 0,2 s dikategorikan F-3.",
        "<b>Dependability</b> = TP / (TP + FN), yaitu kemampuan relai trip ketika seharusnya trip; tergerus oleh F-1 dan F-4.",
        "<b>Security</b> = TN / (TN + FP), yaitu kemampuan relai tidak trip ketika seharusnya tidak trip; tergerus oleh F-2 dan F-3.",
    ])
    story.append(H2("2.5 Eksekusi"))
    story.append(P(f"Seluruh kasus dijalankan secara paralel (setara parsim) dengan 11 proses pekerja"
                   + (f" dalam waktu {num(wall, 1)} menit" if wall else "")
                   + ". Setiap kasus menghasilkan satu rekaman ringkas berisi parameter, temuan Fault Hunter, matriks konfusi, waktu trip, arus terukur, "
                     "sudut arus terhadap tegangan polarisasi, dan lintasan impedansi semu. Seluruh rekaman diekspor ke batch_results.mat, "
                     "batch_results.json, dan postrun_tables.csv (Lampiran B)."))

    # ============================================================ 3 hasil
    story.append(PageBreak())
    story.append(H1("3. Hasil"))
    story.append(H2("3.1 Gambaran Umum"))
    camp_rows = []
    for cp, nama in (("H1", "H1 Penetrasi dan beban"), ("H2", "H2 Penetrasi dan Rf"), ("E", "E Eskalasi kelas relai"), ("I", "I Microgrid terisolasi")):
        rs = [r for r in R if r["campaign"] == cp]
        if not rs:
            continue
        camp_rows.append([nama, ribu(len(rs)), *[ribu(sum(1 for r in rs if r["counts"].get(c, 0))) for c in ALL], pct(rate(rs))])
    camp_rows.append(["<b>Total</b>", f"<b>{ribu(n)}</b>", *[f"<b>{ribu(by_code_runs[c])}</b>" for c in ALL], f"<b>{pct(100 * nfail / n)}</b>"])
    story.append(P(f"Dari {ribu(n)} kasus, {ribu(nfail)} kasus ({pct(100 * nfail / n)}) mengalami minimal satu salah kerja. Tabel berikut "
                   f"merangkum jumlah kasus yang memuat setiap mode kegagalan per kampanye."))
    story.append(table_block("Jumlah kasus yang memuat setiap mode kegagalan", ["Kampanye", "Kasus", *ALL, "Laju gagal"], camp_rows,
                             [40 * mm, 15 * mm, 14 * mm, 14 * mm, 14 * mm, 14 * mm, 14 * mm, 14 * mm, 21 * mm],
                             note="Satu kasus dapat memuat lebih dari satu mode kegagalan."))

    # ---- 3.2 TCC
    story.append(CondPageBreak(120 * mm))
    story.append(H2("3.2 Dynamic TCC Overlay (F-1 dan F-3)"))
    cti_share = 100 * T["cti_violations"] / max(T["cti_cases"], 1)
    story.append(P(f"Gambar 1 menumpuk titik kerja aktual relai A3 (utama) dan A2 (cadangan) pada kurva arus-waktu elemen 51P untuk gangguan tiga fasa "
                   f"di bus 834 dan 848. Pickup 51P A3 adalah {T['pickup_A3_51P']:.0f} A dan pickup A2 adalah {T['pickup_A2_51P']:.0f} A. Pada mode "
                   f"terhubung grid, titik kerja A3 tetap berada di kanan garis pickup dan A3 trip sesuai kurvanya. Pergeseran ke kiri garis pickup "
                   f"terjadi pada microgrid terisolasi yang disuplai inverter: sebanyak {T['a3_no_trip']} kasus berada di bawah pickup A3 sehingga relai "
                   f"utama tidak pernah trip (F-1). Pada {T['a3_upstream_first']} kasus lain, arus A3 berada di atas pickup tetapi gangguan lebih dahulu "
                   f"diputus relai lain. Panel kanan menunjukkan margin CTI antara A2 dan A3 untuk gangguan SLG dan tiga fasa: {T['cti_violations']} dari "
                   f"{T['cti_cases']} kasus ({pct(cti_share)}) berada di bawah batas 0,2 s (F-3), dan jumlahnya meningkat seiring penetrasi DER. Kelompok "
                   f"titik di sekitar -0,15 s adalah kasus ketika A2 trip lebih dahulu melalui elemen seketikanya, sebelum relai utama A3 bekerja."))
    story.append(figure("fig1_tcc_overlay", "Kiri: kurva IEC Standard Inverse 51P relai A3 dan A2 dengan titik kerja aktual gangguan tiga fasa; warna menunjukkan "
                        "tingkat penetrasi DER, tanda silang menunjukkan relai utama tidak trip. Kanan: margin CTI antara A2 dan A3 terhadap penetrasi DER "
                        "untuk DER SG dan IBR; area merah adalah pelanggaran CTI di bawah 0,2 s."))
    tcc_rows = []
    for p in PENS:
        cs, vs = T["cases_by_pen"].get(str(p), 0), T["violations_by_pen"].get(str(p), 0)
        m = T["cti_by_pen"][str(p)]
        tcc_rows.append([f"{p}%", cs, vs, pct(100 * vs / cs if cs else None), num(m["None"], 3), num(m["SG"], 3), num(m["IBR"], 3)])
    story.append(table_block("Pelanggaran CTI antara A2 dan A3 terhadap penetrasi DER", ["Penetrasi", "Kasus", "CTI < 0,2 s", "Persentase",
                             "Median CTI tanpa DER (s)", "Median CTI SG (s)", "Median CTI IBR (s)"], tcc_rows,
                             [20 * mm, 16 * mm, 22 * mm, 22 * mm, 30 * mm, 28 * mm, 28 * mm]))

    # ---- 3.3 heatmap
    story.append(CondPageBreak(120 * mm))
    story.append(H2("3.3 Failure Rate Heatmap"))
    rf_last = ", ".join(f"{pct(r[-1], 0)} pada Rf {rf} Ω" for rf, r in zip(H["rf"]["rows"], H["rf"]["rate"]))
    story.append(P(f"Gambar 2 memetakan laju kegagalan terhadap penetrasi DER dan langgam beban (kiri) serta tahanan gangguan (kanan). Kolom 0% "
                   f"adalah baseline tanpa DER. Pada beban puncak malam, laju kegagalan naik dari {pct(peak[0], 0)} menjadi {pct(peak[-1], 0)} pada "
                   f"120% DER" + (f", dan pertama kali melampaui baseline sebesar 10 poin persentase pada penetrasi {tip}% (tipping point)." if tip is not None else ".")
                   + f" Pada 120% DER, laju kegagalan untuk variasi tahanan gangguan adalah {rf_last}."))
    story.append(figure("fig2_failure_heatmap", "Laju kegagalan relai konvensional (OCR, setting beku) terhadap penetrasi DER dan langgam beban (kiri) serta "
                        "tahanan gangguan Rf (kanan). Setiap sel menggabungkan 10 penempatan DER dan 11 kasus gangguan."))
    hm_rows = [[{40: "Minimum siang 40%", 70: "Menengah 70%", 100: "Puncak malam 100%"}[L], *[pct(v, 0) for v in H["load"]["rate"][i]]]
               for i, L in enumerate(H["load"]["rows"])]
    hm_rows += [[f"Rf {rf} Ω (beban puncak)", *[pct(v, 0) for v in H["rf"]["rate"][i]]] for i, rf in enumerate(H["rf"]["rows"])]
    story.append(table_block("Laju kegagalan (%) per sel peta panas", ["Kondisi", *[f"{p}%" for p in PENS]], hm_rows,
                             [42 * mm] + [17.7 * mm] * 7))
    # per placement at 120%
    pl_rows = []
    pl = sorted({r["fleet"] for r in R if r["campaign"] == "H1" and r["fleet"] != "none"}, key=lambda s: (s.split("@")[1], s))
    for f_ in pl:
        rs = [r for r in R if r["campaign"] == "H1" and r["fleet"] == f_ and r["pen"] == 120 and r["load_pct"] == 100]
        if not rs:
            continue
        cnt = Counter(c for r in rs for c in CODES if r["counts"].get(c, 0))
        tech, bus = f_.split("@")
        pl_rows.append([bus, "Generator sinkron" if tech == "SG" else "Inverter GFL", pct(rate(rs), 0),
                        ", ".join(f"{c} ({v})" for c, v in sorted(cnt.items())) or "Tidak ada"])
    story.append(P(f"Tabel {Counters.tab + 1} menguraikan laju kegagalan pada 120% DER dan beban puncak per lokasi dan teknologi DER, sehingga terlihat kombinasi "
                   "penempatan yang paling memicu salah kerja."))
    story.append(table_block("Laju kegagalan per penempatan DER pada penetrasi 120% (beban puncak, Rf = 0, OCR)",
                             ["Bus DER", "Teknologi", "Laju gagal", "Mode kegagalan (jumlah kasus dari 11)"], pl_rows,
                             [22 * mm, 38 * mm, 22 * mm, 84 * mm]))

    # ---- 3.4 escalation
    story.append(CondPageBreak(120 * mm))
    story.append(H2("3.4 Stacked Bar Escalation Comparison"))

    def dom(cls):
        d = E.get(f"{cls}|120")
        if not d:
            return "N/A"
        k = max(ALL, key=lambda c: d.get(c, 0))
        return f"{k} ({pct(d[k], 0)})" if d[k] > 0 else "tidak ada"
    story.append(P("Gambar 3 membandingkan frekuensi F-1 sampai F-5 dan NT untuk empat kelas relai pada titik proteksi yang sama dengan setting tetap. "
                   "Pada 120% DER, laju kegagalan per kelas adalah "
                   + ", ".join(f"{KELAS[k]} {pct(esc_any[k], 1)}" for k in ("OCR", "DOCR", "DIST", "DIFF"))
                   + ", dengan mode dominan " + ", ".join(f"{KELAS[k]} {dom(k)}" for k in ("OCR", "DOCR", "DIST", "DIFF")) + "."))
    story.append(P("Elemen berarah menghilangkan trip simpatik (F-2) yang dominan pada OCR, tetapi memunculkan salah arah (F-4). Relai jarak memberikan "
                   "penurunan terbesar, namun tetap mengalami under-reach akibat infeed (F-5) dan tidak bebas kegagalan. Relai 87L trip sebelum gangguan "
                   "(NT) ketika DER berada di dalam zona diferensial, karena arus keluaran DER tampak sebagai arus gangguan internal. Pada kelas 87L "
                   f"juga terdapat satu kegagalan baseline ({pct(diff0, 1)}) karena lateral 822 yang memiliki recloser sendiri berada di dalam zona A1 ke A2. "
                   "Dengan demikian, menaikkan kelas relai bersetting tetap mengubah dan mengurangi sebagian kegagalan, tetapi tidak menghilangkannya, "
                   "karena seluruh kelas tetap bergantung pada setting dan asumsi zona yang ditetapkan tanpa DER."))
    story.append(figure("fig3_relay_class_escalation", "Frekuensi mode kegagalan dan NT per 100 kasus untuk kelas OCR 50/51, DOCR 67, Distance 21, dan "
                        "Differential 87L pada penetrasi 0, 40, 80, dan 120%. Angka di atas batang adalah total insiden per 100 kasus."))
    esc_rows = []
    for p in (0, 40, 80, 120):
        for k in ("OCR", "DOCR", "DIST", "DIFF"):
            d = E.get(f"{k}|{p}")
            if d:
                esc_rows.append([f"{p}%", KELAS[k], d["n"], *[pct(d.get(c, 0), 1) for c in ALL], pct(d["any"], 1)])
    story.append(table_block("Persentase kasus per mode kegagalan untuk setiap kelas relai", ["DER", "Kelas relai", "Kasus", *ALL, "Gagal"],
                             esc_rows, [13 * mm, 29 * mm, 14 * mm, 14.5 * mm, 14.5 * mm, 14.5 * mm, 14.5 * mm, 14.5 * mm, 14.5 * mm, 18 * mm]))

    # ---- 3.5 RX & rose
    story.append(CondPageBreak(120 * mm))
    story.append(H2("3.5 R-X Envelope dan Polar Rose (F-4 dan F-5)"))
    zp = [(p, X["by_pen"].get(str(p))) for p in PENS if X["by_pen"].get(str(p)) is not None]
    story.append(P(f"Panel kiri Gambar 4 menumpuk {X['cases']} lintasan impedansi semu relai {X['ied']} (kelas Distance 21) untuk gangguan di bus {X['bus']}. "
                   f"Impedansi fisik ke titik gangguan adalah {num(X['z_true'])} Ω, berada di dalam jangkauan Zona 1 ({num(X['zreach'][0])} Ω). Lintasan berwarna "
                   f"adalah {X['infeed_cases']} kasus dengan DER yang terhubung di antara relai dan titik gangguan (infeed); lintasan abu-abu adalah kasus tanpa DER "
                   f"atau dengan DER di lokasi lain. "
                   + (f"Pada kasus infeed, median impedansi terukur naik dari {num(zp[0][1])} Ω tanpa DER menjadi {num(zp[-1][1])} Ω pada {zp[-1][0]}% DER, "
                      f"sehingga keluar dari Zona 1. " if len(zp) > 1 else "")
                   + f"Sebanyak {X['f5_infeed']} dari {X['infeed_cases']} kasus infeed diklasifikasikan sebagai under-reach (F-5), sedangkan kasus tanpa infeed "
                     f"tetap berada di dalam Zona 1."))
    story.append(P(f"Panel tengah dan kanan menampilkan distribusi sudut arus setiap fasa yang melebihi pickup 67P terhadap tegangan polarisasi kuadraturnya "
                   f"(dikurangi MTA 45°), untuk gangguan di belakang relai berarah. Pembacaan yang benar berada di sekitar ±180°. Dengan DER generator "
                   f"sinkron, {pct(RO['SG']['forward_pct'], 1)} dari {RO['SG']['n']} sampel fasa terbaca FORWARD, sedangkan dengan DER berbasis inverter "
                   f"sebanyak {pct(RO['IBR']['forward_pct'], 1)} dari {RO['IBR']['n']} sampel. Pembacaan keliru terutama terjadi pada fasa sehat (B dan C), "
                   f"yang arusnya didominasi kontribusi DER dan arus beban, bukan oleh impedansi saluran ke titik gangguan. Arus inverter yang dikendalikan "
                   f"dan dibatasi memperburuk efek ini, sehingga referensi arah menjadi tidak andal (F-4)."))
    story.append(figure("fig4_rx_envelope_polar_rose", "Kiri: lintasan impedansi semu loop terganggu dengan zona mho setting beku; bintang merah adalah lokasi "
                        "gangguan sebenarnya. Tengah dan kanan: diagram polar distribusi sudut arus gangguan terhadap tegangan polarisasi untuk gangguan di "
                        "belakang relai, untuk DER generator sinkron dan berbasis inverter; setengah bidang berarsir adalah wilayah yang dinyatakan FORWARD."))

    # ---- 3.6 confusion
    story.append(CondPageBreak(120 * mm))
    story.append(H2("3.6 Protection Confusion Matrix"))
    cb, cd = C["baseline"], C["der"]
    story.append(P(f"Gambar 5 mengklasifikasikan setiap keputusan relai (lima relai per kasus) pada seluruh kasus OCR terhubung grid ({ribu(len(ocr_grid))} kasus). "
                   f"Pada baseline, dependability bernilai {pct(100 * cb['dependability'])} dan security {pct(100 * cb['security'])}. Setelah DER terhubung, "
                   f"dependability menjadi {pct(100 * cd['dependability'])} dan security {pct(100 * cd['security'])}. Pada 120% DER nilainya adalah "
                   f"{pct(C['by_pen']['120']['dependability'])} dan {pct(C['by_pen']['120']['security'])}. Penurunan security yang lebih besar "
                   f"sejalan dengan dominasi F-2 dan F-3, yaitu relai yang trip padahal seharusnya tidak trip."))
    story.append(figure("fig5_confusion_matrix", "Matriks konfusi proteksi untuk baseline tanpa DER (kiri) dan dengan DER 20 sampai 120% (tengah), serta "
                        "dependability dan security terhadap penetrasi DER (kanan)."))
    story.append(table_block("Matriks konfusi dan rasio kinerja proteksi", ["Kondisi", "TP", "FN", "FP", "TN", "Dependability", "Security"], [
        ["Baseline (0% DER)", ribu(cb["TP"]), ribu(cb["FN"]), ribu(cb["FP"]), ribu(cb["TN"]), pct(100 * cb["dependability"]), pct(100 * cb["security"])],
        ["Dengan DER (20 sampai 120%)", ribu(cd["TP"]), ribu(cd["FN"]), ribu(cd["FP"]), ribu(cd["TN"]), pct(100 * cd["dependability"]), pct(100 * cd["security"])],
    ], [48 * mm, 17 * mm, 17 * mm, 17 * mm, 17 * mm, 25 * mm, 25 * mm]))
    story.append(table_block("Dependability dan security terhadap penetrasi DER", ["Penetrasi", *[f"{p}%" for p in PENS]], [
        ["Dependability", *[pct(C["by_pen"][str(p)]["dependability"]) for p in PENS]],
        ["Security", *[pct(C["by_pen"][str(p)]["security"]) for p in PENS]],
    ], [30 * mm] + [19.4 * mm] * 7))

    # ---- 3.7 island
    isl = [r for r in R if r["campaign"] == "I"]
    if isl:
        story.append(CondPageBreak(80 * mm))
        story.append(H2("3.7 Microgrid Terisolasi"))
        il_rows = []
        for k in ("OCR", "DOCR"):
            for p in (60, 90, 120):
                rs = [r for r in isl if r["cls"] == k and r["pen"] == p]
                if rs:
                    il_rows.append([KELAS[k], f"{p}%", len(rs), *[sum(1 for r in rs if r["counts"].get(c, 0)) for c in CODES], pct(rate(rs), 1)])
        story.append(P(f"Pada mode pulau, seluruh arus gangguan disuplai oleh inverter yang arusnya dibatasi sekitar 1,1 sampai 1,5 pu. Dari {len(isl)} kasus "
                       f"terisolasi, {sum(failed(r) for r in isl)} kasus ({pct(rate(isl))}) mengalami salah kerja, dengan {S['islanded']['F-1']} kasus "
                       f"memuat F-1. Kondisi ini menunjukkan bahwa kebutaan proteksi (F-1) terutama muncul ketika jaringan didominasi IBR, "
                       f"sejalan dengan temuan sweep sebelumnya bahwa F-1 sulit muncul pada mode terhubung grid."))
        story.append(table_block("Hasil kampanye microgrid terisolasi (beban minimum siang)", ["Kelas", "Penetrasi", "Kasus", *CODES, "Laju gagal"],
                                 il_rows, [26 * mm, 20 * mm, 15 * mm, 15 * mm, 15 * mm, 15 * mm, 15 * mm, 15 * mm, 20 * mm]))

    # ============================================================ 4 pembahasan
    story.append(PageBreak())
    story.append(H1("4. Pembahasan"))
    top_code = max(CODES, key=lambda c: by_code_runs[c])
    story.append(P(f"Kelima visualisasi saling menguatkan. Tanpa DER, relai OCR, DOCR, dan Distance bebas kegagalan ({pct(base_rate, 0)}), sehingga setting "
                   f"yang digunakan sah sebagai representasi relai konvensional yang terkoordinasi baik. Begitu DER terhubung, kegagalan muncul dan meningkat seiring "
                   f"penetrasi. Mode yang paling sering muncul adalah {top_code} ({NAMA[top_code]}) pada {ribu(by_code_runs[top_code])} kasus."))
    story += bullets([
        "<b>Lokasi DER lebih menentukan daripada besar penetrasi saja.</b> DER di hilir relai atau pada penyulang tetangga menyuplai arus balik "
        "melalui relai non-berarah sehingga memicu trip simpatik (F-2), sedangkan generator sinkron dengan trafo Yg-Δ di hulu relai cadangan "
        "menaikkan arus tanah yang dilihat relai cadangan sehingga koordinasi waktu terlanggar (F-3).",
        "<b>Teknologi DER menentukan jenis kegagalan.</b> Generator sinkron menambah arus gangguan dan sumber urutan nol, sedangkan inverter "
        "membatasi arus dan mengendalikan sudutnya. Akibatnya inverter cenderung membutakan proteksi (F-1) dan merusak referensi arah (F-4).",
        "<b>Kelas relai yang lebih tinggi bukan solusi tuntas.</b> DOCR, Distance, dan Differential dengan setting tetap mengurangi sebagian kegagalan "
        "tetapi gagal pada kondisi yang berbeda (F-4, F-5, NT). Kegagalan bersumber dari asumsi tetap pada setting, zona, dan logika, bukan dari "
        "kelas perangkat semata.",
        "<b>Dampak pada operasi.</b> Turunnya security berarti pemadaman yang meluas secara sia-sia, sedangkan turunnya dependability berarti "
        "gangguan yang dibiarkan menyala. Keduanya merupakan risiko langsung bagi keandalan dan keselamatan jaringan distribusi.",
    ])
    story.append(H2("4.1 Implikasi untuk Rancangan Relai Adaptif"))
    story += bullets([
        "Setting pickup dan TMS perlu mengikuti status dan kapasitas DER yang terhubung (kelompok setting adaptif) agar CTI tetap terjaga.",
        "Elemen arah perlu metode polarisasi yang tetap andal untuk arus inverter terkendali, misalnya dengan memanfaatkan informasi mode kendali "
        "inverter atau komunikasi antar IED.",
        "Jangkauan relai jarak perlu dikompensasi terhadap infeed DER di antara relai dan titik gangguan.",
        "Zona diferensial perlu memperhitungkan kontribusi DER dan cabang (tap) di dalam zona agar keluaran DER tidak dianggap gangguan internal.",
        "Deteksi gangguan pada mode pulau perlu kriteria selain besar arus, karena arus gangguan inverter dapat berada di bawah pickup konvensional.",
    ])

    # ============================================================ 5 keterbatasan
    story.append(H1("5. Keterbatasan dan Penyederhanaan"))
    story.append(P("Hasil ini perlu dibaca dengan memperhatikan penyederhanaan model berikut, yang juga perlu disebutkan pada bab metodologi Tugas Akhir."))
    story += bullets([
        "Model bersifat fasor quasi-steady-state, bukan EMT; transien elektromagnetik orde sub-siklus tidak dimodelkan. Komponen DC offset "
        "direkonstruksi memakai rasio X/R Thevenin di titik gangguan.",
        "Kapasitansi shunt saluran diabaikan, beban dimodelkan impedansi konstan, dan beban terdistribusi dibagi 50/50 ke ujung segmen.",
        "Regulator dimodelkan dengan tap tetap per skenario; auto-reclose (79) belum dimodelkan.",
        "Engine saat ini diimplementasikan dalam Python sebagai pengganti sementara MATLAB/Simulink; hasil diekspor ke format .mat untuk "
        "validasi silang dan interkoneksi MATLAB pada tahap berikutnya.",
        "Setiap kasus menempatkan satu unit DER (atau satu pasangan GFM dan GFL pada mode pulau); interaksi banyak DER sekaligus belum dikaji.",
        "Zona 87L A1 ke A2 memuat lateral 822 yang dilindungi recloser L1 sendiri, sehingga 87L trip untuk gangguan pada lateral tersebut bahkan "
        "tanpa DER. Hal ini merupakan keterbatasan konfigurasi zona pada test bench, bukan dampak DER.",
    ])

    # ============================================================ 6 kesimpulan
    story.append(H1("6. Kesimpulan"))
    story += bullets([
        f"Relai OCR, DOCR, dan Distance dengan setting beku bekerja benar tanpa DER (laju kegagalan {pct(base_rate, 0)}), tetapi dari seluruh {ribu(n)} "
        f"kasus, {pct(100 * nfail / n)} mengalami salah kerja setelah variasi DER dan jaringan diterapkan.",
        f"Laju kegagalan meningkat seiring penetrasi DER hingga {pct(peak[-1], 0)} pada 120% DER dan beban puncak"
        + (f", dengan titik kritis pada {tip}% DER." if tip is not None else "."),
        f"Dependability turun {num(100 * (cb['dependability'] - cd['dependability']), 1)} poin persentase dan security turun "
        f"{num(100 * (cb['security'] - cd['security']), 1)} poin persentase setelah DER terhubung.",
        "Kelima mode kegagalan F-1 sampai F-5 berhasil direproduksi dan dibuktikan secara kuantitatif maupun geometris; F-1 terutama muncul pada "
        "microgrid terisolasi yang didominasi IBR.",
        f"Pergantian kelas relai bersetting tetap mengubah dan mengurangi sebagian kegagalan, tetapi tidak menghilangkannya (laju kegagalan terendah pada "
        f"120% DER adalah {pct(min(v for v in esc_any.values() if v is not None), 1)}). Dengan demikian, kebutuhan akan relai adaptif terbukti mendesak "
        "dan menjadi dasar untuk tahap perancangan dan pengujian Hardware-in-the-Loop berikutnya.",
    ])

    # ============================================================ lampiran
    story.append(PageBreak())
    story.append(H1("Lampiran A. Setting Relai Baseline"))
    names = {"A1": "CB-A, kepala Penyulang A (800 ke 802)", "A2": "REC-A2, recloser tengah (828 ke 830)", "A3": "REC-A3, recloser hilir (858 ke 834)",
             "L1": "REC-L1, lateral satu fasa (816 ke 818)", "B1": "CB-B, kepala Penyulang B (800 ke B01)"}
    srows = []
    for k, s in SET.items():
        srows.append([f"<b>{k}</b>", names.get(k, ""), f"{s['51P_pu']:.0f} / {s['51P_tms']}", "N/A" if not s["50P_pu"] else f"{s['50P_pu']:.0f}",
                      "N/A" if not s["51N_pu"] else f"{s['51N_pu']:.0f} / {s['51N_tms']}", "N/A" if not s["50N_pu"] else f"{s['50N_pu']:.0f}",
                      " / ".join(num(float(z), 1) for z in s["zreach"]), "N/A" if not s["87_pu"] else f"{s['87_pu']:.0f}"])
    story.append(table_block("Setting beku seluruh IED (arus dalam ampere primer, kurva IEC Standard Inverse)",
                             ["IED", "Lokasi", "51P pickup / TMS", "50P", "51N pickup / TMS", "50N", "Z1 / Z2 / Z3 (Ω)", "87L"], srows,
                             [11 * mm, 47 * mm, 22 * mm, 12 * mm, 22 * mm, 12 * mm, 27 * mm, 13 * mm],
                             note="Elemen 67 memakai polarisasi kuadratur dengan MTA 45° dan memori tegangan; 67N memakai 32Q dengan cadangan 32V. "
                                  "Relai jarak memakai karakteristik mho dengan Z1 80% (seketika), Z2 120% (0,3 s), dan Z3 (0,8 s). 87L memakai slope 30% "
                                  "dan kanal 5 ms; IED tanpa pasangan hilir beralih ke relai jarak."))
    story.append(H1("Lampiran B. Berkas Keluaran dan Reproduksi"))
    story.append(table_block("Berkas keluaran kampanye batch", ["Berkas", "Isi"], [
        ["batch/results.jsonl", "Satu rekaman ringkas per kasus (parameter, temuan, waktu trip, arus, sudut, lintasan R-X)."],
        ["batch/batch_results.mat", "Tabel seluruh kasus dalam struct MATLAB <i>batch</i> untuk pengolahan lanjutan di MATLAB."],
        ["batch/batch_results.json", "Seluruh kasus dalam format JSON."],
        ["batch/postrun_tables.csv", "Tabel panjang seluruh kasus, satu baris per kasus."],
        ["batch/postrun_summary.json", "Angka di balik setiap gambar."],
        ["batch/figures/*.png, *.pdf", "Lima gambar Post-Run dalam format raster dan vektor."],
    ], [52 * mm, 114 * mm]))
    story.append(P("Seluruh hasil dapat direproduksi dengan perintah berikut dari folder proyek: <font face='Arial-Bold'>python batch.py</font> "
                   "(menjalankan kampanye dan dapat dilanjutkan bila terhenti), <font face='Arial-Bold'>python postrun.py</font> (membuat gambar), dan "
                   "<font face='Arial-Bold'>python report.py</font> (membuat laporan ini). Gambar dan tabel juga dapat dilihat secara interaktif pada "
                   "halaman Post-Run Analysis di situs lokal SimRELAY."))
    story.append(H1("Lampiran C. Contoh Temuan Fault Hunter"))
    story.append(P("Tabel berikut memuat satu contoh temuan untuk setiap mode kegagalan, sebagaimana tercatat oleh Fault Hunter (teks temuan "
                   "dalam bahasa Inggris sesuai log simulasi)."))
    ex_rows = []
    for c in ALL:
        cand = [(r, f) for r in R for f in r["findings"] if f["code"] == c]
        if not cand:
            ex_rows.append([c, "Tidak ditemukan", ""])
            continue
        pref = "I" if c == "F-1" else "H1" if c in ("F-2", "F-3") else "E"
        cand.sort(key=lambda x: (x[0]["campaign"] != pref, -x[0]["pen"], x[0]["rf"]))
        r, f = cand[0]
        tech = {"SG": "SG", "IBR-GFL": "IBR-GFL", "ISL": "GFM dan GFL (pulau)"}.get(r["tech"], r["tech"])
        ex_rows.append([c, f"{KELAS[r['cls']]}, DER {tech} di {r['site']} {r['pen']}%, gangguan {r['ftype']} di {r['bus']}, Rf {r['rf']} Ω",
                        esc(f["title"])])
    story.append(table_block("Contoh temuan per mode kegagalan", ["Kode", "Kasus", "Temuan"], ex_rows, [14 * mm, 70 * mm, 82 * mm]))
    return story


def main():
    if not os.path.exists(os.path.join(BATCH, "postrun_summary.json")):
        sys.exit("Jalankan batch.py lalu postrun.py terlebih dahulu.")
    doc = Doc(OUT)
    story = build()
    doc.multiBuild(story)
    print(f"[report] {OUT}")


if __name__ == "__main__":
    main()
