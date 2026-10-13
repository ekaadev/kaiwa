import asyncio
import json
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.tutor import QWEN_MODEL, TutorConfig, build_tutor_processors


class FakeSession:
    def __init__(self):
        self.providers = ["CPUExecutionProvider"]
        self.fallback_disabled = False

    def set_providers(self, providers):
        self.providers = providers

    def get_providers(self):
        return [
            provider[0] if isinstance(provider, tuple) else provider for provider in self.providers
        ]

    def disable_fallback(self):
        self.fallback_disabled = True


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


@pytest.mark.parametrize(
    "device,compute_type,provider",
    [
        ("cpu", "int8", "CPUExecutionProvider"),
        ("cuda", "float16", "CUDAExecutionProvider"),
    ],
)
def test_tutor_uses_multilingual_whisper_japanese_voice_and_separate_eot(
    tmp_path, monkeypatch, device, compute_type, provider
):
    pytest.importorskip("faster_whisper")
    from pipecat.audio.turn.smart_turn.base_smart_turn import BaseSmartTurn
    from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
    from pipecat.services.kokoro import tts as kokoro_module
    from pipecat.services.whisper.stt import WhisperSTTService
    from pipecat.turns.user_stop import (
        SpeechTimeoutUserTurnStopStrategy,
        TurnAnalyzerUserTurnStopStrategy,
    )

    from app import japanese_tts

    def fake_turn_init(self, **kwargs):
        BaseSmartTurn.__init__(self, **kwargs)
        self._session = FakeSession()
        self._session.providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]

    monkeypatch.setattr(LocalSmartTurnAnalyzerV3, "__init__", fake_turn_init)

    monkeypatch.setattr(WhisperSTTService, "_load", lambda self: None)
    monkeypatch.setattr(kokoro_module, "Kokoro", lambda *args: SimpleNamespace(sess=FakeSession()))
    monkeypatch.setattr(kokoro_module, "_ensure_model_files", lambda *args: None)
    monkeypatch.setattr(japanese_tts, "JAG2P", lambda **kwargs: object())
    config = TutorConfig(
        tmp_path / "small",
        tmp_path / "kokoro",
        tmp_path / "voices",
        "http://localhost/v1",
        whisper_device=device,
        whisper_compute_type=compute_type,
        kokoro_execution_provider=provider,
    )

    adaptive = build_tutor_processors(config)
    fixed = build_tutor_processors(config, eot_method="fixed")

    for pipeline in (adaptive, fixed):
        stt = pipeline[1]
        llm = pipeline[3]
        tts = pipeline[4]
        assert stt._settings.model == str(config.whisper_path)
        assert stt._settings.language is None  # Autodetect English/Japanese; no forced translation.
        assert stt._device == device
        assert stt._compute_type == compute_type
        assert llm._settings.model == QWEN_MODEL
        assert tts._settings.language == "ja"
        assert tts._settings.voice == "jf_alpha"
        assert tts._kokoro.sess.get_providers()[0] == provider
        assert tts._kokoro.sess.fallback_disabled
        assert pipeline[0]._vad_controller._vad_analyzer._model.session.get_providers() == [
            "CPUExecutionProvider"
        ]

    adaptive_stop = adaptive[2]._user_turn_controller._user_turn_strategies.stop[0]
    fixed_stop = fixed[2]._user_turn_controller._user_turn_strategies.stop[0]
    assert isinstance(adaptive_stop, TurnAnalyzerUserTurnStopStrategy)
    assert isinstance(adaptive_stop._turn_analyzer, LocalSmartTurnAnalyzerV3)
    assert adaptive_stop._turn_analyzer.params.stop_secs == 3.0
    assert adaptive_stop._turn_analyzer._session.get_providers() == ["CPUExecutionProvider"]
    assert isinstance(fixed_stop, SpeechTimeoutUserTurnStopStrategy)
    assert fixed[0]._vad_controller._vad_analyzer.params.stop_secs == 0.7

    with pytest.raises(ValueError, match="Unsupported turn method"):
        build_tutor_processors(config, eot_method="unknown")


