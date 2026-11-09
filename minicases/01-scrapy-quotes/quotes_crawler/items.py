"""The two record types the client asked for. Author biographies are left out on purpose: name, birth
date and place are enough to join on, and the long texts are not ours to republish."""
import scrapy


class QuoteItem(scrapy.Item):
    quote_id = scrapy.Field()    # stable key: hash of the normalized text and author
    text = scrapy.Field()
    author = scrapy.Field()
    tags = scrapy.Field()        # comma-separated
    author_url = scrapy.Field()
    source_url = scrapy.Field()  # page the quote was read from


class AuthorItem(scrapy.Item):
    name = scrapy.Field()
    born_date = scrapy.Field()   # ISO 8601 after cleaning
    born_location = scrapy.Field()
    url = scrapy.Field()
