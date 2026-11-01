"""Date/filter HTTP contracts and opening history without writer credentials."""
from contextlib import contextmanager
from datetime import date, datetime, timezone
from unittest.mock import patch

import sync_history_api as views
import sync_launcher as launcher
from tests.support import OfflineCase
from tests.test_raster_api import ASGIClient


class HistoryTests(OfflineCase):
    def test_four_calendar_months_and_athens_day_boundaries(self):
        start,end=views.date_range('4m',today=date(2026,11,1))
        self.assertEqual(start,datetime(2026,6,30,21,tzinfo=timezone.utc))
        self.assertEqual(end,datetime(2026,11,1,22,tzinfo=timezone.utc))
        start,end=views.date_range('custom',date(2026,10,25),date(2026,10,25))
        self.assertEqual((end-start).total_seconds(),25*3600)
        start,end=views.date_range('1m',today=date(2024,3,31))
        self.assertEqual(start.astimezone(views.ATHENS).date(),date(2024,2,29))

    def test_custom_dates_require_valid_bounded_range(self):
        for start,end in ((None,None),(date(2026,11,2),date(2026,11,1)),(date(2000,1,1),date(2026,1,1)),(date.max,date.max)):
            with self.subTest(start=start,end=end),self.assertRaises(ValueError):
                views.date_range('custom',start,end)

    def test_history_shortcut_needs_no_database_or_sync_credentials(self):
        with patch.object(launcher.webbrowser,'open') as browser,patch.object(launcher,'load_sync_database') as credentials:
            self.assertEqual(launcher.main(['history']),0)
        browser.assert_called_once_with('http://127.0.0.1:8000/sync-history')
        credentials.assert_not_called()
        self.connect.assert_not_called()

    def test_real_routes_validate_before_querying(self):
        client=ASGIClient()
        for path,params in (('/sync-history/api/overview',{'period':'bad'}),
                            ('/sync-history/api/overview',{'limit':10000}),
                            ('/sync-history/api/overview',{'offset':-1}),
                            ('/sync-history/api/overview',{'domain':"tee';DROP TABLE x"}),
                            ('/sync-history/api/runs/not-a-uuid',{})):
            with self.subTest(params=params):
                self.assertEqual(client.get(path,params=params).status_code,422)
        self.connect.assert_not_called()

    def test_absent_installation_is_not_an_empty_successful_history(self):
        @contextmanager
        def snapshot(_):
            from unittest.mock import MagicMock
            yield MagicMock()
        with patch.object(views,'read_only_snapshot',snapshot),patch.object(views.history,'installed',return_value=False):
            response=ASGIClient().get('/sync-history/api/overview',params={})
        self.assertEqual(response.status_code,200)
        self.assertFalse(response.json()['installed'])
        self.assertNotIn('totals',response.json())
