"""Collect one run: walk every listing page, keep the raw HTML, log each page as loaded or failed.

The page log is what makes the rest trustworthy: change detection uses it to tell "this product is
gone" from "we could not see this page today".
"""
from __future__ import annotations

import gzip
import re
from dataclasses import dataclass
from pathlib import Path

from .config import ARCHIVE, STORES, Store
from .fetch import Disallowed, PoliteClient, open_browser
from .parse import Item, parse_books_page, parse_shop_cards, parse_shop_page_count


@dataclass
class PageLog:
    store: str
    category: str
    page: int
    url: str
    ok: bool
    items: int = 0
    error: str = ""


@dataclass
class Collected:
    items: list[Item]
    pages: list[PageLog]


class Archive:
    """Raw HTML of every page, gzipped per run: re-parse later without asking the site again."""

    def __init__(self, run_id: int, root: Path = ARCHIVE):
        self.dir = root / f"run-{run_id:04d}"

    def path(self, store: str, category: str, page: int) -> Path:
        return self.dir / store / re.sub(r"\W+", "-", category) / f"page-{page:03d}.html.gz"

    def save(self, store: str, category: str, page: int, html: str) -> None:
        path = self.path(store, category, page)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(gzip.compress(html.encode("utf-8")))

    def load(self, store: str, category: str, page: int) -> str:
        return gzip.decompress(self.path(store, category, page).read_bytes()).decode("utf-8")


def _short(exc: Exception) -> str:
    return f"{type(exc).__name__}: {str(exc).splitlines()[0] if str(exc) else ''}"[:200]


# --------------------------------------------------------------------------- static: requests + BeautifulSoup
def collect_static(store: Store, client: PoliteClient, archive: Archive, max_pages: int | None = None) -> Collected:
    """Read page 1, learn the page count from the pager, then request every page by its URL.

    Planning the pages up front means one failed page costs 20 products, not the rest of the crawl
    (following "next" links would stop at the first error).
    """
    out = Collected([], [])
    for category, first_url in store.categories.items():
        total, page = 1, 1
        while page <= total and (max_pages is None or page <= max_pages):
            url = re.sub(r"page-\d+\.html", f"page-{page}.html", first_url)
            try:
                html = client.get(url)
                items, announced = parse_books_page(html, url, store.key, category)
                if page == 1:
                    total = announced or 1
                archive.save(store.key, category, page, html)
                out.items += items
                out.pages.append(PageLog(store.key, category, page, url, True, len(items)))
            except Exception as exc:  # noqa: BLE001 - one bad page must not stop the run
                out.pages.append(PageLog(store.key, category, page, url, False, error=_short(exc)))
                if page == 1:
                    total = 0  # without page 1 we do not know how many pages exist
                    break
            page += 1
        # pages we planned but skipped because of --max-pages are logged as not loaded
        for skipped in range(page, total + 1):
            url = re.sub(r"page-\d+\.html", f"page-{skipped}.html", first_url)
            out.pages.append(PageLog(store.key, category, skipped, url, False, error="skipped (--max-pages)"))
    return out


# --------------------------------------------------------------------------- dynamic: Selenium
def collect_dynamic(store: Store, client: PoliteClient, archive: Archive, max_pages: int | None = None) -> Collected:
    """AJAX pagination: the URL never changes, so requests only ever sees page 1. Selenium clicks
    through the pager like a visitor and waits for the product grid to be replaced each time."""
    from selenium.common.exceptions import WebDriverException
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as ec
    from selenium.webdriver.support.ui import WebDriverWait

    cards = (By.CSS_SELECTOR, ".ecomerce-items .thumbnail")
    out = Collected([], [])
    with open_browser(client.user_agent) as driver:
        wait = WebDriverWait(driver, 15)
        for category, url in store.categories.items():
            if not client.allowed(url):
                out.pages.append(PageLog(store.key, category, 1, url, False, error=f"Disallowed: {url}"))
                continue
            try:
                client.wait(url)
                driver.get(url)
                wait.until(ec.presence_of_element_located(cards))
                total = parse_shop_page_count(driver.page_source)
            except WebDriverException as exc:
                out.pages.append(PageLog(store.key, category, 1, url, False, error=_short(exc)))
                continue
            for page in range(1, total + 1):
                page_url = f"{url}#page={page}"
                if max_pages is not None and page > max_pages:
                    out.pages.append(PageLog(store.key, category, page, page_url, False,
                                             error="skipped (--max-pages)"))
                    continue
                try:
                    if page > 1:
                        old_first = driver.find_element(*cards)
                        button = driver.find_element(By.CSS_SELECTOR, f'.pagination .page[data-id="{page}"]')
                        client.wait(url)
                        # a JavaScript click: the site's cookie banner covers the pager, and we neither
                        # accept nor dismiss consent on a visitor's behalf
                        driver.execute_script("arguments[0].click();", button)
                        wait.until(ec.staleness_of(old_first))
                        wait.until(ec.presence_of_element_located(cards))
                    html = driver.page_source
                    items = parse_shop_cards(html, page_url, store.key, category)
                    archive.save(store.key, category, page, html)
                    out.items += items
                    out.pages.append(PageLog(store.key, category, page, page_url, True, len(items)))
                except WebDriverException as exc:
                    out.pages.append(PageLog(store.key, category, page, page_url, False, error=_short(exc)))
    return out


def collect_live(run_id: int, stores: list[str], max_pages: int | None = None,
                 client: PoliteClient | None = None) -> dict[str, Collected]:
    client = client or PoliteClient()
    archive = Archive(run_id)
    collectors = {"static": collect_static, "dynamic": collect_dynamic}
    return {key: collectors[STORES[key].method](STORES[key], client, archive, max_pages) for key in stores}


# --------------------------------------------------------------------------- replay: re-parse a past run
def collect_replay(source_run: int, pages: list[PageLog]) -> dict[str, Collected]:
    """Re-parse the archived HTML of an earlier run (after a parser fix, for example). No network."""
    archive = Archive(source_run)
    out: dict[str, Collected] = {}
    for log in pages:
        bucket = out.setdefault(log.store, Collected([], []))
        if not log.ok:
            bucket.pages.append(PageLog(**{**log.__dict__}))
            continue
        html = archive.load(log.store, log.category, log.page)
        if STORES[log.store].method == "static":
            items, _ = parse_books_page(html, log.url, log.store, log.category)
        else:
            items = parse_shop_cards(html, log.url, log.store, log.category)
        bucket.items += items
        bucket.pages.append(PageLog(log.store, log.category, log.page, log.url, True, len(items)))
    return out
