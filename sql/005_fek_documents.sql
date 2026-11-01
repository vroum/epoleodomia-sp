-- ============================================================================
-- 005_fek_documents.sql
-- Registry of FEK documents: where the PDF lives, remote and local.
-- ============================================================================
--
-- WHY THIS EXISTS
--   sp_geodata.fek_publications (24 rows) and sp_geodata.fek_sheets (74 rows)
--   duplicate epoleodomia data field-for-field. Verified against the live DB:
--
--     fek_sheets.geom            = planning_diagrams.geom             74/74
--     fek_sheets.georef_rms      = raster_catalog.georef_rms          74/74
--     fek_sheets.sheet_number    = planning_diagrams
--                                    .comp_diagr_legend_number        74/74
--     fek_sheets.georef_tif_url  = raster_catalog.url_georef          74/74
--     fek_publications.{publ_date, apof_eidos, title, number_,
--                       sign_date, fek_pdf_url}
--                                = planning_diagrams.{same}           24/24
--
--   And both mirrors are stale: 74 of 103 diagrams, 24 of 36 distinct FEK.
--   /rasters/sheets already serves the raster side through v_all_rasters, with
--   role filtering on top. Nothing in api_server.py or the .lsp files reads
--   either table.
--
--   Exactly ONE column in the pair is not a duplicate:
--
--     fek_publications.local_pdf_path  ->  the only pointer, anywhere in the
--                                          database, to the 24 FEK PDFs held
--                                          locally. planning_diagrams carries
--                                          fek_file_url (remote TEE) only.
--
--   This migration gives that column a home so the mirrors can be dropped
--   without losing it. It drops nothing - see section 6.
--
-- WHY NOT JUST ADD THE COLUMN TO planning_diagrams
--   Because the sync would erase it, on either code path:
--
--     load_postgis.py:196   TRUNCATE TABLE {schema}."{table}" RESTART IDENTITY
--                           - the default path (truncate=True). All rows go.
--     load_postgis.py:262   update_cols = every column except objectid,
--                           set from EXCLUDED. The --track path. A TEE feature
--                           has no local_pdf_path property, so the value comes
--                           through as None and the UPDATE writes NULL over it.
--
--   sp_geodata is not a sync target - config.py:45 defaults the sync schema to
--   epoleodomia, and neither sync_all.py nor load_postgis.py mentions
--   sp_geodata. So a table here survives every sync. That is the whole reason
--   this lives in sp_geodata and not next to the data it describes.
--
-- PATH CONVENTION
--   The 24 local paths are NAS-side and share one prefix, verified as the only
--   distinct value across all 24 rows:
--
--     /volume2/Sp_net/epoleodomia_dir/spetses_urban_planning/footprints_epoleodomia
--       + /{year}_{number}/{filename}.pdf        e.g. 1981_1/091229FT000001XXD-1981.pdf
--
--   AutoCAD and the API run on Windows and cannot open /volume2/... So:
--
--     rel_path   '1981_1/091229FT000001XXD-1981.pdf'  <- THE CONTRACT.
--                Matches how the API already builds paths:
--                api_server.py:3647  os.path.join(RASTER_BASE_PATH, relative_path)
--                A consumer joins rel_path onto a root from the environment,
--                so moving the share never means a data migration.
--     nas_path   the original string, verbatim. Provenance only, never served.
--     abs_path   optional Windows convenience, left NULL. Section 5 has the
--                one-line UPDATE to fill it once the O:\ root is confirmed -
--                the mapping from the NAS prefix to O:\ was NOT verifiable
--                from the DB, so this migration refuses to guess it.
--
-- Run once:  psql -d gis -f sql/005_fek_documents.sql
-- Idempotent: safe to re-run.
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS sp_geodata;

BEGIN;

-- ============================================================================
-- 1. TABLE
-- ============================================================================
-- One row per FEK, keyed on the FEK string as it appears in epoleodomia.
-- Not keyed on planning_diagrams.objectid: a FEK has 1..n diagrams but at most
-- one gazette PDF, and objectid is reassigned by the sync's RESTART IDENTITY.

