from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.main import create_app
from app.models import AllocationCounter, Participant, StudySession
from app.practice import PracticeConnection, PracticeUnavailable


@pytest.fixture
def engine():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    yield engine
    engine.dispose()


@pytest.fixture
def backend(engine):
    with TestClient(create_app(engine)) as client:
        yield client, engine


def test_practice_call_fails_closed_when_voice_service_is_unavailable(backend):
    client, engine = backend

    response = client.post("/v1/practice/calls", json={})
    readiness = client.get("/v1/practice/readiness")

    assert response.status_code == 503
    assert response.json() == {"detail": "Practice calls are unavailable"}
    assert readiness.status_code == 503
    with Session(engine) as db:
        assert db.scalars(select(Participant)).all() == []
        assert db.scalars(select(StudySession)).all() == []
        counter = db.get(AllocationCounter, 1)
        assert (counter.fixed_first, counter.adaptive_first) == (0, 0)


def test_anonymous_practice_call_uses_server_adaptive_and_no_study_records(engine):
    class ReadyVoiceService:
        methods = []

        async def ready(self):
            return True

        async def start(self, *, eot_method):
            self.methods.append(eot_method)
            return PracticeConnection(
                call_id=UUID("db7ea6d0-a45e-455d-9193-67a84d112f1f"),
                room_url="wss://example.livekit.cloud",
                join_token="temporary-test-token",
            )

    voice_service = ReadyVoiceService()
    with TestClient(create_app(engine, practice_starter=voice_service)) as client:
        readiness = client.get("/v1/practice/readiness")
        response = client.post("/v1/practice/calls", json={})

    assert readiness.json() == {"ready": True}
    assert response.status_code == 201
    assert response.json() == {
        "call_id": "db7ea6d0-a45e-455d-9193-67a84d112f1f",
        "room_url": "wss://example.livekit.cloud",
        "join_token": "temporary-test-token",
    }
    assert response.headers["cache-control"] == "no-store"
    assert voice_service.methods == ["adaptive"]
    with Session(engine) as db:
        assert db.scalars(select(Participant)).all() == []
        assert db.scalars(select(StudySession)).all() == []
        counter = db.get(AllocationCounter, 1)
        assert (counter.fixed_first, counter.adaptive_first) == (0, 0)


def test_client_cannot_choose_a_different_practice_method(backend):
    client, engine = backend

    for body in ({"eot_method": "fixed"}, {"method": "adaptive"}, {"study": True}):
        response = client.post("/v1/practice/calls", json=body)
        assert response.status_code == 422

    with Session(engine) as db:
        assert db.scalars(select(Participant)).all() == []
        assert db.scalars(select(StudySession)).all() == []


def test_practice_readiness_reports_unavailable_without_calling_start(engine):
    class UnavailableVoiceService:
        async def ready(self):
            return False

        async def start(self, *, eot_method):
            raise AssertionError("readiness must not create a call")

    with TestClient(create_app(engine, practice_starter=UnavailableVoiceService())) as client:
        response = client.get("/v1/practice/readiness")

    assert response.status_code == 503
    assert response.json() == {"detail": "Practice calls are unavailable"}


def test_voice_service_failure_hides_details_and_does_not_create_study_data(engine):
    class BrokenVoiceService:
        async def start(self, *, eot_method):
            raise PracticeUnavailable("private provider failure")

    with TestClient(create_app(engine, practice_starter=BrokenVoiceService())) as client:
        response = client.post("/v1/practice/calls", json={})

    assert response.status_code == 503
    assert response.json() == {"detail": "Practice calls are unavailable"}
    assert "private provider failure" not in response.text
    with Session(engine) as db:
        assert db.scalars(select(Participant)).all() == []
        assert db.scalars(select(StudySession)).all() == []


def test_practice_call_does_not_change_existing_study_progress(engine):
    class ReadyVoiceService:
        async def start(self, *, eot_method):
            return PracticeConnection(
                call_id=UUID("cc489c12-3293-4533-9483-1701e4ce8705"),
                room_url="wss://example.livekit.cloud",
                join_token="temporary-test-token",
            )

    with TestClient(create_app(engine, practice_starter=ReadyVoiceService())) as client:
        created = client.post("/v1/study/participants", json={"accepted": True}).json()
        headers = {"Authorization": f"Bearer {created['resume_token']}"}
        before = client.get("/v1/study/me", headers=headers).json()

        response = client.post("/v1/practice/calls", json={})

        assert response.status_code == 201
        assert client.get("/v1/study/me", headers=headers).json() == before

    with Session(engine) as db:
        assert len(db.scalars(select(Participant)).all()) == 1
        assert len(db.scalars(select(StudySession)).all()) == 2
        counter = db.get(AllocationCounter, 1)
        assert counter.fixed_first + counter.adaptive_first == 1
