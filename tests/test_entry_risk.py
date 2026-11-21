"""Tests for DSR stop and 2R calculations."""
import unittest

from scripts import entry_risk as er


class EntryRiskTests(unittest.TestCase):
    def test_long_stop_risk_and_2r_target(self):
        result = er.calculate_entry_risk("LONG", 100, 95, 102, "2026-11-20", 1000000, consolidation_pivot_status="OK")
        self.assertEqual(result["risk_per_share"], 5)
        self.assertEqual(result["risk_pct"], 5)
        self.assertEqual(result["target_2r"], 110)
        self.assertEqual(result["breakout_reference_status"], "GEEN_BREAKOUT")
        self.assertEqual(result["action"], "WACHTEN OP ACTUELE CONSOLIDATIEPIVOT")

    def test_long_buy_zone_is_limited_to_five_percent_above_reference(self):
        within = er.calculate_entry_risk("LONG", 104, 95, 100, "2026-11-20", 1000000, consolidation_pivot_status="OK")
        extended = er.calculate_entry_risk("LONG", 106, 95, 100, "2026-11-20", 1000000, consolidation_pivot_status="OK")
        self.assertEqual(within["long_buy_zone_status"], "WITHIN_5PCT")
        self.assertEqual(extended["long_buy_zone_status"], "EXTENDED")

    def test_short_stop_risk_and_2r_target(self):
        result = er.calculate_entry_risk("SHORT", 100, 105, 95, "2026-11-20", 1000000,
                                         news_status="CHECKED", borrow_status="AVAILABLE", consolidation_pivot_status="OK")
        self.assertEqual(result["risk_per_share"], 5)
        self.assertEqual(result["risk_pct"], 5)
        self.assertEqual(result["target_2r"], 90)
        self.assertEqual(result["breakout_reference_status"], "GEEN_DOORBRAAK")
        self.assertEqual(result["action"], "WACHTEN OP ACTUELE CONSOLIDATIEPIVOT")

    def test_long_2r_target_is_compared_with_confirmed_resistance(self):
        result = er.calculate_entry_risk(
            "LONG", 100, 95, 102, "2026-11-20", 1000000,
            news_status="CHECKED", nearest_resistance=108, consolidation_pivot_status="OK"
        )
        self.assertEqual(result["target_2r"], 110)
        self.assertEqual(result["target_feasibility"], "2R_DOEL_BOVEN_WEERSTAND")

    def test_short_2r_target_is_compared_with_confirmed_support(self):
        result = er.calculate_entry_risk(
            "SHORT", 100, 105, 95, "2026-11-20", 1000000,
            news_status="CHECKED", borrow_status="AVAILABLE", nearest_support=92, consolidation_pivot_status="OK"
        )
        self.assertEqual(result["target_2r"], 90)
        self.assertEqual(result["target_feasibility"], "2R_DOEL_ONDER_STEUN")

    def test_missing_swing_level_keeps_target_feasibility_unknown(self):
        result = er.calculate_entry_risk("LONG", 100, 95, 102, "2026-11-20", 1000000, consolidation_pivot_status="OK")
        self.assertEqual(result["target_feasibility"], "ONBEKEND")

    def test_invalid_stop_is_not_used(self):
        result = er.calculate_entry_risk("LONG", 100, 105, 110, "2026-11-20", 1000)
        self.assertEqual(result["entry_status"], "ONGELDIGE_STOP")
        self.assertEqual(result["target_2r"], "")

    def test_missing_stop_remains_unknown(self):
        result = er.calculate_entry_risk("SHORT", 100, None, 90, "2026-11-20", 1000)
        self.assertEqual(result["entry_status"], "ONBEKEND_STOP_OF_ENTRY")
        self.assertEqual(result["action"], "WACHTEN OP BEVESTIGING")

    def test_short_without_borrow_never_gets_entry_action(self):
        result = er.calculate_entry_risk("SHORT", 100, 105, 95, "2026-11-20", 1000,
                                         news_status="CHECKED", borrow_status="ONBEKEND")
        self.assertEqual(result["action"], "GEEN BEVESTIGDE BORROW")


if __name__ == "__main__":
    unittest.main()
