"""HTML -> records. Pure functions with no network access, so every parser is tested on saved markup."""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urljoin

from bs4 import BeautifulSoup

STARS = {"One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5}


@dataclass
class Item:
    store: str
    category: str
    item_id: str              # stable id taken from the product URL, never from the position on the page
    title: str
    url: str
    price_cents: int | None   # integer cents: no floating-point noise can look like a price change
    price_text: str           # raw text as shown on the page, kept for the data quality report
    in_stock: bool | None     # None when the store does not publish stock
    rating: int | None = None
    reviews: int | None = None
    source_url: str = ""      # listing page the record came from (provenance)


def parse_price(text: str | None) -> int | None:
    """'£51.77' -> 5177 · '$1,099.00' -> 109900 · '' or 'N/A' -> None."""
    match = re.search(r"\d[\d,]*(?:\.\d{1,2})?", text or "")
    if not match:
        return None
    whole, _, cents = match.group().replace(",", "").partition(".")
    return int(whole) * 100 + int(cents.ljust(2, "0") or 0)


def _id_from(url: str, pattern: str) -> str:
    match = re.search(pattern, url)
    return match.group(1) if match else url


# --------------------------------------------------------------------------- static store (requests + BS4)
def parse_books_page(html: str, page_url: str, store: str = "books", category: str = "all books"
                     ) -> tuple[list[Item], int | None]:
    """One catalogue page of books.toscrape.com -> (items, total pages announced by the pager)."""
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for pod in soup.select("article.product_pod"):
        link = pod.select_one("h3 a")
        price = pod.select_one(".price_color")
        stock = pod.select_one(".availability")
        stars = pod.select_one("p.star-rating")
        url = urljoin(page_url, link["href"]) if link and link.get("href") else ""
        price_text = price.get_text(strip=True) if price else ""
        items.append(Item(
            store=store, category=category,
            item_id=_id_from(url, r"_(\d+)/index\.html$"),
            title=(link.get("title") or link.get_text(strip=True)) if link else "",
            url=url,
            price_cents=parse_price(price_text),
            price_text=price_text,
            in_stock=("in stock" in stock.get_text(" ", strip=True).lower()) if stock else None,
            rating=next((STARS[c] for c in (stars.get("class", []) if stars else []) if c in STARS), None),
            source_url=page_url,
        ))
    pager = soup.select_one(".pager .current")
    total = re.search(r"of\s+(\d+)", pager.get_text(" ", strip=True)) if pager else None
    return items, int(total.group(1)) if total else (1 if items else None)


# --------------------------------------------------------------------------- dynamic store (Selenium-rendered)
def parse_shop_cards(html: str, page_url: str, store: str, category: str) -> list[Item]:
    """Product cards of the webscraper.io test shop, from the HTML *after* JavaScript has rendered it."""
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for card in soup.select(".ecomerce-items .thumbnail"):
        link = card.select_one("a.title")
        price = card.select_one(".price")
        reviews = card.select_one(".review-count")
        url = urljoin(page_url, link["href"]) if link and link.get("href") else ""
        price_text = price.get_text(strip=True) if price else ""
        count = re.search(r"\d+", reviews.get_text()) if reviews else None
        items.append(Item(
            store=store, category=category,
            item_id=_id_from(url, r"/product/(\d+)"),
            title=(link.get("title") or link.get_text(strip=True)) if link else "",
            url=url,
            price_cents=parse_price(price_text),
            price_text=price_text,
            in_stock=None,  # this shop does not publish stock
            rating=len(card.select(".ratings .ws-icon-star")) or None,
            reviews=int(count.group()) if count else None,
            source_url=page_url,
        ))
    return items


def parse_shop_page_count(html: str) -> int:
    """Number of AJAX pages: the highest numbered pagination button (1 when there is no pager)."""
    soup = BeautifulSoup(html, "html.parser")
    numbers = [int(b["data-id"]) for b in soup.select(".pagination .page[data-id]") if b["data-id"].isdigit()]
    return max(numbers, default=1)
