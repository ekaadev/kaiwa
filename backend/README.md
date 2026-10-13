# AI Conversation — backend foundation

**Scope so far:** a FastAPI control API for anonymous study enrollment, balanced fixed/adaptive allocation, study attempt lifecycle rules, and opt-in LiveKit/Pipecat transport for study and anonymous practice calls. The tutor uses local Whisper small multilingual, Smart Turn v3.2 (adaptive), Qwen3-1.7B via a self-hosted OpenAI-compatible endpoint, and Kokoro-82M Japanese with Misaki/Open JTalk phonemes. Private Runpod smoke tests have exercised real inference and anonymous two-way LiveKit SDK audio; phone playback and concurrent calls remain unvalidated; without all model assets and an accessible inference server the API fails closed. The shared mobile client, transcript delivery, and private study evidence writer are implemented; research export is **not implemented**. Study completion requires explicitly configured private evidence storage and retention. This is not ready for real participants or public deployment.

The architecture decision is: KMP mobile client → FastAPI on a long-running RunPod Pod for control; mobile and Pipecat (also on RunPod) each join a LiveKit Cloud room for WebRTC media. No public inbound UDP is required on the RunPod Pod. PostgreSQL stores study metadata; audio files will be separate. The Obsidian concept/requirements docs remain the source of product behavior.

## Local development

Requires Python 3.11–3.13, `uv`, and Docker for a local PostgreSQL instance.

```sh
cd backend
uv sync --group dev
# local development DB only; production must use different credentials and backups
docker compose up -d postgres
export DATABASE_URL='postgresql+psycopg://conversation:local-dev-only@localhost:55432/conversation'
export STUDY_CONSENT_VERSION='draft-v1'
uv run alembic upgrade head  # new database only; see existing-database note below
uv run uvicorn app.main:app --reload
```

`GET /health` checks the DB. `POST /v1/study/participants` with `{"accepted":true}` returns a pseudonymous participant ID, an **opaque resume token shown only once**, and public Sesi 1/2 statuses (no EOT labels). `GET /v1/study/me` requires `Authorization: Bearer <resume_token>` and returns the same participant/progress. Do not log the token or use participant IDs as authentication.

The study attempt API is `POST /v1/study/sessions/{ordinal}/calls` with `{}`, requiring the bearer resume token and an `Idempotency-Key` header (8–128 printable ASCII characters, freshly generated for each new attempt). It does not accept a method from the client. A repeated key does not create a second attempt; a new key is needed to retry a failed call. Sesi 2 is locked until Sesi 1 is valid. When configured with both `calls` and `tutor` extras and the LiveKit/tutor environment variables below, the backend prepares an isolated `study-*` room with the assigned fixed/adaptive tutor before issuing a room-scoped token; otherwise it returns 503 without making an attempt. A participant may end their own active call with `POST /v1/study/calls/{call_id}/end` using the resume token. Disconnects, setup failure, no join, and operational timeouts are not normal endings. The bot counts only the duration of microphone PCM frames received by the server; joining a room and gaps without frames count as zero. **This is server-received input audio, not proof of audio actually heard by the phone or a stored recording.** Only a normal end with at least 120 seconds of received audio followed by final saved evidence can complete a session; the configured evidence writer must successfully finalize both audio tracks and a manifest before completion. Calls waiting for evidence remain locked for up to 21 minutes before a new attempt can replace them; interrupted calls remain retryable. A process restart loses its in-memory bot/room handle: repeats of an old idempotency key cannot rejoin, and abandoned attempts are recovered on the next reservation after the stale timeout. Deploy a single API process until cross-process call ownership/reconciliation exists.

Database schemas now use Alembic migrations; deployment startup requires revision `0003_study_evidence` and will not create tables. For a **new** database, run `uv run alembic upgrade head` with `DATABASE_URL` set before starting the API. For an **existing** database created by the old startup bootstrap, back it up, inspect that its schema matches migration `0001_study_foundation`, then run `uv run alembic stamp 0001_study_foundation` and `uv run alembic upgrade head`. Do not run the initial migration directly over existing tables or stamp an unverified database. Injected engines in isolated tests still use `create_all` for test fixtures.

For Neon, use a `postgresql+psycopg://` URL with SSL enabled. Set `DATABASE_URL` to
the pooled connection for the API and `DATABASE_URL_UNPOOLED` to the direct
connection for Alembic. Migrations prefer `DATABASE_URL_UNPOOLED` when it is
nonempty, otherwise they use `DATABASE_URL`. Use direct connections for
`pg_dump`/`pg_restore` too. Credentials generated by the Neon CLI in the repository
root `.env.local` are not automatically loaded by the Python backend; supply them
through its private runtime environment. See [the RunPod deployment guide](RUNPOD.md)
for the deployed database and migration backups.

