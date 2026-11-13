"""Builds two fictitious supplier price lists, laid out the way real ones arrive.

Harrow Peak Wholesale and its products are invented. The October file has title rows, category banners,
footer notes and a set of seeded problems, each counted in PLANTED so the tests can check that every one is
caught. The November file renames and reorders the columns and changes prices, stock and the range, as the
next month's list from the same supplier would.

    python -m vendorfeed.generate
"""
from __future__ import annotations

import math
import random
from pathlib import Path

import openpyxl

HERE = Path(__file__).resolve().parent.parent
INPUT = HERE / "input"
CDN = "https://guilhermelt-22.github.io/data-portfolio/minicases/06-supplier-file-to-shopify/img/products"

# code, banner, names, sizes (canonical), colours per style, wholesale range, weight (unit, low, high)
SPEC = [
    ("SOX", "SOCKS", ["Merino Hiker Sock", "Trail Runner Sock", "Alpine Crew Sock", "Lightweight Ankle Sock",
                      "Expedition Boot Sock", "Cushioned Quarter Sock"], ["S", "M", "L", "XL"], (2, 3), (6, 9), ("oz", 2.4, 4.0)),
    ("TEE", "T-SHIRTS", ["Ridge Logo Tee", "Summit Organic Tee", "Basecamp Pocket Tee", "Trailhead Graphic Tee",
                         "Everyday Crew Tee", "Sun Shield Tee"], ["S", "M", "L", "XL", "XXL"], (3, 3), (9, 13), ("oz", 5.0, 7.0)),
    ("HOOD", "HOODIES", ["Canyon Fleece Hoodie", "Glacier Pullover Hoodie", "Timberline Zip Hoodie",
                         "Fireside Heavyweight Hoodie", "Switchback Tech Hoodie"], ["S", "M", "L", "XL", "XXL"], (2, 3), (24, 32), ("lb", 1.0, 1.4)),
    ("BASE", "BASE LAYERS", ["Merino 200 Base Layer Top", "Thermal Crew Base Layer", "Midweight Zip Neck Base Layer",
                             "Lightweight Base Layer Tee"], ["S", "M", "L", "XL"], (2, 2), (28, 36), ("oz", 6.0, 9.0)),
    ("HAT", "BEANIES", ["Ribbed Watch Beanie", "Pom Trail Beanie", "Merino Cuff Beanie", "Reflective Night Beanie",
                        "Chunky Knit Beanie"], ["One Size"], (3, 4), (7, 10), ("g", 80, 120)),
    ("GLV", "GLOVES", ["Windstop Fleece Glove", "Touchscreen Liner Glove", "Insulated Ski Glove", "Grip Trail Glove"],
     ["S", "M", "L", "XL"], (1, 2), (10, 18), ("g", 60, 140)),
    ("PACK", "BACKPACKS", ["Daypack Classic", "Ridgeline Hiking Pack", "Commuter Roll-Top Pack", "Summit Lite Pack"],
     ["20 L", "30 L"], (2, 2), (35, 55), ("lb", 0.9, 1.6)),
    ("BTL", "BOTTLES", ["Insulated Steel Bottle", "Trail Flask Bottle", "Wide Mouth Bottle", "Collapsible Silicone Bottle"],
     ["500 ml", "750 ml", "1 L"], (2, 3), (9, 15), ("kg", 0.25, 0.42)),
]
NEW_IN_NOVEMBER = [
    ("GLV", "Heated Expedition Mitt", ["S", "M", "L", "XL"], ["Black", "Olive"], 34.0),
    ("HAT", "Trapper Fleece Hat", ["One Size"], ["Charcoal", "Rust", "Navy"], 12.0),
    ("SOX", "Ultralight Liner Sock", ["S", "M", "L", "XL"], ["Black", "Sand"], 5.5),
]
COLOR_POOL = ["Black", "Navy", "Charcoal", "Heather Grey", "Forest Green", "Olive", "Rust", "Ochre", "Sand",
              "Slate Blue", "White", "Red"]
CODE = {"Black": "BLK", "Navy": "NVY", "Charcoal": "CHR", "Heather Grey": "HGR", "Forest Green": "FGN",
        "Olive": "OLV", "Rust": "RST", "Ochre": "OCH", "Sand": "SND", "Slate Blue": "SLB", "White": "WHT", "Red": "RED"}
