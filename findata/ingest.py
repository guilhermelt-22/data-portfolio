"""Readers that turn each accounting system's export into one standard line-level table.

Every reader returns the same columns (STANDARD_COLUMNS), one row per debit/credit line,
amounts in the entity's local currency. Nothing is mapped or filtered here: the goal is a
faithful, typed copy of the source so that validation can see every problem.
"""
from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd

from .paths import CONFIG, RAW

STANDARD_COLUMNS = [
    "entity", "source_file", "source_row", "je_id", "date", "period", "local_account",
    "local_account_name", "local_department", "debit", "credit", "txn_type", "party", "memo",
]


def _amount(s: pd.Series, thousands: str = ",", decimal: str = ".") -> pd.Series:
    clean = s.fillna("").str.strip().str.replace(thousands, "", regex=False).str.replace(decimal, ".", regex=False)
    return pd.to_numeric(clean.replace("", "0")).astype(float)


def _finish(df: pd.DataFrame) -> pd.DataFrame:
    df["period"] = df["date"].dt.strftime("%Y-%m")
    for col in ("local_account", "local_department", "je_id"):
        df[col] = df[col].fillna("").astype(str)
    return df[STANDARD_COLUMNS].reset_index(drop=True)


def read_quickbooks_journal(path: Path, entity: str) -> pd.DataFrame:
    """QuickBooks 'Journal' report CSV: 4 title lines, a TOTAL footer, 'Account' = '6000 Name'."""
    df = pd.read_csv(path, skiprows=4, dtype=str, keep_default_na=False)
    df = df[df["Date"].str.match(r"\d{2}/\d{2}/\d{4}")]  # drops the TOTAL footer
    account = df["Account"].str.extract(r"^(?P<code>\S+)\s+(?P<name>.*)$")
    out = pd.DataFrame({
        "entity": entity,
        "source_file": path.name,
        "source_row": df.index + 6,  # 1-based line number in the file
        "je_id": df["Num"],
        "date": pd.to_datetime(df["Date"], format="%m/%d/%Y"),
        "local_account": account["code"],
        "local_account_name": account["name"],
        "local_department": df["Class"].str.strip(),
        "debit": _amount(df["Debit"]),
        "credit": _amount(df["Credit"]),
        "txn_type": df["Transaction Type"],
        "party": df["Name"],
        "memo": df["Memo/Description"],
    })
    return _finish(out)


def read_xero_gl(path: Path, entity: str) -> pd.DataFrame:
    """Xero General Ledger Detail CSV: BOM, dd/mm/yyyy dates, '1,234.56' amounts, padded codes."""
    df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    out = pd.DataFrame({
        "entity": entity,
        "source_file": path.name,
        "source_row": df.index + 2,
        "je_id": df["Journal Number"],
        # explicit format: a day-first date read month-first would silently swap 01/02 and 02/01
        "date": pd.to_datetime(df["Date"], format="%d/%m/%Y"),
        "local_account": df["Account Code"].str.strip(),
        "local_account_name": df["Account"],
        "local_department": df["Department"].str.strip(),
        "debit": _amount(df["Debit (GBP)"]),
        "credit": _amount(df["Credit (GBP)"]),
        "txn_type": df["Source"],
        "party": "",
        "memo": df["Description"],
    })
    return _finish(out)


