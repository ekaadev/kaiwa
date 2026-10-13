# Deployment backend di server GPU

Panduan ini menjalankan backend Kaiwa di server GPU NVIDIA (contoh: pod RunPod). Tidak
terikat model GPU tertentu; yang penting VRAM cukup untuk Qwen (vLLM), Whisper CUDA, dan
Kokoro CUDA. Database dan rekaman evidence berada di **Neon**, bukan di disk server.

Urutan: **siapkan penyimpanan dan konfigurasi → migrasi → Qwen → API → HTTPS →
readiness → uji → mobile**.

## 1. Prasyarat

| Kebutuhan | Catatan |
|---|---|
| GPU NVIDIA, CUDA 12 + cuDNN 9 | Ukur VRAM dengan `nvidia-smi` setelah semua model dimuat; atur `--gpu-memory-utilization` vLLM agar muat bersama Whisper dan Kokoro. |
| Python 3.11–3.13, `uv`, g++, espeak-ng, ffmpeg, libsndfile | g++ diperlukan jika paket Jepang (Misaki/Open JTalk) harus dibangun. |
| Network volume | Kode, model, virtualenv, cache, log. Tidak menyimpan kredensial. |
| Neon | Database PostgreSQL dan bucket privat `kaiwa` (lihat [infra/neon](../infra/neon/README.md)). |
| LiveKit | URL, API key, dan API secret yang valid. |
| Akses HTTPS | Proxy platform (mis. HTTP proxy RunPod) ke API pada `127.0.0.1:8002`. |

Layanan di server:

| Layanan | Alamat | Fungsi |
|---|---|---|
| Qwen (vLLM) | `127.0.0.1:18001` (`/v1`) | LLM tutor |
| FastAPI | `127.0.0.1:8002`, satu worker | Control API, panggilan, transkrip |

PostgreSQL dan Qwen tidak perlu diekspos ke internet. Audio tidak lewat API: mobile dan
tutor sama-sama bergabung ke ruang LiveKit.

## 2. Tata letak penyimpanan

| Lokasi | Isi | Bertahan jika disk container hilang? |
|---|---|---|
| Network volume (`/workspace/kaiwa`) | Kode, `models/`, `.venv-gpu`, `llm-venv`, `logs/` | Ya |
| Disk container (`/root/.config/kaiwa`) | `runtime.env` (mode 600), staging evidence (mode 700), PID | Tidak |
| Neon | Database dan rekaman/transkrip evidence | Ya |

Path `/workspace/kaiwa` adalah contoh (pod saat ini masih memakai `/workspace/ai-conversation`).
Network volume bisa tidak menerapkan `chmod`/`chown`; jangan menyimpan kredensial atau
data privat di sana. Simpan salinan `runtime.env` di tempat aman di luar server.

## 3. Penyiapan pertama

**Model** (di `models/`, revisi dicatat/di-pin):

- `faster-whisper-small/` berisi `model.bin` (Systran/faster-whisper-small; bukan `small.en`).
- `kokoro-v1.0.onnx` dan `voices-v1.0.bin`.
- `qwen3-1.7b/` (Qwen/Qwen3-1.7B) beserta catatan revisi.

**Environment GPU backend** dari `backend/`:

```sh
export UV_CACHE_DIR=/workspace/kaiwa/cache/uv
CONVERSATION_GPU_PYTHON=/usr/bin/python3 bash scripts/install_gpu_trial.sh
```

Skrip membuat `.venv-gpu` dari `uv.lock` dengan `onnxruntime-gpu==1.23.2` menggantikan
`onnxruntime`. Jangan menjalankan `uv sync` biasa pada `.venv-gpu` atau memasang kedua
distribusi ONNX sekaligus.

**Environment vLLM** dipisahkan (`llm-venv`) agar versi transformers tidak bertabrakan
dengan backend.

**Konfigurasi runtime**: salin `deploy/runtime.env.example` ke
`/root/.config/kaiwa/runtime.env`, isi nilainya, lalu `chmod 600`. Buat staging evidence:

```sh
install -d -m 700 /root/.config/kaiwa/study-evidence
```

Library CUDA/cuDNN harus ada di `LD_LIBRARY_PATH` **sebelum** interpreter GPU dijalankan
(pada image PyTorch RunPod: `/usr/local/lib/python3.12/dist-packages/nvidia/*/lib`).

## 4. Migrasi database

Dari `backend/`, memakai koneksi langsung Neon:

```sh
uv run --no-sync --env-file /root/.config/kaiwa/runtime.env alembic upgrade head
```

API tidak membuat tabel saat startup; revisi yang diharapkan adalah `0003_study_evidence`.

## 5. Jalankan Qwen

```sh
export HF_HOME=/workspace/kaiwa/cache/huggingface HF_HUB_DISABLE_TELEMETRY=1 VLLM_NO_USAGE_STATS=1
set -a; . /root/.config/kaiwa/runtime.env; set +a
setsid /workspace/kaiwa/llm-venv/bin/vllm serve /workspace/kaiwa/models/qwen3-1.7b \
  --served-model-name Qwen/Qwen3-1.7B --host 127.0.0.1 --port 18001 \
  --dtype bfloat16 --max-model-len 32768 --max-num-seqs 2 \
  --gpu-memory-utilization 0.75 --enforce-eager --api-key "$TUTOR_LLM_API_KEY" \
  >> /workspace/kaiwa/logs/llm.log 2>&1 < /dev/null &
```

