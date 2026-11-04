"""Generate the synthetic Kestrel Group finance dataset.

Kestrel Group is a FICTITIOUS B2B SaaS company with three legal entities.
Every name, customer, vendor, FX rate and number in this dataset is synthetic.

What it writes
--------------
data/raw/      one general-ledger export per entity, each in the shape of a
               typical accounting system (QuickBooks-style, Xero-style and a
               German DATEV-style booking batch), the FY2026 budget workbook
               and monthly FX rates.
config/        the chart-of-accounts, department and budget-line mappings that
               a finance-data analyst would build when onboarding the client.

Data-quality issues are seeded on purpose and documented in data/README.md.
The output is deterministic: same seed, same files.

Usage:  python data/generate.py
"""
from __future__ import annotations

import calendar
import csv
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import xlsxwriter
from xlsxwriter.utility import xl_col_to_name

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
CONFIG = ROOT / "config"
SEED = 20261103

FIRST = pd.Period("2025-01", "M")
LAST = pd.Period("2026-10", "M")  # the month being closed in the demo
PERIODS = pd.period_range(FIRST, LAST, freq="M")
BUDGET_PERIODS = pd.period_range("2026-01", "2026-12", freq="M")

DEPTS = ["SAL", "MKT", "RND", "CS", "GA"]
GROUP_DEPTS = {"SAL": "Sales", "MKT": "Marketing", "RND": "R&D", "CS": "Customer Success", "GA": "G&A"}

# --------------------------------------------------------------------------- charts of accounts
GROUP_COA = [  # code, name, type, statement line
    ("1000", "Cash", "asset", "Cash"),
    ("1100", "Accounts Receivable", "asset", "Accounts Receivable"),
    ("1150", "Intercompany Receivable", "asset", "Intercompany"),
    ("2000", "Accounts Payable", "liability", "Accounts Payable"),
    ("2100", "Accrued Liabilities", "liability", "Accrued Liabilities"),
    ("2150", "Intercompany Payable", "liability", "Intercompany"),
    ("3000", "Equity", "equity", "Equity"),
    ("4000", "Subscription Revenue", "revenue", "Revenue"),
    ("4100", "Professional Services Revenue", "revenue", "Revenue"),
    ("4900", "Intercompany Revenue", "revenue", "Intercompany"),
    ("5000", "Hosting & Infrastructure", "cogs", "Cost of Revenue"),
    ("5100", "Customer Support Payroll", "cogs", "Cost of Revenue"),
    ("5200", "Third-party Software (COGS)", "cogs", "Cost of Revenue"),
    ("5300", "Payment Processing Fees", "cogs", "Cost of Revenue"),
    ("6000", "Salaries & Wages", "opex", "Payroll"),
    ("6010", "Payroll Taxes & Benefits", "opex", "Payroll"),
    ("6100", "Contractors", "opex", "Contractors"),
    ("6200", "Software & Subscriptions", "opex", "Software"),
    ("6300", "Advertising & Paid Media", "opex", "Marketing Programs"),
    ("6310", "Events & Sponsorships", "opex", "Marketing Programs"),
    ("6400", "Travel & Entertainment", "opex", "Travel & Entertainment"),
    ("6500", "Rent & Facilities", "opex", "Facilities"),
    ("6600", "Professional Fees", "opex", "Professional Fees"),
    ("6700", "Recruiting", "opex", "Recruiting"),
    ("6900", "Intercompany Expense", "opex", "Intercompany"),
    ("7000", "Interest Income", "other", "Other Income/Expense"),
    ("7100", "FX Gain/Loss", "other", "Other Income/Expense"),
]
GROUP_NAME = {code: name for code, name, _, _ in GROUP_COA}

