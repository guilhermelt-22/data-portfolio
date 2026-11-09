"""From the quote list to the author pages, following pagination, plus the ten "top tag" pages.

The tag pages list quotes that the main list already has, so the same quote arrives more than once:
the pipeline keeps one. Scrapy's own duplicate filter makes sure each author page is requested once,
however many quotes link to it.
"""
import scrapy

from ..items import AuthorItem, QuoteItem


class QuotesSpider(scrapy.Spider):
    name = "quotes"
    allowed_domains = ["quotes.toscrape.com"]
    start_urls = ["https://quotes.toscrape.com/"]

    def _count(self, kind: str) -> None:
        if getattr(self, "crawler", None):
            self.crawler.stats.inc_value(f"pages/{kind}")

    def parse(self, response):
        self._count("tag" if "/tag/" in response.url else "list")
        for quote in response.css("div.quote"):
            href = quote.css("span a::attr(href)").get()
            # the canonical author URL ends with "/": asking for it directly saves a redirect per author
            author_url = response.urljoin(href.rstrip("/") + "/") if href else None
            yield QuoteItem(
                text=quote.css("span.text::text").get(),
                author=quote.css("small.author::text").get(),
                tags=",".join(quote.css("div.tags a.tag::text").getall()),
                author_url=author_url,
                source_url=response.url,
            )
            if author_url:
                yield scrapy.Request(author_url, callback=self.parse_author)
        if response.url.rstrip("/") == self.start_urls[0].rstrip("/"):
            for href in response.css("div.tags-box span.tag-item a.tag::attr(href)").getall():
                yield response.follow(href, callback=self.parse)
        next_href = response.css("li.next a::attr(href)").get()
        if next_href:
            yield response.follow(next_href, callback=self.parse)

    def parse_author(self, response):
        self._count("author")
        yield AuthorItem(
            name=response.css("h3.author-title::text").get(),
            born_date=response.css("span.author-born-date::text").get(),
            born_location=response.css("span.author-born-location::text").get(),
            url=response.url,
        )
