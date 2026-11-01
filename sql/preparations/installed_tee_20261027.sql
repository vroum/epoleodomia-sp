-- Reviewed installed TEE preparation, snapshot 2026-10-27.
-- Execute only through prepare_legacy_database.py. No transaction control.
-- ONE guarded SQL statement: even a client continuing after errors cannot run
-- later DDL when the controller guard is absent.
DO $epol_prepare$
BEGIN
    IF current_setting('epol.preparation_guard',true) IS DISTINCT FROM 'installed_tee_20261027' THEN
        RAISE EXCEPTION 'Use prepare_legacy_database.py with its source/backup/plan checks';
    END IF;
    EXECUTE $epol_prepare_ddl$
-- Create new objects as the existing schema owner, including that role's
-- default privileges. The controller checks SET ROLE capability before writes.
DO $owner$
DECLARE owner_name name;
BEGIN
    SELECT pg_get_userbyid(nspowner) INTO STRICT owner_name
    FROM pg_namespace WHERE nspname='epoleodomia';
    EXECUTE format('SET LOCAL ROLE %I',owner_name);
END;
$owner$;
CREATE TEMP TABLE epol_v2_old_views ON COMMIT DROP AS
SELECT c.relname, pg_get_userbyid(c.relowner) AS owner_name, c.reloptions,
       COALESCE(c.relacl, acldefault('r', c.relowner)) AS acl,
       obj_description(c.oid, 'pg_class') AS description
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'epoleodomia' AND c.relname IN
    ('v_building_blocks_regulations','v_land_uses_summary','v_fek_references','v_building_blocks_full','v_oroi_domisis_flags');
CREATE TEMP TABLE epol_v2_old_columns ON COMMIT DROP AS
SELECT c.relname, a.attname, a.attacl AS acl,
       col_description(c.oid, a.attnum) AS description
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
WHERE n.nspname = 'epoleodomia' AND c.relname IN
    ('v_building_blocks_regulations','v_land_uses_summary','v_fek_references','v_building_blocks_full','v_oroi_domisis_flags');

;
DROP VIEW epoleodomia."v_building_blocks_full" RESTRICT;
DROP VIEW epoleodomia."v_building_blocks_regulations" RESTRICT;
DROP VIEW epoleodomia."v_fek_references" RESTRICT;
DROP VIEW epoleodomia."v_land_uses_summary" RESTRICT;
DROP VIEW epoleodomia."v_oroi_domisis_flags" RESTRICT;
SET LOCAL search_path TO epoleodomia,public;
CREATE TABLE sync_runs (
    id SERIAL PRIMARY KEY,
    started_at TIMESTAMP NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMP,
    status VARCHAR(20) DEFAULT 'running',
    mode VARCHAR(20),
    tables_synced INTEGER DEFAULT 0,
    records_new INTEGER DEFAULT 0,
    records_updated INTEGER DEFAULT 0,
    records_deleted INTEGER DEFAULT 0,
    error_message TEXT
);;
CREATE TABLE changelog (
    id SERIAL PRIMARY KEY,
    sync_run_id INTEGER REFERENCES sync_runs(id),
    changed_at TIMESTAMP NOT NULL DEFAULT NOW(),
    table_name VARCHAR(100) NOT NULL,
    objectid INTEGER NOT NULL,
    record_id INTEGER,
    change_type VARCHAR(10) NOT NULL,
    changed_fields TEXT[],
    old_values JSONB,
    new_values JSONB,
    geometry_changed BOOLEAN DEFAULT FALSE,
    old_geom_wkt TEXT,
    new_geom_wkt TEXT,
    old_fek TEXT,
    new_fek TEXT
);;
CREATE TABLE epoleodomia.land_use_codes (
    code VARCHAR(10) PRIMARY KEY,
    description_el VARCHAR(255) NOT NULL,
    description_en VARCHAR(255),
    category VARCHAR(50),
    parent_code VARCHAR(10)
);

-- Insert common land use codes from ΦΕΚ 27Α/1980
INSERT INTO epoleodomia.land_use_codes (code, description_el, category, parent_code) VALUES
-- Main categories (1-digit or 2-digit codes)
('1', 'Κατοικία', 'ΚΑΤΟΙΚΙΑ', NULL),
('2', 'Κατοικία', 'ΚΑΤΟΙΚΙΑ', NULL),
('21', 'Αμιγής Κατοικία', 'ΚΑΤΟΙΚΙΑ', '2'),
('22', 'Γενική Κατοικία', 'ΚΑΤΟΙΚΙΑ', '2'),
('23', 'Πολεοδομικό Κέντρο', 'ΚΕΝΤΡΟ', '2'),
('24', 'Τουριστική Ζώνη', 'ΤΟΥΡΙΣΜΟΣ', '2'),

-- Specific codes (3-digit)
('211', 'Αμιγής Κατοικία - Μονοκατοικία', 'ΚΑΤΟΙΚΙΑ', '21'),
('212', 'Αμιγής Κατοικία - Πολυκατοικία', 'ΚΑΤΟΙΚΙΑ', '21'),
('221', 'Γενική Κατοικία - Μονοκατοικία', 'ΚΑΤΟΙΚΙΑ', '22'),
('222', 'Γενική Κατοικία - Πολυκατοικία', 'ΚΑΤΟΙΚΙΑ', '22'),

-- Other categories
('3', 'Εμπόριο', 'ΕΜΠΟΡΙΟ', NULL),
('4', 'Βιομηχανία - Βιοτεχνία', 'ΒΙΟΜΗΧΑΝΙΑ', NULL),
('5', 'Αναψυχή - Πολιτισμός', 'ΑΝΑΨΥΧΗ', NULL),
('6', 'Κοινωφελείς Εξυπηρετήσεις', 'ΚΟΙΝΩΦΕΛΗ', NULL),
('7', 'Ελεύθεροι Χώροι - Πράσινο', 'ΠΡΑΣΙΝΟ', NULL);

-- Create index
CREATE INDEX idx_land_use_codes_category ON epoleodomia.land_use_codes(category);

-- Function to translate code list to description
CREATE FUNCTION epoleodomia.translate_land_use_codes(codes_str VARCHAR)
RETURNS VARCHAR AS $$
DECLARE
    result VARCHAR := '';
    current_code VARCHAR;
    desc_el VARCHAR;
    codes_array VARCHAR[];
