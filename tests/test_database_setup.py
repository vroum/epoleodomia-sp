"""Migration plans, history integrity, CLI isolation and transaction ownership."""

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest
import json
from unittest.mock import MagicMock, patch

import database_setup as setup
import sync_all
from tests.support import OfflineCase


class MigrationFileTests(unittest.TestCase):
    def test_frozen_baseline_has_no_destructive_or_transaction_control_statements(self):
        migration = setup.load_migrations()[0]
        statements = [line for line in migration.statement.splitlines() if not line.lstrip().startswith("--")]
        self.assertNotRegex("\n".join(statements), r"(?im)^\s*(DROP|TRUNCATE|DELETE|COMMIT|ROLLBACK)\b")
        self.assertIn("SET LOCAL search_path", migration.statement)
        self.assertEqual(len(migration.checksum), 64)

    def test_contract_is_part_of_migration_checksum(self):
        migration = setup.load_migrations()[1]
        self.assertIsNotNone(migration.contract)
        with tempfile.TemporaryDirectory() as directory:
            for source in setup.MIGRATIONS.iterdir():
                if source.suffix in (".sql", ".json"):
                    (Path(directory)/source.name).write_bytes(source.read_bytes())
            path = Path(directory)/Path(migration.filename).with_suffix(".json")
            path.write_bytes(path.read_bytes()+b"\n")
            changed = setup.load_migrations(directory)[1]
        self.assertNotEqual(changed.checksum, migration.checksum)
        self.assertEqual(setup.load_migrations()[0].checksum,
                         '749c2012592514359d683efe568ce220c0d60447e3af5071acf6881754cce5f4')

    def test_only_explicit_view_rendering_variants_are_accepted(self):
        expected={'relations':{'view':{'kind':'v','columns':{'value':'integer'},'constraints':[],
                  'view_definition':'SELECT 1 AS value;', 'view_definition_variants':['SELECT (1) AS value;']}}}
        current={'view':{'kind':'v','columns':{'value':'integer'},'constraints':[],
                 'view_definition':'SELECT (1) AS value;'}}
        with patch.object(setup,'read_structure',return_value=current):
            self.assertEqual(setup.contract_findings(MagicMock(),expected),())
            current['view']['view_definition']='SELECT 2 AS value;'
            self.assertTrue(any('View definition differs' in f for f in setup.contract_findings(MagicMock(),expected)))

    def test_invalid_contracts_are_rejected_before_connecting(self):
        original = setup.load_migrations()[1].contract
        for invalid in ({}, dict(original, format_version=99), dict(original, before={}),
                        dict(original, recreated_views=[{}]), dict(original, recreated_views=['building_blocks'])):
            with self.subTest(invalid=invalid.keys()):
                with tempfile.TemporaryDirectory() as directory:
                    (Path(directory)/'0001_test.sql').write_text('SELECT 1;', encoding='utf-8')
                    (Path(directory)/'0001_test.json').write_text(json.dumps(invalid), encoding='utf-8')
                    with self.assertRaises(setup.SetupError):
                        setup.load_migrations(directory)

    def test_migration_names_order_gaps_duplicates_empty_and_encoding_are_checked(self):
        for files in ({}, {"wrong.sql": b"SELECT 1;"}, {"0002_later.sql": b"SELECT 1;"},
                      {"0001_a.sql": b"SELECT 1;", "0001_b.sql": b"SELECT 2;"},
                      {"0001_a.sql": b""}, {"0001_a.sql": b"SELECT 1;\r\n"},
                      {"0001_a.sql": b"\xef\xbb\xbfSELECT 1;"}):
            with self.subTest(files=files):
                with tempfile.TemporaryDirectory() as directory:
                    for name, content in files.items():
                        (Path(directory)/name).write_bytes(content)
                    with self.assertRaises(setup.SetupError):
                        setup.load_migrations(directory)


