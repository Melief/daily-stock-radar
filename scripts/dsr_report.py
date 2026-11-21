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


def proximity_bar(distance_to_high, kind: str) -> str:
    distance = as_float(distance_to_high)
    if distance is None:
        return "ONBEKEND"
    percent = 100.0 - distance
    if kind == "52w":
        marker = "🟢" if percent > 100 else "🟠" if percent >= 95 else "🔴"
    elif kind == "ath":
        marker = "🟢" if percent >= 90 else "🟠" if percent >= 85 else "🔴"
    else:
        raise ValueError("kind moet 52w of ath zijn")
    filled = max(0, min(10, round(max(0.0, min(100.0, percent)) / 10)))
    bar = "█" * filled + "░" * (10 - filled)
    return f"{marker} {percent:.1f}% {bar}"


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


def select_long_technical_candidates(technical_rows: list[dict]) -> list[dict]:
    return [
        row for row in technical_rows
        if row.get("score_status") == "OK"
        and (as_float(row.get("long_score")) is not None)
        and as_float(row.get("long_score")) >= 3
        and as_bool(row.get("above_sma20_completed")) is True
        and as_bool(row.get("above_sma50_completed")) is True
    ]


def select_ha_long_signals(ha_rows: list[dict]) -> list[dict]:
    return [row for row in ha_rows if as_bool(row.get("ha_pivot_up")) is True]


def select_ha_short_signals(ha_rows: list[dict]) -> list[dict]:
    return [row for row in ha_rows if as_bool(row.get("ha_pivot_down")) is True]


