-- ============================================================================
-- 004_raster_sheets.sql
-- Generic raster sheet catalog for locally georeferenced map sheets.
-- ============================================================================
--
-- WHY THIS EXISTS
--   Before this, every raster collection got its own table and its own LISP
--   command:
--     epoleodomia.raster_catalog   27 cols, download-oriented   -> FEK
--     sp_geodata.dji_footprints    33 cols, folder-scan output   -> DJI
--     sp_geodata.de_footprints      6 cols, shapefile import     -> DE
--   Adding GYS 1:5000 + aigialos diagrams + the 1867 plan the same way would
--   mean six tables, six endpoints and six commands. This table takes any
--   collection instead, keyed by the `collection` column.
--
--   The three existing tables are deliberately left untouched - they work.
--   v_all_rasters below unions all four so "what covers this point" has a
--   single answer.
--
-- THE `role` COLUMN REPLACES A HARDCODED BLACKLIST
--   /rasters/fek/simple currently carries:
--     AND pd.fek NOT IN ('740D/1981','208D/1969','176D/1970','275D/1970',
--                        '541AAP/2007','42AAP/2015')
--   Those are the 1:100000 and 1:200000 sheets: georef RMS 52-288 m and
--   bounding boxes of 11 505 and 26 910 km2, i.e. they blanket the whole
--   island and are useless for tracing. Excluding them drops the number of
--   sheets claiming a given point from 8.9 to 4.2.
--   That knowledge belongs in a column, not in one endpoint's WHERE clause -
--   find_rasters_at_point() does NOT have the blacklist and therefore
--   disagrees with the endpoint today.
--
-- Run once:  psql -d gis -f sql/004_raster_sheets.sql
-- Idempotent: safe to re-run.
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS sp_geodata;

-- ============================================================================
-- 1. TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS sp_geodata.raster_sheets (
    id                  SERIAL PRIMARY KEY,

    -- identity ---------------------------------------------------------------
    collection          TEXT NOT NULL,      -- gys5000 | aigialos | historic | ...
    filename            TEXT NOT NULL,
    rel_path            TEXT NOT NULL,      -- relative to the collection root
    abs_path            TEXT NOT NULL,      -- Windows path handed to AutoCAD

    -- change detection -------------------------------------------------------
    file_size_bytes     BIGINT,
    file_mtime          TIMESTAMPTZ,
    file_hash           TEXT,               -- size + head/tail digest, not full file

    -- geometry ---------------------------------------------------------------
    -- extent    = axis-aligned envelope from the geotransform (cheap prefilter)
    -- footprint = actual valid-data outline from the nodata/alpha mask; for a
    --             warped scan this excludes the black triangles at the corners
    -- useful_area = the neat line / omfelimos choros. NULL for now: filling it
    --             is a separate phase, see AGENTS.md.
    extent              GEOMETRY(Polygon, 2100) NOT NULL,
    footprint           GEOMETRY(Polygon, 2100),
    useful_area         GEOMETRY(Polygon, 2100),

    -- raster properties ------------------------------------------------------
    width_px            INTEGER,
    height_px           INTEGER,
    bands               INTEGER,
    dtype               TEXT,
    res_x               NUMERIC(12,6),
    res_y               NUMERIC(12,6),
    crs_epsg            INTEGER,
    nodata              NUMERIC,
    compression         TEXT,
    is_tiled            BOOLEAN,
    has_overviews       BOOLEAN,
    overview_count      INTEGER,

    -- usability / provenance -------------------------------------------------
    -- role drives both filtering and draw order:
    --   working    - trace on it (fine scale, small RMS)
    --   context    - orientation only, never measure
    --   historical - evidence-grade document, non-conformal georeferencing
    role                TEXT NOT NULL DEFAULT 'working'
                        CHECK (role IN ('working','context','historical','excluded')),
    nominal_scale       INTEGER,            -- 5000 for GYS 1:5000
    georef_rms          NUMERIC(10,4),
    georef_method       TEXT,               -- affine | poly2 | tps | native | ...
    georef_points       INTEGER,            -- number of control points used
    georef_by           TEXT,
    georef_date         DATE,
    doc_ref             TEXT,               -- FEK, sheet name, archive reference
    doc_date            DATE,
    notes               TEXT,

    added_at            TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),

    CONSTRAINT raster_sheets_unique_file UNIQUE (collection, rel_path)
);

