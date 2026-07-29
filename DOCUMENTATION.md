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
├── fetch_layer.py         # ArcGIS REST API query functions
├── load_postgis.py        # GeoJSON to PostGIS loader with change tracking
├── sync_all.py            # Main CLI orchestration script
├── sync_kaek_operating.py # Hellenic Cadastre operating parcels sync
├── download_rasters.py    # Raster planning diagram downloader
├── logger.py              # Local log file generator
├── sync.bat               # Windows batch file for easy sync
├── requirements.txt       # Python dependencies (incl. python-dotenv)
├── README.md              # Quick start guide
├── DOCUMENTATION.md       # This file
├── API_SPEC.md            # FastAPI endpoint specification
├── SP_GEODATA_CLEANUP.md  # sp_geodata schema audit
├── logs/                  # Sync log files (.log and .json)
├── rasters/               # Downloaded planning diagram TIFs (in v1.0 dir)
│   └── georef/            # Georeferenced TIFs organized by FEK
└── sql/
    ├── 001_tables.sql     # Complete DDL (all tables, indexes, constraints)
    ├── 002_views.sql      # All views (corrected)
    └── 003_seed.sql       # Post-sync seed (raster catalog, forest areas)
```

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

- Python 3.8+
- PostgreSQL with PostGIS extension
- Access to the PostGIS database

### Step 1: Install Python Dependencies

```bash
cd "O:\claude_code area\mega project postgis-autocad\epoleodomia v1.1"
pip install -r requirements.txt
```

Required packages:
- `requests>=2.28.0` — HTTP requests to ArcGIS REST API
- `psycopg2-binary>=2.9.0` — PostgreSQL adapter
- `python-dotenv>=1.0.0` — Load credentials from `.env` file
- `tqdm>=4.64.0` — Progress bars for raster downloads
- `rasterio>=1.3.0` — TIF metadata extraction (optional)

### Step 2: Configure Database Connection

Copy `.env.example` to `.env` and set your password:

```bash
copy .env.example .env
# Then edit .env with your credentials
```

The `.env` file is git-ignored. `config.py` reads credentials from environment
variables, falling back to defaults for host/port/database.

### Step 3: Initialize Database (First Time Only)

```bash
# Two SQL files create the complete schema
psql -h %DB_HOST% -p %DB_PORT% -U %DB_USER% -d %DB_NAME% -f sql/001_tables.sql
psql -h %DB_HOST% -p %DB_PORT% -U %DB_USER% -d %DB_NAME% -f sql/002_views.sql

# After first data sync, seed the raster catalog:
psql -h %DB_HOST% -p %DB_PORT% -U %DB_USER% -d %DB_NAME% -f sql/003_seed.sql
```

`001_tables.sql` is a consolidated DDL that creates all tables with tracking
columns, unique constraints, changelog system, raster catalog, and all indexes
in a single file. No migration chain needed.

---

## 4. How to Sync / Update Data

### Using sync.bat (Recommended)

```batch
sync.bat              # Full sync with change tracking (default)
sync.bat full         # Same as above
sync.bat quick        # Quick test - building_blocks only
sync.bat dry          # Dry run - check counts without loading
sync.bat rasters      # Download raster planning diagrams only
sync.bat full-rasters # Full sync + download rasters
sync.bat replace      # Full replace (no tracking, truncates tables)
sync.bat help         # Show help
```

### Using Python Directly

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

- `building_regs_lot` (TEE Layer 17) is synced with full replace even when `--track` is used. The source service can return two meaningful rows with the same `OBJECTID` (`ΚΑΤΑ ΚΑΝΟΝΑ` and `ΚΑΤΑ ΠΑΡΕΚΚΛΙΣΗ`), so objectid-only change tracking collapses/overwrites records.
- After the 2026-06-27 targeted sync, `building_regs_lot` contains 17 rows. The Spetses 740Δ/1981 sectors are:
  - Τομέας Α/Β/Γ: 300 τ.μ. / 12 μ.
  - Τομέας Δ: 500 τ.μ. / 15 μ.
  - Τομέας Ε: 1000 τ.μ. / 25 μ.
- `config.py` accepts both `DB_*` and `EPOL_DB_*` environment variable names. `.env` comments beginning with `#` or `;` are supported.

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

```
epoleodomia/rasters/georef/
├── FEK_1014D_1993/    (7 files, 141 MB)
├── FEK_1353D_1993/    (9 files, 51 MB)
├── FEK_1D_1981/       (12 files, 36 MB)
├── FEK_740D_1981/     (15 files, 35 MB)
├── FEK_406D_1989/     (15 files, 24 MB)
└── ... (31 more folders)
```

### Raster Catalog Table

```sql
-- View downloaded rasters
SELECT * FROM epoleodomia.v_rasters_downloaded;

-- Summary by FEK
SELECT * FROM epoleodomia.v_rasters_by_fek;

-- Find rasters at a point
SELECT * FROM epoleodomia.find_rasters_at_point(420000, 4122000);
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
- Both commands share the building-regulation data produced by `_get_oroitable_data()` in `api_server.py`.

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
