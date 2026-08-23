-- Specials behaviour per retailer on a given day: share of lines flagged on
-- special and the median discount depth where a genuine was-price exists.
-- Grain: one row per (snapshot_date, retailer).
-- Ported from transform/sql/05_mart_specials.sql, logic unchanged.
--
-- This is the same-day view. What a special actually *did* over time — whether
-- the price came back up afterwards — is mart_special_behaviour.

select
    snapshot_date,
    retailer,
    count(*)                                                          as n_products,
    round(avg(case when is_on_special then 1.0 else 0 end) * 100, 1)  as pct_on_special,
    round(median(case
        when is_on_special and was_price is not null and was_price > price
            then (was_price - price) / was_price * 100
    end), 1)                                                          as median_discount_pct

from {{ ref('stg_prices') }}
group by 1, 2
