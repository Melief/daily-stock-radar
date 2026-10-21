#!/usr/bin/env python3
"""Import the 25 publicly displayed VYUS holdings from StockAnalysis."""
import json
import os
import re
import sys
from html.parser import HTMLParser
from urllib.request import Request, urlopen

SOURCE_URL = "https://stockanalysis.com/quote/etr/VYUS/holdings/"
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
        raise RuntimeError("Could not find a holdings table with a Symbol/Ticker column; Sheet left unchanged.")

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
        raise RuntimeError(f"Expected exactly {EXPECTED_COUNT} public holdings; found {len(tickers)}. Sheet left unchanged.")
    return tickers


def main():
    endpoint = os.environ.get("VYUS_GS_WEBAPP_URL", "").strip()
    secret = os.environ.get("VYUS_GS_SECRET", "").strip()
    if not endpoint or not secret:
        raise RuntimeError("Missing GitHub variable VYUS_GS_WEBAPP_URL or secret VYUS_GS_SECRET.")

    tickers = fetch_tickers()
    payload = json.dumps({"secret": secret, "tickers": tickers}).encode("utf-8")
    req = Request(endpoint, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(req, timeout=45) as response:
        result = json.loads(response.read().decode("utf-8"))

    if not result.get("success") or result.get("count") != EXPECTED_COUNT:
        raise RuntimeError(f"Apps Script rejected the import: {result}")
    print(f"SUCCESS: imported {result['count']} VYUS tickers into {result.get('sheet', 'target sheet')}.")
    print(", ".join(tickers))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
