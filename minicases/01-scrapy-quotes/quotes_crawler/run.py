"""Run the spider and write a summary of the run next to the CSV feeds.

Usage (from the mini-case folder):
    python -m quotes_crawler.run      # same as `scrapy crawl quotes`, plus run_summary.json and summary.html
"""
from __future__ import annotations

import html
import json

import pandas as pd
from scrapy.crawler import CrawlerProcess
from scrapy.settings import Settings

from .settings import OUT
from .spiders.quotes import QuotesSpider


def summarize(stats: dict) -> dict:
    quotes = pd.read_csv(OUT / "quotes.csv")
    authors = pd.read_csv(OUT / "authors.csv")
    s = {
        "quotes": len(quotes), "authors": len(authors),
        "quote_items_yielded": len(quotes) + stats.get("pipeline/dropped/duplicate/quote", 0),
        "duplicate_quotes_dropped": stats.get("pipeline/dropped/duplicate/quote", 0),
        "invalid_dropped": sum(v for k, v in stats.items() if k.startswith("pipeline/dropped/invalid/")),
        "pages_list": stats.get("pages/list", 0), "pages_tag": stats.get("pages/tag", 0),
        "pages_author": stats.get("pages/author", 0),
        "requests": stats.get("downloader/request_count", 0),
        "responses_200": stats.get("downloader/response_status_count/200", 0),
        "robots_requests": stats.get("robotstxt/request_count", 0),
        "robots_status": ", ".join(f"HTTP {k.rsplit('/', 1)[1]}" for k in stats
                                   if k.startswith("robotstxt/response_status_count/")),
        "dupefilter_filtered": stats.get("dupefilter/filtered", 0),
        "errors": stats.get("log_count/ERROR", 0),
        "seconds": round(stats.get("elapsed_time_seconds", 0), 1),
        "missing_authors": int((~quotes["author_url"].isin(authors["url"])).sum()),
    }
    sample = quotes.merge(authors, left_on="author_url", right_on="url", how="left").head(6)
    return s, sample


def write_html(s: dict, sample: pd.DataFrame) -> None:
    rows = "".join(f"<tr><td>{html.escape(r.text[:75] + ('…' if len(r.text) > 75 else ''))}</td>"
                   f"<td>{html.escape(r.author)}</td><td class='nw'>{r.born_date}</td><td>{html.escape(str(r.born_location))}</td></tr>"
                   for r in sample.itertuples())
    kpis = [(s["quotes"], "unique quotes"), (s["authors"], "author pages, joined to every quote"),
            (s["requests"], "requests, robots.txt included"), (f"{s['seconds']:.0f} s", "with AutoThrottle")]
    flow = [
        ("Pages read", f"{s['pages_list']} list pages, {s['pages_tag']} tag pages, {s['pages_author']} author pages"),
        ("Quote items yielded", f"{s['quote_items_yielded']:,}"),
        ("Dropped as duplicates", f"{s['duplicate_quotes_dropped']:,} (the tag pages repeat quotes from the list)"),
        ("Dropped as invalid", f"{s['invalid_dropped']:,}"),
        ("Saved", f"{s['quotes']} quotes · {s['authors']} authors · {s['missing_authors']} quotes without their author"),
        ("Author links followed once", f"{s['dupefilter_filtered']:,} repeat requests skipped by Scrapy's duplicate filter"),
        ("robots.txt", f"read first ({s['robots_status'] or 'no answer'}: nothing disallowed) and obeyed"),
        ("Errors", f"{s['errors']}"),
    ]
    kpi_html = "".join(f'<div class="kpi"><b>{v}</b><span>{t}</span></div>' for v, t in kpis)
    flow_html = "".join(f"<tr><td>{a}</td><td>{html.escape(b)}</td></tr>" for a, b in flow)
    (OUT / "summary.html").write_text(f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Scrapy run summary</title><style>
body{{margin:0;background:#f4f5f7;font:15px/1.5 "Segoe UI",system-ui,sans-serif;color:#141414}}
.page{{max-width:1000px;margin:0 auto;padding:24px 20px;background:#fff}}
h1{{margin:0;font-size:24px;color:#1F3864}} .sub{{color:#7F7F7F;margin:4px 0 18px;font-size:13px}}
.kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:8px}}
.kpi{{border:1px solid #e3e3e3;border-radius:8px;padding:10px 12px}} .kpi b{{display:block;font-size:22px;color:#1F3864}}
.kpi span{{font-size:12.5px;color:#555}} h2{{font-size:15px;color:#1F3864;margin:18px 0 6px}}
table{{border-collapse:collapse;width:100%;font-size:13.5px}} th,td{{text-align:left;padding:6px 8px;border-bottom:1px solid #e6e6e6;vertical-align:top}}
th{{background:#1F3864;color:#fff;font-weight:600}} td:first-child{{white-space:nowrap;color:#333}}
.note{{color:#7F7F7F;font-size:12px;margin-top:12px}} .nw{{white-space:nowrap}}
</style></head><body><div class="page">
<h1>Scrapy crawl: quotes and their authors</h1>
<p class="sub">quotes.toscrape.com (scraping practice site) · list pages → author pages, plus the top-ten tag pages ·
ROBOTSTXT_OBEY, AutoThrottle, 1-second delay, generic user agent</p>
<div class="kpis">{kpi_html}</div>
<h2>Pipeline: clean → validate → drop duplicates</h2><table>{flow_html}</table>
<h2>Sample of the output (quotes.csv joined to authors.csv)</h2>
<table><tr><th>Quote</th><th>Author</th><th>Born</th><th>Place</th></tr>{rows}</table>
<p class="note">Author biographies are not collected: name, birth date and place are enough to join on.</p>
</div></body></html>""", encoding="utf-8")


def main() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    settings = Settings()
    settings.setmodule("quotes_crawler.settings")
    process = CrawlerProcess(settings)
    crawler = process.create_crawler(QuotesSpider)
    process.crawl(crawler)
    process.start()
    stats = crawler.stats.get_stats()
    s, sample = summarize(stats)
    (OUT / "run_summary.json").write_text(json.dumps(s, indent=2), encoding="utf-8")
    write_html(s, sample)
    print(json.dumps(s, indent=2))
    return s


if __name__ == "__main__":
    main()
