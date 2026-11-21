#!/usr/bin/env python3
"""Apply the agreed fundamental checks to technically qualified DSR Long candidates."""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
SCORES = ROOT / "data" / "technical_scores.csv"
OUTPUT = ROOT / "data" / "long_fundamentals.csv"
STATUS_OUTPUT = ROOT / "data" / "long_fundamental_status.json"
MIN_MARKET_CAP = 2_000_000_000
MIN_AVERAGE_VOLUME = 500_000
MIN_ROE = 0.10
SLEEP_SECONDS = 0.4


def number(value):
    try:
        result = float(value)
        return result if pd.notna(result) else None
    except (TypeError, ValueError):
        return None


def has_usable_fundamental_data(info: dict) -> bool:
    """Detect an empty Yahoo quoteSummary response rather than treating it as valid missing fields."""
    keys = ("marketCap", "averageVolume", "operatingMargins", "returnOnEquity", "revenueGrowth", "debtToEquity")
    return any(number(info.get(key)) is not None for key in keys)


def evaluate_fundamentals(info: dict, sector: str = "", industry: str = "") -> dict:
    """Return explicit PASS/FAIL/UNKNOWN checks; Yahoo D/E is reported in percent."""
    market_cap = number(info.get("marketCap"))
    average_volume = number(info.get("averageVolume"))
    operating_margin = number(info.get("operatingMargins"))
    roe = number(info.get("returnOnEquity"))
    revenue_growth = number(info.get("revenueGrowth"))
    debt_to_equity_raw = number(info.get("debtToEquity"))

    checks = {
        "market_cap": "UNKNOWN" if market_cap is None else ("PASS" if market_cap >= MIN_MARKET_CAP else "FAIL"),
        "average_volume": "UNKNOWN" if average_volume is None else ("PASS" if average_volume >= MIN_AVERAGE_VOLUME else "FAIL"),
        "operating_margin": "UNKNOWN" if operating_margin is None else ("PASS" if operating_margin > 0 else "FAIL"),
        "roe": "UNKNOWN" if roe is None else ("PASS" if roe > MIN_ROE else "FAIL"),
        "revenue_growth": "UNKNOWN" if revenue_growth is None else ("PASS" if revenue_growth > 0 else "FAIL"),
    }

    financial_sector = "financial" in str(sector).lower()
    financial_industry = any(word in str(industry).lower() for word in
                              ("bank", "insurance", "credit", "capital markets", "financial data"))
    if financial_sector or financial_industry:
        debt_equity_status = "NVT"
        debt_equity_ratio = None
    elif debt_to_equity_raw is None:
        debt_equity_status = "UNKNOWN"
        debt_equity_ratio = None
    else:
        debt_equity_ratio = debt_to_equity_raw / 100.0
        debt_equity_status = "PASS" if debt_equity_ratio < 1.0 else "FAIL"
    checks["debt_to_equity"] = debt_equity_status

    if "FAIL" in checks.values():
        status = "FAIL"
    elif "UNKNOWN" in checks.values():
        status = "UNKNOWN"
    else:
        status = "PASS"

    industry_text = str(industry).lower()
    biotech_review = "REVIEW" if ("biotech" in industry_text or "drug manufacturers" in industry_text) else "NVT"
    return {
        "fundamental_status": status,
        "checks": checks,
        "market_cap": market_cap,
        "average_volume": average_volume,
        "operating_margin": operating_margin,
        "roe": roe,
        "revenue_growth": revenue_growth,
        "debt_to_equity_raw_pct": debt_to_equity_raw,
        "debt_to_equity_ratio": debt_equity_ratio,
        "biotech_clinical_risk_review": biotech_review,
    }


