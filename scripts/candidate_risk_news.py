#!/usr/bin/env python3
"""Candidate-specific news and raw Short squeeze/gap-risk data for DSR."""
from __future__ import annotations

import concurrent.futures
import email.utils
import json
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
TECHNICAL = ROOT / "data" / "technical_scores.csv"
LONG_SW = ROOT / "data" / "long_sw_status.csv"
BORROW = ROOT / "data" / "short_borrow.csv"
OUTPUT = ROOT / "data" / "candidate_risk_news.csv"
STATUS_OUTPUT = ROOT / "data" / "candidate_risk_news_status.json"
NEWS_DAYS = 7
NEWS_LIMIT = 5
HTTP_TIMEOUT = 12
EVENT_KEYWORDS = (
    "earnings", "guidance", "fda", "clinical", "trial", "offering",
    "lawsuit", "investigation", "merger", "acquisition", "downgrade",
    "bankruptcy", "recall", "contract", "data breach", "resignation",
    "short squeeze", "activist", "regulatory",
)


def number(value):
    try:
        result = float(value)
        return result if pd.notna(result) else None
    except (TypeError, ValueError):
        return None


def event_flags(text: str) -> list[str]:
    lowered = str(text).lower()
    return [keyword for keyword in EVENT_KEYWORDS if keyword in lowered]


