"""Case A: the monthly management pack (Excel), built from the close model in one command.

Usage:  python -m findata.report --period 2026-10
"""
from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import pandas as pd
import xlsxwriter

from . import ingest
from .close import CloseResult, run
from .commentary import variance_commentary
from .paths import OUTPUT

OPEX = ["Payroll", "Contractors", "Software", "Marketing Programs", "Travel & Entertainment", "Facilities",
        "Professional Fees", "Recruiting"]
LAYOUT = [  # label, kind, statement lines summed into it
    ("Revenue", "line", ["Revenue"]),
    ("Cost of Revenue", "line", ["Cost of Revenue"]),
    ("Gross Profit", "subtotal", ["Revenue", "Cost of Revenue"]),
    *[(name, "line", [name]) for name in OPEX],
    ("Total Operating Expenses", "subtotal", OPEX),
    ("Operating Result", "subtotal", ["Revenue", "Cost of Revenue", *OPEX]),
    ("Other Income/Expense", "line", ["Other Income/Expense"]),
    ("Net Result", "total", ["Revenue", "Cost of Revenue", *OPEX, "Other Income/Expense"]),
]


# --------------------------------------------------------------------------- data
def apply_layout(lines: pd.DataFrame) -> pd.DataFrame:
    """lines: indexed by statement_line, numeric columns -> one row per LAYOUT entry."""
    rows = [{"label": label, "kind": kind, **lines.reindex(parts).fillna(0.0).sum().to_dict()}
            for label, kind, parts in LAYOUT]
    return pd.DataFrame(rows)


def pnl(con: duckdb.DuckDBPyConnection, period: str, year_start: str) -> pd.DataFrame:
    lines = con.execute("""
        SELECT statement_line,
               SUM(actual_usd) FILTER (WHERE period = $p) AS m_act,
               SUM(budget_usd) FILTER (WHERE period = $p) AS m_bud,
               SUM(actual_usd) AS y_act,
               SUM(budget_usd) AS y_bud
        FROM bva WHERE period BETWEEN $start AND $p
        GROUP BY statement_line
    """, {"p": period, "start": year_start}).df().set_index("statement_line").fillna(0.0)
    out = apply_layout(lines)
    for scope in ("m", "y"):
        out[f"{scope}_var"] = out[f"{scope}_act"] - out[f"{scope}_bud"]
        out[f"{scope}_pct"] = out[f"{scope}_var"] / out[f"{scope}_bud"].abs().where(out[f"{scope}_bud"] != 0)
    return out


def kpis(con: duckdb.DuckDBPyConnection, table: pd.DataFrame, period: str) -> dict[str, float | None]:
    row = table.set_index("label")
    cash = con.execute("SELECT period, SUM(cash_usd) AS cash FROM cash_balance GROUP BY period ORDER BY period"
                       ).df().set_index("period")["cash"]
    i = cash.index.get_loc(period)
    burn = (cash.iloc[i - 3] - cash.iloc[i]) / 3
    revenue = row.loc["Revenue", "m_act"]
    return {
        "Revenue": revenue,
        "Gross margin": row.loc["Gross Profit", "m_act"] / revenue,
        "Operating expenses": row.loc["Total Operating Expenses", "m_act"],
        "Operating result": row.loc["Operating Result", "m_act"],
        "Cash": cash.iloc[i],
        "Net burn (3-mo avg)": burn,
        "Runway (months)": cash.iloc[i] / burn if burn > 0 else None,
    }


def by_entity(con: duckdb.DuckDBPyConnection, period: str) -> pd.DataFrame:
    df = con.execute("SELECT statement_line, entity, SUM(actual_usd) AS v FROM pl_monthly WHERE period = $p "
                     "GROUP BY ALL", {"p": period}).df()
    wide = df.pivot(index="statement_line", columns="entity", values="v").fillna(0.0)[["US", "UK", "DE"]]
    wide["Group"] = wide.sum(axis=1)
    return apply_layout(wide)


