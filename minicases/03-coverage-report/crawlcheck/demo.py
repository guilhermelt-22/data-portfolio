"""The full demo: a real crawl that is killed halfway, then resumed from the checkpoint.

1. Start from nothing and crawl books.toscrape.com with the two injected failures.
2. When 400 books are saved, kill the process (no clean shutdown, like a crash or a closed laptop).
3. Run again: it resumes from the checkpoint and finishes.
4. Write the coverage report. Takes about 20 minutes, at 1 request per second.

Usage (from the mini-case folder):  python -m crawlcheck.demo
"""
from __future__ import annotations

import sqlite3
import subprocess
import sys
import time

from .config import DB_PATH, ROOT
from . import run

KILL_AFTER_RECORDS = 400


def saved_records() -> int:
    try:
        con = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True, timeout=5)
        try:
            return con.execute("SELECT COUNT(*) FROM books").fetchone()[0]
        finally:
            con.close()
    except sqlite3.Error:
        return 0  # the checkpoint does not exist yet


def main() -> None:
    for suffix in ("", "-wal", "-shm"):
        DB_PATH.with_name(DB_PATH.name + suffix).unlink(missing_ok=True)
    print(f"step 1: crawl until {KILL_AFTER_RECORDS} books are saved, then kill the process")
    proc = subprocess.Popen([sys.executable, "-m", "crawlcheck.run", "--inject", "--no-report"], cwd=ROOT)
    while proc.poll() is None and saved_records() < KILL_AFTER_RECORDS:
        time.sleep(0.5)  # reads the local checkpoint file only; the site is not asked anything
    proc.kill()
    proc.wait()
    print(f"killed with {saved_records()} books saved")
    print("step 2: run again; it resumes from the checkpoint")
    run.main(["--inject"])


if __name__ == "__main__":
    main()
