"""SQLite history. Primary keys make duplicates impossible, and every write is an upsert, so running or
re-processing the same run twice leaves the database exactly as running it once.

runs          one row per run (live, replay or simulated)
pages         every listing page of every run: loaded or failed, with the error
items         one row per product ever seen (first seen, latest title and URL)
observations  one row per product per run in which it was seen: price, stock, rating
changes       what changed in a run versus the last known state
quality       data quality checks per run and store
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .collect import PageLog
from .parse import Item

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id      INTEGER PRIMARY KEY,
    started_at  TEXT NOT NULL,
    mode        TEXT NOT NULL CHECK (mode IN ('live', 'replay', 'simulated')),
    source_run  INTEGER,
    note        TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS pages (
    run_id INTEGER, store TEXT, category TEXT, page INTEGER,
    url TEXT, ok INTEGER, items INTEGER, error TEXT,
    PRIMARY KEY (run_id, store, category, page)
);
CREATE TABLE IF NOT EXISTS items (
    store TEXT, item_id TEXT, category TEXT, title TEXT, url TEXT, first_seen_run INTEGER,
    PRIMARY KEY (store, item_id)
);
CREATE TABLE IF NOT EXISTS observations (
    run_id INTEGER, store TEXT, item_id TEXT,
    price_cents INTEGER, price_text TEXT, in_stock INTEGER, rating INTEGER, reviews INTEGER, source_url TEXT,
    PRIMARY KEY (run_id, store, item_id)
);
CREATE TABLE IF NOT EXISTS changes (
    run_id INTEGER, store TEXT, item_id TEXT, change TEXT,
    old_value TEXT, new_value TEXT, pct REAL,
    PRIMARY KEY (run_id, store, item_id, change)
);
CREATE TABLE IF NOT EXISTS quality (
    run_id INTEGER, store TEXT, check_name TEXT, severity TEXT, count INTEGER, detail TEXT,
    PRIMARY KEY (run_id, store, check_name)
);
"""


@dataclass
class ItemState:
    """What we knew about a product before the current run."""
    item_id: str
    category: str
    title: str
    url: str
    price_cents: int | None
    in_stock: bool | None
    last_seen_run: int
    misses: int     # consecutive earlier runs of this store in which the product was missing
    removed: bool   # its latest lifecycle event is 'removed'


def connect(path: Path | str) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def start_run(con: sqlite3.Connection, started_at: str, mode: str, source_run: int | None = None,
              note: str = "") -> int:
    cur = con.execute("INSERT INTO runs (started_at, mode, source_run, note) VALUES (?, ?, ?, ?)",
                      (started_at, mode, source_run, note))
    con.commit()
    return cur.lastrowid


def dedupe(items: list[Item]) -> tuple[list[Item], int]:
    """Keep the first record of each product: AJAX grids and shifting pages can list one twice."""
    seen: dict[str, Item] = {}
    for item in items:
        seen.setdefault(item.item_id, item)
    return list(seen.values()), len(items) - len(seen)


def save_pages(con: sqlite3.Connection, run_id: int, pages: list[PageLog]) -> None:
    con.executemany("""
        INSERT INTO pages VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (run_id, store, category, page) DO UPDATE SET
            url = excluded.url, ok = excluded.ok, items = excluded.items, error = excluded.error
    """, [(run_id, p.store, p.category, p.page, p.url, int(p.ok), p.items, p.error) for p in pages])


def save_items(con: sqlite3.Connection, run_id: int, items: list[Item]) -> None:
    """items must already be deduplicated."""
    con.executemany("""
        INSERT INTO items VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (store, item_id) DO UPDATE SET
            category = excluded.category, title = excluded.title, url = excluded.url,
            first_seen_run = MIN(first_seen_run, excluded.first_seen_run)
    """, [(i.store, i.item_id, i.category, i.title, i.url, run_id) for i in items])
    con.executemany("""
        INSERT INTO observations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (run_id, store, item_id) DO UPDATE SET
            price_cents = excluded.price_cents, price_text = excluded.price_text, in_stock = excluded.in_stock,
            rating = excluded.rating, reviews = excluded.reviews, source_url = excluded.source_url
    """, [(run_id, i.store, i.item_id, i.price_cents, i.price_text,
           None if i.in_stock is None else int(i.in_stock), i.rating, i.reviews, i.source_url) for i in items])


def replace_rows(con: sqlite3.Connection, table: str, run_id: int, store: str, rows: list[tuple]) -> None:
    """Results derived from a run (changes, quality) are recomputed and replaced, never appended."""
    con.execute(f"DELETE FROM {table} WHERE run_id = ? AND store = ?", (run_id, store))
    if rows:
        marks = ", ".join("?" * len(rows[0]))
        con.executemany(f"INSERT INTO {table} VALUES ({marks})", rows)


def previous_run(con: sqlite3.Connection, store: str, run_id: int) -> int | None:
    row = con.execute("SELECT MAX(run_id) FROM pages WHERE store = ? AND run_id < ?", (store, run_id)).fetchone()
    return row[0]


def previous_state(con: sqlite3.Connection, store: str, run_id: int) -> dict[str, ItemState]:
    """Last known state of every product of a store, using only runs before run_id (so it is idempotent)."""
    rows = con.execute("""
        WITH store_runs AS (SELECT DISTINCT run_id FROM pages WHERE store = :s AND run_id < :r),
        last_obs AS (
            SELECT o.*, ROW_NUMBER() OVER (PARTITION BY item_id ORDER BY run_id DESC) AS rn
            FROM observations o WHERE store = :s AND run_id < :r
        ),
        lifecycle AS (
            SELECT item_id, change, ROW_NUMBER() OVER (PARTITION BY item_id ORDER BY run_id DESC) AS rn
            FROM changes WHERE store = :s AND run_id < :r AND change IN ('new', 'returned', 'removed')
        )
        SELECT i.item_id, i.category, i.title, i.url, l.price_cents, l.in_stock, l.run_id AS last_seen_run,
               (SELECT COUNT(*) FROM store_runs sr WHERE sr.run_id > l.run_id) AS misses,
               COALESCE(lc.change = 'removed', 0) AS removed
        FROM items i
        JOIN last_obs l ON l.item_id = i.item_id AND l.rn = 1
        LEFT JOIN lifecycle lc ON lc.item_id = i.item_id AND lc.rn = 1
        WHERE i.store = :s
    """, {"s": store, "r": run_id}).fetchall()
    return {r["item_id"]: ItemState(
        item_id=r["item_id"], category=r["category"], title=r["title"], url=r["url"],
        price_cents=r["price_cents"], in_stock=None if r["in_stock"] is None else bool(r["in_stock"]),
        last_seen_run=r["last_seen_run"], misses=r["misses"], removed=bool(r["removed"]),
    ) for r in rows}


def page_logs(con: sqlite3.Connection, run_id: int) -> list[PageLog]:
    rows = con.execute("SELECT * FROM pages WHERE run_id = ? ORDER BY store, category, page", (run_id,))
    return [PageLog(r["store"], r["category"], r["page"], r["url"], bool(r["ok"]), r["items"], r["error"] or "")
            for r in rows]
