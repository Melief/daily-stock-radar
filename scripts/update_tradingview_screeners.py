import csv
import json
import re
import sys
import urllib.parse
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.source_status import record_status

SOURCE_IDS = {
    "Simpel Monsters": "simpel_monsters",
    "Follow Thrue": "follow_thrue",
}
URL_FILE = ROOT / "tv_screener_urls.txt"
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)


def save_rows(label, rows):
    allow_empty = False
    if isinstance(rows, dict):
        allow_empty = rows.get("totalCount") == 0
        rows = rows.get("symbols") or rows.get("data") or []
    slug = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
    output = DATA_DIR / f"{slug}_tickers.csv"
    retrieved_at = datetime.now(ZoneInfo("Europe/Amsterdam")).isoformat(timespec="seconds")
    parsed = []

    def add_symbol(symbol, description="", exchange=""):
        symbol = str(symbol or "").strip()
        if not symbol:
            return
        if ":" in symbol:
            exchange, ticker = symbol.split(":", 1)
        else:
            ticker = symbol
        ticker = ticker.strip().upper()
        if not ticker or ticker in {"TICKER", "SYMBOL", "NONE", "NAN"}:
            return
        parsed.append([ticker, str(exchange or "").strip(), symbol, str(description or "").strip(), retrieved_at])

    for row in rows:
        if isinstance(row, str):
            add_symbol(row)
            continue
        if not isinstance(row, dict):
            continue
        symbol = row.get("s") or row.get("symbol") or row.get("ticker") or ""
        if symbol:
            add_symbol(symbol, row.get("description", ""), row.get("exchange", ""))
            continue
        raw_values = row.get("rawValues")
        if isinstance(raw_values, list):
            for value in raw_values:
                if isinstance(value, dict):
                    name = value.get("name") or value.get("symbol") or value.get("ticker")
                    exchange = value.get("exchange", "")
                    if name:
                        add_symbol(f"{exchange}:{name}" if exchange else name,
                                   value.get("description", ""), exchange)

    # Remove duplicates without changing the source's ordering.
    unique = []
    seen = set()
    for item in parsed:
        key = item[0]
        if key not in seen:
            seen.add(key)
            unique.append(item)
    if not unique and not allow_empty:
        raise RuntimeError(f"{label}: TradingView retourneerde {len(rows)} records maar geen herkenbare tickers; bestaand CSV-bestand blijft behouden.")
    with output.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["ticker", "exchange", "symbol", "description", "retrieved_at"])
        writer.writerows(unique)
    print(f"{label}: {len(unique)} gevalideerde tickers -> {output.relative_to(ROOT)}")
    return output


