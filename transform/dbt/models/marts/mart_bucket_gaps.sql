-- The registered Arm A test: produce against packaged staples, crossed with
-- brand tier.
-- Grain: one row per (pair_set, aisle_group, brand_tier).
--
-- Scored against the predictions registered at commit 51cb891
-- (docs/preregistration.md), which were written before any of these numbers
-- existed. The four claims under test:
--
--   P1  parity is higher on packaged staples than on produce, in both tiers
--   P2  the median absolute gap is larger on produce than on staples, both tiers
--   P3  store brands move less often than name brands WITHIN each aisle group
--   P4  the median closed gap episode stays at or near 7 days in every cell
--
-- P3 is the one that matters most. It is a robustness test of the finding
-- already published in PRD-v3 §12: if the store-versus-name difference exists
-- only pooled and vanishes once aisle is held constant, that headline was an
-- aisle-mix artefact and the registration commits to correcting it publicly.
--
-- The `opaque` group is carried here for completeness and is NOT the test. It
-- holds three pairs, because a cross-retailer pair needs the product at both
-- chains and the backfill source barely stocks the long tail — the coverage
-- finding that registering surfaced. Nothing should be concluded from it, and
-- the row exists so that its emptiness is visible rather than silently absent.

with assignment as (

    select * from {{ ref('int_bucket_assignment') }}

),

daily as (

    select
        d.*,
        a.aisle_group
    from {{ ref('int_backfill_pair_daily') }} d
    inner join assignment a
        on a.pair_set = d.pair_set
       and a.pair_id  = d.pair_id

),

observed as (

    select * from daily where not is_gap_day

),

movements as (

    select
        pair_set,
        aisle_group,
        brand_tier,
        count(*) as n_change_events
    from (
        select
            pair_set,
            aisle_group,
            brand_tier,
            pair_id,
            price_date,
            wow_price,
            coles_price,
            lag(wow_price) over (
                partition by pair_set, pair_id order by price_date
            ) as prev_wow,
            lag(coles_price) over (
                partition by pair_set, pair_id order by price_date
            ) as prev_coles
        from observed
    ) stepped
    where prev_wow is not null
      and prev_coles is not null
      and (abs(wow_price - prev_wow) >= 0.005 or abs(coles_price - prev_coles) >= 0.005)
    group by pair_set, aisle_group, brand_tier

),

episodes as (

    select
        e.pair_set,
        a.aisle_group,
        e.brand_tier,
        count(*)                                                   as n_gap_episodes,
        sum(case when e.outcome = 'closed' then 1 else 0 end)      as n_episodes_closed,
        median(case when e.outcome = 'closed' then e.episode_days end)
                                                                   as median_closed_episode_days
    from {{ ref('mart_gap_episodes') }} e
    inner join assignment a
        on a.pair_set = e.pair_set
       and a.pair_id  = e.pair_id
    group by e.pair_set, a.aisle_group, e.brand_tier

),

series as (

    select
        pair_set,
        aisle_group,
        brand_tier,
        count(distinct pair_id)                     as n_pairs,
        count(*)                                    as n_pair_days,
        min(price_date)                             as window_start,
        max(price_date)                             as window_end,

        round(100.0 * sum(case when is_parity then 1 else 0 end) / count(*), 1)
                                                    as parity_rate_pct,
        round(median(abs_gap_pct), 2)               as median_abs_gap_pct,
        round(avg(abs_gap_pct), 2)                  as mean_abs_gap_pct,
        round(percentile_cont(0.9) within group (order by abs_gap_pct), 2)
                                                    as p90_abs_gap_pct,
        round(100.0 * sum(case when cheaper_at = 'coles' then 1 else 0 end) / count(*), 1)
                                                    as pct_days_coles_cheaper,
        round(100.0 * sum(case when cheaper_at = 'woolworths' then 1 else 0 end) / count(*), 1)
                                                    as pct_days_wow_cheaper
    from observed
    group by pair_set, aisle_group, brand_tier

)

select
    s.pair_set,
    s.aisle_group,
    s.brand_tier,
    s.n_pairs,
    s.n_pair_days,
    coalesce(m.n_change_events, 0)                  as n_change_events,
    -- The effective sample size, and the measure P3 is stated in. A price that
    -- sits unchanged for nine days is one event, not nine.
    round(100.0 * coalesce(m.n_change_events, 0) / s.n_pair_days, 2)
                                                    as pct_days_a_price_moved,
    s.window_start,
    s.window_end,

    s.parity_rate_pct,
    s.median_abs_gap_pct,
    s.mean_abs_gap_pct,
    s.p90_abs_gap_pct,
    s.pct_days_coles_cheaper,
    s.pct_days_wow_cheaper,

    coalesce(e.n_gap_episodes, 0)                   as n_gap_episodes,
    coalesce(e.n_episodes_closed, 0)                as n_episodes_closed,
    round(e.median_closed_episode_days, 1)          as median_closed_episode_days

from series s
left join movements m
    on m.pair_set = s.pair_set
   and m.aisle_group = s.aisle_group
   and m.brand_tier = s.brand_tier
left join episodes e
    on e.pair_set = s.pair_set
   and e.aisle_group = s.aisle_group
   and e.brand_tier = s.brand_tier
