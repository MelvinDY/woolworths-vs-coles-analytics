# Data quality

Four failures reached published figures before they were caught. Both are
recorded here in full, because the interesting part of each is not the bug but
what it says about the difference between a script that ran once and a pipeline
that runs every morning.

None was found by a failing test. The first two were found by looking at a
number that was the wrong size; the third by a routine change that forced a
check nobody had thought to run; the fourth by reading the output of the third.
The third reversed a headline.

---

## 1. The partial day — 2026-08-22

### What happened

Coles pins its search JSON to a deployed `buildId`. The collector resolves one
at the start of a run and reuses it for all fifty search terms. On 22 August
that id began answering `HTTP 500` partway through the run, and forty-three of
the fifty terms came back empty. Seven answered.

The run wrote the day anyway: 597 rows, of which Woolworths supplied fifty
basket lines and Coles supplied seven.

### Why the guard did not catch it

```python
for retailer, n in counts.items():
    if n == 0:
        raise RuntimeError(f"No products fetched from {retailer} — aborting run")
```

The guard asked whether a retailer had returned *any rows at all*. Coles had
returned 189 of them, across seven search terms. A row count cannot tell the
difference between a retailer that answered the basket and a retailer that
answered a fraction of it very thoroughly.

*Corrected 2026-08-27.* This paragraph read "144 of them, across three search
terms", and the sentence above it said forty-seven terms came back empty. Both
were wrong, and the page contradicted itself: the paragraph before already said
Coles supplied seven. `data/raw/prices_2026-08-22.csv` is the system of record
and holds 189 Coles rows across seven terms, which is also the 14% coverage
`int_day_coverage` reports for that day. The argument is unaffected and the
arithmetic now matches the file.

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

## 3. The basket that compared 2 L of milk to 1 L — every day, from the first

This one is different from the other two. They were incidents: a bad morning,
a bad line. This ran from the first collected day to 2026-08-27, passed every
test, and **reversed the headline finding.**

### What happened

`mart_basket` takes the cheapest relevant hit per basket line and never checked
that the hit was the size the line asked for. So:

| Line | What was priced |
|---|---|
| `skim milk 2l` | Woolworths Skim Milk **1 L** |
| `vegemite 380g` | Vegemite Spread **150 g** |
| `full cream milk 2l` | a2 Milk Full Cream **1 L** |
| `greek yoghurt 1kg` | Chobani Greek Yogurt **160 g** |
| `carrots 1kg` | Coles Carrots Loose, **170 g** |
| `tasty cheese block 500g` | Kenilworth Roast Garlic, **165 g** |

A basket that prices a 1 kg line on a 170 g pack is not measuring price. It is
measuring pack size.

### Why it was not symmetric, and why that mattered

If the error had hit both chains equally it would have added noise. It did not:

| | Sized basket rows | Wrong pack size | Of which **smaller** than the line |
|---|---|---|---|
| **Coles** | 415 | **149 (35.9%)** | **124** |
| Woolworths | 415 | 13 (3.1%) | 13 |

Twelve times the error rate at Coles, overwhelmingly toward *smaller* packs —
which are cheaper. The bug applied a systematic discount to one side of the
comparison, and it was the side the published finding named as cheaper.

The cause is upstream and mundane: the two retailers' search endpoints rank
differently. Coles returns small formats high; Woolworths returns the format you
asked for. Nothing in the pipeline knew the difference.

### Why no test caught it

Every published test still passed. The grain was unique, the prices were
non-null and positive, the day was complete, both retailers had a candidate for
every line. Each row was a real product at a real price. The basket was simply
about something other than what it claimed.

This is the same shape as the other two failures on this page, and the reason
that section exists: **the failure mode of an automated collection is not a
crash, it is a number that is still a number.**

### The fix

The size the line asks for is parsed from the line itself — `full cream milk 2l`
already says `2l` — and a hit must match it within **2%**, which is the tolerance
`matching/match_products.SIZE_TOLERANCE` already uses to decide two packs are the
same size. Lines naming no size (`bananas`, `salmon fillets`) are unconstrained.

Deriving the requirement from the search term rather than configuring it per line
in `basket_relevance` is deliberate: the term is the thing being asked for, so a
derived screen cannot drift away from it.

**A line that names a size also stops being capped at the top five hits**, which
is the same rule `basket_relevance` already applies and for the same reason — a
line that can say what it is looking for does not need to guess that it is near
the top. That half is not optional. Screening on size while keeping the cap is
worse than either alone: at Coles on 2026-08-27 the correct 2 L Coles Full Cream
Milk at $3.55 sits at **rank 6**, so the cap discarded the right product and the
basket priced Pura at $4.65 instead. Applied that way the correction overshot
wildly, putting Woolworths ahead on 13 days of 13 by a mean of $24.

Two lines lose their Coles side permanently and leave the basket, which is the
honest outcome: Coles stocks no 250 g bacon rashers and no 750 g rolled oats.
**The basket is 48 lines, not 50.**

### What it changed

Decomposed, over all 13 complete days:

| | Coles cheaper | Mean gap (Woolworths − Coles) |
|---|---|---|
| As published | 11 of 13 | **+$8.10** |
| Size screen only, cap kept — *wrong* | 0 of 13 | −$24.04 |
| Size screen replacing the cap — **correct** | 6 of 13 | **−$5.02** |

Restricted to the same ten days the study published. These isolate the size fix;
case 4 shifts them again and carries the current figures:

