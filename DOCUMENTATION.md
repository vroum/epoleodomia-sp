# TEE Urban Planning Data Mirror — Spetses Island

## Complete Technical Documentation — v1.2

**Project Location:** `O:\claude_code area\mega project postgis-autocad\lisp for acad v2 - Copy\clean\`
**Database:** PostGIS on `10.90.144.153:65432`, database `gis`, schema `epoleodomia`
**Coordinate System:** EPSG:2100 (GGRS87 — Greek Geodetic Reference System)
**Coverage Area:** Spetses Island, Greece
**Credentials:** `.env` file (never committed to source control)

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Data Sources](#2-data-sources)
3. [Installation & Setup](#3-installation--setup)
4. [How to Sync / Update Data](#4-how-to-sync--update-data)
5. [Data Inventory](#5-data-inventory)
6. [Database Schema](#6-database-schema)
7. [Views and Joins](#7-views-and-joins)
8. [Raster Planning Diagrams](#8-raster-planning-diagrams)
9. [Empty Tables](#9-empty-tables)
10. [Key Findings](#10-key-findings)
11. [Useful Queries](#11-useful-queries)
12. [Change Tracking System](#12-change-tracking-system)
13. [Local Log Files](#13-local-log-files)
14. [Troubleshooting](#14-troubleshooting)
15. [Operational Notes](#15-operational-notes-2026-06-27)

---

## 1. Project Overview

This project mirrors Greek urban planning data from the **TEE (Technical Chamber of Greece) ArcGIS REST Services** to a local PostGIS database. The data covers urban planning regulations, building blocks, archaeological sites, environmental zones, and administrative boundaries for the **Spetses Island** area.

### Why This Project?

The original TEE data source provides tables without joins, making it difficult to:
- Link building blocks to their regulations (height, coverage, FAR)
- Find all legal references (FEK) for a specific area
- Perform spatial analysis across different data layers

This mirror database solves these problems by:
- Storing all data locally in PostGIS
- Providing pre-built views that join related tables
- Enabling spatial queries using PostGIS functions
- Allowing offline access to the data
- **Downloading georeferenced planning diagram TIFs** for use in CAD/GIS

### Project Structure

```
clean/
├── .env                   # Database credentials (git-ignored)
├── .env.example           # Template for .env
├── .gitignore             # Excludes .env, __pycache__, logs, rasters
├── api_server.py          # FastAPI API used by AutoCAD LISP commands
├── api_launcher.py        # Reserve listener before DB startup; recognize an existing API
├── settings.py            # Shared literal .env parsing and runtime settings
├── database_setup.py      # Read-only schema preview; explicit atomic apply/adopt
├── planning_data.py       # Injected GIS providers and report collection
├── planning_reports.py    # Pure point/parcel report builders (no DB/HTTP imports)
├── boundary_corrections.py # KGEOM spatial calculation and text output
├── vertical_corrections.py # KGEOMV validation, clipped AX matching and text output
├── cadastre_geometry.py   # Shared survey validation/model, KAEK filters and rings
├── database_sessions.py   # Pooled read-only repeatable-read transactions
├── epoleodomia.lsp        # LISP loader (v2.1) - loads the 6 epol-*.lsp modules
├── epol-core.lsp          #   config, HTTP, parsing, layers, drawing, tables
├── epol-site.lsp          #   OROITABLE ETABLE EREPORT ENOTES ARCHEO CHURCH
│                          #   NATURA AIGIALOS REMATA
├── epol-bounds.lsp        #   KAEK EKAEK OT EOBT KAEK_OP
├── epol-ktima.lsp         #   KLAYERS KPST KGEOM KGEOMV KVERT KGRID
│                          #   AIGDRAW KCHECK
├── epol-raster.lsp        #   FEK DJI DE CLIPR
├── epol-util.lsp          #   ETRANS ELAYERS EHELP
├── kexport.lsp            # KEXPORT (loaded separately)
├── kfilters.lsp           # KFILTERS KFILTERSDEL KTSEED (loaded separately)
├── config.py              # Service URLs, bbox, DB settings (reads .env)
├── ingest_rasters.py      # Register locally georeferenced map sheets (GYS 5000,
│                          #   aigialos, historic) -> sp_geodata.raster_sheets
├── fetch_layer.py         # ArcGIS REST API query functions
├── load_postgis.py        # GeoJSON to PostGIS loader with change tracking
├── prepare_legacy_database.py # Guarded known-installation preparation; read-only preview default
├── sync_all.py            # Main CLI orchestration script
├── sync_kaek_operating.py # Hellenic Cadastre operating parcels sync
├── download_rasters.py    # Raster planning diagram downloader
├── logger.py              # Local log file generator
├── sync_menu.bat          # Windows entry point for all sync jobs
├── requirements.txt       # Python dependencies; settings use the standard library
├── README.md              # Quick start guide
├── MIGRATION_PLAN.md      # Maintenance, backup rehearsal, explicit apply and recovery
├── DOCUMENTATION.md       # This file
├── API_SPEC.md            # FastAPI endpoint specification
├── SP_GEODATA_CLEANUP.md  # sp_geodata schema audit
├── logs/                  # Sync log files (.log and .json)
├── rasters/               # Downloaded planning diagram TIFs (in v1.0 dir)
│   └── georef/            # Georeferenced TIFs organized by FEK
└── sql/
    ├── migrations/        # Immutable numbered SQL; fresh TEE baseline is 0001
    ├── preparations/      # Frozen source-specific preparation SQL and contract
    ├── tee_baseline_manifest.json # Structural adoption contract
    ├── 001_tables.sql     # Historical destructive rebuild; not the setup entry point
    ├── 002_views.sql      # All views (corrected)
    ├── 003_seed.sql       # Post-sync seed (raster catalog, forest areas)
    └── 004_raster_sheets.sql  # Generic sheet catalog + v_all_rasters +
                            #   raster_exclusions + rasters_at_point()
