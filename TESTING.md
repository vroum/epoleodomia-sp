# Project testing

The fixture suites do not certify compatibility with an existing installation.
The 2026-10-27 read-only schema audit reproduced live report failures because
`epoleodomia.natura_2000.is_deleted` was absent, although synthetic spatial
fixtures supplied that column. It also found a duplicate target key in the
unapplied `005` backfill, which replay on an empty source cannot reveal.
Both source issues are now corrected: legacy/tracked Natura cases and the
nonempty `005` backfill have regression coverage. Six actual API report calls
also passed with `codex_reader` using only read transactions; this was a separate
installed-data smoke check, not part of the synthetic fixture suite.
See DOCUMENTATION.md section 6 for the installed-schema findings and limits.

## Offline regression tests

The planning-data review on 2026-11-01 retains **299 passing offline cases**
(487 discovered, 188 opt-in skipped) and passes **81 disposable PG16/PostGIS
cases**. Five additional SQL cases validate the new read-only planning audit:
positive overlaps with two candidates, shared-line versus point-only contact,
soft-deleted exclusion, separate lot rule/exception variants, and a complete
repeatable-read/read-only audit preserving all table values. The optional
raster contract is an empty fixture view, not another raster catalog.

The production audit reads the three FEK footprints through `v_all_rasters`,
municipality intersections and all 65 active records in the five regulation
tables. It records raw pair areas, attributes and Contains/Covers match counts;
it makes no legal-priority selection or source edits. Scanned TEE gazettes were
visually inspected, including every paragraph of the OT 116 special provision.
The operator's 740Δ/1981 usability explanation is documented separately from
measured GIS facts. Six actual HTTP reports remain byte-identical and the API
remains healthy; no runtime restart or sync was performed. See DATA_REVIEW.md
and local evidence in `logs/data_review_20261101/`.

The supplementary read-only OT intersection check compares all 44 positive-area
overlap pairs with the union of 558 active building blocks. Forty pairs have no
positive area inside OT; four intersect OT 33 (OBJECTID 710082) by approximately
0.0000235356 m² each. Raw results, including pair IDs, areas and affected blocks,
are saved in `logs/data_review_20261101/overlaps_inside_blocks.json`. This was an
installed-data check, separate from the five fixture cases above. Closing the
review changes documentation only; no runtime changes or additional test run.

The forward-only history update on 2026-11-01 passes **299 offline cases**
(482 discovered, 183 opt-in skipped) and **76 disposable PG16/PostGIS cases**.
New SQL tests cover an unchanged reimport including duplicate-ID lots, 10 new
parcels plus three forest records, equal-count overlay replacements, source-ID
renumbering, ring-order equality, geometry-only edits, complete rollback on a
late journal error, missing/duplicate identities, redacted fetch failures,
read-only API queries/pagination, distinct identities versus repeated events,
literal identifier searches, restricted journal grants, transactional setup
rollback, partial installation rejection and a real COMMIT with its response
deliberately lost. Offline cases exercise Greek daylight-saving/date boundaries,
route bounds, missing installation state and the credential-free menu shortcut.

The verified full archive was also restored in isolated PG18/PostGIS and replayed
with all 59 captured source layers. After establishing the current data and
installing an empty journal, the same 23,018 source records produced zero new,
updated, removed, geometry or source-ID-only changes; all 17 lot variants count
unchanged. The recorded replay took 5.19 seconds in the disposable database;
this is not a production performance measurement. Six complete reports match,
actual ASGI overview/detail requests pass, all 96 production source-table
fingerprints and `.env` match before/after, and frozen recipe/controller
checksums are unchanged. No old history was imported and no production sync or
journal DDL was run. Evidence: `logs/sync_history_review_20261101/result.json`.

Browser checks cover the populated summary, source filtering, run drilldown and
safe display of HTML-like attribute text using synthetic loopback fixtures.
The actual restarted API serves the page/assets with a local-only asset policy;
six real HTTP reports remain byte-identical. The production screen correctly
states that journal activation is pending. Operator activation remains separate:
`setup_sync_history.py --apply`; see SYNC_HISTORY.md.

The atomic-publication update on 2026-11-01 passes **294 offline cases**
(462 discovered, 168 opt-in skipped) and **61 disposable PG16/PostGIS cases**.
Sixteen new offline cases cover full capture before any write transaction,
preview/check isolation, duplicate/missing bundles, borrowed connection/audit
ownership, late audit failure, commit uncertainty with audit identity,
credential redaction, automatic menu routing and raster suppression when the
publisher fails or cannot start. Nine new database cases run all selected domains
as the real restricted role, retain old/new reader generations during writes,
verify complete rollback after final-domain SQL, preserve metadata/duplicate
lots, reject schema/FK drift, check lock release/competition and exercise the
single-grant upgrade and independent cadastre/EMSY modes.

A full immutable 117,247,779-byte backup was restored/prepared in a new PG18
container with cron disabled. All 59 live-source layers were captured before
publication. Injecting an error after the final EMSY writes preserved every
original project row; a subsequent publication and identical-input repeat pass.
Six complete reader reports run during uncommitted writes and remain unchanged
after commit. Original relation metadata, curated data and raster judgements
are preserved. All 96 production project-table fingerprints and `.env` remain
unchanged; development production access was read-only.

Evidence: `logs/atomic_rehearsal_20261101_f93701e8/result.json` and adjacent
capture, publication and repeat receipts; final regression logs live under
`logs/atomic_publication_20261101/`. The full-data rehearsal measured 68.95 s for
capture, 2.39 s for its first local-copy transaction (including a deliberate
pause for reports), 2.03 s for repeat publication and 0.30 s for all six reports
during that pause. Six actual production HTTP report reads took 0.125–0.188 s
each. These are small local-copy/baseline measurements, not production writer
latency or a load/concurrency capacity test. The later two-line launcher fix
also suppresses rasters if its publication process cannot start; dedicated
offline cases cover that path. Publishing SQL is unchanged from the rehearsal.

