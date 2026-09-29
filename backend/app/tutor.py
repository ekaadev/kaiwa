"""Portable, opt-in speech services for anonymous Japanese practice calls."""

import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen

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

    @classmethod
    def from_env(cls) -> "TutorConfig | None":
        whisper = os.getenv("TUTOR_WHISPER_PATH", "").strip()
        kokoro = os.getenv("TUTOR_KOKORO_MODEL_PATH", "").strip()
        voices = os.getenv("TUTOR_KOKORO_VOICES_PATH", "").strip()
        llm = os.getenv("TUTOR_LLM_BASE_URL", "").strip().rstrip("/")
        if not (whisper and kokoro and voices and llm.startswith(("http://", "https://"))):
            return None
        return cls(
            Path(whisper),
            Path(kokoro),
            Path(voices),
            llm,
            os.getenv("TUTOR_LLM_API_KEY", "local"),
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
    from pipecat.services.kokoro.tts import KokoroTTSService
    from pipecat.services.openai.llm import OpenAILLMService
    from pipecat.services.whisper.stt import WhisperSTTService
    from pipecat.transcriptions.language import Language
    from pipecat.turns.user_stop import (
        SpeechTimeoutUserTurnStopStrategy,
        TurnAnalyzerUserTurnStopStrategy,
    )
    from pipecat.turns.user_turn_strategies import UserTurnStrategies

    if eot_method == "adaptive":
        vad_stop_secs = 0.2
        stop = TurnAnalyzerUserTurnStopStrategy(
            turn_analyzer=LocalSmartTurnAnalyzerV3(params=SmartTurnParams(stop_secs=3.0))
        )
    elif eot_method == "fixed":
        vad_stop_secs = 0.7
        stop = SpeechTimeoutUserTurnStopStrategy(user_speech_timeout=0)
    else:
        raise ValueError("Unsupported turn method")

    vad = VADProcessor(vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=vad_stop_secs)))
    stt = WhisperSTTService(
        settings=WhisperSTTService.Settings(model=str(config.whisper_path), language=None),
        device="cpu",
        compute_type="int8",
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
    tts = KokoroTTSService(
        model_path=str(config.kokoro_model_path),
        voices_path=str(config.kokoro_voices_path),
        settings=KokoroTTSService.Settings(voice=KOKORO_VOICE, language=Language.JA),
    )
    aggregators = LLMContextAggregatorPair(
        LLMContext(messages=[{"role": "system", "content": TUTOR_INSTRUCTIONS}]),
        user_params=LLMUserAggregatorParams(user_turn_strategies=UserTurnStrategies(stop=[stop])),
    )
    return [vad, stt, aggregators.user(), llm, tts, aggregators.assistant()]
