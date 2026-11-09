"""Checks run on every update: duplicates, rates on closing days, gaps per currency, freshness.

A day without a rate is a gap only if it is a TARGET business day inside the currency's active range.
"""
from __future__ import annotations

import pandas as pd

from .target import business_days, is_closing_day

LONG_GAP = 20  # business days: a run this long is a suspension, not a missing day


def _days(n: int) -> str:
    return f"{n:,} day" + ("" if n == 1 else "s")


def _runs(missing: pd.DatetimeIndex, calendar: pd.DatetimeIndex) -> list[tuple[pd.Timestamp, pd.Timestamp, int]]:
    """Group missing business days into consecutive runs: (first, last, business days)."""
    pos = calendar.get_indexer(missing)
    runs, start = [], 0
    for i in range(1, len(pos) + 1):
        if i == len(pos) or pos[i] != pos[i - 1] + 1:
            runs.append((missing[start], missing[i - 1], int(pos[i - 1] - pos[start] + 1)))
            start = i
    return runs


def coverage(rates: pd.DataFrame) -> pd.DataFrame:
    """One row per currency: active range, values, expected days, gaps and the largest gap."""
    latest = rates["date"].max()
    calendar = business_days(rates["date"].min(), latest)
    rows = []
    for cur, g in rates.groupby("currency"):
        first, last = g["date"].min(), g["date"].max()
        expected = calendar[(calendar >= first) & (calendar <= last)]
        missing = expected.difference(pd.DatetimeIndex(g["date"]))
        runs = _runs(missing, calendar) if len(missing) else []
        big = max(runs, key=lambda r: r[2]) if runs else None
        rows.append({
            "currency": cur, "first": first.date(), "last": last.date(),
            "status": "published" if last == latest else "discontinued",
            "values": len(g), "expected": len(expected), "gap_days": len(missing), "gap_runs": len(runs),
            "largest_gap": (f"{big[0].date()} to {big[1].date()} ({_days(big[2])})" if big and big[2] > 1
                            else f"{big[0].date()}" if big else ""),
            "suspension": bool(big and big[2] >= LONG_GAP),
            "latest_rate": g.loc[g["date"].idxmax(), "rate"],
        })
    return pd.DataFrame(rows).sort_values(["status", "currency"], ascending=[False, True], ignore_index=True)


def run_checks(rates: pd.DataFrame, empty_rows: pd.DataFrame | None = None, duplicates_received: int = 0,
               today: pd.Timestamp | None = None) -> dict:
    """Return {'checks': [(name, result, detail)], 'overall': ..., 'coverage': DataFrame}."""
    today = (today or pd.Timestamp.now(tz="UTC").tz_localize(None)).normalize()
    cov = coverage(rates)
    checks = []

    dups = int(rates.duplicated(["date", "currency"]).sum())
    checks.append(("One rate per currency per day", "PASS" if dups == 0 else "FAIL",
                   f"{dups:,} duplicate date/currency pairs stored; {duplicates_received:,} received and merged"))

    closed = rates[rates["date"].map(is_closing_day)]
    checks.append(("No rate on a weekend or TARGET closing day", "PASS" if closed.empty else "FAIL",
                   f"{len(closed):,} rates on closing days"))

    bad = int((rates["rate"] <= 0).sum())
    checks.append(("Every rate above zero", "PASS" if bad == 0 else "FAIL", f"{bad:,} rates at or below zero"))

    if empty_rows is not None and len(empty_rows):
        on_closing = int(empty_rows["date"].map(is_closing_day).sum())
        checks.append(("Closing days are not gaps", "PASS",
                       f"{len(empty_rows):,} rows published without a value: {on_closing:,} on TARGET closing days "
                       f"(the ECB filled holidays this way until 2012), {len(empty_rows) - on_closing:,} on other days"))

    pub = cov[cov["status"] == "published"]
    gaps = pub[pub["gap_days"] > 0]
    if gaps.empty:
        checks.append(("No gaps in currencies still published", "PASS", "0 missing business days"))
    else:
        detail = "; ".join(f"{r.currency}: suspended {r.largest_gap}" if r.suspension and r.gap_runs == 1
                           else f"{r.currency}: {_days(r.gap_days)} ({r.largest_gap})" if r.gap_runs == 1
                           else f"{r.currency}: {_days(r.gap_days)}, largest {r.largest_gap}"
                           for r in gaps.itertuples())
        checks.append(("No gaps in currencies still published", "WARN", detail + " (as published by the ECB)"))
    old = cov[(cov["status"] == "discontinued") & (cov["gap_days"] > 0)]
    if len(old):
        checks.append(("Gaps in discontinued currencies", "INFO",
                       "; ".join(f"{r.currency}: {_days(r.gap_days)}" for r in old.itertuples())))

    latest = rates["date"].max()
    expected = business_days(today - pd.Timedelta(days=10), today - pd.Timedelta(days=1))[-1]
    checks.append(("Up to date", "PASS" if latest >= expected else "WARN",
                   f"latest rate {latest.date()}; latest complete business day {expected.date()} "
                   "(the day's rates appear around 16:00 CET)"))

    results = {r for _, r, _ in checks}
    overall = "FAIL" if "FAIL" in results else "PASS WITH WARNINGS" if "WARN" in results else "PASS"
    return {"checks": checks, "overall": overall, "coverage": cov}