# local code, local name, group code
LOCAL_COA: dict[str, list[tuple[str, str, str]]] = {
    "US": [
        ("1000", "Operating Checking", "1000"),
        ("1100", "Accounts Receivable (A/R)", "1100"),
        ("2000", "Accounts Payable (A/P)", "2000"),
        ("2100", "Accrued Liabilities", "2100"),
        ("2150", "Due to Affiliates", "2150"),
        ("3000", "Opening Balance Equity", "3000"),
        ("4000", "Subscription Revenue", "4000"),
        ("4100", "Professional Services Revenue", "4100"),
        ("5000", "Cloud Hosting", "5000"),
        ("5100", "Customer Support Salaries", "5100"),
        ("5200", "COGS - Software", "5200"),
        ("5300", "Merchant Processing Fees", "5300"),
        ("6000", "Salaries & Wages", "6000"),
        ("6010", "Payroll Taxes & Benefits", "6010"),
        ("6100", "Contractors", "6100"),
        ("6200", "Software & SaaS Tools", "6200"),
        ("6301", "Advertising:Search Ads", "6300"),
        ("6302", "Advertising:Social Ads", "6300"),
        ("6310", "Events & Conferences", "6310"),
        ("6400", "Travel & Meals", "6400"),
        ("6500", "Rent & Office", "6500"),
        ("6600", "Legal & Accounting", "6600"),
        ("6700", "Recruiting Fees", "6700"),
        ("6900", "Intercompany R&D Services", "6900"),
        ("7000", "Interest Income", "7000"),
    ],
    "UK": [
        ("090", "Business Bank Account", "1000"),
        ("610", "Accounts Receivable", "1100"),
        ("615", "Due from Group Companies", "1150"),
        ("800", "Accounts Payable", "2000"),
        ("825", "Accruals", "2100"),
        ("970", "Share Capital", "3000"),
        ("200", "Sales - Subscriptions", "4000"),
        ("210", "Sales - Professional Services", "4100"),
        ("260", "Intercompany Recharge Income", "4900"),
        ("310", "Hosting Costs", "5000"),
        ("320", "Support Team Salaries", "5100"),
        ("330", "Cost of Sales - Software", "5200"),
        ("340", "Card Processing Fees", "5300"),
        ("477", "Salaries", "6000"),
        ("478", "Employer NI & Pension", "6010"),
        ("480", "Contractors", "6100"),
        ("485", "Subscriptions", "6200"),
        ("400", "Advertising", "6300"),
        ("405", "Events", "6310"),
        ("493", "Travel - International", "6400"),
        ("469", "Rent", "6500"),
        ("412", "Consulting & Accounting", "6600"),
        ("470", "Recruitment", "6700"),
        ("499", "Foreign Currency Gains and Losses", "7100"),
    ],
    "DE": [
        ("1200", "Bank", "1000"),
        ("1400", "Forderungen aus Lieferungen und Leistungen", "1100"),
        ("1590", "Forderungen gegen verbundene Unternehmen", "1150"),
        ("1600", "Verbindlichkeiten aus Lieferungen und Leistungen", "2000"),
        ("1700", "Sonstige Verbindlichkeiten", "2100"),
        ("0800", "Gezeichnetes Kapital", "3000"),
        ("8400", "Erlöse Abonnements", "4000"),
        ("8401", "Erlöse Dienstleistungen", "4100"),
        ("8402", "Erlöse verbundene Unternehmen", "4900"),
        ("3100", "Fremdleistungen Hosting", "5000"),
        ("4125", "Gehälter Kundenservice", "5100"),
        ("3110", "Software Wareneinsatz", "5200"),
        ("4970", "Nebenkosten des Geldverkehrs", "5300"),
        ("4120", "Gehälter", "6000"),
        ("4130", "Gesetzliche soziale Aufwendungen", "6010"),
        ("4780", "Fremdarbeiten", "6100"),
        ("4806", "Software-Abonnements", "6200"),
        ("4600", "Werbekosten", "6300"),
        ("4610", "Messen und Veranstaltungen", "6310"),
        ("4670", "Reisekosten", "6400"),
        ("4210", "Miete", "6500"),
        ("4950", "Rechts- und Beratungskosten", "6600"),
        ("4955", "Personalbeschaffung", "6700"),
        ("2150", "Aufwendungen aus Kursdifferenzen", "7100"),
    ],
}
# Opened by the US team in Oct-2026, after the mapping was built -> unmapped on purpose.
NEW_US_ACCOUNTS = {"6250": "AI Tools & APIs", "6720": "Employer of Record Fees"}

LOCAL_DEPTS = {
    "US": dict(GROUP_DEPTS),
    "UK": {"SAL": "Sales", "MKT": "Marketing", "RND": "Research and Development",
           "CS": "Customer Success", "GA": "General & Admin"},
    "DE": {"SAL": "100", "MKT": "200", "RND": "300", "CS": "400", "GA": "500"},
}

# --------------------------------------------------------------------------- entity profiles
@dataclass(frozen=True)
class Profile:
    code: str
    name: str
    currency: str
    customers: float
    arpa: float
    cust_growth: float
    cust_growth_plan: float
    headcount: dict[str, int]
    salary: dict[str, float]
    payroll_tax: float
    rent: float
    ads: float
    events: float
    hosting_pct: float
    fees_pct: float
    opening_cash: float
    software_per_head: float
    travel_per_head: float
    prof_fees: float
    recruit_per_hire: float


