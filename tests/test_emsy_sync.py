"""Offline EMSY identity, geometry, retention and transaction regressions."""

from copy import deepcopy
import unittest
from unittest.mock import MagicMock, patch

import requests

import sync_ydrolipsies as emsy
from sync_safety import FetchError, LoadError, SyncError
from tests.support import OfflineCase, response


def feature(oid):
    attrs = dict.fromkeys(emsy.ATTRIBUTES)
    attrs.update(OBJECTID=oid, KWDIKOS_EMSY=f"TEST-{oid}")
    return {"attributes": attrs, "geometry": {
        "x": 420000 + oid, "y": 4120000, "spatialReference": {"wkid": 2100},
    }}


def identities(*oids):
    return {"objectIdFieldName": "OBJECTID", "objectIds": list(oids)}


def page(*oids):
    return {"geometryType": "esriGeometryPoint", "spatialReference": {"wkid": 2100},
            "features": [feature(i) for i in oids], "exceededTransferLimit": False}


class EmsyFetchTests(OfflineCase):
    def test_failed_count_is_not_a_valid_empty_source(self):
        self.http.side_effect = requests.exceptions.Timeout("source unavailable")
        with self.assertRaises(FetchError):
            emsy.fetch_features(emsy.DEFAULT_BBOX)

    def test_invalid_counts_and_identity_lists_are_errors(self):
        for count, ids in (({}, identities()), ({"count": 2}, identities(1)),
                           ({"count": 2}, identities(1, 1)),
                           ({"count": 1}, {"objectIdFieldName": "RENAMED", "objectIds": [1]})):
            with self.subTest(count=count, ids=ids):
                self.http.side_effect = [response(count), response(ids)]
                with self.assertRaises(FetchError):
                    emsy.fetch_features(emsy.DEFAULT_BBOX)

    def test_short_batch_ignores_unreliable_transfer_limit_flag(self):
        self.http.side_effect = [response({"count": 3}), response(identities(1, 2, 3)),
                                 response(page(1)), response(page(2, 3)),
                                 response(identities(3, 2, 1))]
        result = emsy.fetch_features(emsy.DEFAULT_BBOX)
        self.assertEqual([f["attributes"]["OBJECTID"] for f in result], [1, 2, 3])
        batches = [c.kwargs["data"] for c in self.http.call_args_list if "data" in c.kwargs]
        self.assertEqual([p["objectIds"] for p in batches], ["1,2,3", "2,3"])
        self.assertEqual(batches[0]["outFields"], ",".join(emsy.ATTRIBUTES))
        self.assertEqual(batches[0]["outSR"], 2100)

    def test_failed_later_page_never_returns_partial_data(self):
        self.http.side_effect = [response({"count": 2}), response(identities(1, 2)),
                                 response(page(1)), requests.exceptions.Timeout("second batch failed")]
        with self.assertRaises(FetchError):
            emsy.fetch_features(emsy.DEFAULT_BBOX)

    def test_empty_later_page_is_an_error(self):
        self.http.side_effect = [response({"count": 2}), response(identities(1, 2)),
                                 response(page(1)), response(page())]
        with self.assertRaisesRegex(FetchError, "incomplete download"):
            emsy.fetch_features(emsy.DEFAULT_BBOX)

    def test_duplicate_or_unrequested_features_are_rejected(self):
        for batch in (page(1, 1), page(9)):
            with self.subTest(batch=batch):
                self.http.side_effect = [response({"count": 2}), response(identities(1, 2)), response(batch)]
                with self.assertRaises(FetchError):
                    emsy.fetch_features(emsy.DEFAULT_BBOX)

    def test_same_count_membership_change_is_rejected(self):
        self.http.side_effect = [response({"count": 1}), response(identities(1)),
                                 response(page(1)), response(identities(2))]
        with self.assertRaisesRegex(FetchError, "IDs changed"):
            emsy.fetch_features(emsy.DEFAULT_BBOX)

    def test_malformed_feature_sets_or_wrong_crs_are_errors(self):
        bad_srid = page(1)
        bad_srid["spatialReference"] = {"wkid": 4326}
        missing_srid = page(1)
        del missing_srid["spatialReference"]
        wrong_type = page(1)
        wrong_type["geometryType"] = "esriGeometryPolygon"
        outside = page(1)
        outside["features"][0]["geometry"]["x"] = 0
        for payload in ({"error": {"message": "service changed"}}, {}, bad_srid,
                        missing_srid, wrong_type, outside):
            with self.subTest(payload=payload):
                self.http.side_effect = [response({"count": 1}), response(identities(1)), response(payload)]
                with self.assertRaises(FetchError):
                    emsy.fetch_features(emsy.DEFAULT_BBOX)

    def test_response_reference_is_carried_into_points_without_mutating_source(self):
        batch = page(1)
        del batch["features"][0]["geometry"]["spatialReference"]
        original = deepcopy(batch)
        self.http.side_effect = [response({"count": 1}), response(identities(1)),
                                 response(batch), response(identities(1))]
        result = emsy.fetch_features(emsy.DEFAULT_BBOX)
        self.assertEqual(result[0]["geometry"]["spatialReference"], {"wkid": 2100})
        self.assertEqual(batch, original)

    def test_verified_empty_source_is_allowed(self):
        self.http.side_effect = [response({"count": 0}), response(identities()), response(identities())]
        self.assertEqual(emsy.fetch_features(emsy.DEFAULT_BBOX), [])

    def test_invalid_bbox_fails_before_network_access(self):
        for bbox in ((0, 1, 2), (0, 0, 0, 1), (2, 0, 1, 1), (0, 0, float("inf"), 1)):
            with self.subTest(bbox=bbox), self.assertRaises(ValueError):
                emsy.fetch_features(bbox)
        self.http.assert_not_called()


