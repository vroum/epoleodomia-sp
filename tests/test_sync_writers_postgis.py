"""Actual writer SQL, exclusively in the marked disposable setup database."""
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import unittest
import time
import tempfile
import uuid
from unittest.mock import patch

import psycopg2
from psycopg2 import extensions

import ingest_rasters
import sync_kaek_operating as cad
import sync_ydrolipsies as emsy
from sync_safety import LoadError
from tests.test_database_setup_postgis import MARKER
from tests.test_emsy_sync import feature


@unittest.skipUnless(os.environ.get('EPOL_TEST_SETUP_DSN'),
                     'Run tests/run_setup_tests.py for disposable writer tests')
class SyncWriterPostGISTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dsn = os.environ['EPOL_TEST_SETUP_DSN']
        target = extensions.parse_dsn(cls.dsn)
        if target.get('host') not in ('127.0.0.1', 'localhost', '::1') or target.get('dbname') != 'epol_setup_test':
            raise RuntimeError('Writer tests require disposable localhost epol_setup_test')
        with closing(psycopg2.connect(cls.dsn)) as conn, conn.cursor() as cur:
            cur.execute("SELECT shobj_description(oid,'pg_database') FROM pg_database WHERE datname=current_database()")
            if cur.fetchone() != (MARKER,):
                raise RuntimeError('Database is not marked as disposable')

    def setUp(self):
        self.conn = psycopg2.connect(self.dsn)
        self.addCleanup(self.conn.close)
        self.conn.autocommit = True
        self.query('DROP SCHEMA IF EXISTS sp_geodata CASCADE; CREATE SCHEMA sp_geodata')
        self.table = 'kaek_douleies_operating'
        self.fields = [('OBJECTID','bigint'),('KAEK','text')]

    def query(self, statement, params=None):
        with self.conn.cursor() as cur:
            cur.execute(statement,params)
            return cur.fetchall() if cur.description else None

    def rows(self, oid=1):
        return [(oid, f'KAEK-{oid}', json.dumps({'type':'Polygon','coordinates':[
            [[420000,4120000],[420010,4120000],[420010,4120010],[420000,4120010],[420000,4120000]]]}))]

    def publish(self, oid=1):
        with closing(psycopg2.connect(self.dsn)) as conn:
            try:
                return cad._replace_layer(conn,self.table,self.fields,self.rows(oid))
            except Exception:
                conn.rollback()
                raise

    def metadata(self):
        return self.query("""SELECT c.oid,c.relname,c.relowner,c.relacl,c.reloptions,
                obj_description(c.oid,'pg_class')
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='sp_geodata' ORDER BY c.relname""")

    def test_cadastre_preserves_table_transitive_views_indexes_and_acl(self):
        self.publish()
        self.query("""CREATE VIEW sp_geodata.consumer WITH (security_barrier=true) AS
                SELECT objectid,kaek FROM sp_geodata.kaek_douleies_operating;
            CREATE VIEW sp_geodata.downstream AS SELECT * FROM sp_geodata.consumer;
            COMMENT ON TABLE sp_geodata.kaek_douleies_operating IS 'keep table';
            COMMENT ON VIEW sp_geodata.consumer IS 'keep view';
            COMMENT ON COLUMN sp_geodata.consumer.kaek IS 'keep column';
            GRANT SELECT ON sp_geodata.kaek_douleies_operating,sp_geodata.consumer,
                sp_geodata.downstream TO PUBLIC;
            GRANT SELECT(kaek) ON sp_geodata.consumer TO PUBLIC;
        """)
        before = self.metadata()
        column_before = self.query("SELECT attacl,col_description(attrelid,attnum) FROM pg_attribute WHERE attrelid='sp_geodata.consumer'::regclass AND attname='kaek'")
        self.publish(2)
        self.assertEqual(self.metadata(),before)
        self.assertEqual(self.query('SELECT * FROM sp_geodata.downstream'),[(2,'KAEK-2')])
        self.assertEqual(self.query("SELECT attacl,col_description(attrelid,attnum) FROM pg_attribute WHERE attrelid='sp_geodata.consumer'::regclass AND attname='kaek'"),column_before)
        self.assertEqual(self.query("SELECT to_regclass('pg_temp.epol_cadastre_stage')"),[(None,)])

    def test_cadastre_schema_drift_rolls_back_and_keeps_manual_columns(self):
        self.publish()
        self.query("ALTER TABLE sp_geodata.kaek_douleies_operating ADD COLUMN manual_note text DEFAULT 'keep'")
        before = self.metadata()
        with self.assertRaisesRegex(LoadError,'columns differ'):
            self.publish(2)
        self.assertEqual(self.metadata(),before)
        self.assertEqual(self.query('SELECT objectid,manual_note FROM sp_geodata.kaek_douleies_operating'),[(1,'keep')])

    def test_cadastre_insert_failure_rolls_back_deletion_and_keeps_view_oid(self):
        self.publish()
        self.query('ALTER TABLE sp_geodata.kaek_douleies_operating ADD CHECK(objectid<2); CREATE VIEW sp_geodata.consumer AS SELECT * FROM sp_geodata.kaek_douleies_operating')
        before = self.metadata()
        with self.assertRaises(psycopg2.errors.CheckViolation):
            self.publish(2)
        self.assertEqual(self.metadata(),before)
        self.assertEqual(self.query('SELECT objectid FROM sp_geodata.consumer'),[(1,)])

    def test_cadastre_blocks_cascading_foreign_keys_before_deleting_rows(self):
        self.publish()
        self.query('''ALTER TABLE sp_geodata.kaek_douleies_operating ADD UNIQUE(objectid);
            CREATE TABLE sp_geodata.child (ref bigint REFERENCES sp_geodata.kaek_douleies_operating(objectid) ON DELETE CASCADE);
            INSERT INTO sp_geodata.child VALUES (1)''')
        with self.assertRaisesRegex(LoadError,'foreign-key consumers'):
            self.publish(2)
        self.assertEqual(self.query('SELECT * FROM sp_geodata.child'),[(1,)])
        self.assertEqual(self.query('SELECT objectid FROM sp_geodata.kaek_douleies_operating'),[(1,)])

    def test_cadastre_blocks_custom_triggers_and_row_security(self):
        self.publish()
        self.query('''CREATE FUNCTION sp_geodata.noop() RETURNS trigger LANGUAGE plpgsql AS $$BEGIN RETURN OLD; END$$;
            CREATE TRIGGER custom_delete BEFORE DELETE ON sp_geodata.kaek_douleies_operating FOR EACH ROW EXECUTE FUNCTION sp_geodata.noop()''')
        with self.assertRaisesRegex(LoadError,'custom triggers'):
            self.publish(2)
        self.query('DROP TRIGGER custom_delete ON sp_geodata.kaek_douleies_operating; ALTER TABLE sp_geodata.kaek_douleies_operating ENABLE ROW LEVEL SECURITY')
        with self.assertRaisesRegex(LoadError,'row security'):
            self.publish(2)
        self.query('ALTER TABLE sp_geodata.kaek_douleies_operating DISABLE ROW LEVEL SECURITY; CREATE RULE keep_old AS ON DELETE TO sp_geodata.kaek_douleies_operating DO INSTEAD NOTHING')
        with self.assertRaisesRegex(LoadError,'rewrite rules'):
            self.publish(2)
        self.assertEqual(self.query('SELECT objectid FROM sp_geodata.kaek_douleies_operating'),[(1,)])

    def test_cadastre_existing_table_needs_only_scoped_writer_privileges(self):
        self.publish()
        role='epol_cadastre_writer_'+uuid.uuid4().hex[:8]
        self.query(f'''CREATE ROLE {role} NOLOGIN;
            GRANT USAGE ON SCHEMA sp_geodata TO {role};
            GRANT SELECT,INSERT,DELETE ON sp_geodata.kaek_douleies_operating TO {role};
            GRANT USAGE ON SEQUENCE sp_geodata.kaek_douleies_operating_gid_seq TO {role}''')
        try:
            self.assertEqual(self.query("SELECT has_schema_privilege(%s,'sp_geodata','CREATE')",(role,)),[(False,)])
            with closing(psycopg2.connect(self.dsn)) as conn:
                with conn.cursor() as cur:
                    cur.execute('SET LOCAL ROLE '+role)
                cad._replace_layer(conn,self.table,self.fields,self.rows(2))
            self.assertEqual(self.query('SELECT objectid FROM sp_geodata.kaek_douleies_operating'),[(2,)])
        finally:
            self.query(f'DROP OWNED BY {role}; DROP ROLE {role}')

    def test_cadastre_parcel_diff_includes_property_counts_and_ignores_import_ids(self):
        table='kaek_parcels_operating'
        fields=[('OBJECTID','bigint'),('KAEK','text'),('MAIN_USE','text'),
                ('DESCR','text'),('PROP_HOR','bigint'),('PROP_VERT','bigint'),('NOTE','text')]
        polygon=self.rows()[0][-1]
        initial=[(1,'K1','MAIN','parcel',13,0,'old',polygon),
                 (2,'K2','MAIN','parcel',0,None,None,polygon),
                 (3,'K3','MAIN','parcel',3,0,'same',polygon)]
        changed=[(101,'K1','MAIN','parcel',12,2,'new',polygon),
                 (2,'K2','MAIN','parcel',8,0,None,polygon),
                 (103,'K3','MAIN','parcel',3,0,'same',polygon)]
        def publish(rows):
            with closing(psycopg2.connect(self.dsn)) as conn:
                return cad._replace_layer(conn,table,fields,rows)[1]
        self.assertIsNone(publish(initial))
        diff=publish(changed)
        self.assertEqual(diff['new'],[])
        self.assertEqual(diff['removed'],[])
        self.assertEqual(diff['geom_changed'],[])
        self.assertEqual(diff['use_changed'],[])
        self.assertEqual(diff['source_ids_changed'],[('K1',1,101),('K3',3,103)])
        by_key={row['kaek']:row['fields'] for row in diff['attributes_changed']}
        self.assertEqual(set(by_key),{'K1','K2'})
        self.assertEqual(by_key['K1']['prop_hor'],{'old':13,'new':12})
        self.assertEqual(by_key['K1']['prop_vert'],{'old':0,'new':2})
        self.assertEqual(by_key['K2']['prop_hor'],{'old':0,'new':8})
        self.assertEqual(by_key['K2']['prop_vert'],{'old':None,'new':0})
        repeated=publish(changed)
        self.assertEqual(repeated['attributes_changed'],[])
        self.assertEqual(repeated['source_ids_changed'],[])

    def test_cadastre_waits_for_reader_then_publishes_without_changing_relation(self):
        self.publish()
        before=self.metadata()
        with closing(psycopg2.connect(self.dsn)) as reader, ThreadPoolExecutor(max_workers=1) as executor:
            with reader.cursor() as cur:
                cur.execute('SELECT objectid FROM sp_geodata.kaek_douleies_operating')
                self.assertEqual(cur.fetchall(),[(1,)])
                pending=executor.submit(self.publish,2)
                try:
                    deadline=time.monotonic()+3
                    while True:
                        blocked=self.query("SELECT count(*) FROM pg_locks WHERE relation='sp_geodata.kaek_douleies_operating'::regclass AND mode='AccessExclusiveLock' AND NOT granted")[0][0]
                        if blocked:break
                        if time.monotonic()>deadline:
                            self.fail('Writer never reached its destination lock')
                        time.sleep(.01)
                    self.assertFalse(pending.done())
                    cur.execute('SELECT objectid FROM sp_geodata.kaek_douleies_operating')
                    self.assertEqual(cur.fetchall(),[(1,)])
                finally:
                    reader.commit()
                pending.result(timeout=5)
        self.assertEqual(self.metadata(),before)
        self.assertEqual(self.query('SELECT objectid FROM sp_geodata.kaek_douleies_operating'),[(2,)])

    def test_emsy_real_upsert_retains_missing_rows_and_detects_unchanged_records(self):
        self.query(emsy.DDL)  # Administrative setup is separate from ordinary sync.
        connect = lambda: psycopg2.connect(self.dsn)
        with patch.object(emsy,'get_connection',side_effect=connect):
            self.assertEqual(emsy.load([feature(1),feature(2)])['new'],2)
            self.assertEqual(emsy.load([feature(1)])['unchanged'],1)
            changed = feature(1)
            changed['attributes']['TOPWNYMIO']='updated'
            self.assertEqual(emsy.load([changed])['updated'],1)
        self.assertEqual(self.query('SELECT objectid,topwnymio FROM sp_geodata.ydrolipsies_emsy ORDER BY objectid'),[(1,'updated'),(2,None)])
        self.assertEqual(self.query('SELECT ST_SRID(geom) FROM sp_geodata.ydrolipsies_emsy GROUP BY 1'),[(2100,)])

    def test_emsy_restricted_writer_needs_no_schema_ddl_and_rolls_back_all_rows(self):
        self.query(emsy.DDL)
        self.query('ALTER TABLE sp_geodata.ydrolipsies_emsy ADD CHECK(objectid < 3)')
        role = 'epol_emsy_writer_' + uuid.uuid4().hex[:8]
        self.query(f'''CREATE ROLE {role} NOLOGIN;
            GRANT USAGE ON SCHEMA sp_geodata TO {role};
            GRANT SELECT,INSERT,UPDATE ON sp_geodata.ydrolipsies_emsy TO {role};
            GRANT USAGE ON SEQUENCE sp_geodata.ydrolipsies_emsy_gid_seq TO {role}''')

        def connect():
            conn = psycopg2.connect(self.dsn)
            with conn.cursor() as cur:
                cur.execute('SET LOCAL ROLE ' + role)
            return conn

        try:
            self.assertEqual(self.query("SELECT has_schema_privilege(%s,'sp_geodata','CREATE')", (role,)), [(False,)])
            before = self.metadata()
            with patch.object(emsy, 'get_connection', side_effect=connect):
                self.assertEqual(emsy.load([feature(1), feature(2)])['new'], 2)
                self.assertEqual(emsy.load([feature(1)])['unchanged'], 1)
                changed = feature(1)
                changed['attributes']['TOPWNYMIO'] = 'updated'
                self.assertEqual(emsy.load([changed])['updated'], 1)
                stored = self.query('SELECT * FROM sp_geodata.ydrolipsies_emsy ORDER BY objectid')
                changed['attributes']['TOPWNYMIO'] = 'must roll back'
                with self.assertRaisesRegex(LoadError, 'rolled back'):
                    emsy.load([changed, feature(3)])
                self.assertEqual(self.query('SELECT * FROM sp_geodata.ydrolipsies_emsy ORDER BY objectid'), stored)
            self.assertEqual(self.metadata(), before)
        finally:
            self.query(f'DROP OWNED BY {role}; DROP ROLE {role}')

    def test_raster_real_upsert_preserves_all_manual_judgements(self):
        source=(Path(__file__).resolve().parents[1]/'sql/004_raster_sheets.sql').read_text(encoding='utf-8')
        self.query(source[source.index('CREATE TABLE IF NOT EXISTS'):source.index('COMMENT ON TABLE')])
        values=dict.fromkeys(['collection','filename','rel_path','abs_path','file_size_bytes','file_mtime','file_hash',
            'extent_wkt','footprint_wkt','width_px','height_px','bands','dtype','res_x','res_y','crs_epsg','nodata',
            'compression','is_tiled','has_overviews','overview_count','role','nominal_scale','georef_rms',
            'georef_method','georef_points','georef_by','georef_date','doc_ref','doc_date','notes'])
        values.update(collection='test',filename='test.tif',rel_path='test.tif',abs_path='/test.tif',
            extent_wkt='POLYGON((0 0,10 0,10 10,0 10,0 0))',role='historical',nominal_scale=1000,
            georef_rms=.2,georef_method='affine',georef_points=6,georef_by='surveyor',georef_date='2026-10-27',
            doc_ref='TEST',doc_date='1980-01-01',notes='manual',width_px=10,crs_epsg=2100)
        self.query(ingest_rasters.UPSERT,values)
        self.query("UPDATE sp_geodata.raster_sheets SET useful_area=extent")
        manual='role,nominal_scale,georef_rms,georef_method,georef_points,georef_by,georef_date,doc_ref,doc_date,notes,ST_AsEWKB(useful_area)'
        before=self.query('SELECT '+manual+' FROM sp_geodata.raster_sheets')
        values.update(role='working',nominal_scale=5000,georef_rms=10,georef_method='other',georef_points=3,
            georef_by='other',georef_date=None,doc_ref='OTHER',doc_date=None,notes='overwrite',width_px=20)
        self.query(ingest_rasters.UPSERT,values)
        self.assertEqual(self.query('SELECT '+manual+' FROM sp_geodata.raster_sheets'),before)
        self.assertEqual(self.query('SELECT count(*),max(width_px) FROM sp_geodata.raster_sheets'),[(1,20)])

    @unittest.skipIf(ingest_rasters.MISSING,'Install requirements.txt for actual GeoTIFF ingestion')
    def test_raster_cli_keeps_successes_before_and_after_a_database_failure(self):
        import numpy as np
        import rasterio
        from rasterio.transform import from_origin
        source=(Path(__file__).resolve().parents[1]/'sql/004_raster_sheets.sql').read_text(encoding='utf-8')
        self.query(source[source.index('CREATE TABLE IF NOT EXISTS'):source.index('COMMENT ON TABLE')])
        self.query("ALTER TABLE sp_geodata.raster_sheets ADD CHECK(filename<>'b_bad.tif')")
        with tempfile.TemporaryDirectory() as directory:
            for name in ('a.tif','b_bad.tif','c.tif'):
                with rasterio.open(Path(directory)/name,'w',driver='GTiff',width=8,height=8,count=1,
                    dtype='uint8',crs='EPSG:2100',transform=from_origin(420000,4120000,1,1)) as dst:
                    dst.write(np.full((1,8,8),100,dtype='uint8'))
            with patch.object(ingest_rasters,'db_connect',side_effect=lambda:psycopg2.connect(self.dsn)), \
                 patch('sys.argv',['ingest_rasters.py','--collection','test','--root',directory,'--commit']):
                self.assertEqual(ingest_rasters.main(),1)
        self.assertEqual(self.query('SELECT filename FROM sp_geodata.raster_sheets ORDER BY filename'),[('a.tif',),('c.tif',)])
