"""Deliverables for the store owner: an Excel workbook and an HTML page per run."""
from __future__ import annotations

import html
import re

import pandas as pd
import xlsxwriter

INK, GREY = "#1F3864", "#7F7F7F"
BADGE = {"PASS": "#2E7D32", "WARN": "#B7791F", "FAIL": "#C62828", "PASS WITH WARNINGS": "#B7791F", "FIX": "#2a78d6"}


def fix_summary(log: pd.DataFrame) -> pd.DataFrame:
    """One line per kind of fix ("Colour written as 'NVY' -> 'Navy'"), with how many rows and which."""
    if log.empty:
        return pd.DataFrame(columns=["severity", "issue", "action", "rows", "example rows"])
    g = log.groupby(["severity", "issue", "action"], sort=False)["row"]
    out = g.agg(rows="count", example=lambda s: ", ".join(str(r) for r in list(s)[:6]) + (" ..." if len(s) > 6 else ""))
    out = out.reset_index().rename(columns={"example": "example rows"})
    return out.sort_values(["severity", "rows"], ascending=[False, False]).reset_index(drop=True)


def fix_kinds(log: pd.DataFrame) -> pd.DataFrame:
    """Coarser: one line per type of problem, for the summary page."""
    if log.empty:
        return pd.DataFrame(columns=["severity", "problem", "rows"])
    kind = (log["issue"].str.replace(r"'[^']*'", "", regex=True).str.replace(r"\$[\d.]+", "", regex=True)
            .str.replace(r"\d+ image links for \S+ start with http://.*", "Image links start with http://", regex=True)
            .str.replace(r"No images for .*", "No images", regex=True).str.replace(r"\s+", " ", regex=True).str.strip())
    kind = kind.str.replace(r"^Colour written as$", "Colour spelled differently", regex=True)
    kind = kind.str.replace(r"^Size written as$", "Size spelled differently", regex=True)
    stock = kind.str.fullmatch("Stock given as")
    kind = kind.mask(stock & (log["severity"] == "FIX"), "Stock written as text (\"50+\")")
    kind = kind.mask(stock & (log["severity"] == "WARN"), "Stock missing or not a number (imported as 0)")
    kind = kind.str.replace(r"^Barcode has 11 digits$", "Barcode lost its leading zero", regex=True)
    out = log.assign(problem=kind).groupby(["severity", "problem"], sort=False)["row"].count().reset_index(name="rows")
    return out.sort_values(["severity", "rows"], ascending=[True, False]).reset_index(drop=True)


def products_table(variants: pd.DataFrame, status: str) -> pd.DataFrame:
    g = variants.groupby("style", sort=False)
    return pd.DataFrame({
        "URL handle": g["handle"].first(), "Title": g["title"].first(), "Type": g["type"].first(),
        "Variants": g["sku"].count(), "Price from": g["price"].min(), "Price to": g["price"].max(),
        "Images": g["images"].apply(lambda s: len(dict.fromkeys(u for lst in s for u in lst))),
        "Priced by rule": g["priced_by_rule"].any().map({True: "yes", False: ""}), "Status": status,
    }).reset_index(drop=True)


def _formats(wb):
    f = {
        "title": wb.add_format({"bold": True, "font_size": 16, "font_color": INK}),
        "sub": wb.add_format({"italic": True, "font_color": GREY}),
        "section": wb.add_format({"bold": True, "font_size": 12, "font_color": INK}),
        "head": wb.add_format({"bold": True, "font_color": "white", "bg_color": INK, "text_wrap": True, "valign": "top"}),
        "text": wb.add_format({"valign": "top"}), "wrap": wb.add_format({"text_wrap": True, "valign": "top"}),
        "int": wb.add_format({"num_format": "#,##0", "valign": "top"}),
        "money": wb.add_format({"num_format": "$#,##0.00", "valign": "top"}),
        "pct": wb.add_format({"num_format": "+0.0\\%;-0.0\\%", "valign": "top"}),
    }
    for name, color in BADGE.items():
        f[name] = wb.add_format({"bold": True, "font_color": color, "valign": "top"})
    return f


def _table(ws, f, row, df, widths=None, money=(), pct=(), wrap=()):
    ws.write_row(row, 0, list(df.columns), f["head"])
    for i, rec in enumerate(df.itertuples(index=False), start=row + 1):
        for j, (col, val) in enumerate(zip(df.columns, rec)):
            if isinstance(val, float) and pd.isna(val):
                val = ""
            fmt = f["money"] if col in money else f["pct"] if col in pct else f["wrap"] if col in wrap else \
                f.get(val) if isinstance(val, str) and val in BADGE else f["int"] if isinstance(val, int) else f["text"]
            ws.write(i, j, val, fmt)
    for j, w in enumerate(widths or []):
        ws.set_column(j, j, w)
    if len(df):
        ws.autofilter(row, 0, row + len(df), len(df.columns) - 1)
    return row + len(df) + 2


