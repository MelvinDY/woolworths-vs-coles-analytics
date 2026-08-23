"""The one place that knows which warehouse we are pointed at.

dbt handles the SQL side of running on two engines. Three steps sit outside
dbt and still have to work on both: loading the raw CSVs, running the fuzzy
matcher, and reading the marts back out to build the dashboard. They all go
through the small interface here rather than importing duckdb directly.

Target selection is one environment variable, shared with dbt's profiles.yml:

    DBT_TARGET=duckdb      (default — local, free, permanent)
    DBT_TARGET=snowflake   (trial; needs SNOWFLAKE_* credentials)

DuckDB is the default on purpose. When the Snowflake trial lapses, nothing in
this repo needs editing for `python run_pipeline.py` to keep working.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DUCKDB_PATH = PROJECT_ROOT / "data" / "warehouse.duckdb"
ENV_FILE = PROJECT_ROOT / ".env"


def _load_env_file() -> None:
    """Read .env at the repo root, if there is one.

    Snowflake credentials have to reach both this module and dbt's profiles.yml,
    and dbt is invoked in-process, so putting them in os.environ once here covers
    both. A file rather than shell exports because the credentials then survive a
    new terminal and stay in one gitignored place instead of a shell history.

    Real environment variables always win: an already-set value is never
    overwritten, so CI or a one-off `DBT_TARGET=duckdb ...` still beats the file.
    """
    if not ENV_FILE.exists():
        return
    for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_env_file()


def target_name() -> str:
    return os.environ.get("DBT_TARGET", "duckdb").strip().lower()


def duckdb_path() -> Path:
    return Path(os.environ.get("DUCKDB_PATH") or DEFAULT_DUCKDB_PATH)


class Warehouse:
    """Minimal read/write interface over the configured target."""

    name = "abstract"

    @property
    def schema(self) -> str:
        raise NotImplementedError

    def query_df(self, sql: str, params: list | None = None) -> pd.DataFrame:
        raise NotImplementedError

    def query_one(self, sql: str, params: list | None = None):
        df = self.query_df(sql, params)
        if df.empty:
            return None
        return tuple(df.iloc[0])

    def query_rows(self, sql: str, params: list | None = None) -> list[tuple]:
        return [tuple(r) for r in self.query_df(sql, params).itertuples(index=False)]

    def replace_table(self, name: str, df: pd.DataFrame) -> None:
        raise NotImplementedError

    def table_exists(self, name: str) -> bool:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError

    def __enter__(self) -> "Warehouse":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class DuckDBWarehouse(Warehouse):
    name = "duckdb"

    def __init__(self, path: Path | None = None, read_only: bool = False):
        import duckdb

        self.path = Path(path or duckdb_path())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.con = duckdb.connect(str(self.path), read_only=read_only)

    @property
    def schema(self) -> str:
        return "main"

    def query_df(self, sql: str, params: list | None = None) -> pd.DataFrame:
        rel = self.con.execute(sql, params) if params else self.con.execute(sql)
        df = rel.df()
        df.columns = [c.lower() for c in df.columns]
        return df

    def replace_table(self, name: str, df: pd.DataFrame) -> None:
        df = df.rename(columns={c: c.lower() for c in df.columns})
        self.con.register("_incoming_df", df)
        self.con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM _incoming_df")
        self.con.unregister("_incoming_df")
        log.info("%s: %d rows written to DuckDB", name, len(df))

    def table_exists(self, name: str) -> bool:
        found = self.con.execute(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE lower(table_name) = lower(?)",
            [name],
        ).fetchone()[0]
        return bool(found)

    def close(self) -> None:
        self.con.close()


class SnowflakeWarehouse(Warehouse):
    """Snowflake target.

    Unverified against a live account — see docs/snowflake.md. It is written
    from the connector's documented behaviour and is deliberately kept to the
    same four operations as the DuckDB target so there is little room for the
    two to drift.
    """

    name = "snowflake"

    def __init__(self):
        import snowflake.connector
        from snowflake.connector.pandas_tools import write_pandas

        # '?' placeholders on both engines. Without this the connector expects
        # %s and every shared query in this repo breaks on one target only.
        snowflake.connector.paramstyle = "qmark"
        self._write_pandas = write_pandas

        missing = [
            v for v in ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD")
            if not os.environ.get(v)
        ]
        if missing:
            raise RuntimeError(
                "DBT_TARGET=snowflake but these are unset: " + ", ".join(missing)
                + f". Copy {ENV_FILE.name}.example to {ENV_FILE.name} and fill it in "
                  "(see docs/snowflake.md), or drop --target to build on DuckDB."
            )

        self._schema = os.environ.get("SNOWFLAKE_SCHEMA", "ANALYTICS")
        self.con = snowflake.connector.connect(
            account=os.environ["SNOWFLAKE_ACCOUNT"],
            user=os.environ["SNOWFLAKE_USER"],
            password=os.environ["SNOWFLAKE_PASSWORD"],
            role=os.environ.get("SNOWFLAKE_ROLE", "ACCOUNTADMIN"),
            warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE", "GROCERY_WH"),
            database=os.environ.get("SNOWFLAKE_DATABASE", "GROCERY"),
            schema=self._schema,
        )

    @property
    def schema(self) -> str:
        return self._schema

    def query_df(self, sql: str, params: list | None = None) -> pd.DataFrame:
        cur = self.con.cursor()
        try:
            cur.execute(sql, params) if params else cur.execute(sql)
            df = cur.fetch_pandas_all() if cur.description else pd.DataFrame()
        finally:
            cur.close()
        df.columns = [c.lower() for c in df.columns]
        return df

    def replace_table(self, name: str, df: pd.DataFrame) -> None:
        # quote_identifiers=False so the table lands with Snowflake's normal
        # unquoted-uppercase identifiers, which is what dbt's generated SQL
        # resolves to. Quoted lowercase would make the source unreferenceable.
        df = df.rename(columns={c: c.upper() for c in df.columns})
        success, _, nrows, _ = self._write_pandas(
            self.con,
            df,
            table_name=name.upper(),
            schema=self._schema,
            auto_create_table=True,
            overwrite=True,
            quote_identifiers=False,
        )
        if not success:
            raise RuntimeError(f"write_pandas failed for {name}")
        log.info("%s: %d rows written to Snowflake", name, nrows)

    def table_exists(self, name: str) -> bool:
        df = self.query_df(
            "SELECT count(*) AS n FROM information_schema.tables "
            "WHERE table_schema = ? AND table_name = ?",
            [self._schema.upper(), name.upper()],
        )
        return bool(df.iloc[0, 0])

    def close(self) -> None:
        self.con.close()


def connect(read_only: bool = False) -> Warehouse:
    target = target_name()
    if target == "duckdb":
        return DuckDBWarehouse(read_only=read_only)
    if target == "snowflake":
        return SnowflakeWarehouse()
    raise ValueError(f"Unknown DBT_TARGET {target!r}; expected 'duckdb' or 'snowflake'")
