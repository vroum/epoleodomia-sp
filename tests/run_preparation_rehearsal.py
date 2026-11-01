"""Restore an actual archive, prepare only that disposable copy, compare data/reports."""
import argparse
import asyncio
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import psycopg2
from psycopg2 import sql, pool

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tests.postgis18_container import disposable_postgis18, IMAGE
import prepare_legacy_database as prep
from settings import SETTINGS


def file_sha(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):
            value.update(chunk)
    return value.hexdigest()


def project_fingerprints(cursor, columns=None):
    if columns is None:
        cursor.execute("""SELECT n.nspname,c.relname,array_agg(a.attname ORDER BY a.attnum)
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped
            WHERE n.nspname IN ('epoleodomia','sp_geodata','public') AND c.relkind='r'
            AND NOT EXISTS(SELECT 1 FROM pg_depend d WHERE d.classid='pg_class'::regclass AND d.objid=c.oid AND d.deptype='e')
            GROUP BY 1,2 ORDER BY 1,2""")
        columns = cursor.fetchall()
    results = {}
    for schema,name,fields in columns:
        cursor.execute(sql.SQL("""SELECT count(*),md5(COALESCE(string_agg(h,'' ORDER BY h),''))
            FROM (SELECT md5(row_to_json(t)::text) h FROM (SELECT {} FROM {}) t) z""").format(
                sql.SQL(',').join(map(sql.Identifier,fields)),sql.Identifier(schema,name)))
        results[schema+'.'+name] = cursor.fetchone()
    return columns,results