`POST /v1/practice/calls` takes `{}` without a study token or research consent. The request does **not** accept an EOT method; the backend fixes the method to `adaptive`. The API does not use the enrollment path or write study records. Without LiveKit and tutor configuration or both the `calls` and `tutor` extras, it returns `503` and issues no credentials. When configured, it returns `call_id`, `room_url`, and a short-lived, room-scoped `join_token` **only after the speech pipeline is constructed and Pipecat joins the room**. `GET /v1/practice/readiness` checks LiveKit API connectivity, available call capacity, local model files and whether the Qwen endpoint advertises the selected model; this is a preflight, not a guarantee of successful inference. Both endpoints fail closed when unavailable. Practice audio/history must stay out of research storage and exports.

For practice availability, `GET /v1/practice/readiness` returns `200 {"ready":true}` or `503`. Both its failure and a failed `POST /v1/practice/calls` use the same safe error shape: `{"detail":{"code":"capacity_full","message":"Practice calls are at capacity"}}` when this process has no free call slots, or `{"detail":{"code":"service_unavailable","message":"Practice calls are unavailable"}}` for missing configuration or connection/setup failure. These codes are for client-facing messages, not provider diagnostics. Both endpoints set `Cache-Control: no-store`. The mobile client must check microphone permission separately, show an actionable message when it is denied, and treat the `POST` response as authoritative: readiness may succeed before a later connection failure. The mobile client lives in `mobile/` and accepts its HTTPS control API address through Settings.

### LiveKit study and practice transport (backend only)

Provide `LIVEKIT_URL` (a `wss://` URL), `LIVEKIT_API_KEY`, and `LIVEKIT_API_SECRET` in your untracked `.env` or runtime environment. They remain server-side; the client only receives its restricted join token. For tutor inference you must additionally configure:

- `TUTOR_WHISPER_PATH`: absolute path to a **local faster-whisper small multilingual** model directory containing `model.bin` (e.g. download `Systran/faster-whisper-small` before starting; do not use `small.en`). The STT does automatic language detection for English and Japanese and transcribes rather than translating.
- `TUTOR_KOKORO_MODEL_PATH` and `TUTOR_KOKORO_VOICES_PATH`: absolute paths to the Kokoro-82M v1.0 ONNX model and matching voicepack. Pipecat's Kokoro service documents the `kokoro-v1.0.onnx` and `voices-v1.0.bin` downloads. The backend uses Japanese `jf_alpha` / `ja`.
- `TUTOR_LLM_BASE_URL`: URL of a **self-hosted OpenAI-compatible** API (including `/v1`) serving `Qwen/Qwen3-1.7B`. Its `/models` response must advertise that exact ID and it must support the Qwen non-thinking chat-template option. Set `TUTOR_LLM_API_KEY` if the server requires one; it defaults to `local`. Do not use an unapproved external inference service for participant speech.

The `.env` file is not automatically loaded by uvicorn:

```sh
uv sync --group dev --extra calls --extra tutor
LOGURU_LEVEL=INFO uv run --extra calls --extra tutor --env-file .env uvicorn app.main:app --reload
```

Whisper and Kokoro default to CPU. For an opt-in Linux NVIDIA trial, run
`bash scripts/install_gpu_trial.sh` to create a separate `.venv-gpu` using the frozen
dependencies with `onnxruntime-gpu==1.23.2` in place of the CPU ONNX distribution.
The GPU environment deliberately installs the exported requirements without resolving
Pipecat's CPU ONNX package again; do not install both ONNX distributions into it or run
ordinary `uv sync` against this environment. CUDA 12/cuDNN 9 shared libraries must be
available to the process at launch (for example through `LD_LIBRARY_PATH` on the PyTorch pod).

