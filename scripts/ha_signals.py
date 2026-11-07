#!/usr/bin/env python3
"""Daily DSR Heikin-Ashi, SMA20/50 and volume checks.

All configured DSR sources are unioned and deduplicated. Original source files
remain untouched. Missing market data is recorded as ONBEKEND, never silently
dropped. SMA200 is intentionally not calculated.
"""
from __future__ import annotations

import csv
import re
import sys
import time
from pathlib import Path

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "ha_signals.csv"
COVERAGE_OUT = ROOT / "data" / "ha_source_coverage.csv"
HISTORY_PERIOD = "1y"
HA_LOOKBACK = 30

# Canonical source list. Each source file is retained in its original format.
SOURCES = [
    ("Sector Top Tickers", ROOT / "tickers.txt", "text"),
    ("Finviz", ROOT / "finviz_tickers.csv", "csv"),
    ("TradingView screener", ROOT / "data" / "tradingview_screener_tickers.csv", "csv"),
    ("Simpel Monsters", ROOT / "data" / "simpel_monsters_tickers.csv", "csv"),
    ("Follow Thrue", ROOT / "data" / "follow_thrue_tickers.csv", "csv"),
    ("VYUS holdings", ROOT / "data" / "vyus_tickers.csv", "csv"),
]
# The existing DSR rule: these two sources must pass both moving averages.
SMA_FILTER_SOURCES = {"Sector Top Tickers", "VYUS holdings"}


def read_source(path: Path, fmt: str) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"Verplicht bronbestand ontbreekt: {path.relative_to(ROOT)}")
    content = path.read_text(encoding="utf-8-sig").strip()
    if not content:
        return []
    if fmt == "csv":
        result = []
        for row in csv.DictReader(content.splitlines()):
            # All current DSR CSV exports use a Ticker column.
            value = (row.get("ticker") or row.get("Ticker") or row.get("symbol") or "").strip().upper()
            if value and value not in {"TICKER", "SYMBOL"}:
                result.append(value)
        return result
    return [
        token.upper()
        for token in re.split(r"[\s,;]+", content)
        if token.strip() and token.strip().upper() not in {"TICKER", "SYMBOL"}
    ]


def load_universe():
    ticker_sources: dict[str, set[str]] = {}
    source_counts: dict[str, int] = {}
    for source_name, path, fmt in SOURCES:
        tickers = read_source(path, fmt)
        source_counts[source_name] = len(set(tickers))
        for ticker in tickers:
            ticker_sources.setdefault(ticker, set()).add(source_name)
    return ticker_sources, source_counts


def make_ha(frame: pd.DataFrame):
    ha_close = (frame["Open"] + frame["High"] + frame["Low"] + frame["Close"]) / 4.0
    ha_open = pd.Series(index=frame.index, dtype="float64")
    ha_open.iloc[0] = (float(frame["Open"].iloc[0]) + float(frame["Close"].iloc[0])) / 2.0
    for i in range(1, len(frame)):
        ha_open.iloc[i] = (ha_open.iloc[i - 1] + ha_close.iloc[i - 1]) / 2.0
    ha_high = pd.concat([frame["High"], ha_open, ha_close], axis=1).max(axis=1)
    ha_low = pd.concat([frame["Low"], ha_open, ha_close], axis=1).min(axis=1)
    return ha_open, ha_high, ha_low, ha_close


def unknown_row(ticker: str, sources: set[str], reason: str) -> dict:
    return {
        "ticker": ticker,
        "sources": ";".join(sorted(sources)),
        "date": "",
        "close": "",
        "ha_day_type": "ONBEKEND",
        "distance_from_low_pct": "",
        "ha_open": "",
        "ha_high": "",
        "ha_low": "",
        "ha_close": "",
        "ha_open_equals_low": "",
        "ha_strong_signal": "",
        "ha_open_equals_high": "",
        "ha_strong_down_signal": "",
        "sma20": "",
        "sma50": "",
        "above_sma20": "",
        "above_sma50": "",
        "sma20_50_filter_required": bool(sources & SMA_FILTER_SOURCES),
        "sma20_50_filter_pass": "ONBEKEND" if sources & SMA_FILTER_SOURCES else "NVT",
        "daily_volume": "",
        "average_volume_30d": "",
        "volume_vs_30d_avg_pct": "",
        "volume_trend_3d": "ONBEKEND",
        "status": f"ONBEKEND: {reason}",
    }