def reports(target, samples=None):
    import api_server as api
    previous_pool = api.db_pool
    api.db_pool = pool.SimpleConnectionPool(1,2,target.dsn,
        options='-c role=codex_reader -c default_transaction_read_only=on -c statement_timeout=20000')
    try:
        if samples is None:
            with closing(target.connect()) as conn,conn.cursor() as cur:
                cur.execute("SELECT ST_X(p),ST_Y(p) FROM (SELECT ST_PointOnSurface(geom) p FROM epoleodomia.building_blocks WHERE geom IS NOT NULL AND NOT COALESCE(is_deleted,false) ORDER BY id LIMIT 2)t")
                samples = [('town_'+str(n),x,y) for n,(x,y) in enumerate(cur.fetchall(),1)]
                cur.execute('''SELECT ST_X(p),ST_Y(p) FROM (SELECT ST_PointOnSurface(geom) p
                    FROM sp_geodata.kaek_parcels_operating WHERE '''+api._kaek_non_special_use_filter()+''')t
                    WHERE NOT EXISTS(SELECT 1 FROM sp_geodata.orio_sxediou_polews b WHERE ST_Covers(b.geom,t.p)) LIMIT 1''')
                outside = cur.fetchone()
                if len(samples)!=2 or outside is None:
                    raise RuntimeError('Rehearsal requires populated town and outside-plan samples')
                samples.append(('outside_plan',*outside))
        result = {}
        for label,x,y in samples:
            for name,endpoint in [('point',api.get_report_rows),('parcel',api.get_report_parcel)]:
                body = asyncio.run(endpoint(x,y))
                if not body or body.startswith('ERR') or 'HEADER|NATURA' not in body:
                    raise RuntimeError('Report failed: '+label+'/'+name)
                result[label+'_'+name] = dict(sha256=hashlib.sha256(body.encode('utf-8')).hexdigest(),lines=len(body.splitlines()))
        return samples,result
    finally:
        api.db_pool.closeall()
        api.db_pool = previous_pool


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup',required=True)
    parser.add_argument('--output',default=str(ROOT/'logs/preparation_rehearsal.json'))
    args = parser.parse_args()
    backup = Path(args.backup).resolve()
    backup_sha = file_sha(backup)
    prep.check_backup(backup,backup_sha)
    recipe,_,checksum,_ = prep.load_recipe()
    # Source access is restricted to role names, used as NOLOGIN placeholders.
    # No source permissions/password hashes or role memberships are copied.
    with closing(psycopg2.connect(**SETTINGS.database.connection_kwargs(),
        options='-c default_transaction_read_only=on')) as source,source.cursor() as cur:
        cur.execute('SET TRANSACTION READ ONLY')
        cur.execute("SELECT rolname FROM pg_roles WHERE rolname !~ '^pg_' ORDER BY 1")
        roles = [v[0] for v in cur.fetchall()]
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True,exist_ok=True)
    result = dict(backup_sha256=backup_sha,backup_bytes=backup.stat().st_size,
        preparation_checksum=checksum,controller_sha256=file_sha(ROOT/'prepare_legacy_database.py'),
        image=IMAGE,started_at=datetime.now(timezone.utc).isoformat(),ok=False)
    print('Restoring the full archive in a new PG18 container; cron execution disabled.',flush=True)
    try:
        with disposable_postgis18('epol_restore_test','EPOL disposable preparation rehearsal',roles=roles) as target:
            with backup.open('rb') as archive:
                restored = subprocess.run(['docker','exec','-i',target.container,
                    '/usr/lib/postgresql/18/bin/pg_restore','-U','postgres',
                    '--exit-on-error','--single-transaction','-d',target.database],
                    stdin=archive,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=1200)
            output.with_suffix('.restore.log').write_bytes(restored.stderr)
            if restored.returncode:
                raise RuntimeError('Archive restore failed; see the adjacent restore log')
            if file_sha(backup)!=backup_sha:
                raise RuntimeError('Archive changed during restore; use an immutable local copy')
            result['restore_ok'] = True
            with closing(target.connect()) as conn,conn.cursor() as cur:
                cur.execute("SELECT current_setting('server_version'),postgis_full_version(),current_setting('cron.launch_active_jobs')")
                version,postgis,cron = cur.fetchone()
                if cron!='off':
                    raise RuntimeError('Rehearsal cron jobs are not disabled')
                result.update(postgresql=version,postgis=postgis,cron_execution=cron)
                # The reader was created after some backups. Give its local
                # placeholder read access for the report checks, without login.
                cur.execute('GRANT USAGE ON SCHEMA epoleodomia,sp_geodata,public TO codex_reader; GRANT SELECT ON ALL TABLES IN SCHEMA epoleodomia,sp_geodata,public TO codex_reader')
                conn.commit()
            with closing(target.connect()) as conn,conn.cursor() as cur:
                columns,before = project_fingerprints(cur)
            samples,before_reports = reports(target)
            print('Archive restored; original data/reports captured. Previewing preparation.',flush=True)
            plan = prep.run_preparation(connect=target.connect)
            if plan.findings or plan.state!='ready':
                raise RuntimeError('Restored preparation preview blocked: '+'; '.join(plan.findings))
            applied = prep.run_preparation(apply=True,expected_plan=plan.plan_hash,
                backup_path=backup,backup_sha256=backup_sha,connect=target.connect)
            if not applied.applied:
                raise RuntimeError('Restored preparation did not commit')
            with closing(target.connect()) as conn,conn.cursor() as cur:
                _,after = project_fingerprints(cur,columns)
            if before!=after:
                raise RuntimeError('Original project-table values changed')
            _,after_reports = reports(target,samples)
            if before_reports!=after_reports:
                raise RuntimeError('Report output changed; review before any production application')
            if prep.run_preparation(connect=target.connect).state!='prepared':
                raise RuntimeError('Prepared-state/history validation failed')
            result.update(ok=True,original_tables_preserved=len(before),original_data_fingerprint=prep.digest(before),
                reports_unchanged=after_reports,reviewed_plan=plan.plan_hash,
                target_version=recipe['target_version'],preparation_applied_to_copy=True)
            print('Preparation passed: original data preserved and six reports unchanged.',flush=True)
        result['temporary_container_removed'] = True
    except BaseException:
        result['ok'] = False
        raise
    finally:
        result['finished_at'] = datetime.now(timezone.utc).isoformat()
        output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
