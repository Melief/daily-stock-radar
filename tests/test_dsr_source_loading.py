"""Unit tests for DSR ticker-source validation and partial-source handling."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import ha_signals


class ReadSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(dir=ha_signals.ROOT)
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)

    def write(self, name: str, content: str) -> Path:
        path = self.root / name
        path.write_text(content, encoding="utf-8")
        return path

    def test_csv_ticker_header_is_case_insensitive(self):
        path = self.write("tickers.csv", "Ticker\nAAPL\nMSFT\n")
        self.assertEqual(ha_signals.read_source(path, "csv"), ["AAPL", "MSFT"])

    def test_csv_symbol_header_is_supported(self):
        path = self.write("symbols.csv", "Symbol\nNVDA\n")
        self.assertEqual(ha_signals.read_source(path, "csv"), ["NVDA"])

    def test_text_source_accepts_whitespace_comma_and_semicolon(self):
        path = self.write("tickers.txt", "aapl, msft; nvda\n")
        self.assertEqual(
            ha_signals.read_source(path, "text"),
            ["AAPL", "MSFT", "NVDA"],
        )

    def test_missing_source_is_rejected(self):
        with self.assertRaises(FileNotFoundError):
            ha_signals.read_source(self.root / "missing.csv", "csv")

    def test_empty_source_is_rejected(self):
        path = self.write("empty.csv", "")
        with self.assertRaisesRegex(ValueError, "leeg"):
            ha_signals.read_source(path, "csv")

    def test_csv_without_ticker_or_symbol_column_is_rejected(self):
        path = self.write("bad.csv", "Name,Price\nExample,10\n")
        with self.assertRaisesRegex(ValueError, "Ticker/Symbol"):
            ha_signals.read_source(path, "csv")

    def test_header_only_csv_is_rejected(self):
        path = self.write("header_only.csv", "Ticker\n")
        with self.assertRaisesRegex(ValueError, "geen tickers"):
            ha_signals.read_source(path, "csv")


class LoadUniverseTests(unittest.TestCase):
    def test_bad_source_does_not_block_valid_source(self):
        with tempfile.TemporaryDirectory(dir=ha_signals.ROOT) as temp:
            root = Path(temp)
            valid = root / "valid.csv"
            valid.write_text("Ticker\nAAPL\nMSFT\n", encoding="utf-8")
            missing = root / "missing.csv"

            configured_sources = [
                ("Broken source", missing, "csv"),
                ("Valid source", valid, "csv"),
            ]
            with patch.object(ha_signals, "SOURCES", configured_sources):
                tickers, counts, errors = ha_signals.load_universe()

            self.assertEqual(set(tickers), {"AAPL", "MSFT"})
            self.assertEqual(tickers["AAPL"], {"Valid source"})
            self.assertEqual(counts, {"Valid source": 2})
            self.assertIn("Broken source", errors)
            self.assertNotIn("Valid source", errors)


if __name__ == "__main__":
    unittest.main()
