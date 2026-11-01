"""Offline regression tests: HTTP and database connections are always mocked."""

import os
import unittest
from unittest.mock import MagicMock, patch

import requests

# These tests never need real credentials, even on a fresh checkout.
with patch.dict(os.environ, {"EPOL_DB_PASSWORD": "unused-by-offline-tests"}):
    import fetch_layer
    import load_postgis
    import sync_all

from sync_safety import FetchError, LoadError, SyncError
from tests.support import OfflineCase, response


def feature(objectid):
    return {
        "type": "Feature",
        "properties": {"OBJECTID": objectid},
        "geometry": {"type": "Point", "coordinates": [420000 + objectid, 4120000]},
    }


def collection(*objectids):
    return {"type": "FeatureCollection", "features": [feature(i) for i in objectids]}


class FetchTests(OfflineCase):
    def test_count_failure_is_not_an_empty_layer(self):
        self.http.side_effect = requests.exceptions.Timeout("source timed out")
        with self.assertRaises(FetchError):
            fetch_layer.fetch_layer_count("https://source.test/MapServer", 1)

    def test_http_error_is_a_failure(self):
        failed = response({})
        failed.raise_for_status.side_effect = requests.exceptions.HTTPError("503")
        self.http.side_effect = None
        self.http.return_value = failed
        with self.assertRaises(FetchError):
            fetch_layer.fetch_layer_count("https://source.test/MapServer", 1)

    def test_invalid_json_is_a_failure(self):
        failed = response({})
        failed.json.side_effect = ValueError("not JSON")
        self.http.side_effect = None
        self.http.return_value = failed
        with self.assertRaises(FetchError):
            fetch_layer.fetch_layer_data("https://source.test/MapServer", 1)

    def test_invalid_count_responses_fail(self):
        for payload in ({"error": {"message": "unavailable"}}, {}, [],
                        {"count": -1}, {"count": "3"}, {"count": True}):
            with self.subTest(payload=payload):
                self.http.side_effect = None
                self.http.return_value = response(payload)
                with self.assertRaises(FetchError):
                    fetch_layer.fetch_layer_count("https://source.test/MapServer", 1)

    def test_verified_empty_layer_is_allowed(self):
        self.http.side_effect = [response({"count": 0})]
        result = fetch_layer.fetch_all_layer_data("https://source.test/MapServer", 1)
        self.assertEqual(result, collection())
        self.assertEqual(self.http.call_count, 1)

    def test_short_pages_continue_until_expected_count(self):
        self.http.side_effect = [response({"count": 5}), response(collection(1, 2)),
                                 response(collection(3, 4)), response(collection(5)),
                                 response({"count": 5})]
        result = fetch_layer.fetch_all_layer_data("https://source.test/MapServer", 1)
        self.assertEqual(result, collection(1, 2, 3, 4, 5))
        offsets = [call.kwargs["params"]["resultOffset"] for call in self.http.call_args_list
                   if "resultOffset" in call.kwargs["params"]]
        self.assertEqual(offsets, [0, 2, 4])

    def test_failed_later_page_never_returns_partial_data(self):
        self.http.side_effect = [response({"count": 3}), response(collection(1, 2)),
                                 requests.exceptions.Timeout("second page failed")]
        with self.assertRaisesRegex(FetchError, "offset 2"):
            fetch_layer.fetch_all_layer_data("https://source.test/MapServer", 1)

    def test_empty_later_page_rejects_partial_data(self):
        self.http.side_effect = [response({"count": 3}), response(collection(1, 2)),
                                 response(collection())]
        with self.assertRaisesRegex(FetchError, "incomplete download"):
            fetch_layer.fetch_all_layer_data("https://source.test/MapServer", 1)

    def test_repeated_page_is_rejected(self):
        self.http.side_effect = [response({"count": 4}), response(collection(1, 2)),
                                 response(collection(1, 2))]
        with self.assertRaisesRegex(FetchError, "repeated page"):
            fetch_layer.fetch_all_layer_data("https://source.test/MapServer", 1)

    def test_more_records_than_expected_is_rejected(self):
        self.http.side_effect = [response({"count": 1}), response(collection(1, 2))]
        with self.assertRaisesRegex(FetchError, "expected 1"):
            fetch_layer.fetch_all_layer_data("https://source.test/MapServer", 1)

    def test_source_count_change_is_rejected(self):
        self.http.side_effect = [response({"count": 2}), response(collection(1, 2)),
                                 response({"count": 3})]
        with self.assertRaisesRegex(FetchError, "source count changed"):
            fetch_layer.fetch_all_layer_data("https://source.test/MapServer", 1)

    def test_failed_final_count_never_returns_unverified_data(self):
        self.http.side_effect = [response({"count": 2}), response(collection(1, 2)),
                                 requests.exceptions.Timeout("verification failed")]
        with self.assertRaises(FetchError):
            fetch_layer.fetch_all_layer_data("https://source.test/MapServer", 1)

    def test_malformed_or_error_page_is_rejected(self):
        for payload in ({"error": {"message": "unavailable"}}, {},
                        {"type": "FeatureCollection", "features": None},
                        {"type": "FeatureCollection", "features": [{}]}):
            with self.subTest(payload=payload):
                self.http.side_effect = None
                self.http.return_value = response(payload)
                with self.assertRaises(FetchError):
                    fetch_layer.fetch_layer_data("https://source.test/MapServer", 1)


