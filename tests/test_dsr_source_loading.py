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

    def test_all_sources_unavailable_persist_diagnostics(self):
        with tempfile.TemporaryDirectory(dir=ha_signals.ROOT) as temp:
            root = Path(temp)
            configured_sources = [
                ("Missing A", root / "missing_a.csv", "csv"),
                ("Missing B", root / "missing_b.csv", "csv"),
            ]
            signals_out = root / "ha_signals.csv"
            coverage_out = root / "ha_source_coverage.csv"
            with (
                patch.object(ha_signals, "SOURCES", configured_sources),
                patch.object(ha_signals, "OUT", signals_out),
                patch.object(ha_signals, "COVERAGE_OUT", coverage_out),
            ):
                self.assertEqual(ha_signals.main(), 1)

            self.assertTrue(signals_out.exists())
            self.assertTrue(coverage_out.exists())
            import pandas as pd
            coverage = pd.read_csv(coverage_out)
            self.assertEqual(set(coverage["source"]), {"Missing A", "Missing B"})
            self.assertTrue(coverage["ha_status"].str.startswith("BRONFOUT:").all())

    def test_unknown_automatic_source_is_included_only_as_partial_fallback(self):
        with tempfile.TemporaryDirectory(dir=ha_signals.ROOT) as temp:
            root = Path(temp)
            source = root / "auto.csv"
            source.write_text("Ticker\nAAPL\n", encoding="utf-8")
            with (
                patch.object(ha_signals, "SOURCES", [("Auto source", source, "csv")]),
                patch.object(ha_signals, "SOURCE_METADATA", {
                    "Auto source": {"id": "auto_source", "refresh_mode": "automatic", "max_age_hours": 24}
                }),
                patch.object(ha_signals, "STATUS_DIR", root / "statuses"),
            ):
                tickers, counts, errors, warnings, status_rows = ha_signals.load_universe(include_status=True)

            self.assertEqual(set(tickers), {"AAPL"})
            self.assertEqual(counts, {"Auto source": 1})
            self.assertFalse(errors)
            self.assertIn("Auto source", warnings)
            self.assertEqual(status_rows[0]["status"], "UNKNOWN")
            self.assertTrue(status_rows[0]["included"])

    def test_expired_automatic_source_is_excluded_from_universe(self):
        from datetime import datetime, timedelta, timezone
        from scripts.source_status import record_status

        with tempfile.TemporaryDirectory(dir=ha_signals.ROOT) as temp:
            root = Path(temp)
            source = root / "auto.csv"
            source.write_text("Ticker\nAAPL\n", encoding="utf-8")
            status_dir = root / "statuses"
            now = datetime.now(timezone.utc)
            record_status("auto_source", "success", status_dir=status_dir, now=now - timedelta(hours=30))
            with (
                patch.object(ha_signals, "SOURCES", [("Auto source", source, "csv")]),
                patch.object(ha_signals, "SOURCE_METADATA", {
                    "Auto source": {"id": "auto_source", "refresh_mode": "automatic", "max_age_hours": 24}
                }),
                patch.object(ha_signals, "STATUS_DIR", status_dir),
            ):
                tickers, counts, errors, warnings, status_rows = ha_signals.load_universe(include_status=True)

            self.assertFalse(tickers)
            self.assertFalse(counts)
            self.assertIn("Auto source", errors)
            self.assertEqual(status_rows[0]["status"], "STALE")
            self.assertFalse(status_rows[0]["included"])



class DSRRunStatusTests(unittest.TestCase):
    def test_source_and_analysis_completeness_are_reported_separately(self):
        import json

        with tempfile.TemporaryDirectory(dir=ha_signals.ROOT) as temp:
            output = Path(temp) / "dsr_run_status.json"
            with patch.object(ha_signals, "RUN_STATUS_OUT", output):
                ha_signals.write_run_status(
                    "PARTIAL",
                    [{"source": "Finviz", "status": "STALE_FALLBACK"}],
                    4,
                    {},
                    {"Finviz": "STALE_FALLBACK"},
                    missing_rows=0,
                    unknown_tickers=2,
                )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(payload["status"], "PARTIAL")
        self.assertEqual(payload["source_status"], "PARTIAL")
        self.assertEqual(payload["analysis_status"], "PARTIAL")
        self.assertEqual(payload["unknown_market_data_tickers"], 2)


if __name__ == "__main__":
    unittest.main()
