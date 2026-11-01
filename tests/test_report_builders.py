"""Report construction can run with the standard library and loaded data only."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import unittest

import planning_reports as reports


FIXTURES = Path(__file__).parent / "fixtures" / "reports"


def scenario(name):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def render(case):
    shared = {key: case[key] for key in ("oroi", "shore", "archeo", "church", "remata", "ydro")}
    shared["outside_plan"] = not case["inside_plan"]
    if case["mode"] == "parcel":
        return reports.build_parcel_report(
            **shared, parcel=case["parcel"], rights=case["rights"], overlaps=case["overlaps"])
    return reports.build_point_report(**shared, natura=case["natura"])


class BuilderTests(unittest.TestCase):
    def test_reference_reports_match_without_api_or_data_providers(self):
        for name in ("parcel_in_plan", "point_minimal", "point_populated"):
            with self.subTest(case=name):
                expected = (FIXTURES / f"{name}.expected.txt").read_text(encoding="utf-8").rstrip("\n")
                self.assertEqual(render(scenario(name)), expected)

    def test_repeated_builds_leave_all_loaded_data_unchanged(self):
        for name in ("parcel_in_plan", "point_minimal", "point_populated"):
            with self.subTest(case=name):
                case = scenario(name)
                before = deepcopy(case)
                first = render(case)
                self.assertEqual(case, before)
                self.assertEqual(render(case), first)
                self.assertEqual(case, before)

    def test_parcel_approval_does_not_leak_into_a_later_point_report(self):
        parcel = scenario("parcel_in_plan")
        point = scenario("point_minimal")
        point["oroi"] = parcel["oroi"]
        before = render(point)
        self.assertIn("Κτηματική Υπηρεσία Δημοσίου", render(parcel))
        self.assertEqual(render(point), before)
        self.assertNotIn("Κτηματική Υπηρεσία Δημοσίου", before)

    def test_missing_regulations_require_explicit_outside_plan_status(self):
        for name in ("parcel_in_plan", "point_minimal"):
            with self.subTest(case=name):
                case = scenario(name)
                case["oroi"] = {"found": False}
                self.assertEqual(render(case), reports.MISSING_REGULATIONS)
                case["inside_plan"] = False
                self.assertIn("ΕΚΤΟΣ ΣΧΕΔΙΟΥ", render(case))

    def test_missing_parcel_returns_the_existing_error(self):
        case = scenario("parcel_in_plan")
        case["parcel"] = None
        self.assertEqual(render(case), reports.MISSING_PARCEL)

    def test_unsupported_characters_keep_the_existing_replacement_behavior(self):
        for name in ("parcel_in_plan", "point_minimal"):
            with self.subTest(case=name):
                case = scenario(name)
                case["oroi"]["xriseis"] = "TEST \U0001f600"
                result = render(case)
                self.assertIn("ROW|Χρήσεις γης|TEST ?", result)
                self.assertEqual(result.encode("windows-1253").decode("windows-1253"), result)

    def test_builders_run_without_site_packages_or_api_import(self):
        # -I -S excludes installed FastAPI/PostgreSQL packages and startup hooks.
        script = """
import sys
sys.path.insert(0, sys.argv[1])
from tests.test_report_builders import FIXTURES, render, scenario
for name in ("parcel_in_plan", "point_minimal", "point_populated"):
    expected = (FIXTURES / (name + ".expected.txt")).read_text(encoding="utf-8").rstrip("\\n")
    assert render(scenario(name)) == expected, name
assert "api_server" not in sys.modules
assert "fastapi" not in sys.modules
assert "psycopg2" not in sys.modules
assert "config" not in sys.modules
"""
        result = subprocess.run(
            [sys.executable, "-I", "-S", "-B", "-c", script, str(FIXTURES.parents[2])],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
