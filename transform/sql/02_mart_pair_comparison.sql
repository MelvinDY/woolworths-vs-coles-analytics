-- Matched product pairs with price gaps and winner flag.
-- Grain: one row per (wow_product_id, coles_product_id, snapshot_date).
CREATE OR REPLACE TABLE mart_pair_comparison AS
SELECT
    snapshot_date,
    search_term,
    category,
    match_type,
    name_score,
    wow_product_id,
    wow_name,
    wow_size,
    wow_price,
    coles_product_id,
    coles_name,
    coles_size,
    coles_price,
    round(coles_price - wow_price, 2)                    AS gap_dollars,
    round((coles_price - wow_price) / coles_price * 100, 1) AS gap_pct_of_coles,
    CASE
        WHEN wow_price < coles_price THEN 'woolworths'
        WHEN coles_price < wow_price THEN 'coles'
        ELSE 'tie'
    END AS cheaper_at
FROM int_matched_products;
