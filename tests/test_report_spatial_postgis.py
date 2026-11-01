"""Actual report-provider SQL against synthetic VALUES only, opt-in/read-only."""

import asyncio
from contextlib import contextmanager
import os
import re
import unittest
from unittest.mock import Mock, patch

import psycopg2

import api_server as api
from planning_reports import MISSING_REGULATIONS
from planning_data import POINT_REPORT_RELATIONS, PARCEL_REPORT_RELATIONS, OPTIONAL_REPORT_RELATIONS
from database_sessions import read_only_snapshot


def rectangle(x0, y0, x1, y1):
    return f"POLYGON(({x0} {y0},{x1} {y0},{x1} {y1},{x0} {y1},{x0} {y0}))"


# Only columns read by these providers. Explicit types also make empty sources
# meaningful: an absent feature is not an absent table or a mocked query result.
SOURCES = {
    "parcel": ('sp_geodata.kaek_parcels_operating',
               "kaek text, main_use text, descr text"),
    "exclusive": ('sp_geodata.kaek_apokleistikes_operating',
                  "kaek text, vp_num text, area float8"),
    "easement": ('sp_geodata.kaek_douleies_operating',
                 "kaek text, right_sn text, area float8"),
    "natura": ('epoleodomia.natura_2000',
               "sitecode text, sitename text, sitetype text, area_ha float8, is_deleted boolean"),
    "forest": ('epoleodomia.forest_maps',
               "forest_type text, region_name text, status text, is_deleted boolean"),
    "posted": ('epoleodomia.forest_maps_posted_attica_2021',
               "forest_type text, is_deleted boolean"),
    "zone": ('sp_geodata."Αρχαιολογία_Ζώνες_Προστασίας"',
             "site_name text, ot_number text, fek_refere text"),
    "monument": ('sp_geodata."Αρχαιλογία_Κυρηγμένα_Μνημεία"',
                 "site_name text, ot_number text, fek_reference text, site_location text"),
    "church": ('sp_geodata."Εκκλησίες_πολυγωνα"',
               "name text, type text, year_built integer, century text, status text, address text"),
    "shore": ('sp_geodata."Αιγιαλός_Παραλία"', "info text, fek text, location text"),
    "plan": ('sp_geodata.orio_sxediou_polews', ""),
    "stream": ('sp_geodata."Ρεματα_Οικισμού_υπό_Οριοθέτηση"', "layer text"),
    "tps": ('sp_geodata."Ρεματα Νησιου ΤΠΣ (εκτος των 6)"', ""),
    "other": ('sp_geodata."Ρεματα εντος οικισμου εκτος των 6"', ""),
    "water": ('sp_geodata.ydrolipsies_emsy',
              "eidos_sy text, kathestws_xrhshs text, kwdikos_emsy text"),
    "block": ('epoleodomia.building_blocks', "ot_num text, is_deleted boolean"),
    "approved": ('epoleodomia.approved_plan_boundaries',
                 "fek text, apof_eidos text, title text, publ_date date, is_deleted boolean"),
    "coef": ('epoleodomia.building_regs_coefficient',
             "sd_tomeas text, sd_timh float8, sd_klimakotos text, sd_comment text, fek text, is_deleted boolean"),
    "height": ('epoleodomia.building_regs_height',
               "max_height_m float8, num_orofon integer, oror_max_height_comment text, fek text, is_deleted boolean"),
    "coverage": ('epoleodomia.building_regs_coverage',
                 "synt_kalypsis float8, remarks text, fek text, is_deleted boolean"),
    "lot": ('epoleodomia.building_regs_lot',
            "elax_embado_m2 float8, elax_prosop_m float8, oros_type text, remarks text, date_pareklisis date, fek text, is_deleted boolean"),
    "system": ('epoleodomia.building_regs_system',
               "oik_systima text, fek text, is_deleted boolean"),
}


class FixtureSession:
    """Substitute only sources, retaining the actual cursor and savepoints."""

    def __init__(self, fixture, session):
        self.fixture = fixture
        self.session = session
        self.savepoint = session.savepoint
        self.unavailable_relations = session.unavailable_relations

    def __call__(self, statement, params=None, fetch_one=False):
        observed = self.session("SELECT pg_backend_pid(), txid_current_snapshot()::text, "
                                "current_setting('transaction_isolation'), "
                                "current_setting('transaction_read_only')", fetch_one=True)
        self.fixture.observed_sessions.append(observed)
        if self.fixture.fail_query and self.fixture.fail_query(statement):
            self.fixture.fail_query = None
            return self.session("SELECT 1 / 0", fetch_one=True)
        return self.fixture.query_fixture(statement, params, fetch_one, query=self.session)


