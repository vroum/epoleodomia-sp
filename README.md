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
| `epol-raster.lsp` | 530 | `FEK` `DJI` `DE` `CLIPR` |
| `epol-util.lsp` | 120 | `ETRANS` `ELAYERS` `EHELP` |
| `kexport.lsp` | 256 | `KEXPORT` — loaded separately |
| `kfilters.lsp` | 250 | `KFILTERS` `KFILTERSDEL` `KTSEED` — loaded separately |

All 29 `epoleodomia` commands are unchanged; only their file location moved.
Editing one module means reloading only that module during development.

## Setup

- Install deps: `pip install -r requirements.txt` (Python 3.8+).
- Copy `.env.example` → `.env` and fill in the `EPOL_DB_*` credentials (never commit `.env`).
- Requires PostgreSQL/PostGIS (`gis` database) and — for the `CLIPR` raster-clip command — QGIS 3.40+.

## Documentation

- **DOCUMENTATION.md** — full technical reference: endpoints, commands, schemas, sync, EREPORT logic. *Start here.*
- **STATUS.md** — changelog and open items.
- **AGENTS.md** — instructions for AI coding agents.
- **archive/** — superseded design notes.
