-- Versioned fresh-install baseline. Execute only through database_setup.py.
-- Fixed target: epoleodomia. Requires PostGIS already installed.
-- No existing table/view/function is dropped or replaced. Existing installations
-- must be structurally inspected and explicitly adopted instead of replayed.
-- Never edit an applied migration; add a new numbered file for future changes.

-- ============================================================================
-- TEE Urban Planning Data Mirror — Spetses Island
-- Schema: epoleodomia  |  CRS: EPSG:2100 (GGRS87)
-- v1.1 — Consolidated DDL (all migrations merged)
--
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS epoleodomia;
SET LOCAL search_path TO epoleodomia, public;

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
CREATE TABLE building_regs_lot (
    id SERIAL PRIMARY KEY,
    objectid INTEGER,
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
CREATE TABLE monuments_points (
    id SERIAL PRIMARY KEY, objectid INTEGER UNIQUE,
    name VARCHAR(500), ota VARCHAR(500), foreas VARCHAR(500),
    geom GEOMETRY(Point, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(), created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP, is_deleted BOOLEAN DEFAULT FALSE, deleted_at TIMESTAMP
);

CREATE TABLE monuments_lines (
    id SERIAL PRIMARY KEY, objectid INTEGER UNIQUE,
    name VARCHAR(500), ota VARCHAR(500), foreas VARCHAR(500), shape_len DOUBLE PRECISION,
    geom GEOMETRY(LineString, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(), created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP, is_deleted BOOLEAN DEFAULT FALSE, deleted_at TIMESTAMP
);

CREATE TABLE monuments_polygons (
    id SERIAL PRIMARY KEY, objectid INTEGER UNIQUE,
    name VARCHAR(500), ota VARCHAR(500), foreas VARCHAR(500),
    shape_area DOUBLE PRECISION, shape_len DOUBLE PRECISION,
    geom GEOMETRY(Polygon, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(), created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP, is_deleted BOOLEAN DEFAULT FALSE, deleted_at TIMESTAMP
);

-- Protection Zones
CREATE TABLE protection_zones_points (
    id SERIAL PRIMARY KEY, objectid INTEGER UNIQUE,
    name VARCHAR(500), ota VARCHAR(500), foreas VARCHAR(500),
    geom GEOMETRY(Point, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(), created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP, is_deleted BOOLEAN DEFAULT FALSE, deleted_at TIMESTAMP
);

CREATE TABLE protection_zones_lines (
    id SERIAL PRIMARY KEY, objectid INTEGER UNIQUE,
    name VARCHAR(500), ota VARCHAR(500), foreas VARCHAR(500), shape_len DOUBLE PRECISION,
    geom GEOMETRY(LineString, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(), created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP, is_deleted BOOLEAN DEFAULT FALSE, deleted_at TIMESTAMP
);

CREATE TABLE protection_zones_polygons (
    id SERIAL PRIMARY KEY, objectid INTEGER UNIQUE,
    name VARCHAR(500), ota VARCHAR(500), foreas VARCHAR(500),
    shape_area DOUBLE PRECISION, shape_len DOUBLE PRECISION,
    geom GEOMETRY(Polygon, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(), created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP, is_deleted BOOLEAN DEFAULT FALSE, deleted_at TIMESTAMP
);

-- Historic Sites
CREATE TABLE historic_sites_points (
    id SERIAL PRIMARY KEY, objectid INTEGER UNIQUE,
    name VARCHAR(500), ota VARCHAR(500), foreas VARCHAR(500),
    geom GEOMETRY(Point, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(), created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP, is_deleted BOOLEAN DEFAULT FALSE, deleted_at TIMESTAMP
);

CREATE TABLE historic_sites_lines (
    id SERIAL PRIMARY KEY, objectid INTEGER UNIQUE,
    name VARCHAR(500), ota VARCHAR(500), foreas VARCHAR(500), shape_len DOUBLE PRECISION,
    geom GEOMETRY(LineString, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(), created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP, is_deleted BOOLEAN DEFAULT FALSE, deleted_at TIMESTAMP
);

CREATE TABLE historic_sites_polygons (
    id SERIAL PRIMARY KEY, objectid INTEGER UNIQUE,
    name VARCHAR(500), ota VARCHAR(500), foreas VARCHAR(500),
    shape_area DOUBLE PRECISION, shape_len DOUBLE PRECISION,
    geom GEOMETRY(Polygon, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(), created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP, is_deleted BOOLEAN DEFAULT FALSE, deleted_at TIMESTAMP
);

-- Archaeological Sites
CREATE TABLE archaeological_sites_points (
    id SERIAL PRIMARY KEY, objectid INTEGER UNIQUE,
    name VARCHAR(500), ota VARCHAR(500), foreas VARCHAR(500),
    geom GEOMETRY(Point, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(), created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP, is_deleted BOOLEAN DEFAULT FALSE, deleted_at TIMESTAMP
);

CREATE TABLE archaeological_sites_lines (
    id SERIAL PRIMARY KEY, objectid INTEGER UNIQUE,
    name VARCHAR(500), ota VARCHAR(500), foreas VARCHAR(500), shape_len DOUBLE PRECISION,
    geom GEOMETRY(LineString, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(), created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP, is_deleted BOOLEAN DEFAULT FALSE, deleted_at TIMESTAMP
);

CREATE TABLE archaeological_sites_polygons (
    id SERIAL PRIMARY KEY, objectid INTEGER UNIQUE,
    name VARCHAR(500), ota VARCHAR(500), foreas VARCHAR(500),
    shape_area DOUBLE PRECISION, shape_len DOUBLE PRECISION,
    geom GEOMETRY(Polygon, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(), created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP, is_deleted BOOLEAN DEFAULT FALSE, deleted_at TIMESTAMP
);

-- Natural Landscapes
CREATE TABLE natural_landscapes_points (
    id SERIAL PRIMARY KEY, objectid INTEGER UNIQUE,
    name VARCHAR(500), ota VARCHAR(500), foreas VARCHAR(500),
    geom GEOMETRY(Point, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(), created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP, is_deleted BOOLEAN DEFAULT FALSE, deleted_at TIMESTAMP
);

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

CREATE TABLE natura_2000 (
    id SERIAL PRIMARY KEY, objectid INTEGER UNIQUE,
    sitecode VARCHAR(50), sitename VARCHAR(500), sitetype VARCHAR(50), area_ha DOUBLE PRECISION,
    geom GEOMETRY(Polygon, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(), created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP, is_deleted BOOLEAN DEFAULT FALSE, deleted_at TIMESTAMP
);

-- Ratified forest maps (Layer 3 — Attica)
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

CREATE TABLE zoe_zones (
    id SERIAL PRIMARY KEY, objectid INTEGER UNIQUE,
    fek VARCHAR(255), fek_file_url VARCHAR(2000),
    zone_name VARCHAR(255), zone_type VARCHAR(255),
    geom GEOMETRY(Polygon, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(), created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP, is_deleted BOOLEAN DEFAULT FALSE, deleted_at TIMESTAMP
);

CREATE TABLE pd_protection_zones (
    id SERIAL PRIMARY KEY, objectid INTEGER UNIQUE,
    fek VARCHAR(255), fek_file_url VARCHAR(2000),
    zone_name VARCHAR(255), protection_type VARCHAR(255),
    geom GEOMETRY(Polygon, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(), created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP, is_deleted BOOLEAN DEFAULT FALSE, deleted_at TIMESTAMP
);

CREATE TABLE ab_zones_attica (
    id SERIAL PRIMARY KEY, objectid INTEGER UNIQUE,
    zone_type VARCHAR(50), zone_name VARCHAR(255),
    geom GEOMETRY(Polygon, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(), created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP, is_deleted BOOLEAN DEFAULT FALSE, deleted_at TIMESTAMP
);

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

CREATE TABLE municipalities_2021 (
    id SERIAL PRIMARY KEY, objectid INTEGER UNIQUE,
    ypes_code VARCHAR(20), ypes_name VARCHAR(255), pop_2021 INTEGER,
    geom GEOMETRY(Polygon, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(), created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP, is_deleted BOOLEAN DEFAULT FALSE, deleted_at TIMESTAMP
);

CREATE TABLE municipal_units_2021 (
    id SERIAL PRIMARY KEY, objectid INTEGER UNIQUE,
    ypes_code VARCHAR(20), ypes_name VARCHAR(255), pop_2021 INTEGER,
    globalid VARCHAR(50),
    geom GEOMETRY(Polygon, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(), created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP, is_deleted BOOLEAN DEFAULT FALSE, deleted_at TIMESTAMP
);

CREATE TABLE municipal_communities_2021 (
    id SERIAL PRIMARY KEY, objectid INTEGER UNIQUE,
    ypes_code VARCHAR(20), ypes_name VARCHAR(255), pop_2021 INTEGER,
    geom GEOMETRY(Polygon, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(), created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP, is_deleted BOOLEAN DEFAULT FALSE, deleted_at TIMESTAMP
);

CREATE TABLE settlements_2021 (
    id SERIAL PRIMARY KEY, objectid INTEGER UNIQUE,
    elstat_code VARCHAR(20), name VARCHAR(255), pop_2021 INTEGER,
    geom GEOMETRY(Point, 2100),
    fetched_at TIMESTAMP DEFAULT NOW(), created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP, is_deleted BOOLEAN DEFAULT FALSE, deleted_at TIMESTAMP
);

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

-- ============================================================================
-- TEE Urban Planning Data Mirror — Views
-- v1.1 — All views consolidated and corrected
--
-- ============================================================================

SET LOCAL search_path TO epoleodomia, public;

-- ============================================================================
-- PRIMARY VIEW: Building blocks with all regulations + zone fallback
-- ============================================================================
CREATE VIEW v_building_blocks_regulations AS
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
CREATE VIEW v_addresses_with_blocks AS
SELECT
    a.id, a.addr AS address, a.num AS number, a.munic AS municipality,
    b.ot_num AS block_number, b.fek AS block_fek,
    a.geom, a.fetched_at
FROM addresses a
LEFT JOIN building_blocks b ON ST_Within(a.geom, b.geom);

-- ============================================================================
-- Land uses summary (FIXED: uses per_cat_gen not gen_xrhsh_gps for ERS)
-- ============================================================================
CREATE VIEW v_land_uses_summary AS
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
CREATE VIEW v_protected_areas AS
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
CREATE VIEW v_planning_lines_all AS
SELECT 'planning' AS line_type, rg_type AS subtype, fek, road_width, prasia_width, kall_dhm_name AS municipality, geom FROM planning_lines
UNION ALL
SELECT 'building', og_type, fek, NULL, prasia_width, kall_dhm_name, geom FROM building_lines
UNION ALL
SELECT 'other', pol_gr_type, fek, NULL, NULL, kall_dhm_name, geom FROM other_planning_lines;

-- ============================================================================
-- FEK reference lookup (normalized)
-- ============================================================================
CREATE VIEW v_fek_references AS
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
CREATE VIEW v_sync_status AS
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

CREATE VIEW v_recent_changes AS
SELECT c.changed_at, c.table_name, c.objectid, c.change_type, c.changed_fields, c.new_fek,
       sr.started_at AS sync_run_date
FROM changelog c LEFT JOIN sync_runs sr ON c.sync_run_id = sr.id
ORDER BY c.changed_at DESC;

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

CREATE VIEW v_fek_changes AS
SELECT c.changed_at, c.table_name, c.objectid, c.old_fek, c.new_fek, c.change_type
FROM changelog c
WHERE c.old_fek IS DISTINCT FROM c.new_fek AND (c.old_fek IS NOT NULL OR c.new_fek IS NOT NULL)
ORDER BY c.changed_at DESC;

CREATE VIEW v_geometry_changes AS
SELECT c.changed_at, c.table_name, c.objectid, c.change_type,
       c.old_geom_wkt, c.new_geom_wkt, sr.started_at AS sync_run_date
FROM changelog c LEFT JOIN sync_runs sr ON c.sync_run_id = sr.id
WHERE c.geometry_changed = TRUE
ORDER BY c.changed_at DESC;

CREATE VIEW v_regulation_changes AS
SELECT c.changed_at, c.table_name, c.objectid, c.change_type, c.changed_fields,
       c.old_values, c.new_values, c.old_fek, c.new_fek
FROM changelog c
WHERE c.table_name IN ('building_regs_height','building_regs_coverage','building_regs_coefficient',
                        'building_regs_lot','building_regs_system','building_blocks')
ORDER BY c.changed_at DESC;

-- ============================================================================
-- Raster catalog views
-- ============================================================================

CREATE VIEW v_rasters_pending AS
SELECT id, fek, filename, url_georef, georef_rms, original_scale
FROM raster_catalog WHERE download_status = 'pending' ORDER BY fek, filename;

CREATE VIEW v_rasters_downloaded AS
SELECT id, fek, filename, local_path_georef, file_size_bytes, width_px, height_px,
       resolution_x AS meters_per_pixel, crs_epsg, georef_rms, original_scale, downloaded_at,
       ST_AsText(bbox) AS bbox_wkt
FROM raster_catalog WHERE download_status = 'downloaded' ORDER BY fek, filename;

CREATE VIEW v_rasters_by_fek AS
SELECT fek, COUNT(*) AS total_rasters,
    COUNT(*) FILTER (WHERE download_status = 'downloaded') AS downloaded,
    COUNT(*) FILTER (WHERE download_status = 'pending') AS pending,
    COUNT(*) FILTER (WHERE download_status = 'failed') AS failed,
    ROUND(SUM(file_size_bytes) FILTER (WHERE download_status = 'downloaded') / 1024.0 / 1024.0, 2) AS total_size_mb
FROM raster_catalog GROUP BY fek ORDER BY fek;

CREATE VIEW v_rasters_failed AS
SELECT id, fek, filename, url_georef, download_error, last_checked
FROM raster_catalog WHERE download_status = 'failed' ORDER BY last_checked DESC;

-- ============================================================================
-- Function: Find rasters at a point
-- ============================================================================

CREATE FUNCTION find_rasters_at_point(x_coord NUMERIC, y_coord NUMERIC)
RETURNS TABLE (id INTEGER, fek VARCHAR, filename VARCHAR, local_path VARCHAR, resolution_m NUMERIC)
AS $$
BEGIN
    RETURN QUERY
    SELECT rc.id, rc.fek, rc.filename, rc.local_path_georef, rc.resolution_x
    FROM epoleodomia.raster_catalog rc
    WHERE rc.download_status = 'downloaded' AND rc.bbox IS NOT NULL
      AND ST_Contains(rc.bbox, ST_SetSRID(ST_MakePoint(x_coord, y_coord), 2100))
    ORDER BY rc.resolution_x;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
SELECT 'v1.1 views created successfully' AS status;
-- ============================================================================

-- Land Use Codes Lookup Table
-- Based on ΦΕΚ 27Α/1980 and later amendments
-- Run this in pgAdmin to create the lookup table


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

