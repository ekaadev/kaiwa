import asyncio
import json
import os
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from enrollment import enroll_request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.evidence import EvidenceStore
from app.livekit_study import ActiveStudyCall, LiveKitStudyStarter
from app.main import create_app
from app.models import Base, StudyAttempt, StudyEvidence, StudySession
from app.practice import PracticeConnection, PracticeReadiness
from app.study_calls import MIN_MEDIA_MS
from app.transcripts import TranscriptRegistry


def update(role, text):
    return SimpleNamespace(messages=[SimpleNamespace(role=role, content=text, timestamp="")])


def audio():
    return SimpleNamespace(audio=b"\0\0" * 320, sample_rate=16000, num_channels=1)


def test_evidence_records_separate_tracks_and_integrity_checked_transcript(tmp_path):
    store = EvidenceStore(tmp_path, 7)
    call_id = uuid4()
    writer = store.begin(call_id)
    registry = TranscriptRegistry()
    log = registry.create(call_id, writer)

    async def record():
        await writer.frame("user", audio())
        await writer.frame("assistant", audio())
        await log.update(None, update("user", "こんにちは"))
        await log.update(None, update("assistant", "こんにちは。"))
        await writer.event({"type": "interruption"})
        return await writer.finalize("normal", MIN_MEDIA_MS)

    assert len(asyncio.run(record())) == 64
    with pytest.raises(RuntimeError, match="manifest integrity"):
        store.transcript(call_id, "0" * 64)
    result = store.transcript(call_id)
    assert [t["role"] for t in result["turns"]] == ["user", "assistant"]
    manifest = json.loads((tmp_path / str(call_id) / "manifest.json").read_text())
    assert set(manifest["files"]) == {"user.wav", "assistant.wav", "events.jsonl"}
    assert manifest["media_ms"] == MIN_MEDIA_MS
    with (tmp_path / str(call_id) / "events.jsonl").open("ab") as output:
        output.write(b"tampered")
    with pytest.raises(RuntimeError, match="integrity"):
        store.transcript(call_id)


def test_missing_audio_cannot_finalize_and_retention_removes_private_files(tmp_path):
    store = EvidenceStore(tmp_path, 1)
    writer = store.begin(uuid4())
    with pytest.raises(RuntimeError, match="missing"):
        asyncio.run(writer.finalize("normal", MIN_MEDIA_MS))
    assert not (writer.directory / "manifest.json").exists()
    os.utime(writer.directory, (0, 0))
    store.cleanup()
    assert not writer.directory.exists()
    with pytest.raises(ValueError):
        EvidenceStore(tmp_path, 0)


def test_practice_transcript_requires_capability_and_never_creates_study_records():
    registry = TranscriptRegistry()
    call_id = uuid4()
    log = registry.create(call_id)
    asyncio.run(log.update(None, update("user", "Real turn")))

    class Starter:
        transcripts = registry

        async def ready(self):
            return PracticeReadiness()

        async def start(self, **kwargs):
            return PracticeConnection(call_id, "wss://livekit", "join", log.token)

        async def end(self, call_id):
            log.finish()
            return True

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    with TestClient(create_app(engine, practice_starter=Starter())) as client:
        started = client.post("/v1/practice/calls", json={}).json()
        assert started["transcript_token"] == log.token
        path = f"/v1/practice/calls/{call_id}/transcript"
        assert client.get(path).status_code == 401
        assert client.get(path, headers={"Authorization": "Bearer wrong"}).status_code == 401
        auth = {"Authorization": f"Bearer {log.token}"}
        response = client.get(path, headers=auth)
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["turns"][0]["text"] == "Real turn"
        assert client.get(path + "?after=1", headers=auth).json()["turns"] == []
        assert client.post(f"/v1/practice/calls/{call_id}/end", headers=auth).status_code == 204
        assert client.get(path, headers=auth).json()["finalized"] is True
        with Session(engine) as db:
            assert db.scalars(select(StudySession)).all() == []
            assert db.scalars(select(StudyEvidence)).all() == []
        log.ended_at -= timedelta(minutes=31)
        assert client.get(path, headers=auth).status_code == 401