Set `TUTOR_WHISPER_DEVICE=cuda`, `TUTOR_WHISPER_COMPUTE_TYPE=float16`, and
`TUTOR_KOKORO_EXECUTION_PROVIDER=CUDAExecutionProvider`, then launch the single API worker
with `.venv-gpu/bin/python`, explicitly loading the runtime environment. Smart Turn and
Silero VAD remain on CPU. Set `ONNX_PROVIDER=CPUExecutionProvider` at launch so Kokoro's
initial model load uses CPU before the adapter applies its per-session CUDA configuration.
Requested Kokoro CUDA failures do not silently rerun the entire model on CPU, although
unsupported individual ONNX operators may use CPU. The configured 1 GiB CUDA arena per
Kokoro session is not a cap on all process VRAM. Verify inference and measure memory before
assuming two concurrent calls fit alongside Qwen.
Per-call Whisper and Kokoro model resources are explicitly released during pipeline cleanup,
so processor reference cycles do not retain their native models until garbage collection.

For a synthetic component comparison, use the same runtime configuration:

```sh
PYTHONPATH=. .venv-gpu/bin/python scripts/benchmark_speech.py \
  --output /private/path/speech-benchmark.json
```

It measures warm CPU/GPU medians and profiles actual Kokoro CUDA nodes; it does not
open a call, create study records, or validate phone playback.

On Debian/Ubuntu, the Japanese frontend dependencies may need a C++ compiler when no
compatible prebuilt wheel is available. If installation fails with `No such file or directory:
'c++'`, install the compiler and repeat the locked dependency installation:

```sh
sudo apt-get install -y g++
uv sync --frozen --group dev --extra calls --extra tutor
uv run --no-sync python -c 'from misaki.ja import JAG2P; print("Japanese frontend import OK")'
```

For an IDE warning such as `Import "misaki.ja" could not be resolved`, first ensure this
installation completed, then select `backend/.venv/bin/python` as the project's Python
interpreter. The lightweight API dependencies alone do not install the `tutor` extra.

The tutor pipeline is constructed before the bot joins and before the start request succeeds. Practice uses adaptive EOT; authorized study calls use their assigned fixed/adaptive method (fixed: 700 ms silence). Adaptive uses the bundled Smart Turn v3.2 CPU model with a 3-second silence cap. Qwen is instructed to answer in Japanese, 1–3 short sentences with at most one question. Japanese practice audio has been exercised with real inference. Response constraints, Japanese voice quality, English input over LiveKit, phone playback, and latency under concurrent load still need validation. A 4 GB GPU must not be assumed sufficient; Whisper defaults to CPU int8 with an opt-in CUDA configuration, and server sizing must be measured with two concurrent calls. Model assets and the OpenAI-compatible endpoint are configuration, not RunPod-specific dependencies. Rooms are removed if bot setup fails, no client joins within 60 seconds, the client disconnects, or the call reaches its 20-minute operational limit. This single-process implementation allows at most **two calls total across practice and study**; **do not expose anonymous provisioning publicly** without durable resource/rate limits and deployment testing. Deployment network tests (including UDP/TCP/TURN fallback), verifying microphone frame timing and both EOT methods against actual inference, and the mobile microphone/connection flow are separate work. Do not enable Pipecat's optional Smart Turn audio logging or DEBUG transcription/TTS logs for real participants.

Local CPU smoke tests have detected synthetic Japanese and English speech with Whisper. A private Runpod practice smoke test additionally exercised Qwen generation, Japanese phoneme-based Kokoro synthesis, two-way LiveKit SDK audio, authenticated call ending, and finalized transcripts without creating study records. This does not validate audible phone playback, both EOT methods, response compliance, or two-call concurrency. Response latency still needs improvement. Keep model caches outside the repository and pin model revisions. See [the private Runpod setup](RUNPOD.md) for access and storage boundaries.

To try Whisper with your **microphone now** on Linux (not an existing audio file), run from `backend/`:

```sh
uv run --extra tutor --env-file .env python scripts/try_whisper_microphone.py
```

Press Enter, speak for 5 seconds, then see the detected language and transcription. Repeat or type `q` to quit. This uses `arecord` (from `alsa-utils`) to send microphone PCM directly to Whisper in memory; no audio is saved. It requires `TUTOR_WHISPER_PATH` in `.env`, but **does not require Qwen, Kokoro, FastAPI, or LiveKit**. If the default ALSA input is wrong, list devices with `arecord -L` and supply `--device NAME`; `--seconds 8` changes the recording duration. This is turn-by-turn microphone transcription, not word-by-word streaming.

The consent text/version and privacy policy must be approved **before** any real participant uses the study enrollment endpoint. A user-facing study explanation and consent are not provided by this backend alone.

## Tests

```sh
uv run pytest -q
uv run ruff check .
```

Unit/API tests use SQLite in-memory for speed. A separate **concurrent PostgreSQL allocation test** runs only with a disposable test database (it drops its own tables):