```

---

### Planning report boundary

Direct API startup and `start_server.bat` use `api_launcher.run_server()`.
It reserves the configured listener before opening the database pool and passes
that same socket to Uvicorn. When binding fails, it checks the existing service's
OpenAPI title and health on that address; a healthy Epoleodomia API is reused.
An unhealthy API or another/unavailable service produces an error. The existing
listener is preserved. Wildcard listen addresses use loopback for the checks.

`api_server.py` opens one read-only repeatable-read snapshot for `/report/rows`
or `/report/parcel` and injects its query session into `planning_data.PlanningData`.
That service owns GIS queries, provider dictionaries and report collection,
then calls `planning_reports.build_point_report()` or `build_parcel_report()`.
It imports no FastAPI, database driver, environment settings or connection pool.
Parcel distances and overlap queries still use the
parcel polygon; building regulations and stream plan-status checks still use
the clicked point. Missing parcel/regulation errors return before collecting
the remaining sections, and outside-plan status is explicitly checked by the service.

All registered required sources are ACCESS SHARE locked before the first SELECT,
including sources for conditional sections. Required sources must exist and be
readable. The EMSY relation is prelocked in a savepoint; if it cannot be locked,
the service records it as unavailable and never queries it during that report,
even if it appears later. Archaeology approval checks and both EMSY queries run
as separate optional groups in savepoints. A failed group rolls back to its
savepoint, preserving the outer snapshot and previously acquired source locks.
Partial EMSY results are discarded. Required query errors still abort the report.
Failed savepoint setup/recovery/release cannot be hidden by an optional provider:
the snapshot fails and its connection is discarded. Every exit rolls back and
returns or discards the pooled connection through `database_sessions.py`.

Source registries are `POINT_REPORT_RELATIONS`, `PARCEL_REPORT_RELATIONS` and
`OPTIONAL_REPORT_RELATIONS` in `planning_data.py`; update them when adding a
source. The API retains thin provider adapters for other existing endpoints and
ENOTES. Those adapters keep their previous per-query connection behavior;
the report snapshot applies to the two complete report endpoints.

Natura is compatible with both legacy tables (no `is_deleted`)
and tracked installations. `PlanningData` checks column availability in the
same injected query session and caches it only for that collector. When the
field exists, deleted rows remain excluded; when absent, legacy records are
read without referencing a nonexistent column. Catalog failures propagate.
The check does not add columns or cache schema assumptions across requests.

`planning_reports.py` owns report section order, regulation/approval rows,
shoreline summaries, forest warnings, EMSY labels and Windows-1253 character
replacement for the existing `TYPE|col1|col2` protocol. It performs no I/O and
does not modify its input dictionaries. Shared shoreline labels, forest-use
codes and the water-point label helper are also imported by the API's other
endpoints/notes, so their definitions stay in one place. The existing planning
assumptions and legal wording are preserved. Synthetic fixtures exercise both
the pure builders and API routes; see `TESTING.md` for coverage and limits.

Spatial providers retain zero distances for monuments/churches, ignore deleted
Natura features and require positive area for Natura/protection-zone parcel
overlaps. Boundary contact alone is not area overlap. Forest features are unioned
within each classification before calculating percentages; total ratified
coverage is a separate union across all classifications. Both the 98% fallback
threshold and 0.5% sliver filter use unrounded values. When coverage is below
98%, both complete source layers are still reported separately, with the
existing warning; posted features are not clipped into an authoritative mosaic.
Different forest classifications may conflict spatially and must be reviewed.

The city-plan test includes its boundary. If a boundary click has no applicable
regulation result, the report returns the existing missing-regulations error
instead of automatically applying outside-plan rules. Regulation point lookups
remain strict containment; this does not resolve conflicting sectors at shared
boundaries. The archaeology point check retains its existing distance-under-1m
tolerance, whereas parcel zones use positive area overlap.

Read-only PostGIS tests run the actual provider SQL and both report routes
against synthetic VALUES, including holes, multipart parcels and repaired
source polygons. Report fixtures use the actual snapshot cursor/savepoints,
check one backend/snapshot/read-only mode and exercise optional query failures.
Catalog-only tests separately verify relation locks and missing optional
sources. A consistent read does not make an entire multi-table sync publish
atomically. Disposable writer tests now exercise a held reader blocking cadastral
publication until release; production contention/timing remain unmeasured.

---

### KGEOM boundary corrections

`POST /geom/diorthosi` accepts one surveyed ring in EPSG:2100 as
`x,y;x,y;...`, with a finite, nonnegative `tol` in m² (default `0.5`).
`cadastre_geometry.parse_survey_ring()` closes the ring and requires three
distinct finite vertices before any connection is acquired. The spatial
calculation requires a valid polygon with positive area; it does not repair the
supplied survey. The subject is the
non-EK parcel with the largest positive overlap. Boundary-only contact cannot
select a subject.

Claimed area (`Δ = survey − subject`) is intersected with each donor parcel and
split at donor boundaries. Every donor with a retained piece appears in the
affected-parcel results. Cut pieces (`Α = subject − survey`) go to the neighbor
with the longest positive shared boundary; corner-only contact is insufficient.
Equal overlap/boundary rankings use KAEK order for repeatability. EK/ΕΚ parcels
can participate in transfers and the table, but their final geometry is not drawn.

The current `OK`/`D`/`A`/`F`/`TBL` text protocol is preserved. Significant
unmapped claims, overlapping donor coverage, unassigned cuts and holes in
drawable transfer/final polygons return `ERROR|...` for review. Each donor piece
is filtered against `tol`; omitted pieces are counted and their area is shown.
The subject final remains the supplied survey, so filtering can produce a
nonzero balance warning. The output format does not support polygon holes.
See `TESTING.md` for synthetic read-only PostGIS checks and remaining limits.

`api_server.py` handles request decoding, input errors and transaction ownership.
It passes the prepared `SurveyRing` and a query callable to
`boundary_corrections.calculate_boundary_correction()`. That module owns the
calculation SQL and output formatting and imports neither FastAPI, database
drivers nor configuration. `cadastre_geometry.py` shares the existing KAEK
survey model/validation, KAEK filters and coordinate/ring formatting with the
other geometry service and API endpoints. The boundary module continues to
expose its previous survey-parser/model imports.

Each KGEOM calculation runs through `database_sessions.read_only_snapshot()`:
one pooled connection/cursor, a transaction-local `REPEATABLE READ, READ ONLY`
setting and an `ACCESS SHARE` lock on the operating-parcels relation before the
first SELECT. Updates cannot change its snapshot, and table replacement must
wait for its read lock to be released. Success, business-error responses and
exceptions all end with rollback; autocommit is restored and the connection
returns to the pool. A connection that cannot be cleaned up is discarded.
KGEOMV uses the same transaction lifecycle for its two source relations. The
remaining API endpoints still use their existing query lifecycle.

### KGEOMV vertical-property corrections

`POST /geom/kathetes` accepts one `V|number|title_area|title_xiliosta|coords`
record per surveyed vertical. `vertical_corrections.parse_vertical_survey()`
prepares immutable records before acquiring a connection: every nonblank line
must be valid, numbers must be unique after auto-numbering, coordinates and
tolerance must be finite, title area must be nonnegative and title xiliosta
must be between 0 and 1000. Empty title fields remain unknown; empty numbers
use the input order (`01`, `02`, ...), independently of cadastral AX numbering.
The common ring validator closes each ring and requires three distinct vertices.

`calculate_vertical_correction()` rejects invalid/zero-area survey polygons
without repairing them. The parent is the non-EK parcel with the largest positive
overlap with the survey union. Each vertical is clipped to that parent. A clip
must have positive area and meet `tol` using its unrounded area; ignored units
do not affect common remainder, overlap checks or internal change lines. The
remainder is the parent minus the union of retained clips, so overlaps are not
double-counted. Multipart clips retain all final components; polygon holes fail
explicitly because the drawing protocol cannot represent them.

Cadastral AX matching uses positive overlap with the clipped survey. Touch-only
contact cannot match. Equal largest overlaps resolve by number and warn for
review; repeated matches to the same AX, explicit number mismatches, missing
matches, lost area, survey/title-area differences and pairwise overlaps also
warn. Missing/duplicate cadastral AX numbers or invalid stored areas return an
error rather than silently overwriting the source area. A multipart AX can be
stored as one record with one unique number. Title xiliosta are presented as
supplied; computed xiliosta are geometric area ratios, not ownership validation.

The API keeps the existing `OK`/`VF`/`L`/`TBL` protocol. Its read-only repeatable-read
transaction protects both `kaek_parcels_operating` and
`kaek_apokleistikes_operating` with ACCESS SHARE locks before the first SELECT.
This provides one database snapshot per calculation; atomic publication of an
entire multi-table sync is a separate concern. SQL/formatting live in
`vertical_corrections.py`, with no FastAPI, database-driver or config imports.
The remaining AutoCAD acceptance and production concurrency/performance checks are
listed in `TESTING.md` and `STATUS.md`.

---

## 2. Data Sources

### TEE ArcGIS REST Services

**Base URL:** `https://sdigmap.tee.gov.gr/mapping/rest/services/UDM/`

| Service Name | Description | Layers |
|--------------|-------------|--------|
| `UDM_SERVICE_POLEODOMIKI_PLIROFORIA` | Urban Planning | 24 layers |
| `UDM_SERVICE_BUILDINGS` | Addresses | 1 layer |
| `UDM_SERVICE_SXEDIA_DOCS` | Planning Diagrams | 1 layer |
| `UDM_SERVICE_POLEOD_RYM_SXD` | Approved Plans | 1 layer |
| `UDM_SERVICE_ARCHAIOLOGIKO` | Archaeological | 14 layers |
| `UDM_SERVICE_NATURA_DASIKA` | Natura & Forest | 4 layers (ratified + posted) |
| `UDM_SERVICE_RYTHMISEIS_EXOASTIKOU_CHOROU` | Rural Regulations | 4 layers |
| `UDM_SERVICE_FEK_NO_SXEDIA_DOCS` | FEK without Diagrams | 1 layer |
| `UDM_SERVICE_YPD` | Zone-level Building Regs | 1 layer |
| `UDM_SERVICE_ELSTAT` | Administrative (ELSTAT) | 5 layers |

### Raster Data Sources

**TIF URL Pattern:** `https://sdigmap.tee.gov.gr/_Digitize_LOW/2_GEOREF_EGSA_LOW/*.tif`

- Georeferenced planning diagrams in GGRS87/EGSA (EPSG:2100)
- Organized by FEK (Government Gazette) reference
- 103 TIF files for Spetses area (~512 MB total)

### Curated `sp_geodata` Layers Used by AutoCAD Reports

The AutoCAD API does not rely only on the `epoleodomia` schema. Several operational report sections use curated or manually maintained layers in `sp_geodata`:

| Report Section | Main Tables | Notes |
|----------------|-------------|-------|
| KAEK / parcel geometry | `kaek_parcels_operating`, `kaek_parcels_autocad` | Operating cadastre is synced by `sync_kaek_operating.py`; special-use parcels marked `EK`/`ΕΚ` are excluded in report parcel resolution. |
| Αιγιαλός / Παραλία | `Αιγιαλός_Παραλία` | Used by `/aigialos` and `EREPORT`; includes current, POA, beach, and old-shoreline lines with FEK refs. |
| Αρχαιολογία | `Αρχαιλογία_Κυρηγμένα_Μνημεία`, `Αρχαιολογία_Ζώνες_Προστασίας` | The monuments table name is misspelled in the database. Protection zones are stored as `MultiLineString` and must be converted with `ST_BuildArea(geom)` for containment/overlap checks. |
| Εκκλησίες / Ρέματα / DJI / DE | `Εκκλησίες_*`, `Ρεματα*`, `dji_footprints`, `de_footprints` | Used by point and parcel report commands. |

### Spetses Bounding Box (EPSG:2100)

```
Min X: 416555    Max X: 431409
Min Y: 4116249   Max Y: 4129267
```

---

## 3. Installation & Setup

