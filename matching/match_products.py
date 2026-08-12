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
int_matched_products table in DuckDB with score and tier for auditability.
"""

from __future__ import annotations

import logging
import re

import duckdb
import pandas as pd
from rapidfuzz import fuzz

log = logging.getLogger(__name__)

NAME_SCORE_NATIONAL = 80
NAME_SCORE_OWN_BRAND = 75
SIZE_TOLERANCE = 0.02

OWN_BRANDS = {
    "woolworths": {"woolworths", "essentials", "macro", "macro organic"},
    "coles": {"coles", "coles simply", "coles finest", "coles natures kitchen", "coles kitchen"},
}


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


def match_snapshot(con: duckdb.DuckDBPyConnection, snapshot_date: str) -> pd.DataFrame:
    df = con.execute(
        """
        SELECT retailer, product_id, name, brand, size_raw, canonical_qty,
               canonical_unit, price, search_term, category, snapshot_date
        FROM stg_prices
        WHERE snapshot_date = ?
        ORDER BY retailer, search_term, product_id
        """,
        [snapshot_date],
    ).df()

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


def run(con: duckdb.DuckDBPyConnection) -> None:
    snapshots = [r[0] for r in con.execute(
        "SELECT DISTINCT snapshot_date FROM stg_prices ORDER BY 1"
    ).fetchall()]
    frames = [match_snapshot(con, str(s)) for s in snapshots]
    matched = pd.concat([f for f in frames if not f.empty], ignore_index=True)
    if matched.empty:
        raise RuntimeError("Product matching produced zero pairs")
    con.register("matched_df", matched)
    con.execute("CREATE OR REPLACE TABLE int_matched_products AS SELECT * FROM matched_df")
    con.unregister("matched_df")
    log.info("int_matched_products: %d rows", len(matched))
