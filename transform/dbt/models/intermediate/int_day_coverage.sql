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
--
-- Completeness is judged on the EVERYDAY panel only
-- -------------------------------------------------
-- v3 added 40 long-tail lines to the basket (plungers, denture tablets, worming
-- tablets) so that Arm B can test the price-visible/price-opaque split, which
-- the backfill source cannot — see docs/preregistration.md.
--
-- The original version of this model took its denominator from
-- `max(terms_seen)` across all days. That was safe against a line being retired
-- and quietly catastrophic against lines being *added*: on the first day the
-- tail was collected the denominator would jump from 50 to 90, every historical
-- day would fall to 56% coverage, `is_complete_day` would go false across the
-- board, and the ten complete days behind every published v2 figure would
-- silently evaporate.
--
-- Panel membership fixes that at the root. The everyday panel is a fixed 50
-- lines that every collected day has always attempted, so it is a denominator
-- that does not move when the basket grows. Tail coverage is reported beside it
-- and deliberately does not gate the day: the tail is an exploratory panel on
-- thinly stocked lines, and a plunger going out of stock must not be able to
-- discard a day of milk and bread prices.

with basket as (

    select
        search_term,
        panel
    from {{ ref('basket') }}

),

priced as (

    select
        p.snapshot_date,
        p.retailer,
        p.search_term,
        coalesce(b.panel, 'everyday') as panel
    from {{ ref('stg_prices') }} p
    left join basket b
        on p.search_term = b.search_term

),

per_day as (

    select
        snapshot_date,

        count(distinct case when panel = 'everyday' then search_term end)     as everyday_terms_seen,
        count(distinct case when panel = 'everyday' and retailer = 'woolworths'
                            then search_term end)                             as wow_terms,
        count(distinct case when panel = 'everyday' and retailer = 'coles'
                            then search_term end)                             as coles_terms,

        count(distinct case when panel = 'tail' then search_term end)         as tail_terms_seen,
        count(distinct case when panel = 'tail' and retailer = 'woolworths'
                            then search_term end)                             as tail_wow_terms,
        count(distinct case when panel = 'tail' and retailer = 'coles'
                            then search_term end)                             as tail_coles_terms
    from priced
    group by 1

),

panel_sizes as (

    -- Declared sizes, from the seed, rather than inferred from the data. The
    -- seed is the contract for what a run is supposed to attempt; inferring the
    -- denominator from what came back is what let the denominator move.
    select
        sum(case when panel = 'everyday' then 1 else 0 end) as everyday_lines,
        sum(case when panel = 'tail'     then 1 else 0 end) as tail_lines
    from basket

)

select
    p.snapshot_date,
    s.everyday_lines                        as full_basket,
    p.wow_terms,
    p.coles_terms,
    least(p.wow_terms, p.coles_terms)       as weaker_side_terms,
    round(100.0 * least(p.wow_terms, p.coles_terms) / s.everyday_lines, 1) as coverage_pct,

    s.tail_lines,
    p.tail_wow_terms,
    p.tail_coles_terms,
    case
        when s.tail_lines = 0 then null
        else round(100.0 * least(p.tail_wow_terms, p.tail_coles_terms) / s.tail_lines, 1)
    end                                     as tail_coverage_pct,

    -- 80% of the everyday basket on BOTH sides. The threshold is deliberately
    -- blunt: every real day so far clears it at 96-100% and 2026-08-22 lands at
    -- 14%, so nothing sits near the line and no day is a judgement call.
    least(p.wow_terms, p.coles_terms) >= 0.8 * s.everyday_lines as is_complete_day

from per_day p
cross join panel_sizes s
