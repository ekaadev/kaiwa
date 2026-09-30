"""Private, streaming study evidence with atomic, fsynced final manifests."""

import asyncio
import hashlib
import json
import os
import shutil
import time
import wave
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID


class EvidenceStore:
    def __init__(self, root: Path, retention_days: int):
        if not root.is_absolute() or not 1 <= retention_days <= 3650:
            raise ValueError("Configure an absolute evidence path and retention days (1–3650)")
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if root.is_symlink() or root.stat().st_mode & 0o077:
            raise ValueError("Evidence directory must be private (chmod 700) and not a symlink")
        self.root = root.resolve()
        self.retention_days = retention_days

    @classmethod
    def from_env(cls):
        directory = os.getenv("STUDY_EVIDENCE_DIR", "")
        days = os.getenv("STUDY_RETENTION_DAYS", "")
        if not directory or not days:
            return None
        try:
            return cls(Path(directory), int(days))
        except (ValueError, OSError):
            return None

    def begin(self, call_id):
        return EvidenceWriter(self, call_id)

    def cleanup(self):
        cutoff = time.time() - self.retention_days * 86400
        for directory in self.root.iterdir():
            if directory.is_symlink() or not directory.is_dir():
                continue
            try:
                # Call directories are UUIDs only; never follow caller-provided paths.
                UUID(directory.name)
                manifest = directory / "manifest.json"
                stamp = manifest.stat().st_mtime if manifest.exists() else directory.stat().st_mtime
                if stamp < cutoff:
                    shutil.rmtree(directory)
            except (ValueError, FileNotFoundError):
                continue

    def transcript(self, call_id, expected_manifest_sha256=None):
        directory = self.root / str(call_id)
        manifest = directory / "manifest.json"
        if not manifest.is_file():
            return None
        manifest_bytes = manifest.read_bytes()
        if (
            expected_manifest_sha256 is not None
            and hashlib.sha256(manifest_bytes).hexdigest() != expected_manifest_sha256
        ):
            raise RuntimeError("Evidence manifest integrity check failed")
        data = json.loads(manifest_bytes)
        expected = data["files"]["events.jsonl"]["sha256"]
        contents = (directory / "events.jsonl").read_bytes()
        if hashlib.sha256(contents).hexdigest() != expected:
            raise RuntimeError("Evidence integrity check failed")
        events = [json.loads(line) for line in contents.splitlines()]
        turns = [
            {key: e[key] for key in ("sequence", "role", "text", "timestamp")}
            for e in events
            if e["type"] == "turn"
        ]
        return {"turns": turns, "finalized": True}


class EvidenceWriter:
    def __init__(self, store, call_id):
        self.store = store
        self.call_id = call_id
        self.directory = store.root / str(call_id)
        self.directory.mkdir(mode=0o700)
        self.events = (self.directory / "events.jsonl").open("xb")
        self.audio = {}
        self.formats = {}
        self.samples = {"user": 0, "assistant": 0}
        self.lock = asyncio.Lock()
        self.closed = False
        self.failed = False
        self.started_ns = time.monotonic_ns()

    async def _io(self, operation, *args):
        # Wait for an in-flight file write even if transport teardown cancels its caller.
        operation_task = asyncio.create_task(asyncio.to_thread(operation, *args))
        try:
            return await asyncio.shield(operation_task)
        except asyncio.CancelledError:
            await operation_task
            raise

    async def event(self, event):
        async with self.lock:
            if self.closed:
                raise RuntimeError("Evidence is already closed")
            entry = {"offset_ns": time.monotonic_ns() - self.started_ns, **event}
            try:
                await self._io(
                    self.events.write, (json.dumps(entry, ensure_ascii=False) + "\n").encode()
                )
            except Exception:
                self.failed = True
                raise

    async def frame(self, role, frame):
        async with self.lock:
            if self.closed:
                raise RuntimeError("Evidence is already closed")
            try:
                await self._io(self._write_audio, role, frame)
            except Exception:
                self.failed = True
                raise

    def _write_audio(self, role, frame):
        audio_format = (frame.sample_rate, frame.num_channels)
        if role not in self.audio:
            output = wave.open(str(self.directory / f"{role}.wav"), "wb")
            output.setnchannels(frame.num_channels)
            output.setsampwidth(2)
            output.setframerate(frame.sample_rate)
            self.audio[role] = output
            self.formats[role] = audio_format
        if self.formats[role] != audio_format:
            raise RuntimeError("Audio format changed within a call")
        self.audio[role].writeframesraw(frame.audio)
        count = len(frame.audio) // (2 * frame.num_channels)
        self.events.write(
            (
                json.dumps(
                    {
                        "type": "audio",
                        "role": role,
                        "offset_ns": time.monotonic_ns() - self.started_ns,
                        "sample_start": self.samples[role],
                        "samples": count,
                        "sample_rate": frame.sample_rate,
                    }
                )
                + "\n"
            ).encode()
        )
        self.samples[role] += count

    async def finalize(self, reason, media_ms):
        async with self.lock:
            if self.closed:
                raise RuntimeError("Evidence is already closed")
            self.closed = True
            try:
                return await self._io(self._finalize, reason, media_ms)
            finally:
                await self._io(self._close_handles)

    def _close_handles(self):
        for output in self.audio.values():
            try:
                output.close()
            except Exception:
                pass
        try:
            self.events.close()
        except Exception:
            pass

    def _finalize(self, reason, media_ms):
        for output in self.audio.values():
            output.close()
        self.events.flush()
        os.fsync(self.events.fileno())
        self.events.close()
        if self.failed:
            raise RuntimeError("Evidence capture failed")
        # Both tracks must exist and contain received/output PCM to count as final evidence.
        if self.samples["user"] == 0 or self.samples["assistant"] == 0:
            raise RuntimeError("Evidence is missing an audio track")
        files = {}
        for name in ("user.wav", "assistant.wav", "events.jsonl"):
            path = self.directory / name
            with path.open("rb") as source:
                digest = hashlib.file_digest(source, "sha256").hexdigest()
                os.fsync(source.fileno())
            files[name] = {"sha256": digest, "bytes": path.stat().st_size}
        manifest = {
            "version": 1,
            "call_id": str(self.call_id),
            "reason": reason,
            "media_ms": media_ms,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "retention_days": self.store.retention_days,
            "files": files,
            "audio_semantics": (
                "user server-received; assistant server-output; not proof of audible phone playback"
            ),
        }
        contents = json.dumps(manifest, ensure_ascii=False).encode()
        pending = self.directory / "manifest.pending"
        with pending.open("xb") as output:
            output.write(contents)
            output.flush()
            os.fsync(output.fileno())
        pending.replace(self.directory / "manifest.json")
        descriptor = os.open(self.directory, os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return hashlib.sha256(contents).hexdigest()