class SetupOwnershipTests(OfflineCase):
    def setUp(self):
        super().setUp()
        self.factory = MagicMock()
        self.conn = self.factory.return_value
        self.cursor = self.conn.cursor.return_value.__enter__.return_value
        self.cursor.fetchone.return_value = (True,)
        self.migration = setup.Migration(1, "0001_test.sql", "checksum", "SELECT 'baseline';")
        self.start_patch(patch.object(setup, "load_migrations", return_value=(self.migration,)))
        self.inspect = self.start_patch(patch.object(setup, "inspect_plan"))
        self.start_patch(patch.object(setup, "baseline_findings", return_value=()))

    def test_default_is_read_only_and_does_not_write_even_when_changes_are_pending(self):
        self.inspect.return_value = setup.SetupPlan("new", (self.migration,))
        result = setup.run_setup(connect=self.factory)
        self.assertEqual(result.state, "new")
        self.assertEqual(self.factory.call_args.kwargs["options"], "-c default_transaction_read_only=on")
        self.conn.commit.assert_not_called()
        self.conn.rollback.assert_called_once_with()
        self.conn.close.assert_called_once_with()
        for call in self.cursor.execute.call_args_list:
            self.assertNotIn("CREATE", str(call))
            self.assertNotIn("INSERT", str(call))

    def test_apply_commits_baseline_and_ledger_together(self):
        self.inspect.return_value = setup.SetupPlan("new", (self.migration,))
        setup.run_setup(apply=True, connect=self.factory)
        statements = [call.args[0] for call in self.cursor.execute.call_args_list]
        self.assertIn(self.migration.statement, statements)
        insert = next(c for c in self.cursor.execute.call_args_list if c.args[0].startswith("INSERT INTO"))
        self.assertEqual(insert.args[1], (1, "0001_test.sql", "checksum", "applied"))
        self.conn.commit.assert_called_once_with()
        self.conn.close.assert_called_once_with()

    def test_adoption_records_baseline_without_replaying_sql(self):
        self.inspect.return_value = setup.SetupPlan("legacy", (self.migration,))
        setup.run_setup(apply=True, adopt=True, connect=self.factory)
        self.assertFalse(any(c.args[0] == self.migration.statement for c in self.cursor.execute.call_args_list))
        insert = next(c for c in self.cursor.execute.call_args_list if c.args[0].startswith("INSERT INTO"))
        self.assertEqual(insert.args[1][-1], "adopted")

    def test_blocked_or_up_to_date_plan_does_not_create_metadata_or_commit(self):
        for plan in (setup.SetupPlan("blocked", (), ("mismatch",)), setup.SetupPlan("managed", ())):
            with self.subTest(plan=plan):
                self.cursor.reset_mock()
                self.inspect.return_value = plan
                setup.run_setup(apply=True, connect=self.factory)
                self.conn.commit.assert_not_called()
                self.assertFalse(any(str(c.args[0]).startswith("CREATE") for c in self.cursor.execute.call_args_list))

    def test_concurrent_setup_lock_failure_does_not_inspect_or_write(self):
        self.cursor.fetchone.return_value = (False,)
        with self.assertRaisesRegex(setup.SetupError, "in progress"):
            setup.run_setup(apply=True, connect=self.factory)
        self.inspect.assert_not_called()
        self.conn.commit.assert_not_called()
        self.conn.close.assert_called_once_with()

    def test_migration_failure_rolls_back_and_never_commits(self):
        self.inspect.return_value = setup.SetupPlan("new", (self.migration,))
        def execute(statement, params=None):
            if statement == self.migration.statement:
                raise RuntimeError("migration failed")
        self.cursor.execute.side_effect = execute
        with self.assertRaisesRegex(RuntimeError, "migration failed"):
            setup.run_setup(apply=True, connect=self.factory)
        self.conn.rollback.assert_called_once_with()
        self.conn.commit.assert_not_called()
        self.conn.close.assert_called_once_with()

    def test_cleanup_failure_preserves_the_original_error(self):
        self.inspect.side_effect = ValueError("inspection failed")
        self.conn.rollback.side_effect = RuntimeError("cleanup failed")
        with self.assertRaisesRegex(ValueError, "inspection failed"):
            setup.run_setup(connect=self.factory)
        self.conn.close.assert_called_once_with()

    def test_postcondition_failure_rolls_back_sql_and_history(self):
        contract = {'before':{}, 'after':{}}
        migration = setup.Migration(2,'0002_test.sql','checksum','SELECT 42;',contract)
        with patch.object(setup,'load_migrations',return_value=(migration,)), \
                patch.object(setup,'upgrade_findings',return_value=()), \
                patch.object(setup,'contract_findings',return_value=('missing generated expression',)):
            self.inspect.return_value=setup.SetupPlan('managed',(migration,))
            with self.assertRaisesRegex(setup.SetupError,'postconditions failed'):
                setup.run_setup(apply=True,connect=self.factory)
        self.conn.commit.assert_not_called()
        self.conn.rollback.assert_called_once_with()

    def test_init_alias_never_syncs_and_rejects_combined_modes_before_work(self):
        with patch.object(setup, "main", return_value=0) as main, \
                patch.object(sync_all, "test_connection", side_effect=AssertionError("Unexpected sync connection")), \
                patch("sys.argv", ["sync_all.py", "--init"]):
            with self.assertRaises(SystemExit) as result:
                sync_all.main()
            self.assertEqual(result.exception.code, 0)
            main.assert_called_once_with([])
        for option in ("--rasters-only", "--rasters", "--test", "--track", "--list"):
            with self.subTest(option=option):
                with patch("sys.argv", ["sync_all.py", "--init", option]), \
                        patch.object(sync_all, "init_database", side_effect=AssertionError("Must reject before work")), \
                        patch("sys.stderr", StringIO()):
                    with self.assertRaises(SystemExit) as result:
                        sync_all.main()
                    self.assertEqual(result.exception.code, 2)
