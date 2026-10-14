import asyncio
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest
from enrollment import enroll_request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.call_capacity import CallCapacity
from app.livekit_practice import LiveKitPracticeStarter
from app.livekit_study import LiveKitStudyStarter, MediaTracker, StudyUnavailable
from app.main import create_app
from app.models import StudyAttempt, StudySession
from app.study_calls import now


class FakeGateway:
    url = "wss://study.livekit.example"

    def __init__(self):
        self.created = []
        self.deleted = []
        self.tokens = []

    async def create_room(self, room):
        self.created.append(room)

    async def delete_room(self, room):
        self.deleted.append(room)

    def join_token(self, room, *, bot):
        self.tokens.append((room, bot))
        return "bot-token" if bot else "room-scoped-client-token"


class ReadyTutor:
    async def ready(self):
        return True


def test_study_api_opens_assigned_room_and_end_keeps_session_pending(monkeypatch):
    received = []

    async def bot(
        url, token, room, ready, *, tutor, eot_method, on_audio_frame, on_audio_lost, **kwargs
    ):
        received.append((room, eot_method))
        ready.set()
        await asyncio.Event().wait()

    monkeypatch.setattr("app.livekit_study.run_transport_bot", bot)
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    gateway = FakeGateway()
    starter = LiveKitStudyStarter(gateway, ReadyTutor(), sessionmaker(engine))
    with TestClient(create_app(engine, study_starter=starter)) as client:
        enrolled = enroll_request(client).json()
        auth = {"Authorization": f"Bearer {enrolled['resume_token']}"}
        with Session(engine) as db:
            method = db.scalar(select(StudySession.method).where(StudySession.ordinal == 1))
        started = client.post(
            "/v1/study/sessions/1/calls",
            json={},
            headers={**auth, "Idempotency-Key": "study-start-request"},
        )
        assert started.status_code == 201
        call_id = UUID(started.json()["call_id"])
        room = f"study-{call_id.hex}"
        assert gateway.created == [room]
        assert gateway.tokens == [(room, True), (room, False)]
        assert received == [(room, method)]
        assert started.json()["join_token"] == "room-scoped-client-token"
        assert "method" not in started.text
        assert client.post(f"/v1/study/calls/{call_id}/end").status_code == 401
        other = enroll_request(client).json()
        other_auth = {"Authorization": f"Bearer {other['resume_token']}"}
        assert client.post(f"/v1/study/calls/{call_id}/end", headers=other_auth).status_code == 404
        assert client.post(f"/v1/study/calls/{call_id}/end", headers=auth).status_code == 204
        assert client.post(f"/v1/study/calls/{call_id}/end", headers=auth).status_code == 404
        assert gateway.deleted == [room]
        with Session(engine) as db:
            attempt = db.get(StudyAttempt, call_id)
            assert attempt is not None
            assert attempt.status == "failed"  # no microphone audio and no evidence
            assert attempt.end_reason == "normal"
        assert client.get("/v1/study/me", headers=auth).json()["sessions"][0] == {
            "ordinal": 1,
            "status": "pending",
            "available": True,
        }
        assert (
            client.post(
                "/v1/study/sessions/2/calls",
                json={},
                headers={**auth, "Idempotency-Key": "study-second-session"},
            ).status_code
            == 409
        )
    engine.dispose()


def test_practice_and_study_share_a_two_call_capacity(monkeypatch):
    async def waiting_bot(
        url, token, room, ready, *, tutor, eot_method, on_audio_frame, on_audio_lost, **kwargs
    ):
        ready.set()
        await asyncio.Event().wait()

    async def waiting_practice_bot(url, token, room, ready):
        ready.set()
        await asyncio.Event().wait()

    monkeypatch.setattr("app.livekit_study.run_transport_bot", waiting_bot)
    monkeypatch.setattr("app.livekit_practice.run_transport_bot", waiting_practice_bot)
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    gateway = FakeGateway()
    capacity = CallCapacity(limit=1)
    practice = LiveKitPracticeStarter(gateway, capacity=capacity)
    study = LiveKitStudyStarter(gateway, ReadyTutor(), sessionmaker(engine), capacity=capacity)

    async def scenario():
        call = await practice.start(eot_method="adaptive")
        assert call.call_id is not None
        assert not (await practice.ready()).ready
        with pytest.raises(StudyUnavailable):
            await study.start(
                attempt_id=UUID("bb3dabca-7052-4cd7-b705-85aaf67c9971"), method="fixed"
            )
        await practice.aclose()
        assert await capacity.available()
        next_call = await study.start(
            attempt_id=UUID("bb3dabca-7052-4cd7-b705-85aaf67c9971"), method="fixed"
        )
        assert next_call.call_id is not None
        await study.aclose()
        assert await capacity.available()

    asyncio.run(scenario())
    engine.dispose()


