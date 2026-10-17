#!/usr/bin/env python3
"""Fetch the ordinary Finviz screener page and extract ticker symbols."""
import re
import sys
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

CONFIG_URL = "https://raw.githubusercontent.com/Melief/daily-stock-radar/main/finviz_url.txt"
TIMEOUT_SECONDS = 25
OUTPUT_FILE = "finviz_screener.html"


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
        params = parse_qs(urlparse(href).query)
        ticker = params.get("t", [""])[0].strip().upper()
        # Current Finviz HTML uses links such as stock?t=FFIV, not quote.ashx.
        if re.search(r"(?:^|/)(?:stock|quote)$", urlparse(href).path) and re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", ticker):
            if ticker not in self.seen:
                self.seen.add(ticker)
                self.tickers.append(ticker)


def main():
    print("TEST: Fetch the regular Finviz screener page and extract tickers.")
    try:
        _, _, _, config = fetch(CONFIG_URL)
        screener_url = config.strip()
        parsed = urlparse(screener_url)
        if parsed.scheme != "https" or parsed.netloc not in ("finviz.com", "www.finviz.com"):
            print("FAIL: Invalid Finviz URL in finviz_url.txt.")
            return 1
        status, final_url, content_type, body = fetch(screener_url)
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        print(f"FAIL: Request failed: {exc}")
        return 1

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(body)
    print(f"Saved response to {OUTPUT_FILE}.")
    print(f"HTTP status: {status}; Content-Type: {content_type}")
    print(f"Final URL: {final_url}")
    print(f"Response length: {len(body):,} characters")

    parser = TickerLinkParser()
    parser.feed(body)
    if not parser.tickers:
        print("FAIL: Page was retrieved, but no ticker symbols were extracted.")
        print("This may indicate a Finviz page-structure change or a blocked/incomplete response.")
        return 1

    print(f"SUCCESS: Extracted {len(parser.tickers)} unique ticker(s) from the screener:")
    print(", ".join(parser.tickers))
    print("These are the tickers currently returned by the Finviz filter, not the full GitHub watchlist.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