SPELL_COLOR = {"Black": ["BLACK", "Black", "blk", "BLK "], "Navy": ["NAVY", "navy", "NVY", "Navy "],
               "Charcoal": ["CHARCOAL", "Char", "charcoal"], "Heather Grey": ["HEATHER GREY", "Heather Gray", "HTHR GREY"],
               "Forest Green": ["FOREST GREEN", "Forest", "FGRN"], "Olive": ["OLIVE", "olive", "OLV"],
               "Rust": ["RUST", "Rust", "rst"], "Ochre": ["OCHRE", "Ochre"], "Sand": ["SAND", "sand", "SND"],
               "Slate Blue": ["SLATE BLUE", "Slate", "SLT BLU"], "White": ["WHITE", "wht"], "Red": ["RED", "Red"]}
SPELL_SIZE = {"S": ["S", "Small", "SM"], "M": ["M", "Medium", "MED"], "L": ["L", "Large", "LG", "lrg"],
              "XL": ["XL", "X-Large", "xl"], "XXL": ["XXL", "2XL"], "One Size": ["OS", "One Size", "O/S"],
              "500 ml": ["500ml", "500 ML"], "750 ml": ["750ml", "750 ML"], "1 L": ["1L", "1000ml"],
              "20 L": ["20L", "20 Ltr"], "30 L": ["30L", "30 Ltr"]}
SIZE_CODE = {"One Size": "OS", "500 ml": "500", "750 ml": "750", "1 L": "1L", "20 L": "20L", "30 L": "30L"}
MATERIAL = {"SOX": "68% merino wool, 30% nylon, 2% elastane", "TEE": "100% organic cotton",
            "HOOD": "80% cotton, 20% recycled polyester fleece", "BASE": "100% merino wool, 200 g/m2",
            "HAT": "100% acrylic rib knit", "GLV": "Polyester fleece with silicone grip", "PACK": "600D recycled polyester",
            "BTL": "18/8 stainless steel"}
FEATURES = {"SOX": ["Cushioned sole for long days on the trail", "Reinforced heel and toe", "Arch support band"],
            "TEE": ["Pre-shrunk jersey", "Taped neck seam", "Relaxed fit"],
            "HOOD": ["Brushed fleece lining", "Kangaroo pocket", "Ribbed cuffs and hem"],
            "BASE": ["Flatlock seams that do not rub", "Naturally odour resistant", "Warm when damp"],
            "HAT": ["Double-layer cuff", "Stretches to fit", "Soft against the skin"],
            "GLV": ["Touchscreen fingertips", "Elastic wrist", "Packs flat"],
            "PACK": ["Padded laptop sleeve", "Water-resistant base", "Side bottle pockets"],
            "BTL": ["Keeps drinks cold for 24 hours", "Leak-proof lid", "Fits most cup holders"]}

# What the October file contains on purpose. The tests compare the pipeline's findings to these numbers.
PLANTED = {
    "title_rows": 2, "banner_rows": 8, "note_rows": 2,
    "exact_duplicates": 6,
    "conflicting_skus": 2,            # same SKU twice with different wholesale prices (4 rows)
    "duplicate_option_pairs": 1,      # two SKUs for the same style, colour and size (2 rows)
    "barcode_scientific": 5,          # "8.40123E+11": digits lost when the file went through Excel
    "barcode_lost_zero": 7,           # 11 digits: the leading zero was dropped, recoverable
    "barcode_bad_check_digit": 3,
    "styles_without_retail": 3,       # priced by the markup rule, flagged for review
    "rows_without_any_price": 2,
    "discontinued_rows": None,        # filled in when the file is built (one whole style + 3 single rows)
    "http_image_styles": 2,
    "styles_without_images": 1,
    "qty_text": 9,                    # "50+", "-", "N/A"
}


def upc_check_digit(first11: str) -> int:
    odd = sum(int(d) for d in first11[0::2])
    even = sum(int(d) for d in first11[1::2])
    return (10 - (odd * 3 + even) % 10) % 10


def make_upc(rng: random.Random, leading_zero: bool) -> str:
    body = ("0" if leading_zero else "8") + "".join(str(rng.randint(0, 9)) for _ in range(10))
    return body + str(upc_check_digit(body))


