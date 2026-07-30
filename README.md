# Epoleodomia GIS Tools for AutoCAD Civil 3D

Greek urban-planning data (epoleodomia) for **Spetses Island**, served from PostGIS by a local FastAPI server and consumed by AutoCAD LISP commands. Coordinates in **EGSA '87 (EPSG:2100)**.

## Quick start

1. **Start the API** — run `start_server.bat` (loads `.env`; serves http://127.0.0.1:8000, docs at `/docs`).
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

- Install deps: `pip install -r requirements.txt` (Python 3.8+).
- Copy `.env.example` → `.env` and fill in the `EPOL_DB_*` credentials (never commit `.env`).
- Requires PostgreSQL/PostGIS (`gis` database) and — for the `CLIPR` raster-clip command — QGIS 3.40+.

## Documentation

- **DOCUMENTATION.md** — full technical reference: endpoints, commands, schemas, sync, EREPORT logic. *Start here.*
- **STATUS.md** — changelog and open items.
- **AGENTS.md** — instructions for AI coding agents.
- **archive/** — superseded design notes.
