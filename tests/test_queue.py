import json

import pytest

from conftest import AS_OF
from pmcompliance.pipeline import run_audit
from pmcompliance.store import NotApproved, Store


def test_rerun_creates_no_duplicate_reminders(paths):
    store = Store(paths.db)
    first = run_audit(paths, store, as_of=AS_OF)
    assert len(first.new_items) > 0
    second = run_audit(paths, store, as_of=AS_OF)
    assert second.new_items == []
    keys = [r["idem_key"] for r in store.items()]
    assert len(keys) == len(set(keys))


def test_new_expiry_window_gets_a_new_reminder(paths):
    store = Store(paths.db)
    run_audit(paths, store, as_of=AS_OF)
    n = len(store.items())
    later = run_audit(paths, store, as_of=AS_OF.replace(day=20))  # owner follow-up period rolls
    assert any(store.get(i)["kind"] == "owner_followup" for i in later.new_items)
    assert len(store.items()) > n


def test_send_refuses_unapproved(paths):
    store = Store(paths.db)
    run_audit(paths, store, as_of=AS_OF)
    item = store.items("pending")[0]
    with pytest.raises(NotApproved):
        store.send([item["id"]], paths.outbox)
    assert store.get(item["id"])["status"] == "pending"
    events = [a["event"] for a in store.audit()]
    assert "send_refused" in events


def test_approved_item_goes_to_outbox_once(paths):
    store = Store(paths.db)
    run_audit(paths, store, as_of=AS_OF)
    item = next(r for r in store.items() if r["kind"] == "renewal_reminder")
    with pytest.raises(ValueError):
        store.decide(item["id"], "  ")
    store.decide(item["id"], "Jamie Reviewer")
    assert store.send([item["id"]], paths.outbox)["sent"] == [item["id"]]
    with pytest.raises(NotApproved):  # already sent, cannot be re-sent
        store.send([item["id"]], paths.outbox)
    lines = open(paths.outbox).read().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["decided_by"] == "Jamie Reviewer"
    events = [(a["actor"], a["event"]) for a in store.audit()]
    assert ("Jamie Reviewer", "approved") in events


def test_status_changes_and_dispatch_pause_are_logged(paths):
    store = Store(paths.db)
    run_audit(paths, store, as_of=AS_OF)
    events = [(a["event"], a["entity_id"]) for a in store.audit(500)]
    assert ("dispatch_paused", "V-103") in events
    assert ("status_change", "V-102") in events
    assert store.dispatch_paused("V-103") and not store.dispatch_paused("V-101")
