# Wispr Flow iPhone exporter

Extract Wispr Flow transcripts from a local iPhone backup, including the
transcription database and the raw ActionTranscript SEGB records that Apple
stores alongside it.

This is an unofficial, best-effort tool. It is not affiliated with or endorsed
by Wispr Flow, Apple, or Phosphor. The exported archive contains private
speech and may contain sensitive text. Keep the output local and do not commit
it to GitHub.

## Quick start

The exporter uses only the Python standard library at runtime. After cloning
the repository, install it and run one command:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
wispr-flow-iphone-export \
  --backup-dir /path/to/phosphor-backup \
  --output ./wispr-flow-export
```

The backup directory must be the directory that directly contains
`Manifest.db`, not the parent directory containing several backups.

If Phosphor exported the Wispr Flow app container separately, pass it as an
optional hint. This can improve audio-file matching, and it is also useful when
the backup manifest does not contain the app's database file:

```bash
wispr-flow-iphone-export \
  --backup-dir /path/to/phosphor-backup \
  --app-container /path/to/com.wispr.flowapp \
  --output ./wispr-flow-export
```

Read the resulting transcripts here:

```text
wispr-flow-export/iphone/transcripts.md
```

For a read-only inventory before writing anything:

```bash
wispr-flow-iphone-export \
  --backup-dir /path/to/phosphor-backup \
  --output ./wispr-flow-export \
  --dry-run
```

## Getting the source files with Phosphor

The exact Phosphor labels can change between releases, but the workflow is:

1. Open the latest local iPhone backup in Phosphor.
2. Use Phosphor's backup export or extraction option to make the decrypted
   backup available as a normal folder on the Mac.
3. Choose the folder containing `Manifest.db` as `--backup-dir`.
4. If the app container is exported separately, choose the folder named
   `com.wispr.flowapp` as `--app-container`.

The backup root has this shape:

```text
<backup-root>/
├── Manifest.db
├── 00/<40-character-file-id>
├── 01/<40-character-file-id>
├── ...
└── ff/<40-character-file-id>
```

`Manifest.db` maps logical iOS paths to those sharded payload files. The
exporter uses the manifest instead of guessing file names.

When an app container is available, its relevant structure is:

```text
<app-container>/
└── Documents/
    ├── database.sqlite
    ├── <audio-id>.wav
    └── ...
```

The tool can resolve `Documents/database.sqlite` directly from the backup
manifest, so an app-container export is optional for most backups.

## What the exporter reads

### Final transcript text

The main source is the Wispr Flow Core Data table `ZTRANSCRIPTION` in
`Documents/database.sqlite`. For each row, the selected text uses this stable
fallback order:

1. `ZTRANSCRIPTIONTEXT`
2. `ZLLMTEXT`
3. `ZASRTEXT`

All source text columns are also preserved in the raw NDJSON output, so the
selection can be audited later.

### ActionTranscript records

The backup manifest commonly contains these logical paths:

```text
SysContainerDomain-com.apple.linkd/
└── ActionTranscript/com.wispr.flowapp/
    ├── local/<record-id>
    ├── tombstone/<record-id>
    └── metadata
```

The record files use Apple's SEGB v2 envelope. This project decodes the
envelope, verifies CRCs when available, preserves the raw container, and
writes each payload as a sidecar. The nested ActionTranscript payload schema
is private and can change, so the tool deliberately does not guess its fields
into transcript text.

In practice, an iPhone backup may contain deleted or zero-filled SEGB entries.
That is why the transcription database is the primary source for readable
text, while the SEGB output preserves the forensic evidence and provenance.

## Output structure

```text
<output>/
├── index.json
├── iphone/
│   └── transcripts.md
└── raw/
    └── iphone/
        ├── transcriptions.ndjson
        ├── transcriptions-manifest.json
        └── action-transcript/
            ├── manifest.json
            ├── records.ndjson
            ├── segb/<file-id>.segb
            └── payloads/<file-id>-<entry-index>.bin
```

The Markdown file is for reading. The NDJSON files are for scripts and later
analysis. `index.json` and the two manifests record counts, source paths, and
the transformations applied. Raw backup files and app database files are
never copied into the output archive.

## Options

```text
--backup-dir PATH             required, folder containing Manifest.db
--app-container PATH          optional extracted com.wispr.flowapp folder
--output PATH                 output directory, default ./wispr-flow-export
--dry-run                     read and count without writing output
--skip-action-transcripts     omit raw SEGB extraction
--skip-transcriptions         omit the ZTRANSCRIPTION database extraction
```

The source backup and SQLite database are opened read-only. The exporter does
not contact Wispr Flow, Apple, Phosphor, or any other network service, and it
does not read credentials.

## Privacy and safety

- Treat the output as sensitive personal data.
- Keep the backup and output outside a Git working tree, or use the included
  `.gitignore` rules.
- Do not upload `transcripts.md`, `*.ndjson`, `*.segb`, audio, or extracted
  app containers to a public issue or repository.
- Output directories are created with mode `0700` and output files with mode
  `0600` where the operating system permits it.
- The code refuses symlinked backup payloads and paths that escape the backup
  root or app container.
- The database is opened with SQLite's immutable URI and `PRAGMA query_only`.

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
python -m pytest
```

Tests use synthetic SQLite databases and SEGB fixtures. No personal backup,
transcript, audio, or app-container files are required.

## Credits and references

This project was created as an iPhone-focused extension of the investigation,
archive conventions, and security practices in
[`junxit/wispr-flow-exporter`](https://github.com/junxit/wispr-flow-exporter).
That repository was used as the primary reference for the exporter workflow,
read-only handling, provenance, and archive layout. Its required notice is
retained in [`LICENSE.md`](LICENSE.md), and the relationship is described in
[`NOTICE.md`](NOTICE.md).

The SEGB envelope work was also cross-checked against the public
[`cclgroupltd/ccl-segb`](https://github.com/cclgroupltd/ccl-segb) research and
the public SEGB format discussion from
[Cellebrite](https://cellebrite.com/en/blog/understanding-and-decoding-the-newest-ios-segb-format/).

## GitHub topics

Suggested repository topics are:

```text
wispr-flow, iphone, ios, ios-forensics, digital-forensics,
data-extraction, python, sqlite, segb, transcription, backup
```

## License

This project is distributed under the PolyForm Noncommercial License 1.0.0.
See [`LICENSE.md`](LICENSE.md) and [`NOTICE.md`](NOTICE.md).
