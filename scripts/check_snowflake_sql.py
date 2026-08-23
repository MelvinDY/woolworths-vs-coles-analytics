"""Static check that the compiled SQL is Snowflake-shaped.

Why this exists
---------------
`dbt build --target snowflake` needs a live account. Without one, the Snowflake
path is a claim rather than a fact, and the failure mode is nasty: everything
looks fine on DuckDB for months, then the first real Snowflake run dies on a
function signature. This script closes as much of that gap as can be closed
offline, so the unverified part of the Snowflake story stays small and named.

What it actually proves
-----------------------
    1. Every compiled model parses under sqlglot's Snowflake dialect, after
       substituting the one documented engine divergence (regex capture groups,
       see transform/dbt/macros/cross_db.sql).
    2. No TRY_CAST is applied to anything but a regex extraction. Snowflake's
       TRY_CAST accepts string input only and raises on a numeric column, where
       DuckDB's happily does the sensible thing — the exact class of bug that is
       invisible on the default target.
    3. No DuckDB-only syntax has crept in (SELECT * EXCLUDE / REPLACE, the
       aggregate FILTER clause).

What it does NOT prove
----------------------
That the models run. sqlglot's grammar is more permissive than Snowflake's
planner, it knows nothing about types or the information schema, and a query can
parse and still fail on execution. Passing this is a floor, not a green build.

Usage:
    python scripts/check_snowflake_sql.py        # compiles on DuckDB first, then checks
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import sqlglot
from sqlglot import exp

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from transform import dbt_runner  # noqa: E402

log = logging.getLogger("check-snowflake-sql")

COMPILED = dbt_runner.PROJECT_DIR / "target" / "compiled" / "wow_vs_coles"

# Syntax DuckDB accepts and Snowflake does not. Checked as text because sqlglot
# parses several of these happily in its DuckDB dialect.
DUCKDB_ONLY = [
    ("* EXCLUDE", "SELECT * EXCLUDE (...) - list the columns instead"),
    ("* REPLACE", "SELECT * REPLACE (...) - write the expression out instead"),
    (") FILTER (", "aggregate FILTER (WHERE ...) - use SUM(CASE WHEN ...) instead"),
]


def to_snowflake_dialect(tree: exp.Expression) -> exp.Expression:
    """Apply the project's one documented engine divergence to the AST.

    regexp_extract(subject, pattern, group)  [DuckDB]
      -> regexp_substr(subject, pattern, 1, 1, 'ce', group)  [Snowflake]

    Kept deliberately in lockstep with snowflake__regex_group in
    macros/cross_db.sql. If that macro changes, this changes with it — and if
    the two ever drift, this check stops testing the thing that ships.
    """
    def rewrite(node: exp.Expression) -> exp.Expression:
        if isinstance(node, exp.RegexpExtract):
            args = [node.this, node.expression,
                    exp.Literal.number(1), exp.Literal.number(1),
                    exp.Literal.string("ce")]
            group = node.args.get("group")
            if group is not None:
                args.append(group)
            return exp.Anonymous(this="REGEXP_SUBSTR", expressions=args)
        return node

    return tree.transform(rewrite)


def check_try_casts(tree: exp.Expression, name: str) -> list[str]:
    """TRY_CAST is legal on Snowflake only over a string expression."""
    problems = []
    for node in tree.find_all(exp.TryCast):
        inner = node.this
        # Unwrap NULLIF(regexp_substr(...), '') — the shape regex_group() emits.
        if isinstance(inner, exp.Nullif):
            inner = inner.this
        ok = isinstance(inner, exp.Anonymous) and str(inner.this).upper() == "REGEXP_SUBSTR"
        ok = ok or isinstance(inner, (exp.RegexpExtract, exp.Literal))
        if not ok:
            problems.append(
                f"{name}: try_cast over {inner.sql()[:60]!r} - Snowflake's TRY_CAST "
                f"takes string input only; use a plain cast, or extract to text first"
            )
    return problems


def check_file(path: Path) -> list[str]:
    name = path.stem
    sql = path.read_text(encoding="utf-8")

    try:
        tree = sqlglot.parse_one(sql, dialect="duckdb")
    except Exception as err:
        return [f"{name}: does not parse as DuckDB SQL - {err}"]

    # Scan the regenerated SQL with comments dropped, not the file. The models
    # carry comments that discuss the very constructs being banned, and a plain
    # text search over the source flags the prose explaining why the construct
    # is absent.
    normalized = tree.sql(dialect="duckdb", comments=False).lower()
    problems = [f"{name}: {why}" for token, why in DUCKDB_ONLY if token.lower() in normalized]

    problems += check_try_casts(tree, name)

    snow = to_snowflake_dialect(tree).sql(dialect="snowflake", comments=False)
    try:
        sqlglot.parse_one(snow, dialect="snowflake")
    except Exception as err:
        problems.append(f"{name}: does not parse as Snowflake SQL - {err}")

    return problems


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)s %(name)s %(message)s", force=True)

    # Compile on DuckDB: the Snowflake target cannot compile without credentials,
    # which is the whole reason this script exists.
    dbt_runner.invoke(["compile", "--target", "duckdb"])

    # is_file() matters: dbt writes a *directory* named `<model>.sql/` alongside
    # the model, holding the SQL for that model's tests. Those get checked too —
    # generated test queries run on Snowflake like anything else.
    paths = sorted(p for p in COMPILED.rglob("*.sql") if p.is_file())
    if not paths:
        log.error("No compiled SQL under %s", COMPILED)
        return 1

    problems: list[str] = []
    for path in paths:
        problems += check_file(path)

    if problems:
        log.error("%d Snowflake portability problem(s):", len(problems))
        for p in problems:
            log.error("  %s", p)
        return 1

    # Plain hyphens in console output: the Windows console decodes this as the
    # system codepage and an em-dash lands as a replacement character.
    log.info("%d compiled statements are Snowflake-shaped. "
             "This is a syntax floor, not a green build - see docs/snowflake.md.",
             len(paths))
    return 0


if __name__ == "__main__":
    sys.exit(main())
