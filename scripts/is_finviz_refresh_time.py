#!/usr/bin/env python3
"""Allow only the five intended refresh times in New York local time."""
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

TARGET_TIMES = {"09:50", "11:30", "13:30", "15:30", "17:30"}

now = datetime.now(ZoneInfo("America/New_York"))
should_run = now.weekday() < 5 and now.strftime("%H:%M") in TARGET_TIMES

output = Path(__import__("os").environ.get("GITHUB_OUTPUT", ""))
if should_run and str(output) not in ("", "."):
    with output.open("a", encoding="utf-8") as f:
        f.write("run=true\n")
elif not should_run and str(output) not in ("", "."):
    with output.open("a", encoding="utf-8") as f:
        f.write("run=false\n")

print(f"New York time: {now:%Y-%m-%d %H:%M:%S %Z}; refresh: {should_run}")
