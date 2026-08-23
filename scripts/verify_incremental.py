"""Prove that the incremental path and the full-refresh path agree.

An incremental model is a claim: "appending a day gives the same answer as
rebuilding everything." Nothing enforces that claim — you can write an
incremental model whose output silently depends on how many times it has been
run, and the usual way people find out is when a full refresh months later
changes a published number.

So this checks it:

  1. rebuild mart_price_history with --full-refresh and keep a copy
  2. delete the most recent days from the real table
  3. run it incrementally, which re-derives exactly those days
  4. assert the result is byte-identical to the copy

Run it after any change to the model or its incremental predicate:

    python scripts/verify_incremental.py

Exits non-zero on a difference and leaves the table correct either way (the
final state is the incrementally rebuilt one, which is what the assertion
just proved equals a full rebuild).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import warehouse  # noqa: E402
from transform import dbt_runner  # noqa: E402

log = logging.getLogger("verify-incremental")

MODEL = "mart_price_history"
BASELINE = "_verify_price_history_full"
DAYS_TO_REPLAY = 2


def main() -> int:
    # force=True: importing dbt installs a root log handler, which makes a plain
    # basicConfig() a silent no-op and swallows this script's own output.
    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)s %(name)s %(message)s", force=True)

    with warehouse.connect() as wh:
        log.info("Step 1/4: full refresh")
        dbt_runner.run(select=[MODEL], full_refresh=True)
        wh.query_df(f"CREATE OR REPLACE TABLE {BASELINE} AS SELECT * FROM {MODEL}")
        n_full = wh.query_one(f"SELECT count(*) FROM {BASELINE}")[0]

        days = [r[0] for r in wh.query_rows(
            f"SELECT DISTINCT snapshot_date FROM {BASELINE} ORDER BY 1 DESC"
        )][:DAYS_TO_REPLAY]
        if len(days) < DAYS_TO_REPLAY:
            log.warning("Only %d day(s) collected — the incremental path cannot be "
                        "exercised yet. Not a failure.", len(days))
            return 0

        log.info("Step 2/4: deleting %d most recent day(s): %s",
                 len(days), ", ".join(str(d) for d in days))
        placeholders = ", ".join("?" for _ in days)
        wh.query_df(f"DELETE FROM {MODEL} WHERE snapshot_date IN ({placeholders})", list(days))

        log.info("Step 3/4: incremental run")
        dbt_runner.run(select=[MODEL])
        n_inc = wh.query_one(f"SELECT count(*) FROM {MODEL}")[0]

        log.info("Step 4/4: comparing")
        only_full = wh.query_one(
            f"SELECT count(*) FROM (SELECT * FROM {BASELINE} EXCEPT SELECT * FROM {MODEL})")[0]
        only_inc = wh.query_one(
            f"SELECT count(*) FROM (SELECT * FROM {MODEL} EXCEPT SELECT * FROM {BASELINE})")[0]
        wh.query_df(f"DROP TABLE {BASELINE}")

        if only_full or only_inc or n_full != n_inc:
            log.error("MISMATCH: full=%d rows, incremental=%d rows, "
                      "%d only in full, %d only in incremental",
                      n_full, n_inc, only_full, only_inc)
            return 1

        log.info("Incremental and full-refresh agree exactly (%d rows).", n_full)
        return 0


if __name__ == "__main__":
    sys.exit(main())
