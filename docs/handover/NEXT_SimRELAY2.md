# SimRELAY 2: catatan diskusi (BELUM dikerjakan)

Ditulis 28 November 2026. **Status: catatan untuk diskusi. Jangan mulai implementasi sebelum pengguna
memutuskan butir-butir di bagian 7.** Pengguna secara eksplisit meminta "keep it note dulu, jangan dikerjakan".

## 1. Konteks

- **Tahap 1 selesai (SimRELAY 1, fasor):** Proof of Urgency. Relai konvensional dengan setelan beku
  terbukti salah kerja pada 49,6% kasus DER (20,6% tanpa F-6) di IEEE 34-bus. Hasil sudah ditulis
  sebagai paper IEEE (`docs/handover/PAPER_IEEE.md`).
- **Tahap 2 (SimRELAY 2):** test bench SIL untuk **membandingkan algoritma proteksi adaptif** dari DP-2,
  sebagai tahap eliminasi sebelum HIL. Menurut DP-2: delapan alternatif disimulasikan, diseleksi
  berpasangan (P-1 sampai P-4) dengan matriks kriteria, sehingga tersisa empat kandidat untuk HIL
  (FPGA + OPAL-RT melalui IEC 61850, waktu respons proteksi di bawah 4 ms).
- Dokumen sumber DP-2: `C:\Users\Sir Ucup\Downloads\DP2_Kelompok_15_revisi3.docx` (dan versi PDF-nya).
  Hanya konteks, tidak dikutip di paper.

### Delapan alternatif DP-2 (variabel desain: Ip dan TMS relai arus lebih)

| Kode | Inti | Sumber data | Sifat |
|---|---|---|---|
| LUT-1 | Grup setelan diskret hasil k-means skenario, dipilih saat operasi | Status CB/DER via GOOSE, beban dari SV | Lokal + status global |
| LUT-2 | Kisi setelan (beban x DER) dengan interpolasi bilinear | Beban dari SV, keluaran DER via GOOSE | Lokal + status global |
| DS-1 | Unit pusat: Zbus, arus gangguan, optimasi linear TMS, kirim setelan | GOOSE dan MMS dari seluruh jaringan | **Global (terpusat)** |
| DS-2 | Tiap relai estimasi Thevenin lokal (RLS), hitung Ip dan TMS sendiri | SV lokal; waktu target hilir via GOOSE bila ada | **Lokal (tersebar)** |
| AI-1 | EKF/WLS estimasi keadaan, lalu MLP regresi ke Ip dan TMS | Pengukuran terbatas + semu | Global |
| AI-2 | Random forest klasifikasi kondisi, pilih grup terverifikasi | Fasor V, I, P, Q lokal | Lokal |
| AI-3 | Agen deep RL (PPO) mengubah Ip dan TMS daring | Beban, DER, status CB, setelan aktif | Global |
| AI-4 | Agen RL berbasis GNN memilih Ip; TMS dari optimasi linear | Graf jaringan (beban, DER, impedansi, status CB) | Global |

Kriteria seleksi DP-2 yang harus bisa dihitung SimRELAY 2: G-1 (persentase skenario bebas F-1 sampai F-4),
G-2 (waktu deteksi, waktu trip, waktu setelan baru aktif), G-3 (salah trip paling tinggi 1% saat data
terlambat, hilang, berderau), lalu kriteria khusus per pasangan (L-1 sampai L-3, D-1 sampai D-3,
S-1 sampai S-3, R-1 sampai R-3). Bobot G-1 25%, lainnya 15%.

## 2. Butir 1: blok relai yang dapat diprogram, SV masuk, GOOSE keluar

Permintaan pengguna: algoritma setelan tidak lagi terbatas pada OCR, DOCR, DIFF, DIST, melainkan
**blok yang dapat diprogram**. Data masuk lewat **Sampled Values**, perintah trip lewat **GOOSE**.
Lingkungan dan DUT dipisah (persiapan menuju SIL/HIL yang sesungguhnya). **Oracle (Fault Hunter dan
ground truth) dipertahankan.**

Gambaran arsitektur awal (untuk didiskusikan):

```
 BLOK LINGKUNGAN (plant)                     BLOK DUT (relai yang diuji)
 jaringan fasor + DER + CB + CT/VT   SV      merging unit -> blok relai programmable
 publisher SV per titik ukur  ─────────────> (fungsi proteksi + fungsi adaptasi)
 subscriber GOOSE -> perintah CB  <───────── GOOSE trip / status / setelan
            │                                         │
            └──────── ORACLE (ground truth, Fault Hunter, kriteria DP-2) ◄──┘
                      membaca keduanya, tidak ikut mengendalikan
```

