"""Installed/legacy schema contracts, only inside a marked disposable database."""

from contextlib import closing
import os
from pathlib import Path
import unittest

import psycopg2
from psycopg2 import extensions

from planning_data import PlanningData
from tests.test_database_setup_postgis import MARKER


@unittest.skipUnless(os.environ.get("EPOL_TEST_SETUP_DSN"),
                     "Run tests/run_setup_tests.py for disposable schema tests")
class SchemaCompatibilityPostGISTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dsn = os.environ["EPOL_TEST_SETUP_DSN"]
        target = extensions.parse_dsn(cls.dsn)
        if target.get("host") not in ("127.0.0.1", "localhost", "::1") or target.get("dbname") != "epol_setup_test":
            raise RuntimeError("Schema tests require the disposable localhost epol_setup_test database")
        with closing(psycopg2.connect(cls.dsn, connect_timeout=5)) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT shobj_description(oid, 'pg_database') FROM pg_database WHERE datname=current_database()")
                if cur.fetchone() != (MARKER,):
                    raise RuntimeError("Database is not marked as disposable")

    def setUp(self):
        self.conn = psycopg2.connect(self.dsn, connect_timeout=5)
        self.addCleanup(self.conn.close)
        self.conn.autocommit = True
        self.query("DROP SCHEMA IF EXISTS epoleodomia CASCADE")
        self.query("DROP SCHEMA IF EXISTS sp_geodata CASCADE")
        self.query("CREATE SCHEMA epoleodomia")
        self.query("CREATE SCHEMA sp_geodata")

    def query(self, statement, params=None, fetch_one=False):
        with self.conn.cursor() as cur:
            cur.execute(statement, params)
            if cur.description:
                return cur.fetchone() if fetch_one else cur.fetchall()

    def apply_registry(self):
        path = Path(__file__).resolve().parents[1]/"sql/005_fek_documents.sql"
        self.query(path.read_text(encoding="utf-8"))

    def seed_registry_sources(self, *, reverse=False):
        self.query("""
            CREATE TABLE sp_geodata.fek_publications (
                fek text, fek_pdf_url text, local_pdf_path text, downloaded boolean, notes text);
            CREATE TABLE epoleodomia.planning_diagrams (
                fek text, fek_file_url text, is_deleted boolean);
            CREATE TABLE epoleodomia.fek_no_diagrams (fek text, fek_file_url text);
            INSERT INTO sp_geodata.fek_publications VALUES
                ('LOCAL','local-url','/archive/1981_1/local.pdf',true,'keep local provenance');
        """)
        diagrams = [(' LOCAL ', 'remote-url', False), ('DUP', 'z-url', False),
                    ('DUP', 'a-url', False), ('DUP', 'deleted-url', True),
                    ('NULL', ' ', False), (' ', 'ignored-url', False), (None, 'ignored-url', False)]
        references = [('DUP', '0-fallback'), ('NULL', 'fallback-url'), ('ONLY', 'only-url')]
        for fek, url, deleted in reversed(diagrams) if reverse else diagrams:
            self.query("INSERT INTO epoleodomia.planning_diagrams VALUES (%s,%s,%s)", (fek,url,deleted))
        for fek, url in reversed(references) if reverse else references:
            self.query("INSERT INTO epoleodomia.fek_no_diagrams VALUES (%s,%s)", (fek,url))

    def test_natura_catalog_detects_legacy_added_and_dropped_columns(self):
        self.query("CREATE TABLE epoleodomia.natura_2000 (sitecode text)")
        legacy = PlanningData(self.query)
        self.assertEqual(legacy._natura_active_filter(), "TRUE")
        self.query("ALTER TABLE epoleodomia.natura_2000 ADD COLUMN is_deleted boolean")
        self.assertEqual(legacy._natura_active_filter(), "TRUE")
        self.assertEqual(PlanningData(self.query)._natura_active_filter(), "NOT COALESCE(n.is_deleted, false)")
        self.query("ALTER TABLE epoleodomia.natura_2000 DROP COLUMN is_deleted")
        self.assertEqual(PlanningData(self.query)._natura_active_filter(), "TRUE")

    def test_registry_deduplicates_sources_and_uses_stable_nonblank_url_preference(self):
        self.seed_registry_sources()
        self.apply_registry()
        expected = [('DUP','a-url','planning_diagrams'), ('LOCAL','local-url','fek_publications'),
                    ('NULL','fallback-url','fek_no_diagrams'), ('ONLY','only-url','fek_no_diagrams')]
        self.assertEqual(self.query("SELECT fek,pdf_url,source FROM sp_geodata.fek_documents ORDER BY fek"), expected)
        self.query("TRUNCATE epoleodomia.planning_diagrams, epoleodomia.fek_no_diagrams, sp_geodata.fek_documents")
        # Reinsert the same candidates in the opposite order.
        self.query("DROP TABLE sp_geodata.fek_publications, epoleodomia.planning_diagrams, epoleodomia.fek_no_diagrams")
        self.seed_registry_sources(reverse=True)
        self.apply_registry()
        self.assertEqual(self.query("SELECT fek,pdf_url,source FROM sp_geodata.fek_documents ORDER BY fek"), expected)

    def test_registry_completion_preserves_existing_local_document_and_manual_values(self):
        self.seed_registry_sources()
        self.apply_registry()
        self.assertEqual(self.query("SELECT rel_path,nas_path,downloaded,notes FROM sp_geodata.fek_documents WHERE fek='LOCAL'"),
            [('1981_1/local.pdf','/archive/1981_1/local.pdf',True,'keep local provenance')])
        self.query("""UPDATE sp_geodata.fek_documents SET pdf_url='curated-url', rel_path='custom/doc.pdf',
            abs_path='confirmed/doc.pdf', downloaded=true, source='manual', notes='reviewed', file_size_bytes=123
            WHERE fek='DUP'""")
        fields="fek,pdf_url,rel_path,abs_path,downloaded,source,notes,file_size_bytes"
        before=self.query("SELECT "+fields+" FROM sp_geodata.fek_documents ORDER BY fek")
        self.apply_registry()
        self.assertEqual(self.query("SELECT "+fields+" FROM sp_geodata.fek_documents ORDER BY fek"), before)

    def test_failed_registry_backfill_rolls_back_registry_creation(self):
        self.seed_registry_sources()
        self.query("INSERT INTO sp_geodata.fek_publications VALUES (NULL,NULL,'/bad/file.pdf',true,NULL)")
        with self.assertRaises(psycopg2.errors.NotNullViolation):
            self.apply_registry()
        self.query("ROLLBACK")
        self.assertEqual(self.query("SELECT to_regclass('sp_geodata.fek_documents')"), [(None,)])
        self.assertEqual(self.query("SELECT count(*) FROM sp_geodata.fek_publications"), [(2,)])