def retail_from(wholesale: float, factor: float) -> float:
    return math.ceil(wholesale * factor) - 0.01


def build_catalog(rng: random.Random) -> list[dict]:
    """The supplier's real range (clean), one dict per variant. Messiness is added when it is written."""
    rows, n = [], 1001
    for code, banner, names, sizes, ncol, wrange, (wunit, wlo, whi) in SPEC:
        for name in names:
            style = f"HP-{n}"
            n += 1
            colors = rng.sample(COLOR_POOL, rng.randint(*ncol))
            wholesale = round(rng.uniform(*wrange) * 2) / 2
            retail = retail_from(wholesale, rng.choice([2.0, 2.2, 2.4]))
            weight = rng.uniform(wlo, whi)
            for color in colors:
                for size in sizes:
                    rows.append({
                        "code": code, "banner": banner, "name": name, "style": style, "color": color, "size": size,
                        "sku": f"{style}-{CODE[color]}-{SIZE_CODE.get(size, size)}",
                        "wholesale": wholesale, "retail": retail, "weight": weight, "wunit": wunit,
                        "upc": make_upc(rng, leading_zero=rng.random() < 0.3), "qty": rng.choice([0, 6, 12, 18, 24, 36, 48, 60, 72]),
                        "img1": f"{CDN}/{style}-{CODE[color]}.png", "img2": f"{CDN}/{style}-detail-1.png",
                        "img3": f"{CDN}/{style}-detail-2.png", "status": "Active",
                    })
    return rows


def fmt_weight(rng: random.Random, value: float, unit: str) -> str:
    if unit == "g":
        return rng.choice([f"{value:.0f} g", f"{value:.0f}g"])
    if unit == "kg":
        return f"{value:.2f} kg"
    if unit == "lb":
        return rng.choice([f"{value:.1f} lb", f"{value:.1f} lbs"])
    return f"{value:.1f} oz"


def messy_row(rng: random.Random, r: dict) -> dict:
    """One variant as the supplier types it: ALL CAPS descriptions, spellings that vary, prices as text."""
    color_raw = rng.choice(SPELL_COLOR[r["color"]])
    size_raw = rng.choice(SPELL_SIZE[r["size"]])
    upc = r["upc"]
    return {
        "Item #": r["sku"], "Style #": r["style"],
        "Description": f"{r['name'].upper()} {color_raw.strip().upper()} {size_raw.upper()}",
        "Colour": color_raw, "Size": size_raw,
        "Wholesale": rng.choice([f"${r['wholesale']:.2f}", r["wholesale"]]),
        "MSRP": "" if r["retail"] is None else rng.choice([r["retail"], f"${r['retail']:.2f}"]),
        "UPC": upc if upc.startswith("0") else int(upc),
        "Avail.": r["qty"], "Wt": fmt_weight(rng, r["weight"], r["wunit"]),
        "Category": rng.choice([r["code"], r["code"].lower(), f" {r['code']}"]),
        "Material": MATERIAL[r["code"]], "Features": "; ".join(FEATURES[r["code"]]),
        "Img 1": r["img1"], "Img 2": r["img2"], "Img 3": r["img3"], "Status": r["status"],
    }


