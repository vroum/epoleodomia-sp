"""
Load GeoJSON data into PostGIS tables with change tracking

v1.1 — Credentials now handled centrally by config.py / .env
"""

import json
import psycopg2
from typing import Dict, List, Any, Optional
from datetime import datetime

from config import DATABASE, FIELD_MAPPINGS


def get_connection():
    """Get a database connection using config settings."""
    return psycopg2.connect(
        host=DATABASE["host"],
        port=DATABASE["port"],
        database=DATABASE["database"],
        user=DATABASE["user"],
        password=DATABASE["password"],
    )


def get_table_columns(conn, schema: str, table_name: str) -> List[str]:
    """
    Get column names for a table (excluding id, geom, fetched_at, tracking columns).

    Args:
        conn: Database connection
        schema: Schema name
        table_name: Table name

    Returns:
        List of column names
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = %s
              AND table_name = %s
              AND column_name NOT IN ('id', 'geom', 'fetched_at', 'created_at', 'updated_at', 'is_deleted', 'deleted_at')
            ORDER BY ordinal_position
        """, (schema, table_name))

        return [row[0] for row in cur.fetchall()]


def map_field_name(arcgis_name: str) -> str:
    """
    Map an ArcGIS field name to PostgreSQL column name.

    Args:
        arcgis_name: Field name from ArcGIS

    Returns:
        PostgreSQL column name
    """
    # Check exact match first
    if arcgis_name in FIELD_MAPPINGS:
        return FIELD_MAPPINGS[arcgis_name]

    # Try uppercase
    upper_name = arcgis_name.upper()
    if upper_name in FIELD_MAPPINGS:
        return FIELD_MAPPINGS[upper_name]

    # Default: lowercase the name
    return arcgis_name.lower()


def geometry_to_wkt(geom: Dict) -> Optional[str]:
    """
    Convert GeoJSON geometry to WKT.

    Args:
        geom: GeoJSON geometry dict

    Returns:
        WKT string or None
    """
    if not geom:
        return None

    geom_type = geom.get("type")
    coords = geom.get("coordinates")

    if not geom_type or coords is None:
        return None

    if geom_type == "Point":
        return f"POINT({coords[0]} {coords[1]})"

    elif geom_type == "LineString":
        coord_str = ", ".join(f"{c[0]} {c[1]}" for c in coords)
        return f"LINESTRING({coord_str})"

    elif geom_type == "Polygon":
        rings = []
        for ring in coords:
            ring_str = ", ".join(f"{c[0]} {c[1]}" for c in ring)
            rings.append(f"({ring_str})")
        return f"POLYGON({', '.join(rings)})"

    elif geom_type == "MultiPoint":
        points = ", ".join(f"({c[0]} {c[1]})" for c in coords)
        return f"MULTIPOINT({points})"

    elif geom_type == "MultiLineString":
        lines = []
        for line in coords:
            line_str = ", ".join(f"{c[0]} {c[1]}" for c in line)
            lines.append(f"({line_str})")
        return f"MULTILINESTRING({', '.join(lines)})"

    elif geom_type == "MultiPolygon":
        polygons = []
        for polygon in coords:
            rings = []
            for ring in polygon:
                ring_str = ", ".join(f"{c[0]} {c[1]}" for c in ring)
                rings.append(f"({ring_str})")
            polygons.append(f"({', '.join(rings)})")
        return f"MULTIPOLYGON({', '.join(polygons)})"

    return None


def check_tracking_columns(conn, schema: str, table_name: str) -> bool:
    """Check if table has tracking columns, add them if not."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            AND column_name IN ('created_at', 'updated_at', 'is_deleted', 'deleted_at')
        """, (schema, table_name))
        existing = {row[0] for row in cur.fetchall()}

        if 'created_at' not in existing:
            cur.execute(f'ALTER TABLE {schema}."{table_name}" ADD COLUMN created_at TIMESTAMP DEFAULT NOW()')
        if 'updated_at' not in existing:
            cur.execute(f'ALTER TABLE {schema}."{table_name}" ADD COLUMN updated_at TIMESTAMP')
        if 'is_deleted' not in existing:
            cur.execute(f'ALTER TABLE {schema}."{table_name}" ADD COLUMN is_deleted BOOLEAN DEFAULT FALSE')
        if 'deleted_at' not in existing:
            cur.execute(f'ALTER TABLE {schema}."{table_name}" ADD COLUMN deleted_at TIMESTAMP')

        conn.commit()
        return True


