"""Credential isolation, launcher failures and atomic local configuration."""

from contextlib import redirect_stdout
from io import StringIO
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from settings import SettingsError, load_settings, load_sync_database, read_env_file
import setup_sync_writer as setup
import sync_access
import sync_launcher as launcher
from tests.support import OfflineCase


class SyncAccessTests(OfflineCase):
    def setUp(self):
        super().setUp()
        self.start_patch(patch.object(launcher,'replica_command',return_value=None))

    def settings(self, **extra):
        return load_sync_database(environ=dict(EPOL_DB_USER='reader',
            EPOL_DB_PASSWORD='api-only', EPOL_SYNC_DB_USER='epol_sync',
            EPOL_SYNC_DB_PASSWORD='sync!%$= #;password', **extra), env_path=None)

    def test_sync_credentials_never_fall_back_to_api_or_accept_an_owner(self):
        for sync_values in ({}, {'EPOL_SYNC_DB_USER':'epol_sync'},
                            {'EPOL_SYNC_DB_USER':'docker','EPOL_SYNC_DB_PASSWORD':'secret'}):
            with self.subTest(values=sync_values), self.assertRaises(SettingsError):
                load_sync_database(environ=dict(EPOL_DB_USER='docker',
                    EPOL_DB_PASSWORD='api-password', **sync_values), env_path=None)

    def test_literal_sync_password_overrides_file_without_changing_api_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'.env'
            path.write_text('EPOL_DB_USER=reader\nEPOL_DB_PASSWORD=api-only\n'
                'EPOL_DB_HOST=target.invalid\nEPOL_SYNC_DB_USER=epol_sync\n'
                'EPOL_SYNC_DB_PASSWORD="file!%$= #;pass"\n', encoding='utf-8')
            process={'EPOL_SYNC_DB_PASSWORD':'process!%$= #;pass'}
            before=dict(process)
            sync=load_sync_database(environ=process,env_path=path)
            api=load_settings(environ=process,env_path=path).database
            self.assertEqual((sync.host,sync.user,sync.password),
                             ('target.invalid','epol_sync','process!%$= #;pass'))
            self.assertEqual((api.user,api.password),('reader','api-only'))
            self.assertEqual(process,before)
            self.assertNotIn(sync.password,repr(sync))

    def test_child_settings_really_use_writer_while_parent_settings_stay_reader(self):
        database=self.settings()
        parent={'EPOL_DB_USER':'reader','EPOL_DB_PASSWORD':'api-only', 'DB_USER':'docker',
                'PATH':os.environ.get('PATH',''), 'SYSTEMROOT':os.environ.get('SYSTEMROOT','')}
        before=dict(parent)
        environment=launcher.child_environment(database,parent)
        result=subprocess.run([sys.executable,'-B','-c',
            'from settings import SETTINGS; assert SETTINGS.database.user=="epol_sync"; '
            'assert SETTINGS.database.password=="sync!%$= #;password"'],
            cwd=Path(__file__).resolve().parents[1],env=environment,capture_output=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(parent,before)

    def test_configuration_preserves_all_api_values_and_literal_passwords(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'.env'
            original='# keep comment\nEPOL_DB_USER=codex_reader\nEPOL_DB_PASSWORD="api!%$= #;pass"\nexport EPOL_SYNC_DB_USER=old\n'
            path.write_text(original,encoding='utf-8')
            password='sync!%$= #;password'
            setup.save_credentials(password,env_path=path,expected_source=original)
            values=read_env_file(path)
            self.assertEqual(values,{'EPOL_DB_USER':'codex_reader',
                'EPOL_DB_PASSWORD':'api!%$= #;pass','EPOL_SYNC_DB_USER':'epol_sync',
                'EPOL_SYNC_DB_PASSWORD':password})
            self.assertIn('# keep comment',path.read_text(encoding='utf-8'))
            self.assertEqual(list(Path(directory).glob('*.tmp')),[])

    def test_failed_atomic_replace_or_changed_file_keeps_original_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'.env'
            original='EPOL_DB_USER=reader\nEPOL_DB_PASSWORD=secret\n'
            path.write_text(original,encoding='utf-8')
            with patch.object(setup.os,'replace',side_effect=OSError('not writable')):
                with self.assertRaises(OSError):
                    setup.save_credentials('sync-password',env_path=path)
            self.assertEqual(path.read_text(encoding='utf-8'),original)
            self.assertEqual(list(Path(directory).glob('*.tmp')),[])
            with self.assertRaisesRegex(SettingsError,'changed'):
                setup.save_credentials('sync-password',env_path=path,expected_source='old')
            self.assertEqual(path.read_text(encoding='utf-8'),original)

    def test_check_is_read_only_and_never_starts_a_child(self):
        with patch.object(launcher,'load_sync_database',return_value=self.settings()), \
             patch.object(launcher,'check_connection') as check, \
             patch.object(launcher.subprocess,'run') as run:
            self.assertEqual(launcher.main(['--check']),0)
        check.assert_called_once()
        run.assert_not_called()

    def test_failed_preflight_never_starts_any_sync(self):
        with patch.object(launcher,'load_sync_database',return_value=self.settings()), \
             patch.object(launcher,'check_connection',side_effect=ValueError('unscoped rights')), \
             patch.object(launcher.subprocess,'run') as run:
            self.assertEqual(launcher.main(['all']),1)
        run.assert_not_called()

    def test_bounded_raster_options_use_only_writer_child_without_mutating_defaults(self):
        original=dict(launcher.COMMANDS)
        with patch.object(launcher,'load_sync_database',return_value=self.settings()), \
             patch.object(launcher,'check_connection'), \
             patch.object(launcher.subprocess,'run',return_value=MagicMock(returncode=0)) as run:
            self.assertEqual(launcher.main(['rasters','--raster-id','35','--limit','1',
                                           '--parallel','1','--force','--dry-run']),0)
        self.assertEqual(run.call_args.args[0],[sys.executable,'-B','download_rasters.py','--repair-missing',
            '--raster-id','35','--limit','1','--parallel','1','--force','--dry-run'])
        self.assertEqual(run.call_args.kwargs['env']['EPOL_DB_USER'],'epol_sync')
        self.assertEqual(launcher.COMMANDS,original)

    def test_raster_options_cannot_accidentally_start_all_or_unbounded_modes(self):
        for argv in (['all','--dry-run'],['--check','--force'],['--limit','1'],
                     ['rasters','--limit','0'],['rasters','--parallel','-1']):
            with self.subTest(argv=argv),patch.object(launcher,'load_sync_database') as load, \
                 patch.object(launcher.subprocess,'run') as run,redirect_stdout(StringIO()), \
                 patch('sys.stderr',StringIO()):
                with self.assertRaises(SystemExit):
                    launcher.main(argv)
            load.assert_not_called()
            run.assert_not_called()

    def test_configured_nas_restores_then_repairs_then_archives_with_reader_credentials(self):
        with patch.object(launcher,'load_sync_database',return_value=self.settings()), \
             patch.object(launcher,'check_connection'), \
             patch.object(launcher,'replica_command',side_effect=lambda mode:('raster_replica.py',mode,'--apply')), \
             patch.dict(os.environ,{'EPOL_DB_USER':'codex_reader','EPOL_DB_PASSWORD':'api-only'}), \
             patch.object(launcher.subprocess,'run',return_value=MagicMock(returncode=0)) as run:
            self.assertEqual(launcher.main(['rasters']),0)
        commands=[call.args[0][2:] for call in run.call_args_list]
        self.assertEqual(commands,[['raster_replica.py','pull','--apply'],
                                   ['download_rasters.py','--repair-missing'],
                                   ['raster_replica.py','push','--apply']])
        self.assertEqual([call.kwargs['env']['EPOL_DB_USER'] for call in run.call_args_list],
                         ['codex_reader','epol_sync','codex_reader'])

    def test_nas_failure_is_reported_but_local_download_still_runs(self):
        with patch.object(launcher,'load_sync_database',return_value=self.settings()), \
             patch.object(launcher,'check_connection'), \
             patch.object(launcher,'replica_command',side_effect=lambda mode:('raster_replica.py',mode,'--apply')), \
             patch.object(launcher.subprocess,'run',side_effect=[MagicMock(returncode=1),
                           MagicMock(returncode=0),MagicMock(returncode=0)]) as run:
            self.assertEqual(launcher.main(['rasters']),1)
        self.assertEqual(run.call_count,3)

    def test_download_preview_never_runs_nas_replication_even_when_configured(self):
        with patch.object(launcher,'load_sync_database',return_value=self.settings()), \
             patch.object(launcher,'check_connection'), \
             patch.object(launcher,'replica_command',return_value=('raster_replica.py','push','--apply')) as command, \
             patch.object(launcher.subprocess,'run',return_value=MagicMock(returncode=0)) as run:
            self.assertEqual(launcher.main(['rasters','--dry-run']),0)
        command.assert_not_called()
        run.assert_called_once()
        self.assertIn('--dry-run',run.call_args.args[0])

    def test_all_mode_runs_fixed_commands_and_propagates_failure_without_secrets(self):
        database=self.settings()
        with patch.object(launcher,'load_sync_database',return_value=database), \
             patch.object(launcher,'check_connection'), \
             patch.object(launcher.subprocess,'run',side_effect=[MagicMock(returncode=0),
                MagicMock(returncode=1),MagicMock(returncode=0)]) as run, \
             redirect_stdout(StringIO()) as output:
            self.assertEqual(launcher.main(['all']),1)
        self.assertEqual([c.args[0][2:] for c in run.call_args_list],
            [['sync_all.py','--track'],['sync_kaek_operating.py'],['sync_ydrolipsies.py']])
        self.assertTrue(all(c.kwargs['env']['EPOL_DB_USER']=='epol_sync' for c in run.call_args_list))
        self.assertTrue(all('shell' not in c.kwargs for c in run.call_args_list))
        self.assertNotIn(database.password,output.getvalue())

    def test_menu_exit_needs_no_credentials_or_connection(self):
        with patch('builtins.input',return_value='0'), \
             patch.object(launcher,'load_sync_database') as settings:
            self.assertEqual(launcher.main([]),0)
        settings.assert_not_called()
        self.connect.assert_not_called()

    def test_reviewed_sql_matches_contract_and_sql_preview_is_connection_free(self):
        self.assertEqual(setup.SQL_PATH.read_text(encoding='utf-8'),sync_access.setup_sql())
        self.assertEqual(setup.main(['--sql']),0)
        self.connect.assert_not_called()

    def test_setup_preview_does_not_create_roles_or_save_credentials(self):
        conn=MagicMock()
        conn.cursor.return_value.__enter__.return_value.fetchone.return_value=None
        with patch.object(setup,'ENV_PATH',Path(__file__)), \
             patch.object(setup.psycopg2,'connect',return_value=conn) as connect, \
             patch.object(setup,'inspect_target',return_value=('gis',[],[])), \
             patch.object(setup,'create_writer') as create, \
             patch.object(setup,'save_credentials') as save:
            self.assertEqual(setup.main([]),0)
        self.assertIn('default_transaction_read_only=on',connect.call_args.kwargs['options'])
        create.assert_not_called()
        save.assert_not_called()

    @unittest.skipUnless(os.name=='nt','Windows launcher wrapper')
    def test_windows_wrappers_preserve_exit_codes_without_sync_or_database_access(self):
        root=Path(__file__).resolve().parents[1]
        # An exported checkout has no project .venv. Make the interpreter
        # running this suite available to the wrappers without requiring
        # activation or a globally installed Python.
        environment=dict(os.environ)
        environment['PATH']=str(Path(sys.executable).parent)+os.pathsep+environment.get('PATH','')
        invalid=subprocess.run(['cmd','/d','/c','sync_menu.bat invalid <nul'],
            cwd=root,env=environment,capture_output=True,timeout=20)
        self.assertEqual(invalid.returncode,2,invalid.stdout+invalid.stderr)
        quit_menu=subprocess.run(['cmd','/d','/c','sync_menu.bat'],input=b'0\n',
            cwd=root,env=environment,capture_output=True,timeout=20)
        self.assertEqual(quit_menu.returncode,0,quit_menu.stdout+quit_menu.stderr)
        sql=subprocess.run(['cmd','/d','/c','setup_sync_writer.bat --sql <nul'],
            cwd=root,env=environment,capture_output=True,timeout=20)
        self.assertEqual(sql.returncode,0,sql.stdout+sql.stderr)