Hal teknis yang perlu disepakati:

- **Format SV:** IEC 61850-9-2 (profil LE: 80 sampel per siklus untuk proteksi, artinya 4.000 sampel/s
  pada 50 Hz). Apakah SV dikirim sebagai paket Ethernet sungguhan, atau sebagai struktur data dengan
  isi dan timing setara (lebih cepat dan cukup untuk SIL)?
- **GOOSE:** IEC 61850-8-1 dengan mekanisme retransmisi; waktu transfer pesan trip kelas TT6 (di bawah 3 ms)
  menurut IEC 61850-5.
- **Sinkronisasi waktu:** lingkungan dan DUT berjalan lockstep (langkah per sampel) atau asinkron dengan
  latensi yang dimodelkan.
- **Antarmuka blok programmable:** fungsi standar yang menerima sampel SV dan pesan GOOSE masuk, serta
  mengeluarkan trip, status, dan setelan. OCR, DOCR, DIST, 87L lama menjadi blok bawaan dengan antarmuka
  yang sama, supaya hasil SimRELAY 1 bisa direproduksi sebagai baseline.

## 3. Butir 2: banyak algoritma adaptif, kode bisa dibuka dari UI, routing data terlihat

- UI dan backend harus memuat beberapa algoritma adaptif sekaligus (delapan alternatif DP-2), dipilih
  per IED atau per skema.
- **Kode algoritma bisa diakses dari UI** (minimal dibaca; perlu diputuskan apakah juga bisa diedit
  dan dijalankan ulang).
- **Visualisasi sumber data:** relai mengambil sensor dari titik mana, dan routing kabel data jelas.
  Ini penting karena sebagian skema lokal (DS-2, AI-2, LUT dengan data lokal) dan sebagian global
  (DS-1, AI-1, AI-3, AI-4 dengan unit pusat). Usulan: lapisan SLD baru yang menggambar
  - process bus (CT/VT ke merging unit ke IED, aliran SV),
  - station/wide-area bus (IED ke unit pusat di GI dan sebaliknya, GOOSE dan MMS),
  - arah aliran data dan latensi tiap tautan, serta status tautan saat uji ketahanan (putus, terlambat).
- Arsitektur relai adaptif sebelumnya: lima titik yang sama (A1, A2, A3, L1, B1), IED lokal + koordinator
  di GI, prioritas A3 lalu A2/B1, HIL di A3.

## 4. Butir 3: SimRELAY versi sekarang sebagai legasi

Usulan nama: **SimRELAY 1.0 "Phasor"** (Proof of Urgency, engine fasor Python dan MATLAB).

Usulan cara mengunci (menunggu persetujuan, belum dilakukan):

1. Commit folder `paper/` dan `docs/handover/` ke branch `campaign/pou-full-sweep`, lalu gabung ke `main`.
2. Buat tag git `v1.0-phasor` pada commit itu, dan branch `legacy/v1-phasor` untuk perbaikan kecil.
3. SimRELAY 2 dikembangkan di branch baru (misalnya `v2/phasor-sil`; nama lama `v2/emt-sil` tidak dipakai
   karena EMT dibatalkan, lihat bagian 9).

**Restorasi** versi 1.0: `git checkout v1.0-phasor`, buat `.venv` dari `requirements.txt`,
MATLAB R2024b dengan Simulink, Simscape, Simscape Electrical, Parallel Computing Toolbox dan
`matlabengine==24.2.*`. Data campaign tidak ada di git: ambil dari
`campaigns/PoU-TA-Proteksi-Adaptif` (13 GB) atau paket `sync/SimRELAY_PoU-TA-Proteksi-Adaptif_view_*.zip`
lewat `Impor Hasil.bat`.

## 5. Butir 4: batch sweep tetap (EMT DIBATALKAN, tetap fasor)

> **Revisi 28 November 2026:** EMT dibatalkan untuk SimRELAY 2. SimRELAY 2 tetap fasor dan fokus pada
> pengujian algoritma adaptif. EMT dipindah ke tahap HIL di OPAL-RT. Tabel dan risiko di bawah adalah
> catatan rencana EMT lama; baris yang masih berlaku di mode fasor ditandai di bagian 9.