CREATE TABLE IF NOT EXISTS sp_geodata.fek_documents (
    id              SERIAL PRIMARY KEY,

    -- identity ---------------------------------------------------------------
    fek             TEXT NOT NULL UNIQUE,   -- '1Δ/1981', '163ΑΑΠ/2009'
                                            -- joins epoleodomia.*.fek verbatim

    -- the gazette PDF --------------------------------------------------------
    pdf_url         TEXT,                   -- remote, from TEE
    rel_path        TEXT,                   -- '1981_1/091229FT...pdf' - see header
    abs_path        TEXT,                   -- Windows path, NULL until confirmed
    nas_path        TEXT,                   -- original /volume2/... provenance
    downloaded      BOOLEAN NOT NULL DEFAULT FALSE,

    -- bookkeeping ------------------------------------------------------------
    file_size_bytes BIGINT,                 -- NULL: not measurable from SQL
    source          TEXT,                   -- where this row came from
    notes           TEXT,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE  sp_geodata.fek_documents IS
    'Which FEK we hold a PDF for, and where. Survives the epoleodomia sync by '
    'living in sp_geodata. Backfilled from the retired sp_geodata.fek_publications.';
COMMENT ON COLUMN sp_geodata.fek_documents.rel_path IS
    'Path relative to the FEK PDF root. Join a root from the environment onto '
    'this; do not store absolute paths as the contract.';
COMMENT ON COLUMN sp_geodata.fek_documents.nas_path IS
    'Original NAS path from fek_publications.local_pdf_path. Provenance only - '
    'not openable from Windows, never serve it to AutoCAD.';
COMMENT ON COLUMN sp_geodata.fek_documents.downloaded IS
    'TRUE means rel_path was populated from a row that claimed the file exists. '
    'Nothing here has stat()-ed the file; treat as a claim, not a guarantee.';

-- ============================================================================
-- 2. BACKFILL - the 24 local PDFs (the part that would otherwise be lost)
-- ============================================================================

INSERT INTO sp_geodata.fek_documents
        (fek, pdf_url, rel_path, nas_path, downloaded, source, notes)
SELECT
    btrim(p.fek),
    p.fek_pdf_url,
    -- last two components: '{year}_{number}/{filename}.pdf'
    regexp_replace(p.local_pdf_path, '^.*/([^/]+/[^/]+)$', '\1'),
    p.local_pdf_path,
    COALESCE(p.downloaded, FALSE),
    'fek_publications',
    p.notes
FROM sp_geodata.fek_publications p
WHERE p.local_pdf_path IS NOT NULL
ON CONFLICT (fek) DO UPDATE SET
    pdf_url    = COALESCE(EXCLUDED.pdf_url,  sp_geodata.fek_documents.pdf_url),
    rel_path   = COALESCE(EXCLUDED.rel_path, sp_geodata.fek_documents.rel_path),
    nas_path   = COALESCE(EXCLUDED.nas_path, sp_geodata.fek_documents.nas_path),
    downloaded = EXCLUDED.downloaded OR sp_geodata.fek_documents.downloaded,
    source     = EXCLUDED.source,
    updated_at = NOW();

-- ============================================================================
-- 3. COMPLETE THE REGISTRY - FEK we know about but hold no PDF for
-- ============================================================================
-- Without this the table only answers "here are 24 paths". With it, it answers
-- "do we have the PDF for this FEK?" - which is the question a /fek endpoint or
-- a download job actually asks. 12 from planning_diagrams + 1 that appears only
-- in fek_no_diagrams (90ΑΑΠ/2016), all with a remote URL to fetch from.
--
-- 5 of the 12 are the coarse regional sheets already blacklisted in
-- /rasters/fek/simple and marked role='excluded' by 004:
--   176Δ/1970, 208Δ/1969, 275Δ/1970, 42ΑΑΠ/2015, 541ΑΑΠ/2007
-- They are recorded here anyway - a gazette PDF is worth having even when the
-- diagram is useless for tracing. Filter on role at the raster layer, not here.

INSERT INTO sp_geodata.fek_documents (fek, pdf_url, downloaded, source, notes)
-- One candidate per target key, including FEK present in BOTH sources (e.g.
-- 406Δ/1989). DISTINCT over (fek,url,src) does not prevent an upsert from
-- affecting the same row twice. Prefer a nonblank URL, then active diagrams,
-- then a stable URL tie-break; existing registry URLs/local paths still win.
SELECT DISTINCT ON (btrim(k.fek))
    btrim(k.fek), NULLIF(btrim(k.fek_file_url), ''), FALSE, k.src, 'no local PDF yet'
FROM (
    SELECT fek, fek_file_url, 'planning_diagrams' AS src, 0 AS source_priority
    FROM epoleodomia.planning_diagrams
    WHERE fek IS NOT NULL AND NOT COALESCE(is_deleted, FALSE)
    UNION ALL
    SELECT fek, fek_file_url, 'fek_no_diagrams' AS src, 1 AS source_priority
    FROM epoleodomia.fek_no_diagrams
    WHERE fek IS NOT NULL
) k
WHERE btrim(k.fek) <> ''
ORDER BY btrim(k.fek),
         NULLIF(btrim(k.fek_file_url), '') IS NULL,
         k.source_priority,
         NULLIF(btrim(k.fek_file_url), '') COLLATE "C"
ON CONFLICT (fek) DO UPDATE SET
    -- never downgrade a row that already has a local path
    pdf_url    = COALESCE(sp_geodata.fek_documents.pdf_url, EXCLUDED.pdf_url),
    updated_at = NOW();

-- ============================================================================
-- 4. INDEXES
-- ============================================================================

CREATE INDEX IF NOT EXISTS fek_documents_downloaded_idx
    ON sp_geodata.fek_documents (downloaded)
    WHERE downloaded;

-- ============================================================================
-- 5. ABS_PATH - run manually, after confirming the Windows root
-- ============================================================================
-- The NAS prefix and the API's Windows roots do not share their intermediate
-- folder names, so the mapping cannot be derived from the data:
--
--   NAS  /volume2/Sp_net/epoleodomia_dir/spetses_urban_planning/footprints_epoleodomia/
--   API  O:\gis_data\epoleodomia\poleodomikoi oroi\        (api_server.py:49,
--        O:\claude_code area\...\epoleodomia\rasters\georef  api_server.py:46)
--
-- Only the trailing 'poleodomikoi oroi geotifs' matches, and that is the TIF
-- folder, not the PDF one. Confirm where the PDFs are reachable on O:, then:
--
--   UPDATE sp_geodata.fek_documents
--   SET abs_path = 'O:\<confirmed pdf root>\' || replace(rel_path, '/', '\'),
--       updated_at = NOW()
--   WHERE rel_path IS NOT NULL;
--
-- Preferred alternative: skip abs_path entirely, add EPOL_FEK_PDF_ROOT to the
-- environment and have the API do os.path.join(root, rel_path) as it already
-- does for rasters. Then there is one place to change when the share moves.

COMMIT;

-- ============================================================================
-- 6. WHAT THIS MIGRATION DELIBERATELY DOES NOT DO
-- ============================================================================
-- It does not drop sp_geodata.fek_publications, fek_sheets or fek_master.
-- Dropping is a separate step because two things are still unresolved:
--
--   a) Dependent views. These are CASCADE casualties, so DROP TABLE will
--      refuse (or take them with it):
--        sp_geodata.v_fek_sheets_full     fek_sheets JOIN fek_publications,
--                                         adds a georef_quality bucket
--                                         (excellent/good/fair/poor on RMS) -
--                                         worth reimplementing over
--                                         v_all_rasters before dropping
--        sp_geodata.v_fek_sheets_coastal  same join + nearest-shoreline
--                                         distance to Αιγιαλός_Παραλία
--      Neither is referenced from api_server.py or any .lsp.
--      sp_geodata.v_universal_fek is unrelated to these tables - it is a
--      hardcoded unnest(ARRAY[...]) of 6 FEK strings, an abandoned experiment,
--      and can go on its own.
--
--   b) External writers. pg_stat_user_tables reports 0 inserts, 0 updates and
--      0 deletes on all three tables - but pg_stat_database.stats_reset is
--      NULL, so that counter has no known start date and proves nothing.
--      The NAS paths suggest a Synology-side producer outside this repo.
--      Confirm nothing writes to them before dropping.
--
-- ON fek_master (68 rows) - do not just drop it, it is the only cross-domain
-- FEK registry in the database: poleodomiko 24, aigialos 23, mnimeia 20,
-- xersaia_zoni 1, with category + source_tables. Nothing else joins FEK across
-- shoreline / monuments / planning. The IDEA is worth keeping; this
-- implementation is not:
--   fek_number   100% NULL
--   fek_year     garbage - 1008, 1097, 1216, 1278, 1317, i.e. the FEK or YA
--                number parsed as a year
--   description  100% NULL
--   pdf_url      100% NULL
--   has_geometry TRUE on all 68 rows - carries no information
--   fek          free text, so unjoinable: '1Δ/1981' in planning_diagrams vs
--                ' ΥΑ ΥΠΠΟ/ΑΡΧ/Β1/Φ26/24042/393/11-6-1991, ΦΕΚ 896/Β/5-11-1992'
--                here, leading space included. No FK to anything.
-- Rebuild it as a view over the real layers, then drop the table.
--
-- TRAP, for whoever writes that view: fek_sheets.fek_id references
-- fek_publications(id), NOT fek_master(id). There is a real FK saying so.
-- Joining it to fek_master.id returns a plausible-looking wrong answer -
-- sheet 1 (file FS000001-1981, i.e. 1Δ/1981) comes back as
-- 'ΦΕΚ 896/Β/1992, μνημεία'.