def load_geojson_to_table(
    geojson: Dict[str, Any],
    table_name: str,
    schema: str = None,
    truncate: bool = True,
    srid: int = 2100
) -> int:
    """
    Load GeoJSON FeatureCollection into a PostGIS table.
    Uses UPSERT based on objectid for change tracking when truncate=False.

    Args:
        geojson: GeoJSON FeatureCollection dict
        table_name: Target table name
        schema: Schema name (defaults to config)
        truncate: Whether to truncate table before loading (default True for backward compat)
        srid: Spatial reference ID

    Returns:
        Number of records inserted/updated
    """
    if schema is None:
        schema = DATABASE["schema"]

    features = geojson.get("features", [])
    if not features:
        print(f"  No features to load into {schema}.{table_name}")
        return 0

    conn = get_connection()
    try:
        # Get table columns
        columns = get_table_columns(conn, schema, table_name)

        if not columns:
            print(f"  Error: Could not get columns for {schema}.{table_name}")
            return 0

        with conn.cursor() as cur:
            if truncate:
                # Original behavior: truncate and insert
                cur.execute(f'TRUNCATE TABLE {schema}."{table_name}" RESTART IDENTITY')

                # Prepare insert statement
                col_list = ", ".join(columns)
                placeholders = ", ".join(["%s"] * len(columns))

                insert_sql = f'''
                    INSERT INTO {schema}."{table_name}" ({col_list}, geom, fetched_at)
                    VALUES ({placeholders}, ST_GeomFromText(%s, {srid}), %s)
                '''

                # Process features
                inserted = 0
                errors = 0

                for feature in features:
                    props = feature.get("properties", {})
                    geom = feature.get("geometry")

                    # Build row values
                    row = []
                    for col in columns:
                        value = None
                        for prop_name, prop_value in props.items():
                            if map_field_name(prop_name) == col:
                                value = prop_value
                                break
                        row.append(value)

                    # Add geometry and timestamp
                    wkt = geometry_to_wkt(geom)
                    row.append(wkt)
                    row.append(datetime.now())

                    try:
                        cur.execute(insert_sql, row)
                        inserted += 1
                    except Exception as e:
                        errors += 1
                        if errors <= 3:
                            print(f"  Error inserting row: {e}")

                conn.commit()

                if errors > 0:
                    print(f"  Inserted {inserted} records with {errors} errors")
                else:
                    print(f"  Inserted {inserted} records")

                return inserted

            else:
                # UPSERT mode with change tracking
                check_tracking_columns(conn, schema, table_name)

                # Get all current objectids
                incoming_objectids = set()
                for feature in features:
                    props = feature.get("properties", {})
                    oid = props.get("OBJECTID") or props.get("objectid") or props.get("OBJECTID_1")
                    if oid:
                        incoming_objectids.add(oid)

                # Build upsert statement
                col_list = ", ".join(columns)
                placeholders = ", ".join(["%s"] * len(columns))
                update_cols = ", ".join([f"{col} = EXCLUDED.{col}" for col in columns if col != 'objectid'])

                upsert_sql = f'''
                    INSERT INTO {schema}."{table_name}" ({col_list}, geom, fetched_at, created_at, updated_at, is_deleted)
                    VALUES ({placeholders}, ST_GeomFromText(%s, {srid}), %s,
                            COALESCE((SELECT created_at FROM {schema}."{table_name}" WHERE objectid = %s), NOW()),
                            NOW(), FALSE)
                    ON CONFLICT (objectid) DO UPDATE SET
                        {update_cols},
                        geom = EXCLUDED.geom,
                        fetched_at = EXCLUDED.fetched_at,
                        updated_at = NOW(),
                        is_deleted = FALSE,
                        deleted_at = NULL
                '''

                inserted = 0
                updated = 0
                errors = 0
                now = datetime.now()

                for feature in features:
                    props = feature.get("properties", {})
                    geom = feature.get("geometry")

                    # Build row values
                    row = []
                    objectid_value = None
                    for col in columns:
                        value = None
                        for prop_name, prop_value in props.items():
                            if map_field_name(prop_name) == col:
                                value = prop_value
                                if col == 'objectid':
                                    objectid_value = value
                                break
                        row.append(value)

                    # Add geometry, timestamp, and objectid for the COALESCE
                    wkt = geometry_to_wkt(geom)
                    row.append(wkt)
                    row.append(now)
                    row.append(objectid_value)

                    try:
                        cur.execute(upsert_sql, row)
                        if cur.rowcount > 0:
                            inserted += 1
                    except Exception as e:
                        errors += 1
                        if errors <= 3:
                            print(f"  Error upserting row: {e}")

                # Mark records not in source as deleted
                if incoming_objectids:
                    placeholders_list = ",".join(["%s"] * len(incoming_objectids))
                    cur.execute(f'''
                        UPDATE {schema}."{table_name}"
                        SET is_deleted = TRUE, deleted_at = NOW()
                        WHERE objectid NOT IN ({placeholders_list})
                        AND (is_deleted = FALSE OR is_deleted IS NULL)
                    ''', list(incoming_objectids))
                    deleted = cur.rowcount
                else:
                    deleted = 0

                conn.commit()

                print(f"  Upserted {inserted} records, marked {deleted} as deleted, {errors} errors")
                return inserted

    except Exception as e:
        conn.rollback()
        print(f"  Error loading data: {e}")
        return 0

    finally:
        conn.close()


