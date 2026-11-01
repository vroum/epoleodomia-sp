#!/usr/bin/env python3
"""Download validated TEE GeoTIFFs with per-file catalog publication.

Use sync_launcher.py rasters for dedicated writer credentials. --dry-run only
reads the catalog; --raster-id and --limit bound controlled downloads.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import closing
from datetime import datetime
import math
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time

import psycopg2
import requests
from tqdm import tqdm

from settings import SETTINGS
from raster_paths import resolve_fek_path


# Resolve relative catalog paths against the same root as the API.
GEOREF_DIR = Path(SETTINGS.raster_base_path)
CHUNK_SIZE = 64 * 1024
REQUEST_TIMEOUT = 120
MAX_RETRIES = 3
RETRY_DELAY = 5


def get_db_connection(*, read_only=False):
    options = '-c lock_timeout=5000 -c statement_timeout=120000'
    if read_only:
        options += ' -c default_transaction_read_only=on'
    return psycopg2.connect(**SETTINGS.database.connection_kwargs(), options=options)


def require_rasterio():
    try:
        import rasterio
    except ImportError as exc:
        raise RuntimeError('rasterio is required; install requirements.txt before downloading') from exc
    return rasterio


def sanitize_fek_folder(fek):
    if not fek:
        return 'FEK_UNKNOWN'
    greek = 'ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ'
    latin = ['A','B','G','D','E','Z','H','TH','I','K','L','M','N','X','O','P','R','S','T','Y','F','CH','PS','O']
    mapping = dict(zip(greek, latin))
    mapping.update({g.lower(): l.lower() for g, l in zip(greek, latin)})
    mapping['ς'] = 's'
    result = ''.join(mapping.get(char, char) for char in fek)
    result = re.sub(r'[/\\:]', '_', result)
    return 'FEK_' + re.sub(r'[^a-zA-Z0-9_-]', '', result)


def raster_destination(raster, base_dir):
    """Reuse an existing flat file or the catalog's safe relative destination."""
    name = raster['filename']
    root = Path(base_dir).resolve()
    relative = raster.get('local_path_georef') or f"{sanitize_fek_folder(raster['fek'])}/{name}"
    destination = resolve_fek_path(root, name, relative)
    return destination, destination.relative_to(root).as_posix()


def get_pending_rasters(conn, fek_filter=None, include_downloaded=False, *, raster_id=None, limit=None):
    statuses = ['pending', 'failed'] + (['downloaded'] if include_downloaded else [])
    query = '''SELECT id,fek,filename,url_georef,url_raw,download_status,local_path_georef
               FROM epoleodomia.raster_catalog WHERE download_status = ANY(%s)'''
    params = [statuses]
    if fek_filter:
        query += ' AND fek = %s'
        params.append(fek_filter)
    if raster_id is not None:
        query += ' AND id = %s'
        params.append(raster_id)
    query += ' ORDER BY fek,filename,id'
    if limit is not None:
        query += ' LIMIT %s'
        params.append(limit)
    with conn.cursor() as cursor:
        cursor.execute(query, params)
        columns = ['id','fek','filename','url_georef','url_raw','download_status','local_path_georef']
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


