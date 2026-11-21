"""Tests for Yahoo fundamental-data completeness and safe fallback."""
import unittest
import pandas as pd

from scripts import long_fundamental_screen as lf


class LongFundamentalFallbackTests(unittest.TestCase):
    def test_empty_yahoo_info_is_not_accepted_as_current_data(self):
        self.assertFalse(lf.has_usable_fundamental_data({}))
        self.assertTrue(lf.has_usable_fundamental_data({"marketCap": 5_000_000_000}))

    def test_stale_fallback_preserves_last_good_values_and_adds_new_unknowns(self):
        candidates = pd.DataFrame([
            {"ticker": "AAA", "sources": "FV", "sector": "Tech", "industry": "Software",
             "long_score": 4, "score_date": "2026-11-21"},
            {"ticker": "BBB", "sources": "Blue Sky", "sector": "Health", "industry": "Services",
             "long_score": 3, "score_date": "2026-11-21"},
        ])
        previous = [{
            "ticker": "AAA", "sources": "FV", "sector": "Tech", "industry": "Software",
            "technical_score": 4, "score_date": "2026-11-20", "fundamental_status": "PASS",
            "checks": '{"roe":"PASS"}', "market_cap": 5_000_000_000,
            "checked_at": "2026-11-20T12:00:00+00:00",
            "data_source": "Yahoo Finance quoteSummary", "error": "",
        }]
        rows = lf.build_stale_fallback_rows(
            candidates, previous, "2026-11-21T12:00:00+00:00", "No current Yahoo data"
        )
        self.assertEqual(rows[0]["fundamental_status"], "PASS")
        self.assertEqual(rows[0]["market_cap"], 5_000_000_000)
        self.assertIn("STALE_FALLBACK", rows[0]["data_source"])
        self.assertEqual(rows[1]["fundamental_status"], "UNKNOWN")
        self.assertEqual(rows[1]["checked_at"], "2026-11-21T12:00:00+00:00")


if __name__ == "__main__":
    unittest.main()

# Regression coverage for Yahoo quoteSummary outages and stale fallback safety.
