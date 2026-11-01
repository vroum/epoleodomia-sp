-- ============================================================================
-- TEE Urban Planning Data Mirror — Views
-- v1.1 — All views consolidated and corrected
--
-- Run AFTER 001_tables.sql and AFTER first data sync
-- ============================================================================

-- HISTORICAL DEFINITIONS: superseded by sql/migrations/0002_live_tee_contract.sql.
-- Do not replay against the current installation. Use database_setup.py preview.
SET search_path TO epoleodomia, public;

-- ============================================================================
-- PRIMARY VIEW: Building blocks with all regulations + zone fallback
-- ============================================================================
CREATE OR REPLACE VIEW v_building_blocks_regulations AS
SELECT DISTINCT ON (b.id)
    b.id,
    b.objectid,
    b.ot_num,
    b.fek,
    b.fek_file_url,
    b.publ_date,
    b.kall_dhm_name,

    -- Height
    h.max_height_m,
    h.num_orofon,
    h.oror_max_height_comment AS height_comment,

    -- Coverage
    c.synt_kalypsis AS coverage_pct,
    c.remarks AS coverage_remarks,

    -- Coefficient: per-block first, fallback to zone
    COALESCE(f.sd_timh, z.sd_timh) AS building_coefficient,
    COALESCE(f.sd_tomeas, z.sd_tomeas) AS sd_tomeas,
    COALESCE(f.sd_klimakotos, z.sd_klimakotos) AS sd_klimakotos,
    COALESCE(f.sd_comment, z.sd_comment) AS coefficient_comment,
    CASE
        WHEN f.sd_timh IS NOT NULL THEN 'per_block'
        WHEN z.sd_timh IS NOT NULL THEN 'zone'
        ELSE NULL
    END AS coefficient_source,

    -- Lot requirements
    l_kanona.elax_embado_m2 AS min_lot_size_m2,
    l_kanona.elax_prosop_m AS min_frontage_m,
    COALESCE(l_kanona.oros_type, l_parek.oros_type) AS oros_type,
    l_parek.date_pareklisis,
    l_parek.remarks AS lot_remarks,

    -- Building system
    s.oik_systima AS building_system,

    -- Land use
    lu.per_cat_gen AS land_use_general,
    lu.per_cat_eid AS land_use_specific,
    lu.remarks AS land_use_remarks,

    -- Geometry
    b.geom

FROM building_blocks b

LEFT JOIN building_regs_height h
    ON ST_Intersects(ST_Centroid(b.geom), h.geom)
    AND NOT COALESCE(h.is_deleted, false)

LEFT JOIN building_regs_coverage c
    ON ST_Intersects(ST_Centroid(b.geom), c.geom)
    AND NOT COALESCE(c.is_deleted, false)

LEFT JOIN building_regs_coefficient f
    ON ST_Intersects(ST_Centroid(b.geom), f.geom)
    AND NOT COALESCE(f.is_deleted, false)

LEFT JOIN building_regs_coefficient_zones z
    ON ST_Intersects(ST_Centroid(b.geom), z.geom)
    AND f.sd_timh IS NULL

LEFT JOIN building_regs_lot l_kanona
    ON ST_Intersects(ST_Centroid(b.geom), l_kanona.geom)
    AND NOT COALESCE(l_kanona.is_deleted, false)
    AND l_kanona.oros_type = 'ΚΑΤΑ ΚΑΝΟΝΑ'

LEFT JOIN building_regs_lot l_parek
    ON ST_Intersects(ST_Centroid(b.geom), l_parek.geom)
    AND NOT COALESCE(l_parek.is_deleted, false)
    AND l_parek.oros_type = 'ΚΑΤΑ ΠΑΡΕΚΚΛΙΣΗ'

LEFT JOIN building_regs_system s
    ON ST_Intersects(ST_Centroid(b.geom), s.geom)
    AND NOT COALESCE(s.is_deleted, false)

LEFT JOIN land_uses_ers lu
    ON ST_Intersects(ST_Centroid(b.geom), lu.geom)
    AND NOT COALESCE(lu.is_deleted, false)

WHERE NOT COALESCE(b.is_deleted, false)
ORDER BY b.id, h.max_height_m DESC NULLS LAST;

COMMENT ON VIEW v_building_blocks_regulations IS
    'Building blocks with all regulations joined. Coefficient uses per-block data with zone fallback.';

-- ============================================================================
-- Addresses with block info
-- ============================================================================
CREATE OR REPLACE VIEW v_addresses_with_blocks AS
SELECT
    a.id, a.addr AS address, a.num AS number, a.munic AS municipality,
    b.ot_num AS block_number, b.fek AS block_fek,
    a.geom, a.fetched_at
FROM addresses a
LEFT JOIN building_blocks b ON ST_Within(a.geom, b.geom);

