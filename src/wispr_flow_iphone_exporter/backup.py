"""Read a local, decrypted Apple iPhone backup without modifying it."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

BACKUP_FILE_ID_RE = re.compile(r"^[0-9a-f]{40}$")


class BackupError(Exception):
    """The backup is missing, unreadable, or structurally unsafe."""


@dataclass(frozen=True, slots=True)
class BackupFile:
    """One row from an Apple backup ``Manifest.db`` file table."""

    file_id: str
    domain: str
    relative_path: str
    flags: int


class IPhoneBackup:
    """Manifest-backed access to files in one backup directory.

    Apple backups store payloads under two-character shards. ``Manifest.db``
    maps a logical domain and path to the 40-character payload id. All paths
    are validated before they are opened, and symlinks are refused.
    """

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        self.manifest = self.root / "Manifest.db"
        if not self.root.is_dir():
            raise BackupError(f"backup directory does not exist: {self.root}")
        if not self.manifest.is_file():
            raise BackupError(f"Manifest.db is missing from: {self.root}")

    def _connection(self) -> sqlite3.Connection:
        quoted = quote(str(self.manifest), safe="/")
        try:
            connection = sqlite3.connect(
                f"file:{quoted}?immutable=1", uri=True, isolation_level=None
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only = 1")
            return connection
        except sqlite3.Error as error:
            raise BackupError(f"cannot open Manifest.db: {error}") from error

    def find(
        self,
        *,
        domain: str | None = None,
        relative_path: str | None = None,
        relative_prefix: str | None = None,
    ) -> tuple[BackupFile, ...]:
        """Return manifest rows matching the supplied exact or prefix filters."""
        clauses: list[str] = []
        parameters: list[str] = []
        if domain is not None:
            clauses.append("domain = ?")
            parameters.append(domain)
        if relative_path is not None:
            clauses.append("relativePath = ?")
            parameters.append(relative_path)
        if relative_prefix is not None:
            clauses.append("relativePath LIKE ?")
            parameters.append(relative_prefix + "%")
        where = " AND ".join(clauses) or "1 = 1"
        connection = self._connection()
        try:
            try:
                rows = connection.execute(
                    f"SELECT fileID, domain, relativePath, COALESCE(flags, 0) AS flags "
                    f"FROM Files WHERE {where} ORDER BY domain, relativePath, fileID",
                    parameters,
                ).fetchall()
            except sqlite3.Error as error:
                raise BackupError(f"cannot query Manifest.db: {error}") from error
        finally:
            connection.close()
        return tuple(
            BackupFile(
                file_id=str(row["fileID"]),
                domain=str(row["domain"]),
                relative_path=str(row["relativePath"]),
                flags=int(row["flags"] or 0),
            )
            for row in rows
        )

    def first(
        self,
        *,
        domain: str | None = None,
        relative_path: str | None = None,
        relative_prefix: str | None = None,
    ) -> BackupFile | None:
        """Return the first matching manifest row, if one exists."""
        return next(
            iter(
                self.find(
                    domain=domain,
                    relative_path=relative_path,
                    relative_prefix=relative_prefix,
                )
            ),
            None,
        )

    def payload_path(self, item: BackupFile | str) -> Path:
        """Resolve a manifest file id inside the backup root."""
        file_id = item.file_id if isinstance(item, BackupFile) else item
        if not BACKUP_FILE_ID_RE.fullmatch(file_id):
            raise BackupError(f"invalid backup file id: {file_id!r}")
        candidate = self.root / file_id[:2] / file_id
        try:
            if candidate.is_symlink() or not candidate.is_file():
                raise BackupError(f"backup payload is missing: {candidate}")
            resolved = candidate.resolve()
        except OSError as error:
            raise BackupError(f"cannot inspect backup payload {candidate}: {error}") from error
        if resolved != self.root and self.root not in resolved.parents:
            raise BackupError(f"backup payload escapes the backup root: {candidate}")
        return candidate

    def app_file(self, relative_path: str, *, app_container: Path | None = None) -> Path | None:
        """Resolve a Wispr app file from an exported container or the backup."""
        if Path(relative_path).is_absolute() or ".." in Path(relative_path).parts:
            raise BackupError(f"unsafe app-relative path: {relative_path!r}")
        if app_container is not None:
            root = app_container.expanduser().resolve()
            candidate = root / relative_path
            if candidate.is_symlink() or not candidate.is_file():
                return None
            resolved = candidate.resolve()
            if resolved != root and root not in resolved.parents:
                raise BackupError(f"app file escapes the app container: {candidate}")
            return candidate

        item = self.first(
            domain="AppDomain-com.wispr.flowapp",
            relative_path=relative_path,
        )
        if item is None:
            return None
        return self.payload_path(item)


def app_audio_resolver(
    backup: IPhoneBackup, app_container: Path | None
):
    """Return a filename-to-path resolver for the Wispr app's Documents."""

    def resolve(filename: str | None) -> Path | None:
        if not filename:
            return None
        if Path(filename).name != filename:
            return None
        return backup.app_file(f"Documents/{filename}", app_container=app_container)

    return resolve