COMMENT ON TABLE sp_geodata.raster_sheets IS
  'Locally georeferenced map sheets (GYS 1:5000, aigialos diagrams, historic '
  'plans, ...). Populated by ingest_rasters.py. One row per file.';

COMMENT ON COLUMN sp_geodata.raster_sheets.extent IS
  'Envelope from the geotransform. Indexed; use as a prefilter.';
COMMENT ON COLUMN sp_geodata.raster_sheets.footprint IS
  'Valid-data outline from the nodata/alpha mask. Prefer over extent.';
COMMENT ON COLUMN sp_geodata.raster_sheets.useful_area IS
  'Neat line of the map sheet. NULL until digitised - phase 2.';
COMMENT ON COLUMN sp_geodata.raster_sheets.role IS
  'working = traceable, context = orientation only, historical = evidence '
  'document with non-conformal georeferencing. Never measure on the last two.';

-- ============================================================================
-- 2. INDEXES
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_raster_sheets_extent
    ON sp_geodata.raster_sheets USING GIST (extent);
CREATE INDEX IF NOT EXISTS idx_raster_sheets_footprint
    ON sp_geodata.raster_sheets USING GIST (footprint);
CREATE INDEX IF NOT EXISTS idx_raster_sheets_useful
    ON sp_geodata.raster_sheets USING GIST (useful_area);
CREATE INDEX IF NOT EXISTS idx_raster_sheets_collection
    ON sp_geodata.raster_sheets (collection);
CREATE INDEX IF NOT EXISTS idx_raster_sheets_role
    ON sp_geodata.raster_sheets (role);
CREATE INDEX IF NOT EXISTS idx_raster_sheets_hash
    ON sp_geodata.raster_sheets (file_hash);

-- ============================================================================
-- 3. updated_at trigger
-- ============================================================================

CREATE OR REPLACE FUNCTION sp_geodata.raster_sheets_touch()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_raster_sheets_touch ON sp_geodata.raster_sheets;
CREATE TRIGGER trg_raster_sheets_touch
    BEFORE UPDATE ON sp_geodata.raster_sheets
    FOR EACH ROW EXECUTE FUNCTION sp_geodata.raster_sheets_touch();

-- ============================================================================
-- 3b. EXCLUSIONS - the /rasters/fek/simple blacklist, moved into data
-- ============================================================================
-- /rasters/fek/simple carries a hardcoded list of six FEK. Five of them are
-- explained by scale and RMS (1:100000 / 1:200000, RMS 15-288 m) and the role
-- rule in the view below reproduces that automatically.
--
-- The other three are NOT explained by any measurable property:
--
--   FEK           sheets  scale     georef RMS
--   740D/1981         15  1:1000    0.13 - 0.55 m
--   176D/1970          2  1:1000    1.43 - 1.44 m
--   275D/1970          1  1:1000    1.38 m
--
-- Those are technically excellent sheets, so they were excluded for a domain
-- reason (superseded? wrong area? duplicates?) that is not recorded anywhere.
-- Rather than guess - and rather than silently re-admit 18 good-looking sheets
-- into every query - the list is carried over verbatim here.
--
-- VERIFIED: with these six rows present, v_all_rasters marks exactly 80 FEK
-- sheets 'working' and 23 'excluded', which is bit-for-bit what
-- /rasters/fek/simple admits today (0 rows differ in either direction).
--
-- ACTION FOR VANGELIS: fill in `reason` for each row. Delete a row to bring
-- that FEK back. See STATUS.md open items.

