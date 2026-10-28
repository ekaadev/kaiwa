import uuid
from collections import Counter
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.main import create_app
from app.models import Participant, StudyAttempt, StudySession
from app.practice import PracticeConnection
from app.study_calls import connected, disconnected, evidence_saved, finish, now
from app.uat import build_plan

ADMIN = {"Authorization": "Bearer admin-secret"}


class FakeStarter:
    def __init__(self):
        self.started = []

    async def start(self, *, attempt_id, method):
        self.started.append((attempt_id, method))
        return PracticeConnection(attempt_id, "wss://example.livekit.cloud", "short-lived-token")

    async def reconnect(self, *, attempt_id):
        return PracticeConnection(attempt_id, "wss://example.livekit.cloud", "fresh-token")


@pytest.fixture
def uat(monkeypatch):
    monkeypatch.setenv("UAT_ADMIN_TOKEN", "admin-secret")
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    starter = FakeStarter()
    with TestClient(create_app(engine, study_starter=starter)) as client:
        run = client.post(
            "/v1/uat/runs",
            json={"pilot": True},
            headers={**ADMIN, "Idempotency-Key": uuid.uuid4().hex},
        ).json()
        auth = {"Authorization": f"Bearer {run['resume_token']}"}
        yield client, engine, starter, auth, run
    engine.dispose()


def call(client, auth, ordinal, key):
    return client.post(
        f"/v1/uat/trials/{ordinal}/calls", headers={**auth, "Idempotency-Key": key}, json={}
    )


def complete_call(engine, attempt_id, media_ms=60_000):
    """Simulate trusted transport code: connected, media received, normal end, evidence saved."""
    with Session(engine) as db:
        attempt = db.get(StudyAttempt, attempt_id)
        attempt.status = "active"
        db.commit()
        connected(db, attempt_id)
        disconnected(db, attempt_id, received_ms=media_ms)
        finish(db, attempt_id, "normal")
        evidence_saved(db, attempt_id)


RATING = {"ratings": [3, 4, 2, 5], "labels": {"2": "Cut off", "4": "Fine"}}


def run_trial(client, engine, auth, ordinal, key):
    started = call(client, auth, ordinal, key)
    assert started.status_code == 201, started.text
    complete_call(engine, uuid.UUID(started.json()["call_id"]))
    saved = client.put(f"/v1/uat/trials/{ordinal}/rating", headers=auth, json=RATING)
    assert saved.status_code == 204, saved.text


def test_plan_is_balanced_counterbalanced_and_seeded():
    plan = build_plan(123)
    assert plan == build_plan(123)
    assert len(plan) == 24
    pairs = {}
    for t in plan:
        pairs.setdefault((t["test_session"], t["scenario"]), []).append(t)
    assert len(pairs) == 12
    firsts = Counter(p[0]["version"] for p in pairs.values())
    assert firsts == {"A": 6, "B": 6}
    adaptive_a = 0
    for pair in pairs.values():
        assert sorted(t["version"] for t in pair) == ["A", "B"]
        assert {t["method"] for t in pair} == {"fixed", "adaptive"}
        adaptive_a += next(t for t in pair if t["version"] == "A")["method"] == "adaptive"
    assert adaptive_a == 6


def test_run_creation_needs_admin_token_and_never_exposes_the_method(uat, monkeypatch):
    client, engine, _, auth, run = uat
    assert "method" not in str(run) and "seed" not in str(run) and "order" not in str(run)
    assert run["label"] == "EXP-01" and run["pilot"] is True and len(run["trials"]) == 24
    key = {"Idempotency-Key": uuid.uuid4().hex}
    assert client.post("/v1/uat/runs", json={}, headers=key).status_code == 401
    wrong = {**key, "Authorization": "Bearer no"}
    assert client.post("/v1/uat/runs", json={}, headers=wrong).status_code == 401
    replay = client.post("/v1/uat/runs", json={"pilot": False}, headers={**ADMIN, **key})
    again = client.post("/v1/uat/runs", json={"pilot": False}, headers={**ADMIN, **key})
    assert replay.json()["resume_token"] == again.json()["resume_token"]
    me = client.get("/v1/uat/me", headers=auth)
    assert me.status_code == 200 and "method" not in me.text and "resume_token" not in me.text
    assert client.get("/v1/uat/me").status_code == 401
    # A study participant token does not open UAT and vice versa.
    assert client.get("/v1/study/me", headers=auth).status_code == 404
    monkeypatch.delenv("UAT_ADMIN_TOKEN")
    assert client.post("/v1/uat/runs", json={}, headers={**ADMIN, **key}).status_code == 404


