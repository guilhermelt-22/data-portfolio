"""Turns the supplier's product rows into clean variants, and logs every fix and every row held back.

Each product row ends with exactly one fate: imported, duplicate removed, held back (with the question the
store owner has to answer) or excluded (discontinued). Fixes that change a value are logged with the row
number, so the store owner can check any of them against the original file.
"""
from __future__ import annotations

import math
import re

import pandas as pd

from . import config

SIZE_OF = {s.upper(): canon for canon, spellings in config.SIZES.items() for s in spellings + [canon]}
COLOR_OF = {s.upper(): canon for canon, spellings in config.COLORS.items() for s in spellings + [canon]}
SIZE_ORDER = {canon: i for i, canon in enumerate(config.SIZES)}
SMALL_WORDS = {"and", "or", "with", "for", "of", "the", "a", "in", "on"}
GRAMS = {"g": 1.0, "kg": 1000.0, "oz": 28.349523125, "lb": 453.59237, "lbs": 453.59237}

FATES = ["imported", "duplicate removed", "held back", "excluded"]


def text(value) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return re.sub(r"\s+", " ", str(value).replace(" ", " ")).strip()


def parse_money(value) -> float | None:
    s = text(value).replace("USD", "").replace("$", "").replace(",", "").strip()
    if not s:
        return None
    try:
        return round(float(s), 2)
    except ValueError:
        return None


def gtin_ok(digits: str) -> bool:
    if not digits.isdigit() or len(digits) not in (8, 12, 13, 14):
        return False
    body, check = digits[:-1], int(digits[-1])
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return (10 - total % 10) % 10 == check


def parse_barcode(value) -> tuple[str, str]:
    """Returns (barcode or "", status). Statuses: ok, restored_zero, scientific, bad_check, missing, bad_length."""
    if value is None or text(value) == "":
        return "", "missing"
    if isinstance(value, float) and not value.is_integer():
        return "", "scientific"
    s = text(value)
    if re.fullmatch(r"\d+(\.\d+)?[eE]\+?\d+", s):
        return "", "scientific"                     # the last digits are gone; only the supplier can resend them
    if isinstance(value, float):
        s = str(int(value))
    s = s.removesuffix(".0")
    if not s.isdigit():
        return "", "bad_length"
    if len(s) == 11 and gtin_ok("0" + s):
        return "0" + s, "restored_zero"
    if len(s) in (8, 12, 13, 14):
        return (s, "ok") if gtin_ok(s) else ("", "bad_check")
    return "", "bad_length"


def parse_qty(value) -> tuple[int, str]:
    s = text(value)
    if s == "":
        return 0, "blank"
    m = re.fullmatch(r"(\d+)\s*\+", s)
    if m:
        return int(m.group(1)), "at_least"
    try:
        n = int(float(s))
    except ValueError:
        return 0, "not_a_number"
    return (0, "negative") if n < 0 else (n, "ok")


def parse_weight(value) -> int | None:
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(g|kg|oz|lbs?|)", text(value).lower())
    if not m:
        return None
    unit = m.group(2) or "g"
    return int(round(float(m.group(1)) * GRAMS[unit]))


def title_case(words: list[str]) -> str:
    out = []
    for i, w in enumerate(words):
        lw = w.lower()
        if any(c.isdigit() for c in w):
            out.append(w.upper() if len(w) <= 3 else w.lower())
        elif i and lw in SMALL_WORDS:
            out.append(lw)
        else:
            out.append("-".join(p.capitalize() for p in lw.split("-")))
    return " ".join(out)


def style_title(descriptions: list[str], colors: list[str], sizes: list[str]) -> str:
    """The shared start of the variants' descriptions ("MERINO HIKER SOCK NAVY LG" -> "Merino Hiker Sock")."""
    toks = [d.upper().split() for d in descriptions if d]
    if len(toks) >= 2:
        prefix = []
        for group in zip(*toks):
            if len(set(group)) > 1:
                break
            prefix.append(group[0])
    else:
        prefix = toks[0] if toks else []
    tail = {c.upper() for c in colors} | {t for c in colors for t in c.upper().split()} | \
           {s.upper() for s in sizes} | {t for k in list(SIZE_OF) + list(COLOR_OF) for t in [k, *k.split()]}
    while prefix and prefix[-1] in tail:
        prefix.pop()
    return title_case(prefix)


