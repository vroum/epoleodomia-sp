"""Reference outputs and behavioral boundaries for the real report endpoints."""

import asyncio
from contextlib import ExitStack, contextmanager, nullcontext
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import Mock, patch

import api_server as api
import planning_reports as reports
from planning_data import PlanningData, POINT_REPORT_RELATIONS, PARCEL_REPORT_RELATIONS, OPTIONAL_REPORT_RELATIONS
from tests.support import OfflineCase


FIXTURES = Path(__file__).parent / "fixtures" / "reports"


def scenario(name):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


class ReportTests(OfflineCase):
    def setUp(self):
        super().setUp()
        self.query = self.start_patch(patch.object(
            api, "execute_query", side_effect=AssertionError("Live report queries disabled in tests")))
        self.session = Mock()
        self.session.savepoint = nullcontext
        self.session.unavailable_relations = set()
        self.snapshot = self.start_patch(patch.object(api, "read_only_snapshot", side_effect=self.fixture_snapshot))

    @contextmanager
    def fixture_snapshot(self, pool, *, protected_relations, optional_relations):
        self.assertIn(protected_relations, (POINT_REPORT_RELATIONS, PARCEL_REPORT_RELATIONS))
        self.assertEqual(optional_relations, OPTIONAL_REPORT_RELATIONS)
        yield self.session

    def render(self, case):
        case = deepcopy(case)
        providers = {
            "_resolve_operating_parcel": "parcel", "_get_oroitable_data": "oroi",
            "_get_parcel_rights": "rights", "_get_parcel_overlaps": "overlaps",
            "_get_shoreline_data": "shore", "_get_archaeology_data": "archeo",
            "_get_church_data": "church", "_get_streams_data": "remata",
            "_get_ydrolipsies_data": "ydro", "_get_natura_forest_data": "natura",
            "_is_inside_city_plan": "inside_plan",
        }
        methods = {
            "_resolve_operating_parcel": "resolve_parcel", "_get_oroitable_data": "get_regulations",
            "_get_parcel_rights": "get_parcel_rights", "_get_parcel_overlaps": "get_parcel_overlaps",
            "_get_shoreline_data": "get_shoreline", "_get_archaeology_data": "get_archaeology",
            "_get_church_data": "get_church", "_get_streams_data": "get_streams",
            "_get_ydrolipsies_data": "get_water_points", "_get_natura_forest_data": "get_natura_forest",
            "_is_inside_city_plan": "is_inside_city_plan",
        }
        with ExitStack() as stack:
            mocks = {fn: stack.enter_context(patch.object(PlanningData, methods[fn], return_value=case.get(key)))
                     for fn, key in providers.items()}
            endpoint = api.get_report_parcel if case["mode"] == "parcel" else api.get_report_rows
            result = asyncio.run(endpoint(*case["point"]))
        self.assertEqual(self.snapshot.call_count, 1)
        self.snapshot.reset_mock()
        return result, mocks

    def test_reference_reports_match_hand_authored_rows(self):
        # Each scenario uses its own context so mocks cannot leak to other cases.
        for name in ("parcel_in_plan", "point_minimal", "point_populated"):
            with self.subTest(case=name):
                expected = (FIXTURES / f"{name}.expected.txt").read_text(encoding="utf-8").rstrip("\n")
                result, _ = self.render(scenario(name))
                self.assertEqual(result.splitlines(), expected.splitlines())
                self.assertEqual(result.encode("windows-1253").decode("windows-1253"), result)
                for row in result.splitlines():
                    self.assertEqual(len(row.split("|")), 3)
        self.query.assert_not_called()

    def test_parcel_features_use_parcel_geometry_while_regulations_use_the_click(self):
        case = scenario("parcel_in_plan")
        _, calls = self.render(case)
        ref = {"ref_geom": api._PARCEL_REF, "ref_args": (case["parcel"]["kaek"],)}
        calls["_get_oroitable_data"].assert_called_once_with(*case["point"])
        calls["_get_shoreline_data"].assert_called_once_with(**ref)
        calls["_get_archaeology_data"].assert_called_once_with(**ref, include_zone=False)
        calls["_get_church_data"].assert_called_once_with(**ref, max_distance=1000)
        calls["_get_streams_data"].assert_called_once_with(*case["point"], **ref)
        calls["_get_ydrolipsies_data"].assert_called_once_with(**ref)
        calls["_get_parcel_overlaps"].assert_called_once_with(case["parcel"]["kaek"])
        calls["_is_inside_city_plan"].assert_not_called()

    def test_point_features_keep_click_coordinates_and_search_distances(self):
        case = scenario("point_populated")
        _, calls = self.render(case)
        for name in ("_get_oroitable_data", "_get_shoreline_data", "_get_archaeology_data",
                     "_get_natura_forest_data", "_get_streams_data"):
            calls[name].assert_called_once_with(*case["point"])
        calls["_get_church_data"].assert_called_once_with(*case["point"], max_distance=1000)
        calls["_get_ydrolipsies_data"].assert_called_once_with(x=case["point"][0], y=case["point"][1])
        calls["_resolve_operating_parcel"].assert_not_called()
        calls["_get_parcel_overlaps"].assert_not_called()
        calls["_is_inside_city_plan"].assert_not_called()

    def test_point_missing_regulations_stops_before_other_queries(self):
        case = scenario("point_minimal")
        case["oroi"] = {"found": False}
        result, calls = self.render(case)
        self.assertEqual(result, "ERROR|No regulations found at this location")
        calls["_is_inside_city_plan"].assert_called_once_with(*case["point"])
        calls["_get_shoreline_data"].assert_not_called()
        calls["_get_ydrolipsies_data"].assert_not_called()

    def test_missing_parcel_cannot_fall_back_to_a_planning_report(self):
        case = scenario("parcel_in_plan")
        case["parcel"] = None
        result, calls = self.render(case)
        self.assertTrue(result.startswith("ERROR|"))
        calls["_get_oroitable_data"].assert_not_called()
        calls["_get_shoreline_data"].assert_not_called()

    def test_missing_regulations_inside_plan_do_not_use_outside_plan_rules(self):
        case = scenario("parcel_in_plan")
        case["oroi"] = {"found": False}
        result, calls = self.render(case)
        self.assertEqual(result, "ERROR|No regulations found at this location")
        calls["_get_parcel_overlaps"].assert_not_called()

    def test_outside_plan_uses_parcel_area_and_shoreline_approval(self):
        case = scenario("parcel_in_plan")
        case["oroi"] = {"found": False}
        case["inside_plan"] = False
        case["parcel"]["area_m2"] = 5000.0
        result, _ = self.render(case)
        self.assertIn("HEADER|ΟΡΟΙ ΔΟΜΗΣΗΣ — ΕΚΤΟΣ ΣΧΕΔΙΟΥ|", result)
        self.assertIn("ROW|Γεωτεμάχιο (5000 τ.μ.)|ΑΡΤΙΟ (εμβαδόν) — έως 204.0 τ.μ.", result)
        self.assertIn("Κτηματική Υπηρεσία Δημοσίου", result)

    def test_inside_emsy_points_take_precedence_over_nearest_point(self):
        result, _ = self.render(scenario("parcel_in_plan"))
        self.assertIn("ROW|Εντός γεωτεμαχίου|Πηγάδι", result)
        self.assertNotIn("TEST NEAREST", result)

    def test_no_inside_emsy_points_reports_nearest_when_available(self):
        case = scenario("parcel_in_plan")
        case["ydro"] = {"available": True, "inside": [], "nearest": {
            "eidos": "Γεώτρηση", "status": None, "emsy": "TEST-NEAR", "distance_m": 25.0}}
        result, _ = self.render(case)
        self.assertIn("ROW|Εντός γεωτεμαχίου|ΟΧΙ", result)
        self.assertIn("ROW|Πλησιέστερη|Γεώτρηση — ΕΜΣΥ TEST-NEAR — 25.0 μ.", result)

    def test_unavailable_emsy_is_not_reported_as_no_points(self):
        case = scenario("parcel_in_plan")
        case["ydro"] = {"available": False, "inside": [], "nearest": None}
        result, _ = self.render(case)
        self.assertNotIn("ΥΔΡΟΛΗΨΙΕΣ", result)

    def test_shoreline_approval_is_not_duplicated(self):
        case = scenario("parcel_in_plan")
        case["oroi"]["egkriseis"].append("Κτηματική Υπηρεσία Δημοσίου")
        result, _ = self.render(case)
        approval = next(row for row in result.splitlines() if row.startswith("ROW||Συμβούλιο"))
        self.assertEqual(approval.count("Κτηματική Υπηρεσία Δημοσίου"), 1)

    def test_http_routes_still_point_at_the_tested_endpoints(self):
        routes = {r.path: r.endpoint for r in api.app.routes if hasattr(r, "endpoint")}
        self.assertIs(routes["/report/parcel"], api.get_report_parcel)
        self.assertIs(routes["/report/rows"], api.get_report_rows)


