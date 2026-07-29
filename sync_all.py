"""
Main synchronization script for TEE ArcGIS data to PostGIS

Usage:
    python sync_all.py                    # Sync all layers
    python sync_all.py --service SERVICE  # Sync specific service
    python sync_all.py --table TABLE      # Sync specific table
    python sync_all.py --init             # Initialize database (run DDL)
    python sync_all.py --test             # Test with one layer only
    python sync_all.py --rasters          # Also download raster diagrams
    python sync_all.py --rasters-only     # Only sync rasters
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from config import SERVICES, DATABASE
from fetch_layer import fetch_all_layer_data, fetch_layer_count
from load_postgis import (load_geojson_to_table, load_geojson_with_tracking,
                          log_sync, execute_sql_file, get_connection,
                          start_sync_run, complete_sync_run,
                          post_sync_recalculate)
from logger import SyncLogger


REPLACE_ONLY_TABLES = {
    # TEE Layer 17 can return two meaningful rows with the same OBJECTID:
    # one "ΚΑΤΑ ΚΑΝΟΝΑ" and one "ΚΑΤΑ ΠΑΡΕΚΚΛΙΣΗ". ObjectID-only tracking
    # collapses those rows, so keep this tiny table as full replace.
    "building_regs_lot",
}

# Content hashes of REPLACE_ONLY tables from the previous sync, so a full
# replace with identical content reports as "unchanged" instead of "N new".
_HASH_FILE = Path(__file__).parent / "logs" / "replace_hashes.json"


def _replace_content_hash(geojson) -> str:
    """Order-independent MD5 of a GeoJSON FeatureCollection's features."""
    feats = geojson.get("features", [])
    parts = sorted(json.dumps(f, sort_keys=True, default=str) for f in feats)
    return hashlib.md5("|".join(parts).encode("utf-8")).hexdigest()


