"""In-memory live view of active study calls for the operator dashboard.

Holds timing metadata only; never transcript text, audio, or participant identifiers.
Single API process by design, matching call ownership.
"""

import statistics
import time
from dataclasses import dataclass, field
from uuid import UUID


@dataclass
class CallState:
    method: str
    started_at: float = field(default_factory=time.time)
    turns: int = 0
    last_latency_ms: int | None = None
    last_eot_source: str | None = None
    last_eot_probability: float | None = None
    last_playback: str | None = None
    evidence_failed: bool = False
    media_ms: int = 0
    latencies_ms: list[int] = field(default_factory=list)

    def view(self, call_id: UUID) -> dict:
        return {
            "call_id": str(call_id),
            "method": self.method,
            "elapsed_s": int(time.time() - self.started_at),
            "media_ms": self.media_ms,
            "turns": self.turns,
            "last_latency_ms": self.last_latency_ms,
            "median_latency_ms": (
                int(statistics.median(self.latencies_ms)) if self.latencies_ms else None
            ),
            "last_eot_source": self.last_eot_source,
            "last_eot_probability": self.last_eot_probability,
            "last_playback": self.last_playback,
            "evidence_failed": self.evidence_failed,
        }


class CallMonitor:
    def __init__(self):
        self.calls: dict[UUID, CallState] = {}

    def start(self, call_id: UUID, method: str) -> CallState:
        state = CallState(method)
        self.calls[call_id] = state
        return state

    def get(self, call_id: UUID) -> CallState | None:
        return self.calls.get(call_id)

    def stop(self, call_id: UUID) -> None:
        self.calls.pop(call_id, None)

    def snapshot(self) -> list[dict]:
        return [state.view(call_id) for call_id, state in self.calls.items()]