def pivot_audit_cells(entry: dict) -> list:
    """Return consolidation-pivot status separately from breakout confirmation."""
    return [
        entry.get("consolidation_pivot", ""),
        entry.get("consolidation_pivot_date", ""),
        entry.get("consolidation_pivot_status", "ONBEKEND"),
        entry.get("breakout_reference_status", "ONBEKEND"),
        entry.get("breakout_reference_date", ""),
        entry.get("breakout_reference_close", ""),
        entry.get("breakout_reference_ha_close", ""),
        entry.get("breakout_reference_volume", ""),
    ]


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
    entry_risk_rows = read_csv("entry_risk.csv")
    market = read_json("market_context.json")
    run_status = read_json("dsr_run_status.json")
    tech_status = read_json("technical_score_status.json")
    fundamental_status = read_json("long_fundamental_status.json")
    sw_status = read_json("long_sw_status.json")
    borrow_status = read_json("short_borrow_status.json")
    risk_status = read_json("candidate_risk_news_status.json")
    entry_risk_status = read_json("entry_risk_status.json")

    tech_by_ticker = {row.get("ticker", "").upper(): row for row in technical}
    ha_by_ticker = {row.get("ticker", "").upper(): row for row in ha_rows}
    borrow_by_ticker = {row.get("ticker", "").upper(): row for row in borrow_rows}
    risk_by_key = {
        (row.get("ticker", "").upper(), row.get("candidate_type", "").upper()): row
        for row in risk_rows
    }
    entry_risk_by_key = {
        (row.get("ticker", "").upper(), row.get("candidate_type", "").upper()): row
        for row in entry_risk_rows
    }

    long_candidates = select_long_candidates(sw_rows)
    short_candidates = select_short_candidates(technical)
    session = (market.get("session_date") or
               (technical[0].get("score_date") if technical else "ONBEKEND"))

    long_table = []
    for candidate in long_candidates:
        ticker = candidate.get("ticker", "").upper()
        tech = tech_by_ticker.get(ticker, {})
        ha = ha_by_ticker.get(ticker, {})
        risk = risk_by_key.get((ticker, "LONG"), {})
        entry = entry_risk_by_key.get((ticker, "LONG"), {})
        long_table.append([
            ticker, candidate.get("sources", ""), candidate.get("sector", ""),
            candidate.get("industry", ""), ha.get("ha_day_type", tech.get("ha_day_type", "")),
            candidate.get("technical_score", ""), f"{candidate.get('financial_health_score')}/6",
            entry.get("entry", tech.get("close_completed", "")), entry.get("stop", ""),
            entry.get("risk_pct", ""), entry.get("target_2r", ""),
            entry.get("target_feasibility", ""), *pivot_audit_cells(entry), entry.get("long_buy_zone_status", ""),
            risk.get("high_52w", ""), proximity_bar(risk.get("distance_to_52w_high_pct"), "52w"),
            risk.get("all_time_high", ""), proximity_bar(risk.get("distance_to_ath_pct"), "ath"),
            tech.get("rvol_5_21", ""), risk.get("risk_status", "ONBEKEND"),
            entry.get("action", "ONBEKEND"),
        ])

    short_table = []
    for candidate in short_candidates:
        ticker = candidate.get("ticker", "").upper()
        ha = ha_by_ticker.get(ticker, {})
        borrow = borrow_by_ticker.get(ticker, {})
        risk = risk_by_key.get((ticker, "SHORT"), {})
        entry = entry_risk_by_key.get((ticker, "SHORT"), {})
        short_table.append([
            ticker, candidate.get("sources", ""), candidate.get("sector", ""),
            candidate.get("industry", ""), ha.get("ha_day_type", candidate.get("ha_day_type", "")),
            candidate.get("short_score", ""), "__EMPTY__",
            entry.get("entry", candidate.get("close_completed", "")), entry.get("stop", ""),
            entry.get("risk_pct", ""), entry.get("target_2r", ""),
            entry.get("target_feasibility", ""), *pivot_audit_cells(entry), borrow.get("status", "ONBEKEND"), borrow.get("fee_rate_pct", ""),
            borrow.get("available_shares", ""), risk.get("short_percent_of_float", ""),
            risk.get("days_to_cover", ""), risk.get("high_52w", ""),
            proximity_bar(risk.get("distance_to_52w_high_pct"), "52w"), risk.get("all_time_high", ""),
            proximity_bar(risk.get("distance_to_ath_pct"), "ath"), risk.get("risk_status", "ONBEKEND"),
            entry.get("action", "ONBEKEND"),
        ])

    ha_long = select_ha_long_signals(ha_rows)
    ha_short = select_ha_short_signals(ha_rows)
    ha_long.sort(key=lambda row: (
        as_float(row.get("ha_pivot_distance_pct"))
        if as_float(row.get("ha_pivot_distance_pct")) is not None else float("inf")
    ))
    ha_short.sort(key=lambda row: (
        as_float(row.get("ha_pivot_distance_pct"))
        if as_float(row.get("ha_pivot_distance_pct")) is not None else float("inf")
    ))

    market_lines = []
    symbols = market.get("symbols", {})
    for label in ("SPX", "QQQ"):
        item = symbols.get(label, {})
        market_lines.append(
            f"- **{label}:** close {clean(item.get('close'))}; SMA20 {clean(item.get('sma20'))}; "
            f"SMA50 {clean(item.get('sma50'))}; positie {clean(item.get('position'))}; "
            f"EMA8 {clean(item.get('ema8'))}; EMA21 {clean(item.get('ema21'))}; "
            f"EMA-status {clean(item.get('ema_momentum_status'))}; "
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

    long_tech_count = len(select_long_technical_candidates(technical))
    short_tech_count = len(short_candidates)
    borrow_available = sum(row.get("status") == "AVAILABLE" for row in borrow_rows)
    borrow_unknown = sum(row.get("status") == "ONBEKEND" for row in borrow_rows)
    source_warnings = [
        row for row in source_rows
        if row.get("status") not in {"CURRENT", "MANUAL"}
    ]

    pending = []
    if market.get("status") != "FULL" or market.get("data_status") != "FULL":
        pending.append("SPX/QQQ-marktcontext ontbreekt of is verouderd.")
    if tech_status.get("status") != "FULL":
        pending.append("Technische Long/Short-scores zijn niet volledig berekend.")
    if source_warnings:
        pending.append("Bronverversing/dekking bevat waarschuwingen of verouderde bronnen.")
    if risk_status.get("status") != "FULL":
        pending.append("Historische koersdata of HA-consolidatiepivotcontrole is onvolledig.")
    if entry_risk_status.get("status") != "FULL":
        pending.append("Entry, HA-stop, risico%, 2R of technische doelhaalbaarheid is onvolledig.")
    fundamental_unknown_tickers = {
        str(row.get("ticker", "")).strip().upper()
        for row in fundamentals if str(row.get("fundamental_status", "")).upper() == "UNKNOWN"
    }
    sw_excluded_tickers = {
        str(row.get("ticker", "")).strip().upper()
        for row in sw_rows if str(row.get("sw_status", "")).upper() == "EXCLUDED"
    }
    nonblocking_fundamental_unknown = sorted(fundamental_unknown_tickers & sw_excluded_tickers)
    unresolved_fundamental_unknown = sorted(fundamental_unknown_tickers - sw_excluded_tickers)
    # External financial, borrow and news data remain visible as non-blocking
    # enrichments. UNKNOWN never becomes PASS and therefore cannot approve a Long.
    non_blocking_components = []
    if (fundamental_status.get("status") != "FULL"
            or fundamental_status.get("data_status", "UNKNOWN") != "CURRENT"
            or fundamental_status.get("unknown", 0)
            or unresolved_fundamental_unknown):
        non_blocking_components.append(
            "Long fundamentals: " + str(fundamental_status.get("data_status", "UNKNOWN"))
            + f"; PASS={fundamental_status.get('passed', 0)}, FAIL={fundamental_status.get('failed', 0)}, "
              f"UNKNOWN={fundamental_status.get('unknown', 0)}."
        )
    if sw_status.get("status") != "FULL" or sw_status.get("unknown", 0):
        non_blocking_components.append(
            f"Simply Wall St: status={sw_status.get('status', 'UNKNOWN')}, "
            f"PASS={sw_status.get('passed', 0)}, excluded={sw_status.get('excluded_sw', 0)}, "
            f"UNKNOWN={sw_status.get('unknown', 0)}."
        )
    if borrow_status.get("status") != "FULL" or borrow_status.get("unknown", 0):
        non_blocking_components.append(
            f"IBKR borrow: status={borrow_status.get('status', 'UNKNOWN')}, "
            f"unknown={borrow_status.get('unknown', 0)}."
        )
    if risk_status.get("status") != "FULL" or risk_status.get("unknown", 0) or risk_status.get("review_required", 0):
        non_blocking_components.append(
            f"News/risk: status={risk_status.get('status', 'UNKNOWN')}, "
            f"unknown={risk_status.get('unknown', 0)}, review={risk_status.get('review_required', 0)}."
        )

    report_status = "FULL" if not pending else "PARTIAL"
    details = {
        "status": report_status,
        "session_date": session,
        "technical_score_status": tech_status.get("status", "ONBEKEND"),
        "long_fundamental_status": fundamental_status.get("status", "ONBEKEND"),
        "long_fundamental_data_status": fundamental_status.get("data_status", "UNKNOWN"),
        "fundamental_unknown_excluded_by_sw": nonblocking_fundamental_unknown,
        "unresolved_fundamental_unknown": unresolved_fundamental_unknown,
        "sw_financial_health_status": sw_status.get("status", "ONBEKEND"),
        "short_borrow_status": borrow_status.get("status", "ONBEKEND"),
        "candidate_risk_news_status": risk_status.get("status", "ONBEKEND"),
        "entry_risk_status": entry_risk_status.get("status", "ONBEKEND"),
        "long_technical_candidates": long_tech_count,
        "long_approved_candidates": len(long_candidates),
        "short_technical_candidates": short_tech_count,
        "short_borrow_available": borrow_available,
        "short_borrow_unknown": borrow_unknown,
        "ha_long_signals": len(ha_long),
        "ha_short_signals": len(ha_short),
        "pending_components": pending,
        "non_blocking_components": non_blocking_components,
    }

    long_summary = (
        f"Technisch gekwalificeerd: **{long_tech_count}**. Fundamenteel PASS: **{fundamental_status.get('passed', 0)}**; "
        f"FAIL: **{fundamental_status.get('failed', 0)}**; onbekend: **{fundamental_status.get('unknown', 0)}**; data: **{fundamental_status.get('data_status', 'UNKNOWN')}**. "
        f"SW PASS: **{sw_status.get('passed', 0)}**; SW uitgesloten: **{sw_status.get('excluded_sw', 0)}**; "
        f"onbekend: **{sw_status.get('unknown', 0)}**. Goedgekeurd voor verdere Long-beoordeling: **{len(long_candidates)}**."
    )
    if nonblocking_fundamental_unknown:
        long_summary += " Fundamenteel ONBEKEND maar al uitgesloten door SW: " + ", ".join(nonblocking_fundamental_unknown) + "."
    long_summary += " Externe financiële gegevens zijn aanvullend; ONBEKEND blijft ONBEKEND en geeft geen Long-goedkeuring."
    lines = [
        f"# DAILY STOCK RADAR — {'VOLLEDIGE DSR' if report_status == 'FULL' else 'GEDEELTELIJKE DSR'}",
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
        long_summary,
        _table(["Ticker", "Bron", "Sector", "Industry", "HA", "Score", "SW", "Entry", "Stop", "Risk %", "2R", "2R haalbaarheid", "Consolidatiepivot", "Pivotdatum", "Pivotstatus", "Breakoutstatus", "Breakoutdatum", "Officieel slot", "HA-slot", "Volume", "Koopzone", "52w high (prior)", "Afstand %", "ATH (prior)", "Afstand %", "RVOL 5/21", "Nieuws", "Actie"], long_table),
        "",
        "## 4. Short",
        f"Technisch gekwalificeerd: **{short_tech_count}**. IBKR beschikbaar: **{borrow_available}**; "
        f"IBKR onbekend: **{borrow_unknown}**.",
        _table(["Ticker", "Bron", "Sector", "Industry", "HA", "Score", "SW", "Entry", "Stop", "Risk %", "2R", "2R haalbaarheid", "Consolidatiepivot", "Pivotdatum", "Pivotstatus", "Doorbraakstatus", "Doorbraakdatum", "Officieel slot", "HA-slot", "Volume", "Borrow", "Fee %", "Shares", "Short float %", "DTC", "52w high (prior)", "Afstand %", "ATH (prior)", "Afstand %", "Nieuws", "Actie"], short_table),
        "",
        "## 5. HA-signalen",
        f"Long-signalen volgens HA 21/8 (HA Low=Open; slotkoers boven SMA20 en SMA50): **{len(ha_long)}**.",
        _table(["Ticker", "Sector", "Industry", "Close", "Afstand HA Low %", "Leeftijd", "RVOL 5/21"], [
            [row.get("ticker"), row.get("sector"), row.get("industry"), row.get("close"),
             row.get("ha_pivot_distance_pct"), row.get("ha_pivot_low_age"), row.get("rvol_5_21")]
            for row in ha_long
        ]),
        f"Short-signalen volgens HA 21/8 (HA High=Open; slotkoers onder SMA20 en SMA50): **{len(ha_short)}**.",
        _table(["Ticker", "Sector", "Industry", "Close", "Afstand HA High %", "Leeftijd", "RVOL 5/21"], [
            [row.get("ticker"), row.get("sector"), row.get("industry"), row.get("close"),
             row.get("ha_pivot_distance_pct"), row.get("ha_pivot_high_age"), row.get("rvol_5_21")]
            for row in ha_short
        ]),
        "",
        "## 6. Nieuws-/eventsignalen",
        f"News/risk: **{clean(risk_status.get('status'))}**; gecontroleerd: {clean(risk_status.get('checked'))}; "
        f"onbekend: {clean(risk_status.get('unknown'))}; review vereist: {clean(risk_status.get('review_required'))}.",
        f"Long fundamentals: **{clean(fundamental_status.get('data_status', 'UNKNOWN'))}**; "
        f"SW Financial Health: **{clean(sw_status.get('status'))}**; "
        f"IBKR borrow: **{clean(borrow_status.get('status'))}**. Deze externe verrijkingen blokkeren DSR FULL niet; UNKNOWN wordt niet als PASS gebruikt.",
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
    current["status"] = details["status"]
    current["report_status"] = details["status"]
    current["component_status"] = {
        "technical_scores": details["technical_score_status"],
        "long_fundamentals": details["long_fundamental_status"],
        "sw_financial_health": details["sw_financial_health_status"],
        "short_borrow": details["short_borrow_status"],
        "candidate_risk_news": details["candidate_risk_news_status"],
        "entry_risk": details["entry_risk_status"],
    }
    current["pending_components"] = details["pending_components"]
    current["non_blocking_components"] = details.get("non_blocking_components", [])
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
    return 0 if details["status"] == "FULL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
