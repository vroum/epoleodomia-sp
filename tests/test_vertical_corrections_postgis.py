"""Opt-in KGEOMV geometry checks using synthetic parcels/AX and read-only SQL."""

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
from tests.test_boundary_corrections_postgis import rectangle, ring_body, ring_wkt


def vst(number, bounds, title_area="", title_xiliosta=""):
    return f"V|{number}|{title_area}|{title_xiliosta}|{ring_body(*bounds)}"


@unittest.skipUnless(os.environ.get("EPOL_TEST_POSTGIS_DSN"),
                     "Set EPOL_TEST_POSTGIS_DSN to opt into read-only PostGIS tests")
class VerticalCorrectionPostGISTests(unittest.TestCase):
    def setUp(self):
        self.conn = psycopg2.connect(os.environ["EPOL_TEST_POSTGIS_DSN"], connect_timeout=5,
                                     options="-c default_transaction_read_only=on")
        self.addCleanup(self.conn.close)
        self.addCleanup(self.conn.rollback)
        self.cur = self.conn.cursor()
        self.addCleanup(self.cur.close)
        self.cur.execute("SHOW transaction_read_only")
        self.assertEqual(self.cur.fetchone()[0], "on")
        self.parcels = [("P01", rectangle(0, 0, 10, 10))]
        self.ax = [("P01", "01", 50, rectangle(0, 0, 5, 10)),
                   ("P01", "02", 50, rectangle(5, 0, 10, 10))]

    def query_fixture(self, statement, params=None, fetch_one=False, *, query):
        statement = statement.strip()
        self.assertRegex(statement.upper(), r"^(SELECT|WITH)\b")
        statement = statement.replace("sp_geodata.kaek_parcels_operating", "fixture_parcels")
        statement = statement.replace("sp_geodata.kaek_apokleistikes_operating", "fixture_ax")
        self.assertNotRegex(statement, r"(?i)\b(sp_geodata|epoleodomia)\s*\.")
        p_values = ",".join("(%s,%s)" for _ in self.parcels)
        # Empty source still has the same explicitly typed schema.
        a_values = ",".join("(%s,%s,%s,%s)" for _ in self.ax) or "(NULL,NULL,NULL,NULL)"
        cte = (f"WITH p_input(kaek,wkt) AS (VALUES {p_values}), "
               "fixture_parcels AS (SELECT kaek,ST_GeomFromText(wkt,2100) AS geom FROM p_input), "
               f"a_input(kaek,vp_num,area,wkt) AS (VALUES {a_values}), "
               "fixture_ax AS (SELECT kaek::text,vp_num::text,area::numeric,"
               "ST_GeomFromText(wkt::text,2100) AS geom FROM a_input WHERE kaek IS NOT NULL) ")
        if re.match(r"(?i)^WITH\b", statement):
            statement = ", " + statement[4:].lstrip()
        args = tuple(v for row in self.parcels for v in row)
        args += tuple(v for row in self.ax for v in row) + tuple(params or ())
        return query(cte + statement, args, fetch_one=fetch_one)

    @contextmanager
    def fixture_snapshot(self, pool, *, protected_relations):
        self.assertEqual(protected_relations, (("sp_geodata", "kaek_parcels_operating"),
                                               ("sp_geodata", "kaek_apokleistikes_operating")))
        fixture_pool = Mock()
        fixture_pool.getconn.return_value = self.conn
        fixture_pool.putconn.side_effect = lambda conn, close=False: conn.close() if close else None
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
            result = asyncio.run(api.geom_kathetes(request, tol=tol))
        self.assertEqual(result.encode("windows-1253").decode("windows-1253"), result)
        return result

    def rows(self, result, kind):
        return [row.split("|") for row in result.splitlines() if row.startswith(kind + "|")]

    def assert_geometry(self, coords, expected):
        self.cur.execute("SELECT ST_Equals(ST_GeomFromText(%s,2100),ST_GeomFromText(%s,2100))",
                         (ring_wkt(coords), expected))
        self.assertTrue(self.cur.fetchone()[0], (coords, expected))

    def assert_internal_lines(self, result, expected_wkt):
        parts = self.rows(result, "L")
        wkts = ["LINESTRING(" + row[1].replace(",", " ").replace(";", ",") + ")" for row in parts]
        if not wkts:
            actual = "MULTILINESTRING EMPTY"
        else:
            self.cur.execute("SELECT ST_AsText(ST_Union(ARRAY[" +
                             ",".join("ST_GeomFromText(%s,2100)" for _ in wkts) + "]))", tuple(wkts))
            actual = self.cur.fetchone()[0]
        self.cur.execute("SELECT ST_Equals(ST_GeomFromText(%s,2100),ST_GeomFromText(%s,2100))",
                         (actual, expected_wkt))
        self.assertTrue(self.cur.fetchone()[0], (actual, expected_wkt))

    def test_partition_reports_expected_areas_shares_and_only_internal_boundary(self):
        result = self.render(vst("01", (0, 0, 5, 10), 50, 500) + "\n" +
                             vst("02", (5, 0, 10, 10), 50, 500))
        self.assertTrue(result.startswith("OK|P01|100.0\n"))
        finals = self.rows(result, "VF")
        self.assertEqual([r[1:3] for r in finals], [["01", "50.0"], ["02", "50.0"]])
        self.assert_geometry(finals[0][3], rectangle(0, 0, 5, 10))
        self.assert_geometry(finals[1][3], rectangle(5, 0, 10, 10))
        self.assertIn("Κοινόχρηστο εκτός ΑΧ|0.0 τ.μ. (0.0‰)", result)
        self.assertIn("Όλοι οι έλεγχοι εντάξει", result)
        self.assert_internal_lines(result, "LINESTRING(5 0,5 10)")

    def test_overhang_is_clipped_and_lost_area_is_reported(self):
        result = self.render(vst("01", (-2, 0, 4, 10)))
        final, = self.rows(result, "VF")
        self.assertEqual(final[1:3], ["01", "40.0"])
        self.assert_geometry(final[3], rectangle(0, 0, 4, 10))
        self.assertIn("κόπηκαν 20.0 τ.μ.", result)
        self.assertIn("Κοινόχρηστο εκτός ΑΧ|60.0 τ.μ. (600.0‰)", result)
        self.assert_internal_lines(result, "LINESTRING(4 0,4 10)")

    def test_pairwise_overlap_warns_without_double_counting_the_remainder(self):
        result = self.render(vst("01", (0, 0, 6, 10)) + "\n" + vst("02", (5, 0, 10, 10)))
        self.assertIn("ΕΠΙΚΑΛΥΨΗ ΑΧ 01 με ΑΧ 02: 10.0", result)
        self.assertIn("Κοινόχρηστο εκτός ΑΧ|0.0 τ.μ.", result)

    def test_explicit_number_mismatch_and_title_area_difference_are_visible(self):
        result = self.render(vst("09", (0, 0, 4, 10), 50, 500))
        self.assertIn("ΑΧ 09: μέγιστη επικάλυψη με κτηματολογική ΑΧ 01", result)
        self.assertIn("τίτλ: 50.0 (500.0‰) · ΚΤ(01): 50.0", result)
        self.assertIn("τίτλος = -10.0 τ.μ.", result)

    def test_blank_numbers_keep_auto_numbering_and_spatial_cadastral_matching(self):
        self.ax = [("P01", "07", 50, rectangle(0, 0, 5, 10)),
                   ("P01", "08", 50, rectangle(5, 0, 10, 10))]
        result = self.render(vst("", (0, 0, 5, 10)) + "\n" + vst("", (5, 0, 10, 10)))
        self.assertEqual([r[1] for r in self.rows(result, "VF")], ["01", "02"])
        self.assertIn("ΚΤ(07)", result)
        self.assertIn("ΚΤ(08)", result)

    def test_parent_requires_positive_area_overlap(self):
        result = self.render(vst("01", (10, 0, 20, 10)))
        self.assertTrue(result.startswith("ERROR|"), result)

    def test_invalid_or_collinear_survey_is_rejected_without_repair(self):
        for coords in ("0,0;10,10;0,10;10,0", "0,0;5,0;10,0"):
            with self.subTest(coords=coords):
                result = self.render("V|01|||" + coords)
                self.assertTrue(result.startswith("ERROR|"), result)

    def test_touch_only_cadastral_ax_is_not_a_match(self):
        self.ax = [("P01", "07", 50, rectangle(5, 0, 10, 10))]
        result = self.render(vst("01", (0, 0, 5, 10)))
        self.assertIn("ΚΤ(—): —", result)
        self.assertNotIn("ΚΤ(07)", result)

    def test_ignored_sliver_does_not_change_common_remainder_or_internal_lines(self):
        result = self.render(vst("01", (0, 0, 5, 10)) + "\n" + vst("02", (8, 0, 8.025, 10)))
        self.assertEqual([r[1] for r in self.rows(result, "VF")], ["01"])
        self.assertIn("Κοινόχρηστο εκτός ΑΧ|50.0 τ.μ. (500.0‰)", result)
        self.assert_internal_lines(result, "LINESTRING(5 0,5 10)")

    def test_zero_tolerance_still_ignores_zero_area_clips(self):
        result = self.render(vst("01", (0, 0, 5, 10)) + "\n" + vst("02", (10, 0, 11, 10)), tol=0)
        self.assertEqual([r[1] for r in self.rows(result, "VF")], ["01"])
        self.assertFalse(any(r.startswith("TBL|ROW|ΑΧ 02|") for r in result.splitlines()))

    def test_all_ignored_surveys_return_an_error(self):
        result = self.render(vst("01", (0, 0, 0.25, 10)), tol=3)
        self.assertTrue(result.startswith("ERROR|"), result)

    def test_tolerance_uses_unrounded_clip_area(self):
        kept = self.render(vst("01", (0, 0, 0.25, 10)), tol=2.5)
        self.assertEqual(len(self.rows(kept, "VF")), 1)
        ignored = self.render(vst("01", (0, 0, 0.2499, 10)), tol=2.5)
        self.assertTrue(ignored.startswith("ERROR|"), ignored)

    def test_holes_are_not_exported_as_filled_polygons(self):
        self.parcels = [("P01", "POLYGON((0 0,10 0,10 10,0 10,0 0),"
                          "(4 4,4 6,6 6,6 4,4 4))")]
        result = self.render(vst("01", (0, 0, 10, 10)))
        self.assertTrue(result.startswith("ERROR|"), result)
        self.assertIn("holes", result)

    def test_repeated_match_to_one_cadastral_ax_is_flagged(self):
        self.ax = [("P01", "07", 50, rectangle(0, 0, 5, 10))]
        result = self.render(vst("01", (0, 0, 2, 10)) + "\n" + vst("02", (2, 0, 4, 10)))
        self.assertIn("περισσότερες από μία", result)

    def test_matching_uses_clipped_geometry(self):
        self.ax = [("P01", "01", 40, rectangle(0, 0, 4, 10)),
                   ("P01", "02", 100, rectangle(-10, 0, 0, 10))]
        result = self.render(vst("01", (-8, 0, 4, 10)))
        self.assertIn("ΚΤ(01)", result)
        self.assertNotIn("ΚΤ(02)", result)

    def test_equal_match_areas_are_flagged_for_review(self):
        result = self.render(vst("", (0, 0, 10, 10)))
        self.assertIn("ίδια μέγιστη επικάλυψη", result)

    def test_duplicate_cadastral_numbers_do_not_silently_overwrite_area(self):
        self.ax = [("P01", "01", 50, rectangle(0, 0, 5, 10)),
                   ("P01", "01", 50, rectangle(5, 0, 10, 10))]
        result = self.render(vst("01", (0, 0, 10, 10)))
        self.assertTrue(result.startswith("ERROR|"), result)

    def test_multipart_clip_preserves_all_final_components(self):
        self.parcels = [("P01", "MULTIPOLYGON(((0 0,2 0,2 10,0 10,0 0)),"
                          "((4 0,6 0,6 10,4 10,4 0)))")]
        self.ax = [("P01", "01", 40, self.parcels[0][1])]
        result = self.render(vst("01", (0, 0, 6, 10)))
        finals = self.rows(result, "VF")
        self.assertEqual(len(finals), 2)
        self.assertTrue(all(row[1:3] == ["01", "40.0"] for row in finals))
        finals.sort(key=lambda row: min(float(pair.split(",")[0]) for pair in row[3].split(";")))
        self.assert_geometry(finals[0][3], rectangle(0, 0, 2, 10))
        self.assert_geometry(finals[1][3], rectangle(4, 0, 6, 10))
        self.assert_internal_lines(result, "MULTILINESTRING EMPTY")

    def test_parent_excludes_special_parcels_and_uses_maximum_positive_overlap(self):
        self.parcels = [("P01", rectangle(0, 0, 2, 10)),
                        ("P02", rectangle(2, 0, 6, 10)),
                        ("ΕΚ01", rectangle(6, 0, 16, 10))]
        self.ax = []
        result = self.render(vst("01", (0, 0, 16, 10)))
        self.assertTrue(result.startswith("OK|P02|40.0\n"))
        final, = self.rows(result, "VF")
        self.assert_geometry(final[3], rectangle(2, 0, 6, 10))

    def test_overlap_at_tolerance_does_not_warn_but_larger_overlap_does(self):
        equal = self.render(vst("01", (0, 0, 5, 10)) + "\n" +
                            vst("02", (4.75, 0, 10, 10)), tol=2.5)
        larger = self.render(vst("01", (0, 0, 5, 10)) + "\n" +
                             vst("02", (4.5, 0, 10, 10)), tol=2.5)
        self.assertNotIn("ΕΠΙΚΑΛΥΨΗ ΑΧ", equal)
        self.assertIn("ΕΠΙΚΑΛΥΨΗ ΑΧ 01 με ΑΧ 02: 5.0", larger)
