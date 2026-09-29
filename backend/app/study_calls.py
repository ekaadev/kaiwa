"""Durable study attempt rules. Only trusted transport code may report media events."""

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import StudyAttempt, StudySession
from app.practice import PracticeConnection

MIN_MEDIA_MS = 120_000
STALE_AFTER = timedelta(minutes=21)


class StudyCallStarter(Protocol):
    async def start(self, *, attempt_id: UUID, method: str) -> PracticeConnection: ...

    async def reconnect(self, *, attempt_id: UUID) -> PracticeConnection: ...

    async def end(self, *, attempt_id: UUID) -> bool: ...


class StudyCallConflict(Exception):
    pass


def now() -> datetime:
    return datetime.now(timezone.utc)


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def reserve(db: Session, participant_id: UUID, ordinal: int, key: str) -> tuple[StudyAttempt, bool]:
    """Lock the study row so concurrent requests cannot open two calls for one participant."""
    sessions = db.scalars(
        select(StudySession)
        .where(StudySession.participant_id == participant_id)
        .order_by(StudySession.ordinal)
        .with_for_update()
    ).all()
    if ordinal not in (1, 2) or len(sessions) != 2:
        raise StudyCallConflict("Session is unavailable")
    session = sessions[ordinal - 1]
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    previous = db.scalar(
        select(StudyAttempt).where(
            StudyAttempt.session_id == session.id, StudyAttempt.request_hash == digest
        )
    )
    if previous is not None:
        return previous, False
    if session.status == "completed" or (ordinal == 2 and sessions[0].status != "completed"):
        raise StudyCallConflict("Session is unavailable")
    active = db.scalar(
        select(StudyAttempt).where(
            StudyAttempt.session_id == session.id, StudyAttempt.status.in_(("starting", "active"))
        )
    )
    if active is None:
        active = db.scalar(
            select(StudyAttempt).where(
                StudyAttempt.session_id == session.id, StudyAttempt.status == "awaiting_evidence"
            )
        )
    if active is not None:
        if now() - utc(active.ended_at or active.started_at) < STALE_AFTER:
            raise StudyCallConflict("A call is already in progress")
        if active.status == "awaiting_evidence":
            active.status = "failed"
            db.commit()
        else:
            finish(db, active.id, "interrupted")
    attempt = StudyAttempt(session_id=session.id, request_hash=digest, started_at=now())
    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    return attempt, True


def connected(db: Session, attempt_id: UUID, at: datetime | None = None) -> None:
    attempt = db.get(StudyAttempt, attempt_id, with_for_update=True)
    if attempt is not None and attempt.status == "active" and attempt.connected_at is None:
        attempt.connected_at = at or now()
        db.commit()


def disconnected(
    db: Session, attempt_id: UUID, at: datetime | None = None, *, received_ms: int | None = None
) -> None:
    attempt = db.get(StudyAttempt, attempt_id, with_for_update=True)
    if attempt is not None and attempt.status == "active" and attempt.connected_at is not None:
        end = at or now()
        # The LiveKit adapter supplies the duration of actual received PCM frames.
        # Other trusted callers may use the connected interval when no samples are supplied.
        duration = (
            received_ms
            if received_ms is not None
            else int((end - utc(attempt.connected_at)).total_seconds() * 1000)
        )
        attempt.media_ms += max(0, duration)
        attempt.connected_at = None
        db.commit()


def evidence_saved(db: Session, attempt_id: UUID) -> None:
    """Call after final evidence is durably stored, never from a client request."""
    existing = db.get(StudyAttempt, attempt_id)
    if existing is None:
        return
    # Same lock order as reserve: session first, then attempt.
    session = db.get(StudySession, existing.session_id, with_for_update=True)
    if session is None:
        db.rollback()
        raise RuntimeError("Study attempt has no session")
    db.expire(existing)
    attempt = db.get(StudyAttempt, attempt_id, with_for_update=True)
    if attempt is not None and attempt.status == "awaiting_evidence":
        attempt.evidence_saved_at = now()
        attempt.status = "completed"
        session.status = "completed"
        db.commit()


def finish(db: Session, attempt_id: UUID, reason: str, at: datetime | None = None) -> None:
    """Idempotently close a call. A client disconnect is not a normal end."""
    attempt = db.get(StudyAttempt, attempt_id, with_for_update=True)
    if attempt is None or attempt.status not in ("starting", "active"):
        return
    end = at or now()
    if attempt.connected_at is not None:
        # Only an observed media disconnect can add duration. A termination
        # event by itself is not proof that audio continued until this instant.
        attempt.connected_at = None
    attempt.ended_at = end
    attempt.end_reason = reason
    valid_duration = reason == "normal" and attempt.media_ms >= MIN_MEDIA_MS
    attempt.status = "awaiting_evidence" if valid_duration else "failed"
    db.commit()
