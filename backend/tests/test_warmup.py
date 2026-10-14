import asyncio

from app import tutor
from app.tutor import TutorConfig, warm_up


def config(tmp_path, present=True):
    whisper = tmp_path / "whisper"
    kokoro = tmp_path / "kokoro.onnx"
    voices = tmp_path / "voices.bin"
    if present:
        whisper.mkdir()
        (whisper / "model.bin").write_bytes(b"x")
        kokoro.write_bytes(b"x")
        voices.write_bytes(b"x")
    return TutorConfig(whisper, kokoro, voices, "http://127.0.0.1:1/v1")


def test_warm_up_runs_each_step_in_order_and_reports_timings(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        tutor,
        "_STEPS",
        tuple((name, lambda c, n=name: calls.append(n)) for name in ("a", "b", "c")),
    )
    results = asyncio.run(warm_up(config(tmp_path)))
    assert calls == ["a", "b", "c"]
    assert all(r["ok"] and r["seconds"] >= 0 for r in results.values())


def test_failing_step_is_recorded_and_does_not_stop_the_rest(tmp_path, monkeypatch):
    calls = []

    def boom(_):
        raise RuntimeError("secret detail must not be reported")

    monkeypatch.setattr(
        tutor, "_STEPS", (("a", boom), ("b", lambda c: calls.append("b")))
    )
    results = asyncio.run(warm_up(config(tmp_path)))
    assert calls == ["b"]
    assert results["a"]["ok"] is False
    assert results["a"]["error"] == "RuntimeError"  # class name only, never the message
    assert results["b"]["ok"] is True


def test_warm_up_is_skipped_when_model_assets_are_missing(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(tutor, "_STEPS", (("a", lambda c: calls.append("a")),))
    assert asyncio.run(warm_up(config(tmp_path, present=False))) == {}
    assert calls == []