Konsep sweep faktorial dan oracle tetap. Tuntutan pengguna tetap berlaku: model DER, relai, komunikasi,
resiliensi, standar, dan transparansi harus jelas.

| Aspek | Arah awal yang diusulkan |
|---|---|
| DER | SG: mesin sinkron Simscape dengan eksitasi dan governor. IBR: model rata-rata (average-value) dengan PLL, kontrol arus dq, pembatas arus, dan kontrol urutan negatif sesuai IEEE 2800 / IEEE 1547 (menutup keterbatasan "tanpa injeksi I2" di versi 1) |
| Relai | Filter DFT dari sampel SV, CT dengan opsi saturasi, elemen trip sesuai IEC 60255-151 dan IEEE C37.112 |
| Komunikasi | Latensi, jitter, kehilangan paket SV dan GOOSE sesuai kelas IEC 61850-5; skenario gagal komunikasi |
| Resiliensi | Uji G-3 DP-2: data terlambat, hilang, berderau, di luar data desain; unit pusat mati; grup cadangan |
| Standar | Daftar standar per blok (IEEE 1547, IEEE 2800, IEC 60255, IEC 61850-9-2 / 8-1 / 5, IEC 60909) |
| Transparansi | Tabel "model card" per blok: apa yang dihitung Simulink, apa yang buatan sendiri, parameter, batas valid |

Risiko yang sudah terlihat:

- **Waktu komputasi.** Sweep fasor 5.247 kasus butuh sekitar 5,5 jam (4 worker). EMT dengan langkah
  puluhan mikrodetik untuk 1,6 s per kasus kemungkinan jauh lebih lambat; perlu uji pilot untuk angka
  nyata sebelum menentukan ukuran campaign.
- **Penyimpanan.** Campaign fasor sudah 13 GB; sisa ruang C: sekitar 10 GB. Gelombang EMT jauh lebih besar,
  jadi perlu drive eksternal atau penyimpanan yang dipangkas (misalnya hanya jendela di sekitar gangguan).
- **RAM 7,7 GB** membatasi jumlah worker paralel.

## 6. Perbedaan yang perlu diselaraskan

- DP-2 menyebut IEEE 34-bus **dimodifikasi menjadi 20 kV / 50 Hz**; SimRELAY 1 memakai **24,9 kV / 60 Hz**
  (data asli IEEE).
- DP-2 hanya memakai mode F-1 sampai F-4 dan gangguan LG, LLG, LLLG, LLL. SimRELAY 1 punya F-1 sampai F-6
  dan NT, serta gangguan SLG dan 3PH saja.
- DP-2 memfokuskan variabel desain pada Ip dan TMS relai arus lebih; permintaan butir 1 lebih umum
  (blok programmable).

## 7. Pertanyaan yang menunggu keputusan pengguna

1. ~~Frekuensi dan tegangan~~ **Diputuskan 28 November 2026: ikut DP-2, 20 kV / 50 Hz.**
   Turunan yang masih perlu diputuskan (bagian 8).
2. ~~Lingkup EMT~~ **Diputuskan 28 November 2026: EMT dibatalkan; SimRELAY 2 tetap fasor, EMT di OPAL-RT
   pada tahap HIL** (lihat bagian 9). Keputusan sebelumnya (EMT subset representatif) tidak berlaku lagi.
3. ~~SV dan GOOSE~~ **Diputuskan 28 November 2026: struktur data setara, bukan paket Ethernet sungguhan.**
   Usulan isi (belum disepakati): SV membawa field 9-2LE (svID, smpCnt 0 sampai 3.999, empat arus dan empat
   tegangan, quality, smpSynch); GOOSE membawa field 8-1 (gocbRef, stNum, sqNum, timeAllowedToLive, data
   trip dan status) dengan pola retransmisi. Latensi, jitter, dan kehilangan pesan dimodelkan per tautan.
   Nama field sengaja sama dengan standar supaya pemetaan ke libiec61850 atau OPAL-RT pada tahap HIL langsung.