@unittest.skipUnless(os.environ.get("EPOL_TEST_POSTGIS_DSN"),
                     "Set EPOL_TEST_POSTGIS_DSN to opt into read-only PostGIS tests")
class ReportSpatialPostGISTests(unittest.TestCase):
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
        self.sources = {key: [] for key in SOURCES}
        self.query_errors = []
        self.fail_query = None
        self.observed_sessions = []
        self.active_relations = None
        self.natura_tracking = True
        self.add("parcel", rectangle(0, 0, 100, 100), kaek="S01")
        for patcher in (
                patch.object(api, "execute_query", side_effect=self.query_fixture),
                patch.object(api, "read_only_snapshot", side_effect=self.fixture_snapshot),
                patch("psycopg2.connect", side_effect=AssertionError("Unexpected connection")),
                patch("requests.get", side_effect=AssertionError("Unexpected HTTP")),
                patch("requests.post", side_effect=AssertionError("Unexpected HTTP"))):
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self):
        # Some providers catch query exceptions for optional datasets. A broken
        # fixture substitution/SQL must still fail even if a provider catches it.
        self.assertEqual(self.query_errors, [])

    @contextmanager
    def fixture_snapshot(self, pool, *, protected_relations, optional_relations):
        self.assertIn(protected_relations, (POINT_REPORT_RELATIONS, PARCEL_REPORT_RELATIONS))
        self.assertEqual(optional_relations, OPTIONAL_REPORT_RELATIONS)
        fixture_pool = Mock()
        fixture_pool.getconn.return_value = self.conn
        fixture_pool.putconn.side_effect = lambda conn, close=False: conn.close() if close else None
        self.active_relations = set(protected_relations + optional_relations)
        # Synthetic VALUES have no relations to lock. Catalog-lock behavior is
        # checked separately; use the real snapshot/cursor/savepoints here.
        try:
            with read_only_snapshot(fixture_pool) as session:
                yield FixtureSession(self, session)
                self.assertEqual(session("SELECT 42", fetch_one=True), (42,))
            fixture_pool.getconn.assert_called_once_with()
            fixture_pool.putconn.assert_called_once_with(self.conn, close=False)
        finally:
            self.active_relations = None

    def add(self, source, geom, **attrs):
        allowed = {column.split()[0] for column in SOURCES[source][1].split(",") if column.strip()}
        self.assertFalse(set(attrs) - allowed)
        self.sources[source].append(dict(attrs, geom=geom))

    def query_fixture(self, statement, params=None, fetch_one=False, *, query=None):
        try:
            return self._query_fixture(statement, params, fetch_one, query)
        except Exception as exc:
            self.query_errors.append(str(exc))
            raise

    def _query_fixture(self, statement, params, fetch_one, query):
        statement = statement.strip()
        self.assertRegex(statement.upper(), r"^(SELECT|WITH)\b")
        if "pg_catalog.pg_attribute" in statement:
            self.assertEqual(params, ("epoleodomia", "natura_2000", "is_deleted"))
            self.assertTrue(fetch_one)
            # The source contract belongs to these VALUES, not the live DB.
            if query is not None:
                return query("SELECT %s::boolean", (self.natura_tracking,), fetch_one=True)
            self.cur.execute("SELECT %s::boolean", (self.natura_tracking,))
            return self.cur.fetchone()
        ctes, args = [], []
        # Replace longer names first (forest_maps is a prefix of the posted name).
        for key, (table, column_spec) in sorted(
                SOURCES.items(), key=lambda item: len(item[1][0]), reverse=True):
            if table not in statement:
                continue
            if self.active_relations is not None:
                schema, name = table.split(".", 1)
                self.assertIn((schema, name.strip('"')), self.active_relations)
            alias = "fixture_" + key
            statement = statement.replace(table, alias)
            if key == "natura" and not self.natura_tracking:
                column_spec = column_spec.replace(", is_deleted boolean", "")
            columns = [col.strip().split() for col in column_spec.split(",") if col.strip()]
            expressions = [f"%s::{kind} AS {name}" for name, kind in columns]
            expressions.append("ST_GeomFromText(%s::text, 2100) AS geom")
            selects = []
            for row in self.sources[key]:
                selects.append("SELECT " + ", ".join(expressions))
                args.extend(row.get(name) for name, _ in columns)
                args.append(row["geom"])
            if not selects:
                selects = ["SELECT " + ", ".join(
                    [f"NULL::{kind} AS {name}" for name, kind in columns]
                    + ["NULL::geometry AS geom"]) + " WHERE false"]
            ctes.append(f"{alias} AS (" + " UNION ALL ".join(selects) + ")")
        # Strip identifier quotes as well, so Greek quoted names cannot bypass
        # the application-schema guard. The fixtures never read live GIS data.
        self.assertNotRegex(statement.replace('"', ''), r"(?i)\b(sp_geodata|epoleodomia)\s*\.")
        self.assertTrue(ctes, "Query did not reference a fixture source")
        if re.match(r"(?i)^WITH\b", statement):
            statement = statement[4:].lstrip()
            prefix = "WITH " + ", ".join(ctes) + ", "
        else:
            prefix = "WITH " + ", ".join(ctes) + " "
        params = tuple(args) + tuple(params or ())
        if query is not None:
            return query(prefix + statement, params, fetch_one=fetch_one)
        self.cur.execute(prefix + statement, params)
        return self.cur.fetchone() if fetch_one else self.cur.fetchall()

    def overlaps(self):
        return api._get_parcel_overlaps("S01")

    def parcel_reference(self):
        return {"ref_geom": api._PARCEL_REF, "ref_args": ("S01",)}

    def test_contained_monument_has_zero_distance(self):
        self.add("monument", "POINT(80 50)", site_name="INSIDE")
        data = api._get_archaeology_data(include_zone=False, **self.parcel_reference())
        self.assertTrue(data["found"])
        self.assertEqual(data["distance_m"], 0.0)

    def test_intersecting_church_has_zero_distance(self):
        self.add("church", rectangle(99, 40, 110, 60), name="INTERSECTING")
        data = api._get_church_data(**self.parcel_reference())
        self.assertTrue(data["found"])
        self.assertEqual(data["distance_m"], 0.0)

    def test_nearest_monument_uses_parcel_edge_instead_of_click(self):
        self.add("monument", "POINT(102 50)", site_name="EDGE")
        self.add("monument", "POINT(-3 50)", site_name="CLICK")
        point = api._get_archaeology_data(0, 50, include_zone=False)
        parcel = api._get_archaeology_data(include_zone=False, **self.parcel_reference())
        self.assertEqual((point["name"], point["distance_m"]), ("CLICK", 3.0))
        self.assertEqual((parcel["name"], parcel["distance_m"]), ("EDGE", 2.0))

    def test_church_and_monument_search_radii_include_exact_limit(self):
        self.add("church", rectangle(110, 40, 115, 60), name="LIMIT")
        self.add("monument", "POINT(110 50)", site_name="LIMIT")
        for provider in (api._get_church_data, api._get_archaeology_data):
            with self.subTest(provider=provider.__name__):
                self.assertTrue(provider(max_distance=10, **self.parcel_reference())["found"])
                self.assertFalse(provider(max_distance=9.99, **self.parcel_reference())["found"])

    def test_shoreline_nearest_per_type_preserves_crossing_zero(self):
        for x, info, fek in ((50, "Γραμμή Παραλίας", "CROSS"),
                             (110, "Γραμμή Αιγιαλού", "NEAR"),
                             (120, "Γραμμή Αιγιαλού", "FAR")):
            self.add("shore", f"LINESTRING({x} -10,{x} 110)", info=info, fek=fek)
        data = api._get_shoreline_data(**self.parcel_reference())
        self.assertEqual({r["info"]: (r["fek"], r["distance_m"]) for r in data["lines"]},
                         {"Γραμμή Παραλίας": ("CROSS", 0.0), "Γραμμή Αιγιαλού": ("NEAR", 10.0)})
        self.assertFalse(api._get_shoreline_data(300, 50, max_distance=50)["found"])

    def test_streams_outside_plan_return_nearest_per_type_and_tps(self):
        layer = "Υδρογραφική Γραμμή Πλημμυρας"
        self.add("stream", "LINESTRING(30 -10,30 110)", layer=layer)
        self.add("stream", "LINESTRING(110 -10,110 110)", layer=layer)
        self.add("tps", "LINESTRING(112 -10,112 110)")
        self.add("other", "LINESTRING(102 -10,102 110)")
        data = api._get_streams_data(10, 50, **self.parcel_reference())
        self.assertFalse(data["inside_city_plan"])
        self.assertEqual(data["oikismos_lines"][0]["distance_m"], 0.0)
        self.assertEqual(data["tps_distance_m"], 12.0)
        self.assertFalse(data["other_found"])

    def test_stream_plan_branch_uses_click_while_distance_uses_parcel(self):
        self.add("plan", rectangle(0, 0, 20, 100))
        self.add("tps", "LINESTRING(112 -10,112 110)")
        self.add("other", "LINESTRING(106 -10,106 110)")
        data = api._get_streams_data(10, 50, **self.parcel_reference())
        self.assertTrue(data["inside_city_plan"])
        self.assertFalse(data["tps_found"])
        self.assertEqual(data["other_distance_m"], 6.0)

    def test_water_half_metre_tolerance_and_nearest_use_parcel(self):
        for x, code in ((50, "IN"), (100.5, "EDGE"), (100.5001, "OUT")):
            self.add("water", f"POINT({x} 50)", kwdikos_emsy=code, eidos_sy="Πηγάδι")
        data = api._get_ydrolipsies_data(**self.parcel_reference())
        self.assertTrue(data["available"])
        self.assertEqual({r["emsy"] for r in data["inside"]}, {"IN", "EDGE"})
        self.assertEqual((data["nearest"]["emsy"], data["nearest"]["distance_m"]), ("IN", 0.0))

    def test_water_empty_source_is_available_and_respects_search_limit(self):
        data = api._get_ydrolipsies_data(**self.parcel_reference())
        self.assertEqual(data, {"available": True, "inside": [], "nearest": None})
        self.add("water", "POINT(125 50)", kwdikos_emsy="NEAR")
        self.assertIsNone(api._get_ydrolipsies_data(max_distance=24.99, **self.parcel_reference())["nearest"])
        self.assertEqual(api._get_ydrolipsies_data(max_distance=25, **self.parcel_reference())["nearest"]["distance_m"], 25.0)

    def test_point_natura_ignores_deleted_features(self):
        self.add("natura", rectangle(0, 0, 100, 100), sitecode="DELETED", is_deleted=True)
        self.assertFalse(api._get_natura_forest_data(50, 50)["in_natura"])

    def test_point_natura_without_tracking_column_still_reports_containment(self):
        self.natura_tracking = False
        self.add("natura", rectangle(0, 0, 100, 100), sitecode="LEGACY")
        data = api._get_natura_forest_data(50, 50)
        self.assertTrue(data["in_natura"])
        self.assertEqual(data["natura_code"], "LEGACY")

    def test_parcel_natura_without_tracking_column_preserves_area_filter(self):
        self.natura_tracking = False
        self.add("natura", rectangle(0, 0, 25, 100), sitecode="LEGACY")
        self.add("natura", rectangle(100, 0, 120, 100), sitecode="TOUCH")
        self.assertEqual([(r["code"], float(r["pct"])) for r in self.overlaps()["natura"]],
                         [("LEGACY", 25.0)])

    def test_point_forest_prefers_active_ratified_source(self):
        geom = rectangle(0, 0, 100, 100)
        self.add("forest", geom, forest_type="ΑΑ", region_name="TEST")
        self.add("posted", geom, forest_type="ΔΔ")
        data = api._get_natura_forest_data(50, 50)
        self.assertEqual((data["forest_source"], data["forest_type"]), ("κυρωμένος", "ΑΑ"))

    def test_point_forest_deleted_ratified_source_falls_back_to_posted(self):
        geom = rectangle(0, 0, 100, 100)
        self.add("forest", geom, forest_type="ΑΑ", is_deleted=True)
        self.add("posted", geom, forest_type="ΔΔ")
        data = api._get_natura_forest_data(50, 50)
        self.assertEqual((data["forest_source"], data["forest_type"]), ("ανάρτηση 2021", "ΔΔ"))

    def test_point_forest_deleted_posted_source_is_ignored(self):
        self.add("posted", rectangle(0, 0, 100, 100), forest_type="ΔΔ", is_deleted=True)
        self.assertFalse(api._get_natura_forest_data(50, 50)["in_forest"])

    def test_parcel_natura_ignores_deleted_features(self):
        self.add("natura", rectangle(0, 0, 100, 100), sitecode="DELETED", is_deleted=True)
        self.add("natura", rectangle(0, 0, 25, 100), sitecode="ACTIVE")
        self.assertEqual([(r["code"], float(r["pct"])) for r in self.overlaps()["natura"]], [("ACTIVE", 25.0)])

    def test_natura_boundary_contact_is_not_area_overlap(self):
        self.add("natura", rectangle(100, 0, 120, 100), sitecode="EDGE")
        self.add("natura", rectangle(100, 100, 120, 120), sitecode="CORNER")
        self.assertEqual(self.overlaps()["natura"], [])

    def test_forest_duplicate_and_overlapping_features_count_once_per_type(self):
        for bounds in ((0, 0, 60, 100), (0, 0, 60, 100), (40, 0, 80, 100)):
            self.add("forest", rectangle(*bounds), forest_type="ΑΑ")
        data = self.overlaps()
        self.assertEqual(data["forest_kyromenos_pct"], 80.0)
        self.assertEqual(float(data["forest"][0]["pct"]), 80.0)

    def test_cross_type_forest_overlap_does_not_hide_posted_fallback(self):
        for code in ("ΑΑ", "ΔΔ"):
            self.add("forest", rectangle(0, 0, 60, 100), forest_type=code)
        self.add("posted", rectangle(60, 0, 100, 100), forest_type="ΧΧ")
        data = self.overlaps()
        self.assertEqual(data["forest_kyromenos_pct"], 60.0)
        self.assertEqual({(f["code"], f["source"]) for f in data["forest"]},
                         {("ΑΑ", "κυρωμένος"), ("ΔΔ", "κυρωμένος"), ("ΧΧ", "ανάρτηση 2021")})

    def test_forest_fallback_threshold_uses_unrounded_coverage(self):
        self.add("forest", rectangle(0, 0, 97.96, 100), forest_type="ΑΑ")
        self.add("posted", rectangle(0, 0, 100, 100), forest_type="ΔΔ")
        data = self.overlaps()
        self.assertEqual(data["forest_kyromenos_pct"], 98.0)
        self.assertIn("ανάρτηση 2021", data["forest_source"])

    def test_forest_exact_98_percent_skips_posted_and_deleted_are_ignored(self):
        self.add("forest", rectangle(0, 0, 98, 100), forest_type="ΑΑ")
        self.add("forest", rectangle(0, 0, 100, 100), forest_type="ΔΔ", is_deleted=True)
        self.add("posted", rectangle(0, 0, 100, 100), forest_type="ΔΔ")
        data = self.overlaps()
        self.assertEqual(data["forest_kyromenos_pct"], 98.0)
        self.assertEqual(data["forest_source"], "κυρωμένος")
        self.assertEqual([f["code"] for f in data["forest"]], ["ΑΑ"])

    def test_forest_sliver_filter_uses_raw_percentage_not_rounded_display(self):
        self.add("forest", rectangle(0, 0, 0.49, 100), forest_type="ΑΑ")
        self.add("forest", rectangle(1, 0, 1.5, 100), forest_type="ΔΔ")
        data = self.overlaps()
        self.assertEqual(data["forest_kyromenos_pct"], 1.0)
        self.assertEqual([(r["code"], float(r["pct"])) for r in data["forest"]], [("ΔΔ", 0.5)])

    def test_partial_ratification_still_reports_both_full_source_layers(self):
        # Preserve the existing evidence policy: posted is a second source,
        # not a silently clipped authoritative mosaic of classifications.
        self.add("forest", rectangle(0, 0, 30, 100), forest_type="ΑΑ")
        self.add("posted", rectangle(0, 0, 100, 100), forest_type="ΔΔ")
        data = self.overlaps()
        self.assertEqual([(r["source"], float(r["pct"])) for r in data["forest"]],
                         [("κυρωμένος", 30.0), ("ανάρτηση 2021", 100.0)])

    def test_posted_deleted_and_boundary_only_forest_features_are_ignored(self):
        self.add("forest", rectangle(100, 0, 120, 100), forest_type="ΑΑ")
        self.add("posted", rectangle(0, 0, 100, 100), forest_type="ΔΔ", is_deleted=True)
        self.assertEqual(self.overlaps()["forest"], [])

    def test_archaeological_closed_linework_builds_partial_area_open_lines_do_not(self):
        self.add("zone", "MULTILINESTRING((0 0,50 0,50 100,0 100,0 0))", site_name="HALF")
        self.add("zone", "LINESTRING(60 0,60 100)", site_name="OPEN")
        self.assertEqual([(r["name"], float(r["pct"])) for r in self.overlaps()["archeo_zones"]], [("HALF", 50.0)])

    def test_archaeological_boundary_contact_is_not_area_overlap(self):
        self.add("zone", "LINESTRING(100 0,120 0,120 100,100 100,100 0)", site_name="EDGE")
        self.assertEqual(self.overlaps()["archeo_zones"], [])

    def test_existing_archaeology_point_one_metre_tolerance_is_preserved(self):
        self.add("zone", "LINESTRING(0 0,100 0,100 100,0 100,0 0)", site_name="ZONE")
        for x, expected in ((50, True), (100, True), (100.9, True), (101, False)):
            with self.subTest(x=x):
                self.assertEqual(api._get_archaeology_data(x, 50)["in_protection_zone"], expected)

    def test_overlap_percentages_use_valid_source_area(self):
        self.add("natura", "POLYGON((0 0,100 100,0 100,100 0,0 0))", sitecode="BOWTIE")
        self.assertEqual(float(self.overlaps()["natura"][0]["pct"]), 50.0)

    def test_parcel_hole_is_excluded_from_overlap_denominator(self):
        self.sources["parcel"] = []
        self.add("parcel", "POLYGON((0 0,100 0,100 100,0 100,0 0),(20 20,20 80,80 80,80 20,20 20))", kaek="S01")
        self.add("natura", rectangle(0, 0, 50, 100), sitecode="HALF")
        self.assertEqual(float(self.overlaps()["natura"][0]["pct"]), 50.0)

    def test_multipart_parcel_uses_total_area(self):
        self.sources["parcel"] = []
        self.add("parcel", "MULTIPOLYGON(((0 0,100 0,100 100,0 100,0 0)),((200 0,300 0,300 100,200 100,200 0)))", kaek="S01")
        self.add("natura", rectangle(0, 0, 100, 100), sitecode="HALF")
        self.assertEqual(float(self.overlaps()["natura"][0]["pct"]), 50.0)

    def test_missing_and_empty_parcels_do_not_produce_overlap_rows(self):
        self.add("natura", rectangle(0, 0, 100, 100), sitecode="AREA")
        for rows in ([], [{"kaek": "S01", "geom": "POLYGON EMPTY"}]):
            with self.subTest(rows=rows):
                self.sources["parcel"] = rows
                data = self.overlaps()
                self.assertEqual(data["natura"], [])
                self.assertEqual(data["forest"], [])
                self.assertEqual(data["archeo_zones"], [])

    def test_regulation_queries_ignore_deleted_rows_and_preserve_sector_fields(self):
        geom = rectangle(0, 0, 100, 100)
        self.add("block", geom, ot_num="DELETED", is_deleted=True)
        self.add("block", geom, ot_num="OT01")
        self.add("coef", geom, sd_tomeas="WRONG", sd_timh=9, fek="DELETED", is_deleted=True)
        self.add("coef", geom, sd_tomeas="A", sd_timh=0.8, fek="COEF")
        self.add("height", geom, max_height_m=7.5, num_orofon=2, fek="HEIGHT")
        self.add("coverage", geom, synt_kalypsis=60, fek="COVER")
        self.add("lot", geom, elax_embado_m2=300, elax_prosop_m=12, oros_type="ΚΑΤΑ ΚΑΝΟΝΑ", fek="LOT")
        self.add("lot", geom, elax_embado_m2=1, oros_type="ΚΑΤΑ ΠΑΡΕΚΚΛΙΣΗ", remarks="EXCEPTION", fek="EXC")
        self.add("system", geom, oik_systima="Συνεχές", fek="SYS")
        self.add("approved", geom, fek="PLAN", publ_date="2000-01-01")
        data = api._get_oroitable_data(50, 50)
        self.assertTrue(data["found"])
        self.assertEqual(data["ot_num"], "OT01")
        self.assertEqual(data["diatagmata_oron"], ["COEF", "COVER", "EXC", "HEIGHT", "LOT", "SYS"])
        sector, = data["tomeis"]
        self.assertEqual((sector["name"], sector["sd"], sector["max_height_m"], sector["coverage_pct"], sector["elax_embado_m2"]),
                         ("A", 0.8, 7.5, 60, 300))
        self.assertEqual(data["kata_parekklisi"]["remarks"], "EXCEPTION")

    def test_city_plan_boundary_without_regulations_cannot_use_outside_rules(self):
        self.add("plan", rectangle(0, 0, 100, 100))
        self.assertTrue(api._is_inside_city_plan(0, 50))
        self.assertEqual(asyncio.run(api.get_report_rows(0, 50)), MISSING_REGULATIONS)
        self.assertEqual(asyncio.run(api.get_report_parcel(0, 50)), MISSING_REGULATIONS)

    def test_parcel_resolution_excludes_special_use_and_measures_selected_shape(self):
        for kaek in ("EK01", "ΕΚ01"):
            self.add("parcel", rectangle(-100, -100, 200, 200), kaek=kaek)
        data = api._resolve_operating_parcel(50, 50)
        self.assertEqual(data["kaek"], "S01")
        self.assertEqual((float(data["area_m2"]), float(data["perim_m"])), (10000.0, 400.0))

    def test_parcel_resolution_fallback_includes_exact_search_radius(self):
        self.assertEqual(api._resolve_operating_parcel(150, 50, radius=50)["kaek"], "S01")
        self.assertIsNone(api._resolve_operating_parcel(150, 50, radius=49.99))

    def test_point_report_collects_real_spatial_providers_and_preserves_zero(self):
        self.add("block", rectangle(0, 0, 100, 100), ot_num="OT01")
        self.add("monument", "POINT(50 50)", site_name="MONUMENT")
        self.add("church", rectangle(40, 40, 60, 60), name="CHURCH")
        self.add("water", "POINT(50 50)", eidos_sy="Πηγάδι", kwdikos_emsy="EMSY01")
        self.add("shore", "LINESTRING(50 0,50 100)", info="Γραμμή Αιγιαλού", fek="SHORE")
        result = asyncio.run(api.get_report_rows(50, 50))
        self.assertIn("ROW|Πλησιέστερο Μνημείο|MONUMENT  (0.0 μ.)", result)
        self.assertIn("ROW|Απόσταση|0.0 μ.", result)
        self.assertIn("ROW|Γραμμή Αιγιαλού|0.0 μ. (ΦΕΚ SHORE)", result)
        self.assertIn("EMSY01", result)
        self.assertNotIn("None μ.", result)

    def test_parcel_report_collects_real_sql_and_renders_inside_features(self):
        self.add("block", rectangle(0, 0, 100, 100), ot_num="OT01")
        self.add("exclusive", rectangle(0, 0, 20, 100), kaek="S01", vp_num="01")
        self.add("easement", rectangle(0, 0, 1, 100), kaek="S01", right_sn="01")
        self.add("monument", "POINT(80 50)", site_name="MONUMENT")
        self.add("church", rectangle(40, 40, 60, 60), name="CHURCH")
        self.add("water", "POINT(80 50)", eidos_sy="Πηγάδι", kwdikos_emsy="EMSY01")
        self.add("shore", "LINESTRING(50 0,50 100)", info="Γραμμή Αιγιαλού", fek="SHORE")
        self.add("natura", rectangle(100, 0, 120, 100), sitecode="TOUCH")
        result = asyncio.run(api.get_report_parcel(10, 50))
        self.assertIn("ROW|ΚΑΕΚ|S01", result)
        self.assertIn("ROW|Αποκλ. χρήσεις (ΑΧ)|1 πολύγωνα — σύνολο 2000.0 τ.μ.", result)
        self.assertIn("ROW|Δουλείες|1 — σύνολο 100.0 τ.μ.", result)
        self.assertIn("ROW|Πλησιέστερο Μνημείο|MONUMENT  (εντός)", result)
        self.assertIn("ROW|Απόσταση|εντός", result)
        self.assertIn("Κτηματική Υπηρεσία Δημοσίου", result)
        self.assertIn("EMSY01", result)
        self.assertIn("ROW|Natura 2000|ΟΧΙ", result)
        self.assertNotIn("None μ.", result)

    def test_report_queries_share_one_backend_snapshot_and_read_only_mode(self):
        self.add("block", rectangle(0, 0, 100, 100), ot_num="OT01")
        with patch.object(api, "execute_query", side_effect=AssertionError("Report snapshot bypass")):
            result = asyncio.run(api.get_report_parcel(10, 50))
        self.assertIn("ROW|ΚΑΕΚ|S01", result)
        self.assertGreater(len(self.observed_sessions), 20)
        self.assertEqual(len(set(self.observed_sessions)), 1)
        self.assertEqual(self.observed_sessions[0][2:], ("repeatable read", "on"))

    def test_both_reports_support_natura_without_tracking_column(self):
        self.natura_tracking = False
        self.add("block", rectangle(0, 0, 100, 100), ot_num="OT01")
        self.add("natura", rectangle(0, 0, 100, 100), sitecode="LEGACY", sitename="LEGACY SITE")
        for endpoint in (api.get_report_rows, api.get_report_parcel):
            with self.subTest(endpoint=endpoint.__name__):
                result = asyncio.run(endpoint(50, 50))
                self.assertIn("ROW|Natura 2000|ΝΑΙ", result)
                self.assertIn("LEGACY SITE (LEGACY)", result)

    def test_natura_catalog_failure_aborts_report_and_returns_clean_connection(self):
        self.add("block", rectangle(0, 0, 100, 100), ot_num="OT01")
        self.fail_query = lambda statement: "pg_catalog.pg_attribute" in statement
        with self.assertRaises(psycopg2.errors.DivisionByZero):
            asyncio.run(api.get_report_rows(50, 50))
        self.assertIsNone(self.fail_query)
        self.cur.execute("SELECT 42")
        self.assertEqual(self.cur.fetchone(), (42,))

    def test_optional_approval_query_error_recovers_before_required_report_sections(self):
        self.add("block", rectangle(0, 0, 100, 100), ot_num="OT01")
        self.add("zone", "LINESTRING(0 0,100 0,100 100,0 100,0 0)", site_name="ZONE")
        self.add("monument", "POINT(50 50)", site_name="MONUMENT")
        self.fail_query = lambda sql: 'SELECT 1 FROM sp_geodata."Αρχαιολογία_Ζώνες_Προστασίας"' in sql
        result = asyncio.run(api.get_report_rows(50, 50))
        self.assertIsNone(self.fail_query)
        self.assertIn("ROW|Ζώνη Προστασίας|ΝΑΙ — ZONE", result)
        self.assertIn("ROW|Πλησιέστερο Μνημείο|MONUMENT  (0.0 μ.)", result)
        self.assertEqual(len(set(self.observed_sessions)), 1)

    def test_optional_water_second_query_failure_discards_partial_data_and_pool_recovers(self):
        self.add("block", rectangle(0, 0, 100, 100), ot_num="OT01")
        self.add("water", "POINT(50 50)", eidos_sy="Πηγάδι", kwdikos_emsy="EMSY01")
        self.fail_query = lambda sql: "FROM sp_geodata.ydrolipsies_emsy" in sql and "LIMIT 1" in sql
        result = asyncio.run(api.get_report_parcel(50, 50))
        self.assertIsNone(self.fail_query)
        self.assertNotIn("EMSY01", result)
        self.assertNotIn("ΥΔΡΟΛΗΨΙΕΣ", result)
        self.assertEqual(len(set(self.observed_sessions)), 1)
        self.observed_sessions.clear()
        fresh = asyncio.run(api.get_report_parcel(50, 50))
        self.assertIn("EMSY01", fresh)

    def test_required_query_failure_aborts_report_and_returns_clean_connection(self):
        self.fail_query = lambda sql: "FROM epoleodomia.building_blocks" in sql
        with self.assertRaises(psycopg2.errors.DivisionByZero):
            asyncio.run(api.get_report_rows(50, 50))
        self.cur.execute("SELECT 42")
        self.assertEqual(self.cur.fetchone(), (42,))