def calculate(ticker: str, sources: set[str]) -> dict:
    try:
        daily = yf.download(
            ticker, period=HISTORY_PERIOD, interval="1d", auto_adjust=False,
            progress=False, threads=False, timeout=25
        )
        if daily is None or daily.empty:
            raise ValueError("geen dagkoersen ontvangen")
        if isinstance(daily.columns, pd.MultiIndex):
            daily.columns = daily.columns.get_level_values(0)
        needed = ["Open", "High", "Low", "Close", "Volume"]
        if not all(c in daily.columns for c in needed):
            raise ValueError("OHLCV-kolommen ontbreken")
        daily = daily[needed].dropna(subset=["Open", "High", "Low", "Close"])
        daily = daily[daily["Volume"].notna()]
        if len(daily) < 55:
            raise ValueError(f"onvoldoende historie voor SMA50/volume: {len(daily)} handelsdagen")

        # The current trading session is built from 5-minute bars when available.
        # The SMA and 30-day volume baseline use completed daily sessions only.
        try:
            intra = yf.download(
                ticker, period="5d", interval="5m", auto_adjust=False,
                progress=False, threads=False, timeout=25
            )
            if intra is not None and not intra.empty:
                if isinstance(intra.columns, pd.MultiIndex):
                    intra.columns = intra.columns.get_level_values(0)
                if all(c in intra.columns for c in needed):
                    idx = pd.DatetimeIndex(intra.index)
                    if idx.tz is None:
                        idx = idx.tz_localize("America/New_York")
                    else:
                        idx = idx.tz_convert("America/New_York")
                    today_et = pd.Timestamp.now(tz="America/New_York").date()
                    mask = [d == today_et for d in idx.date]
                    current = intra.loc[mask, needed].dropna(subset=["Open", "High", "Low", "Close"])
                else:
                    current = pd.DataFrame()
            else:
                current = pd.DataFrame()
        except Exception as exc:
            print(f"{ticker}: intradaydata niet beschikbaar; dagdata gebruikt ({exc})")
            current = pd.DataFrame()

        today_et = pd.Timestamp.now(tz="America/New_York").date()
        daily_dates = pd.DatetimeIndex(daily.index)
        if daily_dates.tz is not None:
            daily_dates = daily_dates.tz_convert("America/New_York").tz_localize(None)
        daily_dates_only = [d.date() for d in daily_dates]
        has_today_daily = bool(daily_dates_only and daily_dates_only[-1] == today_et)

        if not current.empty:
            # Exclude a possibly partial daily bar for today; aggregate 5-minute bars instead.
            completed = daily.iloc[:-1].copy() if has_today_daily else daily.copy()
            session = pd.DataFrame([{
                "Open": float(current["Open"].iloc[0]),
                "High": float(current["High"].max()),
                "Low": float(current["Low"].min()),
                "Close": float(current["Close"].iloc[-1]),
                "Volume": float(current["Volume"].sum()),
            }], index=[pd.Timestamp(today_et)])
            latest = session.iloc[0]
            signal_frame = pd.concat([completed.tail(HA_LOOKBACK), session])
            is_intraday = True
        else:
            completed = daily.copy()
            latest = completed.iloc[-1]
            signal_frame = completed.tail(HA_LOOKBACK)
            is_intraday = False

        if len(completed) < 50:
            raise ValueError("minder dan 50 afgeronde handelsdagen voor SMA50")

        # SMA20/SMA50 use the latest completed close, not an incomplete intraday close.
        sma20_series = completed["Close"].rolling(20).mean()
        sma50_series = completed["Close"].rolling(50).mean()
        sma20 = float(sma20_series.iloc[-1])
        sma50 = float(sma50_series.iloc[-1])
        compare_close = float(latest["Close"])
        above20 = compare_close > sma20
        above50 = compare_close > sma50

        ha_open, ha_high, ha_low, ha_close = make_ha(signal_frame)
        ho, hh, hl, hc = map(float, (ha_open.iloc[-1], ha_high.iloc[-1], ha_low.iloc[-1], ha_close.iloc[-1]))
        day_type = "UP" if hc > ho else "DOWN" if hc < ho else "FLAT"
        distance = (hc - hl) / hl * 100.0 if hl > 0 else float("nan")
        equal_low = abs(ho - hl) <= 1e-8
        equal_high = abs(ho - hh) <= 1e-8

        # Today's volume may be partial during market hours. Volume trend is based
        # only on completed daily sessions to avoid comparing partial volume.
        daily_volume = float(latest["Volume"])
        if is_intraday:
            daily_volume = float(latest["Volume"])
        avg30 = float(completed["Volume"].tail(30).mean())
        baseline = completed["Volume"].tail(30)
        if len(baseline) >= 3:
            v0, v1, v2 = map(float, baseline.iloc[-3:])
            trend = "STIJGEND" if v0 < v1 < v2 else "DALEND" if v0 > v1 > v2 else "GEMENGD"
        else:
            trend = "ONBEKEND"
        volume_ratio = ((daily_volume / avg30) - 1.0) * 100.0 if avg30 > 0 else float("nan")

        requires_filter = bool(sources & SMA_FILTER_SOURCES)
        filter_pass = bool(above20 and above50) if requires_filter else "NVT"
        return {
            "ticker": ticker,
            "sources": ";".join(sorted(sources)),
            "date": pd.Timestamp(signal_frame.index[-1]).strftime("%Y-%m-%d"),
            "close": round(compare_close, 4),
            "ha_day_type": day_type,
            "distance_from_low_pct": round(distance, 1),
            "ha_open": round(ho, 4),
            "ha_high": round(hh, 4),
            "ha_low": round(hl, 4),
            "ha_close": round(hc, 4),
            "ha_open_equals_low": bool(equal_low),
            "ha_strong_signal": bool(equal_low and day_type == "UP"),
            "ha_open_equals_high": bool(equal_high),
            "ha_strong_down_signal": bool(equal_high and day_type == "DOWN"),
            "sma20": round(sma20, 4),
            "sma50": round(sma50, 4),
            "above_sma20": bool(above20),
            "above_sma50": bool(above50),
            "sma20_50_filter_required": requires_filter,
            "sma20_50_filter_pass": filter_pass,
            "daily_volume": int(daily_volume),
            "average_volume_30d": int(avg30),
            "volume_vs_30d_avg_pct": round(volume_ratio, 1),
            "volume_trend_3d": trend,
            "status": "OK" if not is_intraday else "OK_INTRADAY",
        }
    except Exception as exc:
        return unknown_row(ticker, sources, str(exc))