The operator subsequently enabled the single grant. Independent read-only checks
confirm readiness, all 96 unchanged production table values, unchanged `.env`,
no reader writes and healthy API.
Evidence: `logs/atomic_publication_20261101/activation_verified.json`.
The operator's first production atomic run then committed all 59 layers as audit
#2. Independent read-only checks match its database audit and receipt; six actual
HTTP reports remain byte-identical, `.env`/API health and the restricted writer
contract pass. TEE has zero tracked changes/errors and 17 intentional lot-row
replacements; parcels show no changes and all 72 EMSY points are unchanged.
Overlay counts remain 21/725; their count-only digest does not prove geometry or
attribute equality. Collection took 65.05 s and the production transaction 7.19 s
(0.14 s commit); this single execution is not a load test. Verification did not
repeat the sync. Evidence: `logs/atomic_publication_20261101/first_production_verified.json`.
See `SYNC_PUBLICATION.md`. The preparation and migrations remain frozen.

With the project dependencies installed (`pip install -r requirements.txt`):

```bash
python -m unittest discover -s tests -v
```

By default, tests mock HTTP requests and PostgreSQL connections. They require
no live service or database credentials and do not write to the database or sync logs.
The Windows wrapper case supplies the active test interpreter on the child PATH,
so a clean source export also runs without a project `.venv` or global Python.
They cover failed/malformed responses, incomplete and repeated pages, server
page-size limits, source-count changes, input/identity validation, transaction
rollback on record or audit failures, and accurate sync success/error reporting.
They also preserve the duplicate-OBJECTID exception for `building_regs_lot`.
Shared-settings cases cover literal quoting/metacharacters, comment styles/BOM,
malformed or duplicate entries, process/file/alias precedence, value-free errors,
port/schema/timeout validation and client agreement from another working directory.
Setup unit tests check migration ordering/encoding, a read-only default,
atomic SQL/history ownership, explicit adoption without SQL replay, lock conflicts,
rollback/cleanup and `sync_all.py --init` isolation from every sync mode.
The cadastral suite covers ID snapshots, POST batches, incomplete/mismatched
responses, source schema/record validation, staging checks and rollback before
or during publication. CLI audit-summary cases cover table/service/test/full modes
without a file logger. Geometry tests verify that spatial comparison outcomes
drive both updates and audit flags, including same-length coordinate moves.
The EMSY suite checks complete ID snapshots despite short responses or misleading
transfer-limit flags, declared EPSG:2100, finite points inside the requested
bbox, required source fields, no-deletion retention and whole-load rollback.

Planning-report route tests import the real FastAPI module without starting its
database pool and mock the `PlanningData` providers and snapshot boundary.
Separate route-session tests use the real snapshot manager with a mocked pool
to verify one cursor/connection, required/optional source locks before collection,
propagated failures and disabled queries for an unavailable optional source.
Hand-authored synthetic inputs and
expected rows live in `tests/fixtures/reports/`. Cases cover parcel versus point
references, section order, shoreline crossings/approvals, forest-map fallback,
pending flood labels, missing-data errors and EMSY inside/nearest presentation.
They also check arithmetic boundaries of the existing outside-plan formula.
Direct builder tests exercise the same three reference reports without the API,
verify that repeated builds preserve their inputs and do not leak approvals
between reports, and preserve missing-data and character-replacement behavior.
An isolated subprocess renders the fixtures with site packages disabled.
The builder tests can also run using the Python standard library alone:

```bash
python -S -B -m unittest tests.test_report_builders -v
```

The extracted `PlanningData` service also renders the reference reports without
API/driver/config imports, using supplied provider results. Its tests cover
optional-group scope, discarded partial EMSY data, absent-source query prevention
and required-error propagation, including isolated standard-library execution:

```bash
python -S -B -m unittest tests.test_planning_data -v
```

The report cases preserve software behavior; they do not certify legal rules
or validate the accuracy of the live source datasets. See the fixture README.

The offline tests verify failure handling and transaction calls using mocks. They do
not prove real database table-swap/restore behavior, spatial SQL accuracy,
legal correctness or the AutoCAD checks below. Do not run a production sync as a test.

KGEOM offline tests cover malformed/nonfinite input, nonnegative finite tolerance,
ring closure, validity/missing-subject early exits, SQL-failure propagation and the
existing drawing/table protocol. The extracted service also runs against a
hand-authored expected response without FastAPI or database packages:

```bash
python -S -B -m unittest tests.test_boundary_service -v
```

KGEOMV request tests likewise block live connections and verify strict whole-body
parsing, finite values/title fields, unique labels, early validation/source-error
exits, exception propagation and one snapshot protecting both cadastral sources.
Its standalone service has a hand-authored full-protocol reference and an
isolated import/calculation test with site packages disabled:

```bash
python -S -B -m unittest tests.test_vertical_service -v
```

Snapshot unit tests cover one connection/cursor per calculation, transaction and
read-lock setup, autocommit restoration, rollback on success/failure, pool/lock
failures and discarding connections after failed cleanup without hiding the
original calculation error. Savepoint cases verify local rollback, nested groups,
optional lock failures, unavailable-source tracking and propagation/discard after
failed setup/recovery/release even when a provider catches the error.
Geometric and transaction behavior are checked
separately by the opt-in tests below.

## TEE raster downloader checks