```sh
docker compose exec -T postgres psql -U conversation -d postgres -c 'CREATE DATABASE conversation_test;'
export TEST_DATABASE_URL='postgresql+psycopg://conversation:local-dev-only@localhost:55432/conversation_test'
uv run pytest -q
```

The PostgreSQL test checks that 24 simultaneous enrollments stay 12/12; it is skipped if `TEST_DATABASE_URL` is unset. Do not point it at production or the normal development database.

## Next implementation slices

1. Implement a trusted study evidence writer and audio recording, validate received-audio timing and normal endings against real LiveKit media before enabling completion; add operator-only participant handoff on shared devices.
2. Test RunPod outbound UDP/TCP/TURN connectivity and two-way LiveKit audio for both methods with a real Qwen server. Reconcile orphaned rooms/attempts after restarts and support multiple API processes before deployment.
3. Integrate barge-in, recording and event/timestamp correlation; keep normal practice calls out of research data.
4. Add protected audio storage, operator access, retention/deletion policy, and client-side KMP LiveKit adapters for Android/iOS. Never put LiveKit API secrets in mobile clients.

## Mobile transcripts and study evidence

The mobile app uses shared Compose Multiplatform screens and state, native LiveKit Android/Swift
adapters, Room for local transcripts, DataStore for server settings, and platform secure storage for
participant tokens and call capabilities. It accepts an existing researcher-issued resume token;
it does not enroll participants or invent consent copy.

Practice call responses additionally contain `transcript_token`, a call-scoped capability used as
Bearer authorization for `GET /v1/practice/calls/{call_id}/transcript?after=0` and
`POST /v1/practice/calls/{call_id}/end`. Transcript responses contain `turns` (sequence, role, text,
timestamp) and `finalized`. Completed practice transcripts are held only in bounded process memory
for 30 minutes; process restarts discard them. They never enter research persistence.

Study transcripts use `GET /v1/study/calls/{call_id}/transcript?after=0` with the participant resume
token. Ownership is checked before live or durable evidence is read. Only final Whisper text and
post-transport TTS text enter transcripts. An interrupted partial sentence can be omitted when
Kokoro lacks word timing; generated, unspoken replies are not saved as completed turns.
Server output and client audio subscription are not proof of audible playback on a phone.

Before enabling study calls, run `uv run alembic upgrade head` and explicitly configure:

- `STUDY_EVIDENCE_DIR`: absolute, private directory, mode 700, outside HTTP-served paths.
- `STUDY_RETENTION_DAYS`: approved retention period, integer 1–3650; no default is assumed.
- `STUDY_EVIDENCE_BUCKET`: optional private Neon S3 bucket. Set `AWS_ENDPOINT_URL_S3`,
  `AWS_REGION`, `AWS_ACCESS_KEY_ID`, and `AWS_SECRET_ACCESS_KEY` on the server. With
  a bucket configured, `STUDY_EVIDENCE_DIR` is private temporary staging; finalized
  recordings and transcripts are stored durably in the bucket under `study/<call-id>/`.

The backend streams user/server-received and assistant/server-output PCM into separate WAV files,
plus timestamped transcript, audio-offset, and interruption events. It atomically publishes a
fsynced manifest with SHA-256 checksums. The `study_evidence` table references the manifest hash.
Normal endings need 120,000 milliseconds of received microphone PCM and durable final evidence;
missing tracks, capture failures, or storage errors cannot complete a study session. Failed or
interrupted attempts never unlock Session 2. Retention cleanup removes expired UUID directories,
including abandoned incomplete captures. Mount the directory on durable private storage; recordings
have no public download endpoint. Filesystem access is used for local evidence; Neon evidence
requires authenticated S3 access. Cloud uploads are acknowledged and checked before the manifest
is published last and its checksum is registered in Postgres. Upload failures cannot finalize a
session. Final transcripts are fetched from Neon after the local cache or container disappears.
Expired cloud files and abandoned uploads are removed by the backend retention worker; database
metadata is retained. Cleanup runs while the API is running and retries after storage failures.

`POST /v1/study/calls/{call_id}/events` accepts authenticated, bounded client audio-subscription
telemetry (`event`, `client_sequence`, `client_timestamp_ms`), deduplicated per live call. It never
changes received media duration or call outcomes. This is reception metadata, not audible-playback
verification. Real inference, interruption acoustics, transport networks, and phone playback have
not been validated by build/host tests. Maintain the existing single-process deployment constraint.
