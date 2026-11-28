# Paper IEEE: hasil, cara membuat, dan design rule

Ditulis 28 November 2026. Paper konferensi IEEE hasil campaign PoU (5.247 kasus, engine MATLAB fasor).

## 1. Hasil akhir

| Berkas | Isi |
|---|---|
| `docs/handover/paper_final/Numerical_Study_Protection_Failure_IEEE34.pdf` | Salinan beku versi terakhir (10 halaman) |
| `docs/handover/paper_final/Numerical_Study_Protection_Failure_IEEE34.docx` | Salinan beku, bisa diedit di Word |
| `paper/Numerical_Study_Protection_Failure_IEEE34.pdf` dan `.docx` | Versi kerja; tertimpa setiap kali build ulang |

**Judul:** Numerical Study of Conventional Protection Failure in Radial Distribution Systems under
Distributed Energy Resource Penetration: A Case Study of the IEEE 34-Bus Test Feeder.

**Penulis:** Della Cyntia Putri Sibagariang (18023040) dan Yusuf Aji Nugraha (18023047), STEI ITB.
Dosen tidak dicantumkan (keputusan pengguna 26 November 2026).

**Isi:** 10 halaman, 13 gambar, 6 tabel, 16 persamaan Word asli, 27 referensi.

| Bab | Isi |
|---|---|
| I. Introduction | Premis proteksi radial, cara DER mematahkannya, dampak operasi, celah riset, empat kontribusi. **Sudah disetujui pengguna, jangan diubah.** |
| II. System Modeling | A Test Feeder (Fig. 1 dari SLD UI), B DER Models, C Relay Models and Frozen Settings (Table I, II), D Simulation Engine (satu paragraf: fasor, bukan EMT, beserta alasannya) |
| III. Scenarios and Studies | A Campaign Design (Table III, Fig. 2), B Ground Truth and Anchor, C Misoperation Predicates (Table IV, persamaan 11 sampai 14) |
| IV. Results and Discussion | A Reference and Aggregate (Fig. 3, Table V), B Penetration, Load, Rf (Fig. 4, 5), C Relay Principle, DER Location, Fault Position (Fig. 6, 7, 8), D Classification by Failure Cases (F-1 sampai NT; Fig. 9 sampai 13, Table VI) |
| V. Conclusion | Tujuh poin |

**Angka kunci** (dihitung dari `campaigns/PoU-TA-Proteksi-Adaptif/results.jsonl`):

- 98 dari 99 anchor tanpa DER benar; satu-satunya cacat adalah 87L, SLG di 822 (cacat desain zona).
- 49,6% dari 5.148 kasus DER salah kerja; 20,6% bila F-6 dikecualikan.
- Tanpa F-6: 8,6% (20%) naik ke 32,2% (120%). Dependability 95,5% dan security 96,5% pada 120%.
- Confusion matrix kasus DER: TP 4.857, FN 165, FP 520, TN 19.208 (685 keputusan salah).
- Kode per kasus: F-1 224, F-2 420, F-3 173, F-4 68, F-5 18, F-6 1.655, NT 225.
- Mekanisme dominan: jalur urutan nol trafo interkoneksi YgD (bukan teknologi generator). Delay A1 identik
  untuk SG dan GFL (0,572 s dan 0,574 s).
- Backfeed F-6 (H1 dan H2): median 20 A, dari 3,5 A (GFL 20%) sampai 62 A (SG 120%).

**Yang masih harus dicek pengguna:** akurasi referensi (terutama [2] data feeder IEEE PES dan [23] RUPTL).
DP-1 dan DP-2 sengaja tidak dikutip.

## 2. Cara membuat ulang

### Lingkungan

- Python terpisah untuk paper (bukan `.venv` aplikasi): `pip install -r paper/tools/requirements-paper.txt`
  (python-docx, lxml, latex2mathml, matplotlib, numpy, scipy, pymupdf, pillow).