PROFILES = {
    "US": Profile("US", "Kestrel Inc.", "USD", 420, 2150, .022, .025,
                  {"SAL": 20, "MKT": 8, "RND": 25, "CS": 10, "GA": 8},
                  {"SAL": 10000, "MKT": 9500, "RND": 13000, "CS": 7500, "GA": 10000},
                  .10, 40000, 110000, 45000, .09, .022, 18_000_000, 310, 900, 15000, 4000),
    "UK": Profile("UK", "Kestrel Ltd", "GBP", 150, 1250, .018, .020,
                  {"SAL": 8, "MKT": 3, "RND": 10, "CS": 4, "GA": 2},
                  {"SAL": 6500, "MKT": 6000, "RND": 7500, "CS": 4500, "GA": 6000},
                  .138, 12000, 18000, 8000, .09, .020, 1_500_000, 240, 700, 6000, 3000),
    "DE": Profile("DE", "Kestrel GmbH", "EUR", 90, 1150, .015, .016,
                  {"SAL": 4, "MKT": 1, "RND": 12, "CS": 3, "GA": 2},
                  {"SAL": 6500, "MKT": 6000, "RND": 7000, "CS": 4500, "GA": 6000},
                  .20, 9000, 6000, 4000, .09, .018, 1_000_000, 260, 750, 5000, 3500),
}
HC_GROWTH_ACTUAL = {"SAL": .015, "MKT": .010, "RND": .012, "CS": .015, "GA": .008}
HC_GROWTH_PLAN = {"SAL": .020, "MKT": .010, "RND": .025, "CS": .015, "GA": .008}
EVENT_SEASON = {3: 1.5, 6: 2.0, 9: 1.5, 11: 1.8}
IC_MARKUP = 1.05

VENDORS = {
    "5000": ["Nimbus Cloud Services"], "5200": ["Paperlane Docs"], "5300": ["PayStream"],
    "6100": ["Devforge Contractors", "Ledgerline Bookkeeping"], "6200": ["Stackwise", "Paperlane Docs", "Notely"],
    "6300": ["AdReach Search", "SocialSpark Ads"], "6310": ["SaaSConnect Expo", "B2B Growth Summit"],
    "6400": ["Skyway Travel", "Metro Rides"], "6500": ["Harborview Properties"],
    "6600": ["Whitlock & Rowe LLP", "Brightline Audit"], "6700": ["TalentBridge Search"],
}
BILL_ACCOUNTS = ("5000", "5200", "6100", "6200", "6300", "6310", "6400", "6500", "6600", "6700")


# --------------------------------------------------------------------------- driver model
def drivers(e: Profile, p: pd.Period, scenario: str, rng: np.random.Generator | None) -> dict[tuple[str, str], float]:
    """Monthly P&L amounts (local currency, positive numbers) keyed by (group account, dept)."""
    actual = scenario == "actual"
    t = (p - FIRST).n

    def noise(sigma: float) -> float:
        return float(rng.normal(1.0, sigma)) if actual else 1.0

    in_plan = not actual and p.year == 2026
    if in_plan:  # the plan starts from the Dec-2025 level and assumes faster growth
        customers = e.customers * (1 + e.cust_growth) ** 11 * (1 + e.cust_growth_plan) ** p.month
    else:
        customers = e.customers * (1 + e.cust_growth) ** t
    arpa = e.arpa * (1.04 if p.year == 2026 else 1.0)  # list-price increase in Jan-2026
    sub = customers * arpa * noise(.015)
    if actual and e.code == "US" and p >= pd.Period("2026-05", "M"):
        sub *= .965  # a large customer churned in May-2026

    out: dict[tuple[str, str], float] = {
        ("4000", ""): sub,
        ("4100", ""): sub * .05 * noise(.25),
        ("5200", ""): sub * .015 * noise(.05),
        ("5300", ""): sub * e.fees_pct * noise(.03),
    }
    hosting = e.hosting_pct * (1.18 if actual and p >= pd.Period("2026-08", "M") else 1.0)  # AI features
    out[("5000", "")] = sub * hosting * noise(.04)

    for d in DEPTS:
        if in_plan:
            base = e.headcount[d] * (1 + HC_GROWTH_ACTUAL[d]) ** 11
            hc = round(base * (1 + HC_GROWTH_PLAN[d]) ** p.month)
            prev = round(base * (1 + HC_GROWTH_PLAN[d]) ** (p.month - 1))
        else:
            hc = round(e.headcount[d] * (1 + HC_GROWTH_ACTUAL[d]) ** t)
            prev = round(e.headcount[d] * (1 + HC_GROWTH_ACTUAL[d]) ** max(t - 1, 0))
        salary = e.salary[d] * (1.04 if p.year == 2026 else 1.0)
        payroll = hc * salary * noise(.01)
        out[("5100" if d == "CS" else "6000", d)] = payroll
        out[("6010", d)] = payroll * e.payroll_tax
        out[("6200", d)] = hc * e.software_per_head * noise(.05)
        if max(hc - prev, 0):
            out[("6700", d)] = (hc - prev) * e.recruit_per_hire * noise(.15)
        if d in ("SAL", "CS", "GA"):
            share = {"SAL": 1.0, "CS": .35, "GA": .25}[d]
            out[("6400", d)] = hc * e.travel_per_head * share * noise(.12)
        if d == "RND":
            out[("6100", d)] = payroll * .06 * noise(.10)

    if in_plan:
        out[("6300", "MKT")] = e.ads * 1.12
    else:
        out[("6300", "MKT")] = e.ads * 1.01 ** t * noise(.08)
    out[("6310", "MKT")] = e.events * EVENT_SEASON.get(p.month, .6) * noise(.10)
    if actual and e.code == "US" and p == pd.Period("2026-06", "M"):
        out[("6310", "MKT")] += 80_000  # unplanned flagship-conference booth
    out[("6500", "GA")] = e.rent * (1.05 if p.year == 2026 else 1.0)
    audit = 3.0 if p.month in (3, 4) else 0.0
    out[("6600", "GA")] = e.prof_fees * (1 + audit) * noise(.10)
    out[("6100", "GA")] = e.prof_fees * .4 * noise(.15)
    if e.code == "US":
        out[("7000", "")] = 52_500 * (1 - .025 * t) * noise(.03)
    return out


