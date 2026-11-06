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
import sys
import time
from pathlib import Path

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "ha_signals.csv"
HA_LOOKBACK = 20
DOWNLOAD_PERIOD = "3mo"
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

    # The master ticker file is space-separated; CSV sources use the first column.
    if path.suffix.lower() == ".csv":
        rows = csv.reader(io.StringIO(text))
        values = []
        for row in rows:
            if not row:
                continue
            value = row[0].strip().upper()
            if value and value not in {"TICKER", "SYMBOL"}:
                values.append(value)
        return values

    import re
    return [
        token.upper()
        for token in re.split(r"[\s,;]+", text)
        if token.strip() and token.strip().upper() not in {"TICKER", "SYMBOL"}
    ]


def ticker_universe() -> list[str]:
    symbols: set[str] = set()
    for path in OPTIONAL_SOURCES:
        symbols.update(read_tickers(path))
    return sorted(s for s in symbols if s and s.isascii())


def calculate_signals(symbol: str) -> dict | None:
    # Three months provides enough history for SMA50; HA uses its latest 20 sessions.
    last_error = None
    for attempt in range(3):
        try:
            hist = yf.download(
                symbol, period=DOWNLOAD_PERIOD, interval="1d", auto_adjust=False,
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

            # Calculate Heikin-Ashi over the latest 20 sessions.
            # Starting at the first of these 20 sessions is sufficient for the
            # current signal; the recursive initialization effect decays by 2^-19.
            ha_df = df.tail(HA_LOOKBACK)
            ha_close = (
                ha_df["Open"] + ha_df["High"] + ha_df["Low"] + ha_df["Close"]
            ) / 4.0
            ha_open = pd.Series(index=ha_df.index, dtype="float64")
            ha_open.iloc[0] = (ha_df["Open"].iloc[0] + ha_df["Close"].iloc[0]) / 2.0
            for i in range(1, len(ha_df)):
                ha_open.iloc[i] = (ha_open.iloc[i - 1] + ha_close.iloc[i - 1]) / 2.0
            ha_low = pd.concat([ha_df["Low"], ha_open, ha_close], axis=1).min(axis=1)

            sma20 = df["Close"].rolling(20).mean()
            sma50 = df["Close"].rolling(50).mean()
            latest = df.index[-1]
            # HA day type is determined only by the Heikin-Ashi candle:
            # HA Close > HA Open = UP; HA Close < HA Open = DOWN.
            latest_ha_open = float(ha_open.iloc[-1])
            latest_ha_close = float(ha_close.iloc[-1])
            if latest_ha_close > latest_ha_open:
                ha_day_type = "UP"
            elif latest_ha_close < latest_ha_open:
                ha_day_type = "DOWN"
            else:
                ha_day_type = "FLAT"

            # HA-only distance from the latest Heikin-Ashi low:
            # (HA Close - HA Low) / HA Low * 100.
            distance_price = latest_ha_close
            distance_low = float(ha_low.iloc[-1])
            distance_from_low_pct = (
                (distance_price - distance_low) / distance_low * 100.0
                if distance_low > 0 else float("nan")
            )

            # A tiny tolerance avoids false negatives from floating point arithmetic.
            ha_open_equals_low = abs(latest_ha_open - distance_low) <= 1e-8
            latest_ha_high = float(max(ha_df["High"].iloc[-1], latest_ha_open, latest_ha_close))
            latest_ha_low = distance_low
            latest_date = pd.Timestamp(latest).strftime("%Y-%m-%d")
            latest_close = float(df["Close"].iloc[-1])

            # During the US regular session, replace the latest daily candle with
            # the developing session candle aggregated from 5-minute bars.
            # Outside the session (or if intraday data is unavailable), retain
            # the latest completed daily candle above.
            try:
                intra = yf.download(
                    symbol, period="5d", interval="5m", auto_adjust=False,
                    progress=False, threads=False, timeout=25
                )
                if intra is not None and not intra.empty:
                    if isinstance(intra.columns, pd.MultiIndex):
                        intra.columns = intra.columns.get_level_values(0)
                    if all(c in intra.columns for c in required):
                        idx = pd.DatetimeIndex(intra.index)
                        if idx.tz is None:
                            idx = idx.tz_localize("America/New_York")
                        else:
                            idx = idx.tz_convert("America/New_York")
                        today_et = pd.Timestamp.now(tz="America/New_York").date()
                        today_mask = [d == today_et for d in idx.date]
                        today_bars = intra.loc[today_mask, required].dropna()
                        prior_mask = [d < today_et for d in pd.to_datetime(df.index).date]
                        prior_days = df.loc[prior_mask, required].dropna()
                        if not today_bars.empty and len(prior_days) >= 55:
                            prior_ha_df = prior_days.tail(HA_LOOKBACK)
                            prior_ha_close = (
                                prior_ha_df["Open"] + prior_ha_df["High"] +
                                prior_ha_df["Low"] + prior_ha_df["Close"]
                            ) / 4.0
                            prior_ha_open = pd.Series(index=prior_ha_df.index, dtype="float64")
                            prior_ha_open.iloc[0] = (
                                prior_ha_df["Open"].iloc[0] + prior_ha_df["Close"].iloc[0]
                            ) / 2.0
                            for j in range(1, len(prior_ha_df)):
                                prior_ha_open.iloc[j] = (
                                    prior_ha_open.iloc[j - 1] + prior_ha_close.iloc[j - 1]
                                ) / 2.0

                            session_open = float(today_bars["Open"].iloc[0])
                            session_high = float(today_bars["High"].max())
                            session_low = float(today_bars["Low"].min())
                            session_close = float(today_bars["Close"].iloc[-1])
                            latest_ha_open = float(
                                (prior_ha_open.iloc[-1] + prior_ha_close.iloc[-1]) / 2.0
                            )
                            latest_ha_close = (
                                session_open + session_high + session_low + session_close
                            ) / 4.0
                            latest_ha_low = min(session_low, latest_ha_open, latest_ha_close)
                            latest_ha_high = max(session_high, latest_ha_open, latest_ha_close)
                            ha_day_type = (
                                "UP" if latest_ha_close > latest_ha_open else
                                "DOWN" if latest_ha_close < latest_ha_open else "FLAT"
                            )
                            distance_low = latest_ha_low
                            distance_price = latest_ha_close
                            distance_from_low_pct = (
                                (distance_price - distance_low) / distance_low * 100.0
                                if distance_low > 0 else float("nan")
                            )
                            ha_open_equals_low = abs(latest_ha_open - latest_ha_low) <= 1e-8
                            latest_date = today_et.strftime("%Y-%m-%d")
                            latest_close = session_close
            except Exception as intraday_exc:
                print(f"{symbol}: intraday niet beschikbaar, dagdata gebruikt: {intraday_exc}")

            return {
                "ticker": symbol,
                "date": latest_date,
                "close": round(latest_close, 4),
                "ha_day_type": ha_day_type,
                "distance_from_low_pct": round(distance_from_low_pct, 1),
                "sma20": round(float(sma20.iloc[-1]), 4),
                "sma50": round(float(sma50.iloc[-1]), 4),
                "ha_open": round(latest_ha_open, 4),
                "ha_high": round(latest_ha_high, 4),
                "ha_low": round(latest_ha_low, 4),
                "ha_close": round(latest_ha_close, 4),
                "ha_open_equals_low": bool(ha_open_equals_low),
                "ha_strong_signal": bool(ha_open_equals_low and latest_ha_close > latest_ha_open),
                "above_sma20": bool(latest_close > sma20.iloc[-1]),
                "above_sma50": bool(latest_close > sma50.iloc[-1]),
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
        "ha_day_type": "",
        "distance_from_low_pct": "",
        "sma20": "",
        "sma50": "",
        "ha_open": "",
        "ha_high": "",
        "ha_low": "",
        "ha_close": "",
        "ha_open_equals_low": "",
        "ha_strong_signal": "",
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
