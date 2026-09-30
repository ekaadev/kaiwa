"""Bounded call transcripts. Anonymous practice never enters research persistence."""

import hmac
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID


class TranscriptLog:
    def __init__(self, evidence=None):
        self.token = secrets.token_urlsafe(32)
        self.turns = []
        self.finalized = False
        self.ended_at = None
        self.evidence = evidence
        self.client_sequences = set()

    async def update(self, _processor, frame):
        for message in frame.messages:
            if message.role not in ("user", "assistant") or not message.content.strip():
                continue
            turn = {
                "sequence": len(self.turns) + 1,
                "role": message.role,
                "text": message.content[:8192],
                "timestamp": message.timestamp or datetime.now(timezone.utc).isoformat(),
            }
            if len(self.turns) >= 2000:
                raise RuntimeError("Transcript limit exceeded")
            self.turns.append(turn)
            if self.evidence is not None:
                await self.evidence.event({"type": "turn", **turn})

    def finish(self):
        self.finalized = True
        self.ended_at = datetime.now(timezone.utc)

    def view(self, after=0):
        return {
            "turns": [t for t in self.turns if t["sequence"] > after],
            "finalized": self.finalized,
        }


class TranscriptRegistry:
    def __init__(self):
        self.calls: dict[UUID, TranscriptLog] = {}

    def prune(self):
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
        for call_id, log in list(self.calls.items()):
            if log.ended_at is not None and log.ended_at < cutoff:
                del self.calls[call_id]

    def create(self, call_id, evidence=None):
        self.prune()
        log = TranscriptLog(evidence)
        self.calls[call_id] = log
        return log

    def get(self, call_id, token=None):
        self.prune()
        log = self.calls.get(call_id)
        if log is not None and (token is None or hmac.compare_digest(log.token, token)):
            return log
        return None
