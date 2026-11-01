"""
Epoleodomia GIS API Server for AutoCAD Civil 3D
================================================

FastAPI server that exposes PostGIS data for AutoCAD LISP consumption.
All spatial data uses EGSA '87 (EPSG:2100) coordinate system.

Data Sources:
-------------
  epoleodomia schema: Building blocks, planning lines, building regs, forest maps, raster catalog
  sp_geodata schema:  KAEK parcels, churches, streams, DJI/DE footprints, shoreline, archaeology

Usage:
------
  uvicorn api_server:app --host 0.0.0.0 --port 8000 --reload
"""

import logging
import os
import re
from contextlib import asynccontextmanager, contextmanager

import psycopg2
from psycopg2 import pool
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, JSONResponse
from starlette.concurrency import run_in_threadpool
from pathlib import PureWindowsPath

from boundary_corrections import (
    PARCEL_RELATION,
    SurveyInputError,
    calculate_boundary_correction,
    parse_survey_ring,
)
from cadastre_geometry import (
    is_special_kaek as _is_special_kaek,
    non_special_use_filter as _kaek_non_special_use_filter,
    wkt_to_coords as _wkt_to_coords,
)
from database_sessions import read_only_snapshot
from settings import SETTINGS
from raster_paths import resolve_fek_path
from planning_data import (
    PlanningData,
    POINT_REPORT_RELATIONS, PARCEL_REPORT_RELATIONS, OPTIONAL_REPORT_RELATIONS,
    WATER_RELATION,
    POINT_REF as _POINT_REF, PARCEL_REF as _PARCEL_REF,
    STREAM_LABELS as _REMATA_LABELS, STREAM_ORDER as _REMATA_ORDER,
    FOREST_TYPE_LABELS as _FOREST_TYPE_LABELS, decode_forest_type as _decode_forest_type,
)
from vertical_corrections import (
    VERTICAL_RELATIONS,
    calculate_vertical_correction,
    parse_vertical_survey,
)

from planning_reports import (
    SHORELINE_LABELS as _AIGIALOS_LABELS,
    water_point_label as _ydro_point_label,
)

# =============================================================================
# CONFIGURATION
# =============================================================================

DB_CONFIG = SETTINGS.database.connection_kwargs()

# Connection pool
db_pool: pool.SimpleConnectionPool = None

RASTER_BASE_PATH = SETTINGS.raster_base_path
DJI_RASTER_PATH = SETTINGS.dji_raster_path
FEK_LOCAL_PATH = SETTINGS.fek_local_path


def _catalog_raster_path(path, collection, filename=None):
    if collection != 'fek':
        return path.replace('/', '\\')
    name = filename or PureWindowsPath(path).name
    target = resolve_fek_path(RASTER_BASE_PATH, name, path)
    if not target.is_file() and FEK_LOCAL_PATH != RASTER_BASE_PATH:
        legacy = resolve_fek_path(FEK_LOCAL_PATH, name)
        if legacy.is_file():
            return str(legacy)
    return str(target)


def _download_fek_file(url, local_path):
    """The API writes files only; its database connection remains reader-only."""
    from download_rasters import download_file, extract_raster_metadata, require_rasterio
    from pathlib import Path
    require_rasterio()
    destination = Path(local_path)
    if destination.is_file():
        try:
            extract_raster_metadata(destination)
            return {'status': 'exists', 'path': str(destination)}
        except Exception:
            pass  # An invalid existing file must be replaced by a validated one.
    result = download_file(url, destination)
    if not result['success']:
        return {'status': 'error', 'message': result['error']}
    try:
        os.replace(result['staged_path'], destination)
        return {'status': 'downloaded', 'path': str(destination)}
    finally:
        result['staged_path'].unlink(missing_ok=True)

