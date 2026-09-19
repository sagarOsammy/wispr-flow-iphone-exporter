from __future__ import annotations

import sqlite3
from pathlib import Path

from wispr_flow_iphone_exporter.database import read_transcriptions, render_markdown


def _database(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE ZTRANSCRIPTION (
            Z_PK INTEGER PRIMARY KEY,
            ZID TEXT,
            ZSTARTDATE REAL,
            ZENDDATE REAL,
            ZSTATUS TEXT,
            ZTRANSCRIPTORIGIN TEXT,
            ZAPPBUNDLEID TEXT,
            ZAUDIOFILENAME TEXT,
            ZASRTEXT TEXT,
            ZLLMTEXT TEXT,
            ZTRANSCRIPTIONTEXT TEXT
        )
        """
    )
    connection.executemany(
        "INSERT INTO ZTRANSCRIPTION VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (1, "first", 0.0, 1.0, "done", "test", "app", "one.wav", "asr", "llm", "final"),
            (2, "second", 2.0, 3.0, "done", "test", "app", "two.wav", "only asr", None, None),
        ],
    )
    connection.commit()
    connection.close()


def test_read_transcriptions_preserves_text_priority_and_audio(tmp_path: Path) -> None:
    database = tmp_path / "database.sqlite"
    _database(database)
    audio = tmp_path / "one.wav"
    audio.write_bytes(b"audio")

    records = read_transcriptions(
        database,
        audio_resolver=lambda filename: audio if filename == "one.wav" else None,
    )

    assert len(records) == 2
    assert records[0].final_text == "final"
    assert records[0].final_text_source == "transcription_text"
    assert records[0].audio_found is True
    assert records[1].final_text == "only asr"
    assert records[1].final_text_source == "asr_text"
    assert records[1].audio_found is False

    markdown = render_markdown(records, database)
    assert "final" in markdown
    assert "only asr" in markdown
