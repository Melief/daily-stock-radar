"""Tests for the IBKR public FTP short-borrow parser."""
import tempfile
import unittest
from pathlib import Path

from scripts import short_borrow as sb


SAMPLE = """#BOF|2026.11.20|07:34:48
#SYM|CUR|NAME|CON|ISIN|REBATERATE|FEERATE|AVAILABLE|FIGI|
ABCD|USD|ABCD INC|123|US0000000001|-1.2500|2.5000|4000|BBG000000000|
ZERO|USD|ZERO INC|124|US0000000002|0.0000|0.0000|0|BBG000000001|
EURX|EUR|EURX INC|125|XX0000000003|-1.0000|1.0000|900|BBG000000002|
#EOF|3
"""


class ShortBorrowTests(unittest.TestCase):
    def test_parses_bof_and_usd_inventory(self):
        timestamp, data = sb.parse_ftp_payload(SAMPLE)
        self.assertEqual(timestamp.strftime("%Y-%m-%d"), "2026-11-20")
        self.assertEqual(data["ABCD"]["available_shares"], 4000)
        self.assertEqual(data["ABCD"]["fee_rate_pct"], 2.5)
        self.assertEqual(data["ZERO"]["available_shares"], 0)
        self.assertNotIn("EURX", data)

    def test_duplicate_ticker_is_not_silently_combined(self):
        duplicate = SAMPLE.replace(
            "#EOF|3",
            "ABCD|USD|ABCD CLASS B|126|US0000000004|-1.0|3.0|500|BBG000000004|\n#EOF|4",
        )
        _, data = sb.parse_ftp_payload(duplicate)
        self.assertTrue(data["ABCD"]["ambiguous"])
        self.assertEqual(data["ABCD"]["match_count"], 2)

    def test_rejects_missing_headers(self):
        with self.assertRaisesRegex(ValueError, "mist"):
            sb.parse_ftp_payload("ABCD|USD|x\n")

    def test_short_candidate_requires_score_and_sma_alignment(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "scores.csv"
            path.write_text(
                "ticker,score_status,short_score,sma20,sma50\n"
                "AAA,OK,4,90,100\n"
                "BBB,OK,4,110,100\n"
                "CCC,ONBEKEND,5,90,100\n"
                "DDD,OK,2,90,100\n",
                encoding="utf-8",
            )
            self.assertEqual(sb.qualified_short_candidates(path), ["AAA"])


if __name__ == "__main__":
    unittest.main()