```bash
python -B -m unittest tests.test_raster_download tests.test_sync_access tests.test_settings -v
```

Twenty-three downloader cases use actual generated GeoTIFFs and filesystem operations
without network/DB access. They cover interrupted streams, content-length mismatch,
empty/HTML bodies, truncated pixel data, missing rasterio, missing/wrong CRS,
rotated/south-up rasters, path traversal/reserved names, destination collisions,
read-only preview, SQL/commit/rename failure, recovery-backup retention and cleanup
after a lost database connection. Launcher cases ensure bounded raster options
cannot accidentally execute an all-domain sync or alter default command vectors.
Eight ASGI route cases exercise actual HTTP routing/serialization without an
extra HTTP client dependency: flat/nested paths, working-only view queries, JSON
availability, six-field simple output, missing-file filtering, URL fallback and
validated on-demand downloads. Shared-settings tests verify that explicit roots
win and the default catalog root follows the flat FEK folder.

Two additional cases in `tests.test_sync_access_postgis` run as the actual
restricted role in marked disposable PostGIS: parallel staged TIFF downloads
with one SQL rejection and one invalid file still publish the other files,
retain an old file/status and preserve manual fields. A source changed while
downloading cannot publish or receive a stale failure update. All catalog
connections remain on the main thread. This brings that runner to 52 cases.

On 2026-10-31 the full offline suite passed 278 executed cases (437 discovered,
159 opt-in cases skipped), and 52 disposable PG16 cases passed. One actual TEE
file (catalog ID 35, 266,914 bytes, 2679x2318, three bands, EPSG:2100) passed full
validation and matched the existing file byte-for-byte. It was stored only under
`logs/raster_download_review_20261031_31a683ec/`; read-only snapshots proved all
96 production project tables unchanged.

The initial read-only inventory found zero old catalog-root paths and 74/103
filenames under the legacy flat folder. The user's parent-folder location was
then scanned: its 148 TIFFs contain the same 74 distinct byte-identical pairs,
all of which passed full decoding, CRS and north-up checks. The default root now
uses that existing flat folder, and relative paths resolve with a flat fallback.

The actual API was restarted with the project venv. Six report bodies and all
96 project tables stayed identical across restart. The actual scoped launcher
then published exactly one missing working sheet (ID 47, 3,756,421 bytes):
6505x11254 pixels, three bands, EPSG:2100. Only its three catalog timestamps
changed because the stored technical metadata/path already matched. Metadata,
all other table/row values, human judgements, exclusions and all 148 original
files were preserved. Six reports stayed byte-identical. The API's generic
working FEK simple response at that checkpoint had 60 local files (previously 59);
20 working and eight excluded files still needed repair.

Evidence: `logs/production_raster_20261031_95a01537/result.json`,
`logs/backup_review_20261031/raster_storage_inventory_20261031.json` and
`logs/api_raster_paths_20261031/`. AutoCAD itself was not driven again in this
step; the actual HTTP six-field protocol and every emitted FEK path were checked.

### Completion and NAS replication

The scoped menu repaired all remaining 28 files with two network workers and
serialized catalog publication. All 103 TIFFs are local; the working API view
has 80 available files. Only three timestamps changed in those 28 catalog rows.
All 149 pre-batch files, other project values, manual fields, exclusions and
six reports were preserved.
Evidence: logs/raster_completion_20261031_0f88002f/result.json.

Sixteen filesystem replica tests cover preview, deduplication, version retention,
source changes during copy, corruption, interrupted publication retaining the
previous complete manifest, locks, one-file recovery, stale identities,
malformed manifests, concurrent creators and refusal to overwrite different
local bytes. Unified-view reader-only SQL is checked. Launcher cases verify
pull/download/push ordering, credential separation, local continuation on NAS
failure and zero NAS actions during download preview.

Actual NAS publication stored and independently checksummed all 103 objects.
One file was restored into an isolated cache and fully validated. The 103 local
sources, 270 legacy NAS files, database state and six reports were preserved.
Only the non-secret EPOL_RASTER_NAS_PATH key was added after acceptance.
A repeat actual menu run reused all 103 objects and copied/downloaded no TIFFs;
database, local files, normal settings and six reports remained unchanged.

Evidence: logs/raster_nas_acceptance_20261031_3ee82a56/result.json and
logs/raster_menu_nas_20261031_f908adef/result.json.
These checks cover TEE files. DJI/DE and other collections retain their existing
storage procedures. Historical manifests/objects are retained; expiry and
whole-NAS recovery are separate operational policies.

## API startup checks

```bash
python -m unittest tests.test_api_launcher tests.test_settings -v
```

The nine launcher cases use temporary loopback listeners and no database.
They verify reuse of a healthy API, preservation of unhealthy/unrecognized
services, malformed responses, bind failures and socket cleanup. The listener
is reserved before credential checks. One real Uvicorn/ASGI fixture serves HTTP
through the prebound socket and shuts down cleanly. With the eight settings
checks, this targeted run passes 17 tests. The live second-start check also exits
successfully while the existing API remains healthy.

## Optional read-only PostGIS geometry checks

Set `EPOL_TEST_POSTGIS_DSN` to an explicitly selected PostgreSQL connection
string, then run:

```bash
python -m unittest tests.test_geometry_postgis -v
```

Without that variable, these six tests are skipped during normal discovery.
With it, connections enforce `default_transaction_read_only=on` at startup and
verify that the transaction is read-only. Tests use `SELECT` and literal
`VALUES` geometry only; they never read or modify application tables or create
temporary tables. They cover real PostGIS equality for moved coordinates,
reordered rings/vertices, holes, multipart geometry, NULL transitions, binary
precision and results spanning multiple batches.

