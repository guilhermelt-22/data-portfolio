"""Builds the two fictitious price lists and runs both months: the first import, then the monthly update.

    python -m vendorfeed.demo
"""
from __future__ import annotations

from pathlib import Path

from . import generate, report
from .run import process

HERE = Path(__file__).resolve().parent.parent


def main() -> None:
    oct_path, nov_path, _ = generate.build()
    first = process(oct_path, HERE / "output" / "october")
    r = first["result"]
    fates = first["rows"]["fate"].value_counts().to_dict()
    print(f"October: {first['kinds'].get('product')} product rows -> {first['variants']['style'].nunique()} products, "
          f"{len(first['variants'])} variants, {len(first['shop'])} CSV rows in {first['seconds']:.2f} s ({r['overall']})")
    print(f"  fates: {fates}")
    for name, res, detail in r["checks"]:
        print(f"  {res:<5} {name}: {detail}")
    print(report.fix_kinds(first["log"]).to_string(index=False))

    second = process(nov_path, HERE / "output" / "november", previous=HERE / "output" / "october")
    print(f"\nNovember: {second['kinds'].get('product')} product rows in {second['seconds']:.2f} s ({second['result']['overall']})")
    print(report.changes_summary(second["changes"], second["files"]).to_string(index=False))


if __name__ == "__main__":
    main()
