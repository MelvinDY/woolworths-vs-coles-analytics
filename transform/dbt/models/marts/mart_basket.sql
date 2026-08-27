-- Basket comparison: cheapest relevant hit per search term per retailer,
-- restricted to terms where BOTH retailers have a candidate so the totals are
-- comparable.
-- Grain: one row per (retailer, search_term, snapshot_date).
--
-- Ported from transform/sql/03_mart_basket.sql. Two screens are additions to
-- the v1 logic, both there to stop the basket quietly pricing something other
-- than the basket: complete days only, and per-line relevance rules. What each
-- one is for, and the day that made it necessary, is in docs/data_quality.md.

{% set size_pattern = '([0-9]+[.]?[0-9]*)(kg|g|l|ml)([^a-z]|$)' %}

with candidates as (

    select p.*
    from {{ ref('stg_prices') }} p
    join {{ ref('int_day_coverage') }} d
        on p.snapshot_date = d.snapshot_date
    -- The everyday panel only. v3 added 40 long-tail lines for the Arm B bucket
    -- test (docs/preregistration.md), and they are not groceries a shopper puts
    -- in a trolley -- a plunger, denture tablets, worming tablets. Letting them
    -- into this mart would move the published basket total by design rather than
    -- by a price change, and make it incomparable with every figure published
    -- before they were added. The tail is analysed by bucket, not by basket.
    join {{ ref('basket') }} b
        on p.search_term = b.search_term
       and b.panel = 'everyday'
    -- A day where one retailer answered a fraction of the basket is not a
    -- cheaper day, it is an unobserved one. Dropping it here rather than
    -- averaging it in is the same rule the history marts already apply to
    -- missing days.
    where d.is_complete_day

),

-- The size the line actually asks for, parsed from the line itself.
--
-- The bug this fixes ran from the first collected day to 2026-08-27 and is
-- written up in docs/data_quality.md. The basket took the cheapest hit per line
-- and never checked its pack size, so 'skim milk 2l' could be priced on a 1 L
-- bottle and 'vegemite 380g' on a 150 g jar. It was badly one-sided: 149 of 415
-- sized Coles rows carried the wrong pack against 13 of 415 at Woolworths, and
-- 124 of the Coles ones were SMALLER than the line asked for -- a systematic
-- discount on the Coles basket, in the exact direction of the published finding.
--
-- The requirement is derived from the search term rather than configured per
-- line in basket_relevance. The term already states the size, so deriving it
-- means the screen cannot drift away from the thing being asked for. A line
-- naming no size ('bananas', 'salmon fillets') is unconstrained.
--
-- Tolerance is 2%, which is matching/match_products.SIZE_TOLERANCE -- the number
-- this project already uses to decide two packs are the same size, not a new one
-- picked until the output looked right.
line_size as (

    select
        search_term,
        case
            when {{ regex_group('search_term', size_pattern, 2) }} in ('kg', 'l')
                then try_cast({{ regex_group('search_term', size_pattern, 1) }} as double) * 1000
            else try_cast({{ regex_group('search_term', size_pattern, 1) }} as double)
        end as required_qty,
        case
            when {{ regex_group('search_term', size_pattern, 2) }} in ('kg', 'g')  then 'g'
            when {{ regex_group('search_term', size_pattern, 2) }} in ('l', 'ml')  then 'ml'
        end as required_unit
    from (select distinct search_term from candidates) t

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
    --
    -- A line that names a pack size also stops being capped. This is the same
    -- rule, for the same reason: 'full cream milk 2l' is a line that can say
    -- what it is looking for. Capping it at five and then screening on size is
    -- worse than either alone -- at Coles on 2026-08-27 the correct 2 L Coles
    -- Full Cream Milk at $3.55 sits at rank 6, so the cap threw away the right
    -- product and the basket priced Pura at $4.65 instead.
    select c.*
    from candidates c
    left join {{ ref('basket_relevance') }} r
        on c.search_term = r.search_term
    left join line_size ls
        on c.search_term = ls.search_term
    where case
        when r.search_term is null
            then ls.required_qty is not null or c.result_rank <= 5
        else
            (nullif(r.must_match, '') is null
                or {{ regex_contains('lower(c.name)', "nullif(r.must_match, '')") }})
            -- The negative half. Some lines cannot be separated by a positive
            -- pattern alone: 'Nuttelex Buttery Spread' contains 'butter' as a
            -- substring and 'Western Star Spreadable Butter Blend' genuinely
            -- says butter, but neither is what 'butter 500g' is asking for.
            and (nullif(r.must_not_match, '') is null
                or not {{ regex_contains('lower(c.name)', "nullif(r.must_not_match, '')") }})
            and (nullif(r.require_unit_basis, '') is null
                or c.unit_price_basis = r.require_unit_basis)
    end

),

size_matched as (

    select s.*
    from screened s
    left join line_size l
        on s.search_term = l.search_term
    where l.required_qty is null                       -- line names no size
       or (
            s.canonical_unit = l.required_unit
            and s.canonical_qty is not null
            and abs(s.canonical_qty - l.required_qty) / l.required_qty <= 0.02
          )

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
    from size_matched

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
