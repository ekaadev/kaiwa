# Konfigurasi Neon

Folder ini berisi konfigurasi infrastruktur Neon untuk Kaiwa: database PostgreSQL dan
bucket object storage privat `kaiwa` (rekaman dan transkrip evidence studi).

| Berkas | Fungsi | Di Git? |
|---|---|---|
| `neon.ts` | Deklarasi bucket `kaiwa` (akses privat) | Ya |
| `package.json`, `package-lock.json` | Versi Neon config SDK | Ya |
| `.neon` | Tautan lokal ke proyek/branch Neon | Tidak |
| `.env.local` | Kredensial yang dihasilkan Neon CLI (DB dan S3) | Tidak |

## Pemakaian

Jalankan perintah Neon CLI dari folder ini supaya `.neon` dan `neon.ts` terbaca:

```sh
cd infra/neon
npm ci            # pasang dependensi konfigurasi
neon status       # proyek, branch, dan versi Postgres
neon buckets list # bucket pada branch aktif
```

## Menghubungkan backend

Backend Python tidak membaca `.env.local` secara otomatis. Salin nilai yang diperlukan ke
runtime privat server (`deploy/runtime.env.example` sebagai template) atau ke
`backend/.env` untuk pengembangan lokal:

- `DATABASE_URL` (pooled) untuk API dan `DATABASE_URL_UNPOOLED` (langsung) untuk Alembic
  serta `pg_dump`/`pg_restore`.
- `AWS_ENDPOINT_URL_S3`, `AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, dan
  `STUDY_EVIDENCE_BUCKET=kaiwa`.

Jangan menaruh kredensial di dokumentasi atau source. Backup database privat disimpan di
`.neon-backups/` pada root repository (diabaikan Git, mode 700).
