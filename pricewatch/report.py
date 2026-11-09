"""Outputs of a run: an Excel report for people, CSV files for other tools."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import xlsxwriter

from .config import OUT, STORES

LABEL = {"price_down": "Price down", "price_up": "Price up", "out_of_stock": "Out of stock",
         "back_in_stock": "Back in stock", "new": "New product", "returned": "Listed again",
         "removed": "Removed", "not_seen": "Not seen (held)"}
ORDER = list(LABEL)


# --------------------------------------------------------------------------- data
def run_info(con: sqlite3.Connection, run_id: int) -> dict:
    return dict(con.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone())


def changes_table(con: sqlite3.Connection, run_id: int) -> pd.DataFrame:
    df = pd.read_sql_query("""
        SELECT c.store, i.category, i.title AS product, c.change, c.old_value, c.new_value, c.pct, i.url
        FROM changes c JOIN items i USING (store, item_id)
        WHERE c.run_id = ?
    """, con, params=(run_id,))
    df["currency"] = df["store"].map(lambda s: STORES[s].currency if s in STORES else "")
    df["order"] = df["change"].map(ORDER.index)
    df["abs_pct"] = df["pct"].abs()
    return df.sort_values(["order", "abs_pct", "store", "product"], ascending=[True, False, True, True]
                          ).drop(columns=["order", "abs_pct"]).reset_index(drop=True)


def catalog_table(con: sqlite3.Connection, run_id: int) -> pd.DataFrame:
    df = pd.read_sql_query("""
        WITH last_obs AS (
            SELECT o.*, ROW_NUMBER() OVER (PARTITION BY store, item_id ORDER BY run_id DESC) AS rn
            FROM observations o WHERE run_id <= :r
        ),
        lifecycle AS (
            SELECT store, item_id, change,
                   ROW_NUMBER() OVER (PARTITION BY store, item_id ORDER BY run_id DESC) AS rn
            FROM changes WHERE run_id <= :r AND change IN ('new', 'returned', 'removed', 'not_seen')
        )
        SELECT i.store, i.category, i.title AS product, l.price_cents / 100.0 AS price, l.in_stock,
               l.rating, l.reviews,
               CASE WHEN l.run_id = :r THEN 'listed'
                    WHEN lc.change = 'removed' THEN 'removed' ELSE 'not seen' END AS status,
               i.first_seen_run, l.run_id AS last_seen_run, i.url
        FROM items i
        JOIN last_obs l ON l.store = i.store AND l.item_id = i.item_id AND l.rn = 1
        LEFT JOIN lifecycle lc ON lc.store = i.store AND lc.item_id = i.item_id AND lc.rn = 1
        WHERE i.first_seen_run <= :r
        ORDER BY i.store, i.category, i.title
    """, con, params={"r": run_id})
    df["currency"] = df["store"].map(lambda s: STORES[s].currency if s in STORES else "")
    df["in_stock"] = df["in_stock"].map({1: "yes", 0: "no"}).fillna("n/a")
    return df


def quality_table(con: sqlite3.Connection, run_id: int) -> pd.DataFrame:
    return pd.read_sql_query("SELECT store, check_name, severity, count, detail FROM quality WHERE run_id = ?"
                             " ORDER BY store, rowid", con, params=(run_id,))


def runs_table(con: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query("""
        SELECT r.run_id, r.started_at, r.mode, r.source_run,
               (SELECT SUM(ok) FROM pages p WHERE p.run_id = r.run_id) AS pages_ok,
               (SELECT COUNT(*) FROM pages p WHERE p.run_id = r.run_id) AS pages,
               (SELECT COUNT(*) FROM observations o WHERE o.run_id = r.run_id) AS products,
               (SELECT COUNT(*) FROM changes c WHERE c.run_id = r.run_id) AS changes,
               (SELECT CASE MAX(CASE severity WHEN 'error' THEN 2 WHEN 'warning' THEN 1 ELSE 0 END)
                       WHEN 2 THEN 'FAIL' WHEN 1 THEN 'PASS WITH WARNINGS' ELSE 'PASS' END
                FROM quality q WHERE q.run_id = r.run_id) AS quality
        FROM runs r ORDER BY r.run_id
    """, con)


def store_summary(con: sqlite3.Connection, run_id: int, changes: pd.DataFrame, quality: pd.DataFrame
                  ) -> pd.DataFrame:
    rows = []
    pages = con.execute("SELECT store, SUM(ok), COUNT(*) FROM pages WHERE run_id = ? GROUP BY store ORDER BY store",
                        (run_id,)).fetchall()
    for store, ok, total in pages:
        counts = changes[changes["store"] == store]["change"].value_counts()
        sev = quality[quality["store"] == store]["severity"]
        rows.append({
            "store": STORES[store].name if store in STORES else store,
            "method": {"static": "requests + BeautifulSoup", "dynamic": "Selenium (AJAX pages)"}.get(
                STORES[store].method if store in STORES else "", ""),
            "pages": f"{ok} of {total}",
            "products": con.execute("SELECT COUNT(*) FROM observations WHERE run_id = ? AND store = ?",
                                    (run_id, store)).fetchone()[0],
            **{key: int(counts.get(key, 0)) for key in ORDER},
            "quality": "FAIL" if (sev == "error").any() else "PASS WITH WARNINGS" if (sev == "warning").any()
            else "PASS",
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- excel
class Book:
    INK, GREY, LINE = "#1F3864", "#7F7F7F", "#BFBFBF"
    SEVERITY = {"error": ("FAIL", "#C62828"), "warning": ("WARN", "#9C6500"), "ok": ("PASS", "#2E7D32"),
                "info": ("INFO", "#7F7F7F")}
    CHANGE_COLOR = {"removed": "#C62828", "out_of_stock": "#C62828", "not_seen": "#9C6500",
                    "new": "#2E7D32", "returned": "#2E7D32", "back_in_stock": "#2E7D32"}

    def __init__(self, path: Path):
        self.wb = xlsxwriter.Workbook(path, {"nan_inf_to_errors": True, "strings_to_urls": False})
        f = self.wb.add_format
        self.f = {
            "title": f({"bold": True, "font_size": 16, "font_color": self.INK}),
            "subtitle": f({"italic": True, "font_color": self.GREY}),
            "section": f({"bold": True, "font_color": self.INK, "font_size": 12}),
            "head": f({"bold": True, "font_color": "white", "bg_color": self.INK, "text_wrap": True,
                       "valign": "vcenter"}),
            "head_num": f({"bold": True, "font_color": "white", "bg_color": self.INK, "align": "right",
                           "text_wrap": True, "valign": "vcenter"}),
            "text": f({}),
            "wrap": f({"text_wrap": True, "valign": "top"}),
            "int": f({"num_format": "#,##0"}),
            "money": f({"num_format": "#,##0.00"}),
            "pct": f({"num_format": "+0.0%;-0.0%"}),
            "link": f({"font_color": "#2a78d6", "underline": 1}),
            "note": f({"italic": True, "font_color": self.GREY, "font_size": 9}),
            "kpi_label": f({"bottom": 1, "bottom_color": "#D9D9D9"}),
            "kpi_value": f({"bold": True, "font_size": 12, "num_format": "#,##0", "align": "left",
                            "bottom": 1, "bottom_color": "#D9D9D9"}),
            "badge_PASS": f({"bold": True, "font_color": "white", "bg_color": "#2E7D32", "align": "center"}),
            "badge_PASS WITH WARNINGS": f({"bold": True, "font_color": "black", "bg_color": "#FFD966",
                                           "align": "center"}),
            "badge_FAIL": f({"bold": True, "font_color": "white", "bg_color": "#C62828", "align": "center"}),
        }
        for name, (_, color) in self.SEVERITY.items():
            self.f[f"sev_{name}"] = f({"bold": True, "font_color": color})
        for name, color in self.CHANGE_COLOR.items():
            self.f[f"chg_{name}"] = f({"font_color": color, "bold": True})

    def sheet(self, name: str, title: str, subtitle: str):
        ws = self.wb.add_worksheet(name)
        ws.hide_gridlines(2)
        ws.write(0, 0, title, self.f["title"])
        ws.write(1, 0, subtitle, self.f["subtitle"])
        return ws

    def table(self, ws, row: int, df: pd.DataFrame, columns: list[tuple[str, str, str, float]],
              filters: bool = False) -> int:
        """columns: (field, header, format, width). Returns the first free row after the table."""
        for c, (_, head, fmt, width) in enumerate(columns):
            ws.write(row, c, head, self.f["head_num" if fmt in ("int", "money", "pct") else "head"])
            ws.set_column(c, c, width)
        for r, rec in enumerate(df.to_dict("records"), start=row + 1):
            for c, (field, _, fmt, _) in enumerate(columns):
                value = rec.get(field)
                if value is None or (isinstance(value, float) and pd.isna(value)):
                    ws.write_blank(r, c, None)
                elif fmt == "change":
                    ws.write(r, c, LABEL.get(value, value), self.f.get(f"chg_{value}", self.f["text"]))
                elif fmt == "severity":
                    label, _ = self.SEVERITY[value]
                    ws.write(r, c, label, self.f[f"sev_{value}"])
                elif fmt == "link":
                    ws.write_url(r, c, value, self.f["link"], string="open")
                elif fmt in ("int", "money", "pct"):
                    ws.write_number(r, c, float(value), self.f[fmt])
                else:
                    ws.write(r, c, value, self.f[fmt])
        if filters and len(df):
            ws.autofilter(row, 0, row + len(df), len(columns) - 1)
        if filters:
            ws.freeze_panes(row + 1, 0)
        return row + len(df) + 2


def write_report(con: sqlite3.Connection, run_id: int, out_dir: Path = OUT) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    info = run_info(con, run_id)
    changes, catalog = changes_table(con, run_id), catalog_table(con, run_id)
    quality, runs = quality_table(con, run_id), runs_table(con)
    stores = store_summary(con, run_id, changes, quality)
    overall = ("FAIL" if (quality["severity"] == "error").any() else
               "PASS WITH WARNINGS" if (quality["severity"] == "warning").any() else "PASS")
    previous = con.execute("SELECT MAX(run_id) FROM runs WHERE run_id < ?", (run_id,)).fetchone()[0]
    when = info["started_at"].replace("T", " ").replace("Z", " UTC")
    mode = {"live": "live run", "replay": f"replay of run #{info['source_run']}",
            "simulated": f"simulated next day: archived pages of run #{info['source_run']} with seeded changes"
            }[info["mode"]]
    against = f" · compared with run #{previous}" if previous else " · baseline run"

    paths = {"xlsx": out_dir / "Price_Monitor_Report.xlsx", "changes": out_dir / "changes.csv",
             "catalog": out_dir / "catalog.csv", "quality": out_dir / "quality.csv"}
    book = Book(paths["xlsx"])
    f = book.f

    # ---- Summary
    ws = book.sheet("Summary", f"Price & catalog monitor · run #{run_id}", f"{when} · {mode}{against}")
    ws.write(3, 0, "Data quality", f["section"])
    ws.merge_range(3, 1, 3, 2, overall, f[f"badge_{overall}"])
    count = changes["change"].value_counts()
    kpis = [("Products tracked", int((catalog["status"] == "listed").sum())),
            ("Price changes", int(count.get("price_down", 0) + count.get("price_up", 0))),
            ("Stock changes", int(count.get("out_of_stock", 0) + count.get("back_in_stock", 0))),
            ("New products", int(count.get("new", 0) + count.get("returned", 0))),
            ("Removed", int(count.get("removed", 0))),
            ("Not seen (held)", int(count.get("not_seen", 0)))]
    ws.write(5, 0, "This run", f["section"])
    for r, (label, value) in enumerate(kpis, start=6):
        ws.write(r, 0, label, f["kpi_label"])
        ws.write_number(r, 1, value, f["kpi_value"])
    ws.write(13, 0, "By store", f["section"])
    row = book.table(ws, 14, stores, [
        ("store", "Store", "text", 22), ("method", "Collected with", "text", 20), ("pages", "Pages loaded", "text", 13),
        ("products", "Products", "int", 10), ("price_down", "Price down", "int", 10), ("price_up", "Price up", "int", 10),
        ("out_of_stock", "Out of stock", "int", 10), ("new", "New", "int", 8), ("removed", "Removed", "int", 9),
        ("not_seen", "Not seen", "int", 9), ("quality", "Data quality", "text", 20)])
    ws.write(row, 0, "Largest price moves", f["section"])
    moves = changes[changes["change"].isin(["price_down", "price_up"])].copy()
    moves = moves.reindex(moves["pct"].abs().sort_values(ascending=False).index).head(8)
    moves["store"] = moves["store"].map(lambda s: STORES[s].name if s in STORES else s)
    moves["old"], moves["new"] = moves["old_value"].astype(float), moves["new_value"].astype(float)
    row = book.table(ws, row + 1, moves, [
        ("store", "Store", "text", 22), ("product", "Product", "text", 20), ("old", "Before", "money", 13),
        ("new", "After", "money", 10), ("pct", "Change", "pct", 10), ("currency", "Currency", "text", 10)])
    ws.set_column(1, 1, 40)
    ws.write(row, 0, "Not seen (held): missing from a category whose pages did not all load. Kept on watch, "
                     "not reported as removed.", f["note"])
    ws.write(row + 1, 0, "Practice sites with fictitious data (books.toscrape.com, webscraper.io test shop).",
             f["note"])

    # ---- Changes
    ws = book.sheet("Changes", f"Changes in run #{run_id}", f"{len(changes)} changes{against}")
    view = changes.assign(store=changes["store"].map(lambda s: STORES[s].name if s in STORES else s),
                          old=pd.to_numeric(changes["old_value"], errors="coerce"),
                          new=pd.to_numeric(changes["new_value"], errors="coerce"))
    book.table(ws, 3, view, [
        ("store", "Store", "text", 22), ("category", "Category", "text", 11), ("product", "Product", "text", 46),
        ("change", "Change", "change", 16), ("old", "Before", "money", 10), ("new", "After", "money", 10),
        ("pct", "Change %", "pct", 10), ("currency", "Currency", "text", 9), ("url", "Link", "link", 7)],
        filters=True)

    # ---- Catalog
    ws = book.sheet("Catalog", "Catalog after this run",
                    f"{len(catalog):,} products ever seen · price and stock as last observed")
    book.table(ws, 3, catalog.assign(store=catalog["store"].map(lambda s: STORES[s].name if s in STORES else s)), [
        ("store", "Store", "text", 22), ("category", "Category", "text", 11), ("product", "Product", "text", 46),
        ("price", "Price", "money", 10), ("currency", "Currency", "text", 9), ("in_stock", "In stock", "text", 9),
        ("rating", "Rating", "int", 8), ("reviews", "Reviews", "int", 8), ("status", "Status", "text", 10),
        ("first_seen_run", "First seen", "int", 10), ("last_seen_run", "Last seen", "int", 10),
        ("url", "Link", "link", 7)], filters=True)

    # ---- Data quality
    ws = book.sheet("Data quality", f"Data quality · run #{run_id}", f"Overall: {overall}")
    book.table(ws, 3, quality.assign(store=quality["store"].map(lambda s: STORES[s].name if s in STORES else s)), [
        ("store", "Store", "text", 22), ("check_name", "Check", "text", 26), ("severity", "Result", "severity", 8),
        ("count", "Count", "int", 8), ("detail", "Detail", "wrap", 90)])

    # ---- Runs
    ws = book.sheet("Runs", "Run history", "Every run is kept; nothing is overwritten")
    book.table(ws, 3, runs, [
        ("run_id", "Run", "int", 6), ("started_at", "Started (UTC)", "text", 22), ("mode", "Mode", "text", 10),
        ("source_run", "Source run", "int", 10), ("pages_ok", "Pages loaded", "int", 12), ("pages", "Pages", "int", 8),
        ("products", "Products", "int", 10), ("changes", "Changes", "int", 9), ("quality", "Data quality", "text", 20)])
    book.wb.close()

    changes.to_csv(paths["changes"], index=False)
    catalog.to_csv(paths["catalog"], index=False)
    quality.to_csv(paths["quality"], index=False)
    return paths
