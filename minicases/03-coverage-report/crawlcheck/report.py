"""Coverage report: one row per discovered URL, and a summary that reconciles to zero.

discovered = collected + failed + excluded, with nothing left pending. If that does not hold, the
summary says so in red instead of quietly delivering a short file.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd
import xlsxwriter

from . import state
from .config import OUT

INK, GREY = "#1F3864", "#7F7F7F"
STATUS_COLOR = {"collected": "#2E7D32", "failed": "#C62828", "excluded": "#7F7F7F", "pending": "#9C6500"}
RUN_LABEL = {"completed": "completed", "interrupted": "interrupted (process killed)", "running": "running"}


def tables(con: sqlite3.Connection) -> dict[str, pd.DataFrame]:
    coverage = pd.read_sql("""SELECT url, kind AS page_type, status, reason, http_status, attempts, found_on,
                              links_in, found_run, done_run FROM urls ORDER BY seq""", con)
    books = pd.read_sql("""SELECT upc, title, category, price_cents / 100.0 AS price_gbp, stock, rating, reviews,
                           url, run_id FROM books ORDER BY rowid""", con)
    runs = pd.read_sql("SELECT * FROM runs ORDER BY run_id", con)
    if len(runs):
        start = pd.to_datetime(runs["started_at"])
        runs["seconds"] = (pd.to_datetime(runs["last_seen_at"]) - start).dt.total_seconds().round().astype(int)
    by_reason = (coverage.assign(reason=coverage["reason"].fillna("not processed yet"))
                 .groupby(["status", "page_type", "reason"], as_index=False).size().rename(columns={"size": "urls"}))
    order = {"collected": 0, "failed": 1, "excluded": 2, "pending": 3}
    by_reason = by_reason.sort_values(["status", "urls"], key=lambda s: s.map(order) if s.name == "status" else -s)
    return {"coverage": coverage, "books": books, "runs": runs, "by_reason": by_reason,
            "failures": coverage[coverage["status"] == "failed"]}


def summary(con: sqlite3.Connection, t: dict[str, pd.DataFrame]) -> dict:
    cov = t["coverage"]
    count = cov["status"].value_counts().to_dict()
    books = t["books"]
    listing = cov[cov["page_type"] == "listing"]
    robots = {k[len("robots "):]: v for k, v in con.execute("SELECT key, value FROM meta WHERE key LIKE 'robots %'")}
    s = {
        "discovered": len(cov),
        "collected": count.get("collected", 0), "failed": count.get("failed", 0),
        "excluded": count.get("excluded", 0), "pending": count.get("pending", 0),
        "links_found": int(state.get_meta(con, "links_found", 0) or 0),
        "books_announced": int(state.get_meta(con, "books_announced") or 0),
        "book_urls": int((cov["page_type"] == "book").sum()),
        "records": len(books),
        "duplicate_upcs": int(books["upc"].duplicated().sum()),
        "listing_loaded": int((listing["status"] == "collected").sum()), "listing_total": len(listing),
        "robots": "; ".join(robots.values()) if len(robots) == 1 else
                  "; ".join(f"{o}: {n}" for o, n in robots.items()) or "not checked",
        "requested_twice": con.execute("""SELECT COUNT(*) FROM (SELECT url FROM fetches GROUP BY url
                                          HAVING COUNT(DISTINCT run_id) > 1)""").fetchone()[0],
    }
    s["accounted"] = s["collected"] + s["failed"] + s["excluded"]
    s["reconciles"] = s["pending"] == 0 and s["accounted"] == s["discovered"]
    return s


class _Book:
    def __init__(self, path: Path):
        self.wb = xlsxwriter.Workbook(path, {"strings_to_urls": False})
        f = self.wb.add_format
        self.f = {
            "title": f({"bold": True, "font_size": 16, "font_color": INK}),
            "subtitle": f({"italic": True, "font_color": GREY}),
            "section": f({"bold": True, "font_color": INK, "font_size": 12}),
            "head": f({"bold": True, "font_color": "white", "bg_color": INK, "valign": "vcenter"}),
            "head_num": f({"bold": True, "font_color": "white", "bg_color": INK, "align": "right"}),
            "text": f({}), "int": f({"num_format": "#,##0"}), "money": f({"num_format": "#,##0.00"}),
            "total": f({"bold": True, "top": 1}), "total_int": f({"bold": True, "top": 1, "num_format": "#,##0"}),
            "kpi_label": f({"bottom": 1, "bottom_color": "#D9D9D9"}),
            "kpi_value": f({"bold": True, "align": "left", "bottom": 1, "bottom_color": "#D9D9D9",
                            "num_format": "#,##0"}),
            "note": f({"italic": True, "font_color": GREY, "font_size": 9}),
            "equation": f({"bold": True, "font_size": 12}),
            "ok": f({"bold": True, "font_color": "white", "bg_color": "#2E7D32", "align": "center"}),
            "bad": f({"bold": True, "font_color": "white", "bg_color": "#C62828", "align": "center"}),
        }
        for name, color in STATUS_COLOR.items():
            self.f[f"st_{name}"] = f({"bold": True, "font_color": color})

    def sheet(self, name: str, title: str, subtitle: str):
        ws = self.wb.add_worksheet(name)
        ws.hide_gridlines(2)
        ws.write(0, 0, title, self.f["title"])
        ws.write(1, 0, subtitle, self.f["subtitle"])
        return ws

    def table(self, ws, row: int, df: pd.DataFrame, columns, filters: bool = False, set_widths: bool = True) -> int:
        """columns: (field, header, format, width). Returns the first free row after the table."""
        for c, (_, head, fmt, width) in enumerate(columns):
            ws.write(row, c, head, self.f["head_num" if fmt in ("int", "money") else "head"])
            if set_widths:
                ws.set_column(c, c, width)
        for r, rec in enumerate(df.to_dict("records"), start=row + 1):
            for c, (field, _, fmt, _) in enumerate(columns):
                v = rec.get(field)
                if v is None or (isinstance(v, float) and pd.isna(v)):
                    ws.write_blank(r, c, None)
                elif fmt == "status":
                    ws.write(r, c, v, self.f[f"st_{v}"])
                elif fmt in ("int", "money"):
                    ws.write_number(r, c, float(v), self.f[fmt])
                else:
                    ws.write(r, c, str(v), self.f[fmt])
        if filters and len(df):
            ws.autofilter(row, 0, row + len(df), len(columns) - 1)
            ws.freeze_panes(row + 1, 0)
        return row + len(df) + 1


def write_report(con: sqlite3.Connection, out_dir: Path = OUT, source: str = "books.toscrape.com") -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    t = tables(con)
    s = summary(con, t)
    t["coverage"].to_csv(out_dir / "coverage.csv", index=False)
    t["books"].drop(columns="run_id").to_csv(out_dir / "books.csv", index=False)

    xb = _Book(out_dir / "coverage_report.xlsx")
    f = xb.f
    runs = t["runs"]
    when = datetime.fromisoformat(runs["last_seen_at"].iloc[-1]).strftime("%Y-%m-%d %H:%M UTC") if len(runs) else ""
    ws = xb.sheet("Summary", "Crawl coverage report · Books to Scrape",
                  f"{when} · {source} (scraping practice site) · {len(runs)} run{'s' if len(runs) != 1 else ''}, resumed from the checkpoint")
    for col, width in enumerate([43, 22, 40, 12, 12, 14, 4]):
        ws.set_column(col, col, width)
    ws.write(3, 0, "Every URL accounted for?", f["section"])
    if s["reconciles"]:
        ws.merge_range(3, 1, 3, 2, "YES: NOTHING LEFT UNEXPLAINED", f["ok"])
    else:
        gap = s["discovered"] - s["accounted"] + s["pending"]
        ws.merge_range(3, 1, 3, 2, f"NO: {gap:,} URLS WITHOUT AN OUTCOME", f["bad"])
    ws.write(4, 0, f"{s['discovered']:,} discovered = {s['collected']:,} collected + {s['failed']:,} failed "
                   f"+ {s['excluded']:,} excluded" + (f" + {s['pending']:,} pending" if s["pending"] else ""),
             f["equation"])

    row = 6
    ws.write(row, 0, "Outcome by reason", f["section"])
    by = t["by_reason"]
    end = xb.table(ws, row + 1, by, [("status", "Outcome", "status", 0), ("page_type", "Page type", "text", 0),
                                     ("reason", "Reason", "text", 0), ("urls", "URLs", "int", 0)],
                   set_widths=False)
    ws.write(end, 0, "Total discovered", f["total"])
    ws.write_blank(end, 1, None, f["total"])
    ws.write_blank(end, 2, None, f["total"])
    ws.write_number(end, 3, s["discovered"], f["total_int"])

    row = end + 2
    ws.write(row, 0, "Control totals", f["section"])
    announced = s["books_announced"]
    controls = [
        ("Books the site says it has", f"{announced:,}" if announced else "not shown"),
        ("Book URLs discovered", f"{s['book_urls']:,}" + (f" ({s['book_urls'] - announced:+,} vs the site)"
                                                          if announced and s["book_urls"] != announced else "")),
        ("Records saved", f"{s['records']:,}"),
        ("Duplicate records (same UPC)", f"{s['duplicate_upcs']:,}"),
        ("Listing pages loaded", f"{s['listing_loaded']} of {s['listing_total']}"),
        ("Links read on listing pages", f"{s['links_found']:,} ({s['discovered']:,} unique URLs)"),
        ("Saved pages requested again on resume", f"{s['requested_twice']:,}"),
        ("robots.txt", s["robots"]),
    ]
    for i, (label, value) in enumerate(controls, start=row + 1):
        ws.write(i, 0, label, f["kpi_label"])
        ws.merge_range(i, 1, i, 2, value, f["kpi_value"])

    row = row + len(controls) + 2
    ws.write(row, 0, "Runs", f["section"])
    heads = ["Run", "Started (UTC)", "Status", "Seconds", "Requests", "Records added"]
    for c, head in enumerate(heads):
        ws.write(row + 1, c, head, f["head_num" if c >= 3 else "head"])
    for r, rec in enumerate(runs.to_dict("records"), start=row + 2):
        ws.write(r, 0, f"Run {rec['run_id']}", f["text"])
        ws.write(r, 1, rec["started_at"][11:19], f["text"])
        ws.write(r, 2, RUN_LABEL.get(rec["status"], rec["status"]), f["text"])
        for c, k in ((3, "seconds"), (4, "requests"), (5, "records_added")):
            ws.write_number(r, c, rec[k], f["int"])
    end = row + 2 + len(runs)
    if len(runs) > 1:
        ws.write(end, 0, "Total", f["total"])
        ws.write_blank(end, 1, None, f["total"])
        ws.write_blank(end, 2, None, f["total"])
        for c, k in ((3, "seconds"), (4, "requests"), (5, "records_added")):
            ws.write_number(end, c, int(runs[k].sum()), f["total_int"])
        end += 1

    row = end + 1
    ws.write(row, 0, "Failures", f["section"])
    fail = t["failures"]
    if len(fail):
        site = "https://books.toscrape.com"
        ws.write(row + 1, 0, "URL", f["head"])
        ws.merge_range(row + 1, 1, row + 1, 2, "Reason", f["head"])
        ws.merge_range(row + 1, 3, row + 1, 6, "Found on", f["head"])
        for r, rec in enumerate(fail.to_dict("records"), start=row + 2):
            ws.write(r, 0, rec["url"].replace(site, ""), f["text"])
            ws.merge_range(r, 1, r, 2, rec["reason"], f["st_failed"])
            ws.merge_range(r, 3, r, 6, (rec["found_on"] or "").replace(site, ""), f["text"])
        end = row + 2 + len(fail)
    else:
        ws.write(row + 1, 0, "None.", f["text"])
        end = row + 2
    ws.write(end + 1, 0, "Failed URLs stay in the checkpoint: --retry-failed requests them again on the next run.",
             f["note"])
    ws.write(end + 2, 0, "Scraping practice site with fictitious books. Paths are relative to "
                         "https://books.toscrape.com.", f["note"])

    ws = xb.sheet("Coverage", "One row per discovered URL", "Outcome, reason, attempts and the page that linked to it")
    xb.table(ws, 3, t["coverage"], [("url", "URL", "text", 70), ("page_type", "Page type", "text", 11),
                                    ("status", "Outcome", "status", 11), ("reason", "Reason", "text", 34),
                                    ("http_status", "HTTP", "int", 7), ("attempts", "Attempts", "int", 9),
                                    ("links_in", "Links in", "int", 9), ("found_on", "Found on", "text", 52)],
             filters=True)
    ws = xb.sheet("Records", "Books collected", "One row per book; UPC is unique")
    xb.table(ws, 3, t["books"], [("upc", "UPC", "text", 18), ("title", "Title", "text", 50),
                                 ("category", "Category", "text", 18), ("price_gbp", "Price (GBP)", "money", 12),
                                 ("stock", "Stock", "int", 8), ("rating", "Rating", "int", 8),
                                 ("reviews", "Reviews", "int", 9), ("url", "URL", "text", 70)], filters=True)
    xb.wb.close()
    return s