### Prerequisites

- Python 3.10+ (the API and geometry modules use modern annotations)
- PostgreSQL with PostGIS extension
- Access to the PostGIS database

### Step 1: Install Python Dependencies

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Required packages:
- `requests>=2.28.0` — HTTP requests to ArcGIS REST API
- `psycopg2-binary>=2.9.0` — PostgreSQL adapter
- `tqdm>=4.64.0` — Progress bars for raster downloads
- `rasterio>=1.3.0` — Required TIF metadata extraction

### Step 2: Configure Database Connection

Copy `.env.example` to `.env` and set your password:

```bash
copy .env.example .env
# Then edit .env with your credentials
```

The `.env` file is git-ignored. `settings.py` reads this project's `.env` by its
absolute location, independent of the working directory. The API, TEE loader,
cadastre, EMSY and raster ingestion use the same settings. Process variables
override the file across both naming families; within one source `EPOL_DB_*`
wins over the legacy `DB_*` alias. Defaults apply only when a key is absent.
Invalid/empty connection fields, ports and timeouts fail with value-free errors.
`EPOL_DB_SCHEMA` is fixed to `epoleodomia`, matching the API's schema-qualified SQL.

Values are literal, without interpolation or escape expansion. # and ; comment
lines, matching quotes, `export` and a UTF-8 BOM are supported. Unquoted inline
comments require preceding whitespace; quote passwords containing that pattern.
Shell metacharacters and Windows backslashes are preserved. Settings do not
modify process environment variables and secret fields are omitted from repr.
`EPOL_DB_CONNECT_TIMEOUT` defaults to 10 seconds (1–300); `EPOL_API_HOST` and
`EPOL_API_PORT` preserve the existing `0.0.0.0:8000` defaults. Changing the API port
also requires updating the AutoCAD client's URL. Raster roots use the existing
`EPOL_RASTER_BASE_PATH`, `EPOL_DJI_RASTER_PATH` and `EPOL_FEK_LOCAL_PATH` options.
Optional `EPOL_RASTER_NAS_PATH` enables the versioned TEE file archive and the
menu's NAS restore/download/publish cycle; omitted/blank leaves NAS copying off.

Both Windows launchers prefer `.venv\Scripts\python.exe` and let Python parse
credentials. They do not expand passwords through cmd.exe or override process
settings from the file. Server startup no longer terminates another process
holding port 8000; an occupied port produces the normal bind error.

### Step 3: Preview setup, then explicitly apply a reviewed plan

```bash
# Default: read-only catalog/history inspection, no DDL or sync
python database_setup.py

# Empty TEE schema: apply the reviewed fresh-install plan
python database_setup.py --apply

# Existing installation: inspect structural compatibility before adoption
python database_setup.py --adopt
# Record the compatible prefix; apply any later migrations shown by preview:
python database_setup.py --adopt --apply
```

PostGIS and the database must already exist; the tool does not install extensions
or create databases. Fresh TEE setup runs the immutable `0001_tee_baseline.sql`
followed by `0002_live_tee_contract.sql` in one transaction. Version 1 creates
the TEE tables, indexes, audit structures, raster catalog and land-use lookup;
version 2 incorporates the reviewed live improvements. It adds the generated
`building_blocks.label_point`, restores the four evolved view definitions and
accepts Polygon/MultiPolygon in sixteen observed multipart tables while keeping
EPSG:2100 and rejecting point/line geometries there. Text limits only widen;
already wider limits are retained. Coverage is converted to double precision,
and unparseable old text aborts/rolls back rather than becoming NULL. Duplicate
`building_regs_lot` object IDs remain allowed.

An occupied unmanaged schema is never rebuilt. Adoption finds the highest
explicitly described compatible state and records that prefix without replay.
Thus a compatible v2 installation records versions 1 and 2 as adopted; a
compatible v1 installation records v1 and applies the reviewed v2 migration.
Preview prints the separate actions. The installation audited on 2026-10-27
matched neither state. Its reviewed preparation was applied on 2026-10-31;
production now records adopted v2 history and ordinary setup reports `managed`.

The adjacent `0002_live_tee_contract.json` supplies preconditions/postconditions:
relation/column types, keys/checks, valid index signatures, generated-column
attributes and four managed view definitions. Unrelated objects/extra columns
are allowed. An edited managed source view blocks replacement. Three views
need recreation because their row types change; external dependent views block
preview/apply, and SQL uses RESTRICT throughout. Effective table/column grants,
grant options, ownership, view options and comments are preserved. Security
labels or non-owner grant chains require a separate plan and block recreation.
Only an explicit reviewed PostgreSQL 16/18 rendering variant is accepted for
the redundant FEK-view UNION alias; SQL literals/definitions are not broadly
normalized. Adoption is not certification of data or legal/source semantics.

History lives in `epol_meta.schema_migrations`, including filename, SHA-256,
timestamp and applied/adopted mode. Adopted records must form a contiguous
prefix. For migrations with an adjacent contract, the checksum covers both SQL
and JSON bytes; v1 retains its original SQL-only checksum. Unknown, modified or
gapped history blocks changes. Future migrations start at `0003_*.sql`; never
edit an applied file. SQL files are trusted repository code and must qualify
their target objects, avoid transaction control and stay inside a transaction.
Setup serializes its writers with an advisory transaction lock, uses a 5-second
DDL lock timeout/120-second statement timeout, and commits SQL plus history
together. Failures roll back; repeat apply with no pending migrations is a no-op.
Preview and apply independently inspect the target, so a prior preview is never
used as a stale execution plan. Back up an existing database before applying
reviewed structural changes. Contract-covered states are checked even on a
no-op apply; this remains a check of declared properties, not a full drift audit.

`sync_all.py --init` is now a standalone **read-only preview alias**, and rejects
combinations with sync modes. The historical `sql/001_tables.sql` remains a
destructive rebuild script; neither setup entry point runs it. `003_seed.sql`
performs separate historical seed updates and is not automatically replayed.
Current planning-diagram loaders execute `006_refresh_raster_catalog.sql` inside
their data transaction: new active nonblank URLs enter the existing catalog as
pending; duplicate URLs are deterministic. Reference fields can change, while
download paths/status, bbox, recorded RMS/scale and other technical metadata are
preserved. A catalog failure rolls back the corresponding diagram load.
The curated `sp_geodata` sources, operating-cadastre/EMSY imports and existing
raster-unification workflow still need their own installation/data procedures;
a fresh TEE baseline alone is not a complete populated AutoCAD GIS installation.

---

## 4. How to Sync / Update Data

### Using sync_menu.bat (Recommended)

The API keeps its `EPOL_DB_*` reader credentials. The menu uses a dedicated
`epol_sync` account through `sync_launcher.py`; it never falls back to API or
owner credentials. The one-time setup is separate from schema migrations:

```batch
setup_sync_writer.bat          # Read-only preview
setup_sync_writer.bat --apply  # Local administrator password prompt
sync_menu.bat --check          # Read-only login/privilege check; no sync
```

Apply creates a new role and explicit grants in one transaction, verifies its
scope, then verifies an actual login before saving two `EPOL_SYNC_DB_*` keys
atomically in `.env`. The generated password and administrator password are
never printed or placed in shell arguments. Existing API settings retain their
values. Setup refuses to reuse or reset an existing role; `--configure` instead
checks and saves an existing `epol_sync` password entered privately. If the
database commit succeeded but local configuration failed, an administrator can
set a new role password and then use `--configure`. No setup command runs syncs.

Review `sql/admin/epol_sync_writer.sql`: read access covers 66 explicitly named
relations, including migration history and the posted-cadastre reference view.
Tracked TEE tables get INSERT/UPDATE; the duplicate-key lot table gets
INSERT/TRUNCATE. Audit tables get their required INSERT/UPDATE, three operating
cadastral tables get INSERT/DELETE, and EMSY gets INSERT/UPDATE. The existing
raster catalog gets column-scoped INSERT/UPDATE for source references and
download metadata, protecting existing RMS/scale from runtime UPDATE. Only
sequences attached to runtime target tables get USAGE. There is no project
schema CREATE, database CREATE, sequence reset, owner membership or grant on
curated source tables, exclusions, `raster_sheets`, or `sp_ais`. New tables require
a reviewed access-contract change; no default privileges are broadened.

The preflight checks effective application-table/column/sequence rights and role
attributes read-only. Existing extension-owned objects and their installed
PUBLIC permissions remain outside this application grant contract. The setup
requires existing compatible sources and matching managed-v2 history; it does
not install source tables. Administrative credentials are used only during
explicit setup. The menu's runtime account has no administrative role attributes.

```batch
sync_menu.bat              # Interactive menu
sync_menu.bat tee          # TEE epoleodomia tables
sync_menu.bat ktima        # Operating cadastre
sync_menu.bat ydro         # EMSY ydrolipsies
sync_menu.bat rasters      # Raster downloads
sync_menu.bat all          # TEE + cadastre + ydrolipsies
sync_menu.bat all-rasters  # All + rasters
```

