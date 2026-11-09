"""A simulated "next day" for the demo.

Practice sites never change, so a second live run would find nothing to report. The demo therefore
replays the archived pages of the live run and seeds realistic changes into them: price moves, a
misplaced decimal, stock-outs, products delisted and added, and one listing page that fails to load.
The seeded list is returned too, so tests can check that the detector finds every one of them.
"""
from __future__ import annotations

import random
from dataclasses import replace

from .collect import Collected
from .parse import Item

PLAN = {  # per store: how many of each change to seed
    "books": {"fail_page": None, "removed": 2, "new": 2, "down": 4, "up": 4, "extreme": 1, "out_of_stock": 3},
    "electronics": {"fail_page": ("laptops", 7), "removed": 1, "new": 1, "down": 2, "up": 2, "extreme": 0,
                    "out_of_stock": 0},
}
NEW_SUFFIX = {"books": " (Paperback)", "electronics": " (2026 edition)"}


def seed_changes(collected: dict[str, Collected], seed: int = 11
                 ) -> tuple[dict[str, Collected], list[tuple[str, str, str]]]:
    """Returns (changed copy of the run, seeded truth as (store, item_id, expected change))."""
    rng = random.Random(seed)
    out: dict[str, Collected] = {}
    seeded: list[tuple[str, str, str]] = []
    for store, run in collected.items():
        plan = PLAN.get(store)
        items = [replace(i) for i in run.items]
        pages = [replace(p) for p in run.pages]
        if not plan or not items:
            out[store] = Collected(items, pages)
            continue

        # 1. one listing page "times out": its products are not seen, through no fault of their own
        failed_category = None
        if plan["fail_page"]:
            failed_category, number = plan["fail_page"]
            page = next((p for p in pages if p.category == failed_category and p.page == number and p.ok), None)
            if page:
                lost = [i for i in items if i.source_url == page.url]
                items = [i for i in items if i.source_url != page.url]
                page.ok, page.items = False, 0
                page.error = "TimeoutException: product grid did not load within 15 s (simulated)"
                seeded += [(store, i.item_id, "not_seen") for i in lost]

        # 2. products delisted, picked from categories whose pages all loaded
        candidates = [i for i in items if i.category != failed_category]
        for gone in rng.sample(candidates, plan["removed"]):
            items.remove(gone)
            seeded.append((store, gone.item_id, "removed"))

        # 3. price moves and stock-outs on distinct products
        pool = rng.sample([i for i in items if i.price_cents], plan["down"] + plan["up"] + plan["extreme"])
        for n, item in enumerate(pool):
            if n < plan["down"]:
                item.price_cents = round(item.price_cents * (1 - rng.uniform(0.05, 0.25)))
                seeded.append((store, item.item_id, "price_down"))
            elif n < plan["down"] + plan["up"]:
                item.price_cents = round(item.price_cents * (1 + rng.uniform(0.05, 0.20)))
                seeded.append((store, item.item_id, "price_up"))
            else:
                item.price_cents *= 10  # a misplaced decimal on the site: the quality report must flag it
                seeded.append((store, item.item_id, "price_up"))
            item.price_text = f"{item.price_cents / 100:.2f}"
        in_stock = [i for i in items if i.in_stock and i not in pool]
        for item in rng.sample(in_stock, plan["out_of_stock"]):
            item.in_stock = False
            seeded.append((store, item.item_id, "out_of_stock"))

        # 4. new arrivals, modelled on an existing product and clearly marked as simulated
        for n in range(plan["new"]):
            base = rng.choice(candidates)
            new_id = f"9{n + 1:03d}"
            items.append(Item(
                store=store, category=base.category, item_id=new_id, title=base.title + NEW_SUFFIX.get(store, ""),
                url=f"{base.source_url.split('#')[0]}#simulated-new-{new_id}",
                price_cents=base.price_cents, price_text=base.price_text, in_stock=base.in_stock,
                rating=None, reviews=0 if base.reviews is not None else None, source_url=base.source_url,
            ))
            seeded.append((store, new_id, "new"))
        out[store] = Collected(items, pages)
    return out, seeded
