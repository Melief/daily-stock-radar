#!/usr/bin/env python3
"""Sync a ticker CSV to its configured Google Sheets worksheet."""

import csv
import json
import os
import re
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

TIMEOUT = 30


def main():
    web_app_url = os.environ.get("GS_WEBAPP_URL", "").strip()
    secret = os.environ.get("GS_SECRET", "").strip()
    csv_file = Path(os.environ.get("TICKER_CSV_FILE", "finviz_tickers.csv"))
    target_sheet = os.environ.get("GS_TARGET_SHEET", "Import FV uit GH").strip()

    if not web_app_url or not web_app_url.startswith(
        "https://script.google.com/macros/s/"
    ) or not web_app_url.endswith("/exec"):
        print("ERROR: Check the GS_WEBAPP_URL variable.")
        return 1

    if not secret:
        print("ERROR: The GS_SECRET secret is missing.")
        return 1

    if not target_sheet:
        print("ERROR: GS_TARGET_SHEET is empty.")
        return 1

    if not csv_file.exists():
        print(f"ERROR: {csv_file} is missing. Google Sheets was not changed.")
        return 1

    tickers = []
    seen = set()
    try:
        with csv_file.open("r", newline="", encoding="utf-8-sig") as file:
            reader = csv.DictReader(file)
            if not reader.fieldnames or "Ticker" not in reader.fieldnames:
                print(f"ERROR: {csv_file} must have a 'Ticker' column.")
                return 1
            for row in reader:
                ticker = (row.get("Ticker") or "").strip().upper()
                if re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", ticker) and ticker not in seen:
                    seen.add(ticker)
                    tickers.append(ticker)
    except (OSError, csv.Error) as exc:
        print(f"ERROR: Could not read {csv_file}: {exc}")
        return 1

    if not tickers:
        print(f"ERROR: No valid tickers in {csv_file}. Google Sheets was not changed.")
        return 1

    payload = json.dumps({
        "secret": secret,
        "tickers": tickers,
        "targetSheet": target_sheet,
    }).encode("utf-8")

    request = Request(
        web_app_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=TIMEOUT) as response:
            result = response.read().decode("utf-8", errors="replace").strip()
    except (HTTPError, URLError, TimeoutError) as exc:
        print(f"ERROR: Google Sheets request failed: {exc}")
        return 1

    if result != "OK":
        print(f"ERROR: Apps Script response: {result[:300]}")
        return 1

    print(
        f"SUCCESS: Sent {len(tickers)} tickers from {csv_file} "
        f"to Google Sheets worksheet '{target_sheet}'."
    )
    print(", ".join(tickers))
    return 0


if __name__ == "__main__":
    sys.exit(main())
