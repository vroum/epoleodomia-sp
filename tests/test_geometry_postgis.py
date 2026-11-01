"""Opt-in, read-only PostGIS checks. Uses VALUES only, never application tables."""

import os
import unittest

import psycopg2

from sync_geometry import geometry_changes


@unittest.skipUnless(os.environ.get("EPOL_TEST_POSTGIS_DSN"),
                     "Set EPOL_TEST_POSTGIS_DSN to opt into read-only PostGIS tests")
class PostGISGeometryTests(unittest.TestCase):
    def setUp(self):
        self.conn = psycopg2.connect(
            os.environ["EPOL_TEST_POSTGIS_DSN"], connect_timeout=5,
            options="-c default_transaction_read_only=on")
        self.addCleanup(self.conn.close)
        self.addCleanup(self.conn.rollback)
        self.cur = self.conn.cursor()
        self.addCleanup(self.cur.close)
        self.cur.execute("SHOW transaction_read_only")
        self.assertEqual(self.cur.fetchone()[0], "on")

    def old_binary(self, wkt):
        self.cur.execute("SELECT ST_AsEWKB(ST_GeomFromText(%s, 2100))", (wkt,))
        return self.cur.fetchone()[0]

    def check_pairs(self, cases):
        pairs = [(i, self.old_binary(old), new) for i, (old, new, changed) in enumerate(cases)]
        self.assertEqual(geometry_changes(self.cur, pairs),
                         {i: changed for i, (_, _, changed) in enumerate(cases)})

    def test_same_length_moves_and_equal_area_translations_are_changes(self):
        self.check_pairs([
            ("POINT(420001 4120000)", "POINT(420002 4120000)", True),
            ("POLYGON((0 0,2 0,2 2,0 2,0 0))", "POLYGON((1 0,3 0,3 2,1 2,1 0))", True),
            ("POINT(0 0)", "POINT(0.000001 0)", True),
        ])

    def test_vertex_order_and_redundant_collinear_vertices_are_unchanged(self):
        self.check_pairs([
            ("POLYGON((0 0,2 0,2 2,0 2,0 0))", "POLYGON((2 2,2 0,0 0,0 2,2 2))", False),
            ("LINESTRING(0 0,10 10)", "LINESTRING(10 10,5 5,0 0)", False),
            ("MULTIPOINT((0 0),(1 1))", "MULTIPOINT((1 1),(0 0))", False),
        ])

    def test_holes_and_multipart_geometry(self):
        self.check_pairs([
            ("POLYGON((0 0,4 0,4 4,0 4,0 0),(1 1,1 2,2 2,2 1,1 1))",
             "POLYGON((0 0,4 0,4 4,0 4,0 0))", True),
            ("MULTIPOLYGON(((0 0,1 0,1 1,0 0)),((3 3,4 3,4 4,3 3)))",
             "MULTIPOLYGON(((3 3,4 3,4 4,3 3)),((0 0,1 0,1 1,0 0)))", False),
        ])

    def test_null_transitions(self):
        self.check_pairs([(None, None, False), (None, "POINT(0 0)", True),
                          ("POINT(0 0)", None, True)])

    def test_binary_transport_preserves_small_coordinate_changes(self):
        self.check_pairs([
            ("POINT(0.12345678912345678 1)", "POINT(0.12345678912345678 1)", False),
            ("POINT(0.12345678912345678 1)", "POINT(0.123456789123457 1)", True),
        ])

    def test_results_survive_multiple_values_batches(self):
        old = self.old_binary("POINT(0 0)")
        pairs = [(i, old, f"POINT({i % 2} 0)") for i in range(1001)]
        self.assertEqual(geometry_changes(self.cur, pairs), {i: bool(i % 2) for i in range(1001)})