def test_trial_call_uses_the_planned_method_and_runs_in_order(uat):
    client, engine, starter, auth, run = uat
    assert call(client, auth, 2, "attempt-key-0002").status_code == 409
    assert call(client, auth, 1, "short").status_code == 400
    first = call(client, auth, 1, "attempt-key-0001")
    assert first.status_code == 201
    with Session(engine) as db:
        planned = db.scalar(select(StudySession).where(StudySession.ordinal == 1)).method
    assert starter.started[0][1] == planned
    assert call(client, auth, 1, "attempt-key-0001").status_code == 201  # idempotent replay
    assert len(starter.started) == 1
    assert call(client, auth, 1, "attempt-key-0009").status_code == 409  # call in progress
    # Rating before the call ends is refused.
    assert client.put("/v1/uat/trials/1/rating", headers=auth, json=RATING).status_code == 409


def test_short_call_can_be_retried_with_the_same_version_and_method(uat):
    client, engine, starter, auth, run = uat
    first = call(client, auth, 1, "attempt-key-0001").json()["call_id"]
    complete_call(engine, uuid.UUID(first), media_ms=2_000)  # below the UAT minimum
    trial = client.get("/v1/uat/me", headers=auth).json()["trials"][0]
    assert trial["status"] == "pending" and trial["available"] is True
    assert call(client, auth, 1, "attempt-key-0002").status_code == 201
    assert starter.started[0][1] == starter.started[1][1]


def test_rating_redo_and_pair_preference_flow(uat):
    client, engine, starter, auth, run = uat
    letters = [t["version"] for t in run["trials"][:2]]
    assert sorted(letters) == ["A", "B"]
    run_trial(client, engine, auth, 1, "attempt-key-0001")
    trial = client.get("/v1/uat/me", headers=auth).json()["trials"][0]
    assert trial["status"] == "rated" and trial["ratings"] == [3, 4, 2, 5]
    # Redo voids the attempt, keeps the version, and re-opens the trial.
    assert client.post("/v1/uat/trials/1/redo", headers=auth).status_code == 204
    after = client.get("/v1/uat/me", headers=auth).json()["trials"][0]
    assert after["status"] == "pending" and after["version"] == trial["version"]
    run_trial(client, engine, auth, 1, "attempt-key-0002")
    with Session(engine) as db:
        attempts = db.scalars(select(StudyAttempt)).all()
        assert sorted(a.void for a in attempts) == [False, True]
    # Preference needs both trials of the pair.
    pref = {"test_session": 1, "scenario": 0, "choice": "A"}
    assert client.put("/v1/uat/preferences", headers=auth, json=pref).status_code == 409
    run_trial(client, engine, auth, 2, "attempt-key-0003")
    assert client.put("/v1/uat/preferences", headers=auth, json=pref).status_code == 204
    flip = client.put("/v1/uat/preferences", headers=auth, json={**pref, "choice": "B"})
    assert flip.status_code == 204
    me = client.get("/v1/uat/me", headers=auth).json()
    assert me["preferences"] == [{"test_session": 1, "scenario": 0, "choice": "B"}]
    assert [t["available"] for t in me["trials"][:3]] == [False, False, True]


