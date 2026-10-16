#!/usr/bin/env python3
"""Test whether GitHub Actions can read ticker symbols from the regular Finviz screener page."""
import re
import sys
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

CONFIG_URL = "https://raw.githubusercontent.com/Melief/daily-stock-radar/main/finviz_url.txt"
TIMEOUT_SECONDS = 25


def fetch(url):
    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/129.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,*/*",
        },
    )
    with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        body = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
        return response.status, response.geturl(), response.headers.get("Content-Type", ""), body.decode(charset, errors="replace")


class TickerLinkParser(HTMLParser):
    """Collect ticker symbols from Finviz quote links in the screener HTML."""

    def __init__(self):
        super().__init__()
        self.tickers = []
        self.seen = set()

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a":
            return
        attrs = dict(attrs)
        href = attrs.get("href", "")
        if "quote.ashx" not in href and "stock.ashx" not in href:
            return
        params = parse_qs(urlparse(href).query)
        ticker = params.get("t", [""])[0].strip().upper()
        if re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,9}", ticker) and ticker not in self.seen:
            self.seen.add(ticker)
            self.tickers.append(ticker)


def main():
    print("TEST: Can GitHub Actions read tickers from the regular Finviz screener page?")
    try:
        _, _, _, config = fetch(CONFIG_URL)
    except Exception as exc:
        print(f"FAIL: Could not read GitHub configuration: {exc}")
        return 1

    screener_url = config.strip()
    parsed = urlparse(screener_url)
    if parsed.scheme != "https" or parsed.netloc not in ("finviz.com", "www.finviz.com") or not parsed.query:
        print("FAIL: finviz_url.txt does not contain a valid Finviz screener URL.")
        return 1

    print("Requesting the regular screener page (not the CSV export endpoint)...")
    print(f"URL: {screener_url}")
    try:
        status, final_url, content_type, body = fetch(screener_url)
    except HTTPError as exc:
        print(f"FAIL: Screener page returned HTTP {exc.code}.")
        return 1
    except (URLError, TimeoutError) as exc:
        print(f"FAIL: Screener request failed: {exc}")
        return 1

    print(f"HTTP status: {status}")
    print(f"Content-Type: {content_type}")
    print(f"Final URL: {final_url}")
    print(f"Response length: {len(body):,} characters")

    lowered = body[:12000].lower()
    if "cloudflare" in lowered or "verify you are human" in lowered or "captcha" in lowered:
        print("FAIL: Finviz returned an anti-bot/challenge page.")
        print("Response preview: " + body[:350].replace("\n", " "))
        return 1
    if "finviz elite" in body[:5000].lower() and "screener" not in body[:5000].lower():
        print("FAIL: Finviz redirected the request to an Elite/login page.")
        print("Response preview: " + body[:350].replace("\n", " "))
        return 1
    if "<html" not in body[:2000].lower():
        print("FAIL: Response does not look like an HTML page.")
        print("Response preview: " + body[:350].replace("\n", " "))
        return 1

    parser = TickerLinkParser()
    parser.feed(body)
    if not parser.tickers:
        print("FAIL: Finviz returned HTML, but no ticker links could be extracted.")
        print("The page may require JavaScript, authentication, or a different HTML structure.")
        print("Response preview: " + body[:500].replace("\n", " "))
        return 1

    print(f"SUCCESS: Extracted {len(parser.tickers)} unique ticker(s) from the regular screener HTML:")
    print(", ".join(parser.tickers[:50]))
    if len(parser.tickers) > 50:
        print("...")
    print("This confirms HTML/ticker access only; it does not validate quote freshness.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
