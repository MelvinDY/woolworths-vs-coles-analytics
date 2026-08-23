"""Land every raw price snapshot CSV in the target warehouse as `raw_prices`.

v1 skipped this step: DuckDB reads CSVs off disk, so the staging model could
just point `read_csv_auto` at data/raw/. Snowflake cannot see a local file, so
the load has to become an explicit step, and once it is explicit it may as well
be the same step on both engines. dbt then has one honest source table to
declare, test and freshness-check instead of a filesystem glob hidden inside a
model.

The CSVs stay the system of record. This table is rebuilt from them in full on
every run — it is a load, not a merge, and nothing downstream may write to it.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from warehouse import Warehouse

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"
TABLE = "raw_prices"

# The raw contract, as written by ingest/fetch_prices.py. Declared rather than
# inferred: a retailer quietly dropping a field should fail the load here, not
# surface three models later as a column of nulls.
COLUMNS = [
    "retailer", "product_id", "name", "brand", "size_raw",
    "price", "was_price", "unit_price", "unit_measure", "is_on_special",
    "result_rank", "search_term", "category", "snapshot_date", "fetched_at",
]

TEXT_COLUMNS = ["retailer", "product_id", "name", "brand", "size_raw",
                "unit_measure", "search_term", "category"]
FLOAT_COLUMNS = ["price", "was_price", "unit_price"]


def read_snapshots(raw_dir: Path = RAW_DIR) -> pd.DataFrame:
    paths = sorted(raw_dir.glob("prices_*.csv"))
    if not paths:
        raise FileNotFoundError(f"No raw snapshots in {raw_dir}")

    frames = []
    for path in paths:
        # product_id stays a string: Woolworths stockcodes are numeric and
        # would otherwise arrive as floats and stop joining to Coles' ids.
        df = pd.read_csv(path, dtype={c: "string" for c in TEXT_COLUMNS})
        missing = [c for c in COLUMNS if c not in df.columns]
        if missing:
            raise ValueError(f"{path.name} is missing columns: {missing}")
        frames.append(df[COLUMNS])

    raw = pd.concat(frames, ignore_index=True)

    for col in FLOAT_COLUMNS:
        raw[col] = pd.to_numeric(raw[col], errors="coerce")
    raw["result_rank"] = pd.to_numeric(raw["result_rank"], errors="coerce").astype("int64")
    raw["is_on_special"] = (
        raw["is_on_special"].astype("string").str.strip().str.lower().isin(["true", "1", "yes"])
    )
    raw["snapshot_date"] = pd.to_datetime(raw["snapshot_date"]).dt.date
    raw["fetched_at"] = pd.to_datetime(raw["fetched_at"], utc=True)

    log.info(
        "Read %d rows from %d snapshot files (%s .. %s)",
        len(raw), len(paths), raw["snapshot_date"].min(), raw["snapshot_date"].max(),
    )
    return raw


def run(wh: Warehouse, raw_dir: Path = RAW_DIR) -> int:
    raw = read_snapshots(raw_dir)
    wh.replace_table(TABLE, raw)
    return len(raw)
