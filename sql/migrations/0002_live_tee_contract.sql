-- Preserve 0001 and its checksum. Apply only through database_setup.py.
-- Source: read-only catalog audit of the installed database, 2026-10-27.
-- Views retain the installed overlap matching, zone fallback and FEK additions.
-- Preconditions in the adjacent JSON reject edited source views before writes.
-- DROP VIEW uses RESTRICT: unknown dependents stop and roll back the upgrade.
-- No tables/data are dropped; sp_geodata and raster judgements are untouched.
SET LOCAL search_path TO epoleodomia, public;

-- Preserve metadata of views whose incompatible row types require recreation.
CREATE TEMP TABLE epol_v2_old_views ON COMMIT DROP AS
SELECT c.relname, pg_get_userbyid(c.relowner) AS owner_name, c.reloptions,
       COALESCE(c.relacl, acldefault('r', c.relowner)) AS acl,
       obj_description(c.oid, 'pg_class') AS description
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'epoleodomia' AND c.relname IN
    ('v_building_blocks_regulations','v_land_uses_summary','v_rasters_by_fek');
CREATE TEMP TABLE epol_v2_old_columns ON COMMIT DROP AS
SELECT c.relname, a.attname, a.attacl AS acl,
       col_description(c.oid, a.attnum) AS description
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
WHERE n.nspname = 'epoleodomia' AND c.relname IN
    ('v_building_blocks_regulations','v_land_uses_summary','v_rasters_by_fek');

DROP VIEW epoleodomia.v_building_blocks_regulations RESTRICT;
DROP VIEW epoleodomia.v_land_uses_summary RESTRICT;
DROP VIEW epoleodomia.v_rasters_by_fek RESTRICT;

-- Accept Polygon/MultiPolygon without rewriting source coordinates or SRID.
-- Retain EPSG:2100 and reject non-polygonal source geometry.

ALTER TABLE epoleodomia.approved_plan_boundaries
    ALTER COLUMN geom TYPE geometry(Geometry,2100),
    ADD CONSTRAINT approved_plan_boundaries_polygonal CHECK
        (GeometryType(geom) IN ('POLYGON','MULTIPOLYGON'));

ALTER TABLE epoleodomia.building_regs_coefficient
    ALTER COLUMN geom TYPE geometry(Geometry,2100),
    ADD CONSTRAINT building_regs_coefficient_polygonal CHECK
        (GeometryType(geom) IN ('POLYGON','MULTIPOLYGON'));

ALTER TABLE epoleodomia.building_regs_coefficient_zones
    ALTER COLUMN geom TYPE geometry(Geometry,2100),
    ADD CONSTRAINT building_regs_coefficient_zones_polygonal CHECK
        (GeometryType(geom) IN ('POLYGON','MULTIPOLYGON'));

ALTER TABLE epoleodomia.building_regs_coverage
    ALTER COLUMN geom TYPE geometry(Geometry,2100),
    ADD CONSTRAINT building_regs_coverage_polygonal CHECK
        (GeometryType(geom) IN ('POLYGON','MULTIPOLYGON'));

ALTER TABLE epoleodomia.building_regs_height
    ALTER COLUMN geom TYPE geometry(Geometry,2100),
    ADD CONSTRAINT building_regs_height_polygonal CHECK
        (GeometryType(geom) IN ('POLYGON','MULTIPOLYGON'));

ALTER TABLE epoleodomia.building_regs_lot
    ALTER COLUMN geom TYPE geometry(Geometry,2100),
    ADD CONSTRAINT building_regs_lot_polygonal CHECK
        (GeometryType(geom) IN ('POLYGON','MULTIPOLYGON'));

ALTER TABLE epoleodomia.building_regs_system
    ALTER COLUMN geom TYPE geometry(Geometry,2100),
    ADD CONSTRAINT building_regs_system_polygonal CHECK
        (GeometryType(geom) IN ('POLYGON','MULTIPOLYGON'));

ALTER TABLE epoleodomia.fek_no_diagrams
    ALTER COLUMN geom TYPE geometry(Geometry,2100),
    ADD CONSTRAINT fek_no_diagrams_polygonal CHECK
        (GeometryType(geom) IN ('POLYGON','MULTIPOLYGON'));

