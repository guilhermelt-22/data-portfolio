"""Writes the clean variants in Shopify's product CSV format, column for column.

TEMPLATE is the header row of Shopify's own sample file (help.shopify.com, product_template.csv), in the
same order and spelling. Shopify matches headers exactly, so they are not retyped anywhere else.

Layout, as Shopify documents it: the first row of a product carries the product fields and its first
variant; each further variant is a row with the same URL handle; each further image is a row with only the
handle and the image columns.
"""
from __future__ import annotations

import csv
import html
from pathlib import Path

import pandas as pd

from . import config

TEMPLATE = [
    "Title", "URL handle", "Description", "Vendor", "Product category", "Type", "Tags", "Published on online store",
    "Status", "SKU", "Variant Barcodes", "Option1 name", "Option1 value", "Option1 Linked To", "Option2 name",
    "Option2 value", "Option2 Linked To", "Option3 name", "Option3 value", "Option3 Linked To", "Price",
    "Compare-at price", "Cost per item", "Charge tax", "Tax code", "Unit price total measure",
    "Unit price total measure unit", "Unit price base measure", "Unit price base measure unit", "Inventory tracker",
    "Inventory quantity", "Continue selling when out of stock", "Weight value (grams)", "Weight unit for display",
    "Requires shipping", "Fulfillment service", "Product image URL", "Image position", "Image alt text",
    "Variant image URL", "Gift card", "SEO title", "SEO description",
    "Color (product.metafields.shopify.color-pattern)", "Google Shopping / Google product category",
    "Google Shopping / Gender", "Google Shopping / Age group", "Google Shopping / Manufacturer part number (MPN)",
    "Google Shopping / Ad group name", "Google Shopping / Ads labels", "Google Shopping / Condition",
    "Google Shopping / Custom product", "Google Shopping / Custom label 0", "Google Shopping / Custom label 1",
    "Google Shopping / Custom label 2", "Google Shopping / Custom label 3", "Google Shopping / Custom label 4",
    "Packed product length", "Packed product width", "Packed product height", "Packed product dimension unit",
]
SEO_TITLE_MAX, SEO_DESC_MAX, ALT_MAX = 70, 320, 512


def description_html(material: str, features: list[str]) -> str:
    items = "".join(f"<li>{html.escape(f)}</li>" for f in features)
    parts = [f"<ul>{items}</ul>"] if items else []
    if material:
        parts.append(f"<p><strong>Material:</strong> {html.escape(material)}</p>")
    return "".join(parts)


def seo_description(title: str, material: str, features: list[str]) -> str:
    text = f"{title}. " + ". ".join(features[:2]) + (f". {material}." if material else ".")
    return text if len(text) <= SEO_DESC_MAX else text[: SEO_DESC_MAX - 3].rsplit(" ", 1)[0] + "..."


def options_for(grp: pd.DataFrame) -> list[str]:
    """Colour and size become options only when they vary; a single variant gets Shopify's default title."""
    opts = [name for name, col in (("Color", "color"), ("Size", "size")) if grp[col].nunique() > 1]
    return opts or ["Title"]


def build(variants: pd.DataFrame, status: str = config.DEFAULT_STATUS) -> pd.DataFrame:
    rows = []
    for style, grp in variants.groupby("style", sort=False):
        first = grp.iloc[0]
        opts = options_for(grp)
        images = list(dict.fromkeys(u for lst in grp["images"] for u in lst))
        tags = ", ".join(dict.fromkeys([first["type"], config.SEASON_TAG, config.VENDOR] +
                                       ([first["material"].split(",")[0].split("% ")[-1].strip().capitalize()]
                                        if first["material"] else [])))
        for k, (_, v) in enumerate(grp.iterrows()):
            row = dict.fromkeys(TEMPLATE, "")
            row["URL handle"] = v["handle"]
            row["SKU"] = v["sku"]
            row["Variant Barcodes"] = v["barcode"]
            for n, opt in enumerate(opts, start=1):
                row[f"Option{n} name"] = opt
                row[f"Option{n} value"] = "Default Title" if opt == "Title" else v["color" if opt == "Color" else "size"]
            row.update({
                "Price": f"{v['price']:.2f}", "Cost per item": "" if pd.isna(v["wholesale"]) else f"{v['wholesale']:.2f}",
                "Charge tax": "true", "Inventory tracker": "shopify", "Inventory quantity": str(int(v["qty"])),
                "Continue selling when out of stock": "deny", "Weight value (grams)": str(int(v["grams"])),
                "Weight unit for display": config.WEIGHT_UNIT_DISPLAY, "Requires shipping": "true",
                "Fulfillment service": "manual", "Variant image URL": v["variant_image"],
            })
            if k == 0:
                row.update({
                    "Title": v["title"], "Description": description_html(v["material"], v["features"]),
                    "Vendor": config.VENDOR, "Product category": v["category"], "Type": v["type"], "Tags": tags,
                    "Published on online store": config.PUBLISHED, "Status": status, "Gift card": "false",
                    "SEO title": f"{v['title']} | {config.VENDOR}"[:SEO_TITLE_MAX],
                    "SEO description": seo_description(v["title"], v["material"], v["features"]),
                })
                if images:
                    row.update({"Product image URL": images[0], "Image position": "1", "Image alt text": v["title"][:ALT_MAX]})
            rows.append(row)
        for pos, url in enumerate(images[1:], start=2):
            row = dict.fromkeys(TEMPLATE, "")
            row.update({"URL handle": first["handle"], "Product image URL": url, "Image position": str(pos),
                        "Image alt text": first["title"][:ALT_MAX]})
            rows.append(row)
    return pd.DataFrame(rows, columns=TEMPLATE)


def write_csv(df: pd.DataFrame, path: Path) -> Path:
    """UTF-8 without BOM, LF line endings, every field as text (no 8.40123E+11 on the way out either)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
        w.writerow(df.columns)
        w.writerows(df.astype(str).itertuples(index=False, name=None))
    return path