def start_sync_run(mode: str = 'track') -> Optional[int]:
    """Start a new sync run and return its ID."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_schema = %s AND table_name = 'sync_runs'
                )
            """, (DATABASE["schema"],))
            if not cur.fetchone()[0]:
                return None

            cur.execute(f'''
                INSERT INTO {DATABASE["schema"]}.sync_runs (started_at, mode, status)
                VALUES (NOW(), %s, 'running')
                RETURNING id
            ''', (mode,))
            sync_run_id = cur.fetchone()[0]
            conn.commit()
            return sync_run_id
    except Exception as e:
        print(f"  Warning: Could not start sync run: {e}")
        return None
    finally:
        conn.close()


def complete_sync_run(sync_run_id: int, stats: Dict[str, int], status: str = 'success', error_msg: str = None):
    """Complete a sync run with final stats."""
    if sync_run_id is None:
        return

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f'''
                UPDATE {DATABASE["schema"]}.sync_runs
                SET completed_at = NOW(),
                    status = %s,
                    records_new = %s,
                    records_updated = %s,
                    records_deleted = %s,
                    error_message = %s
                WHERE id = %s
            ''', (status, stats.get('new', 0), stats.get('updated', 0),
                  stats.get('deleted', 0), error_msg, sync_run_id))
            conn.commit()
    except Exception as e:
        print(f"  Warning: Could not complete sync run: {e}")
    finally:
        conn.close()


def log_change(
    cur,
    sync_run_id: Optional[int],
    table_name: str,
    objectid: int,
    change_type: str,
    old_values: Dict = None,
    new_values: Dict = None,
    changed_fields: List[str] = None,
    old_geom_wkt: str = None,
    new_geom_wkt: str = None,
    record_id: int = None
):
    """Log a change to the changelog table."""
    if sync_run_id is None:
        return

    schema = DATABASE["schema"]

    old_fek = old_values.get('fek') if old_values else None
    new_fek = new_values.get('fek') if new_values else None

    geometry_changed = (old_geom_wkt is not None or new_geom_wkt is not None) and old_geom_wkt != new_geom_wkt

    try:
        cur.execute(f'''
            INSERT INTO {schema}.changelog
            (sync_run_id, table_name, objectid, record_id, change_type,
             changed_fields, old_values, new_values,
             geometry_changed, old_geom_wkt, new_geom_wkt,
             old_fek, new_fek)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ''', (
            sync_run_id, table_name, objectid, record_id, change_type,
            changed_fields,
            json.dumps(old_values) if old_values else None,
            json.dumps(new_values) if new_values else None,
            geometry_changed,
            old_geom_wkt if geometry_changed else None,
            new_geom_wkt if geometry_changed else None,
            old_fek, new_fek
        ))
    except Exception:
        pass  # Don't fail the sync if changelog write fails


