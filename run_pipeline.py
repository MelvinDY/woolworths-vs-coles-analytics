"""End-to-end pipeline: fetch -> load -> stage -> snapshot -> match -> build -> dashboard.

Usage:
    python run_pipeline.py                  # full run including live fetch
    python run_pipeline.py --skip-fetch     # rebuild the warehouse from stored raw CSVs
    python run_pipeline.py --full-refresh   # rebuild incremental marts from scratch
    python run_pipeline.py --backfill       # also build v3 Arm A from the Hot Prices history
    python run_pipeline.py --target snowflake

The warehouse is chosen by DBT_TARGET (default `duckdb`), which --target sets
for you. Both targets run the same dbt project; see docs/snowflake.md.

Why the run is not just `dbt build`
-----------------------------------
Two steps cannot be SQL. The raw CSVs have to be landed in whichever warehouse
is configured, and cross-retailer matching is fuzzy string work that rapidfuzz
does and SQL does not. The matcher needs staged prices to read and the marts
need matched pairs to read, so dbt runs either side of it.
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

import warehouse  # noqa: E402
from dashboard import build_dashboard  # noqa: E402
from ingest import fetch_hotprices, fetch_prices, load_hotprices, load_raw  # noqa: E402
from matching import match_backfill, match_products  # noqa: E402
from scripts import verify_backfill  # noqa: E402
from transform import dbt_runner  # noqa: E402

log = logging.getLogger("pipeline")

REPLAY_LEDGER = "snapshot_replay_log"

# v3 Arm A models. Selected explicitly rather than built by default, because the
# backfill is a research arm on a three-year external series and the daily job
# is a collection arm on this project's own — the daily run should not pay for
# rebuilding somebody else's history every morning.
BACKFILL_MODELS = [
    "stg_hotprices",
    "int_backfill_pair_daily",
    "mart_gap_episodes",
    "mart_brand_tier_gaps",
]

# The agreement rate below which Arm A figures must not be published. Set from
# the measured rate (99.98%) with room for a handful of same-week price moves
# where the two collectors sit on opposite sides of a change; a real break in
# the id-space join or the change-point semantics would land far below it.
BACKFILL_AGREEMENT_GATE = 99.0


def collected_days(wh: warehouse.Warehouse) -> list[dt.date]:
    rows = wh.query_rows(
        "SELECT DISTINCT snapshot_date FROM int_product_prices_daily ORDER BY 1"
    )
    # Both drivers hand dates back as pandas Timestamps. Normalise here so the
    # value that ends up in a --vars string is '2026-08-16', not
    # '2026-08-16 00:00:00'.
    return [pd.Timestamp(r[0]).date() for r in rows]


def replayed_days(wh: warehouse.Warehouse) -> set[dt.date]:
    if not wh.table_exists(REPLAY_LEDGER):
        return set()
    rows = wh.query_rows(f"SELECT snapshot_date FROM {REPLAY_LEDGER}")
    return {pd.Timestamp(r[0]).date() for r in rows}


def replay_snapshot(wh: warehouse.Warehouse) -> list[dt.date]:
    """Feed collected days into the SCD2 snapshot in chronological order.

    dbt's snapshot compares the source against the snapshot's current state, so
    the days have to go in forwards, one at a time. A ledger table records which
    days have been fed in — the snapshot itself cannot answer that question,
    because a day on which no price moved leaves no trace in it.

    The most recent day is always replayed, even if the ledger already has it.
    Re-running the collector on the same day is a supported operation (it
    overwrites that date's CSV), and a correction to today's prices has to be
    able to reach the snapshot. Replaying an unchanged day is a no-op.
    """
    days = collected_days(wh)
    if not days:
        raise RuntimeError("No collected days found — has the raw load run?")

    done = replayed_days(wh)
    pending = [d for d in days if d not in done or d == days[-1]]

    if len(pending) > 1:
        log.info("Replaying %d day(s) into snap_product_prices: %s .. %s",
                 len(pending), pending[0], pending[-1])

    for day in pending:
        dbt_runner.snapshot(as_of=str(day))

    ledger = pd.DataFrame(
        {
            "snapshot_date": sorted(set(days) & (done | set(pending))),
        }
    )
    ledger["replayed_at"] = pd.Timestamp.now(tz="UTC")
    wh.replace_table(REPLAY_LEDGER, ledger)
    return pending


def run_backfill(wh: warehouse.Warehouse, window_start: str | None) -> None:
    """v3 Arm A: land the Hot Prices history, verify it, pair it, model it.

    The order is the point. Verification runs before any pair is built and
    before any model is refreshed, because PRD-v3 FR-2 makes agreement with this
    project's own collection the gate on the whole arm rather than a report
    printed after the figures are already in the warehouse. If a future dump
    stops agreeing — an id space changed, the change-point semantics shifted —
    the run stops here with nothing published.
    """
    fetch_hotprices.run()
    load_hotprices.run(wh)

    log.info("Verifying the backfill against this project's own collected days")
    verify_backfill.run(wh, fail_under=BACKFILL_AGREEMENT_GATE)

    # Two dates, deliberately not the same one. `backfill_min_history` decides
    # which products are old enough to match; `backfill_start` decides how far
    # back the series is built. Using the analysis window for eligibility means
    # demanding every pair span the whole window, which threw away 96% of the
    # pair set the first time this ran.
    analysis_start = window_start or dbt_runner.project_var("backfill_start")
    min_history = dbt_runner.project_var("backfill_min_history")

    match_backfill.run(wh, window_start=dt.date.fromisoformat(min_history))
    dbt_runner.build_selected(BACKFILL_MODELS, dbt_vars={"backfill_start": analysis_start})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--skip-fetch", action="store_true",
                        help="rebuild from existing raw CSVs without hitting the retailer APIs")
    parser.add_argument("--full-refresh", action="store_true",
                        help="rebuild incremental marts from scratch instead of appending a day")
    parser.add_argument("--target", choices=["duckdb", "snowflake"],
                        help="warehouse to build into (default: $DBT_TARGET, else duckdb)")
    parser.add_argument("--backfill", action="store_true",
                        help="also build v3 Arm A from the Hot Prices dumps (fetches if absent)")
    parser.add_argument("--backfill-start", default=None,
                        help="left edge of the Arm A window (default: dbt var backfill_start)")
    args = parser.parse_args()

    # force=True: importing dbt installs a root log handler, which makes a plain
    # basicConfig() a silent no-op and swallows this pipeline's own output.
    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)s %(name)s %(message)s", force=True)

    if args.target:
        os.environ["DBT_TARGET"] = args.target

    if not args.skip_fetch:
        fetch_prices.run()

    os.chdir(PROJECT_ROOT)
    log.info("Warehouse target: %s", warehouse.target_name())

    dbt_runner.deps()

    with warehouse.connect() as wh:
        load_raw.run(wh)

        # Loud, not fatal: see dbt_runner.source_freshness.
        dbt_runner.source_freshness()

        # Stage first — the matcher reads stg_prices and the snapshot reads the
        # daily product grain, and neither exists until dbt has run.
        dbt_runner.run(select=["stg_prices", "int_product_prices_daily"])

        replay_snapshot(wh)

        match_products.run(wh)

        # Everything else, plus every test. Grain assertions used to live in
        # this file as hand-written Python; they are dbt tests now.
        latest = collected_days(wh)[-1]
        dbt_runner.build(full_refresh=args.full_refresh, as_of=str(latest))

        # After the main build: FR-3 reads int_matched_pairs and FR-2 reads
        # int_product_prices_daily, so both need the v2 graph to exist first.
        if args.backfill:
            run_backfill(wh, args.backfill_start)

        build_dashboard.run(wh)

    log.info("Pipeline complete.")


if __name__ == "__main__":
    main()
