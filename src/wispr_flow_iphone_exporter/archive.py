"""Write a privacy-conscious, provenance-preserving extraction archive."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Iterable

from . import __version__
from .database import Transcript, render_markdown
from .segb import ActionFile, SegbState, action_rows

FILE_MODE = 0o600
DIR_MODE = 0o700


def secure_mkdir(path: Path) -> None:
    """Create every missing directory as owner-only."""
    missing: list[Path] = []
    cursor = path
    while not cursor.exists():
        missing.append(cursor)
        if cursor.parent == cursor:
            break
        cursor = cursor.parent
    for target in reversed(missing):
        target.mkdir(mode=DIR_MODE, exist_ok=True)
        try:
            os.chmod(target, DIR_MODE)
        except OSError:
            pass


def _write_bytes(path: Path, data: bytes) -> None:
    secure_mkdir(path.parent)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    try:
        os.chmod(temporary, FILE_MODE)
    except OSError:
        pass
    temporary.replace(path)


def _write_text(path: Path, text: str) -> None:
    _write_bytes(path, text.encode("utf-8"))


def _write_json(path: Path, value: object) -> None:
    _write_text(path, json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n")


def _write_ndjson(path: Path, rows: Iterable[object]) -> None:
    body = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
    _write_text(path, body)


def _copy_secure(source: Path, destination: Path) -> str:
    """Copy bytes without inheriting a source file's permissions."""
    data = source.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    _write_bytes(destination, data)
    return digest


def write_archive(
    *,
    output_root: Path,
    backup_root: Path,
    database_path: Path | None,
    transcripts: tuple[Transcript, ...],
    action_files: tuple[ActionFile, ...],
    dry_run: bool = False,
) -> dict[str, object]:
    """Write Markdown, NDJSON, manifests, and raw SEGB provenance."""
    output_root = output_root.expanduser().resolve()
    db_path = database_path.expanduser().resolve() if database_path else None
    action = action_rows(action_files)
    with_text = sum(item.final_text is not None for item in transcripts)
    written = sum(row["state"] == SegbState.WRITTEN.name.lower() for row in action)
    deleted = sum(row["state"] == SegbState.DELETED.name.lower() for row in action)
    unknown = len(action) - written - deleted
    payload_bytes = sum(int(row["payload_bytes"]) for row in action)
    nonzero_payload_bytes = sum(int(row["nonzero_payload_bytes"]) for row in action)

    if not dry_run:
        if transcripts and db_path:
            _write_text(
                output_root / "iphone" / "transcripts.md",
                render_markdown(transcripts, db_path),
            )
            records = [item.as_record(db_path) for item in transcripts]
            _write_ndjson(output_root / "raw" / "iphone" / "transcriptions.ndjson", records)
            _write_json(
                output_root / "raw" / "iphone" / "transcriptions-manifest.json",
                {
                    "source": "iphone-database",
                    "database": str(db_path),
                    "rows": len(transcripts),
                    "with_text": with_text,
                    "without_text": len(transcripts) - with_text,
                    "audio_matches": sum(item.audio_found for item in transcripts),
                },
            )

        if action_files:
            raw_root = output_root / "raw" / "iphone" / "action-transcript"
            for item in action_files:
                _copy_secure(
                    item.source_path,
                    raw_root / "segb" / f"{item.file_id}.segb",
                )
                for entry in item.entries:
                    if entry.payload:
                        _write_bytes(
                            raw_root / "payloads" / f"{item.file_id}-{entry.index}.bin",
                            entry.payload,
                        )
            _write_ndjson(raw_root / "records.ndjson", action)
            _write_json(
                raw_root / "manifest.json",
                {
                    "source": "iphone-action-transcript",
                    "backup_root": str(backup_root.expanduser().resolve()),
                    "files": len(action_files),
                    "entries": len(action),
                    "written": written,
                    "deleted": deleted,
                    "unknown": unknown,
                    "payload_bytes": payload_bytes,
                    "nonzero_payload_bytes": nonzero_payload_bytes,
                },
            )

        _write_json(
            output_root / "index.json",
            {
                "schema_version": 1,
                "tool": "wispr-flow-iphone-exporter",
                "tool_version": __version__,
                "backup_root": str(backup_root.expanduser().resolve()),
                "database": str(db_path) if db_path else None,
                "iphone_transcriptions": {
                    "rows": len(transcripts),
                    "with_text": with_text,
                    "without_text": len(transcripts) - with_text,
                    "audio_matches": sum(item.audio_found for item in transcripts),
                },
                "iphone_action_transcripts": {
                    "files": len(action_files),
                    "entries": len(action),
                    "written": written,
                    "deleted": deleted,
                    "unknown": unknown,
                    "payload_bytes": payload_bytes,
                    "nonzero_payload_bytes": nonzero_payload_bytes,
                },
            },
        )

    return {
        "output": str(output_root),
        "database": str(db_path) if db_path else None,
        "transcriptions": len(transcripts),
        "transcribed": with_text,
        "without_text": len(transcripts) - with_text,
        "audio_matches": sum(item.audio_found for item in transcripts),
        "action_files": len(action_files),
        "action_entries": len(action),
        "action_written": written,
        "action_deleted": deleted,
        "action_unknown": unknown,
        "payload_bytes": payload_bytes,
        "nonzero_payload_bytes": nonzero_payload_bytes,
        "dry_run": dry_run,
    }
