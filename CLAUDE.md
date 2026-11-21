# SimRELAY: panduan untuk Claude

Test bench Software-in-the-Loop (SIL) untuk Tugas Akhir 18023047: membuktikan bahwa relai
konvensional salah kerja (F-1 sampai F-5) akibat penetrasi DER pada IEEE 34 Node Test Feeder,
sebagai dasar urgensi relai adaptif.

**Baca `docs/HANDOVER.md` lebih dulu.** Isinya: status pekerjaan, arsitektur, cara build dan
menjalankan, hasil validasi, keputusan yang masih menunggu pengguna, dan jebakan teknis yang
sudah ditemukan. Kalau pengguna berkata "migrasi kesini" atau "lanjutkan", mulai dari bagian
"Status dan langkah berikutnya" di dokumen itu. Pekerjaan campaign "Proof of Urgencies TA Proteksi
Adaptif" (PoU) direncanakan di `docs/CAMPAIGN_PoU.md`.

## Ringkas

- Aplikasi web lokal: `python server.py` lalu buka http://127.0.0.1:8034 (Windows: `Jalankan SimRELAY.bat`).
- Dua engine dengan antarmuka identik:
  - Python (`engine/sim.py`), cepat, dipakai untuk sweep 5.247 run.
  - MATLAB Simulink / Simscape Electrical (`engine/matlab_bridge.py` + `matlab/*.m`), mode fasor.
    Butuh MATLAB R2024b dengan Simulink, Simscape, Simscape Electrical, Parallel Computing
    Toolbox, dan paket Python `matlabengine==24.2.*`. **Tidak bisa dijalankan di sesi cloud**
    (tidak ada MATLAB); di cloud hanya engine Python dan aplikasi web yang bisa diuji.
- Sweep: `python batch.py` (Python) atau `python batch.py --engine matlab` (parfor, default 2 worker).
- Post-run: `python postrun.py` (lima gambar) lalu `python report.py` (laporan PDF Bahasa Indonesia).

## Preferensi pengguna (wajib diikuti)

- Teks di UI website: bahasa Inggris formal dan baku. Jangan pakai em dash, titik tengah, atau
  panah sebagai tanda baca di teks UI. Gaya putih, bersih, modern, profesional.
- Laporan untuk Tugas Akhir: Bahasa Indonesia baku. Label di dalam gambar tetap bahasa Inggris.
- Pengguna menjawab dan bertanya dalam Bahasa Indonesia; jawab dalam Bahasa Indonesia.
- Jujur soal keterbatasan model: bedakan mana yang dihitung Simulink dan mana rumus buatan sendiri
  (lihat tabel di HANDOVER).
- Jalankan proses numpy dengan `OPENBLAS_NUM_THREADS=1` (sudah diset di `server.py` dan `batch.py`);
  tanpa itu simulasi 7 kali lebih lambat dan macet saat paralel.