4. ~~Bahasa blok programmable~~ **Diputuskan 28 November 2026: MATLAB lebih dulu**, karena uji HIL
   nanti di OPAL-RT memakai RT-LAB (model Simulink). Algoritma **harus mungkin dibawa ke FPGA**: tidak
   boleh memakai fungsi library yang tidak bisa dikonstruksi sendiri di FPGA.
   Usulan aturan penulisan blok (belum disepakati), mengikuti subset yang didukung HDL Coder:
   - Blok berupa MATLAB Function di Simulink, dipanggil sekali per sampel SV dengan state persisten.
   - Hanya operasi dasar: tambah, kurang, kali, bandingkan, geser, pencarian tabel ukuran tetap. Bagi dan
     akar dihindari atau diganti tabel atau iterasi berbatas.
   - Larangan: `fft`, `filter`, `interp1`, `inv`, `sqrt` bawaan toolbox, fungsi Statistics, Deep Learning,
     atau Signal Processing Toolbox, ukuran array dinamis, rekursi, string, cell, `try`/`catch`, loop
     tanpa batas tetap.
   - DFT ditulis sendiri sebagai DFT rekursif (sliding) dengan tabel sinus dan kosinus 80 titik; besaran
     dihitung dari kuadrat (tanpa akar) bila memungkinkan, sudut lewat CORDIC tulisan sendiri.
   - Algoritma AI (AI-1 sampai AI-4): **diputuskan 28 November 2026, pelatihan boleh memakai Python**
     (offline, library apa pun, misalnya PyTorch atau scikit-learn). Inferensi di blok MATLAB ditulis
     eksplisit sebagai perkalian matriks bobot tetap dan aktivasi sederhana (ReLU atau tabel), tanpa
     memanggil `predict` atau objek jaringan. Usulan alur (belum disepakati): data latih dari sweep fasor
     SimRELAY 2, model dilatih di Python, bobot diekspor ke berkas `.mat` atau konstanta MATLAB, lalu hasil
     inferensi Python dan blok MATLAB dibandingkan pada data uji yang sama sebelum dipakai. Arsitektur model
     dibatasi pada bentuk yang bisa dibangun di FPGA (MLP kecil, pohon keputusan dengan kedalaman tetap,
     regresi linear); tidak ada lapisan yang butuh fungsi eksponensial bebas kecuali lewat tabel.
   - Hal yang sama berlaku untuk tabel LUT-1 dan LUT-2: tabel boleh dibangun offline di Python, blok MATLAB
     hanya membaca tabel ukuran tetap.
   - Tipe data: mulai dari `double` agar mudah divalidasi, dengan semua operasi sudah mengikuti aturan di
     atas; konversi ke titik tetap dilakukan kemudian.
   **HDL Coder dan Fixed-Point Designer tersedia** (dicek pengguna 28 November 2026). Usulan (belum
   disepakati): setiap blok algoritma wajib lolos `checkhdl` / HDL Workflow Advisor dan konversi titik tetap
   lewat Fixed-Point Designer, ditambah pemeriksa statis buatan sendiri untuk fungsi terlarang. Hasil
   pemeriksaan dicatat di model card tiap algoritma. Sintesis ke FPGA target OPAL-RT dilakukan pada tahap HIL.
   **Engine Python dipensiunkan (diputuskan 28 November 2026).** Semua simulasi SimRELAY 2 memakai MATLAB,
   termasuk oracle dan post-processing. Python hanya hadir sebagai builder di luar SimRELAY (bagian 11).
5. ~~Kode di UI~~ **Diputuskan 28 November 2026: untuk sekarang hanya dibaca, tetapi arsitektur dibuat
   scalable supaya nanti bisa dikembangkan menjadi bisa diedit dan dijalankan.** Usulan agar mudah
   dikembangkan (belum disepakati):
   - Kode algoritma disimpan sebagai berkas `.m` dalam registri algoritma (satu folder per algoritma, dengan
     manifest: nama, versi, hash berkas, port SV/GOOSE yang dipakai, lokal atau global, hasil pemeriksaan HDL).
   - UI membaca kode lewat API backend (misalnya `GET /api/algorithms/<id>/source`), bukan dari berkas statis,
     sehingga nanti cukup menambah `PUT` dan tombol jalankan.
   - Setiap run mencatat id dan hash versi algoritma, supaya hasil tetap bisa dilacak saat kode nanti bisa diubah.
   - Penampil kode memakai komponen editor (misalnya CodeMirror) dalam mode baca saja; mode edit tinggal diaktifkan.
6. Urutan pengerjaan algoritma: delapan sekaligus, atau mulai dari satu per pasangan (misalnya LUT-1, DS-2)?
7. ~~Legasi~~ **Disetujui 28 November 2026: nama SimRELAY 1.0 "Phasor", tag `v1.0-phasor`, branch
   `legacy/v1-phasor`, paper dan handover di-commit.**

