#!/usr/bin/env python3
"""Candidate-specific news and raw Short squeeze/gap-risk data for DSR."""
from __future__ import annotations

import concurrent.futures
import email.utils
import json
import re
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


def parse_google_news_rss(xml_text: str, now: datetime | None = None,
                         relevance_terms: list[str] | None = None) -> list[dict]:
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
        if relevance_terms:
            title_lower = title.lower()
            if not any(re.search(r"\b" + re.escape(term.lower()) + r"\b", title_lower)
                       for term in relevance_terms if term):
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


def fetch_google_news(query: str, relevance_terms: list[str] | None = None) -> list[dict]:
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
    if not relevance_terms:
        raise ValueError("geen betrouwbare bedrijfsnaam/ticker voor nieuwsrelevantie")
    return parse_google_news_rss(xml_text, relevance_terms=relevance_terms)


def _normalise_price_history(frame: pd.DataFrame) -> pd.DataFrame:
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
    return data.dropna(subset=required)


def calculate_price_risk(frame: pd.DataFrame, expected_date: str) -> dict:
    data = _normalise_price_history(frame)
    data = data.loc[data.index.strftime("%Y-%m-%d") <= expected_date]
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


def calculate_history_extremes(frame: pd.DataFrame, expected_date: str) -> dict:
    data = _normalise_price_history(frame)
    data = data.loc[data.index.strftime("%Y-%m-%d") <= expected_date]
    if data.empty:
        raise ValueError("geen afgeronde sessies tot de verwachte datum")
    actual_date = data.index[-1].strftime("%Y-%m-%d")
    if actual_date != expected_date:
        raise ValueError(f"koersdata loopt achter: verwacht {expected_date}, ontvangen {actual_date}")
    close = float(data["Close"].iloc[-1])
    # Reference levels exclude the latest completed session so a breakout can
    # legitimately print above 100% of the prior 52-week high / prior ATH.
    prior = data.iloc[:-1]
    if prior.empty:
        raise ValueError("geen voorafgaande sessies voor high-referenties")
    ath_position = int(prior["High"].to_numpy().argmax())
    ath = float(prior["High"].iloc[ath_position])
    recent_swings = data.tail(126)
    highs = recent_swings["High"].tolist()
    lows = recent_swings["Low"].tolist()
    swing_highs = []
    swing_lows = []
    for i in range(2, len(recent_swings) - 2):
        if highs[i] > max(highs[i - 2:i]) and highs[i] >= max(highs[i + 1:i + 3]):
            swing_highs.append((float(highs[i]), recent_swings.index[i].strftime("%Y-%m-%d")))
        if lows[i] < min(lows[i - 2:i]) and lows[i] <= min(lows[i + 1:i + 3]):
            swing_lows.append((float(lows[i]), recent_swings.index[i].strftime("%Y-%m-%d")))
    support_levels = [level for level in swing_lows if level[0] < close]
    resistance_levels = [level for level in swing_highs if level[0] > close]
    nearest_support = max(support_levels, key=lambda item: item[0]) if support_levels else None
    nearest_resistance = min(resistance_levels, key=lambda item: item[0]) if resistance_levels else None

    result = {
        "history_date": actual_date,
        "history_sessions": int(len(data)),
        "nearest_support": round(nearest_support[0], 4) if nearest_support else "",
        "nearest_support_date": nearest_support[1] if nearest_support else "",
        "nearest_resistance": round(nearest_resistance[0], 4) if nearest_resistance else "",
        "nearest_resistance_date": nearest_resistance[1] if nearest_resistance else "",
        "high_52w": "",
        "high_52w_date": "",
        "low_52w": "",
        "distance_to_52w_high_pct": "",
        "all_time_high": round(ath, 4),
        "all_time_high_date": prior.index[ath_position].strftime("%Y-%m-%d"),
        "distance_to_ath_pct": round((ath - close) / ath * 100.0, 2) if ath > 0 else "",
        "history_extremes_status": "PARTIAL",
    }
    if len(data) >= 253:
        recent = prior.tail(252)
        high_position = int(recent["High"].to_numpy().argmax())
        high_52w = float(recent["High"].iloc[high_position])
        low_52w = float(recent["Low"].min())
        result.update({
            "high_52w": round(high_52w, 4),
            "high_52w_date": recent.index[high_position].strftime("%Y-%m-%d"),
            "low_52w": round(low_52w, 4),
            "distance_to_52w_high_pct": round((high_52w - close) / high_52w * 100.0, 2) if high_52w > 0 else "",
            "history_extremes_status": "FULL",
        })
    return result

 
