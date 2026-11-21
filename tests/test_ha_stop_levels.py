"""Tests for latest completed Heikin-Ashi stop levels."""
import unittest

import pandas as pd

from scripts.ha_signals import latest_ha_stops


class HaStopLevelTests(unittest.TestCase):
    def test_rising_ha_series_returns_latest_low_equals_open_stop(self):
        dates = pd.bdate_range("2026-10-01", periods=40)
        frame = pd.DataFrame({
            "Open": [100 + i for i in range(40)],
            "High": [102 + i for i in range(40)],
            "Low": [100 + i for i in range(40)],
            "Close": [100.5 + i for i in range(40)],
        }, index=dates)
        result = latest_ha_stops(frame)
        self.assertNotEqual(result["last_ha_long_stop"], "")
        self.assertEqual(result["last_ha_long_stop_date"], dates[-1].strftime("%Y-%m-%d"))
        self.assertEqual(result["last_ha_short_stop"], "")

    def test_falling_ha_series_returns_latest_high_equals_open_stop(self):
        dates = pd.bdate_range("2026-10-01", periods=40)
        frame = pd.DataFrame({
            "Open": [200 - i for i in range(40)],
            "High": [200 - i for i in range(40)],
            "Low": [198 - i for i in range(40)],
            "Close": [199.5 - i for i in range(40)],
        }, index=dates)
        result = latest_ha_stops(frame)
        self.assertNotEqual(result["last_ha_short_stop"], "")
        self.assertEqual(result["last_ha_short_stop_date"], dates[-1].strftime("%Y-%m-%d"))
        self.assertEqual(result["last_ha_long_stop"], "")

    def test_empty_frame_returns_explicit_unknown_stops(self):
        result = latest_ha_stops(pd.DataFrame())
        self.assertEqual(result["last_ha_long_stop"], "")
        self.assertEqual(result["last_ha_short_stop"], "")


if __name__ == "__main__":
    unittest.main()
