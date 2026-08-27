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

## v3 — a year of history, and the store-brand split

The 10-day study above has a limitation it states itself: the aisle finding was
*found in the data, not predicted before it*. v3 addresses that in two arms, and
[PRD-v3.md](PRD-v3.md) is the design. **Arm A is built; Arm B is not started.**

**Arm A backfills three years this project could never have collected.**
[Hot Prices AU](https://hotprices.org/) has scraped both chains daily since
September 2023 and publishes the result as two gzipped JSON files. It keys
products by the retailers' own product ids — the same ids collected here — so
v2's matched pairs extend backwards on an equality join, with **no re-matching
at all**.

**The backfill is verified, not trusted.** For every day this project priced a
product itself, the backfill is asked what price it implies for that day and the
two are compared:

```
comparable observations : 20,227
exact agreement         : 20,222  =  99.98%
disagreements           :      5   (all Woolworths, all same-week price moves)
```

Two independently built scrapers, 20,227 shared observations, five
disagreements. `docs/reconciliation.md` proved the dbt port moved none of this
project's *own* numbers; this checks them against a stranger's, which is the only
kind of check that catches a mistake both models make for the same reason. The
pipeline gates on it at 99% and refuses to build Arm A below that.

### Store brand and name brand are not the same question

Every Arm A measure is split by brand tier, and the split is the point. A **name
brand** is the same physical good on both shelves, so a gap is a pricing decision
and parity is deliberate matching. A **store brand** is a substitute from a
different supplier, so a gap is partly a product difference and parity is not
matching at all. Pooling them makes every measure ambiguous — and leaves the
aisle finding above unfalsifiable, because private-label share varies by aisle
and a pooled parity rate could move from pantry to household on mix alone.

One year, 2025-08-27 to 2026-08-27. Both pair sets agree on every direction
despite being built from different brand mechanisms and different blocking:

| | name brand | store brand |
|---|---|---|
| Pairs | 1,361 | 162 |
| Price-change events | 47,821 | 1,687 |
| **Share of days a price moved** | **9.6%** | **2.9%** |
| Parity rate | 50.4% | 60.8% |
| 90th-percentile gap | 51.4% | 20.7% |
| Days more than 5% apart | 47.9% | 32.0% |
| Median closed-episode depth | 30.2% | 14.3% |

**Store brands are repriced about three and a half times less often than name
brands**, sit at parity more often, and when they do diverge the gap is half as
deep. That is a range priced to hold an everyday position, against one priced as
a promotional vehicle.

Tested and discharged: store-brand parity could have been nothing but round
price points colliding, since the two chains' own ranges are different products.
It is not — parity days are no likelier to sit on a whole dollar than non-parity
days (34.4% against 33.3%).

**The median closed gap episode is 7 days in all four cells** — name brand and
store brand, both pair sets. The promotional week is the unit of Australian
grocery pricing, and a 10-day study cannot see it.

### The registered test, scored

Predictions were fixed at commit `51cb891` before any of these numbers existed
(full scorecard in [docs/results_bucket_test.md](docs/results_bucket_test.md)).
**Seven of twelve landed inside the registered range** — packaged staples 5 of
6, fresh produce 2 of 6.

The claim that mattered was P3, a deliberate robustness test of the store-brand
finding above: does it survive holding aisle constant, or was it an aisle-mix
artefact? The registration committed to retracting it publicly if the latter.

**It survives — and is more specific than first published:**

| Share of days a price moved | Name brand | Store brand | Ratio |
|---|---|---|---|
| Packaged staples | 8.9% | 1.1% | **8.1x** |
| Fresh produce | 10.2% | 7.4% | **1.4x** |

The pooled 3.5x is an average of two regimes. **Store brands holding still is a
packaged-goods phenomenon and nearly vanishes in fresh produce** — crop and
weather move a price whoever's name is on it, while private-label pricing
discipline is something you can only exercise over a manufactured good.

**The prediction that failed hardest is the most interesting result.** Produce
was registered to show low parity but *high* correlation — same crop, same
weather, moving together without matching. Median per-pair correlation between
the two chains:

| | Daily | Monthly means | Registered |
|---|---|---|---|
| Produce x name brand | **-0.08** | 0.28 | 0.6-0.85 |
| Staple x name brand | **-0.01** | 0.24 | 0.8-0.95 |
| Staple x store brand | 0.39 | **0.72** | — |

Day to day, national-brand prices at the two chains are **uncorrelated** — not
weakly, zero. Monthly smoothing recovers ~0.25, so shared movement exists but is
swamped at daily frequency, and the rest of the results say why: national brands
are the promotional vehicles and the two chains run their cycles **out of
phase**, so prices take turns rather than moving together. Store brands, lightly
promoted, track each other far more closely (0.72) because what remains is
shared cost.

So the axis separating correlated from uncorrelated prices is not
fresh-versus-packaged. It is **promoted versus not** — which is to say, name
brand versus store brand.

### Two pair sets, one grading the other

`backfill_pairs` holds both, and `pair_set` is part of the grain of every model
downstream so they can never be pooled by accident.

| | `v2_extended` | `wide` |
|---|---|---|
| Pairs | 154 | 1,523 |
| Blocking | v2's basket search term | canonical unit and quantity |
| Brand tier from | the retailer's brand field | the leading tokens of the name |
| Quality | v2's accepted pairs, unchanged | **88% agreement with v2 where they overlap** |

The `wide` set is the weaker work and says so on every row. Its blocking is a
size bucket rather than a human-authored search term, and its brand is a name
prefix rather than a field, so it needs a rule v2 does not: `token_set_ratio`
scores 100 when one name's tokens are a subset of the other's, which without a
search-term block accepts *Macro Organic Baby Food Mixed Fruit Spinach Smoothie*
against *Coles Baby Spinach*. Requiring `token_sort_ratio` too removes those.

It does not remove variant confusion — *Arnott's Shapes Korean BBQ* against
*Arnott's Shapes Garlic Bread* scores high on every name-similarity measure
there is. So the honest quality number for that set is not a threshold but its
measured agreement with v2's pairs, printed on every run.

### What Arm A cannot do, and why the collector keeps running

The dumps carry `price` and nothing else — no `was_price`, no specials flag. So
every question about *advertising* rather than *price* is invisible to it:
promotion frequency, promotion depth against an advertised was-price, reference
integrity, and the badge-vs-price divergence in the findings above. Those stay
with this project's own collection, which is also what the verification gate
checks the backfill against.

Arm A also **cannot be pre-registered** — the data already exists. It is
observational and labelled as such: predictions fixed before measurement on
pre-existing data is a blind analysis, not a pre-registration. Arm B is the
true one.

The assignment is registered (`51cb891`, [docs/preregistration.md](docs/preregistration.md))
and nothing bucket-level has been measured yet. Checking pattern coverage before
registering found something that changed the design: **the 40 price-opaque items
match three pairs in the entire backfill.** Not because the matcher rejects them
— a cross-retailer pair needs the product at both chains, and Hot Prices barely
stocks the tail and stocks it lopsidedly (flea treatment 19 Woolworths and 0
Coles; greeting cards 0 and 6; plungers and clothes pegs absent from both).

So **Arm A cannot test the visible/opaque split at all.** It tests produce
against packaged staples crossed with brand tier. The visibility axis belongs to
Arm B, the only arm that can point a collector at the tail on purpose — which
needs `seeds/basket.csv` expanded past its 50 head lines, and that has not been
done.

Worth saying plainly, because it narrows a claim already published above: v2's
"household" aisle is toilet paper, paper towel, dishwashing liquid and laundry
liquid — mid-tail supermarket lines. **No version of this project has yet
measured the true long tail**, so the 62.5%-to-7.1% parity spread is a spread
across the head of the range.

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

### v3 Arm A — the backfill, built by `--backfill`

```
hotprices.org ──► ingest/fetch_hotprices.py ──► data/external/hotprices_{store}_{date}.json.gz
 (2 gz files)         never overwritten             (a dated observation of
                                                     somebody else's series)
                                                              │
                                                              ▼
                                            ingest/load_hotprices.py ──► raw_hotprices
                                            (unnest priceHistory,        783,141 change
                                             quarantine ambiguous)       points, 3 years
                                                              │
                    ┌─────────────────────────────────────────┤
                    ▼                                         ▼
    scripts/verify_backfill.py                      matching/extend_pairs.py    (FR-3)
    THE GATE: 99.98% vs our own                     matching/match_backfill.py  (FR-4)
    collected days. Below 99%,                      matching/brands.py
    the arm does not build.                          store vs name brand, once
                                                              │
                                                              ▼
                                                       backfill_pairs
                                                    (v2_extended + wide,
                                                     pair_set on the grain)
                                                              │
                                                              ▼
                                              ┌─ dbt ─────────────────────┐
                                              │  stg_hotprices            │
                                              │  int_backfill_pair_daily  │
                                              │  mart_gap_episodes        │
                                              │  mart_brand_tier_gaps     │
                                              └───────────────────────────┘
```

- **The gate runs before anything is built.** Verification is not a report
  printed after the figures land in the warehouse — it is the step that decides
  whether they land at all. If a future dump stops agreeing with our own
  collection, the run stops with nothing published.
- **Change points, not days.** `priceHistory` records only the dates a price
  moved, so three years of 44,648 products is 783,141 rows rather than 44 M.
  `stg_hotprices` turns them into validity windows — the same SCD2 shape
  `snap_product_prices` is replayed into, arriving pre-built.
- **The last window ends at the fetch date, and that is observed, not assumed.**
  The dump publishes a current price beside the history and it equals the final
  change point for all 44,659 products, so the fetch itself witnesses that the
  price still stood. Nothing is carried past it, and nothing is invented before
  a product's first change point.
- **Brand tier is decided once**, in `matching/brands.py`, and rides on the grain
  of every model downstream so no figure can pool store and name brands by
  accident.

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
.venv\Scripts\python run_pipeline.py --backfill          # + v3 Arm A: fetch, verify and model 3 yrs of Hot Prices history
.venv\Scripts\python run_pipeline.py --full-refresh      # rebuild incremental marts from scratch
.venv\Scripts\python scripts\verify_incremental.py       # incremental == full refresh
.venv\Scripts\python scripts\verify_backfill.py          # backfill vs our own collected days
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
- **The v3 backfill is somebody else's collection, on a calendar we cannot see.**
  If Hot Prices missed a week, a change dated the following Monday happened some
  time in the preceding seven days and nothing in the file says so. Their gaps
  become our uncertainty; the 99.98% agreement bounds the error but does not
  remove it, and no per-item latency figure is reported from Arm A because of it.
- **The v3 backfill carries no was-price and no specials flag**, so nothing about
  advertising can be measured from it — only price.
- **Arm A is observational, not pre-registered.** The history already existed
  when the buckets were being chosen, which is exactly the circularity PRD-v3
  exists to avoid, so Arm B is a separate arm and its buckets are not yet
  committed.

## Stack

Python · dbt (dbt-core, dbt-duckdb, dbt-snowflake) · DuckDB · Snowflake ·
rapidfuzz · vanilla SVG/JS. No cloud, no keys, $0 to run.

**Data sources.** Woolworths and Coles public web APIs (this project's own daily
collection), plus [Hot Prices AU](https://hotprices.org/) for the v3 backfill —
an open-source price tracker ([Javex/hotprices-au](https://github.com/Javex/hotprices-au),
a fork of [badlogic/heissepreise](https://github.com/badlogic/heissepreise))
that has scraped both chains daily since September 2023 and publishes the
result. The hotprices-au code is MIT. The data carries no stated licence, so
permission was asked for directly and **granted by the author by email on
2026-08-27 for personal-project use**. That is the basis this repo relies on —
not an open data licence — and it is the scope any reuse here stays inside.

## Docs

- [PRD.md](PRD.md) — v1: same-day comparison, entity resolution
- [PRD-v2.md](PRD-v2.md) — v2: price history, SCD2, incremental, second warehouse
- [PRD-v3.md](PRD-v3.md) — v3: backfilled history from a verified external source, and a pre-registered bucket test
- [docs/preregistration.md](docs/preregistration.md) — the bucket assignment and the predictions, registered 51cb891 before any bucket-level figure existed
- [docs/results_bucket_test.md](docs/results_bucket_test.md) — the registered test, scored: 7 of 12 predictions inside range, and the one that failed hardest
- [docs/snowflake.md](docs/snowflake.md) — what is and is not verified on Snowflake
- [docs/reconciliation.md](docs/reconciliation.md) — proof the dbt port moved no published number
