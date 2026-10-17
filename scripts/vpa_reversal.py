#!/usr/bin/env python3
"""Flag daily VPA reversal setups among tickers returned by the Finviz screener.

Signal on the latest available daily bar:
- At least three immediately preceding red candles.
- Each red candle closes below the prior candle's close.
- Volume on the latest red candle is below volume on the first candle in the run.
- Trigger candle is green and its volume exceeds the latest red candle's volume.
"""
import csv
import json
import re
import sys
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlparse
from urllib.request import Request, urlopen

CONFIG_URL = "https://raw.githubusercontent.com/Melief/daily-stock-radar/main/finviz_url.txt"
TIMEOUT_SECONDS = 20
MIN_RED_BARS = 3
OUTPUT_CSV = "vpa_reversal.csv"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/129.0.0.0 Safari/537.36"


def fetch(url):
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/json,*/*"})
    with urlopen(req, timeout=TIMEOUT_SECONDS) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


class TickerLinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tickers, self.seen = [], set()

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href", "")
        parsed = urlparse(href)
        ticker = parse_qs(parsed.query).get("t", [""])[0].strip().upper()
        if re.search(r"(?:^|/)(?:stock|quote)$", parsed.path) and re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", ticker):
            if ticker not in self.seen:
                self.seen.add(ticker)
                self.tickers.append(ticker)


def get_daily_bars(ticker):
    # Stooq daily CSV avoids Yahoo Finance's frequent HTTP 429 rate limits in hosted runners.
    symbol = ticker.lower().replace(".", "-") + ".us"
    url = f"https://stooq.com/q/d/l/?s={quote(symbol)}&i=d"
    body = fetch(url)
    if not body.strip() or body.lstrip().lower().startswith("no data"):
        raise ValueError(f"No daily data returned by Stooq for {ticker}")
    rows = list(csv.DictReader(body.splitlines()))
    bars = []
    for row in rows[-10:]:
        try:
            open_price = float(row["Open"])
            close_price = float(row["Close"])
            volume = float(row["Volume"])
        except (KeyError, TypeError, ValueError):
            continue
        bars.append({"open": open_price, "close": close_price, "volume": volume})
    if not bars:
        raise ValueError(f"No usable daily OHLCV data returned by Stooq for {ticker}; response starts: {body[:120]!r}")
    return bars

def vpa_signal(bars):
    # Last bar is the trigger; the preceding bars must form a run of lower-closing red candles.
    if len(bars) < MIN_RED_BARS + 1:
        return False, "Insufficient daily history"
    trigger = bars[-1]
    last_red = bars[-2]
    if not (trigger["close"] > trigger["open"] and trigger["volume"] > last_red["volume"]):
        return False, "No green high-volume trigger"

    run_start = len(bars) - 2
    # Extend backwards over red candles whose closes descend consecutively.
    while run_start > 0:
        current = bars[run_start]
        previous = bars[run_start - 1]
        if current["close"] < current["open"] and current["close"] < previous["close"]:
            run_start -= 1
        else:
            break

    # Include the first red candle in the sequence; each subsequent red candle must close lower.
    red_bars = bars[run_start:-1]
    if len(red_bars) < MIN_RED_BARS:
        return False, "Fewer than 3 qualifying red candles"
    if not all(b["close"] < b["open"] for b in red_bars):
        return False, "Red-candle sequence interrupted"
    if not all(red_bars[i]["close"] < red_bars[i - 1]["close"] for i in range(1, len(red_bars))):
        return False, "Closes did not decline consecutively"
    if not (red_bars[-1]["volume"] < red_bars[0]["volume"]):
        return False, "Volume did not contract across red sequence"
    return True, f"{len(red_bars)} red candles; volume contraction and green trigger confirmed"


def main():
    print("Fetching current Finviz screener tickers...")
    try:
        screener_url = fetch(CONFIG_URL).strip()
        parsed = urlparse(screener_url)
        if parsed.scheme != "https" or parsed.netloc not in ("finviz.com", "www.finviz.com"):
            raise ValueError("Invalid Finviz URL in finviz_url.txt")
        html = fetch(screener_url)
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        print(f"ERROR fetching Finviz screener: {exc}", file=sys.stderr)
        return 1

    parser = TickerLinkParser()
    parser.feed(html)
    tickers = parser.tickers
    if not tickers:
        print("ERROR: Finviz returned no extractable tickers; refusing to create misleading output.", file=sys.stderr)
        return 1

    rows = []
    for index, ticker in enumerate(tickers):
        try:
            bars = get_daily_bars(ticker)
            signal, note = vpa_signal(bars)
            rows.append({"Ticker": ticker, "VPA Reversal": "JA" if signal else "NEE", "Toelichting": note})
            print(f"{ticker}: {'JA' if signal else 'NEE'} — {note}")
        except (HTTPError, URLError, TimeoutError, ValueError, KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            rows.append({"Ticker": ticker, "VPA Reversal": "ONBEKEND", "Toelichting": f"Datafout: {exc}"})
            print(f"{ticker}: ONBEKEND — {exc}")
        if index < len(tickers) - 1:
            time.sleep(0.25)

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=["Ticker", "VPA Reversal", "Toelichting"])
        writer.writeheader()
        writer.writerows(rows)

    yes = sum(row["VPA Reversal"] == "JA" for row in rows)
    unknown = sum(row["VPA Reversal"] == "ONBEKEND" for row in rows)
    print(f"\nDone: {len(rows)} tickers checked; {yes} VPA signal(s); {unknown} unknown result(s).")
    print(f"Results written to {OUTPUT_CSV}.")
    return 0 if unknown == 0 else 0


if __name__ == "__main__":
    sys.exit(main())
