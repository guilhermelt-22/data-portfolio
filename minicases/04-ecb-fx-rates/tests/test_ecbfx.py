"""ECB rates collector, tested offline with canned API responses."""
import pandas as pd
import pytest

from ecbfx import fetch_rates
from ecbfx import store
from ecbfx.api import ApiError
from ecbfx.checks import coverage, run_checks
from ecbfx.report import write_report
from ecbfx.target import business_days, is_closing_day

HEADER = "KEY,FREQ,CURRENCY,CURRENCY_DENOM,EXR_TYPE,EXR_SUFFIX,TIME_PERIOD,OBS_VALUE\n"


def csv(rows) -> str:
    return HEADER + "".join(f"EXR.D.{c}.EUR.SP00.A,D,{c},EUR,SP00,A,{d},{v}\n" for d, c, v in rows)


class Resp:
    def __init__(self, status, text, ctype="text/csv"):
        self.status_code, self.text, self.headers = status, text, {"Content-Type": ctype}


class Session:
    def __init__(self, *responses):
        self.responses, self.calls, self.headers = list(responses), [], {}

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        return self.responses.pop(0)


# --------------------------------------------------------------------------- calendar
@pytest.mark.parametrize("day, closed", [("2026-04-03", True),   # Good Friday
                                         ("2026-04-06", True),   # Easter Monday
                                         ("2026-05-01", True), ("2026-12-25", True), ("2026-12-26", True),
                                         ("2001-12-31", True),   # euro cash changeover
                                         ("1999-04-02", False),  # Good Friday became a closing day in 2000
                                         ("2026-11-09", False), ("2026-11-07", True)])
def test_target_closing_days(day, closed):
    assert is_closing_day(pd.Timestamp(day)) is closed


def test_business_days_skip_weekends_and_holidays():
    days = business_days("2026-12-23", "2027-01-04")
    assert [d.strftime("%m-%d") for d in days] == ["12-23", "12-24", "12-28", "12-29", "12-30", "12-31", "01-04"]


# --------------------------------------------------------------------------- api
def test_fetch_builds_the_series_key_and_returns_a_tidy_frame():
    s = Session(Resp(200, csv([("2026-11-05", "USD", 1.1224), ("2026-11-05", "GBP", 0.83393),
                               ("2012-05-01", "USD", "")])))
    df = fetch_rates(["usd", "GBP"], start="2026-11-01", session=s)
    url, params = s.calls[0]
    assert url.endswith("/EXR/D.GBP+USD.EUR.SP00.A")
    assert params == {"format": "csvdata", "detail": "dataonly", "startPeriod": "2026-11-01"}
    assert list(df.columns) == ["date", "currency", "rate"]
    assert len(df) == 2 and df["date"].dtype.kind == "M"  # the holiday row without a value is dropped


def test_no_new_data_is_an_empty_frame_not_an_error():
    df = fetch_rates(["USD"], start="2099-01-01", session=Session(Resp(200, "")))
    assert df.empty and list(df.columns) == ["date", "currency", "rate"]


def test_busy_portal_is_retried_and_an_html_error_page_is_never_parsed(monkeypatch):
    monkeypatch.setattr("ecbfx.api.time.sleep", lambda _: None)
    s = Session(Resp(504, "<html>busy</html>", "text/html"), Resp(200, csv([("2026-11-05", "USD", 1.12)])))
    assert len(fetch_rates(["USD"], session=s)) == 1 and len(s.calls) == 2
    s = Session(*[Resp(503, "<html>down</html>", "text/html")] * 4)
    with pytest.raises(ApiError, match="HTTP 503"):
        fetch_rates(["USD"], session=s)


# --------------------------------------------------------------------------- incremental store
def frame(rows):
    df = pd.DataFrame(rows, columns=["date", "currency", "rate"])
    df["date"] = pd.to_datetime(df["date"])
    return df


def fake_fetch(data: pd.DataFrame, calls: list):
    def fetch(currencies, start=None, keep_empty=False, **_):
        calls.append(start)
        out = data if start is None else data[data["date"] >= pd.Timestamp(start)]
        return out if keep_empty else out.dropna(subset=["rate"])
    return fetch


