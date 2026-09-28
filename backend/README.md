# AI Conversation — backend foundation

**Scope so far:** a FastAPI control API for anonymous study enrollment, balanced fixed/adaptive allocation, and read-only study resumption. Anonymous practice calls can now create a LiveKit room and wait for a transport-only Pipecat bot to join. The bot **does not understand or answer speech yet**: EOT, Whisper, Qwen, Kokoro, study calls, session completion/retry, recordings, and research export are not implemented. This is not ready for real participants or public deployment.

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

`POST /v1/practice/calls` takes `{}` without a study token or research consent. The request does **not** accept an EOT method; the backend fixes the method to `adaptive`. The API does not use the enrollment path or write study records. Without LiveKit configuration or the `calls` extra, it returns `503` and issues no credentials. With both available, it returns `call_id`, `room_url`, and a short-lived, room-scoped `join_token` **only after Pipecat joins the room**. `GET /v1/practice/readiness` checks LiveKit API connectivity and available call capacity, not whether the tutor can answer. Both endpoints fail closed when unavailable. Practice audio/history must stay out of research storage and exports.

For practice availability, `GET /v1/practice/readiness` returns `200 {"ready":true}` or `503`. Both its failure and a failed `POST /v1/practice/calls` use the same safe error shape: `{"detail":{"code":"capacity_full","message":"Practice calls are at capacity"}}` when this process has no free call slots, or `{"detail":{"code":"service_unavailable","message":"Practice calls are unavailable"}}` for missing configuration or connection/setup failure. These codes are for client-facing messages, not provider diagnostics. Both endpoints set `Cache-Control: no-store`. The mobile client must check microphone permission separately, show an actionable message when it is denied, and treat the `POST` response as authoritative: readiness may succeed before a later connection failure. No mobile client is implemented in this repository yet. After the speech pipeline is added, readiness must be extended to cover speech/AI services; its current `200` only means a call can be attempted.

### LiveKit practice transport (backend only)

Provide `LIVEKIT_URL` (a `wss://` URL), `LIVEKIT_API_KEY`, and `LIVEKIT_API_SECRET` in your untracked `.env` or runtime environment. They remain server-side; the client only receives its restricted join token. The `.env` file is not automatically loaded by uvicorn:

```sh
uv sync --group dev --extra calls
uv run --extra calls --env-file .env uvicorn app.main:app --reload
```

The transport-only bot joins the room before the start request succeeds. Rooms are removed if bot setup fails, no client joins within 60 seconds, the client disconnects, or the call reaches its 20-minute operational limit. This single-process implementation allows at most two concurrent practice calls; **do not expose anonymous provisioning publicly** without durable resource/rate limits and deployment testing. Call readiness must also be tested from the actual RunPod Pod to LiveKit Cloud (including UDP/TCP/TURN fallback), and the mobile microphone/connection flow is separate work.

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