ALTER TABLE epoleodomia.forest_maps
    ALTER COLUMN geom TYPE geometry(Geometry,2100),
    ADD CONSTRAINT forest_maps_polygonal CHECK
        (GeometryType(geom) IN ('POLYGON','MULTIPOLYGON'));

ALTER TABLE epoleodomia.forest_maps_posted_attica_2021
    ALTER COLUMN geom TYPE geometry(Geometry,2100),
    ADD CONSTRAINT forest_maps_posted_attica_2021_polygonal CHECK
        (GeometryType(geom) IN ('POLYGON','MULTIPOLYGON'));

ALTER TABLE epoleodomia.forest_maps_posted_pelop_2022
    ALTER COLUMN geom TYPE geometry(Geometry,2100),
    ADD CONSTRAINT forest_maps_posted_pelop_2022_polygonal CHECK
        (GeometryType(geom) IN ('POLYGON','MULTIPOLYGON'));

ALTER TABLE epoleodomia.land_uses_ers
    ALTER COLUMN geom TYPE geometry(Geometry,2100),
    ADD CONSTRAINT land_uses_ers_polygonal CHECK
        (GeometryType(geom) IN ('POLYGON','MULTIPOLYGON'));

ALTER TABLE epoleodomia.land_uses_gps
    ALTER COLUMN geom TYPE geometry(Geometry,2100),
    ADD CONSTRAINT land_uses_gps_polygonal CHECK
        (GeometryType(geom) IN ('POLYGON','MULTIPOLYGON'));

ALTER TABLE epoleodomia.municipal_communities_2021
    ALTER COLUMN geom TYPE geometry(Geometry,2100),
    ADD CONSTRAINT municipal_communities_2021_polygonal CHECK
        (GeometryType(geom) IN ('POLYGON','MULTIPOLYGON'));

ALTER TABLE epoleodomia.municipal_units_2021
    ALTER COLUMN geom TYPE geometry(Geometry,2100),
    ADD CONSTRAINT municipal_units_2021_polygonal CHECK
        (GeometryType(geom) IN ('POLYGON','MULTIPOLYGON'));

ALTER TABLE epoleodomia.municipalities_2021
    ALTER COLUMN geom TYPE geometry(Geometry,2100),
    ADD CONSTRAINT municipalities_2021_polygonal CHECK
        (GeometryType(geom) IN ('POLYGON','MULTIPOLYGON'));


-- Widen text contracts; keep existing wider limits (e.g. per_cat_eid 500,
-- date_pareklisis 20) instead of narrowing them to the installed limits.
ALTER TABLE epoleodomia.approved_plan_boundaries ALTER COLUMN apof_theme TYPE varchar;
ALTER TABLE epoleodomia.building_regs_coefficient
    ALTER COLUMN sd_tomeas TYPE varchar(255),
    ALTER COLUMN sd_klimakotos TYPE varchar(255);
ALTER TABLE epoleodomia.building_regs_lot ALTER COLUMN oros_type TYPE varchar(255);
ALTER TABLE epoleodomia.forest_maps
    ALTER COLUMN forest_code TYPE varchar,
    ALTER COLUMN nomos TYPE varchar,
    ALTER COLUMN forest_type TYPE varchar(255),
    ALTER COLUMN kathgoral1 TYPE varchar,
    ALTER COLUMN kathgoral2 TYPE varchar;
ALTER TABLE epoleodomia.municipal_units_2021 ALTER COLUMN globalid TYPE varchar;

-- Fail/roll back if old text coverage cannot be interpreted numerically.
-- Do not silently turn unparseable source data into NULL.
ALTER TABLE epoleodomia.building_regs_coverage
    ALTER COLUMN synt_kalypsis TYPE double precision USING synt_kalypsis::double precision;

ALTER TABLE epoleodomia.building_blocks
    ADD COLUMN label_point geometry(Point,2100)
    GENERATED ALWAYS AS (ST_PointOnSurface(geom)) STORED;