class LoadTests(OfflineCase):
    def setUp(self):
        super().setUp()
        self.conn = MagicMock()
        self.cur = self.conn.cursor.return_value.__enter__.return_value
        self.cur.rowcount = 0
        self.cur.fetchall.return_value = []
        self.cur.fetchone.return_value = (100,)
        self.get_connection = self.start_patch(patch.object(
            load_postgis, "get_connection", return_value=self.conn))
        self.start_patch(patch.object(
            load_postgis, "get_table_columns", return_value=["objectid"]))
        self.start_patch(patch.object(load_postgis, "check_tracking_columns", return_value=True))

    def load(self, mode, data, **kwargs):
        if mode == "track":
            return load_postgis.load_geojson_with_tracking(data, "test_table", **kwargs)
        return load_postgis.load_geojson_to_table(
            data, "test_table", truncate=(mode == "replace"), **kwargs)

    def test_every_load_mode_rolls_back_on_record_failure_before_deletions(self):
        for mode in ("replace", "upsert", "track"):
            with self.subTest(mode=mode):
                self.conn.reset_mock()
                inserts = []

                def execute(sql, params=None):
                    if "INSERT INTO" in sql:
                        inserts.append(sql)
                        if len(inserts) == 2:
                            raise RuntimeError("simulated record constraint failure")

                self.cur.execute.side_effect = execute
                with self.assertRaisesRegex(LoadError, "rolled back"):
                    self.load(mode, collection(1, 2))
                self.conn.rollback.assert_called_once()
                self.conn.commit.assert_not_called()
                self.conn.close.assert_called_once()
                self.assertFalse(any("is_deleted = TRUE" in c.args[0]
                                     for c in self.cur.execute.call_args_list))

    def test_successful_loads_commit_once_and_close(self):
        def execute(sql, params=None):
            self.cur.rowcount = 1 if sql.lstrip().startswith("INSERT INTO") else 0

        self.cur.execute.side_effect = execute
        for mode in ("replace", "upsert", "track"):
            with self.subTest(mode=mode):
                self.conn.reset_mock()
                result = self.load(mode, collection(1, 2))
                if mode in ("replace", "upsert"):
                    self.assertEqual(result, 2)
                elif mode == "track":
                    self.assertEqual(result["new"], 2)
                self.conn.commit.assert_called_once()
                self.conn.rollback.assert_not_called()
                self.conn.close.assert_called_once()

    def test_invalid_identities_fail_before_database_access(self):
        for data in (collection(1, 1), collection(True), collection(1.5)):
            for mode in ("track", "upsert"):
                with self.subTest(mode=mode, data=data):
                    with self.assertRaises(SyncError):
                        self.load(mode, data)
        self.get_connection.assert_not_called()

    def test_missing_objectid_fails_before_database_access(self):
        data = collection(1)
        data["features"][0]["properties"] = {}
        with self.assertRaisesRegex(SyncError, "OBJECTID"):
            self.load("track", data)
        self.get_connection.assert_not_called()

    def test_supported_objectid_aliases_load_successfully(self):
        for name in ("OBJECTID", "objectid", "OBJECTID_1", "objectid_1"):
            with self.subTest(name=name):
                self.cur.execute.reset_mock()
                data = collection(1)
                data["features"][0]["properties"] = {name: 1}
                result = self.load("track", data)
                self.assertEqual(result["new"], 1)
                inserted = [c for c in self.cur.execute.call_args_list
                            if "INSERT INTO" in c.args[0]]
                self.assertEqual(inserted[0].args[1][0], 1)

    def test_objectid_zero_is_included_in_deletion_guard(self):
        self.load("track", collection(0))
        deletion_calls = [c for c in self.cur.execute.call_args_list
                          if "SET is_deleted = TRUE" in c.args[0]]
        self.assertEqual(len(deletion_calls), 1)
        self.assertIn(0, deletion_calls[0].args[1])

    def test_replacement_preserves_legitimate_duplicate_objectids(self):
        self.assertEqual(self.load("replace", collection(1, 1)), 2)
        self.conn.commit.assert_called_once()

    def test_missing_table_columns_is_a_failed_load(self):
        with patch.object(load_postgis, "get_table_columns", return_value=[]):
            for mode in ("replace", "upsert", "track"):
                with self.subTest(mode=mode):
                    self.conn.reset_mock()
                    with self.assertRaises(LoadError):
                        self.load(mode, collection(1))
                    self.conn.rollback.assert_called_once()
                    self.conn.commit.assert_not_called()

    def test_changelog_write_failure_rolls_back_the_data(self):
        def execute(sql, params=None):
            if ".changelog" in sql:
                raise RuntimeError("audit write failed")

        self.cur.execute.side_effect = execute
        with self.assertRaisesRegex(LoadError, "audit"):
            self.load("track", collection(1), sync_run_id=42)
        self.conn.rollback.assert_called_once()
        self.conn.commit.assert_not_called()

    def test_malformed_payloads_fail_before_database_access(self):
        missing_geom = collection(1)
        del missing_geom["features"][0]["geometry"]
        bad_geom = collection(1)
        bad_geom["features"][0]["geometry"] = {"type": "Unsupported", "coordinates": []}
        null_coords = collection(1)
        null_coords["features"][0]["geometry"]["coordinates"] = None
        for data in ({}, missing_geom, bad_geom, null_coords):
            with self.subTest(data=data):
                with self.assertRaises(SyncError):
                    self.load("replace", data)
        self.get_connection.assert_not_called()

    def test_empty_input_keeps_existing_data(self):
        for mode in ("replace", "upsert", "track"):
            self.load(mode, collection())
        self.get_connection.assert_not_called()

    def test_same_length_coordinate_move_is_updated_and_audited(self):
        old_wkt = "POINT(420001 4120000)"
        new_wkt = "POINT(420002 4120000)"
        self.assertEqual(len(old_wkt), len(new_wkt))
        old_binary = b"full-precision-database-geometry"
        self.cur.fetchall.side_effect = [[(100, 1, 1, old_wkt, old_binary)], []]
        data = collection(1)
        data["features"][0]["geometry"]["coordinates"][0] += 1
        with patch.object(load_postgis, "geometry_changes", return_value={1: True}) as compare:
            result = self.load("track", data)
        self.assertEqual(result["updated"], 1)
        self.assertTrue(result["changes"][0]["geometry_changed"])
        self.assertEqual(compare.call_args.args[1], [(1, old_binary, new_wkt)])
        update = next(c for c in self.cur.execute.call_args_list if "SET objectid" in c.args[0])
        self.assertIn(new_wkt, update.args[1])
        self.conn.commit.assert_called_once()

    def test_equal_geometry_with_different_text_is_unchanged(self):
        self.cur.fetchall.side_effect = [[
            (100, 1, 1, "POINT(420001.0 4120000.0)", b"old-binary")], []]
        with patch.object(load_postgis, "geometry_changes", return_value={1: False}):
            result = self.load("track", collection(1))
        self.assertEqual(result["unchanged"], 1)
        self.assertEqual(result["updated"], 0)
        self.assertFalse(any("SET objectid" in c.args[0] for c in self.cur.execute.call_args_list))

    def test_spatial_comparison_failure_rolls_back_before_row_changes(self):
        self.cur.fetchall.return_value = [(100, 1, 1, "POINT(0 0)", b"old-binary")]
        with patch.object(load_postgis, "geometry_changes", side_effect=RuntimeError("comparison failed")):
            with self.assertRaisesRegex(LoadError, "comparison failed"):
                self.load("track", collection(1))
        self.conn.rollback.assert_called_once()
        self.conn.commit.assert_not_called()
        for call in self.cur.execute.call_args_list:
            self.assertTrue(call.args[0].lstrip().startswith("SELECT"))

    def test_confirmed_spatial_change_remains_in_audit_even_if_text_matches(self):
        self.cur.fetchall.side_effect = [[
            (100, 1, 1, "POINT(420001 4120000)", b"different-full-precision-binary")], []]
        with patch.object(load_postgis, "geometry_changes", return_value={1: True}):
            result = self.load("track", collection(1), sync_run_id=42)
        self.assertTrue(result["changes"][0]["geometry_changed"])
        audit = next(c for c in self.cur.execute.call_args_list if ".changelog" in c.args[0])
        self.assertIs(audit.args[1][8], True)
        self.conn.commit.assert_called_once()


