"""Blind A/B UAT for an expert: seeded counterbalanced plan, trial flow rules, ratings, export.

The detection method of a trial lives only in `StudySession.method`; no view in this module
exposes it. Only the neutral version letter (A/B) reaches the expert.
"""

import csv
import io
import json
import random
import secrets
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import Participant, StudyAttempt, StudySession, UatPreference
from app.study import key_digest, token_digest
from app.study_calls import STALE_AFTER, finish, now, utc

SCENARIO_COUNT = 4
TEST_SESSIONS = 3
TRIALS_PER_SESSION = SCENARIO_COUNT * 2
TURN_LABELS = ("Cut off", "Too slow", "Fine")
RATING_ITEMS = 4
LIVE = ("starting", "active")
CALL_DONE = ("awaiting_evidence", "completed")


class UatConflict(Exception):
    pass


def build_plan(seed: int) -> list[dict]:
    """12 pairs (3 sessions x 4 scenarios): A/B order alternates, A is adaptive in 6 of 12."""
    rng = random.Random(seed)
    a_is_adaptive = [True] * 6 + [False] * 6
    rng.shuffle(a_is_adaptive)
    offset = rng.randrange(2)
    plan = []
    for test_session in range(1, TEST_SESSIONS + 1):
        for scenario in range(SCENARIO_COUNT):
            pair = (test_session - 1) * SCENARIO_COUNT + scenario
            letters = ("A", "B") if (pair + offset) % 2 == 0 else ("B", "A")
            for j, letter in enumerate(letters):
                adaptive = (letter == "A") == a_is_adaptive[pair]
                position = scenario * 2 + j
                plan.append(
                    {
                        "ordinal": (test_session - 1) * TRIALS_PER_SESSION + position + 1,
                        "test_session": test_session,
                        "position": position,
                        "scenario": scenario,
                        "repetition": test_session,
                        "version": letter,
                        "method": "adaptive" if adaptive else "fixed",
                    }
                )
    return plan


def create_run(db: Session, *, pilot: bool, key: str, resume_token: str) -> Participant:
    """One run per idempotency key; a replay returns the same participant."""
    digest = key_digest(key)
    existing = db.scalar(
        select(Participant)
        .options(selectinload(Participant.sessions))
        .where(Participant.enrollment_key_hash == digest)
    )
    if existing is not None:
        return existing
    seed = secrets.randbits(62)
    count = db.scalar(
        select(func.count()).select_from(Participant).where(Participant.kind == "uat")
    )
    participant = Participant(
        token_hash=token_digest(resume_token),
        enrollment_key_hash=digest,
        order="AB",
        consent_version="uat",
        kind="uat",
        label=f"EXP-{(count or 0) + 1:02d}",
        pilot=pilot,
        plan_seed=seed,
    )
    participant.sessions = [
        StudySession(**{k: v for k, v in trial.items()}) for trial in build_plan(seed)
    ]
    db.add(participant)
    db.commit()
    db.refresh(participant)
    return participant


def latest_attempt(session: StudySession) -> StudyAttempt | None:
    attempts = sorted(
        (a for a in session.attempts if not a.void), key=lambda a: utc(a.started_at)
    )
    return attempts[-1] if attempts else None


def trial_status(session: StudySession) -> str:
    if session.status == "skipped":
        return "skipped"
    attempt = latest_attempt(session)
    if attempt is None or attempt.status == "failed":
        return "pending"
    if attempt.status in LIVE:
        return "in_progress"
    return "rated" if attempt.rated_at is not None else "awaiting_rating"


def finished(session: StudySession) -> bool:
    return trial_status(session) in ("rated", "skipped")


def _stale_live(session: StudySession) -> bool:
    return any(
        a.status in LIVE and now() - utc(a.ended_at or a.started_at) < STALE_AFTER
        for a in session.attempts
    )


