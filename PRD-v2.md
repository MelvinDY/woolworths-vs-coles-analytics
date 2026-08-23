# PRD v2 — Price History, Slowly-Changing Dimensions & Snowflake

**Owner:** Melvin Darial Yogiana
**Status:** Built · 2026-08-17 — four of five goals met on DuckDB; G3 (Snowflake) written and statically checked but not run against a live account. See [§11 Delivery status](#11-delivery-status--2026-08-17).
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
| `data/raw/prices_{date}.csv` | (retailer, product_id, search_term, snapshot_date) | Unchanged. Immutable, append-only, one file per day |
| `raw_prices` | as above | **Added in build.** The CSVs landed in the target warehouse by `ingest/load_raw.py`, so dbt has a real source to test and freshness-check. Snowflake cannot read a local file, so the load could not stay inside a model |
| `stg_prices` | (retailer, product_id, search_term, snapshot_date) | Existing cleaning logic ported to a dbt staging model. **Grain corrected from this table's original draft** — see §11 |
| `int_product_prices_daily` | (retailer, product_id, snapshot_date) | **Added in build.** The product-per-day grain this section was reaching for. Everything that reasons about time reads this |
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

*Outturn:* $0, and the Snowflake trial has not been started — the credits are a
30-day clock, and starting it before there is time to use it would spend the
window on setup. The Snowflake target is built and waiting; see §11.

## 10. Definition of done

`dbt build` is green on both targets, the SCD2 snapshot has at least one real
captured price change, the dashboard shows a history chart with its day count
stated, and no figure on the portfolio contradicts the ported models.

---

## 11. Delivery status — 2026-08-17

Three of the four clauses in §10 are met. `dbt build` is green on one target,
not two.

### Against the goals

| # | Goal | Status |
|---|------|--------|
| G1 | Price history is modelled, not just stored | **Met.** `snap_product_prices` holds 3,254 price versions across 2,035 products, 1,219 of them since superseded, with validity windows dated to the day the price actually moved |
| G2 | Incremental, not full-refresh | **Met.** `mart_price_history` is incremental on `snapshot_date`; `scripts/verify_incremental.py` deletes the last two days, replays them, and asserts the result equals a full rebuild |
| G3 | Snowflake is a real target | **Not met.** The target, adapter, loader and dispatched macros exist and `dbt parse --target snowflake` is clean, but no live account has ever run it |
| G4 | A finding only history can produce | **Met**, and by the end it did produce the finding this PRD guessed at — see below |
| G5 | Honest after the trial lapses | **Met by construction.** DuckDB is the default; `requirements.txt` has no Snowflake dependency; the collector and the workflow never touch it |

### G3, stated plainly

`docs/snowflake.md` carries the full verified/unverified breakdown. The short
version: **every figure this project publishes was produced on DuckDB.** The
Snowflake path is written, its engine divergences are isolated in one dispatched
macro, and `scripts/check_snowflake_sql.py` asserts all 69 compiled statements
parse under a Snowflake grammar with no illegal `TRY_CAST` and no DuckDB-only
syntax. That is a syntax floor, not a green build, and the doc names the three
risks only a live run can settle.

Building the second target paid for itself anyway. It caught a real defect —
`try_cast` over a numeric column, which DuckDB accepts and Snowflake rejects —
and it forced the dialect differences into one reviewable file instead of
leaving them scattered through the models.

### G4: the finding arrived late

§2 guessed the history finding would be *"how often a special is a genuine cut
versus a restored baseline."* At five collected days the series could not answer
it: **0 of 137 promotion episodes had collected days on both sides.** §8 said to
hold the finding until the data could carry it, and it was held.

By the close of collection it could. Of **203** promotion episodes, **44** have
observed days on both sides of the promotion, and **39 of those 44 returned to
the baseline price**. The median episode was 41% off and ran 7 days. Nine in ten
specials that ended were a promotional cycle rather than a price change, which
is the question §2 set out to ask.

The earlier finding still stands and is the sharper one. Of 203 episodes, 121
began on a day the product had already been priced here, and **17 of those 121
were not price cuts**: 6 unchanged, and 11 up (including Schweppes mineral
waters, $3.00 → $3.30, flagged on special). All 17 were at Coles. All **100**
testable advertised "was" prices did match a price observed beforehand, so this
is not inflated reference pricing — it is the badge and the price coming apart.
No single snapshot distinguishes those.

The finding neither §2 nor §8 anticipated is the aisle split: parity runs from
62.5% in pantry to 7.1% in household on the same day, with the household gap six
times pantry's. It was found in the data rather than predicted, which makes it a
hypothesis this project generated rather than one it tested.

### Deviation from §5: the `stg_prices` grain

§5 originally gave `stg_prices` the grain `(retailer, product_id,
snapshot_date)`. It kept v1's `(retailer, product_id, search_term,
snapshot_date)`, and §5 above has been corrected to match the build.

One product legitimately answers several basket lines — the same 2 L milk is a
hit for both `full cream milk 2l` and `milk` — and `mart_basket` compares the
cheapest hit *per line*. Collapsing `search_term` out of staging would have
silently changed a published basket total, which §8's reconciliation risk exists
to prevent. The product-per-day grain the snapshot genuinely needs became a new
model, `int_product_prices_daily`.

### §8 risks, resolved

| Risk | Outcome |
|------|---------|
| Too few snapshot days for a credible history claim | **Materialised, and handled as planned.** Day count is printed beside every history figure on the dashboard and in the README; the restored-vs-cut finding is held |
| Collector breaks silently | **Mitigated.** Source freshness on `raw_prices` (warn 36 h, error 96 h) runs every pipeline invocation, loud but non-fatal so the marts still rebuild from history already on disk |
| Snowflake trial expires mid-project | **Avoided.** Trial never started; DuckDB was the default throughout |
| dbt port changes published numbers | **Did not happen.** All six v1 marts reconcile row for row — [docs/reconciliation.md](docs/reconciliation.md). `transform/sql/` was removed only after that passed |

### Milestones, as built

| Phase | Estimate | Status |
|-------|----------|--------|
| P1 dbt project scaffolded; v1 SQL ported and green on DuckDB | 1 day | Done. 69/69 nodes green, marts reconciled |
| P2 Snapshot + incremental marts, grain tests | 1 day | Done. Grain tests on every model via `dbt_utils.unique_combination_of_columns`, plus assertions for the gap rule and the SCD2 one-open-row invariant |
| P3 Snowflake profile; both targets green; divergences documented | half a day | Partial. Profile, adapter, loader and divergence doc done; both-targets-green outstanding |
| P4 Dashboard history + specials sections; README/PRD updated | 1 day | Done |

### What is left

1. Run `dbt build --target snowflake` against a trial account and close G3. Steps
   1–6 of `docs/snowflake.md`; deferred, not abandoned.
2. Keep collecting. Every one of the three open questions above — restored vs
   cut, whether the flat "specials" repeat, whether the basket gap has a trend —
   is waiting on days, not on code.