def handleize(title: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", title.lower())).strip("-")


def clean(raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Returns (variants to import, every product row with its fate, log of fixes and warnings)."""
    df = raw[raw["kind"] == "product"].copy()
    for col in ("sku", "style", "description", "color", "size", "category", "material", "features", "status",
                "image1", "image2", "image3"):
        df[col] = df[col].map(text)
    df["fate"], df["reason"] = "imported", ""
    log: list[dict] = []

    def note(r, issue, action, severity="FIX"):
        log.append({"row": int(r["row"]), "sku": r["sku"], "issue": issue, "action": action, "severity": severity})

    def hold(idx, reason):
        df.loc[idx, ["fate", "reason"]] = ["held back", reason]

    # 1. exact duplicates: identical in every column the supplier sent
    content = [c for c in raw.columns if c not in ("row", "kind", "fate", "reason")]
    dup = df.duplicated(subset=content, keep="first")
    df.loc[dup, ["fate", "reason"]] = ["duplicate removed", "Identical to an earlier row"]

    live = df["fate"] == "imported"
    # 2. the same SKU with different values: no way to know which one is right
    counts = df[live].groupby("sku")["row"].transform("count")
    for sku, grp in df[live][counts > 1].groupby("sku"):
        rows = ", ".join(str(r) for r in grp["row"])
        prices = " vs ".join(f"${parse_money(w):.2f}" if parse_money(w) is not None else "blank" for w in grp["wholesale"])
        hold(grp.index, f"SKU {sku} appears on rows {rows} with different values (wholesale {prices}). Which one is right?")

    # 3. discontinued
    live = df["fate"] == "imported"
    disc = live & df["status"].str.upper().isin(config.DISCONTINUED)
    df.loc[disc, ["fate", "reason"]] = ["excluded", "Marked discontinued by the supplier"]

    # 4. field by field
    out, http_links = [], {}
    for idx, r in df[df["fate"] == "imported"].iterrows():
        code = r["category"].upper()
        if code not in config.CATEGORIES:
            hold(idx, f"Unknown category '{r['category']}': which product type is it?")
            continue
        color = COLOR_OF.get(r["color"].upper())
        if color is None:
            color = title_case(r["color"].split()) if r["color"] else ""
            note(r, f"Colour '{r['color']}' is not in the colour list", f"Kept as '{color}'", "WARN")
        elif r["color"] != color:
            note(r, f"Colour written as '{r['color']}'", f"Standardised to '{color}'")
        size = SIZE_OF.get(r["size"].upper())
        if size is None:
            size = r["size"]
            note(r, f"Size '{r['size']}' is not in the size list", f"Kept as '{size}'", "WARN")
        elif r["size"] != size:
            note(r, f"Size written as '{r['size']}'", f"Standardised to '{size}'")
        wholesale, retail = parse_money(r["wholesale"]), parse_money(r["retail"])
        priced_by_rule = False
        if retail is None and wholesale is None:
            hold(idx, "No wholesale or retail price: what should it sell for?")
            continue
        if retail is None:
            retail = math.ceil(wholesale * config.MARKUP) - 0.01
            priced_by_rule = True
            note(r, "No retail price (MSRP) in the file", f"Priced at ${retail:.2f} by the markup rule "
                 f"(wholesale ${wholesale:.2f} x {config.MARKUP:g}): please confirm", "WARN")
        if wholesale is not None and retail < wholesale:
            note(r, f"Retail ${retail:.2f} is below wholesale ${wholesale:.2f}", "Kept, flagged for review", "WARN")
        barcode, bstatus = parse_barcode(r["barcode"])
        if bstatus == "restored_zero":
            note(r, f"Barcode '{text(r['barcode'])}' has 11 digits", f"Leading zero restored: {barcode} (check digit valid)")
        elif bstatus == "scientific":
            note(r, f"Barcode '{text(r['barcode'])}' was converted to scientific notation by Excel",
                 "Left blank: the last digits are lost; ask the supplier to resend it", "WARN")
        elif bstatus == "bad_check":
            note(r, f"Barcode '{text(r['barcode'])}' fails the check digit", "Left blank: ask the supplier", "WARN")
        elif bstatus == "bad_length":
            note(r, f"Barcode '{text(r['barcode'])}' is not a valid UPC or EAN", "Left blank", "WARN")
        qty, qstatus = parse_qty(r["qty"])
        if qstatus == "at_least":
            note(r, f"Stock given as '{text(r['qty'])}'", f"Imported as {qty}")
        elif qstatus in ("blank", "not_a_number", "negative"):
            note(r, f"Stock given as '{text(r['qty'])}'", "Imported as 0", "WARN")
        grams = parse_weight(r["weight"])
        if grams is None:
            grams = 0
            note(r, f"Weight '{text(r['weight'])}' not understood", "Imported as 0 g: shipping rates need it", "WARN")
        images, dropped = [], []
        for u in (r["image1"], r["image2"], r["image3"]):
            if not u:
                continue
            (images if u.lower().startswith("https://") else dropped).append(u)
        for u in dropped:
            http_links.setdefault(r["style"], (int(r["row"]), {}))[1].setdefault(u, None)
        ptype, category, _path = config.CATEGORIES[code]
        out.append({
            "row": int(r["row"]), "sku": r["sku"], "style": r["style"], "description": r["description"],
            "color": color, "size": size, "wholesale": wholesale, "price": round(retail, 2),
            "priced_by_rule": priced_by_rule, "barcode": barcode, "qty": qty, "grams": grams,
            "type": ptype, "category": category, "material": r["material"],
            "features": [f.strip() for f in r["features"].split(";") if f.strip()],
            "variant_image": r["image1"] if r["image1"].lower().startswith("https://") else "",
            "images": images, "status_raw": r["status"],
        })
    variants = pd.DataFrame(out)
    for style, (row, links) in http_links.items():
        log.append({"row": row, "sku": style, "issue": f"{len(links)} image links for {style} start with http://, "
                    f"for example {next(iter(links))}", "action": "Left out: Shopify only downloads public HTTPS "
                    "images. Ask the supplier for HTTPS links", "severity": "WARN"})

    # 5. two SKUs for the same product, colour and size: Shopify allows one variant per combination
    if not variants.empty:
        key = variants.groupby(["style", "color", "size"])["sku"].transform("count")
        for (style, color, size), grp in variants[key > 1].groupby(["style", "color", "size"]):
            skus = " and ".join(grp["sku"])
            reason = f"{skus} are both {style} in {color}, size {size}. Which SKU should the store use?"
            hold(df.index[df["row"].isin(grp["row"])], reason)
        variants = variants[key == 1].reset_index(drop=True)

    # 6. titles and handles, one per style
    titles = {}
    for style, grp in variants.groupby("style", sort=False):
        titles[style] = style_title(list(grp["description"]), list(grp["color"]), list(grp["size"]))
    handles, seen = {}, set()
    for style, title in titles.items():
        h = handleize(title) or handleize(style)
        if h in seen:
            h = f"{h}-{handleize(style)}"
        seen.add(h)
        handles[style] = h
    variants["title"] = variants["style"].map(titles)
    variants["handle"] = variants["style"].map(handles)
    for style, grp in variants.groupby("style"):
        if not any(grp["images"].map(len)):
            r = grp.iloc[0]
            log.append({"row": int(r["row"]), "sku": style, "issue": f"No images for {titles[style]}",
                        "action": "Imported without photos (status draft): send image links or files", "severity": "WARN"})
    variants["size_rank"] = variants["size"].map(lambda s: SIZE_ORDER.get(s, 99))
    first_color = {k: i for i, k in enumerate(dict.fromkeys(zip(variants["style"], variants["color"])))}
    variants["color_rank"] = [first_color[(s, c)] for s, c in zip(variants["style"], variants["color"])]
    variants = variants.sort_values(["style", "color_rank", "size_rank"]).reset_index(drop=True)
    rows = df[["row", "sku", "fate", "reason"]].reset_index(drop=True)
    return variants, rows, pd.DataFrame(log, columns=["row", "sku", "issue", "action", "severity"])
