"""Read links from listing pages, classify every URL, and turn a book page into a validated record."""
from __future__ import annotations

import re
from urllib.parse import urldefrag, urljoin, urlsplit

from bs4 import BeautifulSoup

SITE = "books.toscrape.com"
RATING = {"One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5}

# What each kind of page is, and why it is not collected when it is not.
EXCLUDED = {
    "category": "out of scope: category page",
    "home": "out of scope: home page",
    "offsite": "out of scope: another site",
    "other": "out of scope: not a book or listing page",
}


class ParseError(Exception):
    """The page loaded but a required field is missing: the template may have changed."""


def classify(url: str) -> str:
    parts = urlsplit(url)
    if parts.netloc != SITE:
        return "offsite"
    path = parts.path
    if re.fullmatch(r"/catalogue/page-\d+\.html", path):
        return "listing"
    if path.startswith("/catalogue/category/"):
        return "category"
    if re.fullmatch(r"/catalogue/[^/]+_\d+/index\.html", path):
        return "book"
    if path in ("/", "/index.html"):
        return "home"
    return "other"


def normalize(href: str, base: str) -> str | None:
    """Absolute URL without fragment; None for links that are not pages (mailto:, javascript:)."""
    url, _ = urldefrag(urljoin(base, href.strip()))
    return url if url.startswith(("http://", "https://")) else None


def parse_listing(html: str, url: str) -> tuple[list[str], int | None, int | None]:
    """Return (every link on the page, in order and with repeats; books announced; page count)."""
    soup = BeautifulSoup(html, "html.parser")
    links = [u for a in soup.select("a[href]") if (u := normalize(a["href"], url))]
    announced = None
    form = soup.select_one("form.form-horizontal strong")
    if form and form.get_text(strip=True).isdigit():
        announced = int(form.get_text(strip=True))
    pages = None
    current = soup.select_one("li.current")
    if current and (m := re.search(r"Page\s+\d+\s+of\s+(\d+)", current.get_text())):
        pages = int(m.group(1))
    return links, announced, pages


def _price_cents(text: str) -> int | None:
    m = re.search(r"(\d+)\.(\d{2})", text.replace(",", ""))
    return int(m.group(1)) * 100 + int(m.group(2)) if m else None


def parse_book(html: str, url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    main = soup.select_one(".product_main")
    if main is None:
        raise ParseError("parse error: product block not found")
    title = main.h1.get_text(strip=True) if main.h1 else ""
    if not title:
        raise ParseError("parse error: title not found")
    price_tag = main.select_one("p.price_color")
    price = _price_cents(price_tag.get_text()) if price_tag else None
    if price is None:
        raise ParseError("parse error: price not found")
    table = {th.get_text(strip=True): th.find_next_sibling("td").get_text(strip=True)
             for th in soup.select("table.table th") if th.find_next_sibling("td")}
    upc = table.get("UPC", "")
    if not re.fullmatch(r"[0-9a-f]{16}", upc):
        raise ParseError("parse error: UPC not found")
    stock_text = main.select_one("p.availability").get_text(" ", strip=True) if main.select_one("p.availability") else ""
    stock = int(m.group(1)) if (m := re.search(r"\((\d+) available\)", stock_text)) else 0
    stars = main.select_one("p.star-rating")
    rating = next((RATING[c] for c in (stars.get("class", []) if stars else []) if c in RATING), None)
    crumbs = soup.select("ul.breadcrumb li")
    category = crumbs[2].get_text(strip=True) if len(crumbs) >= 4 else ""
    reviews = table.get("Number of reviews", "0")
    record = {"url": url, "upc": upc, "title": title, "category": category, "price_cents": price,
              "stock": stock, "rating": rating, "reviews": int(reviews) if reviews.isdigit() else 0}
    if record["price_cents"] <= 0:
        raise ParseError("validation: price is zero")
    return record
