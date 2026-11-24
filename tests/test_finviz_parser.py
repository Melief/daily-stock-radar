"""Tests for Finviz export parsing and valid empty screener results."""

import unittest

from scripts.test_finviz import parse_export


class FinvizParserTests(unittest.TestCase):
    def test_explicit_empty_screener_result_is_valid(self):
        html = (
            "<!doctype html><html><head><title>Stock Screener</title></head>"
            "<body>No stocks match the current screen.</body></html>"
        )
        self.assertEqual(parse_export(html), [])

    def test_finviz_elite_html_is_not_treated_as_empty(self):
        html = (
            "<!doctype html><html><head><title>Finviz Elite</title></head>"
            "<body>Upgrade to Finviz Elite</body></html>"
        )
        with self.assertRaisesRegex(ValueError, "Finviz returned HTML"):
            parse_export(html)

    def test_valid_csv_tickers_are_parsed(self):
        self.assertEqual(parse_export("Ticker\nAAPL\nMSFT\n"), ["AAPL", "MSFT"])


if __name__ == "__main__":
    unittest.main()
