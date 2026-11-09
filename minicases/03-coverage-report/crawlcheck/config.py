"""Where to start, how politely to crawl, and the two failures the demo injects on purpose."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # the mini-case folder
OUT = ROOT / "output"
DB_PATH = OUT / "state.sqlite"  # the checkpoint: every URL, its outcome and every saved record

# Books to Scrape is a sandbox built for scraping practice; its 1,000 books are fictitious.
START_URL = "https://books.toscrape.com/catalogue/page-1.html"

# A generic, honest user agent: says what the client is, never who runs it.
USER_AGENT = "crawlcheck-demo/0.1 (portfolio demo; practice sites only)"
DELAY_SECONDS = 1.0  # minimum pause between two requests (robots.txt Crawl-delay wins if larger)
TIMEOUT_SECONDS = 20
RETRIES = 3          # attempts per page for timeouts, connection errors, 429 and 5xx

# Failures injected by `--inject`, so the report has something real to catch:
# 1. a broken link, as if listing page 25 linked to a book that no longer exists (the site answers 404);
# 2. a template change on one book page: its price block is removed before parsing.
INJECTED_DEAD_LINK = "https://books.toscrape.com/catalogue/the-missing-book_1001/index.html"
INJECTED_DEAD_LINK_ON = "https://books.toscrape.com/catalogue/page-25.html"
INJECTED_LAYOUT_CHANGE_SUFFIX = "_500/index.html"
