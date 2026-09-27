"""Allocation and anonymous resume logic; method never leaves the participant API."""

import hashlib
import secrets
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import AllocationCounter, Participant, StudySession


@dataclass(frozen=True)
class Enrollment:
    participant: Participant
    resume_token: str


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def enroll(db: Session, consent_version: str) -> Enrollment:
    """Allocate both conditions atomically. PostgreSQL row lock prevents concurrent skew."""
    counter = db.execute(
        select(AllocationCounter).where(AllocationCounter.id == 1).with_for_update()
    ).scalar_one()
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

    resume_token = secrets.token_urlsafe(32)
    participant = Participant(
        token_hash=token_digest(resume_token), order=order, consent_version=consent_version
    )
    participant.sessions = [
        StudySession(ordinal=1, method="fixed" if order == "AB" else "adaptive"),
        StudySession(ordinal=2, method="adaptive" if order == "AB" else "fixed"),
    ]
    db.add(participant)
    db.commit()
    db.refresh(participant)
    return Enrollment(participant, resume_token)


def find_by_token(db: Session, token: str) -> Participant | None:
    return db.execute(
        select(Participant)
        .options(selectinload(Participant.sessions))
        .where(Participant.token_hash == token_digest(token))
    ).scalar_one_or_none()
