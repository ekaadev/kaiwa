# Kaiwa backend

Control API (FastAPI) untuk penelitian *adaptive vs fixed end-of-turn detection* pada
percakapan AI bahasa Jepang. Backend mengelola pendaftaran peserta, alokasi metode
fixed/adaptive, siklus panggilan, transkrip, dan evidence studi, serta menjalankan tutor
(Pipecat) yang bergabung ke ruang LiveKit.

Pipeline tutor: Whisper small multilingual (STT) → Smart Turn v3.2 atau jeda tetap (EOT) →
Qwen3-1.7B lewat endpoint OpenAI-compatible self-hosted → Kokoro-82M Jepang (TTS).
Arsitektur lengkap: [docs/arsitektur.md](../docs/arsitektur.md). Deployment GPU:
[docs/deployment-gpu.md](../docs/deployment-gpu.md).

> Belum siap untuk peserta nyata: consent/privasi/retensi belum disahkan dan export riset
> belum diimplementasikan.

## Setup lokal

Memerlukan Python 3.11–3.13, `uv`, dan Docker (PostgreSQL lokal) atau database Neon.

```sh
cd backend
uv sync --group dev
docker compose up -d postgres       # hanya development lokal
cp .env.example .env                # lalu isi nilainya; .env diabaikan Git
uv run --env-file .env alembic upgrade head
uv run --env-file .env uvicorn app.main:app --reload
```

uvicorn tidak membaca `.env` sendiri; muat dengan `--env-file`. Startup API **tidak** membuat
tabel; skema dikelola Alembic (revisi saat ini `0003_study_evidence`). Database lama yang
dibuat sebelum migrasi harus dibackup dan diverifikasi sesuai `0001_study_foundation`
sebelum `alembic stamp`; jangan men-stamp database yang belum diverifikasi.

Panggilan nyata memerlukan extras dan model lokal:

```sh
uv sync --group dev --extra calls --extra tutor
uv run --extra calls --extra tutor --env-file .env uvicorn app.main:app --reload
```

Jika instalasi paket Jepang gagal dengan `'c++' not found`, pasang `g++`
(`sudo apt-get install -y g++`) lalu ulangi `uv sync --frozen ...`.

## Konfigurasi

Template: [`.env.example`](.env.example) (lokal) dan
[`../deploy/runtime.env.example`](../deploy/runtime.env.example) (server GPU).

