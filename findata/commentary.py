"""Rules-based variance commentary.

The engine explains *where* a variance comes from (line, entity, account, department, FX);
the analyst adds *why*. Every sentence is built from reconciled numbers, so it can be checked
against the pack. A language model could rephrase these drafts, but never computes them.
"""
from __future__ import annotations

import duckdb
import pandas as pd

from .ingest import load_config

MATERIALITY_USD = 20_000  # ignore variances smaller than this ...
MATERIALITY_PCT = 0.05  # ... or smaller than this share of the budget line
INCOME_LINES = {"Revenue", "Other Income/Expense"}


def is_material(variance: float, budget: float) -> bool:
    return abs(variance) >= MATERIALITY_USD and abs(variance) >= MATERIALITY_PCT * abs(budget)


def _k(value: float) -> str:
    return f"${abs(value) / 1e3:,.0f}k"


def _signed_k(value: float) -> str:
    return f"{'+' if value > 0 else '-'}{_k(value)}"


def _sentence(line: str, scope: str, variance: float, budget: float, fx: float, driver: dict,
              unallocated: float) -> str:
    income = line in INCOME_LINES
    direction = ("above" if variance > 0 else "below") if income else ("under" if variance > 0 else "over")
    verdict = "favourable" if variance > 0 else "unfavourable"
    pct = f" ({abs(variance) / abs(budget):.1%})" if budget else ""
    dept = f" / {driver['department_name']}" if driver["department_name"] else ""
    text = (f"{line} is {_k(variance)}{pct} {direction} budget {scope} ({verdict}). "
            f"Largest driver: {driver['entity']} {driver['account_name']}{dept} ({_signed_k(driver['variance'])}).")
    if abs(fx) >= 0.25 * abs(variance):
        text += f" FX explains {_signed_k(fx)} (budget rates vs actual rates)."
    if abs(unallocated) >= 0.25 * abs(variance):
        text += (f" Caution: {_k(unallocated)} of actual cost in this line has no valid department, so the "
                 "departmental split is distorted until the mapping is fixed (see Data checks).")
    return text + " [Analyst: add business context]"


def variance_commentary(con: duckdb.DuckDBPyConnection, period: str, year_start: str) -> pd.DataFrame:
    names = dict(load_config("departments").values)
    scopes = {"month": (period, period, f"in {pd.Period(period, 'M').strftime('%b-%y')}"),
              "ytd": (year_start, period, "year to date")}
    rows = []
    for scope, (start, end, label) in scopes.items():
        params = {"start": start, "end": end}
        lines = con.execute("""
            SELECT statement_line, SUM(variance_usd) AS variance, SUM(budget_usd) AS budget,
                   SUM(fx_effect_usd) AS fx,
                   SUM(actual_usd) FILTER (WHERE department = 'UNALLOCATED' AND account_type = 'opex')
                       AS unallocated
            FROM bva WHERE period BETWEEN $start AND $end
            GROUP BY statement_line
        """, params).df().fillna({"unallocated": 0.0})
        for line in lines.sort_values("variance", key=abs, ascending=False).itertuples():
            if not is_material(line.variance, line.budget):
                continue
            driver = con.execute("""
                SELECT entity, account_name, department, SUM(variance_usd) AS variance
                FROM bva WHERE period BETWEEN $start AND $end AND statement_line = $line
                GROUP BY ALL ORDER BY ABS(SUM(variance_usd)) DESC LIMIT 1
            """, params | {"line": line.statement_line}).df().iloc[0].to_dict()
            driver["department_name"] = names.get(driver["department"], "")
            rows.append({"scope": scope, "statement_line": line.statement_line, "variance_usd": line.variance,
                         "commentary": _sentence(line.statement_line, label, line.variance, line.budget,
                                                 line.fx, driver, line.unallocated)})
    return pd.DataFrame(rows, columns=["scope", "statement_line", "variance_usd", "commentary"])
