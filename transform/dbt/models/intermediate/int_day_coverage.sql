-- How much of the basket each retailer actually returned on each collected day.
-- Grain: one row per snapshot_date.
--
-- This model exists because of 2026-08-22. Coles answered HTTP 500 to all but
-- three search terms that morning, the fetcher's only guard was "did this
-- retailer return *any* rows at all", and so a day holding 47 Woolworths lines
-- and 3 Coles ones was written, committed and loaded like any other.
--
-- A partial day is more dangerous than a missing one. A missing day is visible:
-- the history marts flag it and the dashboard draws it dashed. A partial day
-- looks complete, and every comparison built on it silently comes from a
-- different basket at each retailer.
--
-- So completeness is measured in basket LINES answered, not rows returned. A
-- retailer that hands back 400 rows for three search terms has not covered the
-- basket, and a row count cannot tell the difference.

with per_day as (

    select
        snapshot_date,
        count(distinct search_term)                                                     as terms_seen,
        count(distinct case when retailer = 'woolworths' then search_term end)          as wow_terms,
        count(distinct case when retailer = 'coles'      then search_term end)          as coles_terms
    from {{ ref('stg_prices') }}
    group by 1

),

basket_size as (

    -- The denominator is the basket as it was actually collected at its best,
    -- not a hardcoded 50. A line legitimately retired from seeds/basket.csv
    -- should not make every historical day look incomplete.
    select max(terms_seen) as full_basket from per_day

)

select
    p.snapshot_date,
    b.full_basket,
    p.wow_terms,
    p.coles_terms,
    least(p.wow_terms, p.coles_terms) as weaker_side_terms,
    round(100.0 * least(p.wow_terms, p.coles_terms) / b.full_basket, 1) as coverage_pct,

    -- 80% of the basket on BOTH sides. The threshold is deliberately blunt:
    -- every real day so far clears it at 96-100% and 2026-08-22 lands at 14%,
    -- so nothing sits near the line and no day is a judgement call.
    least(p.wow_terms, p.coles_terms) >= 0.8 * b.full_basket as is_complete_day

from per_day p
cross join basket_size b
