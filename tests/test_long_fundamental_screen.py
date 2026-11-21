"""Tests for the DSR Long fundamental checks."""
import tempfile
import unittest
from pathlib import Path

from scripts import long_fundamental_screen as lf


class LongFundamentalTests(unittest.TestCase):
    def passing_info(self):
        return {
            "marketCap": 3_000_000_000,
            "averageVolume": 800_000,
            "operatingMargins": 0.15,
            "returnOnEquity": 0.12,
            "revenueGrowth": 0.08,
            "debtToEquity": 50.0,
        }

    def test_all_fundamental_checks_pass(self):
        result = lf.evaluate_fundamentals(self.passing_info(), "Technology", "Software")
        self.assertEqual(result["fundamental_status"], "PASS")
        self.assertEqual(result["debt_to_equity_ratio"], 0.5)

    def test_missing_value_is_unknown_not_pass(self):
        info = self.passing_info()
        info.pop("returnOnEquity")
        result = lf.evaluate_fundamentals(info, "Technology", "Software")
        self.assertEqual(result["checks"]["roe"], "UNKNOWN")
        self.assertEqual(result["fundamental_status"], "UNKNOWN")

    def test_confirmed_failure_excludes_candidate(self):
        info = self.passing_info()
        info["marketCap"] = 1_000_000_000
        result = lf.evaluate_fundamentals(info, "Technology", "Software")
        self.assertEqual(result["checks"]["market_cap"], "FAIL")
        self.assertEqual(result["fundamental_status"], "FAIL")

    def test_debt_equity_is_not_applied_to_financial_sector(self):
        info = self.passing_info()
        info["debtToEquity"] = 450.0
        result = lf.evaluate_fundamentals(info, "Financial Services", "Insurance")
        self.assertEqual(result["checks"]["debt_to_equity"], "NVT")
        self.assertEqual(result["fundamental_status"], "PASS")

    def test_biotech_is_flagged_for_review_not_automatically_excluded(self):
        result = lf.evaluate_fundamentals(self.passing_info(), "Healthcare", "Biotechnology")
        self.assertEqual(result["biotech_clinical_risk_review"], "REVIEW")
        drug_maker = lf.evaluate_fundamentals(self.passing_info(), "Healthcare", "Drug Manufacturers - Specialty & Generic")
        self.assertEqual(drug_maker["biotech_clinical_risk_review"], "REVIEW")
        self.assertEqual(result["fundamental_status"], "PASS")

    def test_candidate_requires_technical_score_and_close_above_sma50(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "scores.csv"
            path.write_text(
                "ticker,score_status,long_score,close_completed,sma50,sources,sector,industry,score_date\n"
                "AAA,OK,4,110,100,FV,Technology,Software,2026-11-20\n"
                "BBB,OK,4,90,100,VYUS,Technology,Software,2026-11-20\n"
                "CCC,ONBEKEND,5,110,100,VYUS,Technology,Software,2026-11-20\n"
                "DDD,OK,2,110,100,VYUS,Technology,Software,2026-11-20\n",
                encoding="utf-8",
            )
            self.assertEqual(lf.load_candidates(path)["ticker"].tolist(), ["AAA"])


if __name__ == "__main__":
    unittest.main()
