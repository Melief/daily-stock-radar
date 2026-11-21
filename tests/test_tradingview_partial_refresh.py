"""Tests that TradingView sources are attempted independently."""
import unittest
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


if __name__ == "__main__":
    unittest.main()
