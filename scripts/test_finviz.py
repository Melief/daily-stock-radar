#!/usr/bin/env python3
"""Fetch the Finviz screener page and write the current tickers to CSV."""
import csv
import re
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

CONFIG_FILE = Path("finviz_url.txt")
OUTPUT_FILE = Path("finviz_tickers.csv")
TIMEOUT_SECONDS = 30
MAX_ATTEMPTS = 3
TICKER_RE = re.compile(r"""(?:quote\.ashx\?t=|/stock\?t=|stock\?t=)([A-Z][A-Z0-9.\-]*)""", re.IGNORECASE)


def fetch(url):
    request = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    })
    with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        body = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
        return response.status, response.geturl(), response.headers.get("Content-Type", ""), body.decode(charset, errors="replace")


def main():
    print("Fetching Finviz screener URL from finviz_url.txt.")
    if not CONFIG_FILE.exists():
        print("FAIL: finviz_url.txt is missing.")
        return 1

    screener_url = CONFIG_FILE.read_text(encoding="utf-8").strip()
    parsed = urlparse(screener_url)
    if parsed.scheme != "https" or parsed.netloc.lower() not in ("finviz.com", "www.finviz.com") or not parsed.query:
        print("FAIL: finviz_url.txt does not contain a valid Finviz screener URL.")
        return 1

    body = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            status, final_url, content_type, body = fetch(screener_url)
            print(f"Attempt {attempt}: HTTP {status}; Content-Type: {content_type}; final URL: {final_url}; size: {len(body):,} characters.")
            if status == 200 and len(body) > 1000 and "finviz" in body[:10000].lower():
                break
            raise ValueError("Response does not look like a Finviz screener page.")
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            print(f"Attempt {attempt} failed: {exc}")
            if attempt == MAX_ATTEMPTS:
                print("FAIL: Could not retrieve a valid Finviz screener page.")
                return 1
            time.sleep(attempt * 2)

    matches = TICKER_RE.findall(body)
    tickers = []
    seen = set()
    for match in matches:
        ticker = match.upper()
        if ticker not in seen:
            seen.add(ticker)
            tickers.append(ticker)

    if not tickers:
        print("FAIL: No tickers were found in the Finviz response; CSV was not changed.")
        print("Response preview: " + body[:250].replace("\\n", " "))
        return 1

    with OUTPUT_FILE.open("w", newline="", encoding="utf-8") as output:
        writer = csv.writer(output)
        writer.writerow(["Ticker"])
        writer.writerows([[ticker] for ticker in tickers])

    print(f"SUCCESS: Wrote {len(tickers)} unique tickers to {OUTPUT_FILE}:")
    print(", ".join(tickers))
    return 0


if __name__ == "__main__":
    sys.exit(main())