-- ============================================================================
-- Land uses summary (FIXED: uses per_cat_gen not gen_xrhsh_gps for ERS)
-- ============================================================================
CREATE OR REPLACE VIEW v_land_uses_summary AS
SELECT
    COALESCE(gps.id, ers.id) AS id,
    COALESCE(gps.gen_xrhsh_gps, ers.per_cat_gen) AS general_use,
    COALESCE(gps.per_cat_gen, ers.per_cat_gen) AS category_general,
    COALESCE(gps.per_cat_eid, ers.per_cat_eid) AS category_specific,
    COALESCE(gps.remarks, ers.remarks) AS remarks,
    COALESCE(gps.fek, ers.fek) AS fek,
    COALESCE(gps.kall_dhm_name, ers.kall_dhm_name) AS municipality,
    COALESCE(gps.geom, ers.geom) AS geom,
    CASE WHEN gps.id IS NOT NULL THEN 'GPS' ELSE 'ERS' END AS source
FROM land_uses_gps gps
FULL JOIN land_uses_ers ers ON gps.fek = ers.fek AND ST_Equals(gps.geom, ers.geom);

-- ============================================================================
-- Protected areas (combined)
-- ============================================================================
CREATE OR REPLACE VIEW v_protected_areas AS
SELECT 'archaeological_pl' AS protection_type, zone_name AS name, zone_type AS subtype, fek, kall_dhm_name AS municipality, geom FROM archaeological_zones_pl
UNION ALL
SELECT 'archaeological_site', name, NULL, NULL, ota, geom FROM archaeological_sites_polygons
UNION ALL
SELECT 'protection_zone', name, NULL, NULL, ota, geom FROM protection_zones_polygons
UNION ALL
SELECT 'historic_site', name, NULL, NULL, ota, geom FROM historic_sites_polygons
UNION ALL
SELECT 'natura_2000', sitename, sitetype, NULL, NULL, geom FROM natura_2000;

-- ============================================================================
-- All planning lines combined
-- ============================================================================
CREATE OR REPLACE VIEW v_planning_lines_all AS
SELECT 'planning' AS line_type, rg_type AS subtype, fek, road_width, prasia_width, kall_dhm_name AS municipality, geom FROM planning_lines
UNION ALL
SELECT 'building', og_type, fek, NULL, prasia_width, kall_dhm_name, geom FROM building_lines
UNION ALL
SELECT 'other', pol_gr_type, fek, NULL, NULL, kall_dhm_name, geom FROM other_planning_lines;

-- ============================================================================
-- FEK reference lookup (normalized)
-- ============================================================================
CREATE OR REPLACE VIEW v_fek_references AS
SELECT DISTINCT fek, fek_file_url, publ_date, apof_eidos, title, number_, sign_date, kall_dhm_name
FROM (
    SELECT fek, fek_file_url, publ_date, apof_eidos, title, number_, sign_date, kall_dhm_name FROM building_blocks WHERE fek IS NOT NULL
    UNION
    SELECT fek, fek_file_url, publ_date, apof_eidos, title, number_, sign_date, kall_dhm_name FROM planning_lines WHERE fek IS NOT NULL
    UNION
    SELECT fek, fek_file_url, publ_date, apof_eidos, title, number_, sign_date, kall_dhm_name FROM building_lines WHERE fek IS NOT NULL
    UNION
    SELECT fek, fek_file_url, publ_date, apof_eidos, title, number_, sign_date, kall_dhm_name FROM building_regs_height WHERE fek IS NOT NULL
    UNION
    SELECT fek, fek_file_url, publ_date, apof_eidos, title, number_, sign_date, kall_dhm_name FROM building_regs_coverage WHERE fek IS NOT NULL
    UNION
    SELECT fek, fek_file_url, publ_date, apof_eidos, title, number_, sign_date, kall_dhm_name FROM building_regs_coefficient WHERE fek IS NOT NULL
    UNION
    SELECT fek, fek_file_url, publ_date, apof_eidos, title, number_, sign_date, NULL FROM planning_diagrams WHERE fek IS NOT NULL
) combined
ORDER BY fek;

-- ============================================================================
-- Sync status
-- ============================================================================
CREATE OR REPLACE VIEW v_sync_status AS
SELECT
    table_name, service_name, layer_id, records_fetched, status, sync_completed_at,
    CASE
        WHEN sync_completed_at IS NULL THEN 'Never synced'
        WHEN sync_completed_at < NOW() - INTERVAL '7 days' THEN 'Stale (>7 days)'
        WHEN sync_completed_at < NOW() - INTERVAL '1 day' THEN 'Recent (1-7 days)'
        ELSE 'Fresh (<1 day)'
    END AS freshness
FROM sync_log sl
WHERE sl.id = (SELECT MAX(sl2.id) FROM sync_log sl2 WHERE sl2.table_name = sl.table_name)
ORDER BY sync_completed_at DESC NULLS LAST;

-- ============================================================================
-- Changelog views
-- ============================================================================

