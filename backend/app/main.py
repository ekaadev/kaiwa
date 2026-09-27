"""Control-plane API. WebRTC media will join LiveKit, not this HTTP server."""

import os
from contextlib import asynccontextmanager
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.models import AllocationCounter, Base, Participant
from app.practice import PracticeCallStarter, PracticeUnavailable
from app.study import enroll, find_by_token

bearer = HTTPBearer(auto_error=False)


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
            if owns_engine:
                selected_engine.dispose()

    app = FastAPI(title="AI Conversation Control API", version="0.1.0", lifespan=lifespan)

    @app.get("/health")
    def health(db: Annotated[Session, Depends(get_db)]):
        db.execute(text("SELECT 1"))
        return {"status": "ok"}

    @app.post("/v1/practice/calls", response_model=PracticeCallView, status_code=201)
    async def create_practice_call(_: PracticeStartRequest, response: Response) -> PracticeCallView:
        if practice_starter is None:
            raise HTTPException(status_code=503, detail="Practice calls are unavailable")
        try:
            connection = await practice_starter.start(eot_method="adaptive")
        except PracticeUnavailable as exc:
            raise HTTPException(status_code=503, detail="Practice calls are unavailable") from exc
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