- Microsoft Word terpasang (untuk ekspor PDF lewat COM dan untuk `MML2OMML.XSL` di
  `C:\Program Files\Microsoft Office\root\Office16\`).
- Font Courier New dan Book Antiqua (bawaan Windows dan Office).
- Template: `C:\Users\Sir Ucup\Downloads\Desain Sistem Tenaga Listrik\Thyristor Based Automatic Voltage Regulator .docx`
  (sumber header logo STEI ITB, ukuran Letter, margin, dua kolom).

### Langkah

```powershell
cd "C:\Users\Sir Ucup\Downloads\Simrelay 34\paper"
$env:OPENBLAS_NUM_THREADS = "1"
python figures.py method rate heat class wave tcc rx          # Fig. 2, 4, 5, 6, 9, 11, 12
python figures_stats.py network_ui conf site matrix delay backfeed   # Fig. 1, 3, 7, 8, 10, 13
python build_paper.py "<template.docx>" Numerical_Study_Protection_Failure_IEEE34.docx
powershell -ExecutionPolicy Bypass -File tools\to_pdf.ps1 "<path absolut .docx>" "<path absolut .pdf>"
python tools\render.py <file.pdf> <prefix png> all 80          # opsional: render halaman untuk dicek
```

`fig_backfeed` membaca `wave.npz` dari 1.321 run (beberapa menit). Script lain cepat.

### Fig. 1 (SLD dari UI SimRELAY)

Gambar topologi diambil dari SLD aplikasi, bukan digambar ulang:

1. Jalankan SimRELAY (`python server.py`) dan buka sebuah run di browser.
2. Jalankan penerima: `python paper/tools/recv.py <folder keluaran>` (port 8099).
3. Di konsol browser, tempel isi `paper/tools/sld_export.js`, lalu `await sldPaperExport("sld_ui3")`.
   Fungsi ini membuat run sintetis berisi semua kandidat DER dan lokasi gangguan (hanya tampilan),
   menyembunyikan label beban kW, mengganti label, menambah lingkaran putus-putus, lalu mengekspor PNG.
4. Salin PNG ke `paper/figures/sld_ui_raw.png`, lalu `python figures_stats.py network_ui` (legenda di bawah).
5. Muat ulang halaman aplikasi supaya kembali ke run asli.

### Peta berkas

| Berkas | Fungsi |
|---|---|
| `paper/build_paper.py` | Seluruh teks, tabel, persamaan, dan tata letak docx. Tabel dihitung langsung dari data |
| `paper/figures.py` | Gaya global (rcParams, palet) dan Fig. 2, 4, 5, 6, 9, 11, 12 |
| `paper/figures_stats.py` | Fig. 1 (komposisi SLD) dan grafik statistik Fig. 3, 7, 8, 10, 13 |
| `paper/stats.py` | Mencetak statistik campaign untuk pengecekan angka |
| `paper/tools/` | `to_pdf.ps1` (Word COM), `render.py` (PDF ke PNG), `recv.py` (penerima ekspor SLD), `sld_export.js`, `requirements-paper.txt` |

Nama berkas gambar (`fig9_conf.png` dan seterusnya) **tidak sama** dengan nomor gambar di paper; nomor
mengikuti urutan pemanggilan `P.fig()` di `build_paper.py`.

## 3. Design rule (keputusan pengguna, wajib diikuti)

### Bahasa dan gaya tulisan

- Paper dalam bahasa Inggris formal akademik; jawaban ke pengguna dalam Bahasa Indonesia.
- Bahas kegagalan proteksi, bukan tools, kode, atau UI. Metode disajikan formal dan matematis, bukan algoritmik.
- Dilarang membuka kalimat dengan "This/These X" (padanan "Bab ini, penelitian ini, studi ini") dan
  dilarang "As mentioned", "As we discussed earlier", "As XX".
- Jujur soal model: fasor, bukan EMT, dengan justifikasi; F-6 dilaporkan terpisah.

### Persamaan

- **Tidak boleh ada persamaan atau simbol di dalam paragraf.** Setiap persamaan punya baris sendiri
  (bernomor, jarak atas dan bawah 7 pt).
- Penjelasan persamaan dinarasikan dengan kata, contoh "The apparent power rating of a DER unit equals ...",
  bukan "S_DER = ...".

### Gambar

- Latar putih bersih, tanpa tema dasar biru, warna pastel.
- Semua teks di gambar memakai Courier New; label gambar dalam bahasa Inggris.
- Legenda di bawah gambar, tersusun horizontal; tidak boleh ada elemen yang tumpang tindih.
- **Titik data hanya lingkaran berisi.** Bedakan seri dengan warna; garis putus-putus boleh.
- SLD: kotak relai hanya garis tepi (fill putih, warna garis kuning tua), breaker abu-abu, penanda kandidat
  berupa lingkaran putus-putus tanpa fill (hijau DER, ungu GFM, merah lokasi gangguan). Label beban kW
  disembunyikan supaya lega.

### Tabel

- Garis gaya booktabs, padding sel lega (atas dan bawah 40 twip, kiri dan kanan 90 twip).
- **Tabel kecil satu kolom wajib numerik:** isinya nilai variabel, sederhana dan langsung; kata boleh
  sebagai label tetapi tidak untuk menjelaskan.
- Tabel lebar (dua kolom) tidak boleh terpotong antar halaman (baris `cantSplit` dan `keep_with_next`).

### Format dokumen

- Template STEI ITB (docx AVR): Letter, margin 0,65 x 0,70 inci, Book Antiqua 10 pt, dua kolom,
  logo di header halaman pertama, judul ringkas dan nomor halaman berurutan di header berikutnya.
- Maksimal 10 halaman. Kolom halaman terakhir diseimbangkan.
- Kesimpulan berupa poin.
- Referensi gaya IEEE; DP-1 dan DP-2 tidak boleh dikutip.
