"""The demo: load the full history, run again (nothing new), then show the incremental path.

1. Full history since 1999 from an empty store (one request).
2. Run again at once: it asks only for the days after the last stored date, and finds none.
3. Delete the last 5 business days from the local store, as if the last run had been a week ago, and
   run again: it asks the API only for those days and adds them back.

Usage (from the mini-case folder):  python -m ecbfx.demo
"""
from __future__ import annotations

from . import store
from .report import write_report
from .update import DB_PATH, OUT

ROLLBACK_DAYS = 5


def main() -> None:
    DB_PATH.unlink(missing_ok=True)
    con = store.connect(DB_PATH)
    for step in (1, 2, 3):
        if step == 3:
            days = [r[0] for r in con.execute("SELECT DISTINCT date FROM rates ORDER BY date DESC LIMIT ?",
                                              (ROLLBACK_DAYS,))]
            with con:
                gone = con.execute(f"DELETE FROM rates WHERE date IN ({','.join('?' * len(days))})", days).rowcount
            print(f"step 3: deleted {gone} rates for {days[-1]} to {days[0]} from the local store")
        s = store.update(con)
        print(f"step {step}: {s['mode']}, asked from {s['start_period'] or '1999'}: {s['rows_received']:,} rows "
              f"received, {s['rows_new']:,} new rates for {s['days_new']} days, {s['rows_unchanged']:,} unchanged, "
              f"{s['rows_revised']} revised, {s['seconds']} s")
    result = write_report(con, OUT)
    print(f"checks: {result['overall']}")
    for name, res, detail in result["checks"]:
        print(f"  {res:5} {name}: {detail}")


if __name__ == "__main__":
    main()
