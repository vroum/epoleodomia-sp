"""Opt-in KGEOM checks: real endpoint SQL against synthetic VALUES, read-only."""

import asyncio
from contextlib import ExitStack, contextmanager
from functools import partial
import os
import re
import unittest
from unittest.mock import AsyncMock, Mock, patch

import psycopg2

import api_server as api
from database_sessions import read_only_snapshot


def rectangle(x0, y0, x1, y1):
    return f"POLYGON(({x0} {y0},{x1} {y0},{x1} {y1},{x0} {y1},{x0} {y0}))"


def ring_body(x0, y0, x1, y1):
    return f"{x0},{y0};{x1},{y0};{x1},{y1};{x0},{y1}"


def ring_wkt(coords):
    pairs = [p.replace(",", " ") for p in coords.split(";")]
    return "POLYGON((" + ",".join(pairs) + "))"


@unittest.skipUnless(os.environ.get("EPOL_TEST_POSTGIS_DSN"),
                     "Set EPOL_TEST_POSTGIS_DSN to opt into read-only PostGIS tests")
class BoundaryCorrectionPostGISTests(unittest.TestCase):
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
        self.parcels = [("S01", rectangle(0, 0, 10, 10)),
                        ("N01", rectangle(10, 0, 20, 10)),
                        ("EK01", rectangle(-10, 0, 0, 10))]

    def query_fixture(self, statement, params=None, fetch_one=False, *, query):
        """Only substitute the parcel source; run the endpoint's own SQL."""
        statement = statement.strip()
        self.assertRegex(statement.upper(), r"^(SELECT|WITH)\b")
        source = "sp_geodata.kaek_parcels_operating"
        statement = statement.replace(source, "fixture_parcels")
        # Refuse any unreplaced application-table/schema reference.
        self.assertNotRegex(statement, r"(?i)\b(sp_geodata|epoleodomia)\s*\.")
        values = ",".join("(%s,%s)" for _ in self.parcels)
        cte = (f"WITH fixture_input(kaek, wkt) AS (VALUES {values}), "
               "fixture_parcels AS (SELECT kaek, ST_GeomFromText(wkt, 2100) AS geom "
               "FROM fixture_input) ")
        if re.match(r"(?i)^WITH\b", statement):
            statement = ", " + statement[4:].lstrip()
        return query(cte + statement,
                     tuple(v for p in self.parcels for v in p) + tuple(params or ()),
                     fetch_one=fetch_one)

    @contextmanager
    def fixture_snapshot(self, pool, *, protected_relations):
        self.assertEqual(protected_relations, (("sp_geodata", "kaek_parcels_operating"),))
        fixture_pool = Mock()
        fixture_pool.getconn.return_value = self.conn
        fixture_pool.putconn.side_effect = lambda conn, close=False: conn.close() if close else None
        # Synthetic VALUES need no table lock. Exercise the actual snapshot
        # transaction while never opening/locking an application relation.
        with read_only_snapshot(fixture_pool) as query:
            yield partial(self.query_fixture, query=query)
        fixture_pool.getconn.assert_called_once_with()
        fixture_pool.putconn.assert_called_once_with(self.conn, close=False)

    def render(self, body, tol=0.5):
        request = AsyncMock()
        request.body.return_value = body.encode("utf-8")
        with ExitStack() as stack:
            stack.enter_context(patch.object(api, "read_only_snapshot", side_effect=self.fixture_snapshot))
            stack.enter_context(patch.object(api, "execute_query", side_effect=AssertionError("Snapshot bypass")))
            stack.enter_context(patch("psycopg2.connect", side_effect=AssertionError("Unexpected connection")))
            result = asyncio.run(api.geom_diorthosi(request, tol=tol))
        self.assertEqual(result.encode("windows-1253").decode("windows-1253"), result)
        return result

    def rows(self, output, kind):
        return [line.split("|") for line in output.splitlines() if line.startswith(kind + "|")]

    def assert_geometry(self, coords, expected):
        self.cur.execute("SELECT ST_Equals(ST_GeomFromText(%s,2100), ST_GeomFromText(%s,2100))",
                         (ring_wkt(coords), expected))
        self.assertTrue(self.cur.fetchone()[0], (coords, expected))

    def assert_finals(self, output, expected):
        finals = self.rows(output, "F")
        self.assertEqual({r[1] for r in finals}, set(expected))
        self.assertEqual(len(finals), len(expected))
        for _, kaek, area, coords in finals:
            expected_area, expected_geom = expected[kaek]
            self.assertEqual(float(area), expected_area)
            self.assert_geometry(coords, expected_geom)

    def assert_balance(self, output, balance=0.0):
        row = next(r for r in output.splitlines() if r.startswith("TBL|MERGED|Ισοζύγιο:"))
        actual = float(re.search(r"= (-?[\d.]+) τ.μ.", row).group(1))
        self.assertEqual(actual, balance)
        self.assertEqual("ΕΛΕΓΞΕ" in row, abs(balance) >= 0.05)

    def test_unchanged_parcel_has_no_transfer_pieces(self):
        result = self.render(ring_body(0, 0, 10, 10))
        self.assertTrue(result.startswith("OK|S01|0.5\n"))
        self.assertEqual(self.rows(result, "D"), [])
        self.assertEqual(self.rows(result, "A"), [])
        self.assert_finals(result, {"S01": (100.0, rectangle(0, 0, 10, 10))})
        self.assert_balance(result)

    def test_shift_claims_from_neighbor_and_assigns_cut_to_road(self):
        result = self.render(ring_body(2, 0, 12, 10))
        d, = self.rows(result, "D")
        a, = self.rows(result, "A")
        self.assertEqual(d[1:4], ["Δ1", "N01", "20.00"])
        self.assertEqual(a[1:4], ["Α1", "EK01", "20.00"])
        self.assert_geometry(d[4], rectangle(10, 0, 12, 10))
        self.assert_geometry(a[4], rectangle(0, 0, 2, 10))
        self.assert_finals(result, {"S01": (100.0, rectangle(2, 0, 12, 10)),
                                   "N01": (80.0, rectangle(12, 0, 20, 10))})
        self.assertIn("EK01 (κοινόχρ./ΕΚ", result)
        self.assertIn("100.0 ? 120.0 τ.μ. (+20.0)", result)
        self.assert_balance(result)

    def test_expansion_and_contraction_have_the_expected_area_balance(self):
        for bounds, subject_area, d_area, a_area in (
                ((0, 0, 12, 10), 120.0, 20.0, 0.0),
                ((2, 0, 10, 10), 80.0, 0.0, 20.0)):
            with self.subTest(bounds=bounds):
                result = self.render(ring_body(*bounds))
                self.assertEqual(sum(float(r[3]) for r in self.rows(result, "D")), d_area)
                self.assertEqual(sum(float(r[3]) for r in self.rows(result, "A")), a_area)
                subject, = [r for r in self.rows(result, "F") if r[1] == "S01"]
                self.assertEqual(float(subject[2]), subject_area)
                self.assert_geometry(subject[3], rectangle(*bounds))
                self.assert_balance(result)

    def test_sliver_threshold_keeps_equal_area_and_reports_smaller_pieces(self):
        body = ring_body(0.25, 0, 10.25, 10)  # 2.5 m² on each side, exactly representable.
        kept = self.render(body, tol=2.5)
        self.assertEqual(len(self.rows(kept, "D")), 1)
        self.assertEqual(len(self.rows(kept, "A")), 1)
        dropped = self.render(body, tol=3.0)
        self.assertEqual(self.rows(dropped, "D"), [])
        self.assertEqual(self.rows(dropped, "A"), [])
        self.assertIn("Αγνοήθηκαν 1 slivers Δ συνολικού εμβαδού 2.50", dropped)
        self.assertIn("Αγνοήθηκαν 1 slivers Α συνολικού εμβαδού 2.50", dropped)
        self.assert_balance(kept)
        self.assert_balance(dropped)

    def test_asymmetric_sliver_loss_remains_visible_in_balance(self):
        result = self.render(ring_body(0, 0, 10.25, 10), tol=3.0)
        self.assertEqual(self.rows(result, "D"), [])
        self.assertIn("Αγνοήθηκαν 1 slivers Δ", result)
        self.assert_balance(result, -2.5)

    def test_cut_assignment_prefers_longer_shared_boundary(self):
        self.parcels = [("S01", rectangle(0, 0, 10, 10)),
                        ("N01", rectangle(-10, 0, 0, 10)),
                        ("N02", rectangle(0, -10, 10, 0))]
        result = self.render(ring_body(2, 0, 10, 10))
        a, = self.rows(result, "A")
        self.assertEqual(a[2], "N01")  # 10 m shared vs 2 m for N02.
        self.assert_finals(result, {"S01": (80.0, rectangle(2, 0, 10, 10)),
                                   "N01": (120.0, rectangle(-10, 0, 2, 10))})
        self.assert_balance(result)

    def test_subject_uses_largest_overlap_and_excludes_greek_special_parcels(self):
        self.parcels = [("ΕΚ01", rectangle(6, 0, 16, 10)),
                        ("S01", rectangle(0, 0, 2, 10)),
                        ("N01", rectangle(2, 0, 6, 10))]
        result = self.render(ring_body(0, 0, 16, 10))
        self.assertTrue(result.startswith("OK|N01|"))  # EK 100 excluded; N01 40 vs S01 20.

    def test_connected_claim_is_split_by_actual_donor_parcel(self):
        self.parcels = [("S01", rectangle(0, 0, 10, 10)),
                        ("N01", rectangle(10, 0, 20, 4)),
                        ("N02", rectangle(10, 4, 20, 10))]
        result = self.render(ring_body(0, 0, 12, 10))
        pieces = {r[2]: r for r in self.rows(result, "D")}
        self.assertEqual(set(pieces), {"N01", "N02"})
        self.assertEqual(float(pieces["N01"][3]), 8.0)
        self.assertEqual(float(pieces["N02"][3]), 12.0)
        self.assert_geometry(pieces["N01"][4], rectangle(10, 0, 12, 4))
        self.assert_geometry(pieces["N02"][4], rectangle(10, 4, 12, 10))
        self.assert_finals(result, {"S01": (120.0, rectangle(0, 0, 12, 10)),
                                   "N01": (32.0, rectangle(12, 0, 20, 4)),
                                   "N02": (48.0, rectangle(12, 4, 20, 10))})
        self.assert_balance(result)

    def test_sliver_filter_applies_to_each_actual_donor_piece(self):
        self.parcels = [("S01", rectangle(0, 0, 10, 10)),
                        ("N01", rectangle(10, 0, 20, 4)),
                        ("N02", rectangle(10, 4, 20, 10))]
        result = self.render(ring_body(0, 0, 10.5, 10), tol=2.5)
        d, = self.rows(result, "D")
        self.assertEqual(d[2:4], ["N02", "3.00"])
        self.assertIn("Αγνοήθηκαν 1 slivers Δ συνολικού εμβαδού 2.00", result)
        self.assert_balance(result, -2.0)

    def test_disconnected_donor_parts_keep_distinct_pieces_and_final_rings(self):
        self.parcels = [("S01", rectangle(0, 0, 10, 10)),
                        ("N01", "MULTIPOLYGON(((10 0,20 0,20 4,10 4,10 0)),"
                         "((10 6,20 6,20 10,10 10,10 6)))")]
        result = self.render("0,0;12,0;12,4;10,4;10,6;12,6;12,10;0,10")
        d = self.rows(result, "D")
        self.assertEqual(len(d), 2)
        self.assertTrue(all(r[2:4] == ["N01", "8.00"] for r in d))
        finals = [r for r in self.rows(result, "F") if r[1] == "N01"]
        self.assertEqual(len(finals), 2)
        self.assertTrue(all(float(r[2]) == 64.0 for r in finals))
        expected = [rectangle(12, 0, 20, 4), rectangle(12, 6, 20, 10)]
        for row, geom in zip(sorted(finals, key=lambda r: min(float(p.split(",")[1])
                                                            for p in r[3].split(";"))), expected):
            self.assert_geometry(row[3], geom)
        self.assert_balance(result)

    def test_touching_a_parcel_without_area_overlap_is_not_a_subject(self):
        self.parcels = [("S01", rectangle(0, 0, 10, 10))]
        result = self.render(ring_body(10, 0, 20, 10))
        self.assertEqual(result, "ERROR|No operating parcel overlaps the TOPO_PROP polygon")

    def test_self_intersecting_or_degenerate_survey_is_not_silently_repaired(self):
        for body in ("0,0;10,10;0,10;10,0", "0,0;1,0;2,0"):
            with self.subTest(body=body):
                result = self.render(body)
                self.assertEqual(result, "ERROR|TOPO_PROP must be a valid polygon with positive area")

    def test_uncovered_claim_is_not_assigned_to_a_touching_or_partial_donor(self):
        for parcels in ([("S01", rectangle(0, 0, 10, 10))],
                        [("S01", rectangle(0, 0, 10, 10)),
                         ("N01", rectangle(10, 0, 20, 4))]):
            with self.subTest(parcels=parcels):
                self.parcels = parcels
                result = self.render(ring_body(0, 0, 12, 10))
                self.assertEqual(result, "ERROR|Claimed area is not fully covered by donor parcels at this tolerance")

    def test_cut_requires_a_neighbor_with_positive_shared_boundary(self):
        self.parcels = [("S01", rectangle(0, 0, 10, 10)),
                        ("N01", rectangle(-10, -10, 0, 0))]  # corner contact only
        result = self.render(ring_body(2, 0, 10, 10))
        self.assertEqual(result, "ERROR|Cut piece has no neighbor with a positive shared boundary")

    def test_overlapping_donors_are_rejected_instead_of_double_counted(self):
        self.parcels = [("S01", rectangle(0, 0, 10, 10)),
                        ("N01", rectangle(10, 0, 20, 7)),
                        ("N02", rectangle(10, 4, 20, 10))]
        result = self.render(ring_body(0, 0, 12, 10))
        self.assertEqual(result, "ERROR|Claimed area overlaps multiple donor parcels; review cadastral topology")

    def test_holes_in_transfer_or_final_geometry_are_not_exported_as_filled_rings(self):
        for body in (ring_body(2, 2, 8, 8), ring_body(0, 0, 12, 10)):
            with self.subTest(body=body):
                if body == ring_body(0, 0, 12, 10):
                    self.parcels = [("S01", rectangle(0, 0, 10, 10)),
                                    ("N01", "POLYGON((10 0,20 0,20 10,10 10,10 0),"
                                     "(15 4,15 6,17 6,17 4,15 4))")]
                result = self.render(body)
                self.assertTrue(result.startswith("ERROR|"), result)
                self.assertIn("has holes", result)


if __name__ == "__main__":
    unittest.main()
