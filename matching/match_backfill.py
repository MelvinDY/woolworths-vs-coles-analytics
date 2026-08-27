"""FR-4 — match products across the full Hot Prices dumps, and write backfill_pairs.

FR-3 gets 153 pairs for free. This module is how the study reaches ten times
that, and it is measurably weaker work, so the weakness is recorded on every
row rather than described in a footnote.

Two things v2's matcher has that this one does not:

  * **No search term.** v2 blocks candidates within a basket line, which is a
    strong, human-authored block. The dumps have no such field, so blocking here
    is on (canonical unit, quantity within 2%) — cheap, and it lets two unrelated
    500 g products meet as candidates that v2 would never have introduced.
  * **No brand field.** v2 requires equal retailer-supplied brands. Here brand is
    the leading token of the product name (matching/brands.py), which is where
    Hot Prices puts it. That is a proxy and it is stamped on the output as
    `brand_tier_basis = 'derived_from_name'` so no downstream reader can mistake
    it for v2's.

Everything else is v2's rule, unchanged: size within 2%, `token_set_ratio` at 80
for national brands and 75 for store brands, store brands matched only to store
brands, greedy one-to-one assignment by descending score with a deterministic
product-id tiebreak.

The store-brand tier, and why it is scored differently
-----------------------------------------------------
Coles Jasmine Rice and Woolworths Jasmine Rice are substitutes, not the same
good, exactly as v2 has it. They are also guaranteed to disagree on the one
token this module uses as a brand, so the national tier's equal-brand-token rule
would reject every store-brand pair outright. The store-brand tier therefore
scores the names with the retailer prefix removed (`brands.strip_own_brand`),
which compares 'jasmine rice' against 'jasmine rice' instead of paying a penalty
for the two chain names that are supposed to differ.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections import defaultdict

import pandas as pd
from rapidfuzz import fuzz

from matching import extend_pairs
from matching.brands import (
    NATIONAL,
    OWN,
    brand_tier_from_name,
    brand_token_from_name,
    norm_text,
    strip_own_brand,
)
from warehouse import Warehouse

log = logging.getLogger(__name__)

TABLE = "backfill_pairs"
PAIR_SET = "wide"

# v2's thresholds, imported by value rather than reference so that a change to
# the live matcher cannot silently re-cut a published backfill.
NAME_SCORE_NATIONAL = 80
NAME_SCORE_OWN_BRAND = 75
SIZE_TOLERANCE = 0.02

# The one rule here that v2 does not have, and the reason it is needed.
#
# token_set_ratio scores 100 whenever one name's token set is a subset of the
# other's, because it compares the shared tokens and ignores what is left over.
# v2 can live with that: its candidates come from inside a single basket search
# term, so two products that reach the comparison are already the same kind of
# good. This matcher blocks on nothing but pack size, so the subset blindness
# becomes live and produces matches like
#
#   'Macro Organic Baby Food Mixed Fruit Spinach Smoothie' -> 'Coles Baby Spinach'   (set 80)
#   'Only Organic Mango Banana Passion Coconut'            -> 'Only Organic Banana'  (set 81)
#
# token_sort_ratio does not ignore the leftovers, and scores those 39 and 59.
# Requiring both is what removes them. The floor is 75 — the same number v2
# already uses for its looser tier, rather than a fresh constant tuned until the
# output looked good.
#
# It reduces the problem and does not solve it. Two products that differ only by
# flavour ('Arnott's Shapes Korean BBQ' against 'Arnott's Shapes Garlic Bread')
# score high on every name-similarity measure there is, and no global threshold
# separates a variant from a match. The honest quality statement for this pair
# set is not this constant but the measured agreement with the v2 control that
# _overlap_report prints on every run.
NAME_SORT_FLOOR = 75

# A pair needs a real series on both sides to be worth carrying. One change
# point is a price we have seen once, not a price we have watched.
MIN_CHANGES = 2


def _products(wh: Warehouse, window_start: dt.date) -> pd.DataFrame:
    """One row per product, with its observed history bounds.

    Restricted to products whose history opens on or before `window_start`, so
    every candidate can actually be observed across the analysis window. A
    product first seen halfway through would contribute a series that starts
    late for reasons that have nothing to do with pricing.
    """
    df = wh.query_df(
        """
        SELECT retailer,
               product_id,
               max(name)       AS name,
               max(unit)       AS unit,
               max(quantity)   AS quantity,
               min(change_date) AS first_change,
               max(change_date) AS last_change,
               count(*)        AS n_changes
        FROM raw_hotprices
        GROUP BY retailer, product_id
        """
    )
    df = df[df.n_changes >= MIN_CHANGES]
    df = df[df.quantity.notna() & (df.quantity > 0) & df.unit.notna() & (df.unit != "")]
    df["first_change"] = pd.to_datetime(df["first_change"]).dt.date
    df["last_change"] = pd.to_datetime(df["last_change"]).dt.date
    df = df[df.first_change <= window_start]

    df["nname"] = [norm_text(n) for n in df.name]
    df["brand_tier"] = [brand_tier_from_name(r, n) for r, n in zip(df.retailer, df.name)]
    df["brand_token"] = [brand_token_from_name(r, n) for r, n in zip(df.retailer, df.name)]
    df["stripped"] = [strip_own_brand(r, n) for r, n in zip(df.retailer, df.name)]
    return df


def _score(w: dict, c: dict) -> tuple[str, float] | None:
    """v2's tier rules, applied to name-derived brands. None if unacceptable."""
    if w["brand_tier"] != c["brand_tier"]:
        # Never match a store brand against a name brand. v2's rule, and the
        # one that keeps the two analysis groups from contaminating each other.
        return None

    if w["brand_tier"] == OWN:
        left, right, floor, tier = w["stripped"], c["stripped"], NAME_SCORE_OWN_BRAND, OWN
    else:
        if not w["brand_token"] or w["brand_token"] != c["brand_token"]:
            return None
        left, right, floor, tier = w["nname"], c["nname"], NAME_SCORE_NATIONAL, NATIONAL

    score = fuzz.token_set_ratio(left, right)
    if score < floor:
        return None
    if fuzz.token_sort_ratio(left, right) < NAME_SORT_FLOOR:
        return None
    return (tier, score)


