-- Staging: load all raw snapshot CSVs, cast types, canonicalize pack sizes,
-- dedupe to one row per (retailer, product_id, search_term, snapshot_date).
CREATE OR REPLACE TABLE stg_prices AS
WITH raw AS (
    SELECT * FROM read_csv_auto('data/raw/prices_*.csv', header = true, union_by_name = true)
),

typed AS (
    SELECT
        lower(trim(retailer))                       AS retailer,
        CAST(product_id AS VARCHAR)                 AS product_id,
        trim(CAST(name AS VARCHAR))                 AS name,
        trim(coalesce(CAST(brand AS VARCHAR), ''))  AS brand,
        trim(coalesce(CAST(size_raw AS VARCHAR), '')) AS size_raw,
        CAST(price AS DOUBLE)                       AS price,
        TRY_CAST(was_price AS DOUBLE)               AS was_price,
        TRY_CAST(unit_price AS DOUBLE)              AS unit_price,
        lower(trim(coalesce(CAST(unit_measure AS VARCHAR), ''))) AS unit_measure,
        CAST(is_on_special AS BOOLEAN)              AS is_on_special,
        CAST(result_rank AS INTEGER)                AS result_rank,
        CAST(search_term AS VARCHAR)                AS search_term,
        CAST(category AS VARCHAR)                   AS category,
        CAST(snapshot_date AS DATE)                 AS snapshot_date
    FROM raw
    WHERE price IS NOT NULL AND price > 0
),

sized AS (
    SELECT
        *,
        lower(replace(size_raw, ' ', ''))                                    AS size_norm,
        coalesce(TRY_CAST(regexp_extract(lower(replace(size_raw, ' ', '')),
            '^(\d+)x', 1) AS DOUBLE), 1)                                     AS pack_mult,
        TRY_CAST(regexp_extract(lower(replace(size_raw, ' ', '')),
            '(\d+(?:\.\d+)?)(kg|g|l|ml)\b', 1) AS DOUBLE)                    AS size_qty,
        regexp_extract(lower(replace(size_raw, ' ', '')),
            '(\d+(?:\.\d+)?)(kg|g|l|ml)\b', 2)                               AS size_unit,
        TRY_CAST(regexp_extract(lower(replace(size_raw, ' ', '')),
            '(\d+)(?:pack|pk|each|ea)\b', 1) AS DOUBLE)                      AS count_qty
    FROM typed
),

canonical AS (
    SELECT
        * EXCLUDE (size_norm, pack_mult, size_qty, size_unit, count_qty),
        CASE
            WHEN size_qty IS NOT NULL AND size_unit IN ('kg', 'l') THEN pack_mult * size_qty * 1000
            WHEN size_qty IS NOT NULL AND size_unit IN ('g', 'ml') THEN pack_mult * size_qty
            WHEN count_qty IS NOT NULL THEN count_qty
            ELSE NULL
        END AS canonical_qty,
        CASE
            WHEN size_qty IS NOT NULL AND size_unit IN ('kg', 'g') THEN 'g'
            WHEN size_qty IS NOT NULL AND size_unit IN ('l', 'ml') THEN 'ml'
            WHEN count_qty IS NOT NULL THEN 'each'
            ELSE NULL
        END AS canonical_unit,
        -- normalized unit price: $ per 100 g / 100 ml / 1 each, parsed from the
        -- retailer's own unit-price measure (e.g. '1l', '100g', '1ea')
        CASE
            WHEN unit_price IS NOT NULL
                 AND regexp_extract(unit_measure, '(\d+(?:\.\d+)?)(kg|g|l|ml)', 2) IN ('kg', 'l')
                THEN unit_price / (TRY_CAST(regexp_extract(unit_measure, '(\d+(?:\.\d+)?)(kg|g|l|ml)', 1) AS DOUBLE) * 1000) * 100
            WHEN unit_price IS NOT NULL
                 AND regexp_extract(unit_measure, '(\d+(?:\.\d+)?)(kg|g|l|ml)', 2) IN ('g', 'ml')
                THEN unit_price / TRY_CAST(regexp_extract(unit_measure, '(\d+(?:\.\d+)?)(kg|g|l|ml)', 1) AS DOUBLE) * 100
            WHEN unit_price IS NOT NULL AND unit_measure LIKE '%ea%'
                THEN unit_price
            ELSE NULL
        END AS unit_price_per_100,
        CASE
            WHEN regexp_extract(unit_measure, '(\d+(?:\.\d+)?)(kg|g|l|ml)', 2) IN ('kg', 'g') THEN 'per_100g'
            WHEN regexp_extract(unit_measure, '(\d+(?:\.\d+)?)(kg|g|l|ml)', 2) IN ('l', 'ml') THEN 'per_100ml'
            WHEN unit_measure LIKE '%ea%' THEN 'per_each'
            ELSE NULL
        END AS unit_price_basis
    FROM sized
)

SELECT * EXCLUDE (rn)
FROM (
    SELECT
        *,
        row_number() OVER (
            PARTITION BY retailer, product_id, search_term, snapshot_date
            ORDER BY result_rank
        ) AS rn
    FROM canonical
)
WHERE rn = 1;