def load_geojson_with_tracking(
    geojson: Dict[str, Any],
    table_name: str,
    schema: str = None,
    srid: int = 2100,
    sync_run_id: int = None
) -> Dict[str, Any]:
    """
    Load GeoJSON with full change tracking. Returns stats and change details.

    Args:
        geojson: GeoJSON FeatureCollection dict
        table_name: Target table name
        schema: Schema name (defaults to config)
        srid: Spatial reference ID
        sync_run_id: Optional sync run ID for changelog

    Returns:
        Dict with counts and changes
    """
    if schema is None:
        schema = DATABASE["schema"]

    features = geojson.get("features", [])
    stats = {'new': 0, 'updated': 0, 'deleted': 0, 'unchanged': 0, 'errors': 0, 'changes': []}

    if not features:
        print(f"  No features to load into {schema}.{table_name}")
        return stats

    conn = get_connection()
    try:
        check_tracking_columns(conn, schema, table_name)

        columns = get_table_columns(conn, schema, table_name)
        if not columns:
            print(f"  Error: Could not get columns for {schema}.{table_name}")
            return stats

        with conn.cursor() as cur:
            # Get existing records with all their values
            col_list_select = ", ".join(columns)
            cur.execute(f'''
                SELECT id, objectid, {col_list_select}, ST_AsText(geom) as geom_wkt
                FROM {schema}."{table_name}"
                WHERE is_deleted = FALSE OR is_deleted IS NULL
            ''')

            existing = {}
            for row in cur.fetchall():
                record_id = row[0]
                objectid = row[1]
                values = dict(zip(columns, row[2:-1]))
                geom_wkt = row[-1]
                existing[objectid] = {
                    'id': record_id,
                    'values': values,
                    'geom_wkt': geom_wkt
                }

            incoming_objectids = set()
            now = datetime.now()

            for feature in features:
                props = feature.get("properties", {})
                geom = feature.get("geometry")

                objectid = props.get("OBJECTID") or props.get("objectid") or props.get("OBJECTID_1")
                if objectid:
                    incoming_objectids.add(objectid)

                # Build row values
                row_values = {}
                for col in columns:
                    for prop_name, prop_value in props.items():
                        if map_field_name(prop_name) == col:
                            row_values[col] = prop_value
                            break

                # Derived columns: drop the source's area_m2 for tables where we
                # recalculate it from geometry (TEE sends 0 for forest tables).
                # Prevents hundreds of fake "area_m2 → 0" updates on every sync;
                # post_sync_recalculate() fills the value after the load.
                if table_name in AREA_RECALC_TABLES:
                    row_values.pop('area_m2', None)

                wkt = geometry_to_wkt(geom)

                try:
                    if objectid not in existing:
                        # New record — INSERT
                        col_list = ", ".join(row_values.keys())
                        placeholders = ", ".join(["%s"] * len(row_values))
                        values = list(row_values.values())

                        cur.execute(f'''
                            INSERT INTO {schema}."{table_name}" ({col_list}, geom, fetched_at, created_at, is_deleted)
                            VALUES ({placeholders}, ST_GeomFromText(%s, {srid}), %s, %s, FALSE)
                            RETURNING id
                        ''', values + [wkt, now, now])

                        new_id = cur.fetchone()[0]
                        stats['new'] += 1

                        stats['changes'].append({
                            'type': 'INSERT',
                            'objectid': objectid,
                            'new_values': row_values.copy()
                        })

                        log_change(cur, sync_run_id, table_name, objectid, 'INSERT',
                                   old_values=None, new_values=row_values,
                                   new_geom_wkt=wkt, record_id=new_id)
                    else:
                        # Existing record — check what changed
                        old_record = existing[objectid]
                        old_values = old_record['values']
                        old_geom = old_record['geom_wkt']

                        changed_fields = []
                        for col in row_values:
                            old_val = old_values.get(col)
                            new_val = row_values.get(col)
                            old_norm = None if old_val in (None, '', 'None') else old_val
                            new_norm = None if new_val in (None, '', 'None') else new_val
                            if old_norm != new_norm:
                                if str(old_norm) != str(new_norm):
                                    changed_fields.append(col)

                        # Geometry change: WKT length comparison with 5% threshold
                        if old_geom and wkt:
                            len_diff = abs(len(old_geom) - len(wkt))
                            max_len = max(len(old_geom), len(wkt))
                            len_pct = len_diff / max_len if max_len > 0 else 0
                            geom_changed = len_pct > 0.05
                        elif old_geom is None and wkt is None:
                            geom_changed = False
                        else:
                            geom_changed = True

                        if changed_fields or geom_changed:
                            # UPDATE
                            set_clause = ", ".join([f"{col} = %s" for col in row_values.keys()])
                            values = list(row_values.values())

                            cur.execute(f'''
                                UPDATE {schema}."{table_name}"
                                SET {set_clause}, geom = ST_GeomFromText(%s, {srid}),
                                    fetched_at = %s, updated_at = %s, is_deleted = FALSE, deleted_at = NULL
                                WHERE objectid = %s
                            ''', values + [wkt, now, now, objectid])

                            stats['updated'] += 1

                            stats['changes'].append({
                                'type': 'UPDATE',
                                'objectid': objectid,
                                'changed_fields': changed_fields if changed_fields else [],
                                'old_values': {k: old_values.get(k) for k in changed_fields} if changed_fields else {},
                                'new_values': {k: row_values.get(k) for k in changed_fields} if changed_fields else {},
                                'geometry_changed': geom_changed
                            })

                            log_change(cur, sync_run_id, table_name, objectid, 'UPDATE',
                                       old_values=old_values, new_values=row_values,
                                       changed_fields=changed_fields if changed_fields else None,
                                       old_geom_wkt=old_geom if geom_changed else None,
                                       new_geom_wkt=wkt if geom_changed else None,
                                       record_id=old_record['id'])
                        else:
                            stats['unchanged'] += 1

                except Exception as e:
                    stats['errors'] += 1
                    if stats['errors'] <= 3:
                        print(f"  Error processing record: {e}")

            # Mark deleted records
            if incoming_objectids:
                placeholders_list = ",".join(["%s"] * len(incoming_objectids))
                cur.execute(f'''
                    SELECT id, objectid, {col_list_select}, ST_AsText(geom) as geom_wkt
                    FROM {schema}."{table_name}"
                    WHERE objectid NOT IN ({placeholders_list})
                    AND (is_deleted = FALSE OR is_deleted IS NULL)
                ''', list(incoming_objectids))

                deleted_records = cur.fetchall()

                cur.execute(f'''
                    UPDATE {schema}."{table_name}"
                    SET is_deleted = TRUE, deleted_at = %s
                    WHERE objectid NOT IN ({placeholders_list})
                    AND (is_deleted = FALSE OR is_deleted IS NULL)
                ''', [now] + list(incoming_objectids))

                stats['deleted'] = cur.rowcount

                for row in deleted_records:
                    record_id = row[0]
                    objectid = row[1]
                    values = dict(zip(columns, row[2:-1]))
                    geom_wkt = row[-1]

                    stats['changes'].append({
                        'type': 'DELETE',
                        'objectid': objectid,
                        'old_values': values.copy()
                    })

                    log_change(cur, sync_run_id, table_name, objectid, 'DELETE',
                               old_values=values, new_values=None,
                               old_geom_wkt=geom_wkt, record_id=record_id)

            # --- Data quality guard: detect mass zeroing/nulling ---
            zero_counts = {}
            if stats['updated'] > 5:
                for change in stats['changes']:
                    if change.get('type') != 'UPDATE':
                        continue
                    for col in change.get('changed_fields', []):
                        old_val = change.get('old_values', {}).get(col)
                        new_val = change.get('new_values', {}).get(col)
                        # Detect: had a real value, now it's 0/None/empty
                        if old_val not in (None, '', 'None', 0, '0'):
                            if new_val in (None, '', 'None', 0, '0'):
                                zero_counts[col] = zero_counts.get(col, 0) + 1

                for col, count in zero_counts.items():
                    pct = count / stats['updated'] * 100
                    if pct > 50:
                        print(f"  ⚠ DATA QUALITY WARNING: {col} was zeroed/nulled "
                              f"in {count}/{stats['updated']} updates ({pct:.0f}%) "
                              f"— possible API regression")

            stats['warnings'] = [
                f"{col}: {count}/{stats['updated']} zeroed ({count/stats['updated']*100:.0f}%)"
                for col, count in zero_counts.items()
                if stats['updated'] > 0 and count / stats['updated'] > 0.5
            ]

            conn.commit()

            print(f"  New: {stats['new']}, Updated: {stats['updated']}, Deleted: {stats['deleted']}, Unchanged: {stats['unchanged']}, Errors: {stats['errors']}")
            return stats

    except Exception as e:
        conn.rollback()
        print(f"  Error loading data: {e}")
        return stats
    finally:
        conn.close()


