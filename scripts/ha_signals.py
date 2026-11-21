#!/usr/bin/env python3
"""Daily DSR Heikin-Ashi, SMA20/50 and volume checks.

All configured DSR sources are unioned and deduplicated. Original source files
remain untouched. Missing market data is recorded as ONBEKEND, never silently
dropped. SMA200 is intentionally not calculated.
"""
from __future__ import annotations

import csv
import json
import re
import sys
import time
from pathlib import Path

import pandas as pd
import yfinance as yf
import pandas_market_calendars as mcal

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.source_status import evaluate_status

OUT = ROOT / "data" / "ha_signals.csv"
COVERAGE_OUT = ROOT / "data" / "ha_source_coverage.csv"
SOURCE_STATUS_OUT = ROOT / "data" / "dsr_source_status.csv"
RUN_STATUS_OUT = ROOT / "data" / "dsr_run_status.json"
STATUS_DIR = ROOT / "data" / "source_status"
HISTORY_PERIOD = "1y"
HA_LOOKBACK = 30

# The JSON file is the single source of truth for the six DSR sources.
SOURCE_CONFIG = ROOT / "data" / "dsr_ticker_sources.json"
EXPECTED_SOURCES = {
    "Sector Top Tickers", "FV Momentum Darvas", "Blue Sky", "VYUS holdings",
    "Simpel Monsters", "Follow Thrue",
}
# The existing DSR rule: these two sources must pass both moving averages.
SMA_FILTER_SOURCES = {"Sector Top Tickers", "VYUS holdings"}


def load_source_config():
    config = json.loads(SOURCE_CONFIG.read_text(encoding="utf-8"))
    entries = config.get("sources", [])
    names = {entry.get("name") for entry in entries}
    if len(entries) != 6 or names != EXPECTED_SOURCES:
        raise ValueError(
            "DSR-bronconfiguratie moet exact de zes afgesproken bronnen bevatten; "
            f"gevonden: {sorted(str(name) for name in names)}"
        )
    sources = []
    for entry in entries:
        fmt = entry.get("format")
        if fmt == "whitespace":
            fmt = "text"
        if fmt not in {"csv", "text"}:
            raise ValueError(f"Ongeldig bronformaat voor {entry.get('name')}: {fmt}")
        path = (ROOT / entry["path"]).resolve()
        if ROOT.resolve() not in path.parents:
            raise ValueError(f"Bronpad valt buiten de repository: {entry.get('path')}")
        sources.append((entry["name"], path, fmt))
    return sources


SOURCES = load_source_config()


def load_source_metadata():
    config = json.loads(SOURCE_CONFIG.read_text(encoding="utf-8"))
    return {entry["name"]: entry for entry in config["sources"]}


SOURCE_METADATA = load_source_metadata()


def write_run_status(status: str, source_rows: list[dict], ticker_count: int,
                     source_errors: dict, source_warnings: dict, missing_rows: int = 0):
    payload = {
        "status": status,
        "generated_at": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"),
        "unique_tickers": ticker_count,
        "source_count": len(source_rows),
        "source_errors": source_errors,
        "source_warnings": source_warnings,
        "missing_ha_rows": missing_rows,
    }
    temporary = RUN_STATUS_OUT.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(RUN_STATUS_OUT)


def write_source_status(rows: list[dict]):
    pd.DataFrame(rows, columns=[
        "source", "source_id", "status", "last_attempt_at", "last_success_at",
        "age_hours", "included", "ticker_count", "detail",
    ]).to_csv(SOURCE_STATUS_OUT, index=False)


def read_source(path: Path, fmt: str) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"Verplicht bronbestand ontbreekt: {path.relative_to(ROOT)}")
    content = path.read_text(encoding="utf-8-sig").strip()
    if not content:
        raise ValueError(f"Bronbestand is leeg: {path.relative_to(ROOT)}")

    if fmt == "csv":
        reader = csv.DictReader(content.splitlines())
        fields = {field.strip().lower() for field in (reader.fieldnames or [])}
        if not fields.intersection({"ticker", "symbol"}):
            raise ValueError(f"CSV mist een Ticker/Symbol-kolom: {path.relative_to(ROOT)}")
        result = []
        for row in reader:
            normalized_row = {str(key).strip().lower(): value for key, value in row.items() if key}
            value = (normalized_row.get("ticker") or normalized_row.get("symbol") or "").strip().upper()
            if value and value not in {"TICKER", "SYMBOL"}:
                result.append(value)
    else:
        result = [
            token.upper()
            for token in re.split(r"[\s,;]+", content)
            if token.strip() and token.strip().upper() not in {"TICKER", "SYMBOL"}
        ]

    if not result:
        raise ValueError(f"Bron bevat geen tickers: {path.relative_to(ROOT)}")
    return result


