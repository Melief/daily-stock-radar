#!/usr/bin/env python3
"""Test and save the regular Finviz screener HTML for ticker extraction."""
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
        attrs = dict(attrs)
        href = attrs.get("href", "")
        params = parse_qs(urlparse(href).query)
        ticker = params.get("t", [""])[0].strip().upper()
        if ("quote.ashx" in href or "stock.ashx" in href) and re.fullmatch(r"[A-Z][A-Z0-9.\\-]{0,9}", ticker):
            if ticker not in self.seen:
                self.seen.add(ticker)
                self.tickers.append(ticker)


def main():
    print("TEST: Fetch ordinary Finviz screener page and inspect its HTML.")
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
    print(f"Saved response to {OUTPUT_FILE} for artifact upload.")
    print(f"HTTP status: {status}; Content-Type: {content_type}")
    print(f"Final URL: {final_url}")
    print(f"Response length: {len(body):,} characters")

    parser = TickerLinkParser()
    parser.feed(body)
    if parser.tickers:
        print(f"SUCCESS: Extracted {len(parser.tickers)} tickers: {', '.join(parser.tickers)}")
        return 0

    # Show evidence about embedded data and ticker-like strings, without assuming matches are valid tickers.
    patterns = [
        r'quote\\.ashx\\?t=[^"\\'<> ]+',
        r'/quote/[^"\\'<> ]+',
        r'"ticker"\\s*:\\s*"[^"]+"',
        r'"symbol"\\s*:\\s*"[^"]+"',
        r'data-symbol=["\\']([^"\\']+)',
    ]
    print("No ticker links matched the expected format.")
    for pattern in patterns:
        matches = re.findall(pattern, body, flags=re.IGNORECASE)
        print(f"Pattern {pattern}: {len(matches)} match(es); examples: {matches[:8]}")
    print("FAIL: Inspect the saved HTML artifact to determine whether tickers are embedded elsewhere.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
