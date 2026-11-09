"""Work through every pending URL until none is left: listing pages first (discovery), then book pages.

Every URL leaves this loop with one of three outcomes, written to the checkpoint in the same transaction
as its record: collected, failed (with the reason) or excluded (with the rule that excluded it).
"""
from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable

from . import state
from .config import INJECTED_DEAD_LINK, INJECTED_DEAD_LINK_ON, INJECTED_LAYOUT_CHANGE_SUFFIX, START_URL
from .parse import EXCLUDED, ParseError, classify, parse_book, parse_listing
from .polite import FetchError, PoliteClient


def seed(con: sqlite3.Connection, run_id: int, start_url: str = START_URL) -> None:
    if con.execute("SELECT 1 FROM urls LIMIT 1").fetchone() is None:
        with con:
            state.add_url(con, start_url, classify(start_url), "seed", run_id)


def retry_failed(con: sqlite3.Connection) -> int:
    """Put failed URLs back in the queue (used with --retry-failed on a later run)."""
    with con:
        return con.execute("UPDATE urls SET status = 'pending', reason = NULL WHERE status = 'failed'").rowcount


def next_pending(con: sqlite3.Connection) -> sqlite3.Row | None:
    return con.execute("""SELECT url, kind FROM urls WHERE status = 'pending'
                          ORDER BY kind != 'listing', seq LIMIT 1""").fetchone()


def _drop_price(html: str) -> str:
    """The injected template change: the book page loses its price block."""
    return re.sub(r'<p class="price_color">.*?</p>', "", html, count=1, flags=re.S)


def _listing(con, client, url, run_id, inject) -> tuple[int, int]:
    html, attempts = client.get(url)
    links, announced, pages = parse_listing(html, url)
    if inject and url == INJECTED_DEAD_LINK_ON:
        links.append(INJECTED_DEAD_LINK)
    with con:
        if pages and state.get_meta(con, "listing_pages") is None:
            # plan every listing page from the pager ("Page 1 of 50"), so one failed page hides
            # 20 books, not the rest of the catalog (following "next" would stop at the first error)
            state.set_meta(con, "listing_pages", pages)
            state.set_meta(con, "books_announced", announced or "")
            for n in range(1, pages + 1):
                planned = re.sub(r"page-\d+\.html", f"page-{n}.html", url)
                state.add_url(con, planned, "listing", f"{url} (pager)", run_id, count_link=False)
        for link in links:
            kind = classify(link)
            state.add_url(con, link, kind, url, run_id, EXCLUDED.get(kind))
        state.set_meta(con, "links_found", int(state.get_meta(con, "links_found", 0)) + len(links))
        state.close_url(con, url, "collected", run_id, "links read", 200, attempts)
        con.execute("INSERT INTO fetches VALUES (?, ?, ?)", (url, run_id, state.now()))
        state.bump_run(con, run_id, attempts, 0)
    return attempts, 0


def _book(con, client, url, run_id, inject) -> tuple[int, int]:
    html, attempts = client.get(url)
    if inject and url.endswith(INJECTED_LAYOUT_CHANGE_SUFFIX):
        html = _drop_price(html)
    try:
        rec = parse_book(html, url)
    except ParseError as exc:
        with con:
            state.close_url(con, url, "failed", run_id, str(exc), 200, attempts)
            con.execute("INSERT INTO fetches VALUES (?, ?, ?)", (url, run_id, state.now()))
            state.bump_run(con, run_id, attempts, 0)
        return attempts, 0
    with con:
        twin = con.execute("SELECT url FROM books WHERE upc = ?", (rec["upc"],)).fetchone()
        if twin:  # same book under a second URL: keep one record, report the other
            state.close_url(con, url, "failed", run_id, f"duplicate record: same UPC as {twin['url']}", 200, attempts)
            added = 0
        else:
            con.execute("""INSERT INTO books (url, upc, title, category, price_cents, stock, rating, reviews,
                           run_id, collected_at) VALUES (:url, :upc, :title, :category, :price_cents, :stock,
                           :rating, :reviews, :run_id, :at)""", {**rec, "run_id": run_id, "at": state.now()})
            state.close_url(con, url, "collected", run_id, "record saved", 200, attempts)
            added = 1
        con.execute("INSERT INTO fetches VALUES (?, ?, ?)", (url, run_id, state.now()))
        state.bump_run(con, run_id, attempts, added)
    return attempts, added


def crawl(con: sqlite3.Connection, client: PoliteClient, run_id: int, inject: bool = False,
          log: Callable[[str], None] = print, start_url: str = START_URL) -> None:
    seed(con, run_id, start_url)
    done = 0
    while (row := next_pending(con)) is not None:
        url, kind = row["url"], row["kind"]
        try:
            if not client.allowed(url):
                with con:
                    state.close_url(con, url, "excluded", run_id, "disallowed by robots.txt")
                continue
            (_listing if kind == "listing" else _book)(con, client, url, run_id, inject)
        except FetchError as exc:
            with con:
                state.close_url(con, url, "failed", run_id, exc.reason, exc.http_status, exc.attempts)
                con.execute("INSERT INTO fetches VALUES (?, ?, ?)", (url, run_id, state.now()))
                state.bump_run(con, run_id, exc.attempts, 0)
        except Exception as exc:  # noqa: BLE001 - an unexpected error on one page must not stop the crawl
            with con:
                state.close_url(con, url, "failed", run_id, f"unexpected error: {type(exc).__name__}")
                state.bump_run(con, run_id, 0, 0)
        done += 1
        if done % 100 == 0:
            left = con.execute("SELECT COUNT(*) FROM urls WHERE status = 'pending'").fetchone()[0]
            log(f"  {done} pages done in this run, {left} pending")
    for origin, note in client.robots_note.items():
        with con:
            state.set_meta(con, f"robots {origin}", note)
