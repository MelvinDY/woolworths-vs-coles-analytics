-- Pair identity, resolved once across the whole series.
--
-- The matcher runs per day, so the same two products can be re-derived as a
-- pair on Monday, missed on Tuesday (one of them dropped out of the search
-- results) and re-derived on Wednesday. A price *history* needs the pair to be
-- one thing with a stable key, not three unrelated matches, which is what
-- pair_id is for.
--
-- Descriptive columns are taken from the most recent day the pair matched:
-- product names and pack-size strings drift as retailers re-word listings, and
-- the latest wording is the one a reader will recognise on the site today.

with matched as (

    select * from {{ ref('int_matched_products') }}

),

windowed as (

    select
        *,
        row_number() over (
            partition by wow_product_id, coles_product_id
            order by snapshot_date desc
        )                                                                   as recency_rank,
        min(snapshot_date) over (partition by wow_product_id, coles_product_id) as first_matched_date,
        max(snapshot_date) over (partition by wow_product_id, coles_product_id) as last_matched_date,
        count(*)           over (partition by wow_product_id, coles_product_id) as days_matched
    from matched

)

select
    {{ dbt_utils.generate_surrogate_key(['wow_product_id', 'coles_product_id']) }} as pair_id,
    wow_product_id,
    coles_product_id,
    wow_name,
    wow_brand,
    wow_size,
    coles_name,
    coles_brand,
    coles_size,
    search_term,
    category,
    match_type,
    name_score,
    first_matched_date,
    last_matched_date,
    days_matched

from windowed
where recency_rank = 1
