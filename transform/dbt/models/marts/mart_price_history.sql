-- The matched-pair price series: what each pair cost at each chain, every day
-- the collector ran.
-- Grain: one row per (pair_id, snapshot_date).
--
-- Incremental, because a day's run should touch a day's rows. The predicate is
-- `>=` rather than `>` on purpose: re-running today must recompute today, which
-- is the same idempotent-per-day contract the raw layer has. delete+insert on
-- (pair_id, snapshot_date) then makes a same-day re-run a replacement rather
-- than a duplicate.
--
-- Gap days. A pair's row exists for every day from the day it was first matched
-- onward, whether or not both products were seen that day. When one side is
-- missing the price is NULL and is_gap_day is true — the series is never
-- forward-filled. A supermarket that stops listing a product has not held its
-- price flat, and a chart that draws a straight line across the gap is making a
-- claim the data does not support. Downstream code must treat NULL as "not
-- observed", not as "unchanged".
--
-- Prices are joined per product from int_product_prices_daily rather than taken
-- from the matcher's own output, so a day where the matcher happened not to
-- re-derive the pair (a name drifted below the fuzzy threshold, say) still
-- carries both real prices instead of vanishing.

{{ config(
    materialized = 'incremental',
    unique_key = ['pair_id', 'snapshot_date'],
    incremental_strategy = 'delete+insert'
) }}

with days as (

    select distinct snapshot_date
    from {{ ref('int_product_prices_daily') }}

    {% if is_incremental() %}
    where snapshot_date >= (
        select coalesce(max(snapshot_date), cast('1900-01-01' as date)) from {{ this }}
    )
    {% endif %}

),

pairs as (

    select * from {{ ref('int_matched_pairs') }}

),

spine as (

    select
        p.pair_id,
        p.wow_product_id,
        p.coles_product_id,
        p.wow_name,
        p.wow_size,
        p.coles_name,
        p.coles_size,
        p.search_term,
        p.category,
        p.match_type,
        d.snapshot_date
    from pairs p
    cross join days d
    where d.snapshot_date >= p.first_matched_date

),

wow_daily as (

    select product_id, snapshot_date, price, was_price, is_on_special
    from {{ ref('int_product_prices_daily') }}
    where retailer = 'woolworths'

),

coles_daily as (

    select product_id, snapshot_date, price, was_price, is_on_special
    from {{ ref('int_product_prices_daily') }}
    where retailer = 'coles'

)

select
    s.pair_id,
    s.snapshot_date,
    s.search_term,
    s.category,
    s.match_type,

    s.wow_product_id,
    s.wow_name,
    s.wow_size,
    w.price                                                     as wow_price,
    w.is_on_special                                             as wow_on_special,

    s.coles_product_id,
    s.coles_name,
    s.coles_size,
    c.price                                                     as coles_price,
    c.is_on_special                                             as coles_on_special,

    round(c.price - w.price, 2)                                 as gap_dollars,
    round((c.price - w.price) / c.price * 100, 1)               as gap_pct_of_coles,

    case
        when w.price is null or c.price is null then null
        when w.price < c.price then 'woolworths'
        when c.price < w.price then 'coles'
        else 'tie'
    end                                                         as cheaper_at,

    (w.price is null or c.price is null)                        as is_gap_day

from spine s
left join wow_daily w
    on w.product_id = s.wow_product_id
   and w.snapshot_date = s.snapshot_date
left join coles_daily c
    on c.product_id = s.coles_product_id
   and c.snapshot_date = s.snapshot_date
