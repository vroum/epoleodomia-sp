"""Opt-in read-only transaction/snapshot checks, using catalog metadata only."""

from contextlib import closing
import os
import unittest

import psycopg2
from psycopg2 import extensions, pool

from database_sessions import read_only_snapshot


@unittest.skipUnless(os.environ.get("EPOL_TEST_POSTGIS_DSN"),
                     "Set EPOL_TEST_POSTGIS_DSN to opt into read-only PostGIS tests")
class SnapshotPostGISTests(unittest.TestCase):
    def setUp(self):
        self.dsn = os.environ["EPOL_TEST_POSTGIS_DSN"]
        self.pool = pool.SimpleConnectionPool(
            1, 1, self.dsn, connect_timeout=5,
            options="-c default_transaction_read_only=on")
        self.addCleanup(self.pool.closeall)

    def test_snapshot_settings_lock_and_session_state_are_cleaned_up(self):
        for autocommit in (False, True):
            with self.subTest(autocommit=autocommit):
                conn = self.pool.getconn()
                conn.rollback()
                conn.autocommit = autocommit
                original = (conn.isolation_level, conn.readonly, conn.deferrable)
                with conn.cursor() as cur:
                    cur.execute("SELECT 'pg_catalog.pg_class'::regclass::oid")
                    relation_oid = cur.fetchone()[0]
                conn.rollback()
                self.pool.putconn(conn)

                with read_only_snapshot(self.pool, protected_relations=(("pg_catalog", "pg_class"),)) as query:
                    first = query("SELECT current_setting('transaction_isolation'), "
                                  "current_setting('transaction_read_only'), pg_backend_pid()", fetch_one=True)
                    self.assertEqual(first[:2], ("repeatable read", "on"))
                    self.assertEqual(query("SELECT pg_backend_pid()", fetch_one=True)[0], first[2])
                    held = query("SELECT EXISTS (SELECT 1 FROM pg_locks WHERE pid = pg_backend_pid() "
                                 "AND relation = %s AND mode = 'AccessShareLock' AND granted)",
                                 (relation_oid,), fetch_one=True)
                    self.assertTrue(held[0])

                reused = self.pool.getconn()
                try:
                    self.assertIs(reused, conn)
                    self.assertEqual(reused.get_transaction_status(), extensions.TRANSACTION_STATUS_IDLE)
                    self.assertEqual(reused.autocommit, autocommit)
                    self.assertEqual((reused.isolation_level, reused.readonly, reused.deferrable), original)
                    with reused.cursor() as cur:
                        cur.execute("SELECT EXISTS (SELECT 1 FROM pg_locks WHERE pid = pg_backend_pid() "
                                    "AND relation = %s AND mode = 'AccessShareLock' AND granted)",
                                    (relation_oid,))
                        self.assertFalse(cur.fetchone()[0])
                finally:
                    reused.rollback()
                    self.pool.putconn(reused)

    def test_failed_query_leaves_the_pooled_connection_reusable(self):
        with self.assertRaises(psycopg2.errors.DivisionByZero):
            with read_only_snapshot(self.pool) as query:
                query("SELECT 1 / 0", fetch_one=True)
        with read_only_snapshot(self.pool) as query:
            self.assertEqual(query("SELECT 42", fetch_one=True), (42,))
            self.assertEqual(query("SHOW transaction_read_only", fetch_one=True), ("on",))

    def test_multiple_source_relations_are_locked_together(self):
        relations = (("pg_catalog", "pg_class"), ("pg_catalog", "pg_namespace"))
        with read_only_snapshot(self.pool, protected_relations=relations) as query:
            locks = query("SELECT relation FROM pg_locks WHERE pid = pg_backend_pid() "
                          "AND mode = 'AccessShareLock' AND granted AND relation IN "
                          "(%s::regclass, %s::regclass)",
                          ("pg_catalog.pg_class", "pg_catalog.pg_namespace"))
            self.assertEqual(len(locks), 2)
            self.assertEqual(query("SHOW transaction_read_only", fetch_one=True), ("on",))

    def test_optional_sources_are_locked_or_marked_unavailable_before_queries(self):
        required = (("pg_catalog", "pg_class"),)
        optional = (("pg_catalog", "pg_namespace"),
                    ("pg_catalog", "epol_test_absent_optional_source"))
        with self.assertLogs("database_sessions", level="WARNING"):
            with read_only_snapshot(self.pool, protected_relations=required,
                                    optional_relations=optional) as query:
                self.assertEqual(query.unavailable_relations, {optional[1]})
                held = query("SELECT relation FROM pg_locks WHERE pid = pg_backend_pid() "
                             "AND mode = 'AccessShareLock' AND granted AND relation IN "
                             "('pg_catalog.pg_class'::regclass, 'pg_catalog.pg_namespace'::regclass)")
                self.assertEqual(len(held), 2)
                self.assertEqual(query("SHOW transaction_read_only", fetch_one=True), ("on",))
        with read_only_snapshot(self.pool) as query:
            self.assertEqual(query("SELECT 42", fetch_one=True), (42,))

    def test_optional_query_failure_keeps_outer_snapshot_after_horizon_advances(self):
        with read_only_snapshot(self.pool) as query:
            before = query("SELECT txid_current_snapshot()::text, pg_backend_pid()", fetch_one=True)
            with self.assertRaises(psycopg2.errors.DivisionByZero):
                with query.savepoint():
                    query("SELECT 1 / 0", fetch_one=True)
            with closing(psycopg2.connect(
                    self.dsn, connect_timeout=5, options="-c default_transaction_read_only=on")) as other:
                with other.cursor() as cur:
                    cur.execute("SELECT txid_current()")
                    other_id = cur.fetchone()[0]
                other.rollback()
            self.assertEqual(query("SELECT txid_current_snapshot()::text, pg_backend_pid()", fetch_one=True), before)
            self.assertEqual(query("SHOW transaction_isolation", fetch_one=True), ("repeatable read",))
            self.assertEqual(query("SHOW transaction_read_only", fetch_one=True), ("on",))
        with read_only_snapshot(self.pool) as query:
            fresh = query("SELECT txid_current_snapshot()::text", fetch_one=True)[0]
        self.assertGreater(int(fresh.split(":")[1]), other_id)

    def test_snapshot_stays_fixed_when_another_read_only_transaction_finishes(self):
        with read_only_snapshot(self.pool) as query:
            before = query("SELECT txid_current_snapshot()::text", fetch_one=True)[0]
            with closing(psycopg2.connect(
                    self.dsn, connect_timeout=5, options="-c default_transaction_read_only=on")) as other:
                with other.cursor() as cur:
                    cur.execute("SHOW transaction_read_only")
                    self.assertEqual(cur.fetchone()[0], "on")
                    # Allocating an ID advances the snapshot horizon without
                    # creating/modifying any database object or application row.
                    cur.execute("SELECT txid_current()")
                    other_id = cur.fetchone()[0]
                other.rollback()
            after = query("SELECT txid_current_snapshot()::text", fetch_one=True)[0]
            self.assertEqual(after, before)

        with read_only_snapshot(self.pool) as query:
            fresh = query("SELECT txid_current_snapshot()::text", fetch_one=True)[0]
        self.assertGreaterEqual(other_id, int(before.split(":")[1]))
        self.assertGreater(int(fresh.split(":")[1]), other_id)
