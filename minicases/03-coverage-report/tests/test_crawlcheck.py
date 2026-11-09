"""Coverage crawler, tested offline: saved pages from the real site and a small fake site."""
from pathlib import Path

import pytest
import requests

from crawlcheck import state
from crawlcheck.crawl import crawl
from crawlcheck.parse import ParseError, classify, parse_book, parse_listing
from crawlcheck.polite import FetchError, PoliteClient
from crawlcheck.report import summary, tables, write_report

FIXTURES = Path(__file__).parent / "fixtures"
SITE = "https://books.toscrape.com"
START = f"{SITE}/catalogue/page-1.html"


# --------------------------------------------------------------------------- parsers on real pages
def test_listing_page_gives_links_announced_total_and_page_count():
    links, announced, pages = parse_listing((FIXTURES / "listing_page.html").read_text("utf-8"), START)
    assert (announced, pages) == (1000, 50)
    books = {u for u in links if classify(u) == "book"}
    assert len(books) == 20  # each book is linked twice (cover and title): 40 links, 20 URLs
    assert sum(classify(u) == "book" for u in links) == 40
    assert {classify(u) for u in links} == {"home", "category", "book", "listing"}


def test_book_page_becomes_a_complete_record():
    url = f"{SITE}/catalogue/a-light-in-the-attic_1000/index.html"
    rec = parse_book((FIXTURES / "book_page.html").read_text("utf-8"), url)
    assert rec == {"url": url, "upc": "a897fe39b1053632", "title": "A Light in the Attic", "category": "Poetry",
                   "price_cents": 5177, "stock": 22, "rating": 3, "reviews": 0}


def test_a_book_page_without_its_price_is_a_parse_error_not_a_blank_field():
    html = (FIXTURES / "book_page.html").read_text("utf-8").replace('<p class="price_color">£51.77</p>', "", 1)
    with pytest.raises(ParseError, match="price not found"):
        parse_book(html, f"{SITE}/catalogue/x_1/index.html")


# --------------------------------------------------------------------------- a small fake site
def listing(n: int, of: int, books: list[str], announced: int) -> str:
    links = "".join(f'<a href="{b}/index.html">c</a><h3><a href="{b}/index.html">t</a></h3>' for b in books)
    nxt = f'<li class="next"><a href="page-{n + 1}.html">next</a></li>' if n < of else ""
    return (f'<a href="../index.html">Home</a><a href="category/books/poetry_23/index.html">Poetry</a>'
            f'<form class="form-horizontal"><strong>{announced}</strong> results</form>{links}'
            f'<li class="current">Page {n} of {of}</li>{nxt}')


def book(title: str, upc: str, price: str = "£10.00") -> str:
    return (f'<ul class="breadcrumb"><li>Home</li><li>Books</li><li>Poetry</li><li>{title}</li></ul>'
            f'<div class="product_main"><h1>{title}</h1><p class="price_color">{price}</p>'
            f'<p class="instock availability">In stock (3 available)</p><p class="star-rating Two"></p></div>'
            f'<table class="table"><tr><th>UPC</th><td>{upc}</td></tr>'
            f'<tr><th>Number of reviews</th><td>0</td></tr></table>')


def fake_site(robots: str | None = None) -> dict:
    pages = {
        f"{SITE}/catalogue/page-1.html": listing(1, 2, ["a_1", "b_2"], 3),
        f"{SITE}/catalogue/page-2.html": listing(2, 2, ["c_3"], 3),
        f"{SITE}/catalogue/a_1/index.html": book("A", "0" * 15 + "1"),
        f"{SITE}/catalogue/b_2/index.html": book("B", "0" * 15 + "2"),
        f"{SITE}/catalogue/c_3/index.html": book("C", "0" * 15 + "3"),
    }
    if robots is not None:
        pages[f"{SITE}/robots.txt"] = robots
    return pages


class Resp:
    def __init__(self, status, text=""):
        self.status_code, self.text, self.headers = status, text, {"Content-Type": "text/html; charset=utf-8"}


class Killed(BaseException):
    """Stands in for the process being killed: not an Exception, so nothing catches it."""


class FakeSession:
    def __init__(self, pages: dict, kill_after: int | None = None, flaky: dict | None = None):
        self.pages, self.kill_after, self.flaky = pages, kill_after, dict(flaky or {})
        self.calls: list[str] = []
        self.headers = {}

    def get(self, url, timeout=None):
        if not url.endswith("robots.txt"):
            if self.kill_after is not None and len(self.calls) >= self.kill_after:
                raise Killed
            self.calls.append(url)
            if self.flaky.get(url, 0) > 0:
                self.flaky[url] -= 1
                raise requests.Timeout("slow")
        return Resp(200, self.pages[url]) if url in self.pages else Resp(404, "not found")


