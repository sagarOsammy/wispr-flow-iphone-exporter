from __future__ import annotations

import sqlite3
from pathlib import Path

from wispr_flow_iphone_exporter.backup import IPhoneBackup


def test_manifest_resolves_sharded_payload(tmp_path: Path) -> None:
    file_id = "a" * 40
    shard = tmp_path / file_id[:2]
    shard.mkdir()
    payload = shard / file_id
    payload.write_bytes(b"database")
    manifest = tmp_path / "Manifest.db"
    connection = sqlite3.connect(manifest)
    connection.execute(
        "CREATE TABLE Files (fileID TEXT, domain TEXT, relativePath TEXT, flags INTEGER)"
    )
    connection.execute(
        "INSERT INTO Files VALUES (?, ?, ?, ?)",
        (file_id, "AppDomain-com.wispr.flowapp", "Documents/database.sqlite", 1),
    )
    connection.commit()
    connection.close()

    backup = IPhoneBackup(tmp_path)
    resolved = backup.app_file("Documents/database.sqlite")
    assert resolved == payload
    assert resolved.read_bytes() == b"database"
