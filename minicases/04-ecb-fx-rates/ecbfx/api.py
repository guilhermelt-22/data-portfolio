"""One function to read the ECB reference rates: fetch_rates() returns a tidy DataFrame.

The ECB Data Portal serves the EXR dataset over a public SDMX REST API, without a key. Daily reference
rates have the series key D.<currency>.EUR.SP00.A (daily, spot, average, against the euro).
"""
from __future__ import annotations

import io
import time
from collections.abc import Iterable
from datetime import date

import pandas as pd
import requests

API = "https://data-api.ecb.europa.eu/service/data/EXR"
USER_AGENT = "ecbfx-demo/0.1 (portfolio demo)"
SOURCE_NOTE = "Source: ECB statistics (ECB Data Portal, dataset EXR, euro foreign exchange reference rates)"
COLUMNS = ["date", "currency", "rate"]


class ApiError(Exception):
    pass


def _key(currencies: Iterable[str] | None) -> str:
    codes = "+".join(sorted({c.strip().upper() for c in currencies})) if currencies else ""
    return f"D.{codes}.EUR.SP00.A"


def _get(url: str, params: dict, session: requests.Session, retries: int = 4, backoff: float = 5.0,
         timeout: float = 120) -> str:
    """GET with retries on timeouts, 429 and 5xx (the portal answers 503/504 when it is busy)."""
    last = ""
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(url, params=params, timeout=timeout)
        except requests.RequestException as exc:
            last = f"{type(exc).__name__}"
        else:
            ctype = resp.headers.get("Content-Type", "")
            if resp.status_code == 200 and ("csv" in ctype or not resp.text.strip()):
                return resp.text
            if resp.status_code == 404:  # SDMX "no results found"
                return ""
            last = f"HTTP {resp.status_code} ({ctype.split(';')[0] or 'no content type'})"
            if resp.status_code != 429 and resp.status_code < 500 and resp.status_code != 200:
                break
        if attempt < retries:
            time.sleep(backoff * attempt)
    raise ApiError(f"ECB Data Portal: {last} after {attempt} attempt(s)")


def fetch_rates(currencies: Iterable[str] | None = None, start: str | date | None = None,
                end: str | date | None = None, *, keep_empty: bool = False,
                session: requests.Session | None = None) -> pd.DataFrame:
    """Daily ECB reference rates as a long DataFrame with columns date, currency, rate.

    currencies: ISO codes such as ["USD", "GBP"]; None means every series in the dataset.
    start, end: inclusive dates (YYYY-MM-DD); None means from 1999 / up to the latest rate.
    keep_empty: keep the rows the ECB publishes without a value (closing days before mid-2012).
    rate: units of currency per 1 euro, as published (not modified).
    """
    session = session or requests.Session()
    session.headers.setdefault("User-Agent", USER_AGENT)
    params = {"format": "csvdata", "detail": "dataonly"}
    if start:
        params["startPeriod"] = str(start)[:10]
    if end:
        params["endPeriod"] = str(end)[:10]
    text = _get(f"{API}/{_key(currencies)}", params, session)
    if not text.strip():
        return pd.DataFrame({"date": pd.Series(dtype="datetime64[ns]"), "currency": pd.Series(dtype="str"),
                             "rate": pd.Series(dtype="float64")})
    raw = pd.read_csv(io.StringIO(text), usecols=["CURRENCY", "TIME_PERIOD", "OBS_VALUE"])
    df = raw.rename(columns={"CURRENCY": "currency", "TIME_PERIOD": "date", "OBS_VALUE": "rate"})[COLUMNS]
    df["date"] = pd.to_datetime(df["date"], format="%Y-%m-%d")
    df["rate"] = pd.to_numeric(df["rate"], errors="coerce")
    if not keep_empty:
        df = df.dropna(subset=["rate"])
    return df.sort_values(["date", "currency"], ignore_index=True)