class AuditSummaryTests(OfflineCase):
    def test_cli_summary_uses_successful_layer_results_in_all_modes_without_file_logger(self):
        services={'A':{'url':'https://source.test','layers':[
            {'id':1,'table':'building_blocks'},{'id':2,'table':'empty'}]},
            'B':{'url':'https://source.test','layers':[{'id':3,'table':'failed'}]}}
        def result(service,url,layer,*args):
            return {1:{'success':True,'status':'success','stats':{'new':2,'updated':3,'deleted':1}},
                    2:{'success':True,'status':'empty','stats':{}},
                    3:{'success':False,'status':'error','stats':{'new':99}}}[layer['id']]
        for arguments,code,tables in [([],1,2),(['--service','A'],0,2),
            (['--table','building_blocks'],0,1),(['--test'],0,1)]:
            with self.subTest(arguments=arguments):
                conn=MagicMock()
                with patch.object(sync_all,'SERVICES',services), \
                     patch.object(sync_all,'test_connection',return_value=True), \
                     patch.object(sync_all,'start_sync_run',return_value=42), \
                     patch.object(sync_all,'sync_layer',side_effect=result), \
                     patch.object(load_postgis,'get_connection',return_value=conn), \
                     patch('sys.argv',['sync_all.py','--track','--no-log']+arguments):
                    with self.assertRaises(SystemExit) as exit_result:
                        sync_all.main()
                self.assertEqual(exit_result.exception.code,code)
                cur=conn.cursor.return_value.__enter__.return_value
                update=next(c for c in cur.execute.call_args_list if '.sync_runs' in c.args[0])
                self.assertEqual(update.args[1],('error' if code else 'success',2,3,1,tables,None,42))
                conn.commit.assert_called_once()


