#!/usr/bin/env python3
"""Build the auditable daily DSR report and aggregate component status."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUTPUT = DATA / "dsr_report.md"
STATUS_OUTPUT = DATA / "dsr_report_status.json"
RUN_STATUS = DATA / "dsr_run_status.json"


def read_csv(name: str) -> list[dict]:
    path = DATA / name
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_json(name: str) -> dict:
    path = DATA / name
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def as_float(value):
    try:
        result = float(value)
        return result if pd.notna(result) else None
    except (TypeError, ValueError):
        return None


def as_bool(value):
    if isinstance(value, bool):
        return value
    if str(value).strip().lower() in {"true", "1"}:
        return True
    if str(value).strip().lower() in {"false", "0"}:
        return False
    return None


def clean(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "ONBEKEND"
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return "ONBEKEND"
    return text.replace("|", "/")


def select_long_candidates(sw_rows: list[dict]) -> list[dict]:
    return [
        row for row in sw_rows
        if row.get("fundamental_status") == "PASS" and row.get("sw_status") == "PASS"
    ]


def select_short_candidates(technical_rows: list[dict]) -> list[dict]:
    result = []
    for row in technical_rows:
        short_score = as_float(row.get("short_score"))
        sma20, sma50 = as_float(row.get("sma20")), as_float(row.get("sma50"))
        if row.get("score_status") == "OK" and short_score is not None and short_score >= 3:
            if sma20 is not None and sma50 is not None and sma20 < sma50:
                result.append(row)
    return result


def _table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return "_Geen kandidaten._"
    def cell(value):
        if value == "__EMPTY__":
            return ""
        return clean(value)

    lines = ["| " + " | ".join(headers) + " |",
             "| " + " | ".join("---" for _ in headers) + " |"]
    lines.extend("| " + " | ".join(cell(value) for value in row) + " |" for row in rows)
    return "\n".join(lines)


def build_report() -> tuple[str, dict]:
    technical = read_csv("technical_scores.csv")
    ha_rows = read_csv("ha_signals.csv")
    source_rows = read_csv("dsr_source_status.csv")
    fundamentals = read_csv("long_fundamentals.csv")
    sw_rows = read_csv("long_sw_status.csv")
    borrow_rows = read_csv("short_borrow.csv")
    risk_rows = read_csv("candidate_risk_news.csv")
    market = read_json("market_context.json")
    run_status = read_json("dsr_run_status.json")
    tech_status = read_json("technical_score_status.json")
    fundamental_status = read_json("long_fundamental_status.json")
    sw_status = read_json("long_sw_status.json")
    borrow_status = read_json("short_borrow_status.json")
    risk_status = read_json("candidate_risk_news_status.json")

    tech_by_ticker = {row.get("ticker", "").upper(): row for row in technical}
    ha_by_ticker = {row.get("ticker", "").upper(): row for row in ha_rows}
    borrow_by_ticker = {row.get("ticker", "").upper(): row for row in borrow_rows}
    risk_by_ticker = {row.get("ticker", "").upper(): row for row in risk_rows}

    long_candidates = select_long_candidates(sw_rows)
    short_candidates = select_short_candidates(technical)
    session = (market.get("session_date") or
               (technical[0].get("score_date") if technical else "ONBEKEND"))

    long_table = []
    for candidate in long_candidates:
        ticker = candidate.get("ticker", "").upper()
        tech = tech_by_ticker.get(ticker, {})
        ha = ha_by_ticker.get(ticker, {})
        risk = risk_by_ticker.get(ticker, {})
        long_table.append([
            ticker, candidate.get("sources", ""), candidate.get("sector", ""),
            candidate.get("industry", ""), ha.get("ha_day_type", tech.get("ha_day_type", "")),
            candidate.get("technical_score", ""), f"{candidate.get('financial_health_score')}/6",
            tech.get("close_completed", ""), tech.get("pivot_resistance_20d", ""),
            tech.get("rvol_5_21", ""), risk.get("risk_status", "ONBEKEND"),
        ])

    short_table = []
    for candidate in short_candidates:
        ticker = candidate.get("ticker", "").upper()
        ha = ha_by_ticker.get(ticker, {})
        borrow = borrow_by_ticker.get(ticker, {})
        risk = risk_by_ticker.get(ticker, {})
        short_table.append([
            ticker, candidate.get("sources", ""), candidate.get("sector", ""),
            candidate.get("industry", ""), ha.get("ha_day_type", candidate.get("ha_day_type", "")),
            candidate.get("short_score", ""), "__EMPTY__", borrow.get("status", "ONBEKEND"),
            borrow.get("fee_rate_pct", ""), borrow.get("available_shares", ""),
            risk.get("short_percent_of_float", ""), risk.get("days_to_cover", ""),
            risk.get("risk_status", "ONBEKEND"),
        ])

    ha_long = []
    ha_short = []
    for row in ha_rows:
        ticker = row.get("ticker", "").upper()
        if as_bool(row.get("ha_strong_signal")) and as_bool(row.get("above_sma20")) and as_bool(row.get("above_sma50")):
            ha_long.append(row)
        if as_bool(row.get("ha_strong_down_signal")) and as_bool(row.get("above_sma20")) is False and as_bool(row.get("above_sma50")) is False:
            ha_short.append(row)
    ha_long.sort(key=lambda row: as_float(row.get("distance_from_low_pct"))
                    if as_float(row.get("distance_from_low_pct")) is not None else float("inf"))
    ha_short.sort(key=lambda row: (
        ((as_float(row.get("ha_high")) - as_float(row.get("ha_close"))) / as_float(row.get("ha_high")) * 100)
        if as_float(row.get("ha_high")) and as_float(row.get("ha_close")) is not None else float("inf")
    ))

    market_lines = []
    symbols = market.get("symbols", {})
    for label in ("SPX", "QQQ"):
        item = symbols.get(label, {})
        market_lines.append(
            f"- **{label}:** close {clean(item.get('close'))}; SMA20 {clean(item.get('sma20'))}; "
            f"SMA50 {clean(item.get('sma50'))}; positie {clean(item.get('position'))}; "
            f"momentum 5d {clean(item.get('momentum_5d_pct'))}%; "
            f"21d {clean(item.get('momentum_21d_pct'))}%; "
            f"steun {clean(item.get('support'))} ({clean(item.get('support_date'))}); "
            f"weerstand {clean(item.get('resistance'))} ({clean(item.get('resistance_date'))})"
        )
    market_lines.append(f"- **Marktregime:** {clean(market.get('market_regime'))}")

    source_table_rows = []
    for row in source_rows:
        source_table_rows.append([
            row.get("source", ""), row.get("status", ""), row.get("ticker_count", ""),
            row.get("last_success_at", ""), row.get("age_hours", ""), row.get("detail", ""),
        ])

    risk_review = []
    for row in risk_rows:
        if row.get("risk_status") == "REVIEW":
            try:
                items = json.loads(row.get("news_items", "[]"))
            except json.JSONDecodeError:
                items = []
            for item in items:
                if item.get("event_flags"):
                    risk_review.append(
                        f"- **{row.get('ticker')} ({row.get('candidate_type')}):** "
                        f"[{item.get('title', 'Nieuwsitem')}]({item.get('url', '')}) "
                        f"— {item.get('source', '')}, {item.get('published_at', '')}; "
                        f"signalen: {', '.join(item.get('event_flags', []))}"
                    )

    long_tech_count = sum(
        row.get("score_status") == "OK"
        and (as_float(row.get("long_score")) or -1) >= 3
        and (as_float(row.get("close_completed")) or 0) > (as_float(row.get("sma50")) or float("inf"))
        for row in technical
    )
    short_tech_count = len(short_candidates)
    borrow_available = sum(row.get("status") == "AVAILABLE" for row in borrow_rows)
    borrow_unknown = sum(row.get("status") == "ONBEKEND" for row in borrow_rows)
    source_warnings = [
        row for row in source_rows
        if row.get("status") not in {"CURRENT", "MANUAL"}
    ]

    pending = [
        "Risk-on/risk-off marktregime: expliciete criteria ontbreken.",
        "Long-entry: actuele consolidatiepivot, breakoutdatum/-volume, 52-week high/ATH, HA-stop en 2R-validatie.",
        "Short-entry: laatste HA High=Open-stop, 2R-validatie en definitieve squeeze-/gaprisicobeoordeling.",
    ]
    if borrow_unknown:
        pending.append(f"IBKR-borrowinventaris ontbreekt voor {borrow_unknown} Short-kandidaten.")
    if source_warnings:
        pending.append("Bronverversing/dekking bevat waarschuwingen of onbekende statussen.")
    if risk_status.get("status") != "FULL":
        pending.append("Nieuws- en Short-risicocontrole is gedeeltelijk of bevat onbekende gegevens.")
    if fundamental_status.get("unknown", 0):
        pending.append("Fundamentele gegevens ontbreken voor een of meer Long-kandidaten.")
    if sw_status.get("unknown", 0):
        pending.append("SW Financial Health ontbreekt voor een of meer Long-kandidaten.")

    report_status = "PARTIAL"
    details = {
        "status": report_status,
        "session_date": session,
        "technical_score_status": tech_status.get("status", "ONBEKEND"),
        "long_fundamental_status": fundamental_status.get("status", "ONBEKEND"),
        "sw_financial_health_status": sw_status.get("status", "ONBEKEND"),
        "short_borrow_status": borrow_status.get("status", "ONBEKEND"),
        "candidate_risk_news_status": risk_status.get("status", "ONBEKEND"),
        "long_technical_candidates": long_tech_count,
        "long_approved_candidates": len(long_candidates),
        "short_technical_candidates": short_tech_count,
        "short_borrow_available": borrow_available,
        "short_borrow_unknown": borrow_unknown,
        "ha_long_signals": len(ha_long),
        "ha_short_signals": len(ha_short),
        "pending_components": pending,
    }

    lines = [
        f"# DAILY STOCK RADAR — GEDEELTELIJKE DSR",
        f"**Gegevensdatum:** {session}  ",
        f"**Status:** {report_status}",
        "",
        "## 1. Marktbeeld",
        *market_lines,
        "",
        "## 2. Brondekking",
        _table(["Bron", "Status", "Tickers", "Laatste succes", "Leeftijd (uur)", "Detail"], source_table_rows),
        "",
        "## 3. Long",
        f"Technisch gekwalificeerd: **{long_tech_count}**. Fundamenteel PASS: **{fundamental_status.get('passed', 0)}**; "
        f"SW PASS: **{sw_status.get('passed', 0)}**; SW uitgesloten: **{sw_status.get('excluded_sw', 0)}**; "
        f"onbekend: **{sw_status.get('unknown', 0)}**. Goedgekeurd voor verdere Long-beoordeling: **{len(long_candidates)}**.",
        _table(["Ticker", "Bron", "Sector", "Industry", "HA", "Score", "SW", "Close", "20d pivot-ref", "RVOL 5/21", "Nieuws"], long_table),
        "",
        "## 4. Short",
        f"Technisch gekwalificeerd: **{short_tech_count}**. IBKR beschikbaar: **{borrow_available}**; "
        f"IBKR onbekend: **{borrow_unknown}**.",
        _table(["Ticker", "Bron", "Sector", "Industry", "HA", "Score", "SW", "Borrow", "Fee %", "Shares", "Short float %", "DTC", "Nieuws"], short_table),
        "",
        "## 5. HA-signalen",
        f"Long-signalen die aan HA Low=Open en SMA20/SMA50 voldoen: **{len(ha_long)}**.",
        _table(["Ticker", "Sector", "Industry", "Close", "Afstand HA Low %", "RVOL 5/21"], [
            [row.get("ticker"), row.get("sector"), row.get("industry"), row.get("close"),
             row.get("distance_from_low_pct"), row.get("rvol_5_21")] for row in ha_long
        ]),
        f"Short-signalen die aan HA High=Open en SMA20/SMA50 voldoen: **{len(ha_short)}**.",
        _table(["Ticker", "Sector", "Industry", "Close", "Afstand HA High %", "RVOL 5/21"], [
            [row.get("ticker"), row.get("sector"), row.get("industry"), row.get("close"),
             round((as_float(row.get("ha_high")) - as_float(row.get("ha_close"))) / as_float(row.get("ha_high")) * 100, 1)
             if as_float(row.get("ha_high")) and as_float(row.get("ha_close")) is not None else "ONBEKEND",
             row.get("rvol_5_21")] for row in ha_short
        ]),
        "",
        "## 6. Nieuws-/eventsignalen",
        *(risk_review if risk_review else ["_Geen nieuwsitems met de ingestelde event-zoektermen aangetroffen. Dit is geen bewijs dat er geen risico bestaat._"]),
        "",
        "## 7. Nog niet volledig uitgevoerd",
        *[f"- {item}" for item in pending],
        "",
        "Er worden geen koop- of shortacties gepubliceerd zolang pivot, stop, 2R en de bijbehorende technische haalbaarheid niet volledig zijn geverifieerd.",
        "",
    ]
    report = "\n".join(lines)
    return report, details


def update_run_status(details: dict):
    current = read_json("dsr_run_status.json")
    current["status"] = "PARTIAL"
    current["report_status"] = details["status"]
    current["component_status"] = {
        "technical_scores": details["technical_score_status"],
        "long_fundamentals": details["long_fundamental_status"],
        "sw_financial_health": details["sw_financial_health_status"],
        "short_borrow": details["short_borrow_status"],
        "candidate_risk_news": details["candidate_risk_news_status"],
    }
    current["pending_components"] = details["pending_components"]
    temporary = RUN_STATUS.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(current, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(RUN_STATUS)


def main() -> int:
    report, details = build_report()
    OUTPUT.write_text(report, encoding="utf-8")
    STATUS_OUTPUT.write_text(json.dumps(details, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    update_run_status(details)
    print(f"DSR-rapport geschreven: {OUTPUT.relative_to(ROOT)}; status={details['status']}")
    print(
        f"Long technisch={details['long_technical_candidates']} goedgekeurd={details['long_approved_candidates']}; "
        f"Short technisch={details['short_technical_candidates']} borrow beschikbaar={details['short_borrow_available']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
