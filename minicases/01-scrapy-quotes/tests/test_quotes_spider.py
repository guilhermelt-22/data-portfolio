"""Spider callbacks and pipelines, tested offline on saved pages (no network, no reactor)."""
from pathlib import Path

import pytest
from scrapy.exceptions import DropItem
from scrapy.http import HtmlResponse, Request
from scrapy.settings import Settings
from scrapy.statscollectors import MemoryStatsCollector
from scrapy.utils.test import get_crawler

from quotes_crawler import settings as project_settings
from quotes_crawler.items import AuthorItem, QuoteItem
from quotes_crawler.pipelines import CleanPipeline, DedupPipeline, ValidatePipeline
from quotes_crawler.spiders.quotes import QuotesSpider

FIXTURES = Path(__file__).parent / "fixtures"
SITE = "https://quotes.toscrape.com"


def response(name: str, url: str) -> HtmlResponse:
    return HtmlResponse(url=url, body=(FIXTURES / name).read_bytes(), encoding="utf-8", request=Request(url))


def test_list_page_yields_quotes_author_requests_tag_pages_and_the_next_page():
    out = list(QuotesSpider().parse(response("list_page_1.html", f"{SITE}/")))
    quotes = [o for o in out if isinstance(o, QuoteItem)]
    requests = [o.url for o in out if isinstance(o, Request)]
    assert len(quotes) == 10
    assert quotes[0]["author"] == "Albert Einstein"
    assert quotes[0]["author_url"] == f"{SITE}/author/Albert-Einstein/"  # canonical form, no redirect
    assert quotes[0]["tags"] == "change,deep-thoughts,thinking,world"
    assert sum("/author/" in u for u in requests) == 10
    assert sum("/tag/" in u for u in requests) == 10   # the top-ten tags, from the home page only
    assert f"{SITE}/page/2/" in requests


def test_tag_pages_do_not_fan_out_to_other_tags():
    out = list(QuotesSpider().parse(response("tag_page.html", f"{SITE}/tag/love/")))
    requests = [o.url for o in out if isinstance(o, Request)]
    assert not any(u.startswith(f"{SITE}/tag/") and "/page/" not in u for u in requests)
    assert f"{SITE}/tag/love/page/2/" in requests


def test_author_page_becomes_a_clean_valid_record():
    item = next(QuotesSpider().parse_author(response("author_page.html", f"{SITE}/author/Albert-Einstein/")))
    item = ValidatePipeline().process_item(CleanPipeline().process_item(item))
    assert dict(item) == {"name": "Albert Einstein", "born_date": "1879-03-14", "born_location": "Ulm, Germany",
                          "url": f"{SITE}/author/Albert-Einstein/"}


def pipeline_chain(stats):
    return [CleanPipeline(stats), ValidatePipeline(stats), DedupPipeline(stats)]


def run(items, stats):
    kept = []
    chain = pipeline_chain(stats)
    for item in items:
        try:
            for p in chain:
                item = p.process_item(item)
            kept.append(item)
        except DropItem:
            pass
    return kept


def quote(text, author="Jane Austen", url=f"{SITE}/author/Jane-Austen/"):
    return QuoteItem(text=text, author=author, tags="books", author_url=url, source_url=f"{SITE}/")


def test_pipeline_drops_duplicates_and_invalid_items_and_counts_why():
    stats = MemoryStatsCollector(get_crawler())
    items = [quote("“The person, be it gentleman or lady...”"),
             quote("  The person, be it gentleman   or lady...  "),        # same quote, other spacing
             quote("Another one."),
             quote("No author", author=""),
             AuthorItem(name="Jane Austen", born_date="December 16, 1775", born_location="in Steventon",
                        url=f"{SITE}/author/Jane-Austen/"),
             AuthorItem(name="Jane Austen", born_date="December 16, 1775", born_location="in Steventon",
                        url=f"{SITE}/author/Jane-Austen/"),
             AuthorItem(name="Nobody", born_date="sometime", url=f"{SITE}/author/Nobody/")]
    kept = run(items, stats)
    assert [type(i).__name__ for i in kept] == ["QuoteItem", "QuoteItem", "AuthorItem"]
    assert kept[0]["text"] == "The person, be it gentleman or lady..."
    assert kept[2]["born_date"] == "1775-12-16" and kept[2]["born_location"] == "Steventon"
    got = {k: v for k, v in stats.get_stats().items() if k.startswith("pipeline/dropped/")}
    assert got == {"pipeline/dropped/duplicate/quote": 1, "pipeline/dropped/duplicate/author": 1,
                   "pipeline/dropped/invalid/quote missing author": 1,
                   "pipeline/dropped/invalid/author birth date not a date": 1}


def test_settings_are_polite():
    s = Settings()
    s.setmodule(project_settings)
    assert s.getbool("ROBOTSTXT_OBEY") and s.getbool("AUTOTHROTTLE_ENABLED")
    assert s.getfloat("DOWNLOAD_DELAY") >= 1.0
    assert "portfolio demo" in s.get("USER_AGENT")
    assert list(s.getdict("ITEM_PIPELINES").values()) == [100, 200, 300]


@pytest.mark.parametrize("field", ["text", "author_url"])
def test_a_quote_without_a_required_field_is_dropped(field):
    item = quote("Some text")
    item[field] = None
    with pytest.raises(DropItem, match=f"missing {field}"):
        ValidatePipeline().process_item(CleanPipeline().process_item(item))
