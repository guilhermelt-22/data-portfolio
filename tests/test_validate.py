"""The checks must catch real problems and stay quiet on legitimate look-alikes."""
import pandas as pd

from findata.validate import check_balanced_journals, check_unmapped_accounts, find_duplicate_lines


def lines(*rows):
    cols = ["entity", "je_id", "date", "local_account", "local_department", "debit", "credit"]
    df = pd.DataFrame(rows, columns=cols)
    df["date"] = pd.to_datetime(df["date"])
    df["period"] = df["date"].dt.strftime("%Y-%m")
    df["source_file"], df["source_row"] = "test.csv", range(2, len(df) + 2)
    df["local_account_name"], df["memo"] = "", ""
    return df


def test_a_journal_exported_twice_is_flagged_once():
    bill = [("US", "BILL-1", "2026-09-05", "5000", "", 100.0, 0.0),
            ("US", "BILL-1", "2026-09-05", "2000", "", 0.0, 100.0)]
    dupes = find_duplicate_lines(lines(*bill, *bill))
    assert len(dupes) == 2
    assert dupes["source_row"].tolist() == [4, 5]  # the second copy, not the original


def test_coincidental_identical_bank_lines_inside_one_batch_are_not_duplicates():
    payroll = lines(
        ("DE", "PR-1", "2026-10-30", "4120", "100", 500.0, 0.0),
        ("DE", "PR-1", "2026-10-30", "1200", "", 0.0, 500.0),
        ("DE", "PR-1", "2026-10-30", "4120", "300", 500.0, 0.0),
        ("DE", "PR-1", "2026-10-30", "1200", "", 0.0, 500.0),  # same as row 2 by coincidence
    )
    assert find_duplicate_lines(payroll).empty


def test_unbalanced_journal_is_reported_with_its_difference():
    issues = check_balanced_journals(lines(("UK", "7", "2026-10-30", "478", "", 90.0, 0.0),
                                           ("UK", "7", "2026-10-30", "825", "", 0.0, 100.0)))
    assert len(issues) == 1 and issues[0].amount == -10.0 and issues[0].severity == "blocking"


def test_new_local_account_without_mapping_is_blocking():
    mapping = pd.DataFrame({"entity": ["US"], "local_account": ["6200"], "group_account": ["6200"]})
    issues = check_unmapped_accounts(lines(("US", "B", "2026-10-02", "6250", "RND", 10.0, 0.0)), mapping)
    assert [i.check for i in issues] == ["unmapped_account"]
