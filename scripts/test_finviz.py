#!/usr/bin/env python3
"""Test whether a GitHub-hosted script can fetch ticker symbols from Finviz.

Reads the screener URL from finviz_url.txt, requests the page, and extracts
ticker symbols from Finviz quote links. It prints diagnostics and exits with
a non-zero status if no ticker symbols can be confirmed.
"""
import re
import sys
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

CONFIG_URL = "https://raw.githubusercontent.com/Melief/daily-stock-radar/main/finviz_url.txt"
TIMEOUT_SECONDS = 25


class TickerLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tickers = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a":
            return
        attrs = dict(attrs)
        href = attrs.get("href", "")
        # Finviz screener ticker links commonly use /quote.ashx?t=SYMBOL
        match = re.search(r"/quote\.ashx\?[^\"]*\bt=([A-Z0-9.\-]+)", href, re.I)
        if match:
            symbol = match.group(1).upper()
            if symbol not in self.tickers:
                self.tickers.append(symbol)


def fetch(url):
    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/129.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        data = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
        return response.status, response.geturl(), data.decode(charset, errors="replace")


def main():
    print("TEST: Can this script read ticker symbols from Finviz?")
    print("1) Reading the screener URL from GitHub...")
    try:
        status, _, config = fetch(CONFIG_URL)
    except (HTTPError, URLError, TimeoutError) as exc:
        print(f"FAIL: Could not read GitHub configuration: {exc}")
        return 1

    url = config.strip()
    if status != 200 or not url.startswith("https://finviz.com/"):
        print("FAIL: finviz_url.txt is missing or does not contain a Finviz URL.")
        return 1
    print("OK: Finviz URL loaded.")

    print("2) Requesting the Finviz screener...")
    try:
        status, final_url, html = fetch(url)
    except HTTPError as exc:
        print(f"FAIL: Finviz returned HTTP {exc.code}.")
        return 1
    except (URLError, TimeoutError) as exc:
        print(f"FAIL: Finviz request failed: {exc}")
        return 1

    print(f"HTTP status: {status}")
    print(f"Final URL: {final_url}")
    print(f"HTML length: {len(html):,} characters")

    parser = TickerLinks()
    parser.feed(html)
    tickers = parser.tickers

    low = html.lower()
    block_signals = [
        marker for marker in ("captcha", "access denied", "verify you are human", "cloudflare")
        if marker in low
    ]
    if block_signals:
        print("WARNING: Possible anti-bot/access-block page: " + ", ".join(block_signals))

    if tickers:
        print(f"SUCCESS: Extracted {len(tickers)} ticker(s) from the Finviz HTML:")
        print(", ".join(tickers))
        print("Note: this tests retrieval and parsing; it does not yet validate quote freshness.")
        return 0

    print("FAIL: No ticker symbols were extracted from the returned HTML.")
    print("Finviz may be blocking automated requests or may have changed its page structure.")
    print("No ticker list will be guessed or substituted.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
