"""Deliverables: CSV (long and wide), an Excel workbook with the checks and a native chart, and an HTML page."""
from __future__ import annotations

import html
import sqlite3
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import xlsxwriter

from .api import SOURCE_NOTE
from .checks import run_checks
from .store import load

INK, GREY = "#1F3864", "#7F7F7F"
BADGE = {"PASS": "#2E7D32", "WARN": "#B7791F", "FAIL": "#C62828", "INFO": "#7F7F7F",
         "PASS WITH WARNINGS": "#B7791F"}
CHART = [("USD", "US dollar", "#2a78d6"), ("GBP", "Pound sterling", "#d1495b"), ("CHF", "Swiss franc", "#2e7d32")]


def runs_table(con: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql("SELECT * FROM runs ORDER BY run_id", con)


def write_excel(path: Path, rates: pd.DataFrame, result: dict, runs: pd.DataFrame, retrieved: str) -> None:
    cov = result["coverage"]
    order = list(cov["currency"])
    wide = rates.pivot(index="date", columns="currency", values="rate")[order].sort_index()
    wb = xlsxwriter.Workbook(path, {"nan_inf_to_errors": True})
    f = {
        "title": wb.add_format({"bold": True, "font_size": 16, "font_color": INK}),
        "sub": wb.add_format({"italic": True, "font_color": GREY}),
        "section": wb.add_format({"bold": True, "font_size": 12, "font_color": INK}),
        "head": wb.add_format({"bold": True, "font_color": "white", "bg_color": INK}),
        "head_r": wb.add_format({"bold": True, "font_color": "white", "bg_color": INK, "align": "right"}),
        "text": wb.add_format({"valign": "top"}), "wrap": wb.add_format({"text_wrap": True, "valign": "top"}),
        "int": wb.add_format({"num_format": "#,##0", "valign": "top"}),
        "date": wb.add_format({"num_format": "yyyy-mm-dd"}), "rate": wb.add_format({"num_format": "0.0000##"}),
        "note": wb.add_format({"italic": True, "font_color": GREY, "font_size": 9}),
    }
    for name, color in BADGE.items():
        f[name] = wb.add_format({"bold": True, "font_color": color, "valign": "top"})

    ws = wb.add_worksheet("Summary")
    ws.hide_gridlines(2)
    ws.set_column(0, 0, 40)
    ws.set_column(1, 1, 12)
    ws.set_column(2, 2, 90)
    ws.write(0, 0, "ECB euro reference rates · daily since 1999", f["title"])
    ws.write(1, 0, f"{SOURCE_NOTE} · retrieved {retrieved} · rates as published (units per 1 EUR)", f["sub"])
    ws.write(3, 0, "Checks", f["section"])
    ws.write(3, 1, result["overall"], f[result["overall"]])
    ws.write_row(4, 0, ["Check", "Result", "Detail"], f["head"])
    row = 5
    for name, res, detail in result["checks"]:
        ws.write(row, 0, name, f["text"])
        ws.write(row, 1, res, f[res])
        ws.write(row, 2, detail, f["wrap"])
        row += 1
    row += 1
    ws.write(row, 0, "Update log", f["section"])
    row += 1
    cols = [("run_id", "Run"), ("mode", "Mode"), ("start_period", "Asked from"), ("rows_received", "Rows received"),
            ("rows_new", "New rates"), ("days_new", "New days"), ("rows_revised", "Revised"), ("seconds", "Seconds")]
    ws.write_row(row, 0, [c[1] for c in cols], f["head"])
    for r, rec in enumerate(runs.to_dict("records"), start=row + 1):
        for c, (k, _) in enumerate(cols):
            v = rec[k]
            ws.write(r, c, "" if v is None or (isinstance(v, float) and pd.isna(v)) else v,
                     f["int"] if isinstance(v, (int, float)) and k != "seconds" else f["text"])
    row += len(runs) + 2
    ws.write(row, 0, "Coverage by currency", f["section"])
    row += 1
    cov_cols = [("currency", "Currency"), ("status", "Status"), ("first", "First rate"), ("last", "Last rate"),
                ("values", "Rates"), ("expected", "Business days"), ("gap_days", "Missing days"),
                ("largest_gap", "Largest gap")]
    ws.write_row(row, 0, [c[1] for c in cov_cols], f["head"])
    for r, rec in enumerate(cov.to_dict("records"), start=row + 1):
        for c, (k, _) in enumerate(cov_cols):
            v = rec[k]
            ws.write(r, c, str(v) if k in ("first", "last") else v, f["int"] if isinstance(v, int) else f["text"])
    ws.set_column(3, 7, 13)
    ws.write(row + len(cov) + 2, 0, "Holidays follow the TARGET calendar: no rate on those days is expected, "
                                    "not a gap. ECB statistics may be reused free of charge if the source is quoted "
                                    "and the statistics are not modified.", f["note"])

    ws = wb.add_worksheet("Rates")
    ws.freeze_panes(1, 1)
    ws.write(0, 0, "Date", f["head"])
    ws.set_column(0, 0, 11)
    ws.set_column(1, len(order), 10)
    for c, cur in enumerate(order, start=1):
        ws.write(0, c, cur, f["head_r"])
    for r, (day, values) in enumerate(wide.iterrows(), start=1):
        ws.write_datetime(r, 0, day.to_pydatetime(), f["date"])
        for c, v in enumerate(values, start=1):
            if pd.notna(v):
                ws.write_number(r, c, v, f["rate"])
    n = len(wide)

    chart = wb.add_chart({"type": "line"})
    for code, name, color in CHART:
        col = order.index(code) + 1
        chart.add_series({"name": f"{name} per euro", "categories": ["Rates", 1, 0, n, 0],
                          "values": ["Rates", 1, col, n, col], "line": {"color": color, "width": 1.25}})
    chart.set_title({"name": "Euro reference rates since 1999 (units per 1 EUR)"})
    chart.set_x_axis({"date_axis": True, "num_format": "yyyy", "major_unit": 2, "major_unit_type": "years"})
    chart.set_y_axis({"num_format": "0.00", "major_gridlines": {"visible": True, "line": {"color": "#E0E0E0"}}})
    chart.set_legend({"position": "bottom"})
    chart.set_size({"width": 960, "height": 480})
    cs = wb.add_worksheet("Chart")
    cs.hide_gridlines(2)
    cs.insert_chart(1, 1, chart)
    cs.write(26, 1, SOURCE_NOTE, f["note"])
    wb.close()


def write_html(path: Path, rates: pd.DataFrame, result: dict, runs: pd.DataFrame, retrieved: str) -> None:
    fig = go.Figure()
    for code, name, color in CHART:
        s = rates[rates["currency"] == code]
        fig.add_trace(go.Scatter(x=s["date"], y=s["rate"], name=f"{name} ({code})", mode="lines",
                                 line={"color": color, "width": 1.4},
                                 hovertemplate="%{x|%Y-%m-%d}: %{y:.4f} " + code + "<extra></extra>"))
    fig.update_layout(height=380, margin={"l": 50, "r": 20, "t": 10, "b": 30}, template="plotly_white",
                      legend={"orientation": "h", "y": 1.08, "x": 0}, yaxis_title="units per 1 EUR",
                      font={"family": "Segoe UI, system-ui, sans-serif", "size": 13})
    chart = fig.to_html(include_plotlyjs="cdn", full_html=False, config={"displayModeBar": False})
    cov = result["coverage"]
    last = runs.iloc[-1]
    first = runs.iloc[0]
    kpis = [
        (f"{(cov['status'] == 'published').sum()}", f"currencies published today ({len(cov)} series since 1999)"),
        (f"{rates['date'].nunique():,}", f"business days, {rates['date'].min():%d %b %Y} to {rates['date'].max():%d %b %Y}"),
        (f"{len(rates):,}", f"rates stored · full history in {first['seconds']:.1f} s"),
        (f"{int(last['days_new'])} days", f"last update: {int(last['rows_new']):,} new rates in {last['seconds']:.1f} s"),
    ]
    rows = "".join(f'<tr><td>{html.escape(n)}</td><td><b style="color:{BADGE[r]}">{r}</b></td>'
                   f'<td>{html.escape(d)}</td></tr>' for n, r, d in result["checks"])
    kpi_html = "".join(f'<div class="kpi"><b>{v}</b><span>{html.escape(t)}</span></div>' for v, t in kpis)
    path.write_text(f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>ECB euro reference rates</title>
<style>
body{{margin:0;background:#f4f5f7;font:15px/1.5 "Segoe UI",system-ui,sans-serif;color:#141414}}
.page{{max-width:1060px;margin:0 auto;padding:24px 20px;background:#fff}}
h1{{margin:0;font-size:24px;color:{INK}}} .sub{{color:{GREY};margin:4px 0 18px;font-size:13px}}
.kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:18px}}
.kpi{{border:1px solid #e3e3e3;border-radius:8px;padding:10px 12px}} .kpi b{{display:block;font-size:22px;color:{INK}}}
.kpi span{{font-size:12.5px;color:#555}}
h2{{font-size:15px;color:{INK};margin:18px 0 6px}}
table{{border-collapse:collapse;width:100%;font-size:13.5px}} th,td{{text-align:left;padding:6px 8px;border-bottom:1px solid #e6e6e6;vertical-align:top}}
th{{background:{INK};color:#fff;font-weight:600}} td:first-child{{white-space:nowrap}}
.note{{color:{GREY};font-size:12px;margin-top:12px}}
</style></head><body><div class="page">
<h1>ECB euro reference rates, daily since 1999</h1>
<p class="sub">{html.escape(SOURCE_NOTE)} · retrieved {retrieved} · rates as published, units of currency per 1 euro</p>
<div class="kpis">{kpi_html}</div>
{chart}
<h2>Checks on every update · {result['overall']}</h2>
<table><tr><th>Check</th><th>Result</th><th>Detail</th></tr>{rows}</table>
<p class="note">Weekends and TARGET closing days (New Year, Good Friday, Easter Monday, 1 May, 25 and 26 December)
have no reference rate by design; they are not counted as gaps.</p>
</div></body></html>""", encoding="utf-8")


def write_report(con: sqlite3.Connection, out_dir: Path, today: pd.Timestamp | None = None) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    rates, empty = load(con)
    runs = runs_table(con)
    result = run_checks(rates, empty, int(runs["duplicates_received"].fillna(0).sum()) if len(runs) else 0, today)
    retrieved = f"{pd.Timestamp(runs['at'].iloc[-1]):%Y-%m-%d %H:%M} UTC" if len(runs) else ""
    rates.assign(date=rates["date"].dt.strftime("%Y-%m-%d")).to_csv(out_dir / "ecb_rates_long.csv", index=False)
    order = list(result["coverage"]["currency"])
    wide = rates.pivot(index="date", columns="currency", values="rate")[order].sort_index()
    wide.index = wide.index.strftime("%Y-%m-%d")
    wide.to_csv(out_dir / "ecb_rates_wide.csv")
    wide.tail(30).to_csv(out_dir / "sample_last_30_days.csv")
    write_excel(out_dir / "ecb_fx_rates.xlsx", rates, result, runs, retrieved)
    write_html(out_dir / "fx_report.html", rates, result, runs, retrieved)
    return result
