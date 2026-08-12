-- Median normalized unit price ($ per 100 g / 100 ml) per category per
-- retailer, over top-10 ranked hits with a parseable weight/volume unit price.
-- Categories are kept only when both retailers have >= 5 comparable rows.
-- Grain: one row per (snapshot_date, category, unit_price_basis, retailer).
CREATE OR REPLACE TABLE mart_category_unit_price AS
WITH comparable AS (
    SELECT retailer, category, snapshot_date, unit_price_basis, unit_price_per_100
    FROM stg_prices
    WHERE unit_price_per_100 IS NOT NULL
      AND unit_price_basis IN ('per_100g', 'per_100ml')
      AND result_rank <= 10
),

per_retailer AS (
    SELECT
        snapshot_date,
        category,
        unit_price_basis,
        retailer,
        count(*)                             AS n_products,
        round(median(unit_price_per_100), 2) AS median_unit_price_per_100
    FROM comparable
    GROUP BY 1, 2, 3, 4
),

qualified AS (
    SELECT snapshot_date, category, unit_price_basis
    FROM per_retailer
    GROUP BY 1, 2, 3
    HAVING count(*) = 2 AND min(n_products) >= 5
)

SELECT p.*
FROM per_retailer p
JOIN qualified q USING (snapshot_date, category, unit_price_basis);
