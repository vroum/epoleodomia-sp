"""
Configuration for TEE ArcGIS REST Services data sync to PostGIS

v1.1 — Credentials loaded from .env file (never committed to source control)
"""

from settings import SETTINGS

# ---------------------------------------------------------------------------
# Spetses bounding box in EPSG:2100 (GGRS87)
# ---------------------------------------------------------------------------
SPETSES_BBOX = {
    "xmin": 416555,
    "ymin": 4116249,
    "xmax": 431409,
    "ymax": 4129267,
    "spatialReference": {"wkid": 2100}
}

# ---------------------------------------------------------------------------
# Database connection — reads from environment / .env
# ---------------------------------------------------------------------------
DATABASE = dict(SETTINGS.database.connection_kwargs(), schema=SETTINGS.database.schema)

# ---------------------------------------------------------------------------
# Base URLs for ArcGIS REST services
# ---------------------------------------------------------------------------
BASE_URL = "https://sdigmap.tee.gov.gr/mapping/rest/services/UDM"

# ---------------------------------------------------------------------------
# Service definitions with their layers
# ---------------------------------------------------------------------------
SERVICES = {
    # Urban Planning (UDM_SERVICE_POLEODOMIKI_PLIROFORIA)
    "UDM_SERVICE_POLEODOMIKI_PLIROFORIA": {
        "url": f"{BASE_URL}/UDM_SERVICE_POLEODOMIKI_PLIROFORIA/MapServer",
        "layers": [
            {"id": 1, "table": "shorelines", "geom_type": "LineString"},
            {"id": 2, "table": "protected_buildings", "geom_type": "Point"},
            {"id": 3, "table": "settlement_boundaries", "geom_type": "Polygon"},
            {"id": 4, "table": "block_vertices", "geom_type": "Point"},
            {"id": 5, "table": "other_planning_zones", "geom_type": "Polygon"},
            {"id": 6, "table": "building_blocks", "geom_type": "Polygon"},
            {"id": 7, "table": "streams", "geom_type": "LineString"},
            {"id": 8, "table": "pedestrian_zones", "geom_type": "Polygon"},
            {"id": 9, "table": "outside_plan_areas", "geom_type": "Polygon"},
            {"id": 11, "table": "planning_lines", "geom_type": "LineString"},
            {"id": 12, "table": "building_lines", "geom_type": "LineString"},
            {"id": 13, "table": "other_planning_lines", "geom_type": "LineString"},
            {"id": 14, "table": "urban_units", "geom_type": "Polygon"},
            {"id": 16, "table": "building_regs_height", "geom_type": "Polygon"},
            {"id": 17, "table": "building_regs_lot", "geom_type": "Polygon"},
            {"id": 18, "table": "building_regs_coverage", "geom_type": "Polygon"},
            {"id": 19, "table": "building_regs_system", "geom_type": "Polygon"},
            {"id": 20, "table": "building_regs_coefficient", "geom_type": "Polygon"},
            {"id": 21, "table": "land_uses_ers", "geom_type": "Polygon"},
            {"id": 22, "table": "public_spaces", "geom_type": "Polygon"},
            {"id": 23, "table": "archaeological_zones_pl", "geom_type": "Polygon"},
            {"id": 24, "table": "expropriation_zones", "geom_type": "Polygon"},
            {"id": 26, "table": "land_uses_gps", "geom_type": "Polygon"},
        ]
    },

    # Addresses (UDM_SERVICE_BUILDINGS)
    "UDM_SERVICE_BUILDINGS": {
        "url": f"{BASE_URL}/UDM_SERVICE_BUILDINGS/MapServer",
        "layers": [
            {"id": 1, "table": "addresses", "geom_type": "Point"},
        ]
    },

    # Planning Diagrams (UDM_SERVICE_SXEDIA_DOCS)
    "UDM_SERVICE_SXEDIA_DOCS": {
        "url": f"{BASE_URL}/UDM_SERVICE_SXEDIA_DOCS/MapServer",
        "layers": [
            {"id": 0, "table": "planning_diagrams", "geom_type": "Polygon"},
        ]
    },

    # Approved Plans (UDM_SERVICE_POLEOD_RYM_SXD)
    "UDM_SERVICE_POLEOD_RYM_SXD": {
        "url": f"{BASE_URL}/UDM_SERVICE_POLEOD_RYM_SXD/MapServer",
        "layers": [
            {"id": 0, "table": "approved_plan_boundaries", "geom_type": "Polygon"},
        ]
    },

    # Archaeological (UDM_SERVICE_ARCHAIOLOGIKO)
    "UDM_SERVICE_ARCHAIOLOGIKO": {
        "url": f"{BASE_URL}/UDM_SERVICE_ARCHAIOLOGIKO/MapServer",
        "layers": [
            {"id": 1, "table": "monuments_points", "geom_type": "Point"},
            {"id": 2, "table": "monuments_lines", "geom_type": "LineString"},
            {"id": 3, "table": "monuments_polygons", "geom_type": "Polygon"},
            {"id": 5, "table": "protection_zones_points", "geom_type": "Point"},
            {"id": 6, "table": "protection_zones_lines", "geom_type": "LineString"},
            {"id": 7, "table": "protection_zones_polygons", "geom_type": "Polygon"},
            {"id": 9, "table": "historic_sites_points", "geom_type": "Point"},
            {"id": 10, "table": "historic_sites_lines", "geom_type": "LineString"},
            {"id": 11, "table": "historic_sites_polygons", "geom_type": "Polygon"},
            {"id": 13, "table": "archaeological_sites_points", "geom_type": "Point"},
            {"id": 14, "table": "archaeological_sites_lines", "geom_type": "LineString"},
            {"id": 15, "table": "archaeological_sites_polygons", "geom_type": "Polygon"},
            {"id": 17, "table": "natural_landscapes_points", "geom_type": "Point"},
            {"id": 18, "table": "natural_landscapes_polygons", "geom_type": "Polygon"},
        ]
    },

    # Natura & Forest (UDM_SERVICE_NATURA_DASIKA)
    "UDM_SERVICE_NATURA_DASIKA": {
        "url": f"{BASE_URL}/UDM_SERVICE_NATURA_DASIKA/MapServer",
        "layers": [
            {"id": 0, "table": "natura_2000", "geom_type": "Polygon"},
            # Spetses is in Attica region — layer 3 (μερικώς κυρωμένοι)
            {"id": 3, "table": "forest_maps", "geom_type": "Polygon", "extra": {"region_name": "Attica"}},
            # Αναρτημένοι (posted/draft) forest maps
            {"id": 26, "table": "forest_maps_posted_pelop_2022", "geom_type": "Polygon"},
            {"id": 31, "table": "forest_maps_posted_attica_2021", "geom_type": "Polygon"},
        ]
    },

    # Rural Regulations (UDM_SERVICE_RYTHMISEIS_EXOASTIKOU_CHOROU)
    "UDM_SERVICE_RYTHMISEIS_EXOASTIKOU_CHOROU": {
        "url": f"{BASE_URL}/UDM_SERVICE_RYTHMISEIS_EXOASTIKOU_CHOROU/MapServer",
        "layers": [
            {"id": 1, "table": "zoe_zones", "geom_type": "Polygon"},
            {"id": 3, "table": "pd_protection_zones", "geom_type": "Polygon"},
            {"id": 4, "table": "ab_zones_attica", "geom_type": "Polygon"},
            {"id": 5, "table": "streams_environmental", "geom_type": "LineString"},
        ]
    },

    # FEK without diagrams (UDM_SERVICE_FEK_NO_SXEDIA_DOCS)
    "UDM_SERVICE_FEK_NO_SXEDIA_DOCS": {
        "url": f"{BASE_URL}/UDM_SERVICE_FEK_NO_SXEDIA_DOCS/MapServer",
        "layers": [
            {"id": 0, "table": "fek_no_diagrams", "geom_type": "Polygon"},
        ]
    },

    # Urban Planning Data service (UDM_SERVICE_YPD)
    "UDM_SERVICE_YPD": {
        "url": f"{BASE_URL}/UDM_SERVICE_YPD/MapServer",
        "layers": [
            {"id": 20, "table": "building_regs_coefficient_zones", "geom_type": "Polygon"},
        ]
    },

    # Administrative (UDM_SERVICE_ELSTAT)
    "UDM_SERVICE_ELSTAT": {
        "url": f"{BASE_URL}/UDM_SERVICE_ELSTAT/MapServer",
        "layers": [
            {"id": 0, "table": "municipalities_2021", "geom_type": "Polygon"},
            {"id": 5, "table": "municipal_units_2021", "geom_type": "Polygon"},
            {"id": 6, "table": "municipal_communities_2021", "geom_type": "Polygon"},
            {"id": 18, "table": "settlements_2021", "geom_type": "Point"},
            {"id": 20, "table": "census_blocks_2021", "geom_type": "Polygon"},
        ]
    },
}