### KGEOM boundary-correction checks

Using the same `EPOL_TEST_POSTGIS_DSN` variable:

```bash
python -m unittest tests.test_boundary_corrections_postgis -v
```

These 16 tests also enforce a read-only connection. They call the real
`/geom/diorthosi` function and extracted service with a mocked request, replacing
only the parcel table reference with a parameterized, synthetic `VALUES` CTE.
The harness runs the actual snapshot manager on a fixture connection; the
application relation lock is omitted because the source is synthetic VALUES.
Schema-qualified application-table references are rejected by the harness.
No API lifespan/pool startup, application data, temporary tables, DDL or writes
are used. Expected shapes and
areas are specified independently using rectangles and a multipart parcel;
`ST_Equals` compares the returned rings with the expected shapes.

Cases include unchanged boundaries, expansion/contraction, road participation,
positive subject overlap, splitting a connected claim across multiple donors,
multipart results, longest-boundary assignment, exact sliver thresholds and
visible balance discrepancies after filtering. Invalid/degenerate surveys,
point-only neighbor contact, uncovered/overlapping donor areas and holes in
transfer/final geometry must return errors.

### Snapshot transaction checks

```bash
python -m unittest tests.test_database_sessions_postgis -v
```

These six checks use a real one-connection pool with read-only startup
settings. They verify transaction isolation/read-only mode, one backend,
acquisition/release of ACCESS SHARE locks on catalog relations (including two
relations locked together), rollback
after a failed SELECT, session-setting/autocommit restoration and pool reuse.
Another read-only connection allocates a transaction ID and rolls back to
advance the snapshot horizon: the active calculation keeps its snapshot while
the next transaction sees a fresh one. No application tables, database objects
or rows are created/modified. Optional-source checks verify that successful locks
remain held after savepoint release and a missing relation is marked unavailable
without poisoning the session. A deliberate failed SELECT inside a savepoint
preserves the outer backend/snapshot even as another read-only transaction
advances the snapshot horizon; the next operation gets a fresh snapshot.

### KGEOMV vertical-correction checks

```bash
python -m unittest tests.test_vertical_corrections_postgis -v
```

These 20 tests call the real `/geom/kathetes` route and service through the actual
snapshot manager, using parameterized VALUES for both parcel and cadastral AX
sources. The fixture adapter asserts both protected relation names and omits
their application locks because no application table is used. Any unreplaced
application-schema reference is rejected. All expected areas, shapes and linework
are specified independently; returned rings and internal lines are checked using
PostGIS equality.

Cases include full partitions, clipping/lost area, source/title/measurement rows,
automatic numbering, Greek EK exclusion, positive parent/match overlap,
unrounded tolerance thresholds, retained-only common remainder/internal lines,
overlap warnings, multipart geometry, unsupported holes, duplicate source
numbers and ambiguous/repeated cadastral matches.

### Planning-report spatial checks

```bash
python -m unittest tests.test_report_spatial_postgis -v
```

These 39 checks run actual report-provider SQL and both report routes against
typed, parameterized VALUES CTEs on a read-only connection. Only application
source references are substituted; spatial calculations and provider results
are not mocked. The adapter rejects unreplaced application-schema references,
including quoted identifiers. Unexpected SQL/fixture errors still fail a test
when an optional-data provider catches the exception. No application data,
temporary tables, objects or rows are read/created/modified by these fixtures.
Complete report routes use the actual snapshot manager and cursor with fixture
source substitution. The adapter asserts source registration but omits application
locks because VALUES have no relations; catalog tests check the lock behavior.

Cases cover parcel-edge versus click distances, zero distances for intersecting
monuments/churches, nearest-per-type shoreline/stream selection, inclusive
search radii, stream plan-status branching, EMSY's 0.5m proximity tolerance,
deleted Natura/forest rows, positive-area overlaps versus boundary contact,
forest union coverage and unrounded 98%/0.5% thresholds, source priority and
the existing two-source fallback. Archaeological closed/open linework, the
existing point proximity tolerance, invalid source polygon repair, holes,
multipart/empty/missing parcels, EK exclusion, nearest-parcel fallback and
regulation field/source mapping are also exercised. Boundary clicks without
regulations must not automatically use outside-plan rules. Full route cases
check the resulting point/parcel report text with the actual spatial providers.
Additional cases verify one backend/snapshot/read-only mode across all report
queries, recovery after an optional archaeology approval query fails, rollback
of partial EMSY results after its second query fails, clean pool reuse and
propagation of a required-source failure. Deliberate failures use synthetic
`SELECT 1 / 0`, never application-table operations.

The five read-only suites skip by default (91 checks in total). Full discovery
includes 340 tests: 191 offline, 91 read-only PostGIS, 42 disposable PostgreSQL 16
setup/compatibility/writer tests and 16 disposable PostgreSQL 18 preparation tests.
With only `EPOL_TEST_POSTGIS_DSN` set, 282 run and the 58 disposable tests skip.
The report fixtures verify synthetic SQL,
snapshot and failure recovery behavior; they do not establish live-source
accuracy, legal applicability, production query performance, an actual concurrent
table swap or AutoCAD output. Overlapping forest classifications and ambiguous shared
regulation boundaries remain source/interpretation issues requiring review.

This covers synthetic KGEOM/KGEOMV calculations, not the accuracy/topology of the
live cadastre, an actual concurrent table-replacement sync or AutoCAD
drawing/submission behavior. The writer suite separately tests an actual reader
blocking publication until its transaction completes; the read-lock suite above
uses catalog metadata only. Input
and output holes remain unsupported by the current single-ring protocol;
both geometry services reject drawable polygons with holes. KGEOM's ignored
slivers do not change the surveyed subject boundary; nonzero balance warnings
still require review in AutoCAD. KGEOMV's ignored units are excluded consistently
from the remainder and linework. Spatial matching warnings and computed area
ratios do not certify title/ownership relationships.

