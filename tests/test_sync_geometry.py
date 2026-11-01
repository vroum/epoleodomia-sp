"""Transport/error handling around the batched PostGIS comparison."""

from unittest.mock import MagicMock, patch

import sync_geometry
from tests.support import OfflineCase


class GeometryComparisonTests(OfflineCase):
    def test_empty_batch_uses_no_database_queries(self):
        cur = MagicMock()
        with patch.object(sync_geometry, "execute_values") as execute:
            self.assertEqual(sync_geometry.geometry_changes(cur, []), {})
        execute.assert_not_called()
        cur.execute.assert_not_called()

    def test_binary_precision_and_all_batch_results_are_preserved(self):
        pairs = [(1, memoryview(b"exact EWKB bytes"), "POINT(1 1)"), (2, None, None)]
        with patch.object(sync_geometry, "execute_values", return_value=[(1, True), (2, False)]) as execute:
            result = sync_geometry.geometry_changes(MagicMock(), pairs)
        self.assertEqual(result, {1: True, 2: False})
        self.assertIs(execute.call_args.args[2], pairs)
        self.assertTrue(execute.call_args.kwargs["fetch"])

    def test_comparison_failure_propagates_to_the_load_transaction(self):
        with patch.object(sync_geometry, "execute_values", side_effect=RuntimeError("query failed")):
            with self.assertRaisesRegex(RuntimeError, "query failed"):
                sync_geometry.geometry_changes(MagicMock(), [(1, b"binary", "POINT(1 1)")])
