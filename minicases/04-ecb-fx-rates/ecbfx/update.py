"""Bring the local history up to date and rewrite the deliverables.

Usage (from the mini-case folder):
    python -m ecbfx.update            # first run: full history since 1999; then only the new days
    python -m ecbfx.update --fresh    # forget the local history and load everything again
"""
from __future__ import annotations

import argparse
from pathlib import Path

from . import store
from .report import write_report

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
DB_PATH = OUT / "rates.sqlite"


def main(argv: list[str] | None = None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fresh", action="store_true")
    ap.add_argument("--db", type=Path, default=DB_PATH)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)
    if args.fresh:
        args.db.unlink(missing_ok=True)
    con = store.connect(args.db)
    s = store.update(con)
    print(f"run {s['run_id']} ({s['mode']}, asked from {s['start_period'] or '1999'}): {s['rows_received']:,} rows "
          f"received, {s['rows_new']:,} new rates for {s['days_new']} new days, {s['rows_revised']} revised, "
          f"{s['seconds']} s")
    result = write_report(con, args.out)
    print(f"checks: {result['overall']}")
    for name, res, detail in result["checks"]:
        print(f"  {res:5} {name}: {detail}")
    con.close()
    return s


if __name__ == "__main__":
    main()
