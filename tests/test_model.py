"""End-to-end invariants on the demo dataset (run `python data/generate.py` first)."""
import pytest

from findata.close import run


@pytest.fixture(scope="module")
def close():
    return run("2026-10")


def test_all_seeded_issues_are_found(close):
    found = set(zip(close.issues["check"], close.issues["entity"]))
    assert found == {("duplicate_lines", "US"), ("unbalanced_journal", "UK"), ("unmapped_account", "US"),
                     ("unmapped_department", "UK"), ("missing_department", "DE")}


def test_intercompany_is_eliminated_from_the_consolidated_pl(close):
    leftover = close.con.execute("SELECT COUNT(*) FROM pl_monthly WHERE account IN ('4900', '6900')").fetchone()[0]
    assert leftover == 0


def test_budget_vs_actual_reconciles_to_its_inputs(close):
    bva, actual, budget = close.con.execute("""
        SELECT (SELECT SUM(variance_usd) FROM bva),
               (SELECT SUM(actual_usd) FROM pl_monthly WHERE period >= '2026-01'),
               (SELECT SUM(budget_usd) FROM budget_monthly)
    """).fetchone()
    assert bva == pytest.approx(actual - budget, abs=0.01)


def test_quarantined_duplicate_does_not_reach_the_model(close):
    assert len(close.excluded_lines) == 2
    hosting_sep = close.con.execute("""
        SELECT -SUM(actual_usd) FROM pl_monthly
        WHERE entity = 'US' AND account = '5000' AND period = '2026-09'
    """).fetchone()[0]
    assert hosting_sep < 200_000  # one bill of ~87.5k would otherwise be counted twice
