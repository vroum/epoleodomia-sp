"""
Sync operating cadastre (κτηματολόγιο σε λειτουργία) for Spetses from the
Hellenic Cadastre's ArcGIS Online feature services into sp_geodata.

Source: the FeatureServers behind maps.ktimatologio.gr
        (services-eu1.arcgis.com / org 40tFGWzosjaLJpmn)

Layers synced (table -> service):
    kaek_parcels_operating      <- GEOTEMAXIA_LEITOURGOUN_ON_gdb   (~3405 parcels)
    kaek_douleies_operating     <- GEOTEMAXIA_DOULEIES_ON_gdb      (easements)
    kaek_apokleistikes_operating<- GEOTEMAXIA_APOKLEISTIKES_ON_gdb (exclusive uses)

Attributes include KAEK, MAIN_USE, PERCENTAGE, DESCR, PROP_VERT, PROP_HOR, LINK.

Usage:
    python sync_kaek_operating.py             # sync all three layers
    python sync_kaek_operating.py --dry-run   # counts only, no DB writes
    python sync_kaek_operating.py --table kaek_parcels_operating

Requires: .env next to this script (EPOL_DB_* variables), requests, psycopg2.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests


# --- .env loader --------------------------------------------------------------
def load_env(path: Path):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith((";", "#")) or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


load_env(Path(__file__).parent / ".env")

DB = {
    "host": os.environ.get("EPOL_DB_HOST", "10.90.144.153"),
    "port": os.environ.get("EPOL_DB_PORT", "65432"),
    "dbname": os.environ.get("EPOL_DB_NAME", "gis"),
    "user": os.environ.get("EPOL_DB_USER", "docker"),
    "password": os.environ.get("EPOL_DB_PASSWORD", ""),
}

BASE = ("https://services-eu1.arcgis.com/40tFGWzosjaLJpmn/arcgis/"
        "rest/services/{service}/FeatureServer/0/query")

# Spetses bbox, EPSG:2100 (same as SPETSES_BBOX in the TEE sync config)
BBOX = "416555,4116249,431409,4129267"

LAYERS = {
    "kaek_parcels_operating":       "GEOTEMAXIA_LEITOURGOUN_ON_gdb",
    "kaek_douleies_operating":      "GEOTEMAXIA_DOULEIES_ON_gdb",
    "kaek_apokleistikes_operating": "GEOTEMAXIA_APOKLEISTIKES_ON_gdb",
}

SCHEMA = "sp_geodata"
PAGE = 2000
TIMEOUT = 120

# Esri field type -> PostgreSQL type
PG_TYPES = {
    "esriFieldTypeOID": "bigint",
    "esriFieldTypeSmallInteger": "integer",
    "esriFieldTypeInteger": "bigint",
    "esriFieldTypeDouble": "double precision",
    "esriFieldTypeSingle": "double precision",
    "esriFieldTypeString": "text",
    "esriFieldTypeDate": "timestamptz",
}
SKIP_FIELDS = {"shape__area", "shape__length"}


def get_layer_fields(service: str) -> list[tuple[str, str]]:
    url = BASE.format(service=service).rsplit("/query", 1)[0]
    meta = requests.get(url, params={"f": "json"}, timeout=TIMEOUT).json()
    fields = []
    for f in meta.get("fields", []):
        col = f["name"].lower()
        if col in SKIP_FIELDS:
            continue
        fields.append((f["name"], PG_TYPES.get(f["type"], "text")))
    return fields


def fetch_features(service: str):
    """Yield geojson features, paged."""
    offset = 0
    while True:
        params = {
            "where": "1=1",
            "geometry": BBOX,
            "geometryType": "esriGeometryEnvelope",
            "inSR": "2100",
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": "*",
            "outSR": "2100",
            "f": "geojson",
            "maxAllowableOffset": "0",  # Request full-precision vertices (no simplification)
            "resultOffset": offset,
            "resultRecordCount": PAGE,
        }
        r = requests.get(BASE.format(service=service), params=params, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        feats = data.get("features", [])
        if not feats:
            return
        yield from feats
        if len(feats) < PAGE:
            return
        offset += len(feats)


def count_features(service: str) -> int:
    params = {
        "where": "1=1", "geometry": BBOX, "geometryType": "esriGeometryEnvelope",
        "inSR": "2100", "spatialRel": "esriSpatialRelIntersects",
        "returnCountOnly": "true", "f": "json",
    }
    r = requests.get(BASE.format(service=service), params=params, timeout=TIMEOUT)
    return r.json().get("count", -1)


def _diff_before_swap(cur, table: str, tmp: str, qualified: str):
    """
    Diff old vs new BEFORE the table swap.
    Parcels: lists of new/removed KAEK, geometry changes (ST_Equals) and
    main-use changes. Overlay tables (δουλείες/ΑΧ): row-count delta only.
    Returns None on first run (no previous table).
    """
    cur.execute("SELECT to_regclass(%s)", (qualified,))
    if cur.fetchone()[0] is None:
        return None

    if table != "kaek_parcels_operating":
        cur.execute(f"SELECT count(*) FROM {qualified}")
        old_n = cur.fetchone()[0]
        cur.execute(f"SELECT count(*) FROM {tmp}")
        new_n = cur.fetchone()[0]
        return {"table": table, "counts_only": True, "old": old_n, "new": new_n}

    d = {"table": table, "counts_only": False}
    cur.execute(f"""
        SELECT DISTINCT n.kaek FROM {tmp} n
        LEFT JOIN {qualified} o USING (kaek)
        WHERE o.kaek IS NULL ORDER BY 1""")
    d["new"] = [r[0] for r in cur.fetchall()]
    cur.execute(f"""
        SELECT DISTINCT o.kaek FROM {qualified} o
        LEFT JOIN {tmp} n USING (kaek)
        WHERE n.kaek IS NULL ORDER BY 1""")
    d["removed"] = [r[0] for r in cur.fetchall()]
    cur.execute(f"""
        SELECT n.kaek,
               round(ST_Area(o.geom)::numeric, 1),
               round(ST_Area(n.geom)::numeric, 1)
        FROM {tmp} n JOIN {qualified} o USING (kaek)
        WHERE NOT ST_Equals(n.geom, o.geom)
        ORDER BY 1""")
    d["geom_changed"] = [(r[0], float(r[1]), float(r[2])) for r in cur.fetchall()]
    cur.execute(f"""
        SELECT n.kaek, COALESCE(o.descr, o.main_use, '—'),
               COALESCE(n.descr, n.main_use, '—')
        FROM {tmp} n JOIN {qualified} o USING (kaek)
        WHERE COALESCE(o.main_use, '') <> COALESCE(n.main_use, '')
        ORDER BY 1""")
    d["use_changed"] = cur.fetchall()
    return d


def write_changes_report(diffs) -> Path:
    """Write logs/KTIMA_CHANGES_latest.md and echo it to the console."""
    lines = [f"# Κτηματολόγιο — αλλαγές sync {datetime.now():%Y-%m-%d %H:%M}", ""]
    any_change = False

    def _cap(items, n=30):
        extra = len(items) - n
        return items[:n], (f" … +{extra} ακόμα" if extra > 0 else "")

    for d in diffs:
        if d is None:
            continue
        if d.get("counts_only"):
            delta = d["new"] - d["old"]
            if delta != 0:
                any_change = True
                sign = f"+{delta}" if delta > 0 else str(delta)
                lines.append(f"- **{d['table']}**: {d['old']} → {d['new']} ({sign})")
            continue

        parts = []
        if d["new"]:
            capped, more = _cap(d["new"])
            parts.append(f"  - Νέα ΚΑΕΚ ({len(d['new'])}): {', '.join(capped)}{more}")
        if d["removed"]:
            capped, more = _cap(d["removed"])
            parts.append(f"  - Διαγραμμένα ΚΑΕΚ ({len(d['removed'])}): {', '.join(capped)}{more}")
        if d["geom_changed"]:
            gc = [f"{k} ({a1}→{a2} τ.μ.)" for k, a1, a2 in d["geom_changed"][:30]]
            more = len(d["geom_changed"]) - 30
            parts.append(f"  - Αλλαγή γεωμετρίας ({len(d['geom_changed'])}): "
                         + ", ".join(gc) + (f" … +{more} ακόμα" if more > 0 else ""))
        if d["use_changed"]:
            uc = [f"{k}: «{o}» → «{n}»" for k, o, n in d["use_changed"][:30]]
            more = len(d["use_changed"]) - 30
            parts.append(f"  - Αλλαγή χρήσης ({len(d['use_changed'])}): "
                         + "; ".join(uc) + (f" … +{more} ακόμα" if more > 0 else ""))
        if parts:
            any_change = True
            lines.append(f"- **{d['table']}**:")
            lines.extend(parts)

    if not any_change:
        lines.append("Καμία αλλαγή σε σχέση με το προηγούμενο sync.")

    path = Path(__file__).parent / "logs" / "KTIMA_CHANGES_latest.md"
    path.parent.mkdir(exist_ok=True)
    text = "\n".join(lines) + "\n"
    path.write_text(text, encoding="utf-8")

    print("\n" + "=" * 60)
    print("ΤΙ ΑΛΛΑΞΕ ΣΤΟ ΚΤΗΜΑΤΟΛΟΓΙΟ (KTIMA_CHANGES_latest.md)")
    print("=" * 60)
    try:
        print(text)
    except UnicodeEncodeError:
        enc = sys.stdout.encoding or "ascii"
        print(text.encode(enc, errors="replace").decode(enc, errors="replace"))
    return path


def sync_layer(conn, table: str, service: str):
    """Returns (success: bool, diff: dict | None)."""
    import psycopg2.extras

    print(f"\n=== {table}  <-  {service} ===")
    fields = get_layer_fields(service)
    cols = [name.lower() for name, _ in fields]
    qualified = f"{SCHEMA}.{table}"
    tmp = f"{SCHEMA}.{table}_new"

    col_ddl = ", ".join(f'"{n.lower()}" {t}' for n, t in fields)
    insert_cols = ", ".join(f'"{c}"' for c in cols)
    placeholders = ", ".join(["%s"] * len(cols))

    date_cols = {name.lower() for name, pg_type in fields if pg_type == "timestamptz"}

    rows = []
    for feat in fetch_features(service):
        props = feat.get("properties", {})
        geomjson = json.dumps(feat.get("geometry"))
        row = []
        for name, pg_type in fields:
            val = props.get(name)
            if pg_type == "timestamptz" and val is not None:
                val = datetime.fromtimestamp(val / 1000.0, tz=timezone.utc)
            row.append(val)
        rows.append(tuple(row) + (geomjson,))
    print(f"  fetched: {len(rows)} features")
    if not rows:
        print("  nothing fetched — table left untouched")
        return False, None

    with conn.cursor() as cur:
        cur.execute(f'DROP TABLE IF EXISTS {tmp}')
        cur.execute(f'CREATE TABLE {tmp} ({col_ddl}, geom geometry(MultiPolygon, 2100))')
        psycopg2.extras.execute_batch(
            cur,
            f'INSERT INTO {tmp} ({insert_cols}, geom) VALUES ({placeholders}, '
            f'ST_Multi(ST_CollectionExtract(ST_MakeValid('
            f'ST_SetSRID(ST_GeomFromGeoJSON(%s), 2100)), 3)))',
            rows, page_size=200)
        cur.execute(f'ALTER TABLE {tmp} ADD COLUMN gid serial')
        cur.execute(f'ALTER TABLE {tmp} ADD COLUMN synced_at timestamptz DEFAULT now()')

        # Diff old vs new before the swap (None on first run)
        diff = _diff_before_swap(cur, table, tmp, qualified)

        cur.execute(f'DROP TABLE IF EXISTS {qualified}')
        cur.execute(f'ALTER TABLE {tmp} RENAME TO {table}_renaming')
        cur.execute(f'ALTER TABLE {SCHEMA}."{table}_renaming" RENAME TO "{table}"')
        cur.execute(f'CREATE INDEX ON {qualified} USING gist (geom)')
        if "kaek" in cols:
            cur.execute(f'CREATE INDEX ON {qualified} (kaek)')
    conn.commit()
    print(f"  loaded into {qualified}")
    return True, diff


def report_diff(conn):
    sql = f"""
    SELECT
      (SELECT count(*) FROM {SCHEMA}.kaek_parcels_operating)            AS operating,
      (SELECT count(*) FROM {SCHEMA}.kaek_parcels_autocad)              AS anartisi_1i,
      (SELECT count(*) FROM {SCHEMA}.kaek_parcels_operating o
         LEFT JOIN {SCHEMA}.kaek_parcels_autocad a USING (kaek)
         WHERE a.kaek IS NULL)                                          AS new_kaek,
      (SELECT count(*) FROM {SCHEMA}.kaek_parcels_autocad a
         LEFT JOIN {SCHEMA}.kaek_parcels_operating o USING (kaek)
         WHERE o.kaek IS NULL)                                          AS dropped_kaek
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        op, an, new, dropped = cur.fetchone()
    print(f"\nOperating: {op} | 1η ανάρτηση: {an} | new KAEK: {new} | dropped KAEK: {dropped}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--table", choices=list(LAYERS), help="sync one layer only")
    args = ap.parse_args()

    targets = {args.table: LAYERS[args.table]} if args.table else LAYERS

    if args.dry_run:
        for t, s in targets.items():
            print(f"{t}: {count_features(s)} features in Spetses bbox")
        return

    if not DB["password"]:
        print("ERROR: EPOL_DB_PASSWORD not set (.env missing?)")
        sys.exit(1)

    import psycopg2
    conn = psycopg2.connect(**DB)
    try:
        ok = True
        diffs = []
        for t, s in targets.items():
            success, diff = sync_layer(conn, t, s)
            ok = ok and success
            diffs.append(diff)

        if any(d is not None for d in diffs):
            write_changes_report(diffs)
        elif ok:
            print("\n(first run — no previous data to diff)")

        if "kaek_parcels_operating" in targets and ok:
            report_diff(conn)
        sys.exit(0 if ok else 1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
