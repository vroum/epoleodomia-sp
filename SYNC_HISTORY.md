# Forward-only sync history

Open `http://127.0.0.1:8000/sync-history`, menu **7**, or
`sync_menu.bat history`. The existing API must be running. Opening history
requires no writer credentials and cannot start an update.

## One-time activation

From the project folder:

```powershell
.venv\Scripts\python.exe -B setup_sync_history.py
.venv\Scripts\python.exe -B setup_sync_history.py --apply
```

The first command previews using the normal API reader. The second prompts
locally for the schema owner and hidden password, creates four new journal
tables in `epol_meta`, and grants the existing API role SELECT only. The existing
`epol_sync` receives SELECT plus INSERT on layers/changes, INSERT/UPDATE on
attempts, and USAGE on the change-ID sequence. No new login is created. The
owner credentials are not saved and `.env` is not edited. The exact DDL is
`sql/admin/sync_history.sql`; `--sql` prints DDL and role-specific grants without
connecting. Setup is transactional, refuses an active atomic publication and
preserves the start date when repeated.

**Start is installation time.** Neither old JSON receipts nor existing
`sync_runs`/`changelog` entries are imported. The next menu data publication
(1/2/3/5, or the data phase of 6) creates the first journal entry. An earlier
same-day publication does not appear retroactively. No production sync is run
by setup. Until activation, the screen explicitly says history is not enabled;
the existing menu continues to work.

## Reading the screen

- Default period: four calendar months back from today's date through today,
  using Greek local midnight boundaries, including daylight-saving changes.
  Last month, last attempt and custom dates are available.
- Filter by source; changed tables only is the default. Counts include only
  **committed** publications. A record can change in multiple runs, so period
  totals are change events. Each layer also shows distinct affected identities.
- Geometry changes are a subset of modifications, not extra records. Technical
  source-ID-only changes have their own count and detail filter.
- Click a run's date for paginated changes, filter by table/type/KAEK, and inspect
  changed attributes before/after. Failed attempts have no published changes.
  An unconfirmed attempt may still be running or may have been interrupted;
  the screen does not infer a failure from elapsed time.
- After a committed menu sync, the console prints each changed table and totals,
  then the history URL. Local JSON receipts remain useful diagnostics.

## Identity and comparison contract

| Source | Comparison identity |
|---|---|
| Cadastre parcels | KAEK |
| Cadastre easements | KAEK + RIGHT_SN |
| Cadastre exclusive uses | KAEK + VP_NUM |
| TEE lot regulations | OBJECTID + OROS_TYPE (a NULL type is valid) |
| Other TEE tables / EMSY | OBJECTID |

Import PKs (`id` for TEE, `gid` for cadastre/EMSY), import timestamps, generated
columns and derived forest `area_m2` are excluded from business comparisons.
Cadastre's **source field named `id` is retained**. Cadastre OBJECTID renumbering
does not create an addition/modification when attributes and geometry are equal.
Other source attributes remain comparable. Geometry uses PostGIS `ST_Equals`,
so changing polygon vertex order alone is not an edit. Missing or duplicate
stable identities abort the whole publication instead of guessing counts.

This contract reflects the reviewed sources; future source identity/schema
changes need review. A TEE/EMSY OBJECTID renumbering cannot be inferred to be the
same business record. Retained rows from an empty TEE response count unchanged;
the existing EMSY loader never removes absent points. Journal counts describe
the actual result in this database, not unobserved upstream changes.

## Transaction and scope

A small attempt row is committed after access checks and the publication lock,
before downloads. Each source before-image lives only in a temporary table.
Layer counts, changed records and the committed status are written in the same
transaction as all selected GIS tables. Any history failure rolls that entire
publication back; a separate best-effort update records the failed attempt.
A lost COMMIT response never allows that handler to overwrite a committed row.
If the final status cannot be recorded, the attempt remains unconfirmed.

The API reads through a repeatable-read, read-only pooled session, with bounded
pagination/timeouts, parameterized filters and no update endpoints. Its network
access policy is the existing internal GIS API's policy. The page has local
assets and renders source text as text, including HTML-like attribute values.

Only the atomic data publisher is covered. Direct legacy scripts, manual SQL,
manual edits and raster/NAS work do not enter this journal. Old audit tables and
JSON files retain their existing behavior. History is retained; the four-month
filter is not a deletion policy. Frozen migrations 0001/0002, preparation SQL,
LISP protocols, raster catalogs and source-table ownership stay unchanged.

## Planned: map of changes

Recorded as a follow-up on 2026-11-01. Add a map using the history page's period,
source and table filters, distinguish additions/modifications/removals, zoom to
a selected KAEK and compare geometry before/after. Read the recorded geometries
so removed features and older shapes remain visible. The journal schema already
provides `old_geom` and `new_geom` on change records after activation.

Recommended timing is after activation and initial use with real sync runs, so
the map can be checked against actual examples. Map UI and spatial endpoints
remain future work; this entry records the backlog item only.
