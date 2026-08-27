"""FR-2 — does the Hot Prices backfill agree with prices this project collected itself?

The gate PRD-v3 §6 puts in front of every backfill figure, and the reason the
daily collector keeps running even though somebody else has three more years of
history than it does.

The test
--------
For every (retailer, product_id, snapshot_date) this repo observed with its own
collector, ask the backfill what price it implies for that product on that day —
the last change point on or before the date — and compare to what we actually
saw. Two independently built scrapers, hitting the same retailers from different
machines on different schedules, should agree on the shelf price or one of them
is wrong.

This is the same move as docs/reconciliation.md, aimed outward. That document
proved the dbt port moved none of this project's *own* numbers, which is a check
against self-inflicted error. This one checks the numbers against a stranger's,
which is the only kind of check that can catch a mistake both of our models make
for the same reason.

Observations where the backfill has no change point on or before the day are
dropped and counted, never approximated. A product Hot Prices first saw in
August cannot testify about July, and PRD-v3 §5.2 rule 3 forbids pretending
otherwise.

Run it:
    .venv\\Scripts\\python scripts\\verify_backfill.py
    .venv\\Scripts\\python scripts\\verify_backfill.py --fail-under 99.0
"""

from __future__ import annotations

import argparse
import logging
import sys
from bisect import bisect_right
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import warehouse  # noqa: E402

log = logging.getLogger("verify_backfill")

TABLE = "backfill_verification"

# Prices are stored to the cent by both sides; anything under half a cent is a
# float representation artefact, not a disagreement.
CENT = 0.005


def compare(wh: warehouse.Warehouse) -> pd.DataFrame:
    """One row per comparable observation, with both prices and the verdict."""
    mine = wh.query_df(
        """
        SELECT retailer, product_id, snapshot_date, name, price
        FROM int_product_prices_daily
        WHERE price IS NOT NULL
        """
    )
    theirs = wh.query_df(
        """
        SELECT retailer, product_id, change_date, price
        FROM raw_hotprices
        ORDER BY retailer, product_id, change_date
        """
    )
    if mine.empty:
        raise RuntimeError("int_product_prices_daily is empty — has the v2 pipeline run?")
    if theirs.empty:
        raise RuntimeError("raw_hotprices is empty — has ingest/load_hotprices run?")

    mine["product_id"] = mine["product_id"].astype(str)
    theirs["product_id"] = theirs["product_id"].astype(str)
    mine["snapshot_date"] = pd.to_datetime(mine["snapshot_date"]).dt.date
    theirs["change_date"] = pd.to_datetime(theirs["change_date"]).dt.date

    # Sorted change points per product, so the lookup is a binary search rather
    # than a scan per observation.
    series: dict[tuple[str, str], tuple[list, list]] = {}
    for key, group in theirs.groupby(["retailer", "product_id"], sort=False):
        series[key] = (list(group.change_date), list(group.price))

    rows = []
    for r in mine.itertuples(index=False):
        found = series.get((r.retailer, r.product_id))
        if found is None:
            rows.append((r.retailer, r.product_id, r.name, r.snapshot_date,
                         r.price, None, "no_product"))
            continue
        dates, prices = found
        i = bisect_right(dates, r.snapshot_date)
        if i == 0:
            rows.append((r.retailer, r.product_id, r.name, r.snapshot_date,
                         r.price, None, "no_history_yet"))
            continue
        implied = prices[i - 1]
        verdict = "agree" if abs(implied - float(r.price)) < CENT else "disagree"
        rows.append((r.retailer, r.product_id, r.name, r.snapshot_date,
                     r.price, implied, verdict))

    return pd.DataFrame(
        rows,
        columns=["retailer", "product_id", "name", "snapshot_date",
                 "observed_price", "backfill_price", "verdict"],
    )


def report(result: pd.DataFrame) -> float:
    comparable = result[result.verdict.isin(["agree", "disagree"])]
    agree = int((comparable.verdict == "agree").sum())
    total = len(comparable)
    rate = 100.0 * agree / total if total else 0.0

    print()
    print("Hot Prices backfill vs this project's own collection")
    print("=" * 62)
    print(f"  comparable observations : {total:>7,}")
    print(f"  exact agreement         : {agree:>7,}  =  {rate:.2f}%")
    print(f"  disagreements           : {total - agree:>7,}")
    print(f"  no history on/before day: {int((result.verdict == 'no_history_yet').sum()):>7,}  (dropped)")
    print(f"  product absent upstream : {int((result.verdict == 'no_product').sum()):>7,}  (dropped)")

    bad = result[result.verdict == "disagree"]
    if not bad.empty:
        print()
        print(f"  Every disagreement, in full ({len(bad)}):")
        print("  " + "-" * 60)
        for r in bad.sort_values(["retailer", "snapshot_date"]).itertuples(index=False):
            print(f"  {r.retailer:<11} {str(r.snapshot_date):<11} "
                  f"{str(r.name)[:38]:<38} ours ${r.observed_price:>7.2f}  "
                  f"theirs ${r.backfill_price:>7.2f}")

        by_retailer = bad.groupby("retailer").size().to_dict()
        print()
        print(f"  Disagreements by retailer: {by_retailer}")
    print()
    return rate


def run(wh: warehouse.Warehouse, fail_under: float | None = None) -> float:
    result = compare(wh)
    rate = report(result)
    wh.replace_table(TABLE, result)
    log.info("%s: %d rows written", TABLE, len(result))

    if fail_under is not None and rate < fail_under:
        raise SystemExit(
            f"Backfill agreement {rate:.2f}% is below the {fail_under:.2f}% gate. "
            "Backfill figures must not be published until this is understood."
        )
    return rate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fail-under", type=float, default=None,
                        help="exit non-zero if agreement falls below this percentage")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    with warehouse.connect() as wh:
        run(wh, fail_under=args.fail_under)


if __name__ == "__main__":
    main()
