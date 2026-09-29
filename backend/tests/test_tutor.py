import asyncio
import json
from io import BytesIO

import pytest

from app.tutor import QWEN_MODEL, TutorConfig, build_tutor_processors


def test_tutor_requires_all_configuration(monkeypatch):
    for key in (
        "TUTOR_WHISPER_PATH",
        "TUTOR_KOKORO_MODEL_PATH",
        "TUTOR_KOKORO_VOICES_PATH",
        "TUTOR_LLM_BASE_URL",
    ):
        monkeypatch.delenv(key, raising=False)
    assert TutorConfig.from_env() is None


def test_tutor_readiness_requires_files_and_the_exact_qwen_model(tmp_path, monkeypatch):
    from app import tutor

    whisper = tmp_path / "whisper-small"
    whisper.mkdir()
    kokoro = tmp_path / "kokoro.onnx"
    voices = tmp_path / "voices.bin"
    config = TutorConfig(whisper, kokoro, voices, "http://localhost:8000/v1")

    class FakeResponse(BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_):
            self.close()

    offered = ["other-model"]
    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request.full_url, timeout))
        return FakeResponse(json.dumps({"data": [{"id": model} for model in offered]}).encode())

    monkeypatch.setattr(tutor, "urlopen", fake_urlopen)

    async def scenario():
        assert not await config.ready()
        assert requests == []
        (whisper / "model.bin").write_bytes(b"test-only")
        kokoro.write_bytes(b"test-only")
        voices.write_bytes(b"test-only")
        assert not await config.ready()
        offered[:] = [QWEN_MODEL]
        assert await config.ready()
        assert requests[-1] == ("http://localhost:8000/v1/models", 4)

    asyncio.run(scenario())


def test_tutor_uses_multilingual_whisper_japanese_voice_and_separate_eot(tmp_path, monkeypatch):
    pytest.importorskip("faster_whisper")
    from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
    from pipecat.services.kokoro import tts as kokoro_module
    from pipecat.services.whisper.stt import WhisperSTTService
    from pipecat.turns.user_stop import (
        SpeechTimeoutUserTurnStopStrategy,
        TurnAnalyzerUserTurnStopStrategy,
    )

    monkeypatch.setattr(WhisperSTTService, "_load", lambda self: None)
    monkeypatch.setattr(kokoro_module, "Kokoro", lambda *args: object())
    monkeypatch.setattr(kokoro_module, "_ensure_model_files", lambda *args: None)
    config = TutorConfig(tmp_path / "small", tmp_path / "kokoro", tmp_path / "voices", "http://localhost/v1")

    adaptive = build_tutor_processors(config)
    fixed = build_tutor_processors(config, eot_method="fixed")

    for pipeline in (adaptive, fixed):
        stt = pipeline[1]
        llm = pipeline[3]
        tts = pipeline[4]
        assert stt._settings.model == str(config.whisper_path)
        assert stt._settings.language is None  # Autodetect English/Japanese; no forced translation.
        assert llm._settings.model == QWEN_MODEL
        assert tts._settings.language == "ja"
        assert tts._settings.voice == "jf_alpha"

    adaptive_stop = adaptive[2]._user_turn_controller._user_turn_strategies.stop[0]
    fixed_stop = fixed[2]._user_turn_controller._user_turn_strategies.stop[0]
    assert isinstance(adaptive_stop, TurnAnalyzerUserTurnStopStrategy)
    assert isinstance(adaptive_stop._turn_analyzer, LocalSmartTurnAnalyzerV3)
    assert adaptive_stop._turn_analyzer.params.stop_secs == 3.0
    assert isinstance(fixed_stop, SpeechTimeoutUserTurnStopStrategy)
    assert fixed[0]._vad_controller._vad_analyzer.params.stop_secs == 0.7

    with pytest.raises(ValueError, match="Unsupported turn method"):
        build_tutor_processors(config, eot_method="unknown")
