#!/usr/bin/env python3
"""Fetch the Finviz screener CSV and save its current ticker list."""
import csv
import io
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen

CONFIG_URL = "https://raw.githubusercontent.com/Melief/daily-stock-radar/main/finviz_url.txt"
TIMEOUT_SECONDS = 25
OUTPUT_FILE = "finviz_tickers.csv"


def fetch(url):
    request = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
        "Accept": "text/csv,text/plain,*/*",
    })
    with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        body = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
        return response.status, response.geturl(), response.headers.get("Content-Type", ""), body.decode(charset, errors="replace")


def main():
    print("TEST: Fetch the current Finviz screener as CSV and create a ticker CSV.")
    try:
        _, _, _, config = fetch(CONFIG_URL)
        screener_url = config.strip()
        parsed = urlparse(screener_url)
        if parsed.scheme != "https" or parsed.netloc not in ("finviz.com", "www.finviz.com") or not parsed.query:
            print("FAIL: Invalid Finviz screener URL in finviz_url.txt.")
            return 1

        # Keep the screener filters and sorting, but use Finviz's CSV export endpoint.
        params = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key != "preset"]
        export_url = urlunparse(("https", "finviz.com", "/export.ashx", "", urlencode(params), ""))
        status, final_url, content_type, body = fetch(export_url)
    except HTTPError as exc:
        print(f"FAIL: Finviz CSV export returned HTTP {exc.code}.")
        return 1
    except (OSError, URLError, TimeoutError, ValueError) as exc:
        print(f"FAIL: Could not retrieve Finviz CSV: {exc}")
        return 1

    print(f"HTTP status: {status}; Content-Type: {content_type}")
    print(f"Final URL: {final_url}; response length: {len(body):,} characters")

    if "<html" in body[:1000].lower() or "cloudflare" in body[:5000].lower():
        print("FAIL: Finviz returned HTML rather than CSV.")
        print(body[:300].replace("\n", " "))
        return 1

    try:
        rows = list(csv.reader(io.StringIO(body)))
    except csv.Error as exc:
        print(f"FAIL: Could not parse CSV: {exc}")
        return 1

    if len(rows) < 2:
        print("FAIL: CSV contains no data rows.")
        print(body[:300].replace("\n", " "))
        return 1

    headers = [cell.strip().strip('"').lower() for cell in rows[0]]
    ticker_index = next((i for i, name in enumerate(headers) if name in ("ticker", "symbol")), None)
    if ticker_index is None:
        print("FAIL: No Ticker/Symbol column in CSV. Header: " + ", ".join(rows[0]))
        return 1

    tickers = []
    seen = set()
    for row in rows[1:]:
        if ticker_index < len(row):
            ticker = row[ticker_index].strip().strip('"').upper()
            if ticker and ticker not in seen:
                seen.add(ticker)
                tickers.append(ticker)

    if not tickers:
        print("FAIL: CSV contains no ticker values.")
        return 1

    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as output:
        writer = csv.writer(output)
        writer.writerow(["Ticker"])
        writer.writerows([[ticker] for ticker in tickers])

    print(f"SUCCESS: Created {OUTPUT_FILE} with {len(tickers)} unique ticker(s):")
    print(", ".join(tickers))
    return 0


if __name__ == "__main__":
    sys.exit(main())
