"""One command per supplier file.

    python -m vendorfeed.run input/harrow_peak_fw26_october.xlsx --out output/october
    python -m vendorfeed.run input/harrow_peak_fw26_november.xlsx --out output/november --previous output/october

The first form writes the full import. With --previous, it also compares the new list with what was
imported last time and writes the three update files.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import pandas as pd

from . import config, report
from .checks import run_checks
from .clean import clean
from .diff import compare, update_files
from .read import read_supplier
from .shopify import build, write_csv

SNAPSHOT = "store_snapshot.json"


def save_snapshot(variants: pd.DataFrame, path: Path) -> None:
    path.write_text(variants.to_json(orient="records", indent=1), encoding="utf-8")


def load_snapshot(path: Path) -> pd.DataFrame:
    return pd.DataFrame(json.loads(path.read_text(encoding="utf-8")))


def process(src: Path, out: Path, previous: Path | None = None, status: str = config.DEFAULT_STATUS) -> dict:
    t0 = time.perf_counter()
    out.mkdir(parents=True, exist_ok=True)
    raw, layout = read_supplier(src)
    kinds = raw["kind"].value_counts().to_dict()
    variants, rows, log = clean(raw)
    shop = build(variants, status=status)
    csv_path = write_csv(shop, out / "shopify_products.csv")
    result = run_checks(shop, csv_path, rows, kinds)
    rows.to_csv(out / "row_by_row.csv", index=False, encoding="utf-8")
    held = rows[rows["fate"] == "held back"]
    held.to_csv(out / "held_back.csv", index=False, encoding="utf-8")
    seconds = time.perf_counter() - t0
    res = {"layout": layout, "kinds": kinds, "variants": variants, "rows": rows, "log": log, "shop": shop,
           "result": result, "seconds": seconds, "csv": csv_path}
    if previous is not None:
        store = load_snapshot(previous / SNAPSHOT)
        changes = compare(store, variants)
        files = update_files(store, variants, changes)
        for name, df in files.items():
            write_csv(df, out / f"{name}.csv")
        res.update(changes=changes, files=files)
        merged = pd.concat([store[~store["style"].isin(set(variants["style"]) | set(changes["archived_styles"]))],
                            variants], ignore_index=True)
        save_snapshot(merged, out / SNAPSHOT)
        report.changes_excel(out / "changes_report.xlsx", src.name, changes, files)
    else:
        save_snapshot(variants, out / SNAPSHOT)
    res["seconds"] = time.perf_counter() - t0
    report.import_excel(out / "import_report.xlsx", src.name, result, rows, log, variants, status)
    report.import_html(out / "import_report.html", src.name, result, rows, log, variants, kinds, res["seconds"])
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description="Supplier price list to Shopify product CSV")
    ap.add_argument("source", type=Path)
    ap.add_argument("--out", type=Path, default=Path("output"))
    ap.add_argument("--previous", type=Path, help="output folder of the last import, to write update files")
    ap.add_argument("--status", default=config.DEFAULT_STATUS, choices=["draft", "active"])
    a = ap.parse_args()
    res = process(a.source, a.out, a.previous, a.status)
    r = res["result"]
    print(f"{r['overall']}: {res['variants']['style'].nunique()} products, {len(res['variants'])} variants "
          f"in {res['seconds']:.1f} s -> {res['csv']}")
    for name, result, detail in r["checks"]:
        print(f"  {result:<5} {name}: {detail}")


if __name__ == "__main__":
    main()
