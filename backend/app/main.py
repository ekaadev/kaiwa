"""Control-plane API. WebRTC media will join LiveKit, not this HTTP server."""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.call_capacity import CallCapacity
from app.livekit_practice import livekit_practice_from_env
from app.livekit_study import livekit_study_from_env
from app.models import (
    AllocationCounter,
    Base,
    Participant,
    StudyAttempt,
    StudyEvidence,
    StudySession,
)
from app.practice import PracticeCallStarter, PracticeIssue, PracticeUnavailable
from app.study import enroll, find_by_token
from app.study_calls import (
    STALE_AFTER,
    StudyCallConflict,
    StudyCallStarter,
    finish,
    now,
    reserve,
    utc,
)

bearer = HTTPBearer(auto_error=False)
logger = logging.getLogger(__name__)

PRACTICE_MESSAGES = {
    PracticeIssue.SERVICE_UNAVAILABLE: "Practice calls are unavailable",
    PracticeIssue.CAPACITY_FULL: "Practice calls are at capacity",
}


def practice_unavailable(issue: PracticeIssue = PracticeIssue.SERVICE_UNAVAILABLE) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={"code": issue.value, "message": PRACTICE_MESSAGES[issue]},
        headers={"Cache-Control": "no-store"},
    )


class ConsentRequest(BaseModel):
    accepted: Literal[True]


class SessionView(BaseModel):
    ordinal: int
    status: str
    available: bool


class ParticipantView(BaseModel):
    participant_id: UUID
    sessions: list[SessionView]


class EnrollmentView(ParticipantView):
    # Shown only once. The client must store this secret securely, not log it.
    resume_token: str


class PracticeStartRequest(BaseModel):
    # Practice mode and EOT strategy are server decisions, never client options.
    model_config = ConfigDict(extra="forbid")


class StudyStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ClientAudioEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event: Literal["remote_audio_subscribed", "remote_audio_unsubscribed"]
    client_sequence: int = Field(ge=1, le=2000)
    client_timestamp_ms: int = Field(ge=0, le=2**63 - 1)


class PracticeCallView(BaseModel):
    call_id: UUID
    room_url: str
    join_token: str
    transcript_token: str | None = None


def public_view(participant: Participant) -> ParticipantView:
    sessions = sorted(participant.sessions, key=lambda session: session.ordinal)
    return ParticipantView(
        participant_id=participant.id,
        sessions=[
            SessionView(
                ordinal=session.ordinal,
                status=session.status,
                available=(session.ordinal == 1 or sessions[0].status == "completed")
                and session.status != "completed"
                and not any(
                    a.status in ("starting", "active", "awaiting_evidence")
                    and now() - utc(a.ended_at or a.started_at) < STALE_AFTER
                    for a in session.attempts
                ),
            )
            for session in sessions
        ],
    )


def get_db(request: Request):
    with request.app.state.session_factory() as db:
        yield db


def get_current_participant(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    db: Annotated[Session, Depends(get_db)],
) -> Participant:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Missing study resume token")
    participant = find_by_token(db, credentials.credentials)
    if participant is None:
        raise HTTPException(status_code=401, detail="Invalid study resume token")
    return participant


