# Repository guide

## Scope and sources

- This repository contains an AI conversation mobile app and its backend. Use `docs/PLAN.md` for feature priorities and progress, and each project's README for setup and limitations.
- Inspect current code before changing progress checkboxes. Distinguish implemented behavior from validation with actual inference, network audio, and phone playback. Keep plan updates concise; do not add implementation-evidence sections unless requested.
- Read `backend/AGENTS.md` when working in the backend. Its historical statements about missing migrations and startup table creation are outdated: deployment uses Alembic; `create_all` is limited to injected test engines. Some backend README descriptions of manual mobile token/server entry are also outdated; the mobile app enrolls participants and receives its server address at build time.
- Native iOS execution is deferred by the user. Maintain the Compose Multiplatform architecture and iOS sources, but do not treat running Xcode or an iOS device as a blocker for the current Android milestone.

## Layout and architecture

- `backend/app/`: Python 3.11–3.13, FastAPI, SQLAlchemy, study enrollment and call lifecycle, LiveKit/Pipecat transport, tutor pipeline, transcripts, and private study evidence.
- `backend/migrations/`: versioned Alembic database migrations. `backend/tests/` contains API and unit tests; `backend/scripts/` contains local utilities.
- `mobile/shared/src/commonMain/`: Compose Multiplatform UI, application state, Ktor API, Room persistence, and platform contracts.
- `mobile/shared/src/androidMain/`: Android LiveKit adapter, microphone permissions, and Keystore-backed credentials. `mobile/androidApp/` is the Android host.
- `mobile/shared/src/iosMain/` and `mobile/iosApp/`: Kotlin and Swift host/LiveKit/Keychain integration.
- `mobile/shared/src/commonTest/` and `androidHostTest/`: shared logic and Robolectric host tests. `mobile/licenses/` contains bundled asset licenses.
- Mobile calls FastAPI over HTTPS for enrollment, progress, call credentials, ending calls, and transcripts. Mobile and the Pipecat tutor each join the same LiveKit room for WebRTC audio. Do not introduce direct mobile-to-RunPod UDP media transport.
- The backend prepares the tutor and joins LiveKit when a call is requested, before returning room-scoped credentials. Starting the API alone does not establish a tutor call.

## Backend workflow

Run commands from `backend/`:

```sh
uv sync --group dev
docker compose up -d postgres
# Configure the ignored .env using .env.example first.
uv run --env-file .env alembic upgrade head
uv run --env-file .env uvicorn app.main:app --reload
```

- The compose database and its credentials are for local development. For an existing database created before migrations, follow the backup/schema verification and baseline instructions in `backend/README.md`; do not blindly stamp or recreate tables.
- For real calls, install `calls` and `tutor` extras, configure LiveKit and local model assets plus a self-hosted Qwen endpoint, then start with:

```sh
uv sync --group dev --extra calls --extra tutor
uv run --extra calls --extra tutor --env-file .env uvicorn app.main:app --reload
```

- `uvicorn` does not automatically load `.env`; load it explicitly or supply environment variables.
- Run relevant tests and lint for backend changes: `uv run pytest -q` and `uv run ruff check .`. Ruff uses a 100-character line limit and E/F/I rules.
- `TEST_DATABASE_URL` must point to a disposable PostgreSQL database: the concurrent allocation test drops its tables. Never use production or the normal development database for that test.
- Keep deployment to one API process until call ownership and restart reconciliation support multiple processes. Readiness checks and mocked tests do not validate real speech inference or audible playback.

## Mobile workflow

Run commands from `mobile/`, using the checked-in Gradle wrapper:

```sh
./gradlew :shared:testAndroidHostTest :androidApp:lintRelease :androidApp:assembleDebug
```

- Host tests use Robolectric and do not require an emulator. Choose checks appropriate to the changes; documentation-only changes do not require rebuilding the app.
- Set the control API address with `-PconversationServerUrl=...` or `CONVERSATION_SERVER_URL`. It is embedded at build time; Settings has no server/token input. Release connections require HTTPS; local development builds allow HTTP.
- For a USB-connected Android phone and a backend running locally on port 8000:

```sh
adb reverse tcp:8000 tcp:8000
./gradlew :androidApp:assembleDebug -PconversationServerUrl=http://127.0.0.1:8000
```

- For deployment, use `:androidApp:assembleRelease -PconversationServerUrl=https://your-backend.example`. Signed releases require the local, ignored signing files; preserve the signing identity for updates.
- If memory is limited, use `--max-workers=1 --no-daemon '-Dorg.gradle.jvmargs=-Xmx2048m -Dfile.encoding=UTF-8' -Pkotlin.compiler.execution.strategy=in-process`.
- Shared Kotlin iOS compilation can be checked with `:shared:compileKotlinIosArm64` and `:shared:compileKotlinIosSimulatorArm64`. Swift/Xcode builds and simulator tests require macOS; report their status separately.
- Keep reusable UI and orchestration in shared code and native permissions/media/secure storage in platform adapters. Preserve offline font/icon assets and their licenses.

## Study and data boundaries

- Anonymous practice uses adaptive end-of-turn behavior and must not create study participants, sessions, evidence recordings, or research export data.
- Study enrollment requires accepted consent. Never log resume tokens or use participant IDs as credentials. Keep fixed/adaptive assignments out of participant-facing responses and labels.
- Study sessions use server-assigned methods. Session 2 opens only after Session 1 is valid; completion requires a normal ending, at least 120 seconds of server-received microphone audio, and finalized durable evidence. A client timer or end request cannot prove completion.
- Call start/retry idempotency is separate from enrollment idempotency. Do not claim enrollment retries are safe merely because the client disables repeated taps.
- Study calls require an absolute private `STUDY_EVIDENCE_DIR` with mode 700 and explicitly configured `STUDY_RETENTION_DAYS`. Do not invent an approved retention period. On deployment, use persistent storage outside HTTP-served paths.
- Keep user and tutor audio separate from each other and from database metadata. Audio subscription telemetry and server-output audio are not proof of when sound was heard on the phone.
- Consent wording/version and retention/privacy policy need approval before real participant use. Deleting local history does not delete server research evidence; current evidence retention cleanup does not delete database metadata.

## Git hygiene

- Commit source, build configuration, the Gradle wrapper, required assets, licenses, tests, and documentation. Respect project `.gitignore` files.
- Never commit `.env`, real credentials or tokens, signing keys/passwords, `local.properties`, recordings, model caches, APK/AAB files, build/cache directories, or the ignored `mobile/deliverables/` archive.
- Inspect staged paths and content before committing; use `git diff --cached --check`. Preserve unrelated user edits and do not force-add ignored files.
- Follow existing commit subjects: `feat: ...`, `fix: ...`, or `docs: ...`, with a concise English description. Commit or push only within the user's requested scope.
