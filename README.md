# Woolworths vs Coles — Price Analytics

**Is Woolworths or Coles cheaper — and for what?** This project answers the
question with live data: it captures prices from both retailers' public web APIs
every day, matches identical products across the two chains (same brand, same
pack size), and quantifies the gap at four levels — matched product pairs, a
typical grocery basket, per-category unit prices, and now **how those prices
move over time**.

The daily collection is the asset. A price snapshot cannot be backfilled: every
day the collector does not run is a day of history that can never be recovered.
That is why the repo tracks `data/raw/` and why the warehouse does not.

**Status: complete.** Collection ran from 2026-07-15 to 2026-08-23 and the study
is closed at **10 complete days**. An 11th day, 2026-08-22, was collected and is
deliberately excluded: see `docs/data_quality.md`.

**Finding (2026-08-23, from 10 complete days):** still close on the day. The
50-item basket differs by $13.92 ($200.85 Coles vs $214.77 Woolworths), Coles
takes it on 9 of the 10 days, and of 128 identical products **43% are priced
exactly the same**, with Coles and Woolworths splitting the rest 37–36.

**The finding worth the build:** the average hides everything. Split the same
pairs by aisle and parity runs from **62.5% in pantry to 7.1% in household**,
while the mean household gap is six times pantry's ($8.62 vs $1.36). The two
chains compete hard where shoppers can price from memory and barely at all
where they cannot.

**Findings only the history can produce:**

- A "Special" badge is not the same thing as a lower price. Of 203 promotion
  episodes, 121 began on a day this project had already priced the product.
  **17 of those 121 were not price cuts** — 6 unchanged and 11 *up*, including
  four Schweppes mineral waters moving $3.00 → $3.30 while flagged on special.
  All 17 were at Coles.
- **39 of the 44 promotions that ended went straight back to the price they
  started at.** The median one was 41% off and ran 7 days. Nine in ten specials
  are a promotional cycle, not a price change.
- Reference pricing checks out. All **100** advertised "was" prices that could
  be tested against an earlier observation of our own matched it. This is not
  fake was-prices; it is the badge and the shelf price being managed apart.

## Architecture

```
seeds/basket.csv ──► ingest/fetch_prices.py ──► data/raw/prices_{date}.csv
     (50 terms)        Woolworths search API        (immutable, one per day,
                       Coles _next/data API          the thing that accumulates)
                                                              │
                                                              ▼
                                              ingest/load_raw.py ──► raw_prices
                                                              │      (dbt source:
                                                              │       tested + freshness)
                                                              ▼
                                                    ┌─ dbt ──────────────────┐
                                                    │  stg_prices            │
                                                    │  int_product_prices_   │
                                                    │      daily             │
                                                    │  int_day_coverage      │
                                                    └────────┬───────────────┘
                                                             │
                              ┌──────────────────────────────┼──────────────────┐
                              ▼                              ▼                  ▼
                    snap_product_prices        matching/match_products.py   (marts read
                    (SCD2, dbt snapshot,       (rapidfuzz entity            staging directly)
                     replayed day by day)       resolution) ──► matched_pairs
                              │                              │
                              └──────────────┬───────────────┘
                                             ▼
                                    ┌─ dbt marts ────────────────┐
                                    │  mart_pair_comparison      │
                                    │  mart_basket               │
                                    │  mart_category_unit_price  │
                                    │  mart_specials             │
                                    │  mart_price_history  (incremental)
                                    │  mart_special_behaviour    │
                                    └────────────┬───────────────┘
                                                 ▼
                            dashboard/build_dashboard.py ──► dashboard/index.html
                                                              (self-contained, zero deps)
```

- **Ingestion** hits the same JSON endpoints the retailers' own frontends use
  (no HTML scraping, no auth). The Coles Next.js `buildId` is re-scraped every
  run because it changes on deploy, and re-resolved mid-run if Coles starts
  answering empty. Polite pacing, retries with backoff, and a run aborts without
  writing unless **both** retailers answered at least 80% of the basket lines.
- **The warehouse is a dbt project** (`transform/dbt/`) with grain tests on every
  model, a source freshness check that goes loud when the collector stalls, and
  two targets — DuckDB by default, Snowflake behind an env var.
- **Price history is modelled, not just stored.** `snap_product_prices` is an
  SCD2 dbt snapshot (`strategy=check`) holding **3,254 price versions across
  2,035 products**, of which 1,219 have since been superseded. Historical days are
  replayed into it one at a time so validity windows carry the day the price
  actually changed, not the afternoon of the build.
- **`mart_price_history` is incremental** on `snapshot_date`: a day's run touches
  a day's rows. `scripts/verify_incremental.py` proves that appending gives the
  same answer as a full rebuild, by deleting the last two days and replaying them.
