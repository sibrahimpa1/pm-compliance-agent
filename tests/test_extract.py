import hashlib
import os
import shutil

from conftest import AS_OF, ROOT
from pmcompliance.extract import extract, read_pages
from pmcompliance.pipeline import run_audit
from pmcompliance.store import Store
from pmcompliance.synthetic import all_specs, render

DOCS = os.path.join(ROOT, "data", "docs")
FIXTURES = os.path.join(ROOT, "data", "fixtures")


def test_scanned_pdf_has_no_text_and_goes_to_vision():
    path = os.path.join(DOCS, "V-109", "scan_0042.pdf")
    assert "".join(read_pages(path)).strip() == ""
    ex = extract(path, FIXTURES)
    assert ex.route == "vision" and ex.extractor == "replay:vision"
    assert ex.doc_type == "coi"
    assert ex.fields["expiry_date"].verified is None  # cannot be checked against text


def test_text_pdf_evidence_is_verified_against_the_page():
    ex = extract(os.path.join(DOCS, "V-103", "coi.pdf"), FIXTURES)
    assert ex.route == "text"
    exp = ex.fields["expiry_date"]
    assert exp.value == "10/31/2026" and exp.page == 1
    assert exp.line == "Policy Expiration Date: 10/31/2026"
    assert all(f.verified for f in ex.fields.values())


def test_unknown_file_is_flagged_not_crashed(paths, tmp_path):
    data = str(tmp_path / "data")
    shutil.copytree(os.path.join(ROOT, "data"), data)
    with open(os.path.join(data, "docs", "V-101", "mystery.pdf"), "wb") as fh:
        fh.write(render(all_specs()[0]) + b"% re-saved by a scanner app\n")  # new hash
    paths.data = data
    run = run_audit(paths, Store(paths.db), as_of=AS_OF)
    v101 = next(r for _rec, r in run.vendors if r.entity_id == "V-101")
    unclassified = v101.finding("unclassified")
    assert unclassified.status == "needs_review"
    assert "no recorded extraction" in unclassified.reasons[0]


def test_generated_pdfs_are_deterministic():
    for spec in all_specs():
        with open(os.path.join(DOCS, spec.entity, spec.filename), "rb") as fh:
            committed = hashlib.sha256(fh.read()).hexdigest()
        assert hashlib.sha256(render(spec)).hexdigest() == committed, spec.relpath
        assert os.path.exists(os.path.join(FIXTURES, committed + ".json"))
