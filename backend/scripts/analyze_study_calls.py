"""Compute per-turn latency and false cut-off lower bounds from study evidence.

Usage (from backend/): uv run --env-file .env python scripts/analyze_study_calls.py [OUT_DIR]
Output files are written privately (mode 700). Automatic rates are LOWER BOUNDS only; the real
false cut-off rate needs manual annotation of annotation_sample.csv.
"""

import csv
import json
import os
import random
import statistics
import sys
from pathlib import Path

WINDOWS = (1.0, 2.0, 3.0)
SAMPLE_PER_METHOD = 30
NS = 1_000_000_000


def load_events(text: str) -> list[dict]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def analyze_events(events: list[dict]) -> list[dict]:
    """Return one row per EOT decision. All offsets are server-clock seconds."""
    events = sorted(events, key=lambda e: e.get("offset_ns", 0))
    vad_starts = [
        e["offset_ns"] for e in events if e.get("type") == "vad" and e["state"] == "start"
    ]
    first_assistant_audio = [
        e["offset_ns"] for e in events if e.get("type") == "audio" and e.get("role") == "assistant"
    ]
    playbacks = [
        e for e in events
        if e.get("type") == "client_audio" and e.get("event") == "remote_audio_playback_started"
    ]
    clock = next((e for e in events if e.get("type") == "call_clock"), None)
    rows = []
    vad_stop = None
    for e in events:
        if e.get("type") == "vad" and e["state"] == "stop":
            vad_stop = e["offset_ns"]
        if e.get("type") != "eot":
            continue
        eot = e["offset_ns"]
        bot = next((t for t in first_assistant_audio if t >= eot), None)
        resumed_after = next((t for t in vad_starts if t > eot), None)
        row = {
            "turn_index": e.get("turn_index"),
            "method": e.get("method"),
            "eot_source": e.get("source"),
            "probability": e.get("probability"),
            "vad_stop_s": None if vad_stop is None else vad_stop / NS,
            "eot_s": eot / NS,
            "server_audio_s": None if bot is None else bot / NS,
            "latency_vad_to_server_audio_s": (
                None if bot is None or vad_stop is None else (bot - vad_stop) / NS
            ),
            "phone_playback_s": None,
            "latency_vad_to_phone_s": None,
        }
        for window in WINDOWS:
            # Resumption measured from the user's speech restarting after the EOT decision.
            row[f"user_resumed_within_{int(window)}s"] = (
                resumed_after is not None and (resumed_after - eot) / NS <= window
            )
        row["overlaps_tutor_audio"] = (
            bot is not None and resumed_after is not None and resumed_after >= bot
        )
        if clock is not None and bot is not None:
            estimate = _phone_time(playbacks, clock, bot)
            if estimate is not None:
                row["phone_playback_s"] = estimate
                if vad_stop is not None:
                    row["latency_vad_to_phone_s"] = estimate - vad_stop / NS
        rows.append(row)
    return rows


def _phone_time(playbacks, clock, bot_ns):
    """Earliest phone playback event at or after server audio, mapped to server offsets.

    Uses server receive time (includes network delay), so this is an upper estimate.
    """
    base = clock["wall_utc_ns"] - clock["offset_ns"]
    for e in playbacks:
        at = e["server_received_utc_ns"] - base
        if at >= bot_ns:
            return at / NS
    return None


def summarize(rows: list[dict]) -> list[dict]:
    out = []
    for method in sorted({r["method"] for r in rows}):
        mine = [r for r in rows if r["method"] == method]
        lat = sorted(
            r["latency_vad_to_server_audio_s"]
            for r in mine
            if r["latency_vad_to_server_audio_s"] is not None
        )
        summary = {
            "method": method,
            "turns": len(mine),
            "median_latency_s": statistics.median(lat) if lat else None,
            "p90_latency_s": lat[min(len(lat) - 1, int(len(lat) * 0.9))] if lat else None,
        }
        for window in WINDOWS:
            key = f"user_resumed_within_{int(window)}s"
            summary[f"false_cutoff_lower_bound_T{int(window)}s"] = (
                sum(r[key] for r in mine) / len(mine) if mine else None
            )
        out.append(summary)
    return out


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("")
        return
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    path.chmod(0o600)


def main() -> None:
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from app.evidence import EvidenceStore
    from app.models import StudyAttempt, StudyEvidence

    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else ".study-analysis")
    out_dir.mkdir(mode=0o700, exist_ok=True)
    store = EvidenceStore.from_env()
    if store is None:
        raise SystemExit("Study evidence storage is not configured")
    engine = create_engine(os.environ["DATABASE_URL_UNPOOLED"])
    rows = []
    with Session(engine) as db:
        for attempt, evidence in db.execute(
            select(StudyAttempt, StudyEvidence).join(
                StudyEvidence, StudyEvidence.attempt_id == StudyAttempt.id
            )
        ):
            result = store.events(attempt.id, evidence.manifest_sha256)
            if result is None:
                continue
            for row in analyze_events(load_events(result)):
                rows.append({"attempt_id": str(attempt.id), **row})
    write_csv(out_dir / "turns.csv", rows)
    write_csv(out_dir / "summary.csv", summarize(rows))
    rng = random.Random(0)
    sample = []
    for method in sorted({r["method"] for r in rows}):
        mine = [r for r in rows if r["method"] == method]
        for r in rng.sample(mine, min(SAMPLE_PER_METHOD, len(mine))):
            sample.append(
                {
                    "attempt_id": r["attempt_id"],
                    "turn_index": r["turn_index"],
                    "method": method,
                    "user_audio_offset_s": r["vad_stop_s"],
                    "annotation": "",  # complete | incomplete (manual)
                }
            )
    write_csv(out_dir / "annotation_sample.csv", sample)
    print(
        "WARNING: user_resumed_* rates are lower bounds on false cut-off; "
        "annotate annotation_sample.csv for the true rate."
    )


if __name__ == "__main__":
    main()
