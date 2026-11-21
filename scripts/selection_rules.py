"""Shared DSR candidate gates to keep every downstream control consistent."""
from __future__ import annotations


def _number(value):
    try:
        result = float(value)
        return result if result == result else None
    except (TypeError, ValueError):
        return None


def _explicit_false(value) -> bool:
    """Only a known False passes; blank/NaN/unknown values fail closed."""
    if value is None:
        return False
    return str(value).strip().lower() in {"false", "0"}


def is_qualified_short_candidate(row, min_score: int = 3) -> bool:
    """Require score, close below both SMAs, and SMA20 below SMA50."""
    score = _number(row.get("short_score"))
    sma20 = _number(row.get("sma20"))
    sma50 = _number(row.get("sma50"))
    return (
        str(row.get("score_status", "")).strip() == "OK"
        and score is not None
        and score >= min_score
        and _explicit_false(row.get("above_sma20_completed"))
        and _explicit_false(row.get("above_sma50_completed"))
        and sma20 is not None
        and sma50 is not None
        and sma20 < sma50
    )
