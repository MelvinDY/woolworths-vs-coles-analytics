# Results — the registered Arm A test

**Registered:** commit `51cb891`, 2026-08-27, before any figure below existed.
**Run:** 2026-08-27, window 2025-08-27 to 2026-08-27, `pair_set = 'wide'`.
**Predictions:** [preregistration.md](preregistration.md).

Arm A is a **blind analysis**, not a pre-registration: the history existed before
the buckets were written. Predictions were fixed before measurement, which is
worth something, but it is the weaker of the two designs and Arm B is the real
one.

## Scorecard — the numeric predictions

Seven of twelve inside the registered range.

| Cell | Measure | Predicted | Actual | |
|---|---|---|---|---|
| Produce × name brand | Parity | 25–45% | **46.1%** | miss, high by 1.1pp |
| Produce × name brand | Median gap | 2–8% | **9.8%** | miss, high |
| Produce × name brand | Move rate | 8–14% | 10.2% | hit |
| Produce × store brand | Parity | 40–60% | **37.1%** | miss, low by 2.9pp |
| Produce × store brand | Median gap | 1–6% | 5.4% | hit |
| Produce × store brand | Move rate | 3–7% | **7.4%** | miss, high by 0.4pp |
| Staple × name brand | Parity | 50–70% | 53.7% | hit |
| Staple × name brand | Median gap | 0–3% | 0.0% | hit |
| Staple × name brand | Move rate | 8–14% | 8.9% | hit |
| Staple × store brand | Parity | 55–75% | 66.8% | hit |
| Staple × store brand | Median gap | 0–3% | 0.0% | hit |
| Staple × store brand | Move rate | 2–5% | **1.1%** | miss, low |

The misses are not evenly spread: **packaged staples went 5 of 6, produce went 2
of 6.** The cell flagged in the registration as the interesting one is the cell
the predictions got wrong, which is at least the right cell to be wrong about.

## The four directional claims

| | Claim | Result |
|---|---|---|
| **P1** | Parity higher on staples than produce, both tiers | **Holds.** Name brand 53.7% vs 46.1%; store brand 66.8% vs 37.1% |
| **P2** | Median gap larger on produce than staples, both tiers | **Holds.** Name brand 9.8% vs 0.0%; store brand 5.4% vs 0.0% |
| **P3** | Store brands move less often than name brands *within* each aisle group | **Holds, but strongly heterogeneous** — see below |
| **P4** | Median closed episode at or near 7 days in every cell | **Holds in 4 of 5.** Fails on staple × store brand: 13.5 days |

### P3 — the finding survives, with a caveat that matters

P3 was the robustness test of the headline published in PRD-v3 §12: store brands
repriced ~3.5× less often than name brands. The registration committed to
retracting that publicly if it turned out to be an aisle-mix artefact.

**It is not an artefact. The direction holds inside both aisle groups.** But the
size of the effect is not remotely constant:

| Aisle group | Name brand | Store brand | Ratio |
|---|---|---|---|
| Packaged staples | 8.9% of days | 1.1% of days | **8.1×** |
| Produce | 10.2% of days | 7.4% of days | **1.4×** |

So the pooled 3.5× is real but it is close to an average of two different
regimes. **The "store brands hold still" effect is a packaged-goods phenomenon
and nearly disappears in fresh produce** — which makes sense: produce prices
move with the crop and the weather no matter whose name is on the label, while
private-label pricing discipline is something you can only exercise over a
manufactured good.

The §12 headline stands as stated. It is now more precisely stated here.

### P4 — the one clean failure

The 7-day promotional week held everywhere except store-brand packaged staples,
where the median closed episode is **13.5 days**. That is not noise: the
`v2_extended` control, built by a different matcher on a different blocking key,
independently gives **16.0 days** for the same cell.

Store-brand staple gaps last roughly twice as long as everything else. Consistent
with P3 — a range that reprices eight times less often also takes about twice as
long to close a gap when one opens.

## The produce trap — the prediction that failed hardest

The registration singled this out: produce should land **low parity but high
correlation**, two chains buying the same crop in the same weather moving
together without ever matching to the cent. Predicted correlation was 0.6–0.85
for produce and 0.8–0.95 for packaged staples.

Median per-pair correlation of the two chains' prices:

| Cell | Daily | Monthly means | Predicted |
|---|---|---|---|
| Produce × name brand | **−0.08** | 0.28 | 0.6–0.85 |
| Staple × name brand | **−0.01** | 0.24 | 0.8–0.95 |
| Produce × store brand | 0.21 | 0.42 | — |
| Staple × store brand | 0.39 | **0.72** | — |

**Day-to-day, national-brand prices at the two chains are essentially
uncorrelated.** Not weakly correlated — zero, and slightly negative. That is a
long way outside anything registered, and it is the most interesting number the
test produced.

