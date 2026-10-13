"""Compare local CPU/GPU speech inference with synthetic audio; no calls or recordings."""

import argparse
import json
import statistics
import time
from dataclasses import replace
from pathlib import Path

import numpy as np

from app.tutor import TutorConfig, build_tutor_processors


def timed(action, repeats):
    action()  # Warm up kernels separately from measured inference.
    durations = []
    result = None
    for _ in range(repeats):
        started = time.perf_counter()
        result = action()
        durations.append(time.perf_counter() - started)
    return result, round(statistics.median(durations), 3)


def benchmark(output: Path, repeats: int):
    from kokoro_onnx import Kokoro
    from onnxruntime import InferenceSession, SessionOptions

    config = TutorConfig.from_env()
    if config is None:
        raise RuntimeError("Tutor configuration is missing or invalid")
    results = {}
    pipelines = {}
    for mode, device, dtype, provider in (
        ("cpu", "cpu", "int8", "CPUExecutionProvider"),
        ("gpu", "cuda", "float16", "CUDAExecutionProvider"),
    ):
        started = time.perf_counter()
        pipelines[mode] = build_tutor_processors(
            replace(
                config,
                whisper_device=device,
                whisper_compute_type=dtype,
                kokoro_execution_provider=provider,
            )
        )
        pipeline = pipelines[mode]
        analyzer = pipeline[2]._user_turn_controller._user_turn_strategies.stop[0]._turn_analyzer
        results[mode] = {
            "pipeline_load_seconds": round(time.perf_counter() - started, 3),
            "whisper_device": pipeline[1]._model.model.device,
            "whisper_compute_type": pipeline[1]._model.model.compute_type,
            "kokoro_providers": pipeline[4]._kokoro.sess.get_providers(),
            "smart_turn_providers": analyzer._session.get_providers(),
            "vad_providers": pipeline[
                0
            ]._vad_controller._vad_analyzer._model.session.get_providers(),
        }
        assert results[mode]["whisper_device"] == device
        assert results[mode]["kokoro_providers"][0] == provider
        assert results[mode]["smart_turn_providers"] == ["CPUExecutionProvider"]
        assert results[mode]["vad_providers"] == ["CPUExecutionProvider"]

    # Profile real CUDA node execution, rather than only reporting available providers.
    options = SessionOptions()
    options.enable_profiling = True
    options.profile_file_prefix = str(output.parent / "kokoro-cuda-profile")
    tts_gpu = pipelines["gpu"][4]
    providers = tts_gpu._kokoro.sess.get_providers()
    provider_options = tts_gpu._kokoro.sess.get_provider_options()
    session = InferenceSession(
        str(config.kokoro_model_path),
        sess_options=options,
        providers=[(p, provider_options[p]) for p in providers],
    )
    session.disable_fallback()
    tts_gpu._kokoro = Kokoro.from_session(session, str(config.kokoro_voices_path))
    text = "こんにちは。今日はどんなことを話したいですか。"
    phonemes, _ = pipelines["cpu"][4]._japanese_g2p(text)
    samples, rate = pipelines["cpu"][4]._kokoro.create(
        phonemes,
        voice="jf_alpha",
        is_phonemes=True,
    )
    audio = np.interp(
        np.arange(int(len(samples) * 16000 / rate)) * rate / 16000,
        np.arange(len(samples)),
        samples,
    ).astype(np.float32)
    for mode, pipeline in pipelines.items():

        def synthesize():
            return pipeline[4]._kokoro.create(phonemes, voice="jf_alpha", is_phonemes=True)

        def transcribe():
            segments, info = pipeline[1]._model.transcribe(audio, beam_size=1)
            return {"language": info.language, "text": "".join(s.text for s in segments)}

        generated, seconds = timed(synthesize, repeats)
        results[mode]["tts"] = {
            "median_seconds": seconds,
            "audio_seconds": round(len(generated[0]) / generated[1], 3),
            "peak": float(np.max(np.abs(generated[0]))),
        }
        transcription, seconds = timed(transcribe, repeats)
        results[mode]["stt"] = {"median_seconds": seconds, **transcription}
        assert transcription["language"] == "ja" and transcription["text"].strip()
        assert results[mode]["tts"]["peak"] > 0.01

    profile = json.loads(Path(session.end_profiling()).read_text())
    counts = {}
    for event in profile:
        provider = event.get("args", {}).get("provider")
        if event.get("cat") == "Node" and provider:
            counts[provider] = counts.get(provider, 0) + 1
    results["kokoro_profile_node_events"] = counts
    assert counts.get("CUDAExecutionProvider", 0) > 0, "No Kokoro CUDA nodes executed"
    results["repeats"] = repeats
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(json.dumps(results, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    benchmark(args.output, args.repeats)
