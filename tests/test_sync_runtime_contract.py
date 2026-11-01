"""Regressions for sync/setup separation and truthful failure summaries."""

from contextlib import redirect_stderr
from io import StringIO
import json
from pathlib import Path
import tempfile
from unittest.mock import MagicMock, patch

import psycopg2

import load_postgis
from logger import SyncLogger
import sync_all
import sync_ydrolipsies as emsy
from sync_safety import FetchError, LoadError
from tests.support import OfflineCase
from tests.test_emsy_sync import feature


class TrackingSetupTests(OfflineCase):
    def test_tracking_check_never_alters_schema_or_commits(self):
        for columns in (['created_at', 'updated_at', 'is_deleted', 'deleted_at'],
                        ['created_at', 'updated_at']):
            with self.subTest(columns=columns):
                conn = MagicMock()
                cur = conn.cursor.return_value.__enter__.return_value
                cur.fetchall.return_value = [(name,) for name in columns]
                if len(columns) == 4:
                    self.assertTrue(load_postgis.check_tracking_columns(conn, 'epoleodomia', 'test'))
                else:
                    with self.assertRaisesRegex(LoadError, 'database_setup.py'):
                        load_postgis.check_tracking_columns(conn, 'epoleodomia', 'test')
                self.assertEqual(cur.execute.call_count, 1)
                self.assertTrue(cur.execute.call_args.args[0].lstrip().startswith('SELECT'))
                conn.commit.assert_not_called()
                conn.rollback.assert_not_called()


class EmsySetupTests(OfflineCase):
    def test_regular_load_uses_no_schema_ddl(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = []
        cur.fetchone.side_effect = [(1,), (1,)]
        with patch.object(emsy, 'get_connection', return_value=conn):
            self.assertEqual(emsy.load([feature(1)])['new'], 1)
        statements = [call.args[0].lstrip().split()[0].upper()
                      for call in cur.execute.call_args_list]
        self.assertEqual(statements, ['SELECT', 'INSERT', 'SELECT'])
        conn.commit.assert_called_once()

    def test_explicit_setup_commits_or_rolls_back_and_closes(self):
        for failure in (None, RuntimeError('setup denied')):
            with self.subTest(failure=failure):
                conn = MagicMock()
                cur = conn.cursor.return_value.__enter__.return_value
                cur.execute.side_effect = failure
                with patch.object(emsy, 'get_connection', return_value=conn):
                    if failure:
                        with self.assertRaisesRegex(LoadError, 'setup rolled back'):
                            emsy.initialize_schema()
                        conn.rollback.assert_called_once()
                        conn.commit.assert_not_called()
                    else:
                        emsy.initialize_schema()
                        conn.commit.assert_called_once()
                        conn.rollback.assert_not_called()
                cur.execute.assert_called_once_with(emsy.DDL)
                conn.close.assert_called_once()

    def test_missing_emsy_table_fails_with_explicit_setup_guidance(self):
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value.execute.side_effect = psycopg2.errors.UndefinedTable('missing')
        with patch.object(emsy, 'get_connection', return_value=conn):
            with self.assertRaisesRegex(LoadError, '--init'):
                emsy.load([feature(1)])
        conn.rollback.assert_called_once()
        conn.commit.assert_not_called()

    def test_cli_setup_preview_is_database_free_and_apply_never_fetches(self):
        for apply in (False, True):
            with self.subTest(apply=apply), \
                 patch('sys.argv', ['sync_ydrolipsies.py', '--init'] + (['--apply'] if apply else [])), \
                 patch.object(emsy, 'initialize_schema') as initialize, \
                 patch.object(emsy, 'fetch_features') as fetch:
                emsy.main()
                self.assertEqual(initialize.call_count, int(apply))
                fetch.assert_not_called()
        self.connect.assert_not_called()

    def test_cli_rejects_ambiguous_setup_options(self):
        for options in (['--apply'], ['--init', '--dry-run'], ['--init', '--bbox', '0,0,1,1']):
            with self.subTest(options=options), redirect_stderr(StringIO()), \
                 patch('sys.argv', ['sync_ydrolipsies.py'] + options), \
                 patch.object(emsy, 'initialize_schema') as initialize:
                with self.assertRaises(SystemExit) as result:
                    emsy.main()
                self.assertEqual(result.exception.code, 2)
                initialize.assert_not_called()
        self.connect.assert_not_called()
        self.http.assert_not_called()


class FailureSummaryTests(OfflineCase):
    def test_actual_layer_failure_is_in_json_and_digest_without_false_success(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(sync_all, 'fetch_all_layer_data', side_effect=FetchError('source incomplete')), \
             patch.object(sync_all, 'log_sync'):
            with SyncLogger(mode='track', log_dir=directory) as logger:
                result = sync_all.sync_layer('test', 'https://source.test',
                    {'id': 1, 'table': 'building_regs_lot'}, track_changes=True, logger=logger)
                self.assertFalse(result['success'])
                logger.log_table_result('ok', 2, {'unchanged': 3}, fetched=3)
                logger.log_table_result('empty', 3, {}, status='empty')
                logger.log_complete(status='error')
                data = json.loads(logger.json_file.read_text(encoding='utf-8'))
            summary = data['summary']
            self.assertEqual([summary[key] for key in ('tables_synced', 'tables_failed',
                'tables_with_data', 'tables_empty', 'total_errors')], [2, 1, 1, 1, 1])
            self.assertEqual(data['tables'][0]['status'], 'error')
            self.assertIn('source incomplete', data['tables'][0]['error_message'])
            digest = (Path(directory)/'CHANGES_latest.md').read_text(encoding='utf-8')
            self.assertIn('building_regs_lot', digest)
            self.assertIn('source incomplete', digest)
            self.assertNotIn('Καμία αλλαγή', digest)
