# Source checkpoint — 2026-11-01

The later commands/API starting checkpoint on `codex/atomic-sync-publication`
is described at the end of this document. The sections immediately below
record the earlier `checkpoint-20261101` baseline.

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

## Commands/API starting checkpoint — 2026-11-01

Branch: `codex/atomic-sync-publication`, following baseline commit `c022dc1`.
This checkpoint consolidates the work completed before the next round of
AutoCAD command and API improvements:

- Atomic publication of all selected TEE/cadastre/EMSY layers, with one data
  transaction, reader-compatible locks and an explicit uncertain-commit outcome.
  The first production run committed all 59 layers and preserved six reports;
  see SYNC_PUBLICATION.md.
- Forward-only sync history, scoped journal grants, a read-only history page,
  configurable date ranges and before/after record details. A fresh HTTP check
  confirms that production history is installed, with tracking start
  `2026-11-01T08:51:32.169077+00:00` and no recorded runs yet. Old JSON history
  is not imported; see SYNC_HISTORY.md.
- Read-only review of the three FEK exclusions, the OT 116 special regulation
  and zone overlaps. Applying the operator's inside-OT criterion puts 40 of 44
  area-overlap pairs entirely outside OT; four have only 0.0000235356 m² each
  inside OT 33. This finding requires no zone or runtime correction. See
  DATA_REVIEW.md for evidence and the separate presentation/metadata follow-ups.

The selected source tree excludes credentials, runtime logs, database archives,
raster bytes and the unrelated `_to_delete/` and `ync_kaek_operating.py` items.
The earlier checkpoint branch/tag remain intact. Recording and pushing this
checkpoint do not run a production sync, apply SQL or restart the API.

Validation for this checkpoint:

- The exact staged export passes 487 discovered offline tests: 299 executed,
  188 opt-in cases skipped, with no `.env` or copied virtual environment.
- The preceding code review passed 81 disposable PG16/PostGIS cases. Those
  results are retained from `logs/data_review_20261101/disposable_tests.log`;
  the checkpoint does not repeat that database suite.
- Selected Python files compile, changed text is UTF-8 without BOM with LF
  endings, Git whitespace checks pass, and the staged tree is checked against
  configured passwords without printing their values.
- The frozen preparation and migration files remain byte-identical to the
  preceding checkpoint. LISP files and existing command protocols are unchanged.

Validation/export receipts live under ignored `logs/git_release_20261101/`.
Next work can focus on one complete AutoCAD/API workflow at a time, beginning
with EREPORT/OROITABLE. The first production history entry still needs to be
observed during a normal manual sync. Optional 740Δ/1981 sheet selection, the
OT 116 heading and the history map remain separately documented follow-ups.
