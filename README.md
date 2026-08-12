# Woolworths vs Coles — Price Analytics

**Is Woolworths or Coles cheaper — and for what?** This project answers the
question with live data: it captures same-day prices from both retailers'
public web APIs, matches identical products across the two chains (same brand,
same pack size), and quantifies the gap at three levels — matched product
pairs, a typical grocery basket, and per-category unit prices.

**Finding (snapshot 2026-07-15):** a near dead-heat. The 50-item basket differs
by under $2 ($209.59 Coles vs $211.41 Woolworths); of 104 identical products,
half are priced *exactly* the same, with Coles edging the rest 30–22. The real
money is in the outliers — identical laundry and coffee products differ by
$9–15 on the day depending on whose specials cycle they sit in.

## Architecture

```
seeds/basket.csv ──► ingest/fetch_prices.py ──► data/raw/prices_{date}.csv
     (50 terms)        Woolworths search API           (normalized raw grain)
                       Coles _next/data API                    │
                                                               ▼
dashboard/index.html ◄── dashboard/build_dashboard.py ◄── DuckDB warehouse
 (self-contained,                                        stg_prices
  zero dependencies)                                     int_matched_products  ◄── matching/match_products.py
                                                         mart_pair_comparison      (rapidfuzz entity resolution)
                                                         mart_basket
                                                         mart_category_unit_price
                                                         mart_specials
```

- **Ingestion** hits the same JSON endpoints the retailers' own frontends use
  (no HTML scraping, no auth). The Coles Next.js `buildId` is re-scraped every
  run because it changes on deploy. Polite pacing, retries with backoff, and a
  run only fails if a retailer returns nothing at all.
- **Warehouse** is a local DuckDB file built from immutable raw CSVs. Staging
  canonicalizes pack sizes (`2L` / `12x375mL` / `12 pack` → grams/ml/each) and
  normalizes both retailers' unit prices to $/100g/·100ml. Every model's grain
  is asserted on every run.
- **Matching** is the hard part: candidates are generated within the same
  search term, then accepted by tier — national brands need equal brand, pack
  size within 2 %, and fuzzy name score ≥ 80; home brands are matched to each
  other separately (they're substitutes, not identical products). Greedy
  one-to-one assignment with deterministic tie-breaking; every accepted pair
  carries its score so the match set is auditable in SQL.
- **Dashboard** is one static HTML file — inline SVG charts, embedded data,
  light/dark theming, tooltips, and a table view per chart. No CDN, no
  framework, no build step.

## Run it

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python run_pipeline.py            # live fetch (~2 min) + build
.venv\Scripts\python run_pipeline.py --skip-fetch   # rebuild from stored raw
start dashboard\index.html
```

Each run appends a dated snapshot; re-running the same day overwrites that
day's raw file only, so the design supports price tracking over time.

## Honest limitations

- Online national pricing — in-store and state pricing can differ.
- Scope is a fixed 50-term everyday basket, not a whole-of-store price index.
- The retailers flag "specials" differently, so the specials share is
  indicative, not a like-for-like comparison.
- One snapshot is one day; supermarket pricing swings weekly with specials
  cycles, which is exactly why the biggest-gap items are special-driven.

## Stack

Python · requests · DuckDB · rapidfuzz · vanilla SVG/JS. No cloud, no keys,
$0 to run.