def load_universe(include_status: bool = False):
    ticker_sources: dict[str, set[str]] = {}
    source_counts: dict[str, int] = {}
    source_errors: dict[str, str] = {}
    source_warnings: dict[str, str] = {}
    source_status_rows: list[dict] = []

    for source_name, path, fmt in SOURCES:
        metadata = SOURCE_METADATA.get(source_name, {})
        try:
            tickers = read_source(path, fmt)
        except Exception as exc:
            source_errors[source_name] = str(exc)
            if include_status:
                source_status_rows.append({
                    "source": source_name, "source_id": metadata.get("id", ""),
                    "status": "FILE_ERROR", "last_attempt_at": "",
                    "last_success_at": "", "age_hours": "", "included": False,
                    "ticker_count": 0, "detail": str(exc),
                })
            print(f"BRONFOUT [{source_name}]: {exc}", file=sys.stderr)
            continue

        status = {
            "status": "MANUAL", "include": True, "partial": False,
            "last_attempt_at": "", "last_success_at": "", "age_hours": "",
            "detail": "Geen automatische statuscontrole.",
        }
        if include_status:
            source_id = metadata.get("id")
            refresh_mode = metadata.get("refresh_mode", "manual")
            max_age_hours = int(metadata.get("max_age_hours", 96))
            status = evaluate_status(source_id, refresh_mode, max_age_hours, STATUS_DIR)
            if status["partial"]:
                source_warnings[source_name] = f"{status['status']}: {status['detail']}"
            if not status["include"]:
                source_errors[source_name] = f"{status['status']}: {status['detail']}"
            source_status_rows.append({
                "source": source_name,
                "source_id": source_id or "",
                "status": status["status"],
                "last_attempt_at": status["last_attempt_at"],
                "last_success_at": status["last_success_at"],
                "age_hours": status["age_hours"],
                "included": status["include"],
                "ticker_count": len(set(tickers)) if status["include"] else 0,
                "detail": status["detail"],
            })

        if not status["include"]:
            print(f"BRON NIET MEegenomen [{source_name}]: {status['status']}", file=sys.stderr)
            continue

        source_counts[source_name] = len(set(tickers))
        for ticker in tickers:
            ticker_sources.setdefault(ticker, set()).add(source_name)

    if include_status:
        return ticker_sources, source_counts, source_errors, source_warnings, source_status_rows
    return ticker_sources, source_counts, source_errors


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
        "ha_pivot_low_age": "",
        "ha_pivot_high_age": "",
        "ha_pivot_up": "",
        "ha_pivot_down": "",
        "ha_pivot_distance_pct": "",
        "ha_pivot_signal": "",
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

        # Determine whether the NYSE regular session is actually open.
        # The calendar also handles holidays and early closes.
        now_et = pd.Timestamp.now(tz="America/New_York")
        today_et = now_et.date()
        calendar = mcal.get_calendar("NYSE")
        schedule = calendar.schedule(start_date=today_et, end_date=today_et)
        session_open = session_close = None
        if not schedule.empty:
            session_open = schedule.iloc[0]["market_open"].tz_convert("America/New_York")
            session_close = schedule.iloc[0]["market_close"].tz_convert("America/New_York")
        session_is_open = bool(
            session_open is not None and session_open <= now_et < session_close
        )

        current = pd.DataFrame()
        if session_is_open:
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
                        mask = [d == today_et for d in idx.date]
                        current = intra.loc[mask, needed].dropna(
                            subset=["Open", "High", "Low", "Close"]
                        )
            except Exception as exc:
                print(f"{ticker}: intradaydata niet beschikbaar; dagdata-fallback ({exc})")

        daily_dates = pd.DatetimeIndex(daily.index)
        if daily_dates.tz is not None:
            daily_dates = daily_dates.tz_convert("America/New_York").tz_localize(None)
        daily_dates_only = [d.date() for d in daily_dates]
        has_today_daily = bool(daily_dates_only and daily_dates_only[-1] == today_et)

        if session_is_open:
            # The current session is incomplete: exclude its daily bar from all
            # completed-session indicators and use 5-minute bars for the HA candle.
            completed = daily.iloc[:-1].copy() if has_today_daily else daily.copy()
            if not current.empty:
                session = pd.DataFrame([{
                    "Open": float(current["Open"].iloc[0]),
                    "High": float(current["High"].max()),
                    "Low": float(current["Low"].min()),
                    "Close": float(current["Close"].iloc[-1]),
                    "Volume": float(current["Volume"].sum()),
                }], index=[pd.Timestamp(today_et)])
                latest = session.iloc[0]
                signal_frame = pd.concat([completed.tail(HA_LOOKBACK), session])
                data_status = "OK_INTRADAY"
            elif has_today_daily:
                # Fallback only: Yahoo's current daily bar may still be partial.
                latest = daily.iloc[-1]
                signal_frame = pd.concat([completed.tail(HA_LOOKBACK), daily.tail(1)])
                data_status = "OK_INTRADAY_FALLBACK"
            else:
                # Do not silently label yesterday's data as current.
                raise ValueError("lopende NYSE-sessie, maar geen actuele intraday- of dagbalk")
        else:
            # Outside the regular session (including after the close, holidays,
            # weekends and early-close completion), the latest daily bar is final.
            completed = daily.copy()
            latest = completed.iloc[-1]
            signal_frame = completed.tail(HA_LOOKBACK)
            data_status = "OK"

        # Guard against delayed daily data: indicators must end on the
        # latest NYSE session that has officially closed.
        calendar_start = today_et - pd.Timedelta(days=14)
        recent_schedule = calendar.schedule(
            start_date=calendar_start, end_date=today_et
        )
        now_utc = now_et.tz_convert("UTC")
        closed_sessions = recent_schedule[
            recent_schedule["market_close"] <= now_utc
        ]
        if closed_sessions.empty:
            raise ValueError("geen laatst afgeronde NYSE-sessie gevonden")
        expected_completed_date = closed_sessions.index[-1].date()
        completed_index = pd.Timestamp(completed.index[-1])
        if completed_index.tzinfo is not None:
            completed_index = completed_index.tz_convert("America/New_York").tz_localize(None)
        actual_completed_date = completed_index.date()
        if actual_completed_date != expected_completed_date:
            raise ValueError(
                "dagdata niet bijgewerkt tot de laatste afgeronde NYSE-sessie: "
                f"verwacht {expected_completed_date}, ontvangen {actual_completed_date}"
            )

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

        # Dominant HA pivot from the supplied Apps Script: extreme of the
        # latest 21 HA candles must have occurred within the latest 8 (age 0-7).
        # The current candle must also have HA Low=Open / HA High=Open and
        # the regular close must be above / below both completed-session SMAs.
        pivot_window = 21
        pivot_max_age = 7
        recent_lows = [float(v) for v in ha_low.tail(pivot_window)]
        recent_highs = [float(v) for v in ha_high.tail(pivot_window)]
        lowest_ha_low = min(recent_lows)
        highest_ha_high = max(recent_highs)
        low_last_index = max(i for i, value in enumerate(recent_lows) if value == lowest_ha_low)
        high_last_index = max(i for i, value in enumerate(recent_highs) if value == highest_ha_high)
        low_age = len(recent_lows) - 1 - low_last_index
        high_age = len(recent_highs) - 1 - high_last_index
        pivot_up = bool(equal_low and above20 and above50 and low_age <= pivot_max_age)
        pivot_down = bool(equal_high and not above20 and not above50 and high_age <= pivot_max_age)
        if pivot_up and hl > 0:
            pivot_distance = (compare_close - hl) / hl * 100.0
            pivot_signal = f"UP ↑ {int(pivot_distance + 0.5)}% ({low_age})"
        elif pivot_down and hh > 0:
            pivot_distance = (hh - compare_close) / hh * 100.0
            pivot_signal = f"DOWN ↓ {int(pivot_distance + 0.5)}% ({high_age})"
        else:
            pivot_distance = float("nan")
            pivot_signal = ""

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
            "ha_pivot_low_age": low_age,
            "ha_pivot_high_age": high_age,
            "ha_pivot_up": pivot_up,
            "ha_pivot_down": pivot_down,
            "ha_pivot_distance_pct": round(pivot_distance, 1) if not pd.isna(pivot_distance) else "",
            "ha_pivot_signal": pivot_signal,
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
            "status": data_status,
        }
    except Exception as exc:
        return unknown_row(ticker, sources, str(exc))


