"""Tests for candidate session-date alignment."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import candidate_risk_news as rn


class CandidateSessionDateTests(unittest.TestCase):
    def test_long_candidate_uses_technical_score_session_date(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            technical = root / "technical.csv"
            long_sw = root / "long_sw.csv"
            borrow = root / "borrow.csv"
            technical.write_text(
                "ticker,score_status,short_score,sma20,sma50,score_date,sector,industry\n"
                "AAA,OK,1,110,100,2026-11-20,Technology,Software\n",
                encoding="utf-8",
            )
            long_sw.write_text(
                "ticker,fundamental_status,sw_status,sector,industry,technical_score,sources\n"
                "AAA,PASS,PASS,Technology,Software,4,FV\n",
                encoding="utf-8",
            )
            borrow.write_text("ticker,status,available_shares,fee_rate_pct\n", encoding="utf-8")
            with patch.object(rn, "TECHNICAL", technical), patch.object(rn, "LONG_SW", long_sw), \
                 patch.object(rn, "BORROW", borrow):
                candidates = rn.load_candidates()
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["candidate_type"], "LONG")
        self.assertEqual(candidates[0]["score_date"], "2026-11-20")


if __name__ == "__main__":
    unittest.main()
