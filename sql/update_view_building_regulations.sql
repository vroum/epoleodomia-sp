-- Update v_building_blocks_regulations view with additional fields
-- HISTORICAL PATCH: superseded by sql/migrations/0002_live_tee_contract.sql.
-- Replaying this drops the newer overlap/fallback/land-use improvements.
-- Run this in pgAdmin or psql with write access
--
-- Key change: Two joins for building_regs_lot:
--   1. l_kanona: ΚΑΤΑ ΚΑΝΟΝΑ rules (has numeric values for αρτιότητα/πρόσοψη)
--   2. l_parek: ΚΑΤΑ ΠΑΡΕΚΚΛΙΣΗ rules (has remarks explaining exception)

DROP VIEW IF EXISTS epoleodomia.v_building_blocks_regulations;

CREATE VIEW epoleodomia.v_building_blocks_regulations AS
SELECT DISTINCT ON (b.id)
    b.id,
    b.objectid,
    b.ot_num,

    -- FEK info (from building_blocks)
    b.fek,
    b.fek_file_url,
    b.publ_date,
    b.kall_dhm_name,

    -- Height regulations
    h.max_height_m,
    h.num_orofon,
    h.oror_max_height_comment AS height_comment,

    -- Coverage regulations
    c.synt_kalypsis AS coverage_pct,
    c.remarks AS coverage_remarks,

    -- Coefficient (ΣΔ)
    f.sd_timh AS building_coefficient,
    f.sd_tomeas,
    f.sd_klimakotos,
    f.sd_comment AS coefficient_comment,

    -- Lot requirements from ΚΑΤΑ ΚΑΝΟΝΑ (numeric values)
    l_kanona.elax_embado_m2 AS min_lot_size_m2,
    l_kanona.elax_prosop_m AS min_frontage_m,

    -- Lot exception info from ΚΑΤΑ ΠΑΡΕΚΚΛΙΣΗ (remarks)
    -- Use COALESCE to pick ΚΑΤΑ ΚΑΝΟΝΑ if exists, else ΚΑΤΑ ΠΑΡΕΚΚΛΙΣΗ
    COALESCE(l_kanona.oros_type, l_parek.oros_type) AS oros_type,
    l_parek.date_pareklisis,
    l_parek.remarks AS lot_remarks,

    -- Building system
    s.oik_systima AS building_system,

    -- Geometry
    b.geom

FROM epoleodomia.building_blocks b

LEFT JOIN epoleodomia.building_regs_height h
    ON ST_Intersects(ST_Centroid(b.geom), h.geom)
    AND NOT COALESCE(h.is_deleted, false)

LEFT JOIN epoleodomia.building_regs_coverage c
    ON ST_Intersects(ST_Centroid(b.geom), c.geom)
    AND NOT COALESCE(c.is_deleted, false)

LEFT JOIN epoleodomia.building_regs_coefficient f
    ON ST_Intersects(ST_Centroid(b.geom), f.geom)
    AND NOT COALESCE(f.is_deleted, false)

-- Join for ΚΑΤΑ ΚΑΝΟΝΑ (normal rules with numeric values)
LEFT JOIN epoleodomia.building_regs_lot l_kanona
    ON ST_Intersects(ST_Centroid(b.geom), l_kanona.geom)
    AND NOT COALESCE(l_kanona.is_deleted, false)
    AND l_kanona.oros_type = 'ΚΑΤΑ ΚΑΝΟΝΑ'

-- Join for ΚΑΤΑ ΠΑΡΕΚΚΛΙΣΗ (exception rules with remarks)
LEFT JOIN epoleodomia.building_regs_lot l_parek
    ON ST_Intersects(ST_Centroid(b.geom), l_parek.geom)
    AND NOT COALESCE(l_parek.is_deleted, false)
    AND l_parek.oros_type = 'ΚΑΤΑ ΠΑΡΕΚΚΛΙΣΗ'

LEFT JOIN epoleodomia.building_regs_system s
    ON ST_Intersects(ST_Centroid(b.geom), s.geom)
    AND NOT COALESCE(s.is_deleted, false)

WHERE NOT COALESCE(b.is_deleted, false)
ORDER BY b.id, h.max_height_m DESC NULLS LAST;

-- Verify the view
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'epoleodomia'
AND table_name = 'v_building_blocks_regulations'
ORDER BY ordinal_position;

-- Test query
SELECT ot_num, fek, sd_tomeas, oros_type, min_lot_size_m2, min_frontage_m, lot_remarks
FROM epoleodomia.v_building_blocks_regulations
WHERE ot_num = '229';
