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
from contextlib import asynccontextmanager
from typing import Optional

import psycopg2
from psycopg2 import pool
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, JSONResponse

# =============================================================================
# CONFIGURATION
# =============================================================================

DB_CONFIG = {
    "host": os.environ.get("EPOL_DB_HOST", "10.90.144.153"),
    "port": int(os.environ.get("EPOL_DB_PORT", "65432")),
    "database": os.environ.get("EPOL_DB_NAME", "gis"),
    "user": os.environ.get("EPOL_DB_USER", "docker"),
    "password": os.environ.get("EPOL_DB_PASSWORD", ""),
}

# Connection pool
db_pool: pool.SimpleConnectionPool = None

# Raster paths
RASTER_BASE_PATH = os.environ.get("EPOL_RASTER_BASE_PATH", r"O:\claude_code area\mega project postgis-autocad\epoleodomia\rasters\georef")
DJI_RASTER_PATH = os.environ.get("EPOL_DJI_RASTER_PATH", r"O:\GEODATA\drone data")
# Local FEK rasters folder (flat structure, just filenames)
FEK_LOCAL_PATH = os.environ.get("EPOL_FEK_LOCAL_PATH", r"O:\gis_data\epoleodomia\poleodomikoi oroi\poleodomikoi oroi geotifs")

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
# REFERENCE GEOMETRY (point vs. parcel) FOR DISTANCE / CONTAINMENT QUERIES
# =============================================================================
# Distance helpers measure against a "reference geometry". By default that is
# the clicked point; for the parcel-based report it is the operating-cadastre
# parcel polygon. Both fragments are trusted constants interpolated via f-string
# — the %s placeholders inside are filled by psycopg2, not string formatting.
_POINT_REF = "ST_SetSRID(ST_Point(%s, %s), 2100)"          # args: (x, y)
_PARCEL_REF = "(SELECT geom FROM sp_geodata.kaek_parcels_operating WHERE kaek = %s)"  # args: (kaek,)


def _kaek_non_special_use_filter(alias: str = None) -> str:
    """SQL filter that excludes special-use parcels marked with Latin EK or Greek ΕΚ."""
    col = f"{alias}.kaek" if alias else "kaek"
    return f"{col} NOT ILIKE '%%EK%%' AND {col} NOT ILIKE '%%ΕΚ%%'"


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
    """
    Δουλείες (ΕΑΣ) and αποκλειστικές χρήσεις (ΑΧ) registered on a parcel.
    Source: operating cadastre overlay tables (keyed by parent kaek).
    """
    out = {"apokleistikes": [], "douleies": []}
    apok_sql = """
    SELECT vp_num, ROUND(COALESCE(area, ST_Area(geom))::numeric, 1)
    FROM sp_geodata.kaek_apokleistikes_operating
    WHERE kaek = %s ORDER BY vp_num
    """
    for r in (execute_query(apok_sql, (kaek,)) or []):
        out["apokleistikes"].append({"num": r[0], "area_m2": float(r[1])})
    doul_sql = """
    SELECT right_sn, ROUND(COALESCE(area, ST_Area(geom))::numeric, 1)
    FROM sp_geodata.kaek_douleies_operating
    WHERE kaek = %s ORDER BY right_sn
    """
    for r in (execute_query(doul_sql, (kaek,)) or []):
        out["douleies"].append({"num": r[0], "area_m2": float(r[1])})
    return out


def _get_ydrolipsies_data(x: float = None, y: float = None,
                          ref_geom: str = None, ref_args: tuple = None,
                          max_distance: float = 500) -> dict:
    """
    ΕΜΣΥ σημεία υδροληψίας (γεωτρήσεις/πηγάδια/πηγές) relative to a point/parcel.
    Source: sp_geodata.ydrolipsies_emsy, filled by sync_ydrolipsies.py from the
    UNOFFICIAL ΥΠΕΝ viewer service. If the table is missing or the query fails,
    returns available=False and the report silently skips the section.
    """
    if ref_geom is None:
        ref_geom, ref_args = _POINT_REF, (x, y)
    result = {"available": False, "inside": [], "nearest": None}
    try:
        inside_sql = f"""
        SELECT eidos_sy, kathestws_xrhshs, kwdikos_emsy
        FROM sp_geodata.ydrolipsies_emsy
        WHERE ST_DWithin(geom, {ref_geom}, 0.5)
        ORDER BY kwdikos_emsy
        """
        inside = execute_query(inside_sql, (*ref_args,)) or []

        near_sql = f"""
        SELECT eidos_sy, kathestws_xrhshs, kwdikos_emsy,
               ROUND(ST_Distance(geom, {ref_geom})::numeric, 1)
        FROM sp_geodata.ydrolipsies_emsy
        WHERE ST_DWithin(geom, {ref_geom}, %s)
        ORDER BY ST_Distance(geom, {ref_geom})
        LIMIT 1
        """
        near = execute_query(
            near_sql, (*ref_args, *ref_args, max_distance, *ref_args),
            fetch_one=True)
    except Exception:
        return result  # πίνακας δεν υπάρχει ακόμα — τρέξε sync_ydrolipsies.py

    result["available"] = True
    for r in inside:
        result["inside"].append({"eidos": r[0], "status": r[1], "emsy": r[2]})
    if near:
        result["nearest"] = {"eidos": near[0], "status": near[1],
                             "emsy": near[2], "distance_m": float(near[3])}
    return result


def _ydro_point_label(w: dict) -> str:
    lbl = w.get("eidos") or "Σημείο υδροληψίας"
    if w.get("status"):
        lbl += f" ({w['status']})"
    if w.get("emsy"):
        lbl += f" — ΕΜΣΥ {w['emsy']}"
    return lbl


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

def _geom_rings(wkt_col_sql: str, args: tuple) -> list:
    """Exterior-ring coord strings for a geometry-returning SQL."""
    out = []
    for r in (execute_query(wkt_col_sql, args) or []):
        coords = _wkt_to_coords(r[0])
        if coords:
            out.append(";".join(f"{c[0]},{c[1]}" for c in coords))
    return out


def _is_special_kaek(kaek: str) -> bool:
    """EK/ΕΚ special-use parcels (roads, beaches...) — affected but not drawable."""
    k = (kaek or "").upper()
    return "ΕΚ" in k or "EK" in k


