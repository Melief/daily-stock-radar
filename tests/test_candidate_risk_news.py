"""Tests for candidate news parsing and raw Short risk metrics."""
import unittest
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

    def test_rejects_stale_price_risk_data(self):
        dates = pd.bdate_range(end="2026-11-19", periods=30)
        frame = pd.DataFrame({
            "Open": 10, "High": 11, "Low": 9, "Close": 10
        }, index=dates)
        with self.assertRaisesRegex(ValueError, "loopt achter"):
            rn.calculate_price_risk(frame, "2026-11-20")


if __name__ == "__main__":
    unittest.main()
