"""Local history in SQLite, updated incrementally: only the days after the last stored date are asked for.

The update re-reads the last stored day as an overlap check: if the ECB ever revised a rate, it is
logged as a revision instead of silently overwritten.
"""
from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .api import fetch_rates

SCHEMA = """
CREATE TABLE IF NOT EXISTS rates (date TEXT NOT NULL, currency TEXT NOT NULL, rate REAL NOT NULL,
                                  PRIMARY KEY (date, currency));
CREATE TABLE IF NOT EXISTS empty_rows (date TEXT NOT NULL, currency TEXT NOT NULL, PRIMARY KEY (date, currency));
CREATE TABLE IF NOT EXISTS revisions (date TEXT, currency TEXT, old_rate REAL, new_rate REAL, run_id INTEGER);
CREATE TABLE IF NOT EXISTS runs (
    run_id INTEGER PRIMARY KEY, at TEXT NOT NULL, mode TEXT NOT NULL, start_period TEXT,
    rows_received INTEGER, duplicates_received INTEGER, rows_new INTEGER, rows_unchanged INTEGER,
    rows_revised INTEGER, days_new INTEGER, first_new TEXT, last_new TEXT, seconds REAL);
"""


def connect(path: Path | str) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    return con


def load(con: sqlite3.Connection) -> tuple[pd.DataFrame, pd.DataFrame]:
    rates = pd.read_sql("SELECT date, currency, rate FROM rates ORDER BY date, currency", con, parse_dates=["date"])
    empty = pd.read_sql("SELECT date, currency FROM empty_rows", con, parse_dates=["date"])
    return rates, empty


def update(con: sqlite3.Connection, currencies=None, fetch: Callable = fetch_rates, **fetch_kwargs) -> dict:
    """Fetch what is new since the last stored day (or everything on the first run) and merge it."""
    last = con.execute("SELECT MAX(date) FROM rates").fetchone()[0]
    t0 = time.monotonic()
    df = fetch(currencies, start=last, keep_empty=True, **fetch_kwargs)
    received = len(df)
    dups = int(df.duplicated(["date", "currency"]).sum())
    df = df.drop_duplicates(["date", "currency"], keep="last")
    df = df.assign(date=df["date"].dt.strftime("%Y-%m-%d"))
    valid, empty = df.dropna(subset=["rate"]), df[df["rate"].isna()]

    stored = pd.read_sql("SELECT date, currency, rate AS old FROM rates WHERE date >= ?", con,
                         params=(valid["date"].min() if len(valid) else "9999",))
    merged = valid.merge(stored, on=["date", "currency"], how="left")
    new = merged[merged["old"].isna()]
    revised = merged[merged["old"].notna() & (merged["old"] != merged["rate"])]
    with con:
        cur = con.execute("INSERT INTO runs (at, mode, start_period) VALUES (?, ?, ?)",
                          (datetime.now(timezone.utc).isoformat(timespec="seconds"),
                           "incremental" if last else "full history", last or "1999-01-04"))
        run_id = cur.lastrowid
        con.executemany("INSERT INTO rates VALUES (?, ?, ?) ON CONFLICT(date, currency) DO UPDATE SET rate = excluded.rate",
                        valid[["date", "currency", "rate"]].itertuples(index=False, name=None))
        con.executemany("INSERT OR IGNORE INTO empty_rows VALUES (?, ?)",
                        empty[["date", "currency"]].itertuples(index=False, name=None))
        con.executemany("INSERT INTO revisions VALUES (?, ?, ?, ?, ?)",
                        [(r.date, r.currency, r.old, r.rate, run_id) for r in revised.itertuples()])
        stats = {
            "run_id": run_id, "mode": "incremental" if last else "full history", "start_period": last,
            "rows_received": received, "duplicates_received": dups, "rows_new": len(new),
            "rows_unchanged": len(merged) - len(new) - len(revised), "rows_revised": len(revised),
            "days_new": int(new["date"].nunique()), "first_new": new["date"].min() if len(new) else None,
            "last_new": new["date"].max() if len(new) else None, "seconds": round(time.monotonic() - t0, 1),
        }
        con.execute("""UPDATE runs SET rows_received = :rows_received, duplicates_received = :duplicates_received,
                       rows_new = :rows_new, rows_unchanged = :rows_unchanged, rows_revised = :rows_revised,
                       days_new = :days_new, first_new = :first_new, last_new = :last_new, seconds = :seconds
                       WHERE run_id = :run_id""", stats)
    return stats
