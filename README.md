# Kaiwa

Implementasi riset *adaptive end-of-turn detection* pada percakapan AI untuk belajar bahasa
Jepang. Penelitian membandingkan dua aturan: **adaptive** dan **fixed** (baseline), agar
tutor tidak menjawab terlalu cepat dan tidak menunggu terlalu lama.

Terdiri dari aplikasi mobile (Compose Multiplatform) dan backend (FastAPI + Pipecat +
LiveKit) yang dijalankan di server GPU, dengan database dan rekaman di Neon.

## Peta repository

| Folder | Isi | Dokumen |
|---|---|---|
| [`backend/`](backend) | Control API, tutor pipeline, migrasi, tes, utilitas | [backend/README.md](backend/README.md) |
| [`mobile/`](mobile) | Aplikasi Android/iOS (Compose Multiplatform) | [mobile/README.md](mobile/README.md) |
| [`deploy/`](deploy) | Template runtime dan artefak deployment server GPU | [deploy/README.md](deploy/README.md) |
| [`infra/neon/`](infra/neon) | Konfigurasi proyek dan bucket Neon | [infra/neon/README.md](infra/neon/README.md) |
| [`docs/`](docs) | Arsitektur, panduan deployment, rencana fitur | lihat di bawah |

## Dokumentasi

- [Arsitektur](docs/arsitektur.md): alur komponen, pipeline tutor, batas data studi/practice
- [Deployment GPU](docs/deployment-gpu.md): menjalankan backend di server GPU
- [Rencana pengembangan](docs/PLAN.md): daftar fitur dan progres
- [AGENTS.md](AGENTS.md): panduan untuk AI agent (bahasa Inggris)

## Mulai cepat

```sh
# Backend (lokal)
cd backend && uv sync --group dev && uv run pytest -q

# Mobile (host tests dan APK debug)
cd mobile && ./gradlew :shared:testAndroidHostTest :androidApp:assembleDebug
```

## Status

Alur Practice Android dengan inferensi nyata sudah berjalan di deployment GPU. Belum
tervalidasi: playback ponsel, kedua metode EOT pada inferensi nyata, dua panggilan
bersamaan, dan latensi respons. Consent/privasi/retensi harus disahkan sebelum peserta
nyata; export riset belum diimplementasikan. Detail di [docs/PLAN.md](docs/PLAN.md).
