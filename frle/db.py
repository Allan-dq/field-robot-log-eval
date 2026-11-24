"""DuckDB views over the Parquet lake."""

from __future__ import annotations

import duckdb

from frle.config import Config
from frle.schema import TABLES


def connect(cfg: Config) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    for table in TABLES:
        files = sorted((cfg.lake_dir / table).glob("*/*.parquet"))
        if files:
            paths = ", ".join(f"'{p.as_posix()}'" for p in files)
            con.execute(f"CREATE VIEW {table} AS SELECT * FROM read_parquet([{paths}])")
    return con