def log_sync(
    table_name: str,
    service_name: str,
    layer_id: int,
    records_fetched: int,
    status: str,
    error_message: str = None,
    sync_started: datetime = None,
    sync_completed: datetime = None
):
    """Log sync operation to sync_log table."""
    schema = DATABASE["schema"]
    conn = get_connection()

    try:
        with conn.cursor() as cur:
            cur.execute(f'''
                INSERT INTO {schema}.sync_log
                (table_name, service_name, layer_id, records_fetched,
                 sync_started_at, sync_completed_at, status, error_message)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ''', (
                table_name, service_name, layer_id, records_fetched,
                sync_started, sync_completed, status, error_message
            ))
            conn.commit()
    except Exception as e:
        print(f"  Error logging sync: {e}")
    finally:
        conn.close()


# Tables with area_m2 that should always be recalculated from geometry
# (TEE API has proven unreliable for this derived column)
AREA_RECALC_TABLES = [
    'forest_maps',
    'forest_maps_posted_attica_2021',
    'forest_maps_posted_pelop_2022',
]


def post_sync_recalculate(table_name: str, schema: str = None):
    """
    Recalculate derived columns after sync.
    Currently: area_m2 from geometry for forest map tables.
    """
    if schema is None:
        schema = DATABASE["schema"]

    if table_name not in AREA_RECALC_TABLES:
        return

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f'''
                UPDATE {schema}."{table_name}"
                SET area_m2 = round(ST_Area(geom)::numeric, 2)
                WHERE geom IS NOT NULL
                  AND (area_m2 IS NULL OR area_m2 = 0
                       OR abs(area_m2 - ST_Area(geom)) / NULLIF(ST_Area(geom), 0) > 0.01)
            ''')
            fixed = cur.rowcount
            conn.commit()
            if fixed > 0:
                print(f"  ⚠ Post-sync: recalculated area_m2 for {fixed} records in {table_name}")
    except Exception as e:
        conn.rollback()
        print(f"  Warning: post-sync area recalc failed for {table_name}: {e}")
    finally:
        conn.close()


def execute_sql_file(filepath: str) -> bool:
    """Execute an SQL file against the database."""
    with open(filepath, 'r', encoding='utf-8') as f:
        sql = f.read()

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
        print(f"Executed {filepath} successfully")
        return True
    except Exception as e:
        conn.rollback()
        print(f"Error executing {filepath}: {e}")
        return False
    finally:
        conn.close()


if __name__ == "__main__":
    print("Testing database connection...")
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT PostGIS_Version()")
            version = cur.fetchone()[0]
            print(f"Connected! PostGIS version: {version}")
        conn.close()
    except Exception as e:
        print(f"Connection error: {e}")
        print("\nMake sure .env file exists with DB_PASSWORD set")
