"""Portable, opt-in speech services for anonymous Japanese practice calls."""

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

QWEN_MODEL = "Qwen/Qwen3-1.7B"
KOKORO_VOICE = "jf_alpha"

TUTOR_INSTRUCTIONS = (
    "You are a friendly Japanese conversation tutor. The learner may speak in English "
    "or Japanese. Understand either language and always reply in natural Japanese. "
    "Keep every reply to 1–3 short sentences and ask at most one question. "
    "Do not translate the learner's words unless they ask you to. /no_think"
)


@dataclass(frozen=True)
class TutorConfig:
    whisper_path: Path
    kokoro_model_path: Path
    kokoro_voices_path: Path
    llm_base_url: str
    llm_api_key: str = "local"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    kokoro_execution_provider: str = "CPUExecutionProvider"

    @classmethod
    def from_env(cls) -> "TutorConfig | None":
        whisper = os.getenv("TUTOR_WHISPER_PATH", "").strip()
        kokoro = os.getenv("TUTOR_KOKORO_MODEL_PATH", "").strip()
        voices = os.getenv("TUTOR_KOKORO_VOICES_PATH", "").strip()
        llm = os.getenv("TUTOR_LLM_BASE_URL", "").strip().rstrip("/")
        if not (whisper and kokoro and voices and llm.startswith(("http://", "https://"))):
            return None
        device = os.getenv("TUTOR_WHISPER_DEVICE", "cpu").strip()
        compute_type = os.getenv(
            "TUTOR_WHISPER_COMPUTE_TYPE", "float16" if device == "cuda" else "int8"
        ).strip()
        provider = os.getenv("TUTOR_KOKORO_EXECUTION_PROVIDER", "CPUExecutionProvider").strip()
        if (
            device not in {"cpu", "cuda"}
            or compute_type not in {"int8", "float16", "int8_float16", "float32"}
            or (device == "cpu" and compute_type in {"float16", "int8_float16"})
            or provider not in {"CPUExecutionProvider", "CUDAExecutionProvider"}
        ):
            return None
        return cls(
            Path(whisper),
            Path(kokoro),
            Path(voices),
            llm,
            os.getenv("TUTOR_LLM_API_KEY", "local"),
            device,
            compute_type,
            provider,
        )

    def assets_present(self) -> bool:
        return (
            self.whisper_path.is_dir()
            and (self.whisper_path / "model.bin").is_file()
            and self.kokoro_model_path.is_file()
            and self.kokoro_voices_path.is_file()
        )

    async def ready(self) -> bool:
        """Preflight only; pipeline construction and bot join remain authoritative."""
        if not self.assets_present():
            return False
        try:
            return await asyncio.wait_for(asyncio.to_thread(self._model_served), timeout=5)
        except Exception:
            return False

    def _model_served(self) -> bool:
        request = Request(
            f"{self.llm_base_url}/models",
            headers={"Authorization": f"Bearer {self.llm_api_key}"},
        )
        with urlopen(request, timeout=4) as response:
            models = json.load(response).get("data", [])
        return any(model.get("id") == QWEN_MODEL for model in models)


def build_tutor_processors(config: TutorConfig, *, eot_method: str = "adaptive"):
    """Construct one independent per-call Pipecat pipeline (no research storage)."""
    from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
    from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
    from pipecat.audio.vad.silero import SileroVADAnalyzer
    from pipecat.audio.vad.vad_analyzer import VADParams
    from pipecat.processors.aggregators.llm_context import LLMContext
    from pipecat.processors.aggregators.llm_response_universal import (
        LLMContextAggregatorPair,
        LLMUserAggregatorParams,
    )
    from pipecat.processors.audio.vad_processor import VADProcessor
    from pipecat.services.openai.llm import OpenAILLMService
    from pipecat.transcriptions.language import Language
    from pipecat.turns.user_stop import (
        SpeechTimeoutUserTurnStopStrategy,
        TurnAnalyzerUserTurnStopStrategy,
    )
    from pipecat.turns.user_turn_strategies import UserTurnStrategies

    from app.japanese_tts import JapaneseKokoroTTSService
    from app.whisper_stt import LocalWhisperSTTService

    if eot_method == "adaptive":
        vad_stop_secs = 0.2
        turn_analyzer = LocalSmartTurnAnalyzerV3(params=SmartTurnParams(stop_secs=3.0))
        # Pipecat 0.0.108 has no provider constructor argument for Smart Turn.
        # Keep this per-session setting explicit even when CUDA ORT is installed.
        if turn_analyzer._session.get_providers() != ["CPUExecutionProvider"]:
            turn_analyzer._session.set_providers(["CPUExecutionProvider"])
        stop = TurnAnalyzerUserTurnStopStrategy(turn_analyzer=turn_analyzer)
    elif eot_method == "fixed":
        vad_stop_secs = 0.7
        stop = SpeechTimeoutUserTurnStopStrategy(user_speech_timeout=0)
    else:
        raise ValueError("Unsupported turn method")

    vad = VADProcessor(vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=vad_stop_secs)))
    stt = LocalWhisperSTTService(
        settings=LocalWhisperSTTService.Settings(model=str(config.whisper_path), language=None),
        device=config.whisper_device,
        compute_type=config.whisper_compute_type,
    )
    llm = OpenAILLMService(
        api_key=config.llm_api_key,
        base_url=config.llm_base_url,
        settings=OpenAILLMService.Settings(
            model=QWEN_MODEL,
            max_tokens=120,
            extra={"extra_body": {"chat_template_kwargs": {"enable_thinking": False}}},
        ),
    )
    tts = JapaneseKokoroTTSService(
        model_path=str(config.kokoro_model_path),
        voices_path=str(config.kokoro_voices_path),
        execution_provider=config.kokoro_execution_provider,
        settings=JapaneseKokoroTTSService.Settings(voice=KOKORO_VOICE, language=Language.JA),
    )
    aggregators = LLMContextAggregatorPair(
        LLMContext(messages=[{"role": "system", "content": TUTOR_INSTRUCTIONS}]),
        user_params=LLMUserAggregatorParams(user_turn_strategies=UserTurnStrategies(stop=[stop])),
    )
    return [vad, stt, aggregators.user(), llm, tts, aggregators.assistant()]


