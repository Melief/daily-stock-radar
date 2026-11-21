#!/usr/bin/env python3
"""SPX/QQQ market context based on the latest completed NYSE session."""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pandas_market_calendars as mcal
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "market_context.json"
SYMBOLS = {"SPX": "^GSPC", "QQQ": "QQQ"}
HISTORY_PERIOD = "1y"
MIN_HISTORY = 50


def latest_completed_session(now: pd.Timestamp | None = None) -> date:
    """Return the latest NYSE session whose official close has passed."""
    current = now or pd.Timestamp.now(tz="UTC")
    current = current.tz_localize("UTC") if current.tzinfo is None else current.tz_convert("UTC")
    today_ny = current.tz_convert("America/New_York").date()
    calendar = mcal.get_calendar("NYSE")
    schedule = calendar.schedule(
        start_date=today_ny - timedelta(days=30),
        end_date=today_ny,
    )
    closed = schedule[schedule["market_close"] <= current]
    if closed.empty:
        raise RuntimeError("Geen afgeronde NYSE-sessie gevonden in de laatste 30 dagen.")
    return closed.index[-1].date()


def _normalise_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        raise ValueError("geen koersdata ontvangen")
    data = frame.copy()
    if isinstance(data.columns, pd.MultiIndex):
        close_level = next(
            (level for level in range(data.columns.nlevels)
             if "Close" in data.columns.get_level_values(level)),
            None,
        )
        if close_level is None:
            raise ValueError("Close-kolom ontbreekt in yfinance MultiIndex-kolommen")
        data.columns = data.columns.get_level_values(close_level)
    required = ["High", "Low", "Close"]
    missing = [column for column in required if column not in data.columns]
    if missing:
        raise ValueError(f"OHLC-kolommen ontbreken: {missing}")
    index = pd.DatetimeIndex(data.index)
    if index.tz is not None:
        index = index.tz_convert("America/New_York").tz_localize(None)
    data.index = index.normalize()
    data = data[~data.index.duplicated(keep="last")].sort_index()
    for column in required:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    return data.dropna(subset=required)


def ema_momentum_status(ema8: float, ema21: float, current_gap: float, previous_gap: float) -> str:
    """Classify EMA momentum using only completed daily closes."""
    if ema8 == ema21 or current_gap <= previous_gap:
        return "BEWARE"
    return "BULLISH" if ema8 > ema21 else "BEARISH"


def analyse_symbol(frame: pd.DataFrame, symbol: str, expected_session: date) -> dict:
    """Calculate reproducible trend and momentum fields from completed closes."""
    data = _normalise_frame(frame)
    data = data.loc[data.index.date <= expected_session]
    if len(data) < MIN_HISTORY:
        raise ValueError(f"onvoldoende historie: {len(data)} sessies; minimaal {MIN_HISTORY}")
    actual_session = data.index[-1].date()
    if actual_session != expected_session:
        raise ValueError(
            f"koersdata loopt achter: verwacht {expected_session}, ontvangen {actual_session}"
        )

    close = data["Close"]
    last_close = float(close.iloc[-1])
    sma20 = float(close.rolling(20).mean().iloc[-1])
    sma50 = float(close.rolling(50).mean().iloc[-1])
    if pd.isna(sma20) or pd.isna(sma50) or sma20 <= 0 or sma50 <= 0:
        raise ValueError("SMA20/SMA50 niet betrouwbaar berekenbaar")

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
    ema_status = ema_momentum_status(ema8, ema21, ema_gap, previous_ema_gap)

    above20 = last_close > sma20
    above50 = last_close > sma50
    alignment = "BULLISH" if sma20 > sma50 else "BEARISH" if sma20 < sma50 else "FLAT"
    position = "BOVEN_BEIDE" if above20 and above50 else "ONDER_BEIDE" if not above20 and not above50 else "GEMENGD"

    def pct_change(sessions: int) -> float:
        if len(close) <= sessions or float(close.iloc[-sessions - 1]) == 0:
            raise ValueError(f"onvoldoende historie voor momentum over {sessions} sessies")
        return (last_close / float(close.iloc[-sessions - 1]) - 1.0) * 100.0

    # Confirmed five-session swing pivots: two completed bars on either side.
    recent = data.tail(126)
    highs = recent["High"].tolist()
    lows = recent["Low"].tolist()
    swing_highs = []
    swing_lows = []
    for i in range(2, len(recent) - 2):
        if highs[i] > max(highs[i - 2:i]) and highs[i] >= max(highs[i + 1:i + 3]):
            swing_highs.append((float(highs[i]), recent.index[i].date().isoformat()))
        if lows[i] < min(lows[i - 2:i]) and lows[i] <= min(lows[i + 1:i + 3]):
            swing_lows.append((float(lows[i]), recent.index[i].date().isoformat()))
    support_levels = [level for level in swing_lows if level[0] < last_close]
    resistance_levels = [level for level in swing_highs if level[0] > last_close]
    support = max(support_levels, key=lambda item: item[0]) if support_levels else None
    resistance = min(resistance_levels, key=lambda item: item[0]) if resistance_levels else None

    return {
        "symbol": symbol,
        "date": actual_session.isoformat(),
        "close": round(last_close, 4),
        "sma20": round(sma20, 4),
        "sma50": round(sma50, 4),
        "ema8": round(ema8, 4),
        "ema21": round(ema21, 4),
        "ema_gap_pct": round((ema8 / ema21 - 1.0) * 100.0, 3),
        "ema_gap_direction": ema_gap_direction,
        "ema_momentum_status": ema_status,
        "close_above_sma20": above20,
        "close_above_sma50": above50,
        "position": position,
        "sma_alignment": alignment,
        "momentum_5d_pct": round(pct_change(5), 2),
        "momentum_21d_pct": round(pct_change(21), 2),
        "support": round(support[0], 4) if support else None,
        "support_date": support[1] if support else None,
        "resistance": round(resistance[0], 4) if resistance else None,
        "resistance_date": resistance[1] if resistance else None,
        "support_resistance_method": "confirmed 5-session swing pivots; 126-session lookback",
        "support_resistance": (
            f"Steun {support[0]:.2f} ({support[1]})" if support else "Geen bevestigde swing-steun"
        ) + " | " + (
            f"Weerstand {resistance[0]:.2f} ({resistance[1]})" if resistance else "Geen bevestigde swing-weerstand"
        ),
        "status": "OK",
    }


