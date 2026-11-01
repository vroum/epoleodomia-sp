"""
Load GeoJSON data into PostGIS tables with change tracking

v1.1 — Credentials now handled centrally by config.py / .env
"""

import json
import psycopg2
from typing import Dict, List, Any, Optional
from datetime import datetime
from pathlib import Path

from config import DATABASE, FIELD_MAPPINGS
from sync_safety import LoadError, feature_objectid, validate_features
from sync_geometry import geometry_changes


def get_connection():
    """Get a database connection using config settings."""
    return psycopg2.connect(**{k: v for k, v in DATABASE.items() if k != "schema"})


def _refresh_derived_catalog(cur, schema, table_name):
    if schema == 'epoleodomia' and table_name == 'planning_diagrams':
        statement = Path(__file__).with_name('sql').joinpath('006_refresh_raster_catalog.sql')
        cur.execute(statement.read_text(encoding='utf-8'))


def get_table_columns(conn, schema: str, table_name: str) -> List[str]:
    """
    Get writable source columns, excluding generated/identity and managed fields.

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
              AND is_generated = 'NEVER'
              AND is_identity = 'NO'
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
    """Require managed tracking columns without doing DDL in a data sync."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            AND column_name IN ('created_at', 'updated_at', 'is_deleted', 'deleted_at')
        """, (schema, table_name))
        existing = {row[0] for row in cur.fetchall()}

        missing = {'created_at', 'updated_at', 'is_deleted', 'deleted_at'} - existing
        if missing:
            raise LoadError(f'Missing tracking columns in {schema}.{table_name}: '
                            + ', '.join(sorted(missing))
                            + '. Review database_setup.py with the schema administrator before syncing.')
        return True


def load_geojson_to_table(
    geojson: Dict[str, Any],
    table_name: str,
    schema: str = None,
    truncate: bool = True,
    srid: int = 2100,
    *, connection=None, replace_via_delete=False
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

    Raises:
        SyncError for invalid input; LoadError if the entire data load rolls back.
    """
    if schema is None:
        schema = DATABASE["schema"]

    if replace_via_delete and (connection is None or not truncate or
                              (schema, table_name) != ('epoleodomia', 'building_regs_lot')):
        raise LoadError('MVCC replacement requires the publication transaction and the reviewed lot table')

    features = validate_features(geojson, require_unique_ids=not truncate)
    if not features:
        print(f"  No features to load into {schema}.{table_name}")
        return 0

    conn = connection if connection is not None else get_connection()
    try:
        # Get table columns
        columns = get_table_columns(conn, schema, table_name)

        if not columns:
            raise LoadError(f"Could not get columns for {schema}.{table_name}")

        with conn.cursor() as cur:
            if truncate:
                # Replace all source rows, including legitimate duplicate IDs.
                # Internal import IDs continue; resetting sequences is admin work.
                if replace_via_delete:
                    cur.execute(f'DELETE FROM {schema}."{table_name}"')
                else:
                    cur.execute(f'TRUNCATE TABLE {schema}."{table_name}" CONTINUE IDENTITY')

                # Prepare insert statement
                col_list = ", ".join(columns)
                placeholders = ", ".join(["%s"] * len(columns))

                insert_sql = f'''
                    INSERT INTO {schema}."{table_name}" ({col_list}, geom, fetched_at)
                    VALUES ({placeholders}, ST_GeomFromText(%s, {srid}), %s)
                '''

                # Process features
                inserted = 0

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
                        raise LoadError(f"Error inserting source record: {e}") from e

                _refresh_derived_catalog(cur, schema, table_name)
                if connection is None:
                    conn.commit()

                print(f"  Inserted {inserted} records")

                return inserted

            else:
                # UPSERT mode with change tracking
                check_tracking_columns(conn, schema, table_name)

                # Get all current objectids
                incoming_objectids = set()
                for feature in features:
                    props = feature.get("properties", {})
                    oid = feature_objectid(props)
                    if oid is not None:
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
                        raise LoadError(f"Error upserting source record: {e}") from e

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

                _refresh_derived_catalog(cur, schema, table_name)
                if connection is None:
                    conn.commit()

                print(f"  Upserted {inserted} records, marked {deleted} as deleted")
                return inserted

    except Exception as e:
        if connection is None:
            conn.rollback()
        raise LoadError(f"Load rolled back for {schema}.{table_name}: {e}") from e

    finally:
        if connection is None:
            conn.close()