def read_datev_batch(path: Path, entity: str) -> pd.DataFrame:
    """DATEV 'Buchungsstapel': metadata line + header, ';', cp1252, decimal comma, DDMM dates.

    Each booking row has an account (Konto) and a contra account (Gegenkonto); it is expanded
    into two double-entry lines. 'S' means Konto is debited, 'H' means Konto is credited.
    """
    with path.open(encoding="cp1252", newline="") as f:
        meta = next(csv.reader(f, delimiter=";"))
    fiscal_year = meta[12][:4]  # field 13 = fiscal-year start (YYYYMMDD); DDMM dates carry no year
    df = pd.read_csv(path, sep=";", skiprows=1, dtype=str, keep_default_na=False, encoding="cp1252")
    amount = _amount(df["Umsatz (ohne Soll/Haben-Kz)"], thousands=".", decimal=",")
    ddmm = df["Belegdatum"].str.zfill(4)
    date = pd.to_datetime(fiscal_year + ddmm.str[2:] + ddmm.str[:2], format="%Y%m%d")
    debit_side = df["Soll/Haben-Kennzeichen"].str.upper().eq("S")
    common = {"entity": entity, "source_file": path.name, "source_row": df.index + 3, "je_id": df["Belegfeld 1"],
              "date": date, "local_account_name": "", "txn_type": "Buchung", "party": "", "memo": df["Buchungstext"]}
    account_side = pd.DataFrame({**common, "local_account": df["Konto"], "local_department": df["KOST1 - Kostenstelle"],
                                 "debit": amount.where(debit_side, 0.0), "credit": amount.where(~debit_side, 0.0)})
    contra_side = pd.DataFrame({**common, "local_account": df["Gegenkonto (ohne BU-Schlüssel)"], "local_department": "",
                                "debit": amount.where(~debit_side, 0.0), "credit": amount.where(debit_side, 0.0)})
    return _finish(pd.concat([account_side, contra_side]).sort_values(["source_row", "credit"], kind="stable"))


SOURCES = [  # entity, reader, location
    ("US", read_quickbooks_journal, RAW / "us_kestrel_inc" / "Kestrel_Inc_Journal_Jan2025-Oct2026.csv"),
    ("UK", read_xero_gl, RAW / "uk_kestrel_ltd" / "Kestrel_Ltd_General_Ledger_Detail.csv"),
    ("DE", read_datev_batch, RAW / "de_kestrel_gmbh" / "EXTF_Buchungsstapel_2025.csv"),
    ("DE", read_datev_batch, RAW / "de_kestrel_gmbh" / "EXTF_Buchungsstapel_2026.csv"),
]


def load_gl() -> pd.DataFrame:
    return pd.concat([reader(path, entity) for entity, reader, path in SOURCES], ignore_index=True)


def load_budget(path: Path = RAW / "budget" / "FY2026_Budget_v3_FINAL.xlsx") -> pd.DataFrame:
    """Budget workbook -> long table. Skips title rows, section headers, subtotals and the FY column."""
    entities = pd.read_csv(CONFIG / "entities.csv", dtype=str)["entity"]
    frames = []
    for entity in entities:
        sheet = pd.read_excel(path, sheet_name=entity, header=None, dtype=object)
        header_row = sheet.index[sheet[0].eq("Line item")][0]
        table = sheet.iloc[header_row + 1:].copy()
        table.columns = sheet.iloc[header_row].tolist()
        table = table[table["Department"].notna() & ~table["Line item"].astype(str).str.startswith("Total")]
        months = [c for c in table.columns if isinstance(c, str) and c[:3].isalpha() and c[-3] == "-"]
        long = table.melt(id_vars=["Line item", "Department"], value_vars=months, var_name="month",
                          value_name="amount_local")
        long["period"] = pd.to_datetime(long["month"], format="%b-%y").dt.strftime("%Y-%m")
        long["entity"] = entity
        frames.append(long.rename(columns={"Line item": "budget_line", "Department": "local_department"}))
    out = pd.concat(frames, ignore_index=True)
    out["amount_local"] = out["amount_local"].astype(float)
    return out[["entity", "period", "budget_line", "local_department", "amount_local"]]


def load_budget_fx(path: Path = RAW / "budget" / "FY2026_Budget_v3_FINAL.xlsx") -> pd.DataFrame:
    rates = pd.read_excel(path, sheet_name="Assumptions")
    return rates.rename(columns={"Budget FX rate": "currency", "Rate to USD": "budget_rate_to_usd"})


def load_fx(path: Path = RAW / "fx" / "fx_rates_monthly.csv") -> pd.DataFrame:
    return pd.read_csv(path, dtype={"period": str, "currency": str})


def load_config(name: str) -> pd.DataFrame:
    return pd.read_csv(CONFIG / f"{name}.csv", dtype=str, keep_default_na=False)
