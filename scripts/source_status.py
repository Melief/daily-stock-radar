#!/usr/bin/env python3
"""Record and evaluate per-source refresh status for the Daily Stock Radar."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATUS_DIR = ROOT / "data" / "source_status"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Source status timestamps must include a timezone.")
    return parsed.astimezone(timezone.utc)


def status_path(source_id: str, status_dir: Path = STATUS_DIR) -> Path:
    if not source_id or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for ch in source_id):
        raise ValueError(f"Invalid source id: {source_id!r}")
    return Path(status_dir) / f"{source_id}.json"


def record_status(
    source_id: str,
    outcome: str,
    detail: str = "",
    status_dir: Path = STATUS_DIR,
    now: datetime | None = None,
) -> dict:
    if outcome not in {"success", "failure"}:
        raise ValueError("outcome must be 'success' or 'failure'")
    now = (now or utc_now()).astimezone(timezone.utc)
    path = status_path(source_id, status_dir)
    previous = {}
    if path.exists():
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous = {}
    last_success = now.isoformat(timespec="seconds") if outcome == "success" else previous.get("last_success_at")
    payload = {
        "source_id": source_id,
        "last_attempt_status": outcome,
        "last_attempt_at": now.isoformat(timespec="seconds"),
        "last_success_at": last_success,
        "detail": str(detail)[:1000],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return payload


def evaluate_status(
    source_id: str,
    refresh_mode: str,
    max_age_hours: int,
    status_dir: Path = STATUS_DIR,
    now: datetime | None = None,
) -> dict:
    now = (now or utc_now()).astimezone(timezone.utc)
    if refresh_mode == "manual":
        return {
            "source_id": source_id, "status": "MANUAL", "include": True,
            "partial": False, "last_attempt_at": "", "last_success_at": "",
            "age_hours": "", "detail": "Handmatig beheerde bron; automatische actualiteit niet van toepassing.",
        }
    if refresh_mode != "automatic":
        raise ValueError(f"Invalid refresh_mode for {source_id}: {refresh_mode}")

    path = status_path(source_id, status_dir)
    if not path.exists():
        return {
            "source_id": source_id, "status": "UNKNOWN", "include": True,
            "partial": True, "last_attempt_at": "", "last_success_at": "",
            "age_hours": "", "detail": "Geen refreshstatus geregistreerd; bestaand bestand alleen als fallback gebruikt.",
        }

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("source_id") != source_id:
            raise ValueError("Source id mismatch in status file.")
        last_success = parse_timestamp(data.get("last_success_at"))
        last_attempt = parse_timestamp(data.get("last_attempt_at"))
        attempt_status = data.get("last_attempt_status")
        if attempt_status not in {"success", "failure"}:
            raise ValueError("Invalid last_attempt_status.")
        if last_success is None and attempt_status == "success":
            raise ValueError("Successful refresh has no last_success_at.")
        if last_success and last_success > now + timedelta(minutes=5):
            raise ValueError("last_success_at is in the future.")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "source_id": source_id, "status": "UNKNOWN", "include": True,
            "partial": True, "last_attempt_at": "", "last_success_at": "",
            "age_hours": "", "detail": f"Ongeldige bronstatus; bestaand bestand alleen als fallback gebruikt: {exc}",
        }

    age = (now - last_success).total_seconds() / 3600 if last_success else None
    age_text = round(age, 1) if age is not None else ""
    attempt_text = last_attempt.isoformat(timespec="seconds") if last_attempt else ""
    success_text = last_success.isoformat(timespec="seconds") if last_success else ""
    detail = str(data.get("detail", ""))

    if attempt_status == "success" and age is not None and age <= max_age_hours:
        state, include, partial = "CURRENT", True, False
    elif attempt_status == "failure" and age is not None and age <= max_age_hours:
        state, include, partial = "STALE_FALLBACK", True, True
        detail = (detail + " | " if detail else "") + "Laatste refresh mislukte; vorige succesvolle data gebruikt."
    elif age is None:
        state, include, partial = "FAILED", False, True
    else:
        state, include, partial = "STALE", False, True
        detail = (detail + " | " if detail else "") + f"Laatste succesvolle refresh ouder dan {max_age_hours} uur."

    return {
        "source_id": source_id, "status": state, "include": include,
        "partial": partial, "last_attempt_at": attempt_text,
        "last_success_at": success_text, "age_hours": age_text, "detail": detail,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_id")
    parser.add_argument("outcome", choices=("success", "failure"))
    parser.add_argument("--detail", default="")
    args = parser.parse_args()
    record_status(args.source_id, args.outcome, args.detail)
    print(f"Recorded {args.outcome} refresh status for {args.source_id}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