def calculate_consolidation_pivot(frame: pd.DataFrame, expected_date: str,
                                  candidate_type: str) -> dict:
    """Find the latest confirmed swing-origin consolidation in the prior 5–21 sessions.

    The latest completed session is excluded from the range so it can confirm
    a breakout/breakdown. A swing origin needs two completed bars on each side.
    """
    side = candidate_type.upper()
    if side not in {"LONG", "SHORT"}:
        raise ValueError("candidate_type moet LONG of SHORT zijn")
    data = _normalise_price_history(frame)
    data = data.loc[data.index.strftime("%Y-%m-%d") <= expected_date]
    if data.empty or data.index[-1].strftime("%Y-%m-%d") != expected_date:
        raise ValueError("consolidatiepivot gebruikt geen actuele voltooide koerssessie")
    prior = data.iloc[:-1].tail(21)
    unknown = {
        "consolidation_pivot": "",
        "consolidation_pivot_date": "",
        "consolidation_sessions": "",
        "consolidation_pivot_status": "ONBEKEND",
    }
    if len(prior) < 5:
        return unknown

    highs = prior["High"].tolist()
    lows = prior["Low"].tolist()
    eligible = []
    for i in range(2, len(prior) - 2):
        is_origin = (
            lows[i] < min(lows[i - 2:i]) and lows[i] <= min(lows[i + 1:i + 3])
            if side == "LONG" else
            highs[i] > max(highs[i - 2:i]) and highs[i] >= max(highs[i + 1:i + 3])
        )
        sessions = len(prior) - i
        if is_origin and 5 <= sessions <= 21:
            eligible.append((i, sessions))
    if not eligible:
        return unknown

    index, sessions = max(eligible, key=lambda item: item[0])
    segment = prior.iloc[index:]
    level = float(segment["High"].max() if side == "LONG" else segment["Low"].min())
    level_date = (
        segment["High"].idxmax() if side == "LONG" else segment["Low"].idxmin()
    ).strftime("%Y-%m-%d")
    return {
        "consolidation_pivot": round(level, 4),
        "consolidation_pivot_date": level_date,
        "consolidation_sessions": int(sessions),
        "consolidation_pivot_status": "OK",
    }


def _earnings_date(info: dict, today: datetime | None = None) -> str:
    today = (today or datetime.now(timezone.utc)).date()
    candidates = []
    timestamp = number(info.get("earningsTimestamp"))
    if timestamp is not None and timestamp > 0:
        candidates.append(datetime.fromtimestamp(timestamp, timezone.utc).date())
    dates = info.get("earningsDate")
    values = list(dates) if isinstance(dates, (list, tuple)) else ([dates] if dates is not None else [])
    for value in values:
        try:
            candidates.append(pd.Timestamp(value).date())
        except Exception:
            continue
    future = sorted(value for value in candidates if value >= today)
    return future[0].isoformat() if future else ""


