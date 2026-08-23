-- Staging: cast types, canonicalize pack sizes, normalize both retailers' unit
-- prices to $ per 100 g / 100 ml / each, dedupe to one row per
-- (retailer, product_id, search_term, snapshot_date).
--
-- Ported verbatim from transform/sql/01_stg_prices.sql. Two mechanical changes,
-- both forced by the second engine and neither of which moves a number:
--   * regexp_extract(...) -> the regex_group() macro (see macros/cross_db.sql)
--   * SELECT * EXCLUDE / subquery dedupe -> explicit columns + QUALIFY
-- The v1 marts were reconciled row-for-row against this model before the old
-- SQL was retired; see docs/reconciliation.md.
--
-- search_term is part of the grain here, not (retailer, product_id,
-- snapshot_date): one product legitimately answers several basket lines, and
-- mart_basket compares the cheapest hit *per line*. Collapsing it here would
-- silently change a published basket total. The product-per-day grain the
-- snapshot and the history marts need is int_product_prices_daily instead.

{% set size_pattern = '([0-9]+[.]?[0-9]*)(kg|g|l|ml)([^a-z]|$)' %}
{% set count_pattern = '([0-9]+)(pack|pk|each|ea)([^a-z]|$)' %}
{% set measure_pattern = '([0-9]+[.]?[0-9]*)(kg|g|l|ml)' %}

with raw as (

    select * from {{ source('raw', 'raw_prices') }}

),

typed as (

    select
        lower(trim(retailer))                                     as retailer,
        cast(product_id as varchar)                               as product_id,
        trim(cast(name as varchar))                               as name,
        trim(coalesce(cast(brand as varchar), ''))                as brand,
        trim(coalesce(cast(size_raw as varchar), ''))             as size_raw,
        cast(price as double)                                     as price,
        -- Plain cast, not try_cast. v1 needed try_cast because DuckDB read the
        -- CSVs directly and an empty cell arrived as text; ingest/load_raw.py
        -- now coerces these with to_numeric(errors='coerce'), so they are
        -- already float64 with NULL where the retailer sent nothing. It also
        -- has to be a plain cast: Snowflake's TRY_CAST accepts string input
        -- only and errors on a numeric column.
        cast(was_price as double)                                 as was_price,
        cast(unit_price as double)                                as unit_price,
        lower(trim(coalesce(cast(unit_measure as varchar), '')))  as unit_measure,
        cast(is_on_special as boolean)                            as is_on_special,
        cast(result_rank as integer)                              as result_rank,
        cast(search_term as varchar)                              as search_term,
        cast(category as varchar)                                 as category,
        cast(snapshot_date as date)                               as snapshot_date
    from raw
    where price is not null
      and price > 0

),

normalized as (

    select
        typed.*,
        lower(replace(size_raw, ' ', '')) as size_norm
    from typed

),

parsed as (

    select
        retailer,
        product_id,
        name,
        brand,
        size_raw,
        price,
        was_price,
        unit_price,
        unit_measure,
        is_on_special,
        result_rank,
        search_term,
        category,
        snapshot_date,

        -- '12x375ml' -> 12
        coalesce(try_cast({{ regex_group('size_norm', '^([0-9]+)x', 1) }} as double), 1) as pack_mult,
        try_cast({{ regex_group('size_norm', size_pattern, 1) }} as double)              as size_qty,
        {{ regex_group('size_norm', size_pattern, 2) }}                                  as size_unit,
        -- '12 pack' / '6pk' / '10 each'
        try_cast({{ regex_group('size_norm', count_pattern, 1) }} as double)             as count_qty,
        -- the retailer's own unit-price denominator, e.g. '1L', '100g', '1ea'
        try_cast({{ regex_group('unit_measure', measure_pattern, 1) }} as double)        as measure_qty,
        {{ regex_group('unit_measure', measure_pattern, 2) }}                            as measure_unit

    from normalized

),

canonical as (

    select
        retailer,
        product_id,
        name,
        brand,
        size_raw,
        price,
        was_price,
        unit_price,
        unit_measure,
        is_on_special,
        result_rank,
        search_term,
        category,
        snapshot_date,

        case
            when size_qty is not null and size_unit in ('kg', 'l') then pack_mult * size_qty * 1000
            when size_qty is not null and size_unit in ('g', 'ml') then pack_mult * size_qty
            when count_qty is not null then count_qty
        end as canonical_qty,

        case
            when size_qty is not null and size_unit in ('kg', 'g') then 'g'
            when size_qty is not null and size_unit in ('l', 'ml') then 'ml'
            when count_qty is not null then 'each'
        end as canonical_unit,

        case
            when unit_price is not null and measure_unit in ('kg', 'l')
                then unit_price / (measure_qty * 1000) * 100
            when unit_price is not null and measure_unit in ('g', 'ml')
                then unit_price / measure_qty * 100
            when unit_price is not null and unit_measure like '%ea%'
                then unit_price
        end as unit_price_per_100,

        case
            when measure_unit in ('kg', 'g') then 'per_100g'
            when measure_unit in ('l', 'ml') then 'per_100ml'
            when unit_measure like '%ea%' then 'per_each'
        end as unit_price_basis

    from parsed

)

select *
from canonical
qualify row_number() over (
    partition by retailer, product_id, search_term, snapshot_date
    order by result_rank
) = 1
