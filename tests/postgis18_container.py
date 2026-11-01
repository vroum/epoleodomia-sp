"""Owned disposable PostgreSQL 18 container, shared by preparation rehearsals/tests."""
from contextlib import closing, contextmanager
from dataclasses import dataclass
import subprocess
import time
import uuid

import psycopg2
from psycopg2 import sql


IMAGE = 'kartoza/postgis@sha256:cbdd40bde138f57dc7efcbf71c5452409e7c812f4a4ebd7edaf9d777f68b8ce2'


@dataclass(frozen=True)
class DisposablePostGIS:
    container: str
    port: int
    database: str
    marker: str

    @property
    def dsn(self):
        return psycopg2.extensions.make_dsn(host='127.0.0.1', port=self.port,
            dbname=self.database, user='postgres', password='epol-test-only')

    def connect(self, **kwargs):
        conn = psycopg2.connect(self.dsn, connect_timeout=5, options=kwargs.get('options',''))
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT shobj_description(oid,'pg_database') FROM pg_database WHERE datname=current_database()")
                if cur.fetchone() != (self.marker,):
                    raise RuntimeError('Disposable database marker changed')
            conn.rollback()
            return conn
        except BaseException:
            conn.close()
            raise


@contextmanager
def disposable_postgis18(database, marker, *, roles=('docker','codex_reader','ai_reader')):
    if database not in ('epol_setup_test','epol_restore_test'):
        raise ValueError('Only the fixed disposable database names are supported')
    container = None
    name = 'epol-preparation-tests-'+uuid.uuid4().hex[:12]
    command = ('printf "%s\\n" epol-test-only > /tmp/epol-pw && '
        '/usr/lib/postgresql/18/bin/initdb --no-sync --encoding=UTF8 --locale=C '
        '-D /tmp/epol-data --auth-local=trust --auth-host=scram-sha-256 '
        '--pwfile=/tmp/epol-pw > /tmp/epol-init.log && '
        'printf "host all all 0.0.0.0/0 scram-sha-256\\n" >> /tmp/epol-data/pg_hba.conf && '
        'exec /usr/lib/postgresql/18/bin/postgres -D /tmp/epol-data '
        '-c listen_addresses=* -c port=5432 -c shared_preload_libraries=pg_cron '
        '-c cron.database_name='+database+' -c cron.launch_active_jobs=off '
        '-c cron.enable_superuser_jobs=off')
    try:
        container = subprocess.run(['docker','run','--rm','--detach','--name',name,
            '--user','postgres','--tmpfs','/tmp:rw,mode=1777','--publish','127.0.0.1::5432',
            '--entrypoint','sh',IMAGE,'-c',command],check=True,capture_output=True,text=True,timeout=60).stdout.strip()
        port = int(subprocess.run(['docker','port',container,'5432/tcp'],check=True,
            capture_output=True,text=True,timeout=10).stdout.strip().rsplit(':',1)[1])
        deadline = time.monotonic()+30
        while True:
            try:
                conn = psycopg2.connect(host='127.0.0.1',port=port,dbname='postgres',
                    user='postgres',password='epol-test-only',connect_timeout=2)
                break
            except psycopg2.OperationalError:
                if time.monotonic()>deadline:
                    raise RuntimeError('Disposable PostgreSQL 18 startup timed out') from None
                time.sleep(.2)
        with closing(conn):
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(database)))
                cur.execute(sql.SQL('COMMENT ON DATABASE {} IS {}').format(sql.Identifier(database),sql.Literal(marker)))
                for role in sorted(set(roles)-{'postgres'}):
                    cur.execute(sql.SQL('CREATE ROLE {} NOLOGIN').format(sql.Identifier(role)))
                cur.execute(sql.SQL('GRANT CREATE ON DATABASE {} TO docker').format(sql.Identifier(database)))
        target = DisposablePostGIS(container,port,database,marker)
        with closing(target.connect()) as conn,conn.cursor() as cur:
            cur.execute('CREATE EXTENSION postgis')
            conn.commit()
        yield target
    finally:
        if container:
            subprocess.run(['docker','stop','--timeout','5',container],check=True,
                           stdout=subprocess.DEVNULL,timeout=20)
