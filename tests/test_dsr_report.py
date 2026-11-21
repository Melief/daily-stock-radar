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
            self.assertTrue(any("SPX/QQQ-marktcontext" in item for item in details["pending_components"]))


    def test_optional_borrow_partial_does_not_block_full_report(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            data = root / "data"
            data.mkdir()
            csv_files = {
                "technical_scores.csv": "ticker,score_status,long_score,close_completed,sma50,short_score,sma20,above_sma20_completed,above_sma50_completed\n",
                "ha_signals.csv": "ticker,ha_pivot_up,ha_pivot_down\n",
                "dsr_source_status.csv": "source,status,ticker_count,last_success_at,age_hours,detail\nManual,MANUAL,1,,,manual\n",
                "long_fundamentals.csv": "ticker,fundamental_status\n",
                "long_sw_status.csv": "ticker,fundamental_status,sw_status\n",
                "short_borrow.csv": "ticker,status\n",
                "candidate_risk_news.csv": "ticker,candidate_type,risk_status,news_items\n",
                "entry_risk.csv": "ticker,candidate_type,entry_status,target_feasibility\n",
            }
            for name, content in csv_files.items():
                (data / name).write_text(content, encoding="utf-8")
            (data / "market_context.json").write_text(
                '{"status":"FULL","data_status":"FULL","session_date":"2026-11-20","market_regime":"RISK-OFF","symbols":{}}',
                encoding="utf-8",
            )
            statuses = {
                "technical_score_status.json": {"status": "FULL"},
                "long_fundamental_status.json": {"status": "FULL", "unknown": 0, "passed": 0, "failed": 0},
                "long_sw_status.json": {"status": "FULL", "unknown": 0, "passed": 0, "excluded_sw": 0},
                "short_borrow_status.json": {"status": "PARTIAL", "unknown": 4},
                "candidate_risk_news_status.json": {"status": "FULL", "unknown": 0, "review_required": 3},
                "entry_risk_status.json": {"status": "FULL", "unknown": 0},
                "dsr_run_status.json": {},
            }
            import json
            for name, payload in statuses.items():
                (data / name).write_text(json.dumps(payload), encoding="utf-8")
            with patch.object(report, "DATA", data), patch.object(report, "ROOT", root):
                rendered, details = report.build_report()
            self.assertEqual(details["status"], "FULL")
            self.assertIn("VOLLEDIGE DSR", rendered)
            self.assertFalse(details["pending_components"])
            self.assertTrue(any("News/event review" in item for item in details["non_blocking_components"]))


    def test_unknown_fundamentals_do_not_block_when_candidate_is_excluded_by_sw(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            data = root / "data"
            data.mkdir()
            csv_files = {
                "technical_scores.csv": "ticker,score_status,long_score,close_completed,sma50,short_score,sma20,above_sma20_completed,above_sma50_completed\n",
                "ha_signals.csv": "ticker,ha_pivot_up,ha_pivot_down\n",
                "dsr_source_status.csv": "source,status,ticker_count,last_success_at,age_hours,detail\nManual,MANUAL,1,,,manual\n",
                "long_fundamentals.csv": "ticker,fundamental_status\nMCK,UNKNOWN\n",
                "long_sw_status.csv": "ticker,fundamental_status,sw_status,financial_health_score\nMCK,UNKNOWN,EXCLUDED,2\n",
                "short_borrow.csv": "ticker,status\n",
                "candidate_risk_news.csv": "ticker,candidate_type,risk_status,news_items\n",
                "entry_risk.csv": "ticker,candidate_type,entry_status,target_feasibility\n",
            }
            for name, content in csv_files.items():
                (data / name).write_text(content, encoding="utf-8")
            (data / "market_context.json").write_text(
                '{"status":"FULL","data_status":"FULL","session_date":"2026-11-20","market_regime":"RISK-OFF","symbols":{}}',
                encoding="utf-8",
            )
            statuses = {
                "technical_score_status.json": {"status": "FULL"},
                "long_fundamental_status.json": {"status": "PARTIAL", "unknown": 1, "errors": []},
                "long_sw_status.json": {"status": "FULL", "unknown": 0, "passed": 0, "excluded_sw": 1},
                "short_borrow_status.json": {"status": "PARTIAL", "unknown": 4},
                "candidate_risk_news_status.json": {"status": "FULL", "unknown": 0},
                "entry_risk_status.json": {"status": "FULL", "unknown": 0},
                "dsr_run_status.json": {},
            }
            import json
            for name, payload in statuses.items():
                (data / name).write_text(json.dumps(payload), encoding="utf-8")
            with patch.object(report, "DATA", data), patch.object(report, "ROOT", root):
                rendered, details = report.build_report()
            self.assertEqual(details["status"], "FULL")
            self.assertEqual(details["fundamental_unknown_excluded_by_sw"], ["MCK"])
            self.assertEqual(details["unresolved_fundamental_unknown"], [])
            self.assertIn("Fundamenteel ONBEKEND maar al uitgesloten door SW: MCK", rendered)

    def test_unknown_fundamentals_are_nonblocking_when_sw_does_not_exclude(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            data = root / "data"
            data.mkdir()
            files = {
                "technical_scores.csv": "ticker,score_status,long_score,close_completed,sma50,short_score,sma20,above_sma20_completed,above_sma50_completed\n",
                "ha_signals.csv": "ticker,ha_pivot_up,ha_pivot_down\n",
                "dsr_source_status.csv": "source,status,ticker_count,last_success_at,age_hours,detail\nManual,MANUAL,1,,,manual\n",
                "long_fundamentals.csv": "ticker,fundamental_status\nMCK,UNKNOWN\n",
                "long_sw_status.csv": "ticker,fundamental_status,sw_status,financial_health_score\nMCK,UNKNOWN,ONBEKEND_FUNDAMENTALS,\n",
                "short_borrow.csv": "ticker,status\n",
                "candidate_risk_news.csv": "ticker,candidate_type,risk_status,news_items\n",
                "entry_risk.csv": "ticker,candidate_type,entry_status,target_feasibility\n",
            }
            for name, content in files.items():
                (data / name).write_text(content, encoding="utf-8")
            (data / "market_context.json").write_text(
                '{"status":"FULL","data_status":"FULL","session_date":"2026-11-20","market_regime":"RISK-OFF","symbols":{}}',
                encoding="utf-8",
            )
            statuses = {
                "technical_score_status.json": {"status": "FULL"},
                "long_fundamental_status.json": {"status": "PARTIAL", "unknown": 1},
                "long_sw_status.json": {"status": "PARTIAL", "unknown": 1},
                "short_borrow_status.json": {"status": "PARTIAL", "unknown": 4},
                "candidate_risk_news_status.json": {"status": "FULL", "unknown": 0},
                "entry_risk_status.json": {"status": "FULL", "unknown": 0},
                "dsr_run_status.json": {},
            }
            import json
            for name, payload in statuses.items():
                (data / name).write_text(json.dumps(payload), encoding="utf-8")
            with patch.object(report, "DATA", data), patch.object(report, "ROOT", root):
                _, details = report.build_report()
            self.assertEqual(details["status"], "FULL")
            self.assertEqual(details["unresolved_fundamental_unknown"], ["MCK"])
            self.assertFalse(details["pending_components"])
            self.assertTrue(any("Long fundamentals" in item for item in details["non_blocking_components"]))
            self.assertTrue(any("Simply Wall St" in item for item in details["non_blocking_components"]))


    def test_stale_fundamental_fallback_is_nonblocking_but_not_approved(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            data = root / "data"
            data.mkdir()
            files = {
                "technical_scores.csv": "ticker,score_status,long_score,close_completed,sma50,short_score,sma20,above_sma20_completed,above_sma50_completed\n",
                "ha_signals.csv": "ticker,ha_pivot_up,ha_pivot_down\n",
                "dsr_source_status.csv": "source,status,ticker_count,last_success_at,age_hours,detail\nManual,MANUAL,1,,,manual\n",
                "long_fundamentals.csv": "ticker,fundamental_status\nMCK,UNKNOWN\n",
                "long_sw_status.csv": "ticker,fundamental_status,sw_status,financial_health_score\nMCK,UNKNOWN,EXCLUDED,2\n",
                "short_borrow.csv": "ticker,status\n",
                "candidate_risk_news.csv": "ticker,candidate_type,risk_status,news_items\n",
                "entry_risk.csv": "ticker,candidate_type,entry_status,target_feasibility\n",
            }
            for name, content in files.items():
                (data / name).write_text(content, encoding="utf-8")
            (data / "market_context.json").write_text(
                '{"status":"FULL","data_status":"FULL","session_date":"2026-11-20","market_regime":"RISK-OFF","symbols":{}}',
                encoding="utf-8",
            )
            statuses = {
                "technical_score_status.json": {"status": "FULL"},
                "long_fundamental_status.json": {"status": "PARTIAL", "data_status": "STALE_FALLBACK", "unknown": 1},
                "long_sw_status.json": {"status": "PARTIAL", "data_status": "STALE_FALLBACK", "unknown": 0},
                "short_borrow_status.json": {"status": "PARTIAL", "unknown": 4},
                "candidate_risk_news_status.json": {"status": "FULL", "unknown": 0},
                "entry_risk_status.json": {"status": "FULL", "unknown": 0},
                "dsr_run_status.json": {},
            }
            import json
            for name, payload in statuses.items():
                (data / name).write_text(json.dumps(payload), encoding="utf-8")
            with patch.object(report, "DATA", data), patch.object(report, "ROOT", root):
                _, details = report.build_report()
            self.assertEqual(details["status"], "FULL")
            self.assertEqual(details["long_fundamental_data_status"], "STALE_FALLBACK")
            self.assertFalse(details["pending_components"])
            self.assertTrue(any("STALE_FALLBACK" in item for item in details["non_blocking_components"]))


    def test_pivot_and_breakout_status_are_reported_separately(self):
        cells = report.pivot_audit_cells({
            "consolidation_pivot": 95,
            "consolidation_pivot_date": "2026-11-10",
            "consolidation_pivot_status": "OK",
            "breakout_reference_status": "BREAKOUT_BEVESTIGD",
            "breakout_reference_date": "2026-11-20",
            "breakout_reference_close": 100,
            "breakout_reference_ha_close": 96,
            "breakout_reference_volume": 1200,
        })
        self.assertEqual(cells, [95, "2026-11-10", "OK", "BREAKOUT_BEVESTIGD",
                                 "2026-11-20", 100, 96, 1200])


    def test_entry_risk_unknown_still_blocks_full_report(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            data = root / "data"
            data.mkdir()
            files = {
                "technical_scores.csv": "ticker,score_status,long_score,close_completed,sma50,short_score,sma20,above_sma20_completed,above_sma50_completed\n",
                "ha_signals.csv": "ticker,ha_pivot_up,ha_pivot_down\n",
                "dsr_source_status.csv": "source,status,ticker_count,last_success_at,age_hours,detail\nManual,MANUAL,1,,,manual\n",
                "long_fundamentals.csv": "ticker,fundamental_status\n",
                "long_sw_status.csv": "ticker,fundamental_status,sw_status\n",
                "short_borrow.csv": "ticker,status\n",
                "candidate_risk_news.csv": "ticker,candidate_type,risk_status,news_items\n",
                "entry_risk.csv": "ticker,candidate_type,entry_status,target_feasibility\n",
            }
            for name, content in files.items():
                (data / name).write_text(content, encoding="utf-8")
            (data / "market_context.json").write_text(
                '{"status":"FULL","data_status":"FULL","session_date":"2026-11-20","market_regime":"RISK-OFF","symbols":{}}',
                encoding="utf-8",
            )
            statuses = {
                "technical_score_status.json": {"status": "FULL"},
                "long_fundamental_status.json": {"status": "PARTIAL", "data_status": "STALE_FALLBACK", "unknown": 10},
                "long_sw_status.json": {"status": "PARTIAL", "data_status": "STALE_FALLBACK", "unknown": 10},
                "short_borrow_status.json": {"status": "PARTIAL", "unknown": 4},
                "candidate_risk_news_status.json": {"status": "PARTIAL", "unknown": 5},
                "entry_risk_status.json": {"status": "PARTIAL", "unknown": 3},
                "dsr_run_status.json": {},
            }
            import json
            for name, payload in statuses.items():
                (data / name).write_text(json.dumps(payload), encoding="utf-8")
            with patch.object(report, "DATA", data), patch.object(report, "ROOT", root):
                _, details = report.build_report()
            self.assertEqual(details["status"], "PARTIAL")
            self.assertTrue(any("Entry, HA-stop, risico%" in item for item in details["pending_components"]))
            self.assertTrue(details["non_blocking_components"])


    def test_missing_history_for_pivot_validation_still_blocks_full(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            data = root / "data"
            data.mkdir()
            files = {
                "technical_scores.csv": "ticker,score_status,long_score,close_completed,sma50,short_score,sma20,above_sma20_completed,above_sma50_completed\n",
                "ha_signals.csv": "ticker,ha_pivot_up,ha_pivot_down\n",
                "dsr_source_status.csv": "source,status,ticker_count,last_success_at,age_hours,detail\nManual,MANUAL,1,,,manual\n",
                "long_fundamentals.csv": "ticker,fundamental_status\n",
                "long_sw_status.csv": "ticker,fundamental_status,sw_status\n",
                "short_borrow.csv": "ticker,status\n",
                "candidate_risk_news.csv": "ticker,candidate_type,risk_status,news_items\n",
                "entry_risk.csv": "ticker,candidate_type,entry_status,target_feasibility\n",
            }
            for name, content in files.items():
                (data / name).write_text(content, encoding="utf-8")
            (data / "market_context.json").write_text(
                '{"status":"FULL","data_status":"FULL","session_date":"2026-11-20","market_regime":"RISK-OFF","symbols":{}}',
                encoding="utf-8",
            )
            statuses = {
                "technical_score_status.json": {"status": "FULL"},
                "long_fundamental_status.json": {"status": "PARTIAL", "data_status": "STALE_FALLBACK", "unknown": 10},
                "long_sw_status.json": {"status": "PARTIAL", "data_status": "STALE_FALLBACK", "unknown": 10},
                "short_borrow_status.json": {"status": "PARTIAL", "unknown": 4},
                "candidate_risk_news_status.json": {"status": "PARTIAL", "unknown": 2, "review_required": 3},
                "entry_risk_status.json": {"status": "FULL", "unknown": 0},
                "dsr_run_status.json": {},
            }
            import json
            for name, payload in statuses.items():
                (data / name).write_text(json.dumps(payload), encoding="utf-8")
            with patch.object(report, "DATA", data), patch.object(report, "ROOT", root):
                _, details = report.build_report()
            self.assertEqual(details["status"], "PARTIAL")
            self.assertTrue(any("Historische koersdata voor HA-pivotvalidatie" in item
                                for item in details["pending_components"]))


if __name__ == "__main__":
    unittest.main()
