"""Study records: research identity is not a login account."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class AllocationCounter(Base):
    """Single locked row keeps A/B and B/A counts balanced under concurrent requests."""

    __tablename__ = "allocation_counter"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fixed_first: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    adaptive_first: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Participant(Base):
    __tablename__ = "participants"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    order: Mapped[str] = mapped_column(String(2), nullable=False)  # AB = fixed first
    consent_version: Mapped[str] = mapped_column(String(64), nullable=False)
    consented_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    sessions: Mapped[list["StudySession"]] = relationship(back_populates="participant")


class StudySession(Base):
    __tablename__ = "study_sessions"
    __table_args__ = (UniqueConstraint("participant_id", "ordinal"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    participant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("participants.id"), nullable=False, index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    participant: Mapped[Participant] = relationship(back_populates="sessions")
    attempts: Mapped[list["StudyAttempt"]] = relationship(back_populates="session")


class StudyAttempt(Base):
    """Server-owned call outcome; a failed call never replaces an earlier attempt."""

    __tablename__ = "study_attempts"
    __table_args__ = (
        UniqueConstraint("session_id", "request_hash"),
        Index(
            "one_active_attempt_per_session",
            "session_id",
            unique=True,
            postgresql_where=text("status IN ('starting', 'active', 'awaiting_evidence')"),
            sqlite_where=text("status IN ('starting', 'active', 'awaiting_evidence')"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("study_sessions.id"), nullable=False, index=True
    )
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="starting")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    media_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    end_reason: Mapped[str | None] = mapped_column(String(32))
    evidence_saved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    session: Mapped[StudySession] = relationship(back_populates="attempts")
