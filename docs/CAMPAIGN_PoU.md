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
