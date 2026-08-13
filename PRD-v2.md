# PRD v2 — Price History, Slowly-Changing Dimensions & Snowflake

**Owner:** Melvin Darial Yogiana
**Status:** Draft v2 · August 2026
**Extends:** [PRD.md](PRD.md) (v1 — same-day snapshot, DuckDB, entity resolution)
**Stack added:** dbt · Snowflake (dev target alongside DuckDB) · dbt snapshots

---

## 1. Background & positioning

v1 answered "who is cheaper today" from a single same-day snapshot. Since then
the daily collection workflow has been running, and the repo now holds something
that cannot be bought, scraped retroactively or regenerated: **an accumulating
daily price series for matched product pairs.** Nobody can backfill it. If the
collection stops, the asset stops growing.

That changes what this project should be. A one-day comparison is a nice answer
to a household question. A price *history* is the natural home for the three
techniques that dominate analytics-engineering job ads and that the portfolio
does not yet demonstrate anywhere:

1. **Slowly-changing dimensions** — a product's price is the textbook SCD2 case, and here it is real rather than a tutorial fixture.
2. **Incremental models** — appending a day at a time instead of rebuilding history is the difference between a script and a pipeline.
3. **Snowflake** — named alongside dbt and Airflow in a majority of product-company data job descriptions, and the single most conspicuous gap in the portfolio's warehouse coverage.

v1's non-goals deliberately excluded dbt ("the portfolio already shows dbt
twice"). **That decision is reversed here, on purpose:** the reason has changed.
dbt is no longer being added for a third demonstration of models and tests — it
is being added because snapshots and incremental materialisations are the
correct tools for the data this repo now has, and hand-rolled SQL would be the
worse engineering choice.

## 2. Goals

| # | Goal | Measure of success |
|---|------|--------------------|
| G1 | Price history is modelled, not just stored | `snap_product_prices` (SCD2) captures every price change per (retailer, product_id) with valid-from/valid-to |
| G2 | Incremental, not full-refresh | Daily marts build incrementally on `snapshot_date`; a day's run touches only that day's partition |
| G3 | Snowflake is a real target | The same dbt project builds green on both DuckDB (local, free, permanent) and Snowflake (trial), selected by profile |
| G4 | A finding only history can produce | At least one published insight impossible from a single snapshot — e.g. how often a "special" is a genuine cut versus a restored baseline |
| G5 | Honest after the trial lapses | When Snowflake credits expire, `python run_pipeline.py` still runs end-to-end on DuckDB with zero edits |

## 3. Non-goals

- **No paid Snowflake.** Trial credits only. If they run out mid-build, DuckDB is the answer, not a credit card.
- No expansion beyond Woolworths and Coles — ALDI/IGA still have no comparable public endpoints.
- No price *prediction*. Descriptive history is the point; a forecast on three months of one basket would be a claim the data cannot carry.
- No replacement of the static HTML dashboard with a BI tool — that belongs to the SaaS project's v2.
- No rewrite of the matcher. Entity resolution is v1's strongest asset and stays as-is.

## 4. Users

| User | Need |
|------|------|
| Hiring manager / recruiter (primary) | See "Snowflake · dbt · SCD2" in the stack line and a price-history chart above the fold |
| Technical interviewer | Probe the snapshot strategy: why `check` over `timestamp`, what happens when a product disappears from the feed, how late-arriving days are handled |
| Melvin (operator) | One command, unchanged; warehouse chosen by an env var |

## 5. Data & grain

| Layer | Grain | Notes |
|-------|-------|-------|
| `data/raw/prices_{date}.csv` | (retailer, product_id, snapshot_date) | Unchanged. Immutable, append-only, one file per day |
| `stg_prices` | (retailer, product_id, snapshot_date) | Existing cleaning logic ported to a dbt staging model |
| `snap_product_prices` | (retailer, product_id) × validity window | **New.** SCD2 via dbt snapshot, `strategy=check` on `price`, `was_price`, `is_on_special` |
| `mart_price_history` | (pair_id, snapshot_date) | **New.** Incremental. Matched-pair prices per day with gap and winner |
| `mart_special_behaviour` | (retailer, product_id, special_episode) | **New.** One row per promotion episode: depth, duration, and whether the post-special price returned to baseline |

The interesting grain question — and the one an interviewer should ask — is what
happens when a product vanishes from the feed for a day. Ruling: a gap is a gap,
not a price change; the snapshot does not close the record, and
`mart_price_history` leaves the day null rather than forward-filling. Inventing
continuity is how a price series starts lying.

## 6. Functional requirements

### FR-1 dbt project (`transform/dbt/`)
- Port the existing `transform/sql/` models to dbt models, preserving names and logic so the diff is reviewable.
- Sources declared over the raw CSV loads with `not_null`/`unique` on the grain and a `freshness` check (warn > 36 h) — a stale collector should be loud.
- Grain uniqueness tests on every model via `dbt_utils.unique_combination_of_columns`.

### FR-2 Snapshot
- `snapshots/snap_product_prices.sql`, `strategy=check`, `check_cols=['price','was_price','is_on_special']`, `unique_key` on `(retailer, product_id)`.
- Documented decision note on why `check` rather than `timestamp` (the source has no reliable updated-at, only the day we observed it).

### FR-3 Incremental marts
- `mart_price_history` materialised `incremental` on `snapshot_date` with `unique_key=(pair_id, snapshot_date)`.
- Full-refresh path documented and tested, so a schema change is a known operation rather than a surprise.

### FR-4 Dual warehouse targets
- `profiles.yml` with `duckdb` (default) and `snowflake` targets; every model must build on both.
- Any Snowflake-specific SQL isolated behind dbt's `{{ target.type }}` — divergence is allowed but must be visible in one place.
- README documents the trial's expiry and states plainly which artifacts were produced on which engine.

### FR-5 Dashboard additions
- A price-history line per headline pair, and a specials panel driven by `mart_special_behaviour`.
- Notes panel gains the collection start date and the current number of snapshot days — the honest denominator behind every history claim.

## 7. Milestones

| Phase | Deliverable | Estimate |
|-------|-------------|----------|
| P1 | dbt project scaffolded; v1 SQL ported and green on DuckDB | 1 day |
| P2 | Snapshot + incremental marts, grain tests | 1 day |
| P3 | Snowflake profile; both targets green; divergences documented | Half a day |
| P4 | Dashboard history + specials sections; README/PRD updated | 1 day |

## 8. Risks

| Risk | Mitigation |
|------|------------|
| Too few snapshot days for a credible history claim | State the day count next to every history figure; hold the "specials" finding until the series can support it |
| Collector breaks silently (Coles `buildId` rotates) | Source freshness test + alert on the daily workflow; a stale series is worse than a missing one |
| Snowflake trial expires mid-project | DuckDB is the default target throughout; Snowflake is additive by construction |
| dbt port changes numbers already published on the portfolio | Reconcile v1 marts against ported models before deleting the old SQL; any change in a published figure gets corrected on the site, not quietly absorbed |

## 9. Cost

$0. Snowflake 30-day trial credits; DuckDB local; GitHub Actions free tier for
the existing daily collection.

## 10. Definition of done

`dbt build` is green on both targets, the SCD2 snapshot has at least one real
captured price change, the dashboard shows a history chart with its day count
stated, and no figure on the portfolio contradicts the ported models.