class ReportBoundaryTests(OfflineCase):
    def test_distance_threshold_for_lines_and_points(self):
        for distance, line, point in ((None, "—", "—"), (0.0, "διέρχεται", "εντός"),
                                      (0.49, "διέρχεται", "εντός"), (0.5, "0.5 μ.", "0.5 μ.")):
            with self.subTest(distance=distance):
                self.assertEqual(reports._fmt_parcel_dist(distance), line)
                self.assertEqual(reports._fmt_parcel_dist(distance, "point"), point)

    def test_nearest_current_shoreline_tie_prefers_established_over_poa(self):
        shore = {"lines": [
            {"info": "Γραμμή Αιγιαλού_ΠΟΑ", "distance_m": 10.0, "fek": "TEST-POA"},
            {"info": "Γραμμή Αιγιαλού", "distance_m": 10.0, "fek": "TEST-CURRENT"},
        ]}
        rows = reports._build_parcel_shoreline_rows(shore)
        self.assertEqual(rows[-1], "ROW|Απόσταση από Αιγιαλό|10.0 μ. (καθορισμένος, ΦΕΚ TEST-CURRENT)")

    def test_beach_alone_is_a_crossing_but_not_a_current_shoreline_distance(self):
        rows = reports._build_parcel_shoreline_rows({"lines": [
            {"info": "Γραμμή Παραλίας", "distance_m": 0.0, "fek": None}]})
        self.assertEqual(rows, ["HEADER|ΑΙΓΙΑΛΟΣ / ΠΑΡΑΛΙΑ|",
                                "ROW|Διέλευση γραμμής|ΝΑΙ - Γραμμή Παραλίας"])

    def test_current_outside_plan_formula_boundaries(self):
        # Arithmetic regression for the existing code, not legal certification.
        for area, expected in ((3999.9, 0.0), (4000, 186.0), (5000, 204.0),
                               (8000, 258.0), (10000, 276.0), (20000, 360.0)):
            with self.subTest(area=area):
                self.assertEqual(reports._ektos_max_domisi(area), expected)

    def test_flood_line_label_stays_provisional_until_publication_is_reviewed(self):
        self.assertEqual(api._REMATA_LABELS["Υδρογραφική Γραμμή Πλημμυρας"], "Πιθανή Γρ. Πλημμύρας")


