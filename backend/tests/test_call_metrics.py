import asyncio
import importlib.util
import json
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from pipecat.frames.frames import (  # noqa: E402
    BotStartedSpeakingFrame,
    MetricsFrame,
    TranscriptionFrame,
    UserStoppedSpeakingFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.metrics.metrics import TTFBMetricsData, TurnMetricsData  # noqa: E402
from pipecat.observers.base_observer import FramePushed  # noqa: E402
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.call_metrics import StudyMetricsObserver  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import Base  # noqa: E402
from app.monitor import CallMonitor  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "analyze", Path(__file__).parents[1] / "scripts" / "analyze_study_calls.py"
)
analyze = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analyze)


class Recorder:
    closed = False

    def __init__(self):
        self.events = []

    async def event(self, event):
        self.events.append(event)


def push(observer, frame):
    data = FramePushed(source=None, destination=None, frame=frame, direction=None, timestamp=0)
    return observer.on_push_frame(data)


def test_observer_records_turn_events_once_and_updates_monitor():
    evidence, monitor = Recorder(), CallMonitor()
    call_id = uuid4()
    state = monitor.start(call_id, "adaptive")
    observer = StudyMetricsObserver(evidence, "adaptive", state)

    async def run():
        await push(observer, VADUserStartedSpeakingFrame())
        stop = VADUserStoppedSpeakingFrame(stop_secs=0.2)
        await push(observer, stop)
        await push(observer, stop)  # same frame seen on a second hop
        await push(
            observer,
            MetricsFrame(
                data=[
                    TurnMetricsData(
                        processor="t", is_complete=False, probability=0.2, e2e_processing_time_ms=1
                    ),
                    TTFBMetricsData(processor="stt", value=0.12),
                ]
            ),
        )
        await push(observer, TranscriptionFrame(text="abc", user_id="u", timestamp=""))
        await push(observer, UserStoppedSpeakingFrame())
        await push(observer, UserStoppedSpeakingFrame())  # broadcast twin, distinct frame id
        await push(observer, BotStartedSpeakingFrame())

    asyncio.run(run())
    types = [(e["type"], e.get("state") or e.get("source")) for e in evidence.events]
    assert types == [
        ("vad", "start"),
        ("vad", "stop"),
        ("ttfb", None),
        ("stt_final", None),
        ("eot", "timeout"),
        ("bot_speaking", "start"),
    ]
    assert evidence.events[3]["chars"] == 3
    assert state.turns == 1 and state.last_eot_source == "timeout"
    assert state.last_latency_ms is not None
    assert "text" not in json.dumps(monitor.snapshot())


def test_analysis_latency_and_resumption_lower_bounds():
    s = 1_000_000_000
    events = [
        {"type": "call_clock", "offset_ns": 0, "wall_utc_ns": 100 * s},
        {"type": "vad", "offset_ns": 1 * s, "state": "stop"},
        {
            "type": "eot",
            "offset_ns": 1 * s,
            "method": "fixed",
            "source": "silence",
            "turn_index": 1,
        },
        {"type": "vad", "offset_ns": int(2.5 * s), "state": "start"},
        {"type": "audio", "offset_ns": 3 * s, "role": "assistant"},
        {
            "type": "client_audio",
            "event": "remote_audio_playback_started",
            "offset_ns": 4 * s,
            "server_received_utc_ns": 103_500_000_000,
        },
    ]
    [row] = analyze.analyze_events(events)
    assert row["latency_vad_to_server_audio_s"] == 2
    assert row["user_resumed_within_1s"] is False
    assert row["user_resumed_within_2s"] is True
    assert row["overlaps_tutor_audio"] is None  # no bot_speaking events in this evidence
    assert row["latency_vad_to_phone_s"] == 2.5
    summary = analyze.summarize([row])[0]
    assert summary["false_cutoff_lower_bound_T2s"] == 1


def test_monitor_requires_token_and_hides_when_unset(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    app = create_app(engine, study_starter=None)
    sessionmaker(engine)
    with TestClient(app) as client:
        monkeypatch.delenv("MONITOR_TOKEN", raising=False)
        assert client.get("/v1/monitor/calls").status_code == 404
        assert client.get("/monitor").status_code == 404
        monkeypatch.setenv("MONITOR_TOKEN", "secret")
        assert client.get("/v1/monitor/calls").status_code == 401
        denied = client.get("/v1/monitor/calls", headers={"Authorization": "Bearer nope"})
        assert denied.status_code == 401
        ok = client.get("/v1/monitor/calls", headers={"Authorization": "Bearer secret"})
        assert ok.status_code == 200 and ok.json() == {"calls": []}
        page = client.get("/monitor")
        assert page.status_code == 200
        # Relative fetch keeps working behind a path-prefixed proxy.
        assert 'fetch("v1/monitor/calls"' in page.text


def test_analysis_drops_duplicate_eot_and_uses_bot_speaking_for_overlap():
    s = 1_000_000_000

    def vad(t, state):
        return {"type": "vad", "offset_ns": int(t * s), "state": state}

    def bot(t, state):
        return {"type": "bot_speaking", "offset_ns": int(t * s), "state": state}

    eot = {"type": "eot", "method": "adaptive", "source": "smart_turn"}
    events = [
        vad(1, "stop"),
        {**eot, "offset_ns": 1 * s, "turn_index": 1},
        {**eot, "offset_ns": int(1.001 * s), "turn_index": 2, "source": "timeout"},
        bot(3, "start"),
        vad(4, "start"),  # barges in while the tutor is speaking
        bot(5, "stop"),
        vad(9, "start"),
    ]
    rows = analyze.analyze_events(events)
    assert len(rows) == 1 and rows[0]["eot_source"] == "smart_turn"
    assert rows[0]["overlaps_tutor_audio"] is True

    later = events[:5] + [bot(5, "stop"), vad(9, "start")]
    later[4] = vad(7, "start")  # resumes after the tutor finished
    [row] = analyze.analyze_events(later)
    assert row["overlaps_tutor_audio"] is False
