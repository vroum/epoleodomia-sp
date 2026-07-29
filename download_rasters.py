#!/usr/bin/env python3
"""
TEE Epoleodomia Raster Download Script
Downloads georeferenced planning diagram TIF files from TEE servers

Usage:
    python download_rasters.py              # Download all pending rasters
    python download_rasters.py --dry-run    # Show what would be downloaded
    python download_rasters.py --fek "1385Δ/1992"  # Download specific FEK only
    python download_rasters.py --force      # Re-download existing files
    python download_rasters.py --include-raw  # Also download raw scans
"""

import argparse
import os
import re
import sys
import time
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Any
from urllib.parse import urlparse, unquote

import psycopg2
import requests
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).parent))
from config import DATABASE

# Constants
RASTERS_DIR = Path(__file__).parent / "rasters"
GEOREF_DIR = RASTERS_DIR / "georef"
RAW_DIR = RASTERS_DIR / "raw"

CHUNK_SIZE = 8192
REQUEST_TIMEOUT = 120
MAX_RETRIES = 3
RETRY_DELAY = 5


def get_db_connection():
    """Create database connection."""
    return psycopg2.connect(
        host=DATABASE["host"],
        port=DATABASE["port"],
        database=DATABASE["database"],
        user=DATABASE["user"],
        password=DATABASE["password"],
    )


def sanitize_fek_folder(fek: str) -> str:
    if not fek:
        return "FEK_UNKNOWN"
    greek_to_latin = {
        'Α': 'A', 'Β': 'B', 'Γ': 'G', 'Δ': 'D', 'Ε': 'E',
        'Ζ': 'Z', 'Η': 'H', 'Θ': 'TH', 'Ι': 'I', 'Κ': 'K',
        'Λ': 'L', 'Μ': 'M', 'Ν': 'N', 'Ξ': 'X', 'Ο': 'O',
        'Π': 'P', 'Ρ': 'R', 'Σ': 'S', 'Τ': 'T', 'Υ': 'Y',
        'Φ': 'F', 'Χ': 'CH', 'Ψ': 'PS', 'Ω': 'O',
        'α': 'a', 'β': 'b', 'γ': 'g', 'δ': 'd', 'ε': 'e',
        'ζ': 'z', 'η': 'h', 'θ': 'th', 'ι': 'i', 'κ': 'k',
        'λ': 'l', 'μ': 'm', 'ν': 'n', 'ξ': 'x', 'ο': 'o',
        'π': 'p', 'ρ': 'r', 'σ': 's', 'ς': 's', 'τ': 't',
        'υ': 'y', 'φ': 'f', 'χ': 'ch', 'ψ': 'ps', 'ω': 'o'
    }
    result = ""
    for char in fek:
        result += greek_to_latin.get(char, char)
    result = re.sub(r'[/\\:]', '_', result)
    result = re.sub(r'[^a-zA-Z0-9_-]', '', result)
    return f"FEK_{result}"