CREATE INDEX idx_building_blocks_label_point
    ON epoleodomia.building_blocks USING gist (label_point);


CREATE VIEW epoleodomia.v_building_blocks_regulations AS
SELECT b.id,
    b.objectid,
    b.ot_num,
    b.fek,
    b.fek_file_url,
    b.publ_date,
    b.kall_dhm_name,
    h.max_height_m,
    h.num_orofon,
    h.oror_max_height_comment AS height_comment,
    h.match_pct AS height_match_pct,
    c.synt_kalypsis AS coverage_pct,
    c.remarks AS coverage_remarks,
    c.match_pct AS coverage_match_pct,
    COALESCE(f.sd_timh, z.sd_timh) AS building_coefficient,
    COALESCE(f.sd_tomeas, z.sd_tomeas) AS sd_tomeas,
    COALESCE(f.sd_klimakotos, z.sd_klimakotos) AS sd_klimakotos,
    COALESCE(f.sd_comment, (z.sd_comment)::character varying) AS coefficient_comment,
        CASE
            WHEN (f.sd_timh IS NOT NULL) THEN 'per_block'::text
            WHEN (z.sd_timh IS NOT NULL) THEN 'zone'::text
            ELSE NULL::text
        END AS coefficient_source,
    COALESCE(f.match_pct, z.match_pct) AS coefficient_match_pct,
    lk.elax_embado_m2 AS min_lot_size_m2,
    lk.elax_prosop_m AS min_frontage_m,
    COALESCE(lk.oros_type, lp.oros_type) AS oros_type,
    lp.date_pareklisis,
    lp.remarks AS lot_remarks,
    lk.match_pct AS lot_match_pct,
    s.oik_systima AS building_system,
    s.match_pct AS system_match_pct,
    lu.per_cat_gen AS land_use_general,
    lu.per_cat_eid AS land_use_specific,
    lu.remarks AS land_use_remarks,
    lu.match_pct AS land_use_match_pct,
    b.label_point,
    b.geom
   FROM ((((((((epoleodomia.building_blocks b
     LEFT JOIN LATERAL ( SELECT x.max_height_m,
            x.num_orofon,
            x.oror_max_height_comment,
            round(((((100)::double precision * st_area(st_intersection(x.geom, b.geom))) / NULLIF(st_area(b.geom), (0)::double precision)))::numeric, 1) AS match_pct
           FROM epoleodomia.building_regs_height x
          WHERE (st_intersects(x.geom, b.geom) AND (NOT COALESCE(x.is_deleted, false)))
          ORDER BY (st_area(st_intersection(x.geom, b.geom))) DESC
         LIMIT 1) h ON (true))
     LEFT JOIN LATERAL ( SELECT x.synt_kalypsis,
            x.remarks,
            round(((((100)::double precision * st_area(st_intersection(x.geom, b.geom))) / NULLIF(st_area(b.geom), (0)::double precision)))::numeric, 1) AS match_pct
           FROM epoleodomia.building_regs_coverage x
          WHERE (st_intersects(x.geom, b.geom) AND (NOT COALESCE(x.is_deleted, false)))
          ORDER BY (st_area(st_intersection(x.geom, b.geom))) DESC
         LIMIT 1) c ON (true))
     LEFT JOIN LATERAL ( SELECT x.sd_timh,
            x.sd_tomeas,
            x.sd_klimakotos,
            x.sd_comment,
            round(((((100)::double precision * st_area(st_intersection(x.geom, b.geom))) / NULLIF(st_area(b.geom), (0)::double precision)))::numeric, 1) AS match_pct
           FROM epoleodomia.building_regs_coefficient x
          WHERE (st_intersects(x.geom, b.geom) AND (NOT COALESCE(x.is_deleted, false)))
          ORDER BY (st_area(st_intersection(x.geom, b.geom))) DESC
         LIMIT 1) f ON (true))
     LEFT JOIN LATERAL ( SELECT x.sd_timh,
            x.sd_tomeas,
            x.sd_klimakotos,
            x.sd_comment,
            round(((((100)::double precision * st_area(st_intersection(x.geom, b.geom))) / NULLIF(st_area(b.geom), (0)::double precision)))::numeric, 1) AS match_pct
           FROM epoleodomia.building_regs_coefficient_zones x
          WHERE (st_intersects(x.geom, b.geom) AND (NOT COALESCE(x.is_deleted, false)))
          ORDER BY (st_area(st_intersection(x.geom, b.geom))) DESC
         LIMIT 1) z ON (true))
     LEFT JOIN LATERAL ( SELECT x.elax_embado_m2,
            x.elax_prosop_m,
            x.oros_type,
            round(((((100)::double precision * st_area(st_intersection(x.geom, b.geom))) / NULLIF(st_area(b.geom), (0)::double precision)))::numeric, 1) AS match_pct
           FROM epoleodomia.building_regs_lot x
          WHERE (st_intersects(x.geom, b.geom) AND (NOT COALESCE(x.is_deleted, false)) AND ((x.oros_type)::text = 'ΚΑΤΑ ΚΑΝΟΝΑ'::text))
          ORDER BY (st_area(st_intersection(x.geom, b.geom))) DESC
         LIMIT 1) lk ON (true))
     LEFT JOIN LATERAL ( SELECT x.oros_type,
            x.date_pareklisis,
            x.remarks
           FROM epoleodomia.building_regs_lot x
          WHERE (st_intersects(x.geom, b.geom) AND (NOT COALESCE(x.is_deleted, false)) AND ((x.oros_type)::text = 'ΚΑΤΑ ΠΑΡΕΚΚΛΙΣΗ'::text))
          ORDER BY (st_area(st_intersection(x.geom, b.geom))) DESC
         LIMIT 1) lp ON (true))
     LEFT JOIN LATERAL ( SELECT x.oik_systima,
            round(((((100)::double precision * st_area(st_intersection(x.geom, b.geom))) / NULLIF(st_area(b.geom), (0)::double precision)))::numeric, 1) AS match_pct
           FROM epoleodomia.building_regs_system x
          WHERE (st_intersects(x.geom, b.geom) AND (NOT COALESCE(x.is_deleted, false)))
          ORDER BY (st_area(st_intersection(x.geom, b.geom))) DESC
         LIMIT 1) s ON (true))
     LEFT JOIN LATERAL ( SELECT x.per_cat_gen,
            x.per_cat_eid,
            x.remarks,
            round(((((100)::double precision * st_area(st_intersection(x.geom, b.geom))) / NULLIF(st_area(b.geom), (0)::double precision)))::numeric, 1) AS match_pct
           FROM epoleodomia.land_uses_ers x
          WHERE (st_intersects(x.geom, b.geom) AND (NOT COALESCE(x.is_deleted, false)))
          ORDER BY (st_area(st_intersection(x.geom, b.geom))) DESC
         LIMIT 1) lu ON (true))
  WHERE (NOT COALESCE(b.is_deleted, false));


