import unittest

from scripts.selection_rules import is_qualified_short_candidate


class SelectionRuleTests(unittest.TestCase):
    def valid_row(self):
        return {
            "score_status": "OK",
            "short_score": 4,
            "sma20": 90,
            "sma50": 100,
            "above_sma20_completed": False,
            "above_sma50_completed": False,
        }

    def test_short_requires_close_below_both_smas_and_sma20_below_sma50(self):
        self.assertTrue(is_qualified_short_candidate(self.valid_row()))

    def test_short_rejects_close_above_either_sma(self):
        row = self.valid_row()
        row["above_sma20_completed"] = True
        self.assertFalse(is_qualified_short_candidate(row))
        row = self.valid_row()
        row["above_sma50_completed"] = True
        self.assertFalse(is_qualified_short_candidate(row))

    def test_unknown_sma_position_fails_closed(self):
        row = self.valid_row()
        row["above_sma20_completed"] = ""
        self.assertFalse(is_qualified_short_candidate(row))

    def test_short_requires_bearish_sma_alignment(self):
        row = self.valid_row()
        row["sma20"] = 101
        self.assertFalse(is_qualified_short_candidate(row))

    def test_minimum_score_can_be_raised_for_news_checks(self):
        row = self.valid_row()
        row["short_score"] = 3
        self.assertTrue(is_qualified_short_candidate(row))
        self.assertFalse(is_qualified_short_candidate(row, min_score=4))


if __name__ == "__main__":
    unittest.main()
