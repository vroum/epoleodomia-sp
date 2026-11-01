"""Publication ordering, preview isolation, failure outcomes and menu routing."""
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
from unittest.mock import MagicMock, patch

import psycopg2
from psycopg2 import extensions

import enable_sync_publication as enable
import sync_launcher as launcher
import sync_publication as publication
from settings import DatabaseSettings
from sync_safety import FetchError, LoadError
from tests.support import OfflineCase
from tests.test_tee_sync import collection


SERVICES = {'test': {'url': 'https://example.invalid/MapServer',
                    'layers': [{'table': 'building_blocks', 'id': 1}]}}


class PublicationTests(OfflineCase):
    def setUp(self):
        super().setUp()
        self.start_patch(patch.object(publication, 'SERVICES', SERVICES))
        self.database = DatabaseSettings('localhost', 5432, 'test', 'epol_sync', 'test-only')
        self.conn = MagicMock()
        self.conn.autocommit = False
        self.conn.get_transaction_status.return_value = extensions.TRANSACTION_STATUS_IDLE
        self.cur = self.conn.cursor.return_value.__enter__.return_value
        self.cur.fetchone.return_value = (True,)
        self.layers = [publication.PreparedLayer('tee', 'building_blocks', collection(1), service='test', layer_id=1)]

    def run_pipeline(self, **kwargs):
        return publication.run('tee', self.database, connect=lambda **options: self.conn, **kwargs)

    def test_preview_collects_without_locks_or_data_transaction(self):
        with patch.object(publication, 'preflight', return_value={'ready': False}), \
             patch.object(publication, 'publish_bundle') as publish:
            result = self.run_pipeline(collector=lambda mode: self.layers)
        self.assertEqual(result['status'], 'preview')
        publish.assert_not_called()
        self.cur.execute.assert_not_called()
        self.conn.commit.assert_not_called()
        self.conn.close.assert_called_once()

    def test_collection_failure_cannot_publish_any_data_and_releases_session(self):
        with patch.object(publication, 'preflight'), \
             patch.object(publication, 'publish_bundle') as publish:
            with self.assertRaises(FetchError):
                self.run_pipeline(apply=True, collector=MagicMock(side_effect=FetchError('later source failed')))
        publish.assert_not_called()
        self.conn.commit.assert_not_called()
        self.conn.close.assert_called_once()

    def test_session_lock_conflict_stops_before_fetch(self):
        self.cur.fetchone.return_value = (False,)
        collector = MagicMock()
        with patch.object(publication, 'preflight'), self.assertRaisesRegex(LoadError, 'already running'):
            self.run_pipeline(apply=True, collector=collector)
        collector.assert_not_called()

    def test_complete_capture_precedes_the_single_publication(self):
        events = []
        def collect(mode):
            self.assertTrue(self.conn.autocommit)
            events.append('captured')
            return self.layers
        def publish(conn, mode, layers):
            self.assertFalse(conn.autocommit)
            self.assertEqual(events, ['captured'])
            events.append('published')
            return {'status': 'committed', 'timings_seconds': {}}
        with patch.object(publication, 'preflight'), patch.object(publication, 'publish_bundle', side_effect=publish):
            self.assertEqual(self.run_pipeline(apply=True, collector=collect)['status'], 'committed')
        self.assertEqual(events, ['captured', 'published'])

    def test_duplicate_missing_or_unselected_bundle_is_rejected(self):
        for layers in ([], self.layers * 2, [publication.PreparedLayer('tee', 'unknown', collection(1))]):
            with self.subTest(layers=layers), self.assertRaises(LoadError):
                publication.validate_bundle('tee', layers)

    def test_borrowed_loader_audit_and_recalculation_share_one_commit(self):
        stats = dict(new=1, updated=0, deleted=0, unchanged=0, errors=0)
        with patch.object(publication, '_lock_targets'), \
             patch.object(publication.tee_load, 'start_sync_run', return_value=5) as start, \
             patch.object(publication.tee_load, 'load_geojson_with_tracking', return_value=stats) as load, \
             patch.object(publication.tee_load, 'log_sync') as audit, \
             patch.object(publication.tee_load, 'post_sync_recalculate') as recalc, \
             patch.object(publication.tee_load, 'complete_sync_run') as finish:
            self.assertEqual(publication.publish_bundle(self.conn, 'tee', self.layers)['status'], 'committed')
        for call in (start, load, audit, recalc, finish):
            self.assertIs(call.call_args.kwargs['connection'], self.conn)
        self.conn.commit.assert_called_once()
        self.conn.rollback.assert_not_called()
        self.conn.close.assert_not_called()

    def test_failed_late_audit_rolls_back_instead_of_reporting_success(self):
        with patch.object(publication, '_lock_targets'), \
             patch.object(publication.tee_load, 'start_sync_run', return_value=5), \
             patch.object(publication.tee_load, 'load_geojson_with_tracking', return_value=dict(new=1,updated=0,deleted=0,unchanged=0,errors=0)), \
             patch.object(publication.tee_load, 'post_sync_recalculate'), \
             patch.object(publication.tee_load, 'log_sync', side_effect=RuntimeError('audit failed')):
            with self.assertRaisesRegex(RuntimeError, 'audit failed'):
                publication.publish_bundle(self.conn, 'tee', self.layers)
        self.conn.commit.assert_not_called()
        self.conn.rollback.assert_called_once()

    def test_active_or_autocommit_connection_is_refused(self):
        for autocommit, status in ((True, extensions.TRANSACTION_STATUS_IDLE), (False, extensions.TRANSACTION_STATUS_INTRANS)):
            self.conn.autocommit = autocommit
            self.conn.get_transaction_status.return_value = status
            with self.subTest(status=status), self.assertRaises(LoadError):
                publication.publish_bundle(self.conn, 'tee', self.layers)

    def test_lost_commit_response_is_explicit_in_cli_receipt(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(publication, 'load_sync_database', return_value=self.database), \
             patch.object(publication, 'run', side_effect=publication.CommitOutcomeUnknown('check audit', 5)):
            path = Path(directory) / 'receipt.json'
            self.assertEqual(publication.main(['tee', '--apply', '--report', str(path)]), 1)
            self.assertEqual(json.loads(path.read_text())['status'], 'commit_unknown')

    def test_password_is_redacted_from_failed_cli_receipt(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(publication, 'load_sync_database', return_value=self.database), \
             patch.object(publication, 'run', side_effect=RuntimeError(self.database.password)):
            path = Path(directory) / 'receipt.json'
            self.assertEqual(publication.main(['tee', '--report', str(path)]), 1)
            self.assertNotIn(self.database.password, path.read_text())

    def test_enabled_menu_publishes_all_data_with_one_child(self):
        with patch.object(launcher, 'load_sync_database', return_value=self.database), \
             patch.object(launcher, 'check_connection', return_value=True), \
             patch.object(launcher.subprocess, 'run', return_value=MagicMock(returncode=0)) as run:
            self.assertEqual(launcher.main(['all']), 0)
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0][2:], ['sync_publication.py', 'all', '--apply'])
        self.assertEqual(run.call_args.kwargs['env']['EPOL_DB_USER'], 'epol_sync')

    def test_failed_atomic_data_bundle_skips_every_raster_action(self):
        with patch.object(launcher, 'load_sync_database', return_value=self.database), \
             patch.object(launcher, 'check_connection', return_value=True), \
             patch.object(launcher, 'run_replica') as replica, \
             patch.object(launcher.subprocess, 'run', return_value=MagicMock(returncode=1)) as run:
            self.assertEqual(launcher.main(['all-rasters']), 1)
        run.assert_called_once()
        replica.assert_not_called()

    def test_unstartable_atomic_child_skips_every_raster_action(self):
        with patch.object(launcher, 'load_sync_database', return_value=self.database), \
             patch.object(launcher, 'check_connection', return_value=True), \
             patch.object(launcher, 'run_replica') as replica, \
             patch.object(launcher.subprocess, 'run', side_effect=OSError('cannot start')) as run:
            self.assertEqual(launcher.main(['all-rasters']), 1)
        run.assert_called_once()
        replica.assert_not_called()

    def test_commit_response_failure_exposes_the_pending_audit_identity(self):
        self.conn.commit.side_effect = psycopg2.OperationalError('lost response')
        with patch.object(publication, '_lock_targets'), \
             patch.object(publication.tee_load, 'start_sync_run', return_value=5), \
             patch.object(publication.tee_load, 'load_geojson_with_tracking', return_value=dict(new=1,updated=0,deleted=0,unchanged=0,errors=0)), \
             patch.object(publication.tee_load, 'post_sync_recalculate'), \
             patch.object(publication.tee_load, 'log_sync'), \
             patch.object(publication.tee_load, 'complete_sync_run'):
            with self.assertRaises(publication.CommitOutcomeUnknown) as error:
                publication.publish_bundle(self.conn, 'tee', self.layers)
        self.assertEqual(error.exception.audit_id, 5)
        self.conn.rollback.assert_called_once()

    def test_publication_sql_preview_has_no_connections(self):
        self.assertEqual(enable.SQL_PATH.read_text(encoding='utf-8'), enable.STATEMENT)
        self.assertEqual(enable.main(['--sql']), 0)
        self.connect.assert_not_called()

    def test_grant_target_drift_rolls_back_before_grant(self):
        with patch.object(enable, 'inspect_target', return_value='changed'), \
             self.assertRaisesRegex(ValueError, 'changed'):
            enable.enable(lambda: self.conn, 'original')
        self.conn.rollback.assert_called_once()
        self.assertFalse(any(call.args[0] == enable.STATEMENT for call in self.cur.execute.call_args_list))