def test_incoming_audio_counts_frames_but_not_join_or_connection_gap(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with TestClient(create_app(engine)) as client:
        enroll_request(client)
        with Session(engine) as db:
            session = db.scalar(select(StudySession).where(StudySession.ordinal == 1))
            assert session is not None
            attempt = StudyAttempt(
                session_id=session.id,
                request_hash="a" * 64,
                status="active",
                started_at=now(),
            )
            db.add(attempt)
            db.commit()
            attempt_id = attempt.id
        origin = now()
        clock = [0.0]
        monkeypatch.setattr("app.livekit_study.now", lambda: origin + timedelta(seconds=clock[0]))
        monkeypatch.setattr("app.livekit_study.monotonic", lambda: clock[0])
        frame = SimpleNamespace(audio=b"\x00" * 320, sample_rate=16000, num_channels=1)

        async def scenario():
            tracker = MediaTracker(attempt_id, sessionmaker(engine))
            clock[0] = 10.0  # room already joined for 10 seconds
            await tracker.frame(frame)
            clock[0] = 11.0
            await tracker.frame(frame)
            clock[0] = 16.0  # lost audio; five-second gap is excluded
            await tracker.frame(frame)
            await tracker.close()
            clock[0] = 17.0
            # A single huge frame cannot claim two minutes of connected media.
            await tracker.frame(
                SimpleNamespace(audio=b"\x00" * 3_840_000, sample_rate=16000, num_channels=1)
            )
            await tracker.close()

        asyncio.run(scenario())
        with Session(engine) as db:
            saved = db.get(StudyAttempt, attempt_id)
            assert saved is not None
            assert saved.media_ms == 280
            assert saved.connected_at is None
            assert saved.status == "active"
    engine.dispose()


def test_study_setup_failure_cleans_room_and_does_not_return_credentials(monkeypatch):
    async def broken_bot(
        url, token, room, ready, *, tutor, eot_method, on_audio_frame, on_audio_lost, **kwargs
    ):
        raise RuntimeError("private model failure")

    monkeypatch.setattr("app.livekit_study.run_transport_bot", broken_bot)
    monkeypatch.setattr("app.livekit_study.BOT_JOIN_TIMEOUT_SECONDS", 0.01)
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    gateway = FakeGateway()
    starter = LiveKitStudyStarter(gateway, ReadyTutor(), sessionmaker(engine))
    with TestClient(create_app(engine, study_starter=starter)) as client:
        enrolled = enroll_request(client).json()
        response = client.post(
            "/v1/study/sessions/1/calls",
            json={},
            headers={
                "Authorization": f"Bearer {enrolled['resume_token']}",
                "Idempotency-Key": "study-failing-request",
            },
        )
        assert response.status_code == 503
        assert "private" not in response.text
        assert "token" not in response.text
        assert gateway.created == gateway.deleted
        assert all(bot for _, bot in gateway.tokens)
        with Session(engine) as db:
            attempt = db.scalar(select(StudyAttempt))
            assert attempt is not None
            assert attempt.status == "failed"
            assert attempt.end_reason == "setup_failed"
    engine.dispose()


def test_received_audio_can_await_evidence_but_cannot_complete_session(monkeypatch):
    send_audio = asyncio.Event()
    processed = asyncio.Event()
    origin = now()
    clock = [0.0]
    monkeypatch.setattr("app.livekit_study.now", lambda: origin + timedelta(seconds=clock[0]))
    monkeypatch.setattr("app.livekit_study.monotonic", lambda: clock[0])

    async def bot(
        url, token, room, ready, *, tutor, eot_method, on_audio_frame, on_audio_lost, **kwargs
    ):
        ready.set()
        await send_audio.wait()
        # Synthetic 16-bit mono PCM paced for 120 seconds, not a real WebRTC test.
        frame = SimpleNamespace(audio=b"\x00" * 8000, sample_rate=16000, num_channels=1)
        for index in range(480):
            clock[0] = index * 0.25
            await on_audio_frame(frame)
        processed.set()
        await asyncio.Event().wait()

    monkeypatch.setattr("app.livekit_study.run_transport_bot", bot)
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with TestClient(create_app(engine)) as client:
        enroll_request(client)
        with Session(engine) as db:
            session = db.scalar(select(StudySession).where(StudySession.ordinal == 1))
            assert session is not None
            attempt = StudyAttempt(
                session_id=session.id,
                request_hash="b" * 64,
                status="active",
                started_at=now(),
            )
            db.add(attempt)
            db.commit()
            attempt_id = attempt.id
        study = LiveKitStudyStarter(FakeGateway(), ReadyTutor(), sessionmaker(engine))

        async def scenario():
            await study.start(attempt_id=attempt_id, method="fixed")
            send_audio.set()
            await processed.wait()
            assert await study.end(attempt_id=attempt_id)

        asyncio.run(scenario())
        with Session(engine) as db:
            saved = db.get(StudyAttempt, attempt_id)
            assert saved is not None
            assert saved.media_ms == 120_000
            assert saved.status == "awaiting_evidence"
            session = db.get(StudySession, saved.session_id)
            assert session is not None
            assert session.status == "pending"
    engine.dispose()
