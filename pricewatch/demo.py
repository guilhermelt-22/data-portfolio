"""The whole case in one command, from an empty database:

    run 1  live crawl of both practice stores (the baseline)
    run 2  simulated next day: run 1's archived pages with seeded changes and one page that fails

Usage:  python -m pricewatch.demo            (about 2 minutes, mostly the polite pause between requests)
        python -m pricewatch.demo --max-pages 3   (quick look)

It deletes and rebuilds output/pricewatch/ (database, archive and report).
"""
from __future__ import annotations

import argparse
import shutil
import time
from datetime import datetime, timedelta

from . import store as db
from .collect import collect_live, collect_replay
from .config import ARCHIVE, DB_PATH, STORES
from .report import write_report
from .run import print_summary, process_run, utc_now
from .simulate import seed_changes


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--max-pages", type=int, default=None)
    args = ap.parse_args(argv)

    DB_PATH.unlink(missing_ok=True)
    shutil.rmtree(ARCHIVE, ignore_errors=True)
    con = db.connect(DB_PATH)

    started = time.monotonic()
    print("Run 1: live crawl of both practice stores (1 s pause between requests)...")
    run1 = db.start_run(con, utc_now(), "live")
    summary = process_run(con, run1, collect_live(run1, list(STORES), args.max_pages))
    print_summary(run1, summary, time.monotonic() - started, write_report(con, run1))

    started = time.monotonic()
    print("\nRun 2: simulated next day (archived pages of run 1 + seeded changes)...")
    t1 = datetime.strptime(con.execute("SELECT started_at FROM runs WHERE run_id = ?", (run1,)).fetchone()[0],
                           "%Y-%m-%dT%H:%M:%SZ")
    run2 = db.start_run(con, (t1 + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"), "simulated", source_run=run1,
                        note="seeded changes for the demo")
    changed, seeded = seed_changes(collect_replay(run1, db.page_logs(con, run1)))
    summary = process_run(con, run2, changed)
    print_summary(run2, summary, time.monotonic() - started, write_report(con, run2))

    found = {(r["store"], r["item_id"], r["change"]) for r in
             con.execute("SELECT store, item_id, change FROM changes WHERE run_id = ?", (run2,))}
    hits = sum(1 for s in seeded if s in found)
    print(f"\nSeeded changes detected: {hits} of {len(seeded)}")


if __name__ == "__main__":
    main()
