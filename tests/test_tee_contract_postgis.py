"""Real v1->v2 upgrade and sync contracts in a marked disposable DB only."""

from contextlib import closing
import os
from pathlib import Path
import tempfile
import unittest
import json
import uuid
from unittest.mock import patch

import psycopg2
from psycopg2 import extensions

import database_setup as setup
import load_postgis
from sync_safety import LoadError
from tests.test_database_setup_postgis import MARKER


POLYGON = 'POLYGON((0 0,10 0,10 10,0 10,0 0))'
MULTI = 'MULTIPOLYGON(((0 0,4 0,4 10,0 10,0 0)),((6 0,10 0,10 10,6 10,6 0)))'


@unittest.skipUnless(os.environ.get("EPOL_TEST_SETUP_DSN"),
                     "Run tests/run_setup_tests.py for disposable schema tests")
class TeeContractPostGISTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dsn = os.environ["EPOL_TEST_SETUP_DSN"]
        target = extensions.parse_dsn(cls.dsn)
        if target.get("host") not in ("127.0.0.1", "localhost", "::1") or target.get("dbname") != "epol_setup_test":
            raise RuntimeError("Upgrade tests require disposable localhost epol_setup_test")
        with closing(psycopg2.connect(cls.dsn, connect_timeout=5)) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT shobj_description(oid,'pg_database') FROM pg_database WHERE datname=current_database()")
                if cur.fetchone() != (MARKER,):
                    raise RuntimeError("Database is not marked as disposable")

    def setUp(self):
        self.conn = self.connect()
        self.addCleanup(self.conn.close)
        self.conn.autocommit = True
        self.query("DROP SCHEMA IF EXISTS epoleodomia CASCADE")
        self.query("DROP SCHEMA IF EXISTS epol_meta CASCADE")

    def connect(self, **kwargs):
        return psycopg2.connect(self.dsn, connect_timeout=5, options=kwargs.get("options", ""))

    def query(self, statement, params=None, fetch_one=True):
        with self.conn.cursor() as cur:
            cur.execute(statement, params)
            if cur.description:
                return cur.fetchone() if fetch_one else cur.fetchall()

    def run_setup(self, **kwargs):
        return setup.run_setup(connect=self.connect, **kwargs)

    def install_v1(self):
        with tempfile.TemporaryDirectory() as directory:
            baseline = setup.load_migrations()[0]
            (Path(directory)/baseline.filename).write_text(baseline.statement, encoding="utf-8", newline="\n")
            self.run_setup(apply=True, migrations_dir=directory)
        self.assertEqual(self.query("SELECT version FROM epol_meta.schema_migrations"), (1,))

    def test_duplicate_lot_replacement_needs_no_sequence_owner_and_rolls_back(self):
        self.run_setup(apply=True)
        role = 'epol_lot_writer_' + uuid.uuid4().hex[:8]
        self.query(f'''CREATE ROLE {role} NOLOGIN;
            GRANT USAGE ON SCHEMA epoleodomia TO {role};
            GRANT SELECT,INSERT,TRUNCATE ON epoleodomia.building_regs_lot TO {role};
            GRANT USAGE ON SEQUENCE epoleodomia.building_regs_lot_id_seq TO {role}''')

        def connect():
            conn = self.connect()
            with conn.cursor() as cur:
                cur.execute('SET LOCAL ROLE ' + role)
            return conn

        def payload(invalid=False):
            polygon = {'type': 'Polygon', 'coordinates': [
                [[420000,4120000],[420010,4120000],[420010,4120010],
                 [420000,4120010],[420000,4120000]]]}
            rows = [{'type': 'Feature', 'properties': {'OBJECTID': 42, 'OROS_TYPE': kind},
                     'geometry': polygon} for kind in ('normal', 'exception')]
            if invalid:
                rows[1]['geometry'] = {'type': 'Point', 'coordinates': [420000,4120000]}
            return {'type': 'FeatureCollection', 'features': rows}

        def rows():
            return self.query('SELECT id,objectid,oros_type,ST_AsEWKB(geom) '
                              'FROM epoleodomia.building_regs_lot ORDER BY id', fetch_one=False)

        try:
            self.assertEqual(self.query("SELECT has_schema_privilege(%s,'epoleodomia','CREATE')", (role,)), (False,))
            before = self.query("SELECT oid,relowner,relacl FROM pg_class WHERE oid='epoleodomia.building_regs_lot'::regclass")
            with patch.object(load_postgis, 'get_connection', side_effect=connect):
                self.assertEqual(load_postgis.load_geojson_to_table(payload(), 'building_regs_lot'), 2)
                first = rows()
                self.assertEqual(load_postgis.load_geojson_to_table(payload(), 'building_regs_lot'), 2)
                second = rows()
                self.assertGreater(second[0][0], first[-1][0])
                self.assertEqual([(r[1], r[2]) for r in second], [(42, 'normal'), (42, 'exception')])
                with self.assertRaisesRegex(LoadError, 'rolled back'):
                    load_postgis.load_geojson_to_table(payload(invalid=True), 'building_regs_lot')
                self.assertEqual(rows(), second)
                self.query('CREATE TABLE epoleodomia.lot_consumer '
                           '(ref integer REFERENCES epoleodomia.building_regs_lot(id))')
                self.query('INSERT INTO epoleodomia.lot_consumer VALUES (%s)', (second[0][0],))
                with self.assertRaisesRegex(LoadError, 'rolled back'):
                    load_postgis.load_geojson_to_table(payload(), 'building_regs_lot')
                self.assertEqual(rows(), second)
                self.assertEqual(self.query('SELECT ref FROM epoleodomia.lot_consumer'), (second[0][0],))
            self.assertEqual(self.query("SELECT oid,relowner,relacl FROM pg_class WHERE oid='epoleodomia.building_regs_lot'::regclass"), before)
        finally:
            self.query(f'DROP OWNED BY {role}; DROP ROLE {role}')

    def test_upgrade_preserves_data_and_adds_polygonal_and_generated_contracts(self):
        self.install_v1()
        self.query("INSERT INTO epoleodomia.building_blocks(objectid,geom) VALUES (7,ST_GeomFromText(%s,2100))", (POLYGON,))
        before = self.query("SELECT id,ST_AsEWKB(geom) FROM epoleodomia.building_blocks")
        self.query("INSERT INTO epoleodomia.building_regs_lot(objectid,date_pareklisis) VALUES (42,'longer-than-ten'),(42,NULL)")
        self.query("INSERT INTO epoleodomia.building_regs_coverage(synt_kalypsis) VALUES ('60')")
        self.assertEqual([m.version for m in self.run_setup().pending], [2])
        self.run_setup(apply=True)
        self.assertEqual(self.query("SELECT id,ST_AsEWKB(geom) FROM epoleodomia.building_blocks"), before)
        self.assertEqual(self.query("SELECT ST_Contains(geom,label_point) FROM epoleodomia.building_blocks"), (True,))
        self.assertEqual(self.query("SELECT count(*) FROM epoleodomia.building_regs_lot"), (2,))
        self.assertEqual(self.query("SELECT synt_kalypsis FROM epoleodomia.building_regs_coverage"), (60.0,))
        self.query("INSERT INTO epoleodomia.building_regs_height(geom) VALUES (ST_GeomFromText(%s,2100))", (MULTI,))
        with self.assertRaises(psycopg2.errors.CheckViolation):
            self.query("INSERT INTO epoleodomia.building_regs_height(geom) VALUES (ST_SetSRID(ST_Point(0,0),2100))")
        with self.assertRaises(psycopg2.errors.InvalidParameterValue):
            self.query("INSERT INTO epoleodomia.building_regs_height(geom) VALUES (ST_GeomFromText(%s,4326))", (POLYGON,))
        self.assertFalse(self.run_setup().findings)

    def test_view_uses_maximum_overlap_zone_fallback_and_fek_sources(self):
        self.run_setup(apply=True)
        self.query("INSERT INTO epoleodomia.building_blocks(ot_num,geom) VALUES ('OT',ST_GeomFromText(%s,2100))", (POLYGON,))
        self.query("INSERT INTO epoleodomia.building_regs_height(max_height_m,geom) VALUES (7.5,ST_GeomFromText(%s,2100))", (MULTI,))
        self.query("INSERT INTO epoleodomia.building_regs_height(max_height_m,geom) VALUES (99,ST_GeomFromText('POLYGON((4 0,6 0,6 10,4 10,4 0))',2100))")
        self.query("INSERT INTO epoleodomia.building_regs_height(max_height_m,is_deleted,geom) VALUES (100,true,ST_GeomFromText(%s,2100))", (POLYGON,))
        self.query("INSERT INTO epoleodomia.building_regs_coefficient_zones(sd_timh,sd_tomeas,geom) VALUES (.8,'A',ST_GeomFromText(%s,2100))", (POLYGON,))
        self.assertEqual(self.query("SELECT max_height_m,height_match_pct,building_coefficient,coefficient_source,coefficient_match_pct FROM epoleodomia.v_building_blocks_regulations"),
                         (7.5,80,.8,'zone',100))
        self.query("INSERT INTO epoleodomia.settlement_boundaries(fek) VALUES ('SET')")
        self.query("INSERT INTO epoleodomia.land_uses_gps(fek) VALUES ('GPS')")
        self.assertEqual(self.query("SELECT fek FROM epoleodomia.v_fek_references ORDER BY fek", fetch_one=False), [('GPS',),('SET',)])
        self.query("INSERT INTO epoleodomia.raster_catalog(fek,filename,download_status,file_size_bytes) VALUES ('DOC','map.tif','downloaded',1048576)")
        self.assertEqual(self.query("SELECT total_size_bytes,total_size_mb FROM epoleodomia.v_rasters_by_fek"), (1048576,1))

    def test_view_metadata_permissions_owner_and_options_survive_recreation(self):
        self.install_v1()
        self.query("CREATE ROLE epol_v2_reader NOLOGIN")
        self.query("GRANT SELECT ON epoleodomia.v_building_blocks_regulations TO epol_v2_reader WITH GRANT OPTION")
        self.query("GRANT SELECT (ot_num) ON epoleodomia.v_building_blocks_regulations TO PUBLIC")
        self.query("COMMENT ON VIEW epoleodomia.v_building_blocks_regulations IS 'reviewed view'")
        self.query("COMMENT ON COLUMN epoleodomia.v_building_blocks_regulations.ot_num IS 'reviewed column'")
        self.query("ALTER VIEW epoleodomia.v_building_blocks_regulations SET (security_barrier=true)")
        self.query("ALTER VIEW epoleodomia.v_building_blocks_regulations OWNER TO epol_v2_reader")
        self.query("ALTER DEFAULT PRIVILEGES IN SCHEMA epoleodomia GRANT SELECT ON TABLES TO PUBLIC")
        try:
            self.run_setup(apply=True)
            self.assertEqual(self.query("SELECT pg_get_userbyid(relowner),obj_description(oid,'pg_class'),reloptions FROM pg_class WHERE oid='epoleodomia.v_building_blocks_regulations'::regclass"),
                             ('epol_v2_reader','reviewed view',['security_barrier=true']))
            self.assertEqual(self.query("SELECT col_description(attrelid,attnum), EXISTS (SELECT 1 FROM aclexplode(attacl) WHERE grantee=0 AND privilege_type='SELECT') FROM pg_attribute WHERE attrelid='epoleodomia.v_building_blocks_regulations'::regclass AND attname='ot_num'"),
                             ('reviewed column',True))
            self.assertEqual(self.query("SELECT EXISTS (SELECT 1 FROM pg_class c, LATERAL aclexplode(c.relacl) a WHERE c.oid='epoleodomia.v_building_blocks_regulations'::regclass AND a.grantee=0)"), (False,))
            self.assertEqual(self.query("SELECT has_table_privilege('epol_v2_reader','epoleodomia.v_building_blocks_regulations','SELECT WITH GRANT OPTION')"), (True,))
        finally:
            self.query("ALTER DEFAULT PRIVILEGES IN SCHEMA epoleodomia REVOKE SELECT ON TABLES FROM PUBLIC")
            self.query("DROP OWNED BY epol_v2_reader CASCADE")
            self.query("DROP ROLE epol_v2_reader")

    def test_unknown_dependent_view_blocks_preview_and_apply_without_cascade(self):
        self.install_v1()
        self.query("CREATE VIEW epoleodomia.custom_consumer AS SELECT ot_num FROM epoleodomia.v_building_blocks_regulations")
        oid = self.query("SELECT 'epoleodomia.v_building_blocks_regulations'::regclass::oid")
        for apply in (False,True):
            plan=self.run_setup(apply=apply)
            self.assertTrue(any('custom_consumer' in f for f in plan.findings))
        self.assertEqual(self.query("SELECT 'epoleodomia.v_building_blocks_regulations'::regclass::oid"),oid)
        self.assertEqual(self.query("SELECT count(*) FROM epol_meta.schema_migrations"),(1,))

    def test_non_owner_grant_chains_are_blocked_before_recreation(self):
        self.install_v1()
        self.query("CREATE ROLE epol_grantor NOLOGIN; CREATE ROLE epol_grantee NOLOGIN")
        try:
            self.query("GRANT USAGE ON SCHEMA epoleodomia TO epol_grantor")
            self.query("GRANT SELECT ON epoleodomia.v_building_blocks_regulations TO epol_grantor WITH GRANT OPTION")
            self.query("SET ROLE epol_grantor")
            self.query("GRANT SELECT ON epoleodomia.v_building_blocks_regulations TO epol_grantee")
            self.query("RESET ROLE")
            plan=self.run_setup(apply=True)
            self.assertTrue(any('Non-owner grant chains' in f for f in plan.findings))
            self.assertEqual(self.query("SELECT count(*) FROM epol_meta.schema_migrations"),(1,))
        finally:
            self.query("RESET ROLE")
            self.query("DROP OWNED BY epol_grantor CASCADE; DROP OWNED BY epol_grantee CASCADE")
            self.query("DROP ROLE epol_grantor; DROP ROLE epol_grantee")

    def test_contract_checksum_and_adoption_prefix_are_enforced(self):
        self.run_setup(apply=True)
        with tempfile.TemporaryDirectory() as directory:
            for path in setup.MIGRATIONS.iterdir():
                if path.suffix in ('.sql','.json'):
                    (Path(directory)/path.name).write_bytes(path.read_bytes())
            path=Path(directory)/'0002_live_tee_contract.json'
            path.write_bytes(path.read_bytes()+b'\n')
            self.assertEqual(self.run_setup(apply=True,migrations_dir=directory).state,'blocked')
        self.query("UPDATE epol_meta.schema_migrations SET mode='adopted' WHERE version=2")
        self.assertEqual(self.run_setup(apply=True).state,'blocked')

    def test_custom_source_view_definition_blocks_replacement(self):
        self.install_v1()
        original=self.query("SELECT pg_get_viewdef('epoleodomia.v_fek_references'::regclass,false)")[0]
        self.query("CREATE OR REPLACE VIEW epoleodomia.v_fek_references AS "+original.strip().removesuffix(';')+' LIMIT 0')
        plan=self.run_setup(apply=True)
        self.assertTrue(any('v_fek_references' in f for f in plan.findings))
        self.assertEqual(self.query("SELECT count(*) FROM epol_meta.schema_migrations"),(1,))

    def test_unparseable_coverage_rolls_back_data_views_and_history(self):
        self.install_v1()
        self.query("INSERT INTO epoleodomia.building_regs_coverage(synt_kalypsis) VALUES ('60%')")
        oid=self.query("SELECT 'epoleodomia.v_building_blocks_regulations'::regclass::oid")
        with self.assertRaises(psycopg2.errors.InvalidTextRepresentation):
            self.run_setup(apply=True)
        self.assertEqual(self.query("SELECT synt_kalypsis FROM epoleodomia.building_regs_coverage"),('60%',))
        self.assertEqual(self.query("SELECT 'epoleodomia.v_building_blocks_regulations'::regclass::oid"),oid)
        self.assertEqual(self.query("SELECT count(*) FROM epol_meta.schema_migrations"),(1,))

    def test_latest_unmanaged_schema_is_adopted_without_replaying_ddl(self):
        self.run_setup(apply=True)
        oid=self.query("SELECT 'epoleodomia.v_building_blocks_regulations'::regclass::oid")
        self.query("DROP SCHEMA epol_meta CASCADE")
        plan=self.run_setup(adopt=True)
        self.assertEqual((plan.adopt_version,plan.findings),(2,()))
        self.run_setup(adopt=True,apply=True)
        self.assertEqual(self.query("SELECT version,mode FROM epol_meta.schema_migrations ORDER BY version",fetch_one=False),
                         [(1,'adopted'),(2,'adopted')])
        self.assertEqual(self.query("SELECT 'epoleodomia.v_building_blocks_regulations'::regclass::oid"),oid)
        self.assertFalse(self.run_setup().findings)

    def test_later_contract_can_adopt_a_prefix_with_an_intermediate_plain_migration(self):
        self.run_setup(apply=True)
        with tempfile.TemporaryDirectory() as directory:
            for path in setup.MIGRATIONS.iterdir():
                if path.suffix in ('.sql','.json'):
                    (Path(directory)/path.name).write_bytes(path.read_bytes())
            (Path(directory)/'0003_plain.sql').write_text('SELECT 1;',encoding='utf-8')
            (Path(directory)/'0004_snapshot.sql').write_text('SELECT 2;',encoding='utf-8')
            state=setup.load_migrations()[-1].contract['after']
            descriptor={'format_version':1,'before':state,'after':state}
            (Path(directory)/'0004_snapshot.json').write_text(json.dumps(descriptor),encoding='utf-8')
            self.run_setup(apply=True,migrations_dir=directory)
            self.query('DROP SCHEMA epol_meta CASCADE')
            plan=self.run_setup(adopt=True,apply=True,migrations_dir=directory)
            self.assertEqual(plan.adopt_version,4)
            self.assertFalse(self.run_setup(migrations_dir=directory).findings)
            self.assertEqual(self.query('SELECT mode FROM epol_meta.schema_migrations ORDER BY version',fetch_one=False),
                             [('adopted',)]*4)

    def test_generated_column_and_index_drift_are_checked_on_noop(self):
        self.run_setup(apply=True)
        self.query("ALTER INDEX epoleodomia.idx_building_blocks_label_point RENAME TO renamed_label_index")
        self.assertFalse(self.run_setup().findings)
        self.query("ALTER TABLE epoleodomia.building_blocks ALTER COLUMN label_point DROP EXPRESSION")
        self.assertTrue(any('label_point' in f for f in self.run_setup(apply=True).findings))
        self.query("DROP INDEX epoleodomia.renamed_label_index")
        self.assertTrue(any('Missing valid index' in f for f in self.run_setup().findings))

    def test_real_sync_omits_generated_column_and_recomputes_it(self):
        self.run_setup(apply=True)
        with patch.object(load_postgis,'get_connection',side_effect=self.connect):
            for mode in ('replace','upsert','track'):
                with self.subTest(mode=mode):
                    data={'type':'FeatureCollection','features':[{'type':'Feature',
                        'properties':{'OBJECTID':1,'OT_NUM':mode},
                        'geometry':{'type':'Polygon','coordinates':[[[0,0],[10,0],[10,10],[0,10],[0,0]]]}}]}
                    if mode=='track':
                        stats=load_postgis.load_geojson_with_tracking(data,'building_blocks')
                        self.assertEqual(stats['updated'],1)
                    else:
                        self.assertEqual(load_postgis.load_geojson_to_table(data,'building_blocks',truncate=mode=='replace'),1)
                    self.assertEqual(self.query("SELECT ot_num,ST_Contains(geom,label_point) FROM epoleodomia.building_blocks"),
                                     (mode,True))

    def diagram(self, oid, *, fek='TEST', filename='map.tif'):
        return {'type':'Feature','properties':{'OBJECTID':oid,'FEK':fek,
            'GEOREF_DIAGRAM_URL':'https://source.test/'+filename,
            'INITIAL_DIAGRAM_URL':'https://source.test/raw.tif',
            'GGRS87_DIAGR_GEOREF_RMS':1,'INIT_DIAGR_SCALE_DENOMINATOR':1000},
            'geometry':{'type':'Polygon','coordinates':[[[0,0],[10,0],[10,10],[0,10],[0,0]]]}}

    def load_diagrams(self, mode, features):
        data={'type':'FeatureCollection','features':features}
        if mode=='track':
            return load_postgis.load_geojson_with_tracking(data,'planning_diagrams')
        return load_postgis.load_geojson_to_table(data,'planning_diagrams',truncate=mode=='replace')

    def test_diagram_load_refreshes_catalog_without_resetting_downloads_or_judgements(self):
        self.run_setup(apply=True)
        with patch.object(load_postgis,'get_connection',side_effect=self.connect):
            self.load_diagrams('replace',[self.diagram(2),self.diagram(1)])
            self.assertEqual(self.query('SELECT count(*),min(planning_diagram_objectid) FROM epoleodomia.raster_catalog'),(1,1))
            self.query("""UPDATE epoleodomia.raster_catalog SET download_status='downloaded',
                local_path_georef='keep/map.tif',file_size_bytes=42,georef_rms=.123,
                original_scale=500,bbox=ST_GeomFromText(%s,2100)""",(POLYGON,))
            manual='download_status,local_path_georef,file_size_bytes,georef_rms,original_scale,ST_AsEWKB(bbox)'
            before=self.query('SELECT '+manual+' FROM epoleodomia.raster_catalog')
            for mode in ('replace','upsert','track'):
                with self.subTest(mode=mode):
                    data=[self.diagram(2,fek=mode),self.diagram(1,fek=mode)]
                    self.load_diagrams(mode,data)
                    self.assertEqual(self.query('SELECT '+manual+' FROM epoleodomia.raster_catalog'),before)
                    self.assertEqual(self.query('SELECT fek FROM epoleodomia.raster_catalog'),(mode,))
                    timestamp=self.query('SELECT updated_at FROM epoleodomia.raster_catalog')
                    self.load_diagrams(mode,data)
                    self.assertEqual(self.query('SELECT updated_at FROM epoleodomia.raster_catalog'),timestamp)
            self.query("UPDATE epoleodomia.planning_diagrams SET is_deleted=true; INSERT INTO epoleodomia.planning_diagrams(objectid,georef_diagram_url) VALUES (3,'   ')")
            with closing(self.connect()) as conn, conn.cursor() as cur:
                load_postgis._refresh_derived_catalog(cur,'epoleodomia','planning_diagrams')
                conn.commit()
            self.assertEqual(self.query('SELECT count(*) FROM epoleodomia.raster_catalog'),(1,))

    def test_catalog_failure_rolls_back_diagram_changes_in_every_load_mode(self):
        self.run_setup(apply=True)
        with patch.object(load_postgis,'get_connection',side_effect=self.connect):
            self.load_diagrams('replace',[self.diagram(1)])
            self.query("ALTER TABLE epoleodomia.raster_catalog ADD CHECK(filename<>'bad.tif')")
            for mode in ('replace','upsert','track'):
                with self.subTest(mode=mode):
                    with self.assertRaisesRegex(LoadError,'rolled back'):
                        self.load_diagrams(mode,[self.diagram(1,fek='CHANGED'),self.diagram(2,filename='bad.tif')])
                    self.assertEqual(self.query('SELECT objectid,fek FROM epoleodomia.planning_diagrams'),(1,'TEST'))
                    self.assertEqual(self.query('SELECT count(*),min(fek) FROM epoleodomia.raster_catalog'),(1,'TEST'))

    def test_real_sync_run_summary_persists_record_totals_and_table_count(self):
        self.run_setup(apply=True)
        with patch.object(load_postgis,'get_connection',side_effect=self.connect):
            run_id=load_postgis.start_sync_run('test')
            self.assertIsNotNone(run_id)
            load_postgis.complete_sync_run(run_id,{'new':2,'updated':3,'deleted':1,'tables_synced':4})
        self.assertEqual(self.query('SELECT status,records_new,records_updated,records_deleted,tables_synced FROM epoleodomia.sync_runs WHERE id=%s',(run_id,)),
                         ('success',2,3,1,4))