class OrchestrationTests(OfflineCase):
    def setUp(self):
        super().setUp()
        self.log = self.start_patch(patch.object(sync_all, "log_sync"))
        self.recalc = self.start_patch(patch.object(sync_all, "post_sync_recalculate"))
        self.replace = self.start_patch(patch.object(sync_all, "load_geojson_to_table"))
        self.tracked = self.start_patch(patch.object(sync_all, "load_geojson_with_tracking"))
        self.save_hash = self.start_patch(patch.object(sync_all, "_save_replace_hash"))
        self.start_patch(patch.object(sync_all, "_load_replace_hashes", return_value={}))
        self.logger = MagicMock()

    def sync(self, table="building_blocks", track=True, dry_run=False):
        return sync_all.sync_layer(
            "test_service", "https://source.test/MapServer", {"id": 1, "table": table},
            track_changes=track, dry_run=dry_run, logger=self.logger)

    def test_partial_download_never_reaches_either_loader(self):
        # Exercise the actual HTTP -> pagination -> orchestration failure path.
        self.http.side_effect = [response({"count": 3}), response(collection(1, 2)),
                                 requests.exceptions.Timeout("page failed")]
        result = self.sync()
        self.assertFalse(result["success"])
        self.assertEqual(result["status"], "error")
        self.replace.assert_not_called()
        self.tracked.assert_not_called()
        self.recalc.assert_not_called()
        self.save_hash.assert_not_called()
        self.assertEqual(self.log.call_args.kwargs["status"], "error")
        self.logger.log_error.assert_called_once()

    def test_loader_failure_is_reported_as_failure(self):
        for table, track, loader in (("building_blocks", True, self.tracked),
                                     ("building_regs_lot", True, self.replace),
                                     ("building_blocks", False, self.replace)):
            with self.subTest(table=table, track=track):
                loader.side_effect = LoadError("rolled back")
                with patch.object(sync_all, "fetch_all_layer_data", return_value=collection(1)):
                    result = self.sync(table, track)
                self.assertFalse(result["success"])
                self.assertEqual(self.log.call_args.kwargs["status"], "error")
        self.save_hash.assert_not_called()
        self.recalc.assert_not_called()

    def test_incomplete_loader_result_is_not_success(self):
        for track in (True, False):
            with self.subTest(track=track):
                self.tracked.return_value = {"new": 1, "updated": 0, "unchanged": 0, "errors": 0}
                self.replace.return_value = 1
                with patch.object(sync_all, "fetch_all_layer_data", return_value=collection(1, 2)):
                    result = self.sync(track=track)
                self.assertFalse(result["success"])
        self.recalc.assert_not_called()

    def test_successful_tracked_sync_accounts_for_unchanged_records(self):
        self.tracked.return_value = {"new": 0, "updated": 1, "unchanged": 1, "errors": 0}
        with patch.object(sync_all, "fetch_all_layer_data", return_value=collection(1, 2)):
            result = self.sync()
        self.assertTrue(result["success"])
        self.replace.assert_not_called()
        self.assertEqual(self.log.call_args.kwargs["status"], "success")

    def test_lot_exception_still_uses_replacement_with_duplicates(self):
        self.replace.return_value = 2
        with patch.object(sync_all, "fetch_all_layer_data", return_value=collection(1, 1)):
            result = self.sync("building_regs_lot")
        self.assertTrue(result["success"])
        self.tracked.assert_not_called()
        self.save_hash.assert_called_once()

    def test_verified_empty_source_keeps_existing_data(self):
        self.http.side_effect = [response({"count": 0})]
        result = self.sync()
        self.assertTrue(result["success"])
        self.assertEqual(result["status"], "empty")
        self.replace.assert_not_called()
        self.tracked.assert_not_called()

    def test_failed_dry_run_does_not_write_a_database_log(self):
        self.http.side_effect = requests.exceptions.Timeout("source unavailable")
        result = self.sync(dry_run=True)
        self.assertFalse(result["success"])
        self.log.assert_not_called()
        self.replace.assert_not_called()
        self.tracked.assert_not_called()

    def test_failed_download_produces_nonzero_cli_exit(self):
        services = {"test_service": {
            "url": "https://source.test/MapServer",
            "layers": [{"id": 1, "table": "building_blocks"}],
        }}
        self.http.side_effect = requests.exceptions.Timeout("source unavailable")
        with patch.object(sync_all, "SERVICES", services), \
                patch.object(sync_all, "test_connection", return_value=True), \
                patch("sys.argv", ["sync_all.py", "--no-log"]):
            with self.assertRaises(SystemExit) as exc:
                sync_all.main()
        self.assertEqual(exc.exception.code, 1)
        self.replace.assert_not_called()
        self.tracked.assert_not_called()


if __name__ == "__main__":
    unittest.main()
