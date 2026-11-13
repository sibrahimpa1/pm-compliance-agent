"""Run the whole pipeline offline and write out/report.html and site/.

    python -m pmcompliance.demo [--as-of YYYY-MM-DD] [--api-down] [--live]

The demo pins the as-of date (default 2026-11-13) and uses a fixed clock so the
report and the site are reproducible. It starts from a fresh state each time.
"""
from __future__ import annotations

import argparse
import os
from datetime import date, datetime, timedelta

from . import report, site
from .pipeline import Paths, run_audit
from .store import NotApproved, Store

DEMO_AS_OF = date(2026, 11, 13)
REVIEWER = "Demo Reviewer"


def fixed_clock(as_of: date):
    t = [datetime(as_of.year, as_of.month, as_of.day, 9, 0, 0)]

    def now() -> str:
        t[0] += timedelta(seconds=7)
        return t[0].strftime("%Y-%m-%dT%H:%M:%SZ")
    return now


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--as-of", type=date.fromisoformat, default=DEMO_AS_OF)
    ap.add_argument("--api-down", action="store_true", help="simulate the Buildium API failing")
    ap.add_argument("--live", action="store_true", help="call Claude instead of replaying fixtures")
    ap.add_argument("--no-site", action="store_true", help="skip writing site/")
    args = ap.parse_args(argv)

    paths = Paths()
    os.makedirs(paths.out, exist_ok=True)
    for p in (paths.db, paths.outbox):
        if os.path.exists(p):
            os.remove(p)
    store = Store(paths.db, clock=fixed_clock(args.as_of))
    mode = "live" if args.live else "offline"

    run = run_audit(paths, store, as_of=args.as_of, mode=mode, api_available=not args.api_down)
    print("Audit as of %s (%s): %d vendors, %d owners, %d queue items"
          % (run.as_of, mode, len(run.vendors), len(run.owners), len(run.new_items)))
    for note in run.notes + ["skipped " + s for s in run.skipped]:
        print("  note:", note)

    again = run_audit(paths, store, as_of=args.as_of, mode=mode, api_available=not args.api_down)
    print("Second run: %d new queue items (idempotency keys hold)" % len(again.new_items))

    # A reviewer approves one reminder and one owner follow-up; the reminder is sent.
    items = store.items()
    reminder = next((q for q in items if q["kind"] == "renewal_reminder"), None)
    followup = next((q for q in items if q["kind"] == "owner_followup"), None)
    if reminder:
        store.decide(reminder["id"], REVIEWER, approve=True)
        store.send([reminder["id"]], paths.outbox)
        print("Approved and sent #%d (stub sender -> %s)" % (reminder["id"], paths.outbox))
    if followup:
        store.decide(followup["id"], REVIEWER, approve=True)
        print("Approved #%d, not sent yet" % followup["id"])
    pending = next((q for q in store.items("pending") if q["kind"] == "document_request"), None)
    if pending:
        try:
            store.send([pending["id"]], paths.outbox)
        except NotApproved as exc:
            print("Send refused as expected: %s" % exc)

    report_path = os.path.join(paths.out, "report.html")
    with open(report_path, "w") as fh:
        fh.write(report.render(run, store))
    print("Report: %s" % report_path)
    if not args.no_site:
        index = site.write_site(run, store, os.path.join(os.path.dirname(paths.out), "site"))
        print("Site:   %s" % index)
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