CREATE VIEW epoleodomia.v_land_uses_summary AS
SELECT COALESCE(gps.id, ers.id) AS id,
    COALESCE(gps.gen_xrhsh_gps, ers.per_cat_gen) AS general_use,
    COALESCE(gps.per_cat_gen, ers.per_cat_gen) AS category_general,
    COALESCE(gps.per_cat_eid, ers.per_cat_eid) AS category_specific,
    COALESCE(gps.remarks, ers.remarks) AS remarks,
    COALESCE(gps.fek, ers.fek) AS fek,
    COALESCE(gps.kall_dhm_name, ers.kall_dhm_name) AS municipality,
    COALESCE(gps.geom, ers.geom) AS geom,
        CASE
            WHEN (gps.id IS NOT NULL) THEN 'GPS'::text
            ELSE 'ERS'::text
        END AS source
   FROM (epoleodomia.land_uses_gps gps
     FULL JOIN epoleodomia.land_uses_ers ers ON ((((gps.fek)::text = (ers.fek)::text) AND st_equals(gps.geom, ers.geom))));


CREATE OR REPLACE VIEW epoleodomia.v_fek_references AS
SELECT DISTINCT fek,
    fek_file_url,
    publ_date,
    apof_eidos,
    title,
    number_,
    sign_date,
    kall_dhm_name
   FROM ( SELECT building_blocks.fek,
            building_blocks.fek_file_url,
            building_blocks.publ_date,
            building_blocks.apof_eidos,
            building_blocks.title,
            building_blocks.number_,
            building_blocks.sign_date,
            building_blocks.kall_dhm_name
           FROM epoleodomia.building_blocks
          WHERE (building_blocks.fek IS NOT NULL)
        UNION
         SELECT planning_lines.fek,
            planning_lines.fek_file_url,
            planning_lines.publ_date,
            planning_lines.apof_eidos,
            planning_lines.title,
            planning_lines.number_,
            planning_lines.sign_date,
            planning_lines.kall_dhm_name
           FROM epoleodomia.planning_lines
          WHERE (planning_lines.fek IS NOT NULL)
        UNION
         SELECT building_lines.fek,
            building_lines.fek_file_url,
            building_lines.publ_date,
            building_lines.apof_eidos,
            building_lines.title,
            building_lines.number_,
            building_lines.sign_date,
            building_lines.kall_dhm_name
           FROM epoleodomia.building_lines
          WHERE (building_lines.fek IS NOT NULL)
        UNION
         SELECT settlement_boundaries.fek,
            settlement_boundaries.fek_file_url,
            settlement_boundaries.publ_date,
            settlement_boundaries.apof_eidos,
            settlement_boundaries.title,
            settlement_boundaries.number_,
            settlement_boundaries.sign_date,
            settlement_boundaries.kall_dhm_name
           FROM epoleodomia.settlement_boundaries
          WHERE (settlement_boundaries.fek IS NOT NULL)
        UNION
         SELECT building_regs_height.fek,
            building_regs_height.fek_file_url,
            building_regs_height.publ_date,
            building_regs_height.apof_eidos,
            building_regs_height.title,
            building_regs_height.number_,
            building_regs_height.sign_date,
            building_regs_height.kall_dhm_name
           FROM epoleodomia.building_regs_height
          WHERE (building_regs_height.fek IS NOT NULL)
        UNION
         SELECT building_regs_coverage.fek,
            building_regs_coverage.fek_file_url,
            building_regs_coverage.publ_date,
            building_regs_coverage.apof_eidos,
            building_regs_coverage.title,
            building_regs_coverage.number_,
            building_regs_coverage.sign_date,
            building_regs_coverage.kall_dhm_name
           FROM epoleodomia.building_regs_coverage
          WHERE (building_regs_coverage.fek IS NOT NULL)
        UNION
         SELECT building_regs_coefficient.fek,
            building_regs_coefficient.fek_file_url,
            building_regs_coefficient.publ_date,
            building_regs_coefficient.apof_eidos,
            building_regs_coefficient.title,
            building_regs_coefficient.number_,
            building_regs_coefficient.sign_date,
            building_regs_coefficient.kall_dhm_name
           FROM epoleodomia.building_regs_coefficient
          WHERE (building_regs_coefficient.fek IS NOT NULL)
        UNION
         SELECT land_uses_gps.fek,
            land_uses_gps.fek_file_url,
            land_uses_gps.publ_date,
            land_uses_gps.apof_eidos,
            land_uses_gps.title,
            land_uses_gps.number_,
            land_uses_gps.sign_date,
            land_uses_gps.kall_dhm_name
           FROM epoleodomia.land_uses_gps
          WHERE (land_uses_gps.fek IS NOT NULL)
        UNION
         SELECT planning_diagrams.fek,
            planning_diagrams.fek_file_url,
            planning_diagrams.publ_date,
            planning_diagrams.apof_eidos,
            planning_diagrams.title,
            planning_diagrams.number_,
            planning_diagrams.sign_date,
            NULL::character varying
           FROM epoleodomia.planning_diagrams
          WHERE (planning_diagrams.fek IS NOT NULL)) combined
  ORDER BY fek;


