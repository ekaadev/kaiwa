# Akses data bukti pengujian

Dokumen ini menetapkan siapa yang boleh mengambil rekaman dan catatan panggilan pengujian, serta
cara akses yang dipakai. Ini bukan kebijakan privasi; retensi dan persetujuan peserta tetap
memerlukan pengesahan terpisah.

## Petugas berwenang

Hanya **peneliti utama** (pemilik repository dan kredensial deployment) yang berwenang mengakses
bukti panggilan pengujian. Tidak ada akun petugas lain, dan tidak ada API HTTP untuk akses petugas.
Menambah petugas mengubah dokumen ini lebih dulu, sebelum kredensial dibagikan.

## Yang dapat diakses dan tujuannya

| Data | Lokasi | Tujuan |
|---|---|---|
| `user.wav`, `assistant.wav`, `events.jsonl`, `manifest.json` per percobaan | Bucket privat Neon (`study/<attempt_id>/`) | Anotasi false cut-off, analisis latensi, pemeriksaan kualitas rekaman |
| Metadata peserta, sesi, percobaan, checksum manifest | Database Neon | Menghubungkan bukti dengan metode dan sesi |

## Cara akses

1. Kredensial bucket dan database hanya berada di `runtime.env` pada server (mode 600) dan di
   `.env` lokal peneliti yang tidak dikomit.
2. Pengambilan data dilakukan dengan `backend/scripts/export_study_evidence.py` di server, atau
   dengan `analyze_study_calls.py` untuk hasil olahan. Keduanya memeriksa checksum manifest.
3. Setiap ekspor dicatat di `access.log` pada direktori keluaran (pengguna sistem operasi, waktu,
   percobaan yang berhasil dan gagal). Tidak ada token peserta yang diekspor.

## Batasan

- Rekaman tidak diunduh lewat HTTP dan tidak disalin ke layanan pihak ketiga.
- Ekspor tidak dienkripsi oleh skrip; salinan disimpan hanya di penyimpanan terenkripsi milik
  peneliti dan dihapus setelah analisis.
- `/monitor` hanya menampilkan metadata waktu tanpa teks atau audio; tokennya (`MONITOR_TOKEN`)
  tidak memberi akses ke bukti.

## Belum disahkan

- Masa simpan salinan ekspor dan bukti di bucket (nilai `STUDY_RETENTION_DAYS` saat ini belum
  disetujui).
- Teks persetujuan yang menyebut siapa yang dapat mengakses rekaman.
- Penghapusan metadata peserta di database setelah masa retensi.
