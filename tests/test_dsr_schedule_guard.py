"""Tests for DST-safe Amsterdam scheduling."""
import unittest

from scripts.dsr_schedule_guard import should_run


class DsrScheduleGuardTests(unittest.TestCase):
    def test_summer_cron_runs_at_0400_amsterdam(self):
        self.assertTrue(should_run("schedule", "0 2 * * 1-5", "+0200"))

    def test_winter_cron_runs_at_0400_amsterdam(self):
        self.assertTrue(should_run("schedule", "0 3 * * 1-5", "+0100"))

    def test_vyus_cron_runs_at_0345_amsterdam(self):
        self.assertTrue(should_run("schedule", "45 1 * * 1-5", "+0200"))
        self.assertTrue(should_run("schedule", "45 2 * * 1-5", "+0100"))

    def test_wrong_cron_offset_pair_is_skipped(self):
        self.assertFalse(should_run("schedule", "0 2 * * 1-5", "+0100"))
        self.assertFalse(should_run("schedule", "0 3 * * 1-5", "+0200"))

    def test_upstream_workflow_runs_only_after_success(self):
        self.assertTrue(should_run("workflow_run", "", "+0100", "success"))
        self.assertFalse(should_run("workflow_run", "", "+0100", "failure"))
        self.assertFalse(should_run("workflow_run", "", "+0100", "cancelled"))
        self.assertFalse(should_run("workflow_run", "", "+0100"))

    def test_dispatch_and_push_events_are_not_blocked(self):
        self.assertTrue(should_run("workflow_dispatch", "", "+0200"))
        self.assertTrue(should_run("push", "", "+0100"))

    def test_intraday_cron_runs_in_both_amsterdam_offsets(self):
        self.assertTrue(should_run("schedule", "0 14-21 * * 1-5", "+0100"))
        self.assertTrue(should_run("schedule", "0 14-21 * * 1-5", "+0200"))


if __name__ == "__main__":
    unittest.main()
