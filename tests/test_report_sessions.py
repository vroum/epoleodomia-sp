"""Report routes own one snapshot, including optional-source availability."""

import asyncio
from unittest.mock import MagicMock, call, patch

from psycopg2 import errors, sql

import api_server as api
from planning_data import PlanningData, POINT_REPORT_RELATIONS, PARCEL_REPORT_RELATIONS, WATER_RELATION
from tests.support import OfflineCase


class ReportSessionTests(OfflineCase):
    def setUp(self):
        super().setUp()
        self.pool = MagicMock()
        self.conn = self.pool.getconn.return_value
        self.conn.autocommit = True
        self.cursor = self.conn.cursor.return_value.__enter__.return_value
        self.start_patch(patch.object(api, "db_pool", self.pool))
        self.start_patch(patch.object(api, "execute_query", side_effect=AssertionError("Snapshot bypass")))

    def test_both_routes_use_one_cursor_with_all_source_locks_before_collection(self):
        for endpoint, method, relations in (
                (api.get_report_rows, "point_report", POINT_REPORT_RELATIONS),
                (api.get_report_parcel, "parcel_report", PARCEL_REPORT_RELATIONS)):
            with self.subTest(method=method):
                self.pool.reset_mock()
                self.cursor.reset_mock()
                self.cursor.fetchone.return_value = ("RESULT",)
                required_lock = sql.SQL("LOCK TABLE {} IN ACCESS SHARE MODE").format(
                    sql.SQL(", ").join(sql.Identifier(*r) for r in relations))
                optional_lock = sql.SQL("LOCK TABLE {} IN ACCESS SHARE MODE").format(
                    sql.SQL(", ").join([sql.Identifier(*WATER_RELATION)]))
                def collect(data, x, y):
                    self.assertIs(data.query.cursor, self.cursor)
                    self.assertTrue(data.water_available)
                    self.assertEqual(self.cursor.execute.call_args_list[:4], [
                        call("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"),
                        call(required_lock), call("SAVEPOINT epol_read_1"), call(optional_lock)])
                    self.assertEqual((x, y), (10, 20))
                    return data.query("SELECT 42", fetch_one=True)[0]
                with patch.object(PlanningData, method, autospec=True, side_effect=collect):
                    self.assertEqual(asyncio.run(endpoint(10, 20)), "RESULT")
                self.pool.getconn.assert_called_once_with()
                self.conn.cursor.assert_called_once_with()
                self.pool.putconn.assert_called_once_with(self.conn, close=False)
                self.assertTrue(self.conn.autocommit)

    def test_unavailable_optional_lock_disables_water_queries_for_this_report(self):
        optional_lock = sql.SQL("LOCK TABLE {} IN ACCESS SHARE MODE").format(
            sql.SQL(", ").join([sql.Identifier(*WATER_RELATION)]))
        def execute(statement, params=None):
            if statement == optional_lock:
                raise errors.UndefinedTable("Synthetic missing EMSY")
        self.cursor.execute.side_effect = execute
        def collect(data, x, y):
            self.assertFalse(data.water_available)
            self.assertFalse(data.get_water_points(x, y)["available"])
            self.assertEqual(self.cursor.fetchone.call_count, 0)
            self.assertEqual(self.cursor.fetchall.call_count, 0)
            return "RESULT"
        with self.assertLogs("database_sessions", level="WARNING"):
            with patch.object(PlanningData, "point_report", autospec=True, side_effect=collect):
                self.assertEqual(asyncio.run(api.get_report_rows(10, 20)), "RESULT")
        self.pool.getconn.assert_called_once_with()
        self.pool.putconn.assert_called_once_with(self.conn, close=False)

    def test_report_failure_rolls_back_the_whole_snapshot(self):
        with patch.object(PlanningData, "parcel_report", side_effect=ValueError("collection failed")):
            with self.assertRaisesRegex(ValueError, "collection failed"):
                asyncio.run(api.get_report_parcel(10, 20))
        self.assertEqual(self.conn.rollback.call_count, 2)
        self.conn.commit.assert_not_called()
        self.pool.putconn.assert_called_once_with(self.conn, close=False)
