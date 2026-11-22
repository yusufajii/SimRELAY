# Campaign "Proof of Urgencies TA Proteksi Adaptif" (PoU): rencana kerja

Ditulis 21 November 2026. Status: **empat pertanyaan di bagian 8 disetujui pengguna (21 November
2026, semua sesuai default usulan). Infrastruktur dan pilot sedang dikerjakan.** Sweep penuh 5.247
kasus tetap menunggu perintah pengguna.

## 1. Permintaan pengguna (ringkas)

- Campaign 5.247 skenario (definisi di `batch.py`, ringkasan di HANDOVER bagian 5) mulai sekarang
  disebut **Proof of Urgencies TA Proteksi Adaptif** (PoU). Tujuannya tetap Fault Hunter
  (F-1 sampai F-5 dan NT).
- **Seluruh acuan (anchor) pindah ke MATLAB Simulink**, bukan Python. Kampanye Python di `batch/`
  tetap disimpan sebagai pembanding.
- Saat campaign MATLAB berjalan, semua skenario disimpan sebagai cache. Agar tidak terlalu besar,
  model disimpan per topologi identik.
- Tombol **Simulink** di UI harus langsung membuka file Simulink yang sudah ada, bukan membangun
  model dari awal.
- Tambah tombol **Go to Folder** di Run selector yang membuka folder tempat run itu disimpan.
- Perintah tetap yang masih berlaku: **jangan menjalankan sweep 5.247 kasus dan jangan mengubah
  model sebelum pengguna memutuskan.**

## 2. Kondisi kode saat ini (hasil penelusuran)

- `server.py` `_load_settings()`: bila fingerprint engine Python berubah, seluruh `cache/runs`
  dihapus (`shutil.rmtree`). Karena itu hasil campaign **tidak boleh** disimpan di `cache/`.
- Cache run: `cache/runs/<key>/` berisi `result.json` (sekitar 900 KB, belum dikompresi),
  `wave.npz` (sekitar 40 KB), `wave.json`, `meta.json`. Kunci = `scenario_key(sc)`; run MATLAB
  memasukkan `MATLAB_FP` ke kunci.
- `matlab/sr34_run.m`: model `sr34_model` dibangun ulang bila `cfg.structure_key` berbeda dengan
  Tag model, selain itu hanya `sr34_update`. Model **tidak disimpan** ke disk.
- `matlab/sr34_open.m` (tombol Simulink, `/api/simulink/open`): membangun model yang sama, menyimpan
  ke `cache/simulink/sr34_model.slx` (selalu ditimpa, satu file), memasang `InitFcn`/`StopFcn`
  (`sr34_editor.m`), lalu membuka editor. Sekitar 65 s termasuk build.
- `batch.py --engine matlab`: kasus diurutkan per `structure_of(c) = (fleet, bus, ftype)`, dikirim
  per chunk ke `sr34_batch.m` (parfor, default 2 worker), file io di `<outdir>/io/`, hasil ringkas
  ke `<outdir>/results.jsonl`. Hasil per kasus (gelombang, result lengkap) tidak disimpan.
- Katalog Run (`/api/catalog`, `catalogue()` di `server.py`) hanya membaca `cache/runs`. Run ID
  berurutan di `runs/index.json`. Kasus batch belum masuk katalog.
- Pilot MATLAB 121 kasus (`batch_matlab_pilot/`) dibuat **sebelum PR 4** (model komposit), jadi
  fingerprint MATLAB sudah berubah sejak itu.

## 3. Struktur penyimpanan yang direncanakan

```
campaigns/PoU-TA-Proteksi-Adaptif/      (di luar cache/, masuk .gitignore)
  campaign.json        definisi campaign, MATLAB_FP, ringkasan setting relai beku, tanggal, worker
  results.jsonl        satu baris ringkasan Fault Hunter per kasus (format sama dengan batch/)
  models/T001.slx ...  satu model Simulink per topologi identik, plus models/index.json
                       (structure_key -> T###, daftar kasus yang memakainya)
  runs/<run>/          scenario.json, cfg.json, result.json.gz, wave.npz, sim.mat (mentah),
                       topology.txt (menunjuk ke models/T###.slx)
```

