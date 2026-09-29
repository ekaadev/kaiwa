"""Provision anonymous LiveKit calls and join a Pipecat tutor before issuing credentials."""

import asyncio
import logging
import os
from datetime import timedelta
from typing import Any, Awaitable, Callable, Literal
from uuid import UUID, uuid4

from app.call_capacity import CallCapacity
from app.practice import PracticeConnection, PracticeIssue, PracticeReadiness, PracticeUnavailable
from app.tutor import TutorConfig, build_tutor_processors

logger = logging.getLogger(__name__)

BOT_JOIN_TIMEOUT_SECONDS = 20
READINESS_TIMEOUT_SECONDS = 5
CLIENT_JOIN_TIMEOUT_SECONDS = 60
MAX_CALL_SECONDS = 20 * 60
TOKEN_TTL = timedelta(minutes=5)


class LiveKitGateway:
    def __init__(self, url: str, api_key: str, api_secret: str):
        self.url = url
        self.api_key = api_key
        self.api_secret = api_secret

    async def ready(self) -> bool:
        from livekit import api

        try:
            async with api.LiveKitAPI(self.url, self.api_key, self.api_secret) as livekit:
                await livekit.room.list_rooms(api.ListRoomsRequest())
        except Exception:
            return False
        return True

    async def create_room(self, name: str) -> None:
        from livekit import api

        async with api.LiveKitAPI(self.url, self.api_key, self.api_secret) as livekit:
            await livekit.room.create_room(
                api.CreateRoomRequest(
                    name=name,
                    empty_timeout=CLIENT_JOIN_TIMEOUT_SECONDS,
                    max_participants=2,
                )
            )

    async def delete_room(self, name: str) -> None:
        from livekit import api

        async with api.LiveKitAPI(self.url, self.api_key, self.api_secret) as livekit:
            await livekit.room.delete_room(api.DeleteRoomRequest(room=name))

    def join_token(self, name: str, *, bot: bool) -> str:
        from livekit import api

        identity = f"{'bot' if bot else 'user'}-{uuid4().hex}"
        return (
            api.AccessToken(self.api_key, self.api_secret)
            .with_identity(identity)
            .with_ttl(TOKEN_TTL)
            .with_grants(
                api.VideoGrants(
                    room_join=True,
                    room=name,
                    can_publish=True,
                    can_publish_sources=["microphone"],
                    can_subscribe=True,
                    can_publish_data=False,
                )
            )
            .to_jwt()
        )


async def run_transport_bot(
    url: str,
    token: str,
    room_name: str,
    ready: asyncio.Event,
    tutor: TutorConfig | None = None,
    *,
    eot_method: Literal["fixed", "adaptive"] = "adaptive",
    on_audio_frame: Callable[[Any], Awaitable[None]] | None = None,
    on_audio_lost: Callable[[], Awaitable[None]] | None = None,
) -> None:
    """Join and hold the room with a prepared tutor pipeline."""
    from pipecat.frames.frames import UserAudioRawFrame
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.runner import PipelineRunner
    from pipecat.pipeline.task import PipelineParams, PipelineTask
    from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
    from pipecat.transports.livekit.transport import LiveKitParams, LiveKitTransport

    processors = []
    if tutor:
        processors = await asyncio.to_thread(build_tutor_processors, tutor, eot_method=eot_method)

    class AudioObserver(FrameProcessor):
        async def process_frame(self, frame, direction: FrameDirection):
            await super().process_frame(frame, direction)
            if isinstance(frame, UserAudioRawFrame) and on_audio_frame is not None:
                await on_audio_frame(frame)
            await self.push_frame(frame, direction)

    transport = LiveKitTransport(
        url=url,
        token=token,
        room_name=room_name,
        params=LiveKitParams(
            audio_in_enabled=True,
            audio_in_passthrough=bool(tutor),
            audio_out_enabled=True,
        ),
    )
    input_processors: list[FrameProcessor] = [transport.input()]
    if on_audio_frame is not None:
        input_processors.append(AudioObserver())
    pipeline = Pipeline(
        [*input_processors, *processors[:-1], transport.output(), processors[-1]]
        if processors else [*input_processors, transport.output()]
    )
    task = PipelineTask(
        pipeline,
        params=PipelineParams(audio_in_sample_rate=16000),
        enable_rtvi=False,
        idle_timeout_secs=None,
    )
    runner = PipelineRunner(handle_sigint=False)
    joined = asyncio.Event()
    stopping = asyncio.Event()

    async def stop_once():
        if not stopping.is_set():
            stopping.set()
            await runner.cancel()

    @transport.event_handler("on_connected")
    async def on_connected(_transport):
        ready.set()

    @transport.event_handler("on_first_participant_joined")
    async def on_first_participant_joined(_transport, _participant_id):
        joined.set()

    @transport.event_handler("on_participant_disconnected")
    async def on_participant_disconnected(_transport, _participant_id):
        if on_audio_lost is not None:
            await on_audio_lost()
        asyncio.create_task(stop_once())

    @transport.event_handler("on_audio_track_unsubscribed")
    async def on_audio_track_unsubscribed(_transport, _participant_id):
        if on_audio_lost is not None:
            await on_audio_lost()

    @transport.event_handler("on_disconnected")
    async def on_disconnected(_transport):
        asyncio.create_task(stop_once())

    async def stop_when_unused():
        try:
            await asyncio.wait_for(joined.wait(), timeout=CLIENT_JOIN_TIMEOUT_SECONDS)
            await asyncio.sleep(MAX_CALL_SECONDS)
        except TimeoutError:
            pass
        await stop_once()

    stop_task = asyncio.create_task(stop_when_unused())
    try:
        await runner.run(task)
    finally:
        stop_task.cancel()
        await asyncio.gather(stop_task, return_exceptions=True)