def retrieve_screener(browser, label, url):
    captured = []
    diagnostics = []
    page = None
    source_id = SOURCE_IDS.get(label)
    if not source_id:
        raise ValueError(f"Onbekende TradingView-bron: {label}")

    def on_response(response):
        path = urllib.parse.urlsplit(response.url).path
        if not re.search(r"(scan|screener)", path, re.IGNORECASE):
            return
        content_type = response.headers.get("content-type", "")
        detail = {"path": path, "status": response.status, "content_type": content_type}
        try:
            payload = response.json()
            if isinstance(payload, dict):
                detail["keys"] = sorted(payload.keys())[:20]
                rows = payload.get("data", [])
                symbols = payload.get("symbols", [])
                if isinstance(rows, list):
                    detail["row_count"] = len(rows)
                    detail["total_count"] = payload.get("totalCount")
                    detail["symbols_count"] = len(symbols) if isinstance(symbols, list) else None
                    detail["symbols_preview"] = json.dumps(symbols[:25], ensure_ascii=False, default=str)[:1800] if isinstance(symbols, list) else str(type(symbols).__name__)
                    if rows:
                        detail["first_row_type"] = type(rows[0]).__name__
                        if isinstance(rows[0], dict):
                            detail["first_row_keys"] = sorted(rows[0].keys())[:30]
                        detail["first_row_preview"] = json.dumps(rows[0], ensure_ascii=False, default=str)[:1400]
                        detail["raw_values_summary"] = [
                            {"id": item.get("id"), "count": len(item.get("rawValues", [])),
                             "names": [v.get("name") for v in item.get("rawValues", [])[:8] if isinstance(v, dict)]}
                            for item in rows[:5] if isinstance(item, dict)
                        ]
                    if isinstance(symbols, list) and symbols:
                        captured.append(symbols)
                    elif payload.get("totalCount") == 0:
                        captured.append(payload)
                    elif rows:
                        captured.append(rows)
                else:
                    detail["data_type"] = type(rows).__name__
            else:
                detail["json_type"] = type(payload).__name__
        except Exception as exc:
            detail["parse_error"] = str(exc)[:180]
        diagnostics.append(detail)
        print(f"TradingView network response {label}: {json.dumps(detail, ensure_ascii=False)}")

    def on_request_failed(request):
        path = urllib.parse.urlsplit(request.url).path
        if re.search(r"(scan|screener)", path, re.IGNORECASE):
            detail = {"path": path, "failure": request.failure}
            diagnostics.append(detail)
            print(f"TradingView network request failed {label}: {json.dumps(detail, ensure_ascii=False)}")

    try:
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        page.on("response", on_response)
        page.on("requestfailed", on_request_failed)
        print(f"Openen: {label} ({url})")
        response = page.goto(url, wait_until="domcontentloaded", timeout=90000)
        print(f"HTTP-status {label}: {response.status if response else 'geen response'}")
        page.wait_for_timeout(18000)
        try:
            visible_text = page.locator("body").inner_text(timeout=5000)
        except Exception as exc:
            visible_text = f"body niet leesbaar: {exc}"
        print(f"TradingView page summary {label}: title={page.title()!r}; "
              f"url={urllib.parse.urlsplit(page.url).path}; body={visible_text[:1400]!r}")
        if not captured:
            try:
                body_text = page.locator("body").inner_text(timeout=5000)
            except Exception as exc:
                body_text = f"body niet leesbaar: {exc}"
            print(f"TradingView diagnostic summary {label}: title={page.title()!r}; "
                  f"url={urllib.parse.urlsplit(page.url).path}; "
                  f"matching_responses={len(diagnostics)}; body={body_text[:1200]!r}")
            raise RuntimeError(f"Geen scannerresultaten ontvangen voor '{label}'. "
                               f"{len(diagnostics)} scan/screener netwerkreacties gelogd; CSV is niet overschreven.")
        output = save_rows(label, captured[-1])
        with output.open(encoding="utf-8-sig", newline="") as f:
            ticker_count = sum(1 for _ in csv.DictReader(f))
        record_status(source_id, "success", f"{ticker_count} gevalideerde TradingView-tickers opgehaald.")
    except Exception as exc:
        record_status(source_id, "failure", str(exc))
        raise
    finally:
        if page is not None:
            page.close()


def retrieve_all_screeners(browser, screeners):
    failures = []
    for label, url in screeners:
        try:
            retrieve_screener(browser, label, url)
        except Exception as exc:
            failures.append((label, str(exc)))
            print(f"FOUT [{label}]: {exc}", file=sys.stderr)

    if failures:
        details = "; ".join(f"{label}: {error}" for label, error in failures)
        raise RuntimeError(
            f"TradingView-refresh gedeeltelijk mislukt ({len(failures)}/{len(screeners)}): {details}"
        )


def main():
    screeners = []
    for line in URL_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        label, url = line.split("|", 1)
        screeners.append((label.strip(), url.strip()))
    if not screeners:
        raise RuntimeError("Geen TradingView-screeners gevonden in tv_screener_urls.txt")

    # Import only at runtime so the independent-retrieval logic can be unit-tested
    # without installing a browser.
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            retrieve_all_screeners(browser, screeners)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