def parse_google_news_rss(xml_text: str, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    cutoff = now - timedelta(days=NEWS_DAYS)
    root = ET.fromstring(xml_text)
    items = []
    for item in root.findall("./channel/item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub_raw = (item.findtext("pubDate") or "").strip()
        source_node = item.find("source")
        source = (source_node.text or "").strip() if source_node is not None else ""
        if not title or not link or not pub_raw:
            continue
        try:
            published = email.utils.parsedate_to_datetime(pub_raw)
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
            published = published.astimezone(timezone.utc)
        except (TypeError, ValueError, OverflowError):
            continue
        if published < cutoff or published > now + timedelta(hours=1):
            continue
        flags = event_flags(title)
        items.append({
            "title": title,
            "source": source,
            "published_at": published.isoformat(),
            "url": link,
            "event_flags": flags,
        })
    items.sort(key=lambda item: item["published_at"], reverse=True)
    return items[:NEWS_LIMIT]


def fetch_google_news(query: str) -> list[dict]:
    params = urllib.parse.urlencode({
        "q": f'"{query}" stock when:{NEWS_DAYS}d',
        "hl": "en-US",
        "gl": "US",
        "ceid": "US:en",
    })
    url = "https://news.google.com/rss/search?" + params
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 DSR news monitor/1.0"},
    )
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
        xml_text = response.read().decode("utf-8", errors="replace")
    return parse_google_news_rss(xml_text)


def calculate_price_risk(frame: pd.DataFrame, expected_date: str) -> dict:
    if frame is None or frame.empty:
        raise ValueError("geen OHLC-data ontvangen")
    data = frame.copy()
    if isinstance(data.columns, pd.MultiIndex):
        level = next((i for i in range(data.columns.nlevels)
                      if "Close" in data.columns.get_level_values(i)), None)
        if level is None:
            raise ValueError("Close-kolom ontbreekt")
        data.columns = data.columns.get_level_values(level)
    required = ["Open", "High", "Low", "Close"]
    if any(column not in data.columns for column in required):
        raise ValueError("Open/High/Low/Close ontbreken")
    idx = pd.DatetimeIndex(data.index)
    if idx.tz is not None:
        idx = idx.tz_convert("America/New_York").tz_localize(None)
    data.index = idx.normalize()
    data = data[~data.index.duplicated(keep="last")].sort_index()
    for column in required:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data = data.dropna(subset=required)
    if len(data) < 22:
        raise ValueError(f"onvoldoende historie voor ATR/gap: {len(data)} sessies")
    actual_date = data.index[-1].strftime("%Y-%m-%d")
    if actual_date != expected_date:
        raise ValueError(f"koersdata loopt achter: verwacht {expected_date}, ontvangen {actual_date}")

    close = data["Close"]
    previous_close = close.shift(1)
    true_range = pd.concat([
        data["High"] - data["Low"],
        (data["High"] - previous_close).abs(),
        (data["Low"] - previous_close).abs(),
    ], axis=1).max(axis=1)
    atr14 = float(true_range.rolling(14).mean().iloc[-1])
    atr14_pct = atr14 / float(close.iloc[-1]) * 100.0
    gap_pct = ((data["Open"] - previous_close).abs() / previous_close) * 100.0
    max_gap_20d = float(gap_pct.tail(20).max())
    momentum_5d = (float(close.iloc[-1]) / float(close.iloc[-6]) - 1.0) * 100.0
    return {
        "price_date": actual_date,
        "close": round(float(close.iloc[-1]), 4),
        "momentum_5d_pct": round(momentum_5d, 2),
        "atr14_pct": round(atr14_pct, 2),
        "max_overnight_gap_20d_pct": round(max_gap_20d, 2),
    }


def _earnings_date(info: dict) -> str:
    timestamp = number(info.get("earningsTimestamp"))
    if timestamp is not None and timestamp > 0:
        return datetime.fromtimestamp(timestamp, timezone.utc).date().isoformat()
    dates = info.get("earningsDate")
    if isinstance(dates, (list, tuple)) and dates:
        value = dates[0]
        try:
            return pd.Timestamp(value).date().isoformat()
        except Exception:
            return ""
    return ""


def derive_risk_status(news_status: str, flags: list[str], short_metrics_ok: bool = True,
                       price_ok: bool = True) -> str:
    if flags:
        return "REVIEW"
    if news_status == "UNKNOWN" or not short_metrics_ok or not price_ok:
        return "UNKNOWN"
    if news_status == "NO_RESULTS":
        return "NO_RESULTS"
    return "CHECKED"


def _fetch_candidate(candidate: dict) -> dict:
    ticker = candidate["ticker"]
    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    info, info_error = {}, ""
    try:
        info = yf.Ticker(ticker).info or {}
    except Exception as exc:
        info_error = str(exc)

    company = str(info.get("longName") or info.get("shortName") or ticker).strip()
    query = company if company and company != ticker else ticker
    try:
        news = fetch_google_news(query)
        news_status = "CHECKED" if news else "NO_RESULTS"
        news_error = ""
    except Exception as exc:
        news = []
        news_status = "UNKNOWN"
        news_error = str(exc)

    price = {}
    price_error = ""
    if candidate["candidate_type"] == "SHORT":
        try:
            frame = yf.download(
                ticker, period="3mo", interval="1d", auto_adjust=False,
                progress=False, threads=False, timeout=25,
            )
            price = calculate_price_risk(frame, candidate["score_date"])
        except Exception as exc:
            price_error = str(exc)

    short_float_raw = number(info.get("shortPercentOfFloat"))
    short_float_pct = (
        short_float_raw * 100.0 if short_float_raw is not None and abs(short_float_raw) <= 1
        else short_float_raw
    )
    short_ratio = number(info.get("shortRatio"))
    shares_short = number(info.get("sharesShort"))
    shares_short_prior = number(info.get("sharesShortPriorMonth"))
    all_flags = sorted({flag for item in news for flag in item["event_flags"]})
    short_metrics_ok = (
        candidate["candidate_type"] != "SHORT"
        or (short_float_pct is not None and short_ratio is not None)
    )
    price_ok = candidate["candidate_type"] != "SHORT" or bool(price)
    risk_status = derive_risk_status(news_status, all_flags, short_metrics_ok, price_ok)
    errors = [value for value in (info_error, news_error, price_error) if value]
    return {
        "candidate_type": candidate["candidate_type"],
        "ticker": ticker,
        "sector": candidate.get("sector", ""),
        "industry": candidate.get("industry", ""),
        "technical_score": candidate.get("technical_score", ""),
        "borrow_status": candidate.get("borrow_status", ""),
        "available_shares": candidate.get("available_shares", ""),
        "borrow_fee_rate_pct": candidate.get("borrow_fee_rate_pct", ""),
        "short_percent_of_float": round(short_float_pct, 2) if short_float_pct is not None else "",
        "days_to_cover": short_ratio if short_ratio is not None else "",
        "shares_short": shares_short if shares_short is not None else "",
        "shares_short_prior_month": shares_short_prior if shares_short_prior is not None else "",
        "earnings_date": _earnings_date(info),
        "close": price.get("close", ""),
        "momentum_5d_pct": price.get("momentum_5d_pct", ""),
        "atr14_pct": price.get("atr14_pct", ""),
        "max_overnight_gap_20d_pct": price.get("max_overnight_gap_20d_pct", ""),
        "news_status": news_status,
        "news_count": len(news),
        "event_flags": ";".join(all_flags),
        "news_items": json.dumps(news, ensure_ascii=False),
        "risk_status": risk_status,
        "checked_at": checked_at,
        "error": " | ".join(errors),
        "_info_ok": not bool(info_error),
        "_price_ok": not bool(price_error) if candidate["candidate_type"] == "SHORT" else True,
        "_short_metrics_ok": short_metrics_ok,
    }


def load_candidates() -> list[dict]:
    if not TECHNICAL.exists() or not LONG_SW.exists() or not BORROW.exists():
        raise FileNotFoundError("technical_scores.csv, long_sw_status.csv of short_borrow.csv ontbreekt")
    technical = pd.read_csv(TECHNICAL, dtype={"ticker": str})
    long_sw = pd.read_csv(LONG_SW, dtype={"ticker": str})
    borrow = pd.read_csv(BORROW, dtype={"ticker": str})
    candidates = []

    for _, row in long_sw.iterrows():
        if str(row.get("sw_status", "")) != "PASS" or str(row.get("fundamental_status", "")) != "PASS":
            continue
        candidates.append({
            "candidate_type": "LONG", "ticker": str(row["ticker"]).upper(),
            "sector": row.get("sector", ""), "industry": row.get("industry", ""),
            "technical_score": row.get("technical_score", ""),
            "score_date": str(row.get("score_date", "")),
        })

    borrow_map = {str(row["ticker"]).upper(): row for _, row in borrow.iterrows()}
    for _, row in technical.iterrows():
        ticker = str(row.get("ticker", "")).upper()
        short_score = number(row.get("short_score"))
        sma20, sma50 = number(row.get("sma20")), number(row.get("sma50"))
        if str(row.get("score_status", "")) != "OK" or short_score is None or short_score < 4:
            continue
        if sma20 is None or sma50 is None or sma20 >= sma50:
            continue
        loan = borrow_map.get(ticker)
        if loan is None or str(loan.get("status", "")) != "AVAILABLE":
            continue
        candidates.append({
            "candidate_type": "SHORT", "ticker": ticker,
            "sector": row.get("sector", ""), "industry": row.get("industry", ""),
            "technical_score": int(short_score), "score_date": str(row.get("score_date", "")),
            "borrow_status": loan.get("status", ""),
            "available_shares": loan.get("available_shares", ""),
            "borrow_fee_rate_pct": loan.get("fee_rate_pct", ""),
        })
    return candidates


def write_status(payload: dict):
    temporary = STATUS_OUTPUT.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(STATUS_OUTPUT)


def main() -> int:
    try:
        candidates = load_candidates()
    except Exception as exc:
        write_status({"status": "PARTIAL", "errors": [str(exc)], "candidate_count": 0})
        print(f"Candidate risk/news selectie niet beschikbaar: {exc}", file=sys.stderr)
        return 1

    if not candidates:
        pd.DataFrame().to_csv(OUTPUT, index=False)
        write_status({"status": "FULL", "candidate_count": 0, "checked": 0,
                      "unknown": 0, "detail": "Geen volledig gekwalificeerde Long- of Short-kandidaten."})
        print("Geen volledig gekwalificeerde Long/Short kandidaten voor nieuwscontrole.")
        return 0

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(_fetch_candidate, candidate) for candidate in candidates]
        for future in concurrent.futures.as_completed(futures):
            try:
                results.append(future.result())
            except Exception as exc:
                print(f"Candidate risk/news worker error: {exc}", file=sys.stderr)

    results.sort(key=lambda row: (row["candidate_type"], row["ticker"]))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    public_rows = [{key: value for key, value in row.items() if not key.startswith("_")} for row in results]
    pd.DataFrame(public_rows).to_csv(OUTPUT, index=False)

    unknown = sum(
        row["risk_status"] == "UNKNOWN"
        or (row["candidate_type"] == "SHORT" and
            (not row["_info_ok"] or not row["_price_ok"] or not row["_short_metrics_ok"]))
        for row in results
    )
    review = sum(row["risk_status"] == "REVIEW" for row in results)
    payload = {
        "status": "FULL" if unknown == 0 and len(results) == len(candidates) else "PARTIAL",
        "candidate_count": len(candidates),
        "checked": len(results) - unknown,
        "unknown": unknown,
        "review_required": review,
        "long_candidates": sum(row["candidate_type"] == "LONG" for row in results),
        "short_candidates": sum(row["candidate_type"] == "SHORT" for row in results),
        "errors": [f"{row['ticker']}: {row['error']}" for row in results if row["error"]],
        "limitations": [
            "NO_RESULTS betekent geen geïndexeerde Google News RSS-resultaten binnen 7 dagen; het bewijst niet dat er geen nieuws of gebeurtenisrisico bestaat.",
            "Short interest, days-to-cover, ATR en gaps zijn bronafhankelijke ruwe gegevens; er worden geen niet-afgesproken risicodrempels toegepast.",
        ],
    }
    write_status(payload)
    print(f"News/risk: {payload['checked']} gecontroleerd, {unknown} ONBEKEND, {review} REVIEW.")
    return 0 if payload["status"] == "FULL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
