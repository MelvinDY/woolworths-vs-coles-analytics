"""FR-3 — extend v2's matched pairs backwards over the Hot Prices history.

There is no matching in this module, and that is the point.

Hot Prices keys products by the retailers' own product ids, and so does this
repo, so v2's accepted pairs join to three years of history on
`(retailer, product_id)` with an equality predicate. No fuzzy scoring, no new
accept rules, no second opinion about which Woolworths product is which Coles
product. v2's matcher is this repo's strongest asset and v3 does not get to
re-litigate it — it just gets to ask what those same pairs cost in 2024.

Brand tier comes free here. v2's `match_type` is already `national_brand` or
`own_brand`, decided against the retailer-supplied brand *field*, which is a
stronger signal than the name-prefix derivation FR-4 has to fall back on. These
pairs are therefore the control set for the wider match: where the two pair sets
overlap, FR-4's weaker mechanism can be scored against this one.

Pairs where either side has no Hot Prices history are dropped and counted. A
pair with history on one side only is not half a pair; it is no observation of a
gap at all.
"""

from __future__ import annotations

import logging

import pandas as pd

from warehouse import Warehouse

log = logging.getLogger(__name__)

PAIR_SET = "v2_extended"


def run(wh: Warehouse) -> pd.DataFrame:
    pairs = wh.query_df(
        """
        SELECT pair_id, wow_product_id, coles_product_id,
               wow_name, coles_name, search_term, category,
               match_type, name_score
        FROM int_matched_pairs
        """
    )
    if pairs.empty:
        raise RuntimeError("int_matched_pairs is empty — has the v2 pipeline run?")

    covered = wh.query_df(
        """
        SELECT retailer, product_id,
               min(change_date) AS first_change,
               max(change_date) AS last_change,
               count(*)         AS n_changes
        FROM raw_hotprices
        GROUP BY retailer, product_id
        """
    )

    wow = covered[covered.retailer == "woolworths"].set_index("product_id")
    col = covered[covered.retailer == "coles"].set_index("product_id")

    pairs["wow_product_id"] = pairs["wow_product_id"].astype(str)
    pairs["coles_product_id"] = pairs["coles_product_id"].astype(str)

    joined = (
        pairs.join(wow[["first_change", "last_change", "n_changes"]].add_prefix("wow_"),
                   on="wow_product_id")
             .join(col[["first_change", "last_change", "n_changes"]].add_prefix("coles_"),
                   on="coles_product_id")
    )

    have_both = joined["wow_first_change"].notna() & joined["coles_first_change"].notna()
    dropped = int((~have_both).sum())
    extended = joined[have_both].copy()

    # The pair's history starts when BOTH sides start being observed. Before
    # that date one side has no price and there is no gap to measure, so this is
    # the honest left edge of the series (PRD-v3 §5.2 rule 3).
    extended["history_start"] = extended[["wow_first_change", "coles_first_change"]].max(axis=1)
    extended["history_end"] = extended[["wow_last_change", "coles_last_change"]].min(axis=1)

    out = pd.DataFrame(
        {
            "pair_set": PAIR_SET,
            "pair_id": extended["pair_id"],
            "wow_product_id": extended["wow_product_id"],
            "coles_product_id": extended["coles_product_id"],
            "wow_name": extended["wow_name"],
            "coles_name": extended["coles_name"],
            # v2 decided this against the retailers' brand fields. Carried
            # through unchanged rather than re-derived from the name.
            "brand_tier": extended["match_type"],
            "brand_tier_basis": "retailer_brand_field",
            "wow_brand_token": None,
            "coles_brand_token": None,
            "name_score": extended["name_score"],
            "blocking_basis": "v2_search_term",
            "search_term": extended["search_term"],
            "category": extended["category"],
            "history_start": extended["history_start"],
            "history_end": extended["history_end"],
        }
    )

    log.info(
        "%s: %d of %d v2 pairs have history on both sides (%d dropped) — %d national, %d own-brand",
        PAIR_SET, len(out), len(pairs), dropped,
        int((out.brand_tier == "national_brand").sum()),
        int((out.brand_tier == "own_brand").sum()),
    )
    return out