def _load_replace_hashes() -> dict:
    try:
        with open(_HASH_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_replace_hash(table_name: str, content_hash: str):
    hashes = _load_replace_hashes()
    hashes[table_name] = content_hash
    try:
        _HASH_FILE.parent.mkdir(exist_ok=True)
        with open(_HASH_FILE, "w", encoding="utf-8") as f:
            json.dump(hashes, f, indent=2)
    except OSError as e:
        print(f"  Warning: could not save replace hash: {e}")


def init_database():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    ddl_path = os.path.join(script_dir, "sql", "001_create_tables.sql")
    if not os.path.exists(ddl_path):
        print(f"Error: DDL script not found at {ddl_path}")
        return False
    print("Initializing database...")
    return execute_sql_file(ddl_path)


def sync_layer(service_name, service_url, layer_config, dry_run=False, track_changes=False, sync_run_id=None, logger=None):
    layer_id = layer_config["id"]
    table_name = layer_config["table"]

    print(f"\n{'='*60}")
    print(f"Syncing: {table_name} (Layer {layer_id})")
    print(f"Service: {service_name}")
    print(f"{'='*60}")

    sync_started = datetime.now()

    try:
        if dry_run:
            count = fetch_layer_count(service_url, layer_id)
            print(f"  Feature count: {count}")
            return {'success': True, 'stats': {}, 'status': 'dry_run'}

        print("  Fetching data from ArcGIS...")
        geojson = fetch_all_layer_data(service_url, layer_id)
        feature_count = len(geojson.get("features", []))

        if feature_count == 0:
            print(f"  No features found in Spetses area")
            log_sync(table_name=table_name, service_name=service_name, layer_id=layer_id,
                     records_fetched=0, status="empty", sync_started=sync_started, sync_completed=datetime.now())
            if logger:
                logger.log_table_result(table_name, layer_id,
                    stats={'new':0,'updated':0,'deleted':0,'unchanged':0,'errors':0}, fetched=0, status='empty')
            return {'success': True, 'stats': {}, 'status': 'empty'}

        print(f"  Loading {feature_count} features to PostGIS...")
        if track_changes and table_name not in REPLACE_ONLY_TABLES:
            stats = load_geojson_with_tracking(geojson, table_name, sync_run_id=sync_run_id)
            inserted = stats['new'] + stats['updated']
            changes = stats.get('changes', [])
        else:
            is_replace_only = table_name in REPLACE_ONLY_TABLES
            content_hash = prev_hash = None
            if track_changes and is_replace_only:
                print("  Using full replace for this table (OBJECTID is not unique in source)")
                content_hash = _replace_content_hash(geojson)
                prev_hash = _load_replace_hashes().get(table_name)
            inserted = load_geojson_to_table(geojson, table_name)
            if content_hash and content_hash == prev_hash:
                # Same content as last sync — replaced, but nothing changed
                print("  Content identical to previous sync — reporting as unchanged")
                stats = {'new': 0, 'updated': 0, 'deleted': 0, 'unchanged': inserted, 'errors': 0}
            else:
                stats = {'new': inserted, 'updated': 0, 'deleted': 0, 'unchanged': 0, 'errors': 0}
            if content_hash:
                _save_replace_hash(table_name, content_hash)
            changes = []

        sync_completed = datetime.now()
        duration = (sync_completed - sync_started).total_seconds()
        print(f"  Completed in {duration:.1f} seconds")

        # Post-sync: recalculate derived columns (e.g. area_m2 for forest tables)
        post_sync_recalculate(table_name)

        log_sync(table_name=table_name, service_name=service_name, layer_id=layer_id,
                 records_fetched=inserted, status="success", sync_started=sync_started, sync_completed=sync_completed)
        if logger:
            logger.log_table_result(table_name, layer_id, stats=stats, changes=changes,
                                    duration_sec=duration, fetched=feature_count, status='success')

        return {'success': True, 'stats': stats, 'status': 'success'}

    except Exception as e:
        print(f"  Error: {e}")
        log_sync(table_name=table_name, service_name=service_name, layer_id=layer_id,
                 records_fetched=0, status="error", error_message=str(e),
                 sync_started=sync_started, sync_completed=datetime.now())
        if logger:
            logger.log_error(str(e), table_name)
        return {'success': False, 'stats': {}, 'status': 'error', 'error': str(e)}


def sync_service(service_name, dry_run=False, track_changes=False, sync_run_id=None, logger=None):
    if service_name not in SERVICES:
        print(f"Error: Unknown service '{service_name}'")
        return {"success": 0, "failed": 0, "empty": 0}
    service = SERVICES[service_name]
    results = {"success": 0, "failed": 0, "empty": 0}
    if logger: logger.log_service_start(service_name)
    for layer_config in service["layers"]:
        result = sync_layer(service_name, service["url"], layer_config, dry_run, track_changes, sync_run_id, logger)
        if result['success']:
            if result['status'] == 'empty': results["empty"] += 1
            results["success"] += 1
        else:
            results["failed"] += 1
    return results


def sync_table(table_name, dry_run=False, track_changes=False, sync_run_id=None, logger=None):
    for service_name, service in SERVICES.items():
        for layer_config in service["layers"]:
            if layer_config["table"] == table_name:
                if logger: logger.log_service_start(service_name)
                result = sync_layer(service_name, service["url"], layer_config, dry_run, track_changes, sync_run_id, logger)
                return result['success']
    print(f"Error: Table '{table_name}' not found in configuration")
    return False


def sync_all(dry_run=False, track_changes=False, sync_run_id=None, logger=None):
    total = {"success": 0, "failed": 0, "empty": 0}
    for service_name in SERVICES:
        print(f"\n{'#'*60}\n# SERVICE: {service_name}\n{'#'*60}")
        results = sync_service(service_name, dry_run, track_changes, sync_run_id, logger)
        for k in total: total[k] += results[k]
    return total


def print_summary(results):
    print(f"\n{'='*60}\nSYNC SUMMARY\n{'='*60}")
    print(f"  Successful: {results['success']}\n  Failed:     {results['failed']}\n  Empty:      {results.get('empty', 0)}")
    print("="*60)


def test_connection():
    print("Testing database connection...")
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT PostGIS_Version()")
            print(f"  Connected! PostGIS version: {cur.fetchone()[0]}")
            cur.execute("SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name = %s", (DATABASE["schema"],))
            if cur.fetchone()[0] > 0:
                print(f"  Schema '{DATABASE['schema']}' exists")
            else:
                print(f"  Warning: Schema '{DATABASE['schema']}' does not exist\n  Run with --init to create tables")
        conn.close()
        return True
    except Exception as e:
        print(f"  Connection error: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Sync TEE ArcGIS data to PostGIS")
    parser.add_argument("--init", action="store_true", help="Initialize database (create tables)")
    parser.add_argument("--service", type=str, help="Sync specific service only")
    parser.add_argument("--table", type=str, help="Sync specific table only")
    parser.add_argument("--test", action="store_true", help="Test mode: sync building_blocks only")
    parser.add_argument("--dry-run", action="store_true", help="Only fetch counts, don't load data")
    parser.add_argument("--track", action="store_true", help="Track changes: upsert instead of truncate")
    parser.add_argument("--list", action="store_true", help="List all available services and tables")
    parser.add_argument("--no-log", action="store_true", help="Disable local log file generation")
    parser.add_argument("--log-dir", type=str, help="Custom directory for log files")
    parser.add_argument("--rasters", action="store_true", help="Also download raster diagrams")
    parser.add_argument("--rasters-only", action="store_true", help="Only sync raster diagrams")
    parser.add_argument("--rasters-parallel", type=int, default=4, help="Parallel raster downloads (default: 4)")
    args = parser.parse_args()

    print(f"{'='*60}\nTEE ArcGIS to PostGIS Sync\nStarted at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n{'='*60}")

    if args.list:
        print("\nAvailable services and tables:")
        for sn, sv in SERVICES.items():
            print(f"\n{sn}:")
            for l in sv["layers"]: print(f"  - {l['table']} (layer {l['id']}, {l['geom_type']})")
        return

    if args.rasters_only:
        print("\nRasters-only mode...")
        try:
            from download_rasters import sync_rasters
            rr = sync_rasters(parallel=args.rasters_parallel, dry_run=args.dry_run)
            print(f"\nRasters: {rr['downloaded']} downloaded, {rr['failed']} failed")
            sys.exit(0 if rr['failed'] == 0 else 1)
        except Exception as e:
            print(f"\nRaster sync error: {e}"); sys.exit(1)

    if not test_connection():
        print("\nFailed to connect. Check configuration."); sys.exit(1)

    if args.init:
        sys.exit(0 if init_database() else 1)

    sync_run_id = None
    mode = 'table' if args.table else ('service' if args.service else ('test' if args.test else 'full'))
    if args.track and not args.dry_run:
        sync_run_id = start_sync_run(mode)
        if sync_run_id: print(f"\nSync run #{sync_run_id} started (changelog enabled)")
        else: print("\nNote: Changelog not set up — run sql/004_create_changelog.sql first")

    logger = None
    if not args.no_log and not args.dry_run:
        logger = SyncLogger(mode=mode, sync_run_id=sync_run_id, log_dir=args.log_dir, enabled=True)
        logger.log_start()
        print(f"\nLog files: {logger.log_file}")

    total_stats = {'new': 0, 'updated': 0, 'deleted': 0}

    try:
        if args.test:
            print("\nTest mode: syncing building_blocks only")
            success = sync_table("building_blocks", args.dry_run, args.track, sync_run_id, logger)
            if sync_run_id: complete_sync_run(sync_run_id, total_stats, 'success' if success else 'error')
            if logger: logger.log_complete('success' if success else 'error')
            sys.exit(0 if success else 1)

        if args.table:
            success = sync_table(args.table, args.dry_run, args.track, sync_run_id, logger)
            if sync_run_id: complete_sync_run(sync_run_id, total_stats, 'success' if success else 'error')
            if logger: logger.log_complete('success' if success else 'error')
            sys.exit(0 if success else 1)

        if args.service:
            results = sync_service(args.service, args.dry_run, args.track, sync_run_id, logger)
            print_summary(results)
            if sync_run_id: complete_sync_run(sync_run_id, total_stats, 'success' if results["failed"]==0 else 'error')
            if logger: logger.log_complete('success' if results["failed"]==0 else 'error')
            sys.exit(0 if results["failed"]==0 else 1)

        results = sync_all(args.dry_run, args.track, sync_run_id, logger)
        if sync_run_id: complete_sync_run(sync_run_id, total_stats, 'success' if results["failed"]==0 else 'error')
        if logger: logger.log_complete('success' if results["failed"]==0 else 'error')
        print_summary(results)

    except Exception as e:
        if logger: logger.log_complete('error', str(e))
        raise

    raster_results = None
    if args.rasters:
        print(f"\n{'#'*60}\n# RASTER SYNC\n{'#'*60}")
        try:
            from download_rasters import sync_rasters
            raster_results = sync_rasters(parallel=args.rasters_parallel, dry_run=args.dry_run)
            print(f"\nRasters: {raster_results['downloaded']} downloaded, {raster_results['failed']} failed")
            if logger and raster_results:
                # Regenerate the digest so it includes the raster results
                logger.write_changes_digest(raster_results)
        except Exception as e:
            print(f"\nRaster sync error: {e}")

    print(f"\nCompleted at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    exit_code = 0
    if results["failed"] > 0: exit_code = 1
    if raster_results and raster_results.get('failed', 0) > 0: exit_code = 1
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