BEGIN
    IF codes_str IS NULL OR codes_str = '' THEN
        RETURN NULL;
    END IF;

    -- Split by semicolon
    codes_array := string_to_array(codes_str, ';');

    -- Get the main category from first 2-digit code
    FOREACH current_code IN ARRAY codes_array LOOP
        current_code := trim(current_code);
        IF length(current_code) = 2 THEN
            SELECT luc.description_el INTO desc_el
            FROM epoleodomia.land_use_codes luc
            WHERE luc.code = current_code;

            IF desc_el IS NOT NULL THEN
                RETURN desc_el;
            END IF;
        END IF;
    END LOOP;

    -- If no 2-digit code found, try first code
    current_code := trim(codes_array[1]);
    SELECT luc.description_el INTO desc_el
    FROM epoleodomia.land_use_codes luc
    WHERE luc.code = current_code;

    RETURN COALESCE(desc_el, codes_str);
END;
$$ LANGUAGE plpgsql;

;
ALTER TABLE epoleodomia."ab_zones_attica" ADD COLUMN "created_at" timestamp without time zone DEFAULT NOW();
ALTER TABLE epoleodomia."ab_zones_attica" ADD COLUMN "deleted_at" timestamp without time zone;
ALTER TABLE epoleodomia."ab_zones_attica" ADD COLUMN "is_deleted" boolean DEFAULT FALSE;
ALTER TABLE epoleodomia."ab_zones_attica" ADD COLUMN "updated_at" timestamp without time zone;
ALTER TABLE epoleodomia."archaeological_sites_lines" ADD COLUMN "created_at" timestamp without time zone DEFAULT NOW();
ALTER TABLE epoleodomia."archaeological_sites_lines" ADD COLUMN "deleted_at" timestamp without time zone;
ALTER TABLE epoleodomia."archaeological_sites_lines" ADD COLUMN "is_deleted" boolean DEFAULT FALSE;
ALTER TABLE epoleodomia."archaeological_sites_lines" ADD COLUMN "updated_at" timestamp without time zone;
ALTER TABLE epoleodomia."archaeological_sites_points" ADD COLUMN "created_at" timestamp without time zone DEFAULT NOW();
ALTER TABLE epoleodomia."archaeological_sites_points" ADD COLUMN "deleted_at" timestamp without time zone;
ALTER TABLE epoleodomia."archaeological_sites_points" ADD COLUMN "is_deleted" boolean DEFAULT FALSE;
ALTER TABLE epoleodomia."archaeological_sites_points" ADD COLUMN "updated_at" timestamp without time zone;
ALTER TABLE epoleodomia."archaeological_zones_pl" ADD COLUMN "created_at" timestamp without time zone DEFAULT NOW();
ALTER TABLE epoleodomia."archaeological_zones_pl" ADD COLUMN "deleted_at" timestamp without time zone;
ALTER TABLE epoleodomia."archaeological_zones_pl" ADD COLUMN "is_deleted" boolean DEFAULT FALSE;
ALTER TABLE epoleodomia."archaeological_zones_pl" ADD COLUMN "updated_at" timestamp without time zone;
ALTER TABLE epoleodomia."expropriation_zones" ADD COLUMN "created_at" timestamp without time zone DEFAULT NOW();
ALTER TABLE epoleodomia."expropriation_zones" ADD COLUMN "deleted_at" timestamp without time zone;
ALTER TABLE epoleodomia."expropriation_zones" ADD COLUMN "is_deleted" boolean DEFAULT FALSE;
ALTER TABLE epoleodomia."expropriation_zones" ADD COLUMN "updated_at" timestamp without time zone;
ALTER TABLE epoleodomia."historic_sites_lines" ADD COLUMN "created_at" timestamp without time zone DEFAULT NOW();
ALTER TABLE epoleodomia."historic_sites_lines" ADD COLUMN "deleted_at" timestamp without time zone;
ALTER TABLE epoleodomia."historic_sites_lines" ADD COLUMN "is_deleted" boolean DEFAULT FALSE;
ALTER TABLE epoleodomia."historic_sites_lines" ADD COLUMN "updated_at" timestamp without time zone;
ALTER TABLE epoleodomia."historic_sites_points" ADD COLUMN "created_at" timestamp without time zone DEFAULT NOW();
ALTER TABLE epoleodomia."historic_sites_points" ADD COLUMN "deleted_at" timestamp without time zone;
ALTER TABLE epoleodomia."historic_sites_points" ADD COLUMN "is_deleted" boolean DEFAULT FALSE;
ALTER TABLE epoleodomia."historic_sites_points" ADD COLUMN "updated_at" timestamp without time zone;
ALTER TABLE epoleodomia."historic_sites_polygons" ADD COLUMN "created_at" timestamp without time zone DEFAULT NOW();
ALTER TABLE epoleodomia."historic_sites_polygons" ADD COLUMN "deleted_at" timestamp without time zone;
ALTER TABLE epoleodomia."historic_sites_polygons" ADD COLUMN "is_deleted" boolean DEFAULT FALSE;
ALTER TABLE epoleodomia."historic_sites_polygons" ADD COLUMN "updated_at" timestamp without time zone;
ALTER TABLE epoleodomia."land_uses_gps" ADD COLUMN "created_at" timestamp without time zone DEFAULT NOW();
ALTER TABLE epoleodomia."land_uses_gps" ADD COLUMN "deleted_at" timestamp without time zone;
ALTER TABLE epoleodomia."land_uses_gps" ADD COLUMN "is_deleted" boolean DEFAULT FALSE;
ALTER TABLE epoleodomia."land_uses_gps" ADD COLUMN "updated_at" timestamp without time zone;
ALTER TABLE epoleodomia."monuments_lines" ADD COLUMN "created_at" timestamp without time zone DEFAULT NOW();
ALTER TABLE epoleodomia."monuments_lines" ADD COLUMN "deleted_at" timestamp without time zone;
ALTER TABLE epoleodomia."monuments_lines" ADD COLUMN "is_deleted" boolean DEFAULT FALSE;
ALTER TABLE epoleodomia."monuments_lines" ADD COLUMN "updated_at" timestamp without time zone;
ALTER TABLE epoleodomia."natura_2000" ADD COLUMN "created_at" timestamp without time zone DEFAULT NOW();
ALTER TABLE epoleodomia."natura_2000" ADD COLUMN "deleted_at" timestamp without time zone;
ALTER TABLE epoleodomia."natura_2000" ADD COLUMN "is_deleted" boolean DEFAULT FALSE;
ALTER TABLE epoleodomia."natura_2000" ADD COLUMN "updated_at" timestamp without time zone;
ALTER TABLE epoleodomia."natural_landscapes_points" ADD COLUMN "created_at" timestamp without time zone DEFAULT NOW();
ALTER TABLE epoleodomia."natural_landscapes_points" ADD COLUMN "deleted_at" timestamp without time zone;
ALTER TABLE epoleodomia."natural_landscapes_points" ADD COLUMN "is_deleted" boolean DEFAULT FALSE;
ALTER TABLE epoleodomia."natural_landscapes_points" ADD COLUMN "updated_at" timestamp without time zone;
ALTER TABLE epoleodomia."other_planning_zones" ADD COLUMN "created_at" timestamp without time zone DEFAULT NOW();
ALTER TABLE epoleodomia."other_planning_zones" ADD COLUMN "deleted_at" timestamp without time zone;
ALTER TABLE epoleodomia."other_planning_zones" ADD COLUMN "is_deleted" boolean DEFAULT FALSE;
ALTER TABLE epoleodomia."other_planning_zones" ADD COLUMN "updated_at" timestamp without time zone;
ALTER TABLE epoleodomia."outside_plan_areas" ADD COLUMN "created_at" timestamp without time zone DEFAULT NOW();
ALTER TABLE epoleodomia."outside_plan_areas" ADD COLUMN "deleted_at" timestamp without time zone;
ALTER TABLE epoleodomia."outside_plan_areas" ADD COLUMN "is_deleted" boolean DEFAULT FALSE;
ALTER TABLE epoleodomia."outside_plan_areas" ADD COLUMN "updated_at" timestamp without time zone;
ALTER TABLE epoleodomia."pd_protection_zones" ADD COLUMN "created_at" timestamp without time zone DEFAULT NOW();
ALTER TABLE epoleodomia."pd_protection_zones" ADD COLUMN "deleted_at" timestamp without time zone;
ALTER TABLE epoleodomia."pd_protection_zones" ADD COLUMN "is_deleted" boolean DEFAULT FALSE;
ALTER TABLE epoleodomia."pd_protection_zones" ADD COLUMN "updated_at" timestamp without time zone;
ALTER TABLE epoleodomia."protection_zones_lines" ADD COLUMN "created_at" timestamp without time zone DEFAULT NOW();
ALTER TABLE epoleodomia."protection_zones_lines" ADD COLUMN "deleted_at" timestamp without time zone;
ALTER TABLE epoleodomia."protection_zones_lines" ADD COLUMN "is_deleted" boolean DEFAULT FALSE;
ALTER TABLE epoleodomia."protection_zones_lines" ADD COLUMN "updated_at" timestamp without time zone;
ALTER TABLE epoleodomia."protection_zones_points" ADD COLUMN "created_at" timestamp without time zone DEFAULT NOW();
ALTER TABLE epoleodomia."protection_zones_points" ADD COLUMN "deleted_at" timestamp without time zone;
ALTER TABLE epoleodomia."protection_zones_points" ADD COLUMN "is_deleted" boolean DEFAULT FALSE;
ALTER TABLE epoleodomia."protection_zones_points" ADD COLUMN "updated_at" timestamp without time zone;
ALTER TABLE epoleodomia."settlement_boundaries" ADD COLUMN "created_at" timestamp without time zone DEFAULT NOW();
ALTER TABLE epoleodomia."settlement_boundaries" ADD COLUMN "deleted_at" timestamp without time zone;
ALTER TABLE epoleodomia."settlement_boundaries" ADD COLUMN "is_deleted" boolean DEFAULT FALSE;
ALTER TABLE epoleodomia."settlement_boundaries" ADD COLUMN "updated_at" timestamp without time zone;
ALTER TABLE epoleodomia."streams" ADD COLUMN "created_at" timestamp without time zone DEFAULT NOW();
ALTER TABLE epoleodomia."streams" ADD COLUMN "deleted_at" timestamp without time zone;
ALTER TABLE epoleodomia."streams" ADD COLUMN "is_deleted" boolean DEFAULT FALSE;
ALTER TABLE epoleodomia."streams" ADD COLUMN "updated_at" timestamp without time zone;
ALTER TABLE epoleodomia."streams_environmental" ADD COLUMN "created_at" timestamp without time zone DEFAULT NOW();
ALTER TABLE epoleodomia."streams_environmental" ADD COLUMN "deleted_at" timestamp without time zone;
ALTER TABLE epoleodomia."streams_environmental" ADD COLUMN "is_deleted" boolean DEFAULT FALSE;
ALTER TABLE epoleodomia."streams_environmental" ADD COLUMN "updated_at" timestamp without time zone;
ALTER TABLE epoleodomia."urban_units" ADD COLUMN "created_at" timestamp without time zone DEFAULT NOW();
ALTER TABLE epoleodomia."urban_units" ADD COLUMN "deleted_at" timestamp without time zone;
ALTER TABLE epoleodomia."urban_units" ADD COLUMN "is_deleted" boolean DEFAULT FALSE;
ALTER TABLE epoleodomia."urban_units" ADD COLUMN "updated_at" timestamp without time zone;
ALTER TABLE epoleodomia."zoe_zones" ADD COLUMN "created_at" timestamp without time zone DEFAULT NOW();
ALTER TABLE epoleodomia."zoe_zones" ADD COLUMN "deleted_at" timestamp without time zone;
ALTER TABLE epoleodomia."zoe_zones" ADD COLUMN "is_deleted" boolean DEFAULT FALSE;
ALTER TABLE epoleodomia."zoe_zones" ADD COLUMN "updated_at" timestamp without time zone;
ALTER TABLE epoleodomia."building_regs_coverage" ALTER COLUMN "max_embado_m2" TYPE double precision;
ALTER TABLE epoleodomia."building_regs_lot" ALTER COLUMN "date_pareklisis" TYPE varchar(20);
ALTER TABLE epoleodomia."land_uses_ers" ALTER COLUMN "per_cat_eid" TYPE varchar(500);
ALTER TABLE epoleodomia."land_uses_gps" ALTER COLUMN "per_cat_eid" TYPE varchar(500);
ALTER TABLE epoleodomia."ab_zones_attica" ADD CONSTRAINT "ab_zones_attica_objectid_key" UNIQUE (objectid);
ALTER TABLE epoleodomia."addresses" ADD CONSTRAINT "addresses_objectid_key" UNIQUE (objectid);
ALTER TABLE epoleodomia."approved_plan_boundaries" ADD CONSTRAINT "approved_plan_boundaries_polygonal" CHECK ((geometrytype(geom) = ANY (ARRAY['POLYGON'::text, 'MULTIPOLYGON'::text])));
ALTER TABLE epoleodomia."approved_plan_boundaries" ADD CONSTRAINT "approved_plan_boundaries_objectid_key" UNIQUE (objectid);
ALTER TABLE epoleodomia."archaeological_sites_lines" ADD CONSTRAINT "archaeological_sites_lines_objectid_key" UNIQUE (objectid);
ALTER TABLE epoleodomia."archaeological_sites_points" ADD CONSTRAINT "archaeological_sites_points_objectid_key" UNIQUE (objectid);
ALTER TABLE epoleodomia."archaeological_sites_polygons" ADD CONSTRAINT "archaeological_sites_polygons_objectid_key" UNIQUE (objectid);
ALTER TABLE epoleodomia."archaeological_zones_pl" ADD CONSTRAINT "archaeological_zones_pl_objectid_key" UNIQUE (objectid);
ALTER TABLE epoleodomia."block_vertices" ADD CONSTRAINT "block_vertices_objectid_key" UNIQUE (objectid);
ALTER TABLE epoleodomia."building_blocks" ADD CONSTRAINT "building_blocks_objectid_key" UNIQUE (objectid);
ALTER TABLE epoleodomia."building_lines" ADD CONSTRAINT "building_lines_objectid_key" UNIQUE (objectid);
ALTER TABLE epoleodomia."building_regs_coefficient" ADD CONSTRAINT "building_regs_coefficient_polygonal" CHECK ((geometrytype(geom) = ANY (ARRAY['POLYGON'::text, 'MULTIPOLYGON'::text])));
ALTER TABLE epoleodomia."building_regs_coefficient" ADD CONSTRAINT "building_regs_coefficient_objectid_key" UNIQUE (objectid);
ALTER TABLE epoleodomia."building_regs_coefficient_zones" ADD CONSTRAINT "building_regs_coefficient_zones_polygonal" CHECK ((geometrytype(geom) = ANY (ARRAY['POLYGON'::text, 'MULTIPOLYGON'::text])));
ALTER TABLE epoleodomia."building_regs_coefficient_zones" ADD CONSTRAINT "building_regs_coefficient_zones_objectid_key" UNIQUE (objectid);
ALTER TABLE epoleodomia."building_regs_coverage" ADD CONSTRAINT "building_regs_coverage_polygonal" CHECK ((geometrytype(geom) = ANY (ARRAY['POLYGON'::text, 'MULTIPOLYGON'::text])));
ALTER TABLE epoleodomia."building_regs_coverage" ADD CONSTRAINT "building_regs_coverage_objectid_key" UNIQUE (objectid);
ALTER TABLE epoleodomia."building_regs_height" ADD CONSTRAINT "building_regs_height_polygonal" CHECK ((geometrytype(geom) = ANY (ARRAY['POLYGON'::text, 'MULTIPOLYGON'::text])));
ALTER TABLE epoleodomia."building_regs_height" ADD CONSTRAINT "building_regs_height_objectid_key" UNIQUE (objectid);
ALTER TABLE epoleodomia."building_regs_lot" ADD CONSTRAINT "building_regs_lot_polygonal" CHECK ((geometrytype(geom) = ANY (ARRAY['POLYGON'::text, 'MULTIPOLYGON'::text])));
ALTER TABLE epoleodomia."building_regs_system" ADD CONSTRAINT "building_regs_system_polygonal" CHECK ((geometrytype(geom) = ANY (ARRAY['POLYGON'::text, 'MULTIPOLYGON'::text])));
ALTER TABLE epoleodomia."building_regs_system" ADD CONSTRAINT "building_regs_system_objectid_key" UNIQUE (objectid);
ALTER TABLE epoleodomia."census_blocks_2021" ADD CONSTRAINT "census_blocks_2021_objectid_key" UNIQUE (objectid);
ALTER TABLE epoleodomia."expropriation_zones" ADD CONSTRAINT "expropriation_zones_objectid_key" UNIQUE (objectid);
ALTER TABLE epoleodomia."fek_no_diagrams" ADD CONSTRAINT "fek_no_diagrams_polygonal" CHECK ((geometrytype(geom) = ANY (ARRAY['POLYGON'::text, 'MULTIPOLYGON'::text])));
ALTER TABLE epoleodomia."fek_no_diagrams" ADD CONSTRAINT "fek_no_diagrams_objectid_key" UNIQUE (objectid);
ALTER TABLE epoleodomia."forest_maps" ADD CONSTRAINT "forest_maps_polygonal" CHECK ((geometrytype(geom) = ANY (ARRAY['POLYGON'::text, 'MULTIPOLYGON'::text])));
ALTER TABLE epoleodomia."forest_maps" ADD CONSTRAINT "forest_maps_objectid_key" UNIQUE (objectid);
ALTER TABLE epoleodomia."forest_maps_posted_attica_2021" ADD CONSTRAINT "forest_maps_posted_attica_2021_polygonal" CHECK ((geometrytype(geom) = ANY (ARRAY['POLYGON'::text, 'MULTIPOLYGON'::text])));
ALTER TABLE epoleodomia."forest_maps_posted_attica_2021" ADD CONSTRAINT "forest_maps_posted_attica_2021_objectid_key" UNIQUE (objectid);
ALTER TABLE epoleodomia."forest_maps_posted_pelop_2022" ADD CONSTRAINT "forest_maps_posted_pelop_2022_polygonal" CHECK ((geometrytype(geom) = ANY (ARRAY['POLYGON'::text, 'MULTIPOLYGON'::text])));
ALTER TABLE epoleodomia."forest_maps_posted_pelop_2022" ADD CONSTRAINT "forest_maps_posted_pelop_2022_objectid_key" UNIQUE (objectid);
ALTER TABLE epoleodomia."historic_sites_lines" ADD CONSTRAINT "historic_sites_lines_objectid_key" UNIQUE (objectid);
ALTER TABLE epoleodomia."historic_sites_points" ADD CONSTRAINT "historic_sites_points_objectid_key" UNIQUE (objectid);
ALTER TABLE epoleodomia."historic_sites_polygons" ADD CONSTRAINT "historic_sites_polygons_objectid_key" UNIQUE (objectid);
ALTER TABLE epoleodomia."land_uses_ers" ADD CONSTRAINT "land_uses_ers_polygonal" CHECK ((geometrytype(geom) = ANY (ARRAY['POLYGON'::text, 'MULTIPOLYGON'::text])));
ALTER TABLE epoleodomia."land_uses_ers" ADD CONSTRAINT "land_uses_ers_objectid_key" UNIQUE (objectid);
ALTER TABLE epoleodomia."land_uses_gps" ADD CONSTRAINT "land_uses_gps_polygonal" CHECK ((geometrytype(geom) = ANY (ARRAY['POLYGON'::text, 'MULTIPOLYGON'::text])));
ALTER TABLE epoleodomia."land_uses_gps" ADD CONSTRAINT "land_uses_gps_objectid_key" UNIQUE (objectid);
ALTER TABLE epoleodomia."monuments_lines" ADD CONSTRAINT "monuments_lines_objectid_key" UNIQUE (objectid);
ALTER TABLE epoleodomia."monuments_points" ADD CONSTRAINT "monuments_points_objectid_key" UNIQUE (objectid);
ALTER TABLE epoleodomia."monuments_polygons" ADD CONSTRAINT "monuments_polygons_objectid_key" UNIQUE (objectid);
ALTER TABLE epoleodomia."municipal_communities_2021" ADD CONSTRAINT "municipal_communities_2021_polygonal" CHECK ((geometrytype(geom) = ANY (ARRAY['POLYGON'::text, 'MULTIPOLYGON'::text])));
ALTER TABLE epoleodomia."municipal_communities_2021" ADD CONSTRAINT "municipal_communities_2021_objectid_key" UNIQUE (objectid);
ALTER TABLE epoleodomia."municipal_units_2021" ADD CONSTRAINT "municipal_units_2021_polygonal" CHECK ((geometrytype(geom) = ANY (ARRAY['POLYGON'::text, 'MULTIPOLYGON'::text])));
ALTER TABLE epoleodomia."municipal_units_2021" ADD CONSTRAINT "municipal_units_2021_objectid_key" UNIQUE (objectid);
ALTER TABLE epoleodomia."municipalities_2021" ADD CONSTRAINT "municipalities_2021_polygonal" CHECK ((geometrytype(geom) = ANY (ARRAY['POLYGON'::text, 'MULTIPOLYGON'::text])));
ALTER TABLE epoleodomia."municipalities_2021" ADD CONSTRAINT "municipalities_2021_objectid_key" UNIQUE (objectid);
ALTER TABLE epoleodomia."natura_2000" ADD CONSTRAINT "natura_2000_objectid_key" UNIQUE (objectid);
ALTER TABLE epoleodomia."natural_landscapes_points" ADD CONSTRAINT "natural_landscapes_points_objectid_key" UNIQUE (objectid);
ALTER TABLE epoleodomia."natural_landscapes_polygons" ADD CONSTRAINT "natural_landscapes_polygons_objectid_key" UNIQUE (objectid);
ALTER TABLE epoleodomia."other_planning_lines" ADD CONSTRAINT "other_planning_lines_objectid_key" UNIQUE (objectid);
ALTER TABLE epoleodomia."other_planning_zones" ADD CONSTRAINT "other_planning_zones_objectid_key" UNIQUE (objectid);
ALTER TABLE epoleodomia."outside_plan_areas" ADD CONSTRAINT "outside_plan_areas_objectid_key" UNIQUE (objectid);
ALTER TABLE epoleodomia."pd_protection_zones" ADD CONSTRAINT "pd_protection_zones_objectid_key" UNIQUE (objectid);
ALTER TABLE epoleodomia."pedestrian_zones" ADD CONSTRAINT "pedestrian_zones_objectid_key" UNIQUE (objectid);
ALTER TABLE epoleodomia."planning_diagrams" ADD CONSTRAINT "planning_diagrams_objectid_key" UNIQUE (objectid);
ALTER TABLE epoleodomia."planning_lines" ADD CONSTRAINT "planning_lines_objectid_key" UNIQUE (objectid);
ALTER TABLE epoleodomia."protected_buildings" ADD CONSTRAINT "protected_buildings_objectid_key" UNIQUE (objectid);
ALTER TABLE epoleodomia."protection_zones_lines" ADD CONSTRAINT "protection_zones_lines_objectid_key" UNIQUE (objectid);
ALTER TABLE epoleodomia."protection_zones_points" ADD CONSTRAINT "protection_zones_points_objectid_key" UNIQUE (objectid);
ALTER TABLE epoleodomia."protection_zones_polygons" ADD CONSTRAINT "protection_zones_polygons_objectid_key" UNIQUE (objectid);
ALTER TABLE epoleodomia."public_spaces" ADD CONSTRAINT "public_spaces_objectid_key" UNIQUE (objectid);
ALTER TABLE epoleodomia."settlement_boundaries" ADD CONSTRAINT "settlement_boundaries_objectid_key" UNIQUE (objectid);
ALTER TABLE epoleodomia."settlements_2021" ADD CONSTRAINT "settlements_2021_objectid_key" UNIQUE (objectid);
ALTER TABLE epoleodomia."shorelines" ADD CONSTRAINT "shorelines_objectid_key" UNIQUE (objectid);
ALTER TABLE epoleodomia."streams" ADD CONSTRAINT "streams_objectid_key" UNIQUE (objectid);
ALTER TABLE epoleodomia."streams_environmental" ADD CONSTRAINT "streams_environmental_objectid_key" UNIQUE (objectid);
ALTER TABLE epoleodomia."urban_units" ADD CONSTRAINT "urban_units_objectid_key" UNIQUE (objectid);
ALTER TABLE epoleodomia."zoe_zones" ADD CONSTRAINT "zoe_zones_objectid_key" UNIQUE (objectid);
CREATE VIEW epoleodomia."v_oroi_domisis_flags" AS  WITH b AS (
         SELECT building_blocks.id,
            building_blocks.ot_num,
            building_blocks.kall_dhm_name,
            building_blocks.fek,
            building_blocks.geom,
            st_area(building_blocks.geom) AS a,
            ((regexp_match((building_blocks.fek)::text, '/(\d{4})\s*$'::text))[1])::integer AS etos
           FROM epoleodomia.building_blocks
          WHERE (NOT COALESCE(building_blocks.is_deleted, false))
        ), z AS (
         SELECT b_1.id,
            ( SELECT round(((((100)::double precision * st_area(st_intersection(x.geom, b_1.geom))) / NULLIF(b_1.a, (0)::double precision)))::numeric, 1) AS round
                   FROM epoleodomia.building_regs_height x
                  WHERE (st_intersects(x.geom, b_1.geom) AND (NOT COALESCE(x.is_deleted, false)))
                  ORDER BY (st_area(st_intersection(x.geom, b_1.geom))) DESC
                 LIMIT 1) AS h_pct,
            ( SELECT round(((((100)::double precision * st_area(st_intersection(x.geom, b_1.geom))) / NULLIF(b_1.a, (0)::double precision)))::numeric, 1) AS round
                   FROM epoleodomia.building_regs_coefficient x
                  WHERE (st_intersects(x.geom, b_1.geom) AND (NOT COALESCE(x.is_deleted, false)))
                  ORDER BY (st_area(st_intersection(x.geom, b_1.geom))) DESC
                 LIMIT 1) AS sd_pct,
            ( SELECT round(((((100)::double precision * st_area(st_intersection(x.geom, b_1.geom))) / NULLIF(b_1.a, (0)::double precision)))::numeric, 1) AS round
                   FROM epoleodomia.building_regs_coverage x
                  WHERE (st_intersects(x.geom, b_1.geom) AND (NOT COALESCE(x.is_deleted, false)))
                  ORDER BY (st_area(st_intersection(x.geom, b_1.geom))) DESC
                 LIMIT 1) AS c_pct
           FROM b b_1
        ), praxeis AS (
         SELECT b_1.id,
            string_agg(((((((p.fek)::text || ' — '::text) || (COALESCE(p.apof_theme, ''::character varying))::text) || ' ('::text) || round(((((100)::double precision * st_area(st_intersection(p.geom, b_1.geom))) / b_1.a))::numeric, 0)) || '%)'::text), '
'::text ORDER BY (p.publ_date)::date) AS praxeis_info,
            string_agg(DISTINCT (p.fek_file_url)::text, '
'::text) AS fek_urls,
            max((p.publ_date)::date) AS teleftaia_praxi
           FROM (b b_1
             JOIN epoleodomia.approved_plan_boundaries p ON (((NOT COALESCE(p.is_deleted, false)) AND (st_area(p.geom) < (100000)::double precision) AND (EXTRACT(year FROM (p.publ_date)::date) > (b_1.etos)::numeric) AND st_intersects(p.geom, b_1.geom) AND (st_area(st_intersection(p.geom, b_1.geom)) > GREATEST(((0.10)::double precision * b_1.a), (250)::double precision)))))
          GROUP BY b_1.id
        )
 SELECT b.id,
    b.ot_num,
    b.kall_dhm_name AS dimos,
    b.fek AS fek_ot,
    round((b.a)::numeric, 1) AS emvadon_m2,
    pr.praxeis_info,
    pr.fek_urls,
    pr.teleftaia_praxi,
    LEAST(z.h_pct, z.sd_pct, z.c_pct) AS min_pct,
    array_remove(ARRAY[
        CASE
            WHEN (pr.id IS NOT NULL) THEN 'Σ1 νεότερη πράξη επί του ΟΤ'::text
            ELSE NULL::text
        END,
        CASE
            WHEN ((b.ot_num)::text ~ '[-/,]'::text) THEN 'Σ2 ένωση ΟΤ'::text
            ELSE NULL::text
        END,
        CASE
            WHEN (LEAST(COALESCE(z.h_pct, (100)::numeric), COALESCE(z.sd_pct, (100)::numeric), COALESCE(z.c_pct, (100)::numeric)) < (99)::numeric) THEN 'Σ3 πατά σε δύο ζώνες'::text
            ELSE NULL::text
        END,
        CASE
            WHEN (NOT st_intersects(st_centroid(b.geom), b.geom)) THEN 'Σ4 κεντροειδές εκτός'::text
            ELSE NULL::text
        END,
        CASE
            WHEN ((z.h_pct IS NULL) OR (z.sd_pct IS NULL) OR (z.c_pct IS NULL)) THEN 'Σ5 λείπουν όροι'::text
            ELSE NULL::text
        END], NULL::text) AS flags,
        CASE
            WHEN ((pr.id IS NOT NULL) OR ((b.ot_num)::text ~ '[-/,]'::text)) THEN 'ΑΝΟΙΞΕ ΤΟ ΦΕΚ'::text
            WHEN ((LEAST(COALESCE(z.h_pct, (100)::numeric), COALESCE(z.sd_pct, (100)::numeric), COALESCE(z.c_pct, (100)::numeric)) < (99)::numeric) OR (z.h_pct IS NULL) OR (z.sd_pct IS NULL) OR (z.c_pct IS NULL)) THEN 'ΕΛΕΓΞΕ'::text
            WHEN (NOT st_intersects(st_centroid(b.geom), b.geom)) THEN 'ΤΕΧΝΙΚΟ'::text
            ELSE NULL::text
        END AS epipedo,
    b.geom
   FROM ((b
     JOIN z ON ((z.id = b.id)))
     LEFT JOIN praxeis pr ON ((pr.id = b.id)))
  WHERE ((pr.id IS NOT NULL) OR ((b.ot_num)::text ~ '[-/,]'::text) OR (LEAST(COALESCE(z.h_pct, (100)::numeric), COALESCE(z.sd_pct, (100)::numeric), COALESCE(z.c_pct, (100)::numeric)) < (99)::numeric) OR (NOT st_intersects(st_centroid(b.geom), b.geom)) OR (z.h_pct IS NULL) OR (z.sd_pct IS NULL) OR (z.c_pct IS NULL));;
CREATE VIEW epoleodomia."v_land_uses_summary" AS  SELECT COALESCE(gps.id, ers.id) AS id,
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
     FULL JOIN epoleodomia.land_uses_ers ers ON ((((gps.fek)::text = (ers.fek)::text) AND st_equals(gps.geom, ers.geom))));;
CREATE VIEW epoleodomia."v_fek_references" AS  SELECT DISTINCT fek,
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
            NULL::character varying AS "varchar"
           FROM epoleodomia.planning_diagrams
          WHERE (planning_diagrams.fek IS NOT NULL)) combined
  ORDER BY fek;;