# =============================================================================
# LOGGING
# =============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# =============================================================================
# DATABASE CONNECTION POOL
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage database connection pool lifecycle."""
    global db_pool
    SETTINGS.database.require_password()
    logger.info("Creating database connection pool...")
    db_pool = pool.SimpleConnectionPool(
        minconn=1,
        maxconn=10,
        **DB_CONFIG
    )
    logger.info("Database pool created successfully")
    yield
    logger.info("Closing database connection pool...")
    if db_pool:
        db_pool.closeall()
    logger.info("Database pool closed")


def get_db_connection():
    """Get a connection from the pool."""
    return db_pool.getconn()


def release_db_connection(conn):
    """Return a connection to the pool."""
    db_pool.putconn(conn)


def execute_query(sql: str, params: tuple = None, fetch_one: bool = False):
    """Execute a query and return results."""
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(sql, params)
            if fetch_one:
                return cur.fetchone()
            return cur.fetchall()
    except Exception as e:
        logger.error(f"Query error: {e}")
        logger.error(f"SQL: {sql}")
        raise
    finally:
        if conn:
            release_db_connection(conn)


# =============================================================================
# PLANNING REPORT SESSION
# =============================================================================

@contextmanager
def _report_data(*, parcel=False):
    """Bind report collection to one protected snapshot and optional groups."""
    relations = PARCEL_REPORT_RELATIONS if parcel else POINT_REPORT_RELATIONS
    with read_only_snapshot(db_pool, protected_relations=relations,
                            optional_relations=OPTIONAL_REPORT_RELATIONS) as query:
        yield PlanningData(query, optional_scope=query.savepoint,
                           water_available=WATER_RELATION not in query.unavailable_relations)


# =============================================================================
# FASTAPI APP
# =============================================================================

app = FastAPI(
    title="Epoleodomia GIS API",
    description="PostGIS data API for AutoCAD Civil 3D",
    version="2.1.0",  # 2.1.0: added /report/parcel (parcel-based EREPORT)
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# HEALTH CHECK
# =============================================================================

@app.get("/health")
async def health_check():
    """Check API and database health."""
    try:
        result = execute_query("SELECT 1", fetch_one=True)
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}


# =============================================================================
# KAEK - CADASTRAL PARCELS (from sp_geodata)
# =============================================================================

def _get_kaek_data(x: float, y: float, include_neighbors: bool = True, radius: float = 50) -> dict:
    """
    Internal function to get cadastral parcel (KAEK) at a point with optional neighbors.
    Data from sp_geodata.Ανάρτηση_Κτηματολογιου
    """
    # Get main parcel
    main_sql = """
    SELECT
        kaek,
        shape_area,
        shape_leng,
        ST_AsText(geom) as geom_wkt
    FROM sp_geodata."Ανάρτηση_Κτηματολογιου"
    WHERE ST_Contains(geom, ST_SetSRID(ST_Point(%s, %s), 2100))
    LIMIT 1
    """

    main_parcel = execute_query(main_sql, (x, y), fetch_one=True)

    if not main_parcel:
        # Try radius search if point not inside any parcel
        radius_sql = """
        SELECT
            kaek,
            shape_area,
            shape_leng,
            ST_AsText(geom) as geom_wkt,
            ST_Distance(geom, ST_SetSRID(ST_Point(%s, %s), 2100)) as dist
        FROM sp_geodata."Ανάρτηση_Κτηματολογιου"
        WHERE ST_DWithin(geom, ST_SetSRID(ST_Point(%s, %s), 2100), %s)
        ORDER BY geom <-> ST_SetSRID(ST_Point(%s, %s), 2100)
        LIMIT 1
        """
        main_parcel = execute_query(radius_sql, (x, y, x, y, radius, x, y), fetch_one=True)

        if not main_parcel:
            return {"found": False, "message": "No KAEK parcel found at this location"}

    result = {
        "found": True,
        "kaek": main_parcel[0],
        "area_m2": round(main_parcel[1], 2) if main_parcel[1] else None,
        "perimeter_m": round(main_parcel[2], 2) if main_parcel[2] else None,
        "coords": _wkt_to_coords(main_parcel[3]),
        "neighbors": []
    }

    if include_neighbors and main_parcel[0]:
        # Get neighboring parcels (touching or within radius)
        neighbors_sql = """
        SELECT
            kaek,
            ST_AsText(geom) as geom_wkt
        FROM sp_geodata."Ανάρτηση_Κτηματολογιου"
        WHERE kaek != %s
          AND ST_DWithin(geom, ST_SetSRID(ST_Point(%s, %s), 2100), %s)
        ORDER BY geom <-> ST_SetSRID(ST_Point(%s, %s), 2100)
        LIMIT 20
        """
        neighbors = execute_query(neighbors_sql, (main_parcel[0], x, y, radius, x, y))

        for nb in neighbors:
            result["neighbors"].append({
                "kaek": nb[0],
                "coords": _wkt_to_coords(nb[1])
            })

    return result


@app.get("/kaek")
async def get_kaek(
    x: float = Query(..., description="X coordinate (EGSA '87)"),
    y: float = Query(..., description="Y coordinate (EGSA '87)"),
    include_neighbors: bool = Query(True, description="Include neighboring parcels"),
    radius: float = Query(50, description="Radius for neighbor search in meters")
):
    """
    Get cadastral parcel (KAEK) at a point with optional neighbors.
    Data from sp_geodata.Ανάρτηση_Κτηματολογιου
    """
    return _get_kaek_data(x, y, include_neighbors, radius)


def _get_parcel_rights(kaek: str) -> dict:
    return PlanningData(execute_query).get_parcel_rights(kaek=kaek)


def _get_ydrolipsies_data(x: float = None, y: float = None,
                          ref_geom: str = None, ref_args: tuple = None,
                          max_distance: float = 500) -> dict:
    return PlanningData(execute_query).get_water_points(
        x=x, y=y, ref_geom=ref_geom, ref_args=ref_args, max_distance=max_distance)


def _rights_ring_lines(kaek: str) -> list:
    """
    AX|num|coords / DX|num|coords lines for the LISP drawing protocol —
    one line per exterior ring of each ΑΧ/δουλεία polygon on the parcel.
    """
    lines = []
    for prefix, table, num_col in (
            ("AX", "sp_geodata.kaek_apokleistikes_operating", "vp_num"),
            ("DX", "sp_geodata.kaek_douleies_operating", "right_sn")):
        sql = f"""
        SELECT t.{num_col}, ST_AsText(ST_ExteriorRing(dp.geom))
        FROM {table} t, LATERAL ST_Dump(t.geom) AS dp
        WHERE t.kaek = %s
        ORDER BY t.{num_col}, ST_Area(dp.geom) DESC
        """
        for r in (execute_query(sql, (kaek,)) or []):
            coords = _wkt_to_coords(r[1])
            if coords:
                coord_str = ";".join([f"{c[0]},{c[1]}" for c in coords])
                lines.append(f"{prefix}|{r[0] or ''}|{coord_str}")
    return lines


@app.get("/kaek/simple", response_class=PlainTextResponse)
async def get_kaek_simple(
    x: float = Query(..., description="X coordinate (EGSA '87)"),
    y: float = Query(..., description="Y coordinate (EGSA '87)")
):
    """
    Get 1η Ανάρτηση KAEK parcel + neighbors in inline format for LISP.
    MultiPolygon-safe. EK parcels excluded. Neighbors found from parcel geometry.
    Format:
      OK|kaek|area_m2|perimeter_m
      MAIN|x1,y1;x2,y2;...  (one line per polygon ring, largest first)
      NB|x1,y1;x2,y2;...
    """
    TABLE = 'sp_geodata."Ανάρτηση_Κτηματολογιου"'
    EK_FILTER = _kaek_non_special_use_filter()
    NB_EK_FILTER = _kaek_non_special_use_filter("nb")

    def _rings(kaek_val: str) -> list[str]:
        sql = f"""
        SELECT ST_AsText(ST_ExteriorRing(dp.geom))
        FROM {TABLE} k,
             LATERAL ST_Dump(k.geom) AS dp
        WHERE k.kaek = %s
        ORDER BY ST_Area(dp.geom) DESC
        """
        rows = execute_query(sql, (kaek_val,))
        result = []
        for row in (rows or []):
            coords = _wkt_to_coords(row[0])
            if coords:
                result.append(";".join([f"{c[0]},{c[1]}" for c in coords]))
        return result

    # ── Find main parcel ──────────────────────────────────────────────────────
    main_sql = f"""
    SELECT
        kaek,
        ROUND(COALESCE(shape_area, ST_Area(geom))::numeric, 2),
        ROUND(COALESCE(shape_leng, ST_Perimeter(geom))::numeric, 2)
    FROM {TABLE}
    WHERE {EK_FILTER}
      AND ST_Contains(geom, ST_SetSRID(ST_Point(%s, %s), 2100))
    LIMIT 1
    """
    row = execute_query(main_sql, (x, y), fetch_one=True)

    if not row:
        near_sql = f"""
        SELECT
            kaek,
            ROUND(COALESCE(shape_area, ST_Area(geom))::numeric, 2),
            ROUND(COALESCE(shape_leng, ST_Perimeter(geom))::numeric, 2)
        FROM {TABLE}
        WHERE {EK_FILTER}
          AND ST_DWithin(geom, ST_SetSRID(ST_Point(%s, %s), 2100), 50)
        ORDER BY geom <-> ST_SetSRID(ST_Point(%s, %s), 2100)
        LIMIT 1
        """
        row = execute_query(near_sql, (x, y, x, y), fetch_one=True)

    if not row:
        return "ERROR|No KAEK parcel found"

    kaek, area_m2, perim_m = row
    lines = [f"OK|{kaek}|{area_m2}|{perim_m}"]

    for coord_str in _rings(kaek):
        lines.append(f"MAIN|{coord_str}")

    # ── Neighbors — from parcel geometry, not click point ─────────────────────
    nb_sql = f"""
    SELECT DISTINCT nb.kaek
    FROM {TABLE} main
    JOIN {TABLE} nb
      ON nb.kaek != main.kaek
     AND {NB_EK_FILTER}
     AND ST_DWithin(main.geom, nb.geom, 1)
    WHERE main.kaek = %s
    ORDER BY nb.kaek
    LIMIT 20
    """
    neighbors = execute_query(nb_sql, (kaek,))
    for nb in (neighbors or []):
        for coord_str in _rings(nb[0]):
            lines.append(f"NB|{coord_str}")

    # Δουλείες / αποκλειστικές χρήσεις on the parcel (operating overlay)
    lines.extend(_rights_ring_lines(kaek))

    return "\n".join(lines)


@app.get("/kaek/number", response_class=PlainTextResponse)
async def get_kaek_number(
    x: float = Query(..., description="X coordinate (EGSA '87)"),
    y: float = Query(..., description="Y coordinate (EGSA '87)")
):
    """
    Get only the KAEK number at a point (no geometry).
    Returns just the KAEK code string.
    """
    sql = """
    SELECT kaek
    FROM sp_geodata."Ανάρτηση_Κτηματολογιου"
    WHERE ST_Contains(geom, ST_SetSRID(ST_Point(%s, %s), 2100))
    LIMIT 1
    """
    result = execute_query(sql, (x, y), fetch_one=True)

    if result and result[0]:
        return result[0]
    else:
        return "NOT_FOUND"


@app.get("/kaek/operating", response_class=PlainTextResponse)
async def get_kaek_operating(
    x: float = Query(..., description="X coordinate (EGSA '87)"),
    y: float = Query(..., description="Y coordinate (EGSA '87)"),
    radius: float = Query(50, description="Radius for neighbor search in meters")
):
    """
    Get operating cadastre parcel (Hellenic Cadastre λειτουργία) at a point with neighbors.
    Data from sp_geodata.kaek_parcels_operating (synced from AGOL GEOTEMAXIA_LEITOURGOUN_ON_gdb).

    MultiPolygon-safe: uses ST_Dump + ST_ExteriorRing to split each parcel into individual
    polygon rings before serialising, so EK/multi-part parcels draw correctly in AutoCAD.

    Format:
      OK|kaek|area_m2|perimeter_m|main_use
      MAIN|x1,y1;x2,y2;...   (one line per polygon part, largest first)
      NB|x1,y1;x2,y2;...     (one line per polygon part of each neighbor)
    """
    def _rings_for_kaek(kaek_val: str) -> list[str]:
        """Return list of coord strings (x,y;x,y;...) for every exterior ring of a kaek,
        ordered largest-area first. Safe for POLYGON and MULTIPOLYGON."""
        sql = """
        SELECT ST_AsText(ST_ExteriorRing(dp.geom))
        FROM sp_geodata.kaek_parcels_operating k,
             LATERAL ST_Dump(k.geom) AS dp
        WHERE k.kaek = %s
        ORDER BY ST_Area(dp.geom) DESC
        """
        rows = execute_query(sql, (kaek_val,))
        result = []
        for row in (rows or []):
            coords = _wkt_to_coords(row[0])
            if coords:
                result.append(";".join([f"{c[0]},{c[1]}" for c in coords]))
        return result

    # EK (ειδική χρήση) parcels are large special-use zones (forest, beach, road)
    # that cause rendering issues — exclude them from all queries.
    EK_FILTER = _kaek_non_special_use_filter()
    NB_EK_FILTER = _kaek_non_special_use_filter("nb")

    # ── Find main parcel ──────────────────────────────────────────────────────
    main_sql = f"""
    SELECT
        kaek,
        ROUND(ST_Area(geom)::numeric, 2)      AS area_m2,
        ROUND(ST_Perimeter(geom)::numeric, 2) AS perimeter_m,
        main_use
    FROM sp_geodata.kaek_parcels_operating
    WHERE {EK_FILTER}
      AND ST_Contains(geom, ST_SetSRID(ST_Point(%s, %s), 2100))
    LIMIT 1
    """
    main_parcel = execute_query(main_sql, (x, y), fetch_one=True)

    if not main_parcel:
        near_sql = f"""
        SELECT
            kaek,
            ROUND(ST_Area(geom)::numeric, 2),
            ROUND(ST_Perimeter(geom)::numeric, 2),
            main_use
        FROM sp_geodata.kaek_parcels_operating
        WHERE {EK_FILTER}
          AND ST_DWithin(geom, ST_SetSRID(ST_Point(%s, %s), 2100), %s)
        ORDER BY geom <-> ST_SetSRID(ST_Point(%s, %s), 2100)
        LIMIT 1
        """
        main_parcel = execute_query(near_sql, (x, y, radius, x, y), fetch_one=True)

    if not main_parcel:
        return "ERROR|No operating cadastre parcel found (or clicked on EK parcel)"

    kaek, area_m2, perim_m, main_use = main_parcel
    main_use = main_use or ""

    lines = [f"OK|{kaek}|{area_m2}|{perim_m}|{main_use}"]

    # One MAIN| line per polygon ring (handles EK/multi-part parcels)
    for coord_str in _rings_for_kaek(kaek):
        lines.append(f"MAIN|{coord_str}")

    # ── Neighbors — search from the parcel's own geometry, not the click point ──
    # ST_DWithin with 1m tolerance catches touching/adjacent parcels regardless
    # of how far the user clicked from the edge.
    nb_sql = f"""
    SELECT DISTINCT nb.kaek
    FROM sp_geodata.kaek_parcels_operating main
    JOIN sp_geodata.kaek_parcels_operating nb
      ON nb.kaek != main.kaek
     AND {NB_EK_FILTER}
     AND ST_DWithin(main.geom, nb.geom, 1)
    WHERE main.kaek = %s
    ORDER BY nb.kaek
    LIMIT 20
    """
    neighbors = execute_query(nb_sql, (kaek,))
    for nb in (neighbors or []):
        for coord_str in _rings_for_kaek(nb[0]):
            lines.append(f"NB|{coord_str}")

    # Δουλείες / αποκλειστικές χρήσεις on the parcel (operating overlay)
    lines.extend(_rights_ring_lines(kaek))

    return "\n".join(lines)


@app.get("/kaek/pst", response_class=PlainTextResponse)
async def get_kaek_pst(
    x: float = Query(..., description="X coordinate (EGSA '87)"),
    y: float = Query(..., description="Y coordinate (EGSA '87)"),
    radius: float = Query(50, description="Neighbor search radius (m)")
):
    """
    PST_KAEK background for Κτηματολόγιο electronic diagrams (KPST command).
    Main parcel + neighbors with per-parcel KAEK tags, plus the main parcel's
    ΑΧ (→ VST_PST) and δουλείες (→ EAS_PST).

    Format:
      OK|main_kaek|n_parcels
      P|kaek|x,y;x,y;...      one line per exterior ring (largest ring first
                              per parcel — the first ring carries the label)
      V|num|coords            αποκλειστικές χρήσεις of the main parcel
      E|num|coords            δουλείες of the main parcel

    NOTE: αυθεντική πηγή για την υποβολή παραμένει το χορηγούμενο
    Κτηματογραφικό Διάγραμμα — εδώ σχεδιάζεται το συγχρονισμένο operating.
    """
    EK_FILTER = _kaek_non_special_use_filter()
    NB_EK_FILTER = _kaek_non_special_use_filter("nb")

    main_sql = f"""
    SELECT kaek FROM sp_geodata.kaek_parcels_operating
    WHERE {EK_FILTER}
      AND ST_Contains(geom, ST_SetSRID(ST_Point(%s, %s), 2100))
    LIMIT 1
    """
    row = execute_query(main_sql, (x, y), fetch_one=True)
    if not row:
        near_sql = f"""
        SELECT kaek FROM sp_geodata.kaek_parcels_operating
        WHERE {EK_FILTER}
          AND ST_DWithin(geom, ST_SetSRID(ST_Point(%s, %s), 2100), %s)
        ORDER BY geom <-> ST_SetSRID(ST_Point(%s, %s), 2100)
        LIMIT 1
        """
        row = execute_query(near_sql, (x, y, radius, x, y), fetch_one=True)
    if not row:
        return "ERROR|No operating cadastre parcel found (or clicked on EK parcel)"
    main_kaek = row[0]

    nb_sql = f"""
    SELECT DISTINCT nb.kaek
    FROM sp_geodata.kaek_parcels_operating main
    JOIN sp_geodata.kaek_parcels_operating nb
      ON nb.kaek != main.kaek
     AND {NB_EK_FILTER}
     AND ST_DWithin(main.geom, nb.geom, 1)
    WHERE main.kaek = %s
    ORDER BY nb.kaek
    LIMIT 30
    """
    neighbors = [r[0] for r in (execute_query(nb_sql, (main_kaek,)) or [])]
    parcels = [main_kaek] + neighbors

    lines = [f"OK|{main_kaek}|{len(parcels)}"]

    ring_sql = """
    SELECT ST_AsText(ST_ExteriorRing(dp.geom))
    FROM sp_geodata.kaek_parcels_operating k,
         LATERAL ST_Dump(k.geom) AS dp
    WHERE k.kaek = %s
    ORDER BY ST_Area(dp.geom) DESC
    """
    for pk in parcels:
        for r in (execute_query(ring_sql, (pk,)) or []):
            coords = _wkt_to_coords(r[0])
            if coords:
                lines.append(f"P|{pk}|" + ";".join(f"{c[0]},{c[1]}" for c in coords))

    # ΑΧ / δουλείες of the main parcel → VST_PST / EAS_PST helper layers
    for raw in _rights_ring_lines(main_kaek):
        prefix, num, coords = raw.split("|", 2)
        lines.append(("V" if prefix == "AX" else "E") + f"|{num}|{coords}")

    return "\n".join(lines)


# =============================================================================
# ΓΕΩ.Μ CORE — Διόρθωση ορίων γεωτεμαχίου (KGEOM command)
# =============================================================================


@app.post("/geom/diorthosi", response_class=PlainTextResponse)
async def geom_diorthosi(
    request: Request,
    tol: float = Query(0.5, description="Min piece area in m² (sliver filter)")
):
    """
    ΓΕΩ.Μ core: διόρθωση ορίων γεωτεμαχίου.
    Body (plain text): the surveyed TOPO_PROP ring as "x,y;x,y;...".

    Computes: subject parcel (positive max overlap), Δi = TOPO_PROP − subject
    split at source parcel boundaries, Αi = subject − TOPO_PROP (assigned to
    the neighbor with the longest positive shared boundary), τελικά γεωτεμάχια,
    ισοζύγιο εμβαδών and a μεταβολών table. Pieces smaller than `tol` m² are
    dropped as slivers (reported in the table note). Invalid survey polygons,
    overlapping/unmapped donor areas, unassigned cuts and drawable polygons
    with holes return ERROR rather than a partial drawing response.

    Response (windows-1253-safe, pipe protocol):
      OK|subject_kaek|tol
      D|Δi|from_kaek|area|coords      → layer AREA_D
      A|Αi|to_kaek|area|coords        → layer AREA_A
      F|kaek|area|coords              → layer DGM_PROP_FINAL (one per ring)
      TBL|TYPE|c1|c2                  → rows for epol:draw-table-rows
    """
    body = (await request.body()).decode("utf-8", errors="replace")
    try:
        survey = parse_survey_ring(body, tol)
    except SurveyInputError as exc:
        return f"ERROR|{exc}"

    with read_only_snapshot(db_pool, protected_relations=(PARCEL_RELATION,)) as query:
        return calculate_boundary_correction(survey, query)


@app.get("/aigialos/simple", response_class=PlainTextResponse)
async def get_aigialos_simple(
    minx: float = Query(...), miny: float = Query(...),
    maxx: float = Query(...), maxy: float = Query(...)
):
    """
    Υφιστάμενες οριογραμμές αιγιαλού/παραλίας/παλαιού αιγιαλού σε bbox,
    για την εντολή AIGDRAW. Πηγή: sp_geodata.Αιγιαλός_Παραλία (curated,
    πλήρη ΦΕΚ). Clipped στο bbox (+50μ buffer).

    Format:
      COUNT|n
      G|layer|label|x,y;x,y;...   (μία γραμμή ανά linestring)
    layer: DBOUND_AIG / DBOUND_PRL / DBOUND_PAIG (επίσημα ΠΙΝΑΚΑ Ι).
    """
    def _layer_for(info: str) -> str:
        if "Παλαιού" in info:
            return "DBOUND_PAIG"
        if "Παραλίας" in info:
            return "DBOUND_PRL"
        return "DBOUND_AIG"

    sql = """
    WITH env AS (
        SELECT ST_Expand(ST_MakeEnvelope(%s, %s, %s, %s, 2100), 50) AS e
    )
    SELECT a.info, a.fek, a.year,
           ST_AsText((ST_Dump(ST_CollectionExtract(
               ST_Intersection(ST_MakeValid(a.geom), env.e), 2))).geom)
    FROM sp_geodata."Αιγιαλός_Παραλία" a, env
    WHERE ST_Intersects(a.geom, env.e)
    ORDER BY a.info, a.year
    """
    rows = execute_query(sql, (minx, miny, maxx, maxy)) or []

    lines = []
    for info, fek, year, wkt in rows:
        coords = _wkt_to_coords(wkt)
        if not coords or len(coords) < 2:
            continue
        base = (info or "").replace("_ΠΟΑ", " (ΠΟΑ)")
        label = base
        if fek:
            label += f" — ΦΕΚ {fek}"
        elif year:
            label += f" — {year}"
        cs = ";".join(f"{c[0]},{c[1]}" for c in coords)
        lines.append(f"G|{_layer_for(info or '')}|{label}|{cs}")

    text = "\n".join([f"COUNT|{len(lines)}"] + lines)
    return text.encode('windows-1253', errors='replace').decode('windows-1253')


@app.post("/xytable", response_class=PlainTextResponse)
async def xytable(
    request: Request,
    label: str = Query("", description="Suffix for the table title (e.g. prefix)")
):
    """
    Πίνακας συντεταγμένων κορυφών (KVERT command).
    Body: one "name|x|y" line per vertex (x/y already formatted).
    Returns TBL| rows for epol:draw-table-rows — Greek text arrives correctly
    in AutoCAD via HTTP (unlike Greek literals inside the .lsp file).
    """
    body = (await request.body()).decode("utf-8", errors="replace").strip()
    if not body:
        return "ERROR|Empty body"

    rows = [f"TBL|TITLE|ΠΙΝΑΚΑΣ ΣΥΝΤΕΤΑΓΜΕΝΩΝ|{label}".rstrip("|"),
            "TBL|HEADER|Σημείο  —  Χ / Υ (ΕΓΣΑ '87, μ.)|"]
    n = 0
    for ln in body.splitlines():
        parts = ln.strip().split("|")
        if len(parts) >= 3:
            rows.append(f"TBL|ROW|{parts[0]}|{parts[1]}   {parts[2]}")
            n += 1
    if n == 0:
        return "ERROR|No vertex lines (name|x|y)"
    rows.append(f"TBL|ROW|Σύνολο κορυφών|{n}")

    text = "\n".join(rows)
    return text.encode('windows-1253', errors='replace').decode('windows-1253')


@app.post("/geom/kathetes", response_class=PlainTextResponse)
async def geom_kathetes(
    request: Request,
    tol: float = Query(0.5, description="Overlap/sliver tolerance in m²")
):
    """
    ΓΕΩ.Μ: διόρθωση καθέτων ιδιοκτησιών (ΔΓΜ για πράξη — όρια γεωτεμαχίου αμετάβλητα).

    Body (plain text), one line per surveyed κάθετη:
        V|vp_num|title_area|title_xiliosta|x,y;x,y;...
    Empty vp_num fields are auto-numbered; empty title fields mean unknown.

    Does: parent parcel by positive max overlap · VST_FINAL = clip στο γεωτεμάχιο ·
    αντιστοίχιση με κτηματολογικές ΑΧ (positive clipped overlap, mismatch warning) ·
    pairwise overlap check · κοινόχρηστο υπόλοιπο · LINE_XM_VST (εσωτερικές
    γραμμές, το περίγραμμα του γεωτεμαχίου αφαιρείται) · πίνακας
    τίτλος/κτηματολόγιο/αποτύπωση με χιλιοστά.

    Only retained verticals contribute to the common remainder/internal lines.
    Invalid input, duplicate labels and unsupported polygon holes return ERROR.
    All queries share one read-only snapshot protecting both cadastral tables.

    Response:  OK|kaek|parcel_area
               VF|num|area|coords     → VST_FINAL
               L|coords               → LINE_XM_VST (open)
               TBL|TYPE|c1|c2         → table rows
    """
    body = (await request.body()).decode("utf-8", errors="replace")
    try:
        survey = parse_vertical_survey(body, tol)
    except SurveyInputError as exc:
        return f"ERROR|{exc}"

    with read_only_snapshot(db_pool, protected_relations=VERTICAL_RELATIONS) as query:
        return calculate_vertical_correction(survey, query)


@app.get("/ot/number", response_class=PlainTextResponse)
async def get_ot_number(
    x: float = Query(..., description="X coordinate (EGSA '87)"),
    y: float = Query(..., description="Y coordinate (EGSA '87)")
):
    """
    Get only the OT (building block) number at a point (no geometry).
    Returns just the OT number string.
    """
    sql = """
    SELECT ot_num
    FROM epoleodomia.building_blocks
    WHERE NOT COALESCE(is_deleted, false)
      AND ST_Contains(geom, ST_SetSRID(ST_Point(%s, %s), 2100))
    LIMIT 1
    """
    result = execute_query(sql, (x, y), fetch_one=True)

    if result and result[0]:
        return str(result[0])
    else:
        return "NOT_FOUND"


# =============================================================================
# BUILDING REGULATIONS (from epoleodomia)
# =============================================================================

def _get_building_regulations_data(x: float, y: float) -> dict:
    """Internal function to get building regulations at a point.

    Uses the v_building_blocks_regulations view which joins:
    - building_blocks (base geometry, ot_num, fek)
    - building_regs_height (max_height_m, num_orofon, height_comment)
    - building_regs_coverage (coverage_pct, coverage_remarks)
    - building_regs_coefficient (building_coefficient, sd_tomeas, sd_klimakotos, coefficient_comment)
    - building_regs_lot (min_lot_size_m2, min_frontage_m, oros_type, date_pareklisis, lot_remarks)
    - building_regs_system (building_system)
    """
    # Single query from the updated view - all fields included
    sql = """
    SELECT
        ot_num,
        fek,
        fek_file_url,
        publ_date,
        max_height_m,
        num_orofon,
        height_comment,
        coverage_pct,
        coverage_remarks,
        building_coefficient,
        sd_tomeas,
        sd_klimakotos,
        coefficient_comment,
        min_lot_size_m2,
        min_frontage_m,
        oros_type,
        date_pareklisis,
        lot_remarks,
        building_system,
        ST_AsText(geom) as geom_wkt,
        ST_Area(geom) as area_m2
    FROM epoleodomia.v_building_blocks_regulations
    WHERE ST_Contains(geom, ST_SetSRID(ST_Point(%s, %s), 2100))
    LIMIT 1
    """

    result = execute_query(sql, (x, y), fetch_one=True)

    if not result:
        return {"found": False, "message": "No building regulations at this location"}

    data = {
        "found": True,
        "ot_num": result[0],
        "fek": result[1],
        "fek_url": result[2],
        "publ_date": result[3],
        # Height
        "max_height_m": result[4],
        "num_floors": result[5],
        "height_comment": result[6],
        # Coverage
        "coverage_pct": result[7],
        "coverage_remarks": result[8],
        # Coefficient
        "building_coefficient": result[9],
        "sd_tomeas": result[10],
        "sd_klimakotos": result[11],
        "coefficient_comment": result[12],
        # Lot
        "min_lot_size_m2": result[13],
        "min_frontage_m": result[14],
        "oros_type": result[15],
        "date_pareklisis": result[16],
        "lot_remarks": result[17],
        # System
        "building_system": result[18],
        # Geometry
        "area_m2": result[20],
        "coords": _wkt_to_coords(result[19]) if result[19] else None,
        # Land use - still need separate query
        "land_use_codes": None,
    }

    # Get land use from land_uses_ers (not in view)
    land_sql = """
    SELECT eidikh_coded_delim_values, gen_xrhsh_flag
    FROM epoleodomia.land_uses_ers
    WHERE NOT COALESCE(is_deleted, false)
      AND ST_Contains(geom, ST_SetSRID(ST_Point(%s, %s), 2100))
    LIMIT 1
    """
    land_result = execute_query(land_sql, (x, y), fetch_one=True)
    if land_result:
        codes = land_result[0]
        data["land_use_codes"] = codes
        # Translate codes to description
        data["land_use_description"] = _translate_land_use_codes(codes)

    return data


# Land use code lookup (ΦΕΚ 27Α/1980 classification)
LAND_USE_CODES = {
    '1': 'Κατοικία',
    '2': 'Κατοικία',
    '21': 'Αμιγής Κατοικία',
    '22': 'Γενική Κατοικία',
    '23': 'Πολεοδομικό Κέντρο',
    '24': 'Τουριστική Ζώνη',
    '211': 'Αμιγής Κατοικία',
    '212': 'Αμιγής Κατοικία',
    '221': 'Γενική Κατοικία',
    '222': 'Γενική Κατοικία',
    '3': 'Εμπόριο',
    '4': 'Βιομηχανία - Βιοτεχνία',
    '5': 'Αναψυχή - Πολιτισμός',
    '6': 'Κοινωφελείς Εξυπηρετήσεις',
    '7': 'Ελεύθεροι Χώροι - Πράσινο',
}


def _translate_land_use_codes(codes_str: str) -> str:
    """Translate land use codes (e.g., '21;22;211') to description."""
    if not codes_str:
        return None

    codes = [c.strip() for c in codes_str.split(';')]

    # Prefer 2-digit codes (main category)
    for code in codes:
        if len(code) == 2 and code in LAND_USE_CODES:
            return LAND_USE_CODES[code]

    # Fallback to first code found
    for code in codes:
        if code in LAND_USE_CODES:
            return LAND_USE_CODES[code]

    return None


@app.get("/oroi")
async def get_building_regulations(
    x: float = Query(..., description="X coordinate (EGSA '87)"),
    y: float = Query(..., description="Y coordinate (EGSA '87)")
):
    """
    Get all building regulations at a point.
    Data from epoleodomia.v_building_blocks_regulations
    """
    return _get_building_regulations_data(x, y)


@app.get("/oroi/text", response_class=PlainTextResponse)
async def get_building_regulations_text(
    x: float = Query(..., description="X coordinate (EGSA '87)"),
    y: float = Query(..., description="Y coordinate (EGSA '87)")
):
    """Get building regulations formatted as plain text for AutoCAD MTEXT."""
    data = _get_building_regulations_data(x, y)

    if not data.get("found"):
        return "Δεν βρέθηκαν όροι δόμησης"

    lines = [
        f"ΟΤ: {data.get('ot_num', '-')}",
        f"ΦΕΚ: {data.get('fek', '-')}",
    ]

    # Add tomeas if available
    if data.get('sd_tomeas'):
        lines.append(f"Τομέας: {data.get('sd_tomeas')}")

    # Core numeric values
    lines.extend([
        f"Ύψος: {data.get('max_height_m', '-')} m",
        f"Όροφοι: {data.get('num_floors', '-')}",
        f"Κάλυψη: {data.get('coverage_pct', '-')}%",
        f"ΣΔ: {data.get('building_coefficient', '-')}",
    ])

    # Add stepped coefficient if available
    if data.get('sd_klimakotos'):
        lines.append(f"Κλιμακωτός: {data.get('sd_klimakotos')}")

    # Lot requirements - handle ΚΑΤΑ ΚΑΝΟΝΑ vs ΚΑΤΑ ΠΑΡΕΚΚΛΙΣΗ
    oros_type = data.get('oros_type')
    if oros_type == 'ΚΑΤΑ ΚΑΝΟΝΑ':
        # Normal rules - show numeric values
        lines.append(f"Αρτιότητα: {data.get('min_lot_size_m2', '-')} m²")
        lines.append(f"Πρόσοψη: {data.get('min_frontage_m', '-')} m")
    elif oros_type == 'ΚΑΤΑ ΠΑΡΕΚΚΛΙΣΗ':
        # Exception rules - show remarks instead of None values
        lines.append("Αρτιότητα: ΚΑΤΑ ΠΑΡΕΚΚΛΙΣΗ")
        if data.get('lot_remarks'):
            lines.append(f"  {data.get('lot_remarks')}")
        if data.get('date_pareklisis'):
            lines.append(f"  Ημ/νία: {data.get('date_pareklisis')}")
    else:
        # Unknown or no oros_type - show values if available
        if data.get('min_lot_size_m2'):
            lines.append(f"Αρτιότητα: {data.get('min_lot_size_m2')} m²")
        if data.get('min_frontage_m'):
            lines.append(f"Πρόσοψη: {data.get('min_frontage_m')} m")

    # Add building system if available
    if data.get('building_system'):
        lines.append(f"Σύστημα: {data.get('building_system')}")

    # Add land use - prefer description over codes
    if data.get('land_use_description'):
        lines.append(f"Χρήσεις: {data.get('land_use_description')}")
    elif data.get('land_use_codes'):
        lines.append(f"Χρήσεις: {data.get('land_use_codes')}")

    text = "\\P".join(lines)
    return text.encode('windows-1253', errors='replace').decode('windows-1253')


@app.get("/oroi/full", response_class=PlainTextResponse)
async def get_building_regulations_full(
    x: float = Query(..., description="X coordinate (EGSA '87)"),
    y: float = Query(..., description="Y coordinate (EGSA '87)")
):
    """Get building regulations with ALL comments/remarks for detailed view."""
    data = _get_building_regulations_data(x, y)

    if not data.get("found"):
        return "Δεν βρέθηκαν όροι δόμησης"

    lines = [
        "=" * 40,
        f"ΟΤ: {data.get('ot_num', '-')}",
        f"ΦΕΚ: {data.get('fek', '-')}",
        "=" * 40,
    ]

    # Tomeas & Oros type
    if data.get('sd_tomeas'):
        lines.append(f"Τομέας: {data.get('sd_tomeas')}")
    if data.get('oros_type'):
        lines.append(f"Όροι: {data.get('oros_type')}")
    if data.get('date_pareklisis'):
        lines.append(f"Ημ/νία παρέκκλισης: {data.get('date_pareklisis')}")

    # Height section
    lines.append("")
    lines.append("--- ΥΨΟΣ ---")
    lines.append(f"Μέγιστο ύψος: {data.get('max_height_m', '-')} m")
    lines.append(f"Όροφοι: {data.get('num_floors', '-')}")
    if data.get('height_comment'):
        lines.append(f"Σημειώσεις: {data.get('height_comment')}")

    # Coverage section
    lines.append("")
    lines.append("--- ΚΑΛΥΨΗ ---")
    lines.append(f"Ποσοστό: {data.get('coverage_pct', '-')}%")
    if data.get('coverage_remarks'):
        lines.append(f"Σημειώσεις: {data.get('coverage_remarks')}")

    # Coefficient section
    lines.append("")
    lines.append("--- ΣΔ ---")
    lines.append(f"Συντελεστής: {data.get('building_coefficient', '-')}")
    if data.get('sd_klimakotos'):
        lines.append(f"Κλιμακωτός: {data.get('sd_klimakotos')}")
    if data.get('coefficient_comment'):
        lines.append(f"Σημειώσεις: {data.get('coefficient_comment')}")

    # Lot section
    lines.append("")
    lines.append("--- ΟΙΚΟΠΕΔΟ ---")
    lines.append(f"Ελάχιστο εμβαδόν: {data.get('min_lot_size_m2', '-')} m²")
    lines.append(f"Ελάχιστη πρόσοψη: {data.get('min_frontage_m', '-')} m")
    if data.get('lot_remarks'):
        lines.append(f"Σημειώσεις: {data.get('lot_remarks')}")

    # Building system
    if data.get('building_system'):
        lines.append("")
        lines.append("--- ΣΥΣΤΗΜΑ ---")
        lines.append(f"Οικοδομικό σύστημα: {data.get('building_system')}")

    # Land uses
    if data.get('land_use_codes'):
        lines.append("")
        lines.append("--- ΧΡΗΣΕΙΣ ---")
        lines.append(f"Κωδικοί: {data.get('land_use_codes')}")

    text = "\\P".join(lines)
    return text.encode('windows-1253', errors='replace').decode('windows-1253')


# =============================================================================
# OROITABLE - Full Building Regulations Table (like the AutoCAD table format)
# =============================================================================

def _get_oroitable_data(x: float, y: float) -> dict:
    return PlanningData(execute_query).get_regulations(x=x, y=y)


@app.get("/oroitable")
async def get_oroitable(
    x: float = Query(..., description="X coordinate (EGSA '87)"),
    y: float = Query(..., description="Y coordinate (EGSA '87)")
):
    """Get comprehensive building regulations data in JSON format."""
    return _get_oroitable_data(x, y)


@app.get("/oroitable/text", response_class=PlainTextResponse)
async def get_oroitable_text(
    x: float = Query(..., description="X coordinate (EGSA '87)"),
    y: float = Query(..., description="Y coordinate (EGSA '87)")
):
    """Get building regulations formatted as full table text for AutoCAD."""
    data = _get_oroitable_data(x, y)

    if not data.get("found"):
        return "Δεν βρέθηκαν όροι δόμησης"

    lines = []
    sep = "=" * 60

    # OT Number
    if data["ot_num"]:
        lines.append(f"Ο.Τ. {data['ot_num']}")
        lines.append("")

    # ΔΙΑΤΑΓΜΑΤΑ
    lines.append(sep)
    lines.append("ΔΙΑΤΑΓΜΑΤΑ")
    lines.append(sep)
    if data["diatagmata_entaxis"]:
        lines.append(f"Ένταξης - Ρυμοτομίας: {', '.join(data['diatagmata_entaxis'])}")
    if data["diatagmata_oron"]:
        lines.append(f"Όρων Δόμησης: {', '.join(data['diatagmata_oron'])}")

    # ΧΡΗΣΕΙΣ
    lines.append("")
    lines.append(f"Χρήσεις: {data['xriseis']}")

    # ΚΑΤΑ ΚΑΝΟΝΑ - for each ΤΟΜΕΑΣ
    for tomeas in data["tomeis"]:
        lines.append("")
        lines.append(sep)
        lines.append(f"(ΤΟΜΕΑΣ {tomeas['name']}) ΚΑΤΑ ΚΑΝΟΝΑ")
        lines.append(sep)

        if tomeas.get("elax_embado_m2"):
            fek_ref = f" (ΦΕΚ {tomeas['lot_fek']})" if tomeas.get('lot_fek') else ""
            lines.append(f"Ελάχ. Εμβαδόν: {tomeas['elax_embado_m2']} τ.μ.{fek_ref}")
        if tomeas.get("elax_prosop_m"):
            lines.append(f"Ελάχ. Πρόσοψη: {tomeas['elax_prosop_m']} μ.")

        if tomeas.get("coverage_pct"):
            fek_ref = f" (ΦΕΚ {tomeas['coverage_fek']})" if tomeas.get('coverage_fek') else ""
            system = f" σύστημα {tomeas['oik_systima'].lower()}" if tomeas.get('oik_systima') else ""
            lines.append(f"Κάλυψη: {tomeas['coverage_pct']}%{system}{fek_ref}")

        if tomeas.get("sd"):
            fek_ref = f" (ΦΕΚ {tomeas['sd_fek']})" if tomeas.get('sd_fek') else ""
            lines.append(f"Συντ. Δόμησης: {tomeas['sd']}{fek_ref}")

        if tomeas.get("max_height_m"):
            fek_ref = f" (ΦΕΚ {tomeas['height_fek']})" if tomeas.get('height_fek') else ""
            floors = f" - όροφοι {tomeas['num_orofon']}" if tomeas.get('num_orofon') else ""
            lines.append(f"Μέγιστο Ύψος: {tomeas['max_height_m']} μ.{floors}{fek_ref}")

    # ΕΓΚΡΙΣΕΙΣ
    if data["egkriseis"]:
        lines.append("")
        lines.append(sep)
        lines.append("ΕΓΚΡΙΣΕΙΣ")
        lines.append(sep)
        lines.append(", ".join(data["egkriseis"]))

    # ΛΟΙΠΑ
    if data["loipa"]:
        lines.append("")
        lines.append(sep)
        lines.append("ΛΟΙΠΑ")
        lines.append(sep)
        for loipo in data["loipa"]:
            # Split by α., β., γ. etc
            lines.append(f"- {loipo}")

    # Add hardcoded plimmyra note
    lines.append(f"- {data['plimmyra']}")

    # ΛΟΙΠΟΙ ΠΕΡΙΟΡΙΣΜΟΙ
    lines.append("")
    lines.append(f"Λοιποί Περιορισμοί: {data['loipoi_periorismoi']}")

    # ΚΑΤΑ ΠΑΡΕΚΚΛΙΣΗ
    if data["kata_parekklisi"]:
        lines.append("")
        lines.append(sep)
        lines.append("ΚΑΤΑ ΠΑΡΕΚΚΛΙΣΗ")
        lines.append(sep)
        parek = data["kata_parekklisi"]
        if parek.get("date"):
            lines.append(f"προ {parek['date']}")
        if parek.get("remarks"):
            lines.append(parek["remarks"])

    text = "\\P".join(lines)
    return text.encode('windows-1253', errors='replace').decode('windows-1253')


@app.get("/oroitable/rows", response_class=PlainTextResponse)
async def get_oroitable_rows(
    x: float = Query(..., description="X coordinate (EGSA '87)"),
    y: float = Query(..., description="Y coordinate (EGSA '87)")
):
    """
    Structured row data for LISP table drawing (ETABLE command).
    Each line: TYPE|col1|col2
      TITLE  |left-label|right-label  (full-width merged, large text)
      HEADER |label|                  (full-width section header)
      ROW    |label|value             (two-column data row)
      MERGED |text|                   (full-width small-text footnote)
    """
    data = _get_oroitable_data(x, y)

    if not data.get("found"):
        return "ERROR|No regulations found at this location"

    rows = []

    # Title
    ot_label = f"O.T. {data['ot_num']}" if data.get("ot_num") else "SPETSES"
    rows.append(f"TITLE|ΟΡΟΙ ΔΟΜΗΣΗΣ|{ot_label}")

    # Xriseis (always present)
    rows.append(f"ROW|Χρήσεις γης|{data['xriseis']}")

    # Diatagmata entaxis
    if data["diatagmata_entaxis"]:
        rows.append("HEADER|Διατάγματα Εντάξεως - Ρυμοτομίας|")
        for fek in data["diatagmata_entaxis"]:
            rows.append(f"ROW||{fek}")

    # Diatagmata oron domisis
    if data["diatagmata_oron"]:
        rows.append("HEADER|Διατάγματα Όρων Δόμησης|")
        for fek in data["diatagmata_oron"]:
            rows.append(f"ROW||{fek}")

    # Kata kanona (one section per tomeas)
    for tomeas in data["tomeis"]:
        name = tomeas.get("name", "ΚΑΤΑ ΚΑΝΟΝΑ")
        rows.append(f"HEADER|Κατά Κανόνα  —  Τομέας {name}|")

        if tomeas.get("elax_embado_m2"):
            rows.append(f"ROW|Αρτιότητα|{tomeas['elax_embado_m2']} τ.μ.")
        if tomeas.get("elax_prosop_m"):
            rows.append(f"ROW|Πρόσοψη|{tomeas['elax_prosop_m']} μ.")
        if tomeas.get("coverage_pct"):
            cov = f"{tomeas['coverage_pct']}%"
            if tomeas.get("oik_systima"):
                cov += f"  —  Σύστημα {tomeas['oik_systima']}"
            rows.append(f"ROW|Κάλυψη|{cov}")
        if tomeas.get("sd"):
            sd_val = str(tomeas["sd"])
            if tomeas.get("sd_klimakotos"):
                sd_val += f"  (κλιμακωτός: {tomeas['sd_klimakotos']})"
            rows.append(f"ROW|Συντ. Δόμησης|{sd_val}")
        if tomeas.get("max_height_m"):
            h_val = f"{tomeas['max_height_m']} μ."
            if tomeas.get("num_orofon"):
                h_val += f"  ({tomeas['num_orofon']} όροφοι)"
            rows.append(f"ROW|Μέγ. Ύψος|{h_val}")

    # Kata parekklisi
    if data.get("kata_parekklisi"):
        rows.append("HEADER|Κατά Παρέκκλιση|")
        parek = data["kata_parekklisi"]
        if parek.get("date"):
            rows.append(f"ROW|Προ|προ {parek['date']}")
        if parek.get("remarks"):
            rows.append(f"MERGED|{parek['remarks']}|")   # long text → MTEXT wrap
        if parek.get("fek"):
            rows.append(f"ROW|ΦΕΚ|{parek['fek']}")

    # Egkriseis
    if data["egkriseis"]:
        rows.append("HEADER|Απαιτούμενες Εγκρίσεις|")
        rows.append(f"ROW||{', '.join(data['egkriseis'])}")

    # Loipoi periorismoi — only emit rows that have content
    loipoi_rows = []
    if data.get("loipoi_periorismoi"):
        loipoi_rows.append(f"MERGED|{data['loipoi_periorismoi']}|")
    if data.get("loipa"):
        for item in data["loipa"]:
            if item:
                loipoi_rows.append(f"MERGED|{item}|")
    if data.get("plimmyra"):
        loipoi_rows.append(f"MERGED|{data['plimmyra']}|")
    if loipoi_rows:
        rows.append("HEADER|Λοιποί Περιορισμοί|")
        rows.extend(loipoi_rows)

    return "\n".join(rows)


@app.get("/report/rows", response_class=PlainTextResponse)
async def get_report_rows(
    x: float = Query(..., description="X coordinate (EGSA '87)"),
    y: float = Query(..., description="Y coordinate (EGSA '87)")
):
    """
    Full planning report: building regs + aigialos + archeo + church + natura + remata.
    Same TYPE|col1|col2 format as /oroitable/rows — for use with EREPORT LISP command.
    """
    with _report_data(parcel=False) as data:
        return data.point_report(x, y)


# =============================================================================
# PARCEL-BASED REPORT (/report/parcel) — for the EREPORT command
# =============================================================================

def _resolve_operating_parcel(x: float, y: float, radius: float = 50) -> dict:
    return PlanningData(execute_query).resolve_parcel(x=x, y=y, radius=radius)


def _get_parcel_overlaps(kaek: str) -> dict:
    return PlanningData(execute_query).get_parcel_overlaps(kaek=kaek)


@app.get("/report/parcel", response_class=PlainTextResponse)
async def get_report_parcel(
    x: float = Query(..., description="X coordinate (EGSA '87)"),
    y: float = Query(..., description="Y coordinate (EGSA '87)")
):
    """
    Parcel-based planning report for the EREPORT command.

    Resolves the operating-cadastre parcel at the clicked point, then measures
    every distance from the parcel polygon (not the click point) and reports
    Natura / forest / archaeological zones as % of parcel overlap. Building
    regulations are still computed at the clicked point. Same TYPE|col1|col2
    format as /report/rows.
    """
    with _report_data(parcel=True) as data:
        return data.parcel_report(x, y)


# =============================================================================
# ΠΑΡΑΤΗΡΗΣΕΙΣ ΤΟΠΟΓΡΑΦΙΚΟΥ (ENOTES) — template-driven notary notes
# =============================================================================

_NOTES_TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "notes_template.txt")


def _notes_thalassa(ref_geom: str, ref_args: tuple) -> str:
    """Απόσταση από ακτογραμμή (φυσική) + καθορισμένο αιγιαλό (νομική)."""
    # Η ακτογραμμή είναι MULTIPOLYGON (το νησί ως επιφάνεια) — χωρίς ST_Boundary
    # κάθε σημείο μέσα στο νησί θα έδινε απόσταση 0.
    akt_sql = f"""
    SELECT ROUND(MIN(ST_Distance(ST_Boundary(a.geom), {ref_geom}))::numeric, 0)
    FROM sp_geodata."Σπέτσες_Ακτογραμμή" a
    """
    akt = execute_query(akt_sql, (*ref_args,), fetch_one=True)
    if not akt or akt[0] is None:
        return None
    sentence = f"Η ιδιοκτησία βρίσκεται σε απόσταση περίπου {int(akt[0])} μ. από την ακτογραμμή"

    shore = _get_shoreline_data(ref_geom=ref_geom, ref_args=ref_args)
    if shore.get("found"):
        by_type = {r["info"]: r for r in shore.get("lines", [])}
        cands = [by_type[k] for k in ("Γραμμή Αιγιαλού", "Γραμμή Αιγιαλού_ΠΟΑ")
                 if k in by_type and by_type[k].get("distance_m") is not None]
        if cands:
            nearest = min(cands, key=lambda r: r["distance_m"])
            fek = f" (ΦΕΚ {nearest['fek']})" if nearest.get("fek") else ""
            sentence += (f" και {nearest['distance_m']} μ. από την καθορισμένη "
                         f"γραμμή αιγιαλού{fek}")
    return sentence + "."


def _notes_ktisma(main_use: str, descr: str) -> str:
    """Κτίσμα κατά τη χρήση του κτηματολογίου — ενδεικτικό, θέλει αυτοψία."""
    if not main_use:
        return None
    if main_use[0] in "234":
        return (f"Επί του ανωτέρω οικοπέδου υφίσταται κτίσμα "
                f"(χρήση κατά το Κτηματολόγιο: {descr or main_use}).")
    if main_use in ("7100", "1500"):
        return (f"Το οικόπεδο εμφανίζεται αδόμητο κατά το Κτηματολόγιο "
                f"({descr or main_use}).")
    return None


def _notes_dasiko(kaek: str, inside_plan: bool) -> str:
    if inside_plan:
        return ("Το οικόπεδο δεν υπάγεται στις διατάξεις περί δασικής νομοθεσίας "
                "ούτε πρόκειται για δασική έκταση καθώς βρίσκεται εντός "
                "εγκεκριμένου σχεδίου του Δήμου Σπετσών.")
    overlaps = _get_parcel_overlaps(kaek)
    forest = overlaps.get("forest") or []
    bad = [f for f in forest if f.get("category") not in ("μη δασικό",)]
    if not bad:
        src = overlaps.get("forest_source") or "δασικός χάρτης"
        return (f"Κατά τον δασικό χάρτη ({src}) το γήπεδο δεν εμπίπτει σε "
                f"έκταση δασικού χαρακτήρα.")
    worst = max(bad, key=lambda f: float(f.get("pct") or 0))
    return (f"### ΕΛΕΓΧΟΣ: κατά τον δασικό χάρτη "
            f"({worst.get('source', '')}) το γήπεδο εμπίπτει σε «{worst['label']}» "
            f"({worst['pct']}%) — προσαρμόστε τη διατύπωση / απαιτείται έλεγχος. ###")


def _notes_ydro(ref_geom: str, ref_args: tuple) -> str:
    standard = ("Στο παρόν ακίνητο κατά δήλωση των εργοδοτών δεν πραγματοποιείται "
                "υδροληψία από επιφανειακά και υπόγεια ύδατα και δεν "
                "περιλαμβάνονται σε αυτό ενεργά, ανενεργά ή γενικά προοριζόμενα "
                "για μελλοντική χρήση σημεία υδροληψίας.")
    ydro = _get_ydrolipsies_data(ref_geom=ref_geom, ref_args=ref_args)
    if ydro["available"] and ydro["inside"]:
        pts = "; ".join(_ydro_point_label(w) for w in ydro["inside"])
        return (f"### ΕΛΕΓΧΟΣ: καταγεγραμμένο σημείο υδροληψίας ΕΜΣΥ εντός του "
                f"γεωτεμαχίου ({pts}) — προσαρμόστε τη δήλωση. ###")
    return standard


@app.get("/notes/parcel", response_class=PlainTextResponse)
async def get_notes_parcel(
    x: float = Query(..., description="X coordinate (EGSA '87)"),
    y: float = Query(..., description="Y coordinate (EGSA '87)")
):
    """
    ΠΑΡΑΤΗΡΗΣΕΙΣ τοπογραφικού για συμβόλαιο — auto-filled from the DB.
    Template: notes_template.txt (numbering applied automatically; lines whose
    placeholder resolves to nothing are dropped). Returns MTEXT (\\P separators).
    """
    parcel = _resolve_operating_parcel(x, y)
    if not parcel:
        return "ERROR|Δεν βρέθηκε γεωτεμάχιο στο σημείο"
    kaek = parcel["kaek"]
    ref_geom, ref_args = _PARCEL_REF, (kaek,)
    inside_plan = _is_inside_city_plan(x, y)

    values = {
        "RYMOTOMIKI": None,
        "DASIKO": _notes_dasiko(kaek, inside_plan),
        "THALASSA": _notes_thalassa(ref_geom, ref_args),
        "KTISMA": _notes_ktisma(parcel.get("main_use"), parcel.get("descr")),
        "YDRO": _notes_ydro(ref_geom, ref_args),
        "KAEK": (f"Το παρόν ακίνητο φέρει ΚΑΕΚ {kaek} και η περιοχή τελεί υπό "
                 f"καθεστώς λειτουργούντος Κτηματολογίου."),
    }

    if inside_plan:
        oroi = _get_oroitable_data(x, y)
        feks = oroi.get("diatagmata_entaxis") or []
        if feks:
            values["RYMOTOMIKI"] = ("Η ρυμοτομική γραμμή ορίστηκε σύμφωνα με "
                                    + ", ".join(feks) + ".")

    try:
        with open(_NOTES_TEMPLATE, encoding="utf-8") as f:
            raw = f.read()
    except OSError:
        return "ERROR|notes_template.txt not found next to api_server.py"

    out_lines = []
    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith(";"):
            continue
        skip = False
        for key in re.findall(r"\{([A-Z_]+)\}", s):
            val = values.get(key)
            if not val:
                skip = True
                break
            s = s.replace("{" + key + "}", val)
        if skip:
            continue
        out_lines.append(s)

    numbered = [f"{i + 1}. {t}" for i, t in enumerate(out_lines)]
    text = "\\P".join(["ΠΑΡΑΤΗΡΗΣΕΙΣ:"] + numbered)
    return text.encode('windows-1253', errors='replace').decode('windows-1253')


# =============================================================================
# BUILDING BLOCKS / OT (from epoleodomia)
# =============================================================================

def _get_building_block_data(x: float, y: float, include_neighbors: bool = True) -> dict:
    """Internal function to get building block at a point."""
    main_sql = """
    SELECT
        id,
        ot_num,
        fek,
        ST_AsText(geom) as geom_wkt,
        ST_Area(geom) as area_m2,
        ST_Perimeter(geom) as perimeter_m
    FROM epoleodomia.building_blocks
    WHERE NOT COALESCE(is_deleted, false)
      AND ST_Contains(geom, ST_SetSRID(ST_Point(%s, %s), 2100))
    LIMIT 1
    """

    main_block = execute_query(main_sql, (x, y), fetch_one=True)

    if not main_block:
        return {"found": False, "message": "No building block at this location"}

    result = {
        "found": True,
        "id": main_block[0],
        "ot_num": main_block[1],
        "fek": main_block[2],
        "area_m2": round(main_block[4], 2) if main_block[4] else None,
        "perimeter_m": round(main_block[5], 2) if main_block[5] else None,
        "coords": _wkt_to_coords(main_block[3]),
        "neighbors": []
    }

    if include_neighbors:
        neighbors_sql = """
        SELECT
            b.id,
            b.ot_num,
            ST_AsText(b.geom) as geom_wkt
        FROM epoleodomia.building_blocks b
        WHERE NOT COALESCE(b.is_deleted, false)
          AND b.id != %s
          AND ST_Touches(b.geom, (
              SELECT geom FROM epoleodomia.building_blocks WHERE id = %s
          ))
        """
        neighbors = execute_query(neighbors_sql, (main_block[0], main_block[0]))

        for nb in neighbors:
            result["neighbors"].append({
                "id": nb[0],
                "ot_num": nb[1],
                "coords": _wkt_to_coords(nb[2])
            })

    return result


@app.get("/ot")
async def get_building_block(
    x: float = Query(..., description="X coordinate (EGSA '87)"),
    y: float = Query(..., description="Y coordinate (EGSA '87)"),
    include_neighbors: bool = Query(True, description="Include neighboring blocks")
):
    """
    Get building block (OT) at a point with optional neighbors.
    Data from epoleodomia.building_blocks
    """
    return _get_building_block_data(x, y, include_neighbors)


@app.get("/ot/simple", response_class=PlainTextResponse)
async def get_building_block_simple(
    x: float = Query(..., description="X coordinate (EGSA '87)"),
    y: float = Query(..., description="Y coordinate (EGSA '87)")
):
    """Get building block in simple line format for LISP."""
    data = _get_building_block_data(x, y, include_neighbors=True)

    if not data.get("found"):
        return "ERROR|No building block found"

    lines = []
    lines.append(f"OK|{data.get('ot_num', '')}|{data.get('fek', '')}|{data.get('area_m2', '')}|{data.get('perimeter_m', '')}")

    if data.get("coords"):
        coord_str = ";".join([f"{c[0]},{c[1]}" for c in data["coords"]])
        lines.append(f"MAIN|{coord_str}")

    for nb in data.get("neighbors", []):
        if nb.get("coords"):
            coord_str = ";".join([f"{c[0]},{c[1]}" for c in nb["coords"]])
            lines.append(f"NB|{coord_str}")

    return "\n".join(lines)


# =============================================================================
# ARCHAEOLOGY (from sp_geodata)
# =============================================================================

def _get_archaeology_data(x: float = None, y: float = None, max_distance: float = 2000,
                          ref_geom: str = None, ref_args: tuple = None,
                          include_zone: bool = True) -> dict:
    return PlanningData(execute_query).get_archaeology(
        x=x, y=y, max_distance=max_distance, ref_geom=ref_geom,
        ref_args=ref_args, include_zone=include_zone)


@app.get("/archeo")
async def get_archaeology(
    x: float = Query(..., description="X coordinate (EGSA '87)"),
    y: float = Query(..., description="Y coordinate (EGSA '87)"),
    max_distance: float = Query(2000, description="Maximum search distance in meters")
):
    """
    Get archaeological information at a point.
    Data from sp_geodata.Αρχαιλογία_Κυρηγμένα_Μνημεία and Αρχαιολογία_Ζώνες_Προστασίας
    """
    return _get_archaeology_data(x, y, max_distance)


@app.get("/archeo/text", response_class=PlainTextResponse)
async def get_archaeology_text(
    x: float = Query(..., description="X coordinate (EGSA '87)"),
    y: float = Query(..., description="Y coordinate (EGSA '87)")
):
    """Get archaeology info formatted for AutoCAD MTEXT."""
    data = _get_archaeology_data(x, y)

    if not data.get("found"):
        return "Δεν βρέθηκε αρχαιολογικό"

    lines = [
        f"{data.get('name', '-')}",
        f"ΟΤ: {data.get('ot', '-')}",
        f"ΦΕΚ: {data.get('fek', '-')}",
        f"Απόσταση: {data.get('distance_m', '-')} m",
    ]

    if data.get("in_protection_zone"):
        lines.append(f"ΕΝΤΟΣ ΖΩΝΗΣ ΠΡΟΣΤΑΣΙΑΣ")
        lines.append(f"Ζώνη: {data.get('zone_name', '')}")
    else:
        lines.append("Ζώνη προστασίας: ΟΧΙ")

    text = "\\P".join(lines)
    return text.encode('windows-1253', errors='replace').decode('windows-1253')


# =============================================================================
# CHURCHES (from sp_geodata)
# =============================================================================

def _get_church_data(x: float = None, y: float = None, max_distance: float = 500,
                     ref_geom: str = None, ref_args: tuple = None) -> dict:
    return PlanningData(execute_query).get_church(
        x=x, y=y, max_distance=max_distance, ref_geom=ref_geom, ref_args=ref_args)


@app.get("/church")
async def get_church(
    x: float = Query(..., description="X coordinate (EGSA '87)"),
    y: float = Query(..., description="Y coordinate (EGSA '87)"),
    max_distance: float = Query(500, description="Maximum search distance in meters")
):
    """
    Get closest church to a point.
    Data from sp_geodata.Εκκλησίες_πολυγωνα
    """
    return _get_church_data(x, y, max_distance)


@app.get("/church/text", response_class=PlainTextResponse)
async def get_church_text(
    x: float = Query(..., description="X coordinate (EGSA '87)"),
    y: float = Query(..., description="Y coordinate (EGSA '87)")
):
    """Get church info formatted for AutoCAD MTEXT."""
    data = _get_church_data(x, y)

    if not data.get("found"):
        return "Δεν βρέθηκε εκκλησία"

    lines = [f"{data.get('name', '-')}"]
    if data.get('type'):
        lines.append(f"Τύπος: {data.get('type')}")
    lines.append(f"Απόσταση: {data.get('distance_m', '-')} μ.")
    if data.get('century'):
        lines.append(f"Αιώνας: {data.get('century')}")
    if data.get('status'):
        lines.append(f"Κατάσταση: {data.get('status')}")

    text = "\\P".join(lines)
    return text.encode('windows-1253', errors='replace').decode('windows-1253')


# =============================================================================
# SHORELINE / AIGIALOS (from sp_geodata)
# =============================================================================


def _get_shoreline_data(x: float = None, y: float = None, max_distance: float = 5000,
                        ref_geom: str = None, ref_args: tuple = None) -> dict:
    return PlanningData(execute_query).get_shoreline(
        x=x, y=y, max_distance=max_distance, ref_geom=ref_geom, ref_args=ref_args)


@app.get("/aigialos")
async def get_shoreline(
    x: float = Query(..., description="X coordinate (EGSA '87)"),
    y: float = Query(..., description="Y coordinate (EGSA '87)"),
    max_distance: float = Query(5000, description="Maximum search distance in meters")
):
    """Distance to each shoreline type. Data from sp_geodata.Αιγιαλός_Παραλία"""
    return _get_shoreline_data(x, y, max_distance)


@app.get("/aigialos/text", response_class=PlainTextResponse)
async def get_shoreline_text(
    x: float = Query(..., description="X coordinate (EGSA '87)"),
    y: float = Query(..., description="Y coordinate (EGSA '87)")
):
    """Shoreline distances formatted for AutoCAD MTEXT (one line per type)."""
    data = _get_shoreline_data(x, y)

    if not data.get("found"):
        return "Δεν βρέθηκε αιγιαλός εντός 5000 μ."

    # Priority order for display
    priority = [
        "Γραμμή Αιγιαλού",
        "Γραμμή Αιγιαλού_ΠΟΑ",
        "Γραμμή Παραλίας",
        "Γραμμή Παραλίας_ΠΟΑ",
        "Γραμμή Παλαιού Αιγιαλού",
    ]
    by_type = {r["info"]: r for r in data["lines"]}

    out = ["--- ΑΙΓΙΑΛΟΣ / ΠΑΡΑΛΙΑ ---"]
    for key in priority:
        if key in by_type:
            r = by_type[key]
            label = _AIGIALOS_LABELS.get(key, key)
            fek = f"  (ΦΕΚ {r['fek']})" if r.get("fek") else ""
            out.append(f"{label}: {r['distance_m']} μ.{fek}")

    text = "\\P".join(out)
    return text.encode('windows-1253', errors='replace').decode('windows-1253')


# =============================================================================
# STREAMS / REMATA (from sp_geodata)
# =============================================================================

def _is_inside_city_plan(x: float, y: float) -> bool:
    return PlanningData(execute_query).is_inside_city_plan(x=x, y=y)


def _get_streams_data(x: float = None, y: float = None, max_distance: float = 500,
                      ref_geom: str = None, ref_args: tuple = None) -> dict:
    return PlanningData(execute_query).get_streams(
        x=x, y=y, max_distance=max_distance, ref_geom=ref_geom, ref_args=ref_args)


@app.get("/remata")
async def get_streams(
    x: float = Query(..., description="X coordinate (EGSA '87)"),
    y: float = Query(..., description="Y coordinate (EGSA '87)"),
    max_distance: float = Query(500, description="Maximum search distance in meters")
):
    """Stream distances per line type. Data from sp_geodata remata tables."""
    return _get_streams_data(x, y, max_distance)


@app.get("/remata/text", response_class=PlainTextResponse)
async def get_streams_text(
    x: float = Query(..., description="X coordinate (EGSA '87)"),
    y: float = Query(..., description="Y coordinate (EGSA '87)")
):
    """Stream info formatted for AutoCAD MTEXT."""
    data = _get_streams_data(x, y)
    by_layer = {r["layer"]: r for r in data["oikismos_lines"]}

    lines = ["ΕΝΤΟΣ ΣΧΕΔΙΟΥ ΠΟΛΕΩΣ" if data["inside_city_plan"] else "ΕΚΤΟΣ ΣΧΕΔΙΟΥ ΠΟΛΕΩΣ"]
    lines.append("--- ΡΕΜΑΤΑ ---")

    for key in _REMATA_ORDER:
        if key in by_layer:
            r = by_layer[key]
            lines.append(f"{r['label']}: {r['distance_m']} μ.")

    if data.get("tps_found"):
        lines.append(f"Ρέμα ΤΠΣ: {data['tps_distance_m']} μ.")

    if data.get("other_found"):
        lines.append(f"Άλλο ρέμα (εντός οικ.): {data['other_distance_m']} μ.")

    if not data["oikismos_lines"] and not data.get("tps_found"):
        lines.append("Δεν βρέθηκε ρέμα εντός 500 μ.")

    text = "\\P".join(lines)
    return text.encode('windows-1253', errors='replace').decode('windows-1253')


# =============================================================================
# NATURA / FOREST (from epoleodomia)
# =============================================================================

def _get_natura_forest_data(x: float, y: float) -> dict:
    return PlanningData(execute_query).get_natura_forest(x=x, y=y)


@app.get("/natura")
async def get_natura_forest(
    x: float = Query(..., description="X coordinate (EGSA '87)"),
    y: float = Query(..., description="Y coordinate (EGSA '87)")
):
    """
    Check Natura 2000 and forest map status at a point.
    Data from epoleodomia.natura_2000 and epoleodomia.forest_maps
    """
    return _get_natura_forest_data(x, y)


@app.get("/natura/text", response_class=PlainTextResponse)
async def get_natura_forest_text(
    x: float = Query(..., description="X coordinate (EGSA '87)"),
    y: float = Query(..., description="Y coordinate (EGSA '87)")
):
    """Get natura/forest info formatted for AutoCAD MTEXT."""
    data = _get_natura_forest_data(x, y)

    lines = []

    if data.get("in_natura"):
        lines.append(f"NATURA 2000: ΝΑΙ")
        lines.append(f"{data.get('natura_name', '')}")
        lines.append(f"Κωδικός: {data.get('natura_code', '')}")
    else:
        lines.append("NATURA 2000: ΟΧΙ")

    if data.get("in_forest"):
        src = data.get("forest_source", "")
        src_label = f" ({src})" if src else ""
        lines.append(f"ΔΑΣΙΚΟΣ ΧΑΡΤΗΣ{src_label}: ΝΑΙ")
        lines.append(f"Κωδικός: {data.get('forest_type', '')} — {data.get('forest_type_label', '')}")
        lines.append(f"Κατηγορία: {data.get('forest_category', '')}")
    else:
        lines.append("ΔΑΣΙΚΟΣ ΧΑΡΤΗΣ: ΟΧΙ")

    if data.get("kaek_forest_use"):
        lines.append(f"Χρήση γης (ΚΑΕΚ): {data['kaek_forest_use']}")

    text = "\\P".join(lines)
    return text.encode('windows-1253', errors='replace').decode('windows-1253')


# =============================================================================
# PLANNING LINES (from epoleodomia)
# =============================================================================

def _get_planning_lines_data(minx: float, miny: float, maxx: float, maxy: float) -> dict:
    """Internal function to get all planning lines within a bounding box."""
    sql = """
    SELECT
        line_type,
        subtype,
        fek,
        road_width,
        prasia_width,
        ST_AsText(geom) as geom_wkt
    FROM epoleodomia.v_planning_lines_all
    WHERE ST_Intersects(
        geom,
        ST_MakeEnvelope(%s, %s, %s, %s, 2100)
    )
    ORDER BY line_type
    """

    results = execute_query(sql, (minx, miny, maxx, maxy))

    lines = []
    for row in results:
        lines.append({
            "type": row[0],
            "subtype": row[1],
            "fek": row[2],
            "road_width": row[3],
            "prasia_width": row[4],
            "coords": _wkt_to_coords(row[5])
        })

    return {"count": len(lines), "lines": lines}


@app.get("/plan")
async def get_planning_lines(
    minx: float = Query(..., description="Minimum X coordinate"),
    miny: float = Query(..., description="Minimum Y coordinate"),
    maxx: float = Query(..., description="Maximum X coordinate"),
    maxy: float = Query(..., description="Maximum Y coordinate")
):
    """
    Get all planning lines within a bounding box.
    Data from epoleodomia.v_planning_lines_all
    """
    return _get_planning_lines_data(minx, miny, maxx, maxy)


@app.get("/plan/simple", response_class=PlainTextResponse)
async def get_planning_lines_simple(
    minx: float = Query(..., description="Minimum X coordinate"),
    miny: float = Query(..., description="Minimum Y coordinate"),
    maxx: float = Query(..., description="Maximum X coordinate"),
    maxy: float = Query(..., description="Maximum Y coordinate"),
    offset: int = Query(0, description="Skip first N lines (for pagination)"),
    limit: int = Query(500, description="Max lines to return")
):
    """Get planning lines in simple format for LISP.

    Compact format: P|x1,y1;x2,y2  (P=planning, B=building)
    First line: COUNT|total|returned
    Supports pagination via offset/limit.
    """
    data = _get_planning_lines_data(minx, miny, maxx, maxy)

    all_lines = data.get("lines", [])
    total = len(all_lines)
    page = all_lines[offset:offset + limit]

    output = [f"COUNT|{total}|{len(page)}"]

    for line in page:
        if line.get("coords"):
            coord_str = ";".join([f"{c[0]},{c[1]}" for c in line["coords"]])
            # Compact type: P=planning, B=building
            line_code = "B" if line.get('type') == 'building' else "P"
            output.append(f"{line_code}|{coord_str}")

    return "\n".join(output)


# =============================================================================
# KAEK PARCELS (from sp_geodata)
# =============================================================================

@app.get("/kaek/parcels", response_class=PlainTextResponse)
async def get_kaek_parcels(
    x: float = Query(..., description="Point X coordinate (EGSA87)"),
    y: float = Query(..., description="Point Y coordinate (EGSA87)")
):
    """Get the KAEK parcel containing the point + touching neighbors.

    Only private parcels (KAEK with digits only) are returned.
    First line: COUNT|total
    Second line (clicked parcel): C|kaek|area|perimeter|x1,y1;x2,y2;...
    Remaining lines (neighbors): N|kaek|area|perimeter|x1,y1;x2,y2;...
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                WITH clicked AS (
                    SELECT kaek, area_m2, perimeter_m, geom
                    FROM sp_geodata.kaek_parcels_autocad
                    WHERE ST_Contains(geom, ST_SetSRID(ST_MakePoint(%s, %s), 2100))
                      AND kaek ~ '^[0-9]+$'
                    LIMIT 1
                )
                SELECT
                    CASE WHEN c.kaek IS NOT NULL AND p.kaek = c.kaek THEN 'C' ELSE 'N' END as role,
                    p.kaek,
                    ROUND(p.area_m2::numeric, 2) as area,
                    ROUND(p.perimeter_m::numeric, 2) as perimeter,
                    ST_AsText(p.geom) as wkt
                FROM clicked c
                JOIN sp_geodata.kaek_parcels_autocad p
                  ON (p.kaek = c.kaek OR ST_Touches(p.geom, c.geom))
                WHERE p.kaek ~ '^[0-9]+$'
                ORDER BY
                    CASE WHEN p.kaek = c.kaek THEN 0 ELSE 1 END,
                    p.kaek
            """, (x, y))

            rows = cur.fetchall()

            if not rows:
                return "COUNT|0"

            import tempfile
            # Write to temp file for reliable LISP reading
            tmp_dir = os.path.join(os.path.dirname(__file__), "tmp")
            os.makedirs(tmp_dir, exist_ok=True)
            tmp_path = os.path.join(tmp_dir, "kaek_result.txt")

            with open(tmp_path, "w", encoding="ascii", newline="\n") as f:
                f.write(f"COUNT|{len(rows)}\n")
                for role, kaek, area, perimeter, wkt in rows:
                    coords_str = wkt.replace("POLYGON((", "").replace("POLYGON ((", "").replace("))", "")
                    points = []
                    for p in coords_str.split(","):
                        parts = p.strip().split()
                        if len(parts) >= 2:
                            points.append((float(parts[0]), float(parts[1])))

                    # Skip duplicate closing point (WKT convention)
                    if len(points) > 1 and abs(points[0][0] - points[-1][0]) < 0.01 and abs(points[0][1] - points[-1][1]) < 0.01:
                        points = points[:-1]

                    f.write(f"H|{role}|{kaek}|{area}|{perimeter}|{len(points)}\n")
                    for px, py in points:
                        f.write(f"{px:.2f} {py:.2f}\n")

            # Return the file path (forward slashes for LISP)
            return tmp_path.replace("\\", "/")
    finally:
        release_db_connection(conn)


# =============================================================================
# RASTERS - FEK (from epoleodomia)
# =============================================================================

# Quality roles and exclusions come from sp_geodata.v_all_rasters.
# Reasons for the three unresolved exclusions remain a data-review item.

@app.get("/rasters/fek")
async def get_fek_rasters(
    minx: float = Query(..., description="Minimum X coordinate"),
    miny: float = Query(..., description="Minimum Y coordinate"),
    maxx: float = Query(..., description="Maximum X coordinate"),
    maxy: float = Query(..., description="Maximum Y coordinate")
):
    """Working FEK sheets; resolve relative paths and existing flat files."""
    sql = """
    SELECT v.source_id,v.doc_ref,pd.title,v.filename,v.path,
           rc.width_px,rc.height_px,v.res_m,v.nominal_scale,v.georef_rms
    FROM sp_geodata.v_all_rasters v
    JOIN epoleodomia.raster_catalog rc ON rc.id=v.source_id
    LEFT JOIN epoleodomia.planning_diagrams pd ON pd.objectid=rc.planning_diagram_objectid
         AND NOT COALESCE(pd.is_deleted,false)
    WHERE v.collection='fek' AND v.role='working'
      AND ST_Intersects(v.query_geom,ST_MakeEnvelope(%s,%s,%s,%s,2100))
    ORDER BY v.doc_ref,v.filename
    """
    rasters = []
    for row in execute_query(sql,(minx,miny,maxx,maxy)):
        if not row[4]:
            continue
        path = _catalog_raster_path(row[4],'fek',row[3])
        rasters.append({
            'id':row[0], 'fek':row[1], 'title':row[2], 'filename':row[3],
            'path':path, 'available':os.path.isfile(path),
            'width_px':row[5], 'height_px':row[6],
            'resolution':float(row[7]) if row[7] is not None else None,
            'scale':row[8], 'rms':float(row[9]) if row[9] is not None else None,
        })
    return {'count':len(rasters),'paths':[r['path'] for r in rasters],'rasters':rasters}


@app.get("/rasters/fek/simple", response_class=PlainTextResponse)
async def get_fek_rasters_simple(
    minx: float = Query(..., description="Minimum X coordinate"),
    miny: float = Query(..., description="Minimum Y coordinate"),
    maxx: float = Query(..., description="Maximum X coordinate"),
    maxy: float = Query(..., description="Maximum Y coordinate")
):
    """Working sheets as path|fek|ascii|scale|rms|LOCAL-or-URL."""
    sql = """
    SELECT v.filename,v.doc_ref,v.nominal_scale,v.georef_rms,rc.url_georef,v.path
    FROM sp_geodata.v_all_rasters v
    JOIN epoleodomia.raster_catalog rc ON rc.id=v.source_id
    WHERE v.collection='fek' AND v.role='working'
      AND ST_Intersects(v.query_geom,ST_MakeEnvelope(%s,%s,%s,%s,2100))
    ORDER BY v.doc_ref,v.filename
    """
    lines = []
    for filename,fek,scale,rms,url,stored_path in execute_query(sql,(minx,miny,maxx,maxy)):
        if not filename:
            continue
        path = _catalog_raster_path(stored_path or filename,'fek',filename)
        if os.path.isfile(path):
            origin = 'LOCAL'
        elif url:
            path,origin = url,'URL'
        else:
            continue
        lines.append('|'.join([path,fek or '',_transliterate_greek(fek or ''),
                               str(int(scale)) if scale else '',
                               f'{rms:.2f}' if rms is not None else '',origin]))
    return '\n'.join(lines)


@app.get("/rasters/fek/download")
async def download_fek_raster(url: str = Query(..., description="TEE URL to download")):
    """Download a known working TEE sheet using the validated staging pipeline."""
    sql = """
    SELECT v.filename,v.path
    FROM sp_geodata.v_all_rasters v
    JOIN epoleodomia.raster_catalog rc ON rc.id=v.source_id
    WHERE v.collection='fek' AND v.role='working' AND rc.url_georef=%s
    """
    rows = execute_query(sql,(url,))
    if len(rows) != 1:
        return {'status':'error','message':'URL is not a unique working FEK catalog source'}
    filename,stored_path = rows[0]
    try:
        path = _catalog_raster_path(stored_path or filename,'fek',filename)
        return await run_in_threadpool(_download_fek_file,url,path)
    except Exception as exc:
        return {'status':'error','message':str(exc)}


def _transliterate_greek(text: str) -> str:
    """Convert Greek characters to ASCII equivalents."""
    if not text:
        return ""

    greek_to_latin = {
        'Α': 'A', 'Β': 'B', 'Γ': 'G', 'Δ': 'D', 'Ε': 'E', 'Ζ': 'Z', 'Η': 'H',
        'Θ': 'TH', 'Ι': 'I', 'Κ': 'K', 'Λ': 'L', 'Μ': 'M', 'Ν': 'N', 'Ξ': 'X',
        'Ο': 'O', 'Π': 'P', 'Ρ': 'R', 'Σ': 'S', 'Τ': 'T', 'Υ': 'Y', 'Φ': 'F',
        'Χ': 'CH', 'Ψ': 'PS', 'Ω': 'O',
        'α': 'a', 'β': 'b', 'γ': 'g', 'δ': 'd', 'ε': 'e', 'ζ': 'z', 'η': 'h',
        'θ': 'th', 'ι': 'i', 'κ': 'k', 'λ': 'l', 'μ': 'm', 'ν': 'n', 'ξ': 'x',
        'ο': 'o', 'π': 'p', 'ρ': 'r', 'σ': 's', 'ς': 's', 'τ': 't', 'υ': 'y',
        'φ': 'f', 'χ': 'ch', 'ψ': 'ps', 'ω': 'o',
    }

    result = ""
    for char in text:
        result += greek_to_latin.get(char, char)
    return result


# =============================================================================
# RASTERS - DJI (from sp_geodata)
# =============================================================================

@app.get("/rasters/dji")
async def get_dji_rasters(
    minx: float = Query(..., description="Minimum X coordinate"),
    miny: float = Query(..., description="Minimum Y coordinate"),
    maxx: float = Query(..., description="Maximum X coordinate"),
    maxy: float = Query(..., description="Maximum Y coordinate")
):
    """
    Get DJI drone orthophoto rasters that intersect a bounding box.
    Data from sp_geodata.dji_footprints
    """
    sql = """
    SELECT
        id,
        filename,
        full_path,
        res_cm,
        width,
        height,
        date,
        source_project
    FROM sp_geodata.dji_footprints
    WHERE ST_Intersects(
        geom,
        ST_MakeEnvelope(%s, %s, %s, %s, 2100)
    )
    ORDER BY date DESC
    """

    results = execute_query(sql, (minx, miny, maxx, maxy))

    rasters = []
    paths = []

    for row in results:
        full_path = row[2]
        if full_path:
            full_path = full_path.replace("/", "\\")
            paths.append(full_path)
            rasters.append({
                "id": row[0],
                "filename": row[1],
                "path": full_path,
                "res_cm": row[3],
                "width": row[4],
                "height": row[5],
                "date": row[6],
                "project": row[7]
            })

    return {"count": len(rasters), "paths": paths, "rasters": rasters}


# =============================================================================
# RASTERS - DE (from sp_geodata)
# =============================================================================

@app.get("/rasters/de")
async def get_de_rasters(
    minx: float = Query(..., description="Minimum X coordinate"),
    miny: float = Query(..., description="Minimum Y coordinate"),
    maxx: float = Query(..., description="Maximum X coordinate"),
    maxy: float = Query(..., description="Maximum Y coordinate")
):
    """
    Get DE (Diagramma Efarmogis) rasters that intersect a bounding box.
    Data from sp_geodata.de_footprints
    """
    sql = """
    SELECT
        "Id",
        filename,
        raster_path,
        sxolia
    FROM sp_geodata.de_footprints
    WHERE ST_Intersects(
        geometry,
        ST_MakeEnvelope(%s, %s, %s, %s, 2100)
    )
    ORDER BY filename
    """

    results = execute_query(sql, (minx, miny, maxx, maxy))

    rasters = []
    paths = []

    for row in results:
        raster_path = row[2]
        if raster_path:
            raster_path = raster_path.replace("/", "\\")
            paths.append(raster_path)
            rasters.append({
                "id": row[0],
                "filename": row[1],
                "path": raster_path,
                "notes": row[3]
            })

    return {"count": len(rasters), "paths": paths, "rasters": rasters}


# =============================================================================
# RASTERS - GENERIC SHEET CATALOG (sp_geodata.raster_sheets + v_all_rasters)
# =============================================================================
# Locally georeferenced map sheets: GYS 1:5000, aigialos diagrams, historic
# plans. Registered by ingest_rasters.py, see sql/004_raster_sheets.sql.
#
# These two endpoints query v_all_rasters, so they can also reach the FEK, DJI
# and DE collections through the same interface. They use query_geom (the best
# available geometry per row: useful_area > footprint > extent) rather than the
# file envelope, and they filter on role, which is why they will not hand you a
# 1:200000 index sheet with 288 m RMS.


@app.get("/rasters/collections", response_class=PlainTextResponse)
async def get_raster_collections():
    """
    What is actually catalogued, as collection|role|count|scale_hint lines.

    ERASTER calls this to build its prompt, instead of carrying a hardcoded
    list that drifts from reality. An empty response means nothing has been
    ingested yet - which is a different problem from "nothing in this area".
    """
    sql = """
    SELECT collection, role, count(*)::int AS n,
           min(nominal_scale) AS scale_min,
           max(nominal_scale) AS scale_max
    FROM sp_geodata.v_all_rasters
    GROUP BY collection, role
    ORDER BY collection, role
    """
    lines = []
    for coll, role, n, smin, smax in execute_query(sql):
        if smin and smax and smin != smax:
            scale = f"1:{int(smin)}-1:{int(smax)}"
        elif smin:
            scale = f"1:{int(smin)}"
        else:
            scale = ""
        lines.append(f"{coll}|{role}|{n}|{scale}")
    return "\n".join(lines)


@app.get("/rasters/sheets")
async def get_raster_sheets(
    minx: float = Query(..., description="Minimum X coordinate"),
    miny: float = Query(..., description="Minimum Y coordinate"),
    maxx: float = Query(..., description="Maximum X coordinate"),
    maxy: float = Query(..., description="Maximum Y coordinate"),
    collection: str = Query(None, description="gys5000 | aigialos | historic | fek | dji | de"),
    role: str = Query("working", description="Comma-separated: working,context,historical"),
    max_scale: int = Query(None, description="Skip sheets coarser than 1:max_scale"),
):
    """
    Rasters covering a bounding box, from any catalogued collection.

    Ordered finest-scale first, which is also the correct draw order.
    role defaults to 'working' so context and historical sheets stay out of the
    way unless asked for. Pass role=working,context,historical for everything.
    """
    roles = [r.strip() for r in (role or "working").split(",") if r.strip()]

    sql = """
    SELECT source_table, collection, source_id, filename, path,
           role, nominal_scale, res_m, georef_rms, doc_ref, file_size_bytes,
           ST_XMin(extent), ST_YMin(extent), ST_XMax(extent), ST_YMax(extent)
    FROM sp_geodata.v_all_rasters
    WHERE query_geom IS NOT NULL
      AND ST_Intersects(query_geom, ST_MakeEnvelope(%s, %s, %s, %s, 2100))
      AND role = ANY(%s)
      AND (%s::text IS NULL OR collection = %s::text)
      AND (%s::int IS NULL OR COALESCE(nominal_scale, 0) <= %s::int)
    ORDER BY COALESCE(nominal_scale, 2147483647) ASC,
             COALESCE(res_m, 1e9) ASC,
             filename
    """
    results = execute_query(sql, (minx, miny, maxx, maxy, roles,
                                  collection, collection,
                                  max_scale, max_scale))

    sheets, paths = [], []
    for row in results:
        path = row[4]
        if not path:
            continue
        path = _catalog_raster_path(path, row[1], row[3])
        paths.append(path)
        sheets.append({
            "available": os.path.isfile(path) if row[1] == "fek" else None,
            "source": row[0],
            "collection": row[1],
            "id": row[2],
            "filename": row[3],
            "path": path,
            "role": row[5],
            "scale": row[6],
            "res_m": float(row[7]) if row[7] is not None else None,
            "georef_rms": float(row[8]) if row[8] is not None else None,
            "doc_ref": row[9],
            "size_bytes": row[10],
            "extent": [row[11], row[12], row[13], row[14]],
        })

    return {"count": len(sheets), "paths": paths, "sheets": sheets}


@app.get("/rasters/sheets/simple", response_class=PlainTextResponse)
async def get_raster_sheets_simple(
    minx: float = Query(..., description="Minimum X coordinate"),
    miny: float = Query(..., description="Minimum Y coordinate"),
    maxx: float = Query(..., description="Maximum X coordinate"),
    maxy: float = Query(..., description="Maximum Y coordinate"),
    collection: str = Query(None, description="Restrict to one collection"),
    role: str = Query("working", description="Comma-separated roles"),
    max_scale: int = Query(None, description="Skip sheets coarser than 1:max_scale"),
):
    """
    Pipe-delimited form for LISP parsing.

    Format: path|collection|doc_ref_ascii|scale|rms|role
    One per line, finest scale first. Greek in doc_ref is transliterated so it
    is safe to build AutoCAD layer names from it.
    """
    roles = [r.strip() for r in (role or "working").split(",") if r.strip()]

    sql = """
    SELECT path, collection, doc_ref, nominal_scale, georef_rms, role
    FROM sp_geodata.v_all_rasters
    WHERE query_geom IS NOT NULL
      AND path IS NOT NULL
      AND ST_Intersects(query_geom, ST_MakeEnvelope(%s, %s, %s, %s, 2100))
      AND role = ANY(%s)
      AND (%s::text IS NULL OR collection = %s::text)
      AND (%s::int IS NULL OR COALESCE(nominal_scale, 0) <= %s::int)
    ORDER BY COALESCE(nominal_scale, 2147483647) ASC,
             COALESCE(res_m, 1e9) ASC,
             filename
    """
    results = execute_query(sql, (minx, miny, maxx, maxy, roles,
                                  collection, collection,
                                  max_scale, max_scale))

    lines = []
    for path, coll, doc_ref, scale, rms, row_role in results:
        if not path:
            continue
        path = _catalog_raster_path(path, coll)
        if coll == "fek" and not os.path.isfile(path):
            continue
        lines.append("|".join([
            path.replace("/", "\\"),
            coll or "",
            _transliterate_greek(doc_ref or ""),
            str(int(scale)) if scale else "",
            f"{rms:.2f}" if rms is not None else "",
            row_role or "",
        ]))

    return "\n".join(lines)


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    from api_launcher import run_server
    raise SystemExit(run_server(app, SETTINGS))