def create_app(
    engine: Engine | None = None,
    *,
    practice_starter: PracticeCallStarter | None = None,
    study_starter: StudyCallStarter | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        owns_engine = engine is None
        capacity = CallCapacity()
        owned_starter = None
        if practice_starter is None and owns_engine:
            owned_starter = livekit_practice_from_env(capacity)
        selected_starter = practice_starter if practice_starter is not None else owned_starter
        app.state.practice_starter = selected_starter
        selected_engine = engine
        if selected_engine is None:
            url = os.getenv("DATABASE_URL")
            if not url:
                raise RuntimeError("DATABASE_URL is required; see .env.example")
            selected_engine = create_engine(url, pool_pre_ping=True)
        if owns_engine:
            # Never alter a deployment schema implicitly during application startup.
            with selected_engine.connect() as connection:
                revision = connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar()
                if revision != "0003_study_evidence":
                    raise RuntimeError("Run database migrations before starting the API")
        else:
            # Injected engines are isolated test fixtures; deployments use migrations above.
            Base.metadata.create_all(selected_engine)
        app.state.session_factory = sessionmaker(selected_engine, expire_on_commit=False)
        owned_study = (
            livekit_study_from_env(app.state.session_factory, capacity)
            if study_starter is None and owns_engine
            else None
        )
        app.state.study_starter = study_starter if study_starter is not None else owned_study
        with app.state.session_factory() as db:
            if db.get(AllocationCounter, 1) is None:
                db.add(AllocationCounter(id=1, fixed_first=0, adaptive_first=0))
                db.commit()

        async def housekeeping():
            while True:
                practice_registry = getattr(selected_starter, "transcripts", None)
                if practice_registry is not None:
                    practice_registry.prune()
                if app.state.study_starter is not None:
                    store = getattr(app.state.study_starter, "evidence_store", None)
                    if store is not None:
                        await asyncio.to_thread(store.cleanup)
                    registry = getattr(app.state.study_starter, "transcripts", None)
                    if registry is not None:
                        registry.prune()
                await asyncio.sleep(60)

        cleanup_task = asyncio.create_task(housekeeping())
        try:
            yield
        finally:
            cleanup_task.cancel()
            await asyncio.gather(cleanup_task, return_exceptions=True)
            if owned_starter is not None:
                await owned_starter.aclose()
            if owned_study is not None:
                await owned_study.aclose()
            if owns_engine:
                selected_engine.dispose()

    app = FastAPI(title="AI Conversation Control API", version="0.1.0", lifespan=lifespan)

    @app.get("/health")
    def health(db: Annotated[Session, Depends(get_db)]):
        db.execute(text("SELECT 1"))
        return {"status": "ok"}

    @app.get("/v1/practice/readiness")
    async def practice_readiness(request: Request, response: Response):
        starter = request.app.state.practice_starter
        if starter is None:
            raise practice_unavailable()
        try:
            readiness = await starter.ready()
        except Exception as exc:
            logger.warning("Practice readiness check failed")
            raise practice_unavailable() from exc
        if not readiness.ready:
            raise practice_unavailable(readiness.reason or PracticeIssue.SERVICE_UNAVAILABLE)
        response.headers["Cache-Control"] = "no-store"
        return {"ready": True}

    @app.post(
        "/v1/practice/calls",
        response_model=PracticeCallView,
        response_model_exclude_none=True,
        status_code=201,
    )
    async def create_practice_call(
        _: PracticeStartRequest, response: Response, request: Request
    ) -> PracticeCallView:
        starter = request.app.state.practice_starter
        if starter is None:
            raise practice_unavailable()
        try:
            connection = await starter.start(eot_method="adaptive")
        except PracticeUnavailable as exc:
            raise practice_unavailable(exc.reason) from exc
        except Exception as exc:
            logger.warning("Practice call setup failed")
            raise practice_unavailable() from exc
        response.headers["Cache-Control"] = "no-store"
        return PracticeCallView(
            call_id=connection.call_id,
            room_url=connection.room_url,
            join_token=connection.join_token,
            transcript_token=connection.transcript_token,
        )

    @app.post("/v1/study/participants", response_model=EnrollmentView, status_code=201)
    def create_participant(
        _: ConsentRequest,
        db: Annotated[Session, Depends(get_db)],
    ) -> EnrollmentView:
        consent_version = os.getenv("STUDY_CONSENT_VERSION", "draft-v1")
        enrollment = enroll(db, consent_version)
        return EnrollmentView(
            **public_view(enrollment.participant).model_dump(),
            resume_token=enrollment.resume_token,
        )

    @app.get("/v1/study/me", response_model=ParticipantView)
    def get_my_study(
        participant: Annotated[Participant, Depends(get_current_participant)],
    ) -> ParticipantView:
        return public_view(participant)

    @app.post(
        "/v1/study/sessions/{ordinal}/calls", response_model=PracticeCallView, status_code=201
    )
    async def start_study_call(
        ordinal: int,
        _: StudyStartRequest,
        request: Request,
        response: Response,
        participant: Annotated[Participant, Depends(get_current_participant)],
        db: Annotated[Session, Depends(get_db)],
    ) -> PracticeCallView:
        starter = request.app.state.study_starter
        if starter is None:
            raise HTTPException(status_code=503, detail="Study calls are unavailable")
        key = request.headers.get("Idempotency-Key", "")
        if not (8 <= len(key) <= 128 and key.isascii() and key.isprintable()):
            raise HTTPException(status_code=400, detail="A valid Idempotency-Key is required")
        try:
            attempt, created = reserve(db, participant.id, ordinal, key)
        except StudyCallConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if not created and attempt.status not in ("starting", "active"):
            raise HTTPException(status_code=409, detail="This request has already ended")
        try:
            if created:
                connection = await starter.start(
                    attempt_id=attempt.id, method=attempt.session.method
                )
                # A transport can terminate while setup is still returning.
                db.refresh(attempt)
                if attempt.status != "starting":
                    raise RuntimeError("Call ended during setup")
                attempt.status = "active"
                db.commit()
            else:
                connection = await starter.reconnect(attempt_id=attempt.id)
        except Exception as exc:
            if created:
                finish(db, attempt.id, "setup_failed")
            logger.warning("Study call setup failed")
            raise HTTPException(status_code=503, detail="Study calls are unavailable") from exc
        response.headers["Cache-Control"] = "no-store"
        return PracticeCallView(
            call_id=attempt.id, room_url=connection.room_url, join_token=connection.join_token
        )

    @app.post("/v1/study/calls/{call_id}/end", status_code=204)
    async def end_study_call(
        call_id: UUID,
        request: Request,
        participant: Annotated[Participant, Depends(get_current_participant)],
        db: Annotated[Session, Depends(get_db)],
    ) -> Response:
        attempt = db.scalar(
            select(StudyAttempt)
            .join(StudySession)
            .where(StudyAttempt.id == call_id, StudySession.participant_id == participant.id)
        )
        if attempt is None or attempt.status != "active":
            raise HTTPException(status_code=404, detail="Active call not found")
        starter = request.app.state.study_starter
        if starter is None or not await starter.end(attempt_id=call_id):
            raise HTTPException(status_code=409, detail="Call is no longer active")
        return Response(status_code=204, headers={"Cache-Control": "no-store"})

    @app.get("/v1/practice/calls/{call_id}/transcript")
    async def practice_transcript(
        call_id: UUID,
        request: Request,
        response: Response,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
        after: Annotated[int, Query(ge=0)] = 0,
    ):
        starter = request.app.state.practice_starter
        registry = getattr(starter, "transcripts", None)
        log = registry.get(call_id, credentials.credentials) if registry and credentials else None
        if log is None:
            raise HTTPException(status_code=401, detail="Transcript access is unavailable")
        response.headers["Cache-Control"] = "no-store"
        return log.view(after)

    @app.post("/v1/practice/calls/{call_id}/end", status_code=204)
    async def end_practice(
        call_id: UUID,
        request: Request,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ):
        starter = request.app.state.practice_starter
        registry = getattr(starter, "transcripts", None)
        log = registry.get(call_id, credentials.credentials) if registry and credentials else None
        if log is None:
            raise HTTPException(status_code=401, detail="Call access is unavailable")
        if not log.finalized and not await starter.end(call_id):
            raise HTTPException(status_code=409, detail="Call is no longer active")
        return Response(status_code=204, headers={"Cache-Control": "no-store"})

    @app.post("/v1/study/calls/{call_id}/events", status_code=204)
    async def study_client_event(
        call_id: UUID,
        event: ClientAudioEvent,
        request: Request,
        participant: Annotated[Participant, Depends(get_current_participant)],
        db: Annotated[Session, Depends(get_db)],
    ):
        attempt = db.scalar(
            select(StudyAttempt)
            .join(StudySession)
            .where(
                StudyAttempt.id == call_id,
                StudySession.participant_id == participant.id,
                StudyAttempt.status == "active",
            )
        )
        if attempt is None:
            raise HTTPException(status_code=404, detail="Active call not found")
        registry = getattr(request.app.state.study_starter, "transcripts", None)
        log = registry.get(call_id) if registry else None
        if log is None or log.evidence is None or log.evidence.closed:
            raise HTTPException(status_code=409, detail="Evidence is not accepting events")
        if event.client_sequence not in log.client_sequences:
            # Client telemetry cannot alter media duration, outcome, or completion.
            log.client_sequences.add(event.client_sequence)
            try:
                await log.evidence.event({"type": "client_audio", **event.model_dump()})
            except Exception as exc:
                log.client_sequences.discard(event.client_sequence)
                raise HTTPException(status_code=503, detail="Evidence storage unavailable") from exc
        return Response(status_code=204, headers={"Cache-Control": "no-store"})

    @app.get("/v1/study/calls/{call_id}/transcript")
    async def study_transcript(
        call_id: UUID,
        request: Request,
        response: Response,
        participant: Annotated[Participant, Depends(get_current_participant)],
        db: Annotated[Session, Depends(get_db)],
        after: Annotated[int, Query(ge=0)] = 0,
    ):
        attempt = db.scalar(
            select(StudyAttempt)
            .join(StudySession)
            .where(StudyAttempt.id == call_id, StudySession.participant_id == participant.id)
        )
        if attempt is None:
            raise HTTPException(status_code=404, detail="Call not found")
        starter = request.app.state.study_starter
        registry = getattr(starter, "transcripts", None)
        log = registry.get(call_id) if registry else None
        view = log.view(after) if log else None
        if view is None:
            store = getattr(starter, "evidence_store", None)
            record = db.get(StudyEvidence, call_id)
            view = (
                await asyncio.to_thread(store.transcript, call_id, record.manifest_sha256)
                if store and record
                else None
            )
            if view is not None:
                view["turns"] = [t for t in view["turns"] if t["sequence"] > after]
        if view is None:
            raise HTTPException(status_code=404, detail="Transcript unavailable or expired")
        response.headers["Cache-Control"] = "no-store"
        return view

    return app


app = create_app()
