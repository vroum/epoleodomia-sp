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
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from arcgis_client import fetch_count, fetch_object_ids, request_json
from sync_safety import FetchError, LoadError, SyncError, validate_features


from settings import SETTINGS

DB = SETTINGS.database.connection_kwargs()

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
    "esriFieldTypeGUID": "text",
    "esriFieldTypeGlobalID": "text",
}
SKIP_FIELDS = {"shape__area", "shape__length"}


def get_layer_fields(service: str) -> list[tuple[str, str]]:
    url = BASE.format(service=service).rsplit("/query", 1)[0]
    meta = request_json(url, {"f": "json"}, TIMEOUT, "Cadastre")
    if not isinstance(meta.get("fields"), list) or not meta["fields"]:
        raise FetchError(f"{service}: missing/invalid layer fields")
    fields = []
    seen = set()
    for field in meta["fields"]:
        if not isinstance(field, dict):
            raise FetchError(f"{service}: malformed layer field")
        name, field_type = field.get("name"), field.get("type")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise FetchError(f"{service}: invalid layer field name {name!r}")
        col = name.lower()
        if col in SKIP_FIELDS:
            continue
        if col in seen or col in {"geom", "gid", "synced_at"}:
            raise FetchError(f"{service}: duplicate/reserved layer field {name!r}")
        if not isinstance(field_type, str) or field_type not in PG_TYPES:
            raise FetchError(f"{service}: unsupported type for {name}: {field_type!r}")
        seen.add(col)
        fields.append((name, PG_TYPES[field_type]))
    if not fields:
        raise FetchError(f"{service}: no usable layer fields")
    return fields


def _query_params():
    return {
        "where": "1=1", "geometry": BBOX, "geometryType": "esriGeometryEnvelope",
        "inSR": "2100", "spatialRel": "esriSpatialRelIntersects", "f": "json",
    }


def _source_ids(service):
    return fetch_object_ids(BASE.format(service=service), _query_params(), TIMEOUT,
                            f"Cadastre {service}")


def fetch_features(service: str):
    """Return all verified features, never a partially consumed generator.

    Query by the source's object-ID snapshot rather than by offsets. Short
    server-capped responses are retried for only the still-missing IDs. Every
    received identity must be requested and unique; the final source ID set
    must match. This detects membership changes, not concurrent attribute edits.
    """
    expected_count = count_features(service)
    oid_name, expected_ids = _source_ids(service)
    if len(expected_ids) != expected_count:
        raise FetchError(f"{service}: source count/object-ID mismatch; rerun the sync")
    remaining = set(expected_ids)
    features = []
    while remaining:
        requested = set(sorted(remaining)[:PAGE])
        params = dict(_query_params(), objectIds=",".join(str(i) for i in sorted(requested)),
                      outFields="*", outSR="2100", f="geojson", returnGeometry="true",
                      maxAllowableOffset="0", resultRecordCount=PAGE)
        data = request_json(BASE.format(service=service), params, TIMEOUT, "Cadastre", method="POST")
        try:
            batch = validate_features(data)
        except SyncError as exc:
            raise FetchError(f"{service}: {exc}") from exc
        if not batch:
            raise FetchError(f"{service}: incomplete download ({len(features)}/{expected_count})")
        received = set()
        for feat in batch:
            props = {k.lower(): v for k, v in feat["properties"].items()}
            oid = props.get(oid_name.lower())
            if isinstance(oid, bool) or not isinstance(oid, int) or oid not in requested:
                raise FetchError(f"{service}: unexpected/missing object ID {oid!r}")
            if oid in received:
                raise FetchError(f"{service}: duplicate downloaded object ID {oid}")
            received.add(oid)
        remaining.difference_update(received)
        features.extend(batch)

    final_name, final_ids = _source_ids(service)
    if final_name.lower() != oid_name.lower() or final_ids != expected_ids:
        raise FetchError(f"{service}: source object IDs changed during download; rerun the sync")
    return features


def count_features(service: str) -> int:
    return fetch_count(BASE.format(service=service), _query_params(), TIMEOUT,
                       f"Cadastre {service}")


