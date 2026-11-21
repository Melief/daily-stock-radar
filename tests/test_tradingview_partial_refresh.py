"""Tests that TradingView sources are attempted independently."""
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from scripts import update_tradingview_screeners as tv


class TradingViewPartialRefreshTests(unittest.TestCase):
    def test_second_screener_is_attempted_when_first_fails(self):
        attempted = []

        def retrieve(browser, label, url):
            attempted.append(label)
            if label == "Simpel Monsters":
                raise RuntimeError("first source unavailable")

        with patch.object(tv, "retrieve_screener", side_effect=retrieve):
            with self.assertRaisesRegex(RuntimeError, "gedeeltelijk mislukt"):
                tv.retrieve_all_screeners(object(), [
                    ("Simpel Monsters", "https://example.test/first"),
                    ("Follow Thrue", "https://example.test/second"),
                ])

        self.assertEqual(attempted, ["Simpel Monsters", "Follow Thrue"])


    def test_unrecognized_rows_do_not_overwrite_last_valid_csv(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            output = root / "simpel_monsters_tickers.csv"
            previous = "ticker,exchange,symbol,description,retrieved_at\nEPAM,NYSE,NYSE:EPAM,Technology services,2026-11-08T08:45:45+01:00\n"
            output.write_text(previous, encoding="utf-8")
            with patch.object(tv, "DATA_DIR", root):
                with self.assertRaisesRegex(RuntimeError, "geen herkenbare tickers"):
                    tv.save_rows("Simpel Monsters", [{"fields": ["name", "exchange"]}])
            self.assertEqual(output.read_text(encoding="utf-8"), previous)

    def test_legacy_symbol_rows_are_written_with_valid_ticker(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(tv, "DATA_DIR", root), patch.object(tv, "ROOT", root):
                output = tv.save_rows("Follow Thrue", [
                    {"s": "NASDAQ:PGNY", "d": ["PGNY", "StrongBuy"]}
                ])
            content = output.read_text(encoding="utf-8-sig")
            self.assertIn("PGNY,NASDAQ,NASDAQ:PGNY", content)


if __name__ == "__main__":
    unittest.main()
