"""Tests for independent TradingView source retrieval."""

import unittest
from unittest.mock import patch

from scripts import update_tradingview_screeners as tradingview


class RetrieveAllScreenersTests(unittest.TestCase):
    def test_second_source_is_attempted_when_first_source_fails(self):
        screeners = [
            ("Simpel Monsters", "https://example.test/first"),
            ("Follow Thrue", "https://example.test/second"),
        ]
        browser = object()
        with patch.object(
            tradingview,
            "retrieve_screener",
            side_effect=[RuntimeError("first source unavailable"), None],
        ) as retrieve:
            with self.assertRaisesRegex(RuntimeError, "Simpel Monsters"):
                tradingview.retrieve_all_screeners(browser, screeners)

        self.assertEqual(retrieve.call_count, 2)
        self.assertEqual(
            [args[1:] for args, _ in retrieve.call_args_list],
            [
                ("Simpel Monsters", "https://example.test/first"),
                ("Follow Thrue", "https://example.test/second"),
            ],
        )
        self.assertTrue(all(args[0] is browser for args, _ in retrieve.call_args_list))

    def test_successful_sources_do_not_raise(self):
        screeners = [
            ("Simpel Monsters", "https://example.test/first"),
            ("Follow Thrue", "https://example.test/second"),
        ]
        browser = object()
        with patch.object(tradingview, "retrieve_screener") as retrieve:
            tradingview.retrieve_all_screeners(browser, screeners)

        self.assertEqual(retrieve.call_count, 2)
        self.assertEqual(
            [args[1:] for args, _ in retrieve.call_args_list],
            [
                ("Simpel Monsters", "https://example.test/first"),
                ("Follow Thrue", "https://example.test/second"),
            ],
        )
        self.assertTrue(all(args[0] is browser for args, _ in retrieve.call_args_list))


if __name__ == "__main__":
    unittest.main()
