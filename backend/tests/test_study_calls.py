from datetime import timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.main import create_app
from app.models import StudyAttempt, StudySession
from app.practice import PracticeConnection
from app.study_calls import connected, disconnected, evidence_saved, finish, now


class FakeStudyStarter:
    def __init__(self):
        self.started = []

    async def start(self, *, attempt_id, method):
        self.started.append((attempt_id, method))
        return PracticeConnection(attempt_id, "wss://example.livekit.cloud", "short-lived-token")

    async def reconnect(self, *, attempt_id):
        return PracticeConnection(attempt_id, "wss://example.livekit.cloud", "fresh-token")


@pytest.fixture
def study():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    starter = FakeStudyStarter()
    with TestClient(create_app(engine, study_starter=starter)) as client:
        enrollment = client.post("/v1/study/participants", json={"accepted": True}).json()
        auth = {"Authorization": f"Bearer {enrollment['resume_token']}"}
        yield client, engine, starter, auth
    engine.dispose()


def start(client, auth, ordinal=1, key="attempt-key-0001"):
    return client.post(
        f"/v1/study/sessions/{ordinal}/calls",
        headers={**auth, "Idempotency-Key": key},
        json={},
    )


def test_study_call_is_authorized_and_session_two_is_locked(study):
    client, engine, starter, auth = study
    assert start(client, {}, 1).status_code == 401
    assert start(client, auth, 2).status_code == 409
    assert start(client, auth, 1, "short").status_code == 400
    assert client.post(
        "/v1/study/sessions/1/calls",
        headers={**auth, "Idempotency-Key": "attempt-key-0001"},
        json={"method": "fixed"},
    ).status_code == 422
    response = start(client, auth)
    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store"
    assert "method" not in response.text
    assert client.get("/v1/study/me", headers=auth).json()["sessions"] == [
        {"ordinal": 1, "status": "pending", "available": False},
        {"ordinal": 2, "status": "pending", "available": False},
    ]
    with Session(engine) as db:
        session = db.scalar(select(StudySession).where(StudySession.ordinal == 1))
        assert session is not None
        assert starter.started == [(UUID(response.json()["call_id"]), session.method)]
        assert len(db.scalars(select(StudyAttempt)).all()) == 1


def test_duplicate_start_does_not_create_another_attempt(study):
    client, engine, starter, auth = study
    first = start(client, auth)
    repeated = start(client, auth)
    assert repeated.status_code == 201
    assert repeated.json()["call_id"] == first.json()["call_id"]
    assert repeated.json()["join_token"] == "fresh-token"
    assert start(client, auth, key="different-key-0002").status_code == 409
    assert len(starter.started) == 1
    with Session(engine) as db:
        assert len(db.scalars(select(StudyAttempt)).all()) == 1


def test_failed_attempt_can_retry_same_session_but_not_same_request(study):
    client, engine, starter, auth = study
    first = start(client, auth).json()["call_id"]
    with Session(engine) as db:
        connected(db, UUID(first), now())
        finish(db, UUID(first), "disconnected", now() + timedelta(seconds=130))
    assert start(client, auth).status_code == 409
    second = start(client, auth, key="attempt-key-0002")
    assert second.status_code == 201
    assert second.json()["call_id"] != first
    assert starter.started[0][1] == starter.started[1][1]
    with Session(engine) as db:
        attempts = db.scalars(select(StudyAttempt).order_by(StudyAttempt.started_at)).all()
        assert [a.status for a in attempts] == ["failed", "active"]


def test_duration_excludes_disconnections_and_evidence_is_required(study):
    client, engine, _, auth = study
    call = UUID(start(client, auth).json()["call_id"])
    t = now()
    with Session(engine) as db:
        connected(db, call, t)
        disconnected(db, call, t + timedelta(seconds=70))
        connected(db, call, t + timedelta(seconds=100))
        finish(db, call, "normal", t + timedelta(seconds=149))
        attempt = db.get(StudyAttempt, call)
        assert attempt is not None
        assert attempt.media_ms == 119_000
    assert client.get("/v1/study/me", headers=auth).json()["sessions"][1]["available"] is False

    second = UUID(start(client, auth, key="attempt-key-0002").json()["call_id"])
    with Session(engine) as db:
        connected(db, second, t)
        finish(db, second, "normal", t + timedelta(seconds=121))
        attempt = db.get(StudyAttempt, second)
        assert attempt is not None
        assert attempt.status == "awaiting_evidence"
        assert start(client, auth, key="attempt-key-0003").status_code == 409
        attempt.ended_at = now() - timedelta(minutes=22)
        db.commit()
    third = UUID(start(client, auth, key="attempt-key-0003").json()["call_id"])
    with Session(engine) as db:
        connected(db, third, t)
        finish(db, third, "normal", t + timedelta(seconds=120))
        attempt = db.get(StudyAttempt, third)
        assert attempt is not None
        assert attempt.status == "awaiting_evidence"
        assert start(client, auth, key="attempt-key-0004").status_code == 409
        evidence_saved(db, third)
        finish(db, third, "normal")
    assert client.get("/v1/study/me", headers=auth).json()["sessions"] == [
        {"ordinal": 1, "status": "completed", "available": False},
        {"ordinal": 2, "status": "pending", "available": True},
    ]
    assert start(client, auth, key="attempt-key-0004").status_code == 409
    second_session = UUID(start(client, auth, 2, "second-session-01").json()["call_id"])
    with Session(engine) as db:
        connected(db, second_session, t)
        finish(db, second_session, "normal", t + timedelta(seconds=120))
        evidence_saved(db, second_session)
    assert all(
        s["status"] == "completed"
        for s in client.get("/v1/study/me", headers=auth).json()["sessions"]
    )
    assert start(client, auth, 2, "second-session-02").status_code == 409


def test_unconfigured_study_calls_fail_closed_without_attempts():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with TestClient(create_app(engine)) as client:
        enrollment = client.post("/v1/study/participants", json={"accepted": True}).json()
        auth = {"Authorization": f"Bearer {enrollment['resume_token']}"}
        assert start(client, auth).status_code == 503
        with Session(engine) as db:
            assert db.scalars(select(StudyAttempt)).all() == []
    engine.dispose()


def test_setup_failure_is_recorded_and_retry_uses_new_key(study):
    client, engine, starter, auth = study

    async def unavailable(*, attempt_id, method):
        raise RuntimeError("internal provider details")

    starter.start = unavailable
    failed = start(client, auth)
    assert failed.status_code == 503
    assert "internal provider details" not in failed.text
    with Session(engine) as db:
        attempt = db.scalar(select(StudyAttempt))
        assert attempt is not None
        assert attempt.status == "failed"
        assert attempt.end_reason == "setup_failed"
        assert attempt.ended_at is not None
    assert start(client, auth).status_code == 409
    starter.start = FakeStudyStarter().start
    assert start(client, auth, key="new-key-after-failure").status_code == 201


def test_abandoned_call_is_failed_before_next_reservation(study):
    client, engine, _, auth = study
    old = UUID(start(client, auth).json()["call_id"])
    with Session(engine) as db:
        attempt = db.get(StudyAttempt, old)
        assert attempt is not None
        attempt.started_at = now() - timedelta(minutes=22)
        db.commit()
    retry = start(client, auth, key="retry-after-restart")
    assert retry.status_code == 201
    with Session(engine) as db:
        attempt = db.get(StudyAttempt, old)
        assert attempt is not None
        assert attempt.status == "failed"
        assert attempt.end_reason == "interrupted"