CREATE VIEW epoleodomia."v_building_blocks_regulations" AS  SELECT b.id,
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
  WHERE (NOT COALESCE(b.is_deleted, false));;
CREATE VIEW epoleodomia."v_building_blocks_full" AS  SELECT b.id,
    b.objectid,
    b.ot_num,
    b.fek,
    b.fek_file_url,
    b.publ_date,
    b.kall_dhm_name,
    h.max_height_m,
    h.num_orofon,
    h.oror_max_height_comment AS height_comment,
    c.synt_kalypsis AS coverage_pct,
    f.sd_timh AS building_coefficient,
    f.sd_comment AS coefficient_comment,
    l.elax_embado_m2 AS min_lot_size_m2,
    l.elax_prosop_m AS min_frontage_m,
    s.oik_systima AS building_system,
    b.geom,
    b.fetched_at
   FROM (((((epoleodomia.building_blocks b
     LEFT JOIN epoleodomia.building_regs_height h ON (st_intersects(st_centroid(b.geom), h.geom)))
     LEFT JOIN epoleodomia.building_regs_coverage c ON (st_intersects(st_centroid(b.geom), c.geom)))
     LEFT JOIN epoleodomia.building_regs_coefficient f ON (st_intersects(st_centroid(b.geom), f.geom)))
     LEFT JOIN epoleodomia.building_regs_lot l ON (st_intersects(st_centroid(b.geom), l.geom)))
     LEFT JOIN epoleodomia.building_regs_system s ON (st_intersects(st_centroid(b.geom), s.geom)));;
