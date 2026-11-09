"""Recurring runs: no duplicates, the right changes, an honest quality report and a readable workbook."""
from openpyxl import load_workbook

from pricewatch import store as db
from pricewatch.collect import Collected, PageLog
from pricewatch.parse import Item
from pricewatch.quality import run_checks, status
from pricewatch.report import write_report
from pricewatch.run import process_run


def item(item_id, price=1000, stock=True, page=1, category="all books", store="books"):
    return Item(store, category, str(item_id), f"Product {item_id}", f"https://shop.test/p/{item_id}",
                price, f"£{price / 100:.2f}" if price else "", stock, source_url=f"https://shop.test/page-{page}")


def pages(n=2, failed=(), category="all books", store="books"):
    return [PageLog(store, category, p, f"https://shop.test/page-{p}", p not in failed,
                    0 if p in failed else 2, "Timeout" if p in failed else "") for p in range(1, n + 1)]


def run(con, items, page_log=None, store="books"):
    run_id = db.start_run(con, "2026-11-08T21:00:00Z", "live")
    process_run(con, run_id, {store: Collected(items, page_log or pages())})
    return run_id


def changes(con, run_id):
    return sorted((r["item_id"], r["change"]) for r in
                  con.execute("SELECT item_id, change FROM changes WHERE run_id = ?", (run_id,)))


def test_reprocessing_a_run_and_repeated_listings_never_duplicate_rows():
    con = db.connect(":memory:")
    items = [item(1), item(2), item(1, page=2)]  # product 1 listed on two pages
    run_id = run(con, items)
    tables = ["items", "observations", "pages", "quality"]
    before = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
    process_run(con, run_id, {"books": Collected(items, pages())})  # e.g. a retry after a crash
    after = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
    assert before == after and before["observations"] == 2
    dupes = con.execute("SELECT count FROM quality WHERE check_name = 'Duplicates collapsed'").fetchone()[0]
    assert dupes == 1


def test_first_run_is_a_baseline_and_later_runs_report_price_stock_and_new_items():
    con = db.connect(":memory:")
    assert changes(con, run(con, [item(1, 5177), item(2, 2000), item(3, 900, stock=True)])) == []
    second = run(con, [item(1, 5177), item(2, 1850), item(3, 900, stock=False), item(4, 1500)])
    assert changes(con, second) == [("2", "price_down"), ("3", "out_of_stock"), ("4", "new")]
    pct = con.execute("SELECT pct FROM changes WHERE item_id = '2'").fetchone()[0]
    assert round(pct, 4) == -0.075


def test_price_is_compared_with_the_last_price_seen_even_after_a_missed_run():
    con = db.connect(":memory:")
    run(con, [item(1, 1000), item(2, 500, page=2)])
    run(con, [item(1, 1000)], pages(failed=(2,)))          # product 2 not seen: its page failed
    third = run(con, [item(1, 1000), item(2, 450, page=2)])
    assert ("2", "price_down") in changes(con, third)


def test_a_missing_product_is_removed_only_when_every_page_loaded_or_after_three_misses():
    con = db.connect(":memory:")
    run(con, [item(1), item(2, page=2), item(3)])
    second = run(con, [item(1)], pages(failed=(2,)))  # 3 gone (page 1 loaded), 2 unseen (page 2 failed)
    assert changes(con, second) == [("2", "not_seen"), ("3", "not_seen")]  # coverage 50%: nothing is called removed
    third = run(con, [item(1), item(2, page=2)])      # all pages load: 2 is back, 3 is confirmed gone
    assert changes(con, third) == [("3", "removed")]
    fourth = run(con, [item(1), item(2, page=2)])     # a removed product is not reported again
    assert changes(con, fourth) == []


def test_a_product_missing_three_runs_in_a_row_is_removed_even_if_pages_keep_failing():
    con = db.connect(":memory:")
    run(con, [item(1), item(2, page=2)])
    flaky = pages(failed=(2,))
    assert [changes(con, run(con, [item(1)], flaky)) for _ in range(3)] == [
        [("2", "not_seen")], [("2", "not_seen")], [("2", "removed")]]


def test_every_seeded_change_of_the_demo_is_detected_and_a_failed_page_removes_nothing():
    from pricewatch.simulate import seed_changes

    def shop(store, categories):
        out = Collected([], [])
        for category, n_pages, per_page in categories:
            for p in range(1, n_pages + 1):
                url = f"https://shop.test/{store}/{category}#page={p}"
                out.pages.append(PageLog(store, category, p, url, True, per_page))
                out.items += [Item(store, category, f"{category[:2]}{p}-{k}", f"{category} {p}-{k}",
                                   f"https://shop.test/p/{category}{p}-{k}", 1000 + 37 * k + p,
                                   "", True if store == "books" else None, source_url=url)
                              for k in range(per_page)]
        return out

    baseline = {"books": shop("books", [("all books", 3, 20)]),
                "electronics": shop("electronics", [("laptops", 8, 6), ("tablets", 2, 6), ("phones", 2, 6)])}
    con = db.connect(":memory:")
    run1 = db.start_run(con, "2026-11-08T21:00:00Z", "live")
    process_run(con, run1, baseline)
    changed, seeded = seed_changes(baseline)
    run2 = db.start_run(con, "2026-11-09T21:00:00Z", "simulated", source_run=run1)
    process_run(con, run2, changed)

    found = {(r["store"], r["item_id"], r["change"]) for r in
             con.execute("SELECT store, item_id, change FROM changes WHERE run_id = ?", (run2,))}
    assert set(seeded) == found                       # every seeded change, and nothing else
    assert sum(c == "not_seen" for *_, c in seeded) == 6
    flagged = con.execute("SELECT count FROM quality WHERE run_id = ? AND check_name LIKE 'Extreme%' "
                          "AND store = 'books'", (run2,)).fetchone()[0]
    assert flagged == 1                               # the misplaced decimal is flagged for review


def test_quality_report_flags_failed_pages_missing_prices_and_extreme_moves():
    from pricewatch.changes import Change
    checks = run_checks("books", pages(10, failed=(4,)), [item(1, None), item(2)], 0, 2,
                        [Change("books", "2", "price_up", "5.17", "51.70", 9.0)])
    by_name = {c.name: c for c in checks}
    assert by_name["Listing pages loaded"].severity == "warning"     # 9 of 10 pages
    assert by_name["Price parsed"].severity == "error"
    assert by_name["Extreme price moves (50%+)"].count == 1
    assert status(checks) == "FAIL"


def test_report_has_the_five_sheets_and_csv_outputs(tmp_path):
    con = db.connect(":memory:")
    run(con, [item(1, 1000), item(2, 2000)])
    second = run(con, [item(1, 900), item(2, 2000), item(3, 100)])
    paths = write_report(con, second, tmp_path)
    assert load_workbook(paths["xlsx"]).sheetnames == ["Summary", "Changes", "Catalog", "Data quality", "Runs"]
    assert paths["changes"].read_text("utf-8").count("\n") == 3  # header + price_down + new