- Topologi ditentukan oleh `structure_key` dari bridge. Perkiraan: 14 variasi DER (tanpa DER,
  10 penempatan SG/IBR-GFL, 3 microgrid pulau) x 11 gangguan = **sekitar 154 topologi**.
  Beban, Rf, penetrasi, dan kelas relai hanya mengubah nilai. Angka pasti dihitung saat implementasi.
- Perkiraan ukuran: model sekitar 1,1 MB x 154 = 170 MB; run sekitar 5.247 x (150 KB result
  terkompresi + 40 KB wave + 60 KB cfg) = 1,3 GB; ditambah `.mat` mentah (ukuran diukur saat pilot).
  Ruang kosong disk C: 54 GB (21 November 2026).

## 4. Penyimpanan model per topologi (sisi MATLAB)

- `sr34_run` (atau pembungkus baru untuk campaign) menerima folder model. Setelah `sr34_build`
  untuk struktur baru, model disimpan ke `models/T###.slx` bila belum ada.
- Jebakan: `save_system(mdl, path)` dengan nama file berbeda mengganti nama model di memori.
  Rencana: beri nama model sama dengan nama topologi (misalnya `T042`) sejak build, atau simpan
  lewat salinan. Dengan parfor, hanya worker yang membangun struktur itu yang menyimpan; nama file
  unik per struktur sehingga tidak bentrok. Ingat jebakan parfor di HANDOVER bagian 7.
- Callback editor (`InitFcn`/`StopFcn`) jangan ikut tersimpan aktif saat run engine (`SR34_ENGINE`).

## 5. Tombol Simulink

- Run campaign: buka `models/T###.slx` (`open_system`), terapkan nilai kasus dengan `sr34_update`
  memakai `cfg.json` run itu, pasang `InitFcn`/`StopFcn` ke cfg run itu, lalu tampilkan. Tanpa build.
- Run custom di luar campaign: tetap dibangun sekali, lalu disimpan ke cache topologi umum
  (misalnya `cache/simulink/models/`) sehingga pembukaan berikutnya langsung.
- `import_simulink_run` saat ini membaca `cache/simulink/scenario.json` dan `sr34_model_cfg.json`;
  perlu diubah agar mengikuti run/topologi yang sedang dibuka.
- Bila MATLAB belum menyala tetap ada jeda sekitar 30 s untuk start.

## 6. Katalog Run dan tombol Go to Folder

- Run campaign masuk Run selector dengan sumber "Campaign: Proof of Urgencies" dan Run ID terpisah
  `PoU-0001` sampai `PoU-5247` (menunggu persetujuan), sehingga nomor run biasa tidak membengkak.
- Filter tambahan: sub-kampanye H1/H2/E/I, penetrasi, beban, Rf, bus dan jenis gangguan, kelas relai,
  temuan F-1 sampai F-5. Karena ribuan baris, filter dan pencarian dijalankan di server dan daftar
  dimuat bertahap.
- Endpoint baru, misalnya `POST /api/reveal {key}`, membuka Windows Explorer di folder run
  (`explorer /select,` atau `os.startfile`). Hanya berlaku karena server berjalan di PC yang sama.
- Ikuti aturan gaya UI (HANDOVER bagian 4 butir 8 dan CLAUDE.md): bahasa Inggris formal, tanpa
  em dash/titik tengah/panah sebagai tanda baca, tanpa badge atau chip.

## 7. Urutan kerja

1. Bangun infrastruktur (bagian 3 sampai 6) dan uji pada beberapa kasus.
2. Jalankan ulang **pilot 121 kasus** dengan model komposit saat ini ke folder campaign uji:
   buktikan hasil identik dengan Python, ukur kecepatan, RAM, dan ukuran `.mat` di PC ini
   (sekitar 20 menit).
3. Laporkan estimasi waktu sweep penuh, lalu **tunggu perintah pengguna** sebelum menjalankan
   5.247 kasus. Sweep di latar belakang, dapat dilanjutkan bila terputus (resume dari `results.jsonl`),
   PC dijaga tetap menyala. Estimasi: HANDOVER menyebut 4-6 jam dengan 2 worker; ekstrapolasi
   kecepatan pilot lama memberi sampai sekitar 14 jam (sweep penuh lebih jarang membangun ulang model).
