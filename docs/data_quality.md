# Data quality

Two failures reached published figures before they were caught. Both are
recorded here in full, because the interesting part of each is not the bug but
what it says about the difference between a script that ran once and a pipeline
that runs every morning.

Neither was found by a failing test. Both were found by looking at a number
that was the wrong size.

---

## 1. The partial day — 2026-08-22

### What happened

Coles pins its search JSON to a deployed `buildId`. The collector resolves one
at the start of a run and reuses it for all fifty search terms. On 22 August
that id began answering `HTTP 500` partway through the run, and forty-seven of
the fifty terms came back empty. The last three recovered on their own.

The run wrote the day anyway: 597 rows, of which Woolworths supplied fifty
basket lines and Coles supplied seven.

### Why the guard did not catch it

```python
for retailer, n in counts.items():
    if n == 0:
        raise RuntimeError(f"No products fetched from {retailer} — aborting run")
```

The guard asked whether a retailer had returned *any rows at all*. Coles had
returned 144 of them, across three search terms. A row count cannot tell the
difference between a retailer that answered the basket and a retailer that
answered a fraction of it very thoroughly.

### Why it matters more than a missing day

A missing day is visible. The history marts already model it: the series leaves
the day null, a test enforces that the flag and the nulls agree, and the
dashboard draws the stretch dashed instead of joining it with a confident line.

A partial day is invisible. It looks like every other row in the table, and
every comparison built on it silently comes from a different basket at each
retailer. Left in, 22 August reads as a real day on which the two chains
happened to agree less often than usual — 27 matched pairs against a normal
day's 128.

### The fix

Two layers, because the two jobs are different.

**Prevention**, in `ingest/fetch_prices.py`: coverage is now counted in basket
*lines answered* per retailer, not rows returned, and a run covering less than
`MIN_COVERAGE` (80%) of the basket on either side aborts without writing.
Nothing is lost that was not already lost — the day could not have been
backfilled either way, and the honest options are a good day or no day.

The fetcher also now re-resolves the Coles `buildId` after
`COLES_REFRESH_AFTER` consecutive empty terms and retries the term that tripped
it, so a mid-run deploy costs a few seconds rather than a day.

**Containment**, in `models/intermediate/int_day_coverage.sql`: every collected
day gets a coverage percentage and an `is_complete_day` flag, and `mart_basket`
and `mart_pair_comparison` both read only complete days. The raw CSV for 22
August stays exactly where it is. It is the system of record and it is not
edited — it is simply not counted as a day the basket was observed.

The threshold is deliberately blunt. Every real day clears it at 98–100% and 22
August lands at 14%, so nothing sits near the line and no day is a judgement
call.

---

## 2. The basket line that stopped being eggs — 2026-08-18

### What happened

`mart_basket` prices each line at the cheapest of the retailer's top five
search hits. From 18 August the Woolworths `eggs 12 pack` line was priced at
**$65.99**, for an egg incubator. Over the following days it moved to a $22 egg
carrier, then a $39.75 storage box.

That one line inflated the Woolworths basket by roughly $59 and produced an
apparent $46–81 basket gap where the real figure was around $12.

### The actual cause

Not what it first looked like. Woolworths had not stopped selling eggs, and
their search had not broken that morning. Third-party marketplace listings —
incubators, carriers, storage boxes, a dinosaur fossil toy — had been crowding
that term the whole time. The only real carton in the results sat at **rank 5
of 5** on 16 August, and on 18 August it slipped to **rank 6** and left the
window.

So the published $6.90 on 16 August was already luck. The `result_rank <= 5`
cap was doing relevance work it was never designed for, and it had been one
place from failing for as long as the line had existed.

### What did not work

A deny-list of junk keywords (`incubator|hatcher|carrier|storage|…`) was tried
first. It moved the pick from a $65.99 incubator to a **$104.99 dinosaur fossil
digging set**. The supply of things that are not eggs is unbounded; enumerating
it is not a strategy.

### The fix

`seeds/basket_relevance.csv` carries optional per-line rules, and a line that
has one is screened by it across *every* hit returned rather than the top five.
The cap is a crude stand-in for relevance, and a line that can state what it is
looking for does not need to guess that it is near the top.

For `eggs 12 pack` two rules together do it:

| rule | value | what it removes |
|---|---|---|
| `require_unit_basis` | `per_100g` | all marketplace hardware — it is priced per each, or carries no unit price at all |
| `must_match` | `12 pack\|12pack\|eggs 12` | 6-, 18- and 30-packs, and Coles' 2-pack of boiled eggs |

The unit-basis rule is the structural one and it is what makes this more than
keyword whack-a-mole: real groceries in this line are sold by weight and carry
a per-100g unit price, and the hardware polluting the results does not. The
name rule then holds both retailers to the same pack size, which the widened
candidate set otherwise loses — removing the rank cap let the Coles side drift
to a 2-pack at $3.50.

**Both rules test product identity. Neither looks at price.** A price-based
filter — a plausible-range band per line — would have been quicker and is the
wrong tool: it would quietly discard real price movement, which is the one
thing this project exists to measure. A guard that can hide the finding is
worse than the bug.

### Verification

After the fix the Woolworths line reads $6.60–$6.90 on every collected day, and
the Coles line reads a genuine 12-pack throughout. Every basket total from
before 18 August is **unchanged to the cent** — 15 July is still $209.59 against
$211.41 — which is the property that matters: the screen repaired the days it
was meant to repair and moved nothing else.

---

## What both have in common

The v1 study ran once, by hand, and someone looked at the output. Both of these
failures are what that looks like when nobody is looking any more:

- A retailer's search ranking is **not a stable interface**. It is tuned
  continuously, and it will hand back something that is not the product without
  any error at all.
- A guard on **volume** is not a guard on **coverage**.
- The failure mode of an automated collection is not a crash. It is a number
  that is still a number, still passes every type and uniqueness test, and is
  quietly about something else.

Every test in this project passed on both bad days.