SET LOCAL search_path TO epoleodomia,public;
CREATE VIEW v_recent_changes AS
SELECT c.changed_at, c.table_name, c.objectid, c.change_type, c.changed_fields, c.new_fek,
       sr.started_at AS sync_run_date
FROM changelog c LEFT JOIN sync_runs sr ON c.sync_run_id = sr.id
ORDER BY c.changed_at DESC;
;
CREATE VIEW v_sync_run_summary AS
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
;
CREATE VIEW v_fek_changes AS
SELECT c.changed_at, c.table_name, c.objectid, c.old_fek, c.new_fek, c.change_type
FROM changelog c
WHERE c.old_fek IS DISTINCT FROM c.new_fek AND (c.old_fek IS NOT NULL OR c.new_fek IS NOT NULL)
ORDER BY c.changed_at DESC;
;
CREATE VIEW v_geometry_changes AS
SELECT c.changed_at, c.table_name, c.objectid, c.change_type,
       c.old_geom_wkt, c.new_geom_wkt, sr.started_at AS sync_run_date
FROM changelog c LEFT JOIN sync_runs sr ON c.sync_run_id = sr.id
WHERE c.geometry_changed = TRUE
ORDER BY c.changed_at DESC;
;
CREATE VIEW v_regulation_changes AS
SELECT c.changed_at, c.table_name, c.objectid, c.change_type, c.changed_fields,
       c.old_values, c.new_values, c.old_fek, c.new_fek