4. Setelah selesai: `postrun.py` dan `report.py` dibuat ulang dari hasil MATLAB (perlu opsi folder
   masukan), kampanye Python tetap sebagai pembanding.

Kejujuran metodologi: jaringan, DER, relai, dan breaker disimulasikan di Simulink; klasifikasi
Fault Hunter dan rekonstruksi gelombang osiloskop tetap dihitung Python dari keluaran Simulink
(sama dengan engine MATLAB saat ini). Lihat tabel HANDOVER bagian 2.

## 8. Keputusan pengguna (disetujui 21 November 2026, semua sesuai default dalam kurung)

1. Fidelitas model dikunci di versi sekarang, opsi (a) HANDOVER bagian 6, dengan tabel
   penyederhanaan sebagai metodologi? (Ya. Bila nanti pindah ke opsi b atau c, campaign diulang.)
2. Run ID campaign memakai format terpisah `PoU-0001` sampai `PoU-5247`? (Ya.)
3. File `.mat` mentah dari Simulink ikut disimpan? (Ya, bila ukurannya wajar setelah pilot.)
4. Jumlah worker: mulai 2 (RAM 11,9 GB, 4 thread), dinilai ulang dari pemakaian RAM saat pilot? (Ya.)

## 9. Lingkungan PC ini

Windows 10, RAM 11,9 GB, 4 thread, MATLAB R2024b Update 10. Python proyek: `.venv` (Python 3.11,
`matlabengine` 24.2); Python bawaan 3.14 tidak bisa memakai MATLAB. Jalankan sweep dengan
`.venv\Scripts\python batch.py ...`. Server: `Jalankan SimRELAY.bat` atau `.claude/launch.json`.

## 10. Implementasi (21 November 2026)

Infrastruktur bagian 3 sampai 6 sudah dibangun. Ringkasan per berkas:

- `campaign.py` (baru, di root): lokasi folder campaign, Run ID `PoU-####` (urutan definisi penuh
  `build_cases`, jadi kasus pilot memakai nomor yang sama dengan sweep penuh), indeks topologi
  (`models/index.json`), penyimpanan satu run (`save_run`), dan `Store` untuk server (membaca semua
  `campaigns/*/results.jsonl`, dimuat ulang bila berkas berubah). Fingerprint engine dipindah ke sini
  dari `server.py` (isi hash tidak berubah, jadi `cache/runs` tidak terhapus).
- `batch.py --campaign [--pilot] [--workers N] [--limit N] [--outdir D]`: memaksa engine MATLAB,
  menulis ke `campaigns/PoU-TA-Proteksi-Adaptif/` (atau `campaigns/PoU-pilot/`), menetapkan topologi
  tiap kasus dari `structure_key`, mengirim `slx_file` ke MATLAB, dan menyimpan tiap kasus lengkap
  di `runs/PoU-####/` (`scenario.json`, `cfg.json.gz`, `result.json.gz`, `wave.npz`, `wave.json`,
  `sim.mat`, `topology.txt`). `campaign.json` mencatat definisi, fingerprint MATLAB, hash
  `settings.pkl`, ringkasan setelan relai beku, waktu mulai/lanjut/selesai. Resume tetap dari
  `results.jsonl`; peringatan dicetak bila fingerprint MATLAB berubah di tengah campaign.
- `matlab/sr34_store_model.m` (baru) dan `sr34_run.m`: model topologi disimpan sekali sebagai
  `models/T###.slx`. Jebakan: setelah `save_system`, model di memori terikat pada berkas itu; berkas
  sementara dihapus membuat `sim()` gagal ("is not a valid Simulink object name"). Karena itu salinan
  privat per proses disimpan di `tempdir/sr34_store_<pid>/` dan tidak dihapus.
- `matlab/sr34_open.m`: argumen `stored`. Bila berkas topologi ada, dibuka langsung dengan
  `load_system` lalu `sr34_update` (tanpa build); bila belum ada, dibangun sekali lalu disimpan.
  Run di luar campaign memakai cache topologi `cache/simulink/models/sr34_<structure_key>.slx`.
  `sr34_editor.m` mengirim juga path cfg ke `/api/simulink/import`, sehingga impor mengikuti model
  yang sedang dibuka (`cache/simulink/<model>_cfg.json` dan `<model>_scenario.json`).
