"""Offline request validation and failure boundaries for KGEOM."""

import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, Mock, patch

import api_server as api
from tests.support import OfflineCase


class BoundaryCorrectionTests(OfflineCase):
    def setUp(self):
        super().setUp()
        self.query = Mock(side_effect=AssertionError("Unexpected SQL"))
        self.snapshot = self.start_patch(patch.object(api, "read_only_snapshot"))
        self.snapshot.return_value.__enter__.return_value = self.query
        self.snapshot.return_value.__exit__.return_value = False
        self.start_patch(patch.object(
            api, "execute_query", side_effect=AssertionError("KGEOM must use its snapshot")))

    def render(self, body, tol=0.5):
        request = AsyncMock()
        request.body.return_value = body.encode("utf-8")
        return asyncio.run(api.geom_diorthosi(request, tol=tol))

    def test_malformed_and_nonfinite_coordinates_stop_before_sql(self):
        for body in ("", " ", "1,2", "0,0;1,0", "0,0;1,0;0,0", ";;;",
                     "0,0;1,0;no,1", "0,0;1,0;1,2,3", "0,0;1,0;nan,1",
                     "0,0;1,0;1,inf", "0,0;1,0;-inf,1", "0,0;1,0;1e999,1"):
            with self.subTest(body=body):
                self.assertTrue(self.render(body).startswith("ERROR|"))
        self.query.assert_not_called()
        self.snapshot.assert_not_called()

    def test_invalid_tolerance_stops_before_sql(self):
        for tol in (-1.0, float("nan"), float("inf"), float("-inf")):
            with self.subTest(tol=tol):
                self.assertEqual(self.render("0,0;10,0;0,10", tol),
                                 "ERROR|Sliver tolerance must be finite and non-negative")
        self.query.assert_not_called()
        self.snapshot.assert_not_called()

    def test_validity_check_uses_only_the_closed_input_ring(self):
        self.query.side_effect = None
        self.query.return_value = (False,)
        for body in ("0,0;10,0;0,10", "0,0;10,0;0,10;0,0;"):
            with self.subTest(body=body):
                self.query.reset_mock()
                self.assertEqual(self.render(body),
                                 "ERROR|TOPO_PROP must be a valid polygon with positive area")
                self.query.assert_called_once()
                sql, args = self.query.call_args.args
                self.assertNotIn("sp_geodata", sql)
                self.assertNotIn("ST_MakeValid", sql)
                self.assertEqual(args, ("POLYGON((0.0 0.0,10.0 0.0,0.0 10.0,0.0 0.0))",))

    def test_missing_subject_stops_before_piece_or_final_queries(self):
        self.query.side_effect = [(True,), None]
        self.assertEqual(self.render("0,0;10,0;0,10"),
                         "ERROR|No operating parcel overlaps the TOPO_PROP polygon")
        self.assertEqual(self.query.call_count, 2)

    def test_query_failure_cannot_return_partial_drawing_output(self):
        self.query.side_effect = [(True,), ("S01", Decimal("100.00")), RuntimeError("SQL failed")]
        with self.assertRaisesRegex(RuntimeError, "SQL failed"):
            self.render("0,0;10,0;10,10;0,10")
        self.assertEqual(self.query.call_count, 3)
        self.assertIs(self.snapshot.return_value.__exit__.call_args.args[0], RuntimeError)

    def test_unchanged_parcel_preserves_the_drawing_and_table_protocol(self):
        self.query.side_effect = [
            (True,), ("S01", Decimal("100.00")), (Decimal("100.00"),),
            [], (0, Decimal("0.00"), False), [], (0, Decimal("0.00")),
            [("LINESTRING(0 0,10 0,10 10,0 10,0 0)",)],
        ]
        result = self.render("0,0;10,0;10,10;0,10")
        rows = result.splitlines()
        self.assertEqual(rows[:2], ["OK|S01|0.5",
                         "F|S01|100.0|0.0,0.0;10.0,0.0;10.0,10.0;0.0,10.0;0.0,0.0"])
        self.assertTrue(all(row.startswith("TBL|") for row in rows[2:]))
        self.assertEqual(len(rows), 6)
        self.assertIn("TBL|ROW|S01|100.0 ? 100.0 τ.μ. (0.0)", result)
        self.assertNotIn("ΕΛΕΓΞΕ", result)
        self.assertEqual(result.encode("windows-1253").decode("windows-1253"), result)
        self.snapshot.assert_called_once_with(
            api.db_pool, protected_relations=(("sp_geodata", "kaek_parcels_operating"),))

    def test_special_parcel_markers_accept_greek_and_latin(self):
        for kaek, expected in (("EK01", True), ("ek01", True), ("ΕΚ01", True),
                               ("εκ01", True), ("S01", False), (None, False)):
            with self.subTest(kaek=kaek):
                self.assertEqual(api._is_special_kaek(kaek), expected)

    def test_http_route_still_uses_the_tested_endpoint(self):
        routes = {r.path: r for r in api.app.routes if hasattr(r, "endpoint")}
        self.assertIs(routes["/geom/diorthosi"].endpoint, api.geom_diorthosi)
        self.assertEqual(routes["/geom/diorthosi"].methods, {"POST"})