@pytest.mark.parametrize("failure", [False, True])
def test_normal_study_end_unlocks_second_only_after_durable_evidence(
    tmp_path, monkeypatch, failure
):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    sessions = sessionmaker(engine)

    class Tutor:
        async def ready(self):
            return True

    class Gateway:
        url = "wss://livekit"

        async def create_room(self, name):
            pass

        async def delete_room(self, name):
            pass

        def join_token(self, name, **kwargs):
            return "scoped"

    async def bot(url, token, room, ready, **kwargs):
        ready.set()
        log = kwargs["transcript"]
        await log.evidence.frame("user", audio())
        await log.evidence.frame("assistant", audio())
        await log.update(None, update("user", "Hello"))
        await asyncio.Event().wait()

    monkeypatch.setattr("app.livekit_study.run_transport_bot", bot)
    store = EvidenceStore(tmp_path, 7)
    if failure:

        def disk_full(*args):
            raise OSError("Storage full")

        monkeypatch.setattr("app.evidence.EvidenceWriter._finalize", disk_full)
    starter = LiveKitStudyStarter(Gateway(), Tutor(), sessions, evidence_store=store)
    with TestClient(create_app(engine, study_starter=starter)) as client:
        person = enroll_request(client).json()
        auth = {"Authorization": f"Bearer {person['resume_token']}"}
        started = client.post(
            "/v1/study/sessions/1/calls",
            json={},
            headers={**auth, "Idempotency-Key": "unique-attempt-key"},
        )
        from uuid import UUID

        call_id = UUID(started.json()["call_id"])
        with sessions() as db:
            attempt = db.get(StudyAttempt, call_id)
            attempt.media_ms = MIN_MEDIA_MS
            db.commit()
        other = enroll_request(client).json()
        other_auth = {"Authorization": f"Bearer {other['resume_token']}"}
        assert (
            client.get(f"/v1/study/calls/{call_id}/transcript", headers=other_auth).status_code
            == 404
        )
        event_path = f"/v1/study/calls/{call_id}/events"
        event = {
            "event": "remote_audio_subscribed",
            "client_sequence": 1,
            "client_timestamp_ms": 1000,
        }
        assert client.post(event_path, json=event, headers=other_auth).status_code == 404
        assert (
            client.post(event_path, json={**event, "media_ms": 999999}, headers=auth).status_code
            == 422
        )
        assert client.post(event_path, json=event, headers=auth).status_code == 204
        assert client.post(event_path, json=event, headers=auth).status_code == 204
        assert client.post(f"/v1/study/calls/{call_id}/end", headers=auth).status_code == 204
        result = client.get("/v1/study/me", headers=auth).json()
        if failure:
            assert result["sessions"][0]["status"] == "pending"
            assert result["sessions"][1]["available"] is False
            with sessions() as db:
                assert db.get(StudyEvidence, call_id) is None
                assert db.get(StudyAttempt, call_id).status == "awaiting_evidence"
            return
        assert result["sessions"][0]["status"] == "completed"
        assert result["sessions"][1]["available"] is True
        with sessions() as db:
            assert db.get(StudyEvidence, call_id) is not None
        # After memory cleanup, the same owner can retrieve the durable transcript.
        starter.transcripts.calls.clear()
        response = client.get(f"/v1/study/calls/{call_id}/transcript", headers=auth)
        assert response.json()["turns"][0]["text"] == "Hello"


def test_expired_pending_evidence_is_available_for_a_fresh_attempt():
    from app.study_calls import STALE_AFTER, now

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    with TestClient(create_app(engine)) as client:
        person = enroll_request(client).json()
        auth = {"Authorization": f"Bearer {person['resume_token']}"}
        with Session(engine) as db:
            session_id = db.scalar(select(StudySession.id).where(StudySession.ordinal == 1))
            db.add(
                StudyAttempt(
                    session_id=session_id,
                    request_hash="a" * 64,
                    status="awaiting_evidence",
                    started_at=now() - STALE_AFTER,
                    ended_at=now() - STALE_AFTER,
                    media_ms=MIN_MEDIA_MS,
                )
            )
            db.commit()
        sessions = client.get("/v1/study/me", headers=auth).json()["sessions"]
        assert sessions[0]["available"] is True
        assert sessions[0]["status"] == "pending"
        assert sessions[1]["available"] is False


def test_missing_study_attempt_closes_capture_without_registering_evidence(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    deleted_rooms = []

    class Gateway:
        url = "wss://livekit"

        async def delete_room(self, name):
            deleted_rooms.append(name)

    async def bot(url, token, room, ready, **kwargs):
        writer = kwargs["transcript"].evidence
        await writer.frame("user", audio())
        await writer.frame("assistant", audio())

    monkeypatch.setattr("app.livekit_study.run_transport_bot", bot)
    starter = LiveKitStudyStarter(Gateway(), None, sessions)
    call_id = uuid4()
    writer = EvidenceStore(tmp_path, 7).begin(call_id)
    log = starter.transcripts.create(call_id, writer)
    call = ActiveStudyCall("missing-attempt-room", ready=True, ending_normally=True)
    starter._active[call_id] = call

    asyncio.run(starter._run(call_id, call, "scoped", asyncio.Event(), "adaptive"))

    assert writer.closed is True
    assert writer.events.closed is True
    assert log.ended_at is not None
    assert call_id not in starter._active
    assert deleted_rooms == [call.room]
    manifest = json.loads((writer.directory / "manifest.json").read_text())
    assert manifest["reason"] == "setup_failed"
    assert manifest["media_ms"] == 0
    with sessions() as db:
        assert db.scalars(select(StudyEvidence)).all() == []