- `server.py`: run campaign dibaca dari folder campaign (`result.json.gz`), katalog menggabungkan
  run biasa dan run campaign, `POST /api/simulink/open` menerima `_run_key`, endpoint baru
  `POST /api/reveal {key}` membuka folder run di Explorer (hanya dari 127.0.0.1).
- UI (`web/js/app.js`): sumber "Campaign: Proof of Urgencies TA Proteksi Adaptif", filter bagian
  campaign, penetrasi, beban, Rf, dan bus gangguan (hanya muncul bila ada run campaign), tombol
  Go to Folder di tiap baris Run selector, daftar dibatasi 300 baris dengan "Show more". Berbeda
  dari rencana bagian 6: filter tetap di browser (5.247 baris cukup cepat), yang dibatasi hanya
  jumlah baris yang digambar.

Uji 4 kasus (`campaigns/PoU-test2/`, 1 worker): Fault Hunter dan waktu trip identik dengan Python,
replay mismatch 0. Per run sekitar 114 KB (`sim.mat` 55 KB, `result.json.gz` 12 KB, `cfg.json.gz`
12 KB, `wave.npz` 24 KB); per topologi 1,1 MB. Tombol Simulink pada run campaign: 82 s termasuk
start MATLAB dan editor pertama kali, 15 s untuk topologi berikutnya (tanpa build; sebelumnya
sekitar 65 s build). Folder `campaigns/PoU-test/` berisi uji pertama yang gagal (bug di atas) dan
boleh dihapus.

### Hasil pilot 121 kasus (`campaigns/PoU-pilot/`, 21 November 2026, 2 worker)

- Selesai dalam 49,1 menit, tidak ada kasus gagal, replay mismatch 0 pada semua kasus.
- Fault Hunter identik dengan engine Python pada **121 dari 121 kasus** (F-2: 32 kasus, F-3: 6 kasus,
  sama persis). Tidak ada perbedaan trip atau tidak trip.
- Waktu trip: 131 dari 153 trip sama dalam satu langkah (1,04 ms). Selisih terbesar 13,5 ms pada B1
  (trip simpatetik lambat sekitar 1,1 s, SG di B03, gangguan 830), sekitar 1,2 persen dari waktu
  trip kurva inverse; klasifikasi tidak berubah.
- Waktu per kasus di MATLAB: simulasi median 8,9 s (rata-rata 12,2 s), build model median 27 s
  (rata-rata 34 s), pemrosesan Python 1,3 s. Pilot membangun model untuk setiap kasus karena 121
  kasusnya memakai 121 topologi berbeda.
- RAM: dua worker sekitar 2 GB masing-masing, sesi utama sekitar 1,5 GB; RAM bebas terendah 317 MB
  (rata-rata 2,7 GB) dengan MATLAB server sesi lain ikut menyala.
- Ukuran: `sim.mat` median 55 KB tanpa DER, 0,8 MB dengan SG, 2,4 MB dengan IBR (log controller lebih
  panjang); total 2,3 MB per run. Model 1,17 MB per topologi.

Estimasi sweep penuh 5.247 kasus (154 topologi): sekitar 64.000 s simulasi ditambah sekitar 500
build (dua worker dan batas chunk membuat satu topologi bisa dibangun lebih dari sekali) sekitar
17.000 s, dibagi 2 worker: **sekitar 10 sampai 12 jam**. Dengan 3 worker (hanya bila server sesi lain
dimatikan dan RAM bebas cukup) sekitar 8 jam. Ruang disk sekitar 12 GB (sebagian besar `sim.mat`)
ditambah 0,2 GB model; ruang kosong 54 GB.

## 11. Campaign probe: mencari skenario yang lolos dari Fault Hunter (22 November 2026)

Tujuan: sebelum sweep penuh, memastikan tidak ada salah kerja yang masih berada di dalam derajat
kebebasan test bench tetapi tidak terdeteksi Fault Hunter atau tidak pernah disentuh sweep.
Skrip: `probe.py` (engine Python, 97 kasus ditambah 30 baseline tanpa DER, durasi 4 s, sekitar 10
menit dengan 2 proses). Hasil: `probe/PROBE_RESULTS.md`, `probe/summary.json` (tidak di-commit,
dibuat ulang dengan `python probe.py`, atau `python probe.py --report` dari hasil yang ada).

