"""Allocation and anonymous resume logic; method never leaves the participant API."""

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.models import AllocationCounter, Participant, StudySession


@dataclass(frozen=True)
class Enrollment:
    participant: Participant
    resume_token: str


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


MIN_ENROLLMENT_KEY_LENGTH = 32  # clients send a random UUID/secret, not a guessable value


def valid_enrollment_key(key: str) -> bool:
    return (
        MIN_ENROLLMENT_KEY_LENGTH <= len(key) <= 128 and key.isascii() and key.isprintable()
    )


def key_digest(key: str) -> str:
    return hashlib.sha256(b"enrollment-key:" + key.encode("utf-8")).hexdigest()


def derive_resume_token(key: str) -> str:
    """Resume token derived from the client-held key, so a replay can return the same token.

    Only hashes are stored; neither the key nor the token can be recovered from the database.
    """
    mac = hmac.new(key.encode("utf-8"), b"kaiwa-resume-token-v1", hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode().rstrip("=")


def _existing(db: Session, digest: str) -> Participant | None:
    return db.execute(
        select(Participant)
        .options(selectinload(Participant.sessions))
        .where(Participant.enrollment_key_hash == digest)
    ).scalar_one_or_none()


def enroll(db: Session, consent_version: str, key: str) -> Enrollment:
    """Allocate both conditions atomically; the same key never creates a second participant.

    PostgreSQL row lock prevents concurrent skew and serializes concurrent retries.
    """
    digest = key_digest(key)
    resume_token = derive_resume_token(key)
    replay = _existing(db, digest)
    if replay is not None:
        return Enrollment(replay, resume_token)
    counter = db.execute(
        select(AllocationCounter).where(AllocationCounter.id == 1).with_for_update()
    ).scalar_one()
    # A concurrent request with the same key may have committed while we waited for the lock.
    db.refresh(counter)
    replay = _existing(db, digest)
    if replay is not None:
        db.rollback()
        return Enrollment(replay, resume_token)
    if counter.fixed_first < counter.adaptive_first:
        order = "AB"
    elif counter.adaptive_first < counter.fixed_first:
        order = "BA"
    else:
        order = secrets.choice(("AB", "BA"))
    if order == "AB":
        counter.fixed_first += 1
    else:
        counter.adaptive_first += 1

    participant = Participant(
        token_hash=token_digest(resume_token),
        enrollment_key_hash=digest,
        order=order,
        consent_version=consent_version,
    )
    participant.sessions = [
        StudySession(ordinal=1, method="fixed" if order == "AB" else "adaptive"),
        StudySession(ordinal=2, method="adaptive" if order == "AB" else "fixed"),
    ]
    db.add(participant)
    try:
        db.commit()
    except IntegrityError:
        # Lost a race without row locking (e.g. SQLite): the winner's participant is the answer.
        db.rollback()
        replay = _existing(db, digest)
        if replay is None:
            raise
        return Enrollment(replay, resume_token)
    db.refresh(participant)
    return Enrollment(participant, resume_token)


def find_by_token(db: Session, token: str) -> Participant | None:
    return db.execute(
        select(Participant)
        .options(selectinload(Participant.sessions))
        .where(Participant.token_hash == token_digest(token))
    ).scalar_one_or_none()
