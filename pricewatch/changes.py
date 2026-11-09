"""Change detection: compare what this run saw with the last known state of each product.

Change types
    new            first time the product appears in this store
    returned       a product we had marked as removed is listed again
    price_down     price lower than the last price we saw (pct = relative change)
    price_up       price higher than the last price we saw
    out_of_stock   was in stock, now listed as unavailable
    back_in_stock  was unavailable, now in stock
    removed        missing, and the rule below is confident it is really gone
    not_seen       missing, but the evidence is not strong enough to call it removed (yet)
"""
from __future__ import annotations

from dataclasses import dataclass

from .parse import Item
from .store import ItemState


@dataclass(frozen=True)
class Change:
    store: str
    item_id: str
    change: str
    old_value: str | None = None
    new_value: str | None = None
    pct: float | None = None


MAX_MISSES = 3  # consecutive misses after which a product counts as removed even if pages keep failing


def _money(cents: int | None) -> str | None:
    return None if cents is None else f"{cents / 100:.2f}"


def missing_status(coverage: float, misses: int) -> str:
    """Decide what a product that was NOT seen in this run means. Return "removed" or "not_seen".

    coverage  share of its category's listing pages that loaded in this run (1.0 = every page loaded)
    misses    consecutive runs it has been missing, this run included (1 = first time we miss it)
    """
    if coverage >= 1.0:
        return "removed"  # every page of its category loaded and it was on none of them
    # Some pages failed: the product may be on one of them. Hold it, unless it has been missing for
    # several runs in a row, which a single flaky page cannot explain.
    return "removed" if misses >= MAX_MISSES else "not_seen"


def detect_changes(store: str, previous: dict[str, ItemState], current: list[Item],
                   coverage: dict[str, float]) -> list[Change]:
    """previous: last known state per product (store.previous_state). current: this run, deduplicated.
    coverage: category -> share of listing pages loaded in this run."""
    if not previous:
        return []  # first run of a store is the baseline: everything is "new", which says nothing
    changes: list[Change] = []
    seen = set()
    for item in current:
        seen.add(item.item_id)
        before = previous.get(item.item_id)
        if before is None:
            changes.append(Change(store, item.item_id, "new", None, _money(item.price_cents)))
            continue
        if before.removed:
            changes.append(Change(store, item.item_id, "returned", None, _money(item.price_cents)))
        if None not in (before.price_cents, item.price_cents) and before.price_cents != item.price_cents:
            pct = (item.price_cents - before.price_cents) / before.price_cents if before.price_cents else None
            kind = "price_up" if item.price_cents > before.price_cents else "price_down"
            changes.append(Change(store, item.item_id, kind, _money(before.price_cents),
                                  _money(item.price_cents), pct))
        if None not in (before.in_stock, item.in_stock) and before.in_stock != item.in_stock:
            kind = "back_in_stock" if item.in_stock else "out_of_stock"
            changes.append(Change(store, item.item_id, kind, str(before.in_stock), str(item.in_stock)))
    for item_id, before in previous.items():
        if item_id in seen or before.removed:
            continue
        status = missing_status(coverage.get(before.category, 0.0), before.misses + 1)
        changes.append(Change(store, item_id, status, _money(before.price_cents), None))
    return changes


def coverage_by_category(pages: list) -> dict[str, float]:
    """category -> loaded pages / planned pages, from the page log of one store in one run."""
    totals: dict[str, list[int]] = {}
    for p in pages:
        ok_total = totals.setdefault(p.category, [0, 0])
        ok_total[0] += int(p.ok)
        ok_total[1] += 1
    return {cat: ok / total for cat, (ok, total) in totals.items()}
