"""Export verified study evidence for authorized staff, from the server.

Usage (from backend/, on the server, with the runtime environment loaded):
    python scripts/export_study_evidence.py --all [--out DIR]
    python scripts/export_study_evidence.py --attempt UUID [--attempt UUID ...] [--out DIR]

Every exported file is checked against the manifest checksums stored in the database; a mismatch
aborts that attempt. Output is private (directory 700, files 600), never overwritten, and each run
is appended to access.log with the operating-system user. No participant tokens are exported.
The export is NOT encrypted: keep it on encrypted storage and delete it when analysis is done.
"""

import argparse
import csv
import getpass
import json
import os
import socket
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_OUT = ".study-export"
INDEX_FIELDS = (
    "attempt_id",
    "participant_id",
    "session_ordinal",
    "method",
    "status",
    "end_reason",
    "media_ms",
    "evidence_saved_at",
    "files",
)


def export_attempt(store, row: dict, out_dir: Path) -> dict:
    """Write one attempt's verified files under out_dir/<attempt_id>/ and return its index row."""
    target = out_dir / row["attempt_id"]
    if target.exists():
        raise FileExistsError(f"{target} already exists; refusing to overwrite")
    bundle = store.fetch(row["attempt_id"], row["manifest_sha256"])
    if bundle is None:
        raise LookupError("No final evidence for this attempt")
    manifest, files = bundle
    target.mkdir(mode=0o700)
    for name, contents in files.items():
        path = target / name
        path.write_bytes(contents)
        path.chmod(0o600)
    manifest_path = target / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    manifest_path.chmod(0o600)
    return {key: row.get(key) for key in INDEX_FIELDS if key != "files"} | {
        "files": ";".join(sorted(files))
    }


def append_index(out_dir: Path, rows: list[dict]) -> None:
    path = out_dir / "index.csv"
    new = not path.exists()
    with path.open("a", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=INDEX_FIELDS)
        if new:
            writer.writeheader()
        writer.writerows(rows)
    path.chmod(0o600)


def append_audit(out_dir: Path, attempts: list[str], failed: list[str], who: str | None = None):
    entry = {
        "at": datetime.now(timezone.utc).isoformat(),
        "by": who or f"{getpass.getuser()}@{socket.gethostname()}",
        "exported": attempts,
        "failed": failed,
    }
    path = out_dir / "access.log"
    with path.open("a") as handle:
        handle.write(json.dumps(entry) + "\n")
    path.chmod(0o600)


def run_export(store, rows: list[dict], out_dir: Path, who: str | None = None) -> tuple[list, list]:
    out_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    done, failed, index = [], [], []
    for row in rows:
        try:
            index.append(export_attempt(store, row, out_dir))
            done.append(row["attempt_id"])
        except Exception as error:
            failed.append(f"{row['attempt_id']}: {type(error).__name__}")
    append_index(out_dir, index)
    append_audit(out_dir, done, failed, who)
    return done, failed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--attempt", action="append", default=[], metavar="UUID")
    parser.add_argument("--all", action="store_true", help="export every attempt with evidence")
    parser.add_argument("--out", default=DEFAULT_OUT)
    args = parser.parse_args()
    if not args.all and not args.attempt:
        parser.error("choose --all or at least one --attempt")

    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from app.evidence import EvidenceStore
    from app.models import StudyAttempt, StudyEvidence, StudySession

    store = EvidenceStore.from_env()
    if store is None:
        raise SystemExit("Study evidence storage is not configured")
    engine = create_engine(os.environ["DATABASE_URL_UNPOOLED"])
    query = (
        select(StudyAttempt, StudySession, StudyEvidence)
        .join(StudySession, StudySession.id == StudyAttempt.session_id)
        .join(StudyEvidence, StudyEvidence.attempt_id == StudyAttempt.id)
    )
    if args.attempt:
        query = query.where(StudyAttempt.id.in_(args.attempt))
    with Session(engine) as db:
        rows = [
            {
                "attempt_id": str(attempt.id),
                "participant_id": str(session.participant_id),
                "session_ordinal": session.ordinal,
                "method": session.method,
                "status": attempt.status,
                "end_reason": attempt.end_reason,
                "media_ms": attempt.media_ms,
                "evidence_saved_at": attempt.evidence_saved_at,
                "manifest_sha256": evidence.manifest_sha256,
            }
            for attempt, session, evidence in db.execute(query)
        ]
    if not rows:
        raise SystemExit("No matching attempts with final evidence")
    done, failed = run_export(store, rows, Path(args.out))
    print(f"Exported {len(done)} attempt(s) to {args.out}; {len(failed)} failed")
    for item in failed:
        print(f"  FAILED {item}")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
