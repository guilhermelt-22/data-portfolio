"""Dropped duplicates are expected here: log them at DEBUG, not as warnings. The stats still count them."""
import logging

from scrapy import logformatter


class QuietDrops(logformatter.LogFormatter):
    def dropped(self, *args, **kwargs):
        entry = super().dropped(*args, **kwargs)
        entry["level"] = logging.DEBUG
        return entry