def plant_october(rng: random.Random, catalog: list[dict]) -> list[dict]:
    styles = sorted({r["style"] for r in catalog})
    by_style = {s: [r for r in catalog if r["style"] == s] for s in styles}
    pick = rng.sample(styles, 9)
    no_retail, http_img, no_img, disc_style = pick[:3], pick[3:5], pick[5], pick[6]
    for s in no_retail:
        for r in by_style[s]:
            r["retail"] = None
    for s in http_img:
        for r in by_style[s]:
            for k in ("img1", "img2", "img3"):
                r[k] = r[k].replace("https://", "http://")
    for r in by_style[no_img]:
        r["img1"] = r["img2"] = r["img3"] = ""
    for r in by_style[disc_style]:
        r["status"] = "Disc."
    others = [r for r in catalog if r["style"] not in pick]
    singles = rng.sample(others, 3 + 2 + 15 + 9)
    for r in singles[:3]:
        r["status"] = "Disc."
    for r in singles[3:5]:
        r["wholesale_blank"] = True
        r["retail"] = None
    PLANTED["discontinued_rows"] = len(by_style[disc_style]) + 3
    # barcodes: 5 scientific, 7 lost zero, 3 bad check digit
    bc = singles[5:20]
    for r in bc[:5]:
        r["upc_raw"] = f"{int(r['upc']) / 1e11:.5f}E+11" if not r["upc"].startswith("0") else None
        if r["upc_raw"] is None:
            r["upc"] = "8" + r["upc"][1:-1]
            r["upc"] += str(upc_check_digit(r["upc"]))
            r["upc_raw"] = f"{int(r['upc']) / 1e11:.5f}E+11"
    for r in bc[5:12]:
        if not r["upc"].startswith("0"):
            r["upc"] = "0" + r["upc"][1:-1]
            r["upc"] += str(upc_check_digit(r["upc"]))
        r["upc_raw"] = int(r["upc"])                      # Excel drops the zero
    for r in bc[12:15]:
        bad = (int(r["upc"][-1]) + 3) % 10
        r["upc_raw"] = r["upc"][:-1] + str(bad)
        if not r["upc_raw"].startswith("0"):
            r["upc_raw"] = int(r["upc_raw"])
    for r in singles[20:29]:
        r["qty_raw"] = rng.choice(["50+", "50+", "-", "N/A"])
    return catalog