-- ============================================================================
-- 7. VERIFY
-- ============================================================================
-- Expected: 24 local, 37 total, 0 lost, 0 malformed.

-- 7a. counts
--   SELECT count(*) AS total,
--          count(*) FILTER (WHERE downloaded)          AS local_pdf,
--          count(*) FILTER (WHERE rel_path IS NOT NULL) AS with_rel_path,
--          count(*) FILTER (WHERE pdf_url  IS NOT NULL) AS with_remote_url
--   FROM sp_geodata.fek_documents;

-- 7b. nothing lost from the source table - must return 0 rows
--   SELECT p.fek, p.local_pdf_path
--   FROM sp_geodata.fek_publications p
--   WHERE p.local_pdf_path IS NOT NULL
--     AND NOT EXISTS (SELECT 1 FROM sp_geodata.fek_documents d
--                     WHERE d.fek = btrim(p.fek) AND d.rel_path IS NOT NULL);

-- 7c. rel_path really is the last two components - must return 0 rows
--   SELECT fek, nas_path, rel_path
--   FROM sp_geodata.fek_documents
--   WHERE nas_path IS NOT NULL
--     AND nas_path <> '/volume2/Sp_net/epoleodomia_dir/spetses_urban_planning'
--                     '/footprints_epoleodomia/' || rel_path;

-- 7d. every FEK here is a FEK epoleodomia knows - must return 0 rows
--   SELECT d.fek FROM sp_geodata.fek_documents d
--   WHERE NOT EXISTS (SELECT 1 FROM epoleodomia.planning_diagrams p
--                     WHERE btrim(p.fek) = d.fek)
--     AND NOT EXISTS (SELECT 1 FROM epoleodomia.fek_no_diagrams n
--                     WHERE btrim(n.fek) = d.fek);

-- 7e. survives a sync, unlike the rejected planning_diagrams column:
--   python sync_all.py   (or with --track), then re-run 7a. Numbers unchanged.
-- ============================================================================
