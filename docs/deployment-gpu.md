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
| Network volume (`/workspace/ai-conversation`) | Kode, `models/`, `.venv-gpu`, `llm-venv`, `logs/` | Ya |
| Disk container (`/root/.config/ai-conversation`) | `runtime.env` (mode 600), staging evidence (mode 700), PID | Tidak |
| Neon | Database dan rekaman/transkrip evidence | Ya |

Lokasi default dapat diganti lewat `KAIWA_ROOT` dan `KAIWA_CONFIG_DIR`.
Network volume bisa tidak menerapkan `chmod`/`chown`; jangan menyimpan kredensial atau
data privat di sana. Simpan salinan `runtime.env` di tempat aman di luar server.

## 3. Penyiapan pertama

Pod baru dengan network volume yang sudah berisi kode dan model hanya perlu paket sistem dan
virtualenv; `deploy/bootstrap.sh` mengerjakan keduanya (apt, `.venv`, `llm-venv`, unduh Qwen
dengan revisi tercatat). Setelah itu jalankan instalasi GPU di bawah.

**Model** (di `models/`, revisi dicatat/di-pin):

- `faster-whisper-small/` berisi `model.bin` (Systran/faster-whisper-small; bukan `small.en`).
- `kokoro-v1.0.onnx` dan `voices-v1.0.bin`.
- `qwen3-1.7b/` (Qwen/Qwen3-1.7B) beserta catatan revisi.

**Environment GPU backend** dari `backend/`:

```sh
export UV_CACHE_DIR=/workspace/ai-conversation/cache/uv
CONVERSATION_GPU_PYTHON=/usr/bin/python3 bash scripts/install_gpu_trial.sh
```

Skrip membuat `.venv-gpu` dari `uv.lock` dengan `onnxruntime-gpu==1.23.2` menggantikan
`onnxruntime`. Jangan menjalankan `uv sync` biasa pada `.venv-gpu` atau memasang kedua
distribusi ONNX sekaligus.

**Environment vLLM** dipisahkan (`llm-venv`, vLLM 0.10.2 dan transformers 4.55.2) agar versi transformers tidak bertabrakan
dengan backend.

**Konfigurasi runtime**: salin `deploy/runtime.env.example` ke
`/root/.config/ai-conversation/runtime.env`, isi nilainya, lalu `chmod 600`. Buat staging evidence:

```sh
install -d -m 700 /root/.config/ai-conversation/study-evidence
```

Library CUDA/cuDNN dari paket pip (`nvidia/*/lib`) dimasukkan ke `LD_LIBRARY_PATH` oleh
`launch_api.py` dan `launch_gpu_task.py` sebelum interpreter GPU dijalankan.

## 4. Migrasi database

Dari `backend/`, memakai koneksi langsung Neon:

```sh
uv run --no-sync --env-file /root/.config/ai-conversation/runtime.env alembic upgrade head
```

API tidak membuat tabel saat startup; revisi yang diharapkan adalah `0003_study_evidence`.

## 5. Jalankan Qwen dan FastAPI

**Di pod**, dari folder `deploy/` (checkout repo atau salinannya, mis.
`$KAIWA_ROOT/scripts/`):

```sh
bash start-services.sh
```

Skrip memulai Qwen (`launch_llm.py`, vLLM di `127.0.0.1:18001`) dan API
(`launch_api.py`, uvicorn **satu worker** di `127.0.0.1:8002`, interpreter dari
`CONVERSATION_API_PYTHON`, default `.venv-gpu`), menyimpan PID, lalu mengatur proxy
(`configure_proxy.py`). Proses berjalan di background; skrip selesai **bukan** berarti model
sudah dimuat. Layanan yang sudah sehat atau PID-nya masih hidup dilewati.

Tunggu health (Qwen beberapa menit):

```sh
curl -fsS http://127.0.0.1:18001/health   # Qwen
curl -fsS http://127.0.0.1:8002/health    # {"status":"ok"}
```