def write_sheet(path: Path, top: list[list], header: list[str], body: list[list], bottom: list[list], sheet: str) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet
    for row in top:
        ws.append(row)
    ws.append(header)
    for row in body:
        ws.append(row)
    for row in bottom:
        ws.append(row)
    for cell in ws[len(top) + 1]:
        cell.font = openpyxl.styles.Font(bold=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def october(rng: random.Random, catalog: list[dict], folder: Path = INPUT) -> Path:
    header = list(messy_row(rng, catalog[0]).keys())
    body, banner = [], None
    plain = [i for i, r in enumerate(catalog) if r["status"] == "Active" and r["retail"] is not None
             and not ({"upc_raw", "qty_raw", "wholesale_blank"} & r.keys()) and r["img1"].startswith("https")]
    dup_targets = set(rng.sample(plain, 6 + 2))
    exact, conflict = sorted(dup_targets)[:6], sorted(dup_targets)[6:]
    combo_done = False
    for i, r in enumerate(catalog):
        if r["banner"] != banner:
            banner = r["banner"]
            body.append([f"--- {banner} ---"] + [None] * (len(header) - 1))
        row = messy_row(rng, r)
        if "upc_raw" in r:
            row["UPC"] = r["upc_raw"]
        if "qty_raw" in r:
            row["Avail."] = r["qty_raw"]
        if r.get("wholesale_blank"):
            row["Wholesale"] = ""
        values = list(row.values())
        body.append(values)
        if i in exact:
            body.append(list(values))
        if i in conflict:
            twin = dict(row)
            twin["Wholesale"] = round(float(str(row["Wholesale"]).lstrip("$")) + 1.25, 2)
            body.append(list(twin.values()))
        if not combo_done and r["code"] == "TEE" and r["size"] == "M" and r["status"] == "Active" and i not in dup_targets \
                and "upc_raw" not in r and "qty_raw" not in r:
            twin = dict(row)
            twin["Item #"] = r["sku"].rsplit("-", 1)[0] + "-MD"
            twin["UPC"] = int(make_upc(rng, leading_zero=False))
            body.append(list(twin.values()))
            combo_done = True
    top = [["HARROW PEAK WHOLESALE"], ["Fall / Winter 2026 price list. Prices in USD, subject to change."], []]
    bottom = [[], ["Prices exclude shipping. Minimum order 12 units per style."],
              ["Questions about this list: contact your account manager."]]
    path = folder / "harrow_peak_fw26_october.xlsx"
    write_sheet(path, top, header, body, bottom, "Price list")
    return path


def november(rng: random.Random, catalog: list[dict], folder: Path = INPUT) -> tuple[Path, dict]:
    """Next month's list: new column names and order, price changes, new styles, styles dropped."""
    nov = [dict(r) for r in catalog if r["status"] == "Active" and not r.get("wholesale_blank")]
    for r in nov:
        r.pop("upc_raw", None)
        r.pop("qty_raw", None)
        if r["retail"] is None:
            r["retail"] = retail_from(r["wholesale"], 2.0)
        r["img1"], r["img2"], r["img3"] = (u.replace("http://", "https://") for u in (r["img1"], r["img2"], r["img3"]))
    styles = sorted({r["style"] for r in nov})
    dropped = rng.sample(styles, 2)
    rest = [s for s in styles if s not in dropped]
    disc, raised, gains_color = rest[0], rng.sample(rest[1:], 4), rest[-1]
    nov = [r for r in nov if r["style"] not in dropped]
    for r in nov:
        if r["style"] == disc:
            r["status"] = "Disc."
        if r["style"] in raised:
            r["wholesale"] = round(r["wholesale"] * 1.08, 2)
            r["retail"] = retail_from(r["wholesale"], 2.2)
    singles = rng.sample([r for r in nov if r["style"] not in raised and r["style"] != disc], 10)
    for r in singles:
        r["retail"] = round(r["retail"] - rng.choice([2.0, 3.0, -2.0]), 2)
    for r in nov:
        r["qty"] = rng.choice([0, 6, 12, 18, 24, 36, 48, 60, 72])
    # a new colour for one style
    base = [r for r in nov if r["style"] == gains_color]
    have = {r["color"] for r in base}
    new_color = next(c for c in COLOR_POOL if c not in have)
    added_variants = 0
    for size in dict.fromkeys(r["size"] for r in base):
        t = dict(base[0])
        t.update(color=new_color, size=size, sku=f"{t['style']}-{CODE[new_color]}-{SIZE_CODE.get(size, size)}",
                 upc=make_upc(rng, False), img1=f"{CDN}/{t['style']}-{CODE[new_color]}.png", qty=24)
        nov.append(t)
        added_variants += 1
    # new styles
    n = 1001 + sum(len(s[2]) for s in SPEC)
    new_rows = 0
    for code, name, sizes, colors, wholesale in NEW_IN_NOVEMBER:
        style = f"HP-{n}"
        n += 1
        spec = next(s for s in SPEC if s[0] == code)
        for color in colors:
            for size in sizes:
                nov.append({"code": code, "banner": spec[1], "name": name, "style": style, "color": color, "size": size,
                            "sku": f"{style}-{CODE[color]}-{SIZE_CODE.get(size, size)}", "wholesale": wholesale,
                            "retail": retail_from(wholesale, 2.2), "weight": (spec[6][1] + spec[6][2]) / 2, "wunit": spec[6][0],
                            "upc": make_upc(rng, False), "qty": 36, "img1": f"{CDN}/{style}-{CODE[color]}.png",
                            "img2": f"{CDN}/{style}-detail-1.png", "img3": "", "status": "NEW"})
                new_rows += 1
    nov.sort(key=lambda r: (r["code"], r["style"], r["color"]))
    header = ["SKU", "Style", "Product Name", "Color", "Size", "Retail", "Wholesale Price", "Qty", "Barcode",
              "Weight", "Category", "Material", "Features", "Image 1", "Image 2", "Image 3", "Status"]
    body = []
    for r in nov:
        m = messy_row(rng, r)
        body.append([m["Item #"], m["Style #"], m["Description"], m["Colour"], m["Size"], m["MSRP"], m["Wholesale"],
                     m["Avail."], m["UPC"], m["Wt"], m["Category"], m["Material"], m["Features"], m["Img 1"],
                     m["Img 2"], m["Img 3"], m["Status"]])
    top = [["Harrow Peak Wholesale - price list updated 1 November 2026"], []]
    path = folder / "harrow_peak_fw26_november.xlsx"
    write_sheet(path, top, header, body, [], "Products")
    expected = {"dropped_styles": dropped, "discontinued_style": disc, "raised_styles": raised,
                "retail_changed_singles": [r["sku"] for r in singles], "new_color_style": gains_color,
                "new_color_variants": added_variants, "new_style_rows": new_rows}
    return path, expected


def build(seed: int = 2026, folder: Path = INPUT) -> tuple[Path, Path, dict]:
    rng = random.Random(seed)
    catalog = plant_october(rng, build_catalog(rng))
    oct_path = october(rng, catalog, folder)
    nov_path, expected = november(rng, catalog, folder)
    return oct_path, nov_path, expected


if __name__ == "__main__":
    o, n, _ = build()
    print("wrote", o.name, "and", n.name)
