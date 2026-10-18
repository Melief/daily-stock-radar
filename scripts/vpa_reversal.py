#!/usr/bin/env python3
"""Check current Finviz tickers for a daily VPA reversal setup."""
import csv
import io
import json
import re
import random
import sys
import time
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlparse
from urllib.request import Request, urlopen

CONFIG_URL = "https://raw.githubusercontent.com/Melief/daily-stock-radar/main/finviz_url.txt"
TIMEOUT_SECONDS = 25
MIN_RED_BARS = 3
OUTPUT_CSV = "vpa_reversal.csv"
MAX_RETRIES = 4
YAHOO_RATE_LIMITED = False
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/129.0.0.0 Safari/537.36"


class RateLimitError(RuntimeError):
    """Raised when a provider keeps rate-limiting requests after one delayed retry."""


def fetch(url):
    """Fetch with cautious backoff for rate limits and temporary server errors."""
    last_error = None
    for attempt in range(MAX_RETRIES):
        req = Request(url, headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/json,text/csv,*/*",
        })
        try:
            with urlopen(req, timeout=TIMEOUT_SECONDS) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                return response.read().decode(charset, errors="replace")
        except HTTPError as exc:
            last_error = exc
            if exc.code == 429:
                if attempt >= 2:
                    raise RateLimitError(f"HTTP 429 persisted after two delayed retries: {url}") from exc
                retry_after = exc.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    wait = min(300, int(retry_after))
                else:
                    wait = random.uniform(75, 120) if attempt == 0 else random.uniform(150, 240)
                print(f"HTTP 429; pausing {wait:.0f}s before one retry...", file=sys.stderr)
                time.sleep(wait)
                continue
            if exc.code not in (500, 502, 503, 504):
                raise
            wait = 2 ** (attempt + 1)
        except (URLError, TimeoutError) as exc:
            last_error = exc
            wait = 2 ** (attempt + 1)
        if attempt < MAX_RETRIES - 1:
            print(f"Temporary request error ({last_error}); retrying in {wait}s...", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError(f"Request failed after {MAX_RETRIES} attempts: {last_error}")


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


def get_stooq_bars(ticker):
    """Try Stooq first to reduce Yahoo requests; only daily open, close and volume are needed."""
    symbol = ticker.lower().replace(".", "-") + ".us"
    url = f"https://stooq.com/q/d/l/?s={quote(symbol)}&i=d"
    content = fetch(url)
    reader = csv.DictReader(io.StringIO(content))
    bars = []
    for row in reader:
        try:
            open_price = float(row["Open"])
            close_price = float(row["Close"])
            volume = float(row["Volume"])
            if open_price > 0 and close_price > 0 and volume >= 0:
                bars.append({"open": open_price, "close": close_price, "volume": volume})
        except (KeyError, TypeError, ValueError):
            continue
    if not bars:
        raise ValueError(f"Stooq returned no usable daily OHLCV for {ticker}")
    return bars[-10:]


def get_yahoo_bars(ticker):
    """Fallback source for daily OHLCV; use cautious backoff after HTTP 429."""
    symbol = ticker.replace(".", "-")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol)}?range=10d&interval=1d&events=history"
    payload = json.loads(fetch(url))
    chart = payload.get("chart", {})
    if chart.get("error") or not chart.get("result"):
        raise ValueError(f"No Yahoo chart data for {ticker}: {chart.get('error')}")
    result = chart["result"][0]
    quote_data = result["indicators"]["quote"][0]
    bars = []
    opens = quote_data.get("open", [])
    closes = quote_data.get("close", [])
    volumes = quote_data.get("volume", [])
    for i in range(len(result.get("timestamp", []))):
        if i < len(opens) and i < len(closes) and i < len(volumes):
            if opens[i] is not None and closes[i] is not None and volumes[i] is not None:
                bars.append({"open": opens[i], "close": closes[i], "volume": volumes[i]})
    if not bars:
        raise ValueError(f"No usable Yahoo daily OHLCV for {ticker}")
    return bars


def get_daily_bars(ticker):
    """Use Yahoo Finance for daily OHLCV."""
    return get_yahoo_bars(ticker)


def vpa_signal(bars):
    # Latest bar is the trigger; the preceding bars must be descending red candles.
    if len(bars) < MIN_RED_BARS + 1:
        return False, "Insufficient daily history"
    trigger = bars[-1]
    if not (trigger["close"] > trigger["open"] and trigger["volume"] > bars[-2]["volume"]):
        return False, "No green high-volume trigger"

    run_start = len(bars) - 2
    while run_start > 0:
        current, previous = bars[run_start], bars[run_start - 1]
        if current["close"] < current["open"] and current["close"] < previous["close"]:
            run_start -= 1
        else:
            break

    red_bars = bars[run_start:-1]
    if len(red_bars) < MIN_RED_BARS:
        return False, "Fewer than 3 qualifying red candles"
    if not all(bar["close"] < bar["open"] for bar in red_bars):
        return False, "Red-candle sequence interrupted"
    if not all(red_bars[i]["close"] < red_bars[i - 1]["close"] for i in range(1, len(red_bars))):
        return False, "Closes did not decline consecutively"
    if red_bars[-1]["volume"] >= red_bars[0]["volume"]:
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
    except (HTTPError, URLError, TimeoutError, RuntimeError, ValueError) as exc:
        print(f"ERROR fetching Finviz screener: {exc}", file=sys.stderr)
        return 1

    parser = TickerLinkParser()
    parser.feed(html)
    tickers = parser.tickers
    if not tickers:
        print("ERROR: Finviz returned no extractable tickers; refusing to create misleading output.", file=sys.stderr)
        return 1

    rows = []
    print(f"Found {len(tickers)} Finviz tickers. Checking daily bars from Yahoo Finance; unavailable tickers will be marked ONBEKEND and skipped.")
    for index, ticker in enumerate(tickers):
        try:
            bars = get_daily_bars(ticker)
            signal, note = vpa_signal(bars)
            rows.append({"Ticker": ticker, "VPA Reversal": "JA" if signal else "NEE", "Toelichting": note})
            print(f"{ticker}: {'JA' if signal else 'NEE'} — {note}")
        except (HTTPError, URLError, TimeoutError, RuntimeError, ValueError, KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            rows.append({"Ticker": ticker, "VPA Reversal": "ONBEKEND", "Toelichting": f"Datafout: {exc}"})
            print(f"{ticker}: ONBEKEND — {exc}")
            if isinstance(exc, RateLimitError):
                for remaining_ticker in tickers[index + 1:]:
                    rows.append({
                        "Ticker": remaining_ticker,
                        "VPA Reversal": "ONBEKEND",
                        "Toelichting": "Overgeslagen: databron gaf Too Many Requests; geen verdere verzoeken verstuurd",
                    })
                print("Rate limit detected; stopping further ticker requests to avoid hammering providers.")
                break
        if index < len(tickers) - 1:
            pause = random.uniform(20, 35)
            print(f"Pausing {pause:.1f}s before next ticker.")
            time.sleep(pause)

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=["Ticker", "VPA Reversal", "Toelichting"])
        writer.writeheader()
        writer.writerows(rows)

    yes = sum(row["VPA Reversal"] == "JA" for row in rows)
    unknown = sum(row["VPA Reversal"] == "ONBEKEND" for row in rows)
    print(f"\nDone: {len(rows)} tickers checked; {yes} VPA signal(s); {unknown} unknown result(s).")
    print(f"Results written to {OUTPUT_CSV}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