def run_once(con, session, inject=False):
    run_id = state.start_run(con)
    crawl(con, PoliteClient(delay=0, backoff=0, session=session), run_id, inject=inject, log=lambda _: None,
          start_url=START)
    state.finish_run(con, run_id)
    return run_id


@pytest.fixture
def con():
    c = state.connect(":memory:")
    yield c
    c.close()


def test_every_discovered_url_ends_collected_failed_or_excluded(con):
    run_once(con, FakeSession(fake_site()))
    s = summary(con, tables(con))
    assert s["pending"] == 0 and s["reconciles"]
    assert (s["discovered"], s["collected"], s["failed"], s["excluded"]) == (7, 5, 0, 2)  # 2 listings + 3 books
    reasons = dict(con.execute("SELECT kind, reason FROM urls WHERE status = 'excluded'").fetchall())
    assert reasons == {"home": "out of scope: home page", "category": "out of scope: category page"}
    assert s["records"] == s["books_announced"] == 3


def test_dead_link_and_template_change_are_caught_with_their_reason(con, monkeypatch):
    monkeypatch.setattr("crawlcheck.crawl.INJECTED_DEAD_LINK_ON", f"{SITE}/catalogue/page-2.html")
    monkeypatch.setattr("crawlcheck.crawl.INJECTED_DEAD_LINK", f"{SITE}/catalogue/gone_9/index.html")
    monkeypatch.setattr("crawlcheck.crawl.INJECTED_LAYOUT_CHANGE_SUFFIX", "_2/index.html")
    session = FakeSession(fake_site())
    run_once(con, session, inject=True)
    failed = {r["url"]: (r["reason"], r["attempts"]) for r in con.execute(
        "SELECT url, reason, attempts FROM urls WHERE status = 'failed'")}
    assert failed == {f"{SITE}/catalogue/gone_9/index.html": ("HTTP 404", 1),  # a 404 is not retried
                      f"{SITE}/catalogue/b_2/index.html": ("parse error: price not found", 1)}
    s = summary(con, tables(con))
    assert s["reconciles"] and s["records"] == 2 and s["book_urls"] == 4


def test_killed_run_resumes_without_losing_or_duplicating_records(con):
    with pytest.raises(Killed):
        run_once(con, FakeSession(fake_site(), kill_after=3))  # killed during its 4th request
    assert con.execute("SELECT COUNT(*) FROM books").fetchone()[0] == 1
    second = FakeSession(fake_site())
    run_once(con, second)
    s = summary(con, tables(con))
    assert s["reconciles"] and s["records"] == 3 and s["duplicate_upcs"] == 0
    assert s["requested_twice"] == 0  # nothing saved by run 1 was requested again
    assert len(second.calls) == 2      # only the page in flight and the one never reached
    assert [r[0] for r in con.execute("SELECT status FROM runs ORDER BY run_id")] == ["interrupted", "completed"]


def test_robots_txt_exclusions_are_reported_and_never_requested(con):
    session = FakeSession(fake_site(robots="User-agent: *\nDisallow: /catalogue/c_3/\n"))
    run_once(con, session)
    row = con.execute("SELECT status, reason FROM urls WHERE url LIKE '%c_3%'").fetchone()
    assert tuple(row) == ("excluded", "disallowed by robots.txt")
    assert not any("c_3" in u for u in session.calls)
    assert summary(con, tables(con))["reconciles"]


def test_timeouts_are_retried_and_a_second_url_for_the_same_book_is_flagged(con):
    pages = fake_site()
    pages[f"{SITE}/catalogue/page-2.html"] = listing(2, 2, ["c_3", "c-again_4"], 3)
    pages[f"{SITE}/catalogue/c-again_4/index.html"] = book("C", "0" * 15 + "3")  # same UPC as c_3
    run_once(con, FakeSession(pages, flaky={f"{SITE}/catalogue/a_1/index.html": 2}))
    a = con.execute("SELECT status, attempts FROM urls WHERE url LIKE '%a_1%'").fetchone()
    assert tuple(a) == ("collected", 3)
    dup = con.execute("SELECT status, reason FROM urls WHERE url LIKE '%c-again_4%'").fetchone()
    assert dup["status"] == "failed" and dup["reason"].startswith("duplicate record: same UPC as")
    assert con.execute("SELECT COUNT(*) FROM books").fetchone()[0] == 3


def test_retries_give_up_with_a_clear_reason():
    client = PoliteClient(delay=0, backoff=0, session=FakeSession({}, flaky={f"{SITE}/x": 5}))
    with pytest.raises(FetchError, match="timeout after 3 attempts"):
        client.get(f"{SITE}/x")


def test_report_files_are_written(con, tmp_path):
    run_once(con, FakeSession(fake_site()))
    s = write_report(con, tmp_path)
    assert s["reconciles"]
    assert {p.name for p in tmp_path.iterdir()} == {"coverage.csv", "books.csv", "coverage_report.xlsx"}