def fetch_symbol(symbol: str, expected_session: date) -> dict:
    frame = yf.download(
        symbol,
        period=HISTORY_PERIOD,
        interval="1d",
        auto_adjust=False,
        progress=False,
        threads=False,
        timeout=25,
    )
    return analyse_symbol(frame, symbol, expected_session)


def build_context(expected_session: date, results: dict[str, dict], errors: dict[str, str]) -> dict:
    complete = set(results) == {"SPX", "QQQ"} and not errors
    relative = None
    regime = "ONBEKEND"
    if complete:
        relative = round(
            results["QQQ"]["momentum_21d_pct"] - results["SPX"]["momentum_21d_pct"], 2
        )
        positions = [results[label].get("position") for label in ("SPX", "QQQ")]
        if positions == ["BOVEN_BEIDE", "BOVEN_BEIDE"]:
            regime = "RISK-ON"
        elif positions == ["ONDER_BEIDE", "ONDER_BEIDE"]:
            regime = "RISK-OFF"
        else:
            regime = "NEUTRAAL"

    return {
        "status": "FULL" if complete else "PARTIAL",
        "data_status": "FULL" if complete else "PARTIAL",
        "session_date": expected_session.isoformat(),
        "symbols": results,
        "qqq_minus_spx_momentum_21d_pct": relative,
        "market_regime": regime,
        "errors": errors,
        "limitations": [
            "Steun en weerstand zijn afgeleid van bevestigde vijf-sessie swing-pivots; het zijn referentieniveaus, geen automatische entrysignalen.",
            "Marktregime is bepaald op basis van SPX en QQQ ten opzichte van SMA20 en SMA50.",
        ],
    }


def update_run_status(payload: dict) -> None:
    """Keep the aggregate DSR partial until every required component exists."""
    run_status_path = ROOT / "data" / "dsr_run_status.json"
    if not run_status_path.exists():
        return
    try:
        run_status = json.loads(run_status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"DSR-runstatus kan niet veilig worden bijgewerkt: {exc}") from exc

    run_status["market_context_status"] = payload.get("status", "PARTIAL")
    run_status["market_context_data_status"] = payload.get("data_status", "PARTIAL")
    pending = run_status.get("pending_components", [])
    obsolete = {
        "SPX/QQQ market context",
        "Risk-on/risk-off marktregime: expliciete criteria ontbreken.",
    }
    run_status["pending_components"] = [item for item in pending if item not in obsolete]
    run_status["status"] = "PARTIAL" if run_status["pending_components"] or payload.get("status") != "FULL" else run_status.get("status", "PARTIAL")
    temporary = run_status_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(run_status, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(run_status_path)


def write_context(payload: dict, output: Path = OUTPUT) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(output)
    update_run_status(payload)


def main() -> int:
    try:
        session = latest_completed_session()
    except Exception as exc:
        print(f"MARKTCONTEXT ONBEKEND: {exc}", file=sys.stderr)
        payload = {
            "status": "PARTIAL",
            "session_date": None,
            "symbols": {},
            "qqq_minus_spx_momentum_21d_pct": None,
            "market_regime": "ONBEKEND",
            "errors": {"session_calendar": str(exc)},
            "limitations": ["Geen marktbeoordeling mogelijk zonder betrouwbare laatste voltooide sessie."],
        }
        write_context(payload)
        return 1

    results: dict[str, dict] = {}
    errors: dict[str, str] = {}
    for label, ticker in SYMBOLS.items():
        try:
            results[label] = fetch_symbol(ticker, session)
            print(
                f"{label}: {results[label]['date']} close={results[label]['close']} "
                f"positie={results[label]['position']} SMA-alignment={results[label]['sma_alignment']}"
            )
        except Exception as exc:
            errors[label] = str(exc)
            print(f"{label}: ONBEKEND: {exc}", file=sys.stderr)

    payload = build_context(session, results, errors)
    write_context(payload)
    print(f"Marktcontext {payload['status']} opgeslagen: {OUTPUT.relative_to(ROOT)}")
    return 0 if payload.get("data_status") == "FULL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
