"""Read Wispr Flow's iPhone Core Data transcription table."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

COCOA_EPOCH = datetime(2001, 1, 1, tzinfo=UTC)
TABLE = "ZTRANSCRIPTION"
KNOWN_COLUMNS = (
    "Z_PK",
    "ZID",
    "ZSTARTDATE",
    "ZENDDATE",
    "ZSTATUS",
    "ZTRANSCRIPTORIGIN",
    "ZAPPBUNDLEID",
    "ZAUDIOFILENAME",
    "ZASRTEXT",
    "ZLLMTEXT",
    "ZTRANSCRIPTIONTEXT",
)


class DatabaseError(Exception):
    """The extracted Wispr database cannot be read."""


@dataclass(frozen=True, slots=True)
class Transcript:
    """One row from ``ZTRANSCRIPTION``."""

    primary_key: int
    identifier: str
    start_cocoa: float | None
    end_cocoa: float | None
    start_at: datetime | None
    end_at: datetime | None
    status: str | None
    transcription_origin: str | None
    app_bundle_id: str | None
    audio_filename: str | None
    audio_found: bool
    asr_text: str | None
    llm_text: str | None
    transcription_text: str | None
    final_text: str | None

    @property
    def final_text_source(self) -> str | None:
        if self.transcription_text:
            return "transcription_text"
        if self.llm_text:
            return "llm_text"
        if self.asr_text:
            return "asr_text"
        return None

    def as_record(self, database_path: Path) -> dict[str, object]:
        return {
            "source": "iphone-database",
            "source_table": TABLE,
            "source_database": str(database_path),
            "primary_key": self.primary_key,
            "id": self.identifier,
            "start_cocoa": self.start_cocoa,
            "end_cocoa": self.end_cocoa,
            "start_at": self.start_at.isoformat() if self.start_at else None,
            "end_at": self.end_at.isoformat() if self.end_at else None,
            "status": self.status,
            "transcription_origin": self.transcription_origin,
            "app_bundle_id": self.app_bundle_id,
            "audio_filename": self.audio_filename,
            "audio_found": self.audio_found,
            "asr_text": self.asr_text,
            "llm_text": self.llm_text,
            "transcription_text": self.transcription_text,
            "final_text": self.final_text,
            "final_text_source": self.final_text_source,
        }


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _cocoa(value: Any) -> tuple[float | None, datetime | None]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None, None
    seconds = float(value)
    return seconds, COCOA_EPOCH + timedelta(seconds=seconds)


def _connection(path: Path) -> sqlite3.Connection:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise DatabaseError(f"database does not exist: {path}")
    quoted = quote(str(path), safe="/")
    try:
        connection = sqlite3.connect(
            f"file:{quoted}?immutable=1", uri=True, isolation_level=None
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = 1")
        return connection
    except sqlite3.Error as error:
        raise DatabaseError(f"cannot open database {path}: {error}") from error


def _quote_identifier(identifier: str) -> str:
    if not re.fullmatch(r"[A-Z0-9_]+", identifier):
        raise DatabaseError(f"unexpected SQLite identifier: {identifier!r}")
    return f'"{identifier}"'


def read_transcriptions(
    database_path: Path,
    *,
    audio_resolver: Callable[[str | None], Path | None] | None = None,
) -> tuple[Transcript, ...]:
    """Read every transcription row, preserving source values and priority."""
    connection = _connection(database_path)
    try:
        try:
            available = {
                str(row["name"])
                for row in connection.execute(f'PRAGMA table_info("{TABLE}")')
            }
            if "Z_PK" not in available:
                raise DatabaseError(f"{TABLE} has no Z_PK column")
            selected = [column for column in KNOWN_COLUMNS if column in available]
            expressions = [
                f"{_quote_identifier(column)} AS {_quote_identifier(column)}"
                for column in selected
            ]
            for column in KNOWN_COLUMNS:
                if column not in available:
                    expressions.append(f"NULL AS {_quote_identifier(column)}")
            rows = connection.execute(
                f'SELECT {", ".join(expressions)} FROM "{TABLE}" '
                "ORDER BY ZSTARTDATE, Z_PK"
            ).fetchall()
        except sqlite3.Error as error:
            raise DatabaseError(f"cannot read {TABLE}: {error}") from error
    finally:
        connection.close()

    result: list[Transcript] = []
    for row in rows:
        start_cocoa, start_at = _cocoa(row["ZSTARTDATE"])
        end_cocoa, end_at = _cocoa(row["ZENDDATE"])
        audio_filename = _text(row["ZAUDIOFILENAME"])
        asr_text = _text(row["ZASRTEXT"])
        llm_text = _text(row["ZLLMTEXT"])
        transcription_text = _text(row["ZTRANSCRIPTIONTEXT"])
        final_text = transcription_text or llm_text or asr_text
        audio_path = audio_resolver(audio_filename) if audio_resolver else None
        primary_key = int(row["Z_PK"])
        result.append(
            Transcript(
                primary_key=primary_key,
                identifier=_text(row["ZID"]) or f"pk-{primary_key}",
                start_cocoa=start_cocoa,
                end_cocoa=end_cocoa,
                start_at=start_at,
                end_at=end_at,
                status=_text(row["ZSTATUS"]),
                transcription_origin=_text(row["ZTRANSCRIPTORIGIN"]),
                app_bundle_id=_text(row["ZAPPBUNDLEID"]),
                audio_filename=audio_filename,
                audio_found=audio_path is not None,
                asr_text=asr_text,
                llm_text=llm_text,
                transcription_text=transcription_text,
                final_text=final_text,
            )
        )
    return tuple(result)


def _markdown_fence(text: str) -> str:
    runs = [len(match.group(0)) for match in re.finditer(r"`+", text)]
    return "`" * max(3, (max(runs) + 1) if runs else 3)


def render_markdown(records: tuple[Transcript, ...], database_path: Path) -> str:
    """Render readable transcripts while keeping raw text unmodified."""
    lines = [
        "# Wispr Flow iPhone transcripts",
        "",
        f"Source database: `{database_path}`",
        f"Records: {len(records)}",
        f"Records with text: {sum(record.final_text is not None for record in records)}",
        "",
    ]
    for number, record in enumerate(records, start=1):
        started = record.start_at.isoformat() if record.start_at else "undated"
        lines.extend(
            [
                f"## {number:03d}, {started}",
                "",
                f"- ID: `{record.identifier}`",
                f"- Status: `{record.status or ''}`",
                f"- App: `{record.app_bundle_id or ''}`",
                f"- Audio: `{record.audio_filename or ''}`",
                f"- Audio found: `{str(record.audio_found).lower()}`",
                "",
            ]
        )
        if record.final_text is None:
            lines.extend(["_No transcription text stored._", ""])
        else:
            fence = _markdown_fence(record.final_text)
            lines.extend([fence, record.final_text.rstrip("\n"), fence, ""])
    return "\n".join(lines)
