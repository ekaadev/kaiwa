"""Durable study evidence in a private S3 bucket, with private local staging."""

import hashlib
import json
import os
import shutil
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from uuid import UUID

from app.evidence import EvidenceStore, EvidenceWriter

FILES = {"user.wav", "assistant.wav", "events.jsonl", "manifest.json"}
CONTENT_TYPES = {"events.jsonl": "application/x-ndjson", "manifest.json": "application/json"}


class S3EvidenceStore(EvidenceStore):
    def __init__(self, root, retention_days, *, bucket, client=None):
        super().__init__(root, retention_days)
        if not bucket or "/" in bucket:
            raise ValueError("Configure a private study evidence bucket")
        if client is None:
            import boto3
            from botocore.config import Config

            endpoint = os.getenv("AWS_ENDPOINT_URL_S3", "")
            required = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_REGION")
            if not endpoint.startswith("https://") or not all(os.getenv(k) for k in required):
                raise ValueError("Configure Neon S3 endpoint, credentials, and region")
            client = boto3.client(
                "s3",
                endpoint_url=endpoint,
                region_name=os.environ["AWS_REGION"],
                config=Config(
                    signature_version="s3v4",
                    s3={"addressing_style": "path"},
                    retries={"mode": "standard", "max_attempts": 3},
                    connect_timeout=10,
                    read_timeout=30,
                    request_checksum_calculation="when_required",
                    response_checksum_validation="when_required",
                ),
            )
        self.bucket = bucket
        self.client = client
        self.active = set()

    @staticmethod
    def prefix(call_id):
        return f"study/{UUID(str(call_id))}/"

    def begin(self, call_id):
        call_id = UUID(str(call_id))
        writer = S3EvidenceWriter(self, call_id)
        self.active.add(str(call_id))
        return writer

    def publish(self, directory):
        manifest = (directory / "manifest.json").read_bytes()
        details = json.loads(manifest)
        prefix = self.prefix(directory.name)
        # Commit the manifest last, after every track/event upload is acknowledged.
        for name, expected in details["files"].items():
            if name not in FILES - {"manifest.json"}:
                raise RuntimeError("Unexpected evidence file")
            with (directory / name).open("rb") as source:
                self.client.put_object(
                    Bucket=self.bucket,
                    Key=prefix + name,
                    Body=source,
                    ContentLength=expected["bytes"],
                    ContentType=CONTENT_TYPES.get(name, "audio/wav"),
                    Metadata={"sha256": expected["sha256"]},
                )
            head = self.client.head_object(Bucket=self.bucket, Key=prefix + name)
            if (
                head["ContentLength"] != expected["bytes"]
                or head.get("Metadata", {}).get("sha256") != expected["sha256"]
            ):
                raise RuntimeError("Stored evidence integrity check failed")
        digest = hashlib.sha256(manifest).hexdigest()
        self.client.put_object(
            Bucket=self.bucket,
            Key=prefix + "manifest.json",
            Body=manifest,
            ContentType="application/json",
            Metadata={"sha256": digest},
        )
        if self.read(prefix + "manifest.json") != manifest:
            raise RuntimeError("Stored evidence manifest integrity check failed")

    def read(self, key):
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
        except Exception as error:
            code = getattr(error, "response", {}).get("Error", {}).get("Code")
            if code in {"NoSuchKey", "404", "NotFound"}:
                return None
            raise
        try:
            return response["Body"].read()
        finally:
            response["Body"].close()

    def transcript(self, call_id, expected_manifest_sha256=None):
        prefix = self.prefix(call_id)
        manifest = self.read(prefix + "manifest.json")
        if manifest is None:
            return None
        contents = self.read(prefix + "events.jsonl")
        if contents is None:
            raise RuntimeError("Stored evidence is missing events")
        return self.decode_transcript(manifest, contents, expected_manifest_sha256)

    def cleanup(self):
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.retention_days)
        groups = defaultdict(list)
        # Never delete another application's files or an active capture.
        for page in self.client.get_paginator("list_objects_v2").paginate(
            Bucket=self.bucket, Prefix="study/"
        ):
            for item in page.get("Contents", []):
                parts = item["Key"].split("/")
                if len(parts) != 3 or parts[2] not in FILES:
                    continue
                try:
                    call_id = str(UUID(parts[1]))
                except ValueError:
                    continue
                groups[call_id].append(item)
        for call_id, objects in groups.items():
            if call_id in self.active or any(o["LastModified"] >= cutoff for o in objects):
                continue
            # Remove the finalization marker before its referenced files.
            for item in sorted(objects, key=lambda o: not o["Key"].endswith("/manifest.json")):
                self.client.delete_object(Bucket=self.bucket, Key=item["Key"])
        for directory in self.root.iterdir():
            if directory.is_symlink() or not directory.is_dir() or directory.name in self.active:
                continue
            try:
                UUID(directory.name)
                if directory.stat().st_mtime < time.time() - self.retention_days * 86400:
                    shutil.rmtree(directory)
            except (ValueError, FileNotFoundError):
                continue


class S3EvidenceWriter(EvidenceWriter):
    def _finalize(self, reason, media_ms):
        try:
            digest = super()._finalize(reason, media_ms)
            self.store.publish(self.directory)
        except Exception:
            self.failed = True
            (self.directory / "manifest.json").unlink(missing_ok=True)
            raise
        # Finalized evidence is served from Neon even after this container disappears.
        shutil.rmtree(self.directory)
        return digest

    def _close_handles(self):
        try:
            super()._close_handles()
        finally:
            self.store.active.discard(str(self.call_id))