DAYS = [d.strftime("%Y-%m-%d") for d in business_days("2026-10-26", "2026-11-06")]


def test_second_run_asks_only_from_the_last_stored_day_and_adds_only_new_days():
    con = store.connect(":memory:")
    calls = []
    first = frame([(d, c, 1.0 + i / 100) for i, d in enumerate(DAYS[:7]) for c in ("USD", "GBP")])
    s1 = store.update(con, fetch=fake_fetch(first, calls))
    assert (s1["mode"], s1["rows_new"]) == ("full history", 14)
    later = frame([(d, c, 1.0 + i / 100) for i, d in enumerate(DAYS) for c in ("USD", "GBP")])
    s2 = store.update(con, fetch=fake_fetch(later, calls))
    assert calls == [None, DAYS[6]]  # asked from the last stored day (re-read as an overlap check)
    assert (s2["rows_new"], s2["days_new"], s2["rows_unchanged"], s2["rows_revised"]) == (6, 3, 2, 0)
    assert con.execute("SELECT COUNT(*) FROM rates").fetchone()[0] == 20


def test_a_revised_rate_is_logged_and_duplicates_received_are_merged():
    con = store.connect(":memory:")
    store.update(con, fetch=fake_fetch(frame([(DAYS[0], "USD", 1.10), (DAYS[1], "USD", 1.11)]), []))
    again = frame([(DAYS[1], "USD", 1.12), (DAYS[2], "USD", 1.13), (DAYS[2], "USD", 1.13)])
    s = store.update(con, fetch=fake_fetch(again, []))
    assert (s["rows_revised"], s["duplicates_received"], s["rows_new"]) == (1, 1, 1)
    assert con.execute("SELECT old_rate, new_rate FROM revisions").fetchone() == (1.11, 1.12)
    assert con.execute("SELECT COUNT(*) FROM rates").fetchone()[0] == 3


# --------------------------------------------------------------------------- checks
def test_holidays_are_not_gaps_but_a_missing_business_day_is():
    days = business_days("2026-03-30", "2026-04-10")  # Easter 2026: 3 and 6 April closed
    usd = [(d, "USD", 1.1) for d in days]
    gbp = [(d, "GBP", 0.8) for d in days if d != pd.Timestamp("2026-04-08")]  # one real gap
    cov = coverage(frame(usd + gbp)).set_index("currency")
    assert cov.loc["USD", "gap_days"] == 0 and cov.loc["USD", "expected"] == 8
    assert cov.loc["GBP", "gap_days"] == 1 and cov.loc["GBP", "largest_gap"] == "2026-04-08"


def test_checks_flag_a_suspension_and_pass_on_clean_data():
    days = business_days("2026-01-02", "2026-11-06")
    clean = frame([(d, "USD", 1.1) for d in days])
    result = run_checks(clean, today=pd.Timestamp("2026-11-09"))
    assert result["overall"] == "PASS"
    isk = [(d, "ISK", 140.0) for i, d in enumerate(days) if not 20 <= i < 60]  # 40 days missing
    result = run_checks(frame([(d, "USD", 1.1) for d in days] + isk), today=pd.Timestamp("2026-11-09"))
    gaps = dict((n, (r, d)) for n, r, d in result["checks"])["No gaps in currencies still published"]
    assert gaps[0] == "WARN" and "ISK: suspended" in gaps[1] and "(40 days)" in gaps[1]
    stale = run_checks(clean, today=pd.Timestamp("2026-11-20"))
    assert dict((n, r) for n, r, _ in stale["checks"])["Up to date"] == "WARN"


def test_report_files_are_written(tmp_path):
    con = store.connect(":memory:")
    data = frame([(d, c, 1.0) for d in DAYS for c in ("USD", "GBP", "CHF")])
    store.update(con, fetch=fake_fetch(data, []))
    write_report(con, tmp_path, today=pd.Timestamp("2026-11-09"))
    assert {p.name for p in tmp_path.iterdir()} == {"ecb_rates_long.csv", "ecb_rates_wide.csv",
                                                    "sample_last_30_days.csv", "ecb_fx_rates.xlsx", "fx_report.html"}
