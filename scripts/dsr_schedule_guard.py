#!/usr/bin/env python3
"""Schedule and upstream-success guard for DSR and the VYUS refresh."""
from __future__ import annotations

import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo


INTRADAY_SCHEDULE = "0 14-21 * * 1-5"

EXPECTED_OFFSETS = {
    "0 2 * * 1-5": "+0200",  # 04:00 CEST
    "0 3 * * 1-5": "+0100",  # 04:00 CET
    "45 1 * * 1-5": "+0200",  # 03:45 CEST VYUS refresh
    "45 2 * * 1-5": "+0100",  # 03:45 CET VYUS refresh
}


def should_run(
    event_name: str,
    schedule: str,
    offset: str,
    upstream_conclusion: str = "",
) -> bool:
    if event_name == "workflow_run":
        return upstream_conclusion == "success"
    if event_name != "schedule":
        return True
    if schedule == INTRADAY_SCHEDULE:
        return True
    return EXPECTED_OFFSETS.get(schedule) == offset


def main() -> int:
    event_name = os.getenv("GITHUB_EVENT_NAME", "")
    schedule = os.getenv("SCHEDULE", "")
    upstream_conclusion = os.getenv("UPSTREAM_CONCLUSION", "")
    offset = datetime.now(ZoneInfo("Europe/Amsterdam")).strftime("%z")
    run = should_run(event_name, schedule, offset, upstream_conclusion)
    print(f"run={'true' if run else 'false'}")
    if event_name == "workflow_run" and not run:
        detail = f"upstream workflow conclusion={upstream_conclusion or 'UNKNOWN'}"
    else:
        detail = f"{schedule or event_name}; Amsterdam UTC{offset}"
    print(
        f"DSR schedule guard: {detail}; "
        f"{'running' if run else 'skipping'}.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