| Kelompok | Variabel | Catatan |
|---|---|---|
| Database | `DATABASE_URL`, `DATABASE_URL_UNPOOLED` | Neon: pooled untuk API, langsung untuk Alembic dan `pg_dump`. Gunakan `postgresql+psycopg://` dengan SSL. |
| LiveKit | `LIVEKIT_URL` (`wss://`), `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` | Hanya di server; klien menerima token room terbatas. |
| Model | `TUTOR_WHISPER_PATH`, `TUTOR_KOKORO_MODEL_PATH`, `TUTOR_KOKORO_VOICES_PATH` | Path absolut di luar repository. Whisper harus `small` multilingual, bukan `small.en`. |
| LLM | `TUTOR_LLM_BASE_URL` (akhiran `/v1`), `TUTOR_LLM_API_KEY` | Harus mengiklankan `Qwen/Qwen3-1.7B`. Jangan pakai layanan eksternal tak disetujui untuk ucapan peserta. |
| GPU | `TUTOR_WHISPER_DEVICE`, `TUTOR_WHISPER_COMPUTE_TYPE`, `TUTOR_KOKORO_EXECUTION_PROVIDER`, `ONNX_PROVIDER` | Default CPU (`cpu`/`int8`/`CPUExecutionProvider`). GPU: `cuda`/`float16`/`CUDAExecutionProvider`, dengan `ONNX_PROVIDER=CPUExecutionProvider` untuk muat awal. |
| Studi | `STUDY_CONSENT_VERSION`, `STUDY_EVIDENCE_DIR`, `STUDY_RETENTION_DAYS` | Direktori absolut privat mode 700. Retensi 1–3650 hari, **tanpa default**; jangan menetapkan sendiri tanpa persetujuan. |
| Evidence S3 | `STUDY_EVIDENCE_BUCKET`, `AWS_ENDPOINT_URL_S3`, `AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | Bila bucket diisi, `STUDY_EVIDENCE_DIR` hanya staging sementara dan hasil final disimpan di bucket privat `study/<call-id>/`. |

Smart Turn dan Silero VAD selalu di CPU. Untuk GPU, buat `.venv-gpu` dengan
`bash scripts/install_gpu_trial.sh` (lihat panduan deployment); jangan memasang dua
distribusi ONNX ke environment yang sama. Jangan mengaktifkan logging audio Smart Turn atau
log DEBUG transkripsi/TTS untuk peserta nyata.

## API ringkas

| Endpoint | Fungsi |
|---|---|
| `GET /health` | Cek database |
| `GET /v1/practice/readiness` | Preflight: LiveKit, model, Qwen, kapasitas (200 atau 503) |
| `POST /v1/practice/calls` | Panggilan latihan anonim; metode selalu adaptive; tanpa record studi |
| `GET /v1/practice/calls/{id}/transcript`, `POST .../end` | Transkrip dan pengakhiran dengan `transcript_token` |
| `POST /v1/study/participants` | Daftar (`{"accepted":true}`); mengembalikan ID dan resume token **sekali** |
| `GET /v1/study/me` | Progres peserta (Bearer resume token) |
| `POST /v1/study/sessions/{ordinal}/calls` | Mulai/retry panggilan studi; wajib `Idempotency-Key`; metode ditetapkan server |
| `POST /v1/study/calls/{id}/end` | Akhiri panggilan |
| `GET /v1/study/calls/{id}/transcript` | Transkrip (kepemilikan diperiksa) |
| `POST /v1/study/calls/{id}/events` | Telemetri subscription audio klien (metadata, bukan bukti playback) |

Panggilan dibuat setelah pipeline tutor dibangun dan bot bergabung ke room; baru kemudian
kredensial dikembalikan. Tanpa konfigurasi lengkap, endpoint gagal tertutup (503 dengan
kode `capacity_full` atau `service_unavailable`). Jangan mencatat resume token dan jangan
menjadikan ID peserta sebagai kredensial; assignment fixed/adaptive tidak dikirim ke peserta.

## Aturan penyelesaian sesi

- Sesi 2 baru terbuka setelah Sesi 1 valid.
- Selesai hanya jika: akhir normal, ≥ 120 detik audio mikrofon yang **diterima server**, dan
  evidence final tersimpan (dua track audio, event, dan manifest ber-checksum).
- Disconnect, kegagalan setup, tidak ada yang join, dan timeout bukan akhir normal.
- Panggilan menunggu evidence terkunci hingga 21 menit; panggilan terputus dapat diulang.
- Fixed: jeda 700 ms. Adaptive: Smart Turn v3.2 dengan batas diam 3 detik.
- Maksimal **dua panggilan total** per proses; jalankan **satu proses API** sampai
  kepemilikan panggilan lintas proses didukung.

Audio terima server dan keluaran TTS server bukan bukti apa yang terdengar di ponsel.
Evidence tidak punya endpoint unduh publik; cleanup retensi menghapus objek evidence tetapi
tidak metadata database.

## Monitoring pengujian

Hanya jalur study (latihan tidak mencatat data penelitian). Panggilan study menambahkan event ke `events.jsonl`: `call_clock`, `vad`, `eot` (metode, sumber `silence`/`smart_turn`/`timeout`, probabilitas), `stt_final` (panjang teks), `ttfb` (STT/LLM/TTS), dan `bot_speaking`. Sumber `timeout` pada adaptive disimpulkan dari prediksi Smart Turn "belum selesai". Aplikasi Android melaporkan `remote_audio_playback_started/stopped` (audio terdekode di ponsel; bukan bukti terdengar di speaker).

- **Dashboard operator:** set `MONITOR_TOKEN` (kosong = dinonaktifkan), buka `/monitor` lewat HTTPS atau tunnel SSH. JSON di `GET /v1/monitor/calls` (bearer). Tidak memuat teks transkrip atau audio.
- **Analisis:** `uv run --env-file .env python scripts/analyze_study_calls.py [OUT_DIR]` menulis `turns.csv`, `summary.csv`, dan `annotation_sample.csv` ke direktori privat (`.study-analysis/`). Satu EOT dicatat per VAD berhenti; `overlaps_tutor_audio` bernilai kosong bila bukti tidak memuat `bot_speaking`. Angka false cut-off otomatis hanya **batas bawah** (pengguna melanjutkan bicara dalam T = 1/2/3 s setelah EOT); tingkat sebenarnya memerlukan anotasi manual sampel.

## Skrip

| Skrip | Fungsi |
|---|---|
| `scripts/try_whisper_microphone.py` | Transkripsi mikrofon lokal (`arecord`), tanpa menyimpan audio |
| `scripts/benchmark_speech.py` | Benchmark sintetis CPU vs GPU untuk Whisper/Kokoro; tidak membuka panggilan |
| `scripts/install_gpu_trial.sh` | Membuat `.venv-gpu` dengan `onnxruntime-gpu` |

## Tes

```sh
uv run pytest -q
uv run ruff check .
```

Mayoritas tes memakai SQLite in-memory. Tes alokasi PostgreSQL konkuren memerlukan
`TEST_DATABASE_URL` ke database **sekali pakai** karena ia menghapus tabelnya:

```sh
docker compose exec -T postgres psql -U conversation -d postgres -c 'CREATE DATABASE conversation_test;'
export TEST_DATABASE_URL='postgresql+psycopg://conversation:local-dev-only@localhost:55432/conversation_test'
uv run pytest -q
```

Jangan arahkan ke database produksi atau development biasa. Tes dengan layanan tiruan tidak
membuktikan inferensi nyata atau playback ponsel.
