# SimRELAY — SIL Proof-of-Urgency Test Bench (IEEE 34 Bus)

Test bench Software-in-the-Loop untuk **memburu kesalahan relai konvensional** akibat
penetrasi DER pada IEEE 34 Node Test Feeder. Engine sementara memakai Python
(engine fasor 3-fasa); interkoneksi MATLAB/Simulink menyusul.

## Menjalankan

```bash
pip install numpy          # scipy opsional (untuk ekspor .mat)
python server.py           # otomatis membuka http://127.0.0.1:8034
python server.py --port 9000 --no-browser
python server.py --precompute   # simulasikan semua preset ke ./cache lalu keluar
```

**Cache hasil simulasi.** Setiap skenario disimpan di `cache/runs/<hash>/` (`result.json`,
`wave.npz`, `wave.json`), dengan kunci hash isi skenario. Skenario yang sudah pernah
disimulasikan langsung dibaca dari disk, tanpa menjalankan engine lagi. Saat server start,
preset yang belum ada di cache dihitung di latar belakang (sekitar 5 menit untuk semua
preset). Setting relai baseline juga di-cache (`cache/settings.pkl`). Cache otomatis
dibuang bila file `engine/*.py` berubah. Pengecualiannya `engine/layout.py`, yang hanya
berisi koordinat SLD.

Saat start, server menghitung **setting relai baseline** (0% DER, beban puncak malam,
grid-connected) lalu **membekukannya** untuk semua skenario. Itulah definisi "relai
konvensional" di test bench ini.

## Tampilan

| Panel | Filosofi | Isi |
|---|---|---|
| Header | — | Top Main Scenarios (preset), DoF Editor, RUN, ringkasan F-1…F-5 |
| Panel 1 · OPERATOR · REALTIME | Apa yang benar-benar dilihat operator | SLD vektor IEEE 34 + Penyulang B: warna tegangan bus, status CB/recloser, ikon beban/DER/kapasitor/regulator, arah aliran daya (kuning = aliran balik), KPI, strip alarm SCADA. Klik komponen apa pun → inspector parameter + nilai live. Opsi **Scan RTU** (10 ms … 2 s) meniru keterlambatan polling SCADA |
| Panel 2 · GOD VIEW | Fisika aktual | Osiloskop multi-kanal (tambah/hapus baris, mode Sesaat/RMS/Urutan 1-2-0, hover crosshair, klik untuk lompat), SOE simulator (kebenaran fisik), tab **Fault Hunter** (F-1…F-5, matriks TP/TN/FP/FN, dependability/security). Lokasi gangguan muncul samar di SLD bila *God overlay* aktif |
| Panel 3 · DIAMBIL KEMUDIAN | Rekaman lapangan | Relay SOE berstempel waktu IED (pickup, arah, trip, 52b, DTT) |
| Footer | Playback | Play/pause, ±1 siklus, kecepatan 0.02×–2×, scrub, penanda kejadian. Keyboard: Spasi, ←/→ (Shift = 100 ms), Home/End, Esc |

## Derajat kebebasan (DoF Editor)

* **DoF-1 DER** — SG / IBR grid-following / IBR grid-forming; kapasitas 0–150% beban
  puncak; bus lokasi; trafo interkoneksi Yg-Δ (sumber urutan nol) atau Δ-Yg; mode FRT
  prioritas-P / prioritas-Q (IEEE 2800), Imax, injeksi I2, momentary cessation;
  profil iradiasi (konstan, awan lewat, turun mendadak); trip DER terjadwal; kategori
  ride-through IEEE 1547.
* **DoF-2 Beban & Grid** — min siang 40% / menengah 70% / puncak malam 100% / kustom;
  pengali per-fasa (unbalance); Cold Load Pickup; kapasitor C844/C848; tap REG1/REG2;
  Grid-Connected vs Islanded (CB GI dibuka pada t); kapasitas trafo GI.
* **DoF-3 Gangguan** — di bus atau di tengah saluran (posisi %), SLG/LL/DLG/3PH, fasa,
  Rf, waktu masuk, padam sendiri (opsional), bisa lebih dari satu gangguan.
* **DoF-4 Relai** — ganti kelas per IED: OCR 50/51 → DOCR 67 → Distance 21 / Diff 87L
  dengan setting tetap.

## Engine (engine/)

| File | Isi |
|---|---|
| `network.py` | Data IEEE 34 (konfigurasi 300–304, beban spot & terdistribusi, kapasitor, regulator, XFM-1, trafo GI 2.5 MVA), Penyulang B ekuivalen, 5 titik IED |
| `sim.py` | Solver nodal 3-fasa per langkah dt = 1/960 s, CB (waktu buka 50 ms), pulau & frekuensi (swing agregat + droop), CLPU |
| `der.py` | SG (E'' di belakang X''→X'→Xd), IBR-GFL (sumber arus terbatas, PLL, lag 1 siklus), IBR-GFM (sumber tegangan + pembatas arus), proteksi DER |
| `relays.py` | Virtual IED: 50/51/50N/51N (IEC SI), 67/67N (kuadratur + memori, 32Q→32V), 21 mho 3 zona + k0, 87L persentase-restraint; filter DFT 1 siklus |
| `settings.py` | Koordinasi otomatis baseline: pickup 1.5× beban, CTI desain 0.3 s di semua bus zona primary hilir, 50 = 1.25× arus di lokasi relai hilir |
| `hunter.py` | Ground truth radial + klasifikasi F-1…F-5 (+ NT), matriks konfusi |
| `results.py` | Paket data UI (timeline 10 ms), rekonstruksi gelombang sesaat 64 sampel/siklus + DC offset, simpan log |

Setiap run disimpan di `runs/<id>/` sebagai `result.json`, `data.npz` (dan `data.mat`
bila scipy tersedia) — bahan untuk visualisasi Post-Run dan interkoneksi MATLAB.

## Verifikasi yang sudah dilakukan

* **Baseline bersih:** 98 gangguan (SLG/LL/3PH, Rf = 0) di setiap bus tanpa DER →
  **0 temuan**. Jadi setiap kegagalan pada preset berasal dari kondisi DER/jaringan,
  bukan dari setting yang buruk.
* **Sweep fault hunting** (≈1.300 run) untuk mencari kondisi pemicu; ke-7 preset
  memicu target masing-masing (F-1, F-2, F-3, F-4, F-5, NT).
* Temuan jujur: pada mode **grid-connected** sweep tidak menemukan F-1. Pickup OCR di
  IEEE 34 rendah dibanding arus gangguan, bahkan pada Rf 80 Ω dengan infeed SG.
  F-1 muncul pada kondisi **didominasi IBR / islanded**: arus dibatasi ~1.1–1.5 pu.

## Penyederhanaan (perlu disebut di Bab 3)

Model fasor quasi-steady-state (bukan EMT); kapasitansi shunt saluran diabaikan; beban
impedansi konstan; beban terdistribusi dibagi 50/50 ke ujung segmen; regulator = tap
tetap per skenario; auto-reclose (79) belum dimodelkan; frekuensi pulau tak disengaja
(setelah CB membuka dengan DER di hilir) belum dimodelkan terpisah; komponen DC offset
memakai X/R Thevenin di titik gangguan.

## Berikutnya

1. Post-Run: batch/parsim → TCC overlay, heatmap tingkat kegagalan, stacked bar
   eskalasi kelas, R-X envelope & polar rose, confusion matrix agregat.
2. Interkoneksi MATLAB: endpoint `/api/run` yang sama dapat dipanggil dari Simulink,
   atau engine diganti model Simscape Electrical via MATLAB Engine API for Python.
