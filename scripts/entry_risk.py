#!/usr/bin/env python3
"""Calculate DSR watchlist stop, risk percentage and 2R target without action claims."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
TECHNICAL = DATA / "technical_scores.csv"
LONG_SW = DATA / "long_sw_status.csv"
BORROW = DATA / "short_borrow.csv"
RISK_NEWS = DATA / "candidate_risk_news.csv"
OUTPUT = DATA / "entry_risk.csv"
STATUS_OUTPUT = DATA / "entry_risk_status.json"


def number(value):
    try:
        result = float(value)
        return result if pd.notna(result) else None
    except (TypeError, ValueError):
        return None


def calculate_entry_risk(candidate_type: str, entry, stop, pivot, score_date: str,
                          volume, news_status: str = "ONBEKEND",
                          borrow_status: str = "NVT", nearest_support=None,
                          nearest_resistance=None, consolidation_pivot_status="ONBEKEND",
                          consolidation_pivot_date="", prior_breakout_date="",
                          prior_breakout_close=None, prior_breakout_volume=None) -> dict:
    entry, stop, pivot = number(entry), number(stop), number(pivot)
    volume = number(volume)
    side = candidate_type.upper()
    if side not in {"LONG", "SHORT"}:
        raise ValueError("candidate_type moet LONG of SHORT zijn")
    if entry is None or entry <= 0 or stop is None:
        return {
            "entry": entry if entry is not None else "",
            "stop": stop if stop is not None else "",
            "risk_per_share": "",
            "risk_pct": "",
            "target_2r": "",
            "pivot_reference_20d": pivot if pivot is not None else "",
            "consolidation_pivot": pivot if pivot is not None else "",
            "consolidation_pivot_date": consolidation_pivot_date or "",
            "consolidation_pivot_status": consolidation_pivot_status,
            "distance_to_pivot_pct": "",
            "long_buy_zone_status": "ONBEKEND",
            "breakout_reference_status": "ONBEKEND",
            "target_feasibility": "ONBEKEND",
            "breakout_reference_date": "",
            "breakout_reference_close": "",
            "breakout_reference_volume": "",
            "entry_status": "ONBEKEND_STOP_OF_ENTRY",
            "action": "WACHTEN OP BEVESTIGING",
        }
    risk = entry - stop if side == "LONG" else stop - entry
    if risk <= 0:
        return {
            "entry": entry, "stop": stop, "risk_per_share": round(risk, 4),
            "risk_pct": "", "target_2r": "", "pivot_reference_20d": pivot or "",
            "distance_to_pivot_pct": "", "long_buy_zone_status": "ONBEKEND",
            "breakout_reference_status": "ONBEKEND", "target_feasibility": "ONBEKEND",
            "breakout_reference_date": "", "breakout_reference_close": "", "breakout_reference_volume": "",
            "entry_status": "ONGELDIGE_STOP", "action": "VERMIJDEN TOT STOP HERSTELD",
        }
    target = entry + 2 * risk if side == "LONG" else entry - 2 * risk
    if target <= 0:
        return {
            "entry": entry, "stop": stop, "risk_per_share": round(risk, 4),
            "risk_pct": round(risk / entry * 100, 2), "target_2r": "",
            "pivot_reference_20d": pivot or "", "consolidation_pivot": pivot or "",
            "consolidation_pivot_date": consolidation_pivot_date or "",
            "consolidation_pivot_status": consolidation_pivot_status,
            "distance_to_pivot_pct": "",
            "long_buy_zone_status": "ONBEKEND", "breakout_reference_status": "ONBEKEND",
            "target_feasibility": "ONBEKEND", "breakout_reference_date": "",
            "breakout_reference_close": "", "breakout_reference_volume": "",
            "entry_status": "ONGELDIGE_2R", "action": "VERMIJDEN TOT 2R HERSTELD",
        }

    support, resistance = number(nearest_support), number(nearest_resistance)
    if side == "LONG":
        target_feasibility = (
            "ONBEKEND" if resistance is None else
            "2R_DOEL_BOVEN_WEERSTAND" if target > resistance else "2R_DOEL_ONDER_WEERSTAND"
        )
    else:
        target_feasibility = (
            "ONBEKEND" if support is None else
            "2R_DOEL_ONDER_STEUN" if target < support else "2R_DOEL_BOVEN_STEUN"
        )

    if pivot is None or pivot <= 0 or consolidation_pivot_status != "OK":
        pivot_status, distance, breakout_date, breakout_close, breakout_volume = (
            "ONBEKEND", "", "", "", ""
        )
        action = "WACHTEN OP PIVOTVERIFICATIE"
        buy_zone = "ONBEKEND"
    elif side == "LONG":
        distance = (entry / pivot - 1) * 100
        broken = bool(prior_breakout_date) or entry > pivot
        pivot_status = "BREAKOUT_BEVESTIGD" if broken else "GEEN_BREAKOUT"
        breakout_date = prior_breakout_date or (score_date if entry > pivot else "")
        breakout_close = (
            number(prior_breakout_close) if prior_breakout_date
            else entry if entry > pivot else ""
        )
        breakout_volume = (
            number(prior_breakout_volume) if prior_breakout_date
            else volume if entry > pivot and volume is not None else ""
        )
        buy_zone = "NOT_BROKEN" if not broken else ("WITHIN_5PCT" if distance <= 5 else "EXTENDED")
        action = "WACHTEN OP ACTUELE CONSOLIDATIEPIVOT"
    else:
        distance = (pivot / entry - 1) * 100
        broken = bool(prior_breakout_date) or entry < pivot
        pivot_status = "DOORBRAAK_BEVESTIGD" if broken else "GEEN_DOORBRAAK"
        breakout_date = prior_breakout_date or (score_date if entry < pivot else "")
        breakout_close = (
            number(prior_breakout_close) if prior_breakout_date
            else entry if entry < pivot else ""
        )
        breakout_volume = (
            number(prior_breakout_volume) if prior_breakout_date
            else volume if entry < pivot and volume is not None else ""
        )
        buy_zone = "NVT"
        action = "WACHTEN OP ACTUELE CONSOLIDATIEPIVOT"

    if news_status in {"REVIEW", "UNKNOWN"}:
        action = "WACHTEN OP NIEUWS-/RISICOCONTROLE"
    if side == "SHORT" and borrow_status != "AVAILABLE":
        action = "GEEN BEVESTIGDE BORROW"

    return {
        "entry": round(entry, 4),
        "stop": round(stop, 4),
        "risk_per_share": round(risk, 4),
        "risk_pct": round(risk / entry * 100, 2),
        "target_2r": round(target, 4),
        "pivot_reference_20d": round(pivot, 4) if pivot is not None else "",
        "consolidation_pivot": round(pivot, 4) if pivot is not None else "",
        "consolidation_pivot_date": consolidation_pivot_date or "",
        "consolidation_pivot_status": consolidation_pivot_status,
        "distance_to_pivot_pct": round(distance, 2) if distance != "" else "",
        "long_buy_zone_status": buy_zone if side == "LONG" else "NVT",
        "breakout_reference_status": pivot_status,
        "target_feasibility": target_feasibility,
        "breakout_reference_date": breakout_date,
        "breakout_reference_close": round(breakout_close, 4) if breakout_close is not None and breakout_close != "" else "",
        "breakout_reference_volume": int(breakout_volume) if breakout_volume is not None and breakout_volume != "" else "",
        "entry_status": "STOP_2R_BEREKEND",
        "action": action,
    }


def build_rows() -> list[dict]:
    technical = pd.read_csv(TECHNICAL, dtype={"ticker": str})
    sw = pd.read_csv(LONG_SW, dtype={"ticker": str})
    borrow = pd.read_csv(BORROW, dtype={"ticker": str})
    news = pd.read_csv(RISK_NEWS, dtype={"ticker": str}) if RISK_NEWS.exists() else pd.DataFrame()
    tech_map = {str(row["ticker"]).upper(): row for _, row in technical.iterrows()}
    borrow_map = {str(row["ticker"]).upper(): row for _, row in borrow.iterrows()}
    news_map = {
        (str(row["ticker"]).upper(), str(row.get("candidate_type", "")).upper()): row
        for _, row in news.iterrows()
    } if not news.empty else {}
    long_tickers = {
        str(row["ticker"]).upper() for _, row in sw.iterrows()
        if row.get("fundamental_status") == "PASS" and row.get("sw_status") == "PASS"
    }
    candidates = []
    for ticker in long_tickers:
        candidates.append((ticker, "LONG"))
    for _, row in technical.iterrows():
        ticker = str(row["ticker"]).upper()
        short_score = number(row.get("short_score"))
        sma20, sma50 = number(row.get("sma20")), number(row.get("sma50"))
        if row.get("score_status") == "OK" and short_score is not None and short_score >= 3 and sma20 is not None and sma50 is not None and sma20 < sma50:
            candidates.append((ticker, "SHORT"))

    output = []
    for ticker, side in sorted(set(candidates)):
        tech = tech_map.get(ticker, {})
        borrow_row = borrow_map.get(ticker, {})
        news_row = news_map.get((ticker, side), {})
        stop_key = "last_ha_long_stop" if side == "LONG" else "last_ha_short_stop"
        stop_date_key = "last_ha_long_stop_date" if side == "LONG" else "last_ha_short_stop_date"
        risk_row = news_map.get((ticker, side), {})
        pivot_key = "consolidation_pivot"
        result = calculate_entry_risk(
            side,
            tech.get("close_completed"),
            tech.get(stop_key),
            risk_row.get(pivot_key),
            str(tech.get("score_date", "")),
            tech.get("daily_volume"),
            str(news_row.get("risk_status", "ONBEKEND")),
            str(borrow_row.get("status", "ONBEKEND")) if side == "SHORT" else "NVT",
            risk_row.get("nearest_support"), risk_row.get("nearest_resistance"),
            str(risk_row.get("consolidation_pivot_status", "ONBEKEND")),
            str(risk_row.get("consolidation_pivot_date", "")),
            str(risk_row.get("prior_breakout_date", "")),
            risk_row.get("prior_breakout_close"),
            risk_row.get("prior_breakout_volume"),
        )
        output.append({
            "ticker": ticker,
            "candidate_type": side,
            "sector": tech.get("sector", ""),
            "industry": tech.get("industry", ""),
            "sources": tech.get("sources", ""),
            "technical_score": tech.get("long_score" if side == "LONG" else "short_score", ""),
            "ha_day_type": tech.get("ha_day_type", ""),
            "stop_date": tech.get(stop_date_key, ""),
            "borrow_status": borrow_row.get("status", "") if side == "SHORT" else "",
            "nearest_support": news_row.get("nearest_support", ""),
            "nearest_support_date": news_row.get("nearest_support_date", ""),
            "nearest_resistance": news_row.get("nearest_resistance", ""),
            "nearest_resistance_date": news_row.get("nearest_resistance_date", ""),
            "news_status": news_row.get("risk_status", "ONBEKEND"),
            "score_date": tech.get("score_date", ""),
            **result,
        })
    return output


def write_status(payload: dict):
    temporary = STATUS_OUTPUT.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(STATUS_OUTPUT)


def main() -> int:
    try:
        rows = build_rows()
    except Exception as exc:
        write_status({"status": "PARTIAL", "errors": [str(exc)]})
        print(f"Entry-/risicoberekening niet beschikbaar: {exc}", file=sys.stderr)
        return 1
    columns = [
        "ticker", "candidate_type", "sector", "industry", "sources", "technical_score",
        "ha_day_type", "stop_date", "entry", "stop", "risk_per_share", "risk_pct",
        "target_2r", "pivot_reference_20d", "consolidation_pivot",
        "consolidation_pivot_date", "consolidation_pivot_status", "distance_to_pivot_pct",
        "long_buy_zone_status", "breakout_reference_status", "breakout_reference_date",
        "breakout_reference_close", "breakout_reference_volume", "nearest_support",
        "nearest_support_date", "nearest_resistance", "nearest_resistance_date",
        "target_feasibility", "borrow_status", "news_status", "entry_status", "action", "score_date",
    ]
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=columns).to_csv(OUTPUT, index=False)
    stop_unknown = sum(row["entry_status"] != "STOP_2R_BEREKEND" for row in rows)
    feasibility_unknown = sum(row.get("target_feasibility") == "ONBEKEND" for row in rows)
    unknown = sum(
        row["entry_status"] != "STOP_2R_BEREKEND" or row.get("target_feasibility") == "ONBEKEND"
        for row in rows
    )
    status = "FULL" if unknown == 0 else "PARTIAL"
    payload = {
        "status": status,
        "candidate_count": len(rows),
        "stop_2r_calculated": len(rows) - stop_unknown,
        "target_feasibility_unknown": feasibility_unknown,
        "unknown_or_invalid": unknown,
        "note": "Consolidation pivot uses a confirmed swing origin and the following 5–21 completed sessions; the latest completed close is evaluated separately for breakout/breakdown.",
    }
    write_status(payload)
    print(f"Entry risk: {payload['stop_2r_calculated']} stop/2R berekend, {unknown} onbekend/ongeldig.")
    return 0 if status == "FULL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
