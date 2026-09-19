from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from wispr_flow_iphone_exporter.archive import write_archive
from wispr_flow_iphone_exporter.database import Transcript


def test_write_archive_creates_readable_and_raw_outputs(tmp_path: Path) -> None:
    record = Transcript(
        primary_key=1,
        identifier="example-id",
        start_cocoa=0.0,
        end_cocoa=1.0,
        start_at=datetime(2001, 1, 1, tzinfo=UTC),
        end_at=datetime(2001, 1, 1, 0, 0, 1, tzinfo=UTC),
        status="done",
        transcription_origin="test",
        app_bundle_id="com.example.app",
        audio_filename="example.wav",
        audio_found=False,
        asr_text="asr text",
        llm_text=None,
        transcription_text=None,
        final_text="asr text",
    )

    report = write_archive(
        output_root=tmp_path / "output",
        backup_root=tmp_path / "backup",
        database_path=tmp_path / "backup" / "database.sqlite",
        transcripts=(record,),
        action_files=tuple(),
    )

    assert report["transcriptions"] == 1
    assert (tmp_path / "output" / "index.json").is_file()
    assert (tmp_path / "output" / "iphone" / "transcripts.md").read_text()
    assert (tmp_path / "output" / "raw" / "iphone" / "transcriptions.ndjson").is_file()