### Using Python Directly

`python sync_launcher.py tee` (or another menu mode) uses the same scoped
credentials/preflight as the batch menu. Lower-level script examples below use
the ordinary `EPOL_DB_*` process settings; run them only in a deliberately
configured writer process. They do not read the separate sync password by
themselves. Keep the API's `.env` connection on its reader account.

```bash
# Full sync with change tracking
python sync_all.py --track

# Sync specific table
python sync_all.py --track --table building_blocks

# Sync specific service
python sync_all.py --track --service UDM_SERVICE_POLEODOMIKI_PLIROFORIA

# Test mode (building_blocks only)
python sync_all.py --test

# Dry run (check counts)
python sync_all.py --dry-run

# Sync with rasters
python sync_all.py --track --rasters

# Rasters only
python sync_all.py --rasters-only

# List available tables
python sync_all.py --list
```

### Sync Exceptions / Important Notes

- TEE downloads are validated in memory before loading. HTTP/ArcGIS errors,
  malformed responses, empty or repeated pages before completion, excess rows,
  and a changed source count abort that table's sync. A short page alone is not
  treated as completion because service page-size limits vary. The source count
  is checked again after downloading; this detects count changes, not every
  possible remote edit during paging.
- TEE table data loads are transactional: any record or change-audit write
  failure rolls back that load and is reported as an error. Invalid input and
  missing/duplicate tracking IDs are rejected before connecting to PostgreSQL.
  Other successfully synced tables remain committed if a later table fails.
- A verified zero-count source keeps the existing table untouched. This is a
  deliberate safeguard; retiring an entire dataset requires a separate decision.
- Offline regression tests: `python -m unittest discover -s tests -v` (see
  `TESTING.md`). TEE, operating-cadastre and EMSY safeguards are covered; the
  separate raster downloader still needs its own reliability review.
- Tracked TEE geometry changes use batched PostGIS `ST_Equals` comparisons in
  `sync_geometry.py`, with the stored geometry transported as EWKB to preserve
  coordinate precision. Coordinate moves, holes and NULL transitions are
  detected. Reversed rings, reordered vertices and redundant collinear points
  with the same occupied 2D space are unchanged. There is no snapping or distance
  tolerance. Audit records retain the spatial comparison result. This is change
  detection, not a replacement for topological or legal validation.
- Operating-cadastre downloads (`sync_kaek_operating.py`) validate metadata and
  query source object IDs before fetching geometry. Batches use POST to avoid
  URL length limits, account for every requested ID exactly once and recheck
  source membership after completion. Short capped batches request the missing
  IDs; failed, duplicate, unexpected or missing records stop before table SQL.
  Source fields, KAEK and polygon presence are checked before staging. Staged
  row count and nonempty valid polygons are checked before publication. Existing
  destinations are locked and updated with transactional DELETE/INSERT, retaining
  table/index/view identities, owners, grants and comments. No DROP/CASCADE is
  used. Unknown columns/types, row security, custom triggers or referencing foreign
  keys, plus rewrite rules, block publication for review; schema changes are never guessed. A first
  import creates the ordinary source table/indexes. `gid` is an import identifier,
  not a stable consumer key. Write failures explicitly roll back. A verified empty source keeps
  the existing table and exits unsuccessfully, preserving the earlier behavior.
  ID snapshots detect membership changes, not concurrent edits to attributes
  or coordinates of the same IDs. Earlier successful layers remain committed
  if a later layer fails.
  The parcel digest compares by KAEK: new/removed keys, spatial changes, main use
  and other source attributes (including prop_hor/prop_vert). Source OBJECTID
  reassignments are listed separately; gid/synced_at import changes are ignored.
  Eight source IDs changed for unchanged KAEK/geometries in the first production
  run, so source OBJECTID must not be treated as a durable parcel-consumer key.
  Easement/exclusive-use digests still report counts only.
- EMSY (`sync_ydrolipsies.py`) verifies source counts/ID snapshots and fetches
  required attributes using POST ID batches. It does not trust the source's
  transfer-limit flag as proof of completeness. Every record must contain the
  expected nullable attribute keys and finite point coordinates declared in
  EPSG:2100, inside the requested bbox. Missing fields, duplicate/unrequested
  IDs, wrong/absent CRS and changed source membership abort before loading.
  Invalid records are rejected rather than silently skipped. Upsert failures
  explicitly roll back the whole load. Absent source records remain stored;
  there are still no deletions. Empty input and dry runs use no database
  connection. Direct CLI execution now uses the shared `.env`/database config.
  Ordinary loads run no setup DDL. `python sync_ydrolipsies.py --init` previews
  the table/index setup without connecting or fetching data; an administrator
  can apply it separately with `--init --apply`. Existing prepared installations
  already have the EMSY table and do not need this setup replayed.
- Synthetic reference cases for `/report/parcel` and `/report/rows` are in
  `tests/fixtures/reports/`, with explicit expected pipe-delimited rows. They
  freeze current report behavior for refactoring; they do not verify the law,
  source classifications or the spatial calculations supplying those rows.
- `building_regs_lot` (TEE Layer 17) is synced with full replace even when `--track` is used. The source service can return two meaningful rows with the same `OBJECTID` (`ΚΑΤΑ ΚΑΝΟΝΑ` and `ΚΑΤΑ ΠΑΡΕΚΚΛΙΣΗ`), so objectid-only change tracking collapses/overwrites records.
- Full replacement uses `TRUNCATE ... CONTINUE IDENTITY` in the load transaction.
  Generated import IDs advance across reloads; runtime writers need sequence
  USAGE, not sequence ownership/reset rights. A failed insert restores the old
  rows; sequence gaps are normal. Foreign-key consumers block truncation rather
  than being removed with CASCADE. Tracked loads require the managed tracking
  columns and never add columns or commit setup work implicitly.
- Failed TEE layers appear in the JSON table list and `CHANGES_latest.md` with
  their reason. The summary counts failures separately from successful/empty
  layers, and the CLI returns nonzero when any layer fails.
- After the 2026-06-27 targeted sync, `building_regs_lot` contains 17 rows. The Spetses 740Δ/1981 sectors are:
  - Τομέας Α/Β/Γ: 300 τ.μ. / 12 μ.
  - Τομέας Δ: 500 τ.μ. / 15 μ.
  - Τομέας Ε: 1000 τ.μ. / 25 μ.
- `config.py` re-exports the shared `settings.py` database configuration; the same precedence and literal parsing apply to every client.

### Download Rasters Only

```bash
# Download all pending rasters
python download_rasters.py

# Dry run - show what would be downloaded
python download_rasters.py --dry-run

# Download specific FEK only
python download_rasters.py --fek "1385Δ/1992"

# Force re-download existing
python download_rasters.py --force

# Set parallel downloads
python download_rasters.py --parallel 8
```

### Check Sync Status

```sql
SELECT * FROM epoleodomia.v_sync_status;
```

---

## 5. Data Inventory

### Summary Statistics

| Category | Count |
|----------|-------|
| **Total Vector Tables** | 55 |
| **Tables with Data** | 33 |
| **Empty Tables** | 22 |
| **Total Vector Records** | ~18,700+ |
| **Total Views** | 16 |
| **Unique FEK References** | 37 |
| **Raster TIF Files** | 103 |
| **Raster Total Size** | 512 MB |

### Tables with Data (Sorted by Record Count)

| Table | Records | Description |
|-------|---------|-------------|
| `planning_lines` | 13,185 | Ρυμοτομικές γραμμές (street alignment lines) |
| `building_lines` | 1,301 | Οικοδομικές γραμμές (building lines) |
| `forest_maps` | 849 | Forest maps (Attica region) |
| `building_blocks` | 558 | Οικοδομικά τετράγωνα (building blocks/OT) |
| `census_blocks_2021` | 378 | Census building blocks 2021 |
| `block_vertices` | 363 | Building block corner points |
| `planning_diagrams` | 103 | Planning diagram outlines with FEK + TIF URLs |
| `raster_catalog` | 103 | Downloaded TIF catalog with metadata |
| `monuments_points` | 56 | Monument locations |
| `addresses` | 54 | Street addresses |
| `public_spaces` | 47 | Κοινόχρηστοι χώροι (public spaces) |
| `other_planning_lines` | 43 | Other planning lines |
| `approved_plan_boundaries` | 33 | Approved urban plan boundaries |
| `building_regs_lot` | 17 | Lot size regulations (αρτιότητα) |
| `settlements_2021` | 10 | Settlement locations |
| `building_regs_coverage` | 13 | Coverage ratio regulations (κάλυψη) |
| `building_regs_height` | 11 | Height/floor regulations |
| `building_regs_system` | 10 | Building system regulations |
| `building_regs_coefficient` | 14 | Building coefficient/FAR (ΣΔ) |
| `forest_maps_posted_pelop_2022` | 747 | Posted forest maps (Peloponnese) |
| `forest_maps_posted_attica_2021` | 949 | Posted forest maps (Attica) |
| `shorelines` | 7 | Coastal boundaries (αιγιαλός/παραλία) |
| `land_uses_ers` | 7 | Land uses ERS |
| `pedestrian_zones` | 3 | Pedestrian zones |
| `monuments_polygons` | 3 | Monument polygons |
| `archaeological_sites_polygons` | 3 | Archaeological site polygons |
| `protected_buildings` | 2 | Protected buildings |
| `protection_zones_polygons` | 2 | Archaeological protection zones |
| `municipalities_2021` | 2 | Municipalities (Kallikratis) |
| `municipal_units_2021` | 2 | Municipal units |
| `municipal_communities_2021` | 3 | Municipal communities |
| `fek_no_diagrams` | 2 | FEK without georeferenceable diagrams |
| `building_regs_coefficient_zones` | 9 | Zone-level ΣΔ with conditions |
| `natural_landscapes_polygons` | 1 | Natural landscape polygons |

