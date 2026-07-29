# Optimization Plan — Spetses GIS Project
_Proposed 2026-06-26 · plan only, no code changed yet_

Scope chosen: **propose a plan** (no edits), with a **safety net before any refactor**.
Ranked by payoff. Each phase lists effort, impact, risk, and the devil's-advocate caveat.

---

## Phase 0 — Safety net (prerequisite, do first)

**Goal:** lock down the current exact text output of every endpoint so later changes can't silently break the LISP contract.

**Do:**
1. `test_golden.py` — a small script that hits each of the 30 endpoints at ~10 fixed coordinates (parcel-inside, parcel-near, in-plan, archaeology, church, stream, raster-bbox, empty-result) and writes each raw response to `tests/golden/`. Re-run after any change and byte-diff.
2. `test_helpers.py` — pure-function unit tests for `_wkt_to_coords`, `_transliterate_greek`, `_translate_land_use_codes`, `_decode_forest_type`. No DB needed.

**Effort:** ~3–4 h · **Impact:** high (enables everything below) · **Risk:** none.
**Caveat:** goldens need a live PostGIS to record, and only cover the coordinates you pick — choose points that exercise both the "found" and "not found / nearest" branches, or the net has blind spots.

---

## Phase 1 — Runtime performance (biggest user-facing win)

**Problem A — N+1 queries.** `/kaek/simple` calls `_rings()` once per neighbor (up to 20+ round-trips per click); `EKAEK`/`EOBT` paths likely repeat the shape. Each `execute_query` also re-acquires a pooled connection.

**Fix:** batch neighbor rings into a single `ST_Dump`-based query keyed by the neighbor KAEK list (one round-trip instead of N), and acquire **one connection per request** rather than per query.

**Problem B — connection churn.** Endpoints that issue main + nearest + neighbors + rings call `getconn/putconn` 4–20× for one logical request. A per-request connection (FastAPI dependency or a small context helper) removes that overhead.

**Effort:** ~4–6 h · **Impact:** high (perceptible latency drop on every AutoCAD click) · **Risk:** medium — touches hot SQL; Phase 0 goldens must pass byte-identical afterward.
**Caveat:** the speedup only matters if clicks feel slow today. If the DB is on a fast LAN and parcels have few neighbors, real-world gain may be modest — worth timing one slow endpoint before investing.

---

## Phase 2 — Modularize `api_server.py` (maintainability, optional)

The helper + 3-wrapper pattern (`_get_X_data` + `/X`, `/X/text`, `/X/simple`) repeats ~15× in one 2,556-line file. Split into FastAPI routers by domain (kaek, oroi, archeo, rasters, …) with a shared `db.py`.

**Effort:** ~4–6 h · **Impact:** medium (maintainability only, zero perf) · **Risk:** medium-high — large file moves; **do not attempt without Phase 0 green.**
**Caveat:** pure cleanup. If you're the only maintainer and the file is stable, this is optional polish, not a real win. Defer unless you're actively adding endpoints.

---

## Phase 3 — LISP cleanup (optional)

Replace fragile hand-rolled JSON parsing (`epol:extract-json-value`, `extract-json-number`, `parse-rasters-info`) by having the API serve the same pipe format those endpoints' siblings already use; de-hardcode `*epol-api-url*`; reconcile `EHELP` with the real command list.

**Effort:** ~3–5 h · **Impact:** medium (fewer silent parse failures) · **Risk:** medium — LISP has no test harness, so changes are eyeball-verified in AutoCAD.
**Caveat:** highest-risk-per-reward because there's no automated net on the LISP side. Touch only the endpoints already covered by Phase 0 goldens, and only if the JSON parsers are actually causing failures.

---

## Recommended sequence

`Phase 0 → Phase 1 → stop and re-evaluate.`
Phases 2 and 3 are optional and should only follow if maintenance pain or parse failures justify the risk.

## Housekeeping (trivial, do anytime)
- `STATUS.md` says `api_server.py` is 2,073 lines; it's 2,556. Fix the drift.
- CORS is `allow_origins=["*"]` with `allow_credentials=True` — harmless on localhost, but tighten if ever exposed.
- Delete `__pycache__/` and `tmp/` from the working tree (already gitignored).
