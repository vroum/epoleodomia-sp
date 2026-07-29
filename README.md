# Epoleodomia GIS Tools for AutoCAD Civil 3D

Greek urban-planning data (epoleodomia) for **Spetses Island**, served from PostGIS by a local FastAPI server and consumed by AutoCAD LISP commands. Coordinates in **EGSA '87 (EPSG:2100)**.

## Quick start

1. **Start the API** — run `start_server.bat` (loads `.env`; serves http://127.0.0.1:8000, docs at `/docs`).
2. **Load the LISP** in AutoCAD:
   ```
   (load "O:/claude_code area/mega project postgis-autocad/lisp for acad v2 - Copy/clean/epoleodomia.lsp")
   ```
3. **Type `EHELP`** in AutoCAD for the full command list.

## Setup

- Install deps: `pip install -r requirements.txt` (Python 3.8+).
- Copy `.env.example` → `.env` and fill in the `EPOL_DB_*` credentials (never commit `.env`).
- Requires PostgreSQL/PostGIS (`gis` database) and — for the `CLIPR` raster-clip command — QGIS 3.40+.

## Documentation

- **DOCUMENTATION.md** — full technical reference: endpoints, commands, schemas, sync, EREPORT logic. *Start here.*
- **STATUS.md** — changelog and open items.
- **AGENTS.md** — instructions for AI coding agents.
- **archive/** — superseded design notes.
