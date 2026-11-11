#!/usr/bin/env python3
"""Gate scheduled Finviz refreshes to the configured New York refresh slots."""
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# Existing cadence: every two hours during the New York weekday trading day.
TARGET_HOURS = (9, 11, 13, 15, 17)
START_MINUTE = 50
# GitHub scheduled workflows can start late; allow up to 45 minutes.
START_TOLERANCE_MINUTES = 45
TIMEZONE = ZoneInfo("America/New_York")

now = datetime.now(TIMEZONE)
should_run = False
matched_slot = None

if now.weekday() < 5:
    for hour in TARGET_HOURS:
        slot = now.replace(hour=hour, minute=START_MINUTE, second=0, microsecond=0)
        delay = now - slot
        if timedelta(0) <= delay <= timedelta(minutes=START_TOLERANCE_MINUTES):
            should_run = True
            matched_slot = slot
            break

output_path = os.environ.get("GITHUB_OUTPUT")
if output_path:
    with Path(output_path).open("a", encoding="utf-8") as file:
        file.write(f"run={'true' if should_run else 'false'}\n")

if matched_slot:
    print(
        f"New York time: {now:%Y-%m-%d %H:%M:%S %Z}; "
        f"scheduled slot: {matched_slot:%H:%M}; "
        f"delay: {(now - matched_slot).total_seconds() / 60:.1f} minutes; run: true"
    )
else:
    print(f"New York time: {now:%Y-%m-%d %H:%M:%S %Z}; run: false")
