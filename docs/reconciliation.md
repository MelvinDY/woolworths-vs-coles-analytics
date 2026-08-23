# Reconciling the dbt port against v1

PRD v2 lists this as a risk: *"dbt port changes numbers already published on the
portfolio."* The mitigation was to reconcile before deleting the old SQL, and to
correct any changed figure on the site rather than quietly absorb it.

Nothing changed. Every v1 mart is reproduced row for row.

## Result

Run 2026-08-17, over the same five raw snapshots (2026-07-15 to 2026-08-16):

```
OK   stg_prices                   v1=9722   v2=9722   only_in_v1=0 only_in_v2=0
OK   int_matched_products         v1=644    v2=644    only_in_v1=0 only_in_v2=0
OK   mart_pair_comparison         v1=644    v2=644    only_in_v1=0 only_in_v2=0
OK   mart_basket                  v1=498    v2=498    only_in_v1=0 only_in_v2=0
OK   mart_category_unit_price     v1=140    v2=140    only_in_v1=0 only_in_v2=0
OK   mart_specials                v1=10     v2=10     only_in_v1=0 only_in_v2=0
```

`only_in_v1` / `only_in_v2` are the two directions of a set difference over
every shared column, so a single changed cent in a single row would show up.
No published figure needed correcting.

## Method

`scripts/reconcile_v1.py`. The v1 pipeline is run against the same raw CSVs, its
six tables are dumped to parquet, the dbt project is built, and each table is
compared both ways with `EXCEPT`. The script is kept in the repo — see its
docstring for how to regenerate a baseline from a pre-port commit.

Reconciliation ran before `transform/sql/` was removed, and the removal is a
separate, later commit, so the old models remain recoverable from git history.

## Changes that are real, and why they move nothing

Three things about the port are not byte-identical to v1, and each is a type or
a structure rather than a value.

**1. `regexp_extract` became a dispatched macro.** DuckDB and Snowflake have
different capture-group functions, so the call goes through `regex_group()`
(see [snowflake.md](snowflake.md)). The patterns were also rewritten without
backslashes — `[0-9]` for `\d`, `([^a-z]|$)` for `\b` — because Snowflake treats
backslash as a string escape. Different text, same matches: `stg_prices`
reconciles exactly, which is the assertion that the rewrite was faithful.

**2. `try_cast` on `was_price` and `unit_price` became a plain `cast`.**
Snowflake's `TRY_CAST` takes string input only. `ingest/load_raw.py` now coerces
those columns with `to_numeric(errors='coerce')` before dbt sees them, so they
are already floats with NULL where the retailer sent nothing, and the `try` was
doing no work. Values unchanged.

**3. `matched_pairs.snapshot_date` is a DATE, not a midnight TIMESTAMP.** v1's
matcher wrote pandas Timestamps straight back out, which landed that one grain
column as `TIMESTAMP_NS` while every other `snapshot_date` in the warehouse was
a `DATE`. DuckDB compares the two without complaint; Snowflake is less
forgiving. The values were always midnight, so nothing moves — this is a type
correction, and it is the kind of thing a port is for.

## One deliberate deviation from PRD v2 §5

The PRD's data table gives `stg_prices` the grain
`(retailer, product_id, snapshot_date)`. It kept v1's
`(retailer, product_id, search_term, snapshot_date)` instead.

One product legitimately answers several basket lines — the same 2 L milk is a
hit for both `full cream milk 2l` and `milk` — and `mart_basket` compares the
cheapest hit *per line*. Collapsing `search_term` out of staging would have
silently changed a published basket total, which is precisely what this
reconciliation exists to prevent.

The product-per-day grain the PRD was reaching for is real and needed: the SCD2
snapshot cannot key on `(retailer, product_id)` while two rows compete for that
key. It lives in a new model, `int_product_prices_daily`, which resolves the
duplicate deterministically (best-ranked hit wins, search term breaks ties).
Everything that reasons about time reads that; only `mart_basket` and
`mart_category_unit_price` read `stg_prices` directly.