Setiap kasus diperiksa dua kali: oleh Fault Hunter dan oleh *oracle* independen yang hanya melihat
hasil fisik:
- DELAY: primary trip lebih dari dua kali lebih lambat daripada gangguan yang sama tanpa DER dan
  paling sedikit 0,2 s lebih lambat;
- NOTRIP: tidak ada relai yang trip selama run;
- BACKFEED: gangguan masih dicatu DER lebih dari 0,1 s setelah CB relai di jalur gangguan membuka.

Kasus yang ditandai oracle tetapi tidak berlabel Fault Hunter disebut titik buta.

| Hipotesis | Kasus | Label Fault Hunter | Flag oracle | Titik buta |
|---|---|---|---|---|
| A1 Pemadaman tertunda tidak dilabeli (DER di 806, gangguan 812) | 12 | 0 | 12 | 12 |
| A2 Gangguan Rf 50 Ω yang lewat jendela run | 5 | 0 | 5 | 5 |
| A3 Gangguan tetap dicatu DER setelah relai membuka | 10 | 4 | 6 | 6 |
| B1 Gangguan LL dan DLG | 24 | 11 | 11 | 9 |
| B2 Lokasi gangguan di luar sweep (840, 890, 864, 820, B05) | 14 | 4 | 3 | 3 |
| B3 Trafo IBR D-Yg dibanding Yg-D | 8 | 5 | 1 | 0 |
| B4 Dua DER sekaligus | 12 | 5 | 6 | 4 |
| B5 Mode kendali IBR (urutan negatif, momentary cessation, prioritas P) | 12 | 4 | 8 | 4 |

Temuan:
1. **Pemadaman tertunda (A1) terbukti titik buta.** DER di 806 (trafo Yg-D) mengalihkan arus
   gangguan dari A1, sehingga elemen 50 A1 tidak lagi menjangkau gangguan SLG di 812. Waktu trip
   naik dari 0,015 s menjadi 0,65 sampai 0,76 s (sekitar 50 kali), tetapi Fault Hunter mencatat
   normal karena F-1 hanya untuk primary yang tidak trip sama sekali. Data sweep Python sudah
   memuat 42 kasus seperti ini yang berlabel normal.
2. **Durasi run 1,6 s memotong kejadian (A2, B2).** Gangguan SLG 812 dengan Rf 50 Ω dan DER di 806
   baru di-trip A1 pada 1,3 sampai 1,6 s setelah gangguan, di luar jendela sweep (1,3 s). Di sweep
   Python 21 kasus tercatat primary tidak trip tetapi berlabel normal. Gangguan di 890 (sisi
   4,16 kV XFM1) bahkan **tanpa DER** baru di-trip A2 pada 1,39 s (SLG) dan 1,59 s (3PH); dengan SG di
   848 gangguan 3PH di 890 baru di-trip 3,05 s. Ini celah desain proteksi (tidak ada relai untuk
   cabang XFM1), bukan semata akibat DER.
3. **Backfeed setelah relai membuka (A3, B1, B4) adalah titik buta terbesar.** Bila DER berada di
   hilir CB yang membuka, gangguan tetap dicatu dalam pulau tak disengaja sampai proteksi DER
   bekerja. Lamanya 2,0 s, sesuai anti-islanding 2 s dan UV2 kategori III (0,50 pu, 2 s) IEEE 1547.
   Ini diizinkan standar interkoneksi, tetapi bagi proteksi berarti busur gangguan bertahan 2 s
   dan reclosing akan gagal. Oracle menandai 48 dari 97 kasus; Fault Hunter tidak pernah
   memeriksanya.
   *Keterbatasan model:* backfeed dari IBR-GFL bergantung model. Di engine, GFL tetap menjadi sumber
   arus di dalam pulau; inverter nyata dengan PLL kemungkinan kehilangan sinkron dan berhenti lebih
   cepat. Backfeed dari SG lebih dapat dipercaya.
