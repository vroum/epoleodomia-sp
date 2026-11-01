"""Real role creation/rollback and its exact scope in marked disposable PostGIS."""

from contextlib import closing
from contextlib import redirect_stdout
from io import StringIO
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import psycopg2
from psycopg2 import extensions

import database_setup
from settings import DatabaseSettings
from settings import read_env_file
import setup_sync_writer as setup
from sync_access import inspect_target, verify_access
from sync_launcher import check_connection
from tests.test_database_setup_postgis import MARKER


@unittest.skipUnless(os.environ.get('EPOL_TEST_SETUP_DSN'), 'Run tests/run_setup_tests.py')
class SyncAccessPostGISTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dsn=os.environ['EPOL_TEST_SETUP_DSN']
        target=extensions.parse_dsn(cls.dsn)
        if target.get('host') not in ('127.0.0.1','localhost','::1') or target.get('dbname')!='epol_setup_test':
            raise RuntimeError('Requires disposable loopback epol_setup_test')
        with closing(psycopg2.connect(cls.dsn)) as conn,conn.cursor() as cur:
            cur.execute("SELECT shobj_description(oid,'pg_database') FROM pg_database WHERE datname=current_database()")
            if cur.fetchone()!=(MARKER,):
                raise RuntimeError('Disposable marker missing')

    def connect(self,**kwargs):
        return psycopg2.connect(self.dsn,options=kwargs.get('options',''))

    def query(self,statement,params=None):
        with self.conn.cursor() as cur:
            cur.execute(statement,params)
            return cur.fetchall() if cur.description else None

    def setUp(self):
        self.conn=self.connect()
        self.conn.autocommit=True
        self.query('DROP SCHEMA IF EXISTS epoleodomia CASCADE; DROP SCHEMA IF EXISTS epol_meta CASCADE; '
                   'DROP SCHEMA IF EXISTS sp_geodata CASCADE; CREATE SCHEMA sp_geodata')
        self.assertFalse(database_setup.run_setup(apply=True,connect=self.connect).findings)
        for name in ('kaek_parcels_operating','kaek_douleies_operating','kaek_apokleistikes_operating'):
            self.query(f'CREATE TABLE sp_geodata.{name}(gid serial,objectid bigint,geom geometry(MultiPolygon,2100))')
        self.query('CREATE TABLE sp_geodata.posted_source(kaek text); '
                   'CREATE VIEW sp_geodata.kaek_parcels_anartisi AS SELECT kaek FROM sp_geodata.posted_source')
        import sync_ydrolipsies
        self.query(sync_ydrolipsies.DDL)
        self.query("CREATE TABLE sp_geodata.manual_judgement(id int,note text); INSERT INTO sp_geodata.manual_judgement VALUES(1,'keep')")
        with self.conn.cursor() as cur:
            self.target=inspect_target(cur)

    def tearDown(self):
        if self.query("SELECT 1 FROM pg_roles WHERE rolname='epol_sync'"):
            self.query('DROP OWNED BY epol_sync; DROP ROLE epol_sync')
        self.conn.close()

    def create(self):
        setup.create_writer(self.connect,'epol-test-writer-only',expected_target=self.target)

    def test_real_profile_authenticates_and_child_check_uses_separate_credentials(self):
        self.create()
        target=extensions.parse_dsn(self.dsn)
        writer=DatabaseSettings(host=target['host'],port=int(target['port']),database=target['dbname'],
                                user='epol_sync',password='epol-test-writer-only')
        check_connection(writer)
        env=dict(os.environ,EPOL_DB_HOST=writer.host,EPOL_DB_PORT=str(writer.port),
            EPOL_DB_NAME=writer.database,EPOL_DB_USER=target['user'],EPOL_DB_PASSWORD=target['password'],
            EPOL_SYNC_DB_USER=writer.user,EPOL_SYNC_DB_PASSWORD=writer.password)
        result=subprocess.run([sys.executable,'-B','sync_launcher.py','--check'],
            cwd=Path(__file__).resolve().parents[1],env=env,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertNotIn(writer.password,result.stdout+result.stderr)
        raster_id=self.query("""INSERT INTO epoleodomia.raster_catalog
            (fek,filename,url_georef,georef_rms,original_scale)
            VALUES ('PROFILE','map.tif','https://example.invalid/map.tif',0.25,1000) RETURNING id""")[0][0]
        with closing(psycopg2.connect(**writer.connection_kwargs())) as conn,conn.cursor() as cur:
            import download_rasters
            self.assertEqual(len(download_rasters.get_pending_rasters(conn,'PROFILE')),1)
            download_rasters.update_catalog_downloaded(conn,raster_id,'PROFILE/map.tif',123,
                {'width_px':10,'height_px':20,'bands':1,'crs_epsg':2100,
                 'resolution_x':1,'resolution_y':1,'nodata_value':0,
                 'bbox_wkt':'POLYGON((0 0,10 0,10 20,0 20,0 0))'})
            download_rasters.update_catalog_failed(conn,raster_id,'simulated retry')
            for statement in ("UPDATE sp_geodata.manual_judgement SET note='bad'", 'CREATE TABLE epoleodomia.unapproved(id int)',
                "SELECT setval('epoleodomia.building_regs_lot_id_seq',1)",
                'UPDATE epoleodomia.raster_catalog SET georef_rms=999',
                "DELETE FROM epol_meta.schema_migrations"):
                with self.subTest(statement=statement), self.assertRaises(psycopg2.errors.InsufficientPrivilege):
                    cur.execute(statement)
                conn.rollback()
        self.assertEqual(self.query('SELECT * FROM sp_geodata.manual_judgement'),[(1,'keep')])
        self.assertEqual(self.query('SELECT georef_rms,original_scale,download_status,width_px,local_path_georef '
                                    'FROM epoleodomia.raster_catalog WHERE id=%s',(raster_id,)),
                         [(0.25,1000,'downloaded',10,'PROFILE/map.tif')])

    def test_parallel_raster_publication_as_writer_isolates_failure_and_keeps_manual_fields(self):
        import threading
        import download_rasters as dl
        from tests.test_raster_download import Response, tif_bytes
        self.create()
        ids={}
        for name in ('a.tif','b.tif','c.tif','invalid.tif'):
            ids[name]=self.query("""INSERT INTO epoleodomia.raster_catalog
                (fek,filename,url_georef,georef_rms,original_scale,download_status,width_px)
                VALUES ('PROFILE',%s,%s,.25,1000,%s,%s) RETURNING id""",
                (name,'https://example.invalid/'+name,'downloaded' if name=='b.tif' else 'pending',
                 8 if name=='b.tif' else None))[0][0]
        self.query("ALTER TABLE epoleodomia.raster_catalog ADD CHECK(filename<>'b.tif' OR width_px<>16)")
        target=extensions.parse_dsn(self.dsn)
        target.update(user='epol_sync',password='epol-test-writer-only')
        connection_threads=[]
        def connect(*,read_only=False):
            connection_threads.append(threading.get_ident())
            return psycopg2.connect(**target,options='-c default_transaction_read_only=on' if read_only else '')
        def response(url,**kwargs):
            return Response(b'<html>not a TIFF</html>' if url.endswith('invalid.tif') else tif_bytes())
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            old=root/'FEK_PROFILE'/'b.tif'
            old.parent.mkdir()
            previous=tif_bytes(width=8)
            old.write_bytes(previous)
            (root/'a.tif').write_bytes(previous)
            with patch.object(dl,'GEOREF_DIR',root),patch.object(dl,'get_db_connection',side_effect=connect), \
                    patch.object(dl.requests,'get',side_effect=response),patch.object(dl,'RETRY_DELAY',0), \
                    redirect_stdout(StringIO()):
                result=dl.sync_rasters(fek_filter='PROFILE',force=True,parallel=3)
            self.assertEqual((result['downloaded'],result['failed']),(2,2),result)
            self.assertEqual(set(connection_threads),{threading.get_ident()})
            self.assertEqual(old.read_bytes(),previous)
            self.assertEqual(dl.extract_raster_metadata(root/'a.tif')['width_px'],16)
            self.assertFalse((root/'FEK_PROFILE'/'a.tif').exists())
            self.assertTrue((root/'FEK_PROFILE'/'c.tif').exists())
            self.assertFalse((root/'FEK_PROFILE'/'invalid.tif').exists())
            self.assertEqual(list(root.rglob('.epol-*')),[])
        self.assertEqual(self.query("""SELECT filename,download_status,width_px,georef_rms,original_scale
            FROM epoleodomia.raster_catalog ORDER BY filename"""),
            [('a.tif','downloaded',16,.25,1000),('b.tif','downloaded',8,.25,1000),
             ('c.tif','downloaded',16,.25,1000),('invalid.tif','failed',None,.25,1000)])
        self.assertEqual(self.query('SELECT * FROM sp_geodata.manual_judgement'),[(1,'keep')])
        self.assertEqual(self.query("SELECT local_path_georef FROM epoleodomia.raster_catalog WHERE filename='a.tif'"),
                         [('a.tif',)])

    def test_raster_source_changed_during_download_is_not_published(self):
        import download_rasters as dl
        from tests.test_raster_download import Response, tif_bytes
        self.create()
        raster_id=self.query("""INSERT INTO epoleodomia.raster_catalog(fek,filename,url_georef)
            VALUES ('PROFILE','map.tif','https://example.invalid/map.tif') RETURNING id""")[0][0]
        target=extensions.parse_dsn(self.dsn)
        target.update(user='epol_sync',password='epol-test-writer-only')
        with closing(psycopg2.connect(**target)) as conn:
            raster=dl.get_pending_rasters(conn,raster_id=raster_id,limit=1)[0]
            conn.rollback()
            with tempfile.TemporaryDirectory() as directory,patch.object(dl.requests,'get',return_value=Response(tif_bytes())):
                result=dl.download_raster_worker(raster,Path(directory))
                self.query("UPDATE epoleodomia.raster_catalog SET fek='CHANGED' WHERE id=%s",(raster_id,))
                with self.assertRaisesRegex(ValueError,'source changed'):
                    dl.publish_download(conn,raster,result)
                self.assertFalse(Path(result['local_path']).exists())
                self.assertFalse(result['staged_path'].exists())
                dl.update_catalog_failed(conn,raster_id,'stale source',source=raster)
        self.assertEqual(self.query('SELECT fek,download_status,download_error FROM epoleodomia.raster_catalog'),
                         [('CHANGED','pending',None)])

    def test_grants_and_role_creation_roll_back_together_on_verification_failure(self):
        before=self.query("SELECT oid,relacl FROM pg_class WHERE relnamespace IN ('epoleodomia'::regnamespace,'sp_geodata'::regnamespace) ORDER BY oid")
        with patch.object(setup,'verify_access',side_effect=ValueError('injected postcheck')):
            with self.assertRaisesRegex(ValueError,'injected'):
                self.create()
        self.assertEqual(self.query("SELECT 1 FROM pg_roles WHERE rolname='epol_sync'"),[])
        self.assertEqual(self.query("SELECT oid,relacl FROM pg_class WHERE relnamespace IN ('epoleodomia'::regnamespace,'sp_geodata'::regnamespace) ORDER BY oid"),before)

    def test_full_local_setup_flow_creates_checks_and_saves_only_sync_credentials(self):
        target=extensions.parse_dsn(self.dsn)
        base=DatabaseSettings(host=target['host'],port=int(target['port']),database=target['dbname'],
                              user=target['user'],password=target['password'])
        real_save=setup.save_credentials
        password='generated-test-only!%$= #;value'
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'.env'
            path.write_text('EPOL_DB_USER=api_reader\nEPOL_DB_PASSWORD=api-only\n',encoding='utf-8')
            def save(value,**kwargs):
                return real_save(value,env_path=path,**kwargs)
            with patch.object(setup,'ENV_PATH',path), \
                 patch.object(setup,'load_settings',return_value=SimpleNamespace(database=base)), \
                 patch.object(setup.sys,'stdin',MagicMock()), \
                 patch('builtins.input',return_value=base.user), \
                 patch.object(setup.getpass,'getpass',return_value=base.password), \
                 patch.object(setup.secrets,'token_urlsafe',return_value=password), \
                 patch.object(setup,'save_credentials',side_effect=save), \
                 redirect_stdout(StringIO()) as output:
                self.assertEqual(setup.main(['--apply']),0,output.getvalue())
            self.assertEqual(read_env_file(path),{'EPOL_DB_USER':'api_reader','EPOL_DB_PASSWORD':'api-only',
                'EPOL_SYNC_DB_USER':'epol_sync','EPOL_SYNC_DB_PASSWORD':password})
            self.assertNotIn(password,output.getvalue())
            self.assertNotIn(base.password,output.getvalue())

    def test_existing_role_is_never_reused_or_reset(self):
        self.create()
        before=self.query("SELECT rolpassword FROM pg_authid WHERE rolname='epol_sync'")
        with self.assertRaises(psycopg2.errors.DuplicateObject):
            self.create()
        self.assertEqual(self.query("SELECT rolpassword FROM pg_authid WHERE rolname='epol_sync'"),before)

    def test_extra_column_or_curated_write_privileges_are_rejected(self):
        self.create()
        for statement,revoke in (
            ('GRANT UPDATE(georef_rms) ON epoleodomia.raster_catalog TO epol_sync',
             'REVOKE UPDATE(georef_rms) ON epoleodomia.raster_catalog FROM epol_sync'),
            ('GRANT UPDATE ON sp_geodata.manual_judgement TO epol_sync',
             'REVOKE UPDATE ON sp_geodata.manual_judgement FROM epol_sync')):
            self.query(statement)
            with self.conn.cursor() as cur, self.assertRaises(ValueError):
                verify_access(cur)
            self.query(revoke)
        with self.conn.cursor() as cur:
            verify_access(cur)
