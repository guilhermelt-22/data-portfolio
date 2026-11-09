"""What to monitor and how politely. Adding a store is one entry here plus a parser in parse.py."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "pricewatch"
DB_PATH = OUT / "pricewatch.sqlite"
ARCHIVE = OUT / "archive"

# A generic, honest user agent: says what the client is, never who runs it.
USER_AGENT = "pricewatch-demo/0.1 (portfolio demo; practice sites only)"
DELAY_SECONDS = 1.0  # minimum pause between two requests to the same site (robots.txt Crawl-delay wins if larger)
TIMEOUT_SECONDS = 20
RETRIES = 3          # attempts per page for timeouts, connection errors, 429 and 5xx


@dataclass(frozen=True)
class Store:
    key: str                    # short id used in the database and the reports
    name: str
    method: str                 # "static" (requests + BeautifulSoup) or "dynamic" (Selenium)
    currency: str
    categories: dict[str, str]  # category -> first listing page


# Both sources are sandboxes built for scraping practice; their data is fictitious and never changes.
STORES: dict[str, Store] = {
    "books": Store(
        key="books", name="Books to Scrape", method="static", currency="GBP",
        categories={"all books": "https://books.toscrape.com/catalogue/page-1.html"},
    ),
    "electronics": Store(
        key="electronics", name="Web Scraper test shop", method="dynamic", currency="USD",
        categories={
            "laptops": "https://webscraper.io/test-sites/e-commerce/ajax/computers/laptops",
            "tablets": "https://webscraper.io/test-sites/e-commerce/ajax/computers/tablets",
            "phones": "https://webscraper.io/test-sites/e-commerce/ajax/phones/touch",
        },
    ),
}