# ---------------------------------------------------------------------------
# Field mappings: ArcGIS field name → PostgreSQL column name
# ---------------------------------------------------------------------------
FIELD_MAPPINGS = {
    # Common fields
    "OBJECTID": "objectid",
    "OBJECTID_1": "objectid",
    "FEK": "fek",
    "FEK_FILE_URL": "fek_file_url",
    "PUBL_DATE": "publ_date",
    "APOF_EIDOS": "apof_eidos",
    "TITLE": "title",
    "NUMBER_": "number_",
    "SIGN_DATE": "sign_date",
    "KALL_DHM_NAME": "kall_dhm_name",
    "KEY_FLAG": "key_flag",
    "GEOREF_DIAGRAM_URL": "georef_diagram_url",
    "INITIAL_DIAGRAM_URL": "initial_diagram_url",

    # Shorelines (Layer 1)
    "LINE_NAME": "line_name",
    "LINE_TYPE_AIGIAL_PARALIA": "line_type_aigial_paralia",

    # Protected Buildings (Layer 2)
    "EIDOSFEK": "eidosfek",
    "TYPE": "type",
    "THESMKAT": "thesmkat",
    "ODOS": "odos",
    "THESI": "thesi",
    "X": "x",
    "Y": "y",
    "APOF_NUMBER": "apof_number",

    # Settlement Boundaries (Layer 3)
    "NAME": "name",

    # Block Vertices (Layer 4)
    "OT_KORYF_NAME": "ot_koryf_name",
    "X_COORD": "x_coord",
    "Y_COORD": "y_coord",
    "KEY_AUTO": "key_auto",

    # Other Planning Zones (Layer 5)
    "ZONE_NAME": "zone_name",
    "ZONE_TYPE": "zone_type",

    # Building Blocks (Layer 6)
    "OT_NUM": "ot_num",

    # Pedestrian Zones (Layer 8)
    "PZ_XRHSH": "pz_xrhsh",

    # Outside Plan Areas (Layer 9)
    "TEXT": "text",

    # Planning Lines (Layer 11)
    "ROAD_WIDTH": "road_width",
    "PRASIA_WIDTH": "prasia_width",
    "RG_TYPE": "rg_type",

    # Building Lines (Layer 12)
    "OG_TYPE": "og_type",
    "RN": "rn",
    "SHAPE.LEN": "shape_len",

    # Other Planning Lines (Layer 13)
    "POL_GR_TYPE": "pol_gr_type",

    # Urban Units (Layer 14)
    "PL_AREA_TYPE": "pl_area_type",

    # Building Regs Height (Layer 16)
    "MAX_HEIGHT_M": "max_height_m",
    "OROR_MAX_HEIGHT_COMMENT": "oror_max_height_comment",
    "NUM_OROFON": "num_orofon",
    "OROR_NUM_OROFON_COMMENT": "oror_num_orofon_comment",
    "SYNTHIKI_TXT": "synthiki_txt",

    # Building Regs Lot (Layer 17)
    "ARTIOTHTA_M2": "artiothta_m2",
    "ARTIOTHTA_COMMENT": "artiothta_comment",
    "PROSOPSI_M": "prosopsi_m",
    "PROSOPSI_COMMENT": "prosopsi_comment",
    "ELAX_EMBADO_M2": "elax_embado_m2",
    "ELAX_PROSOP_M": "elax_prosop_m",
    "OROS_TYPE": "oros_type",
    "DATE_PAREKLISIS": "date_pareklisis",

    # Building Regs Coverage (Layer 18)
    "KALYPSI_PCT": "kalypsi_pct",
    "KALYPSI_COMMENT": "kalypsi_comment",
    "SYNT_KALYPSIS": "synt_kalypsis",
    "MAX_EMBADO_M2": "max_embado_m2",

    # Building Regs System (Layer 19)
    "OIK_SYSTIMA": "oik_systima",
    "OIK_SYSTIMA_COMMENT": "oik_systima_comment",

    # Building Regs Coefficient (Layer 20)
    "SYNTELESTHS_DOMHSHS": "syntelesths_domhshs",
    "SD_COMMENT": "sd_comment",
    "SD_TIMH": "sd_timh",
    "SD_TOMEAS": "sd_tomeas",
    "SD_KLIMAKOTOS": "sd_klimakotos",

    # Land Uses (Layers 21, 26)
    "GEN_XRHSH_FLAG": "gen_xrhsh_flag",
    "GEN_XRHSH_GPS": "gen_xrhsh_gps",
    "GEN_XRHSH": "per_cat_gen",
    "EPXR_COMMENT": "per_cat_eid",
    "PER_CAT_GEN": "per_cat_gen",
    "PER_CAT_EID": "per_cat_eid",
    "REMARK": "remarks",
    "REMARKS": "remarks",
    "EIDIKH_CODED_DELIM_VALUES": "eidikh_coded_delim_values",

    # Public Spaces (Layer 22)
    "KX_KOINOXR_KODIKOS": "kx_koinoxr_kodikos",
    "KX_KOINOXR_TYPE": "kx_koinoxr_type",
    "EID_XRHSH_TXT": "kx_koinoxr_type",

    # Planning Diagrams
    "COMP_DIAGR_LEGEND_NUMBER": "comp_diagr_legend_number",
    "INIT_DIAGR_SCALE_DENOMINATOR": "init_diagr_scale_denominator",
    "GGRS87_DIAGR_GEOREF_RMS": "ggrs87_diagr_georef_rms",

    # Addresses
    "ADDR": "addr",
    "NUM": "num",
    "MUNIC": "munic",

    # Archaeological
    "OTA": "ota",
    "FOREAS": "foreas",
    "SHAPE.AREA": "shape_area",

    # Forest Maps (Natura/Dasika Layer 3)
    "CODE": "forest_code",
    "NOMOS": "nomos",
    "KATHGORDX": "forest_type",
    "KATHGORAL1": "kathgoral1",
    "KATHGORAL2": "kathgoral2",

    # Natura
    "SITECODE": "sitecode",
    "SITENAME": "sitename",
    "SITETYPE": "sitetype",
    "AREA_HA": "area_ha",

    # ELSTAT
    "YPES_CODE": "ypes_code",
    "YPES_NAME": "ypes_name",
    "POP_2021": "pop_2021",
    "ELSTAT_CODE": "elstat_code",
    "BLOCK_CODE": "block_code",
    "HOUSEHOLDS_2021": "households_2021",
    "NAME_GR": "ypes_name",
    "LAU_LABEL3": "ypes_name",
    "OIKISMOS": "name",
    "GLOBALID": "globalid",

    # Approved Plan Boundaries / FEK No Diagrams
    "APOF_THEME": "apof_theme",
    "DIAGRAM_CAT": "diagram_cat",

    # Posted forest maps area fields (vary by region layer)
    "GISDATA.PER_PELOPONNHSOY.AREA": "area_m2",
    "GISDATA.PER_ATTIKHS_2021.AREA": "area_m2",
    "GISDATA.PER_ATTIKHS_KYROSH.AREA": "area_m2",
}

# ---------------------------------------------------------------------------
# Query parameters
# ---------------------------------------------------------------------------
MAX_RECORDS_PER_REQUEST = 2000
REQUEST_TIMEOUT = 60  # seconds
