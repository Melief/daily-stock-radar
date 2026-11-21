#!/usr/bin/env python3
"""Fetch IBKR's public US stock-loan file for technically qualified DSR shorts."""
from __future__ import annotations

import csv
import io
import json
import sys
from datetime import datetime, timedelta
from ftplib import FTP
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCORES = ROOT / "data" / "technical_scores.csv"
OUTPUT = ROOT / "data" / "short_borrow.csv"
STATUS_OUTPUT = ROOT / "data" / "short_borrow_status.json"
FTP_HOST = "ftp2.interactivebrokers.com"
FTP_USER = "shortstock"
FTP_FILE = "usa.txt"
MAX_AGE = timedelta(hours=24)


def parse_ftp_payload(payload: str) -> tuple[datetime, dict[str, dict]]:
    """Parse IBKR #BOF/#SYM pipe-delimited data; duplicate symbols stay ambiguous."""
    rows = list(csv.reader(io.StringIO(payload), delimiter="|"))
    bof = next((row for row in rows if row and row[0] == "#BOF"), None)
    header = next((row for row in rows if row and row[0] == "#SYM"), None)
    if not bof or len(bof) < 3 or not header:
        raise ValueError("IBKR-bestand mist een geldige #BOF- of #SYM-header")
    timestamp = datetime.strptime(f"{bof[1]} {bof[2]}", "%Y.%m.%d %H:%M:%S").replace(
        tzinfo=ZoneInfo("America/New_York")
    )
    columns = [value.lstrip("#").strip().upper() for value in header]
    required = {"SYM", "CUR", "REBATERATE", "FEERATE", "AVAILABLE"}
    if not required.issubset(columns):
        raise ValueError(f"IBKR-bestand mist verplichte velden: {sorted(required - set(columns))}")
    index = {name: columns.index(name) for name in required}
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        if not row or row[0].startswith("#") or len(row) < len(columns):
            continue
        ticker = row[index["SYM"]].strip().upper()
        currency = row[index["CUR"]].strip().upper()
        if not ticker or currency != "USD":
            continue
        try:
            available = int(float(row[index["AVAILABLE"]]))
            fee = float(row[index["FEERATE"]])
            rebate = float(row[index["REBATERATE"]])
        except (ValueError, IndexError):
            continue
        grouped.setdefault(ticker, []).append({
            "available_shares": available,
            "fee_rate_pct": fee,
            "rebate_rate_pct": rebate,
            "currency": currency,
        })
    parsed = {}
    for ticker, matches in grouped.items():
        if len(matches) == 1:
            parsed[ticker] = matches[0]
        else:
            parsed[ticker] = {"ambiguous": True, "match_count": len(matches)}
    return timestamp, parsed


def fetch_ftp_payload() -> str:
    buffer = io.BytesIO()
    ftp = FTP(FTP_HOST, timeout=35)
    try:
        ftp.login(user=FTP_USER, passwd="")
        ftp.retrbinary(f"RETR {FTP_FILE}", buffer.write)
    finally:
        try:
            ftp.quit()
        except Exception:
            ftp.close()
    return buffer.getvalue().decode("utf-8-sig", errors="replace")


def qualified_short_candidates(path: Path = SCORES) -> list[str]:
    if not path.exists():
        raise FileNotFoundError("technical_scores.csv ontbreekt")
    data = pd.read_csv(path, dtype={"ticker": str})
    required = {"ticker", "score_status", "short_score", "sma20", "sma50"}
    if not required.issubset(data.columns):
        raise ValueError(f"technical_scores.csv mist kolommen: {sorted(required - set(data.columns))}")
    data["short_score"] = pd.to_numeric(data["short_score"], errors="coerce")
    data["sma20"] = pd.to_numeric(data["sma20"], errors="coerce")
    data["sma50"] = pd.to_numeric(data["sma50"], errors="coerce")
    eligible = data[
        (data["score_status"] == "OK")
        & (data["short_score"] >= 3)
        & (data["sma20"] < data["sma50"])
    ]
    return sorted(set(eligible["ticker"].dropna().str.strip().str.upper()))


