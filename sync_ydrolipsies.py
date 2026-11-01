"""
Sync ΕΜΣΥ water abstraction points (σημεία υδροληψίας) → sp_geodata.ydrolipsies_emsy

Source: ΥΠΕΝ Λ.Μ.Τ. public-viewer internal ArcGIS service (UNOFFICIAL endpoint —
not a published WFS/API). It can change or be locked without notice, so every
network call is wrapped and failures produce a clear message, never a crash.

    http://lmt.ypeka.gr/arcgis/rest/services/EMSIes/Idrolipsies_for_map_symbol_Service/FeatureServer/0/query

Data is in EGSA'87 (wkid 2100) — no reprojection needed.

Usage:
    python sync_ydrolipsies.py             # sync Spetses bbox (incremental upsert)
    python sync_ydrolipsies.py --dry-run   # fetch + report count only
    python sync_ydrolipsies.py --bbox minx,miny,maxx,maxy
    python sync_ydrolipsies.py --init       # preview setup; no source download
    python sync_ydrolipsies.py --init --apply  # explicit administrator setup

Rows missing from a later source response are deliberately kept. The endpoint
is unofficial, so a partial/empty response must never erase previously synced
data.
"""

import argparse
import json
import math
import sys
from datetime import datetime

import psycopg2

from arcgis_client import fetch_count, fetch_object_ids, request_json
from config import DATABASE
from sync_safety import FetchError, LoadError, SyncError

SERVICE_URL = ("http://lmt.ypeka.gr/arcgis/rest/services/EMSIes/"
               "Idrolipsies_for_map_symbol_Service/FeatureServer/0/query")

# Spetses bbox (EGSA'87) — same as the cadastre sync
DEFAULT_BBOX = (416555, 4116249, 431409, 4129267)
PAGE = 1000
TIMEOUT = 60
SOURCE = "EMSY (unofficial viewer endpoint)"
ATTRIBUTES = (
    "OBJECTID", "KWDIKOS_EMSY", "KWDIKOS_SY", "EIDOS_SY", "KATHESTWS_XRHSHS",
    "IDIOKTHSIAKO_KATHESTWS", "X_EGSA87", "Y_EGSA87", "Z", "BATHOS_GEWTRHSHS",
    "TOPWNYMIO", "KOINOTHTA", "PARATHRHSEIS", "STATUS",
)

TABLE = 'sp_geodata.ydrolipsies_emsy'

DDL = """
CREATE TABLE IF NOT EXISTS sp_geodata.ydrolipsies_emsy (
    gid                 SERIAL PRIMARY KEY,
    objectid            BIGINT,
    kwdikos_emsy        TEXT,
    kwdikos_sy          BIGINT,
    eidos_sy            TEXT,          -- Γεώτρηση / Πηγάδι / Πηγή / ...
    kathestws_xrhshs    TEXT,          -- Ενεργό / Ανενεργό
    idioktisiako        TEXT,
    x_egsa87            DOUBLE PRECISION,
    y_egsa87            DOUBLE PRECISION,
    z                   DOUBLE PRECISION,
    bathos_gewtrhshs    DOUBLE PRECISION,
    topwnymio           TEXT,
    koinothta           TEXT,
    paratiriseis        TEXT,
    status              TEXT,          -- Καθεστώς επεξεργασίας ΕΜΣΥ
    geom                geometry(Point, 2100),
    synced_at           TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ydrolipsies_emsy_geom
    ON sp_geodata.ydrolipsies_emsy USING gist (geom);
CREATE UNIQUE INDEX IF NOT EXISTS uq_ydrolipsies_emsy_objectid
    ON sp_geodata.ydrolipsies_emsy (objectid);
"""


