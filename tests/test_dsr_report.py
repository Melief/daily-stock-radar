"""Tests for the DSR consolidated report."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from scripts import dsr_report as report


class DsrReportTests(unittest.TestCase):
    def test_long_requires_fundamental_and_sw_pass(self):
        rows = [
            {"ticker": "AAA", "fundamental_status": "PASS", "sw_status": "PASS"},
            {"ticker": "BBB", "fundamental_status": "PASS", "sw_status": "EXCLUDED"},
            {"ticker": "CCC", "fundamental_status": "UNKNOWN", "sw_status": "ONBEKEND"},
        ]
        self.assertEqual([r["ticker"] for r in report.select_long_candidates(rows)], ["AAA"])

    def test_short_requires_technical_score_and_existing_sma_alignment(self):
        rows = [
            {"ticker": "AAA", "score_status": "OK", "short_score": "4", "sma20": "90", "sma50": "100"},
            {"ticker": "BBB", "score_status": "OK", "short_score": "4", "sma20": "110", "sma50": "100"},
            {"ticker": "CCC", "score_status": "OK", "short_score": "2", "sma20": "90", "sma50": "100"},
            {"ticker": "DDD", "score_status": "ONBEKEND", "short_score": "5", "sma20": "90", "sma50": "100"},
        ]
        self.assertEqual([r["ticker"] for r in report.select_short_candidates(rows)], ["AAA"])

    def test_52_week_and_ath_proximity_thresholds(self):
        self.assertTrue(report.proximity_bar(4, "52w").startswith("🟠 96.0%"))
        self.assertTrue(report.proximity_bar(-2, "52w").startswith("🟢 102.0%"))
        self.assertTrue(report.proximity_bar(12, "ath").startswith("🟠 88.0%"))
        self.assertTrue(report.proximity_bar(20, "ath").startswith("🔴 80.0%"))

    def test_ha_lists_use_confirmed_21_8_pivot_flags(self):
        rows = [
            {"ticker": "OLD", "ha_pivot_up": "False", "ha_pivot_down": "False"},
            {"ticker": "LONG", "ha_pivot_up": "True", "ha_pivot_down": "False"},
            {"ticker": "SHORT", "ha_pivot_up": "False", "ha_pivot_down": "True"},
            {"ticker": "ORDINARY", "ha_strong_signal": "True", "ha_strong_down_signal": "True"},
        ]
        self.assertEqual([r["ticker"] for r in report.select_ha_long_signals(rows)], ["LONG"])
        self.assertEqual([r["ticker"] for r in report.select_ha_short_signals(rows)], ["SHORT"])

    def test_long_technical_gate_requires_close_above_both_smas_not_sma_alignment(self):
        rows = [
            {"ticker": "PASS", "score_status": "OK", "long_score": "4",
             "above_sma20_completed": "True", "above_sma50_completed": "True"},
            {"ticker": "BELOW20", "score_status": "OK", "long_score": "4",
             "above_sma20_completed": "False", "above_sma50_completed": "True"},
            {"ticker": "BELOW50", "score_status": "OK", "long_score": "4",
             "above_sma20_completed": "True", "above_sma50_completed": "False"},
            {"ticker": "UNKNOWN", "score_status": "OK", "long_score": "4",
             "above_sma20_completed": "", "above_sma50_completed": "True"},
        ]
        self.assertEqual([r["ticker"] for r in report.select_long_technical_candidates(rows)], ["PASS"])

    def test_empty_table_is_explicit(self):
        self.assertEqual(report._table(["Ticker"], []), "_Geen kandidaten._")

    def test_short_sw_alignment_cell_can_remain_blank(self):
        rendered = report._table(["Ticker", "SW", "Borrow"], [["AAA", "__EMPTY__", "AVAILABLE"]])
        self.assertIn("| AAA |  | AVAILABLE |", rendered)

    def test_report_never_claims_full_when_market_regime_is_unknown(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "data").mkdir()
            files = {
                "technical_scores.csv": "ticker,score_status,long_score,close_completed,sma50,short_score,sma20\n",
                "ha_signals.csv": "ticker,ha_strong_signal,ha_strong_down_signal,above_sma20,above_sma50\n",
                "dsr_source_status.csv": "source,status,ticker_count,last_success_at,age_hours,detail\n",
                "long_fundamentals.csv": "ticker,fundamental_status\n",
                "long_sw_status.csv": "ticker,fundamental_status,sw_status\n",
                "short_borrow.csv": "ticker,status\n",
                "candidate_risk_news.csv": "ticker,risk_status,news_items\n",
            }
            for name, content in files.items():
                (root / "data" / name).write_text(content, encoding="utf-8")
            (root / "data" / "market_context.json").write_text(
                '{"session_date":"2026-11-20","market_regime":"ONBEKEND","symbols":{}}',
                encoding="utf-8",
            )
            for name in ("technical_score_status.json", "long_fundamental_status.json",
                         "long_sw_status.json", "short_borrow_status.json",
                         "candidate_risk_news_status.json", "dsr_run_status.json"):
                (root / "data" / name).write_text("{}", encoding="utf-8")
            with patch.object(report, "DATA", root / "data"), patch.object(report, "ROOT", root):
                text, details = report.build_report()
            self.assertIn("GEDEELTELIJKE DSR", text)
            self.assertEqual(details["status"], "PARTIAL")
            self.assertTrue(any("Risk-on/risk-off" in item for item in details["pending_components"]))


if __name__ == "__main__":
    unittest.main()
