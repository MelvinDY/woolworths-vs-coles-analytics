-- Accepted cross-retailer pairs, one row per pair per snapshot day.
--
-- The table itself is produced by matching/match_products.py (rapidfuzz;
-- see the module docstring for the tiering rules) and lands as a source. This
-- model is the thin wrapper that puts it in the dbt DAG so the marts that read
-- it have real lineage and the grain is tested on every build. The name is
-- kept from v1 so the port is a reviewable diff rather than a rename.

select
    snapshot_date,
    search_term,
    category,
    match_type,
    name_score,
    wow_product_id,
    wow_name,
    wow_brand,
    wow_size,
    wow_price,
    coles_product_id,
    coles_name,
    coles_brand,
    coles_size,
    coles_price

from {{ source('matching', 'matched_pairs') }}