def test_japanese_tts_passes_japanese_phonemes_to_kokoro(tmp_path, monkeypatch):
    pytest.importorskip("misaki.ja")
    import numpy as np
    from pipecat.frames.frames import TTSAudioRawFrame
    from pipecat.services.kokoro import tts as kokoro_module

    from app import japanese_tts

    calls = []

    class FakeKokoro:
        sess = FakeSession()

        async def create_stream(self, text, **kwargs):
            calls.append((text, kwargs))
            yield np.array([0.0, 0.25, -0.25], dtype=np.float32), 24000

    monkeypatch.setattr(kokoro_module, "Kokoro", lambda *args: FakeKokoro())
    monkeypatch.setattr(kokoro_module, "_ensure_model_files", lambda *args: None)
    monkeypatch.setattr(japanese_tts, "JAG2P", lambda **kwargs: lambda text: ("koɲɲiʨiwa", []))
    service = japanese_tts.JapaneseKokoroTTSService(
        model_path=str(tmp_path / "kokoro"),
        voices_path=str(tmp_path / "voices"),
        sample_rate=24000,
        settings=japanese_tts.JapaneseKokoroTTSService.Settings(voice="jf_alpha"),
    )

    async def scenario():
        # Pipeline StartFrame normally supplies this output rate.
        service._sample_rate = 24000
        frames = [frame async for frame in service.run_tts("こんにちは", "test-context")]
        assert calls == [("koɲɲiʨiwa", {"voice": "jf_alpha", "speed": 1.0, "is_phonemes": True})]
        assert len(frames) == 1
        assert isinstance(frames[0], TTSAudioRawFrame)
        assert frames[0].context_id == "test-context"
        assert len(frames[0].audio) == 6

    asyncio.run(scenario())


def test_gpu_runtime_configuration_defaults_and_validation(monkeypatch):
    for name in ("WHISPER_PATH", "KOKORO_MODEL_PATH", "KOKORO_VOICES_PATH"):
        monkeypatch.setenv("TUTOR_" + name, "/model")
    monkeypatch.setenv("TUTOR_LLM_BASE_URL", "http://localhost/v1")
    for name in ("WHISPER_DEVICE", "WHISPER_COMPUTE_TYPE", "KOKORO_EXECUTION_PROVIDER"):
        monkeypatch.delenv("TUTOR_" + name, raising=False)
    cpu = TutorConfig.from_env()
    assert cpu.whisper_device == "cpu"
    assert cpu.whisper_compute_type == "int8"
    assert cpu.kokoro_execution_provider == "CPUExecutionProvider"
    monkeypatch.setenv("TUTOR_WHISPER_DEVICE", "cuda")
    monkeypatch.setenv("TUTOR_KOKORO_EXECUTION_PROVIDER", "CUDAExecutionProvider")
    gpu = TutorConfig.from_env()
    assert gpu.whisper_compute_type == "float16"
    monkeypatch.setenv("TUTOR_WHISPER_DEVICE", "cpu")
    monkeypatch.setenv("TUTOR_WHISPER_COMPUTE_TYPE", "float16")
    assert TutorConfig.from_env() is None
    monkeypatch.setenv("TUTOR_WHISPER_COMPUTE_TYPE", "int8")
    monkeypatch.setenv("TUTOR_KOKORO_EXECUTION_PROVIDER", "unknown")
    assert TutorConfig.from_env() is None


def test_kokoro_requested_cuda_cannot_silently_fall_back_to_cpu(tmp_path, monkeypatch):
    pytest.importorskip("misaki.ja")
    from pipecat.services.kokoro import tts as kokoro_module

    from app import japanese_tts

    session = FakeSession()
    monkeypatch.setattr(session, "set_providers", lambda providers: None)
    monkeypatch.setattr(kokoro_module, "Kokoro", lambda *args: SimpleNamespace(sess=session))
    monkeypatch.setattr(kokoro_module, "_ensure_model_files", lambda *args: None)
    with pytest.raises(RuntimeError, match="execution provider is unavailable"):
        japanese_tts.JapaneseKokoroTTSService(
            model_path=str(tmp_path / "kokoro"),
            voices_path=str(tmp_path / "voices"),
            execution_provider="CUDAExecutionProvider",
        )


@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_speech_cleanup_releases_native_models_even_if_parent_cleanup_fails(
    monkeypatch, cleanup_fails
):
    pytest.importorskip("misaki.ja")
    from pipecat.services.kokoro.tts import KokoroTTSService
    from pipecat.services.whisper.stt import WhisperSTTService

    from app.japanese_tts import JapaneseKokoroTTSService
    from app.whisper_stt import LocalWhisperSTTService

    async def scenario():
        for service_type, parent, attribute in (
            (LocalWhisperSTTService, WhisperSTTService, "_model"),
            (JapaneseKokoroTTSService, KokoroTTSService, "_kokoro"),
        ):
            cleanup = AsyncMock(
                side_effect=RuntimeError("cleanup failed") if cleanup_fails else None
            )
            monkeypatch.setattr(parent, "cleanup", cleanup)
            service = service_type.__new__(service_type)
            setattr(service, attribute, object())
            if cleanup_fails:
                with pytest.raises(RuntimeError, match="cleanup failed"):
                    await service.cleanup()
            else:
                await service.cleanup()
            cleanup.assert_awaited_once()
            assert getattr(service, attribute) is None

    asyncio.run(scenario())
