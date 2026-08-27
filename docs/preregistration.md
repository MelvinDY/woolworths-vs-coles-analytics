# Pre-registration — the bucket hypothesis

**Registered:** 2026-08-27. The commit that adds this file and
`transform/dbt/seeds/buckets.csv` *is* the registration; its hash and timestamp
are the evidence, and anyone who clones the repo can check that it precedes
every bucket-level result. That is the whole mechanism. If a figure in this
project is ever dated before this commit, it was not registered.

## Why this file exists

v2 found that parity runs from 62.5% in pantry to 7.1% in household and that the
mean household gap is six times pantry's. It found that *after* looking. v2 said
so itself: "a hypothesis this project generated rather than one it tested."

The remedy the README named was to assign every line to a bucket up front,
publish the assignment, and only then measure. This is that assignment, plus the
numbers predicted before measuring, so the study can be scored against them
rather than agreeing with itself.

## The assignment

`transform/dbt/seeds/buckets.csv` — 80 items, 40 **price-visible** and 40
**price-opaque**, each with a name-match pattern and a one-line rationale
written before any bucket-level figure was computed.

**price-visible** — lines a shopper can price from memory. 20 fresh produce,
20 packaged staples. Matched to the cent, near-zero margin, and the basis of
price perception for the whole store.

**price-opaque** — the long tail. Bought rarely, under duress, or with no
reference price at all: plungers, denture tablets, teething gel, worming
tablets. Household, baby, health, pet and occasion lines, 8 each.

The word *elasticity* appears nowhere. Scraped prices carry no quantities, so
elasticity cannot be computed from any of this. What the split measures is
exposure to competitive price pressure, which is a different and more answerable
thing.

## Disclosure — what had already been seen

Registration is worthless without an honest account of what was known when the
predictions were written. At the time of this commit:

**Known.** The pooled Arm A results published in PRD-v3 §12 — parity, gap size,
move rate, episode length and depth, split by *brand tier only* (name brand vs
store brand) across the whole pair set. Those are in the previous commit and the
predictions below are made in full knowledge of them.

**Also known, and the reason this file changed shape.** Pattern *coverage* was
checked before registering: how many products and pairs each of the 80 patterns
matches, and their names. That is counting, not measuring — no price, gap,
parity, episode or date figure was computed for any bucket, aisle or item.
Checking coverage first is what stopped this file from registering a test the
data cannot run.

**Not known, and the substance of the test.** No parity rate, gap, move rate or
episode statistic for any bucket, aisle group or item. Nothing below has been
computed.

## The coverage problem, found before registering

**Arm A cannot test the price-visible / price-opaque split. The data does not
contain the tail.**

The 40 opaque items match **3 pairs** in the entire backfill. Not because the
matcher rejects them — because a cross-retailer pair needs the product at *both*
chains, and the tail is barely stocked in the Hot Prices dumps and lopsided
where it is:

| Item | Woolworths | Coles | Pairs |
|---|---|---|---|
| Flea treatment | 19 | 0 | 0 |
| Greeting cards | 0 | 6 | 0 |
| LED globes | 4 | 18 | 0 |
| Sink plunger, picture hooks, reading glasses, worming tablets, clothes pegs | 0 | 0 | 0 |

This also puts v2's own finding in perspective. v2's "household" aisle is
toilet paper, paper towel, dishwashing liquid and laundry liquid — mid-tail
supermarket lines, not the tail. **This project has never measured the true long
tail at all**, in any version, and it cannot start by mining a source that does
not carry it.

So the axis splits by arm:

| Hypothesis | Arm A (backfill) | Arm B (own collection) |
|---|---|---|
| Produce vs packaged staples, by brand tier | **Testable now** — 499 pairs across four cells | later |
| Price-visible vs price-opaque | **Not testable. Ever, on this source.** | **The only arm that can** — the collector can be pointed at the 40 tail items deliberately |

Arm B is therefore not merely "the pre-registered arm". It is the only arm with
any access to the tail, and testing the visibility hypothesis requires expanding
`seeds/basket.csv` from its 50 head lines to include the 40 opaque items. That
expansion has **not** been made and no tail line has been collected. Until it
is, the visibility hypothesis is registered but unrun.

## Predictions — Arm A, produce vs packaged staples

Cell sizes are known (counting is permitted above); every measure is not.