---

## 6. Database Schema

### Installed-schema audit — 2026-10-27

**Current status (2026-10-31):** the guarded preparation has been applied to
production with the existing owner account. The installed TEE schema is managed
at v2; preservation of all 93 original project-table values was verified at
migration acceptance, along with the reader's restricted rights. The following
audit describes the earlier source state. The user has since confirmed AutoCAD
acceptance and the first production TEE/cadastre/EMSY runs pass. Six HTTP reports
remain unchanged and API health stays connected with reader credentials. See
MIGRATION_PLAN.md for the application/backup record and subsequent data updates.

The SQL directory is **not a reproducible description of the installed database**.
The database has later manual changes; some repository features are absent.
Treat the definitions captured from the installed database as evidence to review
and preserve, rather than rebuilding it from the old SQL.

The audit used `codex_reader` with `transaction_read_only=on` on PostgreSQL 18.1.
It inspected 118 non-extension tables/views across `epoleodomia`, `sp_geodata`
and `public`, including column types/nullability/defaults, keys/checks, indexes,
view definitions, project functions and user triggers. Every repository SQL file
was also replayed in a disposable PostgreSQL 16/PostGIS 3.5 database with no
production rows; legacy raster/PDF dependencies were represented by empty tables
with their installed column types. The exact temporary container was removed.

| SQL file | Installed state and consequence |
|---|---|
| `sql/001_tables.sql` | Historical destructive rebuild. Tracking fields, object-ID uniqueness, geometry/text types and later additions differ. Its `UNIQUE(objectid)` on `building_regs_lot` conflicts with the intentional duplicate IDs in current data. Do not replay it to reconcile this database. |
| `sql/002_views.sql` | Eleven of its sixteen views exist; five audit views do not. The regulations, FEK-reference and per-FEK raster-summary views have substantive later changes. `CREATE OR REPLACE` cannot restore the old incompatible view column layouts in place. The old raster function also uses an unqualified table reference; the installed function qualifies it. |
| `sql/003_seed.sql` | The source SELECT plans against the installed schema, the unique raster URL index exists, and there are no duplicate candidate URLs in this snapshot. This does not validate the effects of an actual seed/update run; none was performed. |
| `sql/004_raster_sheets.sql` | Installed table columns/defaults/constraints/indexes, unified-view definition, two functions and update trigger match the reproduced SQL. Existing roles remain in force: 80 working and 23 excluded FEK sheets; DJI 54, DE 322, GYS 9 and historic-plan 9 working sheets. No exclusions were changed. |
| `sql/005_fek_documents.sql` | `sp_geodata.fek_documents` is absent. The audited original produced two input rows for `406Δ/1989` and would fail its upsert. The revised registry-completion SELECT now yields one row per trimmed FEK: prefer a nonblank URL, then active diagrams over `fek_no_diagrams`, then a stable URL tie-break. Verified live input: 37 candidates, 37 keys; the migration remains unapplied. The old source still holds 24 non-NULL local PDF paths; file availability was not checked. |
| `sql/create_land_use_lookup.sql` | The lookup table and SQL translation function are absent. The API has its own Python code lookup, so their absence does not by itself break that API path. The script drops/recreates its table. |
| `sql/update_view_building_regulations.sql` | Older alternative definition: centroid joins, no zone fallback and only 23 output fields. The installed view uses maximum-area lateral matches, coefficient-zone fallback, land-use fields and match percentages (34 fields). Replaying the patch would discard those changes. |
| `sql/migrations/0001_tee_baseline.sql` | Immutable historical TEE starting state. The supported fresh setup now runs this followed by `0002`; never install just the old definitions as the current target. |
| `sql/migrations/0002_live_tee_contract.sql` + `.json` | Versioned geometry/text/generated-column contract plus four reviewed live views. Fresh installs and v1 upgrades are tested in isolation. The existing divergent installation remains blocked; no live DDL was applied. |

The audit reproduced an application issue: the Natura queries in
`PlanningData.get_natura_forest()` and `get_parcel_overlaps()` filter
`natura_2000.is_deleted`, but that installed table has no such column. Executing
the actual point/parcel report collectors against a real in-town sample failed
with undefined-column errors. This is a gap in the recent filtering change:
synthetic fixtures supplied the field, while the installed schema was only
checked for relation existence. This is now corrected through per-collector
catalog detection as described in the report boundary above, preserving deleted
row filtering where the column exists. Six real reports (point and parcel at
two town samples and one outside-plan sample) subsequently passed through the
actual protected API snapshot using `codex_reader`. No database schema was changed.

At the same sample, installed-schema reads passed for both regulations
providers, posted/operating cadastre, block lookup, parcel rights, archaeology,
churches, shoreline, streams, city-plan membership and water points. These are
bounded smoke checks, not exhaustive spatial or AutoCAD validation.

Additional differences and priorities:

- The installed `epoleodomia` schema contains 58 tables and 13 views. Eight
  baseline relations are missing: `sync_runs`, `changelog`, `land_use_codes`,
  `v_recent_changes`, `v_sync_run_summary`, `v_fek_changes`,
  `v_geometry_changes` and `v_regulation_changes`. In this state,
  `start_sync_run()` returns `None` and `log_change()` skips database audit
  writes. File digests and `sync_log` are separate mechanisms; they do not
  supply the missing database history.
- Twenty-two TEE tables lack all four tracking fields (88 columns total).
  Fifty-four baseline object-ID unique constraints are absent, with no
  equivalent valid unique indexes. A read-only aggregate check found no
  duplicate non-NULL object IDs outside `building_regs_lot`; that table has
  six duplicated ID groups and six extra rows, consistent with its deliberate
  replace-only behavior. This is not a reason to add uniqueness to it.
- The installed wider geometry types are necessary for real data. For
  example, `building_regs_coefficient` contains five MultiPolygons and nine
  Polygons, and `approved_plan_boundaries` contains thirteen MultiPolygons and
  twenty Polygons. The historical `geometry(Polygon,2100)` declarations cannot
  store those MultiPolygons. Several varchar widths and the numeric coverage
  type also differ. Do not narrow types merely to satisfy the old manifest.
- The installed FEK-reference view also includes `settlement_boundaries` and
  `land_uses_gps`; its historical definition omits both. The raster-summary
  view adds `total_size_bytes`. The alias-only difference in
  `v_rasters_downloaded`, equivalent `now()`/`CURRENT_TIMESTAMP` defaults and
  function formatting/comments are not functional defects. PostgreSQL 18
  NOT NULL catalog constraints were compared through column nullability,
  avoiding false differences against PostgreSQL 16.
- Two legacy functions fail on a real invocation:
  `sp_geodata.get_oroi_domisis(double precision,double precision)` and
  `sp_geodata.point_info(double precision,double precision)` reference removed
  tables. No calls to either were found in the current root Python/LISP
  sources. Preserve their definitions while checking external consumers
  before repairing or retiring them. Other live-only objects, including
  `epoleodomia.oroi_domisis_at`, `v_building_blocks_full` and
  `v_oroi_domisis_flags`, also need a deliberate place in a future baseline.
- No inspected index was invalid/not-ready. Missing historical active-row
  indexes are a separate performance question, not proof of wrong results.

The reviewed fresh/v1-upgrade contract is now versioned in `0002`; the loader
also excludes generated/identity columns from source writes, verified against
the installed generated `label_point` and real disposable syncs.
The subsequent full-backup rehearsal restored today's NAS archive in isolated
PG 18.4/PostGIS 3.6.4 with cron execution disabled, preserved original values in
93 project tables during preparation, and adopted the copy as v2 with zero target
findings. Both full 55-layer TEE syncs, all three cadastral layers, EMSY and six
reader reports passed; see TESTING.md for exact scope and evidence. The initial
scratch SQL remains historical evidence. The supported known-installation entry
point is now `prepare_legacy_database.py`, backed by frozen SQL/JSON under
`sql/preparations/`; ordinary setup never implicitly invokes it. Preview is
read-only. Apply requires the reviewed plan hash and backup SHA, revalidates the
source under locks, preserves original values/metadata and records preparation
plus adopted 0001/0002 atomically. It creates new objects as the existing schema
owner and keeps codex_reader read-only, including access to migration history.
The full-archive runner compares all 93 original project tables and six report
bodies before/after; the guarded recipe passes on a restored copy.
The later owner-account application completed on 2026-10-31 using the freshly
restored/tested off-NAS archive; see MIGRATION_PLAN.md. Reader previews now report
`prepared` and ordinary setup reports `managed`.
The optional PDF registry remains a separate decision. A source writer account
and actual AutoCAD acceptance still need operational setup/validation.
No production DDL, DML, sync or restart
was performed for this audit.

