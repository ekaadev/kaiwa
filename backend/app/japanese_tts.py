"""Japanese Kokoro synthesis with the model's Japanese phoneme frontend."""

import asyncio

import numpy as np
from misaki.ja import JAG2P
from pipecat.frames.frames import ErrorFrame, TTSAudioRawFrame
from pipecat.services.kokoro.tts import KokoroTTSService
from pipecat.utils.tracing.service_decorators import traced_tts


class JapaneseKokoroTTSService(KokoroTTSService):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._japanese_g2p = JAG2P(version="pyopenjtalk")

    @traced_tts
    async def run_tts(self, text: str, context_id: str):
        try:
            voice = self._settings.voice
            if not isinstance(voice, str) or not voice.strip():
                raise ValueError("Japanese speech synthesis requires a configured voice")
            await self.start_tts_usage_metrics(text)
            phonemes, _ = await asyncio.to_thread(self._japanese_g2p, text)
            stream = self._kokoro.create_stream(
                phonemes, voice=voice, speed=1.0, is_phonemes=True
            )
            async for samples, sample_rate in stream:
                await self.stop_ttfb_metrics()
                audio = (samples * 32767).astype(np.int16).tobytes()
                audio = await self._resampler.resample(audio, sample_rate, self.sample_rate)
                yield TTSAudioRawFrame(
                    audio=audio,
                    sample_rate=self.sample_rate,
                    num_channels=1,
                    context_id=context_id,
                )
        except Exception:
            yield ErrorFrame(error="Japanese speech synthesis failed")
        finally:
            await self.stop_ttfb_metrics()
