# AI Conversation — backend foundation

**Scope of this first slice:** a FastAPI control API for anonymous study enrollment, balanced fixed/adaptive allocation, and read-only study resumption. The audio call, LiveKit Cloud room/token creation, Pipecat pipeline, session completion/retry, recordings, and research export are **not implemented yet**. This is not ready for real participants or production deployment.

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

The consent text/version and privacy policy must be approved **before** any real participant uses this endpoint. A user-facing study explanation and consent are not provided by this backend alone.

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
