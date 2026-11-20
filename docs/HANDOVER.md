# SimRelay 34: dokumen serah-terima (handover)

Ditulis 20 November 2026 untuk melanjutkan pekerjaan di sesi lain. Dokumen ini menjelaskan
apa yang sudah dibangun, bagaimana arsitekturnya, cara menjalankannya, apa yang sudah
divalidasi, dan apa yang belum selesai.

## 1. Tujuan proyek

Tugas Akhir 18023047: pengembangan relai adaptif untuk sistem distribusi dengan penetrasi DER.
Tahap ini adalah **Proof of Urgency** melalui pengujian Software-in-the-Loop (SIL) pada IEEE 34
Node Test Feeder: memburu salah kerja relai konvensional (setting dibekukan pada kondisi 0% DER,
beban puncak) ketika DER terhubung. Lima mode kegagalan yang diburu:

| Kode | Nama | Inti |
|---|---|---|
| F-1 | Blinding of Protection | Arus gangguan di sensor di bawah pickup, relai tidak trip |
| F-2 | Sympathetic Tripping | Penyulang/seksi sehat ikut trip |
| F-3 | Miscoordination / CTI | Relai hulu trip sebelum atau terlalu dekat dengan relai hilir (CTI < 0,2 s) |
| F-4 | Directional Misidentification | Elemen berarah salah membaca forward/reverse |
| F-5 | Impedance Under-reach | Relai jarak mengukur impedansi lebih besar, Zona 1 tergeser |
| NT | Nuisance trip | Relai trip sebelum gangguan diterapkan (ditambahkan saat analisis 87L) |

Spesifikasi awal pengguna (ultraprompt) meminta: engine MATLAB/Simulink, standar IEEE/IEC,
visualisasi di website lokal (panel operator SCADA, panel "god view" osiloskop dan SOE simulator,
panel SOE relai lapangan, playback bar), empat derajat kebebasan (DoF-1 DER, DoF-2 beban dan
jaringan, DoF-3 gangguan, DoF-4 kelas relai), dan visualisasi post-run (TCC overlay, heatmap,
stacked bar eskalasi, R-X envelope dan polar rose, confusion matrix).

## 2. Arsitektur

```
web/ (UI)  <-- HTTP JSON -->  server.py  -->  engine Python (engine/sim.py)
                                         \->  engine MATLAB (engine/matlab_bridge.py -> matlab/*.m -> Simulink)
batch.py  -->  sweep (ProcessPool Python, atau MATLAB parfor)  -->  batch*/results.jsonl
postrun.py --> batch/figures/*.png|pdf, postrun_summary.json  -->  report.py --> Laporan PDF
```

### Berkas utama

