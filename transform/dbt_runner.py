"""Drive the dbt project from Python.

run_pipeline.py is still the one command an operator types, so dbt is invoked
in-process through dbtRunner rather than shelled out to. Everything here is a
thin wrapper: the arguments are exactly what you would type by hand, and
`dbt build` from transform/dbt/ does the same thing without Python in the way.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dbt.cli.main import dbtRunner

from warehouse import duckdb_path, target_name

log = logging.getLogger(__name__)

PROJECT_DIR = Path(__file__).resolve().parent / "dbt"
PACKAGES_DIR = PROJECT_DIR / "dbt_packages"


def _env() -> None:
    """Point dbt at this project's profiles.yml and warehouse file."""
    os.environ.setdefault("DBT_PROFILES_DIR", str(PROJECT_DIR))
    if target_name() == "duckdb":
        # An absolute path, because dbt's working directory is not the caller's.
        os.environ["DUCKDB_PATH"] = str(duckdb_path())


def invoke(args: list[str], allow_failure: bool = False) -> bool:
    _env()
    full = args + ["--project-dir", str(PROJECT_DIR)]
    log.info("dbt %s", " ".join(args))
    result = dbtRunner().invoke(full)
    if not result.success and not allow_failure:
        raise RuntimeError(f"dbt {' '.join(args)} failed: {result.exception or 'see log above'}")
    return bool(result.success)


def deps() -> None:
    """Install dbt packages if they are not already vendored in."""
    if PACKAGES_DIR.exists() and any(PACKAGES_DIR.iterdir()):
        return
    invoke(["deps"])


def source_freshness() -> bool:
    """Check how old the newest snapshot is.

    Deliberately non-fatal. A stale collector must be loud, but it must not stop
    an operator rebuilding the marts from the history already collected — that
    is exactly the situation where you want the dashboard rebuilt so you can see
    where the series stopped.
    """
    fresh = invoke(["source", "freshness"], allow_failure=True)
    if not fresh:
        log.warning(
            "SOURCE FRESHNESS FAILED — the newest raw snapshot is stale. "
            "Check the collector (scripts/collect.ps1) and logs/. Continuing "
            "with the history already on disk."
        )
    return fresh


def run(select: list[str] | None = None, full_refresh: bool = False) -> None:
    args = ["run"]
    if select:
        args += ["--select", *select]
    if full_refresh:
        args.append("--full-refresh")
    invoke(args)


def snapshot(as_of: str | None = None) -> None:
    args = ["snapshot"]
    if as_of:
        args += ["--vars", f"{{snapshot_as_of: {as_of}}}"]
    invoke(args)


def build(full_refresh: bool = False, as_of: str | None = None) -> None:
    args = ["build"]
    if as_of:
        # Pins the snapshot node to the latest collected day so that the
        # snapshot inside `dbt build` is the same no-op replay the loop just
        # ran, rather than a second, wall-clock-stamped pass over the data.
        args += ["--vars", f"{{snapshot_as_of: {as_of}}}"]
    if full_refresh:
        args.append("--full-refresh")
    invoke(args)