Log: `logs/llm.log` dan `logs/api.log`. Nama model yang disajikan harus tepat
`Qwen/Qwen3-1.7B`. Muat `runtime.env` hanya lewat peluncur; uvicorn tidak membaca `.env`.
Port dan utilisasi GPU vLLM dapat diubah lewat `KAIWA_LLM_PORT`, `KAIWA_API_PORT`, dan
`KAIWA_VLLM_GPU_UTILIZATION`.

## 6. Proxy HTTPS

`configure_proxy.py` membuat konfigurasi nginx (port 8000) yang hanya meneruskan jalur
`/pilot/<kode-acak>/` ke API; root mengembalikan 404. Kode jalur dibuat sekali dan disimpan di
`access.json` (disk container); base URL publik dihitung ulang dari `RUNPOD_POD_ID` setiap
dijalankan, sehingga pod baru hanya perlu menjalankan ulang skrip ini. Baca base URL:

```sh
python3 -c 'import json; print(json.load(open("/root/.config/ai-conversation/access.json"))["base_url"])'
```

Port proxy (default 8000) harus diekspos pada pod (`8000/http`); jika tidak, URL publik
mengembalikan 404 meski nginx lokal sehat. Mengubah port yang diekspos me-restart pod dan
menghapus disk container (runtime.env, paket sistem). Alternatifnya memakai port yang sudah
diekspos, mis. 8888 dengan Jupyter dipindah ke port lain.

Karena `access.json` ada di disk container, pod baru mendapat kode jalur dan base URL baru:
build ulang mobile dengan alamat itu. Jangan commit base URL ke Git.

## 7. Readiness dan HTTPS

```sh
curl -fsS --max-time 15 http://127.0.0.1:8002/v1/practice/readiness   # {"ready":true}
```

Readiness memeriksa LiveKit, file model, model Qwen, dan kapasitas; ini belum bukti audio
berfungsi. Dari komputer lokal, uji base URL HTTPS publik (`/health` dan
`/v1/practice/readiness` harus 200). Jangan menonaktifkan verifikasi TLS.

## 8. Uji

**Di pod**, dari folder `deploy/` (lewat `.venv-gpu` dengan library CUDA, sesuai konfigurasi runtime):

```sh
python3 launch_gpu_task.py smoke_models.py    # Qwen, Kokoro Jepang, Whisper (sintetis)
python3 launch_gpu_task.py livekit_smoke.py   # satu panggilan Practice sintetis
```

- `smoke_models.py` menulis `logs/model-smoke.json`; tidak membuka panggilan LiveKit.
- `livekit_smoke.py` menulis `logs/livekit-smoke.json`: start 201, audio tutor diterima, end
  204, transkrip final. Tidak membuktikan playback di ponsel.
- Benchmark CPU vs GPU, memakai CUDA libraries dan runtime.env:
  `python launch_gpu_task.py scripts/benchmark_speech.py --output /path/privat/benchmark.json`

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
| HTTPS 404 padahal nginx lokal 200 | Port proxy belum diekspos pada pod (lihat langkah 6) |
| HTTPS 404/502/403 | Base URL/jalur proxy, API lokal belum siap |
| TTS Jepang gagal | Paket Misaki/Open JTalk, model Kokoro dan voicepack yang cocok |
| CUDA tidak terpakai | `LD_LIBRARY_PATH`, `onnxruntime-gpu` tunggal, variabel `TUTOR_*` |

## 11. Menghentikan dan memulihkan

- Hentikan proses API/Qwen (`api.pid`, `llm.pid`) dengan memverifikasi PID sebelum `kill`; jangan ada panggilan
  aktif. Menghentikan proses tidak menghentikan biaya pod.
- Jika disk container hilang: database dan evidence tetap aman di Neon. Pulihkan
  `runtime.env` dari salinan aman, buat ulang staging evidence, lalu jalankan `start-services.sh` dan ulangi langkah 7. Alamat proxy berubah (lihat langkah 6).
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
