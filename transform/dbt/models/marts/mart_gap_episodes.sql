-- Promotion or position: every run of days where the two chains were more than
-- 5% apart, and whether it ever closed.
-- Grain: one row per (pair_set, pair_id, episode_start).
--
-- This is the model PRD-v3 G3 exists for, and the question a single snapshot
-- cannot answer. On any one morning a wide gap on instant coffee and a wide gap
-- on denture tablets look identical. The difference is only visible afterwards:
-- one closes inside a fortnight because it was a promotion, and the other never
-- closes because it is a pricing position. v2 could not tell them apart with 10
-- days; with a year of change points it is a group-by.
--
-- Islands are found the standard way — the difference between a row number over
-- all days and a row number over days of the same kind is constant within a run.
-- Days where either price is unobserved are excluded before the numbering
-- rather than treated as narrow, so an unobserved day never silently ends an
-- episode that was still running.
--
-- Direction is part of "the same kind", and that is not incidental. Grouping on
-- width alone produced 330-day episodes in which the dearer chain swapped back
-- and forth — one continuous run of wide days, but plainly not one gap. A gap
-- that closes and reopens with the other retailer on top is a new event, so a
-- change of direction ends the episode.
--
-- outcome:
--   'closed'  the gap narrowed to 5% or less while we were still watching. The
--             duration is a real duration.
--   'open'    the run reaches the last observed day. Its duration is a lower
--             bound, not a measurement — the gap was still open when the data
--             ran out, and reporting a mean that mixes these with closed
--             episodes understates persistence.

with daily as (

    select *
    from {{ ref('int_backfill_pair_daily') }}
    where not is_gap_day

),

flagged as (

    select
        pair_set,
        pair_id,
        price_date,
        brand_tier,
        brand_tier_basis,
        wow_name,
        coles_name,
        wow_price,
        coles_price,
        abs_gap_pct,
        gap_dollars,
        cheaper_at,
        case when abs_gap_pct > 5 then 1 else 0 end as is_wide,
        max(price_date) over (partition by pair_set, pair_id) as pair_last_day
    from daily

),

islands as (

    select
        flagged.*,
        row_number() over (
            partition by pair_set, pair_id
            order by price_date
        )
        - row_number() over (
            partition by pair_set, pair_id, is_wide, cheaper_at
            order by price_date
        ) as island
    from flagged

)

select
    pair_set,
    pair_id,
    brand_tier,
    brand_tier_basis,
    max(wow_name)                                       as wow_name,
    max(coles_name)                                     as coles_name,

    min(price_date)                                     as episode_start,
    max(price_date)                                     as episode_end,
    count(*)                                            as episode_days,

    round(max(abs_gap_pct), 2)                          as peak_gap_pct,
    round(avg(abs_gap_pct), 2)                          as mean_gap_pct,
    round(max(abs(gap_dollars)), 2)                     as peak_gap_dollars,

    -- Constant within an episode by construction: direction is part of the
    -- island key above, so a swap starts a new row rather than being averaged
    -- into this one.
    max(cheaper_at)                                     as cheaper_at,

    case
        when max(price_date) < max(pair_last_day) then 'closed'
        else 'open'
    end                                                 as outcome

from islands
where is_wide = 1
group by pair_set, pair_id, brand_tier, brand_tier_basis, cheaper_at, island