def _diff_before_swap(cur, table: str, tmp: str, qualified: str):
    """
    Diff old vs new BEFORE the table swap.
    Parcels: new/removed KAEK, geometry (ST_Equals), main-use and other
    source-attribute changes, including source-ID reassignments for stable KAEK.
    Overlay tables (δουλείες/ΑΧ): row-count delta only.
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
    # Import IDs and timestamps are not source attributes. OBJECTID can also
    # change while the same KAEK/geometry survives, so report it separately.
    ignored = "ARRAY['geom','gid','synced_at','kaek','objectid','main_use']"
    cur.execute(f"""
        SELECT n.kaek, o.objectid, n.objectid,
               to_jsonb(o) - {ignored}, to_jsonb(n) - {ignored}
        FROM {tmp} n JOIN {qualified} o USING (kaek)
        WHERE (to_jsonb(o) - {ignored}) IS DISTINCT FROM (to_jsonb(n) - {ignored})
           OR o.objectid IS DISTINCT FROM n.objectid
        ORDER BY n.kaek
    """)
    d["attributes_changed"], d["source_ids_changed"] = [], []
    for kaek, old_id, new_id, old, new in cur.fetchall():
        changed = {key: {'old': old.get(key), 'new': new.get(key)}
                   for key in sorted(set(old) | set(new)) if old.get(key) != new.get(key)}
        if changed:
            d["attributes_changed"].append({'kaek': kaek, 'fields': changed})
        if old_id != new_id:
            d["source_ids_changed"].append((kaek, old_id, new_id))
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
        attribute_changes = d.get('attributes_changed', [])
        if attribute_changes:
            parts.append(f"  - Αλλαγές λοιπών πεδίων σε {len(attribute_changes)} ΚΑΕΚ:")
            for item in attribute_changes[:30]:
                values = []
                for field, change in item['fields'].items():
                    old_value = json.dumps(change['old'], ensure_ascii=False)
                    new_value = json.dumps(change['new'], ensure_ascii=False)
                    values.append(f"{field}: {old_value} → {new_value}")
                parts.append(f"    - {item['kaek']}: " + '; '.join(values))
            if len(attribute_changes) > 30:
                parts.append(f"    - … και {len(attribute_changes)-30} ακόμα ΚΑΕΚ")
        source_ids = d.get('source_ids_changed', [])
        if source_ids:
            capped, more = _cap([f"{key}: {old} → {new}" for key, old, new in source_ids])
            parts.append(f"  - Αλλαγή OBJECTID πηγής με ίδιο ΚΑΕΚ ({len(source_ids)}): "
                         + '; '.join(capped) + more)
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
    print(f"\n=== {table}  <-  {service} ===")
    fields = get_layer_fields(service)
    if "kaek" not in {name.lower() for name, _ in fields}:
        raise FetchError(f"{service}: source metadata is missing KAEK")

    rows = []
    for feat in fetch_features(service):
        props = feat["properties"]
        missing = [name for name, _ in fields if name not in props]
        if missing:
            raise FetchError(f"{service}: source record is missing fields {missing}")
        geom = feat["geometry"]
        if geom is None or geom["type"] not in {"Polygon", "MultiPolygon"}:
            raise FetchError(f"{service}: source record is missing polygon geometry")
        geomjson = json.dumps(geom)
        row = []
        for name, pg_type in fields:
            val = props[name]
            if name.lower() == "kaek" and (not isinstance(val, str) or not val.strip()):
                raise FetchError(f"{service}: source record has missing/invalid KAEK")
            if pg_type == "timestamptz" and val is not None:
                try:
                    val = datetime.fromtimestamp(val / 1000.0, tz=timezone.utc)
                except (TypeError, ValueError, OverflowError, OSError) as exc:
                    raise FetchError(f"{service}: invalid timestamp in {name}") from exc
            row.append(val)
        rows.append(tuple(row) + (geomjson,))
    print(f"  fetched: {len(rows)} features")
    if not rows:
        print("  nothing fetched — table left untouched")
        return False, None

    try:
        return _replace_layer(conn, table, fields, rows)
    except Exception as exc:
        conn.rollback()
        raise LoadError(f"Cadastral load rolled back for {SCHEMA}.{table}: {exc}") from exc


def _replace_layer(conn, table, fields, rows):
    """Stage all geometry, then publish without replacing the live relation."""
    import psycopg2.extras

    if table not in LAYERS:
        raise LoadError(f"Unknown cadastral destination: {table}")
    cols = [name.lower() for name, _ in fields]
    qualified = f"{SCHEMA}.{table}"
    tmp = "pg_temp.epol_cadastre_stage"
    col_ddl = ", ".join(f'"{n.lower()}" {t}' for n, t in fields)
    insert_cols = ", ".join(f'"{c}"' for c in cols)
    placeholders = ", ".join(["%s"] * len(cols))

    with conn.cursor() as cur:
        cur.execute("SET LOCAL lock_timeout = '5s'")
        cur.execute(f'CREATE TEMP TABLE epol_cadastre_stage ({col_ddl}, '
                    'geom geometry(MultiPolygon, 2100)) ON COMMIT DROP')
        psycopg2.extras.execute_batch(
            cur,
            f'INSERT INTO {tmp} ({insert_cols}, geom) VALUES ({placeholders}, '
            f'ST_Multi(ST_CollectionExtract(ST_MakeValid('
            f'ST_SetSRID(ST_GeomFromGeoJSON(%s), 2100)), 3)))',
            rows, page_size=200)
        cur.execute(f"""
            SELECT count(*), count(*) FILTER (
                WHERE geom IS NULL OR ST_IsEmpty(geom) OR NOT ST_IsValid(geom))
            FROM {tmp}
        """)
        staged_count, bad_geometries = cur.fetchone()
        if staged_count != len(rows) or bad_geometries:
            raise LoadError(f"Staged {staged_count}/{len(rows)} rows; "
                            f"{bad_geometries} empty/invalid polygon geometries")
        # Lock an existing destination before diff/publication. This also keeps
        # a concurrent writer from changing the rows between those operations.
        cur.execute("SELECT to_regclass(%s)", (qualified,))
        if cur.fetchone()[0] is not None:
            cur.execute(f'LOCK TABLE {qualified} IN ACCESS EXCLUSIVE MODE')
        diff = _diff_before_swap(cur, table, tmp, qualified)
        _publish_staged(cur, table, tmp, fields, len(rows))
    conn.commit()
    print(f"  loaded into {qualified}")
    return True, diff


def _publish_staged(cur, table, tmp, fields, expected_count):
    """Preserve table identity/metadata; fail on unreviewed schema changes."""
    qualified = f"{SCHEMA}.{table}"
    cur.execute("SELECT relkind, relrowsecurity, relhasrules FROM pg_class WHERE oid=to_regclass(%s)",
                (qualified,))
    existing = cur.fetchone()
    if existing is None:
        col_ddl = ", ".join(f'"{n.lower()}" {t}' for n, t in fields)
        cur.execute(f'CREATE TABLE {qualified} ({col_ddl}, geom geometry(MultiPolygon,2100), '
                    'gid serial, synced_at timestamptz DEFAULT now())')
        cur.execute(f'CREATE INDEX ON {qualified} USING gist (geom)')
        if any(n.lower() == 'kaek' for n, _ in fields):
            cur.execute(f'CREATE INDEX ON {qualified} (kaek)')
    else:
        if existing != ('r', False, False):
            raise LoadError(f"{qualified}: publication requires an ordinary table without row security or rewrite rules")
        cur.execute("""
            SELECT attname, format_type(atttypid,atttypmod), attgenerated, attidentity
            FROM pg_attribute WHERE attrelid=to_regclass(%s)
              AND attnum>0 AND NOT attisdropped
        """, (qualified,))
        actual = {n: (t, g, i) for n, t, g, i in cur.fetchall()}
        aliases = {'timestamptz': 'timestamp with time zone'}
        expected = {n.lower(): (aliases.get(t, t), '', '') for n, t in fields}
        expected.update(geom=('geometry(MultiPolygon,2100)', '', ''),
                        gid=('integer', '', ''), synced_at=('timestamp with time zone', '', ''))
        if actual != expected:
            raise LoadError(f"{qualified}: source/destination columns differ; review schema before sync")
        # DELETE could otherwise cascade into application-owned child rows.
        # Custom triggers also need a reviewed publication policy of their own.
        cur.execute("""
            SELECT conname FROM pg_constraint WHERE contype='f' AND confrelid=to_regclass(%s)
            UNION ALL
            SELECT tgname FROM pg_trigger WHERE tgrelid=to_regclass(%s) AND NOT tgisinternal
        """, (qualified, qualified))
        if cur.fetchall():
            raise LoadError(f"{qualified}: foreign-key consumers or custom triggers require review before sync")
        cur.execute(f'DELETE FROM {qualified}')
    columns = ', '.join(f'"{name.lower()}"' for name, _ in fields) + ', geom'
    cur.execute(f'INSERT INTO {qualified} ({columns}) SELECT {columns} FROM {tmp}')
    if cur.rowcount != expected_count:
        raise LoadError(f"{qualified}: published {cur.rowcount}/{expected_count} staged rows")


def report_diff(conn):
    sql = f"""
    SELECT
      (SELECT count(*) FROM {SCHEMA}.kaek_parcels_operating)            AS operating,
      (SELECT count(*) FROM {SCHEMA}.kaek_parcels_anartisi)              AS anartisi_1i,
      (SELECT count(*) FROM {SCHEMA}.kaek_parcels_operating o
         LEFT JOIN {SCHEMA}.kaek_parcels_anartisi a USING (kaek)
         WHERE a.kaek IS NULL)                                          AS new_kaek,
      (SELECT count(*) FROM {SCHEMA}.kaek_parcels_anartisi a
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
        try:
            for t, s in targets.items():
                print(f"{t}: {count_features(s)} features in Spetses bbox")
        except SyncError as exc:
            print(f"ERROR: {exc}")
            sys.exit(1)
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
    except SyncError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
