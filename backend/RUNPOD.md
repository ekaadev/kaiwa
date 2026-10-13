# Panduan menjalankan backend di Runpod: dari layanan mati sampai siap dipakai

Panduan ini untuk setup uji coba pribadi yang sudah dipasang di pod. Semua
perintah bertanda **di pod** dijalankan melalui Terminal JupyterLab atau SSH.
Perintah bertanda **di komputer lokal** dijalankan di komputer Anda.

Bagian 2–12 mendokumentasikan baseline awal RTX 3090 dengan PostgreSQL lokal.
Deployment demo sekarang memakai RTX 4090 (bagian 14) dan database Neon
(bagian 15). Untuk deployment Neon, jangan membuat atau memulihkan database lokal
melalui bagian 5 atau 12.4; jalankan Alembic dengan koneksi langsung Neon.

Urutan operasional: **periksa pod dan konfigurasi → PostgreSQL → migrasi →
Qwen → FastAPI → proxy HTTPS → readiness → uji percakapan → mobile**.

## 1. Tentukan kondisi awal

| Kondisi | Langkah yang digunakan |
|---|---|
| Pod hidup, tetapi proses backend/Qwen mati; berkas dan database masih ada | Ikuti bagian 2–9. |
| Semua layanan sudah hidup | Cukup lakukan pemeriksaan bagian 7–9; jangan jalankan proses kedua pada port yang sama. |
| Pod di-Stop/Restart/Reset/Edit atau dibuat ulang dan disk container hilang | Pulihkan sesuai bagian 12, lalu lakukan bagian 4–9. |
| Network volume salah/tidak terpasang atau model belum tersedia | Lengkapi bagian 2–3 sebelum memulai layanan. |