class ForestFallbackTests(OfflineCase):
    def test_small_ratified_sliver_does_not_hide_the_posted_forest_map(self):
        with patch.object(api, "execute_query", side_effect=[
                (True,), [], [("ΑΑ", 0.3, 0.3, 0.3)], [("ΔΔ", 97.5, 97.5, 97.5)], []]) as query:
            overlaps = api._get_parcel_overlaps("000000000001")
        self.assertEqual(overlaps["forest_kyromenos_pct"], 0.3)
        self.assertEqual([(f["code"], f["pct"], f["source"]) for f in overlaps["forest"]],
                         [("ΔΔ", 97.5, "ανάρτηση 2021")])
        self.assertIn("forest_maps_posted_attica_2021", query.call_args_list[3].args[0])
        for call in query.call_args_list[1:]:
            self.assertEqual(call.args[1], ("000000000001",))

    def test_nearly_complete_ratified_coverage_skips_the_posted_map(self):
        with patch.object(api, "execute_query", side_effect=[(True,), [], [("ΑΑ", 98.0, 98.0, 98.0)], []]) as query:
            overlaps = api._get_parcel_overlaps("000000000001")
        self.assertEqual(overlaps["forest_source"], "κυρωμένος")
        self.assertEqual(query.call_count, 4)
        self.assertFalse(any("forest_maps_posted_attica_2021" in c.args[0] for c in query.call_args_list))
