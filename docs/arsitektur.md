# Arsitektur

## Tujuan riset

Membandingkan dua aturan akhir giliran (*end of turn*, EOT) pada tutor percakapan bahasa
Jepang: **fixed** (baseline, jeda 700 ms) dan **adaptive** (Smart Turn v3.2, batas diam
3 detik). Sasarannya tutor tidak menjawab terlalu cepat dan tidak menunggu terlalu lama.
Pipeline kedua kondisi sama persis kecuali aturan EOT.

## Komponen dan alur

```
 Ponsel (KMP)                    Server GPU (satu proses API)              Layanan luar
┌──────────────┐  HTTPS   ┌──────────────────────────────────┐
│ Compose UI   │─────────▶│ FastAPI control API              │──▶ Neon: Postgres + bucket privat
│ Room, Keystore│         │  enrollment, call lifecycle,     │
└──────┬───────┘          │  transkrip, evidence             │
       │ WebRTC           │ Pipecat tutor (bot di room)      │──▶ Qwen3-1.7B (vLLM, lokal)
       ▼                  └───────────────┬──────────────────┘
   LiveKit Cloud ◀── WebRTC audio ────────┘
```

- Mobile memanggil FastAPI lewat HTTPS untuk pendaftaran, progres, kredensial panggilan,
  pengakhiran, dan transkrip. Alamat server ditanam saat build.
- Backend menyiapkan tutor dan bergabung ke room LiveKit **sebelum** mengembalikan token
  room terbatas ke mobile. Audio mengalir lewat LiveKit; tidak ada transport UDP langsung
  mobile-ke-server.
- Qwen berjalan di server yang sama lewat API OpenAI-compatible; Whisper dan Kokoro
  berjalan di proses API (CUDA bila dikonfigurasi).

## Pipeline tutor (`backend/app/tutor.py`)

1. **VAD** Silero (CPU) mendeteksi ucapan.
2. **EOT**: fixed menunggu 700 ms diam; adaptive memakai Smart Turn v3.2 (CPU) dan memaksa
   giliran selesai setelah 3 detik diam.
3. **STT** faster-whisper small multilingual (`whisper_stt.py`), deteksi bahasa
   Inggris/Jepang otomatis.
4. **LLM** Qwen3-1.7B non-thinking; jawaban Jepang, 1–3 kalimat, maksimal satu pertanyaan.
5. **TTS** Kokoro-82M ONNX dengan fonem Misaki/Open JTalk (`japanese_tts.py`).

Sumber daya model per panggilan dilepas eksplisit saat cleanup agar VRAM tidak tertahan.

## Modul backend

| Modul | Peran |
|---|---|
| `main.py` | App FastAPI dan rute |
| `models.py`, `study.py` | Skema SQLAlchemy; pendaftaran, alokasi seimbang, token pemulihan |
| `study_calls.py` | Reservasi/retry panggilan studi, idempotensi, aturan selesai |
| `livekit_study.py`, `livekit_practice.py` | Room, bot, penghitung audio, transkrip untuk studi dan latihan |
| `call_capacity.py` | Batas dua panggilan per proses |
| `evidence.py`, `s3_evidence.py` | Penulis evidence privat (filesystem/S3 Neon), manifest, retensi |
| `transcripts.py`, `practice.py` | Transkrip dan helper latihan |
| `migrations/` | Alembic (`0001`–`0003`) |

## Batas data

- **Practice** selalu adaptive, tanpa peserta, tanpa evidence, dan tidak masuk ekspor
  penelitian; transkrip hanya di memori proses (30 menit).
- **Studi** memerlukan consent; metode ditetapkan server; audio pengguna dan tutor disimpan
  terpisah dari satu sama lain dan dari metadata database; manifest ber-checksum
  didaftarkan di Postgres.
- Penyelesaian sesi dibuktikan server (akhir normal, ≥ 120 s audio diterima, evidence final),
  bukan timer atau permintaan klien.
- Audio yang diterima server dan telemetri subscription klien bukan bukti suara terdengar
  di ponsel.