def start_sync_run(mode: str = 'track', *, connection=None) -> Optional[int]:
    """Start a new sync run and return its ID."""
    conn = connection if connection is not None else get_connection()
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
            if connection is None:
                conn.commit()
            return sync_run_id
    except Exception as e:
        if connection is not None:
            raise
        print(f"  Warning: Could not start sync run: {e}")
        return None
    finally:
        if connection is None:
            conn.close()


def complete_sync_run(sync_run_id: int, stats: Dict[str, int], status: str = 'success', error_msg: str = None, *, connection=None):
    """Complete a sync run with final stats."""
    if sync_run_id is None:
        return

    conn = connection if connection is not None else get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f'''
                UPDATE {DATABASE["schema"]}.sync_runs
                SET completed_at = NOW(),
                    status = %s,
                    records_new = %s,
                    records_updated = %s,
                    records_deleted = %s,
                    tables_synced = %s,
                    error_message = %s
                WHERE id = %s
            ''', (status, stats.get('new', 0), stats.get('updated', 0),
                  stats.get('deleted', 0), stats.get('tables_synced', 0), error_msg, sync_run_id))
            if connection is None:
                conn.commit()
    except Exception as e:
        if connection is not None:
            raise
        print(f"  Warning: Could not complete sync run: {e}")
    finally:
        if connection is None:
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
    record_id: int = None,
    geometry_changed: Optional[bool] = None
):
    """Log a change to the changelog table."""
    if sync_run_id is None:
        return

    schema = DATABASE["schema"]

    old_fek = old_values.get('fek') if old_values else None
    new_fek = new_values.get('fek') if new_values else None

    if geometry_changed is None:
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
    except Exception as e:
        # A failed SQL statement aborts this PostgreSQL transaction. Continuing
        # would hide the failure and could report a rolled-back load as success.
        raise LoadError(f"Could not write change audit for {table_name}: {e}") from e


