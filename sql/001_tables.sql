-- ============================================================================
-- TEE Urban Planning Data Mirror — Spetses Island
-- Schema: epoleodomia  |  CRS: EPSG:2100 (GGRS87)
-- v1.1 — Consolidated DDL (all migrations merged)
--
-- Run: psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME -f sql/001_tables.sql
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS epoleodomia;
SET search_path TO epoleodomia, public;

-- ============================================================================
-- HELPER: Macro columns shared by most tables
-- ============================================================================
-- Every data table includes:
--   objectid INTEGER UNIQUE  (TEE stable ID, used for upsert)
--   created_at / updated_at / is_deleted / deleted_at  (change tracking)
--   fetched_at  (last sync timestamp)

-- ============================================================================
-- 1. URBAN PLANNING  (UDM_SERVICE_POLEODOMIKI_PLIROFORIA)
-- ============================================================================

-- Layer 1: Shorelines (Γραμμές Αιγιαλού και Παραλίας)
DROP TABLE IF EXISTS shorelines CASCADE;
CREATE TABLE shorelines (
    id SERIAL PRIMARY KEY,
    objectid INTEGER UNIQUE,
    fek VARCHAR(255),
    fek_file_url VARCHAR(2000),
    publ_date VARCHAR(10),
    line_name VARCHAR(255),
    line_type_aigial_paralia VARCHAR(255),
    apof_eidos VARCHAR(255),
    title VARCHAR(2000),
    number_ VARCHAR(100),
    sign_date VARCHAR(10),
    georef_diagram_url VARCHAR(2000),
    initial_diagram_url VARCHAR(2000),
    kall_dhm_name VARCHAR(40),
    key_flag INTEGER,
    geom GEOMETRY(LineString, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP,
    is_deleted BOOLEAN DEFAULT FALSE,
    deleted_at TIMESTAMP
);

-- Layer 2: Protected Buildings (Διατηρητέα Κτίσματα)
DROP TABLE IF EXISTS protected_buildings CASCADE;
CREATE TABLE protected_buildings (
    id SERIAL PRIMARY KEY,
    objectid INTEGER UNIQUE,
    fek VARCHAR(521),
    eidosfek VARCHAR(500),
    type VARCHAR(1000),
    thesmkat VARCHAR(500),
    odos VARCHAR(500),
    thesi VARCHAR(500),
    x DOUBLE PRECISION,
    y DOUBLE PRECISION,
    apof_number VARCHAR(255),
    sign_date VARCHAR(10),
    geom GEOMETRY(Point, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP,
    is_deleted BOOLEAN DEFAULT FALSE,
    deleted_at TIMESTAMP
);

-- Layer 3: Settlement Boundaries (Καθορισμένο Όριο Οικισμού)
DROP TABLE IF EXISTS settlement_boundaries CASCADE;
CREATE TABLE settlement_boundaries (
    id SERIAL PRIMARY KEY,
    objectid INTEGER UNIQUE,
    fek VARCHAR(151),
    fek_file_url VARCHAR(2000),
    publ_date VARCHAR(10),
    name VARCHAR(255),
    apof_eidos VARCHAR(255),
    title VARCHAR(2000),
    number_ VARCHAR(100),
    sign_date VARCHAR(10),
    kall_dhm_name VARCHAR(40),
    key_flag INTEGER,
    geom GEOMETRY(Polygon, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP,
    is_deleted BOOLEAN DEFAULT FALSE,
    deleted_at TIMESTAMP
);

-- Layer 4: Block Vertices (Κορυφές ΟΤ)
DROP TABLE IF EXISTS block_vertices CASCADE;
CREATE TABLE block_vertices (
    id SERIAL PRIMARY KEY,
    objectid INTEGER UNIQUE,
    fek VARCHAR(255),
    fek_file_url VARCHAR(2000),
    publ_date VARCHAR(10),
    ot_koryf_name VARCHAR(50),
    x_coord DOUBLE PRECISION,
    y_coord DOUBLE PRECISION,
    apof_eidos VARCHAR(255),
    title VARCHAR(2000),
    number_ VARCHAR(100),
    sign_date VARCHAR(10),
    georef_diagram_url VARCHAR(2000),
    initial_diagram_url VARCHAR(2000),
    kall_dhm_name VARCHAR(40),
    key_flag INTEGER,
    key_auto VARCHAR(255),
    geom GEOMETRY(Point, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP,
    is_deleted BOOLEAN DEFAULT FALSE,
    deleted_at TIMESTAMP
);

-- Layer 5: Other Planning Zones (Λοιπές Ζώνες Ρυμοτομικού Σχεδίου)
DROP TABLE IF EXISTS other_planning_zones CASCADE;
CREATE TABLE other_planning_zones (
    id SERIAL PRIMARY KEY,
    objectid INTEGER UNIQUE,
    fek VARCHAR(151),
    fek_file_url VARCHAR(2000),
    publ_date VARCHAR(10),
    zone_name VARCHAR(255),
    zone_type VARCHAR(255),
    apof_eidos VARCHAR(255),
    title VARCHAR(2000),
    number_ VARCHAR(100),
    sign_date VARCHAR(10),
    kall_dhm_name VARCHAR(40),
    key_flag INTEGER,
    geom GEOMETRY(Polygon, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP,
    is_deleted BOOLEAN DEFAULT FALSE,
    deleted_at TIMESTAMP
);

-- Layer 6: Building Blocks (Οικοδομικά Τετράγωνα)
DROP TABLE IF EXISTS building_blocks CASCADE;
CREATE TABLE building_blocks (
    id SERIAL PRIMARY KEY,
    objectid INTEGER UNIQUE,
    fek VARCHAR(255),
    fek_file_url VARCHAR(2000),
    publ_date VARCHAR(10),
    ot_num VARCHAR(12),
    apof_eidos VARCHAR(255),
    title VARCHAR(2000),
    number_ VARCHAR(100),
    sign_date VARCHAR(10),
    georef_diagram_url VARCHAR(2000),
    initial_diagram_url VARCHAR(2000),
    kall_dhm_name VARCHAR(40),
    key_flag INTEGER,
    geom GEOMETRY(Polygon, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP,
    is_deleted BOOLEAN DEFAULT FALSE,
    deleted_at TIMESTAMP
);

-- Layer 7: Streams (Οριοθετημένο Ρέμα)
DROP TABLE IF EXISTS streams CASCADE;
CREATE TABLE streams (
    id SERIAL PRIMARY KEY,
    objectid INTEGER UNIQUE,
    fek VARCHAR(151),
    fek_file_url VARCHAR(2000),
    publ_date VARCHAR(10),
    line_name VARCHAR(255),
    apof_eidos VARCHAR(255),
    title VARCHAR(2000),
    number_ VARCHAR(100),
    sign_date VARCHAR(10),
    georef_diagram_url VARCHAR(2000),
    initial_diagram_url VARCHAR(2000),
    kall_dhm_name VARCHAR(40),
    key_flag INTEGER,
    geom GEOMETRY(LineString, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP,
    is_deleted BOOLEAN DEFAULT FALSE,
    deleted_at TIMESTAMP
);

-- Layer 8: Pedestrian Zones (Πεζόδρομος)
DROP TABLE IF EXISTS pedestrian_zones CASCADE;
CREATE TABLE pedestrian_zones (
    id SERIAL PRIMARY KEY,
    objectid INTEGER UNIQUE,
    fek VARCHAR(255),
    fek_file_url VARCHAR(2000),
    publ_date VARCHAR(10),
    pz_xrhsh VARCHAR(255),
    apof_eidos VARCHAR(255),
    title VARCHAR(2000),
    number_ VARCHAR(100),
    sign_date VARCHAR(10),
    georef_diagram_url VARCHAR(2000),
    initial_diagram_url VARCHAR(2000),
    kall_dhm_name VARCHAR(40),
    key_flag INTEGER,
    geom GEOMETRY(Polygon, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP,
    is_deleted BOOLEAN DEFAULT FALSE,
    deleted_at TIMESTAMP
);

-- Layer 9: Outside Plan Areas (Περιοχή Εκτός Σχεδίου)
DROP TABLE IF EXISTS outside_plan_areas CASCADE;
CREATE TABLE outside_plan_areas (
    id SERIAL PRIMARY KEY,
    objectid INTEGER UNIQUE,
    fek VARCHAR(151),
    fek_file_url VARCHAR(2000),
    publ_date VARCHAR(10),
    text VARCHAR(255),
    apof_eidos VARCHAR(255),
    title VARCHAR(2000),
    number_ VARCHAR(100),
    sign_date VARCHAR(10),
    kall_dhm_name VARCHAR(40),
    key_flag INTEGER,
    geom GEOMETRY(Polygon, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP,
    is_deleted BOOLEAN DEFAULT FALSE,
    deleted_at TIMESTAMP
);

-- Layer 11: Planning Lines (Ρυμοτομική Γραμμή)
DROP TABLE IF EXISTS planning_lines CASCADE;
CREATE TABLE planning_lines (
    id SERIAL PRIMARY KEY,
    objectid INTEGER UNIQUE,
    fek VARCHAR(255),
    fek_file_url VARCHAR(2000),
    publ_date VARCHAR(10),
    road_width INTEGER,
    prasia_width INTEGER,
    rg_type VARCHAR(255),
    apof_eidos VARCHAR(255),
    title VARCHAR(2000),
    number_ VARCHAR(100),
    sign_date VARCHAR(10),
    georef_diagram_url VARCHAR(2000),
    initial_diagram_url VARCHAR(2000),
    kall_dhm_name VARCHAR(40),
    key_flag INTEGER,
    geom GEOMETRY(LineString, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP,
    is_deleted BOOLEAN DEFAULT FALSE,
    deleted_at TIMESTAMP
);

-- Layer 12: Building Lines (Οικοδομική Γραμμή)
DROP TABLE IF EXISTS building_lines CASCADE;
CREATE TABLE building_lines (
    id SERIAL PRIMARY KEY,
    objectid INTEGER UNIQUE,
    fek VARCHAR(255),
    fek_file_url VARCHAR(2000),
    publ_date VARCHAR(10),
    prasia_width INTEGER,
    og_type VARCHAR(255),
    apof_eidos VARCHAR(255),
    title VARCHAR(2000),
    number_ VARCHAR(100),
    sign_date VARCHAR(10),
    georef_diagram_url VARCHAR(2000),
    initial_diagram_url VARCHAR(2000),
    kall_dhm_name VARCHAR(40),
    key_flag INTEGER,
    rn DOUBLE PRECISION,
    shape_len DOUBLE PRECISION,
    geom GEOMETRY(LineString, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP,
    is_deleted BOOLEAN DEFAULT FALSE,
    deleted_at TIMESTAMP
);

-- Layer 13: Other Planning Lines (Λοιπές Πολεοδομικές Γραμμές)
DROP TABLE IF EXISTS other_planning_lines CASCADE;
CREATE TABLE other_planning_lines (
    id SERIAL PRIMARY KEY,
    objectid INTEGER UNIQUE,
    fek VARCHAR(255),
    fek_file_url VARCHAR(2000),
    publ_date VARCHAR(10),
    pol_gr_type VARCHAR(255),
    apof_eidos VARCHAR(255),
    title VARCHAR(2000),
    number_ VARCHAR(100),
    sign_date VARCHAR(10),
    georef_diagram_url VARCHAR(2000),
    initial_diagram_url VARCHAR(2000),
    kall_dhm_name VARCHAR(40),
    key_flag INTEGER,
    geom GEOMETRY(LineString, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP,
    is_deleted BOOLEAN DEFAULT FALSE,
    deleted_at TIMESTAMP
);

-- Layer 14: Urban Units (Πολεοδομική Ενότητα)
DROP TABLE IF EXISTS urban_units CASCADE;
CREATE TABLE urban_units (
    id SERIAL PRIMARY KEY,
    objectid INTEGER UNIQUE,
    fek VARCHAR(151),
    fek_file_url VARCHAR(2000),
    publ_date VARCHAR(10),
    pl_area_type VARCHAR(255),
    apof_eidos VARCHAR(255),
    title VARCHAR(2000),
    number_ VARCHAR(100),
    sign_date VARCHAR(10),
    kall_dhm_name VARCHAR(40),
    key_flag INTEGER,
    geom GEOMETRY(Polygon, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP,
    is_deleted BOOLEAN DEFAULT FALSE,
    deleted_at TIMESTAMP
);

-- Layer 16: Building Regs — Height (Αριθμός Ορόφων - Ύψος)
DROP TABLE IF EXISTS building_regs_height CASCADE;
CREATE TABLE building_regs_height (
    id SERIAL PRIMARY KEY,
    objectid INTEGER UNIQUE,
    fek VARCHAR(151),
    fek_file_url VARCHAR(2000),
    publ_date VARCHAR(10),
    max_height_m DOUBLE PRECISION,
    oror_max_height_comment VARCHAR(2000),
    num_orofon INTEGER,
    oror_num_orofon_comment VARCHAR(2000),
    synthiki_txt VARCHAR(2000),
    apof_eidos VARCHAR(255),
    title VARCHAR(2000),
    number_ VARCHAR(100),
    sign_date VARCHAR(10),
    kall_dhm_name VARCHAR(40),
    geom GEOMETRY(Polygon, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP,
    is_deleted BOOLEAN DEFAULT FALSE,
    deleted_at TIMESTAMP
);

-- Layer 17: Building Regs — Lot (Αρτιότητα)
DROP TABLE IF EXISTS building_regs_lot CASCADE;
CREATE TABLE building_regs_lot (
    id SERIAL PRIMARY KEY,
    objectid INTEGER UNIQUE,
    fek VARCHAR(151),
    fek_file_url VARCHAR(2000),
    publ_date VARCHAR(10),
    artiothta_m2 DOUBLE PRECISION,
    artiothta_comment VARCHAR(2000),
    prosopsi_m DOUBLE PRECISION,
    prosopsi_comment VARCHAR(2000),
    elax_embado_m2 DOUBLE PRECISION,
    elax_prosop_m DOUBLE PRECISION,
    oros_type VARCHAR(50),
    date_pareklisis VARCHAR(20),
    remarks VARCHAR(2000),
    synthiki_txt VARCHAR(2000),
    apof_eidos VARCHAR(255),
    title VARCHAR(2000),
    number_ VARCHAR(100),
    sign_date VARCHAR(10),
    kall_dhm_name VARCHAR(40),
    geom GEOMETRY(Polygon, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP,
    is_deleted BOOLEAN DEFAULT FALSE,
    deleted_at TIMESTAMP
);

-- Layer 18: Building Regs — Coverage (Κάλυψη)
DROP TABLE IF EXISTS building_regs_coverage CASCADE;
CREATE TABLE building_regs_coverage (
    id SERIAL PRIMARY KEY,
    objectid INTEGER UNIQUE,
    fek VARCHAR(151),
    fek_file_url VARCHAR(2000),
    publ_date VARCHAR(10),
    kalypsi_pct DOUBLE PRECISION,
    kalypsi_comment VARCHAR(2000),
    synt_kalypsis VARCHAR(255),
    max_embado_m2 DOUBLE PRECISION,
    remarks VARCHAR(2000),
    synthiki_txt VARCHAR(2000),
    apof_eidos VARCHAR(255),
    title VARCHAR(2000),
    number_ VARCHAR(100),
    sign_date VARCHAR(10),
    kall_dhm_name VARCHAR(40),
    geom GEOMETRY(Polygon, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP,
    is_deleted BOOLEAN DEFAULT FALSE,
    deleted_at TIMESTAMP
);

-- Layer 19: Building Regs — System (Οικοδομικό Σύστημα)
DROP TABLE IF EXISTS building_regs_system CASCADE;
CREATE TABLE building_regs_system (
    id SERIAL PRIMARY KEY,
    objectid INTEGER UNIQUE,
    fek VARCHAR(151),
    fek_file_url VARCHAR(2000),
    publ_date VARCHAR(10),
    oik_systima VARCHAR(255),
    oik_systima_comment VARCHAR(2000),
    synthiki_txt VARCHAR(2000),
    apof_eidos VARCHAR(255),
    title VARCHAR(2000),
    number_ VARCHAR(100),
    sign_date VARCHAR(10),
    kall_dhm_name VARCHAR(40),
    geom GEOMETRY(Polygon, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP,
    is_deleted BOOLEAN DEFAULT FALSE,
    deleted_at TIMESTAMP
);

-- Layer 20: Building Regs — Coefficient (Συντελεστής Δόμησης)
DROP TABLE IF EXISTS building_regs_coefficient CASCADE;
CREATE TABLE building_regs_coefficient (
    id SERIAL PRIMARY KEY,
    objectid INTEGER UNIQUE,
    fek VARCHAR(151),
    fek_file_url VARCHAR(2000),
    publ_date VARCHAR(10),
    syntelesths_domhshs DOUBLE PRECISION,
    sd_timh DOUBLE PRECISION,
    sd_tomeas VARCHAR(100),
    sd_klimakotos VARCHAR(10),
    sd_comment VARCHAR(2000),
    synthiki_txt VARCHAR(2000),
    apof_eidos VARCHAR(255),
    title VARCHAR(2000),
    number_ VARCHAR(100),
    sign_date VARCHAR(10),
    kall_dhm_name VARCHAR(40),
    geom GEOMETRY(Polygon, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP,
    is_deleted BOOLEAN DEFAULT FALSE,
    deleted_at TIMESTAMP
);

-- Layer 21: Land Uses ERS (Χρήσεις Γης ΕΡΣ)
DROP TABLE IF EXISTS land_uses_ers CASCADE;
CREATE TABLE land_uses_ers (
    id SERIAL PRIMARY KEY,
    objectid INTEGER UNIQUE,
    fek VARCHAR(255),
    fek_file_url VARCHAR(2000),
    publ_date VARCHAR(10),
    gen_xrhsh_flag VARCHAR(255),
    gen_xrhsh_gps VARCHAR(255),
    per_cat_gen VARCHAR(255),
    per_cat_eid VARCHAR(500),
    remarks VARCHAR(1000),
    eidikh_coded_delim_values VARCHAR(1000),
    apof_eidos VARCHAR(255),
    title VARCHAR(2000),
    number_ VARCHAR(100),
    sign_date VARCHAR(10),
    kall_dhm_name VARCHAR(40),
    key_flag INTEGER,
    geom GEOMETRY(Polygon, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP,
    is_deleted BOOLEAN DEFAULT FALSE,
    deleted_at TIMESTAMP
);

-- Layer 22: Public Spaces (Κοινόχρηστοι / Κοινωφελείς)
DROP TABLE IF EXISTS public_spaces CASCADE;
CREATE TABLE public_spaces (
    id SERIAL PRIMARY KEY,
    objectid INTEGER UNIQUE,
    fek VARCHAR(255),
    fek_file_url VARCHAR(2000),
    publ_date VARCHAR(10),
    kx_koinoxr_kodikos VARCHAR(255),
    kx_koinoxr_type VARCHAR(255),
    apof_eidos VARCHAR(255),
    title VARCHAR(2000),
    number_ VARCHAR(100),
    sign_date VARCHAR(10),
    georef_diagram_url VARCHAR(2000),
    initial_diagram_url VARCHAR(2000),
    kall_dhm_name VARCHAR(40),
    key_flag INTEGER,
    geom GEOMETRY(Polygon, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP,
    is_deleted BOOLEAN DEFAULT FALSE,
    deleted_at TIMESTAMP
);

-- Layer 23: Archaeological Zones (from Planning service)
DROP TABLE IF EXISTS archaeological_zones_pl CASCADE;
CREATE TABLE archaeological_zones_pl (
    id SERIAL PRIMARY KEY,
    objectid INTEGER UNIQUE,
    fek VARCHAR(255),
    fek_file_url VARCHAR(2000),
    publ_date VARCHAR(10),
    zone_name VARCHAR(255),
    zone_type VARCHAR(255),
    apof_eidos VARCHAR(255),
    title VARCHAR(2000),
    number_ VARCHAR(100),
    sign_date VARCHAR(10),
    kall_dhm_name VARCHAR(40),
    key_flag INTEGER,
    geom GEOMETRY(Polygon, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP,
    is_deleted BOOLEAN DEFAULT FALSE,
    deleted_at TIMESTAMP
);

-- Layer 24: Expropriation Zones
DROP TABLE IF EXISTS expropriation_zones CASCADE;
CREATE TABLE expropriation_zones (
    id SERIAL PRIMARY KEY,
    objectid INTEGER UNIQUE,
    fek VARCHAR(255),
    fek_file_url VARCHAR(2000),
    publ_date VARCHAR(10),
    zone_name VARCHAR(255),
    apof_eidos VARCHAR(255),
    title VARCHAR(2000),
    number_ VARCHAR(100),
    sign_date VARCHAR(10),
    kall_dhm_name VARCHAR(40),
    key_flag INTEGER,
    geom GEOMETRY(Polygon, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP,
    is_deleted BOOLEAN DEFAULT FALSE,
    deleted_at TIMESTAMP
);

-- Layer 26: Land Uses GPS (Χρήσεις Γης ΓΠΣ)
DROP TABLE IF EXISTS land_uses_gps CASCADE;
CREATE TABLE land_uses_gps (
    id SERIAL PRIMARY KEY,
    objectid INTEGER UNIQUE,
    fek VARCHAR(255),
    fek_file_url VARCHAR(2000),
    publ_date VARCHAR(10),
    gen_xrhsh_flag VARCHAR(255),
    gen_xrhsh_gps VARCHAR(255),
    per_cat_gen VARCHAR(255),
    per_cat_eid VARCHAR(500),
    remarks VARCHAR(1000),
    eidikh_coded_delim_values VARCHAR(1000),
    apof_eidos VARCHAR(255),
    title VARCHAR(2000),
    number_ VARCHAR(100),
    sign_date VARCHAR(10),
    kall_dhm_name VARCHAR(40),
    key_flag INTEGER,
    geom GEOMETRY(Polygon, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP,
    is_deleted BOOLEAN DEFAULT FALSE,
    deleted_at TIMESTAMP
);

-- ============================================================================
-- 2. ADDRESSES  (UDM_SERVICE_BUILDINGS)
-- ============================================================================

DROP TABLE IF EXISTS addresses CASCADE;
CREATE TABLE addresses (
    id SERIAL PRIMARY KEY,
    objectid INTEGER UNIQUE,
    addr VARCHAR(108),
    num VARCHAR(10),
    munic VARCHAR(80),
    geom GEOMETRY(Point, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP,
    is_deleted BOOLEAN DEFAULT FALSE,
    deleted_at TIMESTAMP
);

-- ============================================================================
-- 3. PLANNING DOCUMENTS  (UDM_SERVICE_SXEDIA_DOCS)
-- ============================================================================

DROP TABLE IF EXISTS planning_diagrams CASCADE;
CREATE TABLE planning_diagrams (
    id SERIAL PRIMARY KEY,
    objectid INTEGER UNIQUE,
    fek VARCHAR(255),
    fek_file_url VARCHAR(2000),
    publ_date VARCHAR(10),
    apof_eidos VARCHAR(255),
    title VARCHAR(2000),
    number_ VARCHAR(100),
    sign_date VARCHAR(10),
    comp_diagr_legend_number VARCHAR(255),
    init_diagr_scale_denominator INTEGER,
    ggrs87_diagr_georef_rms DOUBLE PRECISION,
    georef_diagram_url VARCHAR(2000),
    initial_diagram_url VARCHAR(2000),
    geom GEOMETRY(Polygon, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP,
    is_deleted BOOLEAN DEFAULT FALSE,
    deleted_at TIMESTAMP
);

-- ============================================================================
-- 4. APPROVED PLANS  (UDM_SERVICE_POLEOD_RYM_SXD)
-- ============================================================================

DROP TABLE IF EXISTS approved_plan_boundaries CASCADE;
CREATE TABLE approved_plan_boundaries (
    id SERIAL PRIMARY KEY,
    objectid INTEGER UNIQUE,
    fek VARCHAR(255),
    fek_file_url VARCHAR(2000),
    publ_date VARCHAR(10),
    apof_eidos VARCHAR(255),
    apof_theme VARCHAR(255),
    title VARCHAR(2000),
    number_ VARCHAR(100),
    sign_date VARCHAR(10),
    kall_dhm_name VARCHAR(40),
    geom GEOMETRY(Polygon, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP,
    is_deleted BOOLEAN DEFAULT FALSE,
    deleted_at TIMESTAMP
);

-- ============================================================================
-- 5. ARCHAEOLOGICAL  (UDM_SERVICE_ARCHAIOLOGIKO)
-- ============================================================================

-- Monuments (points / lines / polygons)
DROP TABLE IF EXISTS monuments_points CASCADE;
CREATE TABLE monuments_points (
    id SERIAL PRIMARY KEY, objectid INTEGER UNIQUE,
    name VARCHAR(500), ota VARCHAR(500), foreas VARCHAR(500),
    geom GEOMETRY(Point, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(), created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP, is_deleted BOOLEAN DEFAULT FALSE, deleted_at TIMESTAMP
);

DROP TABLE IF EXISTS monuments_lines CASCADE;
CREATE TABLE monuments_lines (
    id SERIAL PRIMARY KEY, objectid INTEGER UNIQUE,
    name VARCHAR(500), ota VARCHAR(500), foreas VARCHAR(500), shape_len DOUBLE PRECISION,
    geom GEOMETRY(LineString, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(), created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP, is_deleted BOOLEAN DEFAULT FALSE, deleted_at TIMESTAMP
);

DROP TABLE IF EXISTS monuments_polygons CASCADE;
CREATE TABLE monuments_polygons (
    id SERIAL PRIMARY KEY, objectid INTEGER UNIQUE,
    name VARCHAR(500), ota VARCHAR(500), foreas VARCHAR(500),
    shape_area DOUBLE PRECISION, shape_len DOUBLE PRECISION,
    geom GEOMETRY(Polygon, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(), created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP, is_deleted BOOLEAN DEFAULT FALSE, deleted_at TIMESTAMP
);

-- Protection Zones
DROP TABLE IF EXISTS protection_zones_points CASCADE;
CREATE TABLE protection_zones_points (
    id SERIAL PRIMARY KEY, objectid INTEGER UNIQUE,
    name VARCHAR(500), ota VARCHAR(500), foreas VARCHAR(500),
    geom GEOMETRY(Point, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(), created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP, is_deleted BOOLEAN DEFAULT FALSE, deleted_at TIMESTAMP
);

DROP TABLE IF EXISTS protection_zones_lines CASCADE;
CREATE TABLE protection_zones_lines (
    id SERIAL PRIMARY KEY, objectid INTEGER UNIQUE,
    name VARCHAR(500), ota VARCHAR(500), foreas VARCHAR(500), shape_len DOUBLE PRECISION,
    geom GEOMETRY(LineString, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(), created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP, is_deleted BOOLEAN DEFAULT FALSE, deleted_at TIMESTAMP
);

DROP TABLE IF EXISTS protection_zones_polygons CASCADE;
CREATE TABLE protection_zones_polygons (
    id SERIAL PRIMARY KEY, objectid INTEGER UNIQUE,
    name VARCHAR(500), ota VARCHAR(500), foreas VARCHAR(500),
    shape_area DOUBLE PRECISION, shape_len DOUBLE PRECISION,
    geom GEOMETRY(Polygon, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(), created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP, is_deleted BOOLEAN DEFAULT FALSE, deleted_at TIMESTAMP
);

-- Historic Sites
DROP TABLE IF EXISTS historic_sites_points CASCADE;
CREATE TABLE historic_sites_points (
    id SERIAL PRIMARY KEY, objectid INTEGER UNIQUE,
    name VARCHAR(500), ota VARCHAR(500), foreas VARCHAR(500),
    geom GEOMETRY(Point, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(), created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP, is_deleted BOOLEAN DEFAULT FALSE, deleted_at TIMESTAMP
);

DROP TABLE IF EXISTS historic_sites_lines CASCADE;
CREATE TABLE historic_sites_lines (
    id SERIAL PRIMARY KEY, objectid INTEGER UNIQUE,
    name VARCHAR(500), ota VARCHAR(500), foreas VARCHAR(500), shape_len DOUBLE PRECISION,
    geom GEOMETRY(LineString, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(), created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP, is_deleted BOOLEAN DEFAULT FALSE, deleted_at TIMESTAMP
);

DROP TABLE IF EXISTS historic_sites_polygons CASCADE;
CREATE TABLE historic_sites_polygons (
    id SERIAL PRIMARY KEY, objectid INTEGER UNIQUE,
    name VARCHAR(500), ota VARCHAR(500), foreas VARCHAR(500),
    shape_area DOUBLE PRECISION, shape_len DOUBLE PRECISION,
    geom GEOMETRY(Polygon, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(), created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP, is_deleted BOOLEAN DEFAULT FALSE, deleted_at TIMESTAMP
);

-- Archaeological Sites
DROP TABLE IF EXISTS archaeological_sites_points CASCADE;
CREATE TABLE archaeological_sites_points (
    id SERIAL PRIMARY KEY, objectid INTEGER UNIQUE,
    name VARCHAR(500), ota VARCHAR(500), foreas VARCHAR(500),
    geom GEOMETRY(Point, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(), created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP, is_deleted BOOLEAN DEFAULT FALSE, deleted_at TIMESTAMP
);

DROP TABLE IF EXISTS archaeological_sites_lines CASCADE;
CREATE TABLE archaeological_sites_lines (
    id SERIAL PRIMARY KEY, objectid INTEGER UNIQUE,
    name VARCHAR(500), ota VARCHAR(500), foreas VARCHAR(500), shape_len DOUBLE PRECISION,
    geom GEOMETRY(LineString, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(), created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP, is_deleted BOOLEAN DEFAULT FALSE, deleted_at TIMESTAMP
);

DROP TABLE IF EXISTS archaeological_sites_polygons CASCADE;
CREATE TABLE archaeological_sites_polygons (
    id SERIAL PRIMARY KEY, objectid INTEGER UNIQUE,
    name VARCHAR(500), ota VARCHAR(500), foreas VARCHAR(500),
    shape_area DOUBLE PRECISION, shape_len DOUBLE PRECISION,
    geom GEOMETRY(Polygon, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(), created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP, is_deleted BOOLEAN DEFAULT FALSE, deleted_at TIMESTAMP
);

-- Natural Landscapes
DROP TABLE IF EXISTS natural_landscapes_points CASCADE;
CREATE TABLE natural_landscapes_points (
    id SERIAL PRIMARY KEY, objectid INTEGER UNIQUE,
    name VARCHAR(500), ota VARCHAR(500), foreas VARCHAR(500),
    geom GEOMETRY(Point, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(), created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP, is_deleted BOOLEAN DEFAULT FALSE, deleted_at TIMESTAMP
);

DROP TABLE IF EXISTS natural_landscapes_polygons CASCADE;
CREATE TABLE natural_landscapes_polygons (
    id SERIAL PRIMARY KEY, objectid INTEGER UNIQUE,
    name VARCHAR(500), ota VARCHAR(500), foreas VARCHAR(500),
    shape_area DOUBLE PRECISION, shape_len DOUBLE PRECISION,
    geom GEOMETRY(Polygon, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(), created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP, is_deleted BOOLEAN DEFAULT FALSE, deleted_at TIMESTAMP
);

-- ============================================================================
-- 6. NATURA & FOREST  (UDM_SERVICE_NATURA_DASIKA)
-- ============================================================================

DROP TABLE IF EXISTS natura_2000 CASCADE;
CREATE TABLE natura_2000 (
    id SERIAL PRIMARY KEY, objectid INTEGER UNIQUE,
    sitecode VARCHAR(50), sitename VARCHAR(500), sitetype VARCHAR(50), area_ha DOUBLE PRECISION,
    geom GEOMETRY(Polygon, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(), created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP, is_deleted BOOLEAN DEFAULT FALSE, deleted_at TIMESTAMP
);

-- Ratified forest maps (Layer 3 — Attica)
DROP TABLE IF EXISTS forest_maps CASCADE;
CREATE TABLE forest_maps (
    id SERIAL PRIMARY KEY, objectid INTEGER UNIQUE,
    forest_code VARCHAR(20),
    nomos VARCHAR(20),
    forest_type VARCHAR(20),
    kathgoral1 VARCHAR(20),
    kathgoral2 VARCHAR(20),
    area_m2 DOUBLE PRECISION,
    region_name VARCHAR(255),
    layer_id INTEGER,
    status VARCHAR(255),
    geom GEOMETRY(Polygon, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(), created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP, is_deleted BOOLEAN DEFAULT FALSE, deleted_at TIMESTAMP
);

COMMENT ON TABLE forest_maps IS 'Μερικώς κυρωμένοι δασικοί χάρτες Αττικής (TEE Layer 3)';

-- Posted forest maps — Peloponnese 2022 (Layer 26)
DROP TABLE IF EXISTS forest_maps_posted_pelop_2022 CASCADE;
CREATE TABLE forest_maps_posted_pelop_2022 (
    id SERIAL PRIMARY KEY, objectid INTEGER UNIQUE,
    ota VARCHAR(20), nomos VARCHAR(20),
    forest_type VARCHAR(20), kathgoral1 VARCHAR(20), kathgoral2 VARCHAR(20),
    area_m2 DOUBLE PRECISION,
    geom GEOMETRY(Polygon, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(), created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP, is_deleted BOOLEAN DEFAULT FALSE, deleted_at TIMESTAMP
);

COMMENT ON TABLE forest_maps_posted_pelop_2022 IS 'Αναρτημένοι δασικοί χάρτες Πελοποννήσου 2022 (TEE Layer 26)';

-- Posted forest maps — Attica 2021 (Layer 31)
DROP TABLE IF EXISTS forest_maps_posted_attica_2021 CASCADE;
CREATE TABLE forest_maps_posted_attica_2021 (
    id SERIAL PRIMARY KEY, objectid INTEGER UNIQUE,
    ota VARCHAR(20), nomos VARCHAR(20),
    forest_type VARCHAR(20), kathgoral1 VARCHAR(20), kathgoral2 VARCHAR(20),
    area_m2 DOUBLE PRECISION,
    geom GEOMETRY(Polygon, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(), created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP, is_deleted BOOLEAN DEFAULT FALSE, deleted_at TIMESTAMP
);

COMMENT ON TABLE forest_maps_posted_attica_2021 IS 'Αναρτημένοι δασικοί χάρτες Αττικής 2021 (TEE Layer 31)';

-- ============================================================================
-- 7. RURAL REGULATIONS  (UDM_SERVICE_RYTHMISEIS_EXOASTIKOU_CHOROU)
-- ============================================================================

DROP TABLE IF EXISTS zoe_zones CASCADE;
CREATE TABLE zoe_zones (
    id SERIAL PRIMARY KEY, objectid INTEGER UNIQUE,
    fek VARCHAR(255), fek_file_url VARCHAR(2000),
    zone_name VARCHAR(255), zone_type VARCHAR(255),
    geom GEOMETRY(Polygon, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(), created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP, is_deleted BOOLEAN DEFAULT FALSE, deleted_at TIMESTAMP
);

DROP TABLE IF EXISTS pd_protection_zones CASCADE;
CREATE TABLE pd_protection_zones (
    id SERIAL PRIMARY KEY, objectid INTEGER UNIQUE,
    fek VARCHAR(255), fek_file_url VARCHAR(2000),
    zone_name VARCHAR(255), protection_type VARCHAR(255),
    geom GEOMETRY(Polygon, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(), created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP, is_deleted BOOLEAN DEFAULT FALSE, deleted_at TIMESTAMP
);

DROP TABLE IF EXISTS ab_zones_attica CASCADE;
CREATE TABLE ab_zones_attica (
    id SERIAL PRIMARY KEY, objectid INTEGER UNIQUE,
    zone_type VARCHAR(50), zone_name VARCHAR(255),
    geom GEOMETRY(Polygon, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(), created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP, is_deleted BOOLEAN DEFAULT FALSE, deleted_at TIMESTAMP
);

DROP TABLE IF EXISTS streams_environmental CASCADE;
CREATE TABLE streams_environmental (
    id SERIAL PRIMARY KEY, objectid INTEGER UNIQUE,
    name VARCHAR(255), stream_type VARCHAR(255),
    geom GEOMETRY(LineString, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(), created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP, is_deleted BOOLEAN DEFAULT FALSE, deleted_at TIMESTAMP
);

-- ============================================================================
-- 8. FEK WITHOUT DIAGRAMS  (UDM_SERVICE_FEK_NO_SXEDIA_DOCS)
-- ============================================================================

DROP TABLE IF EXISTS fek_no_diagrams CASCADE;
CREATE TABLE fek_no_diagrams (
    id SERIAL PRIMARY KEY, objectid INTEGER UNIQUE,
    fek VARCHAR(50), fek_file_url VARCHAR(500), publ_date VARCHAR(20),
    apof_eidos VARCHAR(200), apof_theme VARCHAR(200),
    title TEXT, number_ VARCHAR(100), sign_date VARCHAR(20),
    diagram_cat VARCHAR(100),
    geom GEOMETRY(Polygon, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(), created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP, is_deleted BOOLEAN DEFAULT FALSE, deleted_at TIMESTAMP
);

COMMENT ON TABLE fek_no_diagrams IS 'ΦΕΚ without diagrams — regulatory acts TEE could not georeference';

-- ============================================================================
-- 9. YPD ZONE-LEVEL COEFFICIENTS  (UDM_SERVICE_YPD)
-- ============================================================================

DROP TABLE IF EXISTS building_regs_coefficient_zones CASCADE;
CREATE TABLE building_regs_coefficient_zones (
    id SERIAL PRIMARY KEY, objectid INTEGER UNIQUE,
    fek VARCHAR(50), fek_file_url VARCHAR(500), publ_date VARCHAR(20),
    sd_timh DOUBLE PRECISION, sd_tomeas VARCHAR(100),
    sd_klimakotos VARCHAR(10), sd_comment TEXT,
    apof_eidos VARCHAR(200), title TEXT, number_ VARCHAR(100),
    sign_date VARCHAR(20), kall_dhm_name VARCHAR(100),
    geom GEOMETRY(Polygon, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(), created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP, is_deleted BOOLEAN DEFAULT FALSE, deleted_at TIMESTAMP
);

COMMENT ON TABLE building_regs_coefficient_zones IS 'Zone-level ΣΔ from UDM_SERVICE_YPD L20 — per-ΤΟΜΕΑΣ with conditions';

-- ============================================================================
-- 10. ADMINISTRATIVE  (UDM_SERVICE_ELSTAT)
-- ============================================================================

DROP TABLE IF EXISTS municipalities_2021 CASCADE;
CREATE TABLE municipalities_2021 (
    id SERIAL PRIMARY KEY, objectid INTEGER UNIQUE,
    ypes_code VARCHAR(20), ypes_name VARCHAR(255), pop_2021 INTEGER,
    geom GEOMETRY(Polygon, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(), created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP, is_deleted BOOLEAN DEFAULT FALSE, deleted_at TIMESTAMP
);

DROP TABLE IF EXISTS municipal_units_2021 CASCADE;
CREATE TABLE municipal_units_2021 (
    id SERIAL PRIMARY KEY, objectid INTEGER UNIQUE,
    ypes_code VARCHAR(20), ypes_name VARCHAR(255), pop_2021 INTEGER,
    globalid VARCHAR(50),
    geom GEOMETRY(Polygon, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(), created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP, is_deleted BOOLEAN DEFAULT FALSE, deleted_at TIMESTAMP
);

DROP TABLE IF EXISTS municipal_communities_2021 CASCADE;
CREATE TABLE municipal_communities_2021 (
    id SERIAL PRIMARY KEY, objectid INTEGER UNIQUE,
    ypes_code VARCHAR(20), ypes_name VARCHAR(255), pop_2021 INTEGER,
    geom GEOMETRY(Polygon, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(), created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP, is_deleted BOOLEAN DEFAULT FALSE, deleted_at TIMESTAMP
);

DROP TABLE IF EXISTS settlements_2021 CASCADE;
CREATE TABLE settlements_2021 (
    id SERIAL PRIMARY KEY, objectid INTEGER UNIQUE,
    elstat_code VARCHAR(20), name VARCHAR(255), pop_2021 INTEGER,
    geom GEOMETRY(Point, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(), created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP, is_deleted BOOLEAN DEFAULT FALSE, deleted_at TIMESTAMP
);

DROP TABLE IF EXISTS census_blocks_2021 CASCADE;
CREATE TABLE census_blocks_2021 (
    id SERIAL PRIMARY KEY, objectid INTEGER UNIQUE,
    block_code VARCHAR(50), pop_2021 INTEGER, households_2021 INTEGER,
    geom GEOMETRY(Polygon, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(), created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP, is_deleted BOOLEAN DEFAULT FALSE, deleted_at TIMESTAMP
);

-- ============================================================================
-- 11. SYNC LOG  (metadata)
-- ============================================================================

DROP TABLE IF EXISTS sync_log CASCADE;
CREATE TABLE sync_log (
    id SERIAL PRIMARY KEY,
    table_name VARCHAR(100) NOT NULL,
    service_name VARCHAR(255),
    layer_id INTEGER,
    records_fetched INTEGER,
    sync_started_at TIMESTAMP,
    sync_completed_at TIMESTAMP,
    status VARCHAR(50),
    error_message TEXT
);

-- ============================================================================
-- 12. CHANGELOG SYSTEM
-- ============================================================================

DROP TABLE IF EXISTS changelog CASCADE;
DROP TABLE IF EXISTS sync_runs CASCADE;

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
);

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
);

-- ============================================================================
-- 13. RASTER CATALOG
-- ============================================================================

DROP TABLE IF EXISTS raster_catalog CASCADE;
CREATE TABLE raster_catalog (
    id SERIAL PRIMARY KEY,
    planning_diagram_objectid INTEGER,
    fek VARCHAR(50),
    filename VARCHAR(255) NOT NULL,
    url_georef TEXT,
    url_raw TEXT,
    local_path_georef VARCHAR(500),
    local_path_raw VARCHAR(500),
    file_size_bytes BIGINT,
    downloaded_at TIMESTAMP,
    download_status VARCHAR(20) DEFAULT 'pending',
    download_error TEXT,
    last_checked TIMESTAMP,
    bbox GEOMETRY(Polygon, 2100),
    width_px INTEGER,
    height_px INTEGER,
    bands INTEGER,
    resolution_x NUMERIC(10,4),
    resolution_y NUMERIC(10,4),
    crs_epsg INTEGER,
    nodata_value NUMERIC,
    georef_rms NUMERIC(10,4),
    original_scale INTEGER,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- ============================================================================
-- 14. SPATIAL INDEXES
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_shorelines_geom ON shorelines USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_protected_buildings_geom ON protected_buildings USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_settlement_boundaries_geom ON settlement_boundaries USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_block_vertices_geom ON block_vertices USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_other_planning_zones_geom ON other_planning_zones USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_building_blocks_geom ON building_blocks USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_streams_geom ON streams USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_pedestrian_zones_geom ON pedestrian_zones USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_outside_plan_areas_geom ON outside_plan_areas USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_planning_lines_geom ON planning_lines USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_building_lines_geom ON building_lines USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_other_planning_lines_geom ON other_planning_lines USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_urban_units_geom ON urban_units USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_building_regs_height_geom ON building_regs_height USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_building_regs_lot_geom ON building_regs_lot USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_building_regs_coverage_geom ON building_regs_coverage USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_building_regs_system_geom ON building_regs_system USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_building_regs_coefficient_geom ON building_regs_coefficient USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_land_uses_ers_geom ON land_uses_ers USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_public_spaces_geom ON public_spaces USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_archaeological_zones_pl_geom ON archaeological_zones_pl USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_expropriation_zones_geom ON expropriation_zones USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_land_uses_gps_geom ON land_uses_gps USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_addresses_geom ON addresses USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_planning_diagrams_geom ON planning_diagrams USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_approved_plan_boundaries_geom ON approved_plan_boundaries USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_monuments_points_geom ON monuments_points USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_monuments_lines_geom ON monuments_lines USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_monuments_polygons_geom ON monuments_polygons USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_protection_zones_points_geom ON protection_zones_points USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_protection_zones_lines_geom ON protection_zones_lines USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_protection_zones_polygons_geom ON protection_zones_polygons USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_historic_sites_points_geom ON historic_sites_points USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_historic_sites_lines_geom ON historic_sites_lines USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_historic_sites_polygons_geom ON historic_sites_polygons USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_archaeological_sites_points_geom ON archaeological_sites_points USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_archaeological_sites_lines_geom ON archaeological_sites_lines USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_archaeological_sites_polygons_geom ON archaeological_sites_polygons USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_natural_landscapes_points_geom ON natural_landscapes_points USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_natural_landscapes_polygons_geom ON natural_landscapes_polygons USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_natura_2000_geom ON natura_2000 USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_forest_maps_geom ON forest_maps USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_forest_posted_pelop_2022_geom ON forest_maps_posted_pelop_2022 USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_forest_posted_attica_2021_geom ON forest_maps_posted_attica_2021 USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_zoe_zones_geom ON zoe_zones USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_pd_protection_zones_geom ON pd_protection_zones USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_ab_zones_attica_geom ON ab_zones_attica USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_streams_environmental_geom ON streams_environmental USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_fek_no_diagrams_geom ON fek_no_diagrams USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_brc_zones_geom ON building_regs_coefficient_zones USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_municipalities_2021_geom ON municipalities_2021 USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_municipal_units_2021_geom ON municipal_units_2021 USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_municipal_communities_2021_geom ON municipal_communities_2021 USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_settlements_2021_geom ON settlements_2021 USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_census_blocks_2021_geom ON census_blocks_2021 USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_raster_catalog_bbox ON raster_catalog USING GIST (bbox);

-- ============================================================================
-- 15. ATTRIBUTE INDEXES
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_building_blocks_fek ON building_blocks (fek);
CREATE INDEX IF NOT EXISTS idx_building_blocks_kall_dhm ON building_blocks (kall_dhm_name);
CREATE INDEX IF NOT EXISTS idx_planning_lines_fek ON planning_lines (fek);
CREATE INDEX IF NOT EXISTS idx_building_lines_fek ON building_lines (fek);
CREATE INDEX IF NOT EXISTS idx_building_regs_height_fek ON building_regs_height (fek);
CREATE INDEX IF NOT EXISTS idx_building_regs_coverage_fek ON building_regs_coverage (fek);
CREATE INDEX IF NOT EXISTS idx_building_regs_coefficient_fek ON building_regs_coefficient (fek);
CREATE INDEX IF NOT EXISTS idx_land_uses_gps_fek ON land_uses_gps (fek);
CREATE INDEX IF NOT EXISTS idx_addresses_munic ON addresses (munic);
CREATE INDEX IF NOT EXISTS idx_fek_no_diagrams_fek ON fek_no_diagrams (fek);
CREATE INDEX IF NOT EXISTS idx_brc_zones_tomeas ON building_regs_coefficient_zones (sd_tomeas);
CREATE INDEX IF NOT EXISTS idx_raster_catalog_fek ON raster_catalog (fek);
CREATE INDEX IF NOT EXISTS idx_raster_catalog_status ON raster_catalog (download_status);

-- Changelog indexes
CREATE INDEX IF NOT EXISTS idx_changelog_table ON changelog (table_name);
CREATE INDEX IF NOT EXISTS idx_changelog_objectid ON changelog (objectid);
CREATE INDEX IF NOT EXISTS idx_changelog_changed_at ON changelog (changed_at);
CREATE INDEX IF NOT EXISTS idx_changelog_change_type ON changelog (change_type);
CREATE INDEX IF NOT EXISTS idx_changelog_sync_run ON changelog (sync_run_id);

-- Raster catalog unique constraint
CREATE UNIQUE INDEX IF NOT EXISTS idx_raster_catalog_url_unique ON raster_catalog (url_georef);

-- is_deleted partial indexes for efficient filtered queries
DO $$
DECLARE tbl RECORD;
BEGIN
    FOR tbl IN
        SELECT table_name FROM information_schema.columns
        WHERE table_schema = 'epoleodomia' AND column_name = 'is_deleted'
        AND table_name NOT IN ('sync_log', 'sync_runs', 'changelog', 'raster_catalog')
    LOOP
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS idx_%I_active ON epoleodomia.%I (is_deleted) WHERE is_deleted = FALSE',
            tbl.table_name, tbl.table_name
        );
    END LOOP;
END $$;

-- ============================================================================
SELECT 'v1.1 schema created successfully' AS status;
-- ============================================================================