4. **Mekanisme lama muncul di jenis dan lokasi gangguan baru (B1, B2, B4):** F-3 pada gangguan LL
   dan DLG (50P/50N A2 overreach karena infeed SG di 828), F-4 pada DLG dengan DOCR dan IBR, dan
   **F-1 dalam mode grid** (SG di 848, SLG di 890; di sweep Python F-1 mode grid hanya 3 dari 97). Ini memperluas bukti, bukan mekanisme baru.
5. **Trafo IBR D-Yg (B3):** F-3 hilang untuk IBR di 828 (gangguan 834), jadi sumber urutan nol trafo
   Yg-D memang penyebabnya. F-2 dengan IBR di B03 dan 848 tetap muncul, digerakkan arus fasa (51P B1)
   dan perilaku pulau setelah A2 membuka. Jadi F-2 tidak hanya berasal dari urutan nol.
6. **Mode kendali IBR (B5) belum informatif.** Momentary cessation baru aktif di bawah 0,50 pu dan
   injeksi urutan negatif tidak mendapat sisa arus karena arus IBR sudah di batas Imax, sehingga
   hasilnya identik dengan prioritas Q. Untuk menguji hipotesis ini parameternya perlu diubah
   (Imax, ambang cessation), dan itu keputusan model.

Keputusan yang diperlukan sebelum sweep penuh (belum diputuskan pengguna):
- D1. Menambahkan label baru di Fault Hunter: pemadaman tertunda (perluasan F-1) dan backfeed
  setelah relai membuka (kode baru). Ini mengubah klasifikasi, bukan model fisik, tetapi mengubah
  angka laju salah kerja dibanding hasil Python.
- D2. Durasi run: tetap 1,6 s (waktu sweep MATLAB sekitar 10 sampai 12 jam), atau 3 s ke atas agar
  trip lambat dan backfeed 2 s teramati (waktu simulasi kira-kira naik sebanding dengan durasi).
- D3. Menambah sub-kampanye: gangguan LL/DLG, lokasi 840/890/864/820/B05, dua DER, trafo IBR D-Yg.

### Putaran kedua (22 November 2026): Fault Hunter diperbarui dan reverse engineering premis

Pengguna menyetujui kategori baru. Perubahan di `engine/hunter.py`:
- **F-1 diperluas.** F-1 sekarang juga mencakup:
  - primary yang trip lebih dari dua kali lebih lambat dan paling sedikit 0,2 s lebih lambat
    daripada gangguan yang sama tanpa DER;
  - kasus tanpa relai yang trip sama sekali, padahal tanpa DER ada relai yang memutus gangguan.

  Baseline tanpa DER disimulasikan sekali dengan engine Python lalu di-cache di
  `cache/baseline/<versi engine>/`. Baseline yang sama dipakai juga untuk engine MATLAB, karena
  waktu trip kedua engine sama dalam satu sampai dua langkah. Gangguan sementara (`t_off`) tidak
  diberi F-1 karena tidak trip.
- **F-6 Sustained DER Backfeed (baru).** Arus gangguan di atas 1 A yang masih mengalir lebih dari
  0,1 s setelah CB pertama di jalur gangguan membuka. Dinilai dari arus gangguan saja, jadi berlaku
  sama untuk kedua engine.
- **NT dalam skenario bergangguan.** Trip yang elemennya sudah pickup oleh arus beban sebelum
  gangguan, atau trip yang terjadi lebih dari 50 ms setelah gangguan sementara padam, dilabeli NT,
  bukan F-2 atau F-3.

Premis setiap aturan yang diuji di set 2 (`python probe.py --set 2`, 110 kasus): C1 relai jarak
dengan Rf, C2 fasa B/C dan lateral satu fasa, C3 gangguan sementara, C4 mode pulau, C5 kelas relai
campuran, C6 gangguan di terminal CB dan bus 800, C7 dua gangguan, C8 GFM mode grid, C9 DER di sisi
4,16 kV, C10 tanpa gangguan (aliran daya balik).

Hasil akhir dengan Fault Hunter baru: **tidak ada titik buta yang tersisa** di set 1 (97 kasus) dan
set 2 (110 kasus). Sisa flag oracle tanpa label adalah positif palsu oracle: C10 tanpa gangguan
memang tidak trip, dan backfeed 0,95 A di mode pulau berada di bawah ambang 1 A.

