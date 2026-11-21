"""Regression tests for the five-part DSR technical score."""
import unittest

import pandas as pd

from scripts import technical_score as ts


class TechnicalScoreTests(unittest.TestCase):
    def frame(self, end="2026-11-20", trend=1.0):
        dates = pd.bdate_range(end=end, periods=65)
        values = [100 + i * trend for i in range(65)]
        return pd.DataFrame({
            "High": [v + 1 for v in values],
            "Low": [v - 1 for v in values],
            "Close": values,
        }, index=dates)

    def test_price_history_and_session_validation(self):
        result = ts.analyse_price_history(self.frame(), "2026-11-20")
        self.assertEqual(result["date"], "2026-11-20")
        self.assertGreater(result["momentum_21d_pct"], 0)
        self.assertTrue(result["higher_highs_higher_lows"])
        with self.assertRaisesRegex(ValueError, "loopt achter"):
            ts.analyse_price_history(self.frame(end="2026-11-19"), "2026-11-20")

    def test_long_score_does_not_require_sma20_above_sma50(self):
        ha = {"above_sma20": "False", "above_sma50": "False", "rvol_5_21": "1.5"}
        price = {"above_sma20": True, "above_sma50": True, "sma20_above_sma50": False,
                 "momentum_21d_pct": 12.0, "higher_highs_higher_lows": True,
                 "lower_highs_lower_lows": False}
        result = ts.score_components(ha, price, 5.0, 7.0)
        self.assertEqual(result["long_score"], 5)
        self.assertEqual(result["status"], "OK")

    def test_short_score_is_independent_and_mirrored(self):
        ha = {"above_sma20": "True", "above_sma50": "True", "rvol_5_21": "1.3"}
        price = {"above_sma20": False, "above_sma50": False,
                 "momentum_21d_pct": -12.0, "higher_highs_higher_lows": False,
                 "lower_highs_lower_lows": True}
        result = ts.score_components(ha, price, -5.0, -7.0)
        self.assertEqual(result["short_score"], 5)
        self.assertEqual(result["long_score"], 0)

    def test_missing_input_never_becomes_zero_score(self):
        ha = {"above_sma20": "", "above_sma50": "False", "rvol_5_21": "1.3"}
        price = {"above_sma20": None, "above_sma50": False,
                 "momentum_21d_pct": -12.0, "higher_highs_higher_lows": False,
                 "lower_highs_lower_lows": True}
        result = ts.score_components(ha, price, -5.0, -7.0)
        self.assertIsNone(result["long_score"])
        self.assertIsNone(result["short_score"])
        self.assertEqual(result["status"], "ONBEKEND")


if __name__ == "__main__":
    unittest.main()