def load_geojson_with_tracking(
    geojson: Dict[str, Any],
    table_name: str,
    schema: str = None,
    srid: int = 2100,
    sync_run_id: int = None,
    *, connection=None
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

    Raises:
        SyncError for invalid input; LoadError if the entire data load rolls back.
    """
    if schema is None:
        schema = DATABASE["schema"]

    features = validate_features(geojson, require_unique_ids=True)
    stats = {'new': 0, 'updated': 0, 'deleted': 0, 'unchanged': 0, 'errors': 0, 'changes': []}

    if not features:
        print(f"  No features to load into {schema}.{table_name}")
        return stats

    conn = connection if connection is not None else get_connection()
    try:
        check_tracking_columns(conn, schema, table_name)

        columns = get_table_columns(conn, schema, table_name)
        if not columns:
            raise LoadError(f"Could not get columns for {schema}.{table_name}")

        with conn.cursor() as cur:
            # Get existing records with all their values
            col_list_select = ", ".join(columns)
            cur.execute(f'''
                SELECT id, objectid, {col_list_select}, ST_AsText(geom, 17) as geom_wkt,
                       ST_AsEWKB(geom) as geom_ewkb
                FROM {schema}."{table_name}"
                WHERE is_deleted = FALSE OR is_deleted IS NULL
            ''')

            existing = {}
            for row in cur.fetchall():
                record_id = row[0]
                objectid = row[1]
                values = dict(zip(columns, row[2:-2]))
                geom_wkt = row[-2]
                existing[objectid] = {
                    'id': record_id,
                    'values': values,
                    'geom_wkt': geom_wkt,
                    'geom_ewkb': row[-1],
                }

            # Compare once per batch, before any row is changed. Text length
            # cannot detect coordinate moves and is sensitive to formatting.
            incoming_wkts = {
                feature_objectid(f['properties']): geometry_to_wkt(f['geometry'])
                for f in features
            }
            geom_changes = geometry_changes(cur, [
                (oid, existing[oid]['geom_ewkb'], wkt)
                for oid, wkt in incoming_wkts.items() if oid in existing
            ], srid)

            incoming_objectids = set()
            now = datetime.now()

            for feature in features:
                props = feature.get("properties", {})

                objectid = feature_objectid(props)
                if objectid is not None:
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

                wkt = incoming_wkts[objectid]

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

                        geom_changed = geom_changes[objectid]

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
                                       record_id=old_record['id'], geometry_changed=geom_changed)
                        else:
                            stats['unchanged'] += 1

                except Exception as e:
                    raise LoadError(f"Error processing OBJECTID {objectid}: {e}") from e

            # Mark deleted records
            if incoming_objectids:
                placeholders_list = ",".join(["%s"] * len(incoming_objectids))
                cur.execute(f'''
                    SELECT id, objectid, {col_list_select}, ST_AsText(geom, 17) as geom_wkt
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
                        print(f"  DATA QUALITY WARNING: {col} was zeroed/nulled "
                              f"in {count}/{stats['updated']} updates ({pct:.0f}%) "
                              f"— possible API regression")

            stats['warnings'] = [
                f"{col}: {count}/{stats['updated']} zeroed ({count/stats['updated']*100:.0f}%)"
                for col, count in zero_counts.items()
                if stats['updated'] > 0 and count / stats['updated'] > 0.5
            ]

            _refresh_derived_catalog(cur, schema, table_name)
            if connection is None:
                conn.commit()

            print(f"  New: {stats['new']}, Updated: {stats['updated']}, Deleted: {stats['deleted']}, Unchanged: {stats['unchanged']}, Errors: {stats['errors']}")
            return stats

    except Exception as e:
        if connection is None:
            conn.rollback()
        raise LoadError(f"Load rolled back for {schema}.{table_name}: {e}") from e
    finally:
        if connection is None:
            conn.close()


def log_sync(
    table_name: str,
    service_name: str,
    layer_id: int,
    records_fetched: int,
    status: str,
    error_message: str = None,
    sync_started: datetime = None,
    sync_completed: datetime = None,
    *, connection=None
):
    """Log sync operation to sync_log table."""
    schema = DATABASE["schema"]
    conn = connection if connection is not None else get_connection()

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
            if connection is None:
                conn.commit()
    except Exception as e:
        if connection is not None:
            raise
        print(f"  Error logging sync: {e}")
    finally:
        if connection is None:
            conn.close()


# Tables with area_m2 that should always be recalculated from geometry
# (TEE API has proven unreliable for this derived column)
AREA_RECALC_TABLES = [
    'forest_maps',
    'forest_maps_posted_attica_2021',
    'forest_maps_posted_pelop_2022',
]


def post_sync_recalculate(table_name: str, schema: str = None, *, connection=None):
    """
    Recalculate derived columns after sync.
    Currently: area_m2 from geometry for forest map tables.
    """
    if schema is None:
        schema = DATABASE["schema"]

    if table_name not in AREA_RECALC_TABLES:
        return

    conn = connection if connection is not None else get_connection()
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
            if connection is None:
                conn.commit()
            if fixed > 0:
                print(f"  Post-sync: recalculated area_m2 for {fixed} records in {table_name}")
    except Exception as e:
        if connection is not None:
            raise
        if connection is None:
            conn.rollback()
        print(f"  Warning: post-sync area recalc failed for {table_name}: {e}")
    finally:
        if connection is None:
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