def extract_raster_metadata(tif_path):
    """Decode every pixel block; reject invalid CRS/orientation before publication."""
    rasterio = require_rasterio()
    from rasterio.windows import Window
    with rasterio.open(tif_path) as src:
        if src.driver != 'GTiff' or min(src.width, src.height, src.count) < 1:
            raise ValueError('Expected a nonempty GeoTIFF')
        if src.crs is None or src.crs.to_epsg() != 2100:
            raise ValueError('GeoTIFF must declare EPSG:2100')
        transform = src.transform
        if (not all(math.isfinite(v) for v in transform[:6])
                or transform.b != 0 or transform.d != 0 or transform.a <= 0 or transform.e >= 0):
            raise ValueError('GeoTIFF must be north-up without rotation or shear')
        bounds = src.bounds
        if (not all(math.isfinite(v) for v in bounds)
                or bounds.left >= bounds.right or bounds.bottom >= bounds.top):
            raise ValueError('GeoTIFF has invalid bounds')
        # Header reads alone do not detect truncated pixel data. Bound memory
        # regardless of the source's strip/tile dimensions.
        for band in range(1, src.count + 1):
            for row in range(0, src.height, 512):
                for col in range(0, src.width, 512):
                    src.read(band, window=Window(col, row, min(512, src.width-col), min(512, src.height-row)))
        return {
            'width_px': src.width, 'height_px': src.height, 'bands': src.count,
            'resolution_x': transform.a, 'resolution_y': -transform.e,
            'crs_epsg': 2100, 'nodata_value': src.nodata,
            'bbox_wkt': (f'POLYGON(({bounds.left} {bounds.bottom}, '
                         f'{bounds.right} {bounds.bottom}, {bounds.right} {bounds.top}, '
                         f'{bounds.left} {bounds.top}, {bounds.left} {bounds.bottom}))'),
        }


def download_file(url, local_path, timeout=REQUEST_TIMEOUT):
    """Return a validated temporary file; never overwrite the published file."""
    result = {'success': False, 'file_size': 0, 'error': None}
    for attempt in range(MAX_RETRIES):
        staged = None
        try:
            local_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=local_path.parent, prefix='.epol-', suffix='.part', delete=False) as stream:
                staged = Path(stream.name)
                with requests.get(url, stream=True, timeout=timeout, headers={'Accept-Encoding':'identity'}) as response:
                    response.raise_for_status()
                    if response.status_code != 200:
                        raise ValueError(f'Expected HTTP 200, received {response.status_code}')
                    size = 0
                    for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                        if chunk:
                            stream.write(chunk)
                            size += len(chunk)
                    declared = response.headers.get('Content-Length')
                    encoding = response.headers.get('Content-Encoding', 'identity').lower()
                    if declared is not None and encoding in ('', 'identity') and size != int(declared):
                        raise ValueError(f'Incomplete download: expected {declared} bytes, received {size}')
                    if size == 0:
                        raise ValueError('Empty download')
                stream.flush()
                os.fsync(stream.fileno())
            metadata = extract_raster_metadata(staged)
            return dict(result, success=True, file_size=size, staged_path=staged, metadata=metadata)
        except Exception as exc:
            result['error'] = str(exc)
            if staged is not None:
                staged.unlink(missing_ok=True)
            if isinstance(exc, requests.HTTPError) and exc.response is not None and exc.response.status_code == 404:
                break
            if isinstance(exc, (ValueError, RuntimeError)):
                break
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
    return result


def _source_guard(raster):
    if raster is None:
        return '', []
    return (' AND url_georef IS NOT DISTINCT FROM %s AND filename = %s AND fek IS NOT DISTINCT FROM %s',
            [raster['url_georef'], raster['filename'], raster['fek']])


def update_catalog_downloaded(conn, raster_id, local_path, file_size, metadata, *, commit=True, source=None):
    """Update only technical/download columns; preserve human quality judgements."""
    assignments = ["download_status = 'downloaded'", 'local_path_georef = %s',
                   'file_size_bytes = %s', 'downloaded_at = NOW()', 'last_checked = NOW()',
                   'download_error = NULL', 'updated_at = NOW()']
    params = [local_path, file_size]
    for column in ('width_px','height_px','bands','resolution_x','resolution_y','crs_epsg','nodata_value'):
        if column in metadata:
            assignments.append(f'{column} = %s')
            params.append(metadata[column])
    if metadata.get('bbox_wkt'):
        assignments.append('bbox = ST_GeomFromText(%s,2100)')
        params.append(metadata['bbox_wkt'])
    guard, values = _source_guard(source)
    with conn.cursor() as cursor:
        cursor.execute(f"UPDATE epoleodomia.raster_catalog SET {', '.join(assignments)} WHERE id = %s" + guard,
                       params + [raster_id] + values)
        if cursor.rowcount != 1:
            raise ValueError('Raster catalog source changed or row disappeared; download was not published')
    if commit:
        conn.commit()


