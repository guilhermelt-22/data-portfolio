"""Case B: budget-vs-actual dashboard (single self-contained HTML page) + BI-ready tables.

The same tables written to output/<period>/dashboard_data/ can feed Looker Studio or Power BI;
this page is the zero-install version a CFO can open from an email or a link.

Usage:  python -m findata.dashboard --period 2026-10
"""
from __future__ import annotations

import argparse
import html
from pathlib import Path

import pandas as pd
import plotly
import plotly.graph_objects as go

from .close import CloseResult, run
from .commentary import variance_commentary
from .paths import OUTPUT
from .report import OPEX, by_department, kpis, pnl

# Reference palette (dataviz skill, light mode): series slots, diverging pair, chrome.
SURFACE, GRID, AXIS, INK, INK_2, MUTED = "#fcfcfb", "#e1e0d9", "#c3c2b7", "#0b0b0b", "#52514e", "#898781"
ACTUAL, BUDGET = "#2a78d6", "#eb6834"  # categorical slots 1 and 2
FAVOURABLE, UNFAVOURABLE, TOTAL = "#2a78d6", "#e34948", "#898781"  # diverging poles + neutral


def _layout(fig: go.Figure, title: str, height: int = 340) -> go.Figure:
    fig.update_layout(
        title={"text": title, "x": 0, "font": {"size": 15, "color": INK}},
        height=height, margin={"l": 8, "r": 8, "t": 48, "b": 8},
        paper_bgcolor=SURFACE, plot_bgcolor=SURFACE, barcornerradius=4,
        font={"family": 'system-ui, -apple-system, "Segoe UI", sans-serif', "size": 12, "color": INK_2},
        legend={"orientation": "h", "y": 1.12, "x": 1, "xanchor": "right", "title": None},
        hoverlabel={"bgcolor": "white", "font": {"color": INK}},
    )
    fig.update_xaxes(showgrid=False, linecolor=AXIS, tickcolor=AXIS, tickfont={"color": MUTED})
    fig.update_yaxes(gridcolor=GRID, zeroline=True, zerolinecolor=AXIS, tickfont={"color": MUTED})
    return fig


def revenue_chart(con, period: str) -> go.Figure:
    df = con.execute("""
        WITH a AS (SELECT period, SUM(actual_usd) AS actual FROM pl_monthly
                   WHERE account_type = 'revenue' GROUP BY period),
             b AS (SELECT period, SUM(budget_usd) AS budget FROM budget_monthly
                   WHERE account_type = 'revenue' GROUP BY period)
        SELECT COALESCE(a.period, b.period) AS period, a.actual, b.budget
        FROM a FULL OUTER JOIN b USING (period) ORDER BY period
    """).df()
    df["month"] = pd.PeriodIndex(df["period"], freq="M").strftime("%b-%y")
    fig = go.Figure()
    fig.add_bar(x=df["month"], y=df["actual"] / 1e3, name="Actual", marker={"color": ACTUAL,
                "line": {"color": SURFACE, "width": 2}},
                hovertemplate="%{x}<br>Actual: $%{y:,.0f}k<extra></extra>")
    fig.add_scatter(x=df["month"], y=df["budget"] / 1e3, name="Budget", mode="lines+markers",
                    line={"color": BUDGET, "width": 2}, marker={"size": 8, "line": {"color": SURFACE, "width": 2}},
                    hovertemplate="%{x}<br>Budget: $%{y:,.0f}k<extra></extra>")
    fig.update_yaxes(ticksuffix="k", tickprefix="$")
    return _layout(fig, "Monthly revenue vs budget (USD)")


