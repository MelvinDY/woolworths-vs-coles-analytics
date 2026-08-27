-- The backfilled matched-pair price series.
-- Grain: one row per (pair_set, pair_id, price_date).
--
-- The Arm A counterpart to mart_price_history, and deliberately built the same
-- way: a spine of days crossed with pairs, prices joined on per product, and a
-- NULL where a price was not observed rather than a value carried forward.
--
-- Two things differ from the v2 model, both because the source differs.
--
--   1. Days come from a date spine, not from the days a collector ran. Hot
--      Prices reports change points, so every day between two of them is a day
--      its price is *known* to have stood, and the spine is what turns that
--      back into a series. v2's collector has no such guarantee: a day it did
--      not run is a day nobody looked, which is why that model draws its days
--      from observations and this one does not.
--
--   2. Both pair sets are carried side by side and pair_set is part of the
--      grain. FR-3's pairs were accepted on a retailer brand field and a
--      human-authored block; FR-4's on a name prefix and a size bucket. They
--      are not the same quality of evidence and must never be pooled by
--      accident — PRD-v3 G5.
--
-- brand_tier rides along on every row. Store brands and name brands are
-- different questions (matching/brands.py), and putting the tier on the grain
-- means no downstream model can compute a pooled figure without deciding to.

with pairs as (

    select * from {{ source('matching', 'backfill_pairs') }}

),

bounds as (

    select max(fetched_date) as window_end
    from {{ ref('stg_hotprices') }}

),

-- date_spine compiles to a self-contained subquery and cannot see the CTEs
-- around it, so its bounds have to be literals. The start is the var; the end
-- is today, which is the furthest any dump could reach. The real right edge is
-- the fetch date, and `days` clips to it below — a spine that overshoots costs
-- a few unused rows, whereas one that stops short would silently truncate the
-- series and look like a price that stopped moving.
spine as (

    {{ dbt_utils.date_spine(
        datepart="day",
        start_date="cast('" ~ var("backfill_start") ~ "' as date)",
        end_date=dbt.dateadd('day', 1, 'current_date')
    ) }}

),

days as (

    select cast(s.date_day as date) as price_date
    from spine s
    cross join bounds b
    where cast(s.date_day as date) <= b.window_end

),

pair_days as (

    select
        p.pair_set,
        p.pair_id,
        p.wow_product_id,
        p.coles_product_id,
        p.wow_name,
        p.coles_name,
        p.brand_tier,
        p.brand_tier_basis,
        p.blocking_basis,
        p.name_score,
        p.search_term,
        d.price_date
    from pairs p
    cross join days d
    -- A pair's series opens at the later of its two first observations. Before
    -- that, one side has no price and there is no gap to measure.
    where d.price_date >= p.history_start

),

wow_windows as (

    select product_id, price, valid_from, valid_to
    from {{ ref('stg_hotprices') }}
    where retailer = 'woolworths'

),

coles_windows as (

    select product_id, price, valid_from, valid_to
    from {{ ref('stg_hotprices') }}
    where retailer = 'coles'

)

select
    pd.pair_set,
    pd.pair_id,
    pd.price_date,
    pd.brand_tier,
    pd.brand_tier_basis,
    pd.blocking_basis,
    pd.name_score,
    pd.search_term,

    pd.wow_product_id,
    pd.wow_name,
    w.price                                                as wow_price,

    pd.coles_product_id,
    pd.coles_name,
    c.price                                                as coles_price,

    round(c.price - w.price, 2)                            as gap_dollars,
    -- Denominated on the mean of the two prices rather than on either chain's,
    -- so the measure does not change sign meaning depending on which retailer
    -- happens to be dearer. mart_price_history uses Coles as the base for
    -- continuity with v1's published figure; this is a fresh model and takes
    -- the symmetric definition PRD-v3 §7 asks for.
    case
        when w.price is null or c.price is null then null
        else round(abs(c.price - w.price) / ((c.price + w.price) / 2.0) * 100, 2)
    end                                                    as abs_gap_pct,

    case
        when w.price is null or c.price is null then null
        when abs(c.price - w.price) < 0.005 then true
        else false
    end                                                    as is_parity,

    case
        when w.price is null or c.price is null then null
        when w.price < c.price then 'woolworths'
        when c.price < w.price then 'coles'
        else 'tie'
    end                                                    as cheaper_at,

    (w.price is null or c.price is null)                   as is_gap_day

from pair_days pd
left join wow_windows w
    on w.product_id = pd.wow_product_id
   and pd.price_date between w.valid_from and w.valid_to
left join coles_windows c
    on c.product_id = pd.coles_product_id
   and pd.price_date between c.valid_from and c.valid_to
