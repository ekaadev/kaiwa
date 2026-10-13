"""Japanese Kokoro synthesis with the model's Japanese phoneme frontend."""

import asyncio

import numpy as np
from kokoro_onnx import Kokoro
from misaki.ja import JAG2P
from pipecat.frames.frames import ErrorFrame, TTSAudioRawFrame
from pipecat.services.kokoro.tts import KokoroTTSService
from pipecat.utils.tracing.service_decorators import traced_tts


class JapaneseKokoroTTSService(KokoroTTSService):
    _kokoro: Kokoro | None

    def __init__(self, *, execution_provider: str = "CPUExecutionProvider", **kwargs):
        if execution_provider not in {"CPUExecutionProvider", "CUDAExecutionProvider"}:
            raise ValueError("Unsupported Kokoro execution provider")
        super().__init__(**kwargs)
        kokoro = self._kokoro
        if kokoro is None:
            raise RuntimeError("Kokoro model is not initialized")
        session = kokoro.sess
        if execution_provider == "CUDAExecutionProvider":
            # Bound the CUDA arena per call while sharing the GPU with Qwen/Whisper.
            session.set_providers(
                [
                    (
                        execution_provider,
                        {
                            "gpu_mem_limit": str(1024 * 1024 * 1024),
                            "arena_extend_strategy": "kSameAsRequested",
                            "cudnn_conv_algo_search": "DEFAULT",
                            "cudnn_conv_use_max_workspace": "0",
                        },
                    ),
                    "CPUExecutionProvider",
                ]
            )
        else:
            session.set_providers([execution_provider])
        if session.get_providers()[0] != execution_provider:
            raise RuntimeError("Requested Kokoro execution provider is unavailable")
        # CPU kernels for unsupported ONNX nodes are allowed, but failed CUDA
        # inference must not silently rerun the whole model on CPU.
        session.disable_fallback()
        self._japanese_g2p = JAG2P(version="pyopenjtalk")

    async def cleanup(self):
        try:
            await super().cleanup()
        finally:
            self._kokoro = None

    @traced_tts
    async def run_tts(self, text: str, context_id: str):
        try:
            voice = self._settings.voice
            if not isinstance(voice, str) or not voice.strip():
                raise ValueError("Japanese speech synthesis requires a configured voice")
            kokoro = self._kokoro
            if kokoro is None:
                raise RuntimeError("Kokoro model is not initialized")
            await self.start_tts_usage_metrics(text)
            phonemes, _ = await asyncio.to_thread(self._japanese_g2p, text)
            stream = kokoro.create_stream(phonemes, voice=voice, speed=1.0, is_phonemes=True)
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
