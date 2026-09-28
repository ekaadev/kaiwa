"""Boundary for anonymous practice calls, separate from study enrollment."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Protocol
from uuid import UUID


class PracticeIssue(StrEnum):
    SERVICE_UNAVAILABLE = "service_unavailable"
    CAPACITY_FULL = "capacity_full"


class PracticeUnavailable(Exception):
    """A voice service cannot start a real practice call right now."""

    def __init__(self, reason: PracticeIssue = PracticeIssue.SERVICE_UNAVAILABLE):
        self.reason = reason
        super().__init__(reason.value)


@dataclass(frozen=True)
class PracticeReadiness:
    reason: PracticeIssue | None = None

    @property
    def ready(self) -> bool:
        return self.reason is None


@dataclass(frozen=True)
class PracticeConnection:
    call_id: UUID
    room_url: str
    join_token: str


class PracticeCallStarter(Protocol):
    async def ready(self) -> PracticeReadiness:
        """Check capacity and connectivity without creating a room or promising a working tutor."""
        ...

    async def start(self, *, eot_method: Literal["adaptive"]) -> PracticeConnection:
        """Return only when the Pipecat transport is joined and the client token is ready.

        If provisioning fails, clean up any room/bot and raise PracticeUnavailable.
        Practice calls must not create participants, study sessions, or research records.
        The voice tutor pipeline is a separate feature; joining alone cannot answer speech.
        """
        ...