def run_view(db: Session, participant: Participant) -> dict:
    """Expert-facing progress. Deliberately contains no method, order or seed."""
    sessions = sorted(participant.sessions, key=lambda s: s.ordinal)
    nxt = next((s for s in sessions if not finished(s)), None)
    prefs = db.scalars(
        select(UatPreference).where(UatPreference.participant_id == participant.id)
    ).all()
    trials = []
    for s in sessions:
        attempt = latest_attempt(s)
        status = trial_status(s)
        trials.append(
            {
                "ordinal": s.ordinal,
                "test_session": s.test_session,
                "scenario": s.scenario,
                "repetition": s.repetition,
                "version": s.version,
                "status": status,
                "attempts": sum(1 for a in s.attempts if a.status != "failed" or a.void),
                "available": s is nxt and status in ("pending",) and not _stale_live(s),
                "call_id": str(attempt.id) if attempt is not None else None,
                "ratings": attempt.ratings if attempt is not None else None,
                "labels": attempt.labels if attempt is not None else None,
            }
        )
    return {
        "participant_id": str(participant.id),
        "label": participant.label,
        "pilot": participant.pilot,
        "test_session": nxt.test_session if nxt is not None else TEST_SESSIONS,
        "complete": nxt is None,
        "abandoned": participant.abandoned_at is not None,
        "trials": trials,
        "preferences": [
            {"test_session": p.test_session, "scenario": p.scenario, "choice": p.choice}
            for p in prefs
        ],
    }


def _locked_sessions(db: Session, participant_id: UUID) -> list[StudySession]:
    person = db.get(Participant, participant_id)
    if person is not None and person.abandoned_at is not None:
        raise UatConflict("This run was exited")
    return list(
        db.scalars(
            select(StudySession)
            .where(StudySession.participant_id == participant_id)
            .order_by(StudySession.ordinal)
            .with_for_update()
        ).all()
    )


def reserve_trial(
    db: Session, participant_id: UUID, ordinal: int, key: str
) -> tuple[StudyAttempt, bool]:
    """Open (or replay) a call for one trial. Trials run in order; a retry keeps the same method."""
    import hashlib

    sessions = _locked_sessions(db, participant_id)
    session = next((s for s in sessions if s.ordinal == ordinal), None)
    if session is None:
        raise UatConflict("Trial is unavailable")
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    previous = db.scalar(
        select(StudyAttempt).where(
            StudyAttempt.session_id == session.id, StudyAttempt.request_hash == digest
        )
    )
    if previous is not None:
        return previous, False
    if any(not finished(s) for s in sessions if s.ordinal < ordinal):
        raise UatConflict("Finish the earlier trials first")
    status = trial_status(session)
    if status in ("rated", "skipped"):
        raise UatConflict("Trial is already finished")
    if status == "awaiting_rating":
        raise UatConflict("Rate or redo this trial first")
    live = next((a for a in session.attempts if a.status in LIVE), None)
    if live is not None:
        if now() - utc(live.ended_at or live.started_at) < STALE_AFTER:
            raise UatConflict("A call is already in progress")
        finish(db, live.id, "interrupted")
    attempt = StudyAttempt(session_id=session.id, request_hash=digest, started_at=now())
    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    return attempt, True


def _session_for(db: Session, participant_id: UUID, ordinal: int) -> tuple[StudySession, list]:
    sessions = _locked_sessions(db, participant_id)
    session = next((s for s in sessions if s.ordinal == ordinal), None)
    if session is None:
        raise UatConflict("Trial is unavailable")
    return session, sessions


def skip_trial(db: Session, participant_id: UUID, ordinal: int) -> None:
    session, sessions = _session_for(db, participant_id, ordinal)
    if any(not finished(s) for s in sessions if s.ordinal < ordinal):
        raise UatConflict("Finish the earlier trials first")
    if trial_status(session) not in ("pending",):
        raise UatConflict("Only a trial without a call can be skipped")
    session.status = "skipped"
    db.commit()


def redo_trial(db: Session, participant_id: UUID, ordinal: int) -> None:
    """Void the latest attempt; the trial keeps its version letter and method."""
    session, _ = _session_for(db, participant_id, ordinal)
    attempt = latest_attempt(session)
    if session.status == "skipped" or attempt is None or attempt.status in LIVE:
        raise UatConflict("Nothing to redo")
    attempt.void = True
    if session.status == "completed":
        session.status = "pending"
    db.commit()


