"""Tests for candidate news parsing and raw Short risk metrics."""
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from datetime import datetime, timezone

import pandas as pd

from scripts import candidate_risk_news as rn


class CandidateRiskNewsTests(unittest.TestCase):
    def test_event_keyword_flags(self):
        self.assertEqual(
            rn.event_flags("FDA clinical trial update and earnings guidance"),
            ["earnings", "guidance", "fda", "clinical", "trial"],
        )

    def test_missing_short_interest_metrics_remain_unknown(self):
        self.assertEqual(rn.derive_risk_status("CHECKED", [], False, True), "UNKNOWN")
        self.assertEqual(rn.derive_risk_status("NO_RESULTS", [], True, True), "NO_RESULTS")
        self.assertEqual(rn.derive_risk_status("CHECKED", [], True, True, False), "UNKNOWN")
        self.assertEqual(rn.derive_risk_status("CHECKED", ["fda"], True, True), "REVIEW")

    def test_google_news_rss_filters_old_items_and_extracts_source(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <rss><channel>
          <item><title>Company announces earnings guidance</title>
            <link>https://example.com/new</link>
            <pubDate>Fri, 20 Nov 2026 12:00:00 GMT</pubDate>
            <source>Example News</source></item>
          <item><title>Old article</title><link>https://example.com/old</link>
            <pubDate>Mon, 02 Nov 2026 12:00:00 GMT</pubDate><source>Old</source></item>
        </channel></rss>"""
        now = datetime(2026, 11, 21, 12, tzinfo=timezone.utc)
        items = rn.parse_google_news_rss(xml, now)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["source"], "Example News")
        self.assertEqual(items[0]["event_flags"], ["earnings", "guidance"])

    def test_news_results_must_match_company_or_ticker(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <rss><channel>
          <item><title>MarketAxess Holdings stock update</title>
            <link>https://example.com/unrelated</link>
            <pubDate>Fri, 20 Nov 2026 12:00:00 GMT</pubDate></item>
          <item><title>Cboe Global Markets announces earnings guidance</title>
            <link>https://example.com/relevant</link>
            <pubDate>Fri, 20 Nov 2026 12:00:00 GMT</pubDate></item>
        </channel></rss>"""
        now = datetime(2026, 11, 21, 12, tzinfo=timezone.utc)
        items = rn.parse_google_news_rss(xml, now, ["cboe"])
        self.assertEqual([item["url"] for item in items], ["https://example.com/relevant"])

    def test_earnings_date_uses_future_date_only(self):
        today = datetime(2026, 11, 21, tzinfo=timezone.utc)
        info = {"earningsDate": ["2026-09-09", "2026-12-15"]}
        self.assertEqual(rn._earnings_date(info, today), "2026-12-15")
        self.assertEqual(rn._earnings_date({"earningsDate": ["2026-09-09"]}, today), "")

    def test_short_price_risk_metrics_use_completed_session(self):
        dates = pd.bdate_range(end="2026-11-20", periods=30)
        close = [100 - i * 0.5 for i in range(30)]
        frame = pd.DataFrame({
            "Open": [value + 0.2 for value in close],
            "High": [value + 1.0 for value in close],
            "Low": [value - 1.0 for value in close],
            "Close": close,
        }, index=dates)
        result = rn.calculate_price_risk(frame, "2026-11-20")
        self.assertEqual(result["price_date"], "2026-11-20")
        self.assertGreater(result["atr14_pct"], 0)
        self.assertGreater(result["max_overnight_gap_20d_pct"], 0)
        self.assertLess(result["momentum_5d_pct"], 0)

    def test_history_extremes_require_252_sessions_for_52_week_high(self):
        dates = pd.bdate_range(end="2026-11-20", periods=260)
        frame = pd.DataFrame({
            "Open": [99 + i for i in range(260)],
            "High": [100 + i for i in range(260)],
            "Low": [98 + i for i in range(260)],
            "Close": [99.5 + i for i in range(260)],
        }, index=dates)
        result = rn.calculate_history_extremes(frame, "2026-11-20")
        self.assertEqual(result["history_extremes_status"], "FULL")
        self.assertEqual(result["high_52w"], 358)
        self.assertEqual(result["all_time_high"], 358)
        self.assertLess(result["distance_to_ath_pct"], 0)
        self.assertEqual(result["all_time_high_date"], "2026-11-19")

    def test_confirmed_stock_swing_support_and_resistance_are_returned(self):
        dates = pd.bdate_range(end="2026-11-20", periods=260)
        cycle = [100, 105, 110, 105, 100, 95, 100, 105, 110, 105]
        close = (cycle * 26)[:260]
        frame = pd.DataFrame({
            "Open": close,
            "High": [value + 1 for value in close],
            "Low": [value - 1 for value in close],
            "Close": close,
        }, index=dates)
        result = rn.calculate_history_extremes(frame, "2026-11-20")
        self.assertNotEqual(result["nearest_support"], "")
        self.assertNotEqual(result["nearest_resistance"], "")
        self.assertLess(result["nearest_support"], 105)
        self.assertGreater(result["nearest_resistance"], 105)

    def test_long_consolidation_pivot_uses_confirmed_swing_low_and_prior_range(self):
        dates = pd.bdate_range(end="2026-11-20", periods=22)
        lows = [10.0] * 22
        lows[8:13] = [8.0, 7.0, 4.0, 7.5, 8.0]
        highs = [value + 2 for value in lows]
        highs[10:21] = [12.0 + i * 0.1 for i in range(11)]
        frame = pd.DataFrame({
            "Open": [9.0] * 22, "High": highs, "Low": lows,
            "Close": [9.0] * 21 + [13.5],
        }, index=dates)
        result = rn.calculate_consolidation_pivot(frame, "2026-11-20", "LONG")
        self.assertEqual(result["consolidation_pivot_status"], "OK")
        self.assertEqual(result["consolidation_sessions"], 11)
        self.assertEqual(result["consolidation_pivot"], max(highs[10:21]))

    def test_regular_close_alone_does_not_confirm_ha_pivot_breakout(self):
        dates = pd.bdate_range(end="2026-11-20", periods=22)
        lows = [10.0] * 22
        lows[8:13] = [8.0, 7.0, 4.0, 7.5, 8.0]
        highs = [value + 2 for value in lows]
        highs[10:16] = [12.0, 12.1, 12.2, 12.3, 12.4, 14.0]
        closes = [9.0] * 22
        closes[15] = 13.0
        volumes = [1000] * 22
        volumes[15] = 2500
        frame = pd.DataFrame({
            "Open": [9.0] * 22, "High": highs, "Low": lows,
            "Close": closes, "Volume": volumes,
        }, index=dates)
        result = rn.calculate_consolidation_pivot(frame, "2026-11-20", "LONG")
        self.assertEqual(result["consolidation_pivot_status"], "OK")
        self.assertEqual(result["consolidation_pivot"], 14.0)
        self.assertEqual(result["prior_breakout_date"], "")
        self.assertEqual(result["prior_breakout_close"], "")
        self.assertEqual(result["prior_breakout_volume"], "")

    def test_short_consolidation_pivot_is_mirrored(self):
        dates = pd.bdate_range(end="2026-11-20", periods=22)
        highs = [12.0] * 22
        highs[8:13] = [14.0, 15.0, 18.0, 15.5, 15.0]
        lows = [value - 2 for value in highs]
        lows[10:21] = [8.0 - i * 0.1 for i in range(11)]
        frame = pd.DataFrame({
            "Open": [10.0] * 22, "High": highs, "Low": lows,
            "Close": [10.0] * 21 + [6.5],
        }, index=dates)
        result = rn.calculate_consolidation_pivot(frame, "2026-11-20", "SHORT")
        self.assertEqual(result["consolidation_pivot_status"], "OK")
        self.assertEqual(result["consolidation_sessions"], 11)
        self.assertEqual(result["consolidation_pivot"], min(lows[10:21]))

    def test_consolidation_pivot_requires_completed_current_session(self):
        dates = pd.bdate_range(end="2026-11-19", periods=22)
        frame = pd.DataFrame({
            "Open": 10.0, "High": 11.0, "Low": 9.0, "Close": 10.0
        }, index=dates)
        with self.assertRaisesRegex(ValueError, "geen actuele voltooide"):
            rn.calculate_consolidation_pivot(frame, "2026-11-20", "LONG")

    def test_short_history_keeps_ath_but_52_week_high_unknown(self):
        dates = pd.bdate_range(end="2026-11-20", periods=30)
        frame = pd.DataFrame({
            "Open": 10, "High": 12, "Low": 9, "Close": 11
        }, index=dates)
        result = rn.calculate_history_extremes(frame, "2026-11-20")
        self.assertEqual(result["history_extremes_status"], "PARTIAL")
        self.assertEqual(result["all_time_high"], 12)
        self.assertEqual(result["high_52w"], "")

    def test_incomplete_current_session_is_excluded(self):
        dates = pd.bdate_range(end="2026-11-21", periods=31)
        frame = pd.DataFrame({
            "Open": [100 + i for i in range(31)],
            "High": [102 + i for i in range(31)],
            "Low": [99 + i for i in range(31)],
            "Close": [101 + i for i in range(31)],
        }, index=dates)
        risk = rn.calculate_price_risk(frame, "2026-11-20")
        extremes = rn.calculate_history_extremes(frame, "2026-11-20")
        self.assertEqual(risk["price_date"], "2026-11-20")
        self.assertEqual(extremes["history_date"], "2026-11-20")

    def test_rejects_stale_price_risk_data(self):
        dates = pd.bdate_range(end="2026-11-19", periods=30)
        frame = pd.DataFrame({
            "Open": 10, "High": 11, "Low": 9, "Close": 10
        }, index=dates)
        with self.assertRaisesRegex(ValueError, "loopt achter"):
            rn.calculate_price_risk(frame, "2026-11-20")


    def test_flat_history_returns_known_no_valid_pivot_not_missing_data(self):
        dates = pd.bdate_range(end="2026-11-20", periods=22)
        frame = pd.DataFrame({
            "Open": [10.0] * 22, "High": [10.5] * 22,
            "Low": [9.5] * 22, "Close": [10.0] * 22,
            "Volume": [1000] * 22,
        }, index=dates)
        result = rn.calculate_consolidation_pivot(frame, "2026-11-20", "LONG")
        self.assertEqual(result["consolidation_pivot_status"], "GEEN_GELDIGE_PIVOT")
        self.assertEqual(result["consolidation_pivot"], "")
        self.assertNotEqual(result["current_ha_close"], "")


    def test_optional_news_and_risk_unknowns_are_counted_without_hiding_history_status(self):
        results = [
            {"candidate_type": "LONG", "ticker": "AAA", "_history_ok": True,
             "_pivot_ok": True, "risk_status": "UNKNOWN", "news_status": "UNKNOWN", "error": ""},
            {"candidate_type": "SHORT", "ticker": "BBB", "_history_ok": True,
             "_pivot_ok": True, "risk_status": "REVIEW", "news_status": "CHECKED", "error": ""},
        ]
        status = rn.summarise_results(results, candidate_count=2)
        self.assertEqual(status["status"], "FULL")
        self.assertEqual(status["status_scope"], "HISTORICAL_PRICE_AND_PIVOT")
        self.assertEqual(status["history_pivot_unknown"], 0)
        self.assertEqual(status["risk_unknown"], 1)
        self.assertEqual(status["news_unknown"], 1)
        self.assertEqual(status["review_required"], 1)

    def test_missing_pivot_history_keeps_historical_component_partial(self):
        results = [
            {"candidate_type": "LONG", "ticker": "AAA", "_history_ok": True,
             "_pivot_ok": False, "risk_status": "CHECKED", "news_status": "CHECKED", "error": ""},
        ]
        status = rn.summarise_results(results, candidate_count=1)
        self.assertEqual(status["status"], "PARTIAL")
        self.assertEqual(status["history_pivot_unknown"], 1)


    def test_short_score_three_is_checked_even_without_borrow_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            technical = root / "technical_scores.csv"
            long_sw = root / "long_sw_status.csv"
            technical.write_text(
                "ticker,score_status,short_score,sma20,sma50,score_date,sector,industry\n"
                "ABC,OK,3,90,100,2026-11-20,Technology,Software\n",
                encoding="utf-8",
            )
            long_sw.write_text("ticker,fundamental_status,sw_status\n", encoding="utf-8")
            missing_borrow = root / "short_borrow.csv"
            with patch.object(rn, "TECHNICAL", technical), patch.object(rn, "LONG_SW", long_sw), patch.object(rn, "BORROW", missing_borrow):
                candidates = rn.load_candidates()
            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0]["ticker"], "ABC")
            self.assertEqual(candidates[0]["candidate_type"], "SHORT")
            self.assertEqual(candidates[0]["technical_score"], 3)
            self.assertEqual(candidates[0]["borrow_status"], "ONBEKEND")


if __name__ == "__main__":
    unittest.main()
