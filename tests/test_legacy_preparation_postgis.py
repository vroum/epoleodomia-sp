"""Reviewed legacy preparation against the actual schema-only snapshot, PG18 only."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import psycopg2
from psycopg2 import extensions

import database_setup as setup
import prepare_legacy_database as prep


MARKER = 'EPOL disposable preparation tests'


@unittest.skipUnless(os.environ.get('EPOL_TEST_PREPARATION_DSN'),
                     'Run tests/run_preparation_tests.py for isolated PostgreSQL 18 tests')
class LegacyPreparationPostGISTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dsn = os.environ['EPOL_TEST_PREPARATION_DSN']
        target = extensions.parse_dsn(cls.dsn)
        if target.get('host') != '127.0.0.1' or target.get('dbname') != 'epol_setup_test':
            raise RuntimeError('Preparation tests require disposable localhost epol_setup_test')
        with closing(psycopg2.connect(cls.dsn)) as conn, conn.cursor() as cur:
            cur.execute("SELECT shobj_description(oid,'pg_database'),current_setting('server_version_num')::int FROM pg_database WHERE datname=current_database()")
            if cur.fetchone() != (MARKER, int(conn.server_version)) or conn.server_version//10000 != 18:
                raise RuntimeError('Preparation tests require the PG18 disposable marker')

    def setUp(self):
        self.conn = psycopg2.connect(self.dsn)
        self.addCleanup(self.conn.close)
        self.conn.autocommit = True
        self.query('DROP SCHEMA IF EXISTS epoleodomia CASCADE; DROP SCHEMA IF EXISTS epol_meta CASCADE')
        self.query('CREATE SCHEMA epoleodomia AUTHORIZATION docker')
        self.query((Path(__file__).parent/'fixtures/installed_tee_schema.sql').read_text(encoding='utf-8'))
        self.query('SET search_path TO epoleodomia,public')
        self.query('''GRANT USAGE ON SCHEMA epoleodomia TO codex_reader;
            GRANT SELECT ON ALL TABLES IN SCHEMA epoleodomia TO codex_reader;
            GRANT SELECT ON ALL SEQUENCES IN SCHEMA epoleodomia TO codex_reader;
            INSERT INTO epoleodomia.building_blocks(objectid,ot_num,geom)
                VALUES (7,'original',ST_GeomFromText('POLYGON((0 0,10 0,10 10,0 10,0 0))',2100));
            INSERT INTO epoleodomia.building_regs_lot(objectid,date_pareklisis) VALUES (6,'1977'),(6,'1985');
            INSERT INTO epoleodomia.land_uses_ers(objectid,per_cat_eid) VALUES (8,'preserve text');
            INSERT INTO epoleodomia.raster_catalog(filename,url_georef,download_status,georef_rms)
                VALUES ('keep.tif','https://source.test/keep.tif','downloaded',.123);
        ''')
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.backup = Path(directory.name)/'synthetic-test-marker.dump'
        raw = b'PGDMP synthetic test marker, not an actual backup'
        self.backup.write_bytes(raw)
        self.backup_sha = hashlib.sha256(raw).hexdigest()

    def query(self, statement, params=None):
        with self.conn.cursor() as cur:
            cur.execute(statement, params)
            return cur.fetchall() if cur.description else None

    def connect(self, **kwargs):
        return psycopg2.connect(self.dsn, options='-c role=docker '+kwargs.get('options', ''))

    def preview(self, factory=None):
        return prep.run_preparation(connect=factory or self.connect)

    def apply(self, plan=None, factory=None):
        plan = plan or self.preview(factory)
        return prep.run_preparation(apply=True, expected_plan=plan.plan_hash,
            backup_path=self.backup, backup_sha256=self.backup_sha, connect=factory or self.connect)

    def original(self):
        with closing(self.connect()) as conn, conn.cursor() as cur:
            structure = setup.read_structure(cur)
            columns = prep.original_columns(structure, prep.load_recipe()[0]['before']['relations'])
            return columns, structure, prep.data_fingerprints(cur, columns, structure), prep.preserved_metadata(cur, columns)

    def assert_legacy(self):
        self.assertEqual(self.query("SELECT to_regnamespace('epol_meta'),to_regclass('epoleodomia.sync_runs')"), [(None,None)])
        self.assertEqual(self.query('SELECT ot_num FROM epoleodomia.building_blocks'), [('original',)])

    def test_reader_preview_is_ready_read_only_and_cannot_apply(self):
        factory = lambda **kw: psycopg2.connect(self.dsn, options='-c role=codex_reader '+kw.get('options',''))
        before = self.original()
        plan = self.preview(factory)
        self.assertEqual((plan.state,plan.findings,plan.can_apply), ('ready',(),False))
        self.assertEqual(self.original(), before)
        self.assert_legacy()

    def test_direct_recipe_without_controller_guard_cannot_make_partial_changes(self):
        before = self.original()
        statement = prep.load_recipe()[1]
        with self.assertRaisesRegex(psycopg2.errors.RaiseException,'Use prepare_legacy_database.py'):
            self.query(statement)
        self.assertEqual(self.original(),before)
        self.assert_legacy()

    def test_prepare_preserves_data_metadata_and_records_history_atomically(self):
        self.query("""ALTER VIEW epoleodomia.v_oroi_domisis_flags SET(security_barrier=true);
            COMMENT ON VIEW epoleodomia.v_oroi_domisis_flags IS 'keep view';
            COMMENT ON COLUMN epoleodomia.v_oroi_domisis_flags.ot_num IS 'keep column';
            GRANT SELECT(ot_num) ON epoleodomia.v_oroi_domisis_flags TO codex_reader;
        """)
        columns, structure, data, metadata = self.original()
        result = self.apply()
        self.assertTrue(result.applied)
        self.assertEqual(result.state, 'prepared')
        with closing(self.connect()) as conn, conn.cursor() as cur:
            self.assertEqual(prep.data_fingerprints(cur, columns, structure), data)
            after = prep.preserved_metadata(cur, columns, metadata['functions'])
            after['indexes'] = {n:after['indexes'][n] for n in metadata['indexes']}
            self.assertEqual(after, metadata)
        self.assertEqual(self.query('SELECT version,mode FROM epol_meta.schema_migrations ORDER BY version'), [(1,'adopted'),(2,'adopted')])
        self.assertEqual(self.query('SELECT count(*) FROM epol_meta.schema_preparations'), [(1,)])
        self.assertEqual(self.query("""SELECT DISTINCT pg_get_userbyid(c.relowner)
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='epol_meta' OR (n.nspname='epoleodomia'
                AND c.relname IN ('sync_runs','changelog','land_use_codes'))"""), [('docker',)])
        self.assertEqual(self.query("SELECT ST_Contains(geom,label_point) FROM epoleodomia.building_blocks"), [(True,)])
        self.assertEqual(self.query("SELECT has_table_privilege('codex_reader','epol_meta.schema_migrations','SELECT'),has_table_privilege('codex_reader','epol_meta.schema_migrations','INSERT')"), [(True,False)])
        reader = lambda **kw: psycopg2.connect(self.dsn, options='-c role=codex_reader '+kw.get('options',''))
        self.assertEqual(self.preview(reader).state, 'prepared')
        self.assertFalse(setup.run_setup(connect=self.connect).findings)

    def test_repeat_is_noop_and_receipt_tampering_is_blocked(self):
        plan = self.preview()
        self.apply(plan)
        before = self.query('SELECT * FROM epol_meta.schema_preparations')
        self.assertFalse(self.apply(plan).applied)
        self.assertEqual(self.query('SELECT * FROM epol_meta.schema_preparations'), before)
        self.query("UPDATE epol_meta.schema_preparations SET checksum=repeat('0',64)")
        self.assertEqual(self.preview().state, 'blocked')

    def test_changed_view_body_is_blocked_without_replacement(self):
        body = self.query("SELECT pg_get_viewdef('epoleodomia.v_oroi_domisis_flags'::regclass,false)")[0][0]
        self.query('CREATE OR REPLACE VIEW epoleodomia.v_oroi_domisis_flags AS '+body.strip().removesuffix(';')+' LIMIT 0')
        self.assertEqual(self.preview().state, 'blocked')
        self.assert_legacy()

    def test_external_view_dependency_is_blocked(self):
        self.query('CREATE VIEW public.epol_preparation_consumer AS SELECT * FROM epoleodomia.v_oroi_domisis_flags')
        self.addCleanup(self.query,'DROP VIEW IF EXISTS public.epol_preparation_consumer')
        plan = self.preview()
        self.assertTrue(any('epol_preparation_consumer' in v for v in plan.findings))
        self.assert_legacy()

    def test_nonowner_grant_chain_on_live_only_view_is_blocked(self):
        role = 'epol_preparation_grantor'
        self.query(f'''CREATE ROLE {role} NOLOGIN;
            GRANT USAGE ON SCHEMA epoleodomia TO {role};
            GRANT SELECT ON epoleodomia.v_oroi_domisis_flags TO {role} WITH GRANT OPTION;
            SET ROLE {role};
            GRANT SELECT ON epoleodomia.v_oroi_domisis_flags TO codex_reader;
            RESET ROLE''')
        self.addCleanup(self.query,f'DROP OWNED BY {role} CASCADE; DROP ROLE {role}')
        self.assertTrue(any('Non-owner grant chains' in v for v in self.preview().findings))
        self.assert_legacy()

    def test_duplicate_objectid_and_nonpolygon_are_reported_before_ddl(self):
        self.query('INSERT INTO epoleodomia.building_blocks(objectid) VALUES (7)')
        self.assertTrue(any('Duplicate non-NULL objectid' in v for v in self.preview().findings))
        self.query('DELETE FROM epoleodomia.building_blocks WHERE geom IS NULL')
        self.query("INSERT INTO epoleodomia.forest_maps(objectid,geom) VALUES (10,ST_GeomFromText('POINT(0 0)',2100))")
        self.assertTrue(any('Non-polygon geometry' in v for v in self.preview().findings))
        self.assert_legacy()

    def test_partial_preparation_and_reserved_name_collision_are_blocked(self):
        self.query('ALTER TABLE epoleodomia.natura_2000 ADD COLUMN is_deleted boolean')
        self.assertTrue(any('Partial preparation' in v for v in self.preview().findings))
        self.query('ALTER TABLE epoleodomia.natura_2000 DROP COLUMN is_deleted')
        self.query('ALTER TABLE epoleodomia.building_blocks ADD CONSTRAINT manual_objectid_unique UNIQUE(objectid)')
        self.assertTrue(any('Unreviewed source constraint' in v for v in self.preview().findings))
        self.query('ALTER TABLE epoleodomia.building_blocks DROP CONSTRAINT manual_objectid_unique')
        self.query('CREATE INDEX epol_reconcile_idx_1 ON epoleodomia.building_blocks(objectid)')
        self.assertTrue(any('Reserved preparation index' in v for v in self.preview().findings))

    def test_reviewed_plan_is_bound_to_current_metadata_and_counts(self):
        plan = self.preview()
        self.query("COMMENT ON TABLE epoleodomia.building_blocks IS 'changed after preview'")
        with self.assertRaisesRegex(setup.SetupError, 'Plan changed'):
            self.apply(plan)
        self.assert_legacy()

    def test_postcondition_failure_restores_old_view_oids_and_all_ddl(self):
        before = self.original()
        original = setup.contract_findings
        def fail_target(cur, contract):
            if 'sync_runs' in contract['relations']:
                return ('injected final validation failure',)
            return original(cur,contract)
        plan = self.preview()
        oid = self.query("SELECT 'epoleodomia.v_oroi_domisis_flags'::regclass::oid")
        with patch.object(setup,'contract_findings',side_effect=fail_target):
            with self.assertRaisesRegex(setup.SetupError,'postconditions failed'):
                self.apply(plan)
        self.assertEqual(self.query("SELECT 'epoleodomia.v_oroi_domisis_flags'::regclass::oid"), oid)
        self.assertEqual(self.original(), before)
        self.assert_legacy()

    def test_preservation_failure_rolls_back_every_change(self):
        original = prep.data_fingerprints
        calls = []
        def drift(*args):
            value = original(*args)
            calls.append(True)
            if len(calls)==2:
                value['building_blocks'] = (-1,'injected difference')
            return value
        plan = self.preview()
        with patch.object(prep,'data_fingerprints',side_effect=drift):
            with self.assertRaisesRegex(setup.SetupError,'Original source values changed'):
                self.apply(plan)
        self.assert_legacy()

    def test_advisory_lock_refuses_concurrent_schema_operation(self):
        plan = self.preview()
        with closing(psycopg2.connect(self.dsn)) as other, other.cursor() as cur:
            cur.execute('SELECT pg_advisory_xact_lock(%s,%s)', setup.LOCK_KEY)
            with self.assertRaisesRegex(setup.SetupError, 'Another schema operation'):
                self.apply(plan)
        self.assert_legacy()

    def test_pending_writer_commit_is_visible_after_lock_acquisition(self):
        plan = self.preview()
        with closing(psycopg2.connect(self.dsn)) as writer, ThreadPoolExecutor(max_workers=1) as executor:
            with writer.cursor() as cur:
                cur.execute("UPDATE epoleodomia.building_blocks SET ot_num='pending'")
                future = executor.submit(self.apply,plan)
                try:
                    deadline = time.monotonic()+4
                    while not self.query("SELECT count(*) FROM pg_locks WHERE relation='epoleodomia.building_blocks'::regclass AND mode='AccessExclusiveLock' AND NOT granted")[0][0]:
                        if time.monotonic()>deadline:
                            self.fail('Preparation did not reach the held source lock')
                        time.sleep(.01)
                finally:
                    writer.commit()
                self.assertTrue(future.result(timeout=15).applied)
        self.assertEqual(self.query('SELECT ot_num FROM epoleodomia.building_blocks'), [('pending',)])

    def test_metadata_preservation_failure_rolls_back(self):
        original = prep.preserved_metadata
        calls = []
        def drift(*args, **kwargs):
            value = original(*args, **kwargs)
            calls.append(True)
            if len(calls)==2:
                value['relations']['building_blocks']['comment'] = 'injected difference'
            return value
        plan = self.preview()
        with patch.object(prep,'preserved_metadata',side_effect=drift):
            with self.assertRaisesRegex(setup.SetupError,'Original ownership/grants'):
                self.apply(plan)
        self.assert_legacy()

    def test_receipt_insert_failure_rolls_back_source_and_version_history(self):
        class RejectReceipt(extensions.cursor):
            def execute(self, statement, params=None):
                if isinstance(statement,str) and statement.startswith('INSERT INTO epol_meta.schema_preparations'):
                    raise psycopg2.errors.CheckViolation('injected receipt failure')
                return super().execute(statement, params)
        factory = lambda **kw: psycopg2.connect(self.dsn,cursor_factory=RejectReceipt,
            options='-c role=docker '+kw.get('options',''))
        with self.assertRaisesRegex(psycopg2.errors.CheckViolation,'receipt failure'):
            self.apply(factory=factory)
        self.assert_legacy()
