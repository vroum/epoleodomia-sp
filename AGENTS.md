## Imported Claude Cowork project instructions

## Repo

Git repo lives in this folder. `HEAD~` on `master` is the pre-refactor v2.0
baseline (single 3443-line `epoleodomia.lsp`); use it to diff or roll back.
Never commit `.env` — it is gitignored and holds `EPOL_DB_*` credentials.

## LISP layout (v2.1)

`epoleodomia.lsp` is a **loader only** — it defines no commands. It resolves the
module folder (`*epol-dir*` → its own folder → support path →
`*epol-dir-default*`) and loads six modules in order:

| Module | Contents |
|---|---|
| `epol-core.lsp` | config, HTTP (`epol:http-get/post`), JSON + coord parsing, layer mgmt, drawing, table primitives. **Loads first.** |
| `epol-site.lsp` | `OROITABLE` `ETABLE` `EREPORT` `ENOTES` `ARCHEO` `CHURCH` `NATURA` `AIGIALOS` `REMATA` |
| `epol-bounds.lsp` | `KAEK` `EKAEK` `OT` `EOBT` `KAEK_OP` |
| `epol-ktima.lsp` | `KLAYERS` `KPST` `KGEOM` `KGEOMV` `KVERT` `KGRID` `AIGDRAW` `KCHECK` |
| `epol-raster.lsp` | `ERASTER` `FEK` `DJI` `DE` `CLIPR` |
| `epol-util.lsp` | `ETRANS` `ELAYERS` `EHELP` |

`kexport.lsp` (`KEXPORT`) and `kfilters.lsp` (`KFILTERS` `KFILTERSDEL`
`KTSEED`) are **loaded separately** and depend on `*ktima-layers*` /
`*epol-layers*` from `epol-core.lsp`, so `epoleodomia.lsp` must load first.

### Rules when editing LISP

- Put new commands in the module that matches their domain; put shared helpers
  in `epol-core.lsp`. Do not add commands to `epoleodomia.lsp`.
- Namespace helpers: `epol:` for general, `kgeom:` `kvert:` `kgrid:` `kcheck:`
  for command-specific ones.
- Adding a module means adding it to `*epol-modules*` in the loader.
- **`EHELP` in `epol-util.lsp` is hand-maintained** — update it when adding or
  renaming a command, or it silently drifts.
- Keep files **UTF-8 without BOM, LF endings**. Greek text in comments is fine;
  avoid Greek string literals in code (UTF-8 file vs ANSI loader → mojibake;
  see the `Κάθετες ΚΔ` workaround in `kfilters.lsp`).
- `outputs/verify.py` (session scratch) checks command/helper integrity, arity
  and load order against `git show HEAD:epoleodomia.lsp`. Re-derive it if a
  future refactor needs the same guarantees.

## Rasters — four mechanisms, one view

There are four raster catalogs, for historical reasons. Do **not** add a fifth.

| Table | Rows | Collection | Origin |
|---|---:|---|---|
| `epoleodomia.raster_catalog` | 103 | `fek` | `download_rasters.py` from the TEE service |
| `sp_geodata.dji_footprints` | 54 | `dji` | folder-scan script |
| `sp_geodata.de_footprints` | 322 | `de` | shapefile import |
| `sp_geodata.raster_sheets` | new | anything | `ingest_rasters.py` |

`sp_geodata.v_all_rasters` unions all four. Query **that**, not the base tables.
It exposes `query_geom = COALESCE(useful_area, footprint, extent)` and a `role`
column. New collections go into `raster_sheets` via `ingest_rasters.py` — that is
why `ERASTER` needs no new code per collection.

### role is not decoration

- `working` — fine scale, small RMS, safe to trace on
- `context` — coarse scale or large RMS, orientation only
- `historical` — evidence-grade document, non-conformal georeferencing
- `excluded` — hidden regardless of technical quality, via
  `sp_geodata.raster_exclusions`

Default in every endpoint is `working` only. This exists because a single point
was claimed by 8.9 sheets on average, thanks to 1:100000–1:200000 index sheets
with 52–288 m RMS. Never widen the default to shut up an empty result.

`sp_geodata.raster_exclusions` holds the six ΦΕΚ that used to be a hardcoded
`NOT IN` list inside `/rasters/fek/simple`. Three of them have **no recorded
reason** and are technically excellent (18 sheets, 1:1000, RMS 0.13–1.44 m) —
see the open item in STATUS.md. Do not "fix" this by deleting the rows.

### Rules when adding rasters

- `ingest_rasters.py` is dry-run by default. Keep it that way.
- It rejects anything not EPSG:2100 and north-up **with a reason**. Do not add a
  "best effort" fallback; a wrong datum looks plausible and is off by tens of
  metres.
- The upsert deliberately does not overwrite `role`, `nominal_scale`, `georef_*`,
  `doc_*`, `notes`, `useful_area` — those are human judgements and a file rescan
  must not discard them.
- Default compression is lossless LZW, not JPEG: these are scanned line drawings
  with text, and JPEG rings around black lines.
- `rasterio` is **required**, not optional. `download_rasters.py` wraps its
  import in `except ImportError: pass` and will silently write NULL metadata —
  do not copy that pattern.

## Known dead code

`epol:parse-rasters-info` in `epol-raster.lsp` is defined but never called —
pre-existing since v2.0, left in place deliberately.

## Python side

FastAPI in `api_server.py` on `127.0.0.1:8000`; every LISP command reads from
it. Two data sources: `epoleodomia` (OT, planning, building regs) and
`sp_geodata` (KAEK, churches, streams, rasters). Most endpoints return
pipe-delimited `/simple` text, not JSON — that is why the LISP parsing helpers
are string-based.
