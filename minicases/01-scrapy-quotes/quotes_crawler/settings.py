"""Scrapy settings: polite by default (robots.txt, AutoThrottle, generic user agent), CSV feeds per item type."""
from pathlib import Path

BOT_NAME = "quotes_crawler"
SPIDER_MODULES = ["quotes_crawler.spiders"]
NEWSPIDER_MODULE = "quotes_crawler.spiders"

OUT = Path(__file__).resolve().parents[1] / "output"

# Polite crawling
USER_AGENT = "quotes-demo/0.1 (portfolio demo; practice sites only)"
ROBOTSTXT_OBEY = True                 # robots.txt is read first and obeyed
CONCURRENT_REQUESTS_PER_DOMAIN = 2
DOWNLOAD_DELAY = 1.0                  # at least 1 second between requests to the site
AUTOTHROTTLE_ENABLED = True           # slows down further when the site answers slowly
AUTOTHROTTLE_START_DELAY = 1.0
AUTOTHROTTLE_MAX_DELAY = 10.0
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.0
RETRY_TIMES = 2
COOKIES_ENABLED = False
TELNETCONSOLE_ENABLED = False
MEMUSAGE_ENABLED = False
LOG_FORMATTER = "quotes_crawler.logformatter.QuietDrops"

ITEM_PIPELINES = {
    "quotes_crawler.pipelines.CleanPipeline": 100,
    "quotes_crawler.pipelines.ValidatePipeline": 200,
    "quotes_crawler.pipelines.DedupPipeline": 300,
}

FEEDS = {
    OUT / "quotes.csv": {"format": "csv", "item_classes": ["quotes_crawler.items.QuoteItem"],
                              "fields": ["quote_id", "text", "author", "tags", "author_url", "source_url"],
                              "mode": "overwrite", "encoding": "utf-8"},
    OUT / "authors.csv": {"format": "csv", "item_classes": ["quotes_crawler.items.AuthorItem"],
                               "fields": ["name", "born_date", "born_location", "url"],
                               "mode": "overwrite", "encoding": "utf-8"},
}

LOG_LEVEL = "INFO"