def main() -> int:
    try:
        ticker_sources, source_counts = load_universe()
    except Exception as exc:
        print(f"Broncontrole mislukt: {exc}", file=sys.stderr)
        return 1
    if not ticker_sources:
        print("Geen tickers gevonden in DSR-bronbestanden.", file=sys.stderr)
        return 1

    print("Broncontrole:")
    for name, count in source_counts.items():
        print(f"  {name}: {count} unieke tickers")
    print(f"Gecombineerd: {len(ticker_sources)} unieke tickers")

    rows = []
    for i, ticker in enumerate(sorted(ticker_sources), 1):
        print(f"[{i}/{len(ticker_sources)}] {ticker}")
        rows.append(calculate(ticker, ticker_sources[ticker]))
        time.sleep(0.35)

    results = pd.DataFrame(rows)
    results.to_csv(OUT, index=False)

    # Explicit coverage audit: every ticker from every source must have a result row.
    coverage_rows = []
    result_tickers = set(results["ticker"].astype(str))
    for source_name, _, _ in SOURCES:
        source_tickers = [t for t, names in ticker_sources.items() if source_name in names]
        for ticker in sorted(source_tickers):
            match = results.loc[results["ticker"] == ticker]
            status = match.iloc[0]["status"] if not match.empty else "ONTBREEKT"
            coverage_rows.append({
                "source": source_name,
                "ticker": ticker,
                "ha_row_present": ticker in result_tickers,
                "ha_status": status,
            })
    pd.DataFrame(coverage_rows).to_csv(COVERAGE_OUT, index=False)

    ok = int(results["status"].astype(str).str.startswith("OK").sum())
    unknown = len(results) - ok
    missing = len(ticker_sources) - len(result_tickers)
    print(
        f"Controle voltooid: {ok} tickers OK, {unknown} ONBEKEND, "
        f"{missing} ontbrekende HA-rijen. Totaal {len(ticker_sources)} unieke tickers."
    )
    print(f"HA-uitvoer: {OUT}")
    print(f"Broncontrole: {COVERAGE_OUT}")
    # Unknown data is visible and does not invalidate coverage. Missing rows do.
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