def variance_chart(table: pd.DataFrame) -> go.Figure:
    """Diverging bars: YTD variance by P&L line (a waterfall would be dwarfed by a negative result)."""
    t = table.set_index("label")
    names = ["Revenue", "Cost of Revenue", *OPEX, "Operating Result"]
    short = {"Cost of Revenue": "Cost of revenue", "Travel & Entertainment": "Travel & entertainment",
             "Marketing Programs": "Marketing programs", "Professional Fees": "Professional fees",
             "Operating Result": "Operating result (total)"}
    values = [t.loc[n, "y_var"] / 1e3 for n in names][::-1]
    labels = [short.get(n, n) for n in names][::-1]
    colors = [TOTAL if lab.endswith("(total)") else FAVOURABLE if v > 0 else UNFAVOURABLE
              for lab, v in zip(labels, values)]
    big = max(abs(v) for v in values)
    fig = go.Figure(go.Bar(
        y=labels, x=values, orientation="h", marker={"color": colors, "line": {"color": SURFACE, "width": 2}},
        text=[f"{v:+,.0f}k" if abs(v) >= 40 else "" for v in values],
        # long bars carry their label inside; short ones outside, away from the category axis
        textposition=["inside" if abs(v) >= .35 * big else "outside" for v in values],
        insidetextanchor="middle", insidetextfont={"color": "#ffffff"}, outsidetextfont={"color": INK_2},
        cliponaxis=False, customdata=["favourable" if v > 0 else "unfavourable" for v in values],
        hovertemplate="%{y}: %{x:+,.0f}k (%{customdata})<extra></extra>"))
    lo, hi = min(min(values), 0), max(max(values), 0)
    pad = .18 * (hi - lo)
    fig.update_xaxes(ticksuffix="k", tickprefix="$", showgrid=True, gridcolor=GRID, zeroline=True,
                     zerolinecolor=INK_2, zerolinewidth=1, range=[lo - pad, hi + pad])
    fig.update_yaxes(showgrid=False)
    fig.add_annotation(text="Right / blue = favourable vs budget; left / red = unfavourable", showarrow=False,
                       x=0, y=1.07, xref="paper", yref="paper", xanchor="left", font={"size": 11, "color": MUTED})
    fig.update_layout(showlegend=False)
    return _layout(fig, "Year-to-date variance vs budget by P&L line (USD)", 380)


def department_chart(dept: pd.DataFrame) -> go.Figure:
    d = dept[dept["kind"] == "line"].iloc[::-1]
    fig = go.Figure()
    for col, name, color in (("y_bud", "Budget", BUDGET), ("y_act", "Actual", ACTUAL)):
        fig.add_bar(y=d["label"], x=-d[col] / 1e3, name=name, orientation="h",
                    marker={"color": color, "line": {"color": SURFACE, "width": 2}},
                    hovertemplate="%{y}<br>" + name + ": $%{x:,.0f}k<extra></extra>")
    fig.update_layout(barmode="group", bargap=.3)
    fig.update_xaxes(ticksuffix="k", tickprefix="$", showgrid=True, gridcolor=GRID)
    fig.update_yaxes(showgrid=False)
    return _layout(fig, "Operating expenses by department, year to date (USD)", 340)


def cash_chart(con) -> go.Figure:
    df = con.execute("SELECT period, SUM(cash_usd) AS cash FROM cash_balance GROUP BY period ORDER BY period").df()
    df["month"] = pd.PeriodIndex(df["period"], freq="M").strftime("%b-%y")
    fig = go.Figure(go.Scatter(x=df["month"], y=df["cash"] / 1e6, mode="lines+markers", name="Cash",
                               line={"color": ACTUAL, "width": 2}, marker={"size": 8},
                               hovertemplate="%{x}<br>Cash: $%{y:,.2f}M<extra></extra>"))
    fig.update_yaxes(ticksuffix="M", tickprefix="$", rangemode="tozero")
    fig.update_layout(showlegend=False, hovermode="x")
    return _layout(fig, "Group cash balance, month end (USD)")


def _money(v: float) -> str:
    return f"${v / 1e3:,.0f}k" if abs(v) < 1e6 else f"${v / 1e6:,.2f}M"


def _delta(v: float, income: bool) -> str:
    """Words carry the meaning (not colour alone): above/below for income, under/over for costs."""
    cls = "fav" if v > 0 else "unfav"
    word = ("above" if v > 0 else "below") if income else ("under" if v > 0 else "over")
    mark = "✓" if v > 0 else "✕"
    return f'<span class="{cls}">{mark} ${abs(v) / 1e3:,.0f}k {word} budget</span>'