## 8. Konversi IEEE 34-bus ke 20 kV / 50 Hz (keputusan turunan, belum diputuskan)

Keputusan pengguna 28 November 2026: jaringan SimRELAY 2 memakai 20 kV / 50 Hz sesuai DP-2. Konsekuensinya,
hasil SimRELAY 1 (24,9 kV / 60 Hz) tidak bisa dibandingkan angka demi angka; baseline relai konvensional
harus dihitung ulang pada jaringan baru (setelan beku dihitung ulang dengan aturan yang sama).

Pilihan konversi yang perlu disepakati:

| Butir | Opsi A (usulan awal) | Opsi B |
|---|---|---|
| Impedansi saluran | Resistansi tetap, reaktansi induktif dikali 50/60 (dari geometri konduktor yang sama) | Ganti konduktor dengan tipe standar PLN (misalnya AAAC 150 mm2 dan 70 mm2) |
| Beban | Daya kW dan kvar tetap (1.769 kW puncak), arus naik sekitar 1,25 kali karena tegangan turun | Beban diskalakan supaya arus sama |
| Gardu induk | 150/20 kV (pola GI PLN), rating dan impedansi trafo disesuaikan | Tetap 69 kV di sisi primer |
| Pentanahan netral | Mengikuti pola PLN 20 kV (pentanahan lewat tahanan, misalnya 40 ohm untuk saluran udara) | Tetap empat kawat multi-grounded seperti IEEE 34 |
| Regulator dan trafo 832 ke 888 | Tetap ada, rasio disesuaikan ke 20 kV | Dihapus |
| Kapasitor 844 dan 848 | kvar pada tegangan nominal tetap | Diskalakan |

Catatan penting soal pentanahan: mekanisme dominan di paper (F-1, F-2, F-3) berjalan lewat jalur urutan nol
trafo interkoneksi YgD. Pentanahan netral GI lewat tahanan, seperti pola PLN 20 kV, menurunkan arus gangguan
tanah dari sisi GI secara drastis, sehingga porsi kontribusi DER dan pola kegagalan bisa berubah besar.
Pilihan ini harus diputuskan dengan sadar, bukan ikut default.

### 8.1 Keputusan pentanahan (28 November 2026)

**Diputuskan: netral 20 kV di GI mengikuti pola PLN, yaitu pentanahan lewat tahanan, bukan empat kawat
multi-grounded IEEE 34.**

Konsekuensi yang harus ditangani saat konversi (belum dikerjakan):

- Arus gangguan tanah dari sisi GI dibatasi tahanan netral. Dengan 40 ohm nilainya sekitar
  20 kV / akar 3 / 40 ohm, yaitu sekitar 290 A, jauh di bawah arus gangguan tiga fasa. Dengan 12 ohm
  sekitar 960 A. Nilai tahanan harus diambil dari SPLN yang berlaku untuk wilayahnya dan dicek ulang.
- Jaringan menjadi tiga kawat tanpa netral bersama. Beban fasa-netral dan lateral satu fasa IEEE 34
  (misalnya 816 ke 822, 808 ke 810) harus diubah menjadi beban fasa-fasa atau lewat trafo distribusi,
  mengikuti praktik PLN.
- Relai gangguan tanah (51N/50N, GFR) disetel dengan pickup yang jauh lebih kecil, sesuai arus
  gangguan tanah yang terbatas.
- Trafo interkoneksi DER YgD tetap menjadi sumber urutan nol, dan relatif terhadap GI kontribusinya
  justru lebih dominan. Mekanisme F-1, F-2, F-3 di paper kemungkinan tetap ada, tetapi besarannya akan berbeda.
  Apakah trafo interkoneksi DER juga ikut pola tertentu (YgD, Dyn, atau tanpa pentanahan sisi jaringan)
  perlu diputuskan terpisah, karena pilihan itu langsung menentukan ada tidaknya mekanisme tersebut.

Pertanyaan turunan:

1. ~~Nilai tahanan netral~~ **Diputuskan 28 November 2026: 40 ohm (saluran udara)**, arus gangguan tanah maksimum dari GI sekitar 290 A. Angka ini tetap perlu dicek ke SPLN yang berlaku.
2. ~~Hubungan trafo interkoneksi DER~~ **Diputuskan 28 November 2026: tetap YgD** (sisi jaringan wye ditanahkan, sisi DER delta), sama dengan SimRELAY 1. Jalur urutan nol DER tetap ada dan relatif lebih dominan karena kontribusi GI dibatasi 40 ohm.

