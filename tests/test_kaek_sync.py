"""Offline cadastral snapshot, source-validation and rollback regressions."""

import os
import unittest
from unittest.mock import MagicMock, patch

import requests

with patch.dict(os.environ, {"EPOL_DB_PASSWORD": "unused-by-offline-tests"}):
    import sync_kaek_operating as cad

from sync_safety import FetchError, LoadError
from tests.support import OfflineCase, response


TABLE = "kaek_parcels_operating"
SERVICE = "test_cadastre"
FIELDS = [("OBJECTID", "bigint"), ("KAEK", "text")]


def ids(*values):
    return {"objectIdFieldName": "OBJECTID", "objectIds": list(values)}


def collection(*values):
    return {"type": "FeatureCollection", "features": [{
        "type": "Feature", "properties": {"OBJECTID": i, "KAEK": f"051340000{i:03d}"},
        "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
    } for i in values]}


class CadastreFetchTests(OfflineCase):
    def test_failed_or_malformed_counts_are_errors(self):
        for payload in ({}, {"count": -1}, {"count": True}, {"count": "3"},
                        {"error": {"message": "unavailable"}}):
            with self.subTest(payload=payload):
                self.http.side_effect = None
                self.http.return_value = response(payload)
                with self.assertRaises(FetchError):
                    cad.count_features(SERVICE)
        self.http.side_effect = requests.exceptions.Timeout("timed out")
        with self.assertRaises(FetchError):
            cad.count_features(SERVICE)

    def test_invalid_layer_metadata_is_rejected(self):
        valid = {"name": "OBJECTID", "type": "esriFieldTypeOID"}
        for fields in (None, [], [{}], [valid, valid],
                       [{"name": 'bad"name', "type": "esriFieldTypeString"}],
                       [{"name": "geom", "type": "esriFieldTypeString"}],
                       [{"name": "new_field", "type": "unknownType"}]):
            with self.subTest(fields=fields):
                self.http.side_effect = None
                self.http.return_value = response({"fields": fields})
                with self.assertRaises(FetchError):
                    cad.get_layer_fields(SERVICE)

    def test_known_metadata_types_and_skipped_shape_fields(self):
        self.http.side_effect = None
        self.http.return_value = response({"fields": [
            {"name": "OBJECTID", "type": "esriFieldTypeOID"},
            {"name": "KAEK", "type": "esriFieldTypeString"},
            {"name": "GlobalID", "type": "esriFieldTypeGlobalID"},
            {"name": "Shape__Area", "type": "esriFieldTypeDouble"},
        ]})
        self.assertEqual(cad.get_layer_fields(SERVICE), FIELDS + [("GlobalID", "text")])

    def test_invalid_identity_snapshots_are_rejected(self):
        for payload in ({}, {"objectIdFieldName": "OBJECTID", "objectIds": None},
                        ids(1, 1), ids(True), ids("1"),
                        {"objectIdFieldName": [], "objectIds": []}):
            with self.subTest(payload=payload):
                self.http.side_effect = [response({"count": 1}), response(payload)]
                with self.assertRaises(FetchError):
                    cad.fetch_features(SERVICE)

    def test_count_and_identity_snapshot_must_agree(self):
        self.http.side_effect = [response({"count": 3}), response(ids(1, 2))]
        with self.assertRaisesRegex(FetchError, "count/object-ID mismatch"):
            cad.fetch_features(SERVICE)

    def test_short_server_capped_batches_fetch_only_missing_ids(self):
        self.http.side_effect = [response({"count": 3}), response(ids(1, 2, 3)),
                                 response(collection(1)), response(collection(2, 3)),
                                 response(ids(3, 1, 2))]
        self.assertEqual(cad.fetch_features(SERVICE), collection(1, 2, 3)["features"])
        data_calls = [c for c in self.http.call_args_list if "objectIds" in c.kwargs.get("data", {})]
        self.assertEqual([c.kwargs["data"]["objectIds"] for c in data_calls], ["1,2,3", "2,3"])
        for call in data_calls:
            self.assertNotIn("params", call.kwargs)
            self.assertEqual(call.kwargs["data"]["maxAllowableOffset"], "0")
            self.assertEqual(call.kwargs["data"]["outSR"], "2100")

    def test_failed_later_batch_never_returns_partial_features(self):
        self.http.side_effect = [response({"count": 3}), response(ids(1, 2, 3)),
                                 response(collection(1)), requests.exceptions.Timeout("batch failed")]
        with self.assertRaises(FetchError):
            cad.fetch_features(SERVICE)

    def test_empty_later_batch_rejects_partial_features(self):
        self.http.side_effect = [response({"count": 3}), response(ids(1, 2, 3)),
                                 response(collection(1)), response(collection())]
        with self.assertRaisesRegex(FetchError, "incomplete download"):
            cad.fetch_features(SERVICE)

    def test_duplicate_or_unrequested_downloaded_ids_are_rejected(self):
        for batch in (collection(1, 1), collection(9)):
            with self.subTest(batch=batch):
                self.http.side_effect = [response({"count": 2}), response(ids(1, 2)), response(batch)]
                with self.assertRaises(FetchError):
                    cad.fetch_features(SERVICE)

    def test_ignored_id_filter_cannot_repeat_an_already_fetched_page(self):
        self.http.side_effect = [response({"count": 2}), response(ids(1, 2)),
                                 response(collection(1)), response(collection(1))]
        with self.assertRaisesRegex(FetchError, "unexpected/missing object ID"):
            cad.fetch_features(SERVICE)

    def test_changed_final_membership_is_detected_even_at_the_same_count(self):
        self.http.side_effect = [response({"count": 2}), response(ids(1, 2)),
                                 response(collection(1, 2)), response(ids(1, 3))]
        with self.assertRaisesRegex(FetchError, "IDs changed"):
            cad.fetch_features(SERVICE)

    def test_verified_empty_snapshot_is_empty_data(self):
        self.http.side_effect = [response({"count": 0}), response(ids()), response(ids())]
        self.assertEqual(cad.fetch_features(SERVICE), [])