class LiveKitPracticeStarter:
    """Manage anonymous practice transport without touching study records."""

    def __init__(
        self,
        gateway: LiveKitGateway,
        *,
        max_active_calls: int = 2,
        tutor: TutorConfig | None = None,
        capacity: CallCapacity | None = None,
    ):
        self.gateway = gateway
        self.tutor = tutor
        self._max_active_calls = max_active_calls
        self.capacity = capacity
        self._active: dict[UUID, asyncio.Task | None] = {}
        self._lock = asyncio.Lock()

    async def ready(self) -> PracticeReadiness:
        async with self._lock:
            if len(self._active) >= self._max_active_calls:
                return PracticeReadiness(PracticeIssue.CAPACITY_FULL)
        if self.capacity is not None and not await self.capacity.available():
            return PracticeReadiness(PracticeIssue.CAPACITY_FULL)
        if self.tutor is not None and not await self.tutor.ready():
            return PracticeReadiness(PracticeIssue.SERVICE_UNAVAILABLE)
        try:
            reachable = await asyncio.wait_for(
                self.gateway.ready(), timeout=READINESS_TIMEOUT_SECONDS
            )
        except Exception:
            logger.warning("Practice connectivity check failed")
            reachable = False
        return PracticeReadiness(None if reachable else PracticeIssue.SERVICE_UNAVAILABLE)

    async def start(self, *, eot_method: Literal["adaptive"]) -> PracticeConnection:
        if eot_method != "adaptive":
            raise PracticeUnavailable()
        if self.tutor is not None and not await self.tutor.ready():
            raise PracticeUnavailable()

        call_id = uuid4()
        room_name = f"practice-{call_id.hex}"
        async with self._lock:
            if len(self._active) >= self._max_active_calls:
                raise PracticeUnavailable(PracticeIssue.CAPACITY_FULL)
            if self.capacity is not None and not await self.capacity.acquire():
                raise PracticeUnavailable(PracticeIssue.CAPACITY_FULL)
            self._active[call_id] = None

        bot_task = None
        try:
            await self.gateway.create_room(room_name)
            bot_token = self.gateway.join_token(room_name, bot=True)
            connected = asyncio.Event()
            async with self._lock:
                bot_task = asyncio.create_task(
                    self._run_bot(call_id, room_name, bot_token, connected)
                )
                self._active[call_id] = bot_task
            await self._wait_for_bot(bot_task, connected)
            client_token = self.gateway.join_token(room_name, bot=False)
            if bot_task.done():
                raise PracticeUnavailable()
            return PracticeConnection(call_id, self.gateway.url, client_token)
        except asyncio.CancelledError:
            await self._abort(call_id, room_name, bot_task)
            raise
        except Exception as exc:
            await self._abort(call_id, room_name, bot_task)
            raise PracticeUnavailable() from exc

    async def _run_bot(
        self, call_id: UUID, room_name: str, token: str, connected: asyncio.Event
    ) -> None:
        try:
            if self.tutor is None:
                await run_transport_bot(self.gateway.url, token, room_name, connected)
            else:
                await run_transport_bot(
                    self.gateway.url, token, room_name, connected, tutor=self.tutor
                )
        except Exception:
            logger.warning("Practice transport stopped unexpectedly")
        finally:
            await self._delete_room(room_name)
            async with self._lock:
                self._active.pop(call_id, None)
                if self.capacity is not None:
                    await self.capacity.release()

    async def _wait_for_bot(self, bot_task: asyncio.Task, connected: asyncio.Event) -> None:
        wait_task = asyncio.create_task(connected.wait())
        try:
            done, _ = await asyncio.wait(
                {bot_task, wait_task},
                timeout=BOT_JOIN_TIMEOUT_SECONDS,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if bot_task in done or not connected.is_set():
                raise PracticeUnavailable()
        finally:
            wait_task.cancel()
            await asyncio.gather(wait_task, return_exceptions=True)

    async def _abort(self, call_id: UUID, room_name: str, bot_task: asyncio.Task | None):
        if bot_task is not None:
            bot_task.cancel()
            await asyncio.gather(bot_task, return_exceptions=True)
        async with self._lock:
            still_reserved = call_id in self._active
            if still_reserved:
                self._active.pop(call_id)
                if self.capacity is not None:
                    await self.capacity.release()
        if still_reserved:
            await self._delete_room(room_name)

    async def _delete_room(self, name: str) -> None:
        try:
            await self.gateway.delete_room(name)
        except Exception:
            logger.warning("Could not delete a practice room")

    async def aclose(self) -> None:
        async with self._lock:
            tasks = [task for task in self._active.values() if task is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def livekit_practice_from_env(
    capacity: CallCapacity | None = None,
) -> LiveKitPracticeStarter | None:
    url = os.getenv("LIVEKIT_URL", "").strip()
    key = os.getenv("LIVEKIT_API_KEY", "").strip()
    secret = os.getenv("LIVEKIT_API_SECRET", "").strip()
    tutor = TutorConfig.from_env()
    if not (url.startswith("wss://") and key and secret and tutor is not None):
        return None
    try:
        from faster_whisper import WhisperModel  # noqa: F401
        from livekit import api  # noqa: F401
        from pipecat.services.kokoro.tts import KokoroTTSService  # noqa: F401
        from pipecat.transports.livekit.transport import LiveKitTransport  # noqa: F401
    except Exception:
        return None
    return LiveKitPracticeStarter(LiveKitGateway(url, key, secret), tutor=tutor, capacity=capacity)
