# Agent guide

## Layout and scope

- The application lives in `backend/`; run the commands below from that directory. See `backend/README.md` for setup, API behavior, and current limitations.
- This is a Python 3.11–3.13 FastAPI study control API, not a finished audio/LiveKit application or production-ready participant service. `backend/app/main.py` defines the app, database bootstrap, and routes; `backend/app/models.py` defines SQLAlchemy records; `backend/app/study.py` handles enrollment, balanced allocation, and resume-token lookup. Tests are in `backend/tests/`.
- Database tables are currently created via `Base.metadata.create_all` at startup; versioned migrations are not yet implemented.

## Local workflow

- Dependencies are specified in `backend/pyproject.toml` and locked in `backend/uv.lock`. Local setup requires `uv`, Python 3.11–3.13, and Docker for PostgreSQL.
- From `backend/`: `uv sync --group dev`; `docker compose up -d postgres`; set `DATABASE_URL` and `STUDY_CONSENT_VERSION` as shown in `backend/README.md` or `backend/.env.example`; then `uv run uvicorn app.main:app --reload`. The compose database is for local development only.
- Check changes from `backend/` with `uv run pytest -q` and `uv run ruff check .`. Pytest uses `backend/tests/`; Ruff uses a 100-character line length and E/F/I rules (see `backend/pyproject.toml`).
- Most API tests use in-memory SQLite. The concurrent PostgreSQL allocation test requires `TEST_DATABASE_URL` pointing to a **disposable** test database; it skips otherwise and **drops its own tables**. Follow `backend/README.md` to create the test database. Never point it at production or the normal development database.

## Data and security boundaries

- The enrollment API requires accepted consent and returns an opaque resume token only once. Do not log the token, treat participant IDs as credentials, or expose fixed/adaptive assignment in participant-facing responses. `GET /v1/study/me` authenticates using a bearer resume token.
- `.env` is ignored; use `backend/.env.example` as a template and do not commit real secrets. The consent text/version and privacy policy require approval before any real participants use the endpoint.
