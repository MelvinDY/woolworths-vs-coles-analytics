{#
    SCD2 over the price of every product either chain lists.

    Why `check` and not `timestamp`
    -------------------------------
    The timestamp strategy needs a column the *source* maintains that says when
    the row last changed. Neither retailer publishes one. What the payloads
    carry is a price, and what this repo adds is `fetched_at` — the moment we
    looked, which is a fact about the collector, not about the product. Feeding
    that to the timestamp strategy would open a new validity window every single
    day for all ~1,900 rows and produce an SCD2 table that is really just a
    daily append with extra columns.

    `check` compares the values themselves, which is the honest question here:
    did the price move? A product whose price holds for six weeks stays one row
    with a six-week validity window, which is what an SCD2 is for.

    Cost of that choice, stated plainly: `check` cannot see a change that
    happens and reverts between two observations. If a price drops on Tuesday
    afternoon and is back by Wednesday morning, this snapshot never knows. Daily
    collection is the resolution limit of the whole project, not of the strategy.

    Deletions are deliberately not invalidated
    ------------------------------------------
    `hard_deletes` is left at its default (ignore). When a product drops out of
    the search results for a day, its record stays open rather than being closed
    off. A product missing from a search response has not been discontinued and
    its price has not changed — nobody looked, and the search API is a ranking
    endpoint, not an inventory feed. Closing the record would encode "the price
    stopped existing on 2026-08-15", which is not something this data can say.

    Historical replay
    -----------------
    dbt stamps validity windows with the wall clock. The repo already holds
    months of collected days, so run_pipeline.py replays them one at a time with
    --vars '{snapshot_as_of: <date>}', and macros/snapshot_get_time.sql makes
    both the stamp and the filter below follow that date. Without the override
    every historical price change would be dated the afternoon of the port.
#}

{% snapshot snap_product_prices %}

{{ config(
    unique_key = "product_key",
    strategy = 'check',
    check_cols = ['price', 'was_price', 'is_on_special'],
) }}

select
    -- The grain is (retailer, product_id); product ids collide across chains,
    -- so the key is the pair of them. Snapshots take one key expression, hence
    -- the concatenation rather than a two-column key.
    retailer || '|' || product_id as product_key,

    retailer,
    product_id,
    name,
    brand,
    size_raw,
    category,

    price,
    was_price,
    is_on_special,

    -- The day this version of the row was first seen. Mirrors dbt_valid_from
    -- as a plain date, which is what every downstream query actually wants.
    snapshot_date as first_observed_on

from {{ ref('int_product_prices_daily') }}
where snapshot_date = {{ snapshot_as_of_date() }}

{% endsnapshot %}
