"""Whisper service with explicit release of per-call native model resources."""

from pipecat.services.whisper.stt import WhisperSTTService


class LocalWhisperSTTService(WhisperSTTService):
    async def cleanup(self):
        try:
            await super().cleanup()
        finally:
            # Processor/context cycles can otherwise keep CTranslate2 VRAM alive
            # until Python's cyclic collector runs, even after the call ends.
            self._model = None
