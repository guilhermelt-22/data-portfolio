"""Parsers and polite fetching, tested offline on saved markup and a fake HTTP session."""
from pathlib import Path

import pytest
import requests

from pricewatch.fetch import Disallowed, PoliteClient
from pricewatch.parse import parse_books_page, parse_price, parse_shop_cards, parse_shop_page_count

FIXTURES = Path(__file__).parent / "fixtures"
BOOKS_URL = "https://books.toscrape.com/catalogue/page-1.html"
SHOP_URL = "https://webscraper.io/test-sites/e-commerce/ajax/computers/laptops"


@pytest.mark.parametrize("text, cents", [("£51.77", 5177), ("$1,099.00", 109900), ("$299", 29900),
                                         ("£0.5", 50), ("Call for price", None), ("", None)])
def test_prices_become_integer_cents(text, cents):
    assert parse_price(text) == cents


def test_static_page_yields_complete_records_and_the_page_count():
    items, total = parse_books_page((FIXTURES / "books_page.html").read_text("utf-8"), BOOKS_URL)
    assert total == 50
    first, second, broken = items
    assert (first.item_id, first.title, first.price_cents, first.in_stock, first.rating) == (
        "1000", "A Light in the Attic", 5177, True, 3)  # full title from the link, not the truncated text
    assert first.url == "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"
    assert (second.price_cents, second.in_stock) == (105374, False)
    assert broken.price_cents is None and broken.price_text == "Call for price"  # kept for the quality report


def test_rendered_shop_cards_are_parsed_with_reviews_and_stars():
    html = (FIXTURES / "shop_page.html").read_text("utf-8")
    items = parse_shop_cards(html, SHOP_URL + "#page=1", "electronics", "laptops")
    assert [(i.item_id, i.price_cents, i.rating, i.reviews) for i in items] == [("60", 29599, 3, 12),
                                                                               ("61", 109900, None, 0)]
    assert items[0].url == "https://webscraper.io/test-sites/e-commerce/ajax/product/60"
    assert all(i.in_stock is None for i in items)  # the shop does not publish stock: unknown, not "out"
    assert parse_shop_page_count(html) == 20


class FakeResponse:
    def __init__(self, status=200, text="", headers=None):
        self.status_code, self.text, self.headers = status, text, headers or {"Content-Type": "text/html; charset=utf-8"}


class FakeSession:
    def __init__(self, responses):
        self.responses, self.calls, self.headers = list(responses), [], {}

    def get(self, url, timeout=None):
        self.calls.append(url)
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def client_with(responses) -> PoliteClient:
    client = PoliteClient(delay=0, backoff=0)
    client.session = FakeSession(responses)
    return client


ROBOTS = "User-agent: *\nDisallow: /test-sites/product/\nDisallow: /test-sites/scroll/\n"


def test_robots_txt_is_respected_before_any_page_request():
    client = client_with([FakeResponse(text=ROBOTS)])
    assert client.allowed(SHOP_URL)
    with pytest.raises(Disallowed):
        client.get("https://webscraper.io/test-sites/product/1")
    assert client.session.calls == ["https://webscraper.io/robots.txt"]  # the page itself was never requested


def test_a_site_without_robots_txt_is_open_and_transient_errors_are_retried():
    client = client_with([FakeResponse(404), requests.ConnectionError("reset"), FakeResponse(503),
                          FakeResponse(text="<html>ok</html>")])
    assert client.get(BOOKS_URL) == "<html>ok</html>"
    assert client.requests_made == 3


def test_a_404_page_is_not_retried():
    client = client_with([FakeResponse(404), FakeResponse(404)])
    with pytest.raises(requests.HTTPError):
        client.get(BOOKS_URL)
    assert client.requests_made == 1
