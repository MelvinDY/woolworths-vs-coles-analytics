-- Matched product pairs with price gaps and a winner flag.
-- Grain: one row per (wow_product_id, coles_product_id, snapshot_date).
-- Ported from transform/sql/02_mart_pair_comparison.sql. The only addition is
-- the complete-day filter, for the same reason mart_basket carries one: on
-- 2026-08-22 Coles answered seven of fifty search terms, which yielded 27 pairs
-- against a normal day's 128. Left in, that day reads as a real day on which
-- the two chains happened to agree less often. It is not a day at all.

select
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
    round(coles_price - wow_price, 2)                       as gap_dollars,
    round((coles_price - wow_price) / coles_price * 100, 1) as gap_pct_of_coles,
    case
        when wow_price < coles_price then 'woolworths'
        when coles_price < wow_price then 'coles'
        else 'tie'
    end                                                     as cheaper_at

from {{ ref('int_matched_products') }}
where snapshot_date in (
    select snapshot_date from {{ ref('int_day_coverage') }} where is_complete_day
)
