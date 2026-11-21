#!/usr/bin/env python3
"""Validate manually verified Simply Wall St Financial Health scores for Long candidates.

No scraping or API access is performed. data/sw_financial_health.csv is the
controlled record of manual checks made on the public Simply Wall St website.
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
FUNDAMENTALS = ROOT / "data" / "long_fundamentals.csv"
INPUT = ROOT / "data" / "sw_financial_health.csv"
OUTPUT = ROOT / "data" / "long_sw_status.csv"
STATUS_OUTPUT = ROOT / "data" / "long_sw_status.json"
FUNDAMENTAL_STATUS = ROOT / "data" / "long_fundamental_status.json"


def load_verified_scores(path: Path = INPUT) -> dict[str, dict]:
    if not path.exists():
        raise FileNotFoundError("data/sw_financial_health.csv ontbreekt")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    required = {"ticker", "financial_health_score", "checked_at", "source_url"}
    if rows and not required.issubset(rows[0]):
        raise ValueError(f"SW-bestand mist kolommen: {sorted(required - set(rows[0]))}")
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        ticker = str(row.get("ticker", "")).strip().upper()
        if not ticker:
            continue
        try:
            score = int(row.get("financial_health_score", ""))
        except (TypeError, ValueError):
            continue
        checked = str(row.get("checked_at", "")).strip()
        url = str(row.get("source_url", "")).strip()
        try:
            date.fromisoformat(checked[:10])
        except ValueError:
            continue
        parsed = urlparse(url)
        if score < 0 or score > 6 or parsed.scheme != "https" or parsed.hostname not in {
            "simplywall.st", "www.simplywall.st"
        }:
            continue
        grouped.setdefault(ticker, []).append({
            "score": score, "checked_at": checked, "source_url": url
        })
    verified = {}
    for ticker, matches in grouped.items():
        matches.sort(key=lambda item: item["checked_at"], reverse=True)
        # Multiple entries with the same newest timestamp are ambiguous.
        if len(matches) > 1 and matches[0]["checked_at"] == matches[1]["checked_at"]:
            continue
        verified[ticker] = matches[0]
    return verified


def load_fundamental_data_status(path: Path = FUNDAMENTAL_STATUS) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return "UNKNOWN"
    return str(payload.get("data_status", "CURRENT")).upper()


def build_sw_rows(fundamentals: pd.DataFrame, verified: dict[str, dict], fundamental_data_status: str = "CURRENT") -> list[dict]:
    output = []
    for _, candidate in fundamentals.iterrows():
        ticker = str(candidate.get("ticker", "")).strip().upper()
        fundamental_status = str(candidate.get("fundamental_status", "UNKNOWN")).upper()
        row = {
            "ticker": ticker,
            "sources": candidate.get("sources", ""),
            "sector": candidate.get("sector", "") or "ONBEKEND",
            "industry": candidate.get("industry", "") or "ONBEKEND",
            "technical_score": candidate.get("technical_score", ""),
            "fundamental_status": fundamental_status,
            "financial_health_score": "",
            "checked_at": "",
            "source_url": "",
        }
        item = verified.get(ticker)
        if item is not None and (fundamental_data_status != "CURRENT" or fundamental_status != "FAIL"):
            row["financial_health_score"] = item["score"]
            row["checked_at"] = item["checked_at"]
            row["source_url"] = item["source_url"]
        if fundamental_data_status != "CURRENT":
            row["sw_status"] = "EXCLUDED" if item is not None and item["score"] < 4 else "ONBEKEND_FUNDAMENTALS"
        elif fundamental_status == "FAIL":
            row["sw_status"] = "NIET_BEOORDEELD_FUNDAMENTEEL_UITGESLOTEN"
        elif item is not None and item["score"] < 4:
            row["sw_status"] = "EXCLUDED"
        elif fundamental_status != "PASS":
            row["sw_status"] = "ONBEKEND_FUNDAMENTALS"
        elif item is None:
            row["sw_status"] = "ONBEKEND"
        else:
            row["sw_status"] = "PASS"
        output.append(row)
    return output


def write_status(payload: dict):
    temporary = STATUS_OUTPUT.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(STATUS_OUTPUT)


def main() -> int:
    try:
        fundamentals = pd.read_csv(FUNDAMENTALS, dtype={"ticker": str})
        verified = load_verified_scores()
        fundamental_data_status = load_fundamental_data_status()
        rows = build_sw_rows(fundamentals, verified, fundamental_data_status)
    except Exception as exc:
        write_status({"status": "PARTIAL", "errors": [str(exc)]})
        print(f"SW-controle niet beschikbaar: {exc}", file=sys.stderr)
        return 1

    columns = ["ticker", "sources", "sector", "industry", "technical_score",
               "fundamental_status", "financial_health_score", "checked_at",
               "source_url", "sw_status"]
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=columns).to_csv(OUTPUT, index=False)
    passed = sum(row["sw_status"] == "PASS" for row in rows)
    excluded = sum(row["sw_status"] == "EXCLUDED" for row in rows)
    unknown = sum(row["sw_status"].startswith("ONBEKEND") for row in rows)
    status = "FULL" if unknown == 0 else "PARTIAL"
    payload = {"status": status, "data_status": fundamental_data_status, "long_candidates": len(rows), "passed": passed,
               "excluded_sw": excluded, "unknown": unknown,
               "manual_scores_available": len(verified)}
    write_status(payload)
    print(f"SW Financial Health: {passed} PASS, {excluded} uitgesloten (<4/6), {unknown} ONBEKEND.")
    return 0 if status == "FULL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
