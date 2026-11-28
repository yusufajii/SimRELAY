# Folder handover: posisi terakhir proyek (28 November 2026)

Baca berurutan:

1. `docs/HANDOVER.md` untuk arsitektur SimRELAY 1, cara menjalankan, validasi, dan jebakan teknis.
2. `docs/CAMPAIGN_PoU.md` untuk desain dan pelaksanaan campaign 5.247 kasus.
3. `docs/handover/PAPER_IEEE.md` untuk paper, cara membuatnya ulang, dan design rule.
4. `docs/handover/NEXT_SimRELAY2.md` untuk rencana tahap berikutnya (**masih diskusi, belum dikerjakan**).

## Progres terakhir

| Tanggal | Yang selesai |
|---|---|
| 22 Nov 2026 | Sweep MATLAB penuh 5.247 kasus selesai (bagian 1 tiga worker, bagian 2 sampai 5 empat worker), tanpa error |
| 22 Nov 2026 | Sinkronisasi antar komputer (`sync.py`, `Ekspor Hasil.bat`, `Impor Hasil.bat`); paket view 3,72 GB di `sync/` |
| 22 sampai 26 Nov 2026 | Paper IEEE 10 halaman selesai dan direvisi tiga kali sesuai arahan pengguna |
| 28 Nov 2026 | Hasil, cara membuat, dan design rule paper disimpan; catatan SimRELAY 2 ditulis |

## Lokasi data penting (tidak ada di git)

| Lokasi | Ukuran | Catatan |
|---|---|---|
| `campaigns/PoU-TA-Proteksi-Adaptif/` | 13 GB | Hasil campaign; `results.jsonl` adalah sumber semua angka paper |
| `campaigns/PoU-pilot/` | 0,4 GB | Pilot 121 kasus (dasar validasi silang) |
| `sync/SimRELAY_PoU-TA-Proteksi-Adaptif_view_20261122-1711.zip` | 3,7 GB | Paket untuk Google Drive |

Total proyek sekitar 18 GB; ruang kosong C: sekitar 10 GB (26 November 2026).

## Status git

Legasi disetujui 28 November 2026: folder `paper/` dan `docs/handover/` di-commit di branch
`campaign/pou-full-sweep`, diberi tag `v1.0-phasor` (SimRELAY 1.0 "Phasor"), dan branch `legacy/v1-phasor`
dibuat dari commit itu. Cara restorasi ada di `NEXT_SimRELAY2.md` bagian 4.
