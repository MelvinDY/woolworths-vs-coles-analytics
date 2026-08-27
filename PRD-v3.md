# PRD v3 — The Grocery Panel: backfilled history and a pre-registered test

**Owner:** Melvin Darial Yogiana
**Status:** Arm A built · 2026-08-27 — pipeline green end to end on DuckDB, 38/38 nodes. Arm B (pre-registration) not started. See [§12 Delivery status](#12-delivery-status--2026-08-27).
**Extends:** [PRD.md](PRD.md) (v1 — same-day snapshot) · [PRD-v2.md](PRD-v2.md) (v2 — price history, SCD2, incremental)
**Stack added:** an external backfill source · pre-registration as a build artefact

---

## 1. Background & positioning

v2 closed with a finding it could not defend. Parity runs from 62.5% in pantry
to 7.1% in household, and the mean household gap is six times pantry's — the two
chains compete hard where shoppers can price from memory and barely at all where
they cannot. v2's own delivery note calls this out: *"It was found in the data
rather than predicted, which makes it a hypothesis this project generated rather
than one it tested."*

The README repeats it in the limitations, and names the remedy: assign every
line to a bucket up front, publish the assignment, and only then collect.

The obvious version of v3 was therefore "collect for another 100 days." That
design is sound and slow, and it has a second problem: 100 days is about 14
weeks, promotional cycles run 4 to 6 weeks, so it sees two or three per item —
enough to say a line is cyclical, never enough to state its period.

**There is a faster and much larger answer, and it already exists.**
[Hot Prices AU](https://hotprices.org/) — an open-source fork of
[heissepreise](https://github.com/badlogic/heissepreise), source at
[Javex/hotprices-au](https://github.com/Javex/hotprices-au) — has been scraping
Coles and Woolworths daily since **September 2023** and publishes the whole
thing as two gzipped JSON files. 44,659 products, 783,809 price points, ~3 years.

That does not replace this project's collection. It does something better: it
splits v3 into two arms that answer different questions and check each other.

## 2. The two arms

|  | Arm A — Backfill | Arm B — Pre-registered test |
|---|---|---|
| Source | Hot Prices AU public dumps | This repo's own daily collector |
| Window | 2023-09-26 → today (~3 years) | Forward from the day buckets are committed |
| Scale | 1,568 candidate pairs · 80,292 change events in 12 months | ~80 items, as v2 collects |
| Pre-registered? | **No — the data already exists.** Observational | **Yes.** Buckets committed to git before collection |
| Carries `was_price` / `is_on_special`? | **No.** Price only | **Yes** |
| Answers | Promotion vs position, cycle length, follow latency, persistence, correlation | Reference integrity, badge-vs-price divergence, the bucket hypothesis as a genuine test |

Neither arm alone is the study. Arm A has the scale and the years but cannot be
pre-registered and carries no promotion metadata. Arm B can be pre-registered
and sees the badge, but is small and slow. **Reporting them as one merged number
would be the central dishonesty available in this project, and §6 forbids it.**

## 3. Goals

| # | Goal | Measure of success |
|---|------|--------------------|
| G1 | The bucket hypothesis becomes a test, not a story | Bucket assignment and numeric predictions committed to git **before** any bucket-level result is computed; the commit hash is published beside the results |
| G2 | Backfill is verified, not trusted | Hot Prices agrees with this repo's independently collected days at a rate published as a number, on the same reconciliation pattern as [docs/reconciliation.md](docs/reconciliation.md) |
| G3 | Promotion vs position, answered at scale | Every gap over 5% classified as closing or persistent, with a median persistence per bucket, over ≥12 months |
| G4 | The v2 pairs get their history back | v2's matched pairs extended backwards with **no re-matching** — the join is on retailer product id |
| G5 | The two arms stay separate | No published figure mixes them. Every number is labelled with its arm and its window |

## 4. Non-goals

- **No elasticity.** Public prices carry no quantities. Percentage change in
  quantity over percentage change in price cannot be computed from any of this,
  and the word does not appear in the results. What the bucket split measures is
  exposure to competitive price pressure, which is a different thing.
- **No claim that Arm A is pre-registered.** It cannot be. Said plainly, once,
  in the results.
- No re-scraping of Hot Prices' own history. One file per retailer, cached.
- No abandonment of the daily collector. Arm B depends on it, and it is the only
  source of `was_price` and `is_on_special`.
- No expansion beyond Woolworths and Coles. Hot Prices covers the same two.

## 5. Data & grain

### 5.1 The backfill source

Two files, refetched on a cadence, never reconstructed:

```
https://hotprices.org/data/latest-canonical.coles.compressed.json.gz    2.2 MB
https://hotprices.org/data/latest-canonical.woolies.compressed.json.gz  1.6 MB
```

Per product: `id`, `name`, `description`, `price`, `priceHistory[]`,
`isWeighted`, `unit`, `quantity`, `store`, `category`.

**The grain is a change point, not a day.** `priceHistory` is
`[{date, price}, ...]` holding only the dates the price *changed*. A product with
9 entries over 3 years is 9 rows, not 1,000. This is the same shape as
`snap_product_prices` — v2 already models prices as SCD2 validity windows, so
the backfill lands in an existing pattern rather than a new one.

| Layer | Grain | Notes |
|-------|-------|-------|
| `data/external/hotprices_{store}_{fetched_date}.json.gz` | file | Immutable, as `data/raw/` is. Store the response, derive everything |
| `raw_hotprices` | (store, product_id, change_date) | The `priceHistory` arrays unnested. One row per observed price change |
| `stg_hotprices` | (retailer, product_id, valid_from) | `store` mapped to this repo's `retailer` vocabulary; `valid_to` derived as the next change date |
| `int_backfill_daily` | (retailer, product_id, date) | Change points expanded to a daily series **within observed bounds only** — never before the first change point, never after the last |
| `mart_gap_episodes` | (pair_id, episode_id) | One row per continuous run where the absolute gap exceeds 5%: start, end, depth, and whether it closed |

### 5.2 The rule v2 wrote, applied to somebody else's data

v2's spine is *a day nobody collected is never filled in*. Arm A inherits a
collection calendar it cannot see: if Hot Prices missed a week, a change dated
the following Monday actually happened some time in the preceding seven days,
and nothing in the file says so.

This is the single largest methodological risk in v3 and §8 treats it as such.
Three consequences, binding:

1. `int_backfill_daily` forward-fills **between two observed change points**,
   because that is what a change point means, and never **past the last one** or
   **before the first**. Outside the observed window there is no data.
2. **Follow latency inherits their cadence.** A measured 2-day follow is 2 days
   plus or minus their gap. Latency is reported from Arm A only as a bucket-level
   median with that caveat attached, never as a per-item figure.
3. A first change point is a *first observation*, not a price birth. Any measure
   anchored on "when this price started" is restricted to items whose history
   begins before the analysis window opens.

## 6. Functional requirements

### FR-1 Fetch and land (`ingest/fetch_hotprices.py`)
Download both files, write to `data/external/` under the fetch date, load to
`raw_hotprices`. Never overwrites a stored file. Attribution and source URL
recorded in the row and in the README.

### FR-2 Verification gate (`scripts/verify_backfill.py`)
The build's honesty check, and it must run before any figure is published.
For every (retailer, product_id, snapshot_date) this repo observed itself, take
Hot Prices' implied price — the last change on or before that date — and compare.
Publishes agreement rate, disagreement count, and the disagreeing rows in full.

**This gate has been run. See §11.** It is a permanent model, not a one-off:
each new collected day adds observations to it.

### FR-3 Pair extension (`matching/extend_pairs.py`)
v2's `matched_pairs` joins to the backfill on `(retailer, product_id)` — the
same id space. **No fuzzy matching, no re-scoring, no new accept rules.** v2's
matcher is this repo's strongest asset and v3 does not touch it. Pairs whose
history is missing on either side are dropped and counted, never approximated.

### FR-4 Wider matching for Arm A (`matching/match_backfill.py`)
To reach beyond v2's pairs, the full dump needs matching, and the dump has **no
`search_term`** — v2's blocking key does not exist here. Substitute: block on
(canonical unit, quantity within 2%), then apply v2's acceptance rules unchanged
(fuzzy `token_set_ratio` >= 80, home brands never matched to national brands).
The dump has **no `brand` field either**; brand must be derived from the leading
name tokens and the derivation published with the match set.

Every pair carries its score and its blocking basis, as v2's do. A pair set built
on a weaker blocking key than v2's is a weaker pair set, and the results say so.

### FR-5 Pre-registration (`seeds/buckets.csv`, committed before results)
One row per item: `product_key`, `bucket` (`price_visible` | `price_opaque`),
`aisle`, `rationale`. Committed in its own commit, touching nothing else, before
any bucket-level result exists. `docs/preregistration.md` holds the predictions
from §7 and the commit hash. Git history is the timestamp, and it is checkable
by anyone who clones the repo.

### FR-6 Dashboard
Two sections, never interleaved, each labelled with its arm, window and
verification rate. Arm A gets the promotion-vs-position chart: two items, both
showing a wide gap on one day, one closing and one not.

## 7. The measures, and which arm can produce them

| Measure | Arm | Prediction if the split is real |
|---|---|---|
| Parity rate — share of days matched to the cent | A | High on price-visible, low on price-opaque |
| Median absolute gap, as a share of mean price | A | Under 2% visible, over 10% opaque |
| Price correlation | A | 0.8–0.95 packaged, 0.6–0.85 produce, 0.1–0.4 opaque |
| Gap persistence — days a 5%+ gap survives | A | 1–4 days staples, 20+ days opaque |
| Follow latency — days to answer a 2%+ move | A (bucket median only) | Days on visible, usually never on opaque |
| Cycle length and depth | A | 4–6 week cycles on packaged grocery, absent in the tail |
| **Promotion frequency — share of days badged** | **B only** | Higher on price-visible |
| **Promotion depth against advertised `was`** | **B only** | Rarer but deeper on price-opaque |
| **Reference integrity — was the `was` price charged?** | **B only** | v2 measured 100/100 passing. **v3 predicts it holds** |
| **Badge-vs-price divergence** | **B only** | v2 found 17 of 121 promotion starts were not cuts. Expect the pattern to persist |

The four Arm-B-only measures are the reason the collector keeps running. Hot
Prices carries `price` and nothing else — no `was_price`, no special flag — so
every question about *advertising* rather than *price* is invisible to it.

**Correction carried forward from the design notes:** an earlier draft predicted
that "a small but non-zero share of `was` prices fail the reference test." v2
tested 100 of them and **all 100 passed**. Predicting a failure the project has
already measured as absent is not a prediction; the row above is corrected to
predict that the pass rate holds.

## 8. Risks

| Risk | Mitigation |
|------|------------|
| **Invisible collection gaps in the backfill** | §5.2's three binding rules. FR-2 bounds the error empirically |
| **Data licence is unstated** | `hotprices-au` is MIT *for the code*; the data carries no stated terms. **Resolved 2026-08-27:** the author was asked directly and granted permission for personal-project use by email. Attribution regardless. The permission is scoped to personal projects, so it covers this repo and the portfolio, and does not make the data openly licensed for anyone else |
| Arm A read as pre-registered | G5 and §4. Labels on every figure; one plain sentence in the results |
| Weaker blocking than v2 (FR-4) | Publish both pair sets. Where they overlap, agreement is measurable — v2's 153 extended pairs are the control |
| Source disappears | Files are stored on fetch (FR-1). A vanished upstream costs future refreshes, not history already on disk |
| Backfill makes the collector look redundant | It is not: four measures in §7 exist only in Arm B, and Arm B is what FR-2 verifies against |
| **I have already seen aggregate structure** | Disclosed in §11. Counts, spans and event totals were inspected during feasibility. **Bucket-level gaps were not**, so G1 remains available — but the disclosure ships with the results |

## 9. Cost

$0. Two files totalling 3.9 MB, fetched on a cadence measured in weeks. The
existing collector's cost is unchanged. No cloud, no keys.

## 10. Definition of done

1. `seeds/buckets.csv` and `docs/preregistration.md` committed before any
   bucket-level result exists, hash published.
2. FR-2 verification rate published in the README and on the dashboard.
3. Promotion vs position answered per bucket over 12 months or more, with n as
   **change events**, never row count.
4. Every published figure labelled with arm, window and pair set.
5. Licence question resolved with the Hot Prices author, or derived figures
   withheld and the reason stated.
6. `python run_pipeline.py` still runs end-to-end on DuckDB with zero edits.

## 11. Feasibility, verified — 2026-08-27

Everything in this section was measured against the live dumps and this repo's
warehouse before the PRD was written. Nothing here is projected.

### The source is real and large

| | Coles | Woolworths |
|---|---|---|
| Products | 21,210 | 23,449 |
| Price points | 335,949 | 447,860 |
| With more than one price point | 16,403 (77%) | 19,160 (82%) |
| With a full year of history or more | 5,275 (25%) | 12,174 (52%) |
| Change events in the last 12 months | 232,249 | 330,588 |
| History spans | 2023-09-26 → 2026-08-27 | 2023-09-26 → 2026-08-27 |

### It is the same id space — the join is exact

Hot Prices keys products by the retailers' own product ids, and so does this
repo. Of this repo's distinct products, **89% of Coles (1,450/1,623) and 85% of
Woolworths (422/495)** are present in the dumps, and the names corroborate
line for line. No fuzzy matching is required to extend v2's work (FR-3).

### The backfill agrees with this project's own collection

FR-2's gate, run over every overlapping observation:

```
comparable observations : 17,307
exact agreement         : 17,303  =  99.98%
disagreements           :      4
no history on/before day:  2,733  (dropped, not approximated)
```

Two independently built collectors, 17,307 shared observations, **four
discrepancies.** This is the strongest external validation in the repo — v2's
reconciliation proved the dbt port moved no number of *its own*; this proves the
numbers agree with somebody else's scraper entirely.

The four are listed here rather than smoothed away, and each is a same-week
price move where the two collectors sat on opposite sides of a change:

| Retailer | Product | Day | This repo | Hot Prices |
|---|---|---|---|---|
| Woolworths | Earth Choice Ultra Concentrate Dishwash | 2026-08-18 | $4.95 | $6.00 |
| Woolworths | Woolworths Gourmet Tomatoes Punnet 1kg | 2026-08-18 | $6.70 | $4.90 |
| Woolworths | Macro Organic Extra Lean Beef Mince | 2026-07-15 | $14.00 | $15.50 |
| Woolworths | Woolworths Tuna In Springwater 95g | 2026-08-21 | $1.00 | $1.10 |

All four are Woolworths, which is worth a second look during the build.

### The study this buys

| | v2, published | Arm A, extended pairs (FR-3) | Arm A, wide match (FR-4) |
|---|---|---|---|
| Pairs | 158 matched, 128 identical | **153** (97% of v2's, zero re-matching) | **1,568** |
| Window | 10 complete days / 40 calendar | back to a median joint start of **2025-11-05**; earliest **2024-03-08** | 12 months or more by construction |
| With a full year both sides | 0 | **64** | 1,568 |
| Change events, last 12mo | — | **3,043** (median 48/pair) | **80,292** |

The 100-day panel in the original design was sized at roughly 400–600 effective
events per bucket. **The 64 fully-extended v2 pairs alone carry 3,043**, and they
are available today, on pairs this repo's own matcher already accepted.

### Disclosure

During this feasibility work the following were observed: product counts, date
spans, event totals, field structure, the four disagreements above, and a sample
of matched pair names. **Bucket-level gap distributions were not computed**, and
must not be until FR-5 is committed. That ordering is what keeps G1 honest, and
this paragraph ships with the results.

### What is left

1. Resolve the data licence with the Hot Prices author (§8). Blocking for
   publication.
2. Commit `seeds/buckets.csv` before anything else in §6 is built.
3. Build FR-1 through FR-4; FR-2 first, since it gates the rest.
4. Keep collecting. Arm B's four measures are still waiting on days.

## 12. Delivery status — 2026-08-27

Arm A is built and green: `python run_pipeline.py --backfill` runs fetch → load →
verify → pair → model → test end to end on DuckDB, 132 v2 nodes and 38 Arm A
nodes, and the Snowflake portability gate passes on all 132 compiled statements.
Arm B has not been started: no bucket assignment is committed, so **G1 is open
and no bucket-level figure exists.**

### Against the goals

| # | Goal | Outcome |
|---|------|---------|
| G1 | Bucket hypothesis becomes a test | **Not started.** `seeds/buckets.csv` is not committed and nothing bucket-level has been computed. Deliberately: §11's disclosure only holds while that stays true |
| G2 | Backfill verified, not trusted | **Met.** 20,222 of 20,227 comparable observations agree exactly — **99.98%**, five disagreements, all Woolworths. `scripts/verify_backfill.py`, gated at 99.0% inside the pipeline |
| G3 | Promotion vs position at scale | **Met.** 30,398 national-brand gap episodes across a year; 97.7% close, median closed episode **7 days** |
| G4 | v2 pairs get their history back | **Met.** 154 of 160 v2 pairs extended with zero re-matching, on an equality join |
| G5 | The two arms stay separate | **Met structurally.** `pair_set` is part of the grain of every Arm A model and an accepted-values test pins it to two values |

### A note on the pair counts

§11 measured 158 v2 pairs during feasibility; §12 reports 160. The difference is
not a correction: the build re-ran the matcher across every collected day
including 2026-08-24 and 2026-08-25, which the feasibility pass predated, and
those days contributed two more distinct (Woolworths, Coles) combinations.
§11 is left as it was written — it is a record of what was known before the
build, and rewriting it afterwards would defeat the point of having it.

Five Woolworths products carry more than one v2 pair, having been matched to
different Coles products on different days as names drifted across the fuzzy
threshold. `v2_extended` is therefore not one-to-one on product id, while `wide`
is, which is why the overlap report tests membership rather than equality.

### What was built

| Component | FR | Scale |
|---|---|---|
| `ingest/fetch_hotprices.py` | FR-1 | 2 files, 3.9 MB, never overwritten |
| `ingest/load_hotprices.py` | FR-1 | `raw_hotprices`, **783,141** change points, 44,648 products, 2023-09-26 → 2026-08-27 |
| `scripts/verify_backfill.py` | FR-2 | `backfill_verification`, 23,324 rows |
| `matching/extend_pairs.py` | FR-3 | 154 pairs, brand tier from the retailer brand field |
| `matching/match_backfill.py` | FR-4 | 1,523 pairs, brand tier derived from the name |
| `matching/brands.py` | new | The one definition of store brand vs name brand |
| `stg_hotprices` | FR-1 | Change points to validity windows |
| `int_backfill_pair_daily` | §5.1 | 595,462 pair-days |
| `mart_gap_episodes` | G3 | 33,378 episodes |
| `mart_brand_tier_gaps` | new | The headline, split by brand tier |

### Deviation from §5.1: the brand-tier split

§5.1 planned `int_backfill_daily` at product-per-day grain and no brand-tier
model at all. Both changed during the build.

The grain moved to `int_backfill_pair_daily`, one row per (pair_set, pair_id,
price_date). Expanding 44,648 products across three years would have been ~44 M
rows to support an analysis that only ever reads matched pairs; building the
spine at pair level is 595,462 rows for the same answers.

The larger change is that **every Arm A measure is now split by brand tier**, and
that was not in the PRD. It should have been. A name brand is the same physical
good on both shelves, so a gap is a pricing decision and parity is deliberate
matching. A store brand is a substitute from a different supplier, so a gap is
partly a product difference and parity is not matching at all. Pooling them
leaves every measure ambiguous — and worse, it leaves v2's aisle finding
unfalsifiable, because private-label share varies by aisle and a pooled parity
rate could move from pantry to household on mix alone. `matching/brands.py`
holds the single definition; `mart_brand_tier_gaps` is the model.

### Deviation from FR-4: a rule v2 does not have

FR-4 promised v2's acceptance rules "unchanged". One had to be added, and the
first build showed why: `token_set_ratio` scores 100 when one name's tokens are
a subset of the other's, so with no search-term block it accepted

```
Macro Organic Baby Food Mixed Fruit Spinach Smoothie  ->  Coles Baby Spinach                  (80)
Only Organic Mango Banana Passion Coconut & Flaxseed  ->  Only Organic Banana Biscotti        (81)
Woolworths RSPCA Approved Chicken Giblets             ->  Coles RSPCA Chicken Whole Boneless  (70)
```

v2 never meets these because its candidates come from inside one basket line.
`token_sort_ratio` does not ignore the leftover tokens and scores them 39, 59 and
62, so FR-4 now requires both, with the sort floor at 75 — the number v2 already
uses for its looser tier rather than a fresh constant tuned until the output
looked right. It cut the wide set from 1,827 pairs to 1,523 and raised agreement
with the v2 control from 85% to 88%.

**It reduces the problem and does not solve it.** Two products differing only by
flavour — Arnott's Shapes Korean BBQ against Arnott's Shapes Garlic Bread — score
high on every name-similarity measure there is. The honest quality number for
this pair set is not the threshold but the 88% agreement with v2's pairs,
printed on every run, and that is why FR-3's set is kept beside it as the control
rather than merged into it.

### Deviation from §5.1: 11 quarantined products

The grain assumption — one price per product per date — is false for 11 of
23,449 Woolworths products and none at Coles. Each reports two prices on one
date, in pairs like $4.45/$8.90 and $2.50/$5.00: a promotion that opened and
closed inside one of Hot Prices' collection cycles.

Nothing in the file says which price stood at the end of the day, and an
ambiguous change point does not only corrupt its own day — it makes the validity
window either side of it wrong. So the product is dropped whole rather than a
price guessed, and the loader raises instead if the share ever exceeds 1%. The
ambiguous dates cluster on exactly two days, 2025-05-31 and 2025-08-08, which
makes them two upstream collection incidents rather than noise.

### Deviation from G3: episodes are split by direction

The first build defined an episode as any run of days more than 5% apart, and
produced 330-day episodes in which the dearer chain swapped back and forth. That
is one run of wide days but plainly not one gap. Direction is now part of the
island key, so a gap that closes and reopens with the other retailer on top is a
new episode, and `cheaper_at` is single-valued by construction.

### The finding

A year, 2025-08-27 to 2026-08-27. Both pair sets agree on every direction despite
being built from different brand mechanisms and different blocking:

| | national brand | store brand |
|---|---|---|
| Pairs (wide / v2) | 1,361 / 125 | 162 / 29 |
| Change events (wide) | 47,821 | 1,687 |
| **Share of days a price moved** | **9.6% / 10.2%** | **2.9% / 2.6%** |
| Parity rate | 50.4% / 43.3% | 60.8% / 64.8% |
| 90th-percentile gap | 51.4% / 66.7% | 20.7% / 28.6% |
| Days more than 5% apart | 47.9% / 55.2% | 32.0% / 31.1% |
| Median closed-episode depth | 30.2% / 35.4% | 14.3% / 18.2% |

**Store brands are repriced about three and a half times less often than name
brands**, sit at parity more often, and when they do diverge the gap is half as
deep. That is the shape of a range priced to hold an everyday position against
one priced as a promotional vehicle — and it is a distinction that disappears
entirely if the two are pooled.

**The median closed gap episode is 7 days in all four cells.** Not close to
seven — seven, national and store brand, both pair sets. The promotional week is
the unit of Australian grocery pricing, and a 10-day study cannot see it.

One caveat tested and discharged: store-brand parity might have been nothing but
round-number price points colliding, since the two chains' own ranges are
different products. It is not. Parity days are no likelier to sit on a whole
dollar than non-parity days (34.4% against 33.3%) or on a 50-cent point (56.3%
against 52.5%).

### What is left

1. ~~Resolve the data licence with the Hot Prices author (§8).~~ **Done
   2026-08-27** — permission granted by email for personal-project use.
   Publication of Arm A figures is no longer blocked.
2. **Commit `seeds/buckets.csv`** before computing anything bucket-level. G1
   depends on that ordering and §11's disclosure expires the moment it is broken.
3. Arm B's four measures still wait on collected days, not on code.
