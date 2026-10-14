"""Study-only LiveKit calls; incoming audio frames, not room joins, drive media time."""

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from time import monotonic
from typing import Literal, Protocol, cast
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from app.call_capacity import CallCapacity
from app.call_metrics import StudyMetricsObserver
from app.evidence import EvidenceStore
from app.livekit_practice import (
    BOT_JOIN_TIMEOUT_SECONDS,
    LiveKitGateway,
    run_transport_bot,
)
from app.models import StudyAttempt, StudyEvidence
from app.monitor import CallMonitor
from app.practice import PracticeConnection
from app.study_calls import connected, disconnected, finish, now
from app.transcripts import TranscriptRegistry
from app.tutor import TutorConfig

logger = logging.getLogger(__name__)
FRAME_GAP_SECONDS = 2.0
MAX_FRAME_MS = 250


class StudyUnavailable(Exception):
    pass


class IncomingAudio(Protocol):
    audio: bytes
    sample_rate: int
    num_channels: int


class MediaTracker:
    """Count received microphone PCM; a silent but working microphone still sends frames."""

    def __init__(self, attempt_id: UUID, sessions: sessionmaker[Session]):
        self.attempt_id = attempt_id
        self.sessions = sessions
        self.last_frame_mono: float | None = None
        self.first_frame_mono: float | None = None
        self.last_frame_end: datetime | None = None
        self.last_frame_ms = 0
        self.received_ms = 0
        self._lock = asyncio.Lock()

    async def _write(self, action, at: datetime, *, received_ms: int | None = None):
        def save():
            with self.sessions() as db:
                if received_ms is None:
                    action(db, self.attempt_id, at)
                else:
                    action(db, self.attempt_id, at, received_ms=received_ms)

        await asyncio.to_thread(save)

    async def frame(self, frame: IncomingAudio):
        timestamp = now()
        clock = monotonic()
        # LiveKit input frames are 16-bit PCM; do not count processing or room-join time.
        frame_ms = min(
            int(len(frame.audio) / (frame.sample_rate * frame.num_channels * 2) * 1000),
            MAX_FRAME_MS,
        )
        if frame_ms <= 0:
            return
        end = timestamp + timedelta(milliseconds=frame_ms)
        async with self._lock:
            if (
                self.last_frame_mono is not None
                and clock - self.last_frame_mono > FRAME_GAP_SECONDS
            ):
                await self._close_locked()
            if self.last_frame_mono is None:
                await self._write(connected, timestamp)
                self.first_frame_mono = clock
            self.last_frame_mono = clock
            self.last_frame_end = end
            self.last_frame_ms = frame_ms
            self.received_ms += frame_ms

    async def _close_locked(self):
        if self.last_frame_end is not None:
            assert self.first_frame_mono is not None and self.last_frame_mono is not None
            elapsed_ms = int((self.last_frame_mono - self.first_frame_mono) * 1000)
            verified_ms = min(self.received_ms, elapsed_ms + self.last_frame_ms)
            await self._write(disconnected, self.last_frame_end, received_ms=verified_ms)
        self.last_frame_mono = None
        self.first_frame_mono = None
        self.last_frame_end = None
        self.last_frame_ms = 0
        self.received_ms = 0

    async def close(self):
        async with self._lock:
            await self._close_locked()

    async def watch(self):
        while True:
            await asyncio.sleep(0.5)
            async with self._lock:
                if (
                    self.last_frame_mono is not None
                    and monotonic() - self.last_frame_mono > FRAME_GAP_SECONDS
                ):
                    await self._close_locked()


@dataclass
class ActiveStudyCall:
    room: str
    task: asyncio.Task | None = None
    ready: bool = False
    ending_normally: bool = False
    setup_failed: bool = False


