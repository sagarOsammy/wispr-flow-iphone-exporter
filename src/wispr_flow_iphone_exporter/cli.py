"""Command-line interface for the iPhone extraction workflow."""

from __future__ import annotations

import argparse
from pathlib import Path

from .archive import write_archive
from .backup import BackupError, IPhoneBackup, app_audio_resolver
from .database import DatabaseError, read_transcriptions
from .segb import SegbError, discover_action_files


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wispr-flow-iphone-export",
        description="Extract Wispr Flow iPhone transcripts from a local iPhone backup.",
    )
    parser.add_argument(
        "--backup-dir",
        required=True,
        type=Path,
        metavar="PATH",
        help="Phosphor or Apple backup directory containing Manifest.db",
    )
    parser.add_argument(
        "--app-container",
        type=Path,
        metavar="PATH",
        help="optional extracted com.wispr.flowapp container, used for the database and audio",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("./wispr-flow-export"),
        metavar="PATH",
        help="output directory, default: ./wispr-flow-export",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="read and count records without writing output",
    )
    parser.add_argument(
        "--skip-action-transcripts",
        action="store_true",
        help="skip raw ActionTranscript SEGB extraction",
    )
    parser.add_argument(
        "--skip-transcriptions",
        action="store_true",
        help="skip the ZTRANSCRIPTION database extraction",
    )
    return parser


def _database_path(backup: IPhoneBackup, app_container: Path | None) -> Path | None:
    if app_container is not None:
        candidate = app_container.expanduser().resolve() / "Documents" / "database.sqlite"
        return candidate if candidate.is_file() else None
    return backup.app_file("Documents/database.sqlite")


def main(argv: list[str] | None = None) -> int:
    """Run the extraction and return a shell exit status."""
    args = _parser().parse_args(argv)
    try:
        backup = IPhoneBackup(args.backup_dir)
        action_files = (
            tuple() if args.skip_action_transcripts else discover_action_files(backup)
        )
        database_path = None if args.skip_transcriptions else _database_path(
            backup, args.app_container
        )
        if not args.skip_transcriptions and database_path is None:
            raise DatabaseError(
                "Wispr Flow database.sqlite was not found. Provide --app-container "
                "or use a backup that includes AppDomain-com.wispr.flowapp/Documents/database.sqlite."
            )
        transcripts = tuple()
        if database_path is not None:
            transcripts = read_transcriptions(
                database_path,
                audio_resolver=app_audio_resolver(backup, args.app_container),
            )
        report = write_archive(
            output_root=args.output,
            backup_root=backup.root,
            database_path=database_path,
            transcripts=transcripts,
            action_files=action_files,
            dry_run=args.dry_run,
        )
    except (BackupError, DatabaseError, SegbError, OSError, ValueError) as error:
        print(f"error: {error}")
        return 1

    print(f"backup: {backup.root}")
    print(f"output: {report['output']}")
    print(f"transcriptions: {report['transcriptions']} ({report['transcribed']} with text)")
    print(f"audio matches: {report['audio_matches']}")
    print(
        "ActionTranscript files: "
        f"{report['action_files']}, entries: {report['action_entries']}, "
        f"written: {report['action_written']}, deleted: {report['action_deleted']}"
    )
    print(f"SEGB payload: {report['payload_bytes']} bytes, {report['nonzero_payload_bytes']} nonzero")
    if args.dry_run:
        print("dry run: nothing was written")
    else:
        print("complete")
    return 0
