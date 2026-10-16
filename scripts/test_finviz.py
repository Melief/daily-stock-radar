#!/usr/bin/env python3
"""Test whether GitHub Actions can retrieve Finviz screener data as CSV."""
import csv
import io
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
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
            "Accept": "text/csv,text/plain,text/html,*/*",
        },
    )
    with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        body = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
        return response.status, response.geturl(), response.headers.get("Content-Type", ""), body.decode(charset, errors="replace")


def main():
    print("TEST: Can GitHub Actions retrieve Finviz screener data via CSV export?")
    try:
        status, _, config = fetch(CONFIG_URL)
    except Exception as exc:
        print(f"FAIL: Could not read GitHub configuration: {exc}")
        return 1

    screener_url = config.strip()
    parsed = urlparse(screener_url)
    if not screener_url.startswith("https://finviz.com/") or not parsed.query:
        print("FAIL: finviz_url.txt does not contain a valid Finviz screener URL.")
        return 1

    # Preserve the screener's filters/view/sort, but use Finviz's CSV export endpoint.
    params = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k != "preset"]
    export_url = urlunparse(("https", "finviz.com", "/export.ashx", "", urlencode(params), ""))
    print("Requesting Finviz CSV export endpoint...")
    print(f"URL: {export_url}")

    try:
        status, final_url, content_type, body = fetch(export_url)
    except HTTPError as exc:
        print(f"FAIL: Export endpoint returned HTTP {exc.code}.")
        if exc.code in (401, 403, 429):
            print("This may require authentication or the request may be blocked/rate-limited.")
        return 1
    except (URLError, TimeoutError) as exc:
        print(f"FAIL: Export request failed: {exc}")
        return 1

    print(f"HTTP status: {status}")
    print(f"Content-Type: {content_type}")
    print(f"Final URL: {final_url}")
    print(f"Response length: {len(body):,} characters")

    if "<html" in body[:1000].lower() or "cloudflare" in body[:5000].lower():
        print("FAIL: The export endpoint returned HTML, not CSV (possibly login or anti-bot page).")
        print("Response preview:")
        print(body[:400].replace("\n", " "))
        return 1

    try:
        rows = list(csv.reader(io.StringIO(body)))
    except Exception as exc:
        print(f"FAIL: Could not parse response as CSV: {exc}")
        return 1

    if len(rows) < 2:
        print("FAIL: Response looks like CSV but contains no data rows.")
        print("Response preview:")
        print(body[:400].replace("\n", " "))
        return 1

    header = [cell.strip().strip('"').lower() for cell in rows[0]]
    ticker_index = next((i for i, name in enumerate(header) if name in ("ticker", "symbol")), None)
    if ticker_index is None:
        print("FAIL: CSV has no Ticker/Symbol column.")
        print("CSV header: " + ", ".join(rows[0]))
        print("Response preview: " + body[:300].replace("\n", " "))
        return 1

    tickers = []
    for row in rows[1:]:
        if ticker_index < len(row):
            ticker = row[ticker_index].strip().strip('"')
            if ticker and ticker not in tickers:
                tickers.append(ticker)

    if not tickers:
        print("FAIL: CSV header was found, but no ticker values were present.")
        return 1

    print(f"SUCCESS: Read {len(tickers)} ticker(s) from CSV:")
    print(", ".join(tickers[:30]))
    if len(tickers) > 30:
        print("...")
    print("This confirms CSV retrieval only; it does not validate quote freshness.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
