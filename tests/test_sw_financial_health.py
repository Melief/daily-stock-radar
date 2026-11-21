"""Tests for manual Simply Wall St Financial Health verification."""
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from scripts import sw_financial_health as sw


class SwFinancialHealthTests(unittest.TestCase):
    def test_score_four_or_higher_passes_and_three_excludes(self):
        fundamentals = pd.DataFrame([
            {"ticker": "AAA", "fundamental_status": "PASS", "sources": "FV",
             "sector": "Technology", "industry": "Software", "technical_score": 4},
            {"ticker": "BBB", "fundamental_status": "PASS", "sources": "VYUS",
             "sector": "Technology", "industry": "Software", "technical_score": 3},
        ])
        verified = {
            "AAA": {"score": 4, "checked_at": "2026-11-20", "source_url": "https://simplywall.st/stocks/us/aaa"},
            "BBB": {"score": 3, "checked_at": "2026-11-20", "source_url": "https://simplywall.st/stocks/us/bbb"},
        }
        rows = sw.build_sw_rows(fundamentals, verified)
        self.assertEqual(rows[0]["sw_status"], "PASS")
        self.assertEqual(rows[1]["sw_status"], "EXCLUDED")

    def test_missing_score_remains_unknown(self):
        fundamentals = pd.DataFrame([{"ticker": "AAA", "fundamental_status": "PASS"}])
        rows = sw.build_sw_rows(fundamentals, {})
        self.assertEqual(rows[0]["sw_status"], "ONBEKEND")

    def test_fundamental_failure_is_not_sent_to_sw(self):
        fundamentals = pd.DataFrame([{"ticker": "AAA", "fundamental_status": "FAIL"}])
        rows = sw.build_sw_rows(fundamentals, {
            "AAA": {"score": 6, "checked_at": "2026-11-20", "source_url": "https://simplywall.st/x"}
        })
        self.assertEqual(rows[0]["sw_status"], "NIET_BEOORDEELD_FUNDAMENTEEL_UITGESLOTEN")
        self.assertEqual(rows[0]["financial_health_score"], "")

    def test_manual_input_requires_valid_score_date_and_official_host(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sw.csv"
            path.write_text(
                "ticker,financial_health_score,checked_at,source_url\n"
                "AAA,5,2026-11-20,https://simplywall.st/stocks/us/aaa\n"
                "BBB,7,2026-11-20,https://simplywall.st/stocks/us/bbb\n"
                "CCC,4,2026-11-20,https://example.com/ccc\n"
                "DDD,4,not-a-date,https://simplywall.st/stocks/us/ddd\n",
                encoding="utf-8",
            )
            data = sw.load_verified_scores(path)
            self.assertEqual(set(data), {"AAA"})


    def test_verified_sw_exclusion_applies_even_when_fundamentals_unknown(self):
        fundamentals = pd.DataFrame([
            {"ticker": "MCK", "fundamental_status": "UNKNOWN", "sources": "FV",
             "sector": "Healthcare", "industry": "Health Care Providers", "technical_score": 3}
        ])
        verified = {
            "MCK": {"score": 2, "checked_at": "2026-11-21",
                    "source_url": "https://simplywall.st/stocks/us/healthcare/nyse-mck/mckesson/health"}
        }
        row = sw.build_sw_rows(fundamentals, verified)[0]
        self.assertEqual(row["sw_status"], "EXCLUDED")
        self.assertEqual(row["financial_health_score"], 2)
        self.assertEqual(row["fundamental_status"], "UNKNOWN")

    def test_good_sw_score_does_not_hide_unknown_fundamentals(self):
        fundamentals = pd.DataFrame([{"ticker": "MCK", "fundamental_status": "UNKNOWN"}])
        verified = {
            "MCK": {"score": 5, "checked_at": "2026-11-21",
                    "source_url": "https://simplywall.st/stocks/us/healthcare/nyse-mck/mckesson/health"}
        }
        row = sw.build_sw_rows(fundamentals, verified)[0]
        self.assertEqual(row["sw_status"], "ONBEKEND_FUNDAMENTALS")
        self.assertEqual(row["financial_health_score"], 5)


    def test_stale_fundamentals_never_produce_sw_pass(self):
        fundamentals = pd.DataFrame([
            {"ticker": "AAA", "fundamental_status": "PASS"},
            {"ticker": "BBB", "fundamental_status": "UNKNOWN"},
        ])
        verified = {
            "AAA": {"score": 5, "checked_at": "2026-11-21", "source_url": "https://simplywall.st/a"},
            "BBB": {"score": 2, "checked_at": "2026-11-21", "source_url": "https://simplywall.st/b"},
        }
        rows = sw.build_sw_rows(fundamentals, verified, "STALE_FALLBACK")
        self.assertEqual(rows[0]["sw_status"], "ONBEKEND_FUNDAMENTALS")
        self.assertEqual(rows[1]["sw_status"], "EXCLUDED")


if __name__ == "__main__":
    unittest.main()
