"""The extracted geometry service needs loaded inputs and a query callable only."""

from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock

from boundary_corrections import SurveyInputError, calculate_boundary_correction, parse_survey_ring


EXPECTED = """OK|S01|0.5
F|S01|100.0|0.0,0.0;10.0,0.0;10.0,10.0;0.0,10.0;0.0,0.0
TBL|TITLE|ΠΙΝΑΚΑΣ ΜΕΤΑΒΟΛΩΝ|Διόρθωση ορίων
TBL|HEADER|Αρχικά / Τελικά γεωτεμάχια|
TBL|ROW|S01|100.0 ? 100.0 τ.μ. (0.0)
TBL|MERGED|Ισοζύγιο: 100.0 + Δ(0) ? Α(0) ? τελικό(100.0) = 0.0 τ.μ. ?|"""


def calculate_unchanged():
    survey = parse_survey_ring("0,0;10,0;10,10;0,10")
    query = Mock(side_effect=[
        (True,), ("S01", 100), (100,), [], (0, 0, False), [], (0, 0),
        [("LINESTRING(0 0,10 0,10 10,0 10,0 0)",)],
    ])
    return calculate_boundary_correction(survey, query)


class BoundaryServiceTests(unittest.TestCase):
    def test_standalone_calculation_matches_hand_authored_protocol(self):
        self.assertEqual(calculate_unchanged(), EXPECTED)

    def test_input_errors_keep_specific_messages(self):
        for body, tol, message in (
                ("0,0;1,0;nan,1", 0.5, "TOPO_PROP coordinates must be finite"),
                ("0,0;1,0;0,0", 0.5, "Need at least 3 distinct vertices"),
                ("0,0;1,0;bad,1", 0.5, "Could not parse coordinates (expected x,y;x,y;...)"),
                ("0,0;1,0;0,1", -1, "Sliver tolerance must be finite and non-negative")):
            with self.subTest(body=body, tol=tol):
                with self.assertRaises(SurveyInputError) as error:
                    parse_survey_ring(body, tol)
                self.assertEqual(str(error.exception), message)

    def test_service_runs_without_api_database_driver_or_site_packages(self):
        script = """
import sys
sys.path.insert(0, sys.argv[1])
from tests.test_boundary_service import EXPECTED, calculate_unchanged
assert calculate_unchanged() == EXPECTED
for name in ("api_server", "fastapi", "psycopg2", "database_sessions", "config"):
    assert name not in sys.modules, name
"""
        result = subprocess.run(
            [sys.executable, "-I", "-S", "-B", "-c", script, str(Path(__file__).resolve().parents[1])],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