def save_rating(
    db: Session, participant_id: UUID, ordinal: int, ratings: list[int], labels: dict[str, str]
) -> None:
    if len(ratings) != RATING_ITEMS or any(not 1 <= r <= 5 for r in ratings):
        raise UatConflict("Ratings must be four scores from 1 to 5")
    if any(not k.isdigit() or v not in TURN_LABELS for k, v in labels.items()):
        raise UatConflict("Unknown turn label")
    session, _ = _session_for(db, participant_id, ordinal)
    attempt = latest_attempt(session)
    if attempt is None or attempt.status not in CALL_DONE:
        raise UatConflict("The call for this trial has not finished")
    attempt.ratings = ratings
    attempt.labels = labels
    attempt.rated_at = now()
    db.commit()


def save_preference(
    db: Session, participant_id: UUID, test_session: int, scenario: int, choice: str
) -> None:
    if choice not in ("A", "B", "None"):
        raise UatConflict("Unknown choice")
    sessions = _locked_sessions(db, participant_id)
    pair = [s for s in sessions if s.test_session == test_session and s.scenario == scenario]
    if len(pair) != 2 or not all(finished(s) for s in pair):
        raise UatConflict("Finish both trials of the pair first")
    row = db.get(UatPreference, (participant_id, test_session, scenario))
    if row is None:
        db.add(
            UatPreference(
                participant_id=participant_id,
                test_session=test_session,
                scenario=scenario,
                choice=choice,
            )
        )
    else:
        row.choice = choice
    db.commit()


def abandon_run(db: Session, participant_id: UUID) -> None:
    """Mark the run as left. Data stays; no further trial actions are accepted."""
    sessions = list(
        db.scalars(select(StudySession).where(StudySession.participant_id == participant_id))
    )
    if any(a.status in LIVE for s in sessions for a in s.attempts):
        raise UatConflict("End the current call first")
    person = db.get(Participant, participant_id)
    if person is not None and person.abandoned_at is None:
        person.abandoned_at = now()
        db.commit()


def run_status(person: Participant) -> str:
    if person.abandoned_at is not None:
        return "abandoned"
    return "complete" if all(finished(s) for s in person.sessions) else "in_progress"


def export_csv(db: Session) -> str:
    """Researcher export: includes the method, which participants and experts never see."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(
        [
            "participant", "pilot", "run_status", "test_session", "position", "scenario",
            "repetition",
            "version", "method", "trial_status", "attempt_id", "void", "attempt_status",
            "media_ms", "started_at", "natural", "cut_off", "waited_too_long", "flow",
            "turn_labels_json", "pair_preference",
        ]
    )
    people = db.scalars(
        select(Participant)
        .options(selectinload(Participant.sessions).selectinload(StudySession.attempts))
        .where(Participant.kind == "uat")
        .order_by(Participant.label)
    ).all()
    for person in people:
        prefs = {
            (p.test_session, p.scenario): p.choice
            for p in db.scalars(
                select(UatPreference).where(UatPreference.participant_id == person.id)
            )
        }
        for s in sorted(person.sessions, key=lambda x: x.ordinal):
            attempts = sorted(s.attempts, key=lambda a: utc(a.started_at)) or [None]
            for a in attempts:
                r = (a.ratings if a is not None else None) or [""] * 4
                writer.writerow(
                    [
                        person.label, person.pilot, run_status(person), s.test_session,
                        s.position, s.scenario,
                        s.repetition, s.version, s.method, trial_status(s),
                        a.id if a else "", a.void if a else "", a.status if a else "",
                        a.media_ms if a else "",
                        utc(a.started_at).isoformat() if a else "",
                        *r,
                        json.dumps(a.labels) if a and a.labels else "",
                        prefs.get((s.test_session, s.scenario), ""),
                    ]
                )
    return out.getvalue()