def import_excel(path, source, result, rows, log, variants, status):
    wb = xlsxwriter.Workbook(path, {"nan_inf_to_errors": True})
    f = _formats(wb)
    ws = wb.add_worksheet("Summary")
    ws.hide_gridlines(2)
    ws.set_column(0, 0, 52)
    ws.set_column(1, 1, 22)
    ws.set_column(2, 2, 100)
    ws.write(0, 0, "Supplier file to Shopify import: checks", f["title"])
    ws.write(1, 0, f"Source: {source}. Fictitious supplier and products.", f["sub"])
    ws.write(3, 0, "Overall", f["section"])
    ws.write(3, 1, result["overall"], f[result["overall"]])
    ws.write_row(4, 0, ["Check", "Result", "Detail"], f["head"])
    r = 5
    for name, res, detail in result["checks"]:
        ws.write(r, 0, name, f["text"])
        ws.write(r, 1, res, f[res])
        ws.write(r, 2, detail, f["wrap"])
        r += 1
    r += 1
    ws.write(r, 0, "What was done, by type", f["section"])
    _table(ws, f, r + 1, fix_kinds(log))

    held = rows[rows["fate"] == "held back"][["row", "sku", "reason"]].rename(columns={"reason": "Question for you"})
    _table(wb.add_worksheet("Held back"), f, 0, held, [8, 22, 110], wrap=("Question for you",))
    _table(wb.add_worksheet("Fixes and warnings"), f, 0, fix_summary(log), [10, 70, 80, 8, 30], wrap=("issue", "action"))
    _table(wb.add_worksheet("Products"), f, 0, products_table(variants, status), [32, 30, 14, 9, 11, 11, 8, 13, 9],
           money=("Price from", "Price to"))
    _table(wb.add_worksheet("Every row"), f, 0, rows.rename(columns={"reason": "detail"}), [8, 22, 18, 100], wrap=("detail",))
    _table(wb.add_worksheet("Full log"), f, 0, log, [8, 22, 70, 80, 10], wrap=("issue", "action"))
    wb.close()


def changes_excel(path, source, changes, files):
    wb = xlsxwriter.Workbook(path, {"nan_inf_to_errors": True})
    f = _formats(wb)
    ws = wb.add_worksheet("Summary")
    ws.hide_gridlines(2)
    ws.set_column(0, 0, 46)
    ws.set_column(1, 1, 14)
    ws.write(0, 0, "What changed in the supplier's new price list", f["title"])
    ws.write(1, 0, f"Source: {source}. Compared SKU by SKU with the products imported last time.", f["sub"])
    summary = changes_summary(changes, files)
    _table(ws, f, 3, summary, [46, 14])
    pc = changes["price_changes"][["sku", "title", "old_price", "new_price", "change_pct"]]
    _table(wb.add_worksheet("Price changes"), f, 0, pc, [22, 32, 11, 11, 10], money=("old_price", "new_price"), pct=("change_pct",))
    nv = changes["new_variants"][["sku", "title", "color", "size", "price", "qty"]] if len(changes["new_variants"]) else pd.DataFrame()
    if len(nv):
        _table(wb.add_worksheet("New variants"), f, 0, nv, [22, 32, 14, 10, 10, 8], money=("price",))
    ms = margin_squeeze(changes)
    if len(ms):
        _table(wb.add_worksheet("Margin falls"), f, 0, ms[["sku", "title", "old_cost", "new_cost", "new_price"]],
               [22, 32, 11, 11, 11], money=("old_cost", "new_cost", "new_price"))
    _table(wb.add_worksheet("Stock changes"), f, 0, changes["stock_changes"], [22, 10, 10])
    wb.close()


def margin_squeeze(changes) -> pd.DataFrame:
    cc = changes["cost_changes"]
    return cc[(cc["new_cost"] > cc["old_cost"]) & (cc["new_price"] == cc["old_price"])]


def changes_summary(changes, files) -> pd.DataFrame:
    pc = changes["price_changes"]
    return pd.DataFrame([
        ("Price changes", len(pc)), ("  of which increases", int((pc["change_pct"] > 0).sum())),
        ("  of which decreases", int((pc["change_pct"] < 0).sum())), ("Cost changes", len(changes["cost_changes"])),
        ("  cost up, retail unchanged (margin falls)", len(margin_squeeze(changes))),
        ("Stock changes", len(changes["stock_changes"])), ("New products", len(changes["new_styles"])),
        ("New variants of existing products", len(changes["new_variants"])),
        ("Variants dropped by the supplier (stock set to 0)", len(changes["gone_variants"])),
        ("Products to archive", len(changes["archived_styles"])),
        ("Rows in new_products.csv", len(files["new_products"])),
        ("Rows in update_existing.csv", len(files["update_existing"])), ("Products in archive.csv", int((files["archive"]["Status"] == "archived").sum())),
    ], columns=["Change", "Count"])


