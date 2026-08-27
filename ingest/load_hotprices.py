"""Land the Hot Prices dumps in the warehouse as `raw_hotprices`.

The same shape of step as ingest/load_raw.py, for the same reason: Snowflake
cannot read a local file, so unpacking the JSON is Python's job on both engines
and dbt gets one honest source table to declare and test.

Grain: one row per (retailer, product_id, change_date) — a *price change*, not
a day. `priceHistory` holds only the dates a price moved, so a product with
nine entries across three years is nine rows and not a thousand. PRD-v3 §5.1
covers why that is the right grain to keep and §5.2 covers what it costs.

Product attributes are denormalised onto every change row. They describe the
product as of the fetch, not as of the change — a product renamed in 2026 shows
its 2026 name against a 2024 price. That is a property of the upstream format,
which publishes one current record per product with its history attached, and
it is why `fetched_date` is on the row: it dates the attributes, while
`change_date` dates the price.
"""

from __future__ import annotations

import datetime as dt
import gzip
import json
import logging
from pathlib import Path

import pandas as pd

from ingest.fetch_hotprices import EXTERNAL_DIR, STORES, latest_dump
from warehouse import Warehouse

log = logging.getLogger(__name__)

TABLE = "raw_hotprices"

SOURCE_URL = "https://hotprices.org/data/latest-canonical.{store}.compressed.json.gz"

COLUMNS = [
    "retailer", "product_id", "name", "description",
    "unit", "quantity", "is_weighted", "category",
    "change_date", "price", "current_price",
    "source_store", "source_url", "fetched_date",
]


def _fetched_date_from(path: Path) -> dt.date:
    """hotprices_coles_2026-08-27.json.gz -> date(2026, 8, 27)."""
    return dt.date.fromisoformat(path.stem.replace(".json", "").split("_")[-1])


def read_dump(path: Path, store: str) -> pd.DataFrame:
    retailer = STORES[store]
    fetched_date = _fetched_date_from(path)
    products = json.loads(gzip.decompress(path.read_bytes()))

    rows = []
    for product in products:
        history = product.get("priceHistory") or []
        if not history:
            # No history means no observed price change, which is not the same
            # as a flat price — it is a product Hot Prices has seen once. There
            # is nothing to say about it over time, so it is dropped here rather
            # than carried as a single-point series that looks like data.
            continue
        # product_id stays a string, as in load_raw.py: Woolworths stockcodes are
        # numeric and would arrive as floats and stop joining to this repo's own
        # product ids — which is the whole basis of PRD-v3 FR-3.
        product_id = str(product["id"])
        name = product.get("name") or ""
        description = product.get("description") or ""
        unit = (product.get("unit") or "").lower()
        quantity = product.get("quantity")
        is_weighted = bool(product.get("isWeighted"))
        category = product.get("category")
        current_price = product.get("price")

        for point in history:
            rows.append(
                (
                    retailer, product_id, name, description,
                    unit, quantity, is_weighted, category,
                    point["date"], point["price"], current_price,
                    store, SOURCE_URL.format(store=store), fetched_date,
                )
            )

    df = pd.DataFrame(rows, columns=COLUMNS)
    log.info(
        "%s (%s): %d products -> %d price changes",
        retailer, path.name, len(products), len(df),
    )
    return df


# A dump where a large share of products carried two prices on one day would
# mean the change-point format itself is not what this module thinks it is, and
# quietly quarantining a third of the data would be the wrong response. Below
# this share it is a handful of odd products; above it, stop.
MAX_AMBIGUOUS_SHARE = 0.01


def quarantine_ambiguous(raw: pd.DataFrame) -> pd.DataFrame:
    """Drop products that report two different prices on the same date.

    Observed on 11 of 23,449 Woolworths products and none at Coles. Every case
    is a same-day pair like $4.45 and $8.90, or $2.50 and $5.00 — a promotion
    that opened and closed inside one of Hot Prices' collection cycles, with
    both observations landing on the one date.

    There is no way to tell from the file which of the two prices stood at the
    end of the day, and the whole downstream model is built on a change point
    meaning "the price became this and stayed". An ambiguous point does not just
    corrupt its own day: it makes the validity window either side of it wrong,
    which would silently mis-date a gap episode.

    So the product is dropped whole, not the day. Eleven products out of 44,659
    is a cost worth paying to keep the grain honest, and the alternative —
    picking one of the two prices — would be inventing an observation, which is
    the one thing this repo's rules forbid everywhere else.
    """
    key = ["retailer", "product_id", "change_date"]
    dupe_rows = raw[raw.duplicated(subset=key, keep=False)]
    if dupe_rows.empty:
        return raw

    bad = set(zip(dupe_rows.retailer, dupe_rows.product_id))
    share = len(bad) / max(raw.groupby(["retailer", "product_id"]).ngroups, 1)
    if share > MAX_AMBIGUOUS_SHARE:
        raise ValueError(
            f"{len(bad)} products ({share:.1%}) report two prices on one date. "
            "That is too many to be odd products — the change-point assumption "
            "behind ingest/load_hotprices.py no longer holds for this dump."
        )

    log.warning(
        "Quarantining %d product(s) with two prices on one date (%.3f%% of products, "
        "%d rows). Ambiguous change points cannot be dated, so the whole series is "
        "dropped rather than a price guessed:",
        len(bad), share * 100, len(raw[raw.set_index(key).index.isin(dupe_rows.set_index(key).index)]),
    )
    for retailer, product_id in sorted(bad):
        rows = dupe_rows[(dupe_rows.retailer == retailer) & (dupe_rows.product_id == product_id)]
        name = rows.iloc[0]["name"][:44]
        for date, group in rows.groupby("change_date"):
            log.warning(
                "  %-11s %-9s %-44s %s -> %s",
                retailer, product_id, name, date, sorted(group.price.tolist()),
            )

    keep = ~pd.Series(list(zip(raw.retailer, raw.product_id)), index=raw.index).isin(bad)
    return raw[keep].reset_index(drop=True)


def run(wh: Warehouse, external_dir: Path = EXTERNAL_DIR) -> int:
    frames = []
    for store in STORES:
        path = latest_dump(store, external_dir)
        if path is None:
            raise FileNotFoundError(
                f"No Hot Prices dump for {store!r} in {external_dir}. "
                "Run `python -m ingest.fetch_hotprices` first."
            )
        frames.append(read_dump(path, store))

    raw = pd.concat(frames, ignore_index=True)

    raw["price"] = pd.to_numeric(raw["price"], errors="coerce")
    raw["current_price"] = pd.to_numeric(raw["current_price"], errors="coerce")
    raw["quantity"] = pd.to_numeric(raw["quantity"], errors="coerce")
    raw["change_date"] = pd.to_datetime(raw["change_date"]).dt.date
    raw["fetched_date"] = pd.to_datetime(raw["fetched_date"]).dt.date

    raw = quarantine_ambiguous(raw)

    wh.replace_table(TABLE, raw)
    log.info(
        "%s: %d price changes, %s .. %s, %d products",
        TABLE, len(raw), raw["change_date"].min(), raw["change_date"].max(),
        raw.groupby(["retailer", "product_id"]).ngroups,
    )
    return len(raw)