**Mematikan proses FastAPI atau Qwen berbeda dengan mematikan Pod Runpod.**
Proses yang mati tidak menghapus file; Pod yang masih dialokasikan tetap memakai
resource dan biaya GPU. Operasi Pod melalui Runpod dapat menghapus disk container.
Lihat [pengelolaan Pod](https://docs.runpod.io/pods/manage-pods) dan
[jenis penyimpanan Runpod](https://docs.runpod.io/pods/storage/types).

Setup ini belum memasang autostart aplikasi pada boot container. Status Pod
`Running` tidak berarti PostgreSQL, Qwen, dan API kita sudah siap.

## 2. Apa yang diperlukan

### Resource dan software yang dipakai

| Komponen | Setup saat ini |
|---|---|
| GPU | RTX 3090, 24 GB VRAM |
| CPU / RAM | 6 vCPU / 100 GB RAM; mulai pengujian dengan satu panggilan |
| Disk container | 30 GB; PostgreSQL dan konfigurasi privat berada di sini |
| Network volume | 50 GB, EUR-IS-2, terpasang pada `/workspace` |
| Image | `runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404` |
| Python / PyTorch | Python 3.12, PyTorch 2.8.0 dengan CUDA 12.8 |
| Backend | FastAPI, satu proses; dependensi dari `backend/uv.lock` dengan extras `calls` dan `tutor` |
| Server Qwen | vLLM 0.10.2, transformers 4.55.2, environment terpisah |
| Database | PostgreSQL 16, database dan role bernama `conversation` |
| Sistem | `uv`, nginx bawaan template, espeak-ng, ffmpeg, libsndfile; compiler C++ untuk paket Jepang yang perlu dibangun |
| LiveKit | URL proyek, API key, dan API secret yang valid |
| Jaringan | Akses keluar menuju LiveKit; internet untuk instalasi/unduhan pada penyiapan awal |

Qwen memakai GPU. Whisper small multilingual int8, Smart Turn, dan Kokoro ONNX
memakai CPU. Enam vCPU adalah konfigurasi pod yang sudah diuji untuk satu panggilan,
bukan hasil validasi kapasitas dua panggilan. Pemakaian network volume saat
pemasangan sekitar 27 GB, termasuk environment dan cache.

### Layanan dan port

| Layanan | Alamat di pod | Fungsi |
|---|---|---|
| PostgreSQL | `127.0.0.1:5432` | Database backend |
| Qwen/vLLM | `127.0.0.1:18001`, API dengan akhiran `/v1` | Inferensi model bahasa |
| FastAPI | `127.0.0.1:8002` | Enrollment, readiness, kredensial panggilan, transkrip, dan pengakhiran panggilan |
| nginx aplikasi | `0.0.0.0:8000` | Meneruskan jalur akses privat ke FastAPI |
| JupyterLab | Port 8888 | File browser dan terminal |
| SSH | Port internal 22, dipetakan ke port eksternal Runpod | Akses terminal jarak jauh |

Port yang sudah diekspos pada pod: `8000/http`, `8888/http`, dan `22/tcp`.
PostgreSQL dan Qwen tidak perlu diekspos ke internet. Port 8001 dan 8081 dipakai
nginx bawaan template; jangan gunakan keduanya untuk Qwen pada image ini.

Mobile menggunakan HTTPS pada port proxy 8000. Mobile dan tutor bergabung ke
ruangan LiveKit yang sama untuk audio. Audio tidak dikirim langsung melalui
port HTTP backend atau koneksi UDP mobile-ke-pod.

### Lokasi file

| Lokasi | Isi | Bertahan jika disk container hilang? |
|---|---|---|
| `/workspace/ai-conversation/backend` | Snapshot kode backend, migrasi, dan tes | Ya, selama network volume dipertahankan |
| `/workspace/ai-conversation/backend/.venv` | Environment backend | Berkasnya bertahan; perlu dicek kecocokannya dengan image/Python baru |
| `/workspace/ai-conversation/llm-venv` | Environment vLLM; mengakses PyTorch dari image | Berkasnya bertahan; membutuhkan image yang cocok |
| `/workspace/ai-conversation/models` | Whisper, Kokoro, Qwen | Ya |
| `/workspace/ai-conversation/scripts` | Skrip deployment dan pengujian | Ya |
| `/workspace/ai-conversation/logs` | Log layanan | Ya |
| `/root/.config/ai-conversation/runtime.env` | Kredensial dan konfigurasi runtime | Tidak |
| `/root/.config/ai-conversation/access.json` | Base URL HTTPS dan kode jalur akses privat | Tidak |
| `/root/.config/ai-conversation/api.pid` dan `llm.pid` | PID proses yang diluncurkan skrip | Tidak |
| `/var/lib/postgresql/16/main` | Data PostgreSQL | Tidak |

Pada network volume **yang kita uji ini**, kepemilikan/izin POSIX tidak mengikuti
`chown`/`chmod` yang dibutuhkan PostgreSQL. Karena itu, sesuai pilihan uji coba,
database dan kredensial disimpan di disk container. Jangan memindahkan file
kredensial ke `/workspace` dengan asumsi `chmod 600` akan melindunginya di sana.
Network volume juga bukan pengganti backup.

## 3. Masuk ke pod dan periksa prasyarat

Buka **Runpod Console → Pods → Connect → JupyterLab, port 8888 → Terminal**.
Untuk SSH, ambil informasi terbaru **di komputer lokal**:

```sh
runpodctl pod list
runpodctl ssh info ghqlz7e0dtgjfv
```

Jalankan perintah SSH yang ditampilkan CLI. Jika pod dibuat ulang, gunakan ID
pod yang baru. Port eksternal SSH dapat berubah setelah reset; lihat
[pemetaan port Runpod](https://docs.runpod.io/pods/configuration/expose-ports).

**Di pod**, periksa GPU, mount, kode, environment, dan model:

```sh
nvidia-smi
findmnt -T /workspace
ls /workspace/ai-conversation/backend
ls /workspace/ai-conversation/scripts
ls /workspace/ai-conversation/models
```

Isi model yang diperlukan:

- `models/faster-whisper-small/model.bin`, bersama config/tokenizer/vocabulary.
- `models/kokoro-v1.0.onnx` dan `models/voices-v1.0.bin`.
- `models/qwen3-1.7b/`, berisi config, tokenizer, dan bobot safetensors.
- `models/qwen-revision.json`, catatan revision Qwen yang diunduh.

Jangan gunakan Whisper `small.en`; aplikasi perlu mengenali Jepang dan Inggris.
Kode sekarang dikirim sebagai snapshot; clone repository tidak diperlukan untuk
menjalankannya. Perubahan kode lokal tetap harus dikirim ke pod.

Periksa keberadaan konfigurasi tanpa mencetak kredensial:

```sh
test -f /root/.config/ai-conversation/runtime.env && echo 'runtime.env tersedia'
test -f /root/.config/ai-conversation/access.json && echo 'access.json tersedia'
stat -c '%a %n' /root/.config/ai-conversation/runtime.env
```

Izin `runtime.env` pada disk container harus `600`. Jika konfigurasi hilang,
jangan langsung menjalankan layanan: ikuti pemulihan di bagian 12.

### Konfigurasi runtime yang diperlukan

Ini contoh **struktur**, bukan kredensial yang bisa langsung dipakai:

```dotenv
DATABASE_URL=postgresql+psycopg://conversation:ISI_PASSWORD_DATABASE@127.0.0.1:5432/conversation
LIVEKIT_URL=wss://PROYEK_LIVEKIT_ANDA
LIVEKIT_API_KEY=ISI_KEY_ANDA
LIVEKIT_API_SECRET=ISI_SECRET_ANDA
TUTOR_WHISPER_PATH=/workspace/ai-conversation/models/faster-whisper-small
TUTOR_KOKORO_MODEL_PATH=/workspace/ai-conversation/models/kokoro-v1.0.onnx
TUTOR_KOKORO_VOICES_PATH=/workspace/ai-conversation/models/voices-v1.0.bin
TUTOR_LLM_BASE_URL=http://127.0.0.1:18001/v1
TUTOR_LLM_API_KEY=ISI_KUNCI_QWEN_ANDA
LOGURU_LEVEL=INFO
OMP_NUM_THREADS=2
OPENBLAS_NUM_THREADS=2
STUDY_CONSENT_VERSION=draft-v1
STUDY_EVIDENCE_DIR=
STUDY_RETENTION_DAYS=
```

Format `DATABASE_URL` yang benar untuk setup ini adalah:

```text
postgresql+psycopg://conversation:PASSWORD_DATABASE@127.0.0.1:5432/conversation
```

Password harus cocok dengan role PostgreSQL. Gunakan password yang aman untuk URL,
atau lakukan URL-encoding pada karakter khusus. `TUTOR_LLM_API_KEY` dipakai
peluncur Qwen dan backend dari file yang sama. Peluncur yang terpasang membaca
baris `NAMA=nilai`; tulis nilai tanpa tanda kutip dan jangan menambahkan `export`.

LiveKit API key/secret hanya berada di server. Mobile menerima token room
terbatas dari backend. Study evidence dan retention dibiarkan kosong untuk
pengujian Practice; jangan mengisi masa retensi tanpa kebijakan yang disetujui.

## 4. Pilih cara menjalankan: otomatis atau manual

Untuk penggunaan rutin **di pod**, jalankan:

```sh
bash /workspace/ai-conversation/scripts/start-services.sh
```

Skrip memulai PostgreSQL, meluncurkan Qwen dan API jika belum aktif, menyimpan PID,
lalu mengatur/reload nginx. Proses berjalan di background sehingga tidak bergantung
pada tab terminal. **Skrip selesai bukan berarti Qwen sudah siap**; lanjutkan
pemeriksaan bagian 5–8.

Jalur otomatis mengasumsikan nginx bawaan template masih berjalan. Jika nginx
juga mati, hidupkan seperti bagian 7 sebelum menggunakan skrip ini.

Skrip ini tidak memasang dependensi, membuat database baru, memulihkan kredensial,
atau menunggu seluruh model selesai dimuat. Jika masih gagal, baca log sebelum
menjalankannya ulang. PID yang masih hidup juga membuat skrip melewati peluncuran
proses itu, meskipun health-nya gagal; lihat bagian 10.

Jika ingin memahami urutannya atau menjalankan satu per satu, gunakan bagian 5–7
sebagai jalur manual. Jangan menggabungkan peluncuran otomatis dan manual untuk
layanan yang sudah berjalan.

## 5. Jalankan PostgreSQL dan periksa migrasi

**Di pod**:

```sh
pg_lsclusters
pg_ctlcluster 16 main status
```

Jika cluster `16 main` berstatus `down`, mulai:

```sh
pg_ctlcluster 16 main start
```

Hasil yang diperlukan: cluster `16 main` online pada port 5432. Mulai PostgreSQL
belum tentu berarti database aplikasi atau skemanya sudah ada.

Periksa revision dengan konfigurasi aplikasi:

```sh
cd /workspace/ai-conversation/backend
uv run --no-sync --env-file /root/.config/ai-conversation/runtime.env python -m alembic current
```

Revision untuk kode saat ini: **`0003_study_evidence`**, yaitu head migrasi.
Jika database memiliki riwayat Alembic yang valid tetapi belum head, jalankan:

```sh
uv run --no-sync --env-file /root/.config/ai-conversation/runtime.env python -m alembic upgrade head
```

Untuk database baru, role/database harus dibuat dahulu seperti bagian 12.
Jangan menjalankan `init_database.py` pada database yang sudah ada. Untuk database
lama tanpa riwayat Alembic, ikuti backup/verifikasi/baseline di [README](README.md);
jangan langsung melakukan stamp atau membuat ulang tabel.

## 6. Jalankan Qwen dan tunggu sampai siap

Pada jalur manual, pastikan port 18001 belum dipakai proses Qwen yang sudah berjalan:

```sh
ss -ltnp | grep ':18001'
```

Jika sudah ada layanan di port itu, periksa health terlebih dahulu. Jika belum ada,
jalankan **di pod**:

```sh
export HF_HOME=/workspace/ai-conversation/cache/huggingface
export HF_HUB_DISABLE_TELEMETRY=1
export VLLM_NO_USAGE_STATS=1
umask 077
setsid /workspace/ai-conversation/backend/.venv/bin/python \
  /workspace/ai-conversation/scripts/launch_llm.py \
  >> /workspace/ai-conversation/logs/llm.log 2>&1 < /dev/null &
echo "$!" > /root/.config/ai-conversation/llm.pid
```

`launch_llm.py` menjalankan vLLM dari `llm-venv`, memuat API key dari `runtime.env`,
dan memakai pengaturan berikut:

- Model lokal `models/qwen3-1.7b`; nama layanan tepat `Qwen/Qwen3-1.7B`.
- Bind `127.0.0.1`, port `18001`, dtype `bfloat16`.
- Batas context 32.768 token, maksimum dua sequence, GPU memory utilization 0,75.
- Eager mode; log isi request dinonaktifkan.

Pantau startup dan health:

```sh
tail -f /workspace/ai-conversation/logs/llm.log
```

Tekan `Ctrl+C` untuk keluar dari **tail**, bukan menghentikan Qwen yang di-background.
Kemudian:

```sh
curl -fsS --max-time 5 http://127.0.0.1:18001/health
```

Tunggu sampai HTTP 200. Saat model masih dimuat, connection refused/health gagal
belum membuktikan instalasi rusak; baca `llm.log`. Memuat Qwen bisa membutuhkan
beberapa menit. `nvidia-smi` menunjukkan penggunaan GPU, tetapi tidak menggantikan
health atau uji inferensi.

## 7. Jalankan FastAPI dan proxy HTTPS

Jika API belum aktif pada port 8002, jalankan **di pod**:

```sh
umask 077
setsid /workspace/ai-conversation/backend/.venv/bin/python \
  /workspace/ai-conversation/scripts/launch_api.py \
  >> /workspace/ai-conversation/logs/api.log 2>&1 < /dev/null &
echo "$!" > /root/.config/ai-conversation/api.pid
```

Peluncur memuat `runtime.env`, memakai working directory `backend`, lalu menjalankan
uvicorn pada `127.0.0.1:8002` dengan **satu worker**, tanpa autoreload. Environment
backend dan vLLM dipisahkan agar dependensi transformers tidak saling bertabrakan.
Uvicorn sendiri tidak otomatis membaca file `.env`.

Periksa API dan database:

```sh
curl -fsS --max-time 5 http://127.0.0.1:8002/health
```

Hasil yang diperlukan: HTTP 200 dengan `{"status":"ok"}`. Jika gagal:

```sh
tail -n 80 /workspace/ai-conversation/logs/api.log
```

Periksa nginx bawaan template:

```sh
nginx -t
pgrep -x nginx
```

Jika pemeriksaan konfigurasi berhasil tetapi tidak ada proses nginx, jalankan
`nginx` untuk memulainya. Jika sudah ada proses, jangan jalankan master kedua.
Kemudian aktifkan konfigurasi proxy yang sudah tersedia:

```sh
/workspace/ai-conversation/backend/.venv/bin/python \
  /workspace/ai-conversation/scripts/configure_proxy.py
```

Hasil yang diperlukan: `nginx -t` berhasil, kemudian reload berhasil. nginx port
8000 meneruskan hanya jalur `/pilot/KODE_AKSES/...` ke API port 8002. Alamat proxy
tanpa jalur privat memang mengembalikan 404.

Memulai API tidak otomatis memulai percakapan atau membuat bot bergabung ke
LiveKit. Itu dilakukan ketika aplikasi meminta pembuatan panggilan.

## 8. Periksa readiness dan HTTPS dari luar pod

**Di pod**:

```sh
curl -fsS --max-time 15 http://127.0.0.1:8002/v1/practice/readiness
```

Hasil yang diperlukan: HTTP 200 dengan `{"ready":true}`. Pemeriksaan ini mencakup
konfigurasi LiveKit, file model lokal, model Qwen yang tersedia, serta kapasitas
panggilan. Ini belum membuktikan audio benar-benar diproses atau terdengar.

Ambil base URL **di pod**:

```sh
python3 -c 'import json; print(json.load(open("/root/.config/ai-conversation/access.json"))["base_url"])'
```

Bentuk alamatnya adalah:

```text
https://ID_POD-8000.proxy.runpod.net/pilot/KODE_AKSES_PRIVAT
```

Gunakan seluruh alamat, tanpa menambahkan `/v1` pada base URL mobile. Kode jalur
tersebut adalah akses privat uji coba; jangan memasukkan nilai aslinya ke Git.
HTTPS disediakan proxy Runpod; lihat [akses HTTP Runpod](https://docs.runpod.io/pods/configuration/expose-ports).

**Di komputer lokal**, tempel hasil base URL:

```sh
conversation_api_url='TEMPEL_BASE_URL_PRIVAT_DI_SINI'
curl -fsS --max-time 20 -A 'ktor-client' "$conversation_api_url/health"
curl -fsS --max-time 20 -A 'ktor-client' "$conversation_api_url/v1/practice/readiness"
```

Keduanya harus HTTP 200. Keberhasilan localhost saja belum membuktikan akses
mobile berhasil. Jika local API berhasil tetapi HTTPS gagal, periksa nginx,
port `8000/http`, ID pod, dan jalur privat yang dipakai.

## 9. Uji percakapan lalu hubungkan mobile

Untuk uji inferensi komponen **di pod**:

```sh
/workspace/ai-conversation/backend/.venv/bin/python \
  /workspace/ai-conversation/scripts/smoke_models.py
```

Skrip memakai input sintetis untuk menguji Qwen, Kokoro Jepang, dan Whisper.
Hasil juga ditulis ke `logs/model-smoke.json`; uji ini tidak membuka percakapan
LiveKit.

Untuk uji audio dua arah melalui LiveKit **di pod**:

```sh
/workspace/ai-conversation/backend/.venv/bin/python \
  /workspace/ai-conversation/scripts/livekit_smoke.py
```

Skrip membuat satu panggilan Practice anonim sementara, mengirim audio sintetis,
menerima audio tutor, mengambil transkrip, lalu mengakhiri panggilan dengan token
panggilan. Hasil di `logs/livekit-smoke.json` harus menunjukkan start 201,
klien tersambung, audio tutor diterima, end 204, dan transkrip final.
Ini tidak membuat peserta studi dan tidak membuktikan playback pada ponsel.

**Di komputer lokal**, dari folder `mobile/`, build Android dengan base URL lengkap:

```sh
./gradlew :androidApp:assembleDebug -PconversationServerUrl='TEMPEL_BASE_URL_PRIVAT_DI_SINI'
```

APK berada di `mobile/androidApp/build/outputs/apk/debug/`. Instal ke ponsel,
beri izin mikrofon, lalu coba mode Practice. Alamat server tertanam saat build;
Settings tidak memiliki input alamat server/token. Jika base URL berubah,
mobile perlu dibuild ulang. Jangan memasukkan LiveKit API secret ke mobile.

Setup ini telah melewati uji inferensi, audio LiveKit SDK, pengakhiran panggilan,
dan transkrip final. Playback ponsel, input Inggris melalui LiveKit, kedua metode
EOT dengan inferensi nyata, dan dua panggilan bersamaan belum divalidasi.
Respons suara pada uji sintetis masih sekitar 10–13 detik setelah ucapan selesai;
latensi tersebut masih perlu diperbaiki sebelum menyebut percakapan realtime nyaman.

## 10. Membaca log dan menangani kegagalan

| Gejala | Yang diperiksa |
|---|---|
| SSH/Jupyter tidak tersedia | Pod masih initializing, info SSH terbaru, dan port 8888/22. |
| Qwen health gagal | `logs/llm.log`, GPU pada `nvidia-smi`, model safetensors, dan environment vLLM. |
| `Address already in use` | `ss -ltnp`; jangan meluncurkan proses kedua pada port yang sama. |
| API gagal startup | `logs/api.log`, PostgreSQL, password/database, dan revision Alembic. |
| `/health` 200 tetapi readiness 503 | LiveKit URL/key/secret, file model, API key Qwen, nama model, dan slot panggilan. |
| `capacity_full` | Dua slot total sedang dipakai; akhiri panggilan yang aktif atau tunggu cleanup. |
| HTTPS 404 | Gunakan base URL lengkap dengan jalur privat; root proxy memang 404. |
| HTTPS 502/503 | API lokal belum siap, nginx, atau upstream port 8002. |
| HTTPS 403 | Periksa base URL dan coba curl dengan user-agent seperti bagian 8; jangan menonaktifkan TLS. |
| Skrip startup tidak memulai proses, tetapi health gagal | Baca log dan periksa PID hidup/stale; skrip bukan supervisor yang menyembuhkan layanan otomatis. |
| Database/config hilang setelah operasi Pod | Pemulihan bagian 12; network volume tidak menyimpan kedua data itu pada setup ini. |
| Uji TTS Jepang gagal | Paket Misaki/Open JTalk, kamus Open JTalk, model Kokoro, dan voicepack yang cocok. |

Log utama **di pod**:

```sh
tail -f /workspace/ai-conversation/logs/api.log
tail -f /workspace/ai-conversation/logs/llm.log
```

Jalankan masing-masing di terminal berbeda jika ingin memantau keduanya.
Log bootstrap/dependensi ada di `logs/bootstrap.log` dan `logs/japanese-deps.log`.
Skrip deployment tidak dipantau oleh systemd/supervisor pada setup ini.
Skrip recovery dan backup di panduan ini belum diuji dengan mereset pod aktif;
perintahnya telah dicocokkan dengan skrip serta versi CLI yang tersedia.

## 11. Menghentikan layanan dan membuat cadangan

### Menghentikan proses aplikasi

Akhiri panggilan aktif sebelum menghentikan API. **Di pod**, periksa dahulu bahwa
PID masih merupakan layanan kita:

```sh
ps -p "$(cat /root/.config/ai-conversation/api.pid)" -o pid,comm,args
ps -p "$(cat /root/.config/ai-conversation/llm.pid)" -o pid,comm,args
```

Jika PID sesuai, hentikan API dahulu, kemudian Qwen:

```sh
kill -TERM "$(cat /root/.config/ai-conversation/api.pid)"
kill -TERM "$(cat /root/.config/ai-conversation/llm.pid)"
```

Tunggu proses berhenti; periksa `ss -ltnp` dan `nvidia-smi`. PID file dapat menjadi
stale; jangan membunuh proses lain hanya karena PID lama dipakai ulang.
PostgreSQL boleh tetap hidup. Jika ingin menghentikannya juga:

```sh
pg_ctlcluster 16 main stop
```

Ini hanya menghentikan layanan. nginx/Jupyter dan alokasi Pod tetap berjalan.
Untuk menghidupkan aplikasi kembali tanpa kehilangan disk container, gunakan
`start-services.sh`, lalu ulangi pemeriksaan readiness/HTTPS.

### Cadangan sebelum operasi yang menghapus disk container

Tiga hal yang perlu disimpan di luar pod: `runtime.env`, `access.json`, dan backup
database jika data PostgreSQL ingin dipertahankan. Network volume menyimpan kode,
model, dan skrip; jangan menaruh kredensial atau backup database privat di sana.

Buat dump **di pod**, setelah panggilan aktif selesai. Gunakan nama berbeda jika
sudah ada backup lama yang ingin dipertahankan:

```sh
runuser -u postgres -- sh -c 'umask 077; pg_dump -Fc -d conversation -f /tmp/conversation-backup.dump'
```

Format ini dipulihkan dengan `pg_restore`; lihat [pg_dump PostgreSQL 16](https://www.postgresql.org/docs/16/app-pgdump.html).

**Di komputer lokal**, gunakan informasi terbaru dari `runpodctl ssh info`:

```sh
conversation_pod_ip='ISI_IP_POD'
conversation_ssh_port='ISI_PORT_SSH_EKSTERNAL'
conversation_ssh_key='ISI_PATH_PRIVATE_KEY_SSH'
conversation_backup_dir="$HOME/runpod-private-backup"
mkdir -p "$conversation_backup_dir"
chmod 700 "$conversation_backup_dir"
scp -i "$conversation_ssh_key" -P "$conversation_ssh_port" \
  "root@$conversation_pod_ip:/root/.config/ai-conversation/runtime.env" \
  "root@$conversation_pod_ip:/root/.config/ai-conversation/access.json" \
  "root@$conversation_pod_ip:/tmp/conversation-backup.dump" \
  "$conversation_backup_dir/"
chmod 600 "$conversation_backup_dir"/*
```

Simpan cadangan privat di luar repository. Cadangan ini manual dan mewakili waktu
saat dibuat; tidak ada backup database otomatis yang dipasang oleh setup ini.

## 12. Pemulihan setelah disk container hilang

Bagian ini untuk container kosong dengan **network volume yang sama masih ada**.
Jangan menjalankannya pada layanan aktif atau database berisi data yang belum
dicadangkan. Tidak perlu mengunduh ulang model yang masih lengkap di volume.

### 12.1 Pastikan image, volume, dan port sesuai

Gunakan image yang sama seperti bagian 2, pasang network volume di `/workspace`,
dan siapkan `8000/http`, `8888/http`, `22/tcp`. Jika menggunakan pod baru, volume
harus dipilih ketika pembuatan pod dan berada di data center yang cocok.
Lihat [network volumes Runpod](https://docs.runpod.io/storage/network-volumes).

Periksa GPU dan direktori model seperti bagian 3. Pastikan skrip deployment
masih ada di `scripts/`; clone backend saja tidak otomatis menyediakan seluruh
skrip penyiapan pod yang saat ini tersimpan di network volume.

### 12.2 Pulihkan paket sistem dan environment

**Di pod**:

```sh
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y postgresql-16 espeak-ng ffmpeg libsndfile1 rsync build-essential
export UV_CACHE_DIR=/workspace/ai-conversation/cache/uv
export UV_LINK_MODE=copy
cd /workspace/ai-conversation/backend
uv sync --frozen --no-dev --extra calls --extra tutor --python /usr/bin/python3
```

Periksa PyTorch bawaan image sebelum memulihkan vLLM:

```sh
/usr/bin/python3 -c 'import torch; print(torch.__version__, torch.cuda.is_available())'
```

Harus cocok dengan PyTorch 2.8.0 dan CUDA tersedia. Pulihkan environment vLLM
pada image yang cocok, tanpa menghapus isi yang ada:

```sh
uv venv --allow-existing --system-site-packages --python /usr/bin/python3 \
  /workspace/ai-conversation/llm-venv
uv pip install --python /workspace/ai-conversation/llm-venv/bin/python \
  'vllm==0.10.2' 'transformers==4.55.2'
/workspace/ai-conversation/backend/.venv/bin/python -c \
  'from misaki.ja import JAG2P; JAG2P(version="pyopenjtalk")("こんにちは")'
```

Ini juga menyiapkan kamus Open JTalk sebelum panggilan pertama. Jangan menjalankan
bootstrap ulang hanya untuk menyalakan layanan: bootstrap memasang dependensi
dan `download_qwen.py` mencari revision upstream saat itu. Untuk model yang
masih lengkap, pertahankan revision pada `models/qwen-revision.json`.

### 12.3 Pulihkan kredensial

**Di pod**, siapkan direktori privat pada disk container:

```sh
mkdir -p /root/.config/ai-conversation
chmod 700 /root/.config/ai-conversation
```

**Di komputer lokal**, setelah memperbarui variabel SSH bagian 11, kirim konfigurasi:

```sh
scp -i "$conversation_ssh_key" -P "$conversation_ssh_port" \
  "$conversation_backup_dir/runtime.env" "$conversation_backup_dir/access.json" \
  "root@$conversation_pod_ip:/root/.config/ai-conversation/"
```

**Di pod**:

```sh
chmod 600 /root/.config/ai-conversation/runtime.env /root/.config/ai-conversation/access.json
```

Jika tidak ada cadangan konfigurasi, buat ulang `runtime.env` berdasarkan bagian 3
dengan LiveKit key/secret milik proyek Anda, password database baru, dan kunci Qwen
baru. File dengan placeholder belum dapat menjalankan aplikasi.

### 12.4 Buat database baru atau pulihkan dump

Mulai PostgreSQL **di pod**:

```sh
pg_ctlcluster 16 main start
runuser -u postgres -- psql -At -d postgres \
  -c "SELECT datname FROM pg_database WHERE datname='conversation';"
runuser -u postgres -- psql -At -d postgres \
  -c "SELECT rolname FROM pg_roles WHERE rolname='conversation';"
```

Jika database atau role `conversation` sudah ada, jangan menjalankan inisialisasi
ulang; periksa keadaan yang sudah ada dahulu. Pada cluster
baru yang belum memiliki role maupun database `conversation`, jalankan **sekali**:

```sh
/workspace/ai-conversation/backend/.venv/bin/python \
  /workspace/ai-conversation/scripts/init_database.py
```

Skrip membuat role dengan password dari `runtime.env`, kemudian database miliknya.
Ini tidak mengembalikan data yang hilang.

Jika ada dump yang ingin dipulihkan, kirim dari **komputer lokal**:

```sh
scp -i "$conversation_ssh_key" -P "$conversation_ssh_port" \
  "$conversation_backup_dir/conversation-backup.dump" \
  "root@$conversation_pod_ip:/tmp/conversation-backup.dump"
```

Pulihkan hanya ke database baru/kosong tadi, **di pod**:

```sh
chown postgres:postgres /tmp/conversation-backup.dump
chmod 600 /tmp/conversation-backup.dump
runuser -u postgres -- pg_restore --exit-on-error --no-owner \
  --role=conversation --dbname=conversation /tmp/conversation-backup.dump
```

Jika tidak ada dump, pengujian dimulai dengan database kosong. Setelah salah satu
jalur tersebut, jalankan migrasi:

```sh
cd /workspace/ai-conversation/backend
uv run --no-sync --env-file /root/.config/ai-conversation/runtime.env python -m alembic upgrade head
```

Jangan menggabungkan restore dengan tabel yang sudah dimigrasikan/berisi data.
Lihat [pg_restore PostgreSQL 16](https://www.postgresql.org/docs/16/app-pgrestore.html).

### 12.5 Perbarui alamat jika ID pod berubah atau access.json hilang

`configure_proxy.py` yang dipasang awal memuat ID pod awal ketika membuat alamat
baru. Karena itu, untuk pod baru buat/perbarui `access.json` terlebih dahulu.
**Di pod**, isi ID aktual dari Console/CLI:

```sh
export CONVERSATION_DEPLOY_POD_ID='ISI_ID_POD_AKTIF'
python3 - <<'PY'
import json
import os
import secrets
from pathlib import Path

pod_id = os.environ['CONVERSATION_DEPLOY_POD_ID']
if pod_id == 'ISI_ID_POD_AKTIF' or not pod_id.isalnum():
    raise SystemExit('Isi ID pod aktual terlebih dahulu')
path = Path('/root/.config/ai-conversation/access.json')
access = json.loads(path.read_text()) if path.exists() else {
    'prefix': '/pilot/' + secrets.token_hex(32)
}
access['base_url'] = f"https://{pod_id}-8000.proxy.runpod.net" + access['prefix']
path.write_text(json.dumps(access, indent=2))
path.chmod(0o600)
print('Konfigurasi alamat API diperbarui; nilainya tidak dicetak')
PY
```

Kode akses dari backup dipertahankan jika file ada; jika file hilang, kode baru
dibuat. ID pod yang sama dan konfigurasi yang dipulihkan tidak memerlukan
perubahan alamat. Mulai seluruh layanan dengan `start-services.sh`, kemudian
ikuti pemeriksaan bagian 5–9. Mobile perlu dibuild ulang jika base URL berubah.

## 13. Batas penggunaan setup ini

Mulai dari satu panggilan Practice pribadi. Maksimum dua slot total adalah batas
kode, bukan bukti dua panggilan berjalan dengan latensi yang nyaman. API memakai
satu proses karena kepemilikan panggilan belum mendukung banyak worker.

Untuk penggunaan peserta studi, diperlukan database yang persisten, penyimpanan
evidence privat yang benar-benar menerapkan mode 700, serta persetujuan consent
versi final dan kebijakan retensi. Konfigurasi uji coba saat ini tidak menyediakan
hal tersebut. Transkrip Practice berada dalam memori proses selama waktu terbatas;
restart API tidak mempertahankan transkrip Practice.

## 14. Uji GPU pada RTX 4090

Pada pod demo RTX 4090, Whisper menggunakan CUDA float16 dan Kokoro menggunakan
ONNX CUDA; Smart Turn, Silero VAD, dan frontend fonem Jepang tetap CPU. Qwen tetap
memakai GPU. API tetap satu worker. Alamat demo memakai jalur privat pada proxy
port 8888, dengan Jupyter diteruskan ke port lokal 8889; tidak perlu reset pod
atau rebuild Android jika base URL ini tetap sama.

Environment CPU `.venv` dipertahankan. Environment `.venv-gpu` menggunakan paket
dari lock yang sama dengan penggantian `onnxruntime` menjadi
`onnxruntime-gpu==1.23.2`. Untuk menyiapkan environment tersebut dari kode terkini:

```sh
cd /workspace/ai-conversation/backend
export UV_CACHE_DIR=/workspace/ai-conversation/cache/uv
CONVERSATION_GPU_PYTHON=/usr/bin/python3 bash scripts/install_gpu_trial.sh
```

Jangan menjalankan `uv sync` biasa pada `.venv-gpu` atau memasang kedua distribusi
ONNX sekaligus. Library CUDA/cuDNN bawaan image tersedia di
`/usr/local/lib/python3.12/dist-packages/nvidia/*/lib`; path tersebut harus masuk
`LD_LIBRARY_PATH` **sebelum** interpreter GPU diluncurkan.

Konfigurasi privat demo di `runtime.env` menetapkan:

```dotenv
TUTOR_WHISPER_DEVICE=cuda
TUTOR_WHISPER_COMPUTE_TYPE=float16
TUTOR_KOKORO_EXECUTION_PROVIDER=CUDAExecutionProvider
ONNX_PROVIDER=CPUExecutionProvider
CONVERSATION_API_PYTHON=/workspace/ai-conversation/backend/.venv-gpu/bin/python
```

Peluncur `launch_api.py` pada pod membaca `CONVERSATION_API_PYTHON`; skrip
`start-services.sh` tetap dapat memulai layanan yang mati. `ONNX_PROVIDER` mengatur
pemuatan awal Kokoro; adapter Jepang kemudian memilih CUDA secara eksplisit untuk
session-nya. Operator ONNX yang tidak didukung CUDA masih dapat memakai CPU.

Benchmark sintetis Jepang, median tiga inferensi setelah warm-up: Whisper CPU
4,924 detik versus GPU 0,066 detik; Kokoro CPU 6,910 detik versus GPU 0,147 detik.
Profil Kokoro mencatat eksekusi node CUDA; provider Smart Turn/VAD terverifikasi
CPU. Hasil komponen tidak menggantikan uji audio LiveKit atau playback ponsel.
Setelah cleanup model per panggilan ditambahkan, tiga panggilan Practice LiveKit
berurutan berhasil dengan audio pertama 4,50–6,42 detik sejak input mulai dikirim,
pengakhiran HTTP 204, dan transkrip final. VRAM setelah masing-masing panggilan
tetap 19.338 MiB. Satu panggilan adalah sasaran demo; playback ponsel dan kapasitas
dua panggilan bersamaan belum divalidasi.

Pemeriksaan jeda dengan dua panggilan sintetis tambahan pada API diagnostik lokal
menunjukkan audio pertama sekitar 1,36 dan 5,63 detik setelah akhir audio ucapan
yang dikirim. Whisper selesai dalam 0,11–0,26 detik. Pada uji yang lambat, Smart
Turn menilai ucapan belum selesai dan menunggu batas hening 3 detik; pada uji
berikutnya model langsung menerima akhir giliran. Kokoro menghasilkan audio
pertama dalam 0,76–0,93 detik termasuk frontend dan inferensi pertama per call.
Angka benchmark komponen setelah warm-up bukan latensi respons percakapan. API
diagnostik dihentikan setelah pengukuran; kebijakan akhir giliran belum diubah.

Log API GPU: `logs/api-gpu-demo-4090.log`. Konfigurasi CPU sebelum penggantian
tersimpan privat di `/root/.config/ai-conversation/runtime-cpu.env`. Untuk kembali
ke CPU, akhiri panggilan aktif, hentikan **proses API yang PID-nya sudah diverifikasi**
seperti bagian 11, pulihkan file tersebut ke `runtime.env`, lalu mulai layanan.
Qwen dan pod tidak perlu dihentikan untuk perubahan backend ini.

Setelah migrasi Neon, backup `runtime-cpu.env` masih menunjuk database lokal lama.
Untuk mengganti inferensi kembali ke CPU, pertahankan `DATABASE_URL` dan
`DATABASE_URL_UNPOOLED` Neon dari runtime aktif; jangan menimpa seluruh runtime
dengan backup CPU tersebut.

## 15. Database Neon pada demo RTX 4090

Pada 5 Oktober 2026, database backend dipindahkan dari PostgreSQL 16 di disk
container ke PostgreSQL 18 Neon: proyek `kaiwa` (`still-paper-71605449`), branch
`production`, database `neondb`, region Singapore (`aws-ap-southeast-1`). API
tetap berjalan pada pod RTX 4090 dengan satu worker dan alamat HTTPS yang sama;
perpindahan database tidak memerlukan build ulang Android.

Konfigurasi aktif berada di `/root/.config/ai-conversation/runtime.env` dengan
mode 600. `DATABASE_URL` memakai URL `postgresql+psycopg://` pooled dengan TLS;
`DATABASE_URL_UNPOOLED` memakai URL langsung untuk Alembic. Kredensial tidak
disimpan di dokumentasi atau source. Alembic membaca URL langsung apabila tersedia:

```sh
cd /workspace/ai-conversation/backend
uv run --no-sync --env-file /root/.config/ai-conversation/runtime.env python -m alembic upgrade head
```

Restore diuji pada branch sementara sebelum cutover; branch uji dihapus setelah
validasi selesai. API kemudian dihentikan
tanpa panggilan aktif, dump final dibuat, dan data direstore ke database Neon
kosong. Revisi `0003_study_evidence`, checksum isi enam tabel, kolom, constraint,
indeks, serta satu sequence cocok dengan sumber. Tabel peserta dan sesi studi
masih kosong. Perbandingan metadata memperhitungkan representasi `NOT NULL` dan
cast array indeks yang berbeda antara PostgreSQL 16 dan 18. Transaksi tulis
melalui pooler juga diuji lalu di-rollback. API siap kembali sekitar 46 detik
setelah cutover dimulai. HTTPS health/readiness, pembuatan panggilan Practice
HTTP 201, dan pengakhirannya HTTP 204 lulus; ini bukan uji playback ponsel baru.

Qwen, Whisper, Kokoro, Smart Turn, VAD, LiveKit, dan kebijakan studi tetap memakai
konfigurasi sebelumnya. Skrip `scripts/start-services.sh` di pod melewati startup
PostgreSQL lokal apabila runtime menunjuk Neon. Cluster PostgreSQL lokal beserta
data lamanya dipertahankan untuk pemulihan; backend aktif memakai Neon. Jangan
beralih ke salinan lokal lama setelah ada tulisan baru di Neon tanpa memindahkan
perubahan tersebut terlebih dahulu.

Backup tersedia di dua tempat:

- Di pod: `/workspace/ai-conversation/private-backups/neon-20261005.tar.gz.aesgcm`,
  arsip terenkripsi AES-256-GCM berisi dump final, runtime sebelum/sesudah migrasi,
  dan manifest pemeriksaan. Network volume ini tidak menerapkan `chmod` privat,
  sehingga backup plaintext telah dihapus dari volume.
- Di komputer lokal: `.neon-backups/2026-10-05/`, diabaikan Git, direktori mode 700
  dan file mode 600. Salinan plaintext ada di `pod/`; arsip terenkripsi dan kunci
  `neon-backup-20261005.key` juga disimpan di sini. Kunci cadangan di pod berada pada
  disk container privat `/root/.config/ai-conversation/`, bukan network volume.

Dekripsi autentik arsip lokal telah diverifikasi, dan dump serta konfigurasi
hasil dekripsinya cocok dengan salinan backup lokal.

Untuk mendekripsi arsip **di komputer lokal**, jalankan dari root repository.
Perintah berikut memakai environment sementara, tidak mengubah dependensi GPU:

```sh
uv run --no-project --with cryptography python - <<'PY'
import os
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

os.umask(0o077)
root = Path('.neon-backups/2026-10-05')
data = (root / 'neon-20261005.tar.gz.aesgcm').read_bytes()
assert data[:6] == b'KAIWA1'
key = (root / 'neon-backup-20261005.key').read_bytes()
clear = AESGCM(key).decrypt(data[6:18], data[18:], b'kaiwa-neon-backup-v1')
(root / 'neon-20261005.tar.gz').write_bytes(clear)
PY
```

Restore dump hanya ke database tujuan kosong melalui koneksi langsung, memakai
`pg_restore --exit-on-error --single-transaction --no-owner --no-privileges`.
Sesudahnya jalankan Alembic dan health/readiness. Transkrip Practice tetap berada dalam
memori; migrasi database tidak mengubahnya menjadi arsip permanen.

## 16. Rekaman Testing di Neon Object Storage

Testing menggunakan bucket privat `kaiwa`, dengan konfigurasi S3 di runtime server
dan `STUDY_EVIDENCE_BUCKET=kaiwa`. Retensi untuk pengujian pribadi pemilik aplikasi
ditetapkan 30 hari setelah pemilik meminta memilih durasi operasional. Ini bukan
standar retensi universal atau persetujuan kebijakan untuk peserta penelitian.

`STUDY_EVIDENCE_DIR=/root/.config/ai-conversation/study-evidence` adalah staging
privat mode 700 pada disk container, di luar jalur HTTP. Setelah panggilan berakhir,
`user.wav`, `assistant.wav`, dan `events.jsonl` diunggah serta diperiksa melalui S3;
`manifest.json` diunggah terakhir. Hanya setelah manifest tersimpan dan bisa dibaca
kembali, checksum dicatat pada PostgreSQL Neon dan staging lokal dibuang. Upload
gagal tidak menyelesaikan sesi. Evidence final dapat dibaca setelah container
diganti dengan memulihkan runtime serta kredensial S3 yang sama.

Housekeeping menghapus objek evidence yang berumur lebih dari 30 hari dan capture
lokal yang ditinggalkan. Penghapusan berjalan selama API hidup; ketika API mati,
cleanup dilanjutkan saat startup berikutnya. Metadata database tidak ikut dihapus.
Capture aktif, objek di luar prefix `study/`, serta berkas aplikasi lain tidak dihapus.
Panggilan yang terputus sebelum evidence final diunggah tidak dijamin pulih jika
disk container hilang, dan tidak boleh dinyatakan sebagai sesi selesai.

Konfigurasi lokal `backend/.env` juga menggunakan database dan bucket Neon, dengan
staging lokal privat pada `backend/.study-evidence/`. Folder tersebut diabaikan Git.
Runtime terbaru dan konfigurasi sebelum perubahan dicadangkan terenkripsi di
`private-backups/study-neon-20261005.tar.gz.aesgcm`, menggunakan kunci backup privat
yang sama dengan migrasi database. Salinan runtime lokal berada di folder backup
yang diabaikan Git, bukan source.
Practice tidak membuat rekaman studi atau objek bucket. Alamat backend dan build
Android tetap sama. Evidence berisi offset audio serta timestamp transkrip; durasi
terpisah Whisper/Qwen/Kokoro dan waktu playback ponsel belum dicatat otomatis.

Uji Testing sintetis memakai database SQLite terisolasi dan pipeline GPU/LiveKit
nyata: start HTTP 201, end HTTP 204, kedua track audio dan dua berkas metadata
tersimpan di Neon, serta transkrip pulih tanpa staging lokal. Panggilan pendek
tidak membuka sesi kedua. Objek sintetis dihapus setelah verifikasi; tidak ada
peserta uji yang ditambahkan ke database produksi. Health/readiness HTTPS setelah
deployment kembali HTTP 200. Playback ponsel tidak diuji ulang dalam verifikasi ini.
