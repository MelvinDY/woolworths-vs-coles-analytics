{#
    Override of dbt's built-in snapshot_get_time().

    dbt's `check` strategy stamps dbt_valid_from / dbt_valid_to with the wall
    clock at run time. That is right for a snapshot that runs once a day
    forever, and wrong for this repo, which already holds months of collected
    days that have to be replayed into the SCD2 table in order. Replaying them
    with the default would date every historical price change "today" and turn
    a real price series into a fiction.

    run_pipeline.py therefore replays one day at a time, passing
    --vars '{snapshot_as_of: 2026-08-13}', and this macro makes dbt stamp the
    validity window with the day the price was actually observed.

    With no var set the macro falls back to dbt's own behaviour, so a bare
    `dbt snapshot` still works.
#}

{% macro snapshot_get_time() -%}
    {%- set as_of = var('snapshot_as_of', '') -%}
    {%- if as_of -%}
        cast('{{ as_of }}' as timestamp)
    {%- else -%}
        {{ current_timestamp() }}
    {%- endif -%}
{%- endmacro %}


{#
    The day the snapshot query should look at. Mirrors snapshot_get_time():
    when replaying, only that day's rows are the "current state" as far as the
    snapshot is concerned.
#}
{% macro snapshot_as_of_date() -%}
    {%- set as_of = var('snapshot_as_of', '') -%}
    {%- if as_of -%}
        cast('{{ as_of }}' as date)
    {%- else -%}
        (select max(snapshot_date) from {{ ref('int_product_prices_daily') }})
    {%- endif -%}
{%- endmacro %}
