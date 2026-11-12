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



# Breakout validation: use completed daily OHLC only, never an intraday bar.
PIVOT_LOOKBACK = 65
PIVOT_MIN_BASE = 15
PIVOT_MAX_BASE = 65
PIVOT_MIN_SEPARATION = 5
PIVOT_TOUCH_TOLERANCE = 0.015
BUY_ZONE_MAX_EXTENSION = 0.05


def detect_breakout(completed: pd.DataFrame, current_close: float | None = None) -> dict:
    """Find a tested consolidation ceiling and validate any breakout on daily closes.

    A pivot requires at least two distinct local-high tests, at least five sessions
    apart, within a 1.5% price band, with the first/last tests spanning 15-65 sessions.
    The pivot is the highest high in that resistance cluster. Confirmation requires
    a completed-session close above the pivot. Intraday prices are reported separately.
    """
    unknown = {
        "pivot_point": "",
        "pivot_test_count": 0,
        "pivot_first_test_date": "",
        "pivot_last_test_date": "",
        "breakout_date": "",
        "breakout_close": "",
        "breakout_volume": "",
        "breakout_rvol_21d": "",
        "breakout_status": "ONBEKEND",
        "distance_from_pivot_pct": "",
    }
    if completed is None or len(completed) < PIVOT_MIN_BASE + 5:
        return unknown

    frame = completed[["High", "Close", "Volume"]].dropna().tail(PIVOT_LOOKBACK).copy()
    if len(frame) < PIVOT_MIN_BASE + 5:
        return unknown

    # Local highs: the session high must be the maximum in a five-session window.
    highs = frame["High"].astype(float)
    peaks = []
    for i in range(2, len(frame) - 2):
        value = float(highs.iloc[i])
        window = highs.iloc[i - 2:i + 3]
        if value >= float(window.max()) and int((window == value).sum()) == 1:
            peaks.append((i, value))

    # Group nearby resistance tests into price clusters (maximum 1.5% range).
    clusters = []
    for peak in peaks:
        placed = False
        for cluster in clusters:
            prices = [p[1] for p in cluster]
            if max(prices + [peak[1]]) / min(prices + [peak[1]]) - 1.0 <= PIVOT_TOUCH_TOLERANCE:
                cluster.append(peak)
                placed = True
                break
        if not placed:
            clusters.append([peak])

    valid = []
    for cluster in clusters:
        if len(cluster) < 2:
            continue
        cluster = sorted(cluster, key=lambda item: item[0])
        first_i, last_i = cluster[0][0], cluster[-1][0]
        span = last_i - first_i
        if span < PIVOT_MIN_BASE or span > PIVOT_MAX_BASE:
            continue
        valid.append(cluster)

    if not valid:
        return unknown

    # Prefer the most recently tested valid resistance zone.
    cluster = max(valid, key=lambda c: c[-1][0])
    first_i, last_i = cluster[0][0], cluster[-1][0]
    pivot = max(price for _, price in cluster)
    dates = pd.DatetimeIndex(frame.index)
    first_date = pd.Timestamp(dates[first_i]).strftime("%Y-%m-%d")
    last_date = pd.Timestamp(dates[last_i]).strftime("%Y-%m-%d")

    post_test = frame.iloc[last_i + 1:]
    above = post_test[post_test["Close"].astype(float) > pivot]
    latest_close = float(frame["Close"].iloc[-1])
    result = {
        "pivot_point": round(pivot, 4),
        "pivot_test_count": len(cluster),
        "pivot_first_test_date": first_date,
        "pivot_last_test_date": last_date,
        "breakout_date": "",
        "breakout_close": "",
        "breakout_volume": "",
        "breakout_rvol_21d": "",
        "breakout_status": "NIET_UITGEBROKEN",
        "distance_from_pivot_pct": round((latest_close / pivot - 1.0) * 100.0, 2),
    }

    if not above.empty:
        breakout_idx = above.index[0]
        breakout_row = frame.loc[breakout_idx]
        breakout_date = pd.Timestamp(breakout_idx).strftime("%Y-%m-%d")
        breakout_volume = float(breakout_row["Volume"])
        volume_base = frame.loc[:breakout_idx, "Volume"].iloc[:-1].tail(21)
        breakout_rvol = breakout_volume / float(volume_base.mean()) if len(volume_base) >= 5 and float(volume_base.mean()) > 0 else float("nan")
        result.update({
            "breakout_date": breakout_date,
            "breakout_close": round(float(breakout_row["Close"]), 4),
            "breakout_volume": int(breakout_volume),
            "breakout_rvol_21d": round(breakout_rvol, 3) if not pd.isna(breakout_rvol) else "",
        })
        if latest_close <= pivot:
            result["breakout_status"] = "MISLUKT"
        elif latest_close <= pivot * (1.0 + BUY_ZONE_MAX_EXTENSION):
            result["breakout_status"] = "BEVESTIGD_KOOPZONE"
        else:
            result["breakout_status"] = "BEVESTIGD_UITGEREKT"

    if current_close is not None and float(current_close) > pivot and latest_close <= pivot:
        result["breakout_status"] = "INTRADAY_BOVEN_PIVOT_NIET_BEVESTIGD"
    return result

