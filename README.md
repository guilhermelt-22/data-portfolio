# Finance data for finance teams without a data team

**Guilherme Teófilo**, finance data analyst. I help CFOs, controllers and FP&A consultants at startups and
mid-sized companies close faster and trust their numbers: month-end reporting automation, budget vs actual
dashboards, and one clean model for ledger, budget and actuals.

3+ years building FP&A and controllership data at a multinational financial services company and at
Adapta, a fast-growing AI scale-up. BSc in Computer Science. Fluent English (EF SET C2).

## Case studies

Cases 01 to 03 run on the same engine and the same **fictitious** dataset: Kestrel Group, a 3-entity SaaS
company whose ledgers come from QuickBooks-, Xero- and DATEV-style exports ([dataset notes](data/README.md)).
Case 04 collects its data from the web, from two sites built for scraping practice.

| Case | What it shows | Result on the demo data |
|---|---|---|
| [**01 · Month-end reporting automation**](cases/01-month-end-reporting-automation/README.md) | 3 accounting-system exports become a validated, consolidated management pack in Excel, with variance commentary drafted from reconciled numbers | From a typical 1.5 to 2 days of manual work to **~5 seconds**; **6 of 6** seeded data issues caught, each with file and line |
| [**02 · Budget vs actual dashboard**](cases/02-budget-vs-actual-dashboard/README.md) | A one-page dashboard a CFO opens from a link, plus BI-ready tables for Looker Studio or Power BI | FX separated from operational variance; mis-tagged cost flagged instead of reported as a saving |
| [**03 · Finance data foundation**](cases/03-finance-data-foundation/README.md) | The SQL model underneath: account and department mapping, FX, intercompany elimination, plan vs actual | **11 automated tests**, including budget vs actual reconciling to its inputs to the cent |
| [**04 · Price and catalog monitor**](cases/04-price-and-catalog-monitor/README.md) | Web scraping as a recurring system: static pages (requests + BeautifulSoup) and AJAX pages (Selenium), history without duplicates, change detection and a data quality report per run | **1,147 products** from 76 pages in 82 seconds; **28 of 28** seeded changes detected, and **0 false removals** when a page fails to load |

![Budget vs actual dashboard](cases/02-budget-vs-actual-dashboard/img/dashboard.png)

## Run it yourself

```bash
pip install -e .[dev]
python data/generate.py                        # build the fictitious dataset
python -m findata.report --period 2026-10      # case 01: Excel management pack
python -m findata.dashboard --period 2026-10   # case 02: dashboard + BI tables
python -m pricewatch.demo                      # case 04: live crawl + simulated next day (~2 min, needs Chrome)
pytest                                         # 30 tests, all offline
```

Outputs land in [`output/2026-10/`](output/2026-10/) and [`output/pricewatch/`](output/pricewatch/).

**Stack:** Python, SQL (DuckDB, SQLite), pandas, Plotly, Excel (xlsxwriter), requests, BeautifulSoup,
Selenium, pytest. The finance engine starts from plain CSV/Excel exports, so it works with any ERP or
accounting system.

## Working together

I take fixed-scope projects and monthly support for finance teams. Each case study shows the kind of
deliverable you get: working code, documentation and a recorded walkthrough.

---
<sub>All companies, people and figures in this repository are fictitious. Before/after timings: "after" is
measured on the demo data; "before" is an estimate of a typical manual process.</sub>