CREATE VIEW epoleodomia.v_rasters_by_fek AS
SELECT fek,
    count(*) AS total_rasters,
    count(*) FILTER (WHERE ((download_status)::text = 'downloaded'::text)) AS downloaded,
    count(*) FILTER (WHERE ((download_status)::text = 'pending'::text)) AS pending,
    count(*) FILTER (WHERE ((download_status)::text = 'failed'::text)) AS failed,
    sum(file_size_bytes) FILTER (WHERE ((download_status)::text = 'downloaded'::text)) AS total_size_bytes,
    round(((sum(file_size_bytes) FILTER (WHERE ((download_status)::text = 'downloaded'::text)) / 1024.0) / 1024.0), 2) AS total_size_mb
   FROM epoleodomia.raster_catalog
  GROUP BY fek
  ORDER BY fek;


COMMENT ON VIEW epoleodomia.v_building_blocks_regulations IS
    'Regulations by maximum overlap, with coefficient-zone fallback, land use and match percentages.';
COMMENT ON COLUMN epoleodomia.building_blocks.label_point IS
    'Generated interior label point; excluded from source-sync write columns.';

-- Restore effective table/column grants, options, comments and ownership.
-- No CASCADE: an unsupported dependency/privilege operation rolls back all DDL.
DO $restore_views$
DECLARE
    saved record;
    item record;
    option_value text;
    role_sql text;
