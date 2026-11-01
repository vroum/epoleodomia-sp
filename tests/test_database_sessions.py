"""Transaction ownership, cleanup and pool reuse without a live database."""

from unittest.mock import MagicMock, call

from psycopg2 import errors, sql

from database_sessions import read_only_snapshot
from tests.support import OfflineCase


class SnapshotTests(OfflineCase):
    def setUp(self):
        super().setUp()
        self.pool = MagicMock()
        self.conn = self.pool.getconn.return_value
        self.conn.autocommit = True
        self.cursor = self.conn.cursor.return_value.__enter__.return_value

    def test_queries_share_one_cursor_and_restore_the_session(self):
        self.cursor.fetchone.return_value = (1,)
        self.cursor.fetchall.return_value = [(2,), (3,)]
        with read_only_snapshot(self.pool) as query:
            self.assertFalse(self.conn.autocommit)
            self.assertEqual(query("SELECT %s", (1,), fetch_one=True), (1,))
            self.assertEqual(query("SELECT %s", (2,)), [(2,), (3,)])
            self.pool.putconn.assert_not_called()
        self.pool.getconn.assert_called_once_with()
        self.conn.cursor.assert_called_once_with()
        self.assertEqual(self.cursor.execute.call_args_list, [
            call("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"),
            call("SELECT %s", (1,)), call("SELECT %s", (2,))])
        self.assertTrue(self.conn.autocommit)
        self.assertEqual(self.conn.rollback.call_count, 2)
        self.conn.commit.assert_not_called()
        self.pool.putconn.assert_called_once_with(self.conn, close=False)

    def test_relation_identifiers_are_quoted_and_locked_before_queries(self):
        relations = (("sp_geodata", "kaek_parcels_operating"),
                     ("sp_geodata", "kaek_apokleistikes_operating"))
        with read_only_snapshot(self.pool, protected_relations=relations) as query:
            query("SELECT 1", fetch_one=True)
        expected = sql.SQL("LOCK TABLE {} IN ACCESS SHARE MODE").format(
            sql.SQL(", ").join([sql.Identifier(*relation) for relation in relations]))
        self.assertEqual(self.cursor.execute.call_args_list[1], call(expected))
        self.assertEqual(self.cursor.execute.call_args_list[2], call("SELECT 1", None))

    def test_transaction_setup_failure_does_not_yield_or_leak(self):
        self.cursor.execute.side_effect = RuntimeError("setup failed")
        with self.assertRaisesRegex(RuntimeError, "setup failed"):
            with read_only_snapshot(self.pool):
                self.fail("Setup failure must not yield a query session")
        self.assertTrue(self.conn.autocommit)
        self.pool.putconn.assert_called_once_with(self.conn, close=False)

    def test_lock_failure_does_not_run_the_calculation(self):
        self.cursor.execute.side_effect = [None, RuntimeError("lock failed")]
        with self.assertRaisesRegex(RuntimeError, "lock failed"):
            with read_only_snapshot(self.pool, protected_relations=(("schema", "table"),)):
                self.fail("Lock failure must not yield a query session")
        self.pool.putconn.assert_called_once_with(self.conn, close=False)

    def test_calculation_failure_rolls_back_and_restores_autocommit(self):
        with self.assertRaisesRegex(ValueError, "calculation failed"):
            with read_only_snapshot(self.pool):
                raise ValueError("calculation failed")
        self.assertTrue(self.conn.autocommit)
        self.assertEqual(self.conn.rollback.call_count, 2)
        self.pool.putconn.assert_called_once_with(self.conn, close=False)

    def test_initial_autocommit_false_stays_false(self):
        self.conn.autocommit = False
        with read_only_snapshot(self.pool):
            pass
        self.assertFalse(self.conn.autocommit)
        self.pool.putconn.assert_called_once_with(self.conn, close=False)

    def test_cleanup_failure_discards_the_connection_and_propagates(self):
        self.conn.rollback.side_effect = [None, RuntimeError("rollback failed")]
        with self.assertRaisesRegex(RuntimeError, "rollback failed"):
            with read_only_snapshot(self.pool):
                pass
        self.pool.putconn.assert_called_once_with(self.conn, close=True)

    def test_cleanup_failure_keeps_the_original_calculation_error(self):
        self.conn.rollback.side_effect = [None, RuntimeError("rollback failed")]
        with self.assertLogs("database_sessions", level="ERROR"):
            with self.assertRaisesRegex(ValueError, "original calculation error"):
                with read_only_snapshot(self.pool):
                    raise ValueError("original calculation error")
        self.pool.putconn.assert_called_once_with(self.conn, close=True)

    def test_acquisition_failure_has_no_connection_to_return(self):
        self.pool.getconn.side_effect = RuntimeError("pool exhausted")
        with self.assertRaisesRegex(RuntimeError, "pool exhausted"):
            with read_only_snapshot(self.pool):
                self.fail("Acquisition failure must not yield")
        self.pool.putconn.assert_not_called()

    def test_pool_return_failure_closes_connection_and_propagates(self):
        self.pool.putconn.side_effect = RuntimeError("pool return failed")
        with self.assertRaisesRegex(RuntimeError, "pool return failed"):
            with read_only_snapshot(self.pool):
                pass
        self.conn.close.assert_called_once_with()

    def test_failed_optional_group_rolls_back_only_to_savepoint_and_can_continue(self):
        self.cursor.fetchone.return_value = (42,)
        with read_only_snapshot(self.pool) as query:
            with self.assertRaisesRegex(ValueError, "optional failed"):
                with query.savepoint():
                    raise ValueError("optional failed")
            self.assertEqual(self.conn.rollback.call_count, 1)
            self.assertEqual(query("SELECT 42", fetch_one=True), (42,))
        calls = self.cursor.execute.call_args_list
        self.assertIn(call("ROLLBACK TO SAVEPOINT epol_read_1"), calls)
        self.assertIn(call("RELEASE SAVEPOINT epol_read_1"), calls)
        self.pool.putconn.assert_called_once_with(self.conn, close=False)

    def test_successful_and_nested_optional_groups_use_distinct_savepoints(self):
        with read_only_snapshot(self.pool) as query:
            with query.savepoint():
                with query.savepoint():
                    pass
        self.assertEqual(self.cursor.execute.call_args_list[1:], [
            call("SAVEPOINT epol_read_1"), call("SAVEPOINT epol_read_2"),
            call("RELEASE SAVEPOINT epol_read_2"), call("RELEASE SAVEPOINT epol_read_1")])

    def test_optional_locks_happen_before_queries_and_missing_source_is_recorded(self):
        required = (("schema", "required"),)
        optional = (("schema", "optional"),)
        optional_lock = sql.SQL("LOCK TABLE {} IN ACCESS SHARE MODE").format(
            sql.SQL(", ").join([sql.Identifier(*optional[0])]))

        def execute(statement, params=None):
            if statement == optional_lock:
                raise errors.UndefinedTable("synthetic missing optional relation")

        self.cursor.execute.side_effect = execute
        with self.assertLogs("database_sessions", level="WARNING"):
            with read_only_snapshot(self.pool, protected_relations=required,
                                    optional_relations=optional) as query:
                self.assertEqual(query.unavailable_relations, set(optional))
                query("SELECT 42", fetch_one=True)
        self.assertEqual(self.cursor.execute.call_args_list[-1], call("SELECT 42", None))
        self.assertIn(call("ROLLBACK TO SAVEPOINT epol_read_1"), self.cursor.execute.call_args_list)
        self.pool.putconn.assert_called_once_with(self.conn, close=False)

    def test_optional_permission_failure_is_unavailable_after_successful_recovery(self):
        lock = sql.SQL("LOCK TABLE {} IN ACCESS SHARE MODE").format(
            sql.SQL(", ").join([sql.Identifier("schema", "optional")]))
        def execute(statement, params=None):
            if statement == lock:
                raise errors.InsufficientPrivilege("denied")
        self.cursor.execute.side_effect = execute
        with self.assertLogs("database_sessions", level="WARNING"):
            with read_only_snapshot(self.pool, optional_relations=(("schema", "optional"),)) as query:
                self.assertEqual(query.unavailable_relations, {("schema", "optional")})
        self.pool.putconn.assert_called_once_with(self.conn, close=False)

    def test_swallowed_savepoint_failures_still_abort_snapshot_and_discard_connection(self):
        for phase in ("SAVEPOINT", "ROLLBACK TO SAVEPOINT", "RELEASE SAVEPOINT"):
            with self.subTest(phase=phase):
                self.pool.putconn.reset_mock()
                def execute(statement, params=None):
                    if isinstance(statement, str) and statement == phase + " epol_read_1":
                        raise RuntimeError("savepoint recovery failed")
                self.cursor.execute.side_effect = execute
                with self.assertRaisesRegex(RuntimeError, "savepoint recovery failed"):
                    with read_only_snapshot(self.pool) as query:
                        try:
                            with query.savepoint():
                                if phase == "ROLLBACK TO SAVEPOINT":
                                    raise ValueError("optional group failed")
                        except Exception:
                            pass  # A provider must not hide a broken session.
                self.pool.putconn.assert_called_once_with(self.conn, close=True)

    def test_recovery_failure_preserves_uncaught_original_error(self):
        def execute(statement, params=None):
            if statement == "ROLLBACK TO SAVEPOINT epol_read_1":
                raise RuntimeError("recovery failed")
        self.cursor.execute.side_effect = execute
        with self.assertRaisesRegex(ValueError, "original error"):
            with read_only_snapshot(self.pool) as query:
                with query.savepoint():
                    raise ValueError("original error")
        self.pool.putconn.assert_called_once_with(self.conn, close=True)

    def test_optional_lock_programming_error_does_not_become_missing_data(self):
        def execute(statement, params=None):
            if isinstance(statement, sql.Composed):
                raise ValueError("bad relation setup")
        self.cursor.execute.side_effect = execute
        with self.assertRaisesRegex(ValueError, "bad relation setup"):
            with read_only_snapshot(self.pool, optional_relations=(("schema", "optional"),)):
                self.fail("Unexpected session")
        self.pool.putconn.assert_called_once_with(self.conn, close=False)