def import_html(path, source, result, rows, log, variants, raw_kinds, seconds):
    fates = rows["fate"].value_counts()
    tiles = [
        (f"{raw_kinds.get('product', 0)}", "product rows in the supplier file"),
        (f"{variants['style'].nunique()}", f"products, {len(variants)} variants ready to import"),
        (f"{int(fates.get('held back', 0))}", "rows held back, each with a question"),
        (f"{int((log['severity'] == 'FIX').sum())}", "values fixed, each logged with its row"),
        (f"{seconds:.1f} s", "from the Excel file to a checked CSV"),
    ]
    tile_html = "".join(f"<div class='tile'><div class='big'>{html.escape(a)}</div><div>{html.escape(b)}</div></div>"
                        for a, b in tiles)
    recon = [("Imported", int(fates.get("imported", 0)), "#2E7D32"), ("Duplicate removed", int(fates.get("duplicate removed", 0)), "#7F7F7F"),
             ("Held back", int(fates.get("held back", 0)), "#B7791F"), ("Discontinued", int(fates.get("excluded", 0)), "#9E9E9E")]
    total = sum(n for _, n, _ in recon) or 1
    bar = "".join(f"<div style='width:{max(n / total * 100, 1.2):.2f}%;background:{c}' title='{l}: {n}'></div>" for l, n, c in recon)
    legend = " · ".join(f"<span class='dot' style='background:{c}'></span>{l} <b>{n}</b>" for l, n, c in recon)
    checks = "".join(f"<tr><td>{html.escape(n)}</td><td><b style='color:{BADGE[r]}'>{r}</b></td><td>{html.escape(d)}</td></tr>"
                     for n, r, d in result["checks"])
    kinds = fix_kinds(log)
    kinds_html = "".join(f"<tr><td><b style='color:{BADGE[s]}'>{s}</b></td><td>{html.escape(p)}</td><td class='num'>{n}</td></tr>"
                         for s, p, n in kinds.itertuples(index=False))
    held = rows[rows["fate"] == "held back"]
    items = [re.sub(r" on rows [0-9, ]+ ", " ", r) if sku in r else f"{sku}: {r}" for sku, r in zip(held["sku"], held["reason"])]
    held_html = "".join(f"<li>{html.escape(t)}</li>" for t in dict.fromkeys(items))
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Supplier file to Shopify</title>
<style>
body{{font-family:Segoe UI,Helvetica,Arial,sans-serif;color:#1d2433;margin:0;background:#f6f7f9}}
main{{max-width:1080px;margin:0 auto;padding:28px 24px 40px}}
h1{{font-size:24px;margin:0 0 4px;color:{INK}}} h2{{font-size:16px;margin:26px 0 10px;color:{INK}}}
.sub{{color:#5b6475;font-size:13px}} .tiles{{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin-top:18px}}
.tile{{background:#fff;border:1px solid #e3e6eb;border-radius:8px;padding:12px 14px;font-size:13px;color:#5b6475}}
.big{{font-size:26px;font-weight:700;color:{INK};margin-bottom:2px}}
.bar{{display:flex;height:18px;border-radius:4px;overflow:hidden;margin:8px 0 6px}} .dot{{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:4px}}
table{{width:100%;border-collapse:collapse;background:#fff;font-size:13px;border:1px solid #e3e6eb}}
th{{background:{INK};color:#fff;text-align:left;padding:7px 9px;font-weight:600}} td{{padding:6px 9px;border-top:1px solid #edf0f3;vertical-align:top}}
td.num{{text-align:right}} .cols{{display:grid;grid-template-columns:1fr 1fr;gap:18px}} ul{{margin:0;padding-left:18px;font-size:13px}} li{{margin:4px 0}}
.overall{{display:inline-block;margin-left:8px;font-weight:700;color:{BADGE[result['overall']]}}}
@media (max-width:760px){{.tiles{{grid-template-columns:1fr 1fr}} .cols{{grid-template-columns:1fr}}}}
</style></head><body><main>
<h1>Supplier price list → Shopify import file</h1>
<div class="sub">{html.escape(source)} · fictitious supplier and products · checked against Shopify's product CSV rules</div>
<div class="tiles">{tile_html}</div>
<h2>Every supplier row accounted for</h2><div class="bar">{bar}</div><div class="sub">{legend}</div>
<h2>Checks before upload <span class="overall">{result['overall']}</span></h2>
<table><tr><th style="width:34%">Check</th><th style="width:8%">Result</th><th>Detail</th></tr>{checks}</table>
<div class="cols"><div><h2>What was fixed or flagged</h2><table><tr><th></th><th>Problem</th><th>Rows</th></tr>{kinds_html}</table></div>
<div><h2>Held back: questions for the store owner</h2><ul>{held_html}</ul></div></div>
</main></body></html>"""
    path.write_text(page, encoding="utf-8")