UPSERT_SQL = f"""
INSERT INTO {TABLE} AS dst
    (objectid, kwdikos_emsy, kwdikos_sy, eidos_sy,
     kathestws_xrhshs, idioktisiako, x_egsa87, y_egsa87, z,
     bathos_gewtrhshs, topwnymio, koinothta, paratiriseis,
     status, geom)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
        ST_SetSRID(ST_Point(%s, %s), 2100))
ON CONFLICT (objectid) DO UPDATE SET
    kwdikos_emsy     = EXCLUDED.kwdikos_emsy,
    kwdikos_sy       = EXCLUDED.kwdikos_sy,
    eidos_sy         = EXCLUDED.eidos_sy,
    kathestws_xrhshs = EXCLUDED.kathestws_xrhshs,
    idioktisiako     = EXCLUDED.idioktisiako,
    x_egsa87         = EXCLUDED.x_egsa87,
    y_egsa87         = EXCLUDED.y_egsa87,
    z                = EXCLUDED.z,
    bathos_gewtrhshs = EXCLUDED.bathos_gewtrhshs,
    topwnymio        = EXCLUDED.topwnymio,
    koinothta        = EXCLUDED.koinothta,
    paratiriseis     = EXCLUDED.paratiriseis,
    status           = EXCLUDED.status,
    geom             = EXCLUDED.geom,
    synced_at        = NOW()
WHERE ROW(
    dst.kwdikos_emsy, dst.kwdikos_sy, dst.eidos_sy,
    dst.kathestws_xrhshs, dst.idioktisiako,
    dst.x_egsa87, dst.y_egsa87, dst.z,
    dst.bathos_gewtrhshs, dst.topwnymio, dst.koinothta,
    dst.paratiriseis, dst.status, dst.geom
) IS DISTINCT FROM ROW(
    EXCLUDED.kwdikos_emsy, EXCLUDED.kwdikos_sy, EXCLUDED.eidos_sy,
    EXCLUDED.kathestws_xrhshs, EXCLUDED.idioktisiako,
    EXCLUDED.x_egsa87, EXCLUDED.y_egsa87, EXCLUDED.z,
    EXCLUDED.bathos_gewtrhshs, EXCLUDED.topwnymio, EXCLUDED.koinothta,
    EXCLUDED.paratiriseis, EXCLUDED.status, EXCLUDED.geom
)
RETURNING objectid;
"""


def get_connection():
    return psycopg2.connect(
        host=DATABASE["host"], port=DATABASE["port"], dbname=DATABASE["database"],
        user=DATABASE["user"], password=DATABASE["password"],
    )


