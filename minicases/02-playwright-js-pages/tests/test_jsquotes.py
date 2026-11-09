"""Offline tests. The browser tests run real Chromium against fake pages served by Playwright's router."""
import json
from pathlib import Path

import pytest

from jsquotes.collect import SITE, count_quotes, paginate_js, parse_api, reconcile, scroll_all

FIXTURES = Path(__file__).parent / "fixtures"


# --------------------------------------------------------------------------- without a browser
def test_plain_html_of_both_pages_has_no_quotes():
    assert count_quotes((FIXTURES / "scroll.html").read_text("utf-8")) == 0
    assert count_quotes((FIXTURES / "js_page_1.html").read_text("utf-8")) == 0


def test_api_payload_becomes_clean_records():
    records = parse_api(json.loads((FIXTURES / "api_page_1.json").read_text("utf-8")))
    assert len(records) == 10
    assert records[0]["author"] == "Albert Einstein"
    assert records[0]["text"].startswith("The world as we have created it")  # curly quotes stripped
    assert records[0]["tags"] == "change,deep-thoughts,thinking,world"


def test_reconcile_compares_by_quote_not_by_count():
    a = [{"quote_id": "1"}, {"quote_id": "2"}]
    assert reconcile(a, list(reversed(a))) == {"same": True, "sizes": [2, 2], "duplicates": [0, 0]}
    assert not reconcile(a, [{"quote_id": "1"}, {"quote_id": "3"}])["same"]


# --------------------------------------------------------------------------- with a browser
def quote_div(n: int) -> str:
    return (f"<div class='quote' style='height:150px'><span class='text'>“Quote {n}”</span>"
            f"<span>by <small class='author'>Author {n % 3}</small></span>"
            f"<div class='tags'>Tags: <a class='tag'>t{n}</a></div></div>")


SCROLL_PAGE = """<!doctype html><html><body style="margin:0"><div class="quotes"></div><script>
let page = 0, hasNext = true, busy = false;
async function more() {
  if (!hasNext || busy) return; busy = true; page += 1;
  const data = await (await fetch('/api/fake?page=' + page)).json();
  document.querySelector('.quotes').insertAdjacentHTML('beforeend', data.html);
  hasNext = data.has_next; busy = false;
}
more();
window.addEventListener('scroll', () => {
  if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2) more();
});
</script></body></html>"""


def js_page(n: int, last: int) -> str:
    items = ",".join(json.dumps(quote_div(i)) for i in range((n - 1) * 3, n * 3))
    nxt = f'<li class="next"><a href="/js/page/{n + 1}/">Next</a></li>' if n < last else ""
    return f"<html><body><script>[{items}].forEach(h => document.write(h));</script><ul>{nxt}</ul></body></html>"


@pytest.fixture(scope="module")
def browser():
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"Chromium not installed for Playwright: {exc}")
        yield b
        b.close()


def serve(page, routes: dict):
    calls = []

    def handler(route):
        url = route.request.url
        calls.append(url)
        body, ctype = routes.get(url, ("not found", "text/plain"))
        route.fulfill(status=200 if url in routes else 404, body=body, content_type=ctype)

    page.route(f"{SITE}/**", handler)
    return calls


def test_scroll_continues_until_nothing_new_arrives(browser):
    page = browser.new_page(viewport={"width": 800, "height": 600})
    routes = {f"{SITE}/scroll": (SCROLL_PAGE, "text/html")}
    for n in (1, 2, 3, 4):  # 4 batches of 6 quotes, then has_next = false
        html = "".join(quote_div(i) for i in range((n - 1) * 6, n * 6))
        routes[f"{SITE}/api/fake?page={n}"] = (json.dumps({"html": html, "has_next": n < 4}), "application/json")
    calls = serve(page, routes)
    run = scroll_all(page, f"{SITE}/scroll", pause=0.05, wait_new=1500)
    assert len(run.records) == 24 and len({r["quote_id"] for r in run.records}) == 24
    assert [n for _, n in run.log] == [6, 12, 18, 24, 24, 24]  # two scrolls with nothing new, then stop
    assert sum("/api/fake" in c for c in calls) == 4             # never asks past the last batch
    page.close()


def test_javascript_pages_are_rendered_and_followed_to_the_last_one(browser):
    page = browser.new_page()
    routes = {f"{SITE}/js/": (js_page(1, 3), "text/html")}
    routes.update({f"{SITE}/js/page/{n}/": (js_page(n, 3), "text/html") for n in (2, 3)})
    serve(page, routes)
    run = paginate_js(page, f"{SITE}/js/", pause=0)
    assert run.pages == 3 and len(run.records) == 9
    assert run.records[0]["text"] == "Quote 0" and run.records[0]["author"] == "Author 0"
    page.close()
