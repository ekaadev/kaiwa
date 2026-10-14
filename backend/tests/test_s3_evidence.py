import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.evidence import EvidenceStore
from app.s3_evidence import S3EvidenceStore


class MissingObject(Exception):
    response = {"Error": {"Code": "NoSuchKey"}}


class Storage:
    def __init__(self, failure=None):
        self.objects = {}
        self.operations = []
        self.failure = failure

    def put_object(self, *, Key, Body, Metadata=None, **kwargs):
        self.operations.append(("put", Key))
        if self.failure == Key.rsplit("/", 1)[-1]:
            raise RuntimeError("Upload failed")
        body = Body.read() if hasattr(Body, "read") else Body
        self.objects[Key] = {
            "body": body,
            "metadata": Metadata or {},
            "time": datetime.now(timezone.utc),
        }

    def head_object(self, *, Key, **kwargs):
        obj = self.objects[Key]
        return {"ContentLength": len(obj["body"]), "Metadata": obj["metadata"]}

    def get_object(self, *, Key, **kwargs):
        if Key not in self.objects:
            raise MissingObject()
        return {"Body": BytesIO(self.objects[Key]["body"])}

    def delete_object(self, *, Key, **kwargs):
        self.operations.append(("delete", Key))
        self.objects.pop(Key, None)

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return self

    def paginate(self, *, Prefix, **kwargs):
        # Exercise pagination, not only a single-page bucket.
        for key, value in self.objects.copy().items():
            if key.startswith(Prefix):
                yield {"Contents": [{"Key": key, "LastModified": value["time"]}]}


async def record(writer):
    frame = SimpleNamespace(audio=b"\0\0" * 320, sample_rate=16000, num_channels=1)
    await writer.frame("user", frame)
    await writer.frame("assistant", frame)
    await writer.event(
        {"type": "turn", "sequence": 1, "role": "user", "text": "Hello", "timestamp": "now"}
    )
    return await writer.finalize("normal", 120000)


def test_neon_upload_commits_manifest_last_and_recovers_without_local_cache(tmp_path):
    client = Storage()
    store = S3EvidenceStore(tmp_path / "capture", 30, bucket="kaiwa", client=client)
    call_id = uuid4()
    writer = store.begin(call_id)
    digest = asyncio.run(record(writer))
    assert not writer.directory.exists()
    assert store.active == set()
    puts = [key for operation, key in client.operations if operation == "put"]
    assert puts[-1] == store.prefix(call_id) + "manifest.json"
    manifest = client.objects[puts[-1]]["body"]
    assert hashlib.sha256(manifest).hexdigest() == digest
    assert json.loads(manifest)["retention_days"] == 30
    restarted = S3EvidenceStore(tmp_path / "new-container", 30, bucket="kaiwa", client=client)
    assert restarted.transcript(call_id, digest)["turns"][0]["text"] == "Hello"
    with pytest.raises(RuntimeError, match="manifest integrity"):
        restarted.transcript(call_id, "0" * 64)
    client.objects[store.prefix(call_id) + "events.jsonl"]["body"] += b"tampered"
    with pytest.raises(RuntimeError, match="integrity"):
        restarted.transcript(call_id, digest)


@pytest.mark.parametrize("failure", ["user.wav", "events.jsonl", "manifest.json"])
def test_failed_cloud_upload_cannot_finalize_evidence(tmp_path, failure):
    client = Storage(failure)
    store = S3EvidenceStore(tmp_path, 30, bucket="kaiwa", client=client)
    writer = store.begin(uuid4())
    with pytest.raises(RuntimeError, match="Upload failed"):
        asyncio.run(record(writer))
    assert writer.closed and writer.failed and writer.events.closed
    assert not (writer.directory / "manifest.json").exists()
    assert store.transcript(writer.call_id) is None
    assert store.active == set()


def test_retention_preserves_recent_active_and_unrelated_objects(tmp_path):
    client = Storage()
    store = S3EvidenceStore(tmp_path, 30, bucket="kaiwa", client=client)
    expired, recent, active = uuid4(), uuid4(), uuid4()
    for call_id in (expired, recent, active):
        asyncio.run(record(store.begin(call_id)))
    old = datetime.now(timezone.utc) - timedelta(days=31)
    for key, obj in client.objects.items():
        if str(expired) in key or str(active) in key:
            obj["time"] = old
    store.active.add(str(active))
    client.objects["study/not-a-call/user.wav"] = {"body": b"keep", "time": old}
    client.objects[f"study/{expired}/other.json"] = {"body": b"keep", "time": old}
    client.objects["practice/user.wav"] = {"body": b"keep", "time": old}
    store.cleanup()
    assert store.transcript(expired) is None
    assert store.transcript(recent) is not None
    assert store.transcript(active) is not None
    assert "study/not-a-call/user.wav" in client.objects
    assert f"study/{expired}/other.json" in client.objects
    assert "practice/user.wav" in client.objects
    deleted = [key for operation, key in client.operations if operation == "delete"]
    assert deleted[0].endswith("manifest.json")


def test_missing_cloud_credentials_disable_study_storage_without_local_fallback(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("STUDY_EVIDENCE_DIR", str(tmp_path))
    monkeypatch.setenv("STUDY_RETENTION_DAYS", "30")
    monkeypatch.setenv("STUDY_EVIDENCE_BUCKET", "kaiwa")
    monkeypatch.delenv("AWS_ENDPOINT_URL_S3", raising=False)
    assert EvidenceStore.from_env() is None


def test_cloud_fetch_returns_only_verified_files(tmp_path):
    client = Storage()
    store = S3EvidenceStore(tmp_path / "capture", 30, bucket="kaiwa", client=client)
    call_id = uuid4()
    digest = asyncio.run(record(store.begin(call_id)))
    manifest, files = store.fetch(call_id, digest)
    assert set(files) == {"user.wav", "assistant.wav", "events.jsonl"}
    assert manifest["media_ms"] == 120000
    client.objects[store.prefix(call_id) + "assistant.wav"]["body"] += b"x"
    with pytest.raises(RuntimeError, match="assistant.wav"):
        store.fetch(call_id, digest)
    assert store.fetch(uuid4()) is None
