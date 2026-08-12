"""Fetch live prices from Woolworths and Coles for the basket seed terms.

Both retailers are queried through the same JSON endpoints their own web
frontends use. Output is one normalized CSV per snapshot date:
data/raw/prices_YYYY-MM-DD.csv (re-running the same day overwrites it).
"""

from __future__ import annotations

import csv
import datetime as dt
import logging
import re
import time
from pathlib import Path

import requests

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SEED_PATH = PROJECT_ROOT / "seeds" / "basket.csv"
RAW_DIR = PROJECT_ROOT / "data" / "raw"

REQUEST_DELAY_S = 0.6
RETRIES = 3

RAW_COLUMNS = [
    "retailer",
    "product_id",
    "name",
    "brand",
    "size_raw",
    "price",
    "was_price",
    "unit_price",
    "unit_measure",
    "is_on_special",
    "result_rank",
    "search_term",
    "category",
    "snapshot_date",
    "fetched_at",
]


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
            ),
            "Accept": "application/json, text/html",
            "Accept-Language": "en-AU,en;q=0.9",
        }
    )
    return s


def get_with_retry(session: requests.Session, url: str, **kwargs) -> requests.Response | None:
    for attempt in range(1, RETRIES + 1):
        try:
            resp = session.get(url, timeout=20, **kwargs)
            if resp.status_code == 200:
                return resp
            log.warning("HTTP %s from %s (attempt %d)", resp.status_code, url, attempt)
        except requests.RequestException as exc:
            log.warning("Request error for %s (attempt %d): %s", url, attempt, exc)
        time.sleep(2**attempt)
    return None


def load_basket() -> list[dict]:
    with open(SEED_PATH, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# --- Woolworths -------------------------------------------------------------


def fetch_woolworths(session: requests.Session, term: str) -> list[dict]:
    url = "https://www.woolworths.com.au/apis/ui/Search/products"
    resp = get_with_retry(session, url, params={"searchTerm": term})
    if resp is None:
        return []
    rows = []
    for group in resp.json().get("Products") or []:
        for p in group.get("Products") or []:
            price = p.get("Price")
            if price is None:  # unavailable / online-only placeholder
                continue
            rows.append(
                {
                    "retailer": "woolworths",
                    "product_id": p.get("Stockcode"),
                    "name": p.get("DisplayName") or p.get("Name"),
                    "brand": p.get("Brand") or "",
                    "size_raw": p.get("PackageSize") or "",
                    "price": price,
                    "was_price": p.get("WasPrice"),
                    "unit_price": p.get("CupPrice"),
                    "unit_measure": p.get("CupMeasure") or "",
                    "is_on_special": bool(p.get("IsOnSpecial")),
                }
            )
    return rows


# --- Coles ------------------------------------------------------------------


def resolve_coles_build_id(session: requests.Session) -> str | None:
    resp = get_with_retry(session, "https://www.coles.com.au/")
    if resp is None:
        return None
    m = re.search(r'"buildId":"([^"]+)"', resp.text)
    return m.group(1) if m else None


def fetch_coles(session: requests.Session, build_id: str, term: str) -> list[dict]:
    url = f"https://www.coles.com.au/_next/data/{build_id}/en/search/products.json"
    resp = get_with_retry(session, url, params={"q": term})
    if resp is None or "json" not in resp.headers.get("content-type", ""):
        return []
    results = resp.json().get("pageProps", {}).get("searchResults", {}).get("results", [])
    rows = []
    for p in results:
        if p.get("_type") != "PRODUCT":
            continue
        pricing = p.get("pricing") or {}
        price = pricing.get("now")
        if price is None:
            continue
        unit = pricing.get("unit") or {}
        unit_price = unit.get("price")
        measure_qty = unit.get("ofMeasureQuantity")
        measure_units = unit.get("ofMeasureUnits") or ""
        unit_measure = f"{measure_qty}{measure_units}" if measure_qty and measure_units else ""
        was = pricing.get("was") or None  # Coles uses 0 for "no was price"
        rows.append(
            {
                "retailer": "coles",
                "product_id": p.get("id"),
                "name": f"{p.get('brand') or ''} {p.get('name') or ''}".strip(),
                "brand": p.get("brand") or "",
                "size_raw": p.get("size") or "",
                "price": price,
                "was_price": was,
                "unit_price": unit_price,
                "unit_measure": unit_measure,
                "is_on_special": bool(pricing.get("onlineSpecial")),
            }
        )
    return rows


# --- Orchestration ----------------------------------------------------------


def run(snapshot_date: str | None = None) -> Path:
    snapshot_date = snapshot_date or dt.date.today().isoformat()
    basket = load_basket()
    session = make_session()

    build_id = resolve_coles_build_id(session)
    if build_id:
        log.info("Coles buildId: %s", build_id)
    else:
        log.error("Could not resolve Coles buildId; Coles fetch will be skipped")

    all_rows: list[dict] = []
    counts = {"woolworths": 0, "coles": 0}
    for i, item in enumerate(basket, 1):
        term, category = item["search_term"], item["category"]
        fetched_at = dt.datetime.now(dt.timezone.utc).isoformat()

        wow = fetch_woolworths(session, term)
        time.sleep(REQUEST_DELAY_S)
        col = fetch_coles(session, build_id, term) if build_id else []
        time.sleep(REQUEST_DELAY_S)

        for rows in (wow, col):
            for rank, row in enumerate(rows, 1):
                row["result_rank"] = rank
        for row in wow + col:
            row.update(search_term=term, category=category,
                       snapshot_date=snapshot_date, fetched_at=fetched_at)
            all_rows.append(row)
        counts["woolworths"] += len(wow)
        counts["coles"] += len(col)
        log.info("[%d/%d] %-32s wow=%-3d coles=%-3d", i, len(basket), term, len(wow), len(col))

    for retailer, n in counts.items():
        if n == 0:
            raise RuntimeError(f"No products fetched from {retailer} — aborting run")

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RAW_DIR / f"prices_{snapshot_date}.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=RAW_COLUMNS)
        writer.writeheader()
        writer.writerows(all_rows)
    log.info("Wrote %d rows to %s", len(all_rows), out_path)
    return out_path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    run()