def _pnl_html(table: pd.DataFrame) -> str:
    def cell(v, pct=False):
        if v is None or pd.isna(v):
            return "<td>–</td>"
        txt = f"{v:.1%}" if pct else (f"{v / 1e3:,.0f}" if v >= 0 else f"({abs(v) / 1e3:,.0f})")
        return f"<td>{txt}</td>"

    head = ("<tr><th>USD thousands</th><th>Actual</th><th>Budget</th><th>Var</th><th>Var %</th>"
            "<th>YTD actual</th><th>YTD budget</th><th>YTD var</th><th>YTD var %</th></tr>")
    rows = []
    for r in table.to_dict("records"):
        cells = "".join(cell(r[c], c.endswith("pct")) for c in
                        ("m_act", "m_bud", "m_var", "m_pct", "y_act", "y_bud", "y_var", "y_pct"))
        rows.append(f'<tr class="{r["kind"]}"><td>{html.escape(r["label"])}</td>{cells}</tr>')
    return f'<table class="pnl"><thead>{head}</thead><tbody>{"".join(rows)}</tbody></table>'


def write_dashboard(result: CloseResult, year_start: str = "2026-01") -> Path:
    con, period = result.con, result.period
    month = pd.Period(period, "M").strftime("%B %Y")
    out_dir = OUTPUT / period
    data_dir = out_dir / "dashboard_data"
    data_dir.mkdir(parents=True, exist_ok=True)

    table = pnl(con, period, year_start)
    k = kpis(con, table, period)
    dept = by_department(con, period, year_start)
    notes = variance_commentary(con, period, year_start)
    t = table.set_index("label")
    issues = result.issues
    blocking = int((issues["severity"] == "blocking").sum())

    # BI-ready tables (Looker Studio / Power BI)
    con.execute("SELECT * FROM bva ORDER BY period, entity, account, department").df().to_csv(
        data_dir / "budget_vs_actual.csv", index=False)
    con.execute("SELECT * FROM pl_monthly ORDER BY period, entity, account, department").df().to_csv(
        data_dir / "pl_monthly_actuals.csv", index=False)
    con.execute("SELECT * FROM cash_balance ORDER BY period, entity").df().to_csv(
        data_dir / "cash_balance.csv", index=False)

    charts = [revenue_chart(con, period), variance_chart(table), department_chart(dept), cash_chart(con)]
    chart_html = [c.to_html(full_html=False, include_plotlyjs=False, default_width="100%",
                            config={"displayModeBar": False, "responsive": True}) for c in charts]
    tiles = [
        ("Revenue", _money(k["Revenue"]), _delta(t.loc["Revenue", "m_var"], income=True)),
        ("Gross margin", f"{k['Gross margin']:.1%}", "cost of revenue incl. support payroll"),
        ("Operating expenses", _money(-k["Operating expenses"]),
         _delta(t.loc["Total Operating Expenses", "m_var"], income=False)),
        ("Operating result", _money(k["Operating result"]).replace("$-", "-$"),
         _delta(t.loc["Operating Result", "m_var"], income=True)),
        ("Cash", _money(k["Cash"]), f"net burn {_money(k['Net burn (3-mo avg)'])}/mo (3-mo avg)"),
        ("Runway", f"{k['Runway (months)']:.1f} months", "cash / average burn"),
    ]
    tiles_html = "".join(f'<div class="tile"><div class="t-label">{a}</div><div class="t-value">{b}</div>'
                         f'<div class="t-note">{c}</div></div>' for a, b, c in tiles)
    status = (f'<div class="status draft">⚠ DRAFT: {blocking} blocking data issue(s) before sign-off. '
              f'See data checks below.</div>' if blocking else
              '<div class="status final">✔ FINAL: all blocking data checks passed</div>')
    month_notes = "".join(f"<li>{html.escape(x)}</li>" for x in notes.loc[notes["scope"] == "month", "commentary"])
    ytd_notes = "".join(f"<li>{html.escape(x)}</li>" for x in notes.loc[notes["scope"] == "ytd", "commentary"])
    checks = "".join(
        f'<tr><td class="sev {r["severity"]}">{r["severity"]}</td><td>{html.escape(r["entity"])}</td>'
        f'<td>{html.escape(str(r["period"]))}</td><td>{html.escape(r["detail"])}</td></tr>'
        for r in issues.to_dict("records"))

    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kestrel Group - Budget vs Actual - {month}</title>
