-- Staging: turn Hot Prices' change points into validity windows.
-- Grain: one row per (retailer, product_id, valid_from).
--
-- The upstream format stores only the dates a price moved, which is already an
-- SCD2 series with the valid_to column left implicit. This model makes it
-- explicit, and it is the same shape as snap_product_prices — v2 built that by
-- replaying days forwards through a dbt snapshot, and this arrives pre-built.
--
-- Where valid_to comes from
-- -------------------------
-- For every change point but the last, valid_to is the day before the next
-- change: that is what a change point means and no inference is involved.
--
-- The last segment runs to fetched_date, and that is an observation rather than
-- an assumption. The dump publishes a current `price` alongside the history,
-- and it equals the final history point for all 44,659 products in both files
-- — so the fetch itself witnesses that the price still stood on the day we
-- pulled it. Nothing is projected past fetched_date, per PRD-v3 §5.2 rule 1.
--
-- What is NOT filled in: anything before the first change point. A product Hot
-- Prices first saw in August cannot testify about July, however stable it looks
-- afterwards, and every downstream model starts a pair's series at the later of
-- its two first observations.

with raw as (

    select * from {{ source('raw', 'raw_hotprices') }}

),

typed as (

    select
        lower(trim(retailer))                          as retailer,
        cast(product_id as varchar)                    as product_id,
        trim(cast(name as varchar))                    as name,
        lower(trim(coalesce(cast(unit as varchar), ''))) as unit,
        cast(quantity as double)                       as quantity,
        cast(is_weighted as boolean)                   as is_weighted,
        cast(category as varchar)                      as category,
        cast(change_date as date)                      as change_date,
        cast(price as double)                          as price,
        cast(fetched_date as date)                     as fetched_date,
        cast(source_url as varchar)                    as source_url
    from raw
    where price is not null
      and price > 0

),

sequenced as (

    select
        typed.*,
        lead(change_date) over (
            partition by retailer, product_id
            order by change_date
        ) as next_change_date
    from typed

)

select
    retailer,
    product_id,
    name,
    unit,
    quantity,
    is_weighted,
    category,
    price,
    change_date as valid_from,
    coalesce(
        {{ dbt.dateadd('day', -1, 'next_change_date') }},
        fetched_date
    )           as valid_to,
    (next_change_date is null) as is_current,
    fetched_date,
    source_url

from sequenced
-- A change point dated after the fetch would mean the upstream file disagrees
-- with its own filename. Nothing should match this; it exists so that if the
-- assumption ever breaks, the row is dropped loudly rather than producing a
-- window that ends before it begins.
where change_date <= fetched_date