# --------------------------------------------------------------------------- journals
@dataclass
class Line:
    account: str  # group account
    dept: str  # group department code, "" for balance-sheet / unallocated lines
    debit: float
    credit: float
    local_account: str | None = None  # forces a local account (new, unmapped accounts)


@dataclass
class JE:
    entity: str
    date: date
    kind: str
    ref: str
    party: str
    memo: str
    lines: list[Line] = field(default_factory=list)


def make_je(entity, d, kind, ref, party, memo, multi, single, multi_side="debit") -> JE:
    """n lines on one side balanced by a single line on the other side."""
    lines, total = [], 0.0
    for item in multi:
        acct, dept, amt = item[:3]
        local = item[3] if len(item) > 3 else None
        amt = round(float(amt), 2)
        if amt <= 0:
            continue
        total += amt
        lines.append(Line(acct, dept, amt if multi_side == "debit" else 0.0,
                          amt if multi_side == "credit" else 0.0, local))
    total = round(total, 2)
    lines.append(Line(single, "", total if multi_side == "credit" else 0.0, total if multi_side == "debit" else 0.0))
    return JE(entity, d, kind, ref, party, memo, lines)


def business_day(p: pd.Period, day: int) -> date:
    last = calendar.monthrange(p.year, p.month)[1]
    d = date(p.year, p.month, min(day, last))
    step = timedelta(days=-1 if d.day > 2 else 1)
    while d.weekday() >= 5:
        d += step
    return d


def month_end(p: pd.Period) -> date:
    return business_day(p, 31)