def load_candidates(path: Path = SCORES) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError("technical_scores.csv ontbreekt")
    data = pd.read_csv(path, dtype={"ticker": str})
    required = {"ticker", "score_status", "long_score", "close_completed", "sma50",
                "sources", "sector", "industry", "score_date"}
    if not required.issubset(data.columns):
        raise ValueError(f"technical_scores.csv mist kolommen: {sorted(required - set(data.columns))}")
    for column in ("long_score", "close_completed", "sma50"):
        data[column] = pd.to_numeric(data[column], errors="coerce")
    above_sma20 = data.get("above_sma20_completed", pd.Series(index=data.index, dtype="object"))
    above_sma50 = data.get("above_sma50_completed", pd.Series(index=data.index, dtype="object"))
    return data[
        (data["score_status"] == "OK")
        & (data["long_score"] >= 3)
        & (above_sma20.astype(str).str.lower().isin(["true", "1"]))
        & (above_sma50.astype(str).str.lower().isin(["true", "1"]))
    ].copy()


def write_status(payload: dict):
    temporary = STATUS_OUTPUT.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(STATUS_OUTPUT)



def build_stale_fallback_rows(candidates, previous_rows, checked_at, reason):
    previous = {str(row.get("ticker", "")).strip().upper(): dict(row)
                for row in previous_rows if str(row.get("ticker", "")).strip()}
    output = []
    for _, candidate in candidates.reset_index(drop=True).iterrows():
        ticker = str(candidate["ticker"]).strip().upper()
        row = previous.get(ticker)
        if row is not None:
            row["sources"] = candidate.get("sources", "")
            row["sector"] = candidate.get("sector", "") or "ONBEKEND"
            row["industry"] = candidate.get("industry", "") or "ONBEKEND"
            row["technical_score"] = int(candidate["long_score"])
            row["score_date"] = candidate.get("score_date", "")
            row["data_source"] = f"{row.get('data_source', 'Yahoo Finance quoteSummary')} (STALE_FALLBACK)"
            row["error"] = reason
        else:
            row = {
                "ticker": ticker, "sources": candidate.get("sources", ""),
                "sector": candidate.get("sector", "") or "ONBEKEND",
                "industry": candidate.get("industry", "") or "ONBEKEND",
                "technical_score": int(candidate["long_score"]),
                "score_date": candidate.get("score_date", ""),
                "fundamental_status": "UNKNOWN",
                "checks": {"market_cap": "UNKNOWN", "average_volume": "UNKNOWN",
                           "operating_margin": "UNKNOWN", "roe": "UNKNOWN",
                           "revenue_growth": "UNKNOWN", "debt_to_equity": "UNKNOWN"},
                "checked_at": checked_at,
                "data_source": "Yahoo Finance quoteSummary (STALE_FALLBACK)",
                "error": reason,
            }
        output.append(row)
    return output


def write_rows(rows, columns):
    output_rows = []
    for row in rows:
        clean = dict(row)
        if not isinstance(clean.get("checks"), str):
            clean["checks"] = json.dumps(clean.get("checks", {}), ensure_ascii=False)
        output_rows.append(clean)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(output_rows, columns=columns).to_csv(OUTPUT, index=False)


def read_status_file():
    try:
        return json.loads(STATUS_OUTPUT.read_text(encoding="utf-8"))
    except Exception:
        return {}