def derive_risk_status(news_status: str, flags: list[str], short_metrics_ok: bool = True,
                       price_ok: bool = True, earnings_date_known: bool = True) -> str:
    if flags:
        return "REVIEW"
    if news_status == "UNKNOWN" or not short_metrics_ok or not price_ok or not earnings_date_known:
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
        if not info:
            info_error = "Yahoo Finance info is empty or unavailable"
    except Exception as exc:
        info_error = str(exc)

    company = str(info.get("longName") or info.get("shortName") or ticker).strip()
    query = company if company and company != ticker else ticker
    relevance_terms = []
    if len(ticker) >= 3:
        relevance_terms.append(ticker)
    if company and company != ticker:
        common_name_words = {
            "the", "a", "an", "inc", "corp", "corporation", "company",
            "holdings", "group", "plc", "limited", "ltd", "co",
        }
        name_words = re.findall(r"[A-Za-z0-9]+", company)
        distinctive = next(
            (word for word in name_words
             if len(word) >= 3 and word.lower() not in common_name_words),
            "",
        )
        if distinctive:
            relevance_terms.append(distinctive)
    try:
        news = fetch_google_news(query, relevance_terms)
        news_status = "CHECKED" if news else "NO_RESULTS"
        news_error = ""
    except Exception as exc:
        news = []
        news_status = "UNKNOWN"
        news_error = str(exc)

    price = {}
    price_error = ""
    history_extremes = {}
    history_error = ""
    try:
        frame = yf.download(
            ticker, period="max", interval="1d", auto_adjust=False,
            progress=False, threads=False, timeout=25,
        )
        history_extremes = calculate_history_extremes(frame, candidate["score_date"])
        history_extremes.update(calculate_consolidation_pivot(
            frame, candidate["score_date"], candidate["candidate_type"]
        ))
        if candidate["candidate_type"] == "SHORT":
            price = calculate_price_risk(frame, candidate["score_date"])
    except Exception as exc:
        history_error = str(exc)
        if candidate["candidate_type"] == "SHORT":
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
    earnings_date = _earnings_date(info)
    earnings_date_known = candidate["candidate_type"] != "SHORT" or bool(earnings_date)
    risk_status = derive_risk_status(news_status, all_flags, short_metrics_ok, price_ok, earnings_date_known)
    errors = [value for value in (info_error, news_error, price_error, history_error) if value]
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
        "earnings_date": earnings_date,
        **history_extremes,
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
        "_earnings_date_known": earnings_date_known,
        "_history_ok": history_extremes.get("history_extremes_status") == "FULL",
        "_pivot_ok": history_extremes.get("consolidation_pivot_status") == "OK",
    }


def load_candidates() -> list[dict]:
    if not TECHNICAL.exists() or not LONG_SW.exists() or not BORROW.exists():
        raise FileNotFoundError("technical_scores.csv, long_sw_status.csv of short_borrow.csv ontbreekt")
    technical = pd.read_csv(TECHNICAL, dtype={"ticker": str})
    long_sw = pd.read_csv(LONG_SW, dtype={"ticker": str})
    borrow = pd.read_csv(BORROW, dtype={"ticker": str})
    candidates = []
    technical_map = {
        str(row["ticker"]).upper(): row for _, row in technical.iterrows()
    }

    for _, row in long_sw.iterrows():
        if str(row.get("sw_status", "")) != "PASS" or str(row.get("fundamental_status", "")) != "PASS":
            continue
        ticker = str(row["ticker"]).upper()
        technical_row = technical_map.get(ticker, {})
        score_date = str(technical_row.get("score_date", "")).strip()
        if score_date.lower() in {"", "nan", "none"}:
            score_date = ""
        candidates.append({
            "candidate_type": "LONG", "ticker": ticker,
            "sector": row.get("sector", ""), "industry": row.get("industry", ""),
            "technical_score": row.get("technical_score", ""),
            "score_date": score_date,
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
        or not row["_history_ok"]
        or not row["_pivot_ok"]
        or (row["candidate_type"] == "SHORT" and
            (not row["_info_ok"] or not row["_price_ok"] or not row["_short_metrics_ok"] or not row["_earnings_date_known"]))
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
            "Een kandidaat zonder bevestigde consolidatiepivot volgens de 5–21-sessieregel blijft ONBEKEND en maakt de risicocontrole PARTIAL.",
        ],
    }
    write_status(payload)
    print(f"News/risk: {payload['checked']} gecontroleerd, {unknown} ONBEKEND, {review} REVIEW.")
    return 0 if payload["status"] == "FULL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
