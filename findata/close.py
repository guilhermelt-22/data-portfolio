"""Month-end close pipeline: ingest -> validate -> model.

Usage:  python -m findata.close --period 2026-10
"""
from __future__ import annotations

import argparse
import time
from dataclasses import dataclass

import duckdb
import pandas as pd

from . import ingest, validate
from .model import build_model


@dataclass
class CloseResult:
    period: str
    con: duckdb.DuckDBPyConnection
    issues: pd.DataFrame
    excluded_lines: pd.DataFrame
    seconds: float


def run(period: str) -> CloseResult:
    start = time.perf_counter()
    gl = ingest.load_gl()
    budget = ingest.load_budget()
    entities = ingest.load_config("entities")
    account_map = ingest.load_config("account_mapping")
    dept_map = ingest.load_config("department_mapping")
    line_map = ingest.load_config("budget_line_mapping")

    issues = (validate.check_period_present(gl, period, entities["entity"].tolist())
              + validate.check_balanced_journals(gl)
              + validate.check_duplicates(gl)
              + validate.check_unmapped_accounts(gl, account_map)
              + validate.check_unmapped_departments(gl, dept_map)
              + validate.check_budget_lines(budget, line_map))

    duplicates = validate.find_duplicate_lines(gl)  # quarantined, not modelled
    clean = gl.drop(index=duplicates.index)

    con = build_model({
        "gl": clean,
        "account_mapping": account_map,
        "department_mapping": dept_map,
        "coa": ingest.load_config("group_chart_of_accounts"),
        "entities": entities,
        "fx": ingest.load_fx(),
        "budget": budget,
        "budget_line_mapping": line_map,
        "budget_fx": ingest.load_budget_fx(),
    })
    issues += validate.check_opex_without_department(con) + validate.check_intercompany(con)
    return CloseResult(period, con, validate.to_frame(issues), duplicates, time.perf_counter() - start)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--period", default="2026-10", help="month to close, YYYY-MM")
    args = parser.parse_args()
    result = run(args.period)
    summary = result.issues.groupby(["severity", "check"]).size().rename("count")
    print(f"Close {result.period}: {len(result.issues)} issue(s) in {result.seconds:.1f}s")
    print(summary.to_string())


if __name__ == "__main__":
    main()
