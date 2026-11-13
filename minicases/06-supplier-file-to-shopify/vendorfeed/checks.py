"""Checks the import file against Shopify's documented rules before anyone uploads it.

A Shopify import cannot be cancelled once it starts and has no undo, so the file is checked here first:
headers, encoding, handles, options, SKUs, prices, barcodes, images, text limits and allowed values. The
last check reconciles the supplier file: every product row must be accounted for.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from .clean import gtin_ok
from .shopify import ALT_MAX, SEO_DESC_MAX, SEO_TITLE_MAX, TEMPLATE

MAX_BYTES = 15 * 1024 * 1024
HANDLE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ALLOWED = {
    "Status": {"active", "draft", "archived"},
    "Published on online store": {"true", "false"},
    "Charge tax": {"true", "false"}, "Requires shipping": {"true", "false"}, "Gift card": {"true", "false"},
    "Inventory tracker": {"shopify", "shipwire", "amazon_marketplace_web"},
    "Continue selling when out of stock": {"deny", "continue"},
    "Weight unit for display": {"g", "kg", "lb", "oz"},
}


def _result(problems: list[str], warn_only: bool = False) -> str:
    return "PASS" if not problems else ("WARN" if warn_only else "FAIL")


def _detail(problems: list[str], ok: str, limit: int = 3) -> str:
    if not problems:
        return ok
    more = f" (+{len(problems) - limit} more)" if len(problems) > limit else ""
    return "; ".join(problems[:limit]) + more


def run_checks(df: pd.DataFrame, csv_path: Path, rows: pd.DataFrame | None = None,
               raw_kinds: dict | None = None) -> dict:
    checks = []

    def add(name, problems, ok, warn_only=False):
        checks.append((name, _result(problems, warn_only), _detail(problems, ok)))

    add("Headers match Shopify's template", [] if list(df.columns) == TEMPLATE else
        [f"expected {len(TEMPLATE)} columns in template order, got {len(df.columns)}"],
        f"{len(TEMPLATE)} columns, same names and order as Shopify's sample file")

    data = csv_path.read_bytes()
    enc = []
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as e:
        enc.append(f"not UTF-8 ({e})")
    if data.startswith(b"\xef\xbb\xbf"):
        enc.append("starts with a byte-order mark")
    if b"\r\n" in data:
        enc.append("Windows line endings")
    if len(data) > MAX_BYTES:
        enc.append(f"{len(data) / 1e6:.1f} MB, over Shopify's 15 MB limit")
    add("File: UTF-8, LF line endings, under 15 MB", enc, f"UTF-8, LF, {len(data) / 1024:.0f} KB")

    first = df[df["Title"] != ""]
    handles = df["URL handle"]
    probs = [f"row {i + 2}: no URL handle" for i in df.index[handles == ""]]
    probs += [f"'{h}' is not a valid handle" for h in sorted(set(handles[handles != ""])) if not HANDLE.match(h)]
    starts = df.groupby("URL handle", sort=False).head(1)
    probs += [f"'{h}' starts without a title" for h in starts.loc[starts["Title"] == "", "URL handle"]]
    if first["URL handle"].duplicated().any():
        probs += [f"'{h}' has two title rows" for h in first.loc[first["URL handle"].duplicated(), "URL handle"]]
    add("Every product: valid handle, one title row", probs, f"{len(first)} products, handles use a-z, 0-9 and dashes")

    var = df[df["SKU"] != ""]
    probs = []
    for h, grp in var.groupby("URL handle"):
        names = [tuple(grp[f"Option{n} name"]) for n in (1, 2, 3)]
        if any(len(set(n)) > 1 for n in names):
            probs.append(f"{h}: option names change between rows")
        combo = grp[["Option1 value", "Option2 value", "Option3 value"]].apply(tuple, axis=1)
        if combo.duplicated().any():
            probs.append(f"{h}: two variants with the same options")
        if (grp["Option1 value"] == "").any():
            probs.append(f"{h}: variant without Option1 value")
    add("Options: at most 3, one variant per combination", probs,
        f"{len(var)} variants, every option combination unique within its product")

    dups = var.loc[var["SKU"].duplicated(), "SKU"].tolist()
    add("SKUs unique", [f"{s} repeated" for s in dups], f"{var['SKU'].nunique()} SKUs, none repeated")

    probs = []
    for _, r in var.iterrows():
        try:
            price = float(r["Price"])
        except ValueError:
            probs.append(f"{r['SKU']}: price '{r['Price']}' is not a number")
            continue
        if price <= 0:
            probs.append(f"{r['SKU']}: price {price:.2f}")
        if r["Cost per item"] and float(r["Cost per item"]) > price:
            probs.append(f"{r['SKU']}: cost {r['Cost per item']} above price {r['Price']}")
    add("Prices: numbers above zero, never below cost", probs, "every variant has a price above its cost")

    bad = [f"{r['SKU']}: {r['Variant Barcodes']}" for _, r in var.iterrows()
           if r["Variant Barcodes"] and not all(gtin_ok(b.split(":")[-1]) for b in r["Variant Barcodes"].split(";"))]
    blank = int((var["Variant Barcodes"] == "").sum())
    add("Barcodes: valid check digit", bad, f"{len(var) - blank} barcodes valid; {blank} left blank on purpose (see log)")

    probs = []
    img = df[df["Product image URL"] != ""]
    for h, grp in img.groupby("URL handle"):
        urls = grp["Product image URL"]
        if len(urls) > 250:
            probs.append(f"{h}: {len(urls)} images (max 250)")
        if urls.duplicated().any():
            probs.append(f"{h}: the same image twice")
    for col in ("Product image URL", "Variant image URL"):
        probs += [f"not HTTPS: {u}" for u in df.loc[(df[col] != "") & ~df[col].str.startswith("https://"), col]]
    pos = pd.to_numeric(img["Image position"], errors="coerce")
    if pos.isna().any() or (pos < 1).any():
        probs.append("image position missing or below 1")
    no_img = sorted(set(first["URL handle"]) - set(img["URL handle"]))
    add("Images: HTTPS, unique, positions from 1", probs,
        f"{len(img)} image rows" + (f"; {len(no_img)} products without images (see log)" if no_img else ""))

    probs = [f"{r['URL handle']}: SEO title {len(r['SEO title'])} chars" for _, r in first.iterrows() if len(r["SEO title"]) > SEO_TITLE_MAX]
    probs += [f"{r['URL handle']}: SEO description {len(r['SEO description'])} chars" for _, r in first.iterrows()
              if len(r["SEO description"]) > SEO_DESC_MAX]
    probs += [f"{r['URL handle']}: alt text {len(r['Image alt text'])} chars" for _, r in df.iterrows() if len(r["Image alt text"]) > ALT_MAX]
    probs += [f"{r['URL handle']}: {len(r['Tags'].split(','))} tags" for _, r in first.iterrows() if len(r["Tags"].split(",")) > 250]
    add("Text limits: SEO title 70, SEO description 320, alt text 512, 250 tags", probs, "all within Shopify's limits")

    probs = []
    for col, allowed in ALLOWED.items():
        vals = set(df[col]) - {""}
        probs += [f"{col}: '{v}'" for v in sorted(vals - allowed)]
    probs += [f"{r['SKU']}: weight '{r['Weight value (grams)']}'" for _, r in var.iterrows() if not r["Weight value (grams)"].isdigit()]
    probs += [f"{r['SKU']}: quantity '{r['Inventory quantity']}'" for _, r in var.iterrows() if not r["Inventory quantity"].isdigit()]
    add("Allowed values: status, true/false, inventory, weight", probs, "every value is one Shopify accepts")

    recon = None
    if rows is not None:
        fates = rows["fate"].value_counts().to_dict()
        recon = {"rows_in_sheet": sum((raw_kinds or {}).values()) + 1, "kinds": raw_kinds or {}, "fates": fates}
        accounted = sum(fates.values())
        product_rows = (raw_kinds or {}).get("product", accounted)
        imported = fates.get("imported", 0)
        probs = []
        if accounted != product_rows:
            probs.append(f"{product_rows} product rows in the file, {accounted} accounted for")
        if imported != len(var):
            probs.append(f"{imported} rows marked imported, {len(var)} variants in the CSV")
        add("Reconciliation: every supplier row accounted for", probs,
            f"{product_rows} product rows = {imported} imported + {fates.get('duplicate removed', 0)} duplicates "
            f"removed + {fates.get('held back', 0)} held back + {fates.get('excluded', 0)} discontinued")

    results = [c[1] for c in checks]
    overall = "FAIL" if "FAIL" in results else ("PASS WITH WARNINGS" if "WARN" in results else "PASS")
    return {"overall": overall, "checks": checks, "reconciliation": recon}
