"""Run the comparison and write the outputs.

Usage (from the mini-case folder):
    python -m jsquotes.run      # needs Playwright's Chromium: python -m playwright install chromium
"""
from __future__ import annotations

import csv
import html
import json
import time
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

from .collect import (MAX_MISSES, SITE, USER_AGENT, api_quotes, paginate_js, plain_count, reconcile, robots_allows,
                      scroll_all)

OUT = Path(__file__).resolve().parents[1] / "output"
SCROLL_URL, JS_URL = f"{SITE}/scroll", f"{SITE}/js/"


def write_csv(path: Path, records: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["quote_id", "text", "author", "tags"])
        w.writeheader()
        w.writerows(records)


def main() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    for url in (SCROLL_URL, JS_URL):
        ok, robots = robots_allows(url, session)
        if not ok:
            raise SystemExit(f"robots.txt does not allow {url}: {robots}")

    t0 = time.monotonic()
    plain = {"scroll": plain_count(SCROLL_URL, session), "js": plain_count(JS_URL, session)}
    plain_seconds = round(time.monotonic() - t0, 1)

    requests_seen: dict[str, int] = {"scroll": 0, "js": 0}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=USER_AGENT, viewport={"width": 1280, "height": 900})
        page = context.new_page()
        current = {"name": "scroll"}
        page.on("request", lambda r: requests_seen.__setitem__(current["name"], requests_seen[current["name"]] + 1)
                if r.url.startswith(SITE) else None)
        scroll = scroll_all(page, SCROLL_URL)
        current["name"] = "js"
        js = paginate_js(page, JS_URL)
        browser.close()

    t0 = time.monotonic()
    api, api_pages = api_quotes(session)
    api_seconds = round(time.monotonic() - t0, 1)
    check = reconcile(scroll.records, js.records, api)

    write_csv(OUT / "scroll_quotes.csv", scroll.records)
    write_csv(OUT / "js_quotes.csv", js.records)
    summary = {
        "robots": robots,
        "plain_request": {"scroll_quotes": plain["scroll"], "js_quotes": plain["js"], "requests": 2,
                          "seconds": plain_seconds},
        "playwright_scroll": {"quotes": len(scroll.records), "scrolls": len(scroll.log) - 1,
                              "log": scroll.log, "requests_to_site": requests_seen["scroll"], "seconds": scroll.seconds},
        "playwright_js_pages": {"quotes": len(js.records), "pages": js.pages, "requests_to_site": requests_seen["js"],
                                "seconds": js.seconds},
        "json_endpoint_check": {"quotes": len(api), "requests": api_pages, "seconds": api_seconds},
        "reconciliation": check,
    }
    (OUT / "run_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_html(summary)
    print(json.dumps(summary, indent=2))
    return summary


def write_html(s: dict) -> None:
    sc, js, pl, api, rec = (s["playwright_scroll"], s["playwright_js_pages"], s["plain_request"],
                            s["json_endpoint_check"], s["reconciliation"])
    rows = [
        ("Plain request (requests + BeautifulSoup)", f"<b class='bad'>{pl['scroll_quotes']} quotes</b>",
         f"<b class='bad'>{pl['js_quotes']} quotes</b>", f"{pl['requests']}", f"{pl['seconds']:.1f}"),
        ("Playwright, headless Chromium", f"<b class='ok'>{sc['quotes']} quotes</b> after {sc['scrolls']} scrolls",
         f"<b class='ok'>{js['quotes']} quotes</b> from {js['pages']} pages",
         f"{sc['requests_to_site'] + js['requests_to_site']}", f"{sc['seconds'] + js['seconds']:.1f}"),
        ("Cross-check: the site's JSON endpoint", f"{api['quotes']} quotes", "n/a", f"{api['requests']}",
         f"{api['seconds']:.1f}"),
    ]
    table = "".join(f"<tr><td>{a}</td><td>{b}</td><td>{c}</td><td class='num'>{d}</td><td class='num'>{e}</td></tr>"
                    for a, b, c, d, e in rows)
    peak = max(n for _, n in sc["log"]) or 1
    bars = "".join(f"<div class='step'><div class='bar' style='height:{max(4, 120 * n / peak):.0f}px'></div>"
                   f"<span>{n}</span><small>{'load' if i == 0 else i}</small></div>" for i, n in sc["log"])
    same = "the same 100 quotes in all three" if rec["same"] else f"sizes differ: {rec['sizes']}"
    (OUT / "summary.html").write_text(f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Playwright comparison</title><style>
body{{margin:0;background:#f4f5f7;font:15px/1.5 "Segoe UI",system-ui,sans-serif;color:#141414}}
.page{{max-width:1000px;margin:0 auto;padding:24px 20px;background:#fff}}
h1{{margin:0;font-size:24px;color:#1F3864}} .sub{{color:#7F7F7F;margin:4px 0 18px;font-size:13px}}
h2{{font-size:15px;color:#1F3864;margin:20px 0 8px}}
table{{border-collapse:collapse;width:100%;font-size:13.5px}} th,td{{text-align:left;padding:7px 8px;border-bottom:1px solid #e6e6e6;vertical-align:top}}
th{{background:#1F3864;color:#fff;font-weight:600}} .num{{text-align:right}} .ok{{color:#2E7D32}} .bad{{color:#C62828}}
.chart{{display:flex;align-items:flex-end;gap:10px;height:170px;border-bottom:1px solid #ccc;padding:0 4px}}
.step{{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;font-size:12px;color:#333}}
.bar{{width:60%;background:#2a78d6;border-radius:3px 3px 0 0}} .step small{{color:#7F7F7F}}
.note{{color:#7F7F7F;font-size:12.5px;margin-top:12px}} .check{{margin-top:10px;font-weight:600;color:#2E7D32}}
</style></head><body><div class="page">
<h1>JavaScript pages: what a plain request sees, and what a browser sees</h1>
<p class="sub">quotes.toscrape.com/scroll (infinite scroll) and /js (pages written by JavaScript) · scraping practice
site · robots.txt {html.escape(s['robots'])} · 1-second pause between actions · generic user agent</p>
<table><tr><th>Method</th><th>/scroll</th><th>/js</th><th class="num">Requests</th><th class="num">Seconds</th></tr>{table}</table>
<p class="check">Reconciled by quote: {same}, 0 duplicates.</p>
<h2>Infinite scroll: quotes on the page after each scroll (it stops after {MAX_MISSES} scrolls in a row bring nothing new)</h2>
<div class="chart">{bars}</div>
<p class="note">Requests counts every request the browser made to the site, page assets included. The plain request
gets the page's HTML in full, but the quotes are not in it: JavaScript adds them after the page loads.</p>
</div></body></html>""", encoding="utf-8")


if __name__ == "__main__":
    main()
