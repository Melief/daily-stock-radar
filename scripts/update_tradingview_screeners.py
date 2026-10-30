import csv
import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
URL_FILE = ROOT / "tv_screener_urls.txt"
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

def save_rows(label, rows):
    slug = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
    output = DATA_DIR / f"{slug}_tickers.csv"
    retrieved_at = datetime.now(ZoneInfo("Europe/Amsterdam")).isoformat(timespec="seconds")
    with output.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["ticker", "exchange", "symbol", "description", "retrieved_at"])
        for row in rows:
            symbol = row.get("s", "")
            ticker = symbol.split(":")[-1]
            exchange = symbol.split(":")[0] if ":" in symbol else ""
            values = row.get("d") or []
            description = ""
            if isinstance(values, dict):
                description = values.get("description") or values.get("short_name") or ""
                ticker = values.get("name") or ticker
                exchange = values.get("exchange") or exchange
            elif isinstance(values, list):
                description = next((str(v) for v in values if isinstance(v, str) and v.strip()
                                    and v.strip().upper() not in {ticker.upper(), exchange.upper(), symbol.upper()}
                                    and v.strip().upper() not in {"NASDAQ", "NYSE", "AMEX", "ARCA", "BATS", "USA", "US"}), "")
            writer.writerow([ticker, exchange, symbol, description, retrieved_at])
    print(f"{label}: {len(rows)} tickers -> {output.relative_to(ROOT)}")
    return output

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

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            for label, url in screeners:
                captured = []
                page = browser.new_page(viewport={"width": 1600, "height": 1000})
                def on_response(response):
                    if "/global/scan" not in response.url or response.status != 200:
                        return
                    try:
                        payload = response.json()
                        rows = payload.get("data", [])
                        if rows:
                            captured.append(rows)
                    except Exception:
                        pass
                page.on("response", on_response)
                print(f"Openen: {label} ({url})")
                response = page.goto(url, wait_until="domcontentloaded", timeout=90000)
                print(f"HTTP-status {label}: {response.status if response else 'geen response'}")
                page.wait_for_timeout(18000)
                page.close()
                if not captured:
                    raise RuntimeError(f"Geen scannerresultaten ontvangen voor '{label}'. CSV is niet overschreven.")
                # Gebruik de laatste scannerrespons; die bevat de actuele tabelresultaten.
                save_rows(label, captured[-1])
        finally:
            browser.close()

if __name__ == "__main__":
    main()
