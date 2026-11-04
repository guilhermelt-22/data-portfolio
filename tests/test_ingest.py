"""Each reader must survive the quirks of its source system."""
from pathlib import Path

import pandas as pd

from findata.ingest import read_datev_batch, read_quickbooks_journal, read_xero_gl


def test_quickbooks_drops_report_header_and_total_row(tmp_path: Path):
    f = tmp_path / "journal.csv"
    f.write_text(
        "Kestrel Inc.\nJournal\n\"January 1, 2026 - January 31, 2026\"\n\n"
        "Date,Transaction Type,Num,Name,Memo/Description,Account,Class,Debit,Credit\n"
        "01/05/2026,Bill,BILL-1,Vendor,Hosting,5000 Cloud Hosting,,100.00,\n"
        "01/05/2026,Bill,BILL-1,Vendor,Hosting,2000 Accounts Payable (A/P),,,100.00\n"
        "TOTAL,,,,,,,100.00,100.00\n", encoding="utf-8")
    gl = read_quickbooks_journal(f, "US")
    assert len(gl) == 2
    assert gl["local_account"].tolist() == ["5000", "2000"]
    assert gl["local_account_name"].iloc[0] == "Cloud Hosting"


def test_xero_dates_are_day_first_and_amounts_have_thousand_separators(tmp_path: Path):
    f = tmp_path / "gl.csv"
    f.write_text(
        "Date,Source,Description,Reference,Journal Number,Account Code,Account,Department,Debit (GBP),Credit (GBP)\n"
        '03/02/2026,Manual Journal,x,J1,7,477 ,Salaries,R&D,"1,234.50",\n'
        "03/02/2026,Manual Journal,x,J1,7,090,Bank,,,\"1,234.50\"\n", encoding="utf-8-sig")
    gl = read_xero_gl(f, "UK")
    assert gl["date"].iloc[0] == pd.Timestamp("2026-02-03")  # 3 February, not 2 March
    assert gl["debit"].iloc[0] == 1234.50
    assert gl["local_account"].iloc[0] == "477"  # trailing space removed


def test_datev_rows_expand_into_balanced_double_entry_lines(tmp_path: Path):
    f = tmp_path / "EXTF_Buchungsstapel_2026.csv"
    lines = [
        "EXTF;700;21;Buchungsstapel;13;20261102093000000;;RE;;;1001;20001;20260101;4;20260101;20261031",
        "Umsatz (ohne Soll/Haben-Kz);Soll/Haben-Kennzeichen;WKZ Umsatz;Konto;Gegenkonto (ohne BU-Schlüssel);"
        "Belegdatum;Belegfeld 1;Buchungstext;KOST1 - Kostenstelle",
        "1.500,25;S;EUR;4120;1200;3010;PR-1;Gehälter;300",
        "200,00;H;EUR;8400;1400;0511;INV-1;Ausgangsrechnung;",
    ]
    f.write_bytes("\n".join(lines).encode("cp1252"))
    gl = read_datev_batch(f, "DE")
    assert len(gl) == 4
    assert gl["debit"].sum() == gl["credit"].sum() == 1700.25
    salary = gl[gl["local_account"] == "4120"].iloc[0]
    assert (salary["date"], salary["debit"], salary["local_department"]) == (pd.Timestamp("2026-10-30"), 1500.25, "300")
    revenue = gl[gl["local_account"] == "8400"].iloc[0]
    assert revenue["credit"] == 200.0  # 'H' credits the account
