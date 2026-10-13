# Deployment GPU

Artefak untuk menjalankan backend di server GPU (saat ini pod RunPod). Langkah lengkap:
[docs/deployment-gpu.md](../docs/deployment-gpu.md).

| Berkas | Fungsi |
|---|---|
| `runtime.env.example` | Template konfigurasi runtime (Neon, LiveKit, model, GPU). Salin ke berkas privat mode 600 di luar repository. |
| `bootstrap.sh` | Setup pod baru pada network volume yang ada: paket sistem, `.venv`, `llm-venv`, unduh Qwen. |
| `start-services.sh` | Memulai Qwen dan API di background lalu mengatur proxy. |
| `launch_llm.py`, `launch_api.py` | Peluncur vLLM dan uvicorn (satu worker) yang memuat `runtime.env`. |
| `configure_proxy.py` | Proxy nginx port 8000 dengan jalur privat acak; base URL dari `RUNPOD_POD_ID`. |
| `move_jupyter.py` | Memindahkan JupyterLab template ke port loopback lain agar port publiknya bisa dipakai proxy. |
| `launch_gpu_task.py` | Menjalankan skrip backend (mis. benchmark) di `.venv-gpu` dengan library CUDA. |
| `smoke_models.py`, `livekit_smoke.py` | Uji asap model dan panggilan Practice sintetis. |
| `download_qwen.py`, `_paths.py` | Unduh Qwen pada revisi tercatat; path dan loader env bersama. |

Lokasi default dapat diganti: `KAIWA_ROOT` (`/workspace/ai-conversation`) dan
`KAIWA_CONFIG_DIR` (`/root/.config/ai-conversation`, disk container). Port lewat
`KAIWA_API_PORT` (8002), `KAIWA_LLM_PORT` (18001), dan `KAIWA_PROXY_PORT` (8000; pod yang hanya
mengekspos 8888 memakai 8888 setelah `move_jupyter.py`).

Skrip tidak berisi secret; kredensial hanya dibaca dari `runtime.env`. Skrip ini disalin dari
pod yang berjalan dan hanya diparameterkan; uji ulang di pod setelah perubahan.
