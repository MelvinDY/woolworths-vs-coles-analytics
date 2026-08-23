"""Compare the dbt-built marts against a v1 baseline, row for row.

The v2 port had one hard rule: it was allowed to change how the marts are built
and not what they contain. A figure already published on the portfolio must not
move because the SQL moved into dbt — and if one does, it gets corrected on the
site rather than quietly absorbed.

This is the check behind that rule. It is kept in the repo rather than thrown
away after the port, because the next engine or the next refactor will want it.

Producing a baseline
--------------------
Check out the last commit before the dbt port, run the v1 pipeline against the
same raw CSVs, and dump its tables:

    git worktree add ../v1-baseline <pre-port-sha>
    cd ../v1-baseline && python run_pipeline.py --skip-fetch
    python -c "import duckdb; con=duckdb.connect('data/warehouse.duckdb'); \\
        [con.execute(f\\"COPY {t} TO '../baseline/{t}.parquet' (FORMAT PARQUET)\\") \\
         for t in ['stg_prices','int_matched_products','mart_pair_comparison', \\
                   'mart_basket','mart_category_unit_price','mart_specials']]"

Then, from this repo:

    python scripts/reconcile_v1.py ../baseline

Exits non-zero on any difference. See docs/reconciliation.md for the result of
the run that gated the port.
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WAREHOUSE = PROJECT_ROOT / "data" / "warehouse.duckdb"

TABLES = [
    "stg_prices",
    "int_matched_products",
    "mart_pair_comparison",
    "mart_basket",
    "mart_category_unit_price",
    "mart_specials",
]


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    baseline = Path(sys.argv[1]).resolve()
    tables = sys.argv[2:] or TABLES

    con = duckdb.connect(":memory:")
    con.execute(f"ATTACH '{WAREHOUSE.as_posix()}' AS w (READ_ONLY)")

    failures = 0
    for table in tables:
        parquet = baseline / f"{table}.parquet"
        if not parquet.exists():
            print(f"MISS {table:<28} no baseline at {parquet}")
            failures += 1
            continue

        con.execute(f"CREATE OR REPLACE VIEW v1 AS SELECT * FROM read_parquet('{parquet.as_posix()}')")
        con.execute(f"CREATE OR REPLACE VIEW v2 AS SELECT * FROM w.main.{table}")
        c1 = [r[0] for r in con.execute("describe v1").fetchall()]
        c2 = [r[0] for r in con.execute("describe v2").fetchall()]
        dropped, added = sorted(set(c1) - set(c2)), sorted(set(c2) - set(c1))

        # Compare on the shared columns. A dropped column is a failure; an added
        # one is not, because v2 legitimately adds columns the old SQL never had.
        shared = ", ".join(c for c in c1 if c in c2)
        only_v1 = con.execute(f"SELECT count(*) FROM (SELECT {shared} FROM v1 EXCEPT SELECT {shared} FROM v2)").fetchone()[0]
        only_v2 = con.execute(f"SELECT count(*) FROM (SELECT {shared} FROM v2 EXCEPT SELECT {shared} FROM v1)").fetchone()[0]
        n1 = con.execute("SELECT count(*) FROM v1").fetchone()[0]
        n2 = con.execute("SELECT count(*) FROM v2").fetchone()[0]

        ok = not (dropped or only_v1 or only_v2 or n1 != n2)
        failures += 0 if ok else 1
        print(f"{'OK  ' if ok else 'DIFF'} {table:<28} v1={n1:<6} v2={n2:<6} "
              f"only_in_v1={only_v1} only_in_v2={only_v2} "
              f"cols_dropped={dropped} cols_added={added}")

    con.close()
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
