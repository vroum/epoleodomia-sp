# Source checkpoint — 2026-11-01

This checkpoint records the consolidated Python refactor, managed TEE lifecycle,
restricted manual syncs and local/NAS TEE raster pipeline. The AutoCAD command
layout and wire protocols remain compatible with the existing LISP modules.
It is a source checkpoint, not a new database migration or a completed legal/data
review.

Git references:

- Branch: `codex/checkpoint-20261101`
- Annotated tag: `checkpoint-20261101`
- Parent: `b5f44b1` on the original `claude-opt` branch

## Included

- Shared literal settings, API startup handling, report/data/geometry services
  and protected read snapshots.
- Frozen TEE baseline/contract/preparation, preview-first lifecycle tools and
  installed-schema regression fixtures.
- Validated TEE/cadastre/EMSY syncs, rollback/staging, change reporting and
  separate reader/writer credentials with explicit privilege checks.
- Validated staged GeoTIFF downloads, safe flat/nested local paths and optional
  versioned NAS replication with checksum verification and bounded recovery.
- Regression tests, operational instructions and recorded acceptance limits.

The commit excludes `.env`, the virtual environment, runtime logs, database
archives, raster bytes and the unrelated `_to_delete/` and
`ync_kaek_operating.py` items. Existing tracked LISP files remain in the snapshot.
Production passwords were checked for accidental inclusion without printing
their values.

## Validation and acceptance

Checkpoint validation on 2026-11-01:

- Offline discovery: 437 tests, 278 executed successfully, 159 opt-in tests
  skipped. HTTP and database calls are mocked for the offline suites.
  The exact staged tree also passes from a separate export without `.env` or
  a copied `.venv`; its Windows wrapper test uses the active test interpreter.
- Disposable PostgreSQL 16/PostGIS setup/writer suite: 52 tests. This runner
  creates and removes its own localhost container without host-data mounts.
- Python compilation, UTF-8/LF checks for changed text, Git whitespace checks
  and review of the selected files for credentials.
  Three existing extra EOF blank lines are retained in the frozen 0001 SQL,
  installed-schema fixture and setup test file; all other whitespace checks pass.
- LISP integrity: zero failures; the existing unused `epol:parse-rasters-info`
  helper produces the one known warning and remains unchanged.
- Exact runtime hashes match the 2026-10-31 tested raster/NAS manifest. Frozen
  preparation/migration files retain their reviewed checksums.

The preceding 2026-10-31 acceptance includes a full backup restore/preparation
rehearsal, restricted production TEE/cadastre/EMSY syncs, six unchanged HTTP
reports, 103 local and NAS TEE TIFFs, checksum readback, isolated one-file
recovery and a repeated menu run without TIFF copies/downloads. These are
historical acceptance results; this checkpoint does not repeat production
writes. Full details and limitations are in `TESTING.md`, `STATUS.md` and
`MIGRATION_PLAN.md`.

Local validation receipts live under ignored `logs/git_checkpoint_20261101/`;
earlier receipts live under the ignored paths referenced by `TESTING.md`.
Those receipts are not dependencies of the offline test suite.

## Reproduce and inspect

```powershell
git show --stat checkpoint-20261101
git diff checkpoint-20261101^ checkpoint-20261101 -- api_server.py
python -B -m unittest discover -s tests -v
python -B tests/run_setup_tests.py
```

For a separate checkout, choose a new folder and run:

```powershell
git worktree add --detach '..\epol-checkpoint-20261101' checkpoint-20261101
```

Install the requirements in a virtual environment for that checkout. Offline
tests run without `.env`. Running the API/sync requires a separately configured
local `.env` and the relevant database/file permissions; no credentials are
restored by Git. The disposable database tests also require local Docker.

Switching code versions does not revert PostgreSQL or external raster files.
Database restore and raster recovery use their own verified backups. Historical
`sql/001_tables.sql` drops tables and must not be replayed over production.

## Next acceptance work

1. Exercise 5–10 representative AutoCAD workflows with actual parcels, reports,
   rights and raster/FEK insertion after the completed storage changes. Prior
   user acceptance covered EREPORT/KAEK/ERASTER before that final storage phase.
2. Define whole multi-table sync publication and measure concurrent report
   behavior/performance. A protected report snapshot can still contain tables
   from different sync generations because layers commit separately.
3. Review the three unexplained FEK exclusions and shared-sector/overlapping
   classification cases with domain evidence. Keep existing exclusions and
   human quality judgements until a documented decision is made.
