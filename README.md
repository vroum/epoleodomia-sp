# Epoleodomia GIS Tools for AutoCAD Civil 3D

Greek urban-planning data (epoleodomia) for **Spetses Island**, served from PostGIS by a local FastAPI server and consumed by AutoCAD LISP commands. Coordinates in **EGSA '87 (EPSG:2100)**.

The consolidated 2026-11-01 source baseline is documented in [CHECKPOINT.md](CHECKPOINT.md),
including validation, recovery references and the next acceptance work.

## Quick start

For a new database, follow **DOCUMENTATION.md → Installation & Setup** first.
`python database_setup.py` previews the TEE migration chain without writing;
fresh setup applies versions 1 and 2, including the reviewed live views and
multipart geometry support. An existing divergent database requires reviewed
reconciliation before adoption.

The Spetses installation was prepared and adopted as v2 on 2026-10-31.
Database and API checks pass; the user confirmed `EREPORT`, `KAEK` and `ERASTER`
work in AutoCAD on 2026-10-31. The first production TEE, cadastre and EMSY syncs
also pass with the restricted writer; raster-download acceptance is in STATUS.md.

1. **Start the API** — run `start_server.bat` (uses shared settings and the project venv when available; default URL http://127.0.0.1:8000, docs at `/docs`). A healthy API already on that port is reused and the launcher can be closed. An unavailable port or unhealthy existing API produces a clear message for review.
2. **Load the LISP** in AutoCAD — one call, same as always:
   ```
   (load "O:/claude_code area/mega project postgis-autocad/lisp for acad v2 - Copy/clean/epoleodomia.lsp")
   ```
   `epoleodomia.lsp` is now a **loader**: it locates and loads the six
   `epol-*.lsp` modules itself and reports `Modules: 6/6`. If you move the
   project folder, edit `*epol-dir-default*` at the top of the loader (or add
   the folder to *OPTIONS → Files → Support File Search Path*).
3. **Type `EHELP`** in AutoCAD for the full command list.
4. *Optional:* `(load ".../kexport.lsp")` and `(load ".../kfilters.lsp")` for
   `KEXPORT`, `KFILTERS`, `KFILTERSDEL`, `KTSEED` — these are still loaded
   separately and require `epoleodomia.lsp` to be loaded first.

## LISP layout (v2.1)

| File | Lines | Contents |
|---|---:|---|
| `epoleodomia.lsp` | 170 | Loader + master command reference. Defines no commands. |
| `epol-core.lsp` | 787 | Config, HTTP, JSON/coord parsing, layers, drawing, table primitives. **Loads first.** |
| `epol-site.lsp` | 299 | `OROITABLE` `ETABLE` `EREPORT` `ENOTES` `ARCHEO` `CHURCH` `NATURA` `AIGIALOS` `REMATA` |
| `epol-bounds.lsp` | 477 | `KAEK` `EKAEK` `OT` `EOBT` `KAEK_OP` |
| `epol-ktima.lsp` | 1214 | `KLAYERS` `KPST` `KGEOM` `KGEOMV` `KVERT` `KGRID` `AIGDRAW` `KCHECK` |
| `epol-raster.lsp` | 660 | `ERASTER` `FEK` `DJI` `DE` `CLIPR` |
| `epol-util.lsp` | 120 | `ETRANS` `ELAYERS` `EHELP` |
| `kexport.lsp` | 256 | `KEXPORT` — loaded separately |
| `kfilters.lsp` | 250 | `KFILTERS` `KFILTERSDEL` `KTSEED` — loaded separately |

All 29 original `epoleodomia` commands are unchanged; only their file location
moved. Editing one module means reloading only that module during development.

## TEE raster downloads

Use menu option 4 or `python sync_launcher.py rasters`. With NAS configured, it
restores missing local files, downloads remaining missing/pending TIFFs and
publishes the verified local collection back to NAS. NAS file operations use the
normal database reader; only downloads receive writer credentials.
For a bounded download preview:

```bash
python sync_launcher.py rasters --raster-id 35 --limit 1 --parallel 1 --force --dry-run
```

After verifying the output directory, the same command without `--dry-run`
refreshes that one file. `--force` includes rows already marked downloaded.
Preview creates no files/directories. Downloads require rasterio, validate the
entire EPSG:2100 north-up TIFF, and retain an existing good file on ordinary
download/publication failure. Manual quality fields and exclusions are preserved.
`--include-raw` now fails explicitly; that legacy flag never downloaded raw scans.

The catalog root defaults to `EPOL_FEK_LOCAL_PATH`, unless
`EPOL_RASTER_BASE_PATH` explicitly overrides it. Existing flat files are reused;
new files retain their safe catalog-relative FEK subfolders. Both FEK and unified
endpoints resolve these paths, and the generic simple endpoint omits missing FEK
files. The JSON endpoints expose FEK file availability. On-demand AutoCAD
downloads also validate staged TIFFs and accept only working catalog sources.

Storage was reconciled on 2026-10-31. All **103 TEE TIFFs are now local**;
the 80 working sheets are available to AutoCAD and exclusions remain in force.
The original 148 physical copies, all other project data and six report bodies
were preserved. The menu checks missing files even when their status already
says downloaded; `--force` explicitly refreshes existing files.
Download preview creates no files and does not run NAS replication.

The central NAS archive is:

```
\\10.90.144.153\Sp_net\epoleodomia_dir\spetses_urban_planning\raster_library\fek
```

`EPOL_RASTER_NAS_PATH` configures this optional location. Each validated file
version is kept by checksum, and only a complete manifest becomes current.
Existing NAS folders are retained. Restoration fills missing local files;
a different existing local version is preserved and reported for review.

```bash
python raster_replica.py push                         # preview NAS publication
python raster_replica.py pull --raster-id 35           # preview one-file recovery
python raster_replica.py pull --raster-id 35 --apply   # recover if missing
```

The API continues to return local SSD paths. NAS copying happens during manual
sync, outside image insertion. Database backups preserve metadata;
the raster archive preserves the external TIFF bytes.

## Adding your own georeferenced map sheets

For rasters you georeferenced yourself — ΓΥΣ 1:5000, διαγράμματα αιγιαλού,
historic plans — as opposed to the ΦΕΚ diagrams that `download_rasters.py`
fetches from TEE.

**One-time setup:**

```
psql -d gis -f sql/004_raster_sheets.sql
pip install rasterio shapely
```

**Per collection:**

```
mkdir rasters\gys5000                      # drop the GeoTIFFs in here

python ingest_rasters.py --collection gys5000 --scale 5000        # dry run
python ingest_rasters.py --collection gys5000 --scale 5000 --commit
```

**The ΓΥΣ 1:5000 sheets need `--warp-northup`.** They are stored sideways —
their GeoTIFF `ModelTransformation` is a rotation of ~89.4–89.5°, not
axis-aligned. AutoCAD places attached images from an insertion point, scale and
rotation angle and does not read rotation out of the GeoTIFF, so they would land
wrongly. And because it is 89.5° rather than exactly 90°, it is not a lossless
transpose either. So:

```
python ingest_rasters.py --collection gys5000 --scale 5000 --warp-northup --commit
```

That resamples them onto an axis-aligned grid in the same CRS — no reprojection,
no datum shift, one interpolation pass. Output goes to `rasters\gys5000\_northup\`;
originals are untouched. Pixel count grows about 2%.

Dry run is the default; nothing is written without `--commit`. Re-running is
safe — unchanged files are skipped, changed files are updated, and your manual
edits to `role` / `georef_*` / `doc_ref` / `notes` are never overwritten by a
rescan. Files that must be in **EPSG:2100** and north-up: anything else is
rejected with a reason rather than silently accepted.

Then in AutoCAD: **`ERASTER`** → pick collection → pick role → pick area.

Useful flags:

| Flag | Why |
|---|---|
| `--role historical` | Evidence-grade document with poor/non-conformal georeferencing (e.g. the 1867 plan). Never returned by default, never traced on. |
| `--role context` | Orientation only — coarse scale, large RMS. |
| `--georef-method tps --georef-points 12 --georef-rms 8.5` | Records *how* it was georeferenced. Matters if you ever cite the document. |
| `--optimize` | Writes a tiled copy with overviews to `<root>/_optimized`. Originals untouched. Defaults to lossless LZW because JPEG rings around map line work and text. |

### The `role` column, and why it matters

Before this, `/rasters/fek/simple` carried a hardcoded list of six excluded
ΦΕΚ. Measured on the live catalog: a single point was claimed by **8.9 sheets
on average** (max 15), because five 1:100000–1:200000 index sheets with
**52–288 m georef RMS** and bounding boxes of 11 500 and 26 900 km² blanket the
whole island.

`role` moves that knowledge into the data, so every query path agrees —
`find_rasters_at_point()` did *not* have the blacklist and therefore disagreed
with the endpoint. `sp_geodata.rasters_at_point()` replaces it, filters on role,
and orders finest-scale-first (which is also the correct draw order).

## Setup

- Install deps in the project venv: `python -m pip install -r requirements.txt` (Python 3.10+).
- Copy `.env.example` → `.env` and fill in the `EPOL_DB_*` credentials (never commit `.env`).
- Preview schema setup with `python database_setup.py`; it is read-only by default. See DOCUMENTATION.md before using `--apply` or adopting an existing database. The historical `sql/001_tables.sql` drops tables and is not the setup entry point.
- Requires PostgreSQL/PostGIS (`gis` database) and — for the `CLIPR` raster-clip command — QGIS 3.40+.

## Separate sync account

Keep `EPOL_DB_*` in `.env` on the API reader. Preview sync access with
`setup_sync_writer.bat`; create the dedicated account once with
`setup_sync_writer.bat --apply` from a terminal in this folder. It asks for the
PostgreSQL administrator password privately, creates a random `epol_sync`
password and saves only `EPOL_SYNC_DB_USER` / `EPOL_SYNC_DB_PASSWORD` locally.
The password-free grants are reviewable in `sql/admin/epol_sync_writer.sql`.

Run `sync_menu.bat --check` to verify access without updates. The existing menu
and direct modes (`tee`, `ktima`, `ydro`, `rasters`, `all`, `all-rasters`) now use
`sync_launcher.py`, which passes sync credentials only to its child processes.
Missing or excessive permissions stop before any sync starts. The account
cannot create project tables, reset project sequences or edit curated layers.

## Documentation

- **DOCUMENTATION.md** — full technical reference: endpoints, commands, schemas, sync, EREPORT logic. *Start here.*
- **STATUS.md** — changelog and open items.
- **AGENTS.md** — instructions for AI coding agents.
- **MIGRATION_PLAN.md** — guarded preparation, backup rehearsal, application record and recovery plan. Applied on 2026-10-31; `python prepare_legacy_database.py` now verifies `prepared` without writing.
- **archive/** — superseded design notes.
