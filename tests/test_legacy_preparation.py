"""Preparation-file integrity, explicit apply evidence and read-only defaults."""
from contextlib import redirect_stderr, redirect_stdout
import hashlib
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import prepare_legacy_database as prep
from tests.support import OfflineCase


class PreparationFileTests(unittest.TestCase):
    def copy_recipe(self, directory):
        for source in (prep.RECIPE, prep.RECIPE.with_suffix('.sql')):
            (Path(directory)/source.name).write_bytes(source.read_bytes())
        return Path(directory)/prep.RECIPE.name

    def test_reviewed_recipe_is_bound_to_sql_and_frozen_target_versions(self):
        recipe, statement, checksum, migrations = prep.load_recipe()
        self.assertEqual([m.version for m in migrations], [1, 2])
        self.assertEqual(len(checksum), 64)
        self.assertIn("current_setting('epol.preparation_guard',true)", statement)
        self.assertEqual(statement.count('$epol_prepare$'), 2)
        self.assertTrue(statement.rstrip().endswith('$epol_prepare$;'))
        self.assertNotRegex(statement, r'(?im)^\s*(COMMIT|ROLLBACK|TRUNCATE|DELETE)\b')
        self.assertEqual(sum(map(len, recipe['absent_columns'].values())), 88)

    def test_sql_checksum_and_target_checksum_changes_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.copy_recipe(directory)
            path.with_suffix('.sql').write_bytes(path.with_suffix('.sql').read_bytes()+b'\nSELECT 1;\n')
            with self.assertRaisesRegex(prep.setup.SetupError, 'SQL checksum'):
                prep.load_recipe(path)
        with tempfile.TemporaryDirectory() as directory:
            path = self.copy_recipe(directory)
            value = json.loads(path.read_text(encoding='utf-8'))
            value['migration_checksums']['2'] = '0'*64
            path.write_text(json.dumps(value), encoding='utf-8')
            with self.assertRaisesRegex(prep.setup.SetupError, 'target migration checksums'):
                prep.load_recipe(path)

    def test_invalid_descriptor_and_encoding_are_rejected(self):
        for content in (b'[]', b'{}', b'\xef\xbb\xbf{}', b'{}\r\n'):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as directory:
                path = self.copy_recipe(directory)
                path.write_bytes(content)
                with self.assertRaises(prep.setup.SetupError):
                    prep.load_recipe(path)

    def test_backup_identity_is_checked_without_claiming_a_logical_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'synthetic.dump'
            raw = b'PGDMP synthetic format-marker fixture, not a restorable backup'
            path.write_bytes(raw)
            checksum = hashlib.sha256(raw).hexdigest()
            self.assertEqual(prep.check_backup(path, checksum), checksum)
            self.assertEqual(prep.check_backup(path, checksum.upper()), checksum)
            with self.assertRaisesRegex(prep.setup.SetupError, 'checksum mismatch'):
                prep.check_backup(path, '0'*64)
            path.write_bytes(b'not a PostgreSQL archive')
            with self.assertRaisesRegex(prep.setup.SetupError, 'custom-format'):
                prep.check_backup(path, checksum)


class PreparationOwnershipTests(OfflineCase):
    def test_apply_requires_exact_plan_and_backup_before_opening_any_connection(self):
        factory = MagicMock()
        for args in ({}, {'expected_plan':'a'*64}, {'expected_plan':'a'*64,'backup_path':'missing'}):
            with self.subTest(args=args), self.assertRaises(prep.setup.SetupError):
                prep.run_preparation(apply=True, connect=factory, **args)
        factory.assert_not_called()

    def test_preview_requests_read_only_startup_and_rolls_back_without_committing(self):
        factory = MagicMock()
        conn = factory.return_value
        plan = prep.Preparation('ready', {'host':'localhost','port':'1','database':'fixture'})
        with patch.object(prep, 'inspect', return_value=(plan, None)):
            self.assertEqual(prep.run_preparation(connect=factory), plan)
        self.assertIn('default_transaction_read_only=on', factory.call_args.kwargs['options'])
        calls = [c.args[0] for c in conn.cursor.return_value.__enter__.return_value.execute.call_args_list]
        self.assertIn('READ ONLY', calls[0])
        self.assertTrue(all(v.startswith('SET ') for v in calls))
        conn.commit.assert_not_called()
        conn.rollback.assert_called_once()
        conn.close.assert_called_once()

    def test_original_error_survives_failed_rollback_and_connection_is_closed(self):
        factory = MagicMock()
        factory.return_value.rollback.side_effect = RuntimeError('cleanup failed')
        with patch.object(prep, 'inspect', side_effect=prep.setup.SetupError('original failure')):
            with self.assertRaisesRegex(prep.setup.SetupError, 'original failure'):
                prep.run_preparation(connect=factory)
        factory.return_value.close.assert_called_once()

    def test_cli_apply_rejects_missing_evidence_before_execution(self):
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()), patch.object(prep, 'run_preparation') as run:
            with self.assertRaises(SystemExit) as result:
                prep.main(['--apply'])
        self.assertEqual(result.exception.code, 2)
        run.assert_not_called()
