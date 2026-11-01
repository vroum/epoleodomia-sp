"""Versioned TEE raster archive on NAS and verified local restoration.

Default is a read-only preview. Objects are immutable SHA-256 addressed TIFFs;
only a completed manifest becomes latest.json. Pull never overwrites local
bytes, because AutoCAD drawings may still reference an existing version.
"""

import argparse
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import socket
import tempfile
import uuid

import psycopg2
from psycopg2.extras import RealDictCursor

from download_rasters import extract_raster_metadata, raster_destination
from raster_paths import validate_filename
from settings import SETTINGS


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def object_path(root, digest):
    if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
        raise ValueError('Invalid archive checksum')
    base = Path(root).resolve()
    target = (base / 'objects' / digest[:2] / (digest + '.tif')).resolve()
    if not target.is_relative_to(base):
        raise ValueError('Archive object escapes its root')
    return target


def check_roots(local_root, nas_root):
    local, nas = Path(local_root).resolve(), Path(nas_root).resolve()
    if local.is_relative_to(nas) or nas.is_relative_to(local):
        raise ValueError('Local raster root and NAS archive must be separate')
    return local, nas


def publish_new(staged, destination):
    """Publish without overwriting a concurrent creator, on Windows or POSIX."""
    if os.name == 'nt':
        os.rename(staged, destination)  # Windows rename refuses an existing target.
    else:
        os.link(staged, destination)
        Path(staged).unlink()


def copy_verified(source, destination, digest, *, validate=False):
    """Checksum both the source stream and destination bytes before publication."""
    source, destination = Path(source), Path(destination)
    if destination.exists():
        if not destination.is_file() or sha256(destination) != digest:
            raise FileExistsError(f'Existing file has different content; retained: {destination}')
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    staged = None
    try:
        copied = hashlib.sha256()
        with source.open('rb') as src, tempfile.NamedTemporaryFile(
                dir=destination.parent, prefix='.epol-', suffix='.part', delete=False) as dst:
            staged = Path(dst.name)
            for chunk in iter(lambda: src.read(1024 * 1024), b''):
                dst.write(chunk)
                copied.update(chunk)
            dst.flush()
            os.fsync(dst.fileno())
        if copied.hexdigest() != digest or sha256(staged) != digest:
            raise ValueError(f'Copy checksum mismatch: {source}')
        if validate:
            extract_raster_metadata(staged)
        try:
            publish_new(staged, destination)
        except FileExistsError:
            if not destination.is_file() or sha256(destination) != digest:
                raise
            return False
        return True
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)


@contextmanager
def archive_lock(root):
    """One publisher; a stale lock after a crash needs explicit review."""
    path = Path(root) / '.publish.lock'
    token = uuid.uuid4().hex
    with path.open('x', encoding='utf-8') as stream:
        json.dump(dict(token=token,host=socket.gethostname(),pid=os.getpid()), stream)
    try:
        yield
    finally:
        if json.loads(path.read_text(encoding='utf-8')).get('token') == token:
            path.unlink()


def file_entries(rows, local_root):
    if not rows:
        raise ValueError('Refusing an empty archive publication')
    seen = set()
    result = []
    for row in rows:
        if row['id'] in seen:
            raise ValueError('Duplicate catalog ID')
        seen.add(row['id'])
        source, relative = raster_destination(row, local_root)
        if not source.is_file():
            raise FileNotFoundError(f'Local raster is missing: {source}')
        result.append(dict(id=row['id'],fek=row['fek'],filename=row['filename'],
            source_url=row['url_georef'],local_relative_path=relative,
            sha256=sha256(source),bytes=source.stat().st_size,source=source))
    return result