| Cell | Pairs |
|---|---|
| Produce × name brand | 179 |
| Produce × store brand | 32 |
| Packaged staple × name brand | 265 |
| Packaged staple × store brand | 23 |

| Cell | Parity rate | Median absolute gap | Share of days a price moved |
|---|---|---|---|
| Produce × name brand | 25–45% | 2–8% | 8–14% |
| Produce × store brand | 40–60% | 1–6% | 3–7% |
| Staple × name brand | 50–70% | 0–3% | 8–14% |
| Staple × store brand | 55–75% | 0–3% | 2–5% |

The directional claims, which are the actual test:

- **P1 — Parity is higher on packaged staples than on fresh produce, in both
  brand tiers.** National brands are directly comparable and matched on purpose;
  produce is sold by weight and grade, so an exact match is closer to
  coincidence.
- **P2 — The median absolute gap is larger on produce than on staples, in both
  tiers.** Same reason, read the other way.
- **P3 — Store brands move less often than name brands *within* both aisle
  groups.** This is the important one. It is a robustness test of the finding
  already published in §12: if the store-vs-name gap only exists pooled and
  vanishes once aisle is held constant, the headline was an aisle-mix artefact
  and not a pricing fact.
- **P4 — The median closed gap episode stays at or near 7 days in every cell.**
  If the promotional week is real it should not care which aisle it is in.

**The produce trap.** Parity and correlation are different questions and produce
is where they separate. Two chains buying the same crop in the same weather move
together without ever matching to the cent. Produce is expected to land *low
parity, high correlation* — competitively exposed but not matched. If that shows
up, exposure and matching are two axes rather than one, the two-bucket model is
too coarse, and the honest response is to refine it rather than defend it.

## Predictions — Arm B, price-visible vs price-opaque

Registered now, runnable only after the basket is expanded and days accumulate.

| Measure | Price-visible | Price-opaque |
|---|---|---|
| Parity rate | 40–70% | 5–20% |
| Median absolute gap | 0–5% | 8–25% |
| Days flagged on promotion | 15–35% | 2–8% |
| Median promotion depth | 25–45% | 10–25% |
| Gap persistence over 5% | 1–10 days | 20+ days, most never closing |

- **P5 — Parity is far higher on price-visible lines than on price-opaque ones.**
- **P6 — Price-opaque gaps persist for weeks; price-visible gaps close in days.**
- **P7 — Reference integrity holds.** v2 tested 100 advertised "was" prices
  against its own earlier observations and all 100 passed. The prediction is
  that the pass rate stays at or near 100%, not that failures appear. An earlier
  draft of this design predicted failures; v2 had already measured their
  absence, and predicting something the project has measured as absent is not a
  prediction.

## Reading it either way

Decided now, so the conclusion is not chosen after the fact.

| If the result is | Then |
|---|---|
| P1 and P2 hold; P3 holds | The split is real and the published brand-tier finding survives controlling for aisle. The predicted outcome |
| **P3 fails** | **The store-vs-name finding published in §12 is an aisle-mix artefact.** It gets corrected in the README and the PRD, publicly, with this file cited as what made the error findable |
| P1 fails — parity as high on produce as on staples | The visibility intuition is wrong even inside the head of the range, and the whole visible/opaque framing is in doubt before Arm B ever runs |
| Produce lands low parity but high correlation | Exposure and matching are separate axes. The two-bucket model is too coarse; refine it rather than defend it |
| P5 and P6 fail once Arm B runs | Competitor matching runs across the whole range regardless of category, most likely automated. More interesting than what was set out to test: tail margin would then come from what each chain *ranges*, not what it charges |

Row two and row five are the falsifiers, and both would be published. Naming in
advance the result that would sink the hypothesis — including one that would
retract a finding already published in this repo — is most of what separates a
test from a story.

## Rules binding this registration

1. No bucket-level figure is computed before the commit that adds this file.
2. `buckets.csv` is not edited after this commit to improve a result. A pattern
   may be corrected only for a demonstrable *coverage* fault (matching the wrong
   product, or nothing), in its own commit, stating what was wrong and citing
   the fix — never after seeing the measure it affects.
3. Every published bucket figure cites this commit hash beside it.
4. Arm A results are labelled observational. The history existed before the
   buckets were written, so this is a blind analysis — predictions fixed before
   measurement on pre-existing data — and not a true pre-registration. Arm B is
   the true one. The distinction is stated wherever both appear.
