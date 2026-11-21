"""Tests for DSR stop and 2R calculations."""
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

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
        within = er.calculate_entry_risk("LONG", 104, 95, 100, "2026-11-20", 1000000, consolidation_pivot_status="OK", current_ha_close=101)
        extended = er.calculate_entry_risk("LONG", 106, 95, 100, "2026-11-20", 1000000, consolidation_pivot_status="OK", current_ha_close=101)
        self.assertEqual(within["long_buy_zone_status"], "WITHIN_5PCT")
        self.assertEqual(extended["long_buy_zone_status"], "EXTENDED")

    def test_regular_close_above_pivot_does_not_confirm_without_ha_close(self):
        result = er.calculate_entry_risk("LONG", 104, 95, 100, "2026-11-20", 1800,
                                         consolidation_pivot_status="OK")
        self.assertEqual(result["breakout_reference_status"], "GEEN_BREAKOUT")
        self.assertEqual(result["long_buy_zone_status"], "NOT_BROKEN")

    def test_historical_breakout_that_falls_back_below_ha_pivot_is_not_active(self):
        result = er.calculate_entry_risk("LONG", 99, 95, 100, "2026-11-20", 1800,
                                         consolidation_pivot_status="OK",
                                         prior_breakout_date="2026-11-18",
                                         prior_breakout_close=102, prior_breakout_ha_close=101,
                                         current_ha_close=99)
        self.assertEqual(result["breakout_reference_status"], "BREAKOUT_TERUGGEVALLEN")
        self.assertEqual(result["long_buy_zone_status"], "NOT_BROKEN")

    def test_long_uses_earlier_confirmed_breakout_evidence(self):
        result = er.calculate_entry_risk(
            "LONG", 104, 95, 100, "2026-11-20", 1800,
            consolidation_pivot_status="OK",
            prior_breakout_date="2026-11-18",
            prior_breakout_close=102.5,
            prior_breakout_volume=3200, current_ha_close=101.5, prior_breakout_ha_close=102.8,
        )
        self.assertEqual(result["breakout_reference_status"], "BREAKOUT_BEVESTIGD")
        self.assertEqual(result["breakout_reference_date"], "2026-11-18")
        self.assertEqual(result["breakout_reference_close"], 102.5)
        self.assertEqual(result["breakout_reference_volume"], 3200)
        self.assertEqual(result["long_buy_zone_status"], "WITHIN_5PCT")

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

    def test_nan_prior_breakout_date_is_not_treated_as_confirmed_breakout(self):
        result = er.calculate_entry_risk(
            "LONG", 100, 95, 100, "2026-11-20", 1800,
            consolidation_pivot_status="OK",
            prior_breakout_date=float("nan"),
            prior_breakout_close=None,
            prior_breakout_volume=None,
        )
        self.assertEqual(result["breakout_reference_status"], "GEEN_BREAKOUT")
        self.assertEqual(result["breakout_reference_date"], "")
        self.assertEqual(result["breakout_reference_close"], "")
        self.assertEqual(result["breakout_reference_volume"], "")

    def test_missing_prior_breakout_values_do_not_crash_output_rounding(self):
        result = er.calculate_entry_risk(
            "LONG", 104, 95, 100, "2026-11-20", 1800,
            consolidation_pivot_status="OK",
            prior_breakout_date="2026-11-18",
            prior_breakout_close=None,
            prior_breakout_volume=None, current_ha_close=101, prior_breakout_ha_close=101.5,
        )
        self.assertEqual(result["breakout_reference_status"], "BREAKOUT_BEVESTIGD")
        self.assertEqual(result["breakout_reference_date"], "2026-11-18")
        self.assertEqual(result["breakout_reference_close"], "")
        self.assertEqual(result["breakout_reference_volume"], "")

    def test_missing_borrow_does_not_override_technical_entry_status(self):
        result = er.calculate_entry_risk("SHORT", 100, 105, 95, "2026-11-20", 1000,
                                         news_status="UNKNOWN", borrow_status="ONBEKEND",
                                         consolidation_pivot_status="OK", current_ha_close=94)
        self.assertEqual(result["breakout_reference_status"], "DOORBRAAK_BEVESTIGD")
        self.assertEqual(result["action"], "WACHTEN OP ACTUELE CONSOLIDATIEPIVOT")


    def test_entry_risk_build_rows_does_not_require_optional_borrow_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            technical = root / "technical_scores.csv"
            long_sw = root / "long_sw_status.csv"
            technical.write_text(
                "ticker,score_status,long_score,short_score,sma20,sma50\n",
                encoding="utf-8",
            )
            long_sw.write_text("ticker,fundamental_status,sw_status\n", encoding="utf-8")
            with patch.object(er, "TECHNICAL", technical), patch.object(er, "LONG_SW", long_sw), \
                 patch.object(er, "BORROW", root / "missing_borrow.csv"), \
                 patch.object(er, "RISK_NEWS", root / "missing_news.csv"):
                self.assertEqual(er.build_rows(), [])


if __name__ == "__main__":
    unittest.main()