def push(rows, local_root, nas_root, *, apply=False, progress=None):
    local, nas = check_roots(local_root, nas_root)
    entries = file_entries(rows, local)
    planned = {}
    for index,entry in enumerate(entries,1):
        target = object_path(nas, entry['sha256'])
        if target.exists():
            if not target.is_file() or sha256(target) != entry['sha256']:
                raise ValueError(f'Archive object is corrupt; retained for review: {target}')
        elif entry['sha256'] not in planned:
            extract_raster_metadata(entry['source'])
            planned[entry['sha256']] = entry
        if progress:
            progress(f"Check {index}/{len(entries)}: {entry['filename']}")
    unique = {entry['sha256'] for entry in entries}
    result = dict(mode='push',apply=apply,total=len(entries),new_objects=len(planned),
                  copied=0,reused=len(unique)-len(planned),objects=len(unique),failed=0)
    if not apply:
        return result
    nas.mkdir(parents=True, exist_ok=True)
    with archive_lock(nas):
        for index,entry in enumerate(entries,1):
            if copy_verified(entry['source'],object_path(nas,entry['sha256']),entry['sha256']):
                result['copied'] += 1
            if progress:
                progress(f"Archive {index}/{len(entries)}: {entry['filename']}")
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        manifest = dict(format=1,collection='fek',published_at=datetime.now(timezone.utc).isoformat(),
                        files=[{k:v for k,v in entry.items() if k!='source'} for entry in entries])
        data = (json.dumps(manifest,indent=2,ensure_ascii=True)+'\n').encode()
        history = nas / 'manifests' / (stamp+'_'+uuid.uuid4().hex[:8]+'.json')
        history.parent.mkdir(parents=True, exist_ok=True)
        with history.open('xb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        staged = None
        try:
            with tempfile.NamedTemporaryFile(dir=nas,prefix='.latest-',suffix='.tmp',delete=False) as stream:
                staged = Path(stream.name)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(staged,nas/'latest.json')
        finally:
            if staged is not None:
                staged.unlink(missing_ok=True)
        result['manifest'] = str(history)
    return result


def read_manifest(nas_root):
    path = Path(nas_root) / 'latest.json'
    if path.stat().st_size > 10 * 1024 * 1024:
        raise ValueError('Archive manifest is unexpectedly large')
    value = json.loads(path.read_text(encoding='utf-8'))
    if value.get('format') != 1 or value.get('collection') != 'fek' or not isinstance(value.get('files'),list):
        raise ValueError('Unsupported archive manifest')
    seen = set()
    for entry in value['files']:
        if not isinstance(entry.get('id'),int) or entry['id'] in seen:
            raise ValueError('Invalid or duplicate archive ID')
        seen.add(entry['id'])
        validate_filename(entry['filename'])
        object_path(nas_root,entry['sha256'])
        if not isinstance(entry.get('bytes'),int) or entry['bytes'] < 1:
            raise ValueError('Invalid archive file size')
    if not seen:
        raise ValueError('Empty archive manifest')
    return value


def pull(rows, local_root, nas_root, *, apply=False, progress=None, raster_id=None):
    local, nas = check_roots(local_root,nas_root)
    manifest = read_manifest(nas)
    entries = manifest['files']
    if raster_id is not None:
        entries = [entry for entry in entries if entry['id']==raster_id]
        if not entries:
            raise ValueError('Requested catalog ID is absent from the archive')
    current = {row['id']:row for row in rows}
    result = dict(mode='pull',apply=apply,total=len(entries),copied=0,
                  missing=0,reused=0,failed=0,errors=[])
    for index,entry in enumerate(entries,1):
        try:
            row = current.get(entry['id'])
            if row is None or row['filename']!=entry['filename'] or row['url_georef']!=entry['source_url']:
                raise ValueError('Archive identity differs from the current catalog')
            destination,_ = raster_destination(row,local)
            source = object_path(nas,entry['sha256'])
            if not source.is_file() or source.stat().st_size != entry['bytes'] or sha256(source)!=entry['sha256']:
                raise ValueError('Archive object is missing or has a checksum mismatch')
            if destination.exists():
                if not destination.is_file() or sha256(destination)!=entry['sha256']:
                    raise FileExistsError(f'Local content differs; retained for existing drawings: {destination}')
                result['reused'] += 1
            else:
                result['missing'] += 1
                if apply and copy_verified(source,destination,entry['sha256'],validate=True):
                    result['copied'] += 1
        except (OSError,ValueError) as exc:
            result['failed'] += 1
            result['errors'].append(dict(id=entry['id'],filename=entry['filename'],error=str(exc)))
        if progress:
            progress(f"Restore {index}/{len(entries)}: {entry['filename']}")
    return result


def catalog_rows():
    with closing(psycopg2.connect(**SETTINGS.database.connection_kwargs(),
            options='-c default_transaction_read_only=on -c statement_timeout=30000')) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute('''SELECT rc.id,rc.fek,rc.filename,rc.url_georef,rc.local_path_georef
                FROM sp_geodata.v_all_rasters v
                JOIN epoleodomia.raster_catalog rc ON rc.id=v.source_id
                WHERE v.collection='fek' ORDER BY rc.id''')
            return [dict(row) for row in cur.fetchall()]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=('push','pull'))
    parser.add_argument('--nas-root',help='Explicit UNC archive directory; otherwise EPOL_RASTER_NAS_PATH')
    parser.add_argument('--apply',action='store_true',help='Copy files; default is preview')
    parser.add_argument('--raster-id',type=int,help='pull only: restore one catalog ID')
    args = parser.parse_args(argv)
    if args.raster_id is not None and (args.mode!='pull' or args.raster_id<1):
        parser.error('--raster-id requires pull and a positive ID')
    try:
        root = args.nas_root or getattr(SETTINGS,'raster_nas_path',None)
        if not root or not PureWindowsPath(root).drive.startswith('\\\\') or not PureWindowsPath(root).is_absolute():
            raise ValueError('Set EPOL_RASTER_NAS_PATH or --nas-root to an absolute UNC NAS directory')
        action = push if args.mode=='push' else pull
        kwargs = dict(apply=args.apply,progress=lambda line:print(line,flush=True))
        if args.mode=='pull':
            kwargs['raster_id'] = args.raster_id
        result = action(catalog_rows(),SETTINGS.raster_base_path,root,**kwargs)
        print(json.dumps(result,indent=2),flush=True)
        return int(bool(result['failed']))
    except Exception as exc:
        print(f'Raster archive failed: {exc}',flush=True)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