class LiveKitStudyStarter:
    """One bot and one room per attempt; configured evidence capture gates completion."""

    def __init__(
        self,
        gateway: LiveKitGateway,
        tutor: TutorConfig,
        sessions: sessionmaker[Session],
        *,
        max_active_calls: int = 2,
        capacity: CallCapacity | None = None,
        evidence_store: EvidenceStore | None = None,
    ):
        self.gateway = gateway
        self.tutor = tutor
        self.sessions = sessions
        self.max_active_calls = max_active_calls
        self.capacity = capacity
        self.evidence_store = evidence_store
        self.transcripts = TranscriptRegistry()
        self.monitor = CallMonitor()
        self._active: dict[UUID, ActiveStudyCall] = {}
        self._lock = asyncio.Lock()

    async def start(self, *, attempt_id: UUID, method: str) -> PracticeConnection:
        if method not in ("fixed", "adaptive") or not await self.tutor.ready():
            raise StudyUnavailable()
        room = f"study-{attempt_id.hex}"
        async with self._lock:
            if attempt_id in self._active or len(self._active) >= self.max_active_calls:
                raise StudyUnavailable()
            if self.capacity is not None and not await self.capacity.acquire():
                raise StudyUnavailable()
            call = ActiveStudyCall(room)
            self._active[attempt_id] = call
        try:
            evidence = self.evidence_store.begin(attempt_id) if self.evidence_store else None
            self.transcripts.create(attempt_id, evidence)
            await self.gateway.create_room(room)
            token = self.gateway.join_token(room, bot=True)
            joined = asyncio.Event()
            eot_method = cast(Literal["fixed", "adaptive"], method)
            call.task = asyncio.create_task(self._run(attempt_id, call, token, joined, eot_method))
            joined_wait = asyncio.create_task(joined.wait())
            try:
                done, _ = await asyncio.wait(
                    {call.task, joined_wait},
                    timeout=BOT_JOIN_TIMEOUT_SECONDS,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if call.task in done or not joined.is_set():
                    raise StudyUnavailable()
            finally:
                joined_wait.cancel()
                await asyncio.gather(joined_wait, return_exceptions=True)
            client_token = self.gateway.join_token(room, bot=False)
            if call.task.done():
                raise StudyUnavailable()
            call.ready = True
            return PracticeConnection(attempt_id, self.gateway.url, client_token)
        except BaseException:
            call.setup_failed = True
            if call.task is not None:
                call.task.cancel()
                await asyncio.gather(call.task, return_exceptions=True)
            log = self.transcripts.get(attempt_id)
            if log is not None:
                log.finish()
                if log.evidence is not None and not log.evidence.closed:
                    try:
                        await log.evidence.finalize("setup_failed", 0)
                    except Exception:
                        logger.warning("Study setup evidence could not be finalized")
            async with self._lock:
                still_reserved = attempt_id in self._active
                if still_reserved:
                    self._active.pop(attempt_id)
                    if self.capacity is not None:
                        await self.capacity.release()
            if still_reserved:
                await self._delete_room(room)
            raise

    async def reconnect(self, *, attempt_id: UUID) -> PracticeConnection:
        async with self._lock:
            call = self._active.get(attempt_id)
            if call is None or not call.ready or call.task is None or call.task.done():
                raise StudyUnavailable()
            token = self.gateway.join_token(call.room, bot=False)
            return PracticeConnection(attempt_id, self.gateway.url, token)

    async def end(self, *, attempt_id: UUID) -> bool:
        async with self._lock:
            call = self._active.get(attempt_id)
            if call is None or not call.ready or call.task is None or call.task.done():
                return False
            call.ending_normally = True
            task = call.task
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return True

    async def _run(
        self,
        attempt_id: UUID,
        call: ActiveStudyCall,
        token: str,
        joined: asyncio.Event,
        method: Literal["fixed", "adaptive"],
    ) -> None:
        tracker = MediaTracker(attempt_id, self.sessions)
        watcher = asyncio.create_task(tracker.watch())
        state = self.monitor.start(attempt_id, method)
        log = self.transcripts.get(attempt_id)
        observers = []
        if log is not None and log.evidence is not None:
            metrics = StudyMetricsObserver(log.evidence, method, state)
            observers.append(metrics)

        async def on_frame(frame):
            await tracker.frame(frame)
            state.media_ms = tracker.received_ms

        try:
            if observers:
                await observers[0].start()
            await run_transport_bot(
                self.gateway.url,
                token,
                call.room,
                joined,
                tutor=self.tutor,
                eot_method=method,
                on_audio_frame=on_frame,
                on_audio_lost=tracker.close,
                transcript=log,
                observers=observers,
                enable_metrics=True,
            )
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.warning("Study transport stopped unexpectedly")
        finally:
            self.monitor.stop(attempt_id)
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
            try:
                await tracker.close()
                with self.sessions() as db:
                    reason = (
                        "setup_failed"
                        if call.setup_failed or not call.ready
                        else "normal"
                        if call.ending_normally
                        else "interrupted"
                    )
                    finish(db, attempt_id, reason)
                    attempt = db.get(StudyAttempt, attempt_id)
                    log = self.transcripts.get(attempt_id)
                    if log is not None:
                        log.finish()
                        if log.evidence is not None:
                            try:
                                if attempt is None:
                                    # Close capture files without registering successful evidence.
                                    await log.evidence.finalize("setup_failed", 0)
                                    raise RuntimeError("Study attempt is unavailable")
                                digest = await log.evidence.finalize(reason, attempt.media_ms)
                                db.add(StudyEvidence(attempt_id=attempt_id, manifest_sha256=digest))
                                db.commit()
                                from app.study_calls import evidence_saved

                                evidence_saved(db, attempt_id)
                            except Exception:
                                db.rollback()
                                logger.warning("Study evidence finalization failed")
            finally:
                await self._delete_room(call.room)
                async with self._lock:
                    self._active.pop(attempt_id, None)
                    if self.capacity is not None:
                        await self.capacity.release()

    async def _delete_room(self, room: str):
        try:
            await self.gateway.delete_room(room)
        except Exception:
            logger.warning("Could not delete a study room")

    async def aclose(self):
        async with self._lock:
            tasks = [call.task for call in self._active.values() if call.task is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def livekit_study_from_env(
    sessions: sessionmaker[Session], capacity: CallCapacity | None = None
) -> LiveKitStudyStarter | None:
    url = os.getenv("LIVEKIT_URL", "").strip()
    key = os.getenv("LIVEKIT_API_KEY", "").strip()
    secret = os.getenv("LIVEKIT_API_SECRET", "").strip()
    tutor = TutorConfig.from_env()
    evidence = EvidenceStore.from_env()
    if not (url.startswith("wss://") and key and secret and tutor is not None and evidence):
        return None
    try:
        from faster_whisper import WhisperModel  # noqa: F401
        from livekit import api  # noqa: F401
        from pipecat.services.kokoro.tts import KokoroTTSService  # noqa: F401
        from pipecat.transports.livekit.transport import LiveKitTransport  # noqa: F401
    except Exception:
        return None
    return LiveKitStudyStarter(
        LiveKitGateway(url, key, secret),
        tutor,
        sessions,
        capacity=capacity,
        evidence_store=evidence,
    )
