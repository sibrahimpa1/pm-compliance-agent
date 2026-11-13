import glob
import os

from conftest import AS_OF, ROOT
from pmcompliance import pii, report, site
from pmcompliance.pipeline import run_audit
from pmcompliance.store import Store
from pmcompliance.synthetic import all_specs


def secrets():
    """Every full TIN and bank number printed on the synthetic documents."""
    out = set()
    for spec in all_specs():
        for label, value, field, _conf in spec.rows:
            if field in ("tin_last4", "account_last4") or label == "Routing Number":
                out.add(value)
    assert len(out) >= 10
    return out


def test_mask_keeps_last_four():
    assert pii.mask("TIN (EIN): 00-0000123") == "TIN (EIN): **-***0123"
    assert pii.mask("SSN: 000-00-0456") == "SSN: ***-**-0456"
    assert pii.mask("Account Number: 000000004321") == "Account Number: ********4321"
    assert pii.mask("Policy Number: CGL-00-1001, call (000) 555-0101") == \
        "Policy Number: CGL-00-1001, call (000) 555-0101"


def test_no_full_tin_in_any_output(paths):
    store = Store(paths.db)
    run = run_audit(paths, store, as_of=AS_OF)
    first = store.items()[0]
    store.decide(first["id"], "Reviewer")
    store.send([first["id"]], paths.outbox)
    html = report.render(run, store)
    site_dir = os.path.join(paths.out, "site")
    site.write_site(run, store, site_dir)
    db_dump = "\n".join(store.conn.iterdump())
    blobs = [html, db_dump, open(paths.outbox).read()]
    blobs += [open(p).read() for p in glob.glob(os.path.join(site_dir, "*.*"))]
    blobs += [open(p).read() for p in glob.glob(os.path.join(ROOT, "data", "fixtures", "*.json"))]
    for secret in secrets():
        for blob in blobs:
            assert secret not in blob
    assert "0101" in html  # the last four are still there for a person to match


def test_site_is_self_contained(paths):
    store = Store(paths.db)
    run = run_audit(paths, store, as_of=AS_OF)
    index = open(site.write_site(run, store, os.path.join(paths.out, "site"))).read()
    assert "<script src" not in index and "<link" not in index
    assert "http://" not in index and "https://" not in index
    assert "Demo on synthetic data. Not affiliated with Buildium" in index
    assert "Demo: approvals here don" in index