def test_rating_validation_and_skip(uat):
    client, engine, starter, auth, run = uat
    short = client.put("/v1/uat/trials/1/rating", headers=auth, json={"ratings": [1, 2, 3]})
    assert short.status_code == 422
    started = call(client, auth, 1, "attempt-key-0001").json()["call_id"]
    complete_call(engine, uuid.UUID(started))
    bad = client.put("/v1/uat/trials/1/rating", headers=auth, json={"ratings": [0, 2, 3, 4]})
    assert bad.status_code == 409
    unknown = client.put(
        "/v1/uat/trials/1/rating",
        headers=auth,
        json={"ratings": [1, 2, 3, 4], "labels": {"2": "Bad"}},
    )
    assert unknown.status_code == 422
    assert client.post("/v1/uat/trials/1/skip", headers=auth).status_code == 409
    assert client.post("/v1/uat/trials/2/skip", headers=auth).status_code == 409  # order
    assert client.post("/v1/uat/trials/1/redo", headers=auth).status_code == 204
    assert client.post("/v1/uat/trials/1/skip", headers=auth).status_code == 204
    assert client.get("/v1/uat/me", headers=auth).json()["trials"][0]["status"] == "skipped"


def test_stale_live_call_is_interrupted_when_the_expert_retries(uat):
    client, engine, starter, auth, run = uat
    first = call(client, auth, 1, "attempt-key-0001").json()["call_id"]
    with Session(engine) as db:
        attempt = db.get(StudyAttempt, uuid.UUID(first))
        attempt.started_at = now() - timedelta(minutes=30)
        db.commit()
    assert call(client, auth, 1, "attempt-key-0002").status_code == 201


def test_export_includes_the_method_only_for_the_admin(uat):
    client, engine, starter, auth, run = uat
    run_trial(client, engine, auth, 1, "attempt-key-0001")
    assert client.get("/v1/uat/export.csv", headers=auth).status_code == 401
    csv_text = client.get("/v1/uat/export.csv", headers=ADMIN).text
    header, *rows = csv_text.strip().splitlines()
    assert "method" in header.split(",")
    with Session(engine) as db:
        method = db.scalar(select(StudySession).where(StudySession.ordinal == 1)).method
        assert db.scalar(select(Participant).where(Participant.kind == "uat")) is not None
    assert method in rows[0] and "EXP-01" in rows[0]


def test_open_enrollment_creates_runs_without_a_code_but_export_stays_protected(uat, monkeypatch):
    client, engine, _, auth, run = uat
    key = {"Idempotency-Key": uuid.uuid4().hex}
    assert client.post("/v1/uat/runs", json={}, headers=key).status_code == 401
    monkeypatch.setenv("UAT_OPEN_ENROLLMENT", "1")
    opened = client.post("/v1/uat/runs", json={"pilot": False}, headers=key)
    assert opened.status_code == 201 and opened.json()["label"] == "EXP-02"
    assert "method" not in opened.text
    assert client.get("/v1/uat/export.csv").status_code == 401


def test_exiting_a_run_keeps_its_data_and_blocks_further_trials(uat):
    client, engine, starter, auth, run = uat
    run_trial(client, engine, auth, 1, "attempt-key-0001")
    live = call(client, auth, 2, "attempt-key-0002")
    assert live.status_code == 201
    assert client.post("/v1/uat/abandon", headers=auth).status_code == 409  # call in progress
    complete_call(engine, uuid.UUID(live.json()["call_id"]), media_ms=1_000)
    assert client.post("/v1/uat/abandon", headers=auth).status_code == 204
    assert client.post("/v1/uat/abandon", headers=auth).status_code == 204  # idempotent
    me = client.get("/v1/uat/me", headers=auth).json()
    assert me["abandoned"] is True and me["trials"][0]["status"] == "rated"
    assert call(client, auth, 2, "attempt-key-0003").status_code == 409
    assert client.post("/v1/uat/trials/2/skip", headers=auth).status_code == 409
    rows = client.get("/v1/uat/export.csv", headers=ADMIN).text.strip().splitlines()
    header = rows[0].split(",")
    assert {"pilot", "run_status"} <= set(header)
    assert "abandoned" in rows[1] and "True" in rows[1]
