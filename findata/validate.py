"""Data-quality checks that run before any number reaches a report.

Each check returns a list of Issue records. 'blocking' issues stop the pack from being final until
someone fixes the source or the mapping; 'excluded' lines are quarantined automatically; 'warning'
issues are reported but do not block.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import duckdb
import pandas as pd

TOLERANCE = 0.005  # half a cent


@dataclass
class Issue:
    check: str
    severity: str  # "blocking" | "excluded" | "warning"
    entity: str
    period: str
    detail: str
    amount: float  # local currency unless the detail says USD
    rows: str  # where to look in the source files


def _where(df: pd.DataFrame, limit: int = 5) -> str:
    refs = (df["source_file"] + ":" + df["source_row"].astype(str)).head(limit).tolist()
    more = f" (+{len(df) - limit} more)" if len(df) > limit else ""
    return ", ".join(refs) + more


def find_duplicate_lines(gl: pd.DataFrame) -> pd.DataFrame:
    """Return the *extra* copies of lines that were exported more than once (the first copy is kept).

    Context: exports sometimes repeat a whole transaction (re-run, edit history, overlapping date
    ranges). Each copy is a balanced journal, so the trial balance still ties and nobody notices,
    but the expense is counted twice. Watch out for legitimate look-alikes: in the DATEV file the
    contra (bank) lines of one payroll booking batch share je_id, account and date, and two of them
    can carry the same amount by coincidence.
    """
    # A line is a candidate when it is identical on every business field (not on source_row,
    # which always differs). It is only flagged when its *whole journal* is repeated: every
    # distinct line of that journal appears the same number of times, at least twice. That keeps
    # coincidental twins (two equal bank lines inside one DATEV payroll batch) out of the result.
    key = ["entity", "je_id", "date", "local_account", "local_department", "debit", "credit"]
    occurrence = gl.groupby(key, sort=False).cumcount()  # 0 = first copy, 1 = second, ...
    copies = gl.groupby(key, sort=False)["je_id"].transform("size")
    journal = [gl["entity"], gl["je_id"]]
    repeated_journal = (copies.groupby(journal).transform("min") > 1) & (
        copies.groupby(journal).transform("min") == copies.groupby(journal).transform("max"))
    return gl[repeated_journal & (occurrence > 0)]


def check_duplicates(gl: pd.DataFrame) -> list[Issue]:
    dupes = find_duplicate_lines(gl)
    issues = []
    for (entity, je_id), rows in dupes.groupby(["entity", "je_id"]):
        issues.append(Issue("duplicate_lines", "excluded", entity, rows["period"].iloc[0],
                            f"Journal {je_id}: {len(rows)} line(s) exported more than once; the extra copy is excluded "
                            f"(would have double counted {rows['debit'].sum():,.2f})",
                            float(rows["debit"].sum()), _where(rows)))
    return issues


def check_balanced_journals(gl: pd.DataFrame) -> list[Issue]:
    sums = gl.groupby(["entity", "je_id"], as_index=False).agg(
        debit=("debit", "sum"), credit=("credit", "sum"), period=("period", "first"))
    sums["diff"] = (sums["debit"] - sums["credit"]).round(2)
    issues = []
    for row in sums[sums["diff"].abs() > TOLERANCE].itertuples():
        rows = gl[(gl["entity"] == row.entity) & (gl["je_id"] == row.je_id)]
        issues.append(Issue("unbalanced_journal", "blocking", row.entity, row.period,
                            f"Journal {row.je_id} does not balance (debits - credits = {row.diff:,.2f}); "
                            "the export may have been cut off", float(row.diff), _where(rows)))
    return issues


def check_unmapped_accounts(gl: pd.DataFrame, account_map: pd.DataFrame) -> list[Issue]:
    known = set(zip(account_map["entity"], account_map["local_account"]))
    missing = gl[[(e, a) not in known for e, a in zip(gl["entity"], gl["local_account"])]]
    issues = []
    for (entity, account), rows in missing.groupby(["entity", "local_account"]):
        issues.append(Issue("unmapped_account", "blocking", entity, rows["period"].max(),
                            f"Local account {account} ('{rows['local_account_name'].iloc[0]}') is not in the "
                            "account mapping; "
                            f"{len(rows)} line(s) would drop out of the P&L",
                            float((rows["debit"] - rows["credit"]).sum()), _where(rows)))
    return issues


def check_unmapped_departments(gl: pd.DataFrame, dept_map: pd.DataFrame) -> list[Issue]:
    known = set(zip(dept_map["source"], dept_map["local_department"]))
    tagged = gl[gl["local_department"] != ""]
    missing = tagged[[(e, d) not in known for e, d in zip(tagged["entity"], tagged["local_department"])]]
    issues = []
    for (entity, dept), rows in missing.groupby(["entity", "local_department"]):
        issues.append(Issue("unmapped_department", "warning", entity, rows["period"].max(),
                            f"Department '{dept}' is not in the department mapping; {len(rows)} line(s) "
                            "will show as 'Unallocated'", float((rows["debit"] - rows["credit"]).sum()),
                            _where(rows)))
    return issues


def check_period_present(gl: pd.DataFrame, period: str, entities: list[str]) -> list[Issue]:
    present = set(gl.loc[gl["period"] == period, "entity"])
    return [Issue("missing_period", "blocking", e, period, f"No transactions for {period}: export incomplete?",
                  0.0, "") for e in entities if e not in present]


def check_budget_lines(budget: pd.DataFrame, line_map: pd.DataFrame) -> list[Issue]:
    missing = budget[~budget["budget_line"].isin(line_map["budget_line"])]
    return [Issue("unmapped_budget_line", "blocking", e, "", f"Budget line '{line}' is not mapped to an account",
                  float(rows["amount_local"].sum()), "FY2026_Budget_v3_FINAL.xlsx")
            for (e, line), rows in missing.groupby(["entity", "budget_line"])]


def check_opex_without_department(con: duckdb.DuckDBPyConnection) -> list[Issue]:
    rows = con.execute("""
        SELECT entity, period, je_id, source_file, source_row, debit - credit AS amount
        FROM gl_mapped
        WHERE account_type = 'opex' AND department IS NULL
    """).df()
    return [Issue("missing_department", "warning", r.entity, r.period,
                  f"Opex line in journal {r.je_id} has no department; it will show as 'Unallocated'",
                  float(r.amount), f"{r.source_file}:{r.source_row}") for r in rows.itertuples()]


def check_intercompany(con: duckdb.DuckDBPyConnection, threshold_usd: float = 1_000.0) -> list[Issue]:
    rows = con.execute("""
        SELECT period,
               SUM(CASE WHEN account = '4900' THEN pl_usd END) AS ic_revenue,
               -SUM(CASE WHEN account = '6900' THEN pl_usd END) AS ic_expense
        FROM pl_lines
        WHERE account IN ('4900', '6900')
        GROUP BY period
        ORDER BY period
    """).df()
    rows["diff"] = rows["ic_revenue"] - rows["ic_expense"]
    return [Issue("intercompany_mismatch", "warning", "GROUP", r.period,
                  f"Intercompany revenue ({r.ic_revenue:,.0f}) and expense ({r.ic_expense:,.0f}) differ by "
                  f"USD {r.diff:,.0f} after FX; elimination leaves a residual", float(r.diff), "")
            for r in rows.itertuples() if abs(r.diff) > threshold_usd]


def to_frame(issues: list[Issue]) -> pd.DataFrame:
    cols = ["check", "severity", "entity", "period", "detail", "amount", "rows"]
    return pd.DataFrame([asdict(i) for i in issues], columns=cols)
