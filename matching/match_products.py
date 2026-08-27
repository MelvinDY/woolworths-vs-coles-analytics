"""Cross-retailer product matching (entity resolution).

Candidate pairs are generated within the same search term only, then accepted
by tier:

  tier 1 'national_brand' — same normalized brand, canonical size within 2 %,
                            fuzzy name score >= 80
  tier 2 'own_brand'      — both products are the retailer's home brand,
                            size within 2 %, fuzzy name score >= 75
                            (substitutes, not identical products)

One-to-one assignment: pairs are accepted greedily by descending score, and a
product participates in at most one pair. Results are written to the
matched_pairs table in the target warehouse with score and tier for
auditability, and dbt picks them up from there as a declared source (rapidfuzz
has no SQL equivalent, so pretending dbt builds this table would be a lie in
the lineage graph).

The rules themselves are untouched from v1 — entity resolution is this repo's
strongest asset and the v2 port was not allowed to move a single pair.
"""

from __future__ import annotations

import logging
import re

import pandas as pd
from rapidfuzz import fuzz

from matching.brands import OWN_BRAND_FIELDS as OWN_BRANDS
from warehouse import Warehouse

log = logging.getLogger(__name__)

TABLE = "matched_pairs"

NAME_SCORE_NATIONAL = 80
NAME_SCORE_OWN_BRAND = 75
SIZE_TOLERANCE = 0.02

# OWN_BRANDS moved to matching/brands.py so v3's backfill and this matcher
# answer "store brand or name brand" from one definition. The set is imported
# unchanged and this module's behaviour is identical — the rules stay untouched,
# as the docstring above promises.


def norm_text(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def is_own_brand(retailer: str, brand: str) -> bool:
    return norm_text(brand) in OWN_BRANDS.get(retailer, set())


def sizes_match(a: pd.Series, b: pd.Series) -> bool:
    if pd.isna(a.canonical_qty) or pd.isna(b.canonical_qty):
        return False
    if a.canonical_unit != b.canonical_unit:
        return False
    lo, hi = sorted([a.canonical_qty, b.canonical_qty])
    return lo > 0 and (hi - lo) / hi <= SIZE_TOLERANCE


def score_pair(w: pd.Series, c: pd.Series) -> tuple[str, float] | None:
    """Return (match_type, name_score) if the pair is acceptable, else None."""
    if not sizes_match(w, c):
        return None
    name_score = fuzz.token_set_ratio(norm_text(w["name"]), norm_text(c["name"]))

    w_own, c_own = is_own_brand("woolworths", w.brand), is_own_brand("coles", c.brand)
    if w_own and c_own:
        return ("own_brand", name_score) if name_score >= NAME_SCORE_OWN_BRAND else None
    if w_own or c_own:
        return None  # never match a home brand against a national brand
    if norm_text(w.brand) != norm_text(c.brand) or not norm_text(w.brand):
        return None
    return ("national_brand", name_score) if name_score >= NAME_SCORE_NATIONAL else None


def match_snapshot(wh: Warehouse, snapshot_date: str) -> pd.DataFrame:
    df = wh.query_df(
        """
        SELECT retailer, product_id, name, brand, size_raw, canonical_qty,
               canonical_unit, price, search_term, category, snapshot_date
        FROM stg_prices
        WHERE snapshot_date = ?
        ORDER BY retailer, search_term, product_id
        """,
        [snapshot_date],
    )

    candidates = []
    for term, group in df.groupby("search_term"):
        wow = group[group.retailer == "woolworths"]
        col = group[group.retailer == "coles"]
        for _, w in wow.iterrows():
            for _, c in col.iterrows():
                result = score_pair(w, c)
                if result is None:
                    continue
                match_type, name_score = result
                candidates.append(
                    {
                        "snapshot_date": w.snapshot_date,
                        "search_term": term,
                        "category": w.category,
                        "match_type": match_type,
                        "name_score": name_score,
                        "wow_product_id": w.product_id,
                        "wow_name": w["name"],
                        "wow_brand": w.brand,
                        "wow_size": w.size_raw,
                        "wow_price": w.price,
                        "coles_product_id": c.product_id,
                        "coles_name": c["name"],
                        "coles_brand": c.brand,
                        "coles_size": c.size_raw,
                        "coles_price": c.price,
                    }
                )

    # Greedy one-to-one assignment by descending score (identical products
    # outrank own-brand substitutes at equal name score). Product-id tiebreak
    # keeps the assignment deterministic across runs.
    candidates.sort(
        key=lambda r: (
            r["match_type"] != "national_brand",
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
        "%s: %d candidate pairs -> %d accepted (%d identical, %d own-brand)",
        snapshot_date,
        len(candidates),
        len(accepted),
        sum(1 for a in accepted if a["match_type"] == "national_brand"),
        sum(1 for a in accepted if a["match_type"] == "own_brand"),
    )
    return pd.DataFrame(accepted)


def run(wh: Warehouse) -> None:
    rows = wh.query_rows("SELECT DISTINCT snapshot_date FROM stg_prices ORDER BY 1")
    days = [pd.Timestamp(r[0]).date() for r in rows]
    frames = [match_snapshot(wh, str(day)) for day in days]
    matched = pd.concat([f for f in frames if not f.empty], ignore_index=True)
    if matched.empty:
        raise RuntimeError("Product matching produced zero pairs")
    # A date, not a midnight timestamp. Both drivers hand dates back as pandas
    # Timestamps, and writing them straight back out lands this one column as
    # TIMESTAMP while every other snapshot_date in the warehouse is a DATE.
    # DuckDB compares the two happily; Snowflake's implicit casts are less
    # forgiving, and a grain column with a different type on each engine is
    # exactly the kind of divergence this project is meant not to have.
    matched["snapshot_date"] = pd.to_datetime(matched["snapshot_date"]).dt.date
    wh.replace_table(TABLE, matched)
