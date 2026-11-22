#!/usr/bin/env python3
"""Calculate the agreed five-part DSR technical scores without changing HA inputs."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
HA_INPUT = ROOT / "data" / "ha_signals.csv"
MARKET_INPUT = ROOT / "data" / "market_context.json"
OUTPUT = ROOT / "data" / "technical_scores.csv"
STATUS_OUTPUT = ROOT / "data" / "technical_score_status.json"
HISTORY_PERIOD = "1y"
MIN_ROWS = 55
SLEEP_SECONDS = 0.35


def _number(value):
    try:
        number = float(value)
        return number if pd.notna(number) else None
    except (TypeError, ValueError):
        return None


def _bool(value):
    if isinstance(value, bool):
        return value
    if str(value).strip().lower() in {"true", "1"}:
        return True
    if str(value).strip().lower() in {"false", "0"}:
        return False
    return None


def _normalise(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        raise ValueError("geen dagkoersen ontvangen")
    data = frame.copy()
    if isinstance(data.columns, pd.MultiIndex):
        level = next((i for i in range(data.columns.nlevels)
                      if "Close" in data.columns.get_level_values(i)), None)
        if level is None:
            raise ValueError("Close-kolom ontbreekt")
        data.columns = data.columns.get_level_values(level)
    required = ["High", "Low", "Close"]
    if not all(column in data.columns for column in required):
        raise ValueError("High/Low/Close ontbreken")
    idx = pd.DatetimeIndex(data.index)
    if idx.tz is not None:
        idx = idx.tz_convert("America/New_York").tz_localize(None)
    data.index = idx.normalize()
    data = data[~data.index.duplicated(keep="last")].sort_index()
    for column in required:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    return data.dropna(subset=required)


def analyse_price_history(frame: pd.DataFrame, expected_date: str) -> dict:
    data = _normalise(frame)
    data = data.loc[data.index.strftime("%Y-%m-%d") <= expected_date]
    if len(data) < MIN_ROWS:
        raise ValueError(f"onvoldoende historie: {len(data)} sessies")
    actual_date = data.index[-1].strftime("%Y-%m-%d")
    if actual_date != expected_date:
        raise ValueError(f"koersdata loopt achter: verwacht {expected_date}, ontvangen {actual_date}")

    close = data["Close"]
    sma20 = float(close.rolling(20).mean().iloc[-1])
    sma50 = float(close.rolling(50).mean().iloc[-1])
    latest_close = float(close.iloc[-1])
    momentum_21d = (float(close.iloc[-1]) / float(close.iloc[-22]) - 1.0) * 100.0
    ema8_series = close.ewm(span=8, adjust=False).mean()
    ema21_series = close.ewm(span=21, adjust=False).mean()
    ema8 = float(ema8_series.iloc[-1])
    ema21 = float(ema21_series.iloc[-1])
    ema_gap = abs(ema8 - ema21)
    previous_ema_gap = abs(float(ema8_series.iloc[-2]) - float(ema21_series.iloc[-2]))
    ema_gap_direction = (
        "WIDENING" if ema_gap > previous_ema_gap
        else "NARROWING" if ema_gap < previous_ema_gap
        else "STABLE"
    )
    if ema8 == ema21 or ema_gap <= previous_ema_gap:
        ema_status = "BEWARE"
    else:
        ema_status = "BULLISH" if ema8 > ema21 else "BEARISH"
    recent = data.tail(10)
    prior = data.iloc[-20:-10]
    higher_structure = (
        float(recent["High"].max()) > float(prior["High"].max())
        and float(recent["Low"].min()) > float(prior["Low"].min())
    )
    lower_structure = (
        float(recent["High"].max()) < float(prior["High"].max())
        and float(recent["Low"].min()) < float(prior["Low"].min())
    )
    previous_20 = data.iloc[-21:-1]
    return {
        "date": actual_date,
        "close": round(latest_close, 4),
        "above_sma20": bool(latest_close > sma20),
        "above_sma50": bool(latest_close > sma50),
        "momentum_21d_pct": round(momentum_21d, 3),
        "ema8": round(ema8, 4),
        "ema21": round(ema21, 4),
        "ema_gap_pct": round((ema8 / ema21 - 1.0) * 100.0, 3),
        "ema_gap_direction": ema_gap_direction,
        "ema_momentum_status": ema_status,
        "higher_highs_higher_lows": bool(higher_structure),
        "lower_highs_lower_lows": bool(lower_structure),
        "pivot_resistance_20d": round(float(previous_20["High"].max()), 4),
        "pivot_support_20d": round(float(previous_20["Low"].min()), 4),
    }


def score_components(ha_row: dict, price: dict, spx_momentum: float, qqq_momentum: float) -> dict:
    above20 = price.get("above_sma20")
    above50 = price.get("above_sma50")
    if not isinstance(above20, bool):
        above20 = _bool(ha_row.get("above_sma20"))
    if not isinstance(above50, bool):
        above50 = _bool(ha_row.get("above_sma50"))
    rvol = _number(ha_row.get("rvol_5_21"))
    momentum = _number(price.get("momentum_21d_pct"))
    higher = price.get("higher_highs_higher_lows")
    lower = price.get("lower_highs_lower_lows")

    long_parts = {
        "trend": (above20 is True and above50 is True) if above20 is not None and above50 is not None else None,
        "momentum": momentum > 0 if momentum is not None else None,
        "relative_strength": momentum > qqq_momentum if momentum is not None and qqq_momentum is not None else None,
        "volume": rvol >= 1.25 if rvol is not None else None,
        "structure": higher if isinstance(higher, bool) else None,
    }
    short_parts = {
        "trend": (above20 is False and above50 is False) if above20 is not None and above50 is not None else None,
        "momentum": momentum < 0 if momentum is not None else None,
        "relative_strength": momentum < qqq_momentum if momentum is not None and qqq_momentum is not None else None,
        "volume": rvol >= 1.25 if rvol is not None else None,
        "structure": lower if isinstance(lower, bool) else None,
    }
    complete = all(value is not None for value in long_parts.values()) and all(
        value is not None for value in short_parts.values()
    )
    return {
        "long_components": long_parts,
        "short_components": short_parts,
        "long_score": sum(long_parts.values()) if all(v is not None for v in long_parts.values()) else None,
        "short_score": sum(short_parts.values()) if all(v is not None for v in short_parts.values()) else None,
        "status": "OK" if complete else "ONBEKEND",
    }


def download_history(ticker: str) -> pd.DataFrame:
    return yf.download(
        ticker, period=HISTORY_PERIOD, interval="1d", auto_adjust=False,
        progress=False, threads=False, timeout=25,
    )


def write_status(payload: dict):
    temporary = STATUS_OUTPUT.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(STATUS_OUTPUT)


def main() -> int:
    if not HA_INPUT.exists() or not MARKET_INPUT.exists():
        print("HA-signalen of marktcontext ontbreekt.", file=sys.stderr)
        return 1
    ha = pd.read_csv(HA_INPUT, dtype={"ticker": str})
    market = json.loads(MARKET_INPUT.read_text(encoding="utf-8"))
    session = market.get("session_date")
    symbols = market.get("symbols", {})
    if market.get("data_status") != "FULL" or not session or not {"SPX", "QQQ"}.issubset(symbols):
        print("SPX/QQQ-marktdata is niet volledig; technische score blijft ONBEKEND.", file=sys.stderr)
        write_status({"status": "PARTIAL", "session_date": session, "scored": 0,
                      "unknown": int(len(ha)), "errors": ["SPX/QQQ-marktdata ontbreekt of is onvolledig"]})
        return 1
    spx = _number(symbols["SPX"].get("momentum_21d_pct"))
    qqq = _number(symbols["QQQ"].get("momentum_21d_pct"))
    if spx is None or qqq is None:
        print("SPX/QQQ 21-daags momentum ontbreekt.", file=sys.stderr)
        return 1

    rows, errors = [], []
    for index, ha_row in ha.iterrows():
        ticker = str(ha_row.get("ticker", "")).strip().upper()
        base = {key: ha_row.get(key, "") for key in ("ticker", "sources", "sector", "industry", "date", "close",
                "ha_day_type", "ha_strong_signal", "ha_strong_down_signal",
                "last_ha_long_stop", "last_ha_long_stop_date",
                "last_ha_short_stop", "last_ha_short_stop_date",
                "above_sma20", "above_sma50",
                "sma20", "sma50", "daily_volume", "rvol_5_21", "volume_trend_3d", "status")}
        try:
            if not ticker or str(ha_row.get("status", "")).startswith("ONBEKEND"):
                raise ValueError("HA-marktdata ontbreekt")
            price = analyse_price_history(download_history(ticker), session)
            scores = score_components(ha_row.to_dict(), price, spx, qqq)
            row = {
                **base,
                "close_completed": price["close"],
                "above_sma20_completed": price["above_sma20"],
                "above_sma50_completed": price["above_sma50"],
                "momentum_21d_pct": price["momentum_21d_pct"],
                "ema8": price["ema8"],
                "ema21": price["ema21"],
                "ema_gap_pct": price["ema_gap_pct"],
                "ema_gap_direction": price["ema_gap_direction"],
                "ema_momentum_status": price["ema_momentum_status"],
                "relative_vs_spx_pct": round(price["momentum_21d_pct"] - spx, 3),
                "relative_vs_qqq_pct": round(price["momentum_21d_pct"] - qqq, 3),
                "higher_highs_higher_lows": price["higher_highs_higher_lows"],
                "lower_highs_lower_lows": price["lower_highs_lower_lows"],
                "pivot_resistance_20d": price["pivot_resistance_20d"],
                "pivot_support_20d": price["pivot_support_20d"],
                "long_score": scores["long_score"],
                "short_score": scores["short_score"],
                "long_components": json.dumps(scores["long_components"], ensure_ascii=False),
                "short_components": json.dumps(scores["short_components"], ensure_ascii=False),
                "score_status": scores["status"],
                "score_date": session,
                "error": "",
            }
        except Exception as exc:
            errors.append(f"{ticker}: {exc}")
            row = {**base, "close_completed": "", "above_sma20_completed": "",
                   "above_sma50_completed": "", "momentum_21d_pct": "",
                   "ema8": "", "ema21": "", "ema_gap_pct": "", "ema_gap_direction": "",
                   "ema_momentum_status": "", "relative_vs_spx_pct": "", "relative_vs_qqq_pct": "",
                   "higher_highs_higher_lows": "", "lower_highs_lower_lows": "",
                   "pivot_resistance_20d": "", "pivot_support_20d": "", "long_score": "", "short_score": "",
                   "long_components": "", "short_components": "", "score_status": "ONBEKEND",
                   "score_date": session or "", "error": str(exc)}
        rows.append(row)
        print(f"[{index + 1}/{len(ha)}] {ticker}: Long={row['long_score']} Short={row['short_score']} {row['score_status']}")
        time.sleep(SLEEP_SECONDS)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(OUTPUT, index=False)
    scored = sum(row["score_status"] == "OK" for row in rows)
    unknown = len(rows) - scored
    status = "FULL" if unknown == 0 else "PARTIAL"
    payload = {"status": status, "session_date": session, "total_tickers": len(rows),
               "scored": scored, "unknown": unknown, "errors": errors}
    write_status(payload)
    print(f"Technische scores: {scored} OK, {unknown} ONBEKEND; status={status}")
    # Unknown individual tickers remain explicitly PARTIAL in the status file;
    # successfully written scores for the remaining universe are still usable.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