def write_status(payload: dict):
    temporary = STATUS_OUTPUT.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(STATUS_OUTPUT)


def main() -> int:
    try:
        candidates = qualified_short_candidates()
    except Exception as exc:
        print(f"Short-borrowselectie niet beschikbaar: {exc}", file=sys.stderr)
        write_status({"status": "PARTIAL", "errors": [str(exc)], "candidate_count": 0})
        return 1

    columns = ["ticker", "available_shares", "fee_rate_pct", "rebate_rate_pct",
               "feed_timestamp", "status", "detail"]
    if not candidates:
        pd.DataFrame(columns=columns).to_csv(OUTPUT, index=False)
        write_status({"status": "FULL", "candidate_count": 0, "checked": 0, "unknown": 0,
                      "feed_timestamp": None, "detail": "Geen technisch gekwalificeerde Short-kandidaten."})
        print("IBKR-borrowcontrole overgeslagen: geen technisch gekwalificeerde Short-kandidaten.")
        return 0

    try:
        timestamp, inventory = parse_ftp_payload(fetch_ftp_payload())
        now = datetime.now(ZoneInfo("America/New_York"))
        age = now - timestamp
        if age < timedelta(0) or age > MAX_AGE:
            raise ValueError(f"IBKR-feed is niet actueel: timestamp={timestamp.isoformat()}, leeftijd={age}")
    except Exception as exc:
        rows = [{"ticker": ticker, "available_shares": "", "fee_rate_pct": "",
                 "rebate_rate_pct": "", "feed_timestamp": "", "status": "ONBEKEND",
                 "detail": str(exc)} for ticker in candidates]
        pd.DataFrame(rows, columns=columns).to_csv(OUTPUT, index=False)
        write_status({"status": "PARTIAL", "candidate_count": len(candidates), "checked": 0,
                      "unknown": len(candidates), "feed_timestamp": None, "errors": [str(exc)]})
        print(f"IBKR-borrowdata ONBEKEND: {exc}", file=sys.stderr)
        return 1

    rows = []
    for ticker in candidates:
        item = inventory.get(ticker)
        if item is None:
            rows.append({"ticker": ticker, "available_shares": "", "fee_rate_pct": "",
                         "rebate_rate_pct": "", "feed_timestamp": timestamp.isoformat(),
                         "status": "ONBEKEND", "detail": "Ticker ontbreekt in IBKR-bestand."})
        elif item.get("ambiguous"):
            rows.append({"ticker": ticker, "available_shares": "", "fee_rate_pct": "",
                         "rebate_rate_pct": "", "feed_timestamp": timestamp.isoformat(),
                         "status": "ONBEKEND", "detail": f"Meerdere USD-contractregels ({item['match_count']}); niet samengevoegd."})
        else:
            available = item["available_shares"]
            rows.append({"ticker": ticker, "available_shares": available,
                         "fee_rate_pct": item["fee_rate_pct"], "rebate_rate_pct": item["rebate_rate_pct"],
                         "feed_timestamp": timestamp.isoformat(),
                         "status": "AVAILABLE" if available > 0 else "NOT_AVAILABLE",
                         "detail": "Indicatieve IBKR-inventaris; geen garantie op persoonlijke locate."})
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=columns).to_csv(OUTPUT, index=False)
    unknown = sum(row["status"] == "ONBEKEND" for row in rows)
    payload = {"status": "FULL" if unknown == 0 else "PARTIAL",
               "candidate_count": len(candidates), "checked": len(rows) - unknown,
               "unknown": unknown, "feed_timestamp": timestamp.isoformat(), "errors": []}
    write_status(payload)
    print(f"IBKR-borrowcontrole: {payload['checked']} gecontroleerd, {unknown} ONBEKEND; feed={timestamp.isoformat()}")
    return 0 if unknown == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
