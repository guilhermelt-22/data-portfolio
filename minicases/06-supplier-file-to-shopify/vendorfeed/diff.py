"""Next month's price list: what changed since the last import, and the files to bring the store up to date.

The store keeps the products from the last import. The new list is cleaned the same way, then compared
SKU by SKU against that snapshot:

- new_products.csv: styles the store has never had, full Shopify rows, as drafts
- update_existing.csv: products that changed (price, cost, stock or new colours). It has only the columns
  that change, plus what Shopify needs to find the product and variant: with "Overwrite products with
  matching handles", Shopify leaves the columns that are not in the file untouched, so descriptions and
  photos edited in the store are kept. Every variant of a touched product is listed; variants the supplier
  dropped stay in with stock 0 instead of disappearing.
- archive.csv: products the supplier no longer sells at all, set to archived (kept for order history)
"""
from __future__ import annotations

import pandas as pd

from .shopify import TEMPLATE, build, options_for

UPDATE_COLUMNS = ["Title", "URL handle", "Option1 name", "Option1 value", "Option2 name", "Option2 value", "SKU",
                  "Variant Barcodes", "Price", "Cost per item", "Inventory quantity", "Variant image URL"]
ARCHIVE_COLUMNS = ["Title", "URL handle", "Status"]


def _money(x) -> float | None:
    return None if x is None or pd.isna(x) else round(float(x), 2)


def compare(store: pd.DataFrame, new: pd.DataFrame) -> dict:
    s = store.set_index("sku")
    n = new.set_index("sku")
    common = s.index.intersection(n.index)
    price = pd.DataFrame({
        "sku": common, "title": n.loc[common, "title"].values,
        "old_price": s.loc[common, "price"].values, "new_price": n.loc[common, "price"].values,
        "old_cost": s.loc[common, "wholesale"].values, "new_cost": n.loc[common, "wholesale"].values,
    })
    price_changes = price[(price["old_price"] != price["new_price"])].copy()
    price_changes["change_pct"] = ((price_changes["new_price"] / price_changes["old_price"] - 1) * 100).round(1)
    cost_changes = price[price["old_cost"].round(2) != price["new_cost"].round(2)]
    stock = pd.DataFrame({"sku": common, "old_qty": s.loc[common, "qty"].values, "new_qty": n.loc[common, "qty"].values})
    stock_changes = stock[stock["old_qty"] != stock["new_qty"]]

    store_styles, new_styles = set(store["style"]), set(new["style"])
    brand_new = sorted(new_styles - store_styles)
    added = n.loc[n.index.difference(s.index)]
    new_variants = added[added["style"].isin(store_styles)].reset_index()
    gone = s.loc[s.index.difference(n.index)].reset_index()
    archived_styles = sorted(store_styles - new_styles)
    partial_gone = gone[~gone["style"].isin(archived_styles)]

    touched = sorted((set(n.loc[price_changes["sku"], "style"]) | set(n.loc[cost_changes["sku"], "style"]) |
                      set(n.loc[stock_changes["sku"], "style"]) | set(new_variants["style"]) |
                      set(partial_gone["style"])) - set(brand_new))
    return {"price_changes": price_changes.reset_index(drop=True), "cost_changes": cost_changes.reset_index(drop=True),
            "stock_changes": stock_changes.reset_index(drop=True), "new_styles": brand_new,
            "new_variants": new_variants, "gone_variants": partial_gone.reset_index(drop=True),
            "archived_styles": archived_styles, "touched_styles": touched}


def update_files(store: pd.DataFrame, new: pd.DataFrame, changes: dict) -> dict[str, pd.DataFrame]:
    new_products = build(new[new["style"].isin(changes["new_styles"])])

    rows = []
    for style in changes["touched_styles"]:
        cur = new[new["style"] == style]
        dropped = changes["gone_variants"]
        dropped = dropped[dropped["style"] == style].assign(qty=0)
        grp = pd.concat([cur, dropped], ignore_index=True)
        handle, title = store.loc[store["style"] == style, ["handle", "title"]].iloc[0]
        opts = options_for(grp)
        for k, (_, v) in enumerate(grp.iterrows()):
            row = dict.fromkeys(UPDATE_COLUMNS, "")
            row.update({"Title": title, "URL handle": handle, "SKU": v["sku"], "Variant Barcodes": v["barcode"],
                        "Price": f"{v['price']:.2f}", "Cost per item": "" if pd.isna(v["wholesale"]) else f"{v['wholesale']:.2f}",
                        "Inventory quantity": str(int(v["qty"])), "Variant image URL": v["variant_image"]})
            for i, opt in enumerate(opts[:2], start=1):
                row[f"Option{i} name"] = opt
                row[f"Option{i} value"] = "Default Title" if opt == "Title" else v["color" if opt == "Color" else "size"]
            rows.append(row)
    update = pd.DataFrame(rows, columns=UPDATE_COLUMNS)

    arch = store[store["style"].isin(changes["archived_styles"])].groupby("style").first()
    archive = pd.DataFrame({"Title": arch["title"], "URL handle": arch["handle"], "Status": "archived"},
                           columns=ARCHIVE_COLUMNS).reset_index(drop=True)
    assert all(c in TEMPLATE for c in UPDATE_COLUMNS + ARCHIVE_COLUMNS)
    return {"new_products": new_products, "update_existing": update, "archive": archive}
