"""Opt-in schema writes: only a marked disposable localhost test database."""

from contextlib import closing
import os
from pathlib import Path
import tempfile
import unittest

import psycopg2
from psycopg2 import extensions

import database_setup as setup


MARKER = "EPOL disposable setup tests"


@unittest.skipUnless(os.environ.get("EPOL_TEST_SETUP_DSN"),
                     "Run tests/run_setup_tests.py to provision a disposable PostGIS database")
class SetupPostGISTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dsn = os.environ["EPOL_TEST_SETUP_DSN"]
        target = extensions.parse_dsn(cls.dsn)
        if target.get("host") not in ("127.0.0.1", "localhost", "::1") or target.get("dbname") != "epol_setup_test":
            raise RuntimeError("Schema-write tests require the disposable localhost epol_setup_test database")
        with closing(psycopg2.connect(cls.dsn, connect_timeout=5)) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT shobj_description(oid, 'pg_database') FROM pg_database WHERE datname = current_database()")
                if cur.fetchone() != (MARKER,):
                    raise RuntimeError("Database is not marked as disposable; refusing schema-write tests")

    def setUp(self):
        self.conn = psycopg2.connect(self.dsn, connect_timeout=5)
        self.addCleanup(self.conn.close)
        self.conn.autocommit = True
        with self.conn.cursor() as cur:
            # Fixed names, and only after the explicit disposable marker check.
            cur.execute("DROP SCHEMA IF EXISTS epoleodomia CASCADE")
            cur.execute("DROP SCHEMA IF EXISTS epol_meta CASCADE")

    def connect(self, **kwargs):
        # Deliberately ignore the application's real target/credentials. Honor
        # only the read-only startup option used by preview transactions.
        return psycopg2.connect(self.dsn, connect_timeout=5, options=kwargs.get("options", ""))

    def run_setup(self, **kwargs):
        return setup.run_setup(connect=self.connect, **kwargs)

    def query(self, sql, params=None, fetch_one=True):
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            if cur.description is None:
                return None
            return cur.fetchone() if fetch_one else cur.fetchall()

    def install_legacy(self):
        with closing(self.connect()) as conn:
            with conn.cursor() as cur:
                cur.execute(setup.load_migrations()[0].statement)
            conn.commit()

    def migrations_with_upgrade(self, directory, statement):
        for path in setup.MIGRATIONS.iterdir():
            if path.suffix in (".sql", ".json"):
                (Path(directory)/path.name).write_bytes(path.read_bytes())
        (Path(directory)/"0003_test_upgrade.sql").write_text(statement, encoding="utf-8", newline="\n")

    def test_preview_and_init_target_are_read_only_and_create_nothing(self):
        plan = self.run_setup()
        self.assertEqual(plan.state, "new")
        self.assertEqual(self.query("SELECT to_regnamespace('epoleodomia'), to_regnamespace('epol_meta')"), (None, None))
        def guarded_connect(**kwargs):
            conn = self.connect(**kwargs)
            with conn.cursor() as cur:
                cur.execute("SHOW transaction_read_only")
                self.assertEqual(cur.fetchone(), ("on",))
            conn.rollback()
            return conn
        self.assertEqual(setup.run_setup(connect=guarded_connect).state, "new")

    def test_fresh_baseline_history_constraints_functions_and_noop_repeat(self):
        self.assertEqual(self.run_setup(apply=True).state, "new")
        self.assertEqual(self.query("SELECT version, mode FROM epol_meta.schema_migrations"), (1, "applied"))
        with closing(self.connect()) as check:
            with check.cursor() as cur:
                self.assertEqual(setup.contract_findings(cur, setup.load_migrations()[-1].contract["after"]), ())
        self.query("INSERT INTO epoleodomia.building_regs_lot(objectid) VALUES (42), (42) RETURNING objectid", fetch_one=False)
        self.assertEqual(self.query("SELECT count(*) FROM epoleodomia.building_regs_lot"), (2,))
        self.assertEqual(self.query("SELECT epoleodomia.translate_land_use_codes('21;22;211')"), ("Αμιγής Κατοικία",))
        self.assertEqual(self.query("SELECT * FROM epoleodomia.find_rasters_at_point(0,0)", fetch_one=False), [])
        plan = self.run_setup(apply=True)
        self.assertEqual((plan.state, plan.pending), ("managed", ()))
        self.assertEqual(self.query("SELECT count(*) FROM epoleodomia.building_regs_lot"), (2,))

    def test_existing_schema_is_never_rebuilt_implicitly(self):
        self.install_legacy()
        self.query("INSERT INTO epoleodomia.building_blocks(ot_num) VALUES ('KEEP') RETURNING id")
        plan = self.run_setup(apply=True)
        self.assertEqual(plan.state, "legacy")
        self.assertTrue(plan.findings)
        self.assertEqual(self.query("SELECT ot_num FROM epoleodomia.building_blocks"), ("KEEP",))
        self.assertEqual(self.query("SELECT to_regnamespace('epol_meta')"), (None,))

    def test_explicit_adoption_preserves_data_views_and_object_identity(self):
        self.install_legacy()
        self.query("INSERT INTO epoleodomia.building_blocks(ot_num) VALUES ('KEEP') RETURNING id")
        self.query("CREATE VIEW epoleodomia.custom_consumer AS SELECT ot_num FROM epoleodomia.building_blocks", fetch_one=False)
        oid = self.query("SELECT 'epoleodomia.building_blocks'::regclass::oid")
        plan = self.run_setup(adopt=True)
        self.assertFalse(plan.findings)
        self.assertEqual(self.query("SELECT to_regnamespace('epol_meta')"), (None,))
        self.assertEqual(self.run_setup(adopt=True, apply=True).state, "legacy")
        self.assertEqual(self.query("SELECT 'epoleodomia.building_blocks'::regclass::oid"), oid)
        self.assertEqual(self.query("SELECT * FROM epoleodomia.custom_consumer"), ("KEEP",))
        self.assertEqual(self.query("SELECT mode FROM epol_meta.schema_migrations"), ("adopted",))

    def test_incompatible_legacy_structure_is_blocked_without_repairs(self):
        self.install_legacy()
        self.query("ALTER TABLE epoleodomia.building_blocks DROP COLUMN ot_num CASCADE", fetch_one=False)
        plan = self.run_setup(adopt=True, apply=True)
        self.assertTrue(any("building_blocks.ot_num" in item for item in plan.findings))
        self.assertEqual(self.query("SELECT to_regnamespace('epol_meta')"), (None,))

    def test_lot_unique_objectid_contract_is_checked_during_adoption(self):
        self.install_legacy()
        self.query("ALTER TABLE epoleodomia.building_regs_lot ADD UNIQUE(objectid)", fetch_one=False)
        plan = self.run_setup(adopt=True, apply=True)
        self.assertTrue(any("allow duplicate" in item for item in plan.findings))
        self.assertEqual(self.query("SELECT to_regnamespace('epol_meta')"), (None,))
        self.query("ALTER TABLE epoleodomia.building_regs_lot DROP CONSTRAINT building_regs_lot_objectid_key")
        self.query("CREATE UNIQUE INDEX lot_objectid_only ON epoleodomia.building_regs_lot(objectid)")
        plan = self.run_setup(adopt=True, apply=True)
        self.assertTrue(any("allow duplicate" in item for item in plan.findings))

    def test_empty_schema_cannot_be_adopted(self):
        plan = self.run_setup(adopt=True, apply=True)
        self.assertEqual(plan.state, "blocked")
        self.assertEqual(self.query("SELECT to_regnamespace('epol_meta')"), (None,))

    def test_changed_migration_checksum_blocks_apply(self):
        self.run_setup(apply=True)
        with tempfile.TemporaryDirectory() as directory:
            baseline = setup.load_migrations()[0]
            (Path(directory)/baseline.filename).write_text(baseline.statement+"\n-- changed\n", encoding="utf-8", newline="\n")
            plan = self.run_setup(apply=True, migrations_dir=directory)
        self.assertEqual(plan.state, "blocked")
        self.assertEqual(self.query("SELECT count(*) FROM epol_meta.schema_migrations"), (2,))

    def test_unknown_or_gapped_history_is_blocked(self):
        self.run_setup(apply=True)
        self.query("INSERT INTO epol_meta.schema_migrations(version,filename,checksum,mode) "
                   "VALUES (3,'0003_unknown.sql','unknown','applied') RETURNING version")
        self.assertEqual(self.run_setup(apply=True).state, "blocked")

    def test_future_upgrade_preserves_rows_and_records_its_version(self):
        self.run_setup(apply=True)
        self.query("INSERT INTO epoleodomia.building_blocks(ot_num) VALUES ('KEEP') RETURNING id")
        with tempfile.TemporaryDirectory() as directory:
            self.migrations_with_upgrade(directory, "ALTER TABLE epoleodomia.building_blocks ADD COLUMN upgrade_note TEXT;")
            plan = self.run_setup(apply=True, migrations_dir=directory)
            self.assertEqual([m.version for m in plan.pending], [3])
            self.assertEqual(self.run_setup(apply=True, migrations_dir=directory).pending, ())
        self.assertEqual(self.query("SELECT ot_num,upgrade_note FROM epoleodomia.building_blocks"), ("KEEP", None))
        self.assertEqual(self.query("SELECT version FROM epol_meta.schema_migrations ORDER BY version", fetch_one=False), [(1,), (2,), (3,)])

    def test_failed_upgrade_rolls_back_ddl_and_history_while_preserving_baseline(self):
        self.run_setup(apply=True)
        self.query("INSERT INTO epoleodomia.building_blocks(ot_num) VALUES ('KEEP') RETURNING id")
        with tempfile.TemporaryDirectory() as directory:
            self.migrations_with_upgrade(directory, "CREATE TABLE epoleodomia.failed_probe(value integer); SELECT 1/0;")
            with self.assertRaises(psycopg2.errors.DivisionByZero):
                self.run_setup(apply=True, migrations_dir=directory)
        self.assertEqual(self.query("SELECT to_regclass('epoleodomia.failed_probe')"), (None,))
        self.assertEqual(self.query("SELECT ot_num FROM epoleodomia.building_blocks"), ("KEEP",))
        self.assertEqual(self.query("SELECT count(*) FROM epol_meta.schema_migrations"), (2,))

    def test_failed_fresh_install_rolls_back_baseline_and_metadata_together(self):
        with tempfile.TemporaryDirectory() as directory:
            self.migrations_with_upgrade(directory, "SELECT 1/0;")
            with self.assertRaises(psycopg2.errors.DivisionByZero):
                self.run_setup(apply=True, migrations_dir=directory)
        self.assertEqual(self.query("SELECT to_regnamespace('epoleodomia'),to_regnamespace('epol_meta')"), (None, None))

    def test_concurrent_setup_is_refused_without_creating_anything(self):
        with closing(self.connect()) as other:
            with other.cursor() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(%s,%s)", setup.LOCK_KEY)
            with self.assertRaisesRegex(setup.SetupError, "in progress"):
                self.run_setup(apply=True)
            self.assertEqual(self.query("SELECT to_regnamespace('epol_meta')"), (None,))
            other.rollback()

