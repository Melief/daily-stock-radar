"""Regression tests for the DSR market-context module."""
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from scripts import market_context as mc


class MarketContextTests(unittest.TestCase):
    def frame(self, trend=1.0, end=date(2026, 11, 20)):
        dates = pd.bdate_range(end=end, periods=65)
        return pd.DataFrame({
            "High": [101 + i * trend for i in range(65)],
            "Low": [99 + i * trend for i in range(65)],
            "Close": [100 + i * trend for i in range(65)],
        }, index=dates)

    def test_completed_session_and_indicators(self):
        result = mc.analyse_symbol(self.frame(), "SPX", date(2026, 11, 20))
        self.assertEqual(result["date"], "2026-11-20")
        self.assertEqual(result["position"], "BOVEN_BEIDE")
        self.assertEqual(result["sma_alignment"], "BULLISH")

    def test_confirmed_swing_levels_are_returned(self):
        dates = pd.bdate_range(end=date(2026, 11, 20), periods=65)
        closes = [100 + (i % 8) for i in range(65)]
        frame = pd.DataFrame({
            "High": [value + 2 for value in closes],
            "Low": [value - 2 for value in closes],
            "Close": closes,
        }, index=dates)
        result = mc.analyse_symbol(frame, "SPX", date(2026, 11, 20))
        self.assertEqual(result["support_resistance_method"],
                         "confirmed 5-session swing pivots; 126-session lookback")
        self.assertIsNotNone(result["support"])
        self.assertIsNotNone(result["resistance"])

    def test_rejects_stale_data(self):
        with self.assertRaisesRegex(ValueError, "koersdata loopt achter"):
            mc.analyse_symbol(self.frame(end=date(2026, 11, 19)), "QQQ", date(2026, 11, 20))

    def test_partial_when_symbol_missing(self):
        spx = mc.analyse_symbol(self.frame(), "SPX", date(2026, 11, 20))
        result = mc.build_context(date(2026, 11, 20), {"SPX": spx}, {"QQQ": "data ontbreekt"})
        self.assertEqual(result["data_status"], "PARTIAL")
        self.assertEqual(result["market_regime"], "ONBEKEND")

    def test_does_not_invent_undefined_risk_regime(self):
        session = date(2026, 11, 20)
        spx = mc.analyse_symbol(self.frame(0.5), "SPX", session)
        qqq = mc.analyse_symbol(self.frame(1.0), "QQQ", session)
        result = mc.build_context(session, {"SPX": spx, "QQQ": qqq}, {})
        self.assertEqual(result["data_status"], "FULL")
        self.assertEqual(result["market_regime"], "ONBEKEND")
        self.assertIsNotNone(result["qqq_minus_spx_momentum_21d_pct"])
        self.assertEqual(result["status"], "PARTIAL")

    def test_multilevel_yfinance_columns_are_normalised(self):
        frame = self.frame()
        frame.columns = pd.MultiIndex.from_product([frame.columns, ["^GSPC"]])
        result = mc.analyse_symbol(frame, "SPX", date(2026, 11, 20))
        self.assertEqual(result["status"], "OK")
        frame = self.frame()
        frame.columns = pd.MultiIndex.from_tuples([("^GSPC", column) for column in frame.columns])
        result = mc.analyse_symbol(frame, "SPX", date(2026, 11, 20))
        self.assertEqual(result["status"], "OK")

    def test_download_uses_unadjusted_official_close(self):
        with patch.object(mc.yf, "download", return_value=self.frame()) as download:
            mc.fetch_symbol("^GSPC", date(2026, 11, 20))
        self.assertFalse(download.call_args.kwargs["auto_adjust"])

    def test_json_output_has_real_newline_and_preserves_dsr_status(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "data").mkdir()
            status_file = root / "data" / "dsr_run_status.json"
            status_file.write_text(json.dumps({
                "status": "PARTIAL",
                "pending_components": ["SPX/QQQ market context", "Long selectie"],
                "other_field": "preserve",
            }), encoding="utf-8")
            with patch.object(mc, "ROOT", root):
                mc.write_context({"status": "PARTIAL", "data_status": "FULL"}, root / "market_context.json")
            raw = (root / "market_context.json").read_text(encoding="utf-8")
            self.assertTrue(raw.endswith("\n"))
            self.assertFalse(raw.endswith("\\n"))
            self.assertEqual(json.loads(raw)["data_status"], "FULL")
            updated = json.loads(status_file.read_text(encoding="utf-8"))
            self.assertEqual(updated["status"], "PARTIAL")
            self.assertEqual(updated["pending_components"], ["SPX/QQQ market context", "Long selectie"])
            self.assertEqual(updated["other_field"], "preserve")
            self.assertEqual(updated["market_context_status"], "PARTIAL")
            self.assertEqual(updated["market_context_data_status"], "FULL")


if __name__ == "__main__":
    unittest.main()
