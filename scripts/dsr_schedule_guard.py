#!/usr/bin/env python3
"""DST-safe guard for the DSR 04:00 Europe/Amsterdam scheduled snapshot."""
from __future__ import annotations

import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo


EXPECTED_OFFSETS = {
    "0 2 * * 1-5": "+0200",  # 04:00 CEST
    "0 3 * * 1-5": "+0100",  # 04:00 CET
}


def should_run(event_name: str, schedule: str, offset: str) -> bool:
    if event_name != "schedule":
        return True
    return EXPECTED_OFFSETS.get(schedule) == offset


def main() -> int:
    event_name = os.getenv("GITHUB_EVENT_NAME", "")
    schedule = os.getenv("SCHEDULE", "")
    offset = datetime.now(ZoneInfo("Europe/Amsterdam")).strftime("%z")
    run = should_run(event_name, schedule, offset)
    print(f"run={'true' if run else 'false'}")
    print(
        f"DSR scheduled event={schedule or event_name}; Amsterdam UTC{offset}; "
        f"{'running' if run else 'skipping non-matching DST cron'}.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