- **Matching** is the hard part and is unchanged from v1: candidates are
  generated within the same search term, then accepted by tier — national brands
  need equal brand, pack size within 2%, and fuzzy name score ≥ 80; home brands
  are matched to each other separately (they're substitutes, not identical
  products). Greedy one-to-one assignment with deterministic tie-breaking; every
  accepted pair carries its score so the match set is auditable in SQL.
- **Dashboard** is one static HTML file — inline SVG charts, embedded data,
  light/dark theming, tooltips, and a table view per chart. No CDN, no
  framework, no build step.

## Gaps are gaps

The single design rule that everything downstream obeys: **a day nobody
collected is never filled in.**

- A product missing from a day's search results does not close its SCD2 record.
  It has not been discontinued and its price has not changed — nobody looked,
  and a search endpoint is a ranking API, not an inventory feed.
- `mart_price_history` leaves that day NULL and flags `is_gap_day`, rather than
  carrying the last price forward. A dbt test asserts the two agree, so the rule
  is enforced rather than merely intended.
- The dashboard shades intervals with no collection and draws the line across
  them dashed, so you can see which movement was observed and which was inferred.
- A day where a retailer answered only part of the basket is treated the same
  way: `int_day_coverage` flags it and the basket and pair marts skip it, rather
  than averaging a half-observed morning in as though it were a real one. The
  raw CSV is never edited. See `docs/data_quality.md` for the day this rule was
  written for.

Inventing continuity is how a price series starts lying. The final series
covers **10 complete days across 40 calendar days**, and that denominator is
printed next to every history figure on the page.

## Run it

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python run_pipeline.py                # live fetch (~2 min) + build
.venv\Scripts\python run_pipeline.py --skip-fetch   # rebuild from stored raw
start dashboard\index.html
```

Other entry points:

```powershell
.venv\Scripts\python run_pipeline.py --full-refresh      # rebuild incremental marts from scratch
.venv\Scripts\python scripts\verify_incremental.py       # incremental == full refresh
.venv\Scripts\python scripts\check_snowflake_sql.py      # Snowflake portability gate
.venv\Scripts\python scripts\reconcile_v1.py <baseline>  # compare marts to a v1 baseline
cd transform\dbt; dbt build                              # dbt on its own, no Python wrapper
```

`run_pipeline.py` is a thin orchestrator, not a framework: fetch → load → stage →
snapshot replay → match → `dbt build` → dashboard. Two steps cannot be SQL (the
CSV load has to work on either warehouse, and fuzzy matching is rapidfuzz's job),
so dbt runs either side of the matcher.

## Two warehouses, one project

The target is one environment variable, shared by dbt and by the Python that
loads and reads the warehouse:

```powershell
.venv\Scripts\python run_pipeline.py --skip-fetch --target snowflake
```

**Everything published by this project was built on DuckDB.** The Snowflake path
is written and statically checked but has never been run against a live account —
`docs/snowflake.md` has the verified/unverified breakdown, the complete list of
engine divergences, and the setup steps for when a trial gets created. DuckDB is
the default and the only target that has to work: `requirements.txt` does not
mention Snowflake, and nothing in the daily collection touches it.

Writing the second target was worth it even unrun. It forced the engine
differences into one dispatched macro instead of leaving them scattered, and
`scripts/check_snowflake_sql.py` caught a real bug on the way — `TRY_CAST` over a
numeric column, which DuckDB accepts and Snowflake rejects.

## Honest limitations

- Online national pricing — in-store and state pricing can differ.
- Scope is a fixed 50-term everyday basket, not a whole-of-store price index.
- **10 complete days is a short series**, with a four-week hole between
  2026-07-15 and 2026-08-12 where the collection was not yet automated. Of 203
  promotion episodes, only 44 have observed days on *both* sides of the
  promotion. Those 44 are the whole basis of the restored-versus-genuine-cut
  finding; the other 159 are unresolved and stay that way.
- **The parity-by-aisle split was found in the data, not predicted before it.**
  That makes it a hypothesis this study generated rather than one it tested.
  Testing it properly means assigning every line to a bucket up front,
  publishing the assignment, and only then collecting.
- The comparison baseline for a special is the last day this project priced the
  product — a median of 3 days earlier, not necessarily the previous day.
- The retailers flag "specials" differently, so the same-day specials share is
  indicative, not like-for-like.
- Daily collection is the resolution limit: a price that drops and recovers
  between two mornings is invisible to the SCD2 snapshot by construction.

## Stack

Python · dbt (dbt-core, dbt-duckdb, dbt-snowflake) · DuckDB · Snowflake ·
rapidfuzz · vanilla SVG/JS. No cloud, no keys, $0 to run.

## Docs

- [PRD.md](PRD.md) — v1: same-day comparison, entity resolution
- [PRD-v2.md](PRD-v2.md) — v2: price history, SCD2, incremental, second warehouse
- [docs/snowflake.md](docs/snowflake.md) — what is and is not verified on Snowflake
- [docs/reconciliation.md](docs/reconciliation.md) — proof the dbt port moved no published number
