#!/usr/bin/env python3
"""Build daily Heikin-Ashi and SMA signals for the DSR ticker universe.

Inputs:
  tickers.txt
  finviz_tickers.csv
  data/vyus_tickers.csv
Optional:
  data/tradingview_tickers.csv (column: ticker, or one ticker per line)

The latest returned daily bar is treated as the latest completed session. The
workflow is scheduled after the US market close; weekends/holidays are handled
by the data provider's last available bar.
"""
from __future__ import annotations

import csv
import io
import os
import sys
import time
from pathlib import Path

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "ha_signals.csv"
OPTIONAL_SOURCES = [
    ROOT / "tickers.txt",
    ROOT / "finviz_tickers.csv",
    ROOT / "data" / "vyus_tickers.csv",
    ROOT / "data" / "tradingview_tickers.csv",
]


def read_tickers(path: Path) -> list[str]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8-sig").strip()
    if not text:
        return []
    # CSV files may have a header; plain text files may contain one symbol per line.
    try:
        rows = list(csv.reader(io.StringIO(text)))
        values = []
        for row in rows:
            if not row:
                continue
            value = row[0].strip().upper()
            if value and value not in {"TICKER", "SYMBOL"}:
                values.append(value)
        return values
    except csv.Error:
        return [line.strip().upper() for line in text.splitlines() if line.strip()]


def ticker_universe() -> list[str]:
    symbols: set[str] = set()
    for path in OPTIONAL_SOURCES:
        symbols.update(read_tickers(path))
    return sorted(s for s in symbols if s and s.isascii())


def calculate_signals(symbol: str) -> dict | None:
    # Download enough daily history for reliable SMA50 and HA initialization.
    last_error = None
    for attempt in range(3):
        try:
            hist = yf.download(
                symbol, period="6mo", interval="1d", auto_adjust=False,
                progress=False, threads=False, timeout=25
            )
            if hist is None or hist.empty:
                raise ValueError("geen koershistorie ontvangen")
            if isinstance(hist.columns, pd.MultiIndex):
                hist.columns = hist.columns.get_level_values(0)
            required = ["Open", "High", "Low", "Close"]
            if not all(c in hist.columns for c in required):
                raise ValueError("OHLC-kolommen ontbreken")
            df = hist[required].dropna().copy()
            if len(df) < 55:
                raise ValueError(f"onvoldoende historie: {len(df)} handelsdagen")

            # Standard Heikin-Ashi construction, calculated chronologically.
            ha_close = (df["Open"] + df["High"] + df["Low"] + df["Close"]) / 4.0
            ha_open = pd.Series(index=df.index, dtype="float64")
            ha_open.iloc[0] = (df["Open"].iloc[0] + df["Close"].iloc[0]) / 2.0
            for i in range(1, len(df)):
                ha_open.iloc[i] = (ha_open.iloc[i - 1] + ha_close.iloc[i - 1]) / 2.0
            ha_low = pd.concat([df["Low"], ha_open, ha_close], axis=1).min(axis=1)

            sma20 = df["Close"].rolling(20).mean()
            sma50 = df["Close"].rolling(50).mean()
            latest = df.index[-1]
            # A tiny tolerance avoids false negatives from floating point arithmetic.
            ha_open_equals_low = abs(float(ha_open.iloc[-1]) - float(ha_low.iloc[-1])) <= 1e-8

            return {
                "ticker": symbol,
                "date": pd.Timestamp(latest).strftime("%Y-%m-%d"),
                "close": round(float(df["Close"].iloc[-1]), 4),
                "sma20": round(float(sma20.iloc[-1]), 4),
                "sma50": round(float(sma50.iloc[-1]), 4),
                "ha_open": round(float(ha_open.iloc[-1]), 4),
                "ha_high": round(float(max(float(df["High"].iloc[-1]), ha_open.iloc[-1], ha_close.iloc[-1])), 4),
                "ha_low": round(float(ha_low.iloc[-1]), 4),
                "ha_close": round(float(ha_close.iloc[-1]), 4),
                "ha_open_equals_low": bool(ha_open_equals_low),
                "above_sma20": bool(df["Close"].iloc[-1] > sma20.iloc[-1]),
                "above_sma50": bool(df["Close"].iloc[-1] > sma50.iloc[-1]),
                "status": "OK",
            }
        except Exception as exc:
            last_error = str(exc)
            if attempt < 2:
                time.sleep(2 ** attempt)
    return {
        "ticker": symbol,
        "date": "",
        "close": "",
        "sma20": "",
        "sma50": "",
        "ha_open": "",
        "ha_high": "",
        "ha_low": "",
        "ha_close": "",
        "ha_open_equals_low": "",
        "above_sma20": "",
        "above_sma50": "",
        "status": f"ONBEKEND: {last_error}",
    }


def main() -> int:
    tickers = ticker_universe()
    if not tickers:
        print("Geen tickers gevonden in de bronbestanden.", file=sys.stderr)
        return 1

    rows = []
    for i, ticker in enumerate(tickers, 1):
        print(f"[{i}/{len(tickers)}] {ticker}")
        result = calculate_signals(ticker)
        if result:
            rows.append(result)
        time.sleep(0.4)  # reduce the chance of provider throttling

    OUT.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(OUT, index=False)
    ok = sum(row["status"] == "OK" for row in rows)
    unknown = len(rows) - ok
    print(f"Controle voltooid: {ok} tickers OK, {unknown} ONBEKEND. Bestand: {OUT}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
