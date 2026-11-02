#!/usr/bin/env python3
"""Build a current EURO STOXX 50 constituent/ticker CSV.

Source constituents: official STOXX SX5E components page.
Ticker discovery: Yahoo Finance search endpoint, constrained by listing suffix
for the constituent's home market. Uncertain matches are left blank.
"""
from __future__ import annotations

import csv
import difflib
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

SOURCE_URL = "https://stoxx.com/index/sx5e/?components=true"
YAHOO_SEARCH_URL = "https://query1.finance.yahoo.com/v1/finance/search"
OUTPUT = Path("data/eurostoxx50_tickers.csv")
EXPECTED_COMPONENTS = 50

# Yahoo Finance listing suffix -> Google Finance exchange prefix.
MARKETS = {
    "Netherlands": (".AS", "AMS"),
    "Germany": (".DE", "ETR"),
    "Spain": (".MC", "BME"),
    "France": (".PA", "EPA"),
    "Italy": (".MI", "BIT"),
    "Belgium": (".BR", "EBR"),
    "Finland": (".HE", "HEL"),
    "Ireland": (".IR", "ISE"),
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36",
    "Accept": "text/html,application/json,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


def normalize(value: str) -> str:
    value = value.upper().replace("&", " AND ")
    value = re.sub(r"[^A-Z0-9 ]", " ", value)
    value = re.sub(r"\b( NV| SE| SA| AG| PLC| SPA| S A| N V| HOLDING| HOLDINGS)\b", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    # STOXX abbreviations used in constituent names.
    value = re.sub(r"^BCO\b", "BANCO", value)
    value = re.sub(r"\bGRP\b", "GROUP", value)
    value = re.sub(r"\bHLDG\b", "HOLDING", value)
    return value


def fetch_components(session: requests.Session) -> list[dict[str, str]]:
    response = session.get(SOURCE_URL, timeout=30)
    print(f"STOXX HTTP status: {response.status_code}")
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    for table in soup.find_all("table"):
        rows = []
        for tr in table.find_all("tr"):
            cells = [cell.get_text(" ", strip=True) for cell in tr.find_all(["th", "td"])]
            if cells:
                rows.append(cells)
        if not rows:
            continue

        header = [normalize(x) for x in rows[0]]
        required = ["COMPANY", "SUPERSECTOR", "COUNTRY"]
        if not all(any(h.startswith(item) for h in header) for item in required):
            continue

        def col(prefix: str) -> int:
            return next(i for i, h in enumerate(header) if h.startswith(prefix))

        ci, si, coi = col("COMPANY"), col("SUPERSECTOR"), col("COUNTRY")
        wi = next((i for i, h in enumerate(header) if "WEIGHT" in h), None)

        components = []
        for row in rows[1:]:
            if max(ci, si, coi) >= len(row):
                continue
            company, sector, country = row[ci].strip(), row[si].strip(), row[coi].strip()
            if not company or not country:
                continue
            weight = row[wi].strip() if wi is not None and wi < len(row) else ""
            components.append({
                "Company": company,
                "Supersector": sector,
                "Country": country,
                "Weight (%)": weight,
            })

        if components:
            return components

    raise RuntimeError("Could not find the official STOXX components table.")


def score_match(company: str, candidate_name: str) -> float:
    a, b = normalize(company), normalize(candidate_name)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0

    tokens = [t for t in a.split() if len(t) > 2]
    if not tokens:
        return difflib.SequenceMatcher(None, a, b).ratio()

    token_score = sum(token in b for token in tokens) / len(tokens)
    sequence_score = difflib.SequenceMatcher(None, a, b).ratio()
    return max(token_score, sequence_score * 0.85)


def find_ticker(session: requests.Session, company: str, country: str) -> tuple[str, str, str]:
    market = MARKETS.get(country)
    if not market:
        return "", "", "LAND NIET ONDERSTEUND"

    suffix, gf_prefix = market
    params = {"q": company, "quotesCount": 20, "newsCount": 0}
    last_error = ""

    for attempt in range(3):
        try:
            response = session.get(YAHOO_SEARCH_URL, params=params, timeout=20)
            if response.status_code == 429:
                time.sleep(3 * (attempt + 1))
                continue
            response.raise_for_status()
            payload: dict[str, Any] = response.json()
            quotes = [
                q for q in payload.get("quotes", [])
                if q.get("quoteType") == "EQUITY"
                and isinstance(q.get("symbol"), str)
                and q["symbol"].upper().endswith(suffix)
                and q.get("shortname") or q.get("longname")
            ]

            scored = []
            for quote in quotes:
                name = quote.get("longname") or quote.get("shortname") or ""
                scored.append((score_match(company, name), quote, name))
            scored.sort(key=lambda item: item[0], reverse=True)

            if not scored or scored[0][0] < 0.50:
                return "", "", "NIET GEVONDEN"

            # Avoid assigning a ticker if the two best candidates are too close.
            if len(scored) > 1 and scored[0][0] - scored[1][0] < 0.08:
                return "", "", "CONTROLE NODIG"

            yahoo_symbol = scored[0][1]["symbol"].upper()
            local_ticker = yahoo_symbol[: -len(suffix)]
            if not re.fullmatch(r"[A-Z0-9.-]+", local_ticker):
                return "", "", "CONTROLE NODIG"

            return yahoo_symbol, f"{gf_prefix}:{local_ticker}", "OK"

        except (requests.RequestException, ValueError) as exc:
            last_error = str(exc)
            time.sleep(2 * (attempt + 1))

    return "", "", f"API FOUT: {last_error[:80]}"


def main() -> None:
    session = requests.Session()
    session.headers.update(HEADERS)

    components = fetch_components(session)
    if len(components) != EXPECTED_COMPONENTS:
        raise RuntimeError(
            f"Expected {EXPECTED_COMPONENTS} STOXX constituents, found {len(components)}. "
            "Existing CSV will not be overwritten."
        )

    results = []
    for index, component in enumerate(components, start=1):
        yahoo_symbol, gf_ticker, status = find_ticker(
            session, component["Company"], component["Country"]
        )
        row = {
            **component,
            "Yahoo Symbol": yahoo_symbol,
            "GF Ticker": gf_ticker,
            "Status": status,
        }
        results.append(row)
        print(
            f"{index:02d}/{len(components)} {component['Company']}: "
            f"{gf_ticker or status}"
        )
        # Keep requests gentle; this is a weekly composition refresh, not live trading.
        time.sleep(0.35)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)

    matched = sum(row["Status"] == "OK" for row in results)
    print(f"Saved {len(results)} constituents to {OUTPUT}")
    print(f"Ticker matches: {matched}/{len(results)}")
    print(f"Needs review: {len(results) - matched}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