def _warm_whisper(config: TutorConfig) -> None:
    import numpy as np
    from faster_whisper import WhisperModel

    model = WhisperModel(
        str(config.whisper_path),
        device=config.whisper_device,
        compute_type=config.whisper_compute_type,
    )
    try:
        segments, _ = model.transcribe(np.zeros(16000, dtype=np.float32))
        list(segments)
    finally:
        del model


def _warm_kokoro(config: TutorConfig) -> None:
    from pipecat.transcriptions.language import Language

    from app.japanese_tts import JapaneseKokoroTTSService

    service = JapaneseKokoroTTSService(
        model_path=str(config.kokoro_model_path),
        voices_path=str(config.kokoro_voices_path),
        execution_provider=config.kokoro_execution_provider,
        settings=JapaneseKokoroTTSService.Settings(voice=KOKORO_VOICE, language=Language.JA),
    )
    try:
        phonemes, _ = service._japanese_g2p("こんにちは。")
        service._kokoro.create(phonemes, voice=KOKORO_VOICE, speed=1.0, is_phonemes=True)
    finally:
        service._kokoro = None


def _warm_smart_turn(config: TutorConfig) -> None:
    from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
    from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3

    analyzer = LocalSmartTurnAnalyzerV3(params=SmartTurnParams(stop_secs=3.0))
    if analyzer._session.get_providers() != ["CPUExecutionProvider"]:
        analyzer._session.set_providers(["CPUExecutionProvider"])


def _warm_llm(config: TutorConfig) -> None:
    body = json.dumps(
        {
            "model": QWEN_MODEL,
            "max_tokens": 1,
            "messages": [
                {"role": "system", "content": TUTOR_INSTRUCTIONS},
                {"role": "user", "content": "こんにちは。"},
            ],
            "chat_template_kwargs": {"enable_thinking": False},
        }
    ).encode()
    request = Request(
        f"{config.llm_base_url}/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {config.llm_api_key}",
            "Content-Type": "application/json",
        },
    )
    with urlopen(request, timeout=60) as response:
        response.read()


# Sequential on purpose: each model is released before the next loads, so warm-up never holds more
# GPU memory than one call does.
_STEPS = (
    ("whisper", _warm_whisper),
    ("kokoro", _warm_kokoro),
    ("smart_turn", _warm_smart_turn),
    ("llm", _warm_llm),
)


async def warm_up(config: TutorConfig) -> dict[str, dict]:
    """Run one throwaway inference per model so the first real call skips one-time costs.

    One-time costs are CUDA/cuDNN initialisation, kernel compilation, and cold file caches. Models
    are still constructed per call, so this does not remove per-call model loading. A failing
    step is recorded and never stops the others or the API.
    """
    if not config.assets_present():
        return {}
    results: dict[str, dict] = {}
    for name, step in _STEPS:
        started = time.monotonic()
        try:
            await asyncio.to_thread(step, config)
            results[name] = {"ok": True, "seconds": round(time.monotonic() - started, 2)}
        except Exception as error:
            results[name] = {
                "ok": False,
                "seconds": round(time.monotonic() - started, 2),
                "error": type(error).__name__,
            }
    logger.info("Tutor warm-up finished: %s", results)
    return results
