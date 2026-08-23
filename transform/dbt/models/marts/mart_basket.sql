-- Basket comparison: cheapest relevant hit per search term per retailer,
-- restricted to terms where BOTH retailers have a candidate so the totals are
-- comparable.
-- Grain: one row per (retailer, search_term, snapshot_date).
--
-- Ported from transform/sql/03_mart_basket.sql. Two screens are additions to
-- the v1 logic, both there to stop the basket quietly pricing something other
-- than the basket: complete days only, and per-line relevance rules. What each
-- one is for, and the day that made it necessary, is in docs/data_quality.md.

with candidates as (

    select p.*
    from {{ ref('stg_prices') }} p
    join {{ ref('int_day_coverage') }} d
        on p.snapshot_date = d.snapshot_date
    -- A day where one retailer answered a fraction of the basket is not a
    -- cheaper day, it is an unobserved one. Dropping it here rather than
    -- averaging it in is the same rule the history marts already apply to
    -- missing days.
    where d.is_complete_day

),

screened as (

    -- "Cheapest hit" only means something if the hit is the product. Woolworths
    -- returns third-party marketplace listings alongside groceries, and for
    -- 'eggs 12 pack' they crowd the result set: incubators, egg carriers, a
    -- dinosaur fossil toy. The basket takes a minimum, so one bad hit moves the
    -- whole total.
    --
    -- Lines carrying a rule in basket_relevance are screened by that rule
    -- across every hit returned. Lines without one keep the original top-five
    -- cap, which is all v1 had and is fine wherever search behaves.
    select c.*
    from candidates c
    left join {{ ref('basket_relevance') }} r
        on c.search_term = r.search_term
    where case
        when r.search_term is null
            then c.result_rank <= 5
        else
            (nullif(r.must_match, '') is null
                or {{ regex_contains('lower(c.name)', "nullif(r.must_match, '')") }})
            and (nullif(r.require_unit_basis, '') is null
                or c.unit_price_basis = r.require_unit_basis)
    end

),

relevant as (

    select
        retailer,
        search_term,
        category,
        snapshot_date,
        product_id,
        name,
        price,
        row_number() over (
            partition by retailer, search_term, snapshot_date
            order by price, result_rank
        ) as price_rank
    from screened

),

cheapest as (

    select retailer, search_term, category, snapshot_date, product_id, name, price
    from relevant
    where price_rank = 1

),

both_sides as (

    select search_term, snapshot_date
    from cheapest
    group by 1, 2
    having count(distinct retailer) = 2

)

select c.*
from cheapest c
join both_sides b
    on c.search_term = b.search_term
   and c.snapshot_date = b.snapshot_date
