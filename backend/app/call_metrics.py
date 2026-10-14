"""Study-only timing events derived from Pipecat frames (no text, no audio)."""

import time
from collections import deque

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    MetricsFrame,
    TranscriptionFrame,
    UserStoppedSpeakingFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.metrics.metrics import TTFBMetricsData, TurnMetricsData
from pipecat.observers.base_observer import BaseObserver, FramePushed

from app.monitor import CallState

SEEN_LIMIT = 512


class StudyMetricsObserver(BaseObserver):
    """Writes VAD/EOT/TTFB/bot-speaking events to study evidence and the live monitor.

    The observer sees every hop of a frame, so each frame id is handled once. Event times are
    taken when the observer runs, a few milliseconds after the frame is pushed.
    """

    def __init__(self, evidence, method: str, state: CallState | None = None):
        super().__init__()
        self.evidence = evidence
        self.method = method
        self.state = state
        self.turn_index = 0
        self._seen: deque[int] = deque(maxlen=SEEN_LIMIT)
        self._seen_set: set[int] = set()
        self._last_turn_metrics: TurnMetricsData | None = None
        self._vad_stop_ns: int | None = None
        self._awaiting_bot = False
        # The aggregator broadcasts UserStoppedSpeakingFrame in both directions as distinct
        # frames; accept one EOT per VAD stop so a turn is never counted twice.
        self._eot_allowed = True

    async def start(self):
        await self.evidence.event({"type": "call_clock", "wall_utc_ns": time.time_ns()})

    def _first_sight(self, frame) -> bool:
        if frame.id in self._seen_set:
            return False
        if len(self._seen) == self._seen.maxlen:
            self._seen_set.discard(self._seen[0])
        self._seen.append(frame.id)
        self._seen_set.add(frame.id)
        return True

    async def _emit(self, event: dict) -> None:
        if self.evidence.closed:
            return
        try:
            await self.evidence.event({"turn_index": self.turn_index, **event})
        except Exception:
            if self.state is not None:
                self.state.evidence_failed = True

    async def on_push_frame(self, data: FramePushed):
        frame = data.frame
        interesting = (
            VADUserStartedSpeakingFrame,
            VADUserStoppedSpeakingFrame,
            UserStoppedSpeakingFrame,
            TranscriptionFrame,
            MetricsFrame,
            BotStartedSpeakingFrame,
            BotStoppedSpeakingFrame,
        )
        if not isinstance(frame, interesting) or not self._first_sight(frame):
            return
        now = time.monotonic_ns()
        if isinstance(frame, VADUserStartedSpeakingFrame):
            await self._emit({"type": "vad", "state": "start"})
        elif isinstance(frame, VADUserStoppedSpeakingFrame):
            self._vad_stop_ns = now
            self._eot_allowed = True
            await self._emit({"type": "vad", "state": "stop"})
        elif isinstance(frame, TranscriptionFrame):
            await self._emit({"type": "stt_final", "chars": len(frame.text)})
        elif isinstance(frame, MetricsFrame):
            for item in frame.data:
                if isinstance(item, TurnMetricsData):
                    self._last_turn_metrics = item
                elif isinstance(item, TTFBMetricsData):
                    await self._emit(
                        {
                            "type": "ttfb",
                            "processor": item.processor,
                            "ms": int(item.value * 1000),
                        }
                    )
        elif isinstance(frame, UserStoppedSpeakingFrame):
            if not self._eot_allowed:
                return
            self._eot_allowed = False
            self.turn_index += 1
            metrics = self._last_turn_metrics
            if self.method == "fixed":
                source, probability = "silence", None
            elif metrics is not None and metrics.is_complete:
                source, probability = "smart_turn", metrics.probability
            else:
                # Smart Turn judged incomplete; the turn closed on the silence cap.
                source = "timeout"
                probability = metrics.probability if metrics is not None else None
            self._last_turn_metrics = None
            self._awaiting_bot = True
            if self.state is not None:
                self.state.turns = self.turn_index
                self.state.last_eot_source = source
                self.state.last_eot_probability = probability
            await self._emit(
                {"type": "eot", "method": self.method, "source": source, "probability": probability}
            )
        elif isinstance(frame, BotStartedSpeakingFrame):
            if self._awaiting_bot and self._vad_stop_ns is not None and self.state is not None:
                latency = int((now - self._vad_stop_ns) / 1_000_000)
                self.state.last_latency_ms = latency
                self.state.latencies_ms.append(latency)
            self._awaiting_bot = False
            await self._emit({"type": "bot_speaking", "state": "start"})
        elif isinstance(frame, BotStoppedSpeakingFrame):
            await self._emit({"type": "bot_speaking", "state": "stop"})
