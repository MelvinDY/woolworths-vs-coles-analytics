"""Build the static dashboard: read marts from DuckDB, embed data as JSON into
the HTML template, write dashboard/index.html (fully self-contained)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import duckdb

log = logging.getLogger(__name__)

DASH_DIR = Path(__file__).resolve().parent
TEMPLATE = DASH_DIR / "template.html"
OUTPUT = DASH_DIR / "index.html"
PLACEHOLDER = "/*__DATA__*/"


def latest_snapshot(con: duckdb.DuckDBPyConnection) -> str:
    return str(con.execute("SELECT max(snapshot_date) FROM stg_prices").fetchone()[0])


def pair_stats(con: duckdb.DuckDBPyConnection, snap: str, match_type: str) -> dict:
    row = con.execute(
        """
        SELECT
            count(*)                                              AS n,
            count(*) FILTER (WHERE cheaper_at = 'woolworths')     AS wow_wins,
            count(*) FILTER (WHERE cheaper_at = 'coles')          AS coles_wins,
            count(*) FILTER (WHERE cheaper_at = 'tie')            AS ties,
            round(median(abs(gap_dollars)) FILTER (WHERE cheaper_at != 'tie'), 2) AS median_abs_gap,
            round(sum(wow_price), 2)                              AS wow_total,
            round(sum(coles_price), 2)                            AS coles_total
        FROM mart_pair_comparison
        WHERE snapshot_date = ? AND match_type = ?
        """,
        [snap, match_type],
    ).fetchone()
    keys = ["n", "wow_wins", "coles_wins", "ties", "median_abs_gap", "wow_total", "coles_total"]
    return dict(zip(keys, row))


def build_payload(con: duckdb.DuckDBPyConnection) -> dict:
    snap = latest_snapshot(con)

    basket_rows = con.execute(
        """
        SELECT category, retailer, round(sum(price), 2) AS total, count(*) AS n_terms
        FROM mart_basket
        WHERE snapshot_date = ?
        GROUP BY 1, 2
        ORDER BY 1, 2
        """,
        [snap],
    ).fetchall()
    basket: dict = {}
    for category, retailer, total, n_terms in basket_rows:
        basket.setdefault(category, {})[retailer] = {"total": total, "n_terms": n_terms}
    # comparable categories only (both retailers present)
    basket = {c: v for c, v in basket.items() if len(v) == 2}

    unit_rows = con.execute(
        """
        SELECT category, unit_price_basis, retailer, median_unit_price_per_100, n_products
        FROM mart_category_unit_price
        WHERE snapshot_date = ?
        ORDER BY category, unit_price_basis, retailer
        """,
        [snap],
    ).fetchall()
    unit: dict = {}
    for category, basis, retailer, median_price, n in unit_rows:
        unit.setdefault(f"{category}|{basis}", {"category": category, "basis": basis})[
            retailer
        ] = {"median": median_price, "n": n}
    unit_list = [v for v in unit.values() if "woolworths" in v and "coles" in v]

    top_gaps = con.execute(
        """
        SELECT wow_name, wow_size, wow_price, coles_name, coles_size, coles_price,
               gap_dollars, gap_pct_of_coles, cheaper_at, search_term
        FROM mart_pair_comparison
        WHERE snapshot_date = ? AND match_type = 'national_brand' AND cheaper_at != 'tie'
        ORDER BY abs(gap_dollars) DESC
        LIMIT 12
        """,
        [snap],
    ).fetchall()
    gap_cols = ["wow_name", "wow_size", "wow_price", "coles_name", "coles_size",
                "coles_price", "gap_dollars", "gap_pct", "cheaper_at", "search_term"]

    specials = {
        r[0]: {"n": r[1], "pct_on_special": r[2], "median_discount_pct": r[3]}
        for r in con.execute(
            """
            SELECT retailer, n_products, pct_on_special, median_discount_pct
            FROM mart_specials WHERE snapshot_date = ?
            """,
            [snap],
        ).fetchall()
    }

    n_products, n_terms = con.execute(
        "SELECT count(*), count(DISTINCT search_term) FROM stg_prices WHERE snapshot_date = ?",
        [snap],
    ).fetchone()

    return {
        "snapshot_date": snap,
        "n_products": n_products,
        "n_terms": n_terms,
        "pairs_identical": pair_stats(con, snap, "national_brand"),
        "pairs_own_brand": pair_stats(con, snap, "own_brand"),
        "basket": basket,
        "unit_prices": unit_list,
        "top_gaps": [dict(zip(gap_cols, r)) for r in top_gaps],
        "specials": specials,
    }


def run(con: duckdb.DuckDBPyConnection) -> Path:
    payload = build_payload(con)
    html = TEMPLATE.read_text(encoding="utf-8")
    if PLACEHOLDER not in html:
        raise RuntimeError(f"Placeholder {PLACEHOLDER} missing from template")
    html = html.replace(
        PLACEHOLDER, "const DATA = " + json.dumps(payload, default=str) + ";"
    )
    OUTPUT.write_text(html, encoding="utf-8")
    log.info("Dashboard written to %s", OUTPUT)
    return OUTPUT