class EmsyLoadTests(OfflineCase):
    def setUp(self):
        super().setUp()
        self.conn = MagicMock()
        self.cur = self.conn.cursor.return_value.__enter__.return_value
        self.connection = self.start_patch(patch.object(emsy, "get_connection", return_value=self.conn))

    def test_new_updated_unchanged_are_counted_without_deleting_retained_rows(self):
        self.cur.fetchall.return_value = [(2,), (3,)]
        self.cur.fetchone.side_effect = [(1,), (2,), None, (99,)]
        result = emsy.load([feature(1), feature(2), feature(3)])
        self.assertEqual(result, {"new": 1, "updated": 1, "unchanged": 1, "skipped": 0, "total": 99})
        sql = "\n".join(c.args[0] for c in self.cur.execute.call_args_list).upper()
        self.assertNotIn("DELETE ", sql)
        self.assertNotIn("TRUNCATE ", sql)
        self.conn.commit.assert_called_once()
        self.conn.rollback.assert_not_called()
        self.conn.close.assert_called_once()

    def test_later_row_failure_rolls_back_the_whole_load(self):
        self.cur.fetchall.return_value = []
        inserted = []

        def execute(sql, params=None):
            if sql == emsy.UPSERT_SQL:
                inserted.append(params)
                if len(inserted) == 2:
                    raise RuntimeError("record write failed")

        self.cur.execute.side_effect = execute
        self.cur.fetchone.return_value = (1,)
        with self.assertRaisesRegex(LoadError, "rolled back"):
            emsy.load([feature(1), feature(2)])
        self.conn.rollback.assert_called_once()
        self.conn.commit.assert_not_called()
        self.conn.close.assert_called_once()

    def test_invalid_records_are_rejected_before_database_access(self):
        cases = []
        for problem in ("missing-field", "missing-point", "nan", "bool-id", "wrong-srid", "no-srid",
                        "string-coordinate", "bool-coordinate", "huge-coordinate"):
            row = feature(1)
            if problem == "missing-field":
                del row["attributes"]["STATUS"]
            elif problem == "missing-point":
                row["geometry"] = None
            elif problem == "nan":
                row["geometry"]["x"] = float("nan")
            elif problem == "bool-id":
                row["attributes"]["OBJECTID"] = True
            elif problem == "wrong-srid":
                row["geometry"]["spatialReference"] = {"wkid": 4326}
            elif problem == "no-srid":
                del row["geometry"]["spatialReference"]
            else:
                row["geometry"]["x"] = {
                    "string-coordinate": "420001", "bool-coordinate": True,
                    "huge-coordinate": 10 ** 1000,
                }[problem]
            cases.append([row])
        cases.append([feature(1), feature(1)])
        for rows in cases:
            with self.subTest(rows=rows), self.assertRaises(SyncError):
                emsy.load(rows)
        self.connection.assert_not_called()

    def test_objectid_zero_is_a_valid_identity(self):
        self.cur.fetchall.return_value = []
        self.cur.fetchone.side_effect = [(0,), (1,)]
        result = emsy.load([feature(0)])
        self.assertEqual(result["new"], 1)
        upsert = next(c for c in self.cur.execute.call_args_list if c.args[0] == emsy.UPSERT_SQL)
        self.assertEqual(upsert.args[1][0], 0)

    def test_dry_run_and_empty_input_never_connect(self):
        self.assertEqual(emsy.load([feature(1)], dry_run=True)["total"], None)
        self.assertEqual(emsy.load([])["total"], None)
        self.connection.assert_not_called()


class EmsyCliTests(OfflineCase):
    def test_invalid_bbox_returns_two_without_fetching(self):
        for bbox in ("1,2,3", "0,0,nan,1", "2,0,1,1"):
            with self.subTest(bbox=bbox), patch("sys.argv", ["sync_ydrolipsies.py", "--bbox", bbox]):
                with self.assertRaises(SystemExit) as exc:
                    emsy.main()
                self.assertEqual(exc.exception.code, 2)
        self.http.assert_not_called()

    def test_failed_download_cannot_reach_loader(self):
        with patch("sys.argv", ["sync_ydrolipsies.py"]), \
                patch.object(emsy, "fetch_features", side_effect=FetchError("incomplete")), \
                patch.object(emsy, "load") as load:
            with self.assertRaises(SystemExit) as exc:
                emsy.main()
        self.assertEqual(exc.exception.code, 1)
        load.assert_not_called()

    def test_failed_load_returns_nonzero(self):
        with patch("sys.argv", ["sync_ydrolipsies.py"]), \
                patch.object(emsy, "fetch_features", return_value=[feature(1)]), \
                patch.object(emsy, "load", side_effect=LoadError("rolled back")):
            with self.assertRaises(SystemExit) as exc:
                emsy.main()
        self.assertEqual(exc.exception.code, 1)

    def test_real_dry_run_flow_uses_no_database(self):
        self.http.side_effect = [response({"count": 1}), response(identities(1)),
                                 response(page(1)), response(identities(1))]
        with patch("sys.argv", ["sync_ydrolipsies.py", "--dry-run"]):
            emsy.main()
        self.connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
