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
        return pd.DataFrame({"Close": [100 + i * trend for i in range(65)]}, index=dates)

    def test_completed_session_and_indicators(self):
        result = mc.analyse_symbol(self.frame(), "SPX", date(2026, 11, 20))
        self.assertEqual(result["date"], "2026-11-20")
        self.assertEqual(result["position"], "BOVEN_BEIDE")
        self.assertEqual(result["sma_alignment"], "BULLISH")

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

    def test_json_output_has_real_newline_and_preserves_dsr_status(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            status_file = root / "dsr_run_status.json"
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
            self.assertEqual(updated["pending_components"], ["Long selectie"])
            self.assertEqual(updated["other_field"], "preserve")
            self.assertEqual(updated["market_context_status"], "FULL")


if __name__ == "__main__":
    unittest.main()
