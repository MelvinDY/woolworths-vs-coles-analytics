# PRD — Woolworths vs Coles Price Analytics

**Owner:** Melvin Darial Yogiana
**Status:** Draft v1 · July 2026
**Stack:** Python · requests · DuckDB · rapidfuzz · self-contained HTML dashboard

---

## 1. Background & positioning

The portfolio already contains a *Woolworths price analytics* dbt case study — a single-retailer view. What it cannot answer is the question every Australian household actually asks: **"Is Woolworths or Coles cheaper — and for what?"**

This project answers that head-to-head. It ingests **live prices** from both retailers' public web APIs on the same day, matches identical products across the two chains (same brand, same pack size), and quantifies the price gap at three levels: matched product pairs, a typical grocery basket, and per-category unit prices.

The portfolio signal is different from the earlier dbt projects: this one demonstrates **multi-source ingestion of adversarial real-world data** (two different undocumented APIs, two different schemas), **entity resolution** (cross-retailer product matching — the genuinely hard part), and a **zero-dependency presentation layer**.

## 2. Goals

| # | Goal | Measure of success |
|---|------|--------------------|
| G1 | Live same-day price capture from both retailers | One pipeline run fetches both chains for a defined basket of search terms with no manual steps |
| G2 | Credible cross-retailer product matching | ≥ 60 matched identical-product pairs (brand + size + fuzzy name), with match rules documented and auditable in the warehouse |
| G3 | A defensible "who is cheaper" answer | Headline stats: matched-pair win rate, basket total gap, category unit-price gaps — each traceable to raw rows |
| G4 | Zero-cost, zero-infra | Local DuckDB file, no cloud, no API keys, dashboard is one static HTML file |
| G5 | Re-runnable over time | Each run appends a dated snapshot; re-running the same day is idempotent (overwrites that day's snapshot only) |

## 3. Non-goals

- **No historical price tracking service** — the design supports repeated snapshots, but v1 ships on one snapshot; no scheduler.
- No coverage of ALDI/IGA (no comparable public endpoints).
- No dbt — the portfolio already shows dbt twice; plain SQL models run by an orchestrator script are deliberate here.
- No web scraping of rendered HTML — only the JSON endpoints the retailers' own frontends call.
- No claims about *all* prices — the comparison is scoped to the defined basket of common grocery items.

## 4. Users

| User | Need |
|------|------|
| Hiring manager / recruiter (primary) | Open dashboard, see the headline finding in 30 seconds, sense that the data is real and live |
| Technical interviewer | Read the matching logic and SQL models; probe how false-positive matches are prevented |
| Melvin (operator) | `python run_pipeline.py` end-to-end; re-run any day for a fresh snapshot |

## 5. Data sources

| Source | Endpoint | Notes |
|--------|----------|-------|
| Woolworths | `GET /apis/ui/Search/products?searchTerm=…` | Public JSON, no auth. Fields: `Stockcode`, `DisplayName`, `Brand`, `PackageSize`, `Price`, `WasPrice`, `CupPrice`, `CupMeasure`, `IsOnSpecial` |
| Coles | `GET /_next/data/{buildId}/en/search/products.json?q=…` | `buildId` scraped from homepage `__NEXT_DATA__` each run (changes on deploy). Fields: `id`, `name`, `brand`, `size`, `pricing.now`, `pricing.was`, `pricing.unit.*`, `pricing.onlineSpecial` |
| Basket seed | `seeds/basket.csv` | ~45 curated search terms with category labels (dairy, meat, produce, pantry, drinks, snacks, frozen, household, personal care) — the shared query set that makes the two retailers comparable |

Grain: **one row per (retailer, product_id, snapshot_date)** in the raw layer. A product can appear under multiple search terms in one run; raw keeps every hit, staging dedupes to the product grain and keeps the first category assignment.

## 6. Functional requirements

### FR-1 Ingestion (`ingest/fetch_prices.py`)
- Iterate the basket seed; for each term query both retailers with a shared polite session (browser UA, ≥ 0.6 s delay between requests, 3 retries with backoff).
- Coles `buildId` resolved once per run from the homepage; failure of a single term logs a warning and continues — a run only fails if a retailer returns nothing at all.
- Normalize both payloads to one raw schema: `retailer, product_id, name, brand, size_raw, price, was_price, unit_price, unit_measure, is_on_special, search_term, category, snapshot_date, fetched_at`.
- Write `data/raw/prices_{snapshot_date}.csv`; re-running the same day overwrites that file (idempotent per day).

### FR-2 Warehouse & SQL models (DuckDB, `transform/sql/`)
- `stg_prices` — load all raw CSVs, cast types, dedupe to `(retailer, product_id, snapshot_date)`, parse pack size to canonical grams/ml/each, filter rows with no usable price.
- `int_matched_products` — registered from the Python matcher (FR-3), one row per matched pair per snapshot.
- Marts:
  - `mart_pair_comparison` — matched pairs with both prices, absolute/percent gap, winner flag.
  - `mart_basket` — cheapest item per (category, search term) per retailer summed into a basket total per retailer.
  - `mart_category_unit_price` — median unit price per category per retailer, computed only over unit-comparable rows.
  - `mart_specials` — share of lines on special and median discount depth per retailer.
- Every mart is a table in `data/warehouse.duckdb`; the pipeline asserts grain uniqueness on each model and fails loudly on violation.

### FR-3 Product matching (`matching/match_products.py`)
The core entity-resolution step. Candidate pairs are generated **within the same search term** only, then accepted by tier:
- **Tier 1 — national brands:** normalized brand equal, canonical size within 2 %, `token_set_ratio(name) ≥ 80`.
- **Tier 2 — own brands:** Woolworths/Coles home-brand products (brand in a small alias list) matched to each other on size within 2 % and name score ≥ 75, flagged `match_type='own_brand'` and reported separately — own-brand items are substitutes, not identical products.
- One-to-one enforcement: greedy best-score assignment; a product participates in at most one pair.
- Output includes the match score and tier so every pair is auditable.

### FR-4 Dashboard (`dashboard/index.html`, generated by `dashboard/build_dashboard.py`)
- Single static HTML file, no external requests (charts inline, data embedded as JSON).
- Sections, each led by a written insight sentence: headline verdict (matched-pair win rate + basket gap), pair-level gap distribution, category unit-price comparison, biggest price gaps table, specials behaviour.
- Notes panel: snapshot date, basket scope, matching rules — the honesty box that makes the headline defensible.

### FR-5 Orchestration & repo
- `run_pipeline.py` — fetch → load/transform → match → marts → dashboard, with `--skip-fetch` to rebuild from existing raw data.
- README: 30-second pitch, architecture diagram, how matching works, honest limitations, setup instructions.
- `.gitignore` excludes `data/` and the venv; raw snapshots are artifacts, not source.

## 7. Milestones

| Phase | Deliverable |
|-------|-------------|
| 1 | Endpoint spike: confirm both APIs parse (done — see §5) |
| 2 | Basket seed + ingestion writing normalized raw CSV |
| 3 | DuckDB staging + size canonicalization |
| 4 | Matcher with tiered rules + match audit output |
| 5 | Marts + grain assertions |
| 6 | Dashboard + README |

## 8. Risks

| Risk | Mitigation |
|------|-----------|
| Either retailer hardens its endpoint (bot protection) | Polite pacing + browser headers; pipeline degrades to `--skip-fetch` on stored raw data; scope is a portfolio snapshot, not a service |
| Coles `buildId` changes | Re-scraped every run by design |
| False-positive matches poison the headline | Size tolerance 2 %, brand equality required for tier 1, one-to-one assignment, every pair carries its score for audit |
| Same product, different pack sizes across chains | Unit-price marts capture what pair-matching can't; basket mart compares cheapest-per-term rather than pairs |
| Search results skew to sponsored/irrelevant items | Dedupe by product id; basket mart takes cheapest relevant line; category medians are robust to outliers |
