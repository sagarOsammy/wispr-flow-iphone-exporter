"""Decode the public SEGB v2 envelope used by iOS system streams."""

from __future__ import annotations

import hashlib
import plistlib
import struct
import zlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import IntEnum
from pathlib import Path
from typing import Any

from .backup import IPhoneBackup

MAGIC = b"SEGB"
HEADER_SIZE = 32
ENTRY_HEADER_SIZE = 8
TRAILER_ENTRY_SIZE = 16
MAX_SEGB_BYTES = 512 * 1024 * 1024
ACTION_DOMAIN = "SysContainerDomain-com.apple.linkd"
ACTION_PREFIX = "ActionTranscript/com.wispr.flowapp/"


class SegbError(Exception):
    """A SEGB file is invalid or cannot be read."""


class SegbState(IntEnum):
    """Known entry states in the SEGB v2 trailer."""

    WRITTEN = 1
    DELETED = 3
    UNKNOWN = 4

    @classmethod
    def label(cls, value: int) -> str:
        try:
            return cls(value).name.lower()
        except ValueError:
            return f"unknown_{value}"


@dataclass(frozen=True, slots=True)
class SegbEntry:
    """One logical entry in a SEGB container."""

    index: int
    data_start_offset: int
    end_offset: int
    state: int
    created_at: datetime
    stored_crc: int | None
    actual_crc: int | None
    payload: bytes

    @property
    def state_name(self) -> str:
        return SegbState.label(self.state)

    @property
    def crc_passed(self) -> bool | None:
        if self.stored_crc is None or self.actual_crc is None:
            return None
        return self.stored_crc == self.actual_crc

    @property
    def nonzero_payload_bytes(self) -> int:
        return sum(byte != 0 for byte in self.payload)


@dataclass(frozen=True, slots=True)
class ActionFile:
    """A Wispr ActionTranscript SEGB file discovered from Manifest.db."""

    relative_path: str
    file_id: str
    source_path: Path
    event_type: str | None
    header_created_at: datetime
    entries: tuple[SegbEntry, ...]


def cocoa_time(seconds: float) -> datetime:
    """Convert Apple's seconds since 2001-01-01 into UTC."""
    return datetime(2001, 1, 1, tzinfo=UTC) + timedelta(seconds=seconds)


def decode_segb(path: Path) -> tuple[datetime, tuple[SegbEntry, ...]]:
    """Decode a SEGB v2 envelope and return raw entry payloads."""
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise SegbError(f"cannot read SEGB file: {path}: {error}") from error
    if len(raw) > MAX_SEGB_BYTES:
        raise SegbError(f"SEGB file exceeds the safety cap: {path}")
    if len(raw) < HEADER_SIZE or raw[:4] != MAGIC:
        raise SegbError(f"not a SEGB v2 file: {path}")

    entry_count = struct.unpack_from("<I", raw, 4)[0]
    trailer_start = len(raw) - TRAILER_ENTRY_SIZE * entry_count
    if trailer_start < HEADER_SIZE:
        raise SegbError(f"SEGB trailer is outside the file: {path}")
    header_time = cocoa_time(struct.unpack_from("<d", raw, 8)[0])

    trailers: list[tuple[int, int, datetime]] = []
    for index in range(entry_count):
        offset = trailer_start + index * TRAILER_ENTRY_SIZE
        end_offset, state, seconds = struct.unpack_from("<IId", raw, offset)
        trailers.append((end_offset, state, cocoa_time(seconds)))

    entries: list[SegbEntry] = []
    cursor = HEADER_SIZE
    previous: dict[str, Any] | None = None
    for index, (end_offset, state, created_at) in sorted(
        enumerate(trailers), key=lambda item: item[1][0]
    ):
        data_area_size = trailer_start - HEADER_SIZE
        if end_offset > data_area_size:
            raise SegbError(f"SEGB entry ends outside data area: {path}")
        if state == SegbState.UNKNOWN:
            entries.append(
                SegbEntry(
                    index=index,
                    data_start_offset=cursor,
                    end_offset=end_offset,
                    state=state,
                    created_at=created_at,
                    stored_crc=None,
                    actual_crc=None,
                    payload=b"",
                )
            )
            continue
        if previous is not None and end_offset == previous["end_offset"]:
            entries.append(
                SegbEntry(
                    index=index,
                    data_start_offset=previous["start"],
                    end_offset=end_offset,
                    state=state,
                    created_at=created_at,
                    stored_crc=previous["stored_crc"],
                    actual_crc=previous["actual_crc"],
                    payload=previous["payload"],
                )
            )
            continue

        length = end_offset - (cursor - HEADER_SIZE)
        if length < ENTRY_HEADER_SIZE or cursor + length > trailer_start:
            raise SegbError(f"invalid SEGB entry bounds: {path}")
        stored_crc, _unknown = struct.unpack_from("<Ii", raw, cursor)
        payload = raw[cursor + ENTRY_HEADER_SIZE : cursor + length]
        actual_crc = zlib.crc32(payload) & 0xFFFFFFFF
        entry = SegbEntry(
            index=index,
            data_start_offset=cursor,
            end_offset=end_offset,
            state=state,
            created_at=created_at,
            stored_crc=stored_crc,
            actual_crc=actual_crc,
            payload=payload,
        )
        entries.append(entry)
        previous = {
            "end_offset": end_offset,
            "start": cursor,
            "stored_crc": stored_crc,
            "actual_crc": actual_crc,
            "payload": payload,
        }
        cursor += length
        if end_offset % 4:
            cursor += 4 - (end_offset % 4)

    return header_time, tuple(entries)