Smoothing to monthly means lifts it to about 0.25, so there *is* shared
underlying movement; it is simply swamped at daily frequency. The mechanism is
visible in the rest of the results: national brands are the promotional vehicles
(8.9–10.2% of days see a price move, median episode 7 days), and the two chains
run their cycles **out of phase**. When one is on promotion the other typically
is not, so daily prices take turns rather than moving together. It matches the
ACCC's own observation, from ticketing data this project cannot see, that the
two retailers changed price in opposite directions about 12% of the time.

Store brands are the control that proves it. Lightly promoted, they track each
other far more closely — 0.72 monthly on packaged staples, the highest figure in
the table — because what is left once you remove promotions is shared cost
movement hitting both chains at once.

So the registered framing was wrong twice over: correlation is not high on
produce, and it is not high on staples either. **The axis that separates
correlated from uncorrelated is not fresh-versus-packaged. It is store brand
versus name brand** — which is to say, promoted versus not.

## Caveats

- **Correlation on price levels is dominated by promotional spikes.** That is
  the substantive point above rather than a nuisance, but it means these figures
  describe observed shelf prices, not base or cost-recovery prices.
- **Small cells.** Store-brand staples is 23 pairs and 93 change events; the
  `v2_extended` control cells are 8–39 pairs. Directions are consistent between
  the two independently built pair sets, which is the main reason to believe
  them, but no interval is quoted because none would be honest at that n.
- **`wide` pair quality.** That set agrees with v2's pairs on 88% of shared
  products, so roughly one pair in eight is likely a variant mismatch. Errors of
  that kind inflate gaps and depress parity, and they are not evenly spread —
  produce names are short and generic, which is where fuzzy matching is weakest.
  This is a live candidate explanation for produce's higher median gap.
- **`opaque` is three pairs** and appears in the mart only so its emptiness is
  visible. Nothing in this document rests on it.
- **One year, one season.** Produce is seasonal and this window covers a single
  pass through the calendar.

## What changed as a result

Nothing is retracted. P3 held, so the §12 headline stands.

Two things are now stated more precisely than before: the store-brand repricing
effect is concentrated in packaged goods rather than uniform, and the two chains'
national-brand prices do not track each other day to day at all.

---

## Re-run on the full history — 2026-08-27 (appended)

Appended, not edited. The scorecard above was computed on a twelve-month window
and stands as the record of what was measured first.

**The window was wrong, and not by a date.** Eligibility and analysis window were
driven by one variable, so asking for a longer window also demanded that every
pair span the whole of it, which cut the pair set from 1,523 to 67. Separated —
a product needs a year of history to be *matchable*, each matched pair is then
*measured* over every day it has — the same 1,523 pairs carry **775,418
pair-days back to 2023-09-26**, against 557,418 before.

The registration named no window, so nothing here is a re-registration. It is
the same registered test on 39% more data.

### Every directional claim held

| | 12 months | Full history | |
|---|---|---|---|
| **P1** parity higher on staples, name brand | 53.7 vs 46.1 | **53.7 vs 45.6** | holds |
| **P1** parity higher on staples, store brand | 66.8 vs 37.1 | **66.9 vs 43.8** | holds |
| **P2** median gap larger on produce | 9.8 vs 0.0 | **10.5 vs 0.0** | holds |
| **P3** store brands move less, staples | 8.1× | **8.7×** | holds, stronger |
| **P3** store brands move less, produce | 1.4× | **1.6×** | holds, still weak |
| **P4** median closed episode | 7 days | **7 days** | holds |

P4's one failure improved rather than vanished: store-brand packaged staples ran
13.5 days over twelve months and **9 days** over three, still the only cell away
from seven.

### What the extra data changed

The correlation result got **less** extreme and no less damning. Name-brand
monthly correlation rises from 0.24–0.28 to **0.345–0.346**, still nowhere near
the registered 0.80–0.95, and store brands still track far more closely at
**0.73**. Three years of data did not rescue the prediction; it just measured
its failure more precisely.

Two findings only the longer series can support, both now on the portfolio page:

- **Gap size is bimodal.** 51.5% of pair-days are priced identically to the
  cent, 34% sit more than 20% apart, and the entire band from 1% to 5% holds
  2.4%. Prices are matched exactly or they are nowhere near each other, which is
  why every measure here is a rate or a median and never a mean.
- **December is the floor, three years running.** Repricing runs at 7 to 11% of
  pair-days in most months and drops to 5.4%, 6.1% and 6.0% in the Decembers of
  2023, 2024 and 2025. Both chains stop moving prices over Christmas. A
  twelve-month window shows this once and cannot tell it from noise.