## 9. Fidelitas SimRELAY 2: tetap fasor, EMT di OPAL-RT (diputuskan 28 November 2026)

**Keputusan:** EMT dibatalkan untuk SimRELAY 2. SimRELAY 2 tetap memakai mode fasor (50 Hz, 20 kV) dan
tujuannya menguji algoritma proteksi adaptif DP-2 (SIL). Simulasi EMT dilakukan pada tahap berikutnya di
OPAL-RT (HIL), sejalan dengan rencana DP-2 (SIL lalu HIL dengan FPGA dan OPAL-RT, IEC 61850).
Usulan subset EMT sebelumnya tidak berlaku lagi.

Pembagian peran yang diusulkan:

| Tahap | Platform | Fidelitas | Tujuan |
|---|---|---|---|
| SimRELAY 1.0 "Phasor" | Python dan Simscape fasor, 24,9 kV / 60 Hz | Fasor | Proof of Urgency (selesai) |
| SimRELAY 2 | Simscape fasor (dan engine Python), 20 kV / 50 Hz | Fasor | Uji dan seleksi algoritma adaptif DP-2 dengan sweep penuh |
| HIL | OPAL-RT, FPGA, IEC 61850 | EMT waktu nyata | Validasi algoritma terpilih, waktu di bawah 4 ms |

Konsekuensi yang perlu dicatat dengan jujur (belum dikerjakan):

- **SV dari fasor.** Mode fasor tidak menghasilkan bentuk gelombang sesaat. Agar antarmuka SV tetap ada,
  sampel 80 per siklus harus disintesis dari fasor (rekonstruksi sinusoida per langkah). Isinya setara
  secara fundamental, tetapi tanpa transien DC offset, harmonik, dan saturasi CT. Ini harus tertulis di
  model card. **Diputuskan 28 November 2026: SV sintesis dari fasor** (bukan fasor langsung). Blok relai
  menerima sampel 80 per siklus (4.000 sampel/s pada 50 Hz) dan menjalankan filter DFT sendiri, sehingga
  kode relai yang sama bisa dipakai di OPAL-RT. Usulan teknis (belum disepakati): sampel dibangkitkan per
  langkah dari besar dan sudut fasor tiap fasa, dengan opsi derau pengukuran dan kuantisasi format 9-2LE
  (arus 1 mA, tegangan 10 mV per bit); perubahan fasor saat gangguan menjadi lompatan bentuk gelombang
  tanpa DC offset.
- **Yang tetap berlaku dari tabel bagian 5:** komunikasi (latensi, jitter, paket hilang), resiliensi G-3,
  daftar standar, dan model card transparansi. Model IBR dengan pembatas arus dan kontrol urutan negatif
  masih bisa dibuat dalam domain urutan (fasor).
- **Yang pindah ke HIL:** filter DFT dari sampel nyata, saturasi CT, dinamika PLL dan kontrol cepat IBR,
  dan transien elektromagnetik.
- **Keuntungan:** sweep penuh tetap murah (sekitar 5,5 jam untuk 5.247 kasus di SimRELAY 1), tidak ada
  masalah penyimpanan gelombang EMT, dan RAM 7,7 GB cukup untuk 4 worker.
- **Jembatan ke HIL:** antarmuka blok DUT (SV masuk, GOOSE keluar) dirancang sama dengan yang akan dipakai
  di OPAL-RT, supaya algoritma yang lolos di SimRELAY 2 bisa dibawa tanpa ditulis ulang.

## 10. Milestone, estimasi ruang, dan format output permanen (28 November 2026)

### 10.1 Dua milestone (diputuskan pengguna)

| Milestone | Isi | Sweep |
|---|---|---|
| M1: pengembangan model dan algoritma | Konversi jaringan 20 kV / 50 Hz, lingkungan SV/GOOSE, registri algoritma, delapan algoritma DP-2 dan baseline konvensional. Urutan bebas, mengikuti pengguna. Diuji pada kasus tertentu yang dipilih (bukan sweep) | Tidak ada |
| M2: final sweep | Setelah semua model dan algoritma final (dan kemungkinan SSD baru): 5.247 kasus, **semua algoritma dijalankan bersamaan** | 5.247 kasus |

### 10.2 Arti "semua algoritma bersamaan" (diputuskan 28 November 2026: sembilan varian loop tertutup)