@app.post("/geom/diorthosi", response_class=PlainTextResponse)
async def geom_diorthosi(
    request: Request,
    tol: float = Query(0.5, description="Min piece area in m² (sliver filter)")
):
    """
    ΓΕΩ.Μ core: διόρθωση ορίων γεωτεμαχίου.
    Body (plain text): the surveyed TOPO_PROP ring as "x,y;x,y;...".

    Computes: subject parcel (max overlap), Δi = TOPO_PROP − subject (per
    source parcel), Αi = subject − TOPO_PROP (assigned to the neighbor with
    the longest shared boundary), τελικά γεωτεμάχια, ισοζύγιο εμβαδών and a
    μεταβολών table. Pieces smaller than `tol` m² are dropped as slivers
    (reported in the table note).

    Response (windows-1253-safe, pipe protocol):
      OK|subject_kaek|tol
      D|Δi|from_kaek|area|coords      → layer AREA_D
      A|Αi|to_kaek|area|coords        → layer AREA_A
      F|kaek|area|coords              → layer DGM_PROP_FINAL (one per ring)
      TBL|TYPE|c1|c2                  → rows for epol:draw-table-rows
    """
    body = (await request.body()).decode("utf-8", errors="replace").strip()
    if not body or ";" not in body:
        return "ERROR|Empty/invalid TOPO_PROP coordinates in request body"

    # Build closed POLYGON WKT from "x,y;x,y;..."
    try:
        pts = []
        for pair in body.split(";"):
            pair = pair.strip()
            if not pair:
                continue
            xs, ys = pair.split(",")
            pts.append((float(xs), float(ys)))
        if len(pts) < 3:
            return "ERROR|Need at least 3 vertices"
        if pts[0] != pts[-1]:
            pts.append(pts[0])
        topo_wkt = "POLYGON((" + ",".join(f"{p[0]} {p[1]}" for p in pts) + "))"
    except (ValueError, IndexError):
        return "ERROR|Could not parse coordinates (expected x,y;x,y;...)"

    TOPO = "ST_MakeValid(ST_GeomFromText(%s, 2100))"

    # ── Subject: non-special parcel with max overlap ─────────────────────────
    EK_FILTER = _kaek_non_special_use_filter()
    subj_sql = f"""
    SELECT kaek, ROUND(ST_Area(geom)::numeric, 2)
    FROM sp_geodata.kaek_parcels_operating
    WHERE {EK_FILTER} AND ST_Intersects(geom, {TOPO})
    ORDER BY ST_Area(ST_Intersection(ST_MakeValid(geom), {TOPO})) DESC
    LIMIT 1
    """
    subj = execute_query(subj_sql, (topo_wkt, topo_wkt), fetch_one=True)
    if not subj:
        return "ERROR|No operating parcel overlaps the TOPO_PROP polygon"
    subject_kaek, subject_area0 = subj[0], float(subj[1])

    topo_area_sql = f"SELECT ROUND(ST_Area({TOPO})::numeric, 2)"
    topo_area = float(execute_query(topo_area_sql, (topo_wkt,), fetch_one=True)[0])

    SUBJ = "(SELECT ST_MakeValid(geom) FROM sp_geodata.kaek_parcels_operating WHERE kaek = %s)"

    # ── Δi: claimed pieces (TOPO − subject), source = max-overlap parcel ─────
    d_sql = f"""
    WITH pieces AS (
        SELECT (ST_Dump(ST_CollectionExtract(
                   ST_Difference({TOPO}, {SUBJ}), 3))).geom AS g
    )
    SELECT ST_AsText(ST_ExteriorRing(g)),
           ROUND(ST_Area(g)::numeric, 2),
           (SELECT p.kaek FROM sp_geodata.kaek_parcels_operating p
            WHERE p.kaek != %s AND ST_Intersects(p.geom, g)
            ORDER BY ST_Area(ST_Intersection(ST_MakeValid(p.geom), g)) DESC
            LIMIT 1)
    FROM pieces
    WHERE ST_Area(g) >= %s
    ORDER BY ST_Area(g) DESC
    """
    d_rows = execute_query(d_sql, (topo_wkt, subject_kaek, subject_kaek, tol)) or []

    # sliver accounting
    d_sliv_sql = f"""
    WITH pieces AS (
        SELECT (ST_Dump(ST_CollectionExtract(
                   ST_Difference({TOPO}, {SUBJ}), 3))).geom AS g
    )
    SELECT COUNT(*), COALESCE(ROUND(SUM(ST_Area(g))::numeric, 2), 0)
    FROM pieces WHERE ST_Area(g) < %s
    """
    d_sliv = execute_query(d_sliv_sql, (topo_wkt, subject_kaek, tol), fetch_one=True)

    # ── Αi: cut pieces (subject − TOPO), assigned by longest shared boundary ─
    a_sql = f"""
    WITH pieces AS (
        SELECT (ST_Dump(ST_CollectionExtract(
                   ST_Difference({SUBJ}, {TOPO}), 3))).geom AS g
    )
    SELECT ST_AsText(ST_ExteriorRing(g)),
           ROUND(ST_Area(g)::numeric, 2),
           (SELECT p.kaek FROM sp_geodata.kaek_parcels_operating p
            WHERE p.kaek != %s AND ST_DWithin(p.geom, g, 0.05)
            ORDER BY ST_Length(ST_Intersection(
                ST_Boundary(ST_MakeValid(p.geom)), ST_Boundary(g))) DESC
            LIMIT 1)
    FROM pieces
    WHERE ST_Area(g) >= %s
    ORDER BY ST_Area(g) DESC
    """
    a_rows = execute_query(a_sql, (subject_kaek, topo_wkt, subject_kaek, tol)) or []

    a_sliv_sql = f"""
    WITH pieces AS (
        SELECT (ST_Dump(ST_CollectionExtract(
                   ST_Difference({SUBJ}, {TOPO}), 3))).geom AS g
    )
    SELECT COUNT(*), COALESCE(ROUND(SUM(ST_Area(g))::numeric, 2), 0)
    FROM pieces WHERE ST_Area(g) < %s
    """
    a_sliv = execute_query(a_sliv_sql, (subject_kaek, topo_wkt, tol), fetch_one=True)

    # ── Affected parcels & finals ────────────────────────────────────────────
    # X_final = (X − TOPO) ∪ assigned Αi pieces; subject_final = TOPO
    gains = {}  # kaek -> True (receives Αi)
    for r in a_rows:
        if r[2]:
            gains[r[2]] = True
    losers = {}  # kaek -> True (loses Δi)
    for r in d_rows:
        if r[2]:
            losers[r[2]] = True
    affected = sorted(set(list(gains) + list(losers)))

    lines = [f"OK|{subject_kaek}|{tol}"]

    for i, r in enumerate(d_rows, 1):
        coords = _wkt_to_coords(r[0])
        if coords:
            cs = ";".join(f"{c[0]},{c[1]}" for c in coords)
            lines.append(f"D|Δ{i}|{r[2] or '—'}|{r[1]}|{cs}")

    for i, r in enumerate(a_rows, 1):
        coords = _wkt_to_coords(r[0])
        if coords:
            cs = ";".join(f"{c[0]},{c[1]}" for c in coords)
            lines.append(f"A|Α{i}|{r[2] or '—'}|{r[1]}|{cs}")

    # Subject final = the surveyed polygon itself
    subj_final_rings = _geom_rings(
        f"SELECT ST_AsText(ST_ExteriorRing((ST_Dump({TOPO})).geom))", (topo_wkt,))
    for cs in subj_final_rings:
        lines.append(f"F|{subject_kaek}|{topo_area}|{cs}")

    # Neighbor finals (skip EK/roads — too large to draw; reported in table)
    finals_table = [(subject_kaek, subject_area0, topo_area, False)]
    for nk in affected:
        special = _is_special_kaek(nk)
        fin_sql = f"""
        WITH base AS (
            SELECT ST_Difference(
                (SELECT ST_MakeValid(geom)
                 FROM sp_geodata.kaek_parcels_operating WHERE kaek = %s),
                {TOPO}) AS g
        )
        SELECT ROUND(ST_Area(g)::numeric, 2), ST_AsText(g) FROM base
        """
        fin = execute_query(fin_sql, (nk, topo_wkt), fetch_one=True)
        if not fin:
            continue
        # add assigned Αi areas
        gained = sum(float(r[1]) for r in a_rows if r[2] == nk)
        init_sql = """
        SELECT ROUND(ST_Area(geom)::numeric, 2)
        FROM sp_geodata.kaek_parcels_operating WHERE kaek = %s
        """
        init = execute_query(init_sql, (nk,), fetch_one=True)
        init_area = float(init[0]) if init else 0.0
        final_area = round(float(fin[0]) + gained, 2)
        finals_table.append((nk, init_area, final_area, special))

        if not special:
            fin_rings_sql = f"""
            WITH base AS (
                SELECT ST_Union(
                    ST_Difference(
                        (SELECT ST_MakeValid(geom)
                         FROM sp_geodata.kaek_parcels_operating WHERE kaek = %s),
                        {TOPO}),
                    COALESCE((
                        SELECT ST_Union(g) FROM (
                            SELECT (ST_Dump(ST_CollectionExtract(
                                ST_Difference({SUBJ}, {TOPO}), 3))).geom AS g
                        ) pieces
                        WHERE ST_Area(g) >= %s
                          AND (SELECT p2.kaek FROM sp_geodata.kaek_parcels_operating p2
                               WHERE p2.kaek != %s AND ST_DWithin(p2.geom, g, 0.05)
                               ORDER BY ST_Length(ST_Intersection(
                                   ST_Boundary(ST_MakeValid(p2.geom)), ST_Boundary(g))) DESC
                               LIMIT 1) = %s
                    ), ST_GeomFromText('POLYGON EMPTY', 2100))
                ) AS g
            )
            SELECT ST_AsText(ST_ExteriorRing((ST_Dump(ST_CollectionExtract(g, 3))).geom))
            FROM base
            """
            for cs in _geom_rings(fin_rings_sql,
                                  (nk, topo_wkt, subject_kaek, topo_wkt,
                                   tol, subject_kaek, nk)):
                lines.append(f"F|{nk}|{final_area}|{cs}")

    # ── Ισοζύγιο & πίνακας μεταβολών ─────────────────────────────────────────
    sum_d = round(sum(float(r[1]) for r in d_rows), 2)
    sum_a = round(sum(float(r[1]) for r in a_rows), 2)
    balance = round(subject_area0 + sum_d - sum_a - topo_area, 2)

    tbl = ["TITLE|ΠΙΝΑΚΑΣ ΜΕΤΑΒΟΛΩΝ|Διόρθωση ορίων",
           "HEADER|Αρχικά / Τελικά γεωτεμάχια|"]
    for kaek, a0, a1, special in finals_table:
        diff = round(a1 - a0, 2)
        sign = f"+{diff}" if diff > 0 else str(diff)
        note = " (κοινόχρ./ΕΚ — δεν σχεδιάζεται)" if special else ""
        tbl.append(f"ROW|{kaek}{note}|{a0} → {a1} τ.μ. ({sign})")
    if d_rows or a_rows:
        tbl.append("HEADER|Τμήματα|")
        for i, r in enumerate(d_rows, 1):
            tbl.append(f"ROW|Δ{i} (από {r[2] or '—'})|{r[1]} τ.μ.")
        for i, r in enumerate(a_rows, 1):
            tbl.append(f"ROW|Α{i} (προς {r[2] or '—'})|{r[1]} τ.μ.")
    tbl.append(f"MERGED|Ισοζύγιο: {subject_area0} + Δ({sum_d}) − Α({sum_a}) − "
               f"τελικό({topo_area}) = {balance} τ.μ."
               + (" ✓" if abs(balance) < 0.05 else " — ΕΛΕΓΞΕ!") + "|")
    if d_sliv and (d_sliv[0] or 0) > 0:
        tbl.append(f"MERGED|Αγνοήθηκαν {d_sliv[0]} slivers Δ συνολικού εμβαδού "
                   f"{d_sliv[1]} τ.μ. (όριο {tol} τ.μ.)|")
    if a_sliv and (a_sliv[0] or 0) > 0:
        tbl.append(f"MERGED|Αγνοήθηκαν {a_sliv[0]} slivers Α συνολικού εμβαδού "
                   f"{a_sliv[1]} τ.μ. (όριο {tol} τ.μ.)|")

    lines.extend("TBL|" + t for t in tbl)

    text = "\n".join(lines)
    return text.encode('windows-1253', errors='replace').decode('windows-1253')


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
    vp_num/title fields may be empty (auto-match / unknown).

    Does: parent parcel by max overlap · VST_FINAL = clip στο γεωτεμάχιο ·
    αντιστοίχιση με κτηματολογικές ΑΧ (max overlap, mismatch warning) ·
    pairwise overlap check · κοινόχρηστο υπόλοιπο · LINE_XM_VST (εσωτερικές
    γραμμές, το περίγραμμα του γεωτεμαχίου αφαιρείται) · πίνακας
    τίτλος/κτηματολόγιο/αποτύπωση με χιλιοστά.

    Response:  OK|kaek|parcel_area
               VF|num|area|coords     → VST_FINAL
               L|coords               → LINE_XM_VST (open)
               TBL|TYPE|c1|c2         → table rows
    """
    body = (await request.body()).decode("utf-8", errors="replace").strip()
    if not body:
        return "ERROR|Empty body"

    vsts = []  # dicts: num, title_area, title_xil, wkt
    for ln in body.splitlines():
        ln = ln.strip()
        if not ln or not ln.startswith("V|"):
            continue
        try:
            _, num, ta, tx, coords = ln.split("|", 4)
            pts = []
            for pair in coords.split(";"):
                if pair.strip():
                    xs, ys = pair.split(",")
                    pts.append((float(xs), float(ys)))
            if len(pts) < 3:
                return f"ERROR|VST {num or '?'}: needs at least 3 vertices"
            if pts[0] != pts[-1]:
                pts.append(pts[0])
            vsts.append({
                "num": num.strip(),
                "title_area": float(ta) if ta.strip() else None,
                "title_xil": float(tx) if tx.strip() else None,
                "wkt": "POLYGON((" + ",".join(f"{p[0]} {p[1]}" for p in pts) + "))",
            })
        except (ValueError, IndexError):
            return "ERROR|Could not parse VST line (V|num|area|xil|coords)"
    if not vsts:
        return "ERROR|No V| lines in body"

    G = "ST_MakeValid(ST_GeomFromText(%s, 2100))"
    union_sql_parts = ",".join([G] * len(vsts))
    union_expr = f"ST_Union(ARRAY[{union_sql_parts}])"
    all_wkts = tuple(v["wkt"] for v in vsts)

    # ── Parent parcel: max overlap with the union of surveyed VSTs ──────────
    EK_FILTER = _kaek_non_special_use_filter()
    parent_sql = f"""
    SELECT kaek, ROUND(ST_Area(geom)::numeric, 2)
    FROM sp_geodata.kaek_parcels_operating
    WHERE {EK_FILTER} AND ST_Intersects(geom, {union_expr})
    ORDER BY ST_Area(ST_Intersection(ST_MakeValid(geom), {union_expr})) DESC
    LIMIT 1
    """
    parent = execute_query(parent_sql, all_wkts + all_wkts, fetch_one=True)
    if not parent:
        return "ERROR|No operating parcel overlaps the surveyed κάθετες"
    kaek, parcel_area = parent[0], float(parent[1])
    PARCEL = "(SELECT ST_MakeValid(geom) FROM sp_geodata.kaek_parcels_operating WHERE kaek = %s)"

    # ── Cadastre ΑΧ of the parent parcel ─────────────────────────────────────
    kt_ax = {r[0]: float(r[1]) for r in (execute_query(
        """SELECT vp_num, ROUND(COALESCE(area, ST_Area(geom))::numeric, 1)
           FROM sp_geodata.kaek_apokleistikes_operating WHERE kaek = %s""",
        (kaek,)) or [])}

    lines = [f"OK|{kaek}|{parcel_area}"]
    tbl = [f"TITLE|ΠΙΝΑΚΑΣ ΚΑΘΕΤΩΝ|Διόρθωση καθέτων — {kaek}",
           "HEADER|Γεωτεμάχιο|",
           f"ROW|ΚΑΕΚ|{kaek} — {parcel_area} τ.μ.",
           "HEADER|Κάθετες: τίτλος / κτηματ. / αποτύπωση|"]
    warnings = []
    matched_vps = set()

    for i, v in enumerate(vsts, 1):
        num = v["num"] or f"{i:02d}"
        row = execute_query(f"""
            SELECT ROUND(ST_Area({G})::numeric, 2),
                   ROUND(ST_Area(ST_Intersection({G}, {PARCEL}))::numeric, 2)
            """, (v["wkt"], v["wkt"], kaek), fetch_one=True)
        meas_area, clip_area = float(row[0]), float(row[1])
        if clip_area < tol:
            warnings.append(f"ΑΧ {num}: εκτός γεωτεμαχίου — αγνοήθηκε")
            continue
        clip_loss = round(meas_area - clip_area, 2)
        if clip_loss > 0.05:
            warnings.append(f"ΑΧ {num}: κόπηκαν {clip_loss} τ.μ. εκτός ορίου γεωτεμαχίου")

        # match to cadastre ΑΧ by max overlap
        m = execute_query(f"""
            SELECT vp_num, ROUND(ST_Area(ST_Intersection(
                       ST_MakeValid(a.geom), {G}))::numeric, 2)
            FROM sp_geodata.kaek_apokleistikes_operating a
            WHERE a.kaek = %s AND ST_Intersects(a.geom, {G})
            ORDER BY 2 DESC LIMIT 1
            """, (v["wkt"], kaek, v["wkt"]), fetch_one=True)
        matched = m[0] if m else None
        if matched:
            matched_vps.add(matched)
        if matched and v["num"] and matched != v["num"]:
            warnings.append(f"ΑΧ {num}: μέγιστη επικάλυψη με κτηματολογική ΑΧ {matched} — έλεγξε αρίθμηση")

        # final rings (clipped)
        for cs in _geom_rings(f"""
                SELECT ST_AsText(ST_ExteriorRing((ST_Dump(ST_CollectionExtract(
                    ST_Intersection({G}, {PARCEL}), 3))).geom))
                """, (v["wkt"], kaek)):
            lines.append(f"VF|{num}|{clip_area}|{cs}")

        impl_xil = round(clip_area / parcel_area * 1000, 1) if parcel_area else 0
        t_area = f"{v['title_area']}" if v["title_area"] is not None else "—"
        t_xil = f"{v['title_xil']}‰" if v["title_xil"] is not None else "—"
        kt_area = f"{kt_ax.get(matched, '—')}" if matched else "—"
        tbl.append(f"ROW|ΑΧ {num}|τίτλ: {t_area} ({t_xil}) · ΚΤ({matched or '—'}): {kt_area} "
                   f"· μέτρ: {clip_area} ({impl_xil}‰)")
        if v["title_area"] is not None:
            d = round(clip_area - v["title_area"], 2)
            if abs(d) > tol:
                warnings.append(f"ΑΧ {num}: μέτρηση − τίτλος = {d:+} τ.μ.")

    # ── Pairwise overlaps between clipped VSTs ───────────────────────────────
    for i in range(len(vsts)):
        for j in range(i + 1, len(vsts)):
            ov = execute_query(f"""
                SELECT ROUND(ST_Area(ST_Intersection(
                    ST_Intersection({G}, {PARCEL}),
                    ST_Intersection({G}, {PARCEL})))::numeric, 2)
                """, (vsts[i]["wkt"], kaek, vsts[j]["wkt"], kaek), fetch_one=True)
            if ov and float(ov[0]) > tol:
                warnings.append(f"ΕΠΙΚΑΛΥΨΗ ΑΧ {vsts[i]['num'] or i+1} με "
                                f"ΑΧ {vsts[j]['num'] or j+1}: {ov[0]} τ.μ.")

    # ── Κοινόχρηστο υπόλοιπο + άφαντες κτηματολογικές ΑΧ ────────────────────
    rest = execute_query(f"""
        SELECT ROUND(ST_Area(ST_Difference({PARCEL}, {union_expr}))::numeric, 2)
        """, (kaek,) + all_wkts, fetch_one=True)
    rest_area = float(rest[0]) if rest else 0.0
    tbl.append("HEADER|Έλεγχοι|")
    tbl.append(f"ROW|Κοινόχρηστο εκτός ΑΧ|{rest_area} τ.μ. "
               f"({round(rest_area / parcel_area * 1000, 1) if parcel_area else 0}‰)")
    for vp in sorted(set(kt_ax) - matched_vps):
        warnings.append(f"Κτηματολογική ΑΧ {vp} ({kt_ax[vp]} τ.μ.) δεν αντιστοιχήθηκε σε καμία μέτρηση")
    for w in warnings:
        tbl.append(f"MERGED|⚠ {w}|")
    if not warnings:
        tbl.append("MERGED|Όλοι οι έλεγχοι εντάξει — καμία προειδοποίηση.|")

    # ── LINE_XM_VST: εσωτερικές γραμμές (χωρίς το περίγραμμα γεωτεμαχίου) ────
    l_sql = f"""
    WITH clipped AS (
        SELECT ST_Union(ARRAY[{",".join(
            [f"ST_Boundary(ST_Intersection({G}, {PARCEL}))"] * len(vsts))}]) AS b
    )
    SELECT ST_AsText((ST_Dump(ST_LineMerge(
        ST_Difference(b, ST_Boundary({PARCEL}))))).geom)
    FROM clipped
    """
    l_args = []
    for v in vsts:
        l_args.extend([v["wkt"], kaek])
    l_args.append(kaek)
    for r in (execute_query(l_sql, tuple(l_args)) or []):
        coords = _wkt_to_coords(r[0])
        if coords and len(coords) > 1:
            lines.append("L|" + ";".join(f"{c[0]},{c[1]}" for c in coords))

    lines.extend("TBL|" + t for t in tbl)
    text = "\n".join(lines)
    return text.encode('windows-1253', errors='replace').decode('windows-1253')


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
    """Get comprehensive building regulations data for the OROITABLE command."""

    data = {
        "found": False,
        "ot_num": None,                  # Οικοδομικό Τετράγωνο
        "diatagmata_entaxis": [],      # FEKs for Ένταξης-Ρυμοτομίας
        "diatagmata_oron": [],          # FEKs for Όρων Δόμησης
        "xriseis": "Γενική Κατοικία",   # Hardcoded
        "tomeis": [],                    # All sectors with their regulations
        "egkriseis": [],                 # Approvals required (Αρχαιολογία, etc.)
        "loipa": [],                     # Λοιπά remarks from DB
        "loipoi_periorismoi": "ΦΕΚ 740Δ'/1981, ΓΟΚ 85/2000, ΝΟΚ 2012",  # Hardcoded
        "kata_parekklisi": None,         # Exception rules
        "plimmyra": "Η δόμηση επιτρέπεται σε απόσταση 10μ. από τις πιθανές γραμμές πλημμύρας (Ν.4258/2014 αρθ.9 παρ.4Α — εκκρεμεί ΦΕΚ οριοθέτησης)",  # Hardcoded
    }

    # 0. Get OT number from building_blocks
    ot_sql = """
    SELECT ot_num
    FROM epoleodomia.building_blocks
    WHERE NOT COALESCE(is_deleted, false)
      AND ST_Contains(geom, ST_SetSRID(ST_Point(%s, %s), 2100))
    LIMIT 1
    """
    ot_result = execute_query(ot_sql, (x, y), fetch_one=True)
    if ot_result and ot_result[0]:
        data["ot_num"] = ot_result[0]
        data["found"] = True

    # 1. Get ΔΙΑΤΑΓΜΑΤΑ Ένταξης-Ρυμοτομίας from approved_plan_boundaries
    # These are the FEKs for planning/zoning approvals (ρυμοτομικά διατάγματα)
    entaxis_sql = """
    SELECT DISTINCT fek, apof_eidos, title, publ_date
    FROM epoleodomia.approved_plan_boundaries
    WHERE NOT COALESCE(is_deleted, false)
      AND ST_Contains(geom, ST_SetSRID(ST_Point(%s, %s), 2100))
    ORDER BY publ_date
    """
    entaxis_result = execute_query(entaxis_sql, (x, y), fetch_one=False)
    if entaxis_result:
        # Format: "ΦΕΚ xxx (Π.Δ./Υ.Α./κλπ)"
        fek_list = []
        for r in entaxis_result:
            if r[0]:  # fek exists
                fek = r[0]
                apof_eidos = r[1] if r[1] else ""
                # Shorten apof_eidos for display
                if "ΠΡΟΕΔΡΙΚΟ ΔΙΑΤΑΓΜΑ" in apof_eidos:
                    apof_short = "Π.Δ."
                elif "ΥΠΟΥΡΓΙΚΗ ΑΠΟΦΑΣΗ" in apof_eidos:
                    apof_short = "Υ.Α."
                elif "ΑΠΟΦΑΣΗ ΝΟΜΑΡΧΗ" in apof_eidos:
                    apof_short = "Απ.Νομ."
                elif "ΑΠΟΦΑΣΗ ΓΕΝΙΚΟΥ ΓΡΑΜΜΑΤΕΑ" in apof_eidos:
                    apof_short = "Απ.Γ.Γ."
                else:
                    apof_short = ""

                if apof_short:
                    fek_list.append(f"{apof_short} ΦΕΚ {fek}")
                else:
                    fek_list.append(f"ΦΕΚ {fek}")
        data["diatagmata_entaxis"] = fek_list
        data["found"] = True

    # 2. Get ΔΙΑΤΑΓΜΑΤΑ Όρων Δόμησης from all building_regs_* tables
    oron_sql = """
    SELECT DISTINCT fek FROM (
        SELECT fek FROM epoleodomia.building_regs_height
        WHERE NOT COALESCE(is_deleted, false) AND ST_Contains(geom, ST_SetSRID(ST_Point(%s, %s), 2100))
        UNION
        SELECT fek FROM epoleodomia.building_regs_coverage
        WHERE NOT COALESCE(is_deleted, false) AND ST_Contains(geom, ST_SetSRID(ST_Point(%s, %s), 2100))
        UNION
        SELECT fek FROM epoleodomia.building_regs_coefficient
        WHERE NOT COALESCE(is_deleted, false) AND ST_Contains(geom, ST_SetSRID(ST_Point(%s, %s), 2100))
        UNION
        SELECT fek FROM epoleodomia.building_regs_lot
        WHERE NOT COALESCE(is_deleted, false) AND ST_Contains(geom, ST_SetSRID(ST_Point(%s, %s), 2100))
        UNION
        SELECT fek FROM epoleodomia.building_regs_system
        WHERE NOT COALESCE(is_deleted, false) AND ST_Contains(geom, ST_SetSRID(ST_Point(%s, %s), 2100))
    ) AS all_feks
    ORDER BY fek
    """
    oron_result = execute_query(oron_sql, (x, y) * 5, fetch_one=False)
    if oron_result:
        data["diatagmata_oron"] = [r[0] for r in oron_result if r[0]]
        data["found"] = True

    # 3. Get ΤΟΜΕΑΣ data - query each table separately at the point
    # Coefficient (has sd_tomeas)
    coef_sql = """
    SELECT DISTINCT sd_tomeas, sd_timh, sd_klimakotos, sd_comment, fek
    FROM epoleodomia.building_regs_coefficient
    WHERE NOT COALESCE(is_deleted, false)
      AND ST_Contains(geom, ST_SetSRID(ST_Point(%s, %s), 2100))
    """
    coef_result = execute_query(coef_sql, (x, y), fetch_one=True)

    # Height
    height_sql = """
    SELECT DISTINCT max_height_m, num_orofon, oror_max_height_comment, fek
    FROM epoleodomia.building_regs_height
    WHERE NOT COALESCE(is_deleted, false)
      AND ST_Contains(geom, ST_SetSRID(ST_Point(%s, %s), 2100))
    """
    height_result = execute_query(height_sql, (x, y), fetch_one=True)

    # Coverage
    coverage_sql = """
    SELECT DISTINCT synt_kalypsis, remarks, fek
    FROM epoleodomia.building_regs_coverage
    WHERE NOT COALESCE(is_deleted, false)
      AND ST_Contains(geom, ST_SetSRID(ST_Point(%s, %s), 2100))
    """
    coverage_result = execute_query(coverage_sql, (x, y), fetch_one=True)

    # Lot (ΚΑΤΑ ΚΑΝΟΝΑ only)
    lot_sql = """
    SELECT DISTINCT elax_embado_m2, elax_prosop_m, fek
    FROM epoleodomia.building_regs_lot
    WHERE NOT COALESCE(is_deleted, false)
      AND oros_type = 'ΚΑΤΑ ΚΑΝΟΝΑ'
      AND ST_Contains(geom, ST_SetSRID(ST_Point(%s, %s), 2100))
    """
    lot_result = execute_query(lot_sql, (x, y), fetch_one=True)

    # System
    system_sql = """
    SELECT DISTINCT oik_systima, fek
    FROM epoleodomia.building_regs_system
    WHERE NOT COALESCE(is_deleted, false)
      AND ST_Contains(geom, ST_SetSRID(ST_Point(%s, %s), 2100))
    """
    system_result = execute_query(system_sql, (x, y), fetch_one=True)

    # Build single tomeas from results
    if coef_result or height_result or coverage_result:
        tomeas = {
            "name": coef_result[0] if coef_result and coef_result[0] else "ΚΑΤΑ ΚΑΝΟΝΑ",
            "sd": coef_result[1] if coef_result else None,
            "sd_klimakotos": coef_result[2] if coef_result else None,
            "sd_comment": coef_result[3] if coef_result else None,
            "sd_fek": coef_result[4] if coef_result else None,
            "max_height_m": height_result[0] if height_result else None,
            "num_orofon": height_result[1] if height_result else None,
            "height_comment": height_result[2] if height_result else None,
            "height_fek": height_result[3] if height_result else None,
            "coverage_pct": coverage_result[0] if coverage_result else None,
            "coverage_remarks": coverage_result[1] if coverage_result else None,
            "coverage_fek": coverage_result[2] if coverage_result else None,
            "elax_embado_m2": lot_result[0] if lot_result else None,
            "elax_prosop_m": lot_result[1] if lot_result else None,
            "lot_fek": lot_result[2] if lot_result else None,
            "oik_systima": system_result[0] if system_result else None,
            "system_fek": system_result[1] if system_result else None,
        }
        data["tomeis"].append(tomeas)
        data["found"] = True

    # 4. Get ΕΓΚΡΙΣΕΙΣ
    # Always add required approvals for Spetses (hardcoded)
    data["egkriseis"].append("Συμβούλιο Αρχιτεκτονικής")
    data["egkriseis"].append("Υπηρεσία Νεωτέρων Μνημείων")

    # Check sp_geodata archaeology tables for ΕΦΑ approval requirement
    archeo_zone_sql = """
    SELECT 1 FROM sp_geodata."Αρχαιολογία_Ζώνες_Προστασίας"
    WHERE NOT ST_IsEmpty(ST_BuildArea(geom))
      AND ST_Covers(
          ST_CollectionExtract(ST_MakeValid(ST_BuildArea(geom)), 3),
          ST_SetSRID(ST_Point(%s, %s), 2100)
      )
    LIMIT 1
    """
    archeo_mon_sql = """
    SELECT 1 FROM sp_geodata."Αρχαιλογία_Κυρηγμένα_Μνημεία"
    WHERE ST_DWithin(geom, ST_SetSRID(ST_Point(%s, %s), 2100), 100)
    LIMIT 1
    """
    try:
        zone_hit = execute_query(archeo_zone_sql, (x, y), fetch_one=True)
        mon_hit = execute_query(archeo_mon_sql, (x, y), fetch_one=True)
        if (zone_hit or mon_hit) and "Αρχαιολογία (ΕΦΑ)" not in data["egkriseis"]:
            data["egkriseis"].append("Αρχαιολογία (ΕΦΑ)")
    except Exception:
        pass  # archaeology tables unavailable — skip

    # 5. Collect ΛΟΙΠΑ from comments (avoid duplicates)
    loipa_set = set()
    for tomeas in data["tomeis"]:
        if tomeas.get("height_comment"):
            loipa_set.add(tomeas["height_comment"])
        if tomeas.get("sd_comment"):
            loipa_set.add(tomeas["sd_comment"])
        if tomeas.get("coverage_remarks"):
            loipa_set.add(tomeas["coverage_remarks"])
    data["loipa"] = list(loipa_set)

    # 6. Get ΚΑΤΑ ΠΑΡΕΚΚΛΙΣΗ
    parek_sql = """
    SELECT remarks, date_pareklisis, fek
    FROM epoleodomia.building_regs_lot
    WHERE NOT COALESCE(is_deleted, false)
      AND oros_type = 'ΚΑΤΑ ΠΑΡΕΚΚΛΙΣΗ'
      AND ST_Contains(geom, ST_SetSRID(ST_Point(%s, %s), 2100))
    LIMIT 1
    """
    parek_result = execute_query(parek_sql, (x, y), fetch_one=True)
    if parek_result:
        data["kata_parekklisi"] = {
            "remarks": parek_result[0],
            "date": parek_result[1],
            "fek": parek_result[2],
        }

    return data


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


def _fmt_parcel_dist(d, kind: str = "line") -> str:
    """
    Render a parcel-to-feature distance for the parcel report. A distance of 0
    means the feature crosses or sits inside the parcel; show that as 'διέρχεται'
    for linear features (shoreline, streams) and 'εντός' for point features
    (monuments) instead of a bare '0 μ.'.
    """
    if d is None:
        return "—"
    if d < 0.5:
        return "διέρχεται" if kind == "line" else "εντός"
    return f"{d} μ."


def _shore_crossing_list(shore: dict) -> list:
    """Shoreline/beach/old-shoreline lines that cross the parcel (< 0.5 μ.)."""
    by_type = {r["info"]: r for r in shore.get("lines", [])}
    crossing = []
    for key in ("Γραμμή Αιγιαλού", "Γραμμή Αιγιαλού_ΠΟΑ",
                "Γραμμή Παραλίας", "Γραμμή Παραλίας_ΠΟΑ",
                "Γραμμή Παλαιού Αιγιαλού"):
        r = by_type.get(key)
        if r and r.get("distance_m") is not None and r["distance_m"] < 0.5:
            label = _AIGIALOS_LABELS.get(key, key)
            fek = f" (ΦΕΚ {r['fek']})" if r.get("fek") else ""
            crossing.append(f"{label}{fek}")
    return crossing


def _build_parcel_shoreline_rows(shore: dict) -> list:
    """
    Summarise shoreline constraints for parcel reports. The legal check is
    whether any shoreline/beach/old-shoreline line crosses the parcel; distance
    is reported only for the nearest current shoreline, established or POA.
    """
    rows = ["HEADER|ΑΙΓΙΑΛΟΣ / ΠΑΡΑΛΙΑ|"]
    by_type = {r["info"]: r for r in shore.get("lines", [])}

    crossing = _shore_crossing_list(shore)
    if crossing:
        rows.append(f"ROW|Διέλευση γραμμής|ΝΑΙ - {', '.join(crossing)}")
    else:
        rows.append("ROW|Διέλευση γραμμής|ΟΧΙ")

    aigialos_types = ["Γραμμή Αιγιαλού", "Γραμμή Αιγιαλού_ΠΟΑ"]
    candidates = [by_type[key] for key in aigialos_types if key in by_type]
    if candidates:
        nearest = min(
            candidates,
            key=lambda r: (
                float("inf") if r.get("distance_m") is None else r["distance_m"],
                1 if str(r.get("info", "")).endswith("_ΠΟΑ") else 0,
            ),
        )
        dist = nearest.get("distance_m")
        value = "-" if dist is None else f"{dist} μ."
        source = "ΠΟΑ" if str(nearest.get("info", "")).endswith("_ΠΟΑ") else "καθορισμένος"
        details = [source]
        if nearest.get("fek"):
            details.append(f"ΦΕΚ {nearest['fek']}")
        rows.append(f"ROW|Απόσταση από Αιγιαλό|{value} ({', '.join(details)})")

    return rows


def _build_regs_rows(oroi: dict) -> list:
    """
    Format the ΟΡΟΙ ΔΟΜΗΣΗΣ (building-regulations) section into report rows.
    Shared by the point report (/report/rows) and the parcel report
    (/report/parcel); regulations are always computed at the clicked point.
    """
    rows = []
    ot_label = f"O.T. {oroi['ot_num']}" if oroi.get("ot_num") else "SPETSES"
    rows.append(f"TITLE|ΟΡOI ΔΟΜΗΣΗΣ|{ot_label}")
    rows.append(f"ROW|Χρήσεις γης|{oroi['xriseis']}")

    if oroi["diatagmata_entaxis"]:
        rows.append("HEADER|Διατάγματα Εντάξεως - Ρυμοτομίας|")
        for fek in oroi["diatagmata_entaxis"]:
            rows.append(f"ROW||{fek}")

    if oroi["diatagmata_oron"]:
        rows.append("HEADER|Διατάγματα Όρων Δόμησης|")
        for fek in oroi["diatagmata_oron"]:
            rows.append(f"ROW||{fek}")

    for tomeas in oroi["tomeis"]:
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

    if oroi.get("kata_parekklisi"):
        rows.append("HEADER|Κατά Παρέκκλιση|")
        parek = oroi["kata_parekklisi"]
        if parek.get("date"):
            rows.append(f"ROW|Προ|προ {parek['date']}")
        if parek.get("remarks"):
            rows.append(f"MERGED|{parek['remarks']}|")
        if parek.get("fek"):
            rows.append(f"ROW|ΦΕΚ|{parek['fek']}")

    if oroi["egkriseis"]:
        rows.append("HEADER|Απαιτούμενες Εγκρίσεις|")
        rows.append(f"ROW||{', '.join(oroi['egkriseis'])}")

    loipoi_rows = []
    if oroi.get("loipoi_periorismoi"):
        loipoi_rows.append(f"MERGED|{oroi['loipoi_periorismoi']}|")
    if oroi.get("loipa"):
        for item in oroi["loipa"]:
            if item:
                loipoi_rows.append(f"MERGED|{item}|")
    if oroi.get("plimmyra"):
        loipoi_rows.append(f"MERGED|{oroi['plimmyra']}|")
    if loipoi_rows:
        rows.append("HEADER|Λοιποί Περιορισμοί|")
        rows.extend(loipoi_rows)

    return rows


def _ektos_max_domisi(area_m2: float) -> float:
    """
    Επιτρεπόμενη δόμηση κατοικίας εκτός σχεδίου (Ν.4759/2020, άρθρο 33):
    4.000–8.000: 186 + 0.018×(Ε−4.000) | >8.000: 258 + 0.009×(Ε−8.000), μέγ. 360.
    """
    if area_m2 < 4000:
        return 0.0
    if area_m2 <= 8000:
        return round(186 + 0.018 * (area_m2 - 4000), 1)
    return round(min(258 + 0.009 * (area_m2 - 8000), 360.0), 1)


def _build_ektos_sxediou_rows(parcel_area_m2: float = None,
                              extra_approvals: list = None) -> list:
    """
    ΟΡΟΙ ΔΟΜΗΣΗΣ — ΕΚΤΟΣ ΣΧΕΔΙΟΥ/ΟΡΙΩΝ ΟΙΚΙΣΜΟΥ (static block).
    Πηγές: Π.Δ. 24.05.1985 (ΦΕΚ Δ' 270), Ν.4759/2020 (ΦΕΚ Α' 245),
    ΖΟΕ Αττικής Π.Δ. 22.06.1983 (ΦΕΚ Δ' 284), Ν.5261/2025 (μεταβατικές).
    If parcel_area_m2 is given, computes αρτιότητα and επιτρεπόμενη δόμηση.
    """
    rows = []
    rows.append("TITLE|ΟΡOI ΔΟΜΗΣΗΣ|ΕΚΤΟΣ ΣΧΕΔΙΟΥ")
    rows.append("ROW|Καθεστώς|Π.Δ. 24.05.85 (ΦΕΚ 270Δ') + Ν.4759/2020")

    rows.append("HEADER|Κατά Κανόνα (χρήση: κατοικία)|")
    rows.append("ROW|Αρτιότητα|4.000 τ.μ.")
    rows.append("ROW|Πρόσωπο|σε κοινόχρηστη οδό (25 μ. για γήπεδα μετά 9.12.20)")
    rows.append("ROW|Σε εθν./επαρχ. οδό|πρόσωπο 45 μ. — βάθος 50 μ.")
    rows.append("ROW|Κάλυψη|10%")
    rows.append("ROW|Μέγ. Ύψος|7,50 μ. (2 όροφοι) +1,20 μ. στέγη")
    rows.append("ROW|Αποστάσεις ορίων|15 μ.")
    rows.append("ROW|Από ρέμα / δάσος|10 μ. / 10 μ.")
    rows.append("ROW|Κατάτμηση (ΖΟΕ Αττ.)|20.000 τ.μ. (Π.Δ. 22.06.83, ΦΕΚ 284Δ')")

    rows.append("HEADER|Επιτρεπόμενη Δόμηση (κατοικία)|")
    rows.append("ROW|4.000–8.000 τ.μ.|186 + 0,018×(Ε−4.000) τ.μ.")
    rows.append("ROW|άνω των 8.000 τ.μ.|258 + 0,009×(Ε−8.000) τ.μ. — μέγ. 360")

    if parcel_area_m2:
        if parcel_area_m2 >= 4000:
            dom = _ektos_max_domisi(parcel_area_m2)
            rows.append(f"ROW|Γεωτεμάχιο ({parcel_area_m2:.0f} τ.μ.)|ΑΡΤΙΟ (εμβαδόν) — έως {dom} τ.μ.")
        else:
            rows.append(f"ROW|Γεωτεμάχιο ({parcel_area_m2:.0f} τ.μ.)|ΜΗ ΑΡΤΙΟ κατά κανόνα (< 4.000 τ.μ.)")

    rows.append("HEADER|Κατά Παρέκκλιση|")
    rows.append("MERGED|Παρεκκλίσεις 750/1.200/2.000 τ.μ. καταργήθηκαν (Ν.4759/2020). "
                "Τελευταία μεταβατική προθεσμία 30.06.2026 (Ν.5261/2025) — έχει παρέλθει. "
                "Αναμένεται νέο πλαίσιο (Π.Δ. αναγνώρισης οδών).|")

    rows.append("HEADER|Απαιτούμενες Εγκρίσεις|")
    approvals = ["Συμβούλιο Αρχιτεκτονικής", "Υπηρεσία Νεωτέρων Μνημείων"]
    if extra_approvals:
        approvals.extend(a for a in extra_approvals if a not in approvals)
    rows.append(f"ROW||{', '.join(approvals)}")

    rows.append("HEADER|Λοιποί Περιορισμοί|")
    rows.append("MERGED|Η δόμηση τελεί υπό τον έλεγχο ειδικών καθεστώτων προστασίας "
                "(Natura 2000, δασικός χάρτης, αιγιαλός/παραλία, αρχαιολογία, ρέματα) — "
                "βλ. επόμενες ενότητες.|")

    return rows


@app.get("/report/rows", response_class=PlainTextResponse)
async def get_report_rows(
    x: float = Query(..., description="X coordinate (EGSA '87)"),
    y: float = Query(..., description="Y coordinate (EGSA '87)")
):
    """
    Full planning report: building regs + aigialos + archeo + church + natura + remata.
    Same TYPE|col1|col2 format as /oroitable/rows — for use with EREPORT LISP command.
    """
    rows = []

    # ── BUILDING REGULATIONS ─────────────────────────────────────────────────
    oroi = _get_oroitable_data(x, y)
    if oroi.get("found"):
        rows.extend(_build_regs_rows(oroi))
    elif not _is_inside_city_plan(x, y):
        # Εκτός σχεδίου — γενικές διατάξεις (Π.Δ. 24.05.85 + Ν.4759/2020)
        rows.extend(_build_ektos_sxediou_rows())
    else:
        return "ERROR|No regulations found at this location"

    # ── ΑΙΓΙΑΛΟΣ / ΠΑΡΑΛΙΑ ──────────────────────────────────────────────────
    shore = _get_shoreline_data(x, y)
    if shore.get("found"):
        rows.append("HEADER|ΑΙΓΙΑΛΟΣ / ΠΑΡΑΛΙΑ|")
        priority = ["Γραμμή Αιγιαλού", "Γραμμή Αιγιαλού_ΠΟΑ",
                    "Γραμμή Παραλίας", "Γραμμή Παραλίας_ΠΟΑ", "Γραμμή Παλαιού Αιγιαλού"]
        by_type = {r["info"]: r for r in shore["lines"]}
        for key in priority:
            if key in by_type:
                r = by_type[key]
                label = _AIGIALOS_LABELS.get(key, key)
                fek = f" (ΦΕΚ {r['fek']})" if r.get("fek") else ""
                rows.append(f"ROW|{label}|{r['distance_m']} μ.{fek}")

    # ── ΑΡΧΑΙΟΛΟΓΙΑ ──────────────────────────────────────────────────────────
    archeo = _get_archaeology_data(x, y)
    rows.append("HEADER|ΑΡΧΑΙΟΛΟΓΙΑ|")
    if archeo.get("in_protection_zone"):
        rows.append(f"ROW|Ζώνη Προστασίας|ΝΑΙ — {archeo.get('zone_name', '')}")
    else:
        rows.append("ROW|Ζώνη Προστασίας|ΟΧΙ")
    if archeo.get("found"):
        mn = archeo['name']
        if archeo.get("ot"):
            mn += f" — {archeo['ot']}"
        mn += f"  ({archeo['distance_m']} μ.)"
        rows.append(f"ROW|Πλησιέστερο Μνημείο|{mn}")
    else:
        rows.append("ROW|Πλησιέστερο Μνημείο|ΟΧΙ (εντός 2000 μ.)")

    # ── ΕΚΚΛΗΣΙΕΣ ────────────────────────────────────────────────────────────
    church = _get_church_data(x, y, max_distance=1000)
    if church.get("found"):
        rows.append("HEADER|ΕΚΚΛΗΣΙΕΣ|")
        ch_label = church.get("name", "-")
        if church.get("type"):
            ch_label += f" ({church['type']})"
        rows.append(f"ROW|Πλησιέστερη|{ch_label}")
        rows.append(f"ROW|Απόσταση|{church['distance_m']} μ.")

    # ── NATURA / ΔΑΣΗ ────────────────────────────────────────────────────────
    natura = _get_natura_forest_data(x, y)
    rows.append("HEADER|NATURA / ΔΑΣΗ|")
    if natura.get("in_natura"):
        rows.append(f"ROW|Natura 2000|ΝΑΙ — {natura.get('natura_name', '')} ({natura.get('natura_code', '')})")
    else:
        rows.append("ROW|Natura 2000|ΟΧΙ")
    if natura.get("in_forest"):
        fcode = natura.get("forest_type", "")
        flabel = natura.get("forest_type_label", "")
        fcat = natura.get("forest_category", "")
        fsrc = natura.get("forest_source", "")
        src_label = f" ({fsrc})" if fsrc else ""
        rows.append(f"ROW|Δασικός Χάρτης{src_label}|ΝΑΙ ({fcode} — {flabel})")
        rows.append(f"ROW|Κατηγορία δάσους|{fcat}")
    else:
        rows.append("ROW|Δασικός Χάρτης|ΟΧΙ")
    if natura.get("kaek_forest_use"):
        rows.append(f"ROW|Χρήση γης ΚΑΕΚ|{natura['kaek_forest_use']}")

    # ── ΡΕΜΑΤΑ ───────────────────────────────────────────────────────────────
    remata = _get_streams_data(x, y)
    by_layer = {r["layer"]: r for r in remata["oikismos_lines"]}
    has_remata = bool(remata["oikismos_lines"]) or remata.get("tps_found") or remata.get("other_found")
    if has_remata:
        rows.append("HEADER|ΡΕΜΑΤΑ|")
        # Only Γρ. Πλημμύρας: the οριοθέτηση lines come from the (non-ratified)
        # delimitation study, so they are not reported. "Άλλο ρέμα" still shown below.
        key = "Υδρογραφική Γραμμή Πλημμυρας"
        if key in by_layer:
            r = by_layer[key]
            rows.append(f"ROW|{r['label']}|{r['distance_m']} μ.")
        if remata.get("tps_found"):
            rows.append(f"ROW|Ρέμα ΤΠΣ|{remata['tps_distance_m']} μ.")
        if remata.get("other_found"):
            rows.append(f"ROW|Άλλο ρέμα (εντός οικ.)|{remata['other_distance_m']} μ.")

    # ── ΥΔΡΟΛΗΨΙΕΣ ΕΜΣΥ ─────────────────────────────────────────────────────
    ydro = _get_ydrolipsies_data(x=x, y=y)
    if ydro["available"]:
        rows.append("HEADER|ΥΔΡΟΛΗΨΙΕΣ (ΕΜΣΥ)|")
        if ydro["nearest"]:
            n = ydro["nearest"]
            rows.append(f"ROW|Πλησιέστερη|{_ydro_point_label(n)} — {n['distance_m']} μ.")
        else:
            rows.append("ROW|Πλησιέστερη|ΟΧΙ (εντός 500 μ.)")

    text = "\n".join(rows)
    return text.encode('windows-1253', errors='replace').decode('windows-1253')


# =============================================================================
# PARCEL-BASED REPORT (/report/parcel) — for the EREPORT command
# =============================================================================

def _resolve_operating_parcel(x: float, y: float, radius: float = 50) -> dict:
    """
    Resolve the operating-cadastre parcel at a clicked point using the same logic
    as /kaek/operating: point-in-polygon first, else nearest parcel within `radius`
    metres. EK (special-use) parcels are excluded. Returns a dict with
    kaek/area_m2/perim_m/main_use/descr, or None if nothing is found.
    """
    ek_filter = _kaek_non_special_use_filter()
    main_sql = f"""
    SELECT kaek,
           ROUND(ST_Area(geom)::numeric, 2),
           ROUND(ST_Perimeter(geom)::numeric, 2),
           main_use,
           descr
    FROM sp_geodata.kaek_parcels_operating
    WHERE {ek_filter}
      AND ST_Contains(geom, ST_SetSRID(ST_Point(%s, %s), 2100))
    LIMIT 1
    """
    row = execute_query(main_sql, (x, y), fetch_one=True)

    if not row:
        near_sql = f"""
        SELECT kaek,
               ROUND(ST_Area(geom)::numeric, 2),
               ROUND(ST_Perimeter(geom)::numeric, 2),
               main_use,
               descr
        FROM sp_geodata.kaek_parcels_operating
        WHERE {ek_filter}
          AND ST_DWithin(geom, ST_SetSRID(ST_Point(%s, %s), 2100), %s)
        ORDER BY geom <-> ST_SetSRID(ST_Point(%s, %s), 2100)
        LIMIT 1
        """
        row = execute_query(near_sql, (x, y, radius, x, y), fetch_one=True)

    if not row:
        return None

    return {
        "kaek": row[0],
        "area_m2": row[1],
        "perim_m": row[2],
        "main_use": row[3] or "",
        "descr": row[4] or "",
    }


def _get_parcel_overlaps(kaek: str) -> dict:
    """
    Containment of a parcel for the report: percentage of the parcel area that
    overlaps each Natura 2000 zone, forest-map type, and archaeological protection
    zone. ST_MakeValid guards against GEOS topology errors during ST_Intersection.
    """
    parcel = "(SELECT ST_MakeValid(geom) AS geom FROM sp_geodata.kaek_parcels_operating WHERE kaek = %s)"
    out = {"natura": [], "forest": [], "forest_source": None, "archeo_zones": []}

    # ── Natura 2000 ──────────────────────────────────────────────────────────
    natura_sql = f"""
    SELECT n.sitecode, n.sitename, n.sitetype,
           ROUND((ST_Area(ST_Intersection(ST_MakeValid(n.geom), p.geom))
                  / NULLIF(ST_Area(p.geom), 0) * 100)::numeric, 1) AS pct
    FROM epoleodomia.natura_2000 n, {parcel} p
    WHERE ST_Intersects(n.geom, p.geom)
    ORDER BY pct DESC
    """
    for r in (execute_query(natura_sql, (kaek,)) or []):
        out["natura"].append({"code": r[0], "name": r[1], "type": r[2], "pct": r[3]})

    # ── Forest map: κυρωμένος first, fall back to ανάρτηση 2021 ───────────────
    def _forest_rows(table: str):
        sql = f"""
        SELECT f.forest_type,
               ROUND((SUM(ST_Area(ST_Intersection(ST_MakeValid(f.geom), p.geom)))
                      / NULLIF(ST_Area(p.geom), 0) * 100)::numeric, 1) AS pct
        FROM {table} f, {parcel} p
        WHERE NOT COALESCE(f.is_deleted, false)
          AND ST_Intersects(f.geom, p.geom)
        GROUP BY f.forest_type, p.geom
        ORDER BY pct DESC
        """
        return execute_query(sql, (kaek,))

    # Μερική κύρωση: τμήματα με εκκρεμείς αντιρρήσεις ΛΕΙΠΟΥΝ από τον κυρωμένο
    # χάρτη. Αν ο κυρωμένος δεν καλύπτει (σχεδόν) όλο το γεωτεμάχιο, αναφέρουμε
    # ΚΑΙ την ανάρτηση 2021 — αλλιώς 0.3% slivers κρύβουν π.χ. 97% ΔΔ.
    kyr_rows = _forest_rows("epoleodomia.forest_maps") or []
    kyr_pct = sum(float(r[1] or 0) for r in kyr_rows)
    out["forest_kyromenos_pct"] = round(kyr_pct, 1)

    def _append_forest(rows_, source):
        for r in rows_:
            if r[1] is not None and float(r[1]) < 0.5:
                continue  # boundary slivers — misaligned linework noise
            code = r[0] or ""
            short_label, full_desc, category = _decode_forest_type(code)
            out["forest"].append({
                "code": code, "label": short_label, "category": category,
                "pct": r[1], "source": source,
            })

    _append_forest(kyr_rows, "κυρωμένος")
    if kyr_pct < 98.0:
        _append_forest(
            _forest_rows("epoleodomia.forest_maps_posted_attica_2021") or [],
            "ανάρτηση 2021")

    sources = {f["source"] for f in out["forest"]}
    out["forest_source"] = " + ".join(s for s in ("κυρωμένος", "ανάρτηση 2021") if s in sources) or None

    # ── Archaeological protection zones ──────────────────────────────────────
    archeo_sql = f"""
    WITH zones AS (
        SELECT
            site_name,
            ot_number,
            fek_refere,
            ST_CollectionExtract(ST_MakeValid(ST_BuildArea(geom)), 3) AS geom
        FROM sp_geodata."Αρχαιολογία_Ζώνες_Προστασίας"
        WHERE NOT ST_IsEmpty(ST_BuildArea(geom))
    )
    SELECT z.site_name, z.ot_number, z.fek_refere,
           ROUND((ST_Area(ST_Intersection(z.geom, p.geom))
                  / NULLIF(ST_Area(p.geom), 0) * 100)::numeric, 1) AS pct
    FROM zones z, {parcel} p
    WHERE ST_Intersects(z.geom, p.geom)
    ORDER BY pct DESC
    """
    for r in (execute_query(archeo_sql, (kaek,)) or []):
        out["archeo_zones"].append({"name": r[0], "ot": r[1], "fek": r[2], "pct": r[3]})

    return out


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
    parcel = _resolve_operating_parcel(x, y)
    if not parcel:
        return "ERROR|Δεν βρέθηκε λειτουργούν γεωτεμάχιο στο σημείο (ή κλικ σε ΕΚ)"

    kaek = parcel["kaek"]
    ref_geom, ref_args = _PARCEL_REF, (kaek,)

    # ── ΑΙΓΙΑΛΟΣ (fetched first — a crossing adds Κτηματική Υπηρεσία approval) ─
    shore = _get_shoreline_data(ref_geom=ref_geom, ref_args=ref_args)
    shore_crossing = _shore_crossing_list(shore) if shore.get("found") else []
    _KTIMATIKI = "Κτηματική Υπηρεσία Δημοσίου"

    # ── BUILDING REGULATIONS (at click point — a parcel may span zones) ──────
    oroi = _get_oroitable_data(x, y)
    if oroi.get("found"):
        if shore_crossing and _KTIMATIKI not in oroi["egkriseis"]:
            oroi["egkriseis"].append(_KTIMATIKI)
        regs_rows = _build_regs_rows(oroi)
        ot_label = f"O.T. {oroi['ot_num']}" if oroi.get("ot_num") else "SPETSES"
    elif not _is_inside_city_plan(x, y):
        # Εκτός σχεδίου — γενικές διατάξεις με υπολογισμό από εμβαδόν γεωτεμαχίου
        try:
            area = float(parcel["area_m2"])
        except (TypeError, ValueError):
            area = None
        regs_rows = _build_ektos_sxediou_rows(
            parcel_area_m2=area,
            extra_approvals=[_KTIMATIKI] if shore_crossing else None)
        ot_label = "ΕΚΤΟΣ ΣΧΕΔΙΟΥ"
    else:
        return "ERROR|No regulations found at this location"
    # Demote the regs-block title to a section header — the report has its own title
    regs_rows[0] = f"HEADER|ΟΡΟΙ ΔΟΜΗΣΗΣ — {ot_label}|"

    # ── Report skeleton: ΚΤΗΜΑΤΟΛΟΓΙΟ first, then ΟΡΟΙ ΔΟΜΗΣΗΣ, then the rest ─
    rows = [
        f"TITLE|ΠΟΛΕΟΔΟΜΙΚΕΣ ΠΛΗΡΟΦΟΡΙΕΣ|{ot_label}",
        "HEADER|ΚΤΗΜΑΤΟΛΟΓΙΟ (σε λειτουργία)|",
        f"ROW|ΚΑΕΚ|{kaek}",
        f"ROW|Εμβαδόν / Περίμετρος|{parcel['area_m2']} τ.μ. / {parcel['perim_m']} μ.",
    ]
    rights = _get_parcel_rights(kaek)
    if rights["apokleistikes"]:
        ax = rights["apokleistikes"]
        total = round(sum(a["area_m2"] for a in ax), 1)
        rows.append(f"ROW|Αποκλ. χρήσεις (ΑΧ)|{len(ax)} πολύγωνα — σύνολο {total} τ.μ.")
    if rights["douleies"]:
        dl = rights["douleies"]
        total = round(sum(d["area_m2"] for d in dl), 1)
        rows.append(f"ROW|Δουλείες|{len(dl)} — σύνολο {total} τ.μ.")

    rows.extend(regs_rows)

    overlaps = _get_parcel_overlaps(kaek)

    # ── ΑΙΓΙΑΛΟΣ / ΠΑΡΑΛΙΑ (distance from parcel) ────────────────────────────
    if shore.get("found"):
        rows.extend(_build_parcel_shoreline_rows(shore))

    # ── ΑΡΧΑΙΟΛΟΓΙΑ (zone = parcel overlap %, monument = distance from parcel) ─
    archeo = _get_archaeology_data(ref_geom=ref_geom, ref_args=ref_args, include_zone=False)
    rows.append("HEADER|ΑΡΧΑΙΟΛΟΓΙΑ|")
    if overlaps["archeo_zones"]:
        for z in overlaps["archeo_zones"]:
            zname = z.get("name") or ""
            rows.append(f"ROW|Ζώνη Προστασίας|ΝΑΙ — {zname} ({z['pct']}% γεωτεμαχίου)")
    else:
        rows.append("ROW|Ζώνη Προστασίας|ΟΧΙ")
    if archeo.get("found"):
        mn = archeo['name']
        if archeo.get("ot"):
            mn += f" — {archeo['ot']}"
        mn += f"  ({_fmt_parcel_dist(archeo['distance_m'], 'point')})"
        rows.append(f"ROW|Πλησιέστερο Μνημείο|{mn}")
    else:
        rows.append("ROW|Πλησιέστερο Μνημείο|ΟΧΙ (εντός 2000 μ.)")

    # ── ΕΚΚΛΗΣΙΕΣ (distance from parcel) ─────────────────────────────────────
    church = _get_church_data(ref_geom=ref_geom, ref_args=ref_args, max_distance=1000)
    if church.get("found"):
        rows.append("HEADER|ΕΚΚΛΗΣΙΕΣ|")
        ch_label = church.get("name", "-")
        if church.get("type"):
            ch_label += f" ({church['type']})"
        rows.append(f"ROW|Πλησιέστερη|{ch_label}")
        rows.append(f"ROW|Απόσταση|{_fmt_parcel_dist(church['distance_m'], 'point')}")

    # ── NATURA / ΔΑΣΗ (parcel overlap %) ─────────────────────────────────────
    rows.append("HEADER|NATURA / ΔΑΣΗ|")
    if overlaps["natura"]:
        for n in overlaps["natura"]:
            rows.append(f"ROW|Natura 2000|ΝΑΙ — {n.get('name', '')} ({n.get('code', '')}) {n['pct']}%")
    else:
        rows.append("ROW|Natura 2000|ΟΧΙ")
    if overlaps["forest"]:
        for f in overlaps["forest"]:
            if f.get("source") == "ανάρτηση 2021":
                flabel = "Δασική Ανάρτηση 2021"
            else:
                flabel = "Δασικός Χάρτης (κυρωμένος)"
            rows.append(f"ROW|{flabel}|{f['label']} ({f['category']}) {f['pct']}%")
        kyr_pct = overlaps.get("forest_kyromenos_pct") or 0
        if kyr_pct < 98.0 and any(f.get("source") == "ανάρτηση 2021" for f in overlaps["forest"]):
            rows.append(f"MERGED|Το {round(100 - kyr_pct, 1)}% του γεωτεμαχίου είναι εκτός "
                        "του μερικώς κυρωμένου δασικού χάρτη (πιθανώς εκκρεμείς αντιρρήσεις) "
                        "— για το τμήμα αυτό ισχύει η ανάρτηση 2021.|")
    else:
        rows.append("ROW|Δασικός Χάρτης|ΟΧΙ")
    if parcel["main_use"] in _KAEK_FOREST_USE_CODES and parcel.get("descr"):
        rows.append(f"ROW|Χρήση γης ΚΑΕΚ|{parcel['descr']}")

    # ── ΡΕΜΑΤΑ (distance from parcel; εντός/εκτός σχεδίου at click point) ─────
    remata = _get_streams_data(x, y, ref_geom=ref_geom, ref_args=ref_args)
    by_layer = {r["layer"]: r for r in remata["oikismos_lines"]}
    has_remata = bool(remata["oikismos_lines"]) or remata.get("tps_found") or remata.get("other_found")
    if has_remata:
        rows.append("HEADER|ΡΕΜΑΤΑ|")
        # Only Γρ. Πλημμύρας: the οριοθέτηση lines come from the (non-ratified)
        # delimitation study, so they are not reported. "Άλλο ρέμα" still shown below.
        key = "Υδρογραφική Γραμμή Πλημμυρας"
        if key in by_layer:
            r = by_layer[key]
            rows.append(f"ROW|{r['label']}|{_fmt_parcel_dist(r['distance_m'], 'line')}")
        if remata.get("tps_found"):
            rows.append(f"ROW|Ρέμα ΤΠΣ|{_fmt_parcel_dist(remata['tps_distance_m'], 'line')}")
        if remata.get("other_found"):
            rows.append(f"ROW|Άλλο ρέμα (εντός οικ.)|{_fmt_parcel_dist(remata['other_distance_m'], 'line')}")

    # ── ΥΔΡΟΛΗΨΙΕΣ ΕΜΣΥ (δηλωτέες στα τοπογραφικά) ───────────────────────────
    ydro = _get_ydrolipsies_data(ref_geom=ref_geom, ref_args=ref_args)
    if ydro["available"]:
        rows.append("HEADER|ΥΔΡΟΛΗΨΙΕΣ (ΕΜΣΥ)|")
        if ydro["inside"]:
            for w in ydro["inside"]:
                rows.append(f"ROW|Εντός γεωτεμαχίου|{_ydro_point_label(w)}")
        else:
            rows.append("ROW|Εντός γεωτεμαχίου|ΟΧΙ")
            if ydro["nearest"]:
                n = ydro["nearest"]
                rows.append(f"ROW|Πλησιέστερη|{_ydro_point_label(n)} — {n['distance_m']} μ.")

    text = "\n".join(rows)
    return text.encode('windows-1253', errors='replace').decode('windows-1253')


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
    """
    Archaeological information relative to a reference geometry (point or parcel).

    include_zone=False skips the protection-zone proximity check — used by the
    parcel report, which reports zone *overlap %* via _get_parcel_overlaps instead.
    """
    if ref_geom is None:
        ref_geom, ref_args = _POINT_REF, (x, y)

    result = {
        "found": False,
        "in_protection_zone": False,
    }

    zone = None
    if include_zone:
        # Check if inside protection zone
        zone_sql = f"""
        SELECT
            site_name,
            ot_number as ot,
            fek_refere as fek,
            ST_Distance(
                ST_CollectionExtract(ST_MakeValid(ST_BuildArea(geom)), 3),
                {ref_geom}
            ) as distance
        FROM sp_geodata."Αρχαιολογία_Ζώνες_Προστασίας"
        WHERE NOT ST_IsEmpty(ST_BuildArea(geom))
        ORDER BY distance
        LIMIT 1
        """
        zone = execute_query(zone_sql, (*ref_args,), fetch_one=True)

    # Get closest monument
    monument_sql = f"""
    SELECT
        site_name,
        ot_number as ot,
        fek_reference as fek,
        site_location,
        ST_Distance(geom, {ref_geom}) as distance
    FROM sp_geodata."Αρχαιλογία_Κυρηγμένα_Μνημεία"
    WHERE ST_DWithin(geom, {ref_geom}, %s)
    ORDER BY geom <-> {ref_geom}
    LIMIT 1
    """
    monument = execute_query(monument_sql, (*ref_args, *ref_args, max_distance, *ref_args), fetch_one=True)

    # Check protection zone (inside if distance < 1m)
    if zone and zone[3] is not None and zone[3] < 1:
        result["in_protection_zone"] = True
        result["zone_name"] = zone[0]
        result["zone_ot"] = zone[1]
        result["zone_fek"] = zone[2]

    if monument:
        result["found"] = True
        result["name"] = monument[0]
        result["ot"] = monument[1]
        result["fek"] = monument[2]
        result["location"] = monument[3]
        result["distance_m"] = round(monument[4], 2) if monument[4] else None

    return result


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
    """Closest church to a reference geometry (clicked point by default, or a parcel)."""
    if ref_geom is None:
        ref_geom, ref_args = _POINT_REF, (x, y)
    sql = f"""
    SELECT
        name,
        type,
        year_built,
        century,
        status,
        address,
        ST_Distance(geom, {ref_geom}) as distance,
        ST_X(ST_Centroid(geom)) as cx,
        ST_Y(ST_Centroid(geom)) as cy
    FROM sp_geodata."Εκκλησίες_πολυγωνα"
    WHERE ST_DWithin(geom, {ref_geom}, %s)
    ORDER BY geom <-> {ref_geom}
    LIMIT 1
    """

    result = execute_query(sql, (*ref_args, *ref_args, max_distance, *ref_args), fetch_one=True)

    if not result:
        return {"found": False, "message": "No church found within search distance"}

    return {
        "found": True,
        "name": result[0],
        "type": result[1],
        "year_built": result[2],
        "century": result[3],
        "status": result[4],
        "address": result[5],
        "distance_m": round(result[6], 2) if result[6] else None,
        "centroid_x": result[7],
        "centroid_y": result[8]
    }


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

# Line type labels for display
_AIGIALOS_LABELS = {
    "Γραμμή Αιγιαλού":       "Γραμμή Αιγιαλού",
    "Γραμμή Αιγιαλού_ΠΟΑ":  "Γραμμή Αιγιαλού (ΠΟΑ)",
    "Γραμμή Παραλίας":        "Γραμμή Παραλίας",
    "Γραμμή Παραλίας_ΠΟΑ":  "Γραμμή Παραλίας (ΠΟΑ)",
    "Γραμμή Παλαιού Αιγιαλού": "Γραμμή Παλαιού Αιγιαλού",
}


def _get_shoreline_data(x: float = None, y: float = None, max_distance: float = 5000,
                        ref_geom: str = None, ref_args: tuple = None) -> dict:
    """Return closest segment per line type within max_distance of a reference geometry."""
    if ref_geom is None:
        ref_geom, ref_args = _POINT_REF, (x, y)
    sql = f"""
    SELECT DISTINCT ON (info)
        info,
        fek,
        location,
        ST_Distance(geom, {ref_geom}) AS distance
    FROM sp_geodata."Αιγιαλός_Παραλία"
    WHERE ST_DWithin(geom, {ref_geom}, %s)
    ORDER BY info, distance
    """
    results = execute_query(sql, (*ref_args, *ref_args, max_distance), fetch_one=False)

    if not results:
        return {"found": False, "message": "No shoreline found within search distance"}

    lines = []
    for row in results:
        lines.append({
            "info":       row[0],
            "fek":        row[1],
            "location":   row[2],
            "distance_m": round(row[3], 1) if row[3] is not None else None,
        })

    return {"found": True, "lines": lines}


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
    """Check if point is inside the city plan boundary (orio sxediou polews)."""
    sql = """
    SELECT EXISTS(
        SELECT 1 FROM sp_geodata.orio_sxediou_polews
        WHERE ST_Contains(geom, ST_SetSRID(ST_Point(%s, %s), 2100))
    )
    """
    result = execute_query(sql, (x, y), fetch_one=True)
    return result[0] if result else False


# Display labels for the 3 demarcation line types
_REMATA_LABELS = {
    "Υδρογραφική Γραμμή Πλημμυρας":                    "Πιθανή Γρ. Πλημμύρας",
    "Υδρογραφική Γραμμή Οριοθέτησης με τεχν. έργο":   "Γρ. Οριοθέτησης (με έργο)",
    "Υδρογραφική Γραμμή Οριοθέτησης χωρίς έργο":      "Γρ. Οριοθέτησης (χωρίς έργο)",
}

# Display order: Πλημμύρας first (it's the legal reference), then demarcation lines
_REMATA_ORDER = [
    "Υδρογραφική Γραμμή Πλημμυρας",
    "Υδρογραφική Γραμμή Οριοθέτησης με τεχν. έργο",
    "Υδρογραφική Γραμμή Οριοθέτησης χωρίς έργο",
]


def _get_streams_data(x: float = None, y: float = None, max_distance: float = 500,
                      ref_geom: str = None, ref_args: tuple = None) -> dict:
    """
    Stream distances at a reference geometry (clicked point by default, or a parcel).

    Always returns closest segment per layer type from Ρεματα_Οικισμού_υπό_Οριοθέτηση
    (all 3 line types: Πλημμύρας, Οριοθέτησης με έργο, Οριοθέτησης χωρίς έργο).

    ΕΚΤΟΣ σχεδίου also returns distance to Ρεματα Νησιου ΤΠΣ.
    ΕΝΤΟΣ σχεδίου also checks Ρεματα εντος οικισμου εκτος των 6.

    The εντός/εκτός σχεδίου determination always uses the clicked point (x, y),
    matching the building-regulations basis, even when distances use a parcel.
    """
    if ref_geom is None:
        ref_geom, ref_args = _POINT_REF, (x, y)
    inside_plan = _is_inside_city_plan(x, y)
    result = {
        "inside_city_plan": inside_plan,
        "oikismos_lines": [],   # list of {layer, label, distance_m}
        "tps_found": False,
        "other_found": False,
    }

    # ── All 3 layer types from Ρεματα_Οικισμού — always ─────────────────────
    oik_sql = f"""
    SELECT DISTINCT ON (layer)
        layer,
        ST_Distance(geom, {ref_geom}) AS distance
    FROM sp_geodata."Ρεματα_Οικισμού_υπό_Οριοθέτηση"
    WHERE ST_DWithin(geom, {ref_geom}, %s)
    ORDER BY layer, distance
    """
    oik_rows = execute_query(oik_sql, (*ref_args, *ref_args, max_distance), fetch_one=False)
    if oik_rows:
        for row in oik_rows:
            result["oikismos_lines"].append({
                "layer":      row[0],
                "label":      _REMATA_LABELS.get(row[0], row[0]),
                "distance_m": round(row[1], 1) if row[1] is not None else None,
            })

    # ── ΤΠΣ streams — εκτός σχεδίου only ────────────────────────────────────
    if not inside_plan:
        tps_sql = f"""
        SELECT ST_Distance(geom, {ref_geom}) AS distance
        FROM sp_geodata."Ρεματα Νησιου ΤΠΣ (εκτος των 6)"
        WHERE ST_DWithin(geom, {ref_geom}, %s)
        ORDER BY geom <-> {ref_geom}
        LIMIT 1
        """
        tps = execute_query(tps_sql, (*ref_args, *ref_args, max_distance, *ref_args), fetch_one=True)
        if tps:
            result["tps_found"] = True
            result["tps_distance_m"] = round(tps[0], 1) if tps[0] is not None else None

    # ── Other settlement streams — εντός σχεδίου only ────────────────────────
    if inside_plan:
        other_sql = f"""
        SELECT ST_Distance(geom, {ref_geom}) AS distance
        FROM sp_geodata."Ρεματα εντος οικισμου εκτος των 6"
        WHERE ST_DWithin(geom, {ref_geom}, %s)
        ORDER BY geom <-> {ref_geom}
        LIMIT 1
        """
        other = execute_query(other_sql, (*ref_args, *ref_args, max_distance, *ref_args), fetch_one=True)
        if other:
            result["other_found"] = True
            result["other_distance_m"] = round(other[0], 1) if other[0] is not None else None

    return result


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

# Official forest map type codes (Δασικοί Χάρτες — ΟΚΧΕ/ΕΛΓΟ-ΔΗΜΗΤΡΑ)
# Format: {code: (short_label, full_description, category)}
# category: "δασικό" | "αναδασωτέο" | "χορτολιβαδικό" | "μη δασικό" | "αμφίβολο"
_FOREST_TYPE_LABELS = {
    "ΔΔ": (
        "Δάσος/Δασική έκταση",
        "Δάσος ή δασική έκταση στις αεροφωτογραφίες παλαιότερης ΚΑΙ πρόσφατης λήψης",
        "δασικό",
    ),
    "ΔΑ": (
        "Δάσος (ιστορικό — αυστηρά προστατευμένο)",
        "Δάσος στις αεροφωτογραφίες παλαιότερης λήψης — άλλης μορφής στις πρόσφατες. Διατηρεί δασικό χαρακτήρα, πρακτικά αναλλοίωτος.",
        "δασικό",
    ),
    "ΑΔ": (
        "Δάσος/Δασική έκταση (νέα)",
        "Άλλης μορφής στις αεροφωτογραφίες παλαιότερης λήψης — δάσος ή δασική έκταση στις πρόσφατες. Δασικός χαρακτήρας, ενδέχεται αλλαγή χρήσης.",
        "δασικό",
    ),
    "ΑΑ": (
        "Μη δασική έκταση",
        "Άλλης μορφής/κάλυψης εκτάσεις και στις αεροφωτογραφίες παλαιότερης ΚΑΙ πρόσφατης λήψης",
        "μη δασικό",
    ),
    "ΠΔ": (
        "Δασικό (χαρακτηρισμός)",
        "Τελεσίδικη πράξη/απόφαση χαρακτηρισμού — δασική",
        "δασικό",
    ),
    "ΠΑ": (
        "Μη δασικό (χαρακτηρισμός)",
        "Τελεσίδικη πράξη/απόφαση χαρακτηρισμού — μη δασική",
        "μη δασικό",
    ),
    "ΠΧ": (
        "Χορτολιβαδικό (χαρακτηρισμός)",
        "Τελεσίδικη πράξη/απόφαση χαρακτηρισμού — χορτολιβαδική",
        "χορτολιβαδικό",
    ),
    "ΑΝ": (
        "Αναδασωτέα/Δασωτέα",
        "Αναδασωτέα ή δασωτέα έκταση",
        "αναδασωτέο",
    ),
    "ΧΧ": (
        "Χορτολιβαδική έκταση",
        "Χορτολιβαδική έκταση στις αεροφωτογραφίες παλαιότερης ΚΑΙ πρόσφατης λήψης",
        "χορτολιβαδικό",
    ),
    "ΧΑ": (
        "Χορτολιβαδική (αλλοίωση)",
        "Χορτολιβαδική στις αεροφωτογραφίες παλαιότερης λήψης — άλλης μορφής στις πρόσφατες",
        "χορτολιβαδικό",
    ),
    "ΑΧ": (
        "Χορτολιβαδική (νέα)",
        "Άλλης μορφής στις αεροφωτογραφίες παλαιότερης λήψης — χορτολιβαδική στις πρόσφατες",
        "χορτολιβαδικό",
    ),
}

def _decode_forest_type(code: str) -> tuple:
    """Return (short_label, full_description, category) for a forest type code."""
    if not code:
        return ("—", "Άγνωστος τύπος", "άγνωστο")
    entry = _FOREST_TYPE_LABELS.get(code.strip().upper())
    if entry:
        return entry
    return (code, f"Κωδικός: {code}", "άγνωστο")


_KAEK_FOREST_USE_CODES = {"1110", "1111", "1112", "1320", "1330"}

def _get_natura_forest_data(x: float, y: float) -> dict:
    """
    Check Natura 2000, forest maps, and cadastre land use at a point.
    Forest source priority: forest_maps (κυρωμένος) → forest_maps_posted_attica_2021 (ανάρτηση).
    Also returns cadastre main_use if it indicates woodland.
    """
    result = {
        "in_natura": False,
        "in_forest": False,
        "forest_source": None,       # "κυρωμένος" | "ανάρτηση 2021"
        "kaek_forest_use": None,     # descr from kaek if woodland code
        "kaek_forest_code": None,
    }

    # ── Natura 2000 ──────────────────────────────────────────────────────────
    natura_sql = """
    SELECT sitecode, sitename, sitetype, area_ha
    FROM epoleodomia.natura_2000
    WHERE ST_Contains(geom, ST_SetSRID(ST_Point(%s, %s), 2100))
    LIMIT 1
    """
    natura = execute_query(natura_sql, (x, y), fetch_one=True)
    if natura:
        result["in_natura"] = True
        result["natura_code"] = natura[0]
        result["natura_name"] = natura[1]
        result["natura_type"] = natura[2]

    # ── Κυρωμένος Δασικός Χάρτης ─────────────────────────────────────────────
    forest_sql = """
    SELECT region_name, forest_type, status
    FROM epoleodomia.forest_maps
    WHERE NOT COALESCE(is_deleted, false)
      AND ST_Contains(geom, ST_SetSRID(ST_Point(%s, %s), 2100))
    LIMIT 1
    """
    forest = execute_query(forest_sql, (x, y), fetch_one=True)

    if forest:
        code = forest[1] or ""
        short_label, full_desc, category = _decode_forest_type(code)
        result["in_forest"] = True
        result["forest_source"] = "κυρωμένος"
        result["forest_region"] = forest[0]
        result["forest_type"] = code
        result["forest_type_label"] = short_label
        result["forest_type_desc"] = full_desc
        result["forest_category"] = category
    else:
        # ── Δασική Ανάρτηση 2021 (Αττική) — fallback ─────────────────────────
        posted_sql = """
        SELECT forest_type
        FROM epoleodomia.forest_maps_posted_attica_2021
        WHERE NOT COALESCE(is_deleted, false)
          AND ST_Contains(geom, ST_SetSRID(ST_Point(%s, %s), 2100))
        LIMIT 1
        """
        posted = execute_query(posted_sql, (x, y), fetch_one=True)
        if posted:
            code = posted[0] or ""
            short_label, full_desc, category = _decode_forest_type(code)
            result["in_forest"] = True
            result["forest_source"] = "ανάρτηση 2021"
            result["forest_type"] = code
            result["forest_type_label"] = short_label
            result["forest_type_desc"] = full_desc
            result["forest_category"] = category

    # ── Κτηματολόγιο — χρήση γης (πάντα, αν δασώδης) ────────────────────────
    kaek_sql = """
    SELECT main_use, descr
    FROM sp_geodata.kaek_parcels_operating
    WHERE ST_Contains(geom, ST_SetSRID(ST_Point(%s, %s), 2100))
    LIMIT 1
    """
    kaek = execute_query(kaek_sql, (x, y), fetch_one=True)
    if kaek and kaek[0] in _KAEK_FOREST_USE_CODES:
        result["kaek_forest_code"] = kaek[0]
        result["kaek_forest_use"] = kaek[1]

    return result


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

# FEKs to exclude from search:
# - 740Δ/1981: Covers too large area (whole traditional settlement)
# - 208Δ/1969: Regional Peloponnese decree, scale 1:200,000
# - 176Δ/1970, 275Δ/1970: Before 1980, superseded
# - 541ΑΑΠ/2007, 42ΑΑΠ/2015: ΠΕΡΠΟ regional, scale 1:100,000
EXCLUDED_FEKS = [
    '740Δ/1981',
    '208Δ/1969',
    '176Δ/1970',
    '275Δ/1970',
    '541ΑΑΠ/2007',
    '42ΑΑΠ/2015',
]

@app.get("/rasters/fek")
async def get_fek_rasters(
    minx: float = Query(..., description="Minimum X coordinate"),
    miny: float = Query(..., description="Minimum Y coordinate"),
    maxx: float = Query(..., description="Maximum X coordinate"),
    maxy: float = Query(..., description="Maximum Y coordinate")
):
    """
    Get planning diagram rasters that intersect a bounding box.
    Uses planning_diagrams footprints (approved plan areas) joined with raster_catalog.
    Excludes regional/large-scale FEKs and pre-1980 superseded plans.
    """
    sql = """
    SELECT
        rc.id,
        pd.fek,
        pd.title,
        rc.filename,
        rc.local_path_georef,
        rc.width_px,
        rc.height_px,
        rc.resolution_x,
        pd.init_diagr_scale_denominator as scale,
        rc.georef_rms as rms
    FROM epoleodomia.planning_diagrams pd
    JOIN epoleodomia.raster_catalog rc ON pd.objectid = rc.planning_diagram_objectid
    WHERE NOT COALESCE(pd.is_deleted, false)
      AND rc.download_status = 'downloaded'
      AND rc.local_path_georef IS NOT NULL
      AND pd.geom IS NOT NULL
      AND pd.fek NOT IN ('740Δ/1981', '208Δ/1969', '176Δ/1970', '275Δ/1970', '541ΑΑΠ/2007', '42ΑΑΠ/2015')
      AND ST_Intersects(
          pd.geom,
          ST_MakeEnvelope(%s, %s, %s, %s, 2100)
      )
    ORDER BY pd.fek, rc.filename
    """

    results = execute_query(sql, (minx, miny, maxx, maxy))

    rasters = []
    paths = []

    for row in results:
        relative_path = row[4]
        if relative_path:
            # Build full path from base path + relative path
            relative_path = relative_path.replace("/", "\\")
            full_path = os.path.join(RASTER_BASE_PATH, relative_path)
            paths.append(full_path)
            rasters.append({
                "id": row[0],
                "fek": row[1],
                "title": row[2],
                "filename": row[3],
                "path": full_path,
                "width_px": row[5],
                "height_px": row[6],
                "resolution": float(row[7]) if row[7] else None,
                "scale": row[8],
                "rms": float(row[9]) if row[9] else None
            })

    return {"count": len(rasters), "paths": paths, "rasters": rasters}


@app.get("/rasters/fek/simple", response_class=PlainTextResponse)
async def get_fek_rasters_simple(
    minx: float = Query(..., description="Minimum X coordinate"),
    miny: float = Query(..., description="Minimum Y coordinate"),
    maxx: float = Query(..., description="Maximum X coordinate"),
    maxy: float = Query(..., description="Maximum Y coordinate")
):
    """
    Get planning diagram rasters in simple pipe-delimited format for LISP parsing.
    Format: path|fek_display|fek_ascii|scale|rms|source (one per line)

    Hybrid loading: checks local folder first, falls back to TEE URL if not found.
    Local folder: O:\gis_data\epoleodomia\poleodomikoi oroi\poleodomikoi oroi geotifs

    Greek characters are transliterated to ASCII for layer naming compatibility.
    source: LOCAL or URL (URL means file needs to be downloaded from TEE)
    """
    sql = """
    SELECT
        rc.filename,
        pd.fek,
        pd.init_diagr_scale_denominator as scale,
        rc.georef_rms as rms,
        pd.georef_diagram_url
    FROM epoleodomia.planning_diagrams pd
    JOIN epoleodomia.raster_catalog rc ON pd.objectid = rc.planning_diagram_objectid
    WHERE NOT COALESCE(pd.is_deleted, false)
      AND rc.download_status = 'downloaded'
      AND rc.filename IS NOT NULL
      AND pd.geom IS NOT NULL
      AND pd.fek NOT IN ('740Δ/1981', '208Δ/1969', '176Δ/1970', '275Δ/1970', '541ΑΑΠ/2007', '42ΑΑΠ/2015')
      AND ST_Intersects(
          pd.geom,
          ST_MakeEnvelope(%s, %s, %s, %s, 2100)
      )
    ORDER BY pd.fek, rc.filename
    """

    results = execute_query(sql, (minx, miny, maxx, maxy))

    lines = []
    for row in results:
        filename = row[0]
        fek = row[1] or ""
        scale = row[2]
        rms = row[3]
        tee_url = row[4]

        if filename:
            # Check if file exists locally first
            local_path = os.path.join(FEK_LOCAL_PATH, filename)

            if os.path.exists(local_path):
                # Use local file
                raster_path = local_path
                source = "LOCAL"
            elif tee_url:
                # Fall back to TEE URL - LISP will need to download
                raster_path = tee_url
                source = "URL"
            else:
                # Skip if neither available
                continue

            # Transliterate Greek to ASCII for layer names
            fek_ascii = _transliterate_greek(fek)

            scale_str = str(int(scale)) if scale else ""
            rms_str = f"{rms:.2f}" if rms else ""

            lines.append(f"{raster_path}|{fek}|{fek_ascii}|{scale_str}|{rms_str}|{source}")

    return "\n".join(lines)


@app.get("/rasters/fek/download")
async def download_fek_raster(url: str = Query(..., description="TEE URL to download")):
    """
    Download a FEK raster from TEE and save to local folder.
    Returns the local path after download.
    """
    import urllib.request
    import urllib.error

    # Extract filename from URL
    filename = url.split("/")[-1]
    local_path = os.path.join(FEK_LOCAL_PATH, filename)

    # Check if already exists
    if os.path.exists(local_path):
        return {"status": "exists", "path": local_path}

    try:
        # Download the file
        urllib.request.urlretrieve(url, local_path)
        return {"status": "downloaded", "path": local_path}
    except urllib.error.URLError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        return {"status": "error", "message": str(e)}


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
# UTILITY FUNCTIONS
# =============================================================================

def _wkt_to_coords(wkt: str) -> list:
    """
    Convert WKT geometry to list of coordinate pairs.
    Handles POLYGON, MULTIPOLYGON, LINESTRING, MULTILINESTRING.
    """
    if not wkt:
        return []

    coords = []
    pattern = r'(-?\d+\.?\d*)\s+(-?\d+\.?\d*)'
    matches = re.findall(pattern, wkt)

    for match in matches:
        coords.append([float(match[0]), float(match[1])])

    return coords


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
