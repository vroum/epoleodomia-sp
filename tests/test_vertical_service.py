"""Standalone KGEOMV service fixtures with no live API or database."""

from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock

from vertical_corrections import calculate_vertical_correction, parse_vertical_survey


BODY = "V|01|100|1000|0,0;10,0;10,10;0,10"
EXPECTED = """OK|P01|100.0
VF|01|100.0|0.0,0.0;10.0,0.0;10.0,10.0;0.0,10.0;0.0,0.0
TBL|TITLE|ΠΙΝΑΚΑΣ ΚΑΘΕΤΩΝ|Διόρθωση καθέτων — P01
TBL|HEADER|Γεωτεμάχιο|
TBL|ROW|ΚΑΕΚ|P01 — 100.0 τ.μ.
TBL|HEADER|Κάθετες: τίτλος / κτηματ. / αποτύπωση|
TBL|ROW|ΑΧ 01|τίτλ: 100.0 (1000.0‰) · ΚΤ(01): 100.0 · μέτρ: 100.0 (1000.0‰)
TBL|HEADER|Έλεγχοι|
TBL|ROW|Κοινόχρηστο εκτός ΑΧ|0.0 τ.μ. (0.0‰)
TBL|MERGED|Όλοι οι έλεγχοι εντάξει — καμία προειδοποίηση.|"""


def single_query():
    return Mock(side_effect=[None, ("P01", 100), [("01", 100)], (100, 100),
                            [("01", 100)], [("LINESTRING(0 0,10 0,10 10,0 10,0 0)", 0)],
                            (0,), []])


class VerticalServiceTests(unittest.TestCase):
    def test_single_vertical_matches_hand_authored_protocol(self):
        self.assertEqual(calculate_vertical_correction(parse_vertical_survey(BODY), single_query()), EXPECTED)

    def test_numbers_and_optional_title_fields_are_prepared_without_io(self):
        survey = parse_vertical_survey("\n V||||0,0;1,0;0,1 \n\nV|A|0|1000|2,0;3,0;2,1")
        first, second = survey.verticals
        self.assertEqual((first.number, first.specified_number, first.title_area, first.title_xiliosta),
                         ("01", "", None, None))
        self.assertEqual((second.number, second.title_area, second.title_xiliosta), ("A", 0.0, 1000.0))
        self.assertEqual(first.wkt, "POLYGON((0.0 0.0,1.0 0.0,0.0 1.0,0.0 0.0))")

    def test_service_runs_with_only_the_standard_library(self):
        script = """
import sys
sys.path.insert(0, sys.argv[1])
from tests.test_vertical_service import BODY, EXPECTED, single_query
from vertical_corrections import calculate_vertical_correction, parse_vertical_survey
assert calculate_vertical_correction(parse_vertical_survey(BODY), single_query()) == EXPECTED
for name in ("api_server", "fastapi", "psycopg2", "database_sessions", "config"):
    assert name not in sys.modules, name
"""
        result = subprocess.run(
            [sys.executable, "-I", "-S", "-B", "-c", script, str(Path(__file__).resolve().parents[1])],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