FROM changelog c
WHERE c.table_name IN ('building_regs_height','building_regs_coverage','building_regs_coefficient',
                        'building_regs_lot','building_regs_system','building_blocks')
ORDER BY c.changed_at DESC;
;
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
;
CREATE INDEX "epol_reconcile_idx_1" ON epoleodomia."ab_zones_attica" USING btree (is_deleted) WHERE (is_deleted = false);
CREATE INDEX "epol_reconcile_idx_2" ON epoleodomia."addresses" USING btree (is_deleted) WHERE (is_deleted = false);
CREATE INDEX "epol_reconcile_idx_3" ON epoleodomia."approved_plan_boundaries" USING btree (is_deleted) WHERE (is_deleted = false);
CREATE INDEX "epol_reconcile_idx_4" ON epoleodomia."archaeological_sites_lines" USING btree (is_deleted) WHERE (is_deleted = false);
CREATE INDEX "epol_reconcile_idx_5" ON epoleodomia."archaeological_sites_points" USING btree (is_deleted) WHERE (is_deleted = false);
CREATE INDEX "epol_reconcile_idx_6" ON epoleodomia."archaeological_sites_polygons" USING btree (is_deleted) WHERE (is_deleted = false);
CREATE INDEX "epol_reconcile_idx_7" ON epoleodomia."archaeological_zones_pl" USING btree (is_deleted) WHERE (is_deleted = false);
CREATE INDEX "epol_reconcile_idx_8" ON epoleodomia."block_vertices" USING btree (is_deleted) WHERE (is_deleted = false);
CREATE INDEX "epol_reconcile_idx_9" ON epoleodomia."building_blocks" USING btree (is_deleted) WHERE (is_deleted = false);
CREATE INDEX "epol_reconcile_idx_10" ON epoleodomia."building_lines" USING btree (is_deleted) WHERE (is_deleted = false);
CREATE INDEX "epol_reconcile_idx_11" ON epoleodomia."building_regs_coefficient" USING btree (is_deleted) WHERE (is_deleted = false);
CREATE INDEX "epol_reconcile_idx_12" ON epoleodomia."building_regs_coefficient_zones" USING btree (is_deleted) WHERE (is_deleted = false);
CREATE INDEX "epol_reconcile_idx_13" ON epoleodomia."building_regs_coverage" USING btree (is_deleted) WHERE (is_deleted = false);
CREATE INDEX "epol_reconcile_idx_14" ON epoleodomia."building_regs_height" USING btree (is_deleted) WHERE (is_deleted = false);
CREATE INDEX "epol_reconcile_idx_15" ON epoleodomia."building_regs_lot" USING btree (is_deleted) WHERE (is_deleted = false);
CREATE INDEX "epol_reconcile_idx_16" ON epoleodomia."building_regs_system" USING btree (is_deleted) WHERE (is_deleted = false);
CREATE INDEX "epol_reconcile_idx_17" ON epoleodomia."census_blocks_2021" USING btree (is_deleted) WHERE (is_deleted = false);
CREATE INDEX "epol_reconcile_idx_18" ON epoleodomia."changelog" USING btree (change_type);
CREATE INDEX "epol_reconcile_idx_19" ON epoleodomia."changelog" USING btree (changed_at);
CREATE INDEX "epol_reconcile_idx_20" ON epoleodomia."changelog" USING btree (objectid);
CREATE INDEX "epol_reconcile_idx_21" ON epoleodomia."changelog" USING btree (sync_run_id);
CREATE INDEX "epol_reconcile_idx_22" ON epoleodomia."changelog" USING btree (table_name);
CREATE INDEX "epol_reconcile_idx_23" ON epoleodomia."expropriation_zones" USING btree (is_deleted) WHERE (is_deleted = false);
CREATE INDEX "epol_reconcile_idx_24" ON epoleodomia."fek_no_diagrams" USING btree (is_deleted) WHERE (is_deleted = false);
CREATE INDEX "epol_reconcile_idx_25" ON epoleodomia."forest_maps" USING btree (is_deleted) WHERE (is_deleted = false);
CREATE INDEX "epol_reconcile_idx_26" ON epoleodomia."forest_maps_posted_attica_2021" USING btree (is_deleted) WHERE (is_deleted = false);
CREATE INDEX "epol_reconcile_idx_27" ON epoleodomia."forest_maps_posted_pelop_2022" USING btree (is_deleted) WHERE (is_deleted = false);
CREATE INDEX "epol_reconcile_idx_28" ON epoleodomia."historic_sites_lines" USING btree (is_deleted) WHERE (is_deleted = false);
CREATE INDEX "epol_reconcile_idx_29" ON epoleodomia."historic_sites_points" USING btree (is_deleted) WHERE (is_deleted = false);
CREATE INDEX "epol_reconcile_idx_30" ON epoleodomia."historic_sites_polygons" USING btree (is_deleted) WHERE (is_deleted = false);
CREATE INDEX "epol_reconcile_idx_31" ON epoleodomia."land_uses_ers" USING btree (is_deleted) WHERE (is_deleted = false);
CREATE INDEX "epol_reconcile_idx_32" ON epoleodomia."land_uses_gps" USING btree (is_deleted) WHERE (is_deleted = false);
CREATE INDEX "epol_reconcile_idx_33" ON epoleodomia."monuments_lines" USING btree (is_deleted) WHERE (is_deleted = false);
CREATE INDEX "epol_reconcile_idx_34" ON epoleodomia."monuments_points" USING btree (is_deleted) WHERE (is_deleted = false);
CREATE INDEX "epol_reconcile_idx_35" ON epoleodomia."monuments_polygons" USING btree (is_deleted) WHERE (is_deleted = false);
CREATE INDEX "epol_reconcile_idx_36" ON epoleodomia."municipal_communities_2021" USING btree (is_deleted) WHERE (is_deleted = false);
CREATE INDEX "epol_reconcile_idx_37" ON epoleodomia."municipal_units_2021" USING btree (is_deleted) WHERE (is_deleted = false);
CREATE INDEX "epol_reconcile_idx_38" ON epoleodomia."municipalities_2021" USING btree (is_deleted) WHERE (is_deleted = false);
CREATE INDEX "epol_reconcile_idx_39" ON epoleodomia."natura_2000" USING btree (is_deleted) WHERE (is_deleted = false);
CREATE INDEX "epol_reconcile_idx_40" ON epoleodomia."natural_landscapes_points" USING btree (is_deleted) WHERE (is_deleted = false);
CREATE INDEX "epol_reconcile_idx_41" ON epoleodomia."natural_landscapes_polygons" USING btree (is_deleted) WHERE (is_deleted = false);
CREATE INDEX "epol_reconcile_idx_42" ON epoleodomia."other_planning_lines" USING btree (is_deleted) WHERE (is_deleted = false);
CREATE INDEX "epol_reconcile_idx_43" ON epoleodomia."other_planning_zones" USING btree (is_deleted) WHERE (is_deleted = false);
CREATE INDEX "epol_reconcile_idx_44" ON epoleodomia."outside_plan_areas" USING btree (is_deleted) WHERE (is_deleted = false);
CREATE INDEX "epol_reconcile_idx_45" ON epoleodomia."pd_protection_zones" USING btree (is_deleted) WHERE (is_deleted = false);
CREATE INDEX "epol_reconcile_idx_46" ON epoleodomia."pedestrian_zones" USING btree (is_deleted) WHERE (is_deleted = false);
CREATE INDEX "epol_reconcile_idx_47" ON epoleodomia."planning_diagrams" USING btree (is_deleted) WHERE (is_deleted = false);
CREATE INDEX "epol_reconcile_idx_48" ON epoleodomia."planning_lines" USING btree (is_deleted) WHERE (is_deleted = false);
CREATE INDEX "epol_reconcile_idx_49" ON epoleodomia."protected_buildings" USING btree (is_deleted) WHERE (is_deleted = false);
CREATE INDEX "epol_reconcile_idx_50" ON epoleodomia."protection_zones_lines" USING btree (is_deleted) WHERE (is_deleted = false);
CREATE INDEX "epol_reconcile_idx_51" ON epoleodomia."protection_zones_points" USING btree (is_deleted) WHERE (is_deleted = false);
CREATE INDEX "epol_reconcile_idx_52" ON epoleodomia."protection_zones_polygons" USING btree (is_deleted) WHERE (is_deleted = false);
CREATE INDEX "epol_reconcile_idx_53" ON epoleodomia."public_spaces" USING btree (is_deleted) WHERE (is_deleted = false);
CREATE INDEX "epol_reconcile_idx_54" ON epoleodomia."settlement_boundaries" USING btree (is_deleted) WHERE (is_deleted = false);
CREATE INDEX "epol_reconcile_idx_55" ON epoleodomia."settlements_2021" USING btree (is_deleted) WHERE (is_deleted = false);
CREATE INDEX "epol_reconcile_idx_56" ON epoleodomia."shorelines" USING btree (is_deleted) WHERE (is_deleted = false);
CREATE INDEX "epol_reconcile_idx_57" ON epoleodomia."streams" USING btree (is_deleted) WHERE (is_deleted = false);
CREATE INDEX "epol_reconcile_idx_58" ON epoleodomia."streams_environmental" USING btree (is_deleted) WHERE (is_deleted = false);
CREATE INDEX "epol_reconcile_idx_59" ON epoleodomia."urban_units" USING btree (is_deleted) WHERE (is_deleted = false);
CREATE INDEX "epol_reconcile_idx_60" ON epoleodomia."zoe_zones" USING btree (is_deleted) WHERE (is_deleted = false);

-- The installed reader keeps read-only access to newly introduced objects.
GRANT SELECT ON TABLE epoleodomia.sync_runs, epoleodomia.changelog,
    epoleodomia.land_use_codes, epoleodomia.v_recent_changes,
    epoleodomia.v_sync_run_summary, epoleodomia.v_fek_changes,
    epoleodomia.v_geometry_changes, epoleodomia.v_regulation_changes TO codex_reader;
GRANT SELECT ON SEQUENCE epoleodomia.sync_runs_id_seq,
    epoleodomia.changelog_id_seq TO codex_reader;

$epol_prepare_ddl$;
END;
$epol_prepare$;
