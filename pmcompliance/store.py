"""SQLite state: approval queue, audit log and last-known statuses.

Every outbound item (reminder, document request, owner follow-up, review task,
proposed Buildium change) is a row in `queue`. The idempotency key is unique,
so re-running the audit never creates a duplicate. Nothing leaves the
machine unless a person approved it; `send` refuses everything else.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Callable, Dict, Iterable, List, Optional

from . import pii

SCHEMA = """
CREATE TABLE IF NOT EXISTS queue (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    idem_key     TEXT NOT NULL UNIQUE,
    kind         TEXT NOT NULL,
    channel      TEXT NOT NULL,
    entity_id    TEXT NOT NULL,
    entity_name  TEXT NOT NULL,
    doc_type     TEXT,
    recipient    TEXT,
    subject      TEXT NOT NULL,
    body         TEXT NOT NULL,
    payload      TEXT,
    status       TEXT NOT NULL DEFAULT 'pending',
    created_at   TEXT NOT NULL,
    decided_by   TEXT,
    decided_at   TEXT,
    sent_at      TEXT
);
CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL,
    actor      TEXT NOT NULL,
    event      TEXT NOT NULL,
    entity_id  TEXT,
    detail     TEXT
);
CREATE TABLE IF NOT EXISTS doc_status (
    entity_id  TEXT NOT NULL,
    doc_type   TEXT NOT NULL,
    status     TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (entity_id, doc_type)
);
CREATE TABLE IF NOT EXISTS dispatch (
    entity_id  TEXT PRIMARY KEY,
    paused     INTEGER NOT NULL,
    reason     TEXT,
    updated_at TEXT NOT NULL
);
"""


class NotApproved(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Store:
    def __init__(self, path: str, clock: Optional[Callable[[], str]] = None) -> None:
        self.now = clock or _now
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    # ------------------------------------------------------------- audit log
    def log(self, actor: str, event: str, entity_id: Optional[str], detail: str) -> None:
        self.conn.execute(
            "INSERT INTO audit_log (ts, actor, event, entity_id, detail) VALUES (?,?,?,?,?)",
            (self.now(), actor, event, entity_id, pii.mask(detail)))
        self.conn.commit()

    def audit(self, limit: int = 200) -> List[sqlite3.Row]:
        return list(self.conn.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)))

    # ---------------------------------------------------------- status track
    def record_status(self, entity_id: str, doc_type: str, status: str) -> Optional[str]:
        """Store the status; log and return the previous one if it changed."""
        row = self.conn.execute("SELECT status FROM doc_status WHERE entity_id=? AND doc_type=?",
                                (entity_id, doc_type)).fetchone()
        previous = row["status"] if row else None
        if previous == status:
            return None
        self.conn.execute(
            "INSERT OR REPLACE INTO doc_status (entity_id, doc_type, status, updated_at) "
            "VALUES (?,?,?,?)", (entity_id, doc_type, status, self.now()))
        self.conn.commit()
        self.log("audit", "status_change", entity_id,
                 "%s: %s -> %s" % (doc_type, previous or "new", status))
        return previous or "new"

    def set_dispatch(self, entity_id: str, paused: bool, reason: str) -> bool:
        row = self.conn.execute("SELECT paused FROM dispatch WHERE entity_id=?",
                                (entity_id,)).fetchone()
        if row is not None and bool(row["paused"]) == paused:
            return False
        if row is None and not paused:
            return False
        self.conn.execute("INSERT OR REPLACE INTO dispatch VALUES (?,?,?,?)",
                          (entity_id, int(paused), reason, self.now()))
        self.conn.commit()
        self.log("audit", "dispatch_paused" if paused else "dispatch_resumed", entity_id, reason)
        return True

    def dispatch_paused(self, entity_id: str) -> bool:
        row = self.conn.execute("SELECT paused FROM dispatch WHERE entity_id=?",
                                (entity_id,)).fetchone()
        return bool(row and row["paused"])

    # ----------------------------------------------------------------- queue
    def enqueue(self, idem_key: str, kind: str, channel: str, entity_id: str, entity_name: str,
                doc_type: Optional[str], recipient: Optional[str], subject: str, body: str,
                payload: Optional[dict] = None) -> Optional[int]:
        """Insert unless the idempotency key exists. Returns the new id or None."""
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO queue (idem_key, kind, channel, entity_id, entity_name, "
            "doc_type, recipient, subject, body, payload, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (idem_key, kind, channel, entity_id, entity_name, doc_type, recipient,
             pii.mask(subject), pii.mask(body), json.dumps(payload or {}, sort_keys=True), self.now()))
        self.conn.commit()
        if cur.rowcount == 0:
            return None
        self.log("audit", "queued", entity_id, "%s #%d: %s" % (kind, cur.lastrowid, subject))
        return int(cur.lastrowid)

    def items(self, status: Optional[str] = None) -> List[sqlite3.Row]:
        if status:
            return list(self.conn.execute("SELECT * FROM queue WHERE status=? ORDER BY id",
                                          (status,)))
        return list(self.conn.execute("SELECT * FROM queue ORDER BY id"))

    def get(self, item_id: int) -> sqlite3.Row:
        row = self.conn.execute("SELECT * FROM queue WHERE id=?", (item_id,)).fetchone()
        if row is None:
            raise KeyError("no queue item %d" % item_id)
        return row

    def decide(self, item_id: int, approver: str, approve: bool = True) -> None:
        if not approver or not approver.strip():
            raise ValueError("an approval needs the approver's name")
        row = self.get(item_id)
        if row["status"] != "pending":
            raise ValueError("item %d is %s, not pending" % (item_id, row["status"]))
        status = "approved" if approve else "rejected"
        self.conn.execute("UPDATE queue SET status=?, decided_by=?, decided_at=? WHERE id=?",
                          (status, approver, self.now(), item_id))
        self.conn.commit()
        self.log(approver, status, row["entity_id"], "%s #%d: %s" % (row["kind"], item_id,
                                                                     row["subject"]))

    def send(self, item_ids: Iterable[int], outbox_path: str, actor: str = "sender") -> Dict[str, list]:
        """Hand approved items to the (stub) sender. Unapproved items are refused."""
        sent, refused = [], []
        for item_id in item_ids:
            row = self.get(item_id)
            if row["status"] != "approved":
                refused.append(item_id)
                self.log(actor, "send_refused", row["entity_id"],
                         "#%d is %s; only approved items can be sent" % (item_id, row["status"]))
                continue
            _stub_send(outbox_path, row)
            self.conn.execute("UPDATE queue SET status='sent', sent_at=? WHERE id=?",
                              (self.now(), item_id))
            self.conn.commit()
            self.log(actor, "sent", row["entity_id"], "%s #%d via %s to %s"
                     % (row["kind"], item_id, row["channel"], row["recipient"] or "-"))
            sent.append(item_id)
        if refused and not sent:
            raise NotApproved("refused %s: not approved" % ", ".join("#%d" % i for i in refused))
        return {"sent": sent, "refused": refused}


def _stub_send(outbox_path: str, row: sqlite3.Row) -> None:
    """The only 'sender'. It writes to a file; nothing goes over the network."""
    os.makedirs(os.path.dirname(os.path.abspath(outbox_path)), exist_ok=True)
    record = {k: row[k] for k in ("id", "kind", "channel", "entity_id", "recipient", "subject",
                                  "body", "decided_by")}
    record["payload"] = json.loads(row["payload"] or "{}")
    with open(outbox_path, "a") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")