Local evidence is in ignored `logs/`: `schema_live_2026-10-27.json` contains the
catalog snapshot, `schema_audit_comparison.json` the per-object comparisons,
`schema_audit_checks.json` the read-only check results,
`schema_audit_sql_replay.json` the disposable SQL replay record and
`schema_audit_upsert_reproduction.json` a synthetic-only reproduction of the
`005` conflict pattern (SQLSTATE `21000`) in a separate removed container. These contain
no connection passwords or parcel/report output. The helper scripts in that
folder are session tools, not a supported migration interface.
`schema_fixes_verified.json` separately records the six successful real reports
and the revised `005` candidate-key check, without overwriting the original
audit evidence or recording coordinates, parcel IDs or report content.
`tee_reconciliation_preview.json` records the subsequent read-only comparison
with the v2 target. Its findings are contract differences, including optional
historical indexes, rather than a count of application defects.

### Common Fields Across Tables

Most urban planning tables share these fields:

| Field | Type | Description |
|-------|------|-------------|
| `id` | SERIAL | Primary key (auto-generated) |
| `objectid` | INTEGER | Original ArcGIS ObjectID |
| `fek` | TEXT | Government Gazette reference (ΦΕΚ) |
| `fek_file_url` | TEXT | URL to FEK PDF document |
| `publ_date` | TIMESTAMP | Publication date |
| `apof_eidos` | TEXT | Decision type |
| `title` | TEXT | Subject/title |
| `kall_dhm_name` | TEXT | Municipality name (Kallikratis) |
| `geom` | GEOMETRY | Spatial geometry (SRID 2100) |
| `created_at` | TIMESTAMP | When record was first synced |
| `updated_at` | TIMESTAMP | Last modification time |
| `is_deleted` | BOOLEAN | Soft delete flag |
| `fetched_at` | TIMESTAMP | When data was synced |

### Key Tables Detail

#### building_blocks
Core table of urban building blocks (Οικοδομικά Τετράγωνα)

| Column | Type | Description |
|--------|------|-------------|
| `ot_num` | TEXT | Block number |
| `fek` | TEXT | Legal reference |
| `geom` | POLYGON | Block boundary |

#### building_regs_* (5 tables)
Building regulations split by type:
- `building_regs_height` - Max height (m), number of floors
- `building_regs_coverage` - Coverage percentage (κάλυψη)
- `building_regs_coefficient` - Building coefficient/FAR (ΣΔ)
- `building_regs_lot` - Minimum lot size, frontage
- `building_regs_system` - Building system type

#### planning_diagrams
Planning diagram boundaries with TIF URLs

| Column | Type | Description |
|--------|------|-------------|
| `fek` | TEXT | Legal reference |
| `georef_diagram_url` | TEXT | URL to georeferenced TIF |
| `initial_diagram_url` | TEXT | URL to raw scanned TIF |
| `ggrs87_diagr_georef_rms` | NUMERIC | Georeferencing RMS error (m) |
| `init_diagr_scale_denominator` | INTEGER | Original map scale |
| `geom` | POLYGON | Diagram boundary |

---

## 7. Views and Joins

### Available Views

This table lists the repository's intended views. The five changelog views
below were **absent from the installation audited on 2026-10-27**; see the
installed-schema audit in section 6 before querying or recreating them.

| View | Description |
|------|-------------|
| `v_building_blocks_regulations` | **PRIMARY** — Blocks with all regs, zone fallback, land use, is_deleted filtering |
| `v_addresses_with_blocks` | Addresses with their containing block info |
| `v_fek_references` | Normalized list of all FEK references |
| `v_protected_areas` | Combined archaeological, historic, natura zones |
| `v_planning_lines_all` | All planning lines combined |
| `v_land_uses_summary` | Combined land uses from GPS and ERS (uses `per_cat_gen`) |
| `v_sync_status` | Latest sync status per table |
| `v_recent_changes` | Recent changelog entries |
| `v_sync_run_summary` | Summary of sync runs |
| `v_fek_changes` | FEK reference changes over time |
| `v_geometry_changes` | Geometry/boundary changes |
| `v_regulation_changes` | Building regulation changes |
| `v_rasters_by_fek` | Raster download status by FEK |
| `v_rasters_downloaded` | Downloaded rasters with metadata |
| `v_rasters_pending` | Rasters awaiting download |
| `v_rasters_failed` | Failed downloads for retry |

### Primary View: v_building_blocks_regulations

```sql
SELECT * FROM epoleodomia.v_building_blocks_regulations LIMIT 5;
```

Returns:
- Block ID and number (`ot_num`)
- FEK reference and URL
- **Height**: `max_height_m`, `num_orofon` (floors), `height_comment`
- **Coverage**: `coverage_pct`, `coverage_remarks`
- **FAR**: `building_coefficient` (ΣΔ), `sd_tomeas`, `sd_klimakotos`, `coefficient_comment`, `coefficient_source` (per_block/zone)
- **Lot**: `min_lot_size_m2`, `min_frontage_m`, `oros_type` (ΚΑΤΑ ΚΑΝΟΝΑ/ΠΑΡΕΚΚΛΙΣΗ), `lot_remarks`
- **System**: `building_system`
- **Land use**: `land_use_general`, `land_use_specific`, `land_use_remarks`
- Block geometry

The view uses `COALESCE` to fall back from per-block to zone-level coefficients,
and filters out soft-deleted records (`is_deleted = FALSE`).

---

## 8. Raster Planning Diagrams

### Overview

The system downloads **103 georeferenced TIF planning diagrams** from TEE:
- Total size: **512 MB**
- CRS: **EPSG:2100** (GGRS87) - same as vector data
- Organized by FEK folder
- Average resolution: ~0.7 m/pixel

### Storage Location

`download_rasters.py` uses the shared `EPOL_RASTER_BASE_PATH` setting instead
of a directory relative to its own script. Its default is `EPOL_FEK_LOCAL_PATH`.
An existing flat TIFF is reused when its old FEK-relative path is absent; new
files retain the catalog-relative subfolder. No collection or table is added.
The API resolves the same paths and retains the legacy flat-folder read fallback
when an explicit catalog root differs.

The 2026-10-31 inventory found 74 distinct TIFFs, each in two byte-identical
copies under `O:\gis_data\epoleodomia\poleodomikoi oroi`. All passed full TIFF
validation. The original 148 files remain intact. Production acceptance first
added ID 47 (34Δ/2022), then repaired the remaining 28 files. All 103 are now
local and all 80 working sheets are available. Only download/check/update
timestamps changed because the stored technical metadata already matched.
Menu raster runs include --repair-missing and limit files after filtering.
Explicit --force still refreshes selected existing files.

The downloader stages bytes beside the destination, checks HTTP completeness and
decodes every band of a required EPSG:2100 north-up GeoTIFF before publication.
Parallel workers perform network/file work only; one main-thread connection
publishes each row in a separate transaction. A changed source identity blocks
publication. Existing files are backed up before replacement and restored on
ordinary transaction failure; failed forced refreshes retain the existing
downloaded status/path/technical metadata and record an error. Other files can
still succeed after an individual SQL failure. RMS, scale, roles and exclusions
are not modified.

FEK queries now use `sp_geodata.v_all_rasters` with the `working` default, so
manual exclusions remain authoritative. JSON responses include file availability;
the unified simple protocol emits existing FEK files only. The FEK simple
protocol retains its LOCAL/URL fallback. Its on-demand download endpoint accepts
only a unique working catalog URL and uses the same validated staging pipeline,
without database writes or writer credentials in the API.

PostgreSQL and filesystem replacement cannot share a crash-atomic commit:
a process/power failure between replacement and commit may leave valid new bytes
with old catalog metadata. A bounded repeat reconciles the row/file; retained
`.previous` files must be reviewed if restoration failed. Raw scans are not
implemented; `--include-raw` now returns failure rather than silently doing
nothing. See README.md for bounded writer commands.

```
poleodomikoi oroi geotifs/
├── 021962FS000001-1981E.tif   # original flat files retained
├── ...
├── FEK_34D_2022/
│   └── 169061FS000034-2022E.tif
└── FEK_1014D_1993/           # repaired missing files
```

### Central NAS archive and local restoration

raster_replica.py copies the TEE collection using read-only database queries.
Optional EPOL_RASTER_NAS_PATH enables this location:

    \\10.90.144.153\Sp_net\epoleodomia_dir\spetses_urban_planning\raster_library\fek