BEGIN
    FOR saved IN SELECT * FROM pg_temp.epol_v2_old_views LOOP
        FOR item IN
            SELECT DISTINCT a.grantee FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            CROSS JOIN LATERAL aclexplode(COALESCE(c.relacl, acldefault('r',c.relowner))) a
            WHERE n.nspname = 'epoleodomia' AND c.relname = saved.relname
        LOOP
            role_sql := CASE WHEN item.grantee = 0 THEN 'PUBLIC'
                             ELSE quote_ident(pg_get_userbyid(item.grantee)) END;
            EXECUTE format('REVOKE ALL PRIVILEGES ON TABLE epoleodomia.%I FROM %s', saved.relname, role_sql);
        END LOOP;
        FOR item IN SELECT * FROM aclexplode(saved.acl) LOOP
            role_sql := CASE WHEN item.grantee = 0 THEN 'PUBLIC'
                             ELSE quote_ident(pg_get_userbyid(item.grantee)) END;
            EXECUTE format('GRANT %s ON TABLE epoleodomia.%I TO %s%s',
                item.privilege_type, saved.relname, role_sql,
                CASE WHEN item.is_grantable THEN ' WITH GRANT OPTION' ELSE '' END);
        END LOOP;
        IF saved.reloptions IS NOT NULL THEN
            FOREACH option_value IN ARRAY saved.reloptions LOOP
                EXECUTE format('ALTER VIEW epoleodomia.%I SET (%I = %L)', saved.relname,
                    split_part(option_value,'=',1), split_part(option_value,'=',2));
            END LOOP;
        END IF;
        IF saved.description IS NOT NULL THEN
            EXECUTE format('COMMENT ON VIEW epoleodomia.%I IS %L', saved.relname, saved.description);
        END IF;
    END LOOP;
    FOR saved IN SELECT * FROM pg_temp.epol_v2_old_columns LOOP
        FOR item IN SELECT * FROM aclexplode(saved.acl) LOOP
            role_sql := CASE WHEN item.grantee = 0 THEN 'PUBLIC'
                             ELSE quote_ident(pg_get_userbyid(item.grantee)) END;
            EXECUTE format('GRANT %s (%I) ON TABLE epoleodomia.%I TO %s%s',
                item.privilege_type, saved.attname, saved.relname, role_sql,
                CASE WHEN item.is_grantable THEN ' WITH GRANT OPTION' ELSE '' END);
        END LOOP;
        IF saved.description IS NOT NULL THEN
            EXECUTE format('COMMENT ON COLUMN epoleodomia.%I.%I IS %L',
                saved.relname, saved.attname, saved.description);
        END IF;
    END LOOP;
    FOR saved IN SELECT * FROM pg_temp.epol_v2_old_views LOOP
        EXECUTE format('ALTER VIEW epoleodomia.%I OWNER TO %I', saved.relname, saved.owner_name);
    END LOOP;
END;
$restore_views$;