CREATE TABLE IF NOT EXISTS sp_geodata.raster_exclusions (
    collection  TEXT NOT NULL,
    doc_ref     TEXT NOT NULL,
    reason      TEXT,
    added_at    TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (collection, doc_ref)
);

COMMENT ON TABLE sp_geodata.raster_exclusions IS
  'Rasters to hide from v_all_rasters regardless of technical quality. '
  'Migrated from the hardcoded blacklist in /rasters/fek/simple.';

INSERT INTO sp_geodata.raster_exclusions (collection, doc_ref, reason) VALUES
    ('fek', '740Δ/1981',   'REASON UNKNOWN - carried over from the hardcoded blacklist in /rasters/fek/simple. 15 sheets, 1:1000, RMS 0.13-0.55 m. Needs a documented reason or removal.'),
    ('fek', '176Δ/1970',   'REASON UNKNOWN - carried over from the hardcoded blacklist. 2 sheets, 1:1000, RMS 1.43 m.'),
    ('fek', '275Δ/1970',   'REASON UNKNOWN - carried over from the hardcoded blacklist. 1 sheet, 1:1000, RMS 1.38 m.'),
    ('fek', '208Δ/1969',   'Index sheet 1:200000, RMS 126-288 m, extent 23 000-27 000 km2. Also caught by the role rule.'),
    ('fek', '541ΑΑΠ/2007', 'Index sheet 1:100000, RMS 15-85 m, extent ~10 000 km2. Also caught by the role rule.'),
    ('fek', '42ΑΑΠ/2015',  'Index sheet 1:100000, RMS 55 m, extent ~8 000 km2. Also caught by the role rule.')
ON CONFLICT (collection, doc_ref) DO NOTHING;

-- ============================================================================
-- 4. UNIFIED VIEW over all four raster sources
-- ============================================================================
-- One place to ask "which rasters cover this?" regardless of which historical
-- mechanism catalogued them. `query_geom` is the best available geometry for
-- each row: useful_area if digitised, else footprint, else extent.
--
-- role for the FEK rows is derived from scale + RMS instead of the hardcoded
-- FEK blacklist, so the rule is visible and applies everywhere.

CREATE OR REPLACE VIEW sp_geodata.v_all_rasters AS

-- 4a. locally georeferenced sheets (this table) ------------------------------
SELECT
    'sheets'::text              AS source_table,
    rs.collection,
    rs.id                       AS source_id,
    rs.filename,
    rs.abs_path                 AS path,
    COALESCE(rs.useful_area, rs.footprint, rs.extent) AS query_geom,
    rs.extent,
    rs.role,
    rs.nominal_scale,
    rs.res_x                    AS res_m,
    rs.georef_rms,
    rs.doc_ref,
    rs.doc_date,
    rs.file_size_bytes
FROM sp_geodata.raster_sheets rs

UNION ALL

-- 4b. FEK planning diagrams -------------------------------------------------
-- pd.geom is the official diagram footprint from the ArcGIS service, which is
-- a better query geometry than the raster extent - that is why
-- /rasters/fek/simple already joins on it.
SELECT
    'fek'::text                 AS source_table,
    'fek'::text                 AS collection,
    rc.id                       AS source_id,
    rc.filename,
    rc.local_path_georef        AS path,
    COALESCE(pd.geom, rc.bbox)  AS query_geom,
    rc.bbox                     AS extent,
    CASE
        -- explicit exclusions win over any technical rule
        WHEN x.doc_ref IS NOT NULL                         THEN 'excluded'
        WHEN pd.init_diagr_scale_denominator IS NULL        THEN 'working'
        WHEN pd.init_diagr_scale_denominator > 5000         THEN 'context'
        WHEN COALESCE(rc.georef_rms, 0) > 5                 THEN 'context'
        ELSE 'working'
    END                         AS role,
    pd.init_diagr_scale_denominator::int AS nominal_scale,
    rc.resolution_x             AS res_m,
    rc.georef_rms,
    pd.fek                      AS doc_ref,
    NULL::date                  AS doc_date,
    rc.file_size_bytes
