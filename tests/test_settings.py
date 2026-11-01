"""One literal .env/settings policy for the API and every database client."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from settings import SettingsError, load_settings, read_env_file


class SettingsTests(unittest.TestCase):
    def test_optional_nas_root_is_disabled_by_default_and_process_override_wins(self):
        self.assertIsNone(load_settings(environ={},env_path=None).raster_nas_path)
        value=load_settings(environ={'EPOL_RASTER_NAS_PATH':r'\\nas\gis\rasters'},env_path=None)
        self.assertEqual(value.raster_nas_path,r'\\nas\gis\rasters')
        self.assertIsNone(load_settings(environ={'EPOL_RASTER_NAS_PATH':' '},env_path=None).raster_nas_path)

    def test_raster_root_defaults_to_fek_folder_and_explicit_override_wins(self):
        settings=load_settings(environ={'EPOL_FEK_LOCAL_PATH':r'C:\rasters'},env_path=None)
        self.assertEqual(settings.raster_base_path,settings.fek_local_path)
        settings=load_settings(environ={'EPOL_FEK_LOCAL_PATH':r'C:\flat',
                                       'EPOL_RASTER_BASE_PATH':r'C:\catalog'},env_path=None)
        self.assertEqual(settings.raster_base_path,r'C:\catalog')

    def parse(self, source):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text(source, encoding="utf-8")
            return read_env_file(path)

    def test_literal_passwords_quotes_comments_bom_and_windows_paths(self):
        parsed = self.parse('\ufeff; heading\n# heading\nexport EPOL_DB_PASSWORD="a!%$= #;b" # note\n'
                            "SINGLE='x;#y'\nPLAIN=a!%$=b#c;d\nPATH=O:\\folder\\new\\test\nPORT=5432 ; note\n")
        self.assertEqual(parsed["EPOL_DB_PASSWORD"], "a!%$= #;b")
        self.assertEqual(parsed["PLAIN"], "a!%$=b#c;d")
        self.assertEqual(parsed["SINGLE"], "x;#y")
        self.assertEqual(parsed["PATH"], r"O:\folder\new\test")
        self.assertEqual(parsed["PORT"], "5432")

    def test_malformed_and_duplicate_entries_fail_without_disclosing_values(self):
        for value in ('EPOL_DB_PASSWORD="TOPSECRET', 'EPOL_DB_PASSWORD="TOPSECRET"oops',
                      'not a key=TOPSECRET', 'EPOL_DB_PASSWORD=TOPSECRET\nEPOL_DB_PASSWORD=TOPSECRET'):
            with self.subTest(value=value):
                with self.assertRaises(SettingsError) as caught:
                    self.parse(value)
                self.assertNotIn("TOPSECRET", str(caught.exception))

    def test_process_overrides_file_across_legacy_aliases_without_mutating_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("EPOL_DB_HOST=file\nEPOL_DB_PASSWORD=file-only-secret\n", encoding="utf-8")
            process = {"DB_HOST": "process"}
            before = dict(os.environ)
            settings = load_settings(environ=process, env_path=path)
            self.assertEqual(settings.database.host, "process")
            self.assertEqual(process, {"DB_HOST": "process"})
            self.assertEqual(dict(os.environ), before)
            self.assertEqual(settings.database.password, "file-only-secret")

    def test_canonical_names_win_within_a_source_and_legacy_names_still_work(self):
        settings = load_settings(environ={"EPOL_DB_HOST": "canonical", "DB_HOST": "legacy", "DB_PORT": "5433"}, env_path=None)
        self.assertEqual((settings.database.host, settings.database.port), ("canonical", 5433))

    def test_invalid_connection_ports_timeouts_and_schema_fail_without_values(self):
        for key, values in (("EPOL_DB_PORT", ("0", "65536", "bad-secret", "1.0", "-1")),
                            ("EPOL_API_PORT", ("0", "65536")),
                            ("EPOL_DB_CONNECT_TIMEOUT", ("0", "301")),
                            ("EPOL_DB_SCHEMA", ("different-schema", "bad-secret"))):
            for value in values:
                with self.subTest(key=key, value=value):
                    with self.assertRaises(SettingsError) as caught:
                        load_settings(environ={key: value}, env_path=None)
                    self.assertNotIn("bad-secret", str(caught.exception))

    def test_empty_and_nul_fields_are_rejected_but_password_can_be_omitted_for_inspection(self):
        for key in ("EPOL_DB_HOST", "EPOL_DB_NAME", "EPOL_DB_USER", "EPOL_API_HOST", "EPOL_RASTER_BASE_PATH"):
            for value in ("", "\x00"):
                with self.subTest(key=key, value=value):
                    with self.assertRaises(SettingsError):
                        load_settings(environ={key: value}, env_path=None)
        db = load_settings(environ={}, env_path=None).database
        with self.assertRaises(SettingsError):
            db.require_password()

    def test_secret_is_not_in_settings_repr_or_file_error(self):
        settings = load_settings(environ={"EPOL_DB_PASSWORD": "TOPSECRET"}, env_path=None)
        self.assertNotIn("TOPSECRET", repr(settings))
        self.assertNotIn("schema", settings.database.connection_kwargs())
        self.assertEqual(settings.database.connection_kwargs()["connect_timeout"], 10)

    def test_all_clients_use_the_same_settings_from_an_unrelated_working_directory(self):
        script = """
import sys
sys.path.insert(0, sys.argv[1])
from settings import SETTINGS
from config import DATABASE
import api_server, sync_kaek_operating, sync_ydrolipsies, load_postgis, ingest_rasters, download_rasters
expected=SETTINGS.database.connection_kwargs()
assert api_server.DB_CONFIG == expected
assert sync_kaek_operating.DB == expected
assert {k:v for k,v in DATABASE.items() if k != 'schema'} == expected
assert sync_ydrolipsies.DATABASE is DATABASE
assert load_postgis.DATABASE is DATABASE
assert ingest_rasters.SETTINGS is SETTINGS
assert download_rasters.SETTINGS is SETTINGS
assert str(download_rasters.GEOREF_DIR) == SETTINGS.raster_base_path
assert expected['host'] == 'settings-test.invalid'
assert expected['port'] == 5433
assert expected['password'] == 'fake!%$= #;password'
"""
        env = dict(os.environ, EPOL_DB_HOST="settings-test.invalid", EPOL_DB_PORT="5433",
                   EPOL_DB_PASSWORD="fake!%$= #;password", EPOL_DB_SCHEMA="epoleodomia")
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, "-B", "-c", script, str(Path(__file__).resolve().parents[1])],
                                    cwd=directory, env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
