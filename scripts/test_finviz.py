#!/usr/bin/env python3
"""Fetch the ordinary Finviz screener page and extract ticker symbols."""
import csv
import re
import sys
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

CONFIG_FILE = Path("finviz_url.txt")
OUTPUT_FILE = Path("finviz_tickers.csv")
TIMEOUT_SECONDS = 25
MAX_ATTEMPTS = 3


def fetch(url):
    request = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,*/*",
    })
    with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        body = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
        return response.status, response.geturl(), response.headers.get("Content-Type", ""), body.decode(charset, errors="replace")


class TickerLinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tickers, self.seen = [], set()

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href", "")
        parsed = urlparse(href)
        ticker = parse_qs(parsed.query).get("t", [""])[0].strip().upper()
        if re.search(r"(?:^|/)(?:stock|quote)$", parsed.path) and re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", ticker):
            if ticker not in self.seen:
                self.seen.add(ticker)
                self.tickers.append(ticker)


def main():
    print("Fetch Finviz screener and create finviz_tickers.csv.")
    if not CONFIG_FILE.exists():
        print("FAIL: finviz_url.txt is missing.")
        return 1
    screener_url = CONFIG_FILE.read_text(encoding="utf-8").strip()
    parsed = urlparse(screener_url)
    if parsed.scheme != "https" or parsed.netloc.lower() not in ("finviz.com", "www.finviz.com") or not parsed.query:
        print("FAIL: Invalid Finviz URL in finviz_url.txt.")
        return 1

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            status, final_url, content_type, body = fetch(screener_url)
            print(f"Attempt {attempt}: HTTP {status}; Content-Type: {content_type}; final URL: {final_url}; response length: {len(body):,}.")
            if status != 200 or len(body) < 1000 or "finviz" not in body[:20000].lower():
                raise ValueError("Response does not look like a valid Finviz page.")
            break
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            print(f"Attempt {attempt} failed: {exc}")
            if attempt == MAX_ATTEMPTS:
                print("FAIL: Could not retrieve a valid Finviz page.")
                return 1
            time.sleep(attempt * 2)

    parser = TickerLinkParser()
    parser.feed(body)
    if not parser.tickers:
        print("FAIL: No tickers extracted; existing CSV left unchanged.")
        return 1

    with OUTPUT_FILE.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Ticker"])
        writer.writerows([[ticker] for ticker in parser.tickers])
    print(f"SUCCESS: Wrote {len(parser.tickers)} unique tickers to {OUTPUT_FILE}:")
    print(", ".join(parser.tickers))
    return 0


if __name__ == "__main__":
    sys.exit(main())