class CadastreLoadTests(OfflineCase):
    def setUp(self):
        super().setUp()
        self.conn = MagicMock()
        self.cur = self.conn.cursor.return_value.__enter__.return_value
        self.cur.fetchone.return_value = (1, 0)
        self.cur.fetchall.return_value = []
        self.fields = self.start_patch(patch.object(cad, "get_layer_fields", return_value=FIELDS))
        self.batch = self.start_patch(patch("psycopg2.extras.execute_batch"))
        self.diff = self.start_patch(patch.object(cad, "_diff_before_swap", return_value=None))
        self.publish = self.start_patch(patch.object(cad, "_publish_staged"))

    def test_failed_download_uses_no_table_sql(self):
        self.http.side_effect = [response({"count": 3}), response(ids(1, 2, 3)),
                                 response(collection(1)), requests.exceptions.Timeout("batch failed")]
        with self.assertRaises(FetchError):
            cad.sync_layer(self.conn, TABLE, SERVICE)
        self.conn.cursor.assert_not_called()
        self.conn.commit.assert_not_called()
        self.batch.assert_not_called()

    def test_invalid_source_records_never_reach_staging(self):
        records = []
        for problem in ("missing-field", "null-geometry", "wrong-geometry", "missing-kaek"):
            feat = collection(1)["features"][0]
            if problem == "missing-field":
                del feat["properties"]["KAEK"]
            elif problem == "null-geometry":
                feat["geometry"] = None
            elif problem == "wrong-geometry":
                feat["geometry"] = {"type": "Point", "coordinates": [0, 0]}
            else:
                feat["properties"]["KAEK"] = None
            records.append(feat)
        for feat in records:
            with self.subTest(feature=feat), patch.object(cad, "fetch_features", return_value=[feat]):
                with self.assertRaises(FetchError):
                    cad.sync_layer(self.conn, TABLE, SERVICE)
        self.conn.cursor.assert_not_called()

    def test_missing_kaek_metadata_blocks_download_and_staging(self):
        self.fields.return_value = [("OBJECTID", "bigint")]
        with patch.object(cad, "fetch_features") as fetch:
            with self.assertRaisesRegex(FetchError, "missing KAEK"):
                cad.sync_layer(self.conn, TABLE, SERVICE)
        fetch.assert_not_called()
        self.conn.cursor.assert_not_called()

    def test_stage_count_or_geometry_failure_rolls_back_before_live_table_drop(self):
        for staged in ((0, 0), (1, 1)):
            with self.subTest(staged=staged), patch.object(
                    cad, "fetch_features", return_value=collection(1)["features"]):
                self.conn.reset_mock()
                self.cur.fetchone.return_value = staged
                with self.assertRaises(LoadError):
                    cad.sync_layer(self.conn, TABLE, SERVICE)
                self.conn.rollback.assert_called_once()
                self.conn.commit.assert_not_called()
                self.assertFalse(any(f"{TABLE} CASCADE" in c.args[0]
                                     for c in self.cur.execute.call_args_list))
                self.diff.assert_not_called()

    def test_batch_write_failure_rolls_back(self):
        self.batch.side_effect = RuntimeError("insert failed")
        with patch.object(cad, "fetch_features", return_value=collection(1)["features"]):
            with self.assertRaisesRegex(LoadError, "rolled back"):
                cad.sync_layer(self.conn, TABLE, SERVICE)
        self.conn.rollback.assert_called_once()
        self.conn.commit.assert_not_called()

    def test_publication_failure_rolls_back(self):
        self.publish.side_effect = RuntimeError("publication failed")
        with patch.object(cad, "fetch_features", return_value=collection(1)["features"]):
            with self.assertRaisesRegex(LoadError, "publication failed"):
                cad.sync_layer(self.conn, TABLE, SERVICE)
        self.conn.rollback.assert_called_once()
        self.conn.commit.assert_not_called()

    def test_successful_verified_load_commits_once(self):
        with patch.object(cad, "fetch_features", return_value=collection(1)["features"]):
            self.assertEqual(cad.sync_layer(self.conn, TABLE, SERVICE), (True, None))
        self.conn.commit.assert_called_once()
        self.conn.rollback.assert_not_called()
        self.batch.assert_called_once()
        self.assertEqual(self.batch.call_args.args[2][0][:2], (1, "051340000001"))

    def test_empty_snapshot_preserves_existing_table(self):
        with patch.object(cad, "fetch_features", return_value=[]):
            self.assertEqual(cad.sync_layer(self.conn, TABLE, SERVICE), (False, None))
        self.conn.cursor.assert_not_called()
        self.conn.commit.assert_not_called()


class CadastreCliTests(OfflineCase):
    def test_failed_dry_run_returns_nonzero_without_connecting(self):
        self.http.side_effect = requests.exceptions.Timeout("source unavailable")
        with patch("sys.argv", ["sync_kaek_operating.py", "--dry-run", "--table", TABLE]):
            with self.assertRaises(SystemExit) as exc:
                cad.main()
        self.assertEqual(exc.exception.code, 1)
        self.connect.assert_not_called()

    def test_download_failure_closes_connection_and_returns_nonzero(self):
        conn = MagicMock()
        with patch("sys.argv", ["sync_kaek_operating.py", "--table", TABLE]), \
                patch.object(cad, "DB", {"password": "dummy"}), \
                patch("psycopg2.connect", return_value=conn), \
                patch.object(cad, "sync_layer", side_effect=FetchError("incomplete download")), \
                patch.object(cad, "write_changes_report") as report:
            with self.assertRaises(SystemExit) as exc:
                cad.main()
        self.assertEqual(exc.exception.code, 1)
        conn.close.assert_called_once()
        conn.commit.assert_not_called()
        report.assert_not_called()


if __name__ == "__main__":
    unittest.main()
