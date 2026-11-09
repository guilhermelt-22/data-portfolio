"""Data quality report per run and store: can this run's numbers be trusted before anyone acts on them?"""
from __future__ import annotations

from dataclasses import dataclass

from .changes import Change
from .collect import PageLog
from .parse import Item

EXTREME_MOVE = 0.5   # a price that moves 50%+ in one run is more often a parsing error than a real price
SIZE_DROP_WARN, SIZE_DROP_ERROR = 0.02, 0.10
SEVERITY_ORDER = {"ok": 0, "info": 0, "warning": 1, "error": 2}


@dataclass
class Check:
    store: str
    name: str
    severity: str  # ok | info | warning | error
    count: int
    detail: str


def run_checks(store: str, pages: list[PageLog], kept: list[Item], duplicates: int,
               previous_count: int | None, changes: list[Change]) -> list[Check]:
    checks: list[Check] = []

    def add(name: str, severity: str, count: int, detail: str) -> None:
        checks.append(Check(store, name, severity, count, detail))

    # 1. Did every listing page load?
    failed = [p for p in pages if not p.ok]
    share = 1 - len(failed) / len(pages) if pages else 0.0
    if not pages:
        add("Listing pages loaded", "error", 0, "no pages were attempted")
    else:
        first = f" First failure: {failed[0].url} ({failed[0].error})" if failed else ""
        add("Listing pages loaded", "ok" if not failed else ("warning" if share >= 0.9 else "error"),
            len(pages) - len(failed), f"{len(pages) - len(failed)} of {len(pages)} pages ({share:.0%}).{first}")

    # 2. Required fields
    no_price = [i for i in kept if i.price_cents is None]
    add("Price parsed", "ok" if not no_price else "error", len(kept) - len(no_price),
        "every product has a price" if not no_price else
        f"{len(no_price)} without a readable price, e.g. '{no_price[0].title}': '{no_price[0].price_text}'")
    incomplete = [i for i in kept if not i.title or not i.url]
    add("Title and URL present", "ok" if not incomplete else "error", len(kept) - len(incomplete),
        "complete" if not incomplete else f"{len(incomplete)} products missing a title or URL")
    zero = [i for i in kept if i.price_cents is not None and i.price_cents <= 0]
    add("Prices above zero", "ok" if not zero else "warning", len(zero),
        "none at zero or below" if not zero else f"{len(zero)} at zero or below")

    # 3. Duplicates collapsed inside the run (expected on shifting pages; reported, not an error)
    add("Duplicates collapsed", "info", duplicates,
        "no product listed twice" if not duplicates else f"{duplicates} repeated listings kept once")

    # 4. Catalog size versus the previous run
    if previous_count:
        drop = (previous_count - len(kept)) / previous_count
        severity = "error" if drop >= SIZE_DROP_ERROR else "warning" if drop >= SIZE_DROP_WARN else "ok"
        add("Catalog size vs last run", severity, len(kept),
            f"{len(kept):,} products vs {previous_count:,} ({(len(kept) - previous_count) / previous_count:+.1%})")
    else:
        add("Catalog size vs last run", "info", len(kept), f"{len(kept):,} products (baseline run)")

    # 5. Price moves too large to act on without a look
    extreme = [c for c in changes if c.pct is not None and abs(c.pct) >= EXTREME_MOVE]
    titles = {i.item_id: i.title for i in kept}
    add("Extreme price moves (50%+)", "ok" if not extreme else "warning", len(extreme),
        "none" if not extreme else "check before acting, often a parsing error: " +
        ", ".join(f"'{titles.get(c.item_id, c.item_id)}' {c.old_value} -> {c.new_value}" for c in extreme[:3]))
    return checks


def status(checks: list[Check]) -> str:
    worst = max((SEVERITY_ORDER[c.severity] for c in checks), default=0)
    return {0: "PASS", 1: "PASS WITH WARNINGS", 2: "FAIL"}[worst]
