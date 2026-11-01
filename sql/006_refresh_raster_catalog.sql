-- Refresh the existing TEE download catalog after planning_diagrams changes.
-- The loader executes this INSIDE the same transaction as the source rows.
-- No files, download state, geometry, exclusions or human judgements are reset.
-- Archived catalog entries remain available when a source diagram disappears.
INSERT INTO epoleodomia.raster_catalog AS dst (
    planning_diagram_objectid, fek, filename, url_georef, url_raw,
    georef_rms, original_scale, download_status
)
SELECT DISTINCT ON (pd.georef_diagram_url)
    pd.objectid, pd.fek,
    regexp_replace(pd.georef_diagram_url, '.*/([^/]+)$', '\1'),
    pd.georef_diagram_url, pd.initial_diagram_url,
    pd.ggrs87_diagr_georef_rms, pd.init_diagr_scale_denominator, 'pending'
FROM epoleodomia.planning_diagrams pd
WHERE NULLIF(btrim(pd.georef_diagram_url), '') IS NOT NULL
  AND NOT COALESCE(pd.is_deleted, false)
ORDER BY pd.georef_diagram_url, pd.objectid
ON CONFLICT (url_georef) DO UPDATE SET
    planning_diagram_objectid = EXCLUDED.planning_diagram_objectid,
    fek = EXCLUDED.fek,
    url_raw = EXCLUDED.url_raw,
    updated_at = NOW()
WHERE ROW(dst.planning_diagram_objectid, dst.fek, dst.url_raw)
      IS DISTINCT FROM ROW(EXCLUDED.planning_diagram_objectid, EXCLUDED.fek, EXCLUDED.url_raw);