def synthetic_fx(rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    level = {"GBP": 1.27, "EUR": 1.08}
    for p in pd.period_range(FIRST, "2026-12", freq="M"):
        for cur in ("GBP", "EUR"):
            avg = level[cur]
            level[cur] = round(level[cur] * float(rng.normal(1.0, .012)), 4)
            rows.append({"period": str(p), "currency": cur, "avg_rate_to_usd": round(avg, 4),
                         "close_rate_to_usd": level[cur]})
    return pd.DataFrame(rows)


def customer_names(rng: np.random.Generator, suffix: str, n: int) -> list[str]:
    first = ["Blue", "North", "Silver", "Bright", "Granite", "Cedar", "Harbor", "Summit", "Quarry", "Maple",
             "Copper", "Pioneer", "Orchid", "Falcon", "Juniper", "Meridian", "Beacon", "Willow", "Ember", "Tidal"]
    second = ["Logistics", "Health", "Foods", "Labs", "Retail", "Systems", "Partners", "Energy", "Media",
              "Studios", "Analytics", "Robotics", "Freight", "Clinics", "Outdoors", "Learning", "Travel"]
    pairs = [f"{a} {b} {suffix}" for a in first for b in second]
    return list(rng.choice(pairs, size=n, replace=False))


def simulate(rng: np.random.Generator, fx: pd.DataFrame) -> dict[str, list[JE]]:
    avg_rate = {(r.period, r.currency): r.avg_rate_to_usd for r in fx.itertuples()}
    journals: dict[str, list[JE]] = {e: [] for e in PROFILES}
    customers = {"US": customer_names(rng, "Inc.", 80), "UK": customer_names(rng, "Ltd", 40),
                 "DE": customer_names(rng, "GmbH", 30)}
    invoices_per_month = {"US": 35, "UK": 18, "DE": 12}
    seq = {e: {} for e in PROFILES}
    open_ar = {e: [] for e in PROFILES}
    open_tax = {e: 0.0 for e in PROFILES}
    open_ic: dict[str, float] = {"UK": 0.0, "DE": 0.0, "US": 0.0}

    def ref(e, prefix):
        seq[e][prefix] = seq[e].get(prefix, 0) + 1
        return f"{prefix}-{seq[e][prefix]:05d}"

    for e, prof in PROFILES.items():
        journals[e].append(make_je(e, date(2025, 1, 1), "opening", ref(e, "OB"), "", "Opening balance",
                                   [("1000", "", prof.opening_cash)], "3000"))

    for p in PERIODS:
        amounts = {e: drivers(PROFILES[e], p, "actual", rng) for e in PROFILES}
        ic_local = {e: round((amounts[e][("6000", "RND")] + amounts[e][("6010", "RND")]) * IC_MARKUP, 2)
                    for e in ("UK", "DE")}
        ic_usd = {e: round(ic_local[e] * avg_rate[(str(p), PROFILES[e].currency)], 2) for e in ic_local}

        for e, prof in PROFILES.items():
            js = journals[e]
            a = amounts[e]
            # collections of last month's invoices
            for party, amt in open_ar[e]:
                js.append(make_je(e, business_day(p, int(rng.integers(3, 28))), "payment", ref(e, "PMT"), party,
                                  "Customer payment", [("1000", "", amt)], "1100"))
            open_ar[e] = []
            # subscription invoices
            n = invoices_per_month[e]
            weights = rng.dirichlet(np.ones(n) * 2.0)
            for party, w in zip(rng.choice(customers[e], size=n, replace=False), weights):
                amt = round(a[("4000", "")] * w, 2)
                js.append(make_je(e, business_day(p, int(rng.integers(1, 6))), "invoice", ref(e, "INV"), party,
                                  "Subscription fees", [("4000", "", amt)], "1100", multi_side="credit"))
                open_ar[e].append((party, amt))
            for party, w in zip(rng.choice(customers[e], size=3, replace=False), rng.dirichlet(np.ones(3))):
                amt = round(a[("4100", "")] * w, 2)
                js.append(make_je(e, business_day(p, int(rng.integers(10, 25))), "invoice", ref(e, "INV"), party,
                                  "Implementation services", [("4100", "", amt)], "1100", multi_side="credit"))
                open_ar[e].append((party, amt))
            # payroll, payroll taxes (accrued, paid the following month)
            payroll = [(acct, d, v) for (acct, d), v in a.items() if acct in ("6000", "5100")]
            js.append(make_je(e, month_end(p), "payroll", ref(e, "PR"), "Payroll", f"Payroll {p.strftime('%b %Y')}",
                              payroll, "1000"))
            if open_tax[e]:
                js.append(make_je(e, business_day(p, 15), "accrual_payment", ref(e, "TAX"), "Tax authority",
                                  "Payroll taxes paid", [("2100", "", open_tax[e])], "1000"))
            taxes = [(acct, d, v) for (acct, d), v in a.items() if acct == "6010"]
            tax_je = make_je(e, month_end(p), "accrual", ref(e, "JNL"), "", f"Payroll taxes {p.strftime('%b %Y')}",
                             taxes, "2100")
            js.append(tax_je)
            open_tax[e] = tax_je.lines[-1].credit
            # vendor bills, paid later in the same month
            bills = [(acct, d, v) for (acct, d), v in a.items() if acct in BILL_ACCOUNTS]
            if e == "US" and p == LAST:  # new accounts opened by the US team
                bills.append(("6200", "RND", 18_500.00, "6250"))
                bills.append(("6100", "RND", 9_200.00, "6720"))
            for item in bills:
                acct, d, v = item[:3]
                local = item[3] if len(item) > 3 else None
                vendor = ("Cortexa AI APIs" if local == "6250" else "GlobalHire EOR" if local == "6720"
                          else str(rng.choice(VENDORS[acct])))
                parts = [v] if v < 5_000 or local else [v * .55, v * .45]
                for part in parts:
                    bill_ref = ref(e, "BILL")
                    day = int(rng.integers(2, 15))
                    js.append(make_je(e, business_day(p, day), "bill", bill_ref, vendor, GROUP_NAME[acct],
                                      [(acct, d, part, local)] if local else [(acct, d, part)], "2000",
                                      multi_side="debit"))
                    paid = js[-1].lines[-1].credit
                    js.append(make_je(e, business_day(p, day + int(rng.integers(5, 13))), "bill_payment",
                                      ref(e, "BP"), vendor, f"Payment {bill_ref}", [("2000", "", paid)], "1000"))
            # card / payment processing fees deducted by the processor
            js.append(make_je(e, month_end(p), "expense", ref(e, "EXP"), "PayStream", "Processing fees",
                              [("5300", "", a[("5300", "")])], "1000"))
            # interest income (US treasury account)
            if ("7000", "") in a:
                js.append(make_je(e, month_end(p), "deposit", ref(e, "DEP"), "Bank", "Interest income",
                                  [("1000", "", a[("7000", "")])], "7000"))
            # FX revaluation on non-USD entities
            if e in ("UK", "DE"):
                fx_amt = round(float(rng.normal(0, 1500)), 2)
                if fx_amt > 0:
                    js.append(make_je(e, month_end(p), "fx", ref(e, "JNL"), "", "FX revaluation",
                                      [("7100", "", fx_amt)], "1000"))
                elif fx_amt < 0:
                    js.append(make_je(e, month_end(p), "fx", ref(e, "JNL"), "", "FX revaluation",
                                      [("1000", "", -fx_amt)], "7100"))
            # intercompany: UK and DE recharge their R&D cost (+5%) to the US parent
            if e in ("UK", "DE"):
                if open_ic[e]:
                    js.append(make_je(e, business_day(p, 15), "ic_settlement", ref(e, "ICS"), "Kestrel Inc.",
                                      "Intercompany settlement", [("1000", "", open_ic[e])], "1150"))
                js.append(make_je(e, month_end(p), "ic", ref(e, "IC"), "Kestrel Inc.",
                                  f"R&D services recharge {p.strftime('%b %Y')}", [("4900", "", ic_local[e])], "1150",
                                  multi_side="credit"))
                open_ic[e] = ic_local[e]
            else:
                if open_ic["US"]:
                    js.append(make_je(e, business_day(p, 15), "ic_settlement", ref(e, "ICS"), "Group affiliates",
                                      "Intercompany settlement", [("2150", "", open_ic["US"])], "1000"))
                lines = [("6900", "RND", ic_usd["UK"]), ("6900", "RND", ic_usd["DE"])]
                js.append(make_je(e, month_end(p), "ic", ref(e, "IC"), "Kestrel Ltd / Kestrel GmbH",
                                  f"R&D services from affiliates {p.strftime('%b %Y')}", lines, "2150"))
                open_ic["US"] = js[-1].lines[-1].credit
    for e in journals:
        journals[e].sort(key=lambda j: j.date)
    return journals


# --------------------------------------------------------------------------- exporters
def local_lookup(entity: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for code, _, group in LOCAL_COA[entity]:
        out.setdefault(group, []).append(code)
    return out


def local_name(entity: str, code: str) -> str:
    names = {c: n for c, n, _ in LOCAL_COA[entity]}
    return names.get(code) or NEW_US_ACCOUNTS[code]


def export_us(journals: list[JE], rng: np.random.Generator, path: Path) -> None:
    """QuickBooks Online 'Journal' report exported to CSV (report header + TOTAL row)."""
    kinds = {"invoice": "Invoice", "payment": "Payment", "bill": "Bill", "bill_payment": "Bill Payment (Check)",
             "payroll": "Payroll Check", "accrual": "Journal Entry", "accrual_payment": "Check",
             "expense": "Expense", "deposit": "Deposit", "ic": "Bill", "ic_settlement": "Bill Payment (Check)",
             "opening": "Journal Entry"}
    lookup = local_lookup("US")
    rows: list[list[str]] = []
    duplicated = False
    for je in journals:
        block = []
        for ln in je.lines:
            code = ln.local_account or (str(rng.choice(lookup[ln.account], p=[.6, .4]))
                                        if ln.account == "6300" else lookup[ln.account][0])
            block.append([je.date.strftime("%m/%d/%Y"), kinds[je.kind], je.ref, je.party, je.memo,
                          f"{code} {local_name('US', code)}", LOCAL_DEPTS["US"].get(ln.dept, ""),
                          f"{ln.debit:.2f}" if ln.debit else "", f"{ln.credit:.2f}" if ln.credit else ""])
        rows.extend(block)
        # ISSUE: a hosting bill appears twice in the September-2026 export
        if (not duplicated and je.kind == "bill" and je.date.strftime("%Y-%m") == "2026-09"
                and je.lines[0].account == "5000"):
            rows.extend(block)
            duplicated = True
    debit = sum(float(r[7] or 0) for r in rows)
    credit = sum(float(r[8] or 0) for r in rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Kestrel Inc."])
        w.writerow(["Journal"])
        w.writerow(["January 1, 2025 - October 31, 2026"])
        w.writerow([])
        w.writerow(["Date", "Transaction Type", "Num", "Name", "Memo/Description", "Account", "Class",
                    "Debit", "Credit"])
        w.writerows(rows)
        w.writerow(["TOTAL", "", "", "", "", "", "", f"{debit:.2f}", f"{credit:.2f}"])


def export_uk(journals: list[JE], rng: np.random.Generator, path: Path) -> None:
    """Xero 'General Ledger Detail' style export: UTF-8 BOM, dd/mm/yyyy dates, 1,234.56 amounts."""
    kinds = {"invoice": "Receivable Invoice", "payment": "Receivable Payment", "bill": "Payable Invoice",
             "bill_payment": "Payable Payment", "payroll": "Manual Journal", "accrual": "Manual Journal",
             "accrual_payment": "Spend Money", "expense": "Spend Money", "fx": "Manual Journal",
             "ic": "Receivable Invoice", "ic_settlement": "Receive Money", "opening": "Manual Journal"}
    lookup = local_lookup("UK")
    rows = []
    broken = False
    for n, je in enumerate(journals, start=1):
        lines = je.lines
        # ISSUE: the Oct-2026 payroll-tax journal was cut off by the export (one line missing)
        if not broken and je.kind == "accrual" and je.date.strftime("%Y-%m") == "2026-10":
            lines = [ln for ln in lines if ln.dept != "RND"]
            broken = True
        for ln in lines:
            code = lookup[ln.account][0]
            dept = LOCAL_DEPTS["UK"].get(ln.dept, "")
            if ln.dept == "RND" and je.date >= date(2026, 3, 1) and rng.random() < .5:
                dept = "R&D"  # ISSUE: a second spelling appears after a Xero settings change
            if ln.dept == "RND" and je.date >= date(2026, 8, 1) and rng.random() < .3:
                dept = "Research & Dev"  # ISSUE: and a third one, not in the department mapping
            if rng.random() < .3:
                code = code + " "  # ISSUE: trailing spaces in account codes
            rows.append([je.date.strftime("%d/%m/%Y"), kinds[je.kind], je.memo, je.ref, str(n), code,
                         local_name("UK", code.strip()), dept,
                         f"{ln.debit:,.2f}" if ln.debit else "", f"{ln.credit:,.2f}" if ln.credit else ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["Date", "Source", "Description", "Reference", "Journal Number", "Account Code", "Account",
                    "Department", "Debit (GBP)", "Credit (GBP)"])
        w.writerows(rows)


GERMAN_TEXT = {
    "invoice": "Ausgangsrechnung", "payment": "Zahlungseingang", "bill": "Eingangsrechnung",
    "bill_payment": "Zahlung Lieferant", "payroll": "Gehälter", "accrual": "Sozialabgaben Rückstellung",
    "accrual_payment": "Zahlung Sozialabgaben", "expense": "Gebühren Zahlungsdienstleister",
    "fx": "Kursdifferenzen", "ic": "Konzernumlage F&E", "ic_settlement": "Ausgleich Konzernverrechnung",
    "opening": "Eröffnungsbilanz",
}


def export_de(journals: list[JE], folder: Path) -> None:
    """DATEV-style 'Buchungsstapel': one file per fiscal year, cp1252, ';', decimal comma, DDMM dates."""
    lookup = local_lookup("DE")
    by_year: dict[int, list[list[str]]] = {}
    missing_cc_done = False
    for je in journals:
        debits = [ln for ln in je.lines if ln.debit]
        credits = [ln for ln in je.lines if ln.credit]
        if len(credits) == 1:
            multi, single, flag = debits, credits[0], "S"
        else:
            multi, single, flag = credits, debits[0], "H"
        for ln in multi:
            cc = LOCAL_DEPTS["DE"].get(ln.dept, "")
            # ISSUE: one travel booking in Jul-2026 lost its cost centre
            if not missing_cc_done and ln.account == "6400" and je.date.strftime("%Y-%m") == "2026-07":
                cc, missing_cc_done = "", True
            amount = ln.debit or ln.credit
            by_year.setdefault(je.date.year, []).append([
                f"{amount:.2f}".replace(".", ","), flag, "EUR", lookup[ln.account][0], lookup[single.account][0],
                je.date.strftime("%d%m"), je.ref, f"{GERMAN_TEXT[je.kind]} {je.party}".strip()[:60], cc])
    header = ["Umsatz (ohne Soll/Haben-Kz)", "Soll/Haben-Kennzeichen", "WKZ Umsatz", "Konto",
              "Gegenkonto (ohne BU-Schlüssel)", "Belegdatum", "Belegfeld 1", "Buchungstext", "KOST1 - Kostenstelle"]
    folder.mkdir(parents=True, exist_ok=True)
    for year, rows in by_year.items():
        end = "20261031" if year == 2026 else f"{year}1231"
        meta = ["EXTF", "700", "21", "Buchungsstapel", "13", "20261102093000000", "", "RE", "", "", "1001",
                "20001", f"{year}0101", "4", f"{year}0101", end, f"Buchungsstapel {year}", "", "1", "0", "0", "EUR"]
        with (folder / f"EXTF_Buchungsstapel_{year}.csv").open("w", newline="", encoding="cp1252") as f:
            w = csv.writer(f, delimiter=";", quoting=csv.QUOTE_MINIMAL)
            w.writerow(meta)
            w.writerow(header)
            w.writerows(rows)


BUDGET_SECTIONS = [
    ("Revenue", ["4000", "4100"], "Total Revenue"),
    ("Cost of Revenue", ["5000", "5100", "5200", "5300"], "Total Cost of Revenue"),
    ("Operating Expenses", ["6000", "6010", "6100", "6200", "6300", "6310", "6400", "6500", "6600", "6700"],
     "Total Operating Expenses"),
    ("Other Income", ["7000"], "Total Other Income"),
]
BUDGET_LABEL = {**GROUP_NAME, "6300": "Advertising"}  # FP&A uses its own labels
BUDGET_FX = {"USD": 1.0, "GBP": 1.27, "EUR": 1.08}


def export_budget(path: Path) -> None:
    """FY2026 budget: one sheet per entity, wide months, title rows, formula subtotals, FY column."""
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = xlsxwriter.Workbook(path)
    bold = wb.add_format({"bold": True})
    title = wb.add_format({"bold": True, "font_size": 14})
    num = wb.add_format({"num_format": "#,##0"})
    sub = wb.add_format({"num_format": "#,##0", "bold": True, "top": 1})
    head = wb.add_format({"bold": True, "bg_color": "#DDEBF7", "bottom": 1})

    ws = wb.add_worksheet("Read me")
    ws.write(0, 0, "Kestrel Group - FY2026 Operating Budget", title)
    ws.write(2, 0, "Version: v3 FINAL - approved by the Board on 10-Dec-2025. Do not edit.")
    ws.write(3, 0, "Amounts in local currency. Budget FX rates on the 'Assumptions' sheet.")

    for e, prof in PROFILES.items():
        ws = wb.add_worksheet(e)
        ws.write(0, 0, f"Kestrel Group - FY2026 Operating Budget - {prof.name} ({prof.currency})", title)
        ws.write(1, 0, "Version: v3 FINAL")
        ws.write(2, 0, f"Currency: {prof.currency}")
        cols = ["Line item", "Department"] + [p.strftime("%b-%y") for p in BUDGET_PERIODS] + ["FY2026"]
        for c, h in enumerate(cols):
            ws.write(4, c, h, head)
        plan = {p: drivers(prof, p, "budget", None) for p in BUDGET_PERIODS}
        r = 5
        for section, accounts, total_label in BUDGET_SECTIONS:
            keys = sorted({k for p in BUDGET_PERIODS for k in plan[p] if k[0] in accounts},
                          key=lambda k: (accounts.index(k[0]), DEPTS.index(k[1]) if k[1] else -1))
            if not keys:
                continue
            ws.write(r, 0, section, bold)
            r += 1
            first = r
            for acct, d in keys:
                ws.write(r, 0, BUDGET_LABEL[acct])
                ws.write(r, 1, GROUP_DEPTS[d] if d else "—")
                vals = [round(plan[p].get((acct, d), 0.0)) for p in BUDGET_PERIODS]
                for c, v in enumerate(vals, start=2):
                    ws.write_number(r, c, v, num)
                ws.write_formula(r, 14, f"=SUM(C{r + 1}:N{r + 1})", num, sum(vals))
                r += 1
            ws.write(r, 0, total_label, bold)
            monthly = [sum(round(plan[p].get(k, 0.0)) for k in keys) for p in BUDGET_PERIODS]
            for c, cached in enumerate(monthly + [sum(monthly)], start=2):
                col = xl_col_to_name(c)
                ws.write_formula(r, c, f"=SUM({col}{first + 1}:{col}{r})", sub, cached)
            r += 2
        ws.set_column(0, 0, 32)
        ws.set_column(1, 1, 18)
        ws.set_column(2, 14, 11)

    ws = wb.add_worksheet("Assumptions")
    ws.write_row(0, 0, ["Budget FX rate", "Rate to USD"], head)
    for i, (cur, rate) in enumerate(BUDGET_FX.items(), start=1):
        ws.write_row(i, 0, [cur, rate])
    wb.close()


def export_config() -> None:
    CONFIG.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(GROUP_COA, columns=["account", "account_name", "account_type", "statement_line"]).to_csv(
        CONFIG / "group_chart_of_accounts.csv", index=False)
    rows = [{"entity": e, "local_account": c, "local_account_name": n, "group_account": g}
            for e, coa in LOCAL_COA.items() for c, n, g in coa]
    pd.DataFrame(rows).to_csv(CONFIG / "account_mapping.csv", index=False)
    depts = [{"source": e, "local_department": local, "department": code}
             for e, m in LOCAL_DEPTS.items() for code, local in m.items()]
    depts.append({"source": "UK", "local_department": "R&D", "department": "RND"})
    depts += [{"source": "BUDGET", "local_department": name, "department": code} for code, name in GROUP_DEPTS.items()]
    pd.DataFrame(depts).to_csv(CONFIG / "department_mapping.csv", index=False)
    pd.DataFrame([{"budget_line": label, "account": code} for code, label in BUDGET_LABEL.items()
                  if code[0] in "4567"]).to_csv(CONFIG / "budget_line_mapping.csv", index=False)
    pd.DataFrame([{"department": c, "department_name": n} for c, n in GROUP_DEPTS.items()]).to_csv(
        CONFIG / "departments.csv", index=False)
    pd.DataFrame([{"entity": e, "entity_name": p.name, "currency": p.currency} for e, p in PROFILES.items()]).to_csv(
        CONFIG / "entities.csv", index=False)


def main() -> None:
    rng = np.random.default_rng(SEED)
    fx = synthetic_fx(rng)
    journals = simulate(rng, fx)
    export_us(journals["US"], rng, RAW / "us_kestrel_inc" / "Kestrel_Inc_Journal_Jan2025-Oct2026.csv")
    export_uk(journals["UK"], rng, RAW / "uk_kestrel_ltd" / "Kestrel_Ltd_General_Ledger_Detail.csv")
    export_de(journals["DE"], RAW / "de_kestrel_gmbh")
    export_budget(RAW / "budget" / "FY2026_Budget_v3_FINAL.xlsx")
    (RAW / "fx").mkdir(parents=True, exist_ok=True)
    fx.to_csv(RAW / "fx" / "fx_rates_monthly.csv", index=False)
    export_config()
    total = sum(len(ln.lines) for js in journals.values() for ln in js)
    print(f"Generated {sum(len(js) for js in journals.values()):,} journals / {total:,} lines -> {RAW}")


if __name__ == "__main__":
    main()
