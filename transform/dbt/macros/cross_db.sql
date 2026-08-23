{#
    The one place where DuckDB and Snowflake are allowed to diverge.

    Everything else in this project is written in SQL both engines accept
    verbatim. Where that was not possible the difference lives here behind
    adapter.dispatch, so a reviewer can see the complete list of engine
    dependencies by reading one file.

    Divergence #1 — regular-expression capture groups.
      DuckDB   regexp_extract(subject, pattern, group)   -> '' when no match
      Snowflake regexp_substr(subject, pattern, 1, 1, 'ce', group) -> NULL

    Both are normalised to NULL so downstream CASE expressions behave the same.

    Note what is deliberately NOT here: the patterns themselves. Every pattern
    in this project is written without a single backslash ([0-9] rather than
    \d, [.] rather than \., ([^a-z]|$) rather than \b) because Snowflake treats
    backslash as a string escape and DuckDB does not. Backslash-free patterns
    mean one literal works on both engines, which is worth the slight verbosity.
#}

{% macro regex_group(subject, pattern, group_num) -%}
    {{ return(adapter.dispatch('regex_group', 'wow_vs_coles')(subject, pattern, group_num)) }}
{%- endmacro %}


{% macro default__regex_group(subject, pattern, group_num) -%}
    nullif(regexp_extract({{ subject }}, '{{ pattern }}', {{ group_num }}), '')
{%- endmacro %}


{% macro snowflake__regex_group(subject, pattern, group_num) -%}
    {#
        Positional arguments are position=1, occurrence=1, then the regex
        parameters and the capture group. 'c' = case sensitive, 'e' = return the
        capture group rather than the whole match. Snowflake will extract a group
        when group_num is given even without 'e', but stating it leaves nothing
        to a default.

        The result is VARCHAR, which is also why every try_cast in this project
        wraps one of these calls and nothing else: Snowflake's TRY_CAST takes
        string input only and errors on a numeric column.
    #}
    nullif(regexp_substr({{ subject }}, '{{ pattern }}', 1, 1, 'ce', {{ group_num }}), '')
{%- endmacro %}


{#
    Divergence #2 — "does this string contain a match for this pattern".
      DuckDB    regexp_matches(subject, pattern)  -> substring search
      Snowflake regexp_like(subject, pattern)     -> whole-string match

    Snowflake anchors implicitly, so the pattern is padded to make both engines
    answer the substring question. Same no-backslash rule as above.

    pattern_sql is a SQL expression, not a literal, because the patterns live in
    the basket_relevance seed rather than in the model. Pass a quoted string if
    you want a constant.
#}

{% macro regex_contains(subject, pattern_sql) -%}
    {{ return(adapter.dispatch('regex_contains', 'wow_vs_coles')(subject, pattern_sql)) }}
{%- endmacro %}


{% macro default__regex_contains(subject, pattern_sql) -%}
    regexp_matches({{ subject }}, {{ pattern_sql }})
{%- endmacro %}


{% macro snowflake__regex_contains(subject, pattern_sql) -%}
    regexp_like({{ subject }}, '.*(' || {{ pattern_sql }} || ').*')
{%- endmacro %}
