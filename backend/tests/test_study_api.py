from collections import Counter

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.main import create_app
from app.models import Participant, StudySession


@pytest.fixture
def backend():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with TestClient(create_app(engine)) as client:
        yield client, engine
    engine.dispose()


def test_refusing_consent_creates_no_participant(backend):
    client, engine = backend
    response = client.post("/v1/study/participants", json={"accepted": False})
    assert response.status_code == 422
    with Session(engine) as db:
        assert db.scalars(select(Participant)).all() == []


def test_enrollment_is_anonymous_and_resume_requires_token(backend):
    client, _ = backend
    created = client.post("/v1/study/participants", json={"accepted": True})
    assert created.status_code == 201
    body = created.json()
    assert set(body) == {"participant_id", "resume_token", "sessions"}
    assert len(body["resume_token"]) >= 40
    assert body["sessions"] == [
        {"ordinal": 1, "status": "pending", "available": True},
        {"ordinal": 2, "status": "pending", "available": False},
    ]
    assert "method" not in created.text and "order" not in created.text
    assert client.get("/v1/study/me").status_code == 401
    assert client.get("/v1/study/me", headers={"Authorization": "Bearer wrong"}).status_code == 401
    resumed = client.get(
        "/v1/study/me", headers={"Authorization": f"Bearer {body['resume_token']}"}
    )
    assert resumed.status_code == 200
    assert resumed.json()["participant_id"] == body["participant_id"]
    assert "resume_token" not in resumed.json()


def test_conditions_balanced_and_fixed_per_participant(backend):
    client, engine = backend
    ids = [
        client.post("/v1/study/participants", json={"accepted": True}).json()["participant_id"]
        for _ in range(8)
    ]
    with Session(engine) as db:
        participants = db.scalars(select(Participant)).all()
        counts = Counter(participant.order for participant in participants)
        assert counts == {"AB": 4, "BA": 4}
        for participant in participants:
            sessions = db.scalars(
                select(StudySession)
                .where(StudySession.participant_id == participant.id)
                .order_by(StudySession.ordinal)
            ).all()
            assert [session.method for session in sessions] in [
                ["fixed", "adaptive"],
                ["adaptive", "fixed"],
            ]
            assert [session.status for session in sessions] == ["pending", "pending"]
    assert len(set(ids)) == 8


def test_health_checks_database(backend):
    client, _ = backend
    assert client.get("/health").json() == {"status": "ok"}
