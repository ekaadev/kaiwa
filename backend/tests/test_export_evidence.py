import asyncio
import importlib.util
import json
import stat
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.evidence import EvidenceStore

spec = importlib.util.spec_from_file_location(
    "export_evidence", Path(__file__).parents[1] / "scripts" / "export_study_evidence.py"
)
export = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export)


async def record(writer):
    frame = SimpleNamespace(audio=b"\0\0" * 320, sample_rate=16000, num_channels=1)
    await writer.frame("user", frame)
    await writer.frame("assistant", frame)
    await writer.event({"type": "eot", "method": "fixed", "source": "silence"})
    return await writer.finalize("normal", 120000)


def make(tmp_path):
    store = EvidenceStore(tmp_path / "store", 30)
    call_id = uuid4()
    digest = asyncio.run(record(store.begin(call_id)))
    row = {
        "attempt_id": str(call_id),
        "participant_id": "p1",
        "session_ordinal": 1,
        "method": "fixed",
        "status": "completed",
        "end_reason": "normal",
        "media_ms": 120000,
        "evidence_saved_at": "2026-10-14T00:00:00+00:00",
        "manifest_sha256": digest,
    }
    return store, row


def test_export_verifies_writes_private_files_and_audits(tmp_path):
    store, row = make(tmp_path)
    out = tmp_path / "out"
    done, failed = export.run_export(store, [row], out, who="researcher@lab")
    assert done == [row["attempt_id"]] and failed == []
    folder = out / row["attempt_id"]
    assert {p.name for p in folder.iterdir()} == {
        "user.wav", "assistant.wav", "events.jsonl", "manifest.json",
    }
    assert stat.S_IMODE(out.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in folder.iterdir())
    audit = json.loads((out / "access.log").read_text().splitlines()[-1])
    assert audit["by"] == "researcher@lab" and audit["exported"] == [row["attempt_id"]]
    index = (out / "index.csv").read_text()
    assert row["attempt_id"] in index and "resume" not in index.lower()


def test_tampered_evidence_is_not_exported_and_is_audited_as_failed(tmp_path):
    store, row = make(tmp_path)
    with (store.root / row["attempt_id"] / "user.wav").open("ab") as handle:
        handle.write(b"tampered")
    out = tmp_path / "out"
    done, failed = export.run_export(store, [row], out, who="x@y")
    assert done == [] and len(failed) == 1 and "RuntimeError" in failed[0]
    assert not (out / row["attempt_id"]).exists()
    assert json.loads((out / "access.log").read_text())["failed"] == failed


def test_wrong_manifest_checksum_and_missing_evidence_are_rejected(tmp_path):
    store, row = make(tmp_path)
    with pytest.raises(RuntimeError, match="manifest integrity"):
        store.fetch(row["attempt_id"], "0" * 64)
    assert store.fetch(str(uuid4())) is None


def test_export_never_overwrites_an_existing_attempt_folder(tmp_path):
    store, row = make(tmp_path)
    out = tmp_path / "out"
    export.run_export(store, [row], out, who="x@y")
    done, failed = export.run_export(store, [row], out, who="x@y")
    assert done == [] and "FileExistsError" in failed[0]