def initialize_schema():
    """Explicit administrative setup; normal loads never create objects."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(DDL)
        conn.commit()
    except Exception as exc:
        conn.rollback()
        raise LoadError(f'EMSY setup rolled back: {exc}') from exc
    finally:
        conn.close()


def _finite_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def validate_bbox(bbox):
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4 or not all(map(_finite_number, bbox)):
        raise ValueError("bbox requires four finite coordinates")
    if bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
        raise ValueError("bbox minima must be smaller than maxima")
    return tuple(bbox)


def _query_params(bbox):
    bbox = validate_bbox(bbox)
    return {"f": "json", "where": "1=1", "geometry": json.dumps({
        "xmin": bbox[0], "ymin": bbox[1], "xmax": bbox[2], "ymax": bbox[3],
        "spatialReference": {"wkid": 2100},
    }), "geometryType": "esriGeometryEnvelope", "spatialRel": "esriSpatialRelIntersects", "inSR": 2100}


def _require_egsa87(reference):
    if not isinstance(reference, dict) or not any(k in reference for k in ("wkid", "latestWkid")):
        raise SyncError("EMSY: missing spatial reference; expected EPSG:2100")
    if any(reference[k] != 2100 for k in ("wkid", "latestWkid") if k in reference):
        raise SyncError("EMSY: unexpected spatial reference; expected EPSG:2100")


def _validate_features(features, spatial_reference=None, bbox=None):
    """Validate all records before writing; nullable values must still have keys."""
    if not isinstance(features, list):
        raise SyncError("EMSY: missing/invalid features list")
    normalized, seen = [], set()
    for index, feat in enumerate(features, 1):
        attrs = feat.get("attributes") if isinstance(feat, dict) else None
        geom = feat.get("geometry") if isinstance(feat, dict) else None
        if not isinstance(attrs, dict) or not isinstance(geom, dict):
            raise SyncError(f"EMSY record {index}: missing attributes/point geometry")
        missing = [name for name in ATTRIBUTES if name not in attrs]
        if missing:
            raise SyncError(f"EMSY record {index}: missing source fields {missing}")
        oid = attrs["OBJECTID"]
        if isinstance(oid, bool) or not isinstance(oid, int) or oid in seen:
            raise SyncError(f"EMSY record {index}: missing/invalid/duplicate OBJECTID")
        seen.add(oid)
        for axis in ("x", "y"):
            value = geom.get(axis)
            if not _finite_number(value):
                raise SyncError(f"EMSY record {index}: missing/non-finite point {axis}")
        if any(key in geom for key in ("rings", "paths", "points")):
            raise SyncError(f"EMSY record {index}: expected point geometry")
        reference = geom.get("spatialReference", spatial_reference)
        _require_egsa87(reference)
        if bbox and not (bbox[0] <= geom["x"] <= bbox[2] and bbox[1] <= geom["y"] <= bbox[3]):
            raise SyncError(f"EMSY record {index}: point outside requested bbox")
        item = dict(feat)
        item["attributes"] = dict(attrs)
        item["geometry"] = dict(geom, spatialReference=dict(reference))
        normalized.append(item)
    return normalized


def fetch_features(bbox):
    """Verify the entire source identity snapshot; never return a partial import."""
    params = _query_params(bbox)
    expected_count = fetch_count(SERVICE_URL, params, TIMEOUT, SOURCE)
    name, expected_ids = fetch_object_ids(SERVICE_URL, params, TIMEOUT, SOURCE)
    if name != "OBJECTID" or len(expected_ids) != expected_count:
        raise FetchError("EMSY: source count/object-ID field or membership mismatch")
    remaining, features = set(expected_ids), []
    while remaining:
        requested = set(sorted(remaining)[:PAGE])
        batch_params = dict(params, objectIds=",".join(str(i) for i in sorted(requested)),
                            outSR=2100, outFields=",".join(ATTRIBUTES), returnGeometry="true",
                            maxAllowableOffset="0", resultRecordCount=PAGE)
        data = request_json(SERVICE_URL, batch_params, TIMEOUT, SOURCE, method="POST")
        try:
            if data.get("geometryType") != "esriGeometryPoint":
                raise SyncError("EMSY: expected point feature set")
            reference = data.get("spatialReference")
            _require_egsa87(reference)
            batch = _validate_features(data.get("features"), reference, bbox)
        except SyncError as exc:
            raise FetchError(str(exc)) from exc
        if not batch:
            raise FetchError(f"EMSY: incomplete download ({len(features)}/{expected_count})")
        received = {feat["attributes"]["OBJECTID"] for feat in batch}
        if not received <= requested:
            raise FetchError("EMSY: received unexpected or already downloaded object IDs")
        remaining.difference_update(received)
        features.extend(batch)
    final_name, final_ids = fetch_object_ids(SERVICE_URL, params, TIMEOUT, SOURCE)
    if final_name != name or final_ids != expected_ids:
        raise FetchError("EMSY: source object IDs changed during download; rerun the sync")
    return features


def load(features, dry_run=False, *, connection=None):
    features = _validate_features(features)
    if dry_run:
        print(f"  [dry-run] {len(features)} σημεία υδροληψίας στο bbox")
        print("  [dry-run] Η βάση δεν αλλάζει")
        return {"new": 0, "updated": 0, "unchanged": 0,
                "skipped": 0, "total": None}

    if not features:
        return {"new": 0, "updated": 0, "unchanged": 0, "skipped": 0, "total": None}

    conn = connection if connection is not None else get_connection()
    try:
        with conn.cursor() as cur:
            source_objectids = [
                f.get("attributes", {}).get("OBJECTID")
                for f in features
                if f.get("attributes", {}).get("OBJECTID") is not None
            ]
            existing_objectids = set()
            if source_objectids:
                cur.execute(
                    f"SELECT objectid FROM {TABLE} WHERE objectid = ANY(%s)",
                    (source_objectids,),
                )
                existing_objectids = {row[0] for row in cur.fetchall()}

            stats = {"new": 0, "updated": 0, "unchanged": 0, "skipped": 0}
            for f in features:
                a = f.get("attributes", {})
                g = f.get("geometry") or {}
                objectid = a.get("OBJECTID")
                x, y = g.get("x"), g.get("y")
                cur.execute(UPSERT_SQL, (
                    objectid, a.get("KWDIKOS_EMSY"), a.get("KWDIKOS_SY"),
                    a.get("EIDOS_SY"), a.get("KATHESTWS_XRHSHS"),
                    a.get("IDIOKTHSIAKO_KATHESTWS"),
                    a.get("X_EGSA87"), a.get("Y_EGSA87"), a.get("Z"),
                    a.get("BATHOS_GEWTRHSHS"), a.get("TOPWNYMIO"),
                    a.get("KOINOTHTA"), a.get("PARATHRHSEIS"), a.get("STATUS"),
                    x, y,
                ))
                changed = cur.fetchone()
                if changed:
                    if objectid in existing_objectids:
                        stats["updated"] += 1
                    else:
                        stats["new"] += 1
                        existing_objectids.add(objectid)
                else:
                    stats["unchanged"] += 1

            cur.execute(f"SELECT COUNT(*) FROM {TABLE}")
            stats["total"] = cur.fetchone()[0]
        if connection is None:
            conn.commit()
        return stats
    except Exception as exc:
        if connection is None:
            conn.rollback()
        hint = (' Review sync_ydrolipsies.py --init with the schema administrator.'
                if isinstance(exc, psycopg2.errors.UndefinedTable) else '')
        raise LoadError(f"EMSY load rolled back: {exc}{hint}") from exc
    finally:
        if connection is None:
            conn.close()


def main():
    ap = argparse.ArgumentParser(description="Sync ΕΜΣΥ υδροληψίες → PostGIS")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--bbox", type=str, help="minx,miny,maxx,maxy (EGSA'87)")
    ap.add_argument("--init", action="store_true", help="Preview administrative table/index setup without fetching data")
    ap.add_argument("--apply", action="store_true", help="Apply setup only with --init and owner credentials")
    args = ap.parse_args()
    if args.apply and not args.init:
        ap.error('--apply requires --init; ordinary sync does not do schema setup')
    if args.init:
        if args.dry_run or args.bbox:
            ap.error('--init is standalone; do not combine it with data-sync options')
        if not args.apply:
            print(DDL)
            print('Preview only. An administrator may apply with --init --apply.')
            return
        try:
            initialize_schema()
        except (psycopg2.Error, SyncError) as exc:
            print(f'DB SETUP ERROR: {exc}')
            sys.exit(1)
        print('EMSY schema setup completed. No source data fetched.')
        return

    bbox = DEFAULT_BBOX
    if args.bbox:
        try:
            bbox = tuple(float(v) for v in args.bbox.split(","))
            bbox = validate_bbox(bbox)
        except ValueError as exc:
            print(f"Invalid --bbox: {exc}. Expected: minx,miny,maxx,maxy")
            sys.exit(2)

    print("=" * 60)
    print(f"ΕΜΣΥ Υδροληψίες sync — {datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"  bbox: {bbox}")
    print("=" * 60)

    try:
        features = fetch_features(bbox)
    except RuntimeError as e:
        print(f"\nERROR: {e}")
        sys.exit(1)

    print(f"  Fetched: {len(features)} σημεία")

    try:
        stats = load(features, dry_run=args.dry_run)
    except (psycopg2.Error, SyncError) as e:
        print(f"\nDB ERROR: {e}")
        sys.exit(1)

    if not args.dry_run:
        print(f"  New: {stats['new']}")
        print(f"  Updated: {stats['updated']}")
        print(f"  Unchanged: {stats['unchanged']}")
        if stats["skipped"]:
            print(f"  Skipped (missing OBJECTID/geometry): {stats['skipped']}")
        if stats["total"] is None:
            print("  Empty source: existing data kept; no database writes")
        else:
            print(f"  Table total: {stats['total']} → {TABLE} (no deletions)")
    print("Done.")


if __name__ == "__main__":
    main()
