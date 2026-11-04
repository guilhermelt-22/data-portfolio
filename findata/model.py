"""Load the standardised tables into DuckDB and build the SQL model (findata/sql/model.sql)."""
from __future__ import annotations

import duckdb
import pandas as pd

from .paths import SQL


def build_model(tables: dict[str, pd.DataFrame], database: str = ":memory:") -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(database)
    for name, frame in tables.items():
        con.register(f"{name}_df", frame)
        con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM {name}_df")
        con.unregister(f"{name}_df")
    script = (SQL / "model.sql").read_text(encoding="utf-8")
    code = "\n".join(line.split("--", 1)[0] for line in script.splitlines())  # drop comments
    for statement in code.split(";"):
        if statement.strip():
            con.execute(statement)
    return con
