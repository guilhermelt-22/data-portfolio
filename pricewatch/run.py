"""One monitoring run: collect -> store -> detect changes -> check quality -> report.

Usage:
    python -m pricewatch.run                      # live run of every store, appended to the history
    python -m pricewatch.run --stores books       # one store
    python -m pricewatch.run --max-pages 2        # quick check (pages not loaded count as not loaded)
    python -m pricewatch.run --replay 3           # re-parse the archived HTML of run 3, no network

Schedule it with cron or Windows Task Scheduler (daily, for example); each run is kept.
"""
from __future__ import annotations

import argparse
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from . import store as db
from .changes import coverage_by_category, detect_changes
from .collect import Collected, collect_live, collect_replay
from .config import DB_PATH, STORES
from .quality import run_checks, status
from .report import write_report


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def process_run(con: sqlite3.Connection, run_id: int, collected: dict[str, Collected]) -> dict[str, dict]:
    """Store a collected run and derive its changes and quality checks. Safe to call twice for one run."""
    summary = {}
    for store_key, run in collected.items():
        kept, duplicates = db.dedupe(run.items)
        prev_run = db.previous_run(con, store_key, run_id)
        previous = db.previous_state(con, store_key, run_id)
        prev_count = con.execute("SELECT COUNT(*) FROM observations WHERE run_id = ? AND store = ?",
                                 (prev_run, store_key)).fetchone()[0] if prev_run else None
        changes = detect_changes(store_key, previous, kept, coverage_by_category(run.pages))
        checks = run_checks(store_key, run.pages, kept, duplicates, prev_count, changes)

        db.save_pages(con, run_id, run.pages)
        db.save_items(con, run_id, kept)
        db.replace_rows(con, "changes", run_id, store_key,
                        [(run_id, c.store, c.item_id, c.change, c.old_value, c.new_value, c.pct) for c in changes])
        db.replace_rows(con, "quality", run_id, store_key,
                        [(run_id, c.store, c.name, c.severity, c.count, c.detail) for c in checks])
        con.commit()
        summary[store_key] = {
            "pages": f"{sum(p.ok for p in run.pages)}/{len(run.pages)}", "products": len(kept),
            "changes": len(changes), "quality": status(checks),
        }
    return summary


def print_summary(run_id: int, summary: dict[str, dict], seconds: float, paths: dict[str, Path]) -> None:
    print(f"\nRun #{run_id} done in {seconds:.0f} s")
    for key, s in summary.items():
        print(f"  {STORES[key].name:<24} pages {s['pages']:>7}   products {s['products']:>5}   "
              f"changes {s['changes']:>4}   quality {s['quality']}")
    print(f"  Report: {paths['xlsx']}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stores", default=",".join(STORES), help="comma-separated store keys")
    ap.add_argument("--max-pages", type=int, default=None, help="stop after N pages per category")
    ap.add_argument("--replay", type=int, default=None, metavar="RUN_ID", help="re-parse an archived run")
    ap.add_argument("--db", type=Path, default=DB_PATH)
    args = ap.parse_args(argv)

    started = time.monotonic()
    con = db.connect(args.db)
    if args.replay:
        run_id = db.start_run(con, utc_now(), "replay", source_run=args.replay)
        collected = collect_replay(args.replay, db.page_logs(con, args.replay))
    else:
        run_id = db.start_run(con, utc_now(), "live")
        collected = collect_live(run_id, args.stores.split(","), args.max_pages)
    summary = process_run(con, run_id, collected)
    paths = write_report(con, run_id)
    print_summary(run_id, summary, time.monotonic() - started, paths)


if __name__ == "__main__":
    main()
