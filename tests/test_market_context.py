"""Unit tests for SPX/QQQ market context calculations."""
import unittest
from datetime import date

import pandas as pd

from scripts.market_context import analyse_symbol, build_context


class MarketContextTests(unittest.TestCase):
    def frame(self, end=date(2026, 11, 20), trend=1.0):
        dates = pd.bdate_range(end=end, periods=65)
        closes = [100.0 + i * trend for i in range(len(dates))]
        return pd.DataFrame({"Close": closes}, index=dates)

    def test_calculates_completed_session_and_moving_average_position(self):
        result = analyse_symbol(self.frame(), "SPX", date(2026, 11, 20))
        self.assertEqual(result["date"], "2026-11-20")
        self.assertEqual(result["position"], "BOVEN_BEIDE")
        self.assertEqual(result["sma_alignment"], "BULLISH")
        self.assertGreater(result["momentum_21d_pct"], 0)
        self.assertEqual(result["status"], "OK")

    def test_rejects_data_behind_expected_completed_session(self):
        frame = self.frame(end=date(2026, 11, 19))
        with self.assertRaisesRegex(ValueError, "koersdata loopt achter"):
            analyse_symbol(frame, "QQQ", date(2026, 11, 20))

    def test_context_is_partial_when_one_index_is_missing(self):
        spx = analyse_symbol(self.frame(), "SPX", date(2026, 11, 20))
        context = build_context(date(2026, 11, 20), {"SPX": spx}, {"QQQ": "HTTP/data error"})
        self.assertEqual(context["status"], "PARTIAL")
        self.assertEqual(context["market_regime"], "ONBEKEND")
        self.assertIsNone(context["qqq_minus_spx_momentum_21d_pct"])

    def test_complete_context_has_explicit_regime_and_relative_momentum(self):
        session = date(2026, 11, 20)
        spx = analyse_symbol(self.frame(trend=0.5), "SPX", session)
        qqq = analyse_symbol(self.frame(trend=1.0), "QQQ", session)
        context = build_context(session, {"SPX": spx, "QQQ": qqq}, {})
        self.assertEqual(context["status"], "FULL")
        self.assertIsNotNone(context["qqq_minus_spx_momentum_21d_pct"])
        self.assertIn(context["market_regime"], {"RISK_ON", "RISK_OFF", "GEMENGD"})


if __name__ == "__main__":
    unittest.main()