def _event_type(backup: IPhoneBackup, file_id: str) -> str | None:
    """Read the optional event type from Apple's archived stream metadata."""
    try:
        decoded = plistlib.loads(backup.payload_path(file_id).read_bytes())
    except (OSError, plistlib.InvalidFileException, ValueError):
        return None
    objects = decoded.get("$objects") if isinstance(decoded, dict) else None
    if not isinstance(objects, list):
        return None
    for item in objects:
        if not isinstance(item, dict) or "eventType" not in item:
            continue
        event_uid = item["eventType"]
        if not isinstance(event_uid, plistlib.UID):
            continue
        index = event_uid.data
        if 0 <= index < len(objects) and isinstance(objects[index], str):
            return objects[index]
    return None


def discover_action_files(backup: IPhoneBackup) -> tuple[ActionFile, ...]:
    """Find and decode Wispr ActionTranscript records in the backup."""
    rows = backup.find(
        domain=ACTION_DOMAIN,
        relative_prefix=ACTION_PREFIX,
    )
    rows = tuple(
        row
        for row in rows
        if (row.flags & 1)
        and (
            row.relative_path.startswith(ACTION_PREFIX + "local/")
        or row.relative_path.startswith(ACTION_PREFIX + "tombstone/")
        )
    )
    metadata = backup.first(
        domain=ACTION_DOMAIN,
        relative_path=ACTION_PREFIX.rstrip("/") + "/metadata",
    )
    event_type = _event_type(backup, metadata.file_id) if metadata else None

    result: list[ActionFile] = []
    for row in rows:
        source = backup.payload_path(row)
        header_time, entries = decode_segb(source)
        result.append(
            ActionFile(
                relative_path=row.relative_path,
                file_id=row.file_id,
                source_path=source,
                event_type=event_type,
                header_created_at=header_time,
                entries=entries,
            )
        )
    return tuple(result)


def action_rows(
    files: tuple[ActionFile, ...],
) -> tuple[dict[str, object], ...]:
    """Return JSON-safe provenance rows for decoded SEGB entries."""
    rows: list[dict[str, object]] = []
    for item in files:
        raw_path = f"raw/iphone/action-transcript/segb/{item.file_id}.segb"
        for entry in item.entries:
            rows.append(
                {
                    "source": "iphone-action-transcript",
                    "event_type": item.event_type,
                    "relative_path": item.relative_path,
                    "file_id": item.file_id,
                    "raw_path": raw_path,
                    "entry_index": entry.index,
                    "state": entry.state_name,
                    "state_code": entry.state,
                    "header_created_at": item.header_created_at.isoformat(),
                    "created_at": entry.created_at.isoformat(),
                    "data_start_offset": entry.data_start_offset,
                    "end_offset": entry.end_offset,
                    "payload_bytes": len(entry.payload),
                    "nonzero_payload_bytes": entry.nonzero_payload_bytes,
                    "payload_sha256": hashlib.sha256(entry.payload).hexdigest(),
                    "payload_path": (
                        f"raw/iphone/action-transcript/payloads/"
                        f"{item.file_id}-{entry.index}.bin"
                        if entry.payload
                        else None
                    ),
                    "crc_passed": entry.crc_passed,
                }
            )
    return tuple(rows)
