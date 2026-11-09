"""One crawl run: resume from the checkpoint, work through every pending URL, write the coverage report.

Usage (from the mini-case folder):
    python -m crawlcheck.run                  # start, or resume where the last run stopped
    python -m crawlcheck.run --inject         # with the two demo failures (dead link, template change)
    python -m crawlcheck.run --retry-failed   # request failed URLs again
    python -m crawlcheck.run --fresh          # forget the checkpoint and start over
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

from . import state
from .config import DB_PATH, OUT
from .crawl import crawl, retry_failed
from .polite import PoliteClient
from .report import write_report


def main(argv: list[str] | None = None) -> dict | None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--inject", action="store_true", help="inject the two demo failures")
    ap.add_argument("--retry-failed", action="store_true", help="put failed URLs back in the queue")
    ap.add_argument("--fresh", action="store_true", help="delete the checkpoint and start over")
    ap.add_argument("--no-report", action="store_true", help="crawl only")
    ap.add_argument("--db", type=Path, default=DB_PATH)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)

    if args.fresh:
        for suffix in ("", "-wal", "-shm"):
            Path(f"{args.db}{suffix}").unlink(missing_ok=True)
    con = state.connect(args.db)
    run_id = state.start_run(con)
    if args.retry_failed:
        print(f"{retry_failed(con)} failed URLs queued again")
    pending = con.execute("SELECT COUNT(*) FROM urls WHERE status = 'pending'").fetchone()[0]
    done = con.execute("SELECT COUNT(*) FROM urls WHERE status != 'pending'").fetchone()[0]
    print(f"run {run_id}: " + (f"resuming: {done} URLs already done, {pending} pending" if done else "starting"))
    t0 = time.monotonic()
    crawl(con, PoliteClient(), run_id, inject=args.inject)
    state.finish_run(con, run_id)
    print(f"run {run_id} finished in {time.monotonic() - t0:.0f} s")
    if args.no_report:
        return None
    s = write_report(con, args.out)
    print(f"{s['discovered']:,} discovered = {s['collected']:,} collected + {s['failed']:,} failed + "
          f"{s['excluded']:,} excluded · records {s['records']:,} · reconciles: {s['reconciles']}")
    print(f"report: {args.out / 'coverage_report.xlsx'}")
    return s


if __name__ == "__main__":
    main()
