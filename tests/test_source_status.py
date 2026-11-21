"""Tests for per-source refresh status and stale-data handling."""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.source_status import evaluate_status, record_status


class SourceStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.now = datetime(2026, 11, 21, 10, 0, tzinfo=timezone.utc)

    def test_success_is_current_within_age_limit(self):
        record_status("finviz", "success", status_dir=self.directory, now=self.now - timedelta(hours=2))
        result = evaluate_status("finviz", "automatic", 24, self.directory, self.now)
        self.assertEqual(result["status"], "CURRENT")
        self.assertTrue(result["include"])
        self.assertFalse(result["partial"])

    def test_failure_preserves_last_success_and_uses_recent_fallback(self):
        record_status("finviz", "success", status_dir=self.directory, now=self.now - timedelta(hours=4))
        record_status("finviz", "failure", "HTTP 403", self.directory, self.now)
        result = evaluate_status("finviz", "automatic", 24, self.directory, self.now)
        self.assertEqual(result["status"], "STALE_FALLBACK")
        self.assertTrue(result["include"])
        self.assertTrue(result["partial"])
        self.assertIn("HTTP 403", result["detail"])

    def test_failed_source_without_success_is_excluded(self):
        record_status("vyus", "failure", "HTTP 403", self.directory, self.now)
        result = evaluate_status("vyus", "automatic", 24, self.directory, self.now)
        self.assertEqual(result["status"], "FAILED")
        self.assertFalse(result["include"])

    def test_expired_success_is_excluded(self):
        record_status("tv", "success", status_dir=self.directory, now=self.now - timedelta(hours=30))
        result = evaluate_status("tv", "automatic", 24, self.directory, self.now)
        self.assertEqual(result["status"], "STALE")
        self.assertFalse(result["include"])

    def test_missing_status_is_explicit_fallback(self):
        result = evaluate_status("blue_sky", "automatic", 24, self.directory, self.now)
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertTrue(result["include"])
        self.assertTrue(result["partial"])

    def test_manual_source_does_not_require_status_file(self):
        result = evaluate_status("sector", "manual", 24, self.directory, self.now)
        self.assertEqual(result["status"], "MANUAL")
        self.assertTrue(result["include"])
        self.assertFalse(result["partial"])

    def test_corrupt_status_is_not_treated_as_current(self):
        (self.directory / "finviz.json").write_text("{bad", encoding="utf-8")
        result = evaluate_status("finviz", "automatic", 24, self.directory, self.now)
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertTrue(result["partial"])


    def test_missing_attempt_timestamp_is_unknown(self):
        path = self.directory / "finviz.json"
        path.write_text(json.dumps({
            "source_id": "finviz",
            "last_attempt_status": "success",
            "last_success_at": self.now.isoformat(),
        }), encoding="utf-8")
        result = evaluate_status("finviz", "automatic", 24, self.directory, self.now)
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertTrue(result["partial"])

    def test_future_attempt_timestamp_is_unknown(self):
        record_status("finviz", "success", status_dir=self.directory, now=self.now + timedelta(hours=1))
        result = evaluate_status("finviz", "automatic", 24, self.directory, self.now)
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertTrue(result["partial"])

    def test_attempt_before_success_timestamp_is_unknown(self):
        path = self.directory / "finviz.json"
        path.write_text(json.dumps({
            "source_id": "finviz",
            "last_attempt_status": "failure",
            "last_attempt_at": (self.now - timedelta(hours=2)).isoformat(),
            "last_success_at": (self.now - timedelta(hours=1)).isoformat(),
        }), encoding="utf-8")
        result = evaluate_status("finviz", "automatic", 24, self.directory, self.now)
        self.assertEqual(result["status"], "UNKNOWN")

    def test_corrupt_status_is_not_overwritten_and_last_success_is_not_lost(self):
        path = self.directory / "finviz.json"
        path.write_text("{bad", encoding="utf-8")
        with self.assertRaises(json.JSONDecodeError):
            record_status("finviz", "failure", "refresh failed", self.directory, self.now)
        self.assertEqual(path.read_text(encoding="utf-8"), "{bad")


if __name__ == "__main__":
    unittest.main()