Temuan tambahan yang perlu dicatat di laporan:
- **Aliran daya balik.** DER di B03 (SG maupun IBR) sebesar 90% atau lebih pada beban rendah
  membuat B1 trip **tanpa gangguan**, karena arus balik 25 sampai 40 A melebihi pickup 51P B1 yang
  19 A. Di sweep, trip B1 seperti ini sebelumnya ikut dihitung F-2; dengan aturan baru menjadi NT.
- **Relai jarak dengan Rf 5 Ω sudah gagal tanpa DER.** F-3 sudah muncul tanpa DER, karena cakupan
  resistif mho terbatas. Itu keterbatasan setting, bukan akibat DER. Dengan Rf 20 Ω dan DER di 848,
  tidak ada relai yang trip (F-1), sedangkan tanpa DER zona 3 masih memutus.
- Angka sweep Python lama (19,4% salah kerja) belum memakai aturan baru dan perlu dihitung ulang
  sebelum dibandingkan dengan sweep MATLAB.

### Persiapan sweep MATLAB dengan anchor MATLAB (22 November 2026)

Pengguna memutuskan sweep Python tidak dihitung ulang. **Semua acuan memakai MATLAB.**
- **Dua fase `batch.py --campaign`.**
  - Fase 1 menjalankan 99 kasus tanpa DER (H1, H2, E pada 0%).
  - Fase 2 menjalankan kasus ber-DER. Fault Hunter menilai pemadaman tertunda (F-1) terhadap
    anchor MATLAB dengan beban, Rf, bus, jenis gangguan, dan kelas relai yang sama (`anchor_key`).
  - Kasus pulau (I) tidak punya anchor.
  - Field `anchor` di setiap record mencatat sumber acuannya.
- **Perbaikan dari uji label ulang pilot.**
  - Event relai hasil replay MATLAB tidak urut waktu, jadi sekarang diurutkan dulu.
  - Trip relai **di jalur gangguan** tidak pernah dianggap trip beban. Trip yang terlambat di sana
    dinilai sebagai F-1.
- **Label ulang pilot 121 kasus.** Pilot dilabel ulang dari `sim.mat` yang tersimpan, hanya untuk
  pemeriksaan; berkas pilot tidak diubah.

  | Kode | Sebelum | Sesudah |
  |---|---|---|
  | F-2 | 32 | 16 |
  | F-3 | 6 | 6 |
  | NT (trip B1 oleh aliran daya balik dari DER di B03) | 0 | 16 |
  | F-1 (pemadaman tertunda) | 0 | 2 |
  | F-6 | 0 | 38 |

  Kasus dengan minimal satu temuan naik dari 38 menjadi 70 dari 121. F-6 mendominasi, jadi laporan
  sebaiknya menampilkan laju salah kerja dengan dan tanpa F-6.
- Durasi run tetap 1,6 s. F-6 tetap terdeteksi, tetapi lamanya tercatat sebagai batas bawah
  ("atau lebih").

### Sweep dalam 5 bagian dan cara menjalankannya (22 November 2026)

- **Pembagian part.** `batch.py --campaign --part N` (N = 1 sampai 5) membagi 5.148 kasus ber-DER
  menjadi 5 bagian, masing-masing sekitar 1.035 kasus atau sekitar 2 sampai 2,5 jam. Satu topologi
  tidak pernah dipecah ke dua bagian. Anchor tanpa DER (99 kasus) selalu dijalankan lebih dulu bila
  belum ada, jadi bagian mana pun boleh dijalankan lebih dulu. Lihat status dengan
  `Jalankan Sweep.bat list`.
