#!/usr/bin/env python3
"""Safely merge concurrent per-source status updates during a Git rebase."""
import json
import subprocess
import sys
from datetime import datetime


def timestamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def read_stage(stage, path):
    raw = subprocess.check_output(["git", "show", f":{stage}:{path}"], text=True)
    return json.loads(raw)


def main():
    if len(sys.argv) < 2:
        raise SystemExit("Usage: merge_source_status.py <status-json> [...]")

    for path in sys.argv[1:]:
        if not path.startswith("data/source_status/") or not path.endswith(".json"):
            raise SystemExit(f"Refusing to merge non-status file: {path}")

        upstream = read_stage(2, path)
        local = read_stage(3, path)
        source_id = upstream.get("source_id")
        if not source_id or source_id != local.get("source_id"):
            raise SystemExit(f"Refusing to merge mismatched source IDs in {path}")

        latest = max((upstream, local), key=lambda item: timestamp(item["last_attempt_at"]))
        successful = [
            item["last_success_at"]
            for item in (upstream, local)
            if item.get("last_success_at")
        ]
        merged = dict(latest)
        merged["last_success_at"] = max(successful, key=timestamp) if successful else None

        with open(path, "w", encoding="utf-8") as output:
            json.dump(merged, output, indent=2)
            # Keep merged status files as valid, consistently formatted JSON.
            output.write("\n")
        print(f"Merged concurrent status updates: {path}")


if __name__ == "__main__":
    main()