Each validated TIFF version is stored as an immutable checksum-named object.
Historical manifests map versions to source IDs, filenames, URLs and relative
paths. Only a complete publication replaces latest.json. Copies use temporary
paths, checksums after writing and publication without overwriting an object.
PostGIS remains the spatial catalog; the manifests track copied file versions.

Menu option 4, and the raster phase of option 6, perform NAS pull → local
missing repair/download → NAS push. Replication children keep normal reader
credentials; downloads use epol_sync. A NAS failure is reported while local
downloads can proceed. Download --dry-run skips all NAS actions.

Standalone push/pull commands default to preview; copying requires --apply.
Pull fills missing files and retains different existing local content for
review, protecting drawing references. Pull --raster-id N restores one file.
AutoCAD/API keep local SSD paths; insertion does not contact the NAS.
Other PCs can restore with database-reader and NAS-read access.

The initial archive holds 103 objects / 536,700,407 bytes. Checksums were
independently verified and ID 35 was restored into an isolated cache. The 270
files in the legacy NAS folders retain their original stats. A repeat of the
actual configured menu reused all 103 files and copied/downloaded no TIFFs.
Database state, local source files and six reports stayed identical.
Database dumps and the TIFF archive cover separate parts of recovery.

### Raster Catalog Table

```sql
-- View downloaded rasters
SELECT * FROM epoleodomia.v_rasters_downloaded;

-- Summary by FEK
SELECT * FROM epoleodomia.v_rasters_by_fek;

-- Find rasters at a point
SELECT * FROM sp_geodata.v_all_rasters
WHERE collection = 'fek' AND role = 'working'
  AND ST_Covers(query_geom, ST_SetSRID(ST_Point(420000, 4122000), 2100));
```

### Raster Catalog Fields

| Field | Type | Description |
|-------|------|-------------|
| `fek` | TEXT | FEK reference |
| `filename` | TEXT | TIF filename |
| `local_path_georef` | TEXT | Relative path to downloaded TIF |
| `url_georef` | TEXT | Original TEE URL |
| `file_size_bytes` | BIGINT | File size |
| `width_px`, `height_px` | INTEGER | Image dimensions |
| `resolution_x` | NUMERIC | Meters per pixel |
| `crs_epsg` | INTEGER | Coordinate reference system |
| `bbox` | GEOMETRY | Bounding box polygon |
| `download_status` | TEXT | pending/downloaded/failed |

### Using in AutoCAD

The TIF files are georeferenced and can be used directly:
1. XREF the TIF file in AutoCAD
2. Use GGRS87 coordinate system
3. The image will align with vector data automatically

---

## 9. Empty Tables

The following tables exist but have no data for the Spetses area:

| Table | Reason |
|-------|--------|
| `settlement_boundaries` | No defined boundaries |
| `other_planning_zones` | No special zones |
| `streams` | No defined streams |
| `outside_plan_areas` | Area fully covered by plan |
| `urban_units` | Not defined for Spetses |
| `archaeological_zones_pl` | Use archaeological_sites instead |
| `expropriation_zones` | No active expropriations |
| `land_uses_gps` | Uses ERS system instead |
| `natura_2000` | Spetses not in Natura 2000 |
| `zoe_zones` | Not applicable to island |
| ... | (see full list in schema) |

---

## 10. Key Findings

### Building Regulations Coverage

- **556 building blocks** total in database (Spetses + nearby mainland)
- **481 blocks** have **complete regulations** (height, coverage, coefficient, building system)
- **9 distinct regulation zones** covering the island
- Regulations linked via spatial overlap (centroid-based `ST_Intersects`), not FK

**75 blocks without building system — all explained:**

| Group | Blocks | Reason |
|-------|--------|--------|
| 176Δ/1970 (Αγ. Αιμιλιανός) | 39 | Mainland Ermionida — housing cooperative, not Spetses |
| 275Δ/1970 (Κόστα ΔΕΗ) | 26 | Mainland Ermionida — housing cooperative, not Spetses |
| 1385Δ/1992 + 459Δ/1987 | 7 | Mainland Ermionida extensions |
| ΟΤ 116 | 1 | Falls in zone 8 (961Δ/1992) which has NULL oik_systima at TEE source; inherits "Πρώην Πτερύγων" from parent 740Δ/1981 |
| ΟΤ 442 (εκκλησία) | 1 | Tiny polygon (112 m²) — church, no building regulations applicable |
| ΟΤ 444 (φάρος) | 1 | Tiny polygon (203 m²) — lighthouse, no building regulations applicable |

All 481 buildable Spetses blocks have complete regulation data. Zero actionable gaps.

### Building System Data (Coded Domain Fix — 2026-02-25)

The `building_regs_system` table (Layer 19) uses ArcGIS **coded value domains** for the `OIK_SYSTIMA` field. Prior to 2026-02-25, `oik_systima` and `oik_systima_comment` were NULL for all 9 Spetses zones because the API returned raw codes instead of display text.

**Fix applied:** Added `returnDomainValues=true` to `fetch_layer.py` query parameters. This resolved the issue for 7 of 9 zones. The remaining 2 (mainland Ermionida zones 1, 2) are genuinely NULL at the TEE source.

Known building systems for Spetses:

| Zone IDs | FEK | Οικ. Σύστημα | Τομέας | Blocks |
|----------|-----|-------------|--------|--------|
| 3-7 | 740Δ/1981 | Πρώην Πτερύγων | Α-Ε | 480 |
| 8 | 961Δ/1992 | NULL (inherits Πρώην Πτερύγων) | Γ' (ΟΤ 116) | 1 |
| 9 | 163ΑΑΠ/2009 | Ως Ν.Ο.Κ. | School zone | 1 |
| 1 | 275Δ/1970 | NULL | Κόστα ΔΕΗ (mainland) | 26 |
| 2 | 176Δ/1970 | NULL | Αγ. Αιμιλιανός (mainland) | 39 |

### Field Audit Summary (2026-02-25/26)

Complete field-by-field comparison of PostGIS data against TEE public site popups, plus a full NULL-column scan across all tables.

**Building Regulations (Layers 16-20):**

- **building_regs_height** (Layer 16) — ✅ COMPLETE: max_height_m, num_orofon, comments with pilotis prohibition, 3rd floor exceptions
- **building_regs_coverage** (Layer 18) — ✅ COMPLETE: synt_kalypsis, remarks with 120 τ.μ. exceptions
- **building_regs_coefficient** (Layer 20) — ✅ COMPLETE: sd_timh, sd_tomeas (ΤΟΜΕΑΣ Α-Ε), sd_klimakotos, sd_comment
- **building_regs_lot** (Layer 17) — ✅ COMPLETE: both ΚΑΤΑ ΚΑΝΟΝΑ and ΚΑΤΑ ΠΑΡΕΚΚΛΙΣΗ records with full remarks
- **building_regs_system** (Layer 19) — ✅ FIXED: oik_systima and oik_systima_comment now populated after `returnDomainValues` fix

**Field Mapping Fixes (2026-02-26):**

A full scan of all tables revealed multiple wrong field name mappings in `config.py`. The API field names were different from what was originally assumed, causing NULL columns despite the data being available.

| Table | API Field | Was Mapped As | Fixed To | Data |
|-------|-----------|---------------|----------|------|
| land_uses_ers | `GEN_XRHSH` | PER_CAT_GEN (no match) | per_cat_gen | ΠΕΡΙΟΧΗ ΓΕΝΙΚΗΣ ΚΑΤΟΙΚΙΑΣ |
| land_uses_ers | `EPXR_COMMENT` | PER_CAT_EID (no match) | per_cat_eid | Απαγορεύονται βιομηχανίες... |
| land_uses_ers | `REMARK` | REMARKS (plural) | remarks | ΤΟΜΕΑΣ Δ, legal notes |
| public_spaces | `EID_XRHSH_TXT` | KX_KOINOXR_TYPE (no match) | kx_koinoxr_type | ΧΩΡΟΣ ΣΧΟΛΕΙΟΥ, ΠΛΑΤΕΙΑ, churches |
| settlements_2021 | `OIKISMOS` | NAME (no match) | name | Σπέτσαι, Κουζούνος, Λιγονέρι |
| municipalities_2021 | `NAME_GR` | YPES_NAME (no match) | ypes_name | ΔΗΜΟΣ ΕΡΜΙΟΝΙΔΑΣ |
| municipal_units_2021 | `NAME_GR` | YPES_NAME (no match) | ypes_name | ΔΗΜΟΤΙΚΗ ΕΝΟΤΗΤΑ... |
| municipal_communities_2021 | `LAU_LABEL3` | YPES_NAME (no match) | ypes_name | Δημοτική Κοινότητα... |
| forest_maps | `KATHGORDX` | (unmapped) | forest_type | ΔΔ, ΠΑ, ΑΝ, ΧΑ etc. |
| approved_plan_boundaries | `APOF_THEME` | (unmapped) | apof_theme | ΤΡΟΠΟΠΟΙΗΣΗ ΡΥΜΟΤΟΜΙΚΟΥ |