| Berkas | Isi |
|---|---|
| `server.py` | Server HTTP lokal (port 8034). API: `/api/init`, `/api/preset?id=&engine=`, `/api/run` (POST skenario), `/api/wave`, `/api/status`, `/api/catalog` (daftar run tersimpan), `/api/result?key=`, `/api/labels` (POST), `/batch/...`. Cache hasil per hash skenario di `cache/runs/<hash>/`. |
| `engine/network.py` | Data IEEE 34 (konfigurasi saluran 300-304, beban spot dan terdistribusi, kapasitor, regulator, XFM-1, trafo GI 2,5 MVA), Penyulang B ekuivalen, 5 titik IED (A1, A2, A3, L1, B1). |
| `engine/layout.py` | Koordinat SLD saja (dikecualikan dari fingerprint cache). |
| `engine/sim.py` | Engine Python: solver nodal 3 fasa fasor, dt = 1/960 s, CB buka 50 ms, pulau dan frekuensi, CLPU. |
| `engine/der.py` | Model DER: SG (E'' di belakang X''->X'->Xd), IBR-GFL (sumber arus, PLL, FRT IEEE 2800, Imax), IBR-GFM (sumber tegangan + pembatas arus), proteksi IEEE 1547. |
| `engine/relays.py` | Virtual IED: OCR 50/51 (IEC SI), DOCR 67/67N (kuadratur, 32Q/32V), Distance 21 mho 3 zona + k0, Differential 87L (persentase restraint, kanal 5 ms, sampel kedua ujung diselaraskan waktunya). |
| `engine/settings.py` | Koordinasi otomatis baseline (pickup 1,5x beban, CTI desain 0,3 s, 50 = 1,25x). Disimpan beku di `cache/settings.pkl`. |
| `engine/hunter.py` | Fault Hunter: ground truth radial, klasifikasi F-1 sampai F-5, confusion matrix. |
| `engine/results.py` | Paket hasil untuk UI, `WaveSource` (rekonstruksi gelombang sesaat + DC offset), simpan log. |
| `engine/scenarios.py` | 8 preset skenario (S0 baseline, S1 F-1, S2 F-2, S3 F-3, S4 F-4, S5 F-5, S6 NT CLPU, S7 awan lewat). |
| `engine/matlab_bridge.py` | Jembatan ke MATLAB: `export_config` (skenario -> netlist generik JSON), `load_results` (hasil MATLAB -> objek kompatibel `Simulator`), `MatlabSession` (satu sesi MATLAB persisten). |
| `matlab/sr34_build.m` | Membangun model Simscape Electrical (Specialized Power Systems, mode fasor 60 Hz) dari netlist. |
| `matlab/sr34_update.m` | Mengubah nilai blok saja bila struktur model sama (hemat waktu build). |
| `matlab/sr34_run.m` | Bangun/pakai ulang model, simulasi, simpan `simV`, `simI`, log kontroler ke .mat. |
| `matlab/sr34_ctrl.m` | Kontroler per langkah (blok Interpreted MATLAB Function): relai, DER, breaker, event. State persisten in-place. |
| `matlab/sr34_ctrl_state0.m`, `sr34_ctrl_outputs.m`, `sr34_ctrl_init.m`, `sr34_normalise.m` | State awal, pengemasan keluaran, nilai awal Unit Delay, normalisasi hasil `jsondecode`. |
| `matlab/sr34_batch.m` | Sweep MATLAB: serial (1 worker) atau `parfor`. |
| `matlab/sr34_worker_init.m` | Folder kerja/cache Simulink pribadi per sesi MATLAB (wajib untuk parfor). |
| `matlab/sr34_progress.m` | Menulis progres build/simulasi ke file (dipakai `MatlabSession.run`). |
| `matlab/sr34_polarity_test.m` | Uji konvensi polaritas blok SPS (lihat jebakan teknis). |
| `batch.py` | Kampanye sweep 5.247 kasus (H1, H2, E, I). Lihat bagian 5. |
| `postrun.py` | Lima gambar post-run + `postrun_summary.json` + `postrun_tables.csv`. |
| `report.py` | Laporan PDF Bahasa Indonesia (`batch/Laporan_PostRun_SimRelay34.pdf`). |
| `web/` | UI: `index.html`, `js/app.js`, `sld.js`, `scope.js`, `editor.js`, `css/app.css`, `img/logo-stei.png`. Halaman Post-Run dihapus dari UI (skrip `postrun.py`/`report.py` tetap ada). |
| `Jalankan SimRelay.bat`, `simrelay.ico` | Launcher satu klik untuk Windows (start server + buka Edge). |

### Engine MATLAB: alur satu simulasi

1. `export_config` mengubah skenario aplikasi menjadi netlist generik: node (0 = tanah,
   1..N = node-fasa bus), elemen `mutual` (saluran 3x3 R/L), `rl`, `cap`, `xf` (regulator/trafo
   per fasa), `brk` (breaker), `vsrc`/`isrc` (sumber terkendali), `imeas` (pengukuran arus seri),
   ditambah konfigurasi IED, DER, gangguan, event, dan `structure_key` (hash struktur tanpa nilai).
2. `sr34_run` membangun model (atau `sr34_update` bila struktur sama), lalu `sim`.
3. Setiap langkah, blok kontroler menerima semua tegangan node dan arus terukur, menjalankan
   relai/DER/event, lalu mengeluarkan status breaker dan fasor sumber untuk langkah berikutnya
   (melalui Unit Delay, sama dengan urutan engine Python).
4. Simulasi dimulai 0,1 s sebelum t = 0 (`T_INIT`) agar keluaran DER mencapai setpoint.
5. `load_results` membentuk objek setara `Simulator`; log relai (pickup/arah/trip) dibangun ulang
   dengan logika relai aplikasi di atas fasor terukur Simulink, waktu trip diambil dari MATLAB, dan
   ketidakcocokan dihitung di `replay_mismatch` (selama ini selalu 0).

### Pembagian kerja: Simulink vs rumus sendiri (penting untuk Bab 3)

Dihitung Simulink/Simscape: penyelesaian jaringan (KCL/KVL fasor) dan perilaku elemen (saluran
terkopel, trafo, breaker, pengukuran). Rumus/model buatan sendiri (sebagian besar dari standar,
tetapi dengan penyederhanaan atau nilai parameter yang dipilih sendiri):

| # | Model | Status |
|---|---|---|
| 1 | Impedansi saluran = data konfigurasi IEEE 34 x panjang | data standar |
| 2 | Semua beban impedansi konstan Z = V^2/S* | penyederhanaan (IEEE 34 punya PQ/I/Z) |
| 3 | Beban terdistribusi dibagi 50/50 ke ujung segmen | penyederhanaan |
| 4 | Regulator rasio 1 + 0,00625 tap, impedansi seri 0,01+j0,05 ohm | nilai impedansi dipilih sendiri |
| 5 | Gardu induk = sumber Thevenin (bukan belitan D-Yg) | penyederhanaan |
| 6 | SG = E'' di belakang X(t) meluruh X''->X'->Xd, eksitasi konstan, tanpa AVR/governor | IEC 60909; bukan blok Synchronous Machine |
| 7 | GFL = sumber arus, PLL ideal, lag 1 siklus, FRT Iq = 2(0,9 - V), Imax 1,2 pu | IEEE 2800 disederhanakan |
| 8 | GFM = sumber tegangan + impedansi virtual, batas arus 1,3 pu | nilai dipilih sendiri |
| 9 | Jalur urutan nol trafo Yg-D DER, Z0 = 0,01+j0,06 pu | asumsi |
| 10 | Ride-through dan anti-islanding DER | tabel IEEE 1547 disederhanakan |
| 11 | Frekuensi pulau: swing agregat + droop 5% | hanya untuk tampilan |
| 12 | Filter fasor relai = rata-rata 1 siklus | pendekatan respons DFT |
| 13-15 | Kurva IEC SI, 67 kuadratur/32Q/32V, 21 mho + k0, 87L slope 30%, aturan setting | standar IEC 60255 / praktik |
| 16 | Gelombang sesaat osiloskop = rekonstruksi dari fasor + DC offset (Python) | bukan keluaran Simulink |
| 17 | Kriteria Fault Hunter (misal CTI 0,2 s) | desain sendiri |
| 18 | Gangguan: Breaker Simscape dengan Ron = Rf; DLG = tiap fasa ke tanah lewat Rf + 1 mOhm antar-fasa | topologi dipilih sendiri (blok Three-Phase Fault tidak dipakai) |

## 3. Cara menjalankan

Lingkungan yang dipakai: Windows 11, Python 3.11, RAM 7,7 GB, MATLAB R2024b Update 1.

```bash
pip install numpy scipy matplotlib reportlab
pip install "matlabengine==24.2.*"      # hanya untuk engine MATLAB
python server.py                          # http://127.0.0.1:8034, preset dihitung otomatis
python server.py --precompute             # hitung semua preset lalu keluar
python batch.py                           # sweep Python 5.247 kasus (~30 menit) -> batch/
python batch.py --engine matlab           # sweep MATLAB parfor 2 worker -> batch_matlab/
python batch.py --engine matlab --pilot --outdir batch_matlab_pilot   # pilot 121 kasus
python postrun.py                         # gambar post-run dari batch/results.jsonl
python report.py                          # laporan PDF
```

Catatan:
- Engine MATLAB di UI: pilih **Engine: MATLAB Simulink** di header. Run pertama menyalakan MATLAB
  (~10-30 s) dan membangun model (~25 s); hasil di-cache terpisah dari engine Python.
- `cache/` dan `runs/` tidak ikut repo; dibangun ulang otomatis. Setting relai baseline dihitung
  ulang saat server pertama kali jalan (beberapa detik).
- `postrun.py` dan `report.py` membaca `batch/results.jsonl` (ikut di repo) dan menulis ke `batch/`.
- Di sesi cloud (Linux, tanpa MATLAB): aplikasi web, engine Python, batch Python, post-run, dan
  laporan bisa dijalankan; engine MATLAB tidak.

## 4. Status dan hasil validasi

Sudah selesai:
1. Aplikasi web lengkap (tema putih, bahasa Inggris formal), SLD IEEE 34 tanpa tumpang tindih,
   panah aliran daya beranimasi, osiloskop, SOE, inspector, editor DoF, playback. Halaman Post-Run
   sempat ada, lalu dihapus dari UI atas permintaan pengguna (akan dibuat ulang bersama katalog batch).
2. Preset dihitung sebelumnya dan di-cache di disk; ganti preset instan.
3. Kampanye Python 5.247 run dan post-run lengkap (lihat bagian 5) dengan laporan PDF 17 halaman.
4. Bug 87L diperbaiki: sampel kedua ujung kini diselaraskan terhadap tunda kanal dan memakai filter
   yang sama; sebelumnya 87L trip pada gangguan eksternal bahkan tanpa DER.
5. Engine MATLAB Simulink (Simscape Electrical) selesai dan tervalidasi:
   - Baseline: tegangan menyimpang 0,15% (tunak) dan 1,5% (saat gangguan); arus cabang <= 1,6%.
   - 8/8 skenario uji (semua F-1..F-5, semua kelas relai, semua jenis DER) menghasilkan klasifikasi
     Fault Hunter identik dengan engine Python, replay mismatch 0.
   - Pilot parfor 121 kasus (`batch_matlab_pilot/`): 121/121 identik dengan Python, 0 gagal,
     selisih waktu trip rata-rata 0,6 ms (maks 13,5 ms, 153 trip), 19,8 menit dengan 2 worker.
6. Launcher satu klik (`Jalankan SimRelay.bat`) dan shortcut desktop (dibuat ulang di PC baru).
7. Revisi kanvas SLD (`web/js/sld.js`, `engine/layout.py`):
   - Simbol IEC 60617 (CB tetap kotak SCADA), relai = kotak "R" dengan kabel CT/VT dan trip ke CB.
   - Layer komponen dan teks (tombol Layers), Key, dan ceklis besaran per komponen di info box.
   - Info box menjelaskan arti setiap warna komponen.
   - Warna netral default; amber = tegangan marginal; ungu = pickup relai; merah = tegangan
     kritis atau trip.
   - Saluran dianggap hidup bila bertegangan atau dialiri arus di atas 1 A.
   - Jalur arus gangguan (merah, layer ground truth) ditentukan secara topologi: lintasan dari
     sumber tersambung (grid via CB-GI, DER in service) ke titik gangguan lewat CB tertutup, dan
     hanya saluran yang berarus. Beban besar seperti CLPU tidak pernah ikut tertandai.
   - Layout ringkas (viewBox sekitar 1830 x 585). Bus yang kehabisan sisi menjadi busbar
     vertikal: semua sambungan masuk dari samping, dan bus sesudahnya bergeser ke kanan.
   - Alarm SCADA berbentuk tabel formal di panel kanan.
8. Top bar dan navigasi:
   - Logo STEI ITB dan judul "SimRelay 34" (font Space Grotesk). Font UI memakai IBM Plex Sans
     dan IBM Plex Mono.
   - Keterangan mode (saat ini View). Tombol Start Simulation (satu skenario) dan Start Campaign
     (banyak skenario) dinonaktifkan selama mode View; fungsinya belum dibuat.
   - Selector "Run" membuka katalog run tersimpan (preset dan run custom dari `cache/runs`),
     dilengkapi pencarian, filter (sumber, engine, outcome, tipe DER, tipe gangguan, kelas relai,
     label), serta Labels dan Notes yang bisa diedit.
   - Run ID adalah nomor urut run sesuai urutan dihasilkan (0001, 0002, dan seterusnya), tetap
     setelah diberikan (`runs/index.json`).
   - Labels dan notes disimpan di `runs/annotations.json`. Preset diberi label awal `PRE-S0` dan
     seterusnya, dengan notes nama presetnya.
   - Kasus batch belum masuk katalog (direncanakan nanti).
   - Aturan gaya UI: tanpa badge, chip, atau kotak bersudut bulat dengan isi berwarna cerah.
     Status ditulis sebagai teks berwarna dengan penanda kotak kecil, dan pemisah memakai garis
     tipis.

## 5. Ringkasan hasil kampanye Python (batch/)

5.247 kasus: H1 penetrasi x beban (2.013), H2 penetrasi x Rf (2.013), E eskalasi kelas relai (1.023),
I microgrid pulau (198). Setiap kasus = satu DER (SG Yg-D atau IBR-GFL) di bus 806/828/840/848/B03
dengan ukuran 0-120% beban puncak Penyulang A (1.769 kW), x 11 kasus gangguan
(SLG/3PH di 812, 830, 834, 848, B04; SLG di 822). Setting relai beku.

- Kasus gagal 1.018/5.247 (19,4%). Temuan: F-1 97, F-2 555, F-3 174, F-4 120, F-5 18, NT 88.
- Baseline 0% DER: OCR/DOCR/21 0% gagal; 87L 1 kasus (lateral 822 berada di dalam zona A1-A2).
- Beban puncak: laju gagal 0% -> 34,5% pada 120% DER; tipping point 80% DER.
- Dependability 100% -> 96,8%, security 100% -> 96,5% (pada 120%: 95,4% dan 93,0%).
- 120% DER per kelas: OCR 34,5%, DOCR 19,1%, Distance 4,5%, 87L 48,2% (didominasi NT).
- Polar rose: 30,8% sampel IBR terbaca FORWARD untuk gangguan reverse, vs 14,3% SG (F-4).
- R-X: dengan infeed, median |Z| A3 untuk gangguan di 848 naik 4,25 -> 5,91 ohm, melewati Z1 4,83 ohm (F-5).
- F-1 hanya muncul pada microgrid pulau yang didominasi IBR.

## 6. Status dan langkah berikutnya

Belum selesai / menunggu keputusan pengguna:
1. **Keputusan fidelitas model MATLAB** (ditanyakan, belum dijawab):
   (a) tetap seperti sekarang dan tabel bagian 2 dicantumkan sebagai metodologi;
   (b) upgrade ke blok bawaan Simscape (Synchronous Machine, inverter model rata-rata, Load Flow
       powergui, blok Three-Phase Fault) tetap mode fasor;
   (c) upgrade ke EMT untuk skenario utama, sweep tetap fasor.
2. **Sweep penuh 5.247 kasus dengan engine MATLAB** belum dijalankan (perkiraan 4-6 jam dengan
   2 worker karena RAM 7,7 GB). Pengguna diminta konfirmasi; terakhir menjawab untuk memindahkan
   proyek dulu.
3. **Uji tombol Engine = MATLAB di UI** belum tuntas (pada percobaan sebelumnya RAM habis karena
   pilot berjalan bersamaan).
4. **Popup progres** dibatalkan pengguna di tengah jalan ("kelamaan"). Yang sudah terpasang:
   pelaporan progres dari MATLAB (`sr34_progress.m`, polling di `MatlabSession.run` dengan callback
   `progress(stage, percent)`). Yang belum: endpoint `/api/progress`, `progress.json` di batch,
   dan popup di UI. Jangan lanjutkan kecuali diminta lagi.
5. README belum diperbarui untuk engine MATLAB (dokumen ini yang terbaru).
6. Laporan PDF masih memakai hasil engine Python; versi MATLAB menunggu poin 2. Halaman Post-Run
   di UI sudah dihapus dan akan dibuat ulang nanti.

Pertanyaan dosen yang sudah dijawab di percakapan (ringkas): dasar penempatan CB/IED dan DER
(pertimbangan rekayasa, bukan optimasi; IEEE 34 tidak menetapkan perangkat proteksi), metode sweep
(faktorial penuh satu-faktor-per-kampanye), metode kontrol DER (lihat tabel bagian 2; DER tidak
menyerap daya aktif karena tidak ada BESS), dan lokasi relai adaptif (lima titik yang sama;
prioritas A3, lalu A2/B1, arsitektur IED lokal + koordinator di GI; HIL di A3).

## 7. Jebakan teknis yang sudah ditemukan

- **BLAS multithread**: set `OPENBLAS_NUM_THREADS=1` sebelum import numpy. Tanpa itu satu run 8,5 s
  (vs 1,2 s) dan proses paralel bisa macet.
- **Polaritas SPS**: Controlled Voltage/Current Source punya terminal positif di sisi RConn
  (diverifikasi `sr34_polarity_test.m`); builder menyambung RConn ke node a.
- **Breaker SPS** dimodelkan sebagai sumber arus: wajib snubber resistif 1e6 ohm, kalau tidak
  muncul error "cannot be connected in series".
- **Current source** perlu shunt 1e6 ohm (beberapa topologi ditolak tanpa itu).
- Cabang tanpa reaktansi harus BranchType 'R' murni; RL dengan L ~1e-12 H memicu singularitas
  matriks induktansi.
- **parfor**: tiap worker perlu folder cache/codegen Simulink sendiri (`sr34_worker_init`), kalau
  tidak muncul "Nested invocation of Simulink.fileGenControl".
- **RAM**: satu sesi Simulink + Simscape ~1,5-2 GB. Pada 7,7 GB maksimal 2 worker; 6 worker crash.
- Fasor SPS dalam nilai puncak; bridge membagi/mengalikan sqrt(2).
- Fingerprint cache: `engine/*.py` kecuali `layout.py` dan `matlab_bridge.py` menentukan cache
  Python; hasil MATLAB juga bergantung pada `matlab/*.m` dan bridge.
- Git Bash di Windows sering gagal mem-parse heredoc panjang yang berisi kutip; tulis skrip ke file.
- Mengedit berkas `engine/*.py` mana pun (selain dua pengecualian di atas) mengubah fingerprint,
  sehingga semua cache preset dan setting baseline dihitung ulang saat server berikutnya start.
