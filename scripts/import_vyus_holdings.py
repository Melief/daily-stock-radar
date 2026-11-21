#!/usr/bin/env python3
"""Import the 25 publicly displayed VYUS holdings from StockAnalysis."""
import csv
import json
import os
import re
import sys
from pathlib import Path
from html.parser import HTMLParser
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.source_status import record_status

SOURCE_ID = "vyus_holdings"
SOURCE_URL = "https://stockanalysis.com/quote/etr/VYUS/holdings/"
OUTPUT_FILE = ROOT / "data" / "vyus_tickers.csv"
EXPECTED_COUNT = 25


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.depth = 0
        self.in_row = False
        self.in_cell = False
        self.cell = []
        self.row = []
        self.rows = []

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.depth += 1
        elif self.depth and tag == "tr":
            self.in_row, self.row = True, []
        elif self.depth and self.in_row and tag in ("td", "th"):
            self.in_cell, self.cell = True, []
        elif self.depth and self.in_cell and tag == "br":
            self.cell.append(" ")

    def handle_data(self, data):
        if self.depth and self.in_row and self.in_cell:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if self.depth and tag in ("td", "th") and self.in_cell:
            self.row.append(" ".join("".join(self.cell).split()))
            self.in_cell = False
        elif self.depth and tag == "tr" and self.in_row:
            if self.row:
                self.rows.append(self.row)
            self.in_row = False
        elif tag == "table" and self.depth:
            self.depth -= 1


def fetch_tickers():
    req = Request(SOURCE_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=30) as response:
        html = response.read().decode("utf-8", errors="replace")

    parser = TableParser()
    parser.feed(html)
    header_index = symbol_index = None
    for i, row in enumerate(parser.rows):
        normalized = [cell.strip().lower() for cell in row]
        if "symbol" in normalized:
            header_index, symbol_index = i, normalized.index("symbol")
            break
        if "ticker" in normalized:
            header_index, symbol_index = i, normalized.index("ticker")
            break

    if header_index is None:
        raise RuntimeError("Could not find a holdings table with a Symbol/Ticker column; CSV and Sheet left unchanged.")

    tickers = []
    for row in parser.rows[header_index + 1:]:
        if symbol_index >= len(row):
            continue
        ticker = row[symbol_index].strip().upper()
        if re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", ticker) and ticker not in tickers:
            tickers.append(ticker)
        if len(tickers) == EXPECTED_COUNT:
            break

    if len(tickers) != EXPECTED_COUNT:
        raise RuntimeError(f"Expected exactly {EXPECTED_COUNT} public holdings; found {len(tickers)}. CSV and Sheet left unchanged.")
    return tickers


def write_tickers_csv(tickers, output_file=OUTPUT_FILE):
    """Atomically persist a validated VYUS ticker list for the DSR source loader."""
    if len(tickers) != EXPECTED_COUNT or len(set(tickers)) != EXPECTED_COUNT:
        raise ValueError(f"Expected {EXPECTED_COUNT} unique VYUS tickers before writing CSV.")
    output_file = Path(output_file)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    temporary_file = output_file.with_suffix(output_file.suffix + ".tmp")
    try:
        with temporary_file.open("w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow(["ticker"])
            writer.writerows([[ticker] for ticker in tickers])
        temporary_file.replace(output_file)
    finally:
        if temporary_file.exists():
            temporary_file.unlink()
    print(f"Persisted {len(tickers)} validated VYUS tickers to {output_file}.", flush=True)


def main():
    print("VYUS stage 1/3: fetching and parsing StockAnalysis holdings.", flush=True)
    try:
        tickers = fetch_tickers()
    except Exception as exc:
        record_status(SOURCE_ID, "failure", f"StockAnalysis fetch/parse stage failed: {exc}")
        raise RuntimeError(f"StockAnalysis fetch/parse stage failed: {exc}") from exc
    print(f"VYUS stage 1/3 complete: {len(tickers)} tickers retrieved.", flush=True)

    # The DSR CSV is written before the independent Sheets sync. A Sheets
    # outage must not discard a successfully retrieved source refresh.
    write_tickers_csv(tickers)
    record_status(SOURCE_ID, "success", f"{len(tickers)} gevalideerde VYUS-tickers opgehaald.")

    # Google Sheets is a separate downstream destination. Missing Sheets
    # credentials must not prevent a valid DSR source CSV from being refreshed.
    endpoint = os.environ.get("VYUS_GS_WEBAPP_URL", "").strip()
    secret = os.environ.get("VYUS_GS_SECRET", "").strip()
    if not endpoint or not secret:
        raise RuntimeError(
            "VYUS CSV refreshed, but Google Sheets sync skipped: "
            "missing VYUS_GS_WEBAPP_URL or VYUS_GS_SECRET."
        )

    payload = json.dumps({"secret": secret, "tickers": tickers}).encode("utf-8")
    req = Request(endpoint, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    print("VYUS stage 2/3: posting holdings to Google Apps Script.", flush=True)
    try:
        with urlopen(req, timeout=45) as response:
            result = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Google Apps Script POST stage failed: {exc}") from exc

    if not result.get("success") or result.get("count") != EXPECTED_COUNT:
        raise RuntimeError(f"Google Apps Script response validation failed: {result}")
    print(f"SUCCESS: imported {result['count']} VYUS tickers into {result.get('sheet', 'target sheet')}.")
    print(", ".join(tickers))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