New columns added to schema: `forest_code`, `nomos`, `kathgoral1`, `kathgoral2` (forest_maps), `apof_theme` (approved_plan_boundaries), `globalid` (municipal_units_2021).

The `v_land_uses_summary` view was also fixed to use `ers.per_cat_gen` instead of `ers.gen_xrhsh_gps` for the `general_use` column.

**Columns confirmed genuinely empty at TEE source (no fix possible):**

- `census_blocks_2021` — API returns geometry only, no attributes
- `pop_2021`, `ypes_code`, `elstat_code` across ELSTAT tables — TEE does not serve demographic data
- `planning_lines.road_width` — field exists in API but TEE hasn't populated it
- `forest_maps.layer_id, region_name, status` — orphan columns from original schema design, no API equivalent

### Building Lines Data Quality

The `building_lines` table has limited data:
- Only **1,301 records** vs 13,185 planning_lines
- **77%** from FEK 1385Δ/1992
- Average length: 17.78m
- TEE has not fully digitized building lines for Spetses

### Raster Quality

- Some rasters have very high resolution (0.017 m/pixel)
- Others are lower resolution (~1-2 m/pixel)
- RMS georeferencing error varies (check `ggrs87_diagr_georef_rms`)

---

## 11. Useful Queries

### Find Building Block by Number

```sql
SELECT * FROM epoleodomia.building_blocks
WHERE ot_num = '123';
```

### Get Full Regulations for a Block

```sql
SELECT * FROM epoleodomia.v_building_blocks_regulations
WHERE ot_num = '123';
```

### Find Blocks by Coordinates

```sql
SELECT ot_num, fek, ST_AsText(geom)
FROM epoleodomia.building_blocks
WHERE ST_Contains(geom, ST_SetSRID(ST_MakePoint(420000, 4122000), 2100));
```

### Find Rasters Covering a Point

```sql
SELECT * FROM epoleodomia.find_rasters_at_point(420000, 4122000);
```

### Get All FEK References

```sql
SELECT DISTINCT fek, fek_file_url, publ_date
FROM epoleodomia.v_fek_references
WHERE fek IS NOT NULL
ORDER BY publ_date DESC;
```

### Export to GeoJSON

```sql
SELECT jsonb_build_object(
    'type', 'FeatureCollection',
    'features', jsonb_agg(ST_AsGeoJSON(t.*)::jsonb)
) FROM (
    SELECT ot_num, fek, geom
    FROM epoleodomia.building_blocks
) t;
```

---

## 12. Change Tracking System

### How It Works

When using `--track` mode:
1. **UPSERT** instead of TRUNCATE+INSERT
2. Detects **new**, **updated**, **deleted** records
3. Logs all changes to `changelog` table
4. Tracks field-level changes with old/new values

Geometry equality follows [PostGIS ST_Equals](https://postgis.net/docs/ST_Equals.html).
The cadastral ID-batch approach follows the
[ArcGIS feature-layer query API](https://developers.arcgis.com/rest/services-reference/enterprise/query-feature-service-layer/).

### Changelog Queries

```sql
-- Recent changes
SELECT * FROM epoleodomia.v_recent_changes LIMIT 50;

-- Sync run summary
SELECT * FROM epoleodomia.v_sync_run_summary;

-- FEK changes
SELECT * FROM epoleodomia.v_fek_changes;

-- Geometry changes
SELECT * FROM epoleodomia.v_geometry_changes;

-- Changes to specific block
SELECT * FROM epoleodomia.changelog
WHERE table_name = 'building_blocks'
AND objectid = 12345
ORDER BY changed_at;
```

---

## 13. Local Log Files

### Location

```
epoleodomia/logs/
├── sync_2026-02-03_143022.log   # Human-readable
└── sync_2026-02-03_143022.json  # Machine-parseable
```

### CLI Options

```bash
python sync_all.py --track              # Logs enabled (default)
python sync_all.py --track --no-log     # Disable logs
python sync_all.py --track --log-dir "D:\logs"  # Custom directory
```

### Log Content

The logs contain:
- Sync start/end times
- Per-table statistics (new/updated/deleted/unchanged)
- Individual change details
- Error messages
- Duration and status

---

## 14. Troubleshooting

### Connection Failed

```bash
psql -h 10.90.144.153 -p 65432 -U docker -d gis -c "SELECT 1"
```

### No Data Returned

1. Check bounding box in `config.py`
2. Run dry-run: `python sync_all.py --dry-run`
3. Layer may have no data in Spetses area

### Raster Download Failed

```bash
# Check failed downloads
SELECT * FROM epoleodomia.v_rasters_failed;

# Retry failed
python download_rasters.py --force
```

### All Records Showing as "Updated"

This was fixed - the sync now uses geometry length comparison with 5% threshold to avoid false positives from floating-point precision differences.

---

## 15. Operational Notes (2026-06-27)

### AutoCAD Report Commands

- `ETABLE` calls `/oroitable/rows`.
- `EREPORT` calls `/report/parcel` and resolves the operating-cadastre parcel first.
- Both commands share `PlanningData.get_regulations()` in `planning_data.py`; `_get_oroitable_data()` remains an API adapter for existing callers.

### Required Approvals

`ETABLE` and the building-regulations section of `EREPORT` always include:

- `Συμβούλιο Αρχιτεκτονικής`
- `Υπηρεσία Νεωτέρων Μνημείων`

`Αρχαιολογία (ΕΦΑ)` is added when the clicked point is inside a built archaeological protection zone or within 100 m of a curated monument.

### EREPORT Shoreline Summary

The `ΑΙΓΙΑΛΟΣ / ΠΑΡΑΛΙΑ` section in `/report/parcel` is intentionally summarized:

- `Διέλευση γραμμής`: checks whether any current/POA shoreline, beach line, or old-shoreline line crosses the parcel.
- `Απόσταση από Αιγιαλό`: reports only the nearest current shoreline, choosing between `Γραμμή Αιγιαλού` and `Γραμμή Αιγιαλού_ΠΟΑ`, with FEK reference.

The raw `/aigialos` endpoint still returns one distance per shoreline type.

### Archaeology Geometry Model

The active report source is `sp_geodata`, not the TEE `epoleodomia.archaeological_*` tables:

- `sp_geodata."Αρχαιλογία_Κυρηγμένα_Μνημεία"`: 62 curated monument polygons with FEK refs.
- `sp_geodata."Αρχαιολογία_Ζώνες_Προστασίας"`: 5 protection-zone linework features.

Protection zones are stored as `MultiLineString`, so containment and parcel-overlap checks must use:

```sql
ST_CollectionExtract(ST_MakeValid(ST_BuildArea(geom)), 3)
```

This is applied in:

- ΕΦΑ approval checks.
- `/archeo` zone checks.
- `/report/parcel` zone percentage overlap.

### KAEK Special-Use Parcels

Special-use KAEK parcels can be marked with Latin `EK` or Greek `ΕΚ`. The API now excludes both using `_kaek_non_special_use_filter()` in:

- `/kaek/simple`
- `/kaek/operating`
- `/report/parcel`

This prevents large special-use polygons from being selected instead of the actual private parcel.

### EREPORT Streams (ΡΕΜΑΤΑ) Summary

The `ΡΕΜΑΤΑ` section in `/report/parcel` and `/report/rows` reports **only `Γρ. Πλημμύρας`** (flood line, from `sp_geodata."Ρεματα_Οικισμού_υπό_Οριοθέτηση"`), plus `Άλλο ρέμα` / `Ρέμα ΤΠΣ` when present. The two `Οριοθέτησης` lines (με/χωρίς έργο) are intentionally suppressed — they come from the non-ratified delimitation study and are not yet meaningful. The standalone `REMATA` command (`/remata/text`) still lists all three line types.

Stream source tables (all curated in `sp_geodata`): `Ρεματα_Οικισμού_υπό_Οριοθέτηση` (49, settlement, 3 line types), `Ρεματα εντος οικισμου εκτος των 6` (4, εντός σχεδίου), `Ρεματα Νησιου ΤΠΣ (εκτος των 6)` (57 polygons, εκτός σχεδίου), and the **unused** `Ρεματα_νησιού_από_ΓΥΣ_5000` (569 lines, whole island — candidate for εκτός-σχεδίου use).

---

*v1.3 — 2026-06-27: EREPORT ΡΕΜΑΤΑ reports only Γρ. Πλημμύρας; docs reviewed (API_SPEC/FASTAPI_REFERENCE/OPTIMIZATION_PLAN archived).*
*v1.2 — 2026-06-27*
*Updated canonical workspace path, sync exception notes, ETABLE/EREPORT behavior, archaeology zone handling, and KAEK EK/ΕΚ filtering.*
*v1.1 — 2026-02-26: consolidated SQL, credentials to .env, corrected views, complete data inventory.*
*Original documentation: 2026-02-03. Field audit: 2026-02-25/26.*
