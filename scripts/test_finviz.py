#!/usr/bin/env python3
"""Fetch Finviz tickers and safely refresh the ticker CSV."""
import csv
import io
import re
import sys
import time
from html.parser import HTMLParser
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
    request = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/csv,text/plain,text/html,application/xhtml+xml,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://finviz.com/",
    })
    with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        body = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
        return response.status, response.geturl(), response.headers.get("Content-Type", ""), body.decode(charset, errors="replace")


def make_url(screener_url, path):
    parsed = urlparse(screener_url)
    query = urlencode(parse_qsl(parsed.query, keep_blank_values=True))
    return urlunparse(("https", "finviz.com", path, "", query, ""))


class ScreenerParser(HTMLParser):
    """Extract ticker symbols from Finviz screener quote links."""
    def __init__(self):
        super().__init__()
        self.tickers = []
        self.seen = set()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href", "")
        if not href:
            return
        if any(word in href.lower() for word in ("quote", "stock", "ticker")) and len(self.links) < 12:
            self.links.append(href)
        parsed = urlparse(href)
        ticker = ""
        if parsed.path.lower().rstrip("/").endswith(("quote.ashx", "quote", "stock.ashx", "stock")):
            for key, value in parse_qsl(parsed.query):
                if key.lower() in ("t", "ticker", "symbol"):
                    ticker = value.strip().upper()
                    break
        if ticker and TICKER_RE.fullmatch(ticker) and ticker not in self.seen:
            self.seen.add(ticker)
            self.tickers.append(ticker)


def parse_export(body):
    if not body.strip() or "<html" in body[:1000].lower() or "<!doctype" in body[:1000].lower():
        title = re.search(r"<title[^>]*>(.*?)</title>", body[:10000], re.I | re.S)
        parser = ScreenerParser()
        parser.feed(body)
        detail = f"HTML title={title.group(1).strip()[:120]!r}" if title else "HTML title not found"
        detail += f"; candidate links={parser.links!r}; extracted tickers={len(parser.tickers)}"
        if parser.tickers:
            return parser.tickers
        raise ValueError("Finviz returned HTML, not CSV; " + detail)

    try:
        reader = csv.DictReader(io.StringIO(body))
        if not reader.fieldnames:
            raise ValueError("CSV header is missing.")
        columns = {name.strip().lower(): name for name in reader.fieldnames if name}
        ticker_column = columns.get("ticker")
        if not ticker_column:
            raise ValueError("Finviz CSV has no Ticker column.")
        tickers, seen = [], set()
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
    print("Fetch Finviz tickers and refresh finviz_tickers.csv.")
    if not CONFIG_FILE.exists():
        print("FAIL: finviz_url.txt is missing; existing CSV left unchanged.")
        return 1
    screener_url = CONFIG_FILE.read_text(encoding="utf-8").strip()
    parsed = urlparse(screener_url)
    if parsed.scheme != "https" or parsed.netloc.lower() not in ("finviz.com", "www.finviz.com") or not parsed.query:
        print("FAIL: Invalid Finviz URL; existing CSV left unchanged.")
        return 1

    # Try Finviz's CSV export first, then its classic screener HTML endpoint.
    urls = [make_url(screener_url, "/export.ashx"), make_url(screener_url, "/screener.ashx")]
    errors = []
    tickers = None
    for url in urls:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                status, final_url, content_type, body = fetch(url)
                print(f"Request {urlparse(url).path}, attempt {attempt}: HTTP {status}; Content-Type: {content_type}; length: {len(body):,}.")
                if status != 200:
                    raise ValueError(f"Unexpected HTTP status {status}.")
                tickers = parse_export(body)
                print(f"Validated {len(tickers)} unique tickers from {urlparse(url).path}.")
                break
            except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
                errors.append(f"{urlparse(url).path} attempt {attempt}: {exc}")
                print(f"Attempt failed: {exc}")
                if attempt < MAX_ATTEMPTS:
                    time.sleep(attempt * 2)
        if tickers:
            break

    if not tickers:
        print("FAIL: Finviz retrieval failed; existing CSV left unchanged.")
        return 1

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