def main() -> int:
    try:
        ticker_sources, source_counts, source_errors, source_warnings, source_status_rows = load_universe(
            include_status=True
        )
    except Exception as exc:
        print(f"Bronconfiguratie mislukt: {exc}", file=sys.stderr)
        return 1

    write_source_status(source_status_rows)
    if not ticker_sources:
        empty_columns = list(unknown_row("", set(), "").keys())
        pd.DataFrame(columns=empty_columns).to_csv(OUT, index=False)
        coverage_rows = [
            {
                "source": source_name,
                "ticker": "",
                "ha_row_present": False,
                "ha_status": f"BRONFOUT: {source_errors.get(source_name, 'geen tickers beschikbaar')}",
            }
            for source_name, _, _ in SOURCES
        ]
        pd.DataFrame(
            coverage_rows,
            columns=["source", "ticker", "ha_row_present", "ha_status"],
        ).to_csv(COVERAGE_OUT, index=False)
        write_run_status("PARTIAL", source_status_rows, 0, source_errors, source_warnings)
        print("Geen bruikbare tickers uit de DSR-bronnen; lege uitvoer en bronstatus opgeslagen.", file=sys.stderr)
        return 1

    print("Broncontrole:")
    for source_name, _, _ in SOURCES:
        if source_name in source_errors:
            print(f"  {source_name}: UITGESLOTEN")
        elif source_name in source_warnings:
            print(f"  {source_name}: {source_warnings[source_name]}")
        else:
            print(f"  {source_name}: {source_counts[source_name]} unieke tickers")
    print(f"Gecombineerd: {len(ticker_sources)} unieke tickers")
    print(f"Bronfouten: {len(source_errors)}; bronwaarschuwingen: {len(source_warnings)}")

    rows = []
    for i, ticker in enumerate(sorted(ticker_sources), 1):
        print(f"[{i}/{len(ticker_sources)}] {ticker}")
        rows.append(calculate(ticker, ticker_sources[ticker]))
        time.sleep(0.35)

    results = pd.DataFrame(rows)
    results.to_csv(OUT, index=False)

    # Preserve the established four-column ticker coverage schema.
    coverage_rows = []
    result_tickers = set(results["ticker"].astype(str))
    for source_name, _, _ in SOURCES:
        if source_name in source_errors:
            coverage_rows.append({
                "source": source_name,
                "ticker": "",
                "ha_row_present": False,
                "ha_status": f"BRONFOUT: {source_errors[source_name]}",
            })
            continue

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
    partial = bool(source_errors or source_warnings or missing)
    run_state = "PARTIAL" if partial else "FULL"
    write_run_status(run_state, source_status_rows, len(ticker_sources),
                     source_errors, source_warnings, missing)
    print(
        f"Controle voltooid: {ok} tickers OK, {unknown} ONBEKEND, "
        f"{missing} ontbrekende HA-rijen. Totaal {len(ticker_sources)} unieke tickers."
    )
    print(f"DSR-status: {run_state}")
    print(f"HA-uitvoer: {OUT}")
    print(f"Broncontrole: {COVERAGE_OUT}")
    print(f"Bronactualiteit: {SOURCE_STATUS_OUT}")
    # Existing market-data ONBEKEND rows remain visible; source freshness errors
    # and missing HA rows make the overall run PARTIAL.
    return 1 if partial else 0


if __name__ == "__main__":
    raise SystemExit(main())
