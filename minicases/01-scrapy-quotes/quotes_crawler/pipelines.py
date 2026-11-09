"""Item pipelines: clean, then validate, then drop duplicates. Every drop is counted by reason in the stats."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime

from scrapy.exceptions import DropItem

from .items import AuthorItem, QuoteItem


def _space(value):
    return re.sub(r"\s+", " ", value).strip() if isinstance(value, str) else value


def quote_key(text: str, author: str) -> str:
    norm = re.sub(r"\W+", " ", f"{text}|{author}".lower()).strip()
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:12]


class _Counted:
    def __init__(self, stats=None):
        self.stats = stats

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler.stats)

    def drop(self, reason: str, item) -> None:
        if self.stats is not None:
            self.stats.inc_value(f"pipeline/dropped/{reason}")
        raise DropItem(f"{reason}: {dict(item)}")


class CleanPipeline(_Counted):
    def process_item(self, item, spider=None):
        for field in item.fields:
            if field in item:
                item[field] = _space(item[field])
        if isinstance(item, QuoteItem) and item.get("text"):
            item["text"] = item["text"].strip("“”\"")
        if isinstance(item, AuthorItem):
            if item.get("born_date"):
                try:
                    item["born_date"] = datetime.strptime(item["born_date"], "%B %d, %Y").date().isoformat()
                except ValueError:
                    pass  # left as is; validation reports it
            if item.get("born_location"):
                item["born_location"] = re.sub(r"^in\s+", "", item["born_location"])
        return item


class ValidatePipeline(_Counted):
    def process_item(self, item, spider=None):
        if isinstance(item, QuoteItem):
            for field in ("text", "author", "author_url"):
                if not item.get(field):
                    self.drop(f"invalid/quote missing {field}", item)
            item["quote_id"] = quote_key(item["text"], item["author"])
        elif isinstance(item, AuthorItem):
            if not item.get("name") or not item.get("url"):
                self.drop("invalid/author missing name or url", item)
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", item.get("born_date") or ""):
                self.drop("invalid/author birth date not a date", item)
        return item


class DedupPipeline(_Counted):
    def __init__(self, stats=None):
        super().__init__(stats)
        self.seen: set[tuple[str, str]] = set()

    def process_item(self, item, spider=None):
        key = ("quote", item["quote_id"]) if isinstance(item, QuoteItem) else ("author", item["url"])
        if key in self.seen:
            self.drop(f"duplicate/{key[0]}", item)
        self.seen.add(key)
        return item
