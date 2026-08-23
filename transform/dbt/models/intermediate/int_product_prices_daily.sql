-- One row per (retailer, product_id, snapshot_date): the product-level daily
-- price series, and the only model the SCD2 snapshot and the history marts are
-- allowed to read.
--
-- stg_prices carries a row per search term because the basket mart needs one.
-- A snapshot keyed on (retailer, product_id) cannot: the same milk answering
-- "full cream milk 2l" and "milk" would be two competing current rows for one
-- key. This model resolves that once, deterministically — best-ranked hit
-- wins, search term breaks ties — so every history model downstream is reading
-- the same single price per product per day.

select
    retailer,
    product_id,
    name,
    brand,
    size_raw,
    price,
    was_price,
    is_on_special,
    unit_price_per_100,
    unit_price_basis,
    canonical_qty,
    canonical_unit,
    search_term,
    category,
    snapshot_date

from {{ ref('stg_prices') }}

qualify row_number() over (
    partition by retailer, product_id, snapshot_date
    order by result_rank, search_term
) = 1