<script src="https://cdn.plot.ly/plotly-{plotly.offline.get_plotlyjs_version()}.min.js"></script>
<style>
  :root {{ color-scheme: light; --page:#f9f9f7; --surface:{SURFACE}; --ink:{INK}; --ink2:{INK_2};
          --muted:{MUTED}; --line:rgba(11,11,11,.10); --fav:#006300; --unfav:#c62828; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:var(--page); color:var(--ink);
         font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif; }}
  main {{ max-width:1200px; margin:0 auto; padding:24px 16px 48px; }}
  h1 {{ font-size:22px; margin:0 0 4px; }}
  .sub {{ color:var(--ink2); margin:0 0 16px; }}
  .status {{ padding:10px 14px; border-radius:8px; font-weight:600; margin-bottom:16px; }}
  .status.draft {{ background:#fdecea; color:#8e1b1b; }}
  .status.final {{ background:#e6f4e6; color:#1b5e20; }}
  .tiles {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:12px; margin-bottom:16px; }}
  .tile, .card {{ background:var(--surface); border:1px solid var(--line); border-radius:10px; }}
  .tile {{ padding:12px 14px; }}
  .t-label {{ color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.04em; }}
  .t-value {{ font-size:24px; font-weight:650; margin:2px 0; }}
  .t-note {{ color:var(--ink2); font-size:12px; }}
  .fav {{ color:var(--fav); }} .unfav {{ color:var(--unfav); }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,520px),1fr)); gap:12px; }}
  .grid > * {{ min-width:0; }}
  .card {{ padding:8px 12px 12px; margin-bottom:12px; overflow-x:auto; }}
  .grid .card {{ overflow:hidden; }}
  h2 {{ font-size:16px; margin:20px 0 8px; }}
  ul.notes li {{ margin-bottom:6px; color:var(--ink2); }}
  table {{ border-collapse:collapse; width:100%; font-variant-numeric:tabular-nums; }}
  th, td {{ padding:6px 8px; border-bottom:1px solid #eeede8; text-align:right; white-space:nowrap; }}
  th:first-child, td:first-child {{ text-align:left; }}
  th {{ color:var(--ink2); font-weight:600; background:#f3f2ee; }}
  tr.subtotal td {{ font-weight:600; border-top:1px solid #c3c2b7; }}
  tr.total td {{ font-weight:700; border-top:1px solid #c3c2b7; border-bottom:3px double #c3c2b7; }}
  table.checks td {{ text-align:left; white-space:normal; }}
  .sev {{ font-weight:700; text-transform:uppercase; font-size:12px; }}
  .sev.blocking {{ color:#c62828; }} .sev.excluded {{ color:#b35c00; }} .sev.warning {{ color:#7f6000; }}
  footer {{ color:var(--muted); font-size:12px; margin-top:24px; }}
</style>
</head>
<body>
<main>
  <h1>Budget vs Actual - {month}</h1>
  <p class="sub">Kestrel Group (fictitious demo company) | consolidated in USD, intercompany eliminated |
     3 entities, 3 accounting systems</p>
  {status}
  <section class="tiles">{tiles_html}</section>
  <section class="grid">
    <div class="card">{chart_html[0]}</div>
    <div class="card">{chart_html[1]}</div>
    <div class="card">{chart_html[2]}</div>
    <div class="card">{chart_html[3]}</div>
  </section>
  <h2>Variance commentary (draft, generated from reconciled numbers)</h2>
  <div class="card"><strong>{month}</strong><ul class="notes">{month_notes}</ul>
    <strong>Year to date</strong><ul class="notes">{ytd_notes}</ul></div>
  <h2>P&amp;L vs budget (profit-signed: costs in brackets, positive variance = favourable)</h2>
  <div class="card">{_pnl_html(table)}</div>
  <h2>Data checks</h2>
  <div class="card"><table class="checks"><thead><tr><th>Severity</th><th>Entity</th><th>Period</th>
    <th>Detail</th></tr></thead><tbody>{checks}</tbody></table></div>
  <footer>Built with Python, DuckDB and Plotly. All companies, people and numbers are fictitious.</footer>
</main>
<script>
  // Charts are drawn while the page is still parsing; size them to their final grid cells.
  window.addEventListener("load", () =>
    document.querySelectorAll(".js-plotly-plot").forEach((p) => Plotly.Plots.resize(p)));
</script>
</body>
</html>"""
    path = out_dir / "dashboard.html"
    path.write_text(page, encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--period", default="2026-10")
    args = parser.parse_args()
    path = write_dashboard(run(args.period))
    print(path.relative_to(OUTPUT.parent))


if __name__ == "__main__":
    main()
