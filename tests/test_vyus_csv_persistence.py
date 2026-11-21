"""Unit tests for the scheduled VYUS CSV persistence."""
import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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


class VYUSMainTests(unittest.TestCase):
    def test_csv_is_persisted_before_sheets_post(self):
        tickers = [f"T{i:02d}" for i in range(25)]
        with (
            patch.dict("os.environ", {
                "VYUS_GS_WEBAPP_URL": "https://example.test",
                "VYUS_GS_SECRET": "test-secret",
            }),
            patch.object(vyus, "fetch_tickers", return_value=tickers),
            patch.object(vyus, "write_tickers_csv") as write_csv,
            patch.object(vyus, "urlopen") as urlopen,
        ):
            response = urlopen.return_value.__enter__.return_value
            response.read.return_value = b'{"success": true, "count": 25, "sheet": "VYUS"}'
            vyus.main()

        write_csv.assert_called_once_with(tickers)
        self.assertTrue(write_csv.call_args_list[0] is not None)
        urlopen.assert_called_once()


if __name__ == "__main__":
    unittest.main()
