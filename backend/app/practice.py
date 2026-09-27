"""Boundary for anonymous practice calls, separate from study enrollment."""

from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID


class PracticeUnavailable(Exception):
    """A voice service cannot start a real practice call right now."""


@dataclass(frozen=True)
class PracticeConnection:
    call_id: UUID
    room_url: str
    join_token: str


class PracticeCallStarter(Protocol):
    async def start(self, *, eot_method: Literal["adaptive"]) -> PracticeConnection:
        """Return only when a short-lived client token and the voice tutor are ready.

        If provisioning fails, clean up any room/bot and raise PracticeUnavailable.
        Practice calls must not create participants, study sessions, or research records.
        """
        ...
