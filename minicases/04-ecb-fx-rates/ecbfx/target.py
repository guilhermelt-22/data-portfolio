"""The TARGET calendar: the days the euro payment system is closed, so the ECB publishes no reference rate.

Weekends, plus New Year's Day, Good Friday, Easter Monday, 1 May, 25 and 26 December (from 2000; in 1999
only 1 January and 25 December), plus two one-off closing days: 31 December 1999 (the year 2000
changeover) and 31 December 2001 (the euro cash changeover). A day without a rate on one of these dates
is expected, not a gap.
"""
from __future__ import annotations

from functools import lru_cache

import pandas as pd
from dateutil.easter import easter

ONE_OFF_CLOSINGS = {pd.Timestamp("1999-12-31"), pd.Timestamp("2001-12-31")}


@lru_cache(maxsize=None)
def closing_days(year: int) -> frozenset[pd.Timestamp]:
    days = {pd.Timestamp(year, 1, 1), pd.Timestamp(year, 12, 25)}
    if year >= 2000:
        e = pd.Timestamp(easter(year))
        days |= {e - pd.Timedelta(days=2), e + pd.Timedelta(days=1), pd.Timestamp(year, 5, 1),
                 pd.Timestamp(year, 12, 26)}
    days |= {d for d in ONE_OFF_CLOSINGS if d.year == year}
    return frozenset(days)


def is_closing_day(day: pd.Timestamp) -> bool:
    return day.weekday() >= 5 or day.normalize() in closing_days(day.year)


def business_days(start, end) -> pd.DatetimeIndex:
    """TARGET business days from start to end, inclusive: the days a reference rate should exist."""
    days = pd.bdate_range(pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize())
    return days[[d not in closing_days(d.year) for d in days]]