Nama model harus tepat `Qwen/Qwen3-1.7B`. Tunggu sampai
`curl -fsS http://127.0.0.1:18001/health` mengembalikan 200 (beberapa menit).

## 6. Jalankan FastAPI

```sh
cd /workspace/kaiwa/backend
umask 077
setsid .venv-gpu/bin/python -m uvicorn app.main:app \
  --host 127.0.0.1 --port 8002 --workers 1 \
  >> /workspace/kaiwa/logs/api.log 2>&1 < /dev/null &
```

Muat `runtime.env` lebih dulu seperti langkah 5 dan pastikan `LD_LIBRARY_PATH` sudah diatur (langkah 3); uvicorn tidak membaca `.env`. Gunakan
**satu worker** dan tanpa autoreload. Periksa `curl -fsS http://127.0.0.1:8002/health`
(`{"status":"ok"}`).

## 7. Readiness dan HTTPS

```sh
curl -fsS --max-time 15 http://127.0.0.1:8002/v1/practice/readiness   # {"ready":true}
```

Readiness memeriksa LiveKit, file model, model Qwen, dan kapasitas; ini belum bukti audio
berfungsi. Dari komputer lokal, uji base URL HTTPS publik (`/health` dan
`/v1/practice/readiness` harus 200). Jangan menonaktifkan verifikasi TLS.

## 8. Uji

- `smoke_models.py` menguji Qwen, Kokoro Jepang, dan Whisper dengan input sintetis.
- `livekit_smoke.py` membuat satu panggilan Practice sintetis: start 201, audio tutor
  diterima, end 204, transkrip final. Ini tidak membuktikan playback di ponsel.
- Uji komponen CPU vs GPU: `PYTHONPATH=. .venv-gpu/bin/python scripts/benchmark_speech.py --output /path/privat/benchmark.json` dari `backend/`.

## 9. Hubungkan mobile

Dari `mobile/`, build dengan base URL lengkap (tanpa `/v1`):

```sh
./gradlew :androidApp:assembleDebug -PconversationServerUrl='https://…'
```

Alamat tertanam saat build; jika berubah, build ulang. Jangan memasukkan LiveKit API secret
ke mobile.

## 10. Log dan masalah umum

| Gejala | Periksa |
|---|---|
| Qwen health gagal | `logs/llm.log`, `nvidia-smi`, model, environment vLLM |
| `Address already in use` | `ss -ltnp`; jangan jalankan proses kedua di port yang sama |
| API gagal startup | `logs/api.log`, `DATABASE_URL`, revisi Alembic |
| `/health` 200, readiness 503 | LiveKit, file model, API key Qwen, nama model, slot panggilan |
| `capacity_full` | Dua slot sedang dipakai; akhiri panggilan atau tunggu cleanup |
| HTTPS 404/502/403 | Base URL/jalur proxy, API lokal belum siap |
| TTS Jepang gagal | Paket Misaki/Open JTalk, model Kokoro dan voicepack yang cocok |
| CUDA tidak terpakai | `LD_LIBRARY_PATH`, `onnxruntime-gpu` tunggal, variabel `TUTOR_*` |

## 11. Menghentikan dan memulihkan

- Hentikan proses API/Qwen dengan memverifikasi PID sebelum `kill`; jangan ada panggilan
  aktif. Menghentikan proses tidak menghentikan biaya pod.
- Jika disk container hilang: database dan evidence tetap aman di Neon. Pulihkan
  `runtime.env` dari salinan aman, buat ulang staging evidence, lalu ulangi langkah 5–7.
  Panggilan yang terputus sebelum evidence final diunggah tidak dijamin pulih.
- Untuk kembali ke inferensi CPU, ganti hanya variabel `TUTOR_*`/`ONNX_PROVIDER`; pertahankan
  `DATABASE_URL*`.

## 12. Backup dan restore Neon

- Backup: `pg_dump` melalui `DATABASE_URL_UNPOOLED`; simpan terenkripsi di luar repository
  (`.neon-backups/` diabaikan Git, mode 700).
- Restore hanya ke database tujuan kosong (koneksi langsung):
  `pg_restore --exit-on-error --single-transaction --no-owner --no-privileges`, lalu
  `alembic upgrade head` dan periksa health/readiness. Uji dulu pada branch Neon sementara.
- Transkrip Practice hanya di memori proses; tidak ikut backup.

## 13. Batas setup ini

Satu proses API, maksimal dua panggilan total (Practice + studi). Playback ponsel, kedua
metode EOT dengan inferensi nyata, dan dua panggilan bersamaan belum divalidasi; latensi
respons masih perlu diukur dan diperbaiki. Penggunaan peserta nyata memerlukan consent dan
kebijakan retensi yang disahkan, serta evidence privat yang benar-benar mode 700. Retensi
pengujian pribadi (30 hari) bukan standar penelitian.
