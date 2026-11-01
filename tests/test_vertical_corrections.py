"""KGEOMV request and failure boundaries without database/network access."""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import api_server as api
from tests.support import OfflineCase
from tests.test_vertical_service import BODY, EXPECTED, single_query


class VerticalCorrectionTests(OfflineCase):
    def setUp(self):
        super().setUp()
        self.query = Mock(side_effect=AssertionError("Unexpected SQL"))
        self.snapshot = self.start_patch(patch.object(api, "read_only_snapshot"))
        self.snapshot.return_value.__enter__.return_value = self.query
        self.snapshot.return_value.__exit__.return_value = False
        self.start_patch(patch.object(api, "execute_query", side_effect=AssertionError("Snapshot bypass")))

    def render(self, body, tol=0.5):
        request = AsyncMock()
        request.body.return_value = body.encode("utf-8")
        return asyncio.run(api.geom_kathetes(request, tol=tol))

    def test_malformed_record_cannot_silently_drop_part_of_a_request(self):
        for body in ("", " ", "unexpected", "V|01|", "V|01|||", BODY + "\nbad record",
                     BODY + "\nV|02|1|2|0,0;bad,0;0,1", BODY + "|extra"):
            with self.subTest(body=body):
                self.assertTrue(self.render(body).startswith("ERROR|"))
        self.snapshot.assert_not_called()
        self.query.assert_not_called()

    def test_nonfinite_and_degenerate_coordinates_fail_before_connection(self):
        for coords in ("0,0;1,0;nan,1", "0,0;1,0;inf,1", "0,0;1,0;1,1e999",
                       "0,0;1,0;0,0", "0,0;1,0", "0,0;1,0;1,2,3"):
            with self.subTest(coords=coords):
                self.assertTrue(self.render("V|01|||" + coords).startswith("ERROR|"))
        self.snapshot.assert_not_called()

    def test_tolerance_must_be_finite_and_nonnegative(self):
        for tol in (-0.1, float("nan"), float("inf"), float("-inf")):
            with self.subTest(tol=tol):
                self.assertEqual(self.render(BODY, tol),
                                 "ERROR|Overlap/sliver tolerance must be finite and non-negative")
        self.snapshot.assert_not_called()

    def test_title_numbers_require_finite_nonnegative_area_and_valid_xiliosta(self):
        for area, xiliosta in (("nan", ""), ("inf", ""), ("-1", ""), ("text", ""),
                               ("", "NaN"), ("", "inf"), ("", "-1"), ("", "1001")):
            with self.subTest(area=area, xiliosta=xiliosta):
                self.assertTrue(self.render(f"V|01|{area}|{xiliosta}|0,0;1,0;0,1").startswith("ERROR|"))
        self.snapshot.assert_not_called()

    def test_duplicate_or_unrepresentable_labels_fail_before_connection(self):
        for body in (BODY + "\n" + BODY, BODY.replace("|01|", "||", 1) + "\n" + BODY,
                     BODY.replace("|01|", "|\U0001f600|", 1), BODY.replace("|01|", "|A\x00B|", 1)):
            with self.subTest(body=body):
                self.assertTrue(self.render(body).startswith("ERROR|"))
        self.snapshot.assert_not_called()

    def test_invalid_polygon_stops_before_source_queries(self):
        self.query.side_effect = [("01",)]
        self.assertEqual(self.render(BODY), "ERROR|VST 01 must be a valid polygon with positive area")
        self.query.assert_called_once()
        self.assertNotIn("sp_geodata", self.query.call_args.args[0])

    def test_missing_parent_does_not_query_ax_or_build_output(self):
        self.query.side_effect = [None, None]
        self.assertEqual(self.render(BODY), "ERROR|No operating parcel overlaps the surveyed kathetes")
        self.assertEqual(self.query.call_count, 2)

    def test_invalid_cadastral_fields_fail_before_measurement(self):
        for rows in ([(None, 50)], [("01", -1)], [("01", float("nan"))],
                     [("01", None)], [("01", 50), ("01", 60)]):
            with self.subTest(rows=rows):
                self.query.reset_mock()
                self.query.side_effect = [None, ("P01", 100), rows]
                self.assertTrue(self.render(BODY).startswith("ERROR|"))
                self.assertEqual(self.query.call_count, 3)

    def test_query_failure_propagates_and_exits_the_snapshot(self):
        self.query.side_effect = [None, ("P01", 100), [("01", 100)], RuntimeError("geometry failed")]
        with self.assertRaisesRegex(RuntimeError, "geometry failed"):
            self.render(BODY)
        self.assertIs(self.snapshot.return_value.__exit__.call_args.args[0], RuntimeError)

    def test_reference_output_uses_one_snapshot_protecting_both_sources(self):
        self.snapshot.return_value.__enter__.return_value = single_query()
        self.assertEqual(self.render(BODY), EXPECTED)
        self.snapshot.assert_called_once_with(api.db_pool, protected_relations=(
            ("sp_geodata", "kaek_parcels_operating"), ("sp_geodata", "kaek_apokleistikes_operating")))

    def test_route_still_uses_the_same_post_endpoint(self):
        routes = {route.path: route for route in api.app.routes if hasattr(route, "endpoint")}
        self.assertIs(routes["/geom/kathetes"].endpoint, api.geom_kathetes)
        self.assertEqual(routes["/geom/kathetes"].methods, {"POST"})