def update_catalog_failed(conn, raster_id, error, *, source=None):
    # A failed forced refresh must not hide a previously published raster.
    guard, values = _source_guard(source)
    with conn.cursor() as cursor:
        cursor.execute('''UPDATE epoleodomia.raster_catalog
            SET download_status = CASE WHEN download_status = 'downloaded' THEN 'downloaded' ELSE 'failed' END,
                download_error = %s, last_checked = NOW(), updated_at = NOW()
            WHERE id = %s''' + guard, [error, raster_id] + values)
    conn.commit()


def download_raster_worker(raster, base_dir):
    """Network/files only: no connection or transaction is shared by threads."""
    result = {key: raster[key] for key in ('id','fek','filename')}
    result.update(success=False, file_size=0, error=None)
    try:
        destination, relative = raster_destination(raster, base_dir)
        if not raster['url_georef']:
            raise ValueError('No georeferenced URL available')
        result.update(download_file(raster['url_georef'], destination))
        result.update(local_path=str(destination), relative_path=relative)
    except Exception as exc:
        result.update(success=False, error=str(exc))
    return result


def publish_download(conn, raster, result):
    """Publish on the main thread; restore the previous file on transaction failure.

    Filesystem/PostgreSQL cannot share a crash-atomic commit. A crash between
    replacement and commit can leave valid new bytes with old catalog metadata;
    repeating that bounded download reconciles it. Retain the backup if its
    restoration fails instead of discarding the last good copy.
    """
    staged = result['staged_path']
    destination = Path(result['local_path'])
    backup = None
    published = False
    try:
        with conn:
            update_catalog_downloaded(conn, raster['id'], result['relative_path'], result['file_size'],
                                      result['metadata'], commit=False, source=raster)
            # The UPDATE above locks/verifies this source row before replacing
            # its file; a concurrent publication of the same row waits here.
            if destination.exists():
                with tempfile.NamedTemporaryFile(dir=destination.parent, prefix='.epol-', suffix='.previous', delete=False) as stream:
                    backup = Path(stream.name)
                shutil.copyfile(destination, backup)
            os.replace(staged, destination)
            published = True
    except BaseException:
        if published:
            if backup is not None:
                try:
                    os.replace(backup, destination)
                except OSError as exc:
                    raise RuntimeError(f'Could not restore raster; previous file retained at {backup}') from exc
                backup = None
            else:
                destination.unlink(missing_ok=True)
        raise
    finally:
        staged.unlink(missing_ok=True)
        if backup is not None and not published:
            backup.unlink(missing_ok=True)
    if backup is not None:
        backup.unlink(missing_ok=True)