def main() -> int:
    try:
        candidates = load_candidates()
    except Exception as exc:
        write_status({"status": "PARTIAL", "candidate_count": 0, "errors": [str(exc)]})
        print(f"Long-fundamentalscreen niet beschikbaar: {exc}", file=sys.stderr)
        return 1

    rows, errors = [], []
    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    previous_rows = (pd.read_csv(OUTPUT, dtype={"ticker": str}).fillna("").to_dict("records")
                     if OUTPUT.exists() else [])
    previous_status = read_status_file()
    for index, candidate in candidates.reset_index(drop=True).iterrows():
        ticker = str(candidate["ticker"]).strip().upper()
        try:
            info = yf.Ticker(ticker).info or {}
            if not has_usable_fundamental_data(info):
                raise RuntimeError("Yahoo Finance quoteSummary returned no usable fundamental fields (possible Invalid Crumb, access block or rate limit).")
            result = evaluate_fundamentals(info, str(candidate.get("sector", "")),
                                           str(candidate.get("industry", "")))
            row = {
                "ticker": ticker, "sources": candidate.get("sources", ""),
                "sector": candidate.get("sector", "") or "ONBEKEND",
                "industry": candidate.get("industry", "") or "ONBEKEND",
                "technical_score": int(candidate["long_score"]),
                "score_date": candidate.get("score_date", ""),
                **result, "checked_at": checked_at,
                "data_source": "Yahoo Finance quoteSummary",
                "error": "",
            }
        except Exception as exc:
            errors.append(f"{ticker}: {exc}")
            row = {
                "ticker": ticker, "sources": candidate.get("sources", ""),
                "sector": candidate.get("sector", "") or "ONBEKEND",
                "industry": candidate.get("industry", "") or "ONBEKEND",
                "technical_score": int(candidate["long_score"]),
                "score_date": candidate.get("score_date", ""),
                "fundamental_status": "UNKNOWN",
                "checks": {"market_cap": "UNKNOWN", "average_volume": "UNKNOWN",
                           "operating_margin": "UNKNOWN", "roe": "UNKNOWN",
                           "revenue_growth": "UNKNOWN", "debt_to_equity": "UNKNOWN"},
                "checked_at": checked_at, "data_source": "Yahoo Finance quoteSummary",
                "error": str(exc),
            }
        rows.append(row)
        print(f"[{index + 1}/{len(candidates)}] {ticker}: {row['fundamental_status']}")
        time.sleep(SLEEP_SECONDS)

    columns = ["ticker", "sources", "sector", "industry", "technical_score", "score_date",
               "fundamental_status", "checks", "market_cap", "average_volume",
               "operating_margin", "roe", "revenue_growth", "debt_to_equity_raw_pct",
               "debt_to_equity_ratio", "biotech_clinical_risk_review", "checked_at",
               "data_source", "error"]
    global_unavailable = bool(rows) and all(
        row["fundamental_status"] == "UNKNOWN"
        and not any(number(row.get(key)) is not None for key in
                    ("market_cap", "average_volume", "operating_margin", "roe",
                     "revenue_growth", "debt_to_equity_raw_pct"))
        for row in rows
    )
    if global_unavailable:
        reason = ("Yahoo Finance quoteSummary returned no usable fundamental fields for any current Long candidate; "
                  "the last validated values are retained as STALE_FALLBACK.")
        fallback_rows = build_stale_fallback_rows(candidates, previous_rows, checked_at, reason)
        write_rows(fallback_rows, columns)
        last_success_at = previous_status.get("last_success_at") or previous_status.get("checked_at")
        last_known_counts = {"passed": previous_status.get("passed", 0),
                             "failed": previous_status.get("failed", 0),
                             "unknown": previous_status.get("unknown", 0)}
        payload = {"status": "PARTIAL", "data_status": "STALE_FALLBACK",
                   "candidate_count": len(candidates), "passed": 0, "failed": 0,
                   "unknown": len(candidates), "checked_at": checked_at,
                   "last_success_at": last_success_at, "last_known_counts": last_known_counts,
                   "fallback_used": True, "errors": [reason]}
        write_status(payload)
        print(f"Long-fundamentals: Yahoo leverde geen bruikbare velden voor {len(candidates)} kandidaten; "
              "laatste gevalideerde gegevens behouden als STALE_FALLBACK.")
        return 1

    write_rows(rows, columns)
    passed = sum(row["fundamental_status"] == "PASS" for row in rows)
    failed = sum(row["fundamental_status"] == "FAIL" for row in rows)
    unknown = sum(row["fundamental_status"] == "UNKNOWN" for row in rows)
    status = "FULL" if unknown == 0 and not errors else "PARTIAL"
    payload = {"status": status, "data_status": "CURRENT", "candidate_count": len(rows),
               "passed": passed, "failed": failed, "unknown": unknown,
               "checked_at": checked_at, "last_success_at": checked_at,
               "fallback_used": False, "errors": errors}
    write_status(payload)
    print(f"Long-fundamentals: {passed} PASS, {failed} FAIL, {unknown} UNKNOWN; status={status}")
    return 0 if status == "FULL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