def match(wh: Warehouse, window_start: dt.date) -> pd.DataFrame:
    products = _products(wh, window_start)
    wow = products[products.retailer == "woolworths"].to_dict("records")
    col = products[products.retailer == "coles"].to_dict("records")
    log.info(
        "%s: %d Woolworths and %d Coles products eligible (history opens on/before %s)",
        PAIR_SET, len(wow), len(col), window_start,
    )

    # Block on (unit, quantity). The 2% tolerance is applied by probing the
    # three rounded buckets a tolerated size could land in, then re-checking the
    # real tolerance on each candidate — bucketing alone would drop pairs that
    # straddle a bucket edge.
    buckets: dict[tuple[str, float], list[dict]] = defaultdict(list)
    for c in col:
        buckets[(c["unit"], round(c["quantity"], 3))].append(c)

    candidates = []
    comparisons = 0
    for w in wow:
        seen: set[str] = set()
        for delta in (1 - SIZE_TOLERANCE, 1.0, 1 + SIZE_TOLERANCE):
            for c in buckets.get((w["unit"], round(w["quantity"] * delta, 3)), []):
                if c["product_id"] in seen:
                    continue
                seen.add(c["product_id"])
                lo, hi = sorted([w["quantity"], c["quantity"]])
                if hi <= 0 or (hi - lo) / hi > SIZE_TOLERANCE:
                    continue
                comparisons += 1
                result = _score(w, c)
                if result is None:
                    continue
                tier, score = result
                candidates.append(
                    {
                        "brand_tier": tier,
                        "name_score": score,
                        "wow_product_id": w["product_id"],
                        "coles_product_id": c["product_id"],
                        "wow_name": w["name"],
                        "coles_name": c["name"],
                        "wow_brand_token": w["brand_token"],
                        "coles_brand_token": c["brand_token"],
                        "canonical_qty": w["quantity"],
                        "canonical_unit": w["unit"],
                        "history_start": max(w["first_change"], c["first_change"]),
                        "history_end": min(w["last_change"], c["last_change"]),
                    }
                )

    # v2's assignment, verbatim in spirit: identical products outrank store-brand
    # substitutes at equal score, then descending score, then ids for determinism.
    candidates.sort(
        key=lambda r: (
            r["brand_tier"] != NATIONAL,
            -r["name_score"],
            str(r["wow_product_id"]),
            str(r["coles_product_id"]),
        )
    )
    used_wow: set = set()
    used_coles: set = set()
    accepted = []
    for cand in candidates:
        if cand["wow_product_id"] in used_wow or cand["coles_product_id"] in used_coles:
            continue
        used_wow.add(cand["wow_product_id"])
        used_coles.add(cand["coles_product_id"])
        accepted.append(cand)

    log.info(
        "%s: %d comparisons -> %d candidates -> %d accepted (%d national, %d own-brand)",
        PAIR_SET, comparisons, len(candidates), len(accepted),
        sum(1 for a in accepted if a["brand_tier"] == NATIONAL),
        sum(1 for a in accepted if a["brand_tier"] == OWN),
    )

    out = pd.DataFrame(accepted)
    if out.empty:
        raise RuntimeError("Backfill matching produced zero pairs")

    out.insert(0, "pair_set", PAIR_SET)
    out.insert(1, "pair_id", [
        f"{w}_{c}" for w, c in zip(out.wow_product_id, out.coles_product_id)
    ])
    out["brand_tier_basis"] = "derived_from_name"
    out["blocking_basis"] = "unit_and_quantity"
    out["search_term"] = None
    out["category"] = None
    return out


