# Campaign "Proof of Urgencies TA Proteksi Adaptif" (PoU): rencana kerja

Ditulis 21 November 2026. Status: **rencana disusun, belum dikerjakan, menunggu persetujuan
pengguna atas empat pertanyaan di bagian 8.** Belum ada kode yang diubah untuk campaign ini.

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

## 8. Pertanyaan yang menunggu jawaban pengguna (default usulan dalam kurung)

1. Fidelitas model dikunci di versi sekarang, opsi (a) HANDOVER bagian 6, dengan tabel
   penyederhanaan sebagai metodologi? (Ya. Bila nanti pindah ke opsi b atau c, campaign diulang.)
2. Run ID campaign memakai format terpisah `PoU-0001` sampai `PoU-5247`? (Ya.)
3. File `.mat` mentah dari Simulink ikut disimpan? (Ya, bila ukurannya wajar setelah pilot.)
4. Jumlah worker: mulai 2 (RAM 11,9 GB, 4 thread), dinilai ulang dari pemakaian RAM saat pilot? (Ya.)

## 9. Lingkungan PC ini

Windows 10, RAM 11,9 GB, 4 thread, MATLAB R2024b Update 10. Python proyek: `.venv` (Python 3.11,
`matlabengine` 24.2); Python bawaan 3.14 tidak bisa memakai MATLAB. Jalankan sweep dengan
`.venv\Scripts\python batch.py ...`. Server: `Jalankan SimRELAY.bat` atau `.claude/launch.json`.
