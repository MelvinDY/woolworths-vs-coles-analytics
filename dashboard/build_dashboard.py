"""Build the static dashboard: read marts from the warehouse, embed the data as
JSON in the HTML template, write dashboard/index.html (fully self-contained).

Reads through the warehouse abstraction rather than a DuckDB connection, so the
page can be built from either target. Every query here is plain SQL both engines
accept — no FILTER clauses, no engine-specific functions.
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path

from warehouse import Warehouse

log = logging.getLogger(__name__)

DASH_DIR = Path(__file__).resolve().parent
TEMPLATE = DASH_DIR / "template.html"
OUTPUT = DASH_DIR / "index.html"
PLACEHOLDER = "/*__DATA__*/"

# A line drawn between two observations more than this many days apart is
# spanning a hole in the collection, not a stable price. The dashboard draws
# those segments dashed.
CONSECUTIVE_DAY_TOLERANCE = 2
N_HEADLINE_PAIRS = 6


def num(value) -> float | None:
    """A price or None — never a NaN.

    Both drivers return missing numerics as float('nan'), which is not None, is
    not falsy, and survives `is None` checks. A gap day that reaches the browser
    as NaN instead of null is exactly the bug this project cares most about
    avoiding, so nothing numeric leaves this module without passing through here.
    """
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def scrub(obj):
    """Recursively replace NaN with None so the embedded JSON is real JSON."""
    if isinstance(obj, dict):
        return {k: scrub(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [scrub(v) for v in obj]
    if isinstance(obj, float):
        return None if math.isnan(obj) else obj
    return obj


def latest_snapshot(wh: Warehouse) -> str:
    return str(wh.query_one("SELECT max(snapshot_date) FROM stg_prices")[0])[:10]


def collection_window(wh: Warehouse) -> dict:
    first, last, n_days = wh.query_one(
        "SELECT min(snapshot_date), max(snapshot_date), count(DISTINCT snapshot_date) "
        "FROM int_product_prices_daily"
    )
    first, last = str(first)[:10], str(last)[:10]
    return {
        "first_day": first,
        "last_day": last,
        "n_days": int(n_days),
        # The denominator that matters for any history claim: how many days were
        # collected out of how many days elapsed.
        "calendar_days": (
            wh.query_one(
                "SELECT max(snapshot_date) - min(snapshot_date) FROM int_product_prices_daily"
            )[0]
        ),
    }


def pair_stats(wh: Warehouse, snap: str, match_type: str) -> dict:
    row = wh.query_one(
        """
        SELECT
            count(*)                                                    AS n,
            sum(CASE WHEN cheaper_at = 'woolworths' THEN 1 ELSE 0 END)  AS wow_wins,
            sum(CASE WHEN cheaper_at = 'coles' THEN 1 ELSE 0 END)       AS coles_wins,
            sum(CASE WHEN cheaper_at = 'tie' THEN 1 ELSE 0 END)         AS ties,
            round(median(CASE WHEN cheaper_at <> 'tie' THEN abs(gap_dollars) END), 2) AS median_abs_gap,
            round(sum(wow_price), 2)                                    AS wow_total,
            round(sum(coles_price), 2)                                  AS coles_total
        FROM mart_pair_comparison
        WHERE snapshot_date = ? AND match_type = ?
        """,
        [snap, match_type],
    )
    keys = ["n", "wow_wins", "coles_wins", "ties", "median_abs_gap", "wow_total", "coles_total"]
    return {k: (int(v) if k in ("n", "wow_wins", "coles_wins", "ties") else v)
            for k, v in zip(keys, row)}


def basket_history(wh: Warehouse, days: list[str]) -> dict:
    """Basket totals over time, on a fixed basket.

    mart_basket keeps a term only on days where both chains answered it, so its
    membership drifts from day to day. Summing it per day would produce a line
    whose movement is partly composition change — the classic way to make a
    price index say whatever you want. This restricts to the terms present for
    both retailers on every collected day, so the only thing that moves is price.
    """
    complete_terms_cte = """
        WITH complete_terms AS (
            SELECT search_term
            FROM mart_basket
            GROUP BY search_term
            HAVING count(DISTINCT snapshot_date) = (
                SELECT count(DISTINCT snapshot_date) FROM mart_basket
            )
            AND count(DISTINCT retailer) = 2
        )
    """
    rows = wh.query_rows(
        complete_terms_cte + """
        SELECT b.snapshot_date, b.retailer, round(sum(b.price), 2) AS total, count(*) AS n_terms
        FROM mart_basket b
        JOIN complete_terms c ON c.search_term = b.search_term
        GROUP BY b.snapshot_date, b.retailer
        ORDER BY b.snapshot_date, b.retailer
        """
    )
    dropped = [
        r[0] for r in wh.query_rows(
            complete_terms_cte + """
            SELECT DISTINCT search_term FROM mart_basket
            WHERE search_term NOT IN (SELECT search_term FROM complete_terms)
            ORDER BY 1
            """
        )
    ]
    by_day: dict[str, dict] = {}
    n_terms = 0
    for day, retailer, total, n in rows:
        by_day.setdefault(str(day)[:10], {})[retailer] = num(total)
        n_terms = max(n_terms, int(n))
    return {
        "n_terms": n_terms,
        # Named, not just counted. Dropping lines to hold the basket constant is
        # the right call for a time series and it does move the total, so the
        # page has to say which lines went and let the reader judge.
        "dropped_terms": dropped,
        "woolworths": [by_day.get(d, {}).get("woolworths") for d in days],
        "coles": [by_day.get(d, {}).get("coles") for d in days],
    }


def headline_pair_histories(wh: Warehouse, days: list[str]) -> list[dict]:
    """The pairs whose prices actually moved — a flat line teaches nothing.

    Ranked by total day-to-day movement across both chains, over identical
    products only, and only pairs seen on every collected day (a series with
    holes makes a poor headline even though the marts handle it correctly).
    """
    rows = wh.query_rows(
        """
        SELECT pair_id, snapshot_date, wow_name, wow_size, coles_name,
               wow_price, coles_price, is_gap_day
        FROM mart_price_history
        WHERE match_type = 'national_brand'
        ORDER BY pair_id, snapshot_date
        """
    )

    series: dict[str, dict] = {}
    for pair_id, day, wow_name, wow_size, coles_name, wow_price, coles_price, gap in rows:
        s = series.setdefault(pair_id, {
            "label": wow_name, "size": wow_size, "coles_label": coles_name,
            "wow": {}, "coles": {},
        })
        s["wow"][str(day)[:10]] = num(wow_price)
        s["coles"][str(day)[:10]] = num(coles_price)

    def movement(s: dict) -> float:
        total = 0.0
        for side in ("wow", "coles"):
            values = [s[side].get(d) for d in days]
            for a, b in zip(values, values[1:]):
                if a is not None and b is not None:
                    total += abs(b - a)
        return total

    complete = [
        s for s in series.values()
        if all(s["wow"].get(d) is not None and s["coles"].get(d) is not None for d in days)
    ]
    complete.sort(key=movement, reverse=True)

    return [
        {
            "label": s["label"],
            "size": s["size"],
            "coles_label": s["coles_label"],
            "wow": [s["wow"].get(d) for d in days],
            "coles": [s["coles"].get(d) for d in days],
        }
        for s in complete[:N_HEADLINE_PAIRS]
    ]


def special_behaviour(wh: Warehouse) -> dict:
    """The history-only finding: what a 'Special' badge actually did to a price."""
    kinds = {
        str(k): int(n) for k, n in wh.query_rows(
            "SELECT special_kind, count(*) FROM mart_special_behaviour "
            "WHERE special_kind IS NOT NULL GROUP BY special_kind"
        )
    }
    n_episodes, n_unresolved, median_age = wh.query_one(
        """
        SELECT count(*),
               sum(CASE WHEN outcome IN ('ongoing', 'no_baseline') THEN 1 ELSE 0 END),
               round(median(baseline_age_days), 0)
        FROM mart_special_behaviour
        """
    )
    was_tested, was_matched = wh.query_one(
        """
        SELECT count(*), sum(CASE WHEN was_price_matches_observed THEN 1 ELSE 0 END)
        FROM mart_special_behaviour
        WHERE was_price_matches_observed IS NOT NULL
        """
    )
    not_cuts = wh.query_rows(
        """
        SELECT retailer, name, size_raw, baseline_before, lowest_special_price,
               baseline_age_days, special_kind
        FROM mart_special_behaviour
        WHERE special_kind IN ('no_change', 'price_rise')
        ORDER BY lowest_special_price - baseline_before DESC, name
        """
    )
    cols = ["retailer", "name", "size", "baseline", "special_price", "baseline_age_days", "kind"]

    return {
        "n_episodes": int(n_episodes),
        "n_with_baseline": sum(kinds.values()),
        "n_unresolved": int(n_unresolved or 0),
        "median_baseline_age_days": None if median_age is None else int(median_age),
        "kinds": {
            "price_cut": kinds.get("price_cut", 0),
            "no_change": kinds.get("no_change", 0),
            "price_rise": kinds.get("price_rise", 0),
        },
        "was_price_tested": int(was_tested or 0),
        "was_price_matched": int(was_matched or 0),
        "not_cuts": [dict(zip(cols, r)) for r in not_cuts],
    }


def build_payload(wh: Warehouse) -> dict:
    snap = latest_snapshot(wh)
    window = collection_window(wh)
    days = [str(r[0])[:10] for r in wh.query_rows(
        "SELECT DISTINCT snapshot_date FROM int_product_prices_daily ORDER BY 1"
    )]

    basket_rows = wh.query_rows(
        """
        SELECT category, retailer, round(sum(price), 2) AS total, count(*) AS n_terms
        FROM mart_basket
        WHERE snapshot_date = ?
        GROUP BY category, retailer
        ORDER BY category, retailer
        """,
        [snap],
    )
    basket: dict = {}
    for category, retailer, total, n_terms in basket_rows:
        basket.setdefault(category, {})[retailer] = {"total": total, "n_terms": int(n_terms)}
    # comparable categories only (both retailers present)
    basket = {c: v for c, v in basket.items() if len(v) == 2}

    unit_rows = wh.query_rows(
        """
        SELECT category, unit_price_basis, retailer, median_unit_price_per_100, n_products
        FROM mart_category_unit_price
        WHERE snapshot_date = ?
        ORDER BY category, unit_price_basis, retailer
        """,
        [snap],
    )
    unit: dict = {}
    for category, basis, retailer, median_price, n in unit_rows:
        unit.setdefault(f"{category}|{basis}", {"category": category, "basis": basis})[
            retailer
        ] = {"median": median_price, "n": int(n)}
    unit_list = [v for v in unit.values() if "woolworths" in v and "coles" in v]

    top_gaps = wh.query_rows(
        """
        SELECT wow_name, wow_size, wow_price, coles_name, coles_size, coles_price,
               gap_dollars, gap_pct_of_coles, cheaper_at, search_term
        FROM mart_pair_comparison
        WHERE snapshot_date = ? AND match_type = 'national_brand' AND cheaper_at <> 'tie'
        ORDER BY abs(gap_dollars) DESC
        LIMIT 12
        """,
        [snap],
    )
    gap_cols = ["wow_name", "wow_size", "wow_price", "coles_name", "coles_size",
                "coles_price", "gap_dollars", "gap_pct", "cheaper_at", "search_term"]

    specials = {
        r[0]: {"n": int(r[1]), "pct_on_special": r[2], "median_discount_pct": r[3]}
        for r in wh.query_rows(
            """
            SELECT retailer, n_products, pct_on_special, median_discount_pct
            FROM mart_specials WHERE snapshot_date = ?
            """,
            [snap],
        )
    }

    n_products, n_terms = wh.query_one(
        "SELECT count(*), count(DISTINCT search_term) FROM stg_prices WHERE snapshot_date = ?",
        [snap],
    )

    n_versions, n_tracked, n_changes = wh.query_one(
        """
        SELECT count(*), count(DISTINCT product_key),
               sum(CASE WHEN dbt_valid_to IS NOT NULL THEN 1 ELSE 0 END)
        FROM snap_product_prices
        """
    )

    return {
        "snapshot_date": snap,
        "n_products": int(n_products),
        "n_terms": int(n_terms),
        "collection": window,
        "days": days,
        "consecutive_tolerance": CONSECUTIVE_DAY_TOLERANCE,
        "pairs_identical": pair_stats(wh, snap, "national_brand"),
        "pairs_own_brand": pair_stats(wh, snap, "own_brand"),
        "basket": basket,
        "unit_prices": unit_list,
        "top_gaps": [dict(zip(gap_cols, r)) for r in top_gaps],
        "specials": specials,
        "basket_history": basket_history(wh, days),
        "pair_histories": headline_pair_histories(wh, days),
        "special_behaviour": special_behaviour(wh),
        "scd2": {
            "versions": int(n_versions),
            "products": int(n_tracked),
            "closed_versions": int(n_changes or 0),
        },
    }


def run(wh: Warehouse) -> Path:
    payload = scrub(build_payload(wh))
    html = TEMPLATE.read_text(encoding="utf-8")
    if PLACEHOLDER not in html:
        raise RuntimeError(f"Placeholder {PLACEHOLDER} missing from template")
    html = html.replace(
        PLACEHOLDER,
        "const DATA = " + json.dumps(payload, default=str, allow_nan=False) + ";",
    )
    OUTPUT.write_text(html, encoding="utf-8")
    log.info("Dashboard written to %s", OUTPUT)
    return OUTPUT
