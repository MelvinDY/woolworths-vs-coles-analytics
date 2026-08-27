-- The headline Arm A result, split the way it has to be split.
-- Grain: one row per (pair_set, brand_tier).
--
-- Why store brand and name brand are never pooled here
-- ---------------------------------------------------
-- A name brand is the *same physical good* on both shelves. A gap between the
-- chains is then a pricing decision about one product, and parity means one
-- chain deliberately matched the other to the cent.
--
-- A store brand is only ever a substitute. Coles Tasty Cheese and Woolworths
-- Tasty Cheese are different products from different suppliers, so a gap
-- between them is part pricing and part recipe, pack and sourcing — and parity
-- between them is close to coincidence rather than evidence of matching.
--
-- Pooling the two makes every measure below ambiguous, and worse, it makes the
-- v2 aisle finding unfalsifiable: private-label share varies by aisle, so a
-- pooled parity rate that moves from pantry to household could be reporting
-- nothing but a change in the mix. Splitting the tier is what stops that
-- explanation from hiding inside the result. See matching/brands.py.
--
-- n is change events, not rows
-- ----------------------------
-- A price that sits unchanged for nine days is one event, not nine, and
-- PRD-v3 §10 forbids quoting the row count. Both are published here so the
-- ratio between them is visible; anything inferential must use the event count.

with daily as (

    select * from {{ ref('int_backfill_pair_daily') }}

),

observed as (

    select * from daily where not is_gap_day

),

-- A day on which either side moved. This is the effective sample size: the
-- number of times a retailer actually made a decision we could see.
movements as (

    select
        pair_set,
        brand_tier,
        count(*) as n_change_events
    from (
        select
            pair_set,
            pair_id,
            brand_tier,
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
    group by pair_set, brand_tier

),

episodes as (

    select
        pair_set,
        brand_tier,
        count(*)                                                    as n_gap_episodes,
        sum(case when outcome = 'closed' then 1 else 0 end)         as n_episodes_closed,
        sum(case when outcome = 'open' then 1 else 0 end)           as n_episodes_open,
        -- Closed episodes only. An open episode's length is a lower bound, and
        -- averaging the two together reports a persistence shorter than the
        -- truth precisely for the tier where gaps persist most.
        median(case when outcome = 'closed' then episode_days end)  as median_closed_episode_days,
        median(case when outcome = 'closed' then peak_gap_pct end)  as median_closed_peak_gap_pct
    from {{ ref('mart_gap_episodes') }}
    group by pair_set, brand_tier

),

series as (

    select
        pair_set,
        brand_tier,
        max(brand_tier_basis)                       as brand_tier_basis,
        max(blocking_basis)                         as blocking_basis,
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
        round(100.0 * sum(case when abs_gap_pct > 5 then 1 else 0 end) / count(*), 1)
                                                    as pct_days_gap_over_5,

        round(100.0 * sum(case when cheaper_at = 'coles' then 1 else 0 end) / count(*), 1)
                                                    as pct_days_coles_cheaper,
        round(100.0 * sum(case when cheaper_at = 'woolworths' then 1 else 0 end) / count(*), 1)
                                                    as pct_days_wow_cheaper
    from observed
    group by pair_set, brand_tier

)

select
    s.pair_set,
    s.brand_tier,
    s.brand_tier_basis,
    s.blocking_basis,
    s.n_pairs,
    s.n_pair_days,
    coalesce(m.n_change_events, 0)                  as n_change_events,
    s.window_start,
    s.window_end,

    s.parity_rate_pct,
    s.median_abs_gap_pct,
    s.mean_abs_gap_pct,
    s.p90_abs_gap_pct,
    s.pct_days_gap_over_5,
    s.pct_days_coles_cheaper,
    s.pct_days_wow_cheaper,

    coalesce(e.n_gap_episodes, 0)                   as n_gap_episodes,
    coalesce(e.n_episodes_closed, 0)                as n_episodes_closed,
    coalesce(e.n_episodes_open, 0)                  as n_episodes_open,
    round(e.median_closed_episode_days, 1)          as median_closed_episode_days,
    round(e.median_closed_peak_gap_pct, 2)          as median_closed_peak_gap_pct,
    case
        when coalesce(e.n_gap_episodes, 0) = 0 then null
        else round(100.0 * e.n_episodes_closed / e.n_gap_episodes, 1)
    end                                             as pct_episodes_closed

from series s
left join movements m
    on m.pair_set = s.pair_set and m.brand_tier = s.brand_tier
left join episodes e
    on e.pair_set = s.pair_set and e.brand_tier = s.brand_tier
