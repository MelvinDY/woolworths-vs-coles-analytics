-- One row per promotion episode: how deep, how long, and what happened to the
-- price when it ended.
-- Grain: one row per (retailer, product_id, special_episode).
--
-- This is the model that only exists because the collection kept running. From
-- a single day you can see that a product is flagged on special and what the
-- retailer says the "was" price is. You cannot see whether that was price was
-- ever charged, or whether the shelf price came back up afterwards. Both of
-- those are the difference between a discount and a pricing pattern, and both
-- need the series.
--
-- Episodes are runs of consecutive *observed* days on special, not consecutive
-- calendar days. A day the collector missed does not end an episode and does
-- not start a new one — it is simply a day nobody looked. calendar_days is
-- reported alongside days_observed so the reader can see how much of the span
-- was actually watched.

with observed as (

    select
        retailer,
        product_id,
        name,
        brand,
        size_raw,
        category,
        snapshot_date,
        price,
        was_price,
        coalesce(is_on_special, false) as is_on_special
    from {{ ref('int_product_prices_daily') }}

),

sequenced as (

    select
        *,
        row_number() over (partition by retailer, product_id order by snapshot_date) as day_seq,
        lag(price)         over (partition by retailer, product_id order by snapshot_date) as prev_price,
        lead(price)        over (partition by retailer, product_id order by snapshot_date) as next_price,
        -- Not "yesterday" — the previous day anyone *looked*. Everything that
        -- compares against a baseline has to be able to say how old it is.
        lag(snapshot_date) over (partition by retailer, product_id order by snapshot_date) as prev_observed_on,
        lead(snapshot_date) over (partition by retailer, product_id order by snapshot_date) as next_observed_on,
        max(snapshot_date) over (partition by retailer, product_id)                        as product_last_seen
    from observed

),

islands as (

    -- Classic gaps-and-islands: within a product, the offset between the
    -- overall day sequence and the per-flag day sequence is constant for the
    -- length of a run and changes whenever the flag flips.
    select
        *,
        day_seq - row_number() over (
            partition by retailer, product_id, is_on_special
            order by snapshot_date
        ) as island
    from sequenced

),

episode_edges as (

    select
        *,
        first_value(prev_price) over (
            partition by retailer, product_id, island
            order by snapshot_date
            rows between unbounded preceding and unbounded following
        ) as baseline_before,
        first_value(prev_observed_on) over (
            partition by retailer, product_id, island
            order by snapshot_date
            rows between unbounded preceding and unbounded following
        ) as baseline_observed_on,
        first_value(was_price) over (
            partition by retailer, product_id, island
            order by snapshot_date
            rows between unbounded preceding and unbounded following
        ) as was_price_claimed,
        last_value(next_price) over (
            partition by retailer, product_id, island
            order by snapshot_date
            rows between unbounded preceding and unbounded following
        ) as price_after,
        last_value(next_observed_on) over (
            partition by retailer, product_id, island
            order by snapshot_date
            rows between unbounded preceding and unbounded following
        ) as price_after_observed_on
    from islands
    where is_on_special

),

episodes as (

    select
        retailer,
        product_id,
        min(name)                 as name,
        min(brand)                as brand,
        min(size_raw)             as size_raw,
        min(category)             as category,
        island,
        min(snapshot_date)        as episode_start,
        max(snapshot_date)        as episode_end,
        count(*)                  as days_observed,
        min(product_last_seen)    as product_last_seen,
        min(price)                    as lowest_special_price,
        min(baseline_before)          as baseline_before,
        min(baseline_observed_on)     as baseline_observed_on,
        min(was_price_claimed)        as was_price_claimed,
        min(price_after)              as price_after,
        min(price_after_observed_on)  as price_after_observed_on,
        round(median(case
            when was_price is not null and was_price > price
                then (was_price - price) / was_price * 100
        end), 1)                  as median_claimed_depth_pct
    from episode_edges
    group by retailer, product_id, island

),

classified as (

    select
        e.*,
        {{ dbt.datediff('episode_start', 'episode_end', 'day') }} + 1 as calendar_days,

        -- How stale the baseline is. A "10% higher than before" claim means
        -- something different against yesterday than against four weeks ago,
        -- and the collection has holes in it, so this travels with the number.
        case
            when baseline_observed_on is not null
                then {{ dbt.datediff('baseline_observed_on', 'episode_start', 'day') }}
        end as baseline_age_days,

        -- Depth measured against a price this project actually watched being
        -- charged, rather than against the retailer's own "was" claim.
        case
            when baseline_before is not null and baseline_before > 0
                then round((baseline_before - lowest_special_price) / baseline_before * 100, 1)
        end as observed_depth_pct,

        -- The blunt question a shopper would ask: did the price actually go
        -- down when the "Special" badge appeared? NULL when we never saw the
        -- product before the special, which is not the same as "no".
        case
            when baseline_before is null then null
            when lowest_special_price < baseline_before - 0.01 then 'price_cut'
            when lowest_special_price > baseline_before + 0.01 then 'price_rise'
            else 'no_change'
        end as special_kind,

        -- Was the advertised "was" price the price we saw the day before?
        case
            when baseline_before is null or was_price_claimed is null then null
            else abs(was_price_claimed - baseline_before) <= 0.01
        end as was_price_matches_observed,

        case
            -- Still running on the last day we looked: nothing to conclude yet.
            when episode_end >= product_last_seen or price_after is null then 'ongoing'
            -- We never saw the product before the special started.
            when baseline_before is null then 'no_baseline'
            -- Price went back to (or above) where it was: a promotion cycle.
            when price_after >= baseline_before - 0.01 then 'restored_baseline'
            else 'genuine_cut'
        end as outcome

    from episodes e

)

select
    retailer,
    product_id,
    row_number() over (partition by retailer, product_id order by episode_start) as special_episode,
    name,
    brand,
    size_raw,
    category,
    episode_start,
    episode_end,
    days_observed,
    calendar_days,
    lowest_special_price,
    baseline_before,
    baseline_observed_on,
    baseline_age_days,
    price_after,
    price_after_observed_on,
    was_price_claimed,
    was_price_matches_observed,
    median_claimed_depth_pct,
    observed_depth_pct,
    special_kind,
    outcome

from classified
