"""Offline HTTP/database guards shared by the regression suites."""

from contextlib import redirect_stdout
from io import StringIO
import unittest
from unittest.mock import MagicMock, patch


def response(payload):
    result = MagicMock()
    result.json.return_value = payload
    return result


class OfflineCase(unittest.TestCase):
    def start_patch(self, patcher):
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def setUp(self):
        self.http = MagicMock(side_effect=AssertionError("Live HTTP disabled in tests"))
        self.start_patch(patch("requests.get", self.http))
        self.start_patch(patch("requests.post", self.http))
        self.connect = self.start_patch(patch(
            "psycopg2.connect", side_effect=AssertionError("Live database disabled in tests")))
        output = redirect_stdout(StringIO())
        output.__enter__()
        self.addCleanup(output.__exit__, None, None, None)
