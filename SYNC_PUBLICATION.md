# Atomic GIS sync publication

Forward-only persistent changes and the local history page are described in
[SYNC_HISTORY.md](SYNC_HISTORY.md). After its separate activation, the publisher
records business changes across every selected domain in this same transaction.

`sync_publication.py` collects the selected sources completely, validates the
bundle, then publishes it through one connection and one PostgreSQL transaction.
It preserves the existing tables, views, indexes and AutoCAD protocols.

## Scope

| Mode | One data transaction |
|---|---|
| `tee` | All 55 configured TEE layers, derived catalog refresh, area recalculation and audit rows |
| `ktima` | All three operating-cadastre layers |
| `ydro` | EMSY, retaining its existing no-deletion policy |
| `all` | All 59 layers across those three domains |

An empty TEE source retains its existing rows, as before. An empty cadastral
source cancels the complete publication. Empty EMSY retains existing points.
Every selected layer must occur exactly once in the captured bundle.

The source services provide no shared revision/snapshot. Downloads can therefore
describe different source observation times. The guarantee is that the selected
database changes become visible together after successful collection; source
accuracy and legal interpretation remain separate questions.

## Reader and writer behavior

One session advisory lock spans capture and publication. Another atomic publisher
is refused before it fetches data. Connection closure releases this lock after
success, errors or interruption.

The write transaction takes source-table locks in sorted order using `SHARE ROW
EXCLUSIVE`. This serializes data writers and blocks incompatible schema changes,
while ordinary readers continue. The derived raster catalog keeps its existing
column-scoped rights: it receives an `ACCESS SHARE` lock and ordinary DML row
locks. Human quality/download fields keep their existing preservation rules.

The duplicate-OBJECTID lot table uses `DELETE/INSERT` inside the same transaction.
This preserves old reader snapshots. Its existing foreign-key consumers, custom
triggers, inheritance, row security and rewrite rules require explicit review;
the publisher refuses those cases. Cadastral metadata/column/FK guards also stay
in force. No persistent source table is created or replaced by this workflow.

Complete reports already use one read-only repeatable-read snapshot. A report
running before commit retains the old generation; one beginning after commit
sees the new generation. Separate commands/HTTP requests can observe different
generations if a publication commits between them. Direct legacy sync scripts or
other editing applications can still make independent changes; use the menu's
atomic path for the guarantees described here.

PostgreSQL references: [table locks](https://www.postgresql.org/docs/18/explicit-locking.html),
[LOCK ordering and snapshots](https://www.postgresql.org/docs/18/sql-lock.html),
and [TRUNCATE snapshot limitations](https://www.postgresql.org/docs/18/sql-truncate.html).

## Enable the existing restricted account

An installation with the legacy sync profile needs one additional data privilege:

```sql
GRANT DELETE ON epoleodomia.building_regs_lot TO epol_sync;
```

The reviewed SQL is `sql/admin/enable_atomic_publication.sql`. It grants no
ownership, role administration, schema CREATE, sequence reset or access to other
tables. Existing `TRUNCATE` access remains for the legacy tools. New sync-account
setup includes the extra DELETE; the verifier accepts the old and upgraded
profiles and continues rejecting other unexpected writes.

```powershell
& .\.venv\Scripts\python.exe -B enable_sync_publication.py
& .\.venv\Scripts\python.exe -B enable_sync_publication.py --sql
& .\.venv\Scripts\python.exe -B enable_sync_publication.py --apply
```

The first command previews using the normal reader; the second prints SQL without
connecting. Only `--apply` prompts locally for the schema owner's password,
checks the same target/history and grants DELETE transactionally. Repeating it
after success makes no changes. It never writes `.env`, resets a password or runs
a sync.

After this grant, `sync_menu.bat` automatically uses atomic publication for data
modes 1/2/3/5/6. Mode 5 publishes all three domains together. Before the grant,
existing menu data modes retain the legacy per-layer behavior and print that
fact. An explicit `--atomic` never falls back if publication access is missing.

```powershell
& .\.venv\Scripts\python.exe -B sync_publication.py all --check
& .\.venv\Scripts\python.exe -B sync_publication.py all
sync_menu.bat all --atomic
```

`--check` reads privileges/schema only, without HTTP capture. The bare Python
command performs a complete collection preview using a read-only database
session. Both save a local JSON receipt and perform no data writes or advisory
locking. `sync_menu.bat all --atomic` is an actual update. The Python publisher
also has explicit `--apply`; preview is its default.

## Failures and receipts

Loaders borrow the publication connection without committing, rolling back or
closing it. Derived-column and audit failures propagate to the controller. A
failure before COMMIT rolls back all selected source changes and audit rows.
Sequences can have gaps after rollback; their counters are not reset.

Every publication has a `sync_runs` audit ID and `publication_<mode>` mode. It is
created/completed in the same transaction as the source changes. The audit's row
change counters cover tracked TEE rows; lot replacements and other domains have
their detailed counts/diffs in the JSON receipt. Its table count covers the full
selected bundle.

An interrupted/lost COMMIT response is reported as `commit_unknown` with its audit
ID. Check that ID and the data before retrying: the client cannot infer whether
the server committed. Local receipt-write errors after commit explicitly print
the committed status and do not claim a rollback.

Menu mode 6 runs raster/NAS operations only after the data transaction succeeds.
Files, NAS manifests and PostgreSQL are separate commits; a subsequent raster
failure does not undo the already committed data. Failed data publication skips
all raster/NAS actions. No new raster catalog is introduced.

The transaction uses a 5-second lock timeout, 120-second statement timeout and
60-second idle-in-transaction timeout. Capture happens outside the write
transaction. Receipts record capture, locking/guards, per-table, transaction and
commit durations; capture time is not time holding the source write locks.

## Validation and rollout

The offline suite covers preview isolation, complete capture before publication,
lock conflicts, complete-bundle validation, shared connection ownership, fatal
audit failures, explicit commit uncertainty, credential redaction and menu
routing. Disposable PostGIS tests execute all-domain publication under the real
restricted role, verify full rollback after the last EMSY write, preserve
metadata/duplicate lots, run old/new readers concurrently, reject schema/FK drift
and verify the one-grant upgrade/idempotence/rollback.

Production access during development is read-only. The operator enabled the
single lot DELETE grant on 2026-11-01. Independent read-only verification confirms
`lot_delete_granted: true`, `ready: true`, unchanged values in all 96 project
tables, unchanged `.env`, no reader writes and a healthy API. The first production
atomic sync then committed all 59 layers as audit #2 (`publication_all`, success).
Independent read-only audit/count/report checks pass; all six HTTP reports remain
byte-identical. Collection took 65.05 s and the transaction 7.19 s. Evidence:
`logs/atomic_publication_20261101/first_production_verified.json`.
Database migrations 0001/0002 and their preparation
stay unchanged. Full-backup rehearsal and timing evidence are recorded separately
under ignored `logs/atomic_publication_20261101/` and its linked rehearsal folder.
Grant verification: `logs/atomic_publication_20261101/activation_verified.json`.

On 2026-11-01, 294 offline and 61 disposable PG16 cases pass. A full-backup PG18
rehearsal captured all 59 real-source layers, verified rollback after the final
domain write, ran six complete old-generation reports during publication and
passed an identical-input repeat. Metadata, curated data and raster judgements
remain intact; all 96 production project-table fingerprints and `.env` match
before/after. Evidence: `logs/atomic_rehearsal_20261101_f93701e8/result.json`.
See TESTING.md for measured timings and their limits.
