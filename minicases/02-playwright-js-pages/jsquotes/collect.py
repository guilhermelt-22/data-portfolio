"""Three ways to read the same quotes, so the difference is measured, not claimed.

1. plain_count: a plain HTTP request (requests + BeautifulSoup), as a one-off script would do. The HTML
   arrives without quotes, because JavaScript writes them after the page loads.
2. scroll_all / paginate_js: Playwright drives headless Chromium the way a visitor would: it scrolls the
   infinite-scroll page until nothing new appears, and walks the JavaScript-rendered pages.
3. api_quotes: the site's own JSON endpoint, which the scroll page calls. Used here as a cross-check.
"""
from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

SITE = "https://quotes.toscrape.com"
USER_AGENT = "jsquotes-demo/0.1 (portfolio demo; practice sites only)"
PAUSE = 1.0          # seconds between actions that make the page request something
WAIT_NEW = 5_000     # ms to wait for new quotes after a scroll
MAX_MISSES = 2       # stop after this many scrolls in a row bring nothing new

QUOTES_JS = """() => [...document.querySelectorAll('div.quote')].map(q => ({
    text: q.querySelector('.text')?.innerText ?? '',
    author: q.querySelector('.author')?.innerText ?? '',
    tags: [...q.querySelectorAll('.tags a.tag')].map(a => a.innerText).join(',')}))"""


def key(text: str, author: str) -> str:
    norm = re.sub(r"\W+", " ", f"{text}|{author}".lower()).strip()
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:12]


def clean(rec: dict) -> dict:
    text = re.sub(r"\s+", " ", rec["text"]).strip().strip("“”\"")
    author = re.sub(r"\s+", " ", rec["author"]).strip()
    return {"quote_id": key(text, author), "text": text, "author": author, "tags": rec.get("tags", "")}


def robots_allows(url: str, session: requests.Session) -> tuple[bool, str]:
    rp = RobotFileParser(urljoin(url, "/robots.txt"))
    resp = session.get(rp.url, timeout=20)
    if resp.status_code == 200:
        rp.parse(resp.text.splitlines())
        return rp.can_fetch(USER_AGENT, url), "read and obeyed"
    if 400 <= resp.status_code < 500 and resp.status_code not in (401, 403):
        return True, f"none published (HTTP {resp.status_code}): nothing disallowed"
    return False, f"unreadable (HTTP {resp.status_code}): not crawled"


# --------------------------------------------------------------------------- 1. plain request
def count_quotes(html: str) -> int:
    return len(BeautifulSoup(html, "html.parser").select("div.quote"))


def plain_count(url: str, session: requests.Session) -> int:
    resp = session.get(url, timeout=20)
    resp.raise_for_status()
    return count_quotes(resp.text)


# --------------------------------------------------------------------------- 2. browser
@dataclass
class BrowserRun:
    records: list[dict] = field(default_factory=list)
    log: list[tuple[int, int]] = field(default_factory=list)  # (step, quotes on the page after it)
    pages: int = 0
    seconds: float = 0.0


def scroll_all(page, url: str, pause: float = PAUSE, wait_new: int = WAIT_NEW, max_misses: int = MAX_MISSES) -> BrowserRun:
    """Scroll to the bottom until `max_misses` scrolls in a row bring no new quote."""
    t0 = time.monotonic()
    run = BrowserRun(pages=1)
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_selector("div.quote", timeout=15_000)
    count, misses, step = page.locator("div.quote").count(), 0, 0
    run.log.append((0, count))
    while misses < max_misses:
        time.sleep(pause)
        step += 1
        page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
        try:
            page.wait_for_function("n => document.querySelectorAll('div.quote').length > n", arg=count,
                                   timeout=wait_new)
            misses = 0
        except Exception:  # noqa: BLE001 - Playwright's TimeoutError: nothing new arrived
            misses += 1
        count = page.locator("div.quote").count()
        run.log.append((step, count))
    run.records = [clean(r) for r in page.evaluate(QUOTES_JS)]
    run.seconds = round(time.monotonic() - t0, 1)
    return run


def paginate_js(page, url: str, pause: float = PAUSE, max_pages: int = 100) -> BrowserRun:
    """Render each JavaScript page and follow its "Next" link until there is none."""
    t0 = time.monotonic()
    run = BrowserRun()
    next_url: str | None = url
    while next_url and run.pages < max_pages:
        if run.pages:
            time.sleep(pause)
        page.goto(next_url, wait_until="domcontentloaded")
        page.wait_for_selector("div.quote", timeout=15_000)
        found = [clean(r) for r in page.evaluate(QUOTES_JS)]
        run.records += found
        run.pages += 1
        run.log.append((run.pages, len(run.records)))
        href = page.locator("li.next a").first.get_attribute("href") if page.locator("li.next a").count() else None
        next_url = urljoin(page.url, href) if href else None
    run.seconds = round(time.monotonic() - t0, 1)
    return run


# --------------------------------------------------------------------------- 3. JSON endpoint (cross-check)
def parse_api(payload: dict) -> list[dict]:
    return [clean({"text": q["text"], "author": q["author"]["name"], "tags": ",".join(q["tags"])})
            for q in payload.get("quotes", [])]


def api_quotes(session: requests.Session, pause: float = PAUSE) -> tuple[list[dict], int]:
    records, page, has_next = [], 0, True
    while has_next:
        if page:
            time.sleep(pause)
        page += 1
        data = session.get(f"{SITE}/api/quotes", params={"page": page}, timeout=20).json()
        records += parse_api(data)
        has_next = bool(data.get("has_next"))
    return records, page


def reconcile(*sets: list[dict]) -> dict:
    keys = [{r["quote_id"] for r in s} for s in sets]
    return {"same": all(k == keys[0] for k in keys), "sizes": [len(k) for k in keys],
            "duplicates": [len(s) - len(k) for s, k in zip(sets, keys)]}
