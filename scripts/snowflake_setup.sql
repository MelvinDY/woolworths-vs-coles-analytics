-- Run once, in a Snowflake worksheet, before the first `--target snowflake` build.
--
-- Everything this project needs on the Snowflake side is here. It is short on
-- purpose: the point of the exercise is that the same dbt project builds on a
-- second engine, not that the second engine gets an elaborate estate.
--
-- Cost control is the only interesting decision in this file. The trial is 30
-- days of credits and there is no card behind it, so the warehouse is the
-- smallest size that exists and suspends after a minute of idle. A dbt build of
-- this project is a few seconds of compute; an XSMALL warehouse left running by
-- accident overnight is most of a day's credits. auto_suspend is what stops a
-- forgotten session quietly ending the experiment.

create warehouse if not exists GROCERY_WH
    warehouse_size       = 'XSMALL'
    auto_suspend         = 60      -- seconds idle before it stops billing
    auto_resume          = true    -- so dbt never waits on a manual start
    initially_suspended  = true;

create database if not exists GROCERY;
create schema   if not exists GROCERY.ANALYTICS;

-- The trial's default role owns everything it creates, so no grants are needed
-- for a single-user setup. If you build this under a non-admin role instead:
--
--   grant usage   on warehouse GROCERY_WH        to role <your_role>;
--   grant usage   on database  GROCERY           to role <your_role>;
--   grant all     on schema    GROCERY.ANALYTICS to role <your_role>;

-- Sanity check: these three should match SNOWFLAKE_WAREHOUSE, SNOWFLAKE_DATABASE
-- and SNOWFLAKE_SCHEMA in your .env.
select current_warehouse(), current_database(), current_schema();
