-- Specials behaviour per retailer: share of lines flagged on special and the
-- median discount depth where a genuine was-price exists.
-- Grain: one row per (snapshot_date, retailer).
CREATE OR REPLACE TABLE mart_specials AS
SELECT
    snapshot_date,
    retailer,
    count(*)                                            AS n_products,
    round(avg(CASE WHEN is_on_special THEN 1.0 ELSE 0 END) * 100, 1) AS pct_on_special,
    round(median(CASE
        WHEN is_on_special AND was_price IS NOT NULL AND was_price > price
            THEN (was_price - price) / was_price * 100
    END), 1)                                            AS median_discount_pct
FROM stg_prices
GROUP BY 1, 2;
