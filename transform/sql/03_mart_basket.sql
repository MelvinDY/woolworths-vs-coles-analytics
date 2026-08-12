-- Basket comparison: cheapest relevant line (top-5 ranked search hits) per
-- search term per retailer, restricted to terms where BOTH retailers have a
-- candidate so the totals are comparable.
-- Grain: one row per (snapshot_date, category, search_term, retailer).
CREATE OR REPLACE TABLE mart_basket AS
WITH relevant AS (
    SELECT retailer, search_term, category, snapshot_date, product_id, name, price,
           row_number() OVER (
               PARTITION BY retailer, search_term, snapshot_date
               ORDER BY price, result_rank
           ) AS price_rank
    FROM stg_prices
    WHERE result_rank <= 5
),

cheapest AS (
    SELECT retailer, search_term, category, snapshot_date, product_id, name, price
    FROM relevant
    WHERE price_rank = 1
),

both_sides AS (
    SELECT search_term, snapshot_date
    FROM cheapest
    GROUP BY 1, 2
    HAVING count(DISTINCT retailer) = 2
)

SELECT c.*
FROM cheapest c
JOIN both_sides b USING (search_term, snapshot_date);
