
#!/usr/bin/env python3
"""Sync Finviz screener tickers to Google Sheets."""

import json
import os
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

TIMEOUT = 30


def fetch(url):
    request = Request(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Accept": "text/html,application/xhtml+xml,*/*",
    })
    with urlopen(request, timeout=TIMEOUT) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.status, response.geturl(), response.read().decode(
            charset, errors="replace"
        )


class TickerParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tickers = []
        self.seen = set()

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a":
            return

        href = dict(attrs).get("href", "")
        parsed = urlparse(href)
        ticker = parse_qs(parsed.query).get("t", [""])[0].strip().upper()

        if (
            re.search(r"(?:^|/)(?:stock|quote)$", parsed.path)
            and re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", ticker)
            and ticker not in self.seen
        ):
            self.seen.add(ticker)
            self.tickers.append(ticker)


def main():
    web_app_url = os.environ.get("GS_WEBAPP_URL", "").strip()
    secret = os.environ.get("GS_SECRET", "").strip()

    if not web_app_url or not web_app_url.startswith(
        "https://script.google.com/macros/s/"
    ) or not web_app_url.endswith("/exec"):
        print("ERROR: Check the GS_WEBAPP_URL variable.")
        return 1

    if not secret:
        print("ERROR: The GS_SECRET secret is missing.")
        return 1

    try:
        finviz_url = Path("finviz_url.txt").read_text(
            encoding="utf-8"
        ).strip()

        parsed_url = urlparse(finviz_url)
        if parsed_url.scheme != "https" or parsed_url.netloc not in (
            "finviz.com", "www.finviz.com"
        ):
            print("ERROR: Invalid URL in finviz_url.txt.")
            return 1

        status, final_url, html = fetch(finviz_url)

    except (OSError, HTTPError, URLError, TimeoutError, ValueError) as exc:
        print(f"ERROR: Could not retrieve Finviz: {exc}")
        return 1

    parser = TickerParser()
    parser.feed(html)

    if not parser.tickers:
        print("ERROR: No tickers found. Google Sheets was not changed.")
        print(f"HTTP status: {status}; HTML length: {len(html)}")
        return 1

    payload = json.dumps({
        "secret": secret,
        "tickers": parser.tickers,
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

    print(f"SUCCESS: Sent {len(parser.tickers)} tickers to Google Sheets.")
    print(", ".join(parser.tickers))
    return 0


if __name__ == "__main__":
    sys.exit(main())
