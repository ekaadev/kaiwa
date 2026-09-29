# AI Conversation — backend foundation

**Scope so far:** a FastAPI control API for anonymous study enrollment, balanced fixed/adaptive allocation, and read-only study resumption. Anonymous practice calls have an opt-in Pipecat speech pipeline using local Whisper small multilingual, Smart Turn v3.2, Qwen3-1.7B via a self-hosted OpenAI-compatible endpoint, and Kokoro-82M Japanese. The full model/audio pipeline has **not yet been validated with real inference**; without all model assets and an accessible inference server the API fails closed. Study calls, session completion/retry, recordings, and research export are not implemented. This is not ready for real participants or public deployment.

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
uv run uvicorn app.main:app --reload
```

`GET /health` checks the DB. `POST /v1/study/participants` with `{"accepted":true}` returns a pseudonymous participant ID, an **opaque resume token shown only once**, and public Sesi 1/2 statuses (no EOT labels). `GET /v1/study/me` requires `Authorization: Bearer <resume_token>` and returns the same participant/progress. Do not log the token or use participant IDs as authentication.

`POST /v1/practice/calls` takes `{}` without a study token or research consent. The request does **not** accept an EOT method; the backend fixes the method to `adaptive`. The API does not use the enrollment path or write study records. Without LiveKit and tutor configuration or both the `calls` and `tutor` extras, it returns `503` and issues no credentials. When configured, it returns `call_id`, `room_url`, and a short-lived, room-scoped `join_token` **only after the speech pipeline is constructed and Pipecat joins the room**. `GET /v1/practice/readiness` checks LiveKit API connectivity, available call capacity, local model files and whether the Qwen endpoint advertises the selected model; this is a preflight, not a guarantee of successful inference. Both endpoints fail closed when unavailable. Practice audio/history must stay out of research storage and exports.

For practice availability, `GET /v1/practice/readiness` returns `200 {"ready":true}` or `503`. Both its failure and a failed `POST /v1/practice/calls` use the same safe error shape: `{"detail":{"code":"capacity_full","message":"Practice calls are at capacity"}}` when this process has no free call slots, or `{"detail":{"code":"service_unavailable","message":"Practice calls are unavailable"}}` for missing configuration or connection/setup failure. These codes are for client-facing messages, not provider diagnostics. Both endpoints set `Cache-Control: no-store`. The mobile client must check microphone permission separately, show an actionable message when it is denied, and treat the `POST` response as authoritative: readiness may succeed before a later connection failure. No mobile client is implemented in this repository yet.

### LiveKit practice transport (backend only)

Provide `LIVEKIT_URL` (a `wss://` URL), `LIVEKIT_API_KEY`, and `LIVEKIT_API_SECRET` in your untracked `.env` or runtime environment. They remain server-side; the client only receives its restricted join token. For tutor inference you must additionally configure:

- `TUTOR_WHISPER_PATH`: absolute path to a **local faster-whisper small multilingual** model directory containing `model.bin` (e.g. download `Systran/faster-whisper-small` before starting; do not use `small.en`). The STT does automatic language detection for English and Japanese and transcribes rather than translating.
- `TUTOR_KOKORO_MODEL_PATH` and `TUTOR_KOKORO_VOICES_PATH`: absolute paths to the Kokoro-82M v1.0 ONNX model and matching voicepack. Pipecat's Kokoro service documents the `kokoro-v1.0.onnx` and `voices-v1.0.bin` downloads. The backend uses Japanese `jf_alpha` / `ja`.
- `TUTOR_LLM_BASE_URL`: URL of a **self-hosted OpenAI-compatible** API (including `/v1`) serving `Qwen/Qwen3-1.7B`. Its `/models` response must advertise that exact ID and it must support the Qwen non-thinking chat-template option. Set `TUTOR_LLM_API_KEY` if the server requires one; it defaults to `local`. Do not use an unapproved external inference service for participant speech.

The `.env` file is not automatically loaded by uvicorn:

```sh
uv sync --group dev --extra calls --extra tutor
LOGURU_LEVEL=INFO uv run --extra calls --extra tutor --env-file .env uvicorn app.main:app --reload
```

The tutor pipeline is constructed before the bot joins and before the start request succeeds. Only the practice API is exposed, with adaptive EOT; a fixed 700 ms silence strategy exists internally but **study calls must not be opened** before session authorization is implemented. Adaptive uses the bundled Smart Turn v3.2 CPU model with a 3-second silence cap. Qwen is instructed to answer in Japanese, 1–3 short sentences with at most one question. Model output constraints, Japanese voice quality, bilingual transcription and real end-to-end audio/latency **still need local inference validation**. A 4 GB GPU must not be assumed sufficient; Whisper is configured for CPU int8 and server sizing must be measured with two concurrent calls. Model assets and the OpenAI-compatible endpoint are configuration, not RunPod-specific dependencies. Rooms are removed if bot setup fails, no client joins within 60 seconds, the client disconnects, or the call reaches its 20-minute operational limit. This single-process implementation allows at most two concurrent practice calls; **do not expose anonymous provisioning publicly** without durable resource/rate limits and deployment testing. Deployment network tests (including UDP/TCP/TURN fallback) and mobile microphone/connection flow are separate work. Do not enable Pipecat's optional Smart Turn audio logging or DEBUG transcription/TTS logs for real participants.

Local CPU smoke testing has loaded the Whisper small model and Kokoro v1.0, generated synthetic Japanese and English speech, and detected both as `ja`/`en` with nonempty transcriptions. This does **not** validate Qwen generation, the response rules, or two-way LiveKit audio. Before calling the tutor complete, run those end-to-end tests with a real local Qwen3-1.7B server, then measure warm/cold inference latency, RAM/VRAM peak, and two-call concurrency. Keep the model caches outside the repository and pin model revisions for repeatable deployment.

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

1. Add versioned PostgreSQL migrations (current table creation is a development bootstrap), durable study session/attempt lifecycle with an agreed definition of valid completion, and operator-only participant handoff on shared devices.
2. Add short-lived LiveKit room credentials issued only for the assigned session; start Pipecat `LiveKitTransport` joining the same room, without LiveKit Agents worker registration; test RunPod outbound UDP/TCP/TURN connectivity.
3. Integrate fixed/adaptive EOT, speech pipeline, barge-in, recording and event/timestamp correlation; keep normal practice calls out of research data.
4. Add protected audio storage, operator access, retention/deletion policy, and client-side KMP LiveKit adapters for Android/iOS. Never put LiveKit API secrets in mobile clients.
