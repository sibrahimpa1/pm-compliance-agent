"""Command line: audit, queue, approve, reject, send.

    python -m pmcompliance audit [--as-of DATE] [--live] [--record] [--api-down]
    python -m pmcompliance queue [--status pending]
    python -m pmcompliance approve ID --by "Name"
    python -m pmcompliance reject ID --by "Name"
    python -m pmcompliance send ID [ID ...] | --all-approved
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date

from . import report
from .pipeline import Paths, run_audit
from .store import NotApproved, Store


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="pmcompliance")
    ap.add_argument("--db", help="SQLite state file (default out/state.db)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("audit", help="run the audit and queue drafts")
    a.add_argument("--as-of", type=date.fromisoformat, default=None,
                   help="evaluate expiry as of this date (default today)")
    a.add_argument("--live", action="store_true", help="call Claude (needs ANTHROPIC_API_KEY)")
    a.add_argument("--record", action="store_true", help="with --live: save results as fixtures")
    a.add_argument("--api-down", action="store_true", help="simulate the Buildium API failing")
    q = sub.add_parser("queue", help="list queue items")
    q.add_argument("--status")
    for name in ("approve", "reject"):
        p = sub.add_parser(name)
        p.add_argument("id", type=int)
        p.add_argument("--by", required=True, help="name of the person deciding")
    s = sub.add_parser("send", help="send approved items through the stub sender")
    s.add_argument("ids", type=int, nargs="*")
    s.add_argument("--all-approved", action="store_true")
    args = ap.parse_args(argv)

    paths = Paths()
    store = Store(args.db or paths.db)
    try:
        if args.cmd == "audit":
            mode = "live" if args.live else "offline"
            run = run_audit(paths, store, as_of=args.as_of, mode=mode,
                            api_available=not args.api_down, record=args.record)
            for _rec, res in run.vendors + run.owners:
                flag = "  DISPATCH PAUSED" if res.dispatch_paused else ""
                print("%-6s %-40s %s%s" % (res.entity_id, res.name, res.status, flag))
            print("%d new queue items" % len(run.new_items))
            out = os.path.join(paths.out, "report.html")
            with open(out, "w") as fh:
                fh.write(report.render(run, store))
            print("report: %s" % out)
        elif args.cmd == "queue":
            for r in store.items(args.status):
                print("#%-3d %-9s %-17s %-6s %s" % (r["id"], r["status"], r["kind"],
                                                  r["entity_id"], r["subject"]))
        elif args.cmd in ("approve", "reject"):
            store.decide(args.id, args.by, approve=args.cmd == "approve")
            print("#%d %sd by %s" % (args.id, args.cmd, args.by))
        elif args.cmd == "send":
            ids = [r["id"] for r in store.items("approved")] if args.all_approved else args.ids
            result = store.send(ids, paths.outbox)
            print("sent: %s  refused: %s" % (result["sent"], result["refused"]))
    except NotApproved as exc:
        print("refused: %s" % exc, file=sys.stderr)
        return 2
    except (KeyError, ValueError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1
    finally:
        store.close()
    return 0
