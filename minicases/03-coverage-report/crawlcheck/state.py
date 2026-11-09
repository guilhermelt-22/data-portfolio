"""The checkpoint: one SQLite file with every URL, its outcome, every record and every run.

Each page is finished in one transaction (its outcome, its record, the request log and the run counters),
so a crash at any moment leaves the file consistent: a page is either fully done or still pending.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS urls (
    url         TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,                     -- listing | book | category | home | offsite | other
    status      TEXT NOT NULL DEFAULT 'pending',   -- pending | collected | failed | excluded
    reason      TEXT,
    http_status INTEGER,
    attempts    INTEGER NOT NULL DEFAULT 0,
    found_on    TEXT,                              -- first page that linked to it
    links_in    INTEGER NOT NULL DEFAULT 1,        -- how many links pointed to it
    seq         INTEGER NOT NULL,                  -- discovery order
    found_run   INTEGER,
    done_run    INTEGER,
    done_at     TEXT
);
CREATE TABLE IF NOT EXISTS books (
    url          TEXT PRIMARY KEY REFERENCES urls(url),
    upc          TEXT NOT NULL UNIQUE,
    title        TEXT NOT NULL,
    category     TEXT,
    price_cents  INTEGER NOT NULL,
    stock        INTEGER,
    rating       INTEGER,
    reviews      INTEGER,
    run_id       INTEGER NOT NULL,
    collected_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    run_id        INTEGER PRIMARY KEY,
    started_at    TEXT NOT NULL,
    last_seen_at  TEXT NOT NULL,
    status        TEXT NOT NULL,                   -- running | completed | interrupted
    requests      INTEGER NOT NULL DEFAULT 0,
    pages_done    INTEGER NOT NULL DEFAULT 0,
    records_added INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS fetches (url TEXT NOT NULL, run_id INTEGER NOT NULL, at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: Path | str) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=30)
    con.row_factory = sqlite3.Row
    # rollback journal, not WAL: crash-safe, and no shared-memory file for a sync client to lock
    con.execute("PRAGMA journal_mode=DELETE")
    con.execute("PRAGMA synchronous=FULL")
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(SCHEMA)
    return con


def start_run(con: sqlite3.Connection) -> int:
    """Open a run. A previous run still marked 'running' was killed: say so."""
    with con:
        con.execute("UPDATE runs SET status = 'interrupted' WHERE status = 'running'")
        cur = con.execute("INSERT INTO runs (started_at, last_seen_at, status) VALUES (?, ?, 'running')",
                          (now(), now()))
    return cur.lastrowid


def finish_run(con: sqlite3.Connection, run_id: int) -> None:
    with con:
        con.execute("UPDATE runs SET status = 'completed', last_seen_at = ? WHERE run_id = ?", (now(), run_id))


def set_meta(con: sqlite3.Connection, key: str, value) -> None:
    con.execute("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value)))


def get_meta(con: sqlite3.Connection, key: str, default=None):
    row = con.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def add_url(con: sqlite3.Connection, url: str, kind: str, found_on: str, run_id: int,
            excluded_reason: str | None = None, count_link: bool = True) -> None:
    """Record a discovered URL once; later links to it only raise its link count."""
    if not count_link and con.execute("SELECT 1 FROM urls WHERE url = ?", (url,)).fetchone():
        return
    seq = con.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM urls").fetchone()[0]
    if excluded_reason:
        con.execute("""INSERT INTO urls (url, kind, status, reason, found_on, seq, found_run, done_run, done_at)
                       VALUES (?, ?, 'excluded', ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(url) DO UPDATE SET links_in = links_in + 1""",
                    (url, kind, excluded_reason, found_on, seq, run_id, run_id, now()))
    else:
        con.execute("""INSERT INTO urls (url, kind, found_on, seq, found_run) VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(url) DO UPDATE SET links_in = links_in + 1""",
                    (url, kind, found_on, seq, run_id))


def close_url(con: sqlite3.Connection, url: str, status: str, run_id: int, reason: str | None = None,
              http_status: int | None = None, attempts: int = 0) -> None:
    con.execute("""UPDATE urls SET status = ?, reason = ?, http_status = ?, attempts = attempts + ?,
                   done_run = ?, done_at = ? WHERE url = ?""",
                (status, reason, http_status, attempts, run_id, now(), url))


def bump_run(con: sqlite3.Connection, run_id: int, requests: int, records: int) -> None:
    con.execute("""UPDATE runs SET requests = requests + ?, pages_done = pages_done + 1,
                   records_added = records_added + ?, last_seen_at = ? WHERE run_id = ?""",
                (requests, records, now(), run_id))
