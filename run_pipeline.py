"""End-to-end pipeline: fetch -> stage -> match -> marts -> dashboard.

Usage:
    python run_pipeline.py               # full run including live fetch
    python run_pipeline.py --skip-fetch  # rebuild warehouse from existing raw CSVs
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from dashboard import build_dashboard  # noqa: E402
from ingest import fetch_prices  # noqa: E402
from matching import match_products  # noqa: E402

log = logging.getLogger("pipeline")

SQL_DIR = PROJECT_ROOT / "transform" / "sql"
DB_PATH = PROJECT_ROOT / "data" / "warehouse.duckdb"

GRAIN_KEYS = {
    "stg_prices": ["retailer", "product_id", "search_term", "snapshot_date"],
    "int_matched_products": ["wow_product_id", "coles_product_id", "snapshot_date"],
    "mart_pair_comparison": ["wow_product_id", "coles_product_id", "snapshot_date"],
    "mart_basket": ["retailer", "search_term", "snapshot_date"],
    "mart_category_unit_price": ["snapshot_date", "category", "unit_price_basis", "retailer"],
    "mart_specials": ["snapshot_date", "retailer"],
}


def run_sql_file(con: duckdb.DuckDBPyConnection, path: Path) -> None:
    log.info("Running %s", path.name)
    con.execute(path.read_text(encoding="utf-8"))


def assert_grain(con: duckdb.DuckDBPyConnection, table: str, keys: list[str]) -> None:
    key_expr = ", ".join(keys)
    total, distinct = con.execute(
        f"SELECT count(*), count(DISTINCT ({key_expr})) FROM {table}"
    ).fetchone()
    if total != distinct:
        raise AssertionError(
            f"Grain violation in {table}: {total} rows but {distinct} distinct ({key_expr})"
        )
    if total == 0:
        raise AssertionError(f"{table} is empty")
    log.info("Grain OK: %-28s %5d rows unique on (%s)", table, total, key_expr)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-fetch", action="store_true",
                        help="rebuild from existing raw CSVs without hitting the retailer APIs")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    if not args.skip_fetch:
        fetch_prices.run()

    os.chdir(PROJECT_ROOT)  # SQL models reference data/raw/*.csv relatively
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH))

    sql_files = sorted(SQL_DIR.glob("*.sql"))
    staging = [p for p in sql_files if p.name.startswith("01_")]
    marts = [p for p in sql_files if not p.name.startswith("01_")]

    for path in staging:
        run_sql_file(con, path)
    match_products.run(con)
    for path in marts:
        run_sql_file(con, path)

    for table, keys in GRAIN_KEYS.items():
        assert_grain(con, table, keys)

    build_dashboard.run(con)
    con.close()
    log.info("Pipeline complete. Warehouse: %s", DB_PATH)


if __name__ == "__main__":
    main()