def unknown_row(ticker: str, sources: set[str], reason: str) -> dict:
    return {
        "ticker": ticker,
        "sector": "",
        "industry": "",
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
        "average_volume_5d": "",
        "average_volume_21d": "",
        "rvol_5_21": "",
        "rvol_5_21_label": "",
        "volume_trend_3d": "ONBEKEND",
        "pivot_point": "",
        "pivot_test_count": 0,
        "pivot_first_test_date": "",
        "pivot_last_test_date": "",
        "breakout_date": "",
        "breakout_close": "",
        "breakout_volume": "",
        "breakout_rvol_21d": "",
        "breakout_status": "ONBEKEND",
        "distance_from_pivot_pct": "",
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
        # SMA and RVOL use completed daily sessions only.
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
            # Yahoo daily data can contain today's still-forming bar even when
            # intraday data is unavailable. Keep it for the current signal, but
            # never include it in completed-session averages or volume trend.
            if has_today_daily:
                completed = daily.iloc[:-1].copy()
                latest = daily.iloc[-1]
                signal_frame = pd.concat([completed.tail(HA_LOOKBACK), daily.tail(1)])
            else:
                completed = daily.copy()
                latest = completed.iloc[-1]
                signal_frame = completed.tail(HA_LOOKBACK)
            is_intraday = False

        if len(completed) < 50:
            raise ValueError("minder dan 50 afgeronde handelsdagen voor SMA50")

        # Yahoo Finance company classification for the DSR display.
        # Missing metadata remains blank; it must not be guessed.
        try:
            info = yf.Ticker(ticker).info or {}
            sector = info.get("sector") or ""
            industry = info.get("industry") or ""
        except Exception as exc:
            print(f"{ticker}: sector/industry niet beschikbaar ({exc})")
            sector = ""
            industry = ""

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

        # RVOL 5/21: compare averages of the latest 5 and 21 fully completed
        # regular sessions. The current/incomplete session is never included.
        daily_volume = float(latest["Volume"])
        volume_history = completed["Volume"]
        avg5 = float(volume_history.tail(5).mean()) if len(volume_history) >= 5 else float("nan")
        avg21 = float(volume_history.tail(21).mean()) if len(volume_history) >= 21 else float("nan")
        rvol_5_21 = avg5 / avg21 if avg21 > 0 else float("nan")
        if pd.isna(rvol_5_21):
            rvol_label = "ONBEKEND"
        elif rvol_5_21 < 0.80:
            rvol_label = "ZWAK"
        elif rvol_5_21 < 1.00:
            rvol_label = "BENEDEN GEMIDDELD"
        elif rvol_5_21 < 1.25:
            rvol_label = "NEUTRAAL"
        elif rvol_5_21 < 1.50:
            rvol_label = "POSITIEF"
        elif rvol_5_21 <= 2.00:
            rvol_label = "STERK"
        else:
            rvol_label = "ZEER STERK"

        # Keep the separate 3-session rising-volume signal, also using completed
        # sessions only (not the current partial session).
        last_three = volume_history.tail(3)
        if len(last_three) == 3:
            v0, v1, v2 = map(float, last_three)
            trend = "STIJGEND" if v0 < v1 < v2 else "DALEND" if v0 > v1 > v2 else "GEMENGD"
        else:
            trend = "ONBEKEND"

        requires_filter = bool(sources & SMA_FILTER_SOURCES)
        filter_pass = bool(above20 and above50) if requires_filter else "NVT"
        breakout = detect_breakout(completed, compare_close if is_intraday else None)
        return {
            "ticker": ticker,
            "sector": sector,
            "industry": industry,
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
            "daily_volume": int(latest["Volume"]),
            "average_volume_5d": int(avg5) if not pd.isna(avg5) else "",
            "average_volume_21d": int(avg21) if not pd.isna(avg21) else "",
            "rvol_5_21": round(rvol_5_21, 3) if not pd.isna(rvol_5_21) else "",
            "rvol_5_21_label": rvol_label,
            "volume_trend_3d": trend,
            **breakout,
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
