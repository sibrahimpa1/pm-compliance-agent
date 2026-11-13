from datetime import date

import pytest

from conftest import AS_OF, coi, make_ex
from pmcompliance.checks import check_document, evaluate, required_docs
from pmcompliance.parsing import parse_date, parse_money


@pytest.mark.parametrize("raw,expected", [
    ("12/01/2026", date(2026, 12, 1)),
    ("2026-12-01", date(2026, 12, 1)),
    ("December 1, 2026", date(2026, 12, 1)),
    ("Dec 1, 2026", date(2026, 12, 1)),
    ("September 30th, 2027", date(2027, 9, 30)),
    ("31/12/2026", None),
    ("", None),
])
def test_parse_date(raw, expected):
    assert parse_date(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("$1,000,000", 1000000), ("1M", 1000000), ("$500K", 500000), ("$1.5M", 1500000),
    ("one million", None),
])
def test_parse_money(raw, expected):
    assert parse_money(raw) == expected


@pytest.mark.parametrize("expiry,status", [
    ("12/14/2026", "compliant"),       # 31 days
    ("12/13/2026", "expiring_soon"),   # exactly 30 days
    ("11/13/2026", "expiring_soon"),   # expires today
    ("11/12/2026", "expired"),         # yesterday
])
def test_expiry_status_against_fixed_as_of(req, expiry, status):
    f = check_document("V-1", "Acme Electric LLC", "coi", coi(expiry=expiry), req, AS_OF)
    assert f.status == status


def test_as_of_moves_the_answer(req):
    ex = coi(expiry="12/01/2026")
    assert check_document("V-1", "Acme Electric LLC", "coi", ex, req, date(2026, 10, 1)).status \
        == "compliant"
    assert check_document("V-1", "Acme Electric LLC", "coi", ex, req, date(2026, 11, 13)).status \
        == "expiring_soon"
    assert check_document("V-1", "Acme Electric LLC", "coi", ex, req, date(2026, 12, 2)).status \
        == "expired"


def test_coverage_below_minimum_needs_review(req):
    f = check_document("V-1", "Acme Electric LLC", "coi", coi(limit="$500,000"), req, AS_OF)
    assert f.status == "needs_review"
    assert any("below the $1,000,000 minimum" in r for r in f.reasons)


def test_missing_additional_insured_needs_review(req):
    f = check_document("V-1", "Acme Electric LLC", "coi", coi(ai="None"), req, AS_OF)
    assert f.status == "needs_review"
    assert any("additional insured" in r for r in f.reasons)


def test_name_mismatch_needs_review(req):
    f = check_document("V-1", "Acme Electric LLC", "coi", coi(name="Zenith Roofing Inc."), req,
                       AS_OF)
    assert f.status == "needs_review"


def test_low_confidence_expired_date_is_not_trusted(req):
    ex = coi(expiry="10/01/2026", route="vision", exp_conf=0.55)
    f = check_document("V-1", "Acme Electric LLC", "coi", ex, req, AS_OF)
    assert f.status == "needs_review"
    assert any("uncertain" in r for r in f.reasons)


def test_unsigned_agreement_needs_review(req):
    ex = make_ex("management_agreement", owner_name="Pat Example", signature="")
    f = check_document("O-1", "Pat Example", "management_agreement", ex, req, AS_OF)
    assert f.status == "needs_review"
    assert "not signed" in f.reasons


def test_requirement_matrix(req):
    assert required_docs(req, "vendor", trade="electrical") == ["coi", "w9", "trade_license"]
    assert required_docs(req, "vendor", trade="cleaning") == ["coi", "w9"]
    assert "hoa_rules" in required_docs(req, "owner", has_hoa=True)
    assert "hoa_rules" not in required_docs(req, "owner", has_hoa=False)
    with pytest.raises(KeyError):
        required_docs(req, "vendor", trade="roofing")


def test_missing_coi_pauses_dispatch_missing_licence_does_not(req):
    w9 = make_ex("w9", legal_name="Acme Electric LLC", tin_last4="0123", signature="/s/ x")
    lic_only_missing = evaluate("vendor", "V-1", "Acme Electric LLC", "", "electrical",
                                required_docs(req, "vendor", trade="electrical"),
                                [coi(), w9], req, AS_OF)
    assert lic_only_missing.finding("trade_license").status == "missing"
    assert lic_only_missing.dispatch_paused is False
    coi_missing = evaluate("vendor", "V-1", "Acme Electric LLC", "", "cleaning",
                           required_docs(req, "vendor", trade="cleaning"), [w9], req, AS_OF)
    assert coi_missing.status == "missing"
    assert coi_missing.dispatch_paused is True
