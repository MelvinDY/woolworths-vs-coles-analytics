# Snowflake as a second target

## Status, stated plainly

**Every figure published by this project — on the dashboard, in the README, in
the PRDs — was produced on DuckDB.** Nothing here has been executed against a
live Snowflake account. As of **2026-08-17** the Snowflake path is written,
statically checked, and unrun.

That is a deliberate ordering, not an oversight. The PRD's rule is that
Snowflake is additive and DuckDB is the target that has to work; a trial account
expires after 30 days, and starting the clock before the code was ready would
have spent the credits on debugging rather than on demonstrating anything. The
honest way to write this down is to say which parts are facts and which are
claims:

| | Status |
|---|---|
| dbt project builds green on DuckDB | **Verified.** 69/69 nodes, `dbt build` |
| v1 marts reconcile row-for-row after the port | **Verified.** See [reconciliation.md](reconciliation.md) |
| Incremental path equals full refresh | **Verified.** `scripts/verify_incremental.py` |
| Project parses with the Snowflake adapter registered | **Verified.** `dbt parse --target snowflake` |
| Compiled SQL is accepted by a Snowflake grammar | **Verified, with caveats.** `scripts/check_snowflake_sql.py` |
| `dbt build --target snowflake` is green | **Not verified.** Needs an account |
| write_pandas lands the raw table with usable types | **Not verified.** Needs an account |

## Running it

1. **Create the trial.** [signup.snowflake.com](https://signup.snowflake.com) —
   30 days, no card. Any cloud/region; pick the one nearest you.
2. **Create the objects.** Paste `scripts/snowflake_setup.sql` into a worksheet
   and run it. It makes an XSMALL warehouse that suspends after 60 seconds idle,
   a database and a schema. The auto-suspend is the whole cost story: a build of
   this project is seconds of compute, and a warehouse left running is not.
3. **Add credentials.** `cp .env.example .env` and fill in the four Snowflake
   values. `.env` is gitignored and nothing reads it but this repo.
4. **Install the adapter.** `pip install -r requirements-snowflake.txt`
5. **Check the connection.** From `transform/dbt/`:
   `dbt debug --target snowflake`
6. **Build.** `python run_pipeline.py --skip-fetch --target snowflake`

`--target snowflake` sets `DBT_TARGET`, which is the single switch: the dbt
profile, the Python loader, the matcher and the dashboard builder all read it.

## What is engine-specific, in full

The whole list. If it is not here, both engines run the identical statement.

### 1. Regular-expression capture groups
`transform/dbt/macros/cross_db.sql`, dispatched on `target.type`:

```
DuckDB      regexp_extract(subject, pattern, group)              -> '' when no match
Snowflake   regexp_substr(subject, pattern, 1, 1, 'ce', group)   -> NULL when no match
```

Both are wrapped in `nullif(..., '')` so the two behave identically downstream.

Note what is *not* dispatched: the patterns. Every regex in this project is
written without a backslash — `[0-9]` not `\d`, `[.]` not `\.`,
`([^a-z]|$)` not `\b` — because Snowflake treats backslash as a string escape
and DuckDB does not. One literal, both engines, no escaping rules to remember.

### 2. `TRY_CAST`
Snowflake's `TRY_CAST` accepts **string input only** and raises on a numeric
column; DuckDB's accepts anything. `stg_prices` originally used `try_cast` on
`was_price` and `unit_price` (a v1 habit from when DuckDB read the CSVs
directly). Those are plain casts now — `ingest/load_raw.py` coerces the columns
with `to_numeric(errors='coerce')`, so they arrive as floats with NULL where the
retailer sent nothing, and the try was doing no work.

`scripts/check_snowflake_sql.py` enforces this: a `try_cast` over anything but a
regex extraction fails the check. This was a real bug, caught statically, before
it ever reached a Snowflake account.

### 3. Loading the raw CSVs
DuckDB reads `data/raw/*.csv` off disk; Snowflake cannot see a local file. So
the load is Python's job on both engines (`ingest/load_raw.py` →
`warehouse.replace_table`), which is also why `raw_prices` is a declared dbt
source with tests and a freshness check rather than a glob buried in a model.

`warehouse/__init__.py` holds the two implementations. Both expose the same four
operations, deliberately, so there is little room for them to drift:
`query_df`, `replace_table`, `table_exists`, `close`.

### 4. Identifier case
`write_pandas` is called with `quote_identifiers=False` so tables and columns
land as Snowflake's normal unquoted-uppercase identifiers, which is what dbt's
generated SQL resolves to. Quoted lowercase would make the source
unreferenceable. `query_df` lowercases result column names on both engines so
the Python that reads them does not care.

## What only a live run can settle

Named, so nobody has to guess what "unverified" covers:

- **`write_pandas` type inference.** `snapshot_date` is a column of Python
  `date` objects and `fetched_at` is tz-aware; both should land as DATE and
  TIMESTAMP_TZ via pyarrow, but "should" is doing work in that sentence. If
  `snapshot_date` arrives as VARCHAR, `stg_prices` still casts it, but the
  source freshness check on `fetched_at` would not survive a string.
- **`'ce'` versus `'c'` in `regexp_substr`.** Snowflake extracts the capture
  group whenever `group_num` is supplied, with or without the `e` flag. `'ce'`
  is explicit and documented as correct; sqlglot's own translation emits `'c'`.
  Either should work. Neither has been run.
- **Division by zero.** `unit_price / (measure_qty * 1000)` returns NULL on
  DuckDB and **raises** on Snowflake. No row in the collected data has a zero
  unit measure, so this has never fired — but it is an engine difference sitting
  in live SQL, and the first Snowflake run is when it would be found.
- **`delete+insert` on the incremental mart.** Supported by both adapters, but
  the Snowflake implementation is a different statement.
- **Cost.** A build is seconds of XSMALL compute. Unmeasured.

## What `check_snowflake_sql.py` does and does not prove

It compiles the project on DuckDB, applies the one documented divergence to the
AST, and asserts every resulting statement — 69 of them, models and generated
test queries alike — parses under sqlglot's Snowflake dialect, carries no
`TRY_CAST` over a non-string, and contains no DuckDB-only syntax.

It proves the SQL is *shaped* right. It does not prove it runs: sqlglot's
grammar is more permissive than Snowflake's planner, it knows nothing about
types or the information schema, and the three risks above are all invisible to
it. Passing is a floor.

## When the trial expires

Nothing happens. DuckDB is the default target, `requirements.txt` does not
mention Snowflake, and the GitHub workflow and the daily collector never touch
it. `python run_pipeline.py` keeps working with zero edits — which was the
requirement (PRD v2, G5), and is the reason the Snowflake path was built as an
addition rather than a migration.