def get_pending_rasters(conn, fek_filter=None, include_downloaded=False):
    cursor = conn.cursor()
    status_filter = "('pending', 'failed', 'downloaded')" if include_downloaded else "('pending', 'failed')"
    query = f"""
        SELECT id, fek, filename, url_georef, url_raw, download_status, local_path_georef
        FROM epoleodomia.raster_catalog
        WHERE download_status IN {status_filter}
    """
    params = []
    if fek_filter:
        query += " AND fek = %s"
        params.append(fek_filter)
    query += " ORDER BY fek, filename"
    cursor.execute(query, params)
    columns = ['id', 'fek', 'filename', 'url_georef', 'url_raw', 'download_status', 'local_path_georef']
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def download_file(url, local_path, timeout=REQUEST_TIMEOUT):
    result = {'success': False, 'file_size': 0, 'error': None}
    for attempt in range(MAX_RETRIES):
        try:
            local_path.parent.mkdir(parents=True, exist_ok=True)
            response = requests.get(url, stream=True, timeout=timeout)
            response.raise_for_status()
            with open(local_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                    if chunk:
                        f.write(chunk)
            if local_path.exists():
                result['success'] = True
                result['file_size'] = local_path.stat().st_size
                return result
            else:
                result['error'] = "File not created after download"
        except requests.exceptions.Timeout:
            result['error'] = f"Timeout after {timeout}s"
        except requests.exceptions.HTTPError as e:
            result['error'] = f"HTTP {e.response.status_code}: {e.response.reason}"
            if e.response.status_code == 404:
                return result
        except requests.exceptions.RequestException as e:
            result['error'] = str(e)
        except Exception as e:
            result['error'] = f"Unexpected error: {str(e)}"
        if attempt < MAX_RETRIES - 1:
            time.sleep(RETRY_DELAY)
    return result


def extract_raster_metadata(tif_path):
    metadata = {}
    try:
        import rasterio
        with rasterio.open(tif_path) as src:
            metadata['width_px'] = src.width
            metadata['height_px'] = src.height
            metadata['bands'] = src.count
            metadata['resolution_x'] = abs(src.transform[0])
            metadata['resolution_y'] = abs(src.transform[4])
            if src.crs:
                try:
                    metadata['crs_epsg'] = src.crs.to_epsg()
                except:
                    metadata['crs_epsg'] = None
            metadata['nodata_value'] = src.nodata
            bounds = src.bounds
            metadata['bbox_wkt'] = (
                f"POLYGON(({bounds.left} {bounds.bottom}, "
                f"{bounds.right} {bounds.bottom}, "
                f"{bounds.right} {bounds.top}, "
                f"{bounds.left} {bounds.top}, "
                f"{bounds.left} {bounds.bottom}))"
            )
    except ImportError:
        pass
    except Exception as e:
        print(f"Warning: Could not extract metadata from {tif_path}: {e}")
    return metadata


def update_catalog_downloaded(conn, raster_id, local_path, file_size, metadata):
    cursor = conn.cursor()
    set_parts = [
        "download_status = 'downloaded'", "local_path_georef = %s",
        "file_size_bytes = %s", "downloaded_at = NOW()", "last_checked = NOW()",
        "download_error = NULL", "updated_at = NOW()"
    ]
    params = [local_path, file_size]
    for key, col in [('width_px','width_px'), ('height_px','height_px'), ('bands','bands'),
                     ('resolution_x','resolution_x'), ('resolution_y','resolution_y'),
                     ('crs_epsg','crs_epsg')]:
        if metadata.get(key):
            set_parts.append(f"{col} = %s")
            params.append(metadata[key])
    if metadata.get('nodata_value') is not None:
        set_parts.append("nodata_value = %s")
        params.append(metadata['nodata_value'])
    if metadata.get('bbox_wkt'):
        set_parts.append("bbox = ST_GeomFromText(%s, 2100)")
        params.append(metadata['bbox_wkt'])
    params.append(raster_id)
    cursor.execute(f"UPDATE epoleodomia.raster_catalog SET {', '.join(set_parts)} WHERE id = %s", params)
    conn.commit()


def update_catalog_failed(conn, raster_id, error):
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE epoleodomia.raster_catalog
        SET download_status = 'failed', download_error = %s, last_checked = NOW(), updated_at = NOW()
        WHERE id = %s
    """, (error, raster_id))
    conn.commit()


def download_raster_worker(raster, base_dir, conn):
    result = {'id': raster['id'], 'fek': raster['fek'], 'filename': raster['filename'],
              'success': False, 'file_size': 0, 'error': None}
    url = raster['url_georef']
    if not url:
        result['error'] = "No URL available"
        return result
    fek_folder = sanitize_fek_folder(raster['fek'])
    local_path = base_dir / fek_folder / raster['filename']
    relative_path = f"{fek_folder}/{raster['filename']}"
    dl_result = download_file(url, local_path)
    if dl_result['success']:
        result['success'] = True
        result['file_size'] = dl_result['file_size']
        result['local_path'] = str(local_path)
        metadata = extract_raster_metadata(local_path)
        update_catalog_downloaded(conn, raster['id'], relative_path, dl_result['file_size'], metadata)
    else:
        result['error'] = dl_result['error']
        update_catalog_failed(conn, raster['id'], dl_result['error'])
    return result


def sync_rasters(fek_filter=None, force=False, include_raw=False, parallel=4, dry_run=False):
    GEOREF_DIR.mkdir(parents=True, exist_ok=True)
    if include_raw:
        RAW_DIR.mkdir(parents=True, exist_ok=True)
    conn = get_db_connection()
    try:
        rasters = get_pending_rasters(conn, fek_filter, include_downloaded=force)
        if not rasters:
            print("No rasters to download.")
            return {'total': 0, 'downloaded': 0, 'failed': 0, 'skipped': 0}
        print(f"\nFound {len(rasters)} raster(s) to download")
        if dry_run:
            print("\n[DRY RUN] Would download:")
            for r in rasters:
                print(f"  - {sanitize_fek_folder(r['fek'])}/{r['filename']}")
                print(f"    URL: {r['url_georef']}")
            return {'total': len(rasters), 'downloaded': 0, 'failed': 0, 'skipped': 0}
        results = {'total': len(rasters), 'downloaded': 0, 'failed': 0, 'skipped': 0,
                   'total_bytes': 0, 'errors': []}
        print(f"\nDownloading to: {GEOREF_DIR}")
        print(f"Parallel downloads: {parallel}\n")
        with tqdm(total=len(rasters), desc="Downloading", unit="file") as pbar:
            if parallel > 1:
                with ThreadPoolExecutor(max_workers=parallel) as executor:
                    futures = {executor.submit(download_raster_worker, r, GEOREF_DIR, conn): r for r in rasters}
                    for future in as_completed(futures):
                        result = future.result()
                        if result['success']:
                            results['downloaded'] += 1
                            results['total_bytes'] += result['file_size']
                        else:
                            results['failed'] += 1
                            results['errors'].append({'filename': result['filename'], 'error': result['error']})
                        pbar.update(1)
            else:
                for raster in rasters:
                    result = download_raster_worker(raster, GEOREF_DIR, conn)
                    if result['success']:
                        results['downloaded'] += 1
                        results['total_bytes'] += result['file_size']
                    else:
                        results['failed'] += 1
                        results['errors'].append({'filename': result['filename'], 'error': result['error']})
                    pbar.update(1)
        print(f"\n{'='*60}")
        print("DOWNLOAD SUMMARY")
        print(f"{'='*60}")
        print(f"Total rasters:    {results['total']}")
        print(f"Downloaded:       {results['downloaded']}")
        print(f"Failed:           {results['failed']}")
        print(f"Total size:       {results['total_bytes'] / 1024 / 1024:.2f} MB")
        if results['errors']:
            print(f"\nFailed downloads:")
            for err in results['errors'][:10]:
                print(f"  - {err['filename']}: {err['error']}")
            if len(results['errors']) > 10:
                print(f"  ... and {len(results['errors']) - 10} more")
        print(f"{'='*60}")
        return results
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Download TEE planning diagram rasters")
    parser.add_argument('--fek', type=str, help='Download only rasters for this FEK')
    parser.add_argument('--force', action='store_true', help='Re-download existing files')
    parser.add_argument('--include-raw', action='store_true', help='Also download raw scans')
    parser.add_argument('--parallel', type=int, default=4, help='Number of parallel downloads (default: 4)')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be downloaded')
    args = parser.parse_args()

    print("="*60)
    print("TEE RASTER DOWNLOAD")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)

    results = sync_rasters(fek_filter=args.fek, force=args.force, include_raw=args.include_raw,
                           parallel=args.parallel, dry_run=args.dry_run)
    if results['failed'] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