def sync_rasters(fek_filter=None, force=False, include_raw=False, parallel=4, dry_run=False, *,
                 raster_id=None, limit=None, repair_missing=False):
    if include_raw:
        raise ValueError('--include-raw is unsupported; raw scans were never downloaded by this command')
    for name, number in (('parallel', parallel), ('limit', limit), ('raster_id', raster_id)):
        if number is not None and (isinstance(number, bool) or not isinstance(number, int) or number < 1):
            raise ValueError(f'{name} must be a positive integer')
    with closing(get_db_connection(read_only=True)) as conn:
        rasters = get_pending_rasters(conn, fek_filter, include_downloaded=force or repair_missing,
                                     raster_id=raster_id, limit=None if repair_missing and not force else limit)
    if repair_missing and not force:
        rasters = [r for r in rasters if r['download_status'] != 'downloaded'
                   or not raster_destination(r, GEOREF_DIR)[0].is_file()]
        if limit is not None:
            rasters = rasters[:limit]
    results = {'total': len(rasters), 'downloaded': 0, 'failed': 0, 'skipped': 0, 'total_bytes': 0, 'errors': []}
    if not rasters:
        print('No rasters to download.')
        return results
    destinations = [str(raster_destination(r, GEOREF_DIR)[0]).casefold() for r in rasters]
    if len(set(destinations)) != len(destinations):
        raise ValueError('Multiple catalog rows resolve to the same raster destination')
    print(f'Found {len(rasters)} raster(s); destination: {GEOREF_DIR}')
    if dry_run:
        for raster, destination in zip(rasters, destinations):
            print(f"[DRY RUN] id={raster['id']} {destination}")
        return results
    require_rasterio()
    # Only this thread writes. Roll back each failed transaction before recording
    # the error, so one failed file cannot poison another file's publication.
    futures = {}
    try:
        with closing(get_db_connection()) as conn, ThreadPoolExecutor(max_workers=parallel) as executor:
            futures = {executor.submit(download_raster_worker, r, GEOREF_DIR): r for r in rasters}
            with tqdm(total=len(rasters), desc='Downloading', unit='file') as progress:
                for future in as_completed(futures):
                    raster = futures[future]
                    try:
                        result = future.result()
                        if not result['success']:
                            raise ValueError(result['error'])
                        publish_download(conn, raster, result)
                    except Exception as exc:
                        conn.rollback()
                        error = str(exc)
                        try:
                            update_catalog_failed(conn, raster['id'], error, source=raster)
                        except Exception as audit_error:
                            conn.rollback()
                            error += f'; could not record download failure: {audit_error}'
                        results['failed'] += 1
                        results['errors'].append({'id': raster['id'], 'filename': raster['filename'], 'error': error})
                    else:
                        results['downloaded'] += 1
                        results['total_bytes'] += result['file_size']
                    progress.update(1)
    finally:
        # Executor shutdown has joined the workers, including on interruption or
        # connection loss. Remove validated files that never reached publication.
        for future in futures:
            try:
                staged = future.result().get('staged_path')
            except BaseException:
                continue
            if staged is not None:
                try:
                    staged.unlink(missing_ok=True)
                except OSError as exc:
                    print(f'Could not remove staged download {staged}: {exc}', file=sys.stderr)
    print(f"Downloaded: {results['downloaded']}; failed: {results['failed']}; size: {results['total_bytes']/1024/1024:.2f} MB")
    for error in results['errors']:
        print(f"  id={error['id']} {error['filename']}: {error['error']}")
    return results


def main():
    parser = argparse.ArgumentParser(description='Download and validate TEE EPSG:2100 planning GeoTIFFs')
    parser.add_argument('--fek', help='Download only this FEK')
    parser.add_argument('--force', action='store_true', help='Refresh already downloaded files too')
    parser.add_argument('--repair-missing', action='store_true',
                        help='Include downloaded rows whose local TIFF is missing; --force overrides this filter')
    parser.add_argument('--include-raw', action='store_true', help='Unsupported legacy option (fails explicitly)')
    parser.add_argument('--parallel', type=int, default=4)
    parser.add_argument('--limit', type=int, help='Process at most this many catalog rows')
    parser.add_argument('--raster-id', type=int, help='Process only this catalog ID')
    parser.add_argument('--dry-run', action='store_true', help='Read-only preview; creates no directories or files')
    args = parser.parse_args()
    print(f"TEE RASTER DOWNLOAD - {datetime.now():%Y-%m-%d %H:%M:%S}")
    try:
        results = sync_rasters(fek_filter=args.fek, force=args.force, include_raw=args.include_raw,
                               parallel=args.parallel, dry_run=args.dry_run, raster_id=args.raster_id,
                               limit=args.limit, repair_missing=args.repair_missing)
    except Exception as exc:
        print(f'Raster sync failed: {exc}', file=sys.stderr)
        return 1
    return 1 if results['failed'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