FROM epoleodomia.raster_catalog rc
LEFT JOIN epoleodomia.planning_diagrams pd
       ON pd.objectid = rc.planning_diagram_objectid
      AND NOT COALESCE(pd.is_deleted, false)
LEFT JOIN sp_geodata.raster_exclusions x
       ON x.collection = 'fek' AND x.doc_ref = pd.fek
WHERE rc.download_status = 'downloaded'
  AND rc.filename IS NOT NULL

UNION ALL

-- 4c. DJI drone orthophotos -------------------------------------------------
-- Useful area == raster for an ortho, so geom is already the right answer.
SELECT
    'dji'::text                 AS source_table,
    'dji'::text                 AS collection,
    d.id                        AS source_id,
    d.filename,
    d.full_path                 AS path,
    d.geom                      AS query_geom,
    d.geom                      AS extent,
    'working'::text             AS role,
    NULL::int                   AS nominal_scale,
    d.res_x                     AS res_m,
    NULL::numeric               AS georef_rms,
    d.source_project            AS doc_ref,
    NULL::date                  AS doc_date,
    (d.file_size_mb * 1048576)::bigint AS file_size_bytes
FROM sp_geodata.dji_footprints d

UNION ALL

-- 4d. DE rasters ------------------------------------------------------------
SELECT
    'de'::text                  AS source_table,
    'de'::text                  AS collection,
    e."Id"                      AS source_id,
    e.filename,
    e.raster_path               AS path,
    e.geometry                  AS query_geom,
    e.geometry                  AS extent,
    'working'::text             AS role,
    NULL::int                   AS nominal_scale,
    NULL::numeric               AS res_m,
    NULL::numeric               AS georef_rms,
    e.sxolia                    AS doc_ref,
    NULL::date                  AS doc_date,
    NULL::bigint                AS file_size_bytes
FROM sp_geodata.de_footprints e;

COMMENT ON VIEW sp_geodata.v_all_rasters IS
  'Every catalogued raster from all four mechanisms. query_geom is the best '
  'available geometry per row (useful_area > footprint > extent). Use role to '
  'filter: working is traceable, context/historical are not.';

-- ============================================================================
-- 5. Replacement for find_rasters_at_point() that understands role
-- ============================================================================
-- The original returns every sheet whose *extent* contains the point,
-- including the 1:200000 ones. This one filters by role and orders finest
-- first, which is also the correct draw order.

CREATE OR REPLACE FUNCTION sp_geodata.rasters_at_point(
    x_coord      NUMERIC,
    y_coord      NUMERIC,
    p_roles      TEXT[] DEFAULT ARRAY['working'],
    p_collection TEXT   DEFAULT NULL
)
RETURNS TABLE (
    source_table  TEXT,
    collection    TEXT,
    source_id     INTEGER,
    filename      TEXT,
    path          TEXT,
    role          TEXT,
    nominal_scale INTEGER,
    res_m         NUMERIC,
    georef_rms    NUMERIC,
    doc_ref       TEXT
) AS $$
    SELECT v.source_table, v.collection, v.source_id, v.filename, v.path,
           v.role, v.nominal_scale, v.res_m, v.georef_rms, v.doc_ref
    FROM sp_geodata.v_all_rasters v
    WHERE v.query_geom IS NOT NULL
      AND ST_Contains(v.query_geom,
                      ST_SetSRID(ST_MakePoint(x_coord, y_coord), 2100))
      AND v.role = ANY(p_roles)
      AND (p_collection IS NULL OR v.collection = p_collection)
    ORDER BY COALESCE(v.nominal_scale, 2147483647) ASC,
             COALESCE(v.res_m, 1e9) ASC;
$$ LANGUAGE sql STABLE;

COMMENT ON FUNCTION sp_geodata.rasters_at_point IS
  'Rasters covering a point, filtered by role and ordered finest-first (which '
  'is also the correct draw order). Defaults to working sheets only.';

-- ============================================================================
SELECT 'sql/004_raster_sheets.sql applied' AS status;
-- ============================================================================
