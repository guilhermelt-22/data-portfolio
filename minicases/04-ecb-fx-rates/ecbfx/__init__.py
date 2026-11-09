"""ECB euro foreign exchange reference rates from the official ECB Data Portal API (no key needed).

    from ecbfx import fetch_rates
    df = fetch_rates(["USD", "GBP"], start="2026-01-01")   # columns: date, currency, rate

Rates are units of currency per 1 euro, exactly as published. Source: ECB statistics.
"""
from .api import SOURCE_NOTE, fetch_rates

__all__ = ["fetch_rates", "SOURCE_NOTE"]
