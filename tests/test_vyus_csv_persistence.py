"""Unit tests for the scheduled VYUS CSV persistence."""
import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts import import_vyus_holdings as vyus


class VYUSCsvTests(unittest.TestCase):
    def test_writes_exactly_25_unique_tickers_with_ticker_header(self):
        tickers = [f"T{i:02d}" for i in range(25)]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "vyus_tickers.csv"
            vyus.write_tickers_csv(tickers, output)
            with output.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.reader(handle))
        self.assertEqual(rows[0], ["ticker"])
        self.assertEqual([row[0] for row in rows[1:]], tickers)
        self.assertFalse(output.with_suffix(".csv.tmp").exists())

    def test_rejects_incomplete_or_duplicate_holdings_without_overwriting(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "vyus_tickers.csv"
            output.write_text("ticker\nOLD\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                vyus.write_tickers_csv(["AAPL"] * 25, output)
            self.assertEqual(output.read_text(encoding="utf-8"), "ticker\nOLD\n")


class VYUSFetchTests(unittest.TestCase):
    def test_fetch_uses_browser_headers_accepted_by_stockanalysis(self):
        html = "<table><tr><th>Symbol</th></tr>" + "".join(
            f"<tr><td>T{i:02d}</td></tr>" for i in range(25)
        ) + "</table>"
        response = MagicMock()
        response.__enter__.return_value.read.return_value = html.encode()
        with patch.object(vyus, "urlopen", return_value=response) as mocked:
            tickers = vyus.fetch_tickers()
        request = mocked.call_args.args[0]
        self.assertEqual(len(tickers), 25)
        self.assertIn("Chrome/126.0", request.get_header("User-agent"))
        self.assertEqual(request.get_header("Accept-language"), "en-US,en;q=0.9")


class VYUSMainTests(unittest.TestCase):
    def _environment(self):
        return patch.dict("os.environ", {
            "VYUS_GS_WEBAPP_URL": "https://example.test",
            "VYUS_GS_SECRET": "test-secret",
        })

    def test_csv_is_persisted_before_sheets_post(self):
        tickers = [f"T{i:02d}" for i in range(25)]
        events = []
        real_write = vyus.write_tickers_csv
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "vyus_tickers.csv"

            def persist(values):
                events.append("csv")
                real_write(values, output)

            response = MagicMock()
            response.__enter__.return_value.read.return_value = json.dumps({
                "success": True, "count": 25, "sheet": "VYUS"
            }).encode()

            def post(request, timeout):
                events.append("sheets")
                self.assertTrue(output.exists())
                return response

            with (
                self._environment(),
                patch.object(vyus, "fetch_tickers", return_value=tickers),
                patch.object(vyus, "write_tickers_csv", side_effect=persist),
                patch.object(vyus, "urlopen", side_effect=post),
            ):
                vyus.main()

            self.assertEqual(events, ["csv", "sheets"])
            with output.open(newline="", encoding="utf-8") as handle:
                self.assertEqual(len(list(csv.DictReader(handle))), 25)

    def test_validated_csv_is_written_even_when_sheets_credentials_are_missing(self):
        tickers = [f"T{i:02d}" for i in range(25)]
        real_write = vyus.write_tickers_csv
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "vyus_tickers.csv"
            with (
                patch.dict("os.environ", {}, clear=True),
                patch.object(vyus, "fetch_tickers", return_value=tickers),
                patch.object(vyus, "write_tickers_csv", side_effect=lambda values: real_write(values, output)),
            ):
                with self.assertRaisesRegex(RuntimeError, "CSV refreshed"):
                    vyus.main()
            with output.open(newline="", encoding="utf-8") as handle:
                self.assertEqual(len(list(csv.DictReader(handle))), 25)

    def test_validated_csv_remains_when_sheets_post_fails(self):
        tickers = [f"T{i:02d}" for i in range(25)]
        real_write = vyus.write_tickers_csv
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "vyus_tickers.csv"
            with (
                self._environment(),
                patch.object(vyus, "fetch_tickers", return_value=tickers),
                patch.object(vyus, "write_tickers_csv", side_effect=lambda values: real_write(values, output)),
                patch.object(vyus, "urlopen", side_effect=OSError("Sheets unavailable")),
            ):
                with self.assertRaisesRegex(RuntimeError, "Google Apps Script POST stage failed"):
                    vyus.main()

            with output.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual([row["ticker"] for row in rows], tickers)


if __name__ == "__main__":
    unittest.main()