| | As published | Corrected |
|---|---|---|
| Basket lines | 50 | 48 |
| Coles cheaper on | **9 of 10 days** | **4 of 10 days** |
| Mean basket | Coles $200.85 / Woolworths $214.77 | Coles $192.19 / Woolworths $187.23 |
| Headline gap (2026-08-23) | **$13.92, Coles cheaper** | **$0.11, Coles cheaper** |

The published claim that Coles wins the basket does not survive. The two chains
are level to about a dollar on the headline day, the winner flips repeatedly, and
across ten days Woolworths is on average **$4.96 cheaper**, not Coles by $13.92.

That is a better answer as well as a truer one. A basket gap that flips sign and
averages near zero is what genuine competition between two national chains looks
like; a stable $13.92 lead was always more likely to be a measurement artefact
than a market fact, and it was.

### What it did not change

Nothing that comes from matched pairs. `mart_pair_comparison` compares products
resolved by the matcher, which has always enforced pack size within 2% — the
screen this mart was missing. On 2026-08-23 it still reports **128 pairs, 43%
priced identically**, exactly as published, and the parity-by-aisle spread of
62.5% in pantry to 7.1% in household is untouched.

The lesson is uncomfortable and worth keeping: **the matcher was right and the
basket was wrong, and the basket was the number on the front page.** The careful
component existed all along; the headline was computed by the crude one.

---

## 4. The butter that was margarine — every day, from the first

Found while reading the output of the case 3 fix, which is the point of reading
the output of a fix.

### What happened

With pack sizes finally correct, two lines were still pricing the wrong product:

| Line | Coles | Woolworths |
|---|---|---|
| `butter 500g` | Nuttelex Buttery **Spread** $4.50 | Meadowlea Original **Spread** $4.00 |
| `paper towel` | Coles Simply Facial **Tissues** $1.90 | Strike 2 Ply Paper Towel $2.20 |

Both chains rank margarine into a butter search, and both are 500 g, so the
case 3 size screen passed them happily. Coles ranks facial tissues second and
toilet paper third for `paper towel`, and the basket took the tissues.

A size screen answers "is this the right amount of something". It has nothing to
say about whether it is the right something.

### Why must_not_match had to exist

`basket_relevance` could only require a pattern, and a positive pattern cannot
separate these:

- **`Nuttelex Buttery Spread` contains the string `butter`.** Any rule matching
  butter matches buttery.
- **`Western Star Original Spreadable Butter Blend` genuinely says butter.** It
  is a dairy blend cut with vegetable oil, and at $6.80 it would have undercut
  every real 500 g butter at Woolworths and won the line.

So the seed gained a `must_not_match` column, applied after `must_match`, which
lets a rule admit a family and then carve exceptions out of it. `butter 500g` is
now `must_match: butter`, `must_not_match: buttery|spread|blend`.

`paper towel` needed only the positive half, `must_match: paper towel` — tissues
and toilet paper do not contain the phrase.

### What it changed

Both lines now compare like with like, and both land level:

| Line | Coles | Woolworths |
|---|---|---|
| `butter 500g` | Coles Simply Salted Butter **$7.00** | Woolworths Salted Butter 500g **$7.00** |
| `paper towel` | Coles Simply Paper Towel **$2.20** | Strike 2 Ply Paper Towel **$2.20** |

Worth noting that `Coles Simply Paper Towel` at $2.20 was never in the top five
hits. It only becomes reachable because a line carrying a rule stops being
capped — the same mechanism case 2 introduced and case 3 extended to sized
lines, doing its job a third time.

Headline effect, over the ten published days, relative to the case 3 figures:

| | After case 3 | After case 4 |
|---|---|---|
| Mean Coles basket | $192.19 | **$194.30** |
| Mean Woolworths basket | $187.23 | **$187.83** |
| Mean gap | −$4.96 | **−$6.47** |
| 2026-08-23 | $0.11, Coles cheaper | **$0.76, Coles cheaper** |
| Coles cheaper on | 4 of 10 days | **4 of 10 days** |

Removing the margarine raised the Coles basket more than the Woolworths one,
because Coles was the side being priced on $4.50 Nuttelex. The conclusion from
case 3 is unchanged and slightly reinforced: the two chains are level on the
headline day, the winner flips repeatedly, and across ten days Woolworths is
cheaper on average.

### What is still not fixed

`paper towel` names no pack size, so nothing screens it: Coles parses that line's
pack count as rolls and Woolworths as sheets, and the basket compares $2.20 for
two rolls with $2.20 for 2×80 sheets. Every unsized line in the basket has the
same exposure. It is a comparability problem rather than an identity one, the
size screen from case 3 cannot reach it because the line states no size, and it
is recorded here rather than fixed.

---

## What they have in common

The v1 study ran once, by hand, and someone looked at the output. All four of
these failures are what that looks like when nobody is looking any more:

- A retailer's search ranking is **not a stable interface**. It is tuned
  continuously, and it will hand back something that is not the product without
  any error at all.
- A guard on **volume** is not a guard on **coverage**.
- The failure mode of an automated collection is not a crash. It is a number
  that is still a number, still passes every type and uniqueness test, and is
  quietly about something else.

- A guard on **identity** is not a guard on **comparability**. Every row in
  case 3 was a real product at a real price; it was the wrong size.
- An error that is **asymmetric between the things being compared** does not add
  noise, it adds bias — and it will point wherever the ranking happens to point.

Every test in this project passed on all four.

Two of the three were found by looking at a number that was the wrong size. The
third was found because a routine change forced a check nobody had run. None was
found by a failing test, which is the whole argument for looking.
