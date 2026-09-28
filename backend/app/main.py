"""Control-plane API. WebRTC media will join LiveKit, not this HTTP server."""

import logging
import os
from contextlib import asynccontextmanager
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.livekit_practice import livekit_practice_from_env
from app.models import AllocationCounter, Base, Participant
from app.practice import PracticeCallStarter, PracticeIssue, PracticeUnavailable
from app.study import enroll, find_by_token

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


class PracticeCallView(BaseModel):
    call_id: UUID
    room_url: str
    join_token: str


def public_view(participant: Participant) -> ParticipantView:
    sessions = sorted(participant.sessions, key=lambda session: session.ordinal)
    return ParticipantView(
        participant_id=participant.id,
        sessions=[
            SessionView(
                ordinal=session.ordinal,
                status=session.status,
                available=(session.ordinal == 1 or sessions[0].status == "completed")
                and session.status != "completed",
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
    engine: Engine | None = None, *, practice_starter: PracticeCallStarter | None = None
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        owns_engine = engine is None
        owned_starter = (
            livekit_practice_from_env() if practice_starter is None and owns_engine else None
        )
        selected_starter = practice_starter if practice_starter is not None else owned_starter
        app.state.practice_starter = selected_starter
        selected_engine = engine
        if selected_engine is None:
            url = os.getenv("DATABASE_URL")
            if not url:
                raise RuntimeError("DATABASE_URL is required; see .env.example")
            selected_engine = create_engine(url, pool_pre_ping=True)
        # Bootstrap only. Replace create_all with versioned migrations before research deployment.
        Base.metadata.create_all(selected_engine)
        app.state.session_factory = sessionmaker(selected_engine, expire_on_commit=False)
        with app.state.session_factory() as db:
            if db.get(AllocationCounter, 1) is None:
                db.add(AllocationCounter(id=1, fixed_first=0, adaptive_first=0))
                db.commit()
        try:
            yield
        finally:
            if owned_starter is not None:
                await owned_starter.aclose()
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

    @app.post("/v1/practice/calls", response_model=PracticeCallView, status_code=201)
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

    return app


app = create_app()
