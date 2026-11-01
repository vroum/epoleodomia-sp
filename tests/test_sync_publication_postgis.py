"""Atomic cross-domain writes and concurrent readers in marked disposable DBs."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
import os
from threading import Event
import time
import unittest
from unittest.mock import patch

import psycopg2
from psycopg2 import extensions, pool, sql

import database_setup
from database_sessions import read_only_snapshot
import enable_sync_publication as enable
from settings import DatabaseSettings
import setup_sync_writer
from sync_access import inspect_target
import sync_kaek_operating as cadastre
from sync_launcher import check_connection
import sync_publication as publication
import sync_ydrolipsies as emsy
from sync_safety import FetchError, LoadError
from tests.test_database_setup_postgis import MARKER
from tests.test_emsy_sync import feature as water_feature


GEOMETRY = {'type': 'Polygon', 'coordinates': [[[420000,4120000], [420010,4120000],
    [420010,4120010], [420000,4120010], [420000,4120000]]]}
FIELDS = (('OBJECTID', 'bigint'), ('KAEK', 'text'))
READER = 'epol_publication_reader'


def cadastre_fields(table):
    return FIELDS + ((('MAIN_USE', 'text'), ('DESCR', 'text')) if table == 'kaek_parcels_operating' else ())


def bundle(version):
    layers = []
    for service_name, service in publication.SERVICES.items():
        for item in service['layers']:
            features = []
            if item['table'] == 'building_blocks':
                features = [{'type': 'Feature', 'properties': {'OBJECTID': 1, 'TITLE': f'gen-{version}'}, 'geometry': GEOMETRY}]
            elif item['table'] == 'building_regs_lot':
                features = [{'type': 'Feature', 'properties': {'OBJECTID': 7, 'TITLE': f'gen-{version}-{n}'}, 'geometry': GEOMETRY} for n in ('a', 'b')]
            layers.append(publication.PreparedLayer('tee', item['table'],
                {'type': 'FeatureCollection', 'features': features}, service=service_name, layer_id=item['id']))
    for table, service in cadastre.LAYERS.items():
        fields = cadastre_fields(table)
        attributes = (version, 'TEST-' + table) + (('test-use', 'test-description') if table == 'kaek_parcels_operating' else ())
        rows = [attributes + (json.dumps(GEOMETRY),)]
        layers.append(publication.PreparedLayer('ktima', table, rows, fields, service))
    water = water_feature(1)
    water['attributes']['STATUS'] = f'gen-{version}'
    layers.append(publication.PreparedLayer('ydro', 'ydrolipsies_emsy', [water]))
    return layers


@unittest.skipUnless(os.environ.get('EPOL_TEST_SETUP_DSN'), 'Run tests/run_setup_tests.py')
class PublicationFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dsn = os.environ['EPOL_TEST_SETUP_DSN']
        target = extensions.parse_dsn(cls.dsn)
        if target.get('host') not in ('localhost', '127.0.0.1', '::1') or target.get('dbname') != 'epol_setup_test':
            raise RuntimeError('Requires marked disposable loopback epol_setup_test')
        with closing(psycopg2.connect(cls.dsn)) as conn, conn.cursor() as cur:
            cur.execute("SELECT shobj_description(oid,'pg_database') FROM pg_database WHERE datname=current_database()")
            if cur.fetchone() != (MARKER,):
                raise RuntimeError('Disposable database marker required')

    def connect(self, **kwargs):
        return psycopg2.connect(self.dsn, options=kwargs.get('options', ''))

    def query(self, statement, params=None):
        with self.owner.cursor() as cur:
            cur.execute(statement, params)
            return cur.fetchall() if cur.description else None

    def setUp(self):
        self.owner = self.connect()
        self.addCleanup(self.owner.close)
        self.owner.autocommit = True
        self.addCleanup(self.cleanup_roles)
        self.query('DROP SCHEMA IF EXISTS epoleodomia CASCADE; DROP SCHEMA IF EXISTS epol_meta CASCADE; '
                   'DROP SCHEMA IF EXISTS sp_geodata CASCADE; CREATE SCHEMA sp_geodata')
        self.assertFalse(database_setup.run_setup(apply=True, connect=self.connect).findings)
        for table in cadastre.LAYERS:
            columns = ','.join(name.lower() + ' ' + kind for name, kind in cadastre_fields(table))
            self.query(f'''CREATE TABLE sp_geodata.{table}({columns},
                geom geometry(MultiPolygon,2100),gid serial,synced_at timestamptz DEFAULT now())''')
        self.query('CREATE TABLE sp_geodata.posted_source(kaek text); CREATE VIEW sp_geodata.kaek_parcels_anartisi AS SELECT * FROM sp_geodata.posted_source')
        self.query(emsy.DDL)
        with self.owner.cursor() as cur:
            self.target = inspect_target(cur)
        setup_sync_writer.create_writer(self.connect, 'publication-test-writer', expected_target=self.target)
        parsed = extensions.parse_dsn(self.dsn)
        self.writer = DatabaseSettings(parsed['host'], int(parsed['port']), parsed['dbname'], 'epol_sync', 'publication-test-writer')
        # Initial publication establishes a realistic old generation, including
        # duplicate lot OBJECTIDs, audits and every domain's source rows.
        self.publish(1)
        self.query(f'CREATE ROLE {READER} LOGIN; GRANT USAGE ON SCHEMA epoleodomia,sp_geodata TO {READER}; '
                   f'GRANT SELECT ON ALL TABLES IN SCHEMA epoleodomia,sp_geodata TO {READER}')

    def cleanup_roles(self):
        for role in (READER, 'epol_sync'):
            if self.query('SELECT 1 FROM pg_roles WHERE rolname=%s', (role,)):
                self.query(f'DROP OWNED BY {role}; DROP ROLE {role}')

    def publish(self, version=2):
        return publication.run('all', self.writer, apply=True, collector=lambda mode: bundle(version))

    def values(self, query):
        return query('''SELECT title FROM epoleodomia.building_blocks WHERE objectid=1
            UNION ALL SELECT title FROM epoleodomia.building_regs_lot
            UNION ALL SELECT status FROM sp_geodata.ydrolipsies_emsy ORDER BY 1''')

    def metadata(self):
        return self.query("""SELECT c.oid,c.relname,c.relowner,c.relacl,c.reloptions
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname IN ('epoleodomia','sp_geodata','epol_meta') ORDER BY c.oid""")

    def fingerprints(self):
        result = {}
        for schema, table in self.query("""SELECT n.nspname,c.relname FROM pg_class c
            JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.relkind='r'
            AND n.nspname IN ('epoleodomia','sp_geodata','epol_meta') ORDER BY 1,2"""):
            with self.owner.cursor() as cur:
                cur.execute(sql.SQL("SELECT count(*),md5(COALESCE(string_agg(h,'' ORDER BY h),'')) FROM (SELECT md5(row_to_json(t)::text) h FROM {} t) z").format(sql.Identifier(schema, table)))
                result[schema, table] = cur.fetchone()
        return result

    def reader_pool(self):
        # Trust/password behavior is fixture-local; the reader has only SELECT.
        kwargs = extensions.parse_dsn(self.dsn)
        kwargs['user'] = READER
        kwargs['password'] = 'publication-test-reader'
        self.query(f"ALTER ROLE {READER} PASSWORD 'publication-test-reader'")
        return pool.SimpleConnectionPool(1, 2, **kwargs)

class PublicationPostGISTests(PublicationFixture):
    def test_all_domains_commit_together_preserving_metadata_and_duplicate_lots(self):
        metadata = self.metadata()
        result = self.publish()
        self.assertEqual(result['status'], 'committed')
        self.assertEqual(len(result['tables']), 59)
        self.assertEqual(self.values(self.query), [('gen-2',), ('gen-2',), ('gen-2-a',), ('gen-2-b',)])
        self.assertEqual(self.query('SELECT objectid,count(*) FROM epoleodomia.building_regs_lot GROUP BY objectid'), [(7,2)])
        self.assertEqual(self.metadata(), metadata)
        self.assertTrue(all(self.query(f'SELECT objectid FROM sp_geodata.{t}') == [(2,)] for t in cadastre.LAYERS))
        self.assertEqual(self.query('SELECT status FROM epoleodomia.sync_runs ORDER BY id'), [('success',), ('success',)])

    def test_failure_after_tee_cadastre_and_emsy_sql_rolls_back_every_row(self):
        before = self.fingerprints()
        metadata = self.metadata()
        real_load = emsy.load
        def fail_late(features, **kwargs):
            real_load(features, **kwargs)
            raise RuntimeError('injected after final domain SQL')
        with patch.object(emsy, 'load', side_effect=fail_late), self.assertRaisesRegex(RuntimeError, 'final domain'):
            self.publish()
        self.assertEqual(self.fingerprints(), before)
        self.assertEqual(self.metadata(), metadata)

    def test_cadastre_and_emsy_modes_each_have_one_audit_and_need_no_lot_delete(self):
        self.query('REVOKE DELETE ON epoleodomia.building_regs_lot FROM epol_sync')
        for mode in ('ktima', 'ydro'):
            layers = [layer for layer in bundle(2) if layer.domain == mode]
            result = publication.run(mode, self.writer, apply=True, collector=lambda selected: layers)
            self.assertEqual(result['status'], 'committed')
            self.assertEqual(len(result['tables']), 3 if mode == 'ktima' else 1)
            self.assertEqual(self.query('SELECT mode,status FROM epoleodomia.sync_runs WHERE id=%s', (result['audit_id'],)),
                             [('publication_' + mode, 'success')])

    def test_old_and_new_readers_continue_during_publication_and_keep_whole_generations(self):
        reader = self.reader_pool()
        staged, release = Event(), Event()
        real_replace = cadastre._replace_layer
        def pause_after_write(*args, **kwargs):
            result = real_replace(*args, **kwargs)
            staged.set()
            if not release.wait(10):
                raise RuntimeError('test synchronization timed out')
            return result
        old = [('gen-1',), ('gen-1',), ('gen-1-a',), ('gen-1-b',)]
        protected = (('epoleodomia','building_blocks'), ('epoleodomia','building_regs_lot'), ('sp_geodata','ydrolipsies_emsy'))
        try:
            with ThreadPoolExecutor(max_workers=1) as workers, read_only_snapshot(reader, protected_relations=protected) as snapshot:
                self.assertEqual(self.values(snapshot), old)
                with patch.object(cadastre, '_replace_layer', side_effect=pause_after_write):
                    future = workers.submit(self.publish)
                    try:
                        self.assertTrue(staged.wait(10))
                        # A fresh reader must complete even while all TEE writes
                        # and the first cadastral replacement remain uncommitted.
                        with read_only_snapshot(reader, protected_relations=protected) as fresh:
                            fresh.cursor.execute("SET LOCAL statement_timeout='1000ms'")
                            self.assertEqual(self.values(fresh), old)
                    finally:
                        release.set()
                    self.assertEqual(future.result(timeout=15)['status'], 'committed')
                self.assertEqual(self.values(snapshot), old)
            with read_only_snapshot(reader, protected_relations=protected) as snapshot:
                self.assertEqual(self.values(snapshot), [('gen-2',), ('gen-2',), ('gen-2-a',), ('gen-2-b',)])
        finally:
            release.set()
            reader.closeall()

    def test_source_failure_releases_session_lock_and_a_second_publisher_is_refused(self):
        before = self.fingerprints()
        def first_collector(mode):
            with self.assertRaisesRegex(LoadError, 'already running'):
                self.publish()
            raise FetchError('incomplete source')
        with self.assertRaises(FetchError):
            publication.run('all', self.writer, apply=True, collector=first_collector)
        self.assertEqual(self.fingerprints(), before)
        self.assertEqual(self.publish()['status'], 'committed')

    def test_existing_role_upgrade_changes_only_the_reviewed_grant(self):
        self.query('REVOKE DELETE ON epoleodomia.building_regs_lot FROM epol_sync')
        self.assertFalse(check_connection(self.writer))
        with self.assertRaisesRegex(LoadError, 'DELETE grant'):
            self.publish()
        before = self.fingerprints()
        enable.enable(self.connect, self.target)
        self.assertTrue(check_connection(self.writer))
        self.assertEqual(self.fingerprints(), before)
        enable.enable(self.connect, self.target)
        self.assertEqual(self.fingerprints(), before)

    def test_upgrade_postcheck_failure_rolls_back_the_grant(self):
        self.query('REVOKE DELETE ON epoleodomia.building_regs_lot FROM epol_sync')
        real_verify = enable.verify_access
        count = 0
        def verify(cur):
            nonlocal count
            count += 1
            real_verify(cur)
            if count == 2:
                raise ValueError('injected postcheck')
        with patch.object(enable, 'verify_access', side_effect=verify), self.assertRaisesRegex(ValueError, 'postcheck'):
            enable.enable(self.connect, self.target)
        self.assertFalse(check_connection(self.writer))

    def test_lot_foreign_key_consumers_are_rejected_without_cascading(self):
        self.query('''CREATE TABLE sp_geodata.protected_child(ref int REFERENCES epoleodomia.building_regs_lot(id) ON DELETE CASCADE);
            INSERT INTO sp_geodata.protected_child SELECT min(id) FROM epoleodomia.building_regs_lot''')
        before = self.fingerprints()
        with self.assertRaisesRegex(LoadError, 'foreign-key consumers'):
            self.publish()
        self.assertEqual(self.fingerprints(), before)

    def test_late_schema_drift_preserves_previous_whole_generation(self):
        self.query('ALTER TABLE sp_geodata.kaek_douleies_operating ADD COLUMN manual_note text DEFAULT \'keep\'')
        before = self.fingerprints()
        with self.assertRaisesRegex(LoadError, 'columns differ'):
            self.publish()
        self.assertEqual(self.fingerprints(), before)
