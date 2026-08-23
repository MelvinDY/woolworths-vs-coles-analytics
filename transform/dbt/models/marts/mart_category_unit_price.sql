-- Median normalized unit price ($ per 100 g / 100 ml) per category per
-- retailer, over top-10 ranked hits with a parseable weight/volume unit price.
-- Categories are kept only when both retailers have >= 5 comparable rows.
-- Grain: one row per (snapshot_date, category, unit_price_basis, retailer).
-- Ported from transform/sql/04_mart_category_unit_price.sql, logic unchanged.

with comparable as (

    select retailer, category, snapshot_date, unit_price_basis, unit_price_per_100
    from {{ ref('stg_prices') }}
    where unit_price_per_100 is not null
      and unit_price_basis in ('per_100g', 'per_100ml')
      and result_rank <= 10

),

per_retailer as (

    select
        snapshot_date,
        category,
        unit_price_basis,
        retailer,
        count(*)                             as n_products,
        round(median(unit_price_per_100), 2) as median_unit_price_per_100
    from comparable
    group by 1, 2, 3, 4

),

qualified as (

    select snapshot_date, category, unit_price_basis
    from per_retailer
    group by 1, 2, 3
    having count(*) = 2
       and min(n_products) >= 5

)

select p.*
from per_retailer p
join qualified q
    on p.snapshot_date = q.snapshot_date
   and p.category = q.category
   and p.unit_price_basis = q.unit_price_basis