**Keputusan pengguna: sembilan varian loop tertutup per kasus**, bukan mode bayangan. Rincian di bawah
menjadi dasar rancangan.

Relai adaptif mengirim GOOSE trip yang membuka CB, sehingga jalannya jaringan setelah trip berbeda untuk
tiap algoritma. Satu simulasi jaringan tidak bisa dipakai bersama oleh delapan algoritma secara loop tertutup.
Usulan: per kasus, satu tugas worker menjalankan **sembilan varian** (baseline konvensional dan delapan
algoritma DP-2) dengan skenario, seed, dan data prafault yang identik, lalu oracle menilai kesembilannya
sekaligus. Bagi pengguna tampil sebagai satu sweep dengan semua algoritma; secara komputasi ada
5.247 x 9 = 47.223 simulasi loop tertutup.

Alternatif lebih murah: mode bayangan (shadow), yaitu satu simulasi jaringan dengan relai konvensional,
lalu delapan algoritma hanya membaca SV yang sama dan keputusan tripnya dinilai tanpa membuka CB. Ini
cukup untuk kriteria kecepatan dan selektivitas keputusan pertama, tetapi tidak bisa menilai kejadian
setelah trip (F-2 simpatetik lanjutan, F-6 backfeed, koordinasi cadangan).

### 10.3 Estimasi ruang disk

Dasar ukur SimRELAY 1 (diukur 28 November 2026): folder `runs/` 13 GB untuk 5.247 kasus, rata-rata
2,5 MB per kasus. Isinya `sim.mat` (log mentah Simulink, 0,05 sampai 2,8 MB, porsi terbesar), `wave.npz`
(0,02 sampai 0,9 MB), `result.json.gz` sekitar 20 KB, dan `cfg.json.gz` sekitar 12 KB yang isinya hampir
sama di semua kasus. Model `.slx` 174 MB.

| Skenario penyimpanan SimRELAY 2 (9 varian per kasus) | Per kasus | Total 5.247 kasus |
|---|---|---|
| Pola SimRELAY 1 diulang apa adanya (sim.mat dan wave per varian) | sekitar 22 MB | **sekitar 115 GB** |
| Ditambah menyimpan SV 4.000 sampel/s mentah | tambah sekitar 9 MB | sekitar 160 GB |
| **Usulan efisien (bagian 10.4)** | 0,3 sampai 0,6 MB | **sekitar 2 sampai 4 GB** |

Ruang kerja sementara selama sweep: sekitar 1 GB per worker (berkas sementara Simulink dihapus setelah
tiap kasus selesai diringkas). Untuk usulan efisien, SSD 256 GB pun sudah lebih dari cukup; SSD 500 GB
memberi ruang untuk beberapa campaign dan cadangan.

Estimasi waktu (kasar, perlu pilot di M1): sweep SimRELAY 1 sekitar 5,5 jam dengan 4 worker. Sembilan varian
memberi sekitar 50 jam, ditambah perlambatan blok MATLAB Function yang dipanggil 4.000 kali per detik
simulasi. Angka nyata baru bisa ditetapkan setelah pilot.

### 10.4 Usulan format output permanen

Prinsip: **simpan yang tidak bisa dibuat ulang dengan murah, dan simpan semua sidik (hash) yang
dibutuhkan untuk membuat ulang sisanya.** SV, log mentah Simulink, dan konfigurasi lengkap per kasus bisa
dibangkitkan ulang secara deterministik dari manifest, jadi tidak disimpan.

```
campaigns/<nama>/
  manifest.json        sidik lengkap campaign (dibuat sebelum sweep, dikunci)
  cases.parquet        satu baris per kasus: parameter skenario dan seed
  results.parquet      satu baris per (kasus, varian): kode F-1..F-6, NT, waktu trip, metrik G/L/D/S/R DP-2
  events.parquet       satu baris per kejadian: GOOSE, trip, CB buka/tutup, perubahan setelan, pesan hilang
  traces/<kasus>.h5    fasor ringkas semua varian kasus itu (float32, satu nilai per setengah siklus)
  models/              model .slx per topologi (atau hanya hash bila dibangun ulang dari kode)
  logs/                log worker
  CHECKSUMS.sha256     hash semua berkas di atas
```

Isi `manifest.json`:

- commit dan tag git SimRELAY, versi MATLAB dan semua toolbox (termasuk HDL Coder dan Fixed-Point Designer),
  versi Python dan library;