def run(wh: Warehouse, window_start: dt.date) -> pd.DataFrame:
    """Build both pair sets and write them to one table.

    The two sets are kept side by side rather than merged. They may cover the
    same products, and that overlap is the point: FR-3's pairs were accepted on
    a brand field and a human-authored block, so where the two agree, FR-4's
    weaker derivation has been checked against a stronger one. Merging them
    would throw that check away and leave a single set nobody can grade.
    """
    v2_pairs = extend_pairs.run(wh)
    wide_pairs = match(wh, window_start)

    columns = [
        "pair_set", "pair_id", "wow_product_id", "coles_product_id",
        "wow_name", "coles_name",
        "brand_tier", "brand_tier_basis", "wow_brand_token", "coles_brand_token",
        "name_score", "blocking_basis", "search_term", "category",
        "history_start", "history_end",
    ]
    for frame in (v2_pairs, wide_pairs):
        for col in columns:
            if col not in frame.columns:
                frame[col] = None

    pairs = pd.concat([v2_pairs[columns], wide_pairs[columns]], ignore_index=True)
    pairs["history_start"] = pd.to_datetime(pairs["history_start"]).dt.date
    pairs["history_end"] = pd.to_datetime(pairs["history_end"]).dt.date
    pairs["wow_product_id"] = pairs["wow_product_id"].astype(str)
    pairs["coles_product_id"] = pairs["coles_product_id"].astype(str)

    overlap = _overlap_report(v2_pairs, wide_pairs)
    wh.replace_table(TABLE, pairs)
    log.info("%s: %d rows (%s)", TABLE, len(pairs), overlap)
    return pairs


def _overlap_report(v2_pairs: pd.DataFrame, wide_pairs: pd.DataFrame) -> str:
    """How often the weak derivation reproduces the strong one, as a sentence.

    This is the quality number for the wide pair set. No threshold inside this
    module can be trusted as a measure of its own output; agreement with pairs
    that were accepted on a retailer brand field and a human-authored block can.

    Only Woolworths products present in both sets can be compared. Agreement
    means the wide matcher landed on a Coles product that v2 also chose.

    Membership, not equality, because v2's pair identity is per (wow, coles)
    combination: five products here carry more than one v2 pair, having been
    matched to different Coles items on different days as names drifted across
    the fuzzy threshold. The wide matcher is one-to-one and offers a single
    answer, so the fair test is whether that answer is among v2's — an equality
    test against an arbitrarily chosen one of them would score the matcher on a
    coin flip.
    """
    v2_by_wow: dict[str, set[str]] = defaultdict(set)
    for w, c in zip(v2_pairs.wow_product_id.astype(str),
                    v2_pairs.coles_product_id.astype(str)):
        v2_by_wow[w].add(c)

    wide_by_wow = dict(zip(wide_pairs.wow_product_id.astype(str),
                           wide_pairs.coles_product_id.astype(str)))

    shared = sorted(set(v2_by_wow) & set(wide_by_wow))
    if not shared:
        return "no overlap between pair sets"
    agree = sum(1 for w in shared if wide_by_wow[w] in v2_by_wow[w])
    return (
        f"{len(shared)} products in both sets, wide matcher agrees with v2 on "
        f"{agree} ({agree / len(shared):.0%})"
    )