def trend(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    df = con.execute("SELECT statement_line, period, SUM(actual_usd) AS v FROM pl_monthly GROUP BY ALL").df()
    return apply_layout(df.pivot(index="statement_line", columns="period", values="v").fillna(0.0))


def by_department(con: duckdb.DuckDBPyConnection, period: str, year_start: str) -> pd.DataFrame:
    df = con.execute("""
        SELECT department,
               SUM(actual_usd) FILTER (WHERE period = $p) AS m_act,
               SUM(budget_usd) FILTER (WHERE period = $p) AS m_bud,
               SUM(actual_usd) AS y_act, SUM(budget_usd) AS y_bud
        FROM bva WHERE account_type = 'opex' AND period BETWEEN $start AND $p
        GROUP BY department
    """, {"p": period, "start": year_start}).df().fillna(0.0)
    names = dict(ingest.load_config("departments").values) | {"UNALLOCATED": "Unallocated"}
    df["label"] = df["department"].map(names)
    df["order"] = df["department"].map({k: i for i, k in enumerate(names)})
    df = df.sort_values("order")
    total = df[["m_act", "m_bud", "y_act", "y_bud"]].sum()
    df = pd.concat([df, pd.DataFrame([{"label": "Total Operating Expenses", **total.to_dict()}])], ignore_index=True)
    df["kind"] = ["line"] * (len(df) - 1) + ["total"]
    for scope in ("m", "y"):
        df[f"{scope}_var"] = df[f"{scope}_act"] - df[f"{scope}_bud"]
        df[f"{scope}_pct"] = df[f"{scope}_var"] / df[f"{scope}_bud"].abs().where(df[f"{scope}_bud"] != 0)
    return df


# --------------------------------------------------------------------------- excel
class Pack:
    NAVY, GREEN, RED, GREY = "#1F3864", "#E2EFDA", "#FCE4D6", "#7F7F7F"

    def __init__(self, path: Path):
        self.wb = xlsxwriter.Workbook(path, {"nan_inf_to_errors": True})
        f = self.wb.add_format
        k = '#,##0;(#,##0);"–"'
        self.f = {
            "title": f({"bold": True, "font_size": 16, "font_color": self.NAVY}),
            "subtitle": f({"italic": True, "font_color": self.GREY}),
            "head": f({"bold": True, "font_color": "white", "bg_color": self.NAVY, "align": "center",
                       "valign": "vcenter", "text_wrap": True}),
            "head_left": f({"bold": True, "font_color": "white", "bg_color": self.NAVY}),
            "label": f({}),
            "label_sub": f({"bold": True, "top": 1}),
            "label_total": f({"bold": True, "top": 1, "bottom": 6}),
            "num": f({"num_format": k}),
            "num_sub": f({"num_format": k, "bold": True, "top": 1}),
            "num_total": f({"num_format": k, "bold": True, "top": 1, "bottom": 6}),
            "pct": f({"num_format": '0.0%;(0.0%);"–"'}),
            "pct_sub": f({"num_format": '0.0%;(0.0%);"–"', "bold": True, "top": 1}),
            "pct_total": f({"num_format": '0.0%;(0.0%);"–"', "bold": True, "top": 1, "bottom": 6}),
            "good": f({"font_color": "#2E7D32"}),
            "bad": f({"font_color": "#C62828"}),
            "draft": f({"bold": True, "font_color": "white", "bg_color": "#C62828"}),
            "final": f({"bold": True, "font_color": "white", "bg_color": "#2E7D32"}),
            "kpi_label": f({"font_color": self.GREY, "font_size": 9, "top": 1, "left": 1, "right": 1}),
            "kpi_value": f({"bold": True, "font_size": 14, "num_format": '#,##0;(#,##0)', "left": 1, "right": 1}),
            "kpi_pct": f({"bold": True, "font_size": 14, "num_format": "0.0%", "left": 1, "right": 1}),
            "kpi_months": f({"bold": True, "font_size": 14, "num_format": "0.0", "left": 1, "right": 1}),
            "kpi_note": f({"font_size": 9, "font_color": self.GREY, "bottom": 1, "left": 1, "right": 1,
                           "num_format": '+#,##0;-#,##0'}),
            "wrap": f({"text_wrap": True, "valign": "top"}),
            "blocking": f({"font_color": "#C62828", "bold": True}),
            "excluded": f({"font_color": "#EF6C00", "bold": True}),
            "warning": f({"font_color": "#7F6000"}),
        }

    def header(self, ws, title: str, subtitle: str) -> None:
        ws.write(0, 0, title, self.f["title"])
        ws.write(1, 0, subtitle, self.f["subtitle"])
        ws.hide_gridlines(2)

    def layout_table(self, ws, df: pd.DataFrame, row: int, columns: list[tuple[str, str, str]]) -> int:
        """columns: (field, header, 'num'|'pct'). Values in USD are shown in thousands."""
        ws.write(row, 0, "USD thousands", self.f["head_left"])
        for c, (_, head, _) in enumerate(columns, start=1):
            ws.write(row, c, head, self.f["head"])
        for r, rec in enumerate(df.to_dict("records"), start=row + 1):
            style = {"line": "", "subtotal": "_sub", "total": "_total"}[rec["kind"]]
            ws.write(r, 0, rec["label"], self.f[f"label{style}"])
            for c, (field, _, kind) in enumerate(columns, start=1):
                value = rec.get(field)
                value = None if value is None or pd.isna(value) else (value / 1e3 if kind == "num" else value)
                if value is None:
                    ws.write_blank(r, c, None, self.f[f"{kind}{style}"])
                else:
                    ws.write_number(r, c, value, self.f[f"{kind}{style}"])
        return row + len(df) + 1

    def color_variances(self, ws, first_row: int, last_row: int, cols: list[int]) -> None:
        for c in cols:
            ws.conditional_format(first_row, c, last_row, c, {"type": "cell", "criteria": ">", "value": 0,
                                                              "format": self.f["good"]})
            ws.conditional_format(first_row, c, last_row, c, {"type": "cell", "criteria": "<", "value": 0,
                                                              "format": self.f["bad"]})


def write_pack(result: CloseResult, year_start: str = "2026-01") -> Path:
    con, period = result.con, result.period
    month = pd.Period(period, "M").strftime("%B %Y")
    out_dir = OUTPUT / period
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"Kestrel_Group_Management_Pack_{period}.xlsx"

    table = pnl(con, period, year_start)
    k = kpis(con, table, period)
    notes = variance_commentary(con, period, year_start)
    issues = result.issues
    blocking = int((issues["severity"] == "blocking").sum())
    subtitle = ("Kestrel Group (fictitious demo data) | consolidated, intercompany eliminated | "
                f"generated by findata in {result.seconds:.1f}s")

    pack = Pack(path)
    f = pack.f

    # Summary -----------------------------------------------------------------------------
    ws = pack.wb.add_worksheet("Summary")
    pack.header(ws, f"Management Pack - {month}", subtitle)
    status = (f"DRAFT - {blocking} blocking data issue(s) must be resolved before sign-off. See 'Data checks'."
              if blocking else "FINAL - all blocking data checks passed")
    ws.merge_range(3, 0, 3, 7, status, f["draft"] if blocking else f["final"])
    budget = table.set_index("label")
    tiles = [
        ("Revenue ($k)", k["Revenue"] / 1e3, "kpi_value", budget.loc["Revenue", "m_var"] / 1e3, "vs budget ($k)"),
        ("Gross margin", k["Gross margin"], "kpi_pct", None, ""),
        ("Operating expenses ($k)", k["Operating expenses"] / 1e3, "kpi_value",
         budget.loc["Total Operating Expenses", "m_var"] / 1e3, "vs budget ($k)"),
        ("Operating result ($k)", k["Operating result"] / 1e3, "kpi_value",
         budget.loc["Operating Result", "m_var"] / 1e3, "vs budget ($k)"),
        ("Cash ($k)", k["Cash"] / 1e3, "kpi_value", None, "month end"),
        ("Net burn, 3-mo avg ($k)", k["Net burn (3-mo avg)"] / 1e3, "kpi_value", None, "per month"),
        ("Runway (months)", k["Runway (months)"], "kpi_months", None, "cash / burn"),
    ]
    for c, (label, value, fmt, note, note_label) in enumerate(tiles):
        ws.write(5, c, label, f["kpi_label"])
        ws.write(6, c, value, f[fmt])
        if note is None:
            ws.write(7, c, note_label, f["kpi_note"])
        else:
            ws.write_number(7, c, note, f["kpi_note"])
    ws.set_row(6, 24)
    ws.set_column(0, 6, 21)
    ws.write(9, 0, "Variance commentary (draft)", f["title"])
    r = 10
    for scope, label in (("month", f"{month}"), ("ytd", "Year to date")):
        ws.write(r, 0, label, f["label_sub"])
        r += 1
        for text in notes.loc[notes["scope"] == scope, "commentary"]:
            ws.merge_range(r, 0, r, 6, f"- {text}", f["wrap"])
            ws.set_row(r, 32)
            r += 1
        r += 1

    # P&L ------------------------------------------------------------------------------------
    ws = pack.wb.add_worksheet("P&L")
    pack.header(ws, f"P&L vs budget - {month}", subtitle + " | profit-signed: costs in brackets, "
                "positive variance = favourable")
    cols = [("m_act", f"{period}\nActual", "num"), ("m_bud", "Budget", "num"), ("m_var", "Var", "num"),
            ("m_pct", "Var %", "pct"), ("y_act", "YTD\nActual", "num"), ("y_bud", "YTD\nBudget", "num"),
            ("y_var", "YTD Var", "num"), ("y_pct", "YTD Var %", "pct")]
    end = pack.layout_table(ws, table, 3, cols)
    pack.color_variances(ws, 4, end, [3, 4, 7, 8])
    ws.set_row(3, 30)
    ws.set_column(0, 0, 28)
    ws.set_column(1, 8, 12)
    ws.freeze_panes(4, 1)

    # By entity --------------------------------------------------------------------------------
    ws = pack.wb.add_worksheet("By entity")
    pack.header(ws, f"P&L by entity - {month} (actual)", subtitle)
    pack.layout_table(ws, by_entity(con, period), 3,
                      [("US", "Kestrel Inc.\n(US)", "num"), ("UK", "Kestrel Ltd\n(UK)", "num"),
                       ("DE", "Kestrel GmbH\n(DE)", "num"), ("Group", "Group", "num")])
    ws.set_row(3, 30)
    ws.set_column(0, 0, 28)
    ws.set_column(1, 4, 14)

    # Opex by department ------------------------------------------------------------------------
    ws = pack.wb.add_worksheet("Opex by department")
    pack.header(ws, f"Operating expenses by department - {month}", subtitle)
    end = pack.layout_table(ws, by_department(con, period, year_start), 3, cols)
    pack.color_variances(ws, 4, end, [3, 4, 7, 8])
    ws.set_row(3, 30)
    ws.set_column(0, 0, 28)
    ws.set_column(1, 8, 12)

    # Trend ------------------------------------------------------------------------------------
    ws = pack.wb.add_worksheet("Trend")
    pack.header(ws, "Monthly P&L trend (actual)", subtitle)
    tr = trend(con)
    periods = [c for c in tr.columns if c not in ("label", "kind")]
    pack.layout_table(ws, tr, 3, [(p, p, "num") for p in periods])
    ws.set_column(0, 0, 28)
    ws.set_column(1, len(periods), 9)
    ws.freeze_panes(4, 1)

    # Data checks -------------------------------------------------------------------------------
    ws = pack.wb.add_worksheet("Data checks")
    pack.header(ws, "Data checks", "Every issue points to the file and line in the source export")
    heads = ["Severity", "Check", "Entity", "Period", "Detail", "Amount (local)", "Where in the source"]
    for c, h in enumerate(heads):
        ws.write(3, c, h, f["head"])
    order = {"blocking": 0, "excluded": 1, "warning": 2}
    for r, rec in enumerate(issues.sort_values("severity", key=lambda s: s.map(order)).to_dict("records"), start=4):
        ws.write(r, 0, rec["severity"].upper(), f[rec["severity"]])
        ws.write(r, 1, rec["check"])
        ws.write(r, 2, rec["entity"])
        ws.write(r, 3, rec["period"])
        ws.write(r, 4, rec["detail"], f["wrap"])
        ws.write_number(r, 5, rec["amount"], f["num"])
        ws.write(r, 6, rec["rows"], f["wrap"])
        ws.set_row(r, 45)
    ws.set_column(0, 0, 11)
    ws.set_column(1, 1, 20)
    ws.set_column(2, 3, 8)
    ws.set_column(4, 4, 70)
    ws.set_column(5, 5, 14)
    ws.set_column(6, 6, 50)

    # About -------------------------------------------------------------------------------------
    ws = pack.wb.add_worksheet("About")
    pack.header(ws, "How this pack is built", "")
    about = [
        "Sources: QuickBooks-style journal (US, USD), Xero-style general ledger (UK, GBP), "
        "DATEV-style booking batches (DE, EUR), FY2026 budget workbook, monthly FX rates.",
        "Each export is read as-is, validated (balance, duplicates, mappings, departments, completeness), "
        "mapped to the group chart of accounts and converted to USD (P&L at monthly average rate, cash at "
        "month-end rate). Intercompany R&D recharges are eliminated.",
        "Budget is converted at budget FX rates; the FX effect line in the commentary is the difference "
        "between budget at budget rates and budget at actual rates.",
        "Commentary is generated by rules from reconciled numbers; the analyst adds business context.",
        "All companies, people and numbers are fictitious.",
    ]
    for r, text in enumerate(about, start=3):
        ws.merge_range(r, 0, r, 8, text, f["wrap"])
        ws.set_row(r, 32)

    pack.wb.close()
    issues.to_csv(out_dir / "data_checks.csv", index=False)
    notes.to_csv(out_dir / "commentary.csv", index=False)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--period", default="2026-10")
    args = parser.parse_args()
    result = run(args.period)
    path = write_pack(result)
    blocking = int((result.issues["severity"] == "blocking").sum())
    print(f"{path.relative_to(OUTPUT.parent)} | {len(result.issues)} issue(s), {blocking} blocking | "
          f"close ran in {result.seconds:.1f}s")


if __name__ == "__main__":
    main()