CREATE OR REPLACE VIEW v_recent_changes AS
SELECT c.changed_at, c.table_name, c.objectid, c.change_type, c.changed_fields, c.new_fek,
       sr.started_at AS sync_run_date
FROM changelog c LEFT JOIN sync_runs sr ON c.sync_run_id = sr.id
ORDER BY c.changed_at DESC;

CREATE OR REPLACE VIEW v_sync_run_summary AS
SELECT
    sr.id AS sync_run_id, sr.started_at, sr.completed_at, sr.status, sr.mode,
    COALESCE(sr.records_new, COUNT(*) FILTER (WHERE c.change_type = 'INSERT')) AS inserts,
    COALESCE(sr.records_updated, COUNT(*) FILTER (WHERE c.change_type = 'UPDATE')) AS updates,
    COALESCE(sr.records_deleted, COUNT(*) FILTER (WHERE c.change_type = 'DELETE')) AS deletes,
    COUNT(DISTINCT c.table_name) AS tables_affected
FROM sync_runs sr LEFT JOIN changelog c ON sr.id = c.sync_run_id
GROUP BY sr.id, sr.started_at, sr.completed_at, sr.status, sr.mode,
         sr.records_new, sr.records_updated, sr.records_deleted
ORDER BY sr.started_at DESC;

CREATE OR REPLACE VIEW v_fek_changes AS
SELECT c.changed_at, c.table_name, c.objectid, c.old_fek, c.new_fek, c.change_type
FROM changelog c
WHERE c.old_fek IS DISTINCT FROM c.new_fek AND (c.old_fek IS NOT NULL OR c.new_fek IS NOT NULL)
ORDER BY c.changed_at DESC;

CREATE OR REPLACE VIEW v_geometry_changes AS
SELECT c.changed_at, c.table_name, c.objectid, c.change_type,
       c.old_geom_wkt, c.new_geom_wkt, sr.started_at AS sync_run_date
FROM changelog c LEFT JOIN sync_runs sr ON c.sync_run_id = sr.id
WHERE c.geometry_changed = TRUE
ORDER BY c.changed_at DESC;

CREATE OR REPLACE VIEW v_regulation_changes AS
SELECT c.changed_at, c.table_name, c.objectid, c.change_type, c.changed_fields,
       c.old_values, c.new_values, c.old_fek, c.new_fek
FROM changelog c
WHERE c.table_name IN ('building_regs_height','building_regs_coverage','building_regs_coefficient',
                        'building_regs_lot','building_regs_system','building_blocks')
ORDER BY c.changed_at DESC;

-- ============================================================================
-- Raster catalog views
-- ============================================================================

CREATE OR REPLACE VIEW v_rasters_pending AS
SELECT id, fek, filename, url_georef, georef_rms, original_scale
FROM raster_catalog WHERE download_status = 'pending' ORDER BY fek, filename;

CREATE OR REPLACE VIEW v_rasters_downloaded AS
SELECT id, fek, filename, local_path_georef, file_size_bytes, width_px, height_px,
       resolution_x AS meters_per_pixel, crs_epsg, georef_rms, original_scale, downloaded_at,
       ST_AsText(bbox) AS bbox_wkt
FROM raster_catalog WHERE download_status = 'downloaded' ORDER BY fek, filename;

CREATE OR REPLACE VIEW v_rasters_by_fek AS
SELECT fek, COUNT(*) AS total_rasters,
    COUNT(*) FILTER (WHERE download_status = 'downloaded') AS downloaded,
    COUNT(*) FILTER (WHERE download_status = 'pending') AS pending,
    COUNT(*) FILTER (WHERE download_status = 'failed') AS failed,
    ROUND(SUM(file_size_bytes) FILTER (WHERE download_status = 'downloaded') / 1024.0 / 1024.0, 2) AS total_size_mb
FROM raster_catalog GROUP BY fek ORDER BY fek;

CREATE OR REPLACE VIEW v_rasters_failed AS
SELECT id, fek, filename, url_georef, download_error, last_checked
FROM raster_catalog WHERE download_status = 'failed' ORDER BY last_checked DESC;

-- ============================================================================
-- Function: Find rasters at a point
-- ============================================================================

CREATE OR REPLACE FUNCTION find_rasters_at_point(x_coord NUMERIC, y_coord NUMERIC)
RETURNS TABLE (id INTEGER, fek VARCHAR, filename VARCHAR, local_path VARCHAR, resolution_m NUMERIC)
AS $$
BEGIN
    RETURN QUERY
    SELECT rc.id, rc.fek, rc.filename, rc.local_path_georef, rc.resolution_x
    FROM raster_catalog rc
    WHERE rc.download_status = 'downloaded' AND rc.bbox IS NOT NULL
      AND ST_Contains(rc.bbox, ST_SetSRID(ST_MakePoint(x_coord, y_coord), 2100))
    ORDER BY rc.resolution_x;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
SELECT 'v1.1 views created successfully' AS status;
-- ============================================================================
