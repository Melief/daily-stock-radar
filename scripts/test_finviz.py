#!/usr/bin/env python3
"""Fetch the Finviz screener export and safely refresh the ticker CSV."""
import csv
import io
import re
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen

CONFIG_FILE = Path("finviz_url.txt")
OUTPUT_FILE = Path("finviz_tickers.csv")
TIMEOUT_SECONDS = 30
MAX_ATTEMPTS = 3
TICKER_RE = re.compile(r"[A-Z][A-Z0-9.-]{0,9}")


def fetch(url):
    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/129.0.0.0 Safari/537.36"
            ),
            "Accept": "text/csv,text/plain,*/*",
            "Referer": "https://finviz.com/",
        },
    )
    with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        body = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
        return (
            response.status,
            response.geturl(),
            response.headers.get("Content-Type", ""),
            body.decode(charset, errors="replace"),
        )


def make_export_url(screener_url):
    parsed = urlparse(screener_url)
    # Keep the exact screener filters, view, sort order and selected columns.
    query = urlencode(parse_qsl(parsed.query, keep_blank_values=True))
    return urlunparse(
        ("https", "finviz.com", "/export.ashx", "", query, "")
    )


def parse_export(body):
    if not body.strip() or "<html" in body[:1000].lower() or "<!doctype" in body[:1000].lower():
        raise ValueError("Finviz returned an empty response or HTML instead of CSV.")

    try:
        reader = csv.DictReader(io.StringIO(body))
        if not reader.fieldnames:
            raise ValueError("CSV header is missing.")

        columns = {name.strip().lower(): name for name in reader.fieldnames if name}
        ticker_column = columns.get("ticker")
        if not ticker_column:
            raise ValueError(
                "Finviz CSV has no Ticker column. Headers: "
                + ", ".join(reader.fieldnames)
            )

        tickers = []
        seen = set()
        for row in reader:
            ticker = (row.get(ticker_column) or "").strip().upper()
            if TICKER_RE.fullmatch(ticker) and ticker not in seen:
                seen.add(ticker)
                tickers.append(ticker)
    except csv.Error as exc:
        raise ValueError(f"Could not parse Finviz CSV: {exc}") from exc

    if not tickers:
        raise ValueError("Finviz export contained no valid ticker rows.")
    return tickers


def write_csv_atomically(tickers):
    # Write to a temporary file first so a failed write cannot truncate the
    # previous valid CSV.
    temporary_file = OUTPUT_FILE.with_suffix(OUTPUT_FILE.suffix + ".tmp")
    try:
        with temporary_file.open("w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow(["Ticker"])
            writer.writerows([[ticker] for ticker in tickers])
        temporary_file.replace(OUTPUT_FILE)
    finally:
        if temporary_file.exists():
            temporary_file.unlink()


def main():
    print("Fetch authoritative Finviz CSV export and refresh finviz_tickers.csv.")
    if not CONFIG_FILE.exists():
        print("FAIL: finviz_url.txt is missing; existing CSV left unchanged.")
        return 1

    screener_url = CONFIG_FILE.read_text(encoding="utf-8").strip()
    parsed = urlparse(screener_url)
    if (
        parsed.scheme != "https"
        or parsed.netloc.lower() not in ("finviz.com", "www.finviz.com")
        or not parsed.path.rstrip("/").endswith("screener")
        or not parsed.query
    ):
        print("FAIL: Invalid Finviz screener URL in finviz_url.txt; existing CSV left unchanged.")
        return 1

    export_url = make_export_url(screener_url)
    tickers = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            status, final_url, content_type, body = fetch(export_url)
            print(
                f"Attempt {attempt}: HTTP {status}; Content-Type: {content_type}; "
                f"response length: {len(body):,}."
            )
            if status != 200:
                raise ValueError(f"Unexpected HTTP status {status}.")
            tickers = parse_export(body)
            print(f"Validated {len(tickers)} unique tickers from Finviz CSV export.")
            break
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            print(f"Attempt {attempt} failed: {exc}")
            if attempt == MAX_ATTEMPTS:
                print("FAIL: Finviz export failed validation; existing CSV left unchanged.")
                return 1
            time.sleep(attempt * 2)

    try:
        write_csv_atomically(tickers)
    except OSError as exc:
        print(f"FAIL: Could not safely write {OUTPUT_FILE}: {exc}")
        return 1

    print(f"SUCCESS: Wrote {len(tickers)} unique tickers to {OUTPUT_FILE}:")
    print(", ".join(tickers))
    return 0


if __name__ == "__main__":
    sys.exit(main())