## Disposable PostGIS setup/upgrade tests

With Docker running and the project dependencies installed:

```bash
python -B tests/run_setup_tests.py
```

This helper provisions `postgis/postgis:16-3.5` with synthetic credentials,
a random localhost-only port, tmpfs database storage, no host mounts and a database
explicitly marked as disposable. It runs 50 schema/writer integration tests, then
stops/removes the exact container it created, including its temporary storage. It uses a separate
`EPOL_TEST_SETUP_DSN`, never the application's connection settings. Tests refuse
non-loopback targets, database names other than `epol_setup_test`, and a database
without the disposable catalog marker. Normal discovery skips all these tests.

Cases cover read-only preview, real fresh installation and manifest validation,
both SQL helper functions, duplicate lot IDs, repeated apply, refusal to rebuild
an unmanaged schema, compatible adoption preserving data/views/object IDs,
incompatible adoption, checksum/history failures, a successful subsequent
version, atomic rollback of failed fresh installation/upgrade and concurrent
setup locking. All source rows in these tests are synthetic. This verifies the
migration workflow, not production restore, adoption of the current divergent
legacy schema or atomic multi-table sync publication.

Compatibility cases also exercise real catalog detection before/after adding
and dropping Natura tracking, plus `005` with nonempty sources: cross-source
duplicate FEK keys, deterministic URL/source selection regardless of insertion
order, existing local/manual registry values and rollback of a failed backfill.
Read-only report fixtures separately execute both Natura column layouts and
ensure a catalog error aborts the report instead of hiding protection data.

The v2 cases exercise fresh setup and a real managed-v1 upgrade, preserved
geometry/IDs/duplicate lot IDs, Polygon/MultiPolygon acceptance with SRID and
nonpolygon rejection, maximum-overlap matching versus a centroid trap, zone
fallback, extra FEK sources and raster-byte totals. They also check ownership,
table/column grants, grant options, security-barrier options and comments through
view recreation; block custom view bodies, external dependents and non-owner
grant chains; enforce SQL+JSON checksums/adoption prefixes; and detect generated-
column/index drift even on no-op apply. Real replace/upsert/tracked TEE loads
exclude and recompute the generated label point. A failed coverage-text cast
restores data/view OIDs/history through transaction rollback. These are not
crash-durability, production backup-restore or legacy-preparation tests.

Writer cases exercise actual cadastral staging/publication, transitive views,
table/view/index identities, grants/options/comments, rollback after DELETE,
schema-drift refusal, foreign-key cascades, custom triggers, rewrite rules and RLS gates. A
scoped role can publish with SELECT/INSERT/DELETE and sequence USAGE, without
schema CREATE or ownership. An actual held reader lock blocks publication until
release. EMSY upserts retain absent rows and detect unchanged/changed values.
Restricted-writer cases also exercise duplicate lot replacement with only
sequence USAGE: IDs advance on repeat, a later invalid polygon restores the
previous rows and a referencing foreign key blocks truncation without CASCADE.
EMSY loads run under a role without schema CREATE, preserve missing rows and
roll back an earlier update when a later insert fails. Fixtures create EMSY's
table/indexes explicitly through the administrative connection first.
Raster UPSERT preserves every manual judgement; an actual three-GeoTIFF CLI run
proves a DB-rejected middle file cannot discard the successful first/last files.
TEE tests verify all three load modes refresh the raster catalog in the same
transaction, collapse repeated URLs, preserve downloads/metadata and roll back
source changes on catalog failure. A real sync_runs update checks persisted
record totals and table count.

## Restored-backup rehearsal (2026-10-27)

This separate session used the full `gis_Tue.dump` from the NAS, created at
01:00 UTC (03:00 Athens), 117,220,127 bytes. Restore completed with
`pg_restore --exit-on-error --single-transaction` in a new, localhost-only
PG 18.4/PostGIS 3.6.4 container; source versions were PG 18.1/PostGIS 3.6.1.
NOLOGIN role placeholders permitted owner/ACL restoration. The cluster used
explicit UTF-8, temporary memory storage and disabled cron job execution. This
tests logical restore and application behavior, not power-loss durability or
equivalence of every original role's login/membership configuration.

Only the marked restored copy was prepared/adopted as v2. Original values of 93
project tables matched before/after; five affected live views were recreated
with their definitions and metadata. The target contract then had zero findings.
The guarded session scripts and exact SQL/evidence remain in ignored `logs/`;
they are the initial experiments. The supported guarded preparation package
described below supersedes their direct execution.

Both full TEE runs succeeded (55 layers, 22 valid empty sources). The repeat
reported 18,794 unchanged records, zero changes/errors, and a matching sync_runs
summary with 55 checked layers. Actual cadastre imported 3,406 parcels, 21
easements and 725 exclusive-use polygons; a repeat preserved metadata/identities
of 164 public/sp_geodata relations. EMSY returned 72 records. Six actual reports
passed through read-only codex_reader sessions. One 266,914-byte TEE GeoTIFF
download supplied EPSG:2100/resolution/bbox metadata; a small generated GeoTIFF
was ingested into the existing raster_sheets table. This is not an exhaustive
check of all historical raster files or AutoCAD rendering.

At the end of that 2026-10-27 rehearsal, production remained unchanged and
ordinary adoption still blocked. The later production acceptance is recorded
below. The two standard off-NAS folders had stopped at 2026-08-14; fresh local
archives were separately supplied and restored on 2026-10-31.