- **Peluncuran.** Setiap bagian dijalankan dengan `Jalankan Sweep.bat N`:
  - kode dijalankan dari salinan beku `.sweep\` (dibuat sekali, dipakai semua bagian; daftar berkas
    yang belum di-commit dicatat di `.sweep\snapshot.json`);
  - berjalan di jendelanya sendiri dengan prioritas below normal;
  - log ditulis ke `campaigns/PoU-TA-Proteksi-Adaptif/logs/partN.log`.

  Perubahan kode di repo, termasuk engine dan UI, tidak memengaruhi sweep yang berjalan. Hapus
  `.sweep\` hanya bila ingin memakai kode baru, dan jangan di tengah campaign.
- **Resume.** Tutup jendela untuk berhenti, lalu jalankan bagian yang sama lagi untuk melanjutkan.
  Run yang sudah tersimpan dilewati.
- **Pengaman.**
  - Sweep menahan Windows agar tidak sleep sendiri, tanpa bergantung pada Claude.
  - `sweep.lock` mencegah dua bagian berjalan bersamaan.
- **Uji.** Diuji dari snapshot ke `campaigns/PoU-test-parts/`:
  - 2 anchor (fase 1);
  - 1 kasus ber-DER (fase 2, PoU-3369: F-1 terhadap anchor MATLAB plus F-6).

  Folder uji boleh dihapus.

### Pelaksanaan dan hasil sweep penuh (22 November 2026)

- **Pelaksanaan.** Part 1 berjalan dengan 3 worker (03:14 sampai 04:35, 80,3 menit, termasuk 99
  anchor). Part 2 sampai 5 dijalankan berantai oleh `Jalankan Sweep.bat 2` dengan 4 worker
  (07:02 sampai 11:17; 62,9, 69,0, 62,1, dan 60,4 menit). Fallback ke 3 worker tidak pernah terpicu.
  Kecepatan sekitar 13 kasus/menit dengan 3 worker dan sekitar 16 kasus/menit dengan 4 worker; CPU
  2 core fisik adalah batasnya.
- **Launcher sekarang.** `Jalankan Sweep.bat N [W]` menjalankan part N sampai 5 berurutan dengan W
  worker (default 4). Bila MATLAB berhenti dengan galat, semua proses MATLAB ditutup dan part yang
  sama dilanjutkan dengan 3 worker (berlaku juga untuk part berikutnya). Part yang masih memiliki
  kasus gagal di MATLAB diulang sekali. Catatan runner: `logs/runner.log`. Launcher menolak berjalan
  bila sweep lain masih aktif. Jalankan dari Explorer agar tidak terikat ke proses Claude.
- **Kelengkapan.** 5.247 dari 5.247 kasus tersimpan, tanpa galat. 4.950 kasus ber-DER dilabeli
  dengan anchor MATLAB; 198 kasus islanding tidak memiliki anchor (sesuai rancangan). Dua kasus
  (PoU-3320, PoU-3788) memiliki selisih satu event antara Simulink dan replay Python.
- **Ringkasan.** Dari 5.148 kasus ber-DER, 2.553 (49,6%) salah kerja; 1.060 (20,6%) tanpa F-6; 835
  (16,2%) tanpa F-6 dan NT. Jumlah kasus per kode: F-6 1.655, F-2 420, NT 225, F-1 224, F-3 173,
  F-4 68, F-5 18. Satu anchor (PoU-4717, DIFF, 822 SLG) sudah F-3 tanpa DER, artinya miskoordinasi
  bawaan setelan dasar. F-6 bergantung pada asumsi DER tanpa anti-islanding, sehingga laju kegagalan
  dilaporkan dengan dan tanpa F-6.

### Memindahkan hasil ke komputer lain (`sync.py`, 22 November 2026)

- `Ekspor Hasil.bat` (atau `python sync.py export [--raw]`) membuat paket .zip di `sync/`:
  - **view** (sekitar 3,7 GB): semua yang dibaca aplikasi, `postrun.py`, dan `report.py`, yaitu
    `campaign.json`, `results.jsonl`, `batch_results.*`, log, `models/index.json`, dan setiap folder
    run tanpa `sim.mat`;
  - **raw** (sekitar 9,5 GB): `runs/*/sim.mat` dan `models/*.slx`, hanya untuk melabel ulang Fault
    Hunter atau membuka model di Simulink.
- `Impor Hasil.bat` (atau `python sync.py import [zip ...]`) mengambil paket terbaru di `sync/` atau
  folder Downloads, memeriksa manifest dan CRC, lalu mengekstrak ke `campaigns/`. Berkas yang sudah
  ada dilewati, `results.jsonl` ditulis terakhir, dan hasil lokal yang tidak ada di paket tidak
  ditimpa tanpa `--force`.
- Kode tetap dipindahkan lewat git; data lewat Google Drive. PC sweep adalah sumber utama.