- hash model jaringan, setelan solver fasor, langkah waktu, frekuensi sampel SV, aturan sintesis SV
  (derau dan kuantisasi), parameter kanal komunikasi;
- registri algoritma: id, versi, hash berkas `.m`, hash berkas bobot atau tabel (hasil pelatihan Python),
  hasil pemeriksaan HDL, tautan model card;
- definisi sweep dan seed utama, setelan baseline konvensional;
- versi oracle dan definisi kode kegagalan.

Alasan format:

- **Parquet** untuk tabel: kolumnar dan terkompresi, puluhan kali lebih kecil dari JSONL 29 MB SimRELAY 1,
  dapat dibaca Python (pandas, pyarrow) dan MATLAB (`parquetread`).
- **HDF5** untuk jejak fasor: dibaca langsung oleh MATLAB (`h5read`) dan Python (`h5py`), satu berkas per
  kasus berisi sembilan varian, sehingga jumlah berkas tetap 5.247 dan tidak menjadi puluhan ribu.
  Ukuran per varian: 5 titik ukur x 3 fasa x arus dan tegangan kompleks x float32, 160 titik waktu
  (1,6 s dengan satu nilai per setengah siklus), sekitar 40 KB mentah, sekitar 20 sampai 30 KB terkompresi.
  Titik ukur tambahan (misalnya semua bus untuk oracle) menaikkan ukuran secara sebanding.
- Tidak menyimpan `sim.mat`, SV mentah, dan `cfg` per kasus: semuanya dapat dibangkitkan ulang.

Reproduksibilitas:

- Perintah ulang satu kasus, misalnya `rerun --campaign <nama> --case PoU-0123 --variant DS-2`, membangun
  ulang semuanya dari manifest, termasuk SV dan log Simulink lengkap bila diperlukan untuk analisis mendalam.
- Uji determinisme: hasil ulang dibandingkan dengan baris di `results.parquet` dan hash jejak fasor; selisih
  dilaporkan. Uji ini dijalankan pada sampel acak setelah sweep sebagai bukti reproduksibilitas.
- Bila commit, toolbox, atau hash algoritma berbeda dengan manifest, perintah ulang menolak berjalan
  kecuali diminta secara sadar, dan perbedaannya dicatat.

Fidelitas:

- Setiap blok (jaringan, DER, sintesis SV, kanal komunikasi, algoritma, oracle) punya model card yang
  dirujuk dengan hash di manifest: apa yang dihitung Simscape, apa yang buatan sendiri, parameter, dan batas
  valid (misalnya tanpa DC offset dan saturasi CT karena mode fasor).

## 11. Peran Python: builder terpisah (diputuskan 28 November 2026)

Keputusan pengguna:

- Engine Python SimRELAY 1 dipensiunkan. SimRELAY 2 seluruhnya MATLAB: lingkungan, DUT, oracle,
  post-processing.
- Python hadir sebagai **builder**, di folder kerja terpisah di luar SimRELAY. Tugasnya membangun dari data
  latih. **Keluarannya adalah bank (model terlatih atau tabel), bukan algoritma.** Kode algoritma (`.m`) tetap
  milik SimRELAY dan hanya membaca isi bank.

Usulan antarmuka (belum disepakati):

```
SimRELAY-Builder/           (folder terpisah, repo git sendiri)
  datasets/                 data latih yang diekspor SimRELAY 2 (Parquet atau HDF5) beserta hashnya
  recipes/                  resep training per bank (misalnya ai1_mlp.py, lut1_table.py)
  banks/<bank_id>/<versi>/
    bank.mat                bobot, bias, normalisasi, atau tabel; ukuran tetap, tipe numerik saja
    bank.json               manifest: id, versi, jenis (model atau tabel), bentuk array, hash dataset,
                            commit builder, versi library, seed, metrik validasi, batas valid input
SimRELAY 2
  algorithms/<algo_id>/     kode .m algoritma, manifest menyebut bank_id dan versi yang dipakai
  banks/                    salinan bank yang diimpor, diverifikasi hash dengan bank.json
```

Alur: SimRELAY 2 mengekspor kasus latih, builder melatih dan menulis bank, SimRELAY 2 mengimpor bank
dan memverifikasi hash, lalu uji kesetaraan (inferensi MATLAB dibandingkan dengan Python pada data uji
yang sama, selisih maksimum dicatat di model card). Hash bank masuk ke manifest campaign, sehingga run
tetap reproduksibel tanpa menjalankan ulang builder.
