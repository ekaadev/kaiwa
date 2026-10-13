# Deployment GPU

Folder ini menampung artefak untuk menjalankan backend di server GPU (saat ini pod RunPod).
Langkah lengkapnya ada di [docs/deployment-gpu.md](../docs/deployment-gpu.md).

| Berkas | Fungsi |
|---|---|
| `runtime.env.example` | Template konfigurasi runtime (database Neon, LiveKit, model, GPU). Salin ke berkas privat di luar repository. |

## Skrip peluncur pod belum ada di repo

Skrip berikut masih berada di `/workspace/ai-conversation/scripts` pada pod dan perlu
disalin ke folder ini setelah diperiksa agar bebas secret dan URL privat:

- `start-services.sh`, `launch_llm.py`, `launch_api.py`, `configure_proxy.py`
- `smoke_models.py`, `livekit_smoke.py`

Sebelum itu, `docs/deployment-gpu.md` menjelaskan perintah manual yang setara.
`init_database.py` hanya untuk PostgreSQL lokal lama dan tidak perlu disalin.
