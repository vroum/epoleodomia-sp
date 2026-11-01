"""Planning collection/formatting runs with a supplied query, without packages."""

from contextlib import contextmanager
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock

from planning_data import PlanningData


FIXTURES = Path(__file__).parent / "fixtures" / "reports"
PROVIDERS = {
    "resolve_parcel": "parcel", "get_regulations": "oroi",
    "get_parcel_rights": "rights", "get_parcel_overlaps": "overlaps",
    "get_shoreline": "shore", "get_archaeology": "archeo",
    "get_church": "church", "get_streams": "remata",
    "get_water_points": "ydro", "get_natura_forest": "natura",
    "is_inside_city_plan": "inside_plan",
}


class PlanningDataTests(unittest.TestCase):
    @staticmethod
    def regulation_remarks(coverage="Middle regulation"):
        query = Mock(side_effect=[
            ("1",), [], [],
            ("A", 0.5, None, "Alpha regulation", "1D"),
            (7.5, 2, "Zulu regulation", "1D"),
            (40, coverage, "1D"),
            None, None, None, None, None,
        ])
        return PlanningData(query).get_regulations(10, 20)["loipa"]

    def test_regulation_remarks_have_the_same_order_across_processes(self):
        script = """
import json, sys
sys.path.insert(0, sys.argv[1])
from tests.test_planning_data import PlanningDataTests
print(json.dumps(PlanningDataTests.regulation_remarks()))
"""
        for seed in ("1", "11", "123"):
            with self.subTest(hash_seed=seed):
                result = subprocess.run(
                    [sys.executable, "-S", "-B", "-c", script, str(FIXTURES.parents[2])],
                    env=dict(os.environ, PYTHONHASHSEED=seed),
                    capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout),
                                 ["Alpha regulation", "Middle regulation", "Zulu regulation"])

    def test_regulation_remarks_keep_all_unique_nonempty_comments(self):
        for coverage in ("Alpha regulation", "", None):
            with self.subTest(coverage=coverage):
                self.assertEqual(self.regulation_remarks(coverage),
                                 ["Alpha regulation", "Zulu regulation"])

    def test_natura_column_detection_is_cached_only_for_one_collector(self):
        query = Mock(side_effect=[(False,), (True,)])
        legacy = PlanningData(query)
        self.assertEqual(legacy._natura_active_filter(), "TRUE")
        self.assertEqual(legacy._natura_active_filter(), "TRUE")
        query.assert_called_once()
        self.assertEqual(query.call_args.args[1], ("epoleodomia", "natura_2000", "is_deleted"))
        self.assertTrue(query.call_args.kwargs["fetch_one"])
        managed = PlanningData(query)
        self.assertEqual(managed._natura_active_filter(), "NOT COALESCE(n.is_deleted, false)")
        self.assertEqual(query.call_count, 2)

    def test_natura_catalog_error_is_not_swallowed_or_cached(self):
        query = Mock(side_effect=[ValueError("catalog failed"), (True,)])
        data = PlanningData(query)
        with self.assertRaisesRegex(ValueError, "catalog failed"):
            data._natura_active_filter()
        self.assertEqual(data._natura_active_filter(), "NOT COALESCE(n.is_deleted, false)")

    def test_natura_invalid_catalog_response_cannot_disable_filtering(self):
        for row in (None, (), (None,), (0,), ("false",), (False, False)):
            with self.subTest(row=row):
                with self.assertRaisesRegex(RuntimeError, "Natura tracking-column"):
                    PlanningData(Mock(return_value=row))._natura_active_filter()

    def test_reference_reports_run_directly_without_api_or_database(self):
        for name in ("parcel_in_plan", "point_minimal", "point_populated"):
            with self.subTest(name=name):
                case = json.loads((FIXTURES / (name + ".json")).read_text(encoding="utf-8"))
                before = deepcopy(case)
                data = PlanningData(Mock(side_effect=AssertionError("Unscripted query")))
                for method, key in PROVIDERS.items():
                    setattr(data, method, Mock(return_value=case.get(key)))
                render = data.parcel_report if case["mode"] == "parcel" else data.point_report
                expected = (FIXTURES / (name + ".expected.txt")).read_text(encoding="utf-8").rstrip("\n")
                self.assertEqual(render(*case["point"]), expected)
                self.assertEqual(case, before)

    def test_unavailable_water_source_does_not_query_unlocked_relation(self):
        query = Mock(side_effect=AssertionError("Absent optional source must not be queried"))
        data = PlanningData(query, water_available=False)
        self.assertEqual(data.get_water_points(10, 20),
                         {"available": False, "inside": [], "nearest": None})
        query.assert_not_called()

    def test_optional_queries_are_grouped_and_partial_water_data_is_discarded(self):
        events = []
        @contextmanager
        def scope():
            events.append("enter")
            try:
                yield
            except Exception:
                events.append("recover")
                raise
            finally:
                events.append("exit")
        def query(statement, params, fetch_one=False):
            self.assertEqual(events[0], "enter")
            if fetch_one:
                raise RuntimeError("second query failed")
            return [("well", None, "EMSY")]
        data = PlanningData(query, optional_scope=scope)
        self.assertEqual(data.get_water_points(10, 20),
                         {"available": False, "inside": [], "nearest": None})
        self.assertEqual(events, ["enter", "recover", "exit"])

    def test_required_query_error_propagates(self):
        data = PlanningData(Mock(side_effect=ValueError("required source failed")))
        with self.assertRaisesRegex(ValueError, "required source failed"):
            data.point_report(10, 20)

    def test_data_service_runs_without_site_packages(self):
        script = """
import sys
sys.path.insert(0, sys.argv[1])
from tests.test_planning_data import PlanningDataTests
test = PlanningDataTests('test_reference_reports_run_directly_without_api_or_database')
result = test.run()
assert result.wasSuccessful(), (result.failures, result.errors)
for name in ('api_server', 'fastapi', 'psycopg2', 'config'):
    assert name not in sys.modules, name
"""
        result = subprocess.run([sys.executable, "-I", "-S", "-B", "-c", script, str(FIXTURES.parents[2])],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
