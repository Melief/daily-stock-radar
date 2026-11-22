"""Tests that TradingView sources are attempted independently."""
import unittest
import csv
import base64
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

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


    def test_standalone_screener_symbols_list_is_parsed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(tv, "DATA_DIR", root), patch.object(tv, "ROOT", root):
                output = tv.save_rows("Follow Thrue", ["NASDAQ:CRVL", "NASDAQ:PLMR"])
            content = output.read_text(encoding="utf-8-sig")
            self.assertIn("CRVL,NASDAQ,NASDAQ:CRVL", content)
            self.assertIn("PLMR,NASDAQ,NASDAQ:PLMR", content)

    def test_standalone_screener_raw_values_are_parsed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            rows = [{
                "id": "TickerUniversal",
                "rawValues": [
                    {"name": "CRVL", "exchange": "NASDAQ", "description": "CorVel Corp."},
                    {"name": "PLMR", "exchange": "NASDAQ", "description": "Palomar Holdings, Inc."},
                ],
            }]
            with patch.object(tv, "DATA_DIR", root), patch.object(tv, "ROOT", root):
                output = tv.save_rows("Follow Thrue", rows)
            with output.open(encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual([row["ticker"] for row in rows], ["CRVL", "PLMR"])
            self.assertEqual(rows[1]["description"], "Palomar Holdings, Inc.")


    def test_explicit_zero_result_screener_writes_valid_empty_csv(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(tv, "DATA_DIR", root), patch.object(tv, "ROOT", root):
                output = tv.save_rows("Simpel Monsters", {"totalCount": 0, "symbols": [], "data": []})
            with output.open(encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(rows, [])


    def test_login_restricted_screen_is_not_marked_as_success(self):
        message = (
            "Log in to see the results. "
            "This screen is using some filters for registered users only."
        )
        with self.assertRaisesRegex(RuntimeError, "verbergt screenerresultaten achter een login"):
            tv.ensure_results_visible("Simpel Monsters", message)

    def test_unrestricted_empty_screen_is_allowed(self):
        tv.ensure_results_visible("Simpel Monsters", "No symbols match your criteria")

    def test_login_banner_does_not_reject_captured_results(self):
        message = "Log in to see the results. This screen is using some filters for registered users only."
        tv.ensure_results_visible("Follow Thrue", message, has_results=True)


    def test_storage_state_secret_is_loaded_without_logging_contents(self):
        browser = MagicMock()
        state = {"cookies": [], "origins": []}
        encoded = base64.b64encode(json.dumps(state).encode("utf-8")).decode("ascii")
        with patch.dict(tv.os.environ, {"TRADINGVIEW_STORAGE_STATE_B64": encoded}):
            context = tv.create_authenticated_context(browser)
        browser.new_context.assert_called_once_with(
            storage_state=state, viewport={"width": 1600, "height": 1000}
        )
        self.assertIs(context, browser.new_context.return_value)

    def test_missing_storage_state_secret_uses_public_context(self):
        browser = MagicMock()
        with patch.dict(tv.os.environ, {}, clear=True):
            context = tv.create_authenticated_context(browser)
        browser.new_context.assert_called_once_with(viewport={"width": 1600, "height": 1000})
        self.assertIs(context, browser.new_context.return_value)


    def test_retrieve_screener_uses_authenticated_context_for_pages(self):
        import inspect
        source = inspect.getsource(tv.retrieve_screener)
        self.assertIn("context.new_page()", source)
        self.assertNotIn("browser.new_page()", source)


if __name__ == "__main__":
    unittest.main()
