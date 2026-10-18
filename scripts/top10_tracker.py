#!/usr/bin/env python3
"""Track changes in the published Google Sheets Top 10 by 15-day return."""
import csv
import io
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen

SOURCE_URL = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vSf8RlB7i3wH2aeqM4YPDMp-skoxCHbfAyLxfMytrfB-48J5DZgqVdcENpmac2m2xzExKFEfzr5X-CH/"
    "pub?gid=1548364892&single=true&output=csv"
)
ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
PREVIOUS = DATA_DIR / "top10_previous.csv"
OUTPUT = ROOT / "top10_status.csv"
FINVIZ_HTML = ROOT / "finviz_screener.html"


class FinvizTickerParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tickers = set()

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a":
            return
        from urllib.parse import parse_qs, urlparse
        href = dict(attrs).get("href", "")
        parsed = urlparse(href)
        ticker = parse_qs(parsed.query).get("t", [""])[0].strip().upper()
        if re.search(r"(?:^|/)(?:stock|quote)$", parsed.path) and re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", ticker):
            self.tickers.add(ticker)


def fetch_rows():
    request = Request(SOURCE_URL, headers={"User-Agent": "daily-stock-radar/1.0"})
    with urlopen(request, timeout=30) as response:
        raw = response.read().decode("utf-8-sig")
    rows = []
    for row in csv.reader(io.StringIO(raw)):
        if len(row) < 2:
            continue
        ticker = row[0].strip().upper()
        ret = row[1].strip().replace(",", ".")
        if not ticker or not ret or ticker in {"TICKER", "SYMBOL"}:
            continue
        if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,9}", ticker):
            continue
        if not re.fullmatch(r"-?\d+(?:\.\d+)?\s*%?", ret):
            continue
        if not ret.endswith("%"):
            ret += "%"
        rows.append((ticker, ret))
    if len(rows) != 10:
        raise ValueError(f"Expected exactly 10 valid Top 10 rows, received {len(rows)}; refusing to replace previous snapshot.")
    if len({ticker for ticker, _ in rows}) != 10:
        raise ValueError("Duplicate tickers in Top 10; refusing to replace previous snapshot.")
    return rows


def read_previous():
    with PREVIOUS.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError("Previous snapshot is empty; refusing to continue.")
    return {row["Ticker"].strip().upper(): row["15-day return"].strip() for row in rows}


def read_finviz_tickers():
    if not FINVIZ_HTML.exists():
        print("WARNING: Finviz HTML missing; no Finviz markers applied.")
        return set()
    parser = FinvizTickerParser()
    parser.feed(FINVIZ_HTML.read_text(encoding="utf-8", errors="replace"))
    return parser.tickers


def main():
    current_rows = fetch_rows()
    previous = read_previous()
    finviz = read_finviz_tickers()
    current = {ticker: ret for ticker, ret in current_rows}
    result = []
    for ticker, ret in current_rows:
        status = "⭐ TOP 10" if ticker in previous else "🟢 TOP 10 IN"
        shown_ticker = ticker + (" ⭐" if ticker in finviz else "")
        result.append((shown_ticker, ret, status))
    for ticker, ret in previous.items():
        if ticker not in current:
            shown_ticker = ticker + (" ⭐" if ticker in finviz else "")
            result.append((shown_ticker, ret, "🔴 TOP 10 UIT"))

    with OUTPUT.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["Ticker", "15-day return", "Status"])
        writer.writerows(result)

    # Update the saved comparison only after the source was fully validated.
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with PREVIOUS.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Ticker", "15-day return"])
        writer.writerows(current_rows)

    print(f"Validated {len(current_rows)} current Top 10 rows.")
    print(f"Found {len(finviz)} current Finviz ticker(s).")
    print(f"Wrote {len(result)} status rows to {OUTPUT.name}.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
