"""Compliance rules. All decisions are made here, in code, from parsed values.

Statuses (per document and rolled up per entity):
  compliant      everything on file and valid
  expiring_soon  valid, but expires within the reminder window (default 30 days)
  expired        expiry date is in the past (and was read with confidence)
  missing        required document not on file
  needs_review   a person must look: low confidence, name mismatch, coverage
                 below minimum, missing additional insured, unsigned, unreadable
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Tuple

from . import names
from .extract import Extraction, Field
from .parsing import parse_date, parse_money

STATUS_ORDER = {"compliant": 0, "expiring_soon": 1, "needs_review": 2, "missing": 3, "expired": 4}


def load_requirements(path: str) -> dict:
    with open(path) as fh:
        return json.load(fh)


def required_docs(req: dict, kind: str, trade: Optional[str] = None,
                  has_hoa: bool = False) -> List[str]:
    if kind == "vendor":
        by_trade = req["vendor"]["by_trade"]
        if trade not in by_trade:
            raise KeyError("no requirements defined for trade %r" % trade)
        return list(req["vendor"]["all_trades"]) + list(by_trade[trade])
    docs = list(req["owner"]["always"])
    if has_hoa:
        docs += req["owner"]["if_property_has_hoa"]
    return docs


@dataclass
class Finding:
    entity_id: str
    doc_type: str
    label: str
    status: str
    reasons: List[str] = field(default_factory=list)
    expiry: Optional[date] = None
    days_left: Optional[int] = None
    extraction: Optional[Extraction] = None
    blocks_dispatch: bool = False
    checks: List[Tuple[str, bool, str]] = field(default_factory=list)  # (check, passed, detail)

    def evidence(self) -> List[Tuple[str, Field]]:
        if not self.extraction:
            return []
        return sorted(self.extraction.fields.items())


@dataclass
class EntityResult:
    kind: str
    entity_id: str
    name: str
    email: str
    detail: str
    status: str
    findings: List[Finding]
    dispatch_paused: bool = False
    meta: Dict[str, object] = field(default_factory=dict)

    def finding(self, doc_type: str) -> Optional[Finding]:
        for f in self.findings:
            if f.doc_type == doc_type:
                return f
        return None


def _key_fields(doc_type: str, spec: dict) -> List[str]:
    keys = []
    if spec.get("name_field"):
        keys.append(spec["name_field"])
    if spec.get("expires"):
        keys.append("expiry_date")
    if spec.get("min_per_occurrence"):
        keys.append("per_occurrence_limit")
    if spec.get("additional_insured_required"):
        keys.append("additional_insured")
    if spec.get("signature_required"):
        keys.append("signature")
    if spec.get("tin_required"):
        keys.append("tin_last4")
    return keys


_PRETTY = {
    "insured_name": "insured name", "legal_name": "legal name", "licensee_name": "licensee",
    "owner_name": "owner name", "payee_name": "payee name", "expiry_date": "expiry date",
    "per_occurrence_limit": "each-occurrence limit", "additional_insured": "additional insured",
    "signature": "signature", "tin_last4": "TIN",
}


def check_document(entity_id: str, entity_name: str, doc_type: str, ex: Extraction, req: dict,
                   as_of: date) -> Finding:
    spec = req["doc_types"][doc_type]
    min_conf = req["min_confidence"]
    f = Finding(entity_id, doc_type, spec["label"], "compliant", extraction=ex,
                blocks_dispatch=bool(spec.get("blocks_dispatch")))
    reasons: List[str] = []

    def chk(name: str, ok: bool, detail: str, reason: Optional[str] = None) -> None:
        f.checks.append((name, ok, detail))
        if not ok and reason:
            reasons.append(reason)

    chk("Document type", ex.doc_type_confidence >= min_conf,
        "%s (%.2f)" % (doc_type, ex.doc_type_confidence),
        "document type uncertain (%.2f)" % ex.doc_type_confidence)
    low, unverified, absent = [], [], []
    for key in _key_fields(doc_type, spec):
        fld = ex.get(key)
        pretty = _PRETTY.get(key, key)
        if fld is None or not fld.value.strip():
            absent.append(key)
            if key == "signature":
                reasons.append("not signed")
            elif key == "additional_insured":
                reasons.append("no additional insured listed")
            else:
                reasons.append("%s not found" % pretty)
            continue
        if fld.confidence < min_conf:
            low.append(key)
            via = " (read from a scan)" if ex.route == "vision" else ""
            reasons.append("low confidence %.2f on %s%s" % (fld.confidence, pretty, via))
        if fld.verified is False:
            unverified.append(key)
            reasons.append("%s quote not found in the document text" % pretty)
    f.checks.append(("Key fields present", not absent,
                     "all present" if not absent else "missing: " + ", ".join(absent)))
    f.checks.append(("Confidence >= %.2f" % min_conf, not low,
                     "all key fields" if not low else "low: " + ", ".join(low)))
    if ex.route == "text":
        f.checks.append(("Evidence found in PDF text", not unverified,
                         "every quote matched" if not unverified
                         else "not found: " + ", ".join(unverified)))
    else:
        f.checks.append(("Evidence found in PDF text", False,
                         "scan has no text layer; a person confirms low-confidence values"))

    # Name on the document vs name on the record.
    nf = spec.get("name_field")
    if nf and ex.get(nf) and ex.get(nf).value.strip():
        doc_name = ex.get(nf).value
        verdict = names.match(doc_name, entity_name, **req["name_match"])
        score = names.similarity(doc_name, entity_name)
        label = _PRETTY.get(nf, nf)
        chk("Name matches record", verdict == "match",
            '"%s" vs "%s" (score %.2f)' % (doc_name, entity_name, score),
            ('%s "%s" does not match "%s" (%.2f)' if verdict == "mismatch"
             else '%s "%s" is close to "%s" (%.2f); confirm') % (label, doc_name, entity_name,
                                                                 score))

    # Coverage minimum.
    minimum = spec.get("min_per_occurrence")
    lim = ex.get("per_occurrence_limit")
    if minimum and lim and lim.value.strip():
        amount = parse_money(lim.value)
        if amount is None:
            chk("GL each occurrence >= minimum", False, "unreadable: %r" % lim.value,
                "each-occurrence limit unreadable: %r" % lim.value)
        else:
            chk("GL each occurrence >= minimum", amount >= minimum,
                "$%s vs $%s required" % (format(amount, ","), format(minimum, ",")),
                "GL each occurrence $%s is below the $%s minimum"
                % (format(amount, ","), format(minimum, ",")))

    # Management company as additional insured.
    ai = ex.get("additional_insured")
    if spec.get("additional_insured_required") and ai and ai.value.strip():
        mgmt = req["management_company"]
        ok = names.normalize(mgmt) in names.normalize(ai.value) or \
            names.similarity(ai.value, mgmt) >= req["name_match"]["accept"]
        chk("Management company is additional insured", ok, ai.value,
            "%s not named as additional insured" % mgmt)

    sig = ex.get("signature")
    if spec.get("signature_required") and sig and sig.value.strip():
        chk("Signed", sig.value.strip().lower() not in ("none", "n/a"), sig.value, "not signed")
    elif spec.get("signature_required"):
        f.checks.append(("Signed", False, "signature line blank"))
    tin = ex.get("tin_last4")
    if spec.get("tin_required") and tin:
        chk("TIN present", len(tin.value) == 4, "ending %s" % tin.value, "TIN incomplete")

    # Expiry.
    status = "compliant"
    if spec.get("expires"):
        exp_field = ex.get("expiry_date")
        exp = parse_date(exp_field.value) if exp_field else None
        if exp_field and exp_field.value and exp is None:
            chk("Expiry date", False, "unreadable: %r" % exp_field.value,
                "expiry date unreadable: %r" % exp_field.value)
        if exp is not None:
            f.expiry = exp
            f.days_left = (exp - as_of).days
            trusted = exp_field.confidence >= min_conf and exp_field.verified is not False
            window = req["reminder_window_days"]
            f.checks.append(("Not expired, > %d days left" % window, f.days_left > window,
                             "%s (%d days)" % (exp.isoformat(), f.days_left)))
            if f.days_left < 0 and trusted:
                status = "expired"
                reasons.insert(0, "expired %s (%d days ago)" % (exp.isoformat(), -f.days_left))
            elif f.days_left < 0:
                reasons.insert(0, "reads as expired, but the date is uncertain")
            elif f.days_left <= window:
                if not reasons:
                    status = "expiring_soon"
                reasons.append("expires in %d days" % f.days_left)
    if status == "compliant" and reasons:
        status = "needs_review"
    f.status = status
    f.reasons = reasons
    return f


def _pick(extractions: List[Extraction]) -> Extraction:
    """Several files of one type: prefer the one that expires last."""
    def key(ex: Extraction):
        fld = ex.get("expiry_date")
        d = parse_date(fld.value) if fld else None
        return d or date.min
    return sorted(extractions, key=key)[-1]


def evaluate(kind: str, entity_id: str, name: str, email: str, detail: str, required: List[str],
             extractions: List[Extraction], req: dict, as_of: date,
             meta: Optional[dict] = None) -> EntityResult:
    by_type: Dict[str, List[Extraction]] = {}
    for ex in extractions:
        by_type.setdefault(ex.doc_type, []).append(ex)
    findings: List[Finding] = []
    for doc_type in required:
        spec = req["doc_types"][doc_type]
        if doc_type not in by_type:
            findings.append(Finding(entity_id, doc_type, spec["label"], "missing",
                                    ["%s not on file" % spec["label"]],
                                    blocks_dispatch=bool(spec.get("blocks_dispatch"))))
            continue
        findings.append(check_document(entity_id, name, doc_type, _pick(by_type[doc_type]),
                                       req, as_of))
    for ex in by_type.get("unknown", []):
        findings.append(Finding(entity_id, "unclassified", "Unclassified file", "needs_review",
                                [ex.error or "document type not recognised"], extraction=ex))
    status = max((f.status for f in findings), key=lambda s: STATUS_ORDER[s], default="compliant")
    paused = any(f.blocks_dispatch and f.status in ("expired", "missing") for f in findings)
    return EntityResult(kind, entity_id, name, email, detail, status, findings,
                        dispatch_paused=paused if kind == "vendor" else False, meta=meta or {})
