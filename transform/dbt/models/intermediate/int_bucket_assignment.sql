-- Map matched pairs onto the pre-registered basket.
-- Grain: one row per (pair_set, pair_id).
--
-- The assignment itself is `buckets`, registered at commit 51cb891 before any
-- bucket-level figure was computed (docs/preregistration.md). This model does
-- not decide which item belongs in which tier; it only decides which pairs are
-- which items, and it must do so by a rule that cannot be steered by a result.
--
-- The rule: a pair belongs to an item if either product name contains the
-- item's pattern, and where several patterns match, **the longest wins**.
--
-- Longest-wins is not arbitrary tidying. 'Coles Tinned Tomatoes' contains both
-- `tomato` (produce, price-visible) and `tinned tomato` (pantry, price-visible)
-- and those sit in different aisle groups, which is the axis under test. The
-- more specific pattern is the one that describes the product, so it takes it.
-- Ties in length break on item_key so the assignment is deterministic across
-- runs and across engines.
--
-- A pair matching no registered pattern is **out of scope**, not unassigned:
-- the registered basket is 80 items and most of the 1,523 backfill pairs are
-- not among them. They are dropped here rather than pooled into a residual
-- bucket, because a residual is not a hypothesis.
--
-- Post-registration decision, disclosed: the tie-break rule was not written
-- into docs/preregistration.md. It was chosen here on the reasoning above, and
-- `n_patterns_matched` is carried on every row so the ambiguous assignments can
-- be counted and inspected rather than taken on trust.

with pairs as (

    select
        pair_set,
        pair_id,
        brand_tier,
        wow_name,
        coles_name
    from {{ source('matching', 'backfill_pairs') }}

),

buckets as (

    select
        item_key,
        bucket,
        aisle,
        lower(match_pattern) as match_pattern
    from {{ ref('buckets') }}

),

matched as (

    select
        p.pair_set,
        p.pair_id,
        p.brand_tier,
        p.wow_name,
        p.coles_name,
        b.item_key,
        b.bucket,
        b.aisle,
        b.match_pattern,
        length(b.match_pattern) as pattern_length
    from pairs p
    inner join buckets b
        on lower(p.wow_name)   like '%' || b.match_pattern || '%'
        or lower(p.coles_name) like '%' || b.match_pattern || '%'

),

ranked as (

    select
        matched.*,
        count(*) over (partition by pair_set, pair_id) as n_patterns_matched,
        row_number() over (
            partition by pair_set, pair_id
            order by pattern_length desc, item_key
        ) as specificity_rank
    from matched

)

select
    pair_set,
    pair_id,
    brand_tier,
    wow_name,
    coles_name,
    item_key,
    bucket,
    aisle,
    match_pattern,
    n_patterns_matched,

    -- The axis under test. Produce and packaged staples are both price-visible
    -- but behave differently on purpose: produce is sold by weight and grade,
    -- so an exact match between chains is closer to coincidence than to
    -- matching, while a national-brand staple is directly comparable.
    case
        when bucket = 'price_opaque' then 'opaque'
        when aisle = 'produce'       then 'produce'
        else 'packaged_staple'
    end as aisle_group

from ranked
where specificity_rank = 1
