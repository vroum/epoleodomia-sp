-- ============================================================================
-- Post-sync seed operations
-- Run AFTER first data sync to populate derived data
-- Historical manual seed. Current planning_diagrams loaders automatically run
-- 006_refresh_raster_catalog.sql in their data transaction. Prefer that refresh
-- for subsequent catalog updates; it preserves existing technical judgements.
-- ============================================================================

SET search_path TO epoleodomia, public;

-- ============================================================================
-- 1. Seed raster_catalog from planning_diagrams
-- ============================================================================

INSERT INTO raster_catalog (
    planning_diagram_objectid, fek, filename,
    url_georef, url_raw, georef_rms, original_scale, download_status
)
SELECT
    pd.objectid, pd.fek,
    REGEXP_REPLACE(pd.georef_diagram_url, '.*/([^/]+)$', '\1') AS filename,
    pd.georef_diagram_url, pd.initial_diagram_url,
    pd.ggrs87_diagr_georef_rms, pd.init_diagr_scale_denominator,
    'pending'
FROM planning_diagrams pd
WHERE pd.georef_diagram_url IS NOT NULL
ON CONFLICT (url_georef) DO UPDATE SET
    fek = EXCLUDED.fek,
    url_raw = EXCLUDED.url_raw,
    georef_rms = EXCLUDED.georef_rms,
    original_scale = EXCLUDED.original_scale,
    updated_at = NOW();

-- ============================================================================
-- 2. Calculate forest map areas from geometry where missing
-- ============================================================================

UPDATE forest_maps SET area_m2 = ST_Area(geom)
    WHERE area_m2 IS NULL OR area_m2 = 0;
UPDATE forest_maps_posted_attica_2021 SET area_m2 = ST_Area(geom)
    WHERE area_m2 IS NULL OR area_m2 = 0;
UPDATE forest_maps_posted_pelop_2022 SET area_m2 = ST_Area(geom)
    WHERE area_m2 IS NULL OR area_m2 = 0;

-- ============================================================================
SELECT 'Post-sync seed completed' AS status;
-- ============================================================================
