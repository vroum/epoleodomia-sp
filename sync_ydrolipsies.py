"""
Sync ΕΜΣΥ water abstraction points (σημεία υδροληψίας) → sp_geodata.ydrolipsies_emsy

Source: ΥΠΕΝ Λ.Μ.Τ. public-viewer internal ArcGIS service (UNOFFICIAL endpoint —
not a published WFS/API). It can change or be locked without notice, so every
network call is wrapped and failures produce a clear message, never a crash.

    http://lmt.ypeka.gr/arcgis/rest/services/EMSIes/Idrolipsies_for_map_symbol_Service/FeatureServer/0/query

Data is in EGSA'87 (wkid 2100) — no reprojection needed.

Usage:
    python sync_ydrolipsies.py             # sync Spetses bbox (full replace)
    python sync_ydrolipsies.py --dry-run   # fetch + report count only
    python sync_ydrolipsies.py --bbox minx,miny,maxx,maxy
"""

import argparse
import json
import os
import sys
from datetime import datetime

import psycopg2
import requests

SERVICE_URL = ("http://lmt.ypeka.gr/arcgis/rest/services/EMSIes/"
               "Idrolipsies_for_map_symbol_Service/FeatureServer/0/query")

# Spetses bbox (EGSA'87) — same as the cadastre sync
DEFAULT_BBOX = (416555, 4116249, 431409, 4129267)

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
"""


def get_connection():
    return psycopg2.connect(
        host=os.environ.get("EPOL_DB_HOST", "10.90.144.153"),
        port=int(os.environ.get("EPOL_DB_PORT", "65432")),
        dbname=os.environ.get("EPOL_DB_NAME", "gis"),
        user=os.environ.get("EPOL_DB_USER", "docker"),
        password=os.environ.get("EPOL_DB_PASSWORD", ""),
    )


def fetch_features(bbox):
    """Fetch all features in bbox with paging. Returns list or raises RuntimeError."""
    features = []
    offset = 0
    page = 1000  # server maxRecordCount
    geometry = json.dumps({
        "xmin": bbox[0], "ymin": bbox[1], "xmax": bbox[2], "ymax": bbox[3],
        "spatialReference": {"wkid": 2100},
    })
    while True:
        params = {
            "f": "json",
            "geometry": geometry,
            "geometryType": "esriGeometryEnvelope",
            "spatialRel": "esriSpatialRelIntersects",
            "inSR": 2100,
            "outSR": 2100,
            "outFields": "*",
            "returnGeometry": "true",
            "resultOffset": offset,
            "resultRecordCount": page,
        }
        try:
            r = requests.get(SERVICE_URL, params=params, timeout=60)
            r.raise_for_status()
            data = r.json()
        except requests.exceptions.RequestException as e:
            raise RuntimeError(
                f"ΕΜΣΥ endpoint unreachable ({e.__class__.__name__}: {e}).\n"
                "  Το endpoint είναι ανεπίσημο (internal service του viewer του ΥΠΕΝ) —\n"
                "  μπορεί να άλλαξε ή να κλειδώθηκε. Έλεγξε το URL στον browser:\n"
                f"  {SERVICE_URL}?f=json")
        except ValueError:
            raise RuntimeError(
                "ΕΜΣΥ endpoint returned non-JSON (πιθανό HTML error page) — "
                "το service ίσως άλλαξε μορφή. Έλεγξε το URL στον browser.")

        if "error" in data:
            raise RuntimeError(f"ΕΜΣΥ ArcGIS error: {data['error']}")

        batch = data.get("features", [])
        features.extend(batch)
        if not data.get("exceededTransferLimit") or not batch:
            break
        offset += len(batch)

    return features


def load(features, dry_run=False):
    if dry_run:
        print(f"  [dry-run] {len(features)} σημεία υδροληψίας στο bbox")
        return 0

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(DDL)
            cur.execute(f"TRUNCATE {TABLE} RESTART IDENTITY")
            n = 0
            for f in features:
                a = f.get("attributes", {})
                g = f.get("geometry") or {}
                x, y = g.get("x"), g.get("y")
                if x is None or y is None:
                    continue
                cur.execute(f"""
                    INSERT INTO {TABLE}
                        (objectid, kwdikos_emsy, kwdikos_sy, eidos_sy,
                         kathestws_xrhshs, idioktisiako, x_egsa87, y_egsa87, z,
                         bathos_gewtrhshs, topwnymio, koinothta, paratiriseis,
                         status, geom)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                            ST_SetSRID(ST_Point(%s, %s), 2100))
                """, (
                    a.get("OBJECTID"), a.get("KWDIKOS_EMSY"), a.get("KWDIKOS_SY"),
                    a.get("EIDOS_SY"), a.get("KATHESTWS_XRHSHS"),
                    a.get("IDIOKTHSIAKO_KATHESTWS"),
                    a.get("X_EGSA87"), a.get("Y_EGSA87"), a.get("Z"),
                    a.get("BATHOS_GEWTRHSHS"), a.get("TOPWNYMIO"),
                    a.get("KOINOTHTA"), a.get("PARATHRHSEIS"), a.get("STATUS"),
                    x, y,
                ))
                n += 1
        conn.commit()
        return n
    finally:
        conn.close()


def main():
    ap = argparse.ArgumentParser(description="Sync ΕΜΣΥ υδροληψίες → PostGIS")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--bbox", type=str, help="minx,miny,maxx,maxy (EGSA'87)")
    args = ap.parse_args()

    bbox = DEFAULT_BBOX
    if args.bbox:
        try:
            bbox = tuple(float(v) for v in args.bbox.split(","))
            assert len(bbox) == 4
        except (ValueError, AssertionError):
            print("Invalid --bbox. Expected: minx,miny,maxx,maxy")
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
        n = load(features, dry_run=args.dry_run)
    except psycopg2.Error as e:
        print(f"\nDB ERROR: {e}")
        sys.exit(1)

    if not args.dry_run:
        print(f"  Loaded: {n} → {TABLE} (full replace)")
    print("Done.")


if __name__ == "__main__":
    main()