## Guarded legacy preparation tests and rehearsal

```powershell
& .\.venv\Scripts\python.exe -B tests/run_preparation_tests.py
& .\.venv\Scripts\python.exe -B tests/run_preparation_rehearsal.py `
    --backup logs/restore_2026-10-27.dump --output logs/preparation_rehearsal.json
```

The first command runs 16 tests in a new marked PostgreSQL 18 database on a
random localhost port. Its pinned image is declared in `postgis18_container.py`.
The actual installed schema is a schema-only fixture; all inserted rows are
synthetic. Tests cover reader previews, owner-role application without requiring
a superuser schema owner, direct SQL refusal without the controller guard,
unchanged original values/geometry/metadata, live-only
view options/comments/column grants, new read-only history access, adopted ledger
compatibility, repeat/no-op and receipt checks. Changed bodies, external view
dependencies, nonowner grant chains, duplicate IDs, nonpolygons, partial tracking,
unreviewed constraints, reserved names and stale plans stop before DDL. Injected
postcondition, data/metadata-preservation and receipt-insert failures restore the
source and old view OIDs through rollback. The advisory lock rejects a second
schema operator; a pending writer can commit before the source locks are acquired,
and its committed value remains visible/preserved during preparation.

Eight offline cases additionally verify SQL/descriptor/target checksums, encoding,
explicit apply evidence, archive identity checks, read-only startup/transaction
ownership and cleanup errors. Synthetic format-marker files exercise checksum
gating only; they are not claimed to be logically restorable backups.

The second command independently restores the actual full archive, with owners
and grants represented through NOLOGIN role placeholders. It reads only role
names from the configured source database and all mutations target a newly
created marked localhost container. Cron execution is disabled. The current
archive rehearsal passes: 93 original project tables retain identical values,
the frozen source-specific preparation commits with adopted v2 history, and six
complete point/parcel reports are byte-identical before/after. It verifies the
archive checksum again after restore and removes the exact container it created.
Results, checksums and versions are in ignored `logs/preparation_rehearsal.json`.

The production controller is read-only by default. Before application the
source preview was `ready`, with no findings and `can_apply: false` for
codex_reader. After the 2026-10-31 application it reports `prepared` with valid
history. MIGRATION_PLAN.md describes fresh-backup selection, maintenance, the
explicit apply command and recovery limits. File SHA/format checks alone do not
prove backup freshness, origin or logical restore. These tests do not validate
actual AutoCAD output, production lock duration or a post-commit service cutover.

### Production acceptance — 2026-10-31

The user applied the exact rehearsed preparation with locally entered owner
credentials. Independent read-only checks verify adopted 0001/0002, the receipt
and selected archive SHA, unchanged original values in all 93 project tables,
and zero reader-writable project relations. Another full restore compares the
same six geographic requests on the unmigrated backup, migrated copy and live
database; report bodies match within one process. All temporary containers are
removed. Production remains PG 18.1/PostGIS 3.6.1; the comparison image is
PG 18.4/PostGIS 3.6.4.

Comparing separate processes exposed an existing Python-set ordering issue in
regulation remarks. Sorting those unique comments stabilizes their order;
their contents do not change. Two regressions reproduce the old failure with
three hash seeds and check duplicate/empty handling. All 36 planning service,
builder and report-route tests pass after the fix. The restarted API is healthy;
six real HTTP reports match direct reader responses byte-for-byte and preserve
the unmigrated backup's complete row contents. Posted/operating cadastre and the
unified raster endpoint's `working` default also pass HTTP smoke checks.

Evidence is in ignored `logs/backup_review_20261031/production_postcheck.json`
and `http_postcheck.json`. AutoCAD acceptance and the first production writer run
were still pending at that initial checkpoint; follow-up acceptance is recorded
below.

Settings and setup do not invoke data sync, recreate curated `sp_geodata` layers
or replay raster judgement/exclusion migrations. The historical destructive
`sql/001_tables.sql` is never the migration-test/install entry point.

## Initial sync diagnosis before restricted-writer fixes — 2026-10-31

The fresh archive was restored and prepared in a marked PG18 copy with cron
execution disabled. Current TEE/cadastre/EMSY entry points ran as the existing
non-superuser owner. Source fetches were captured only after their normal
completeness checks; replay used identical input and isolated report/hash files.
TEE passes 55 layers (22 empty). The repeat has 18,794 unchanged records and
zero new/updated/deleted records. Cadastre and EMSY also pass twice.

A clone-only DML writer with sequence access but no owner membership/schema
CREATE passes cadastre. Its TEE run fails on the lot table's sequence ownership
requirement for `RESTART IDENTITY`; EMSY fails on its unconditional setup DDL.
These expected failures diagnose permissions; they are not a fully passing
writer configuration. The failed TEE layer was missing from its JSON table list
and digest, even though the CLI exited nonzero; the follow-up below fixes this gap.
The lot source contains 17 meaningful rows with 11 OBJECTIDs (six duplicate
groups), so replacing it cannot simply be changed to OBJECTID-only upsert.

Relation metadata, curated data and original raster manual/download metadata
survive all phases; six reports remain unchanged. Production data fingerprints
match before/after and the temporary container is removed. Evidence is in
ignored `logs/sync_diagnosis_20261031_195141bc/result.json`. No production writer
role or production sync was created/executed during this diagnosis.

## Restricted-writer fixes and rehearsal — 2026-10-31

`tests.test_sync_runtime_contract` adds seven offline cases for tracking-column
checks without DDL/commit, EMSY setup isolation/preview/invalid options, normal
data-only loading, setup rollback/missing-table guidance, and a real orchestration
failure appearing in JSON/digest without false success counts. Full discovery
passes 209 offline tests (360 discovered, 151 opt-in integration tests skipped).
All 44 disposable PG16 schema/writer tests pass, including the two new limited-
writer replacement/upsert rollback cases described above. Logs are under ignored
`logs/backup_review_20261031/sync_writer_{offline,setup}_tests.log`.

The verified fresh full archive was restored again into a marked PG18 copy and
prepared using the unchanged migration package. A clone-only writer has sequence
USAGE, no owner membership and no schema CREATE. All 55 TEE layers (22 empty),
the three operating-cadastre layers and EMSY pass twice. The first run captures
normally validated live source responses; the repeat reuses exactly that input.
TEE's repeat reports 18,794 unchanged records, zero changes and zero errors. The
lot source remains a 17-row full replacement, preserving meaningful duplicates.
The first EMSY run adds two records to the archive's 70; its repeat reports 72
unchanged, demonstrating writes as well as no-op behavior under the limited role.

Original relation metadata, curated data, raster manual/download fields and six
report bodies remain unchanged. Final preparation validation passes. Production
fingerprints match before/after; the exact temporary container is removed.
Evidence: ignored `logs/sync_diagnosis_20261031_eae6caf3/result.json` and its phase
console/JSON logs. Source-file SHA-256 values match the current runtime files.
This diagnostic grant profile is not a finalized production permission policy.
Production role creation, credential separation and a production writer run
remain pending; `.env` and the API still use the reader.

## Dedicated sync account and menu — 2026-10-31

`tests.test_sync_access` covers missing/owner credential rejection, literal
passwords and API/sync separation, actual child-process settings, atomic local
configuration preserving API keys, failed replace/concurrent-file changes,
read-only preflight/no child on failure, fixed command dispatch/nonzero exits,
menu exit without credentials, SQL/contract agreement, read-only setup preview,
and actual Windows batch-wrapper exit codes. Full discovery passes 221 offline
tests (377 discovered, 156 opt-in integration cases skipped).

`tests.test_sync_access_postgis` adds five marked-disposable cases: real role
creation/login and actual launcher check with separate API/sync settings;
forbidden schema creation, sequence reset, manual raster/curated/history writes;
real downloader pending/status/technical-metadata updates; transaction rollback
of role/grants on injected verification failure; refusal to reset an existing
role/password; a full setup-to-local-file flow with synthetic credentials and
API keys preserved; and rejection of extra column/curated privileges. All 49
disposable PG16 schema/writer tests pass. Existing installed extension-owned
objects/PUBLIC defaults are excluded from the application ACL contract; tests
never change extension grants.

A fresh full-archive PG18 restore additionally tests the exact reviewed SQL via
`create_writer`, verifies real login with the actual `sync_launcher.py --check`,
then runs TEE/cadastre/EMSY twice with those exact grants. First-pass source
capture follows normal completeness checks; replay uses identical input. All six
phases exit zero; repeat TEE has 18,794 unchanged records, zero changes/errors.
Six reports remain unchanged; original relation metadata, curated data and
raster judgements/downloads are preserved. Final preparation checks pass,
production fingerprints match and the exact container is removed. Evidence:
`logs/sync_access_rehearsal_20261031_efed685f/result.json`; automated logs:
`logs/backup_review_20261031/sync_access_{offline,setup}_tests.log`.

After the operator's local setup, the production menu access check passed.
Independent explicit read-only sessions confirm actual epol_sync authentication
and the full application grant contract; codex_reader retains zero write rights
on 128 application relations. All 96 current project-table fingerprints match
their values before role setup. The API remains healthy/connected and its
configured credentials remain reader-only. Evidence is recorded without secrets
in `logs/backup_review_20261031/production_sync_access_verified.json`. The first
production sync and recorded AutoCAD acceptance were still pending at this access
checkpoint; these checks ran no updates. The subsequent TEE acceptance follows.

## First production TEE sync — 2026-10-31

The user confirmed AutoCAD EREPORT/KAEK/ERASTER work. A read-only preview then
verified the full archive SHA, unchanged rehearsed code/SQL, unchanged project
fingerprint, zero other active epol_sync connections and six valid HTTP reports.
The explicit apply ran the actual `sync_launcher.py tee` with the restricted
account, a 5-second lock timeout and a 120-second statement timeout. It ran no
cadastre, EMSY or raster-download step. The CLI exited zero without warnings;
persisted audit run #1 matches the local JSON totals: 55 successful layers,
22 empty, 18,794 unchanged, zero new/updated/deleted/errors.

Reader snapshots preserve relation metadata, all curated/cadastral/EMSY and
migration-history rows, plus existing raster manual/download fields. Independent
semantic hashes of all 55 TEE sources, excluding managed import IDs/timestamps,
are unchanged. Raw fingerprints differ only for the expected full-replaced lot
table and the sync_log/sync_runs audit tables. Six identical-point HTTP report
bodies match their pre-sync hashes exactly; API health remains healthy/connected
with reader settings. No runtime code or schema migration was changed for this
operation. Evidence: `logs/production_tee_20261031_c2f7cb8e/result.json`, the
adjacent before/after snapshots and console log, and `logs/sync_2026-10-31_144037.json`.
Cadastre/EMSY acceptance followed as recorded below; production raster-download
acceptance remains separate.

## First production cadastre/EMSY syncs and parcel digest — 2026-10-31

Read-only preview verified the accepted TEE state, unchanged rehearsed sources,
full-backup SHA, restricted writer and six HTTP reports. Explicit cadastre and
EMSY executions ran separately through the actual launcher with 5-second lock
and 120-second statement timeouts. Both exited zero with no warnings/errors;
postchecks ran between phases. Cadastre has 3,406 parcels and 21 easements as
before; exclusive uses increase 723 to 725. EMSY increases 70 to 72, with two new,
zero updated and 70 unchanged records. No prior EMSY row disappears.

Independent before/after snapshots confirm unchanged metadata, permissions,
views/indexes, data outside the four targets, migration history and raster manual/
download fields. Six report bodies remain byte-identical after each phase and
at completion. Parcel comparison by KAEK additionally finds unchanged KAEK sets,
binary geometries and main uses, but eight prop_hor changes, one prop_vert change
and eight source OBJECTID reassignments. These were not new/removed parcel KAEK.

The old digest tracked geometry/main use but omitted other parcel attributes.
`_diff_before_swap` now detects remaining source attributes by KAEK, ignoring
import IDs/timestamps, and records source OBJECTID changes separately. Three
offline digest cases cover counts, NULL-to-zero, source-ID-only changes and the
old empty-diff shape. A new disposable writer case exercises actual SQL with
property edits, NULL/zero values, reassignments and a repeated import that must
not report gid/synced_at noise. Full discovery passes 224 offline tests (381
discovered, 157 opt-in cases skipped); all 50 disposable PG16 cases pass.

An additional explicitly read-only PG18 SELECT compares all 3,406 actual saved
old/current parcel attribute sets; its eight edits/reassignments match the
independent comparison. Publication/fetch/validation/transaction functions are
AST-identical to the runtime used for the accepted production writes. No new
production import was run for this report-only fix. The verified digest was
regenerated from saved snapshots; the original runtime digest remains archived.
Evidence: `logs/production_cadastre_emsy_20261031_7c7f643b/result.json`, adjacent
snapshots/phase console logs, `parcel_kaek_comparison.json`,
`attribute_digest_pg18_readonly.json` and `ktima/KTIMA_CHANGES_verified.md`.
Test logs: `logs/backup_review_20261031/cadastre_digest_{offline,setup}_tests.log`.

## Λίστα δοκιμών — νέες εντολές (2026-07-11)

> Πριν ξεκινήσεις: restart `start_server.bat` + reload το LISP.
> Σημείωνε ✅/❌ και τι είδες — τα διορθώνουμε στην επόμενη session.

### 1. KLAYERS
- [ ] Τρέξε σε κενό σχέδιο → 30 layers, σωστά χρώματα (PST_KAEK=16, TOPO_PROP=30, AREA_A=6)
- [ ] LINE_XM / LINE_XM_VST πήραν διακεκομμένη JIS_02_2.0 (όχι Continuous);

### 2. KPST
- [ ] Σε γεωτεμάχιο με κάθετες (π.χ. 051341520004): πολύγωνα στο PST_KAEK, ΚΑΕΚ ως TEXT
- [ ] ΑΧ στο VST_PST με labels AX 01/02/03
- [ ] Σύγκρινε οπτικά με επίσημο ΚΔ αν έχεις πρόχειρο — ταυτίζεται;

### 3. KCHECK
- [ ] Σε παλιό ΔΓΜ που έχει περάσει: τρέξε το αντίστοιχο προφίλ → πρέπει PASS
- [ ] Βάλε επίτηδες ένα MTEXT στο PST_KAEK → πρέπει να το πιάσει
- [ ] Άνοιξε μια polyline του TOPO_PROP (explode/open) → πρέπει να το πιάσει

### 4. KGEOM (διόρθωση ορίων)
- [ ] Σε πραγματική περίπτωση που έχεις λύσει με το χέρι: σύγκρινε Δ/Α εμβαδά
- [ ] Ισοζύγιο στον πίνακα με ✓;
- [ ] Slivers: λογικός αριθμός; (αν πολλά → κατέβασε tolerance και ξανά)

### 5. KGEOMV (διόρθωση καθέτων)
- [ ] 2-3 μετρημένες κάθετες → σωστή αντιστοίχιση με κτηματολογικές ΑΧ;
- [ ] Πίνακας τίτλος/ΚΤ/μέτρηση — τα χιλιοστά βγάζουν νόημα;
- [ ] LINE_XM_VST: μόνο εσωτερικές γραμμές (όχι το περίγραμμα);

### 6. KVERT
- [ ] Κλειστό πολύγωνο: κύκλοι σωστό μέγεθος στην κλίμακα εκτύπωσης;
- [ ] Δεύτερο πολύγωνο με κοινή πλευρά → «reused existing names», όχι διπλοί κύκλοι
- [ ] Πίνακας: 3 δεκαδικά, ελληνικοί τίτλοι ΟΚ (όχι αλαμπουρνέζικα)

### 7. KGRID
- [ ] 1:500 → σταυροί ανά 50μ σε στρογγυλές συντεταγμένες
- [ ] Χ κατακόρυφα κάτω/πάνω, Υ οριζόντια — σωστές θέσεις/μεγέθη σε εκτύπωση;

### 8. AIGDRAW
- [ ] Σε παραλιακή περιοχή: κόκκινο/κίτρινο/μπλε σωστά, ΦΕΚ labels σωστά ελληνικά
- [ ] ΠΟΑ γραμμές μαρκαρισμένες «(ΠΟΑ)»

### Γνωστά όρια (μην τα αναφέρεις ως bugs)
- KCHECK: όχι τοπολογικά (snap/κόμβοι) — επόμενη φάση
- KGEOM/KGEOMV: όχι hatches/βελάκια — επόμενη φάση
- «Κάθετες ΚΔ» layer: χειροκίνητα (ελληνικό όνομα από LISP σπάει)
- KPST: για υποβολή, επιβεβαίωση με επίσημο ΚΔ
