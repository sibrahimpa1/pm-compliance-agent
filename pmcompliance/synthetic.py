"""Synthetic vendor and owner documents.

Every name, address, tax ID and policy number here is invented. Tax IDs use
the reserved-looking 00-0000xxx / 000-00-0xxx patterns so nobody mistakes
them for real ones.

`build_all(out_root)` writes the PDFs to data/docs/<ENTITY_ID>/ and the
offline extraction fixtures to data/fixtures/<sha256>.json. The fixtures are
produced from the same spec as the PDFs (ground truth); running the extractor
in live mode with --record replaces them with real model output.
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Dict, List, Optional, Tuple

from .pdfwriter import PDF, TextPage, raster_page
from .pii import mask

MGMT = "Sample Residential Management LLC"
MGMT_ADDR = "500 Demo Blvd, Anytown, TX 00000"
BANNER = "SYNTHETIC SAMPLE FOR SOFTWARE TESTING - NOT A REAL DOCUMENT"

Row = Tuple[str, str, Optional[str], float]  # label, value, field name, confidence


class DocSpec:
    def __init__(self, entity: str, filename: str, doc_type: str, title: str,
                 rows: List[Row], scanned: bool = False) -> None:
        self.entity = entity
        self.filename = filename
        self.doc_type = doc_type
        self.title = title
        self.rows = rows
        self.scanned = scanned

    @property
    def relpath(self) -> str:
        return "%s/%s" % (self.entity, self.filename)


def _r(label: str, value: str, field: Optional[str] = None, conf: float = 0.97) -> Row:
    return (label, value, field, conf)


def coi(entity: str, insured: str, policy: str, eff: str, exp: str, each_occ: str,
        aggregate: str, additional_insured: str, filename: str = "coi.pdf",
        scanned: bool = False, conf: Optional[Dict[str, float]] = None) -> DocSpec:
    c = conf or {}
    rows = [
        _r("Producer", "Demo Insurance Brokers, 1 Example Plaza, Anytown, TX 00000"),
        _r("Insured", insured, "insured_name", c.get("insured_name", 0.98)),
        _r("Insurer A", "Example Mutual Insurance Co.", "insurer", c.get("insurer", 0.97)),
        _r("Type of Insurance", "Commercial General Liability - Occurrence", "policy_type",
           c.get("policy_type", 0.96)),
        _r("Policy Number", policy, "policy_number", c.get("policy_number", 0.97)),
        _r("Policy Effective Date", eff, "effective_date", c.get("effective_date", 0.97)),
        _r("Policy Expiration Date", exp, "expiry_date", c.get("expiry_date", 0.97)),
        _r("Each Occurrence", each_occ, "per_occurrence_limit", c.get("per_occurrence_limit", 0.96)),
        _r("General Aggregate", aggregate, "aggregate_limit", c.get("aggregate_limit", 0.96)),
        _r("Additional Insured", additional_insured, "additional_insured",
           c.get("additional_insured", 0.95)),
        _r("Certificate Holder", "%s, %s" % (MGMT, MGMT_ADDR)),
    ]
    return DocSpec(entity, filename, "coi", "CERTIFICATE OF LIABILITY INSURANCE", rows, scanned)


def w9(entity: str, legal_name: str, classification: str, tin_label: str, tin: str,
       signature: str, signed: str) -> DocSpec:
    rows = [
        _r("Name (as shown on your income tax return)", legal_name, "legal_name", 0.98),
        _r("Federal tax classification", classification, "tax_classification", 0.95),
        _r("Address", "Street address on file, Anytown, TX 00000"),
        _r("Taxpayer Identification Number (%s)" % tin_label, tin, "tin_last4", 0.97),
        _r("Signature of U.S. person", signature, "signature", 0.93),
        _r("Date", signed, "signed_date", 0.95),
    ]
    return DocSpec(entity, "w9.pdf", "w9",
                   "REQUEST FOR TAXPAYER IDENTIFICATION NUMBER AND CERTIFICATION (W-9)", rows)


def license_doc(entity: str, licensee: str, trade: str, number: str, state: str,
                issued: str, expires: str) -> DocSpec:
    rows = [
        _r("Licensee", licensee, "licensee_name", 0.98),
        _r("License Type", trade, "trade", 0.96),
        _r("License Number", number, "license_number", 0.98),
        _r("Issuing State", state, "state", 0.98),
        _r("Issued", issued, "issue_date", 0.96),
        _r("Expires", expires, "expiry_date", 0.97),
        _r("Issued by", "State Trade Licensing Board (synthetic)"),
    ]
    return DocSpec(entity, "trade_license.pdf", "trade_license", "STATE TRADE LICENSE", rows)


def landlord_insurance(entity: str, insured: str, prop: str, policy: str, eff: str,
                       exp: str) -> DocSpec:
    rows = [
        _r("Named Insured", insured, "insured_name", 0.98),
        _r("Insured Location", prop, "property_address", 0.96),
        _r("Policy Type", "Landlord Dwelling Policy (DP-3)", "policy_type", 0.96),
        _r("Policy Number", policy, "policy_number", 0.97),
        _r("Effective Date", eff, "effective_date", 0.97),
        _r("Expiration Date", exp, "expiry_date", 0.97),
        _r("Personal Liability Limit", "$300,000", "liability_limit", 0.95),
        _r("Additional Interest", MGMT, "additional_insured", 0.94),
    ]
    return DocSpec(entity, "landlord_insurance.pdf", "landlord_insurance",
                   "EVIDENCE OF PROPERTY INSURANCE - LANDLORD POLICY", rows)


def mgmt_agreement(entity: str, owner: str, prop: str, eff: str, owner_sig: str) -> DocSpec:
    rows = [
        _r("Owner", owner, "owner_name", 0.98),
        _r("Manager", MGMT),
        _r("Property", prop, "property_address", 0.96),
        _r("Effective Date", eff, "effective_date", 0.97),
        _r("Term", "12 months, renews automatically"),
        _r("Management Fee", "8% of collected rent"),
        _r("Owner Signature", owner_sig, "signature", 0.92),
        _r("Manager Signature", "/s/ Casey Example, Sample Residential Management LLC"),
    ]
    return DocSpec(entity, "management_agreement.pdf", "management_agreement",
                   "RESIDENTIAL PROPERTY MANAGEMENT AGREEMENT", rows)


def direct_deposit(entity: str, payee: str, account: str, signature: str) -> DocSpec:
    rows = [
        _r("Payee Name", payee, "payee_name", 0.98),
        _r("Bank Name", "Example Community Bank"),
        _r("Routing Number", "000000017"),
        _r("Account Number", account, "account_last4", 0.97),
        _r("Account Type", "Checking"),
        _r("Authorized Signature", signature, "signature", 0.93),
    ]
    return DocSpec(entity, "direct_deposit.pdf", "direct_deposit",
                   "OWNER DIRECT DEPOSIT AUTHORIZATION", rows)


def hoa_rules(entity: str, hoa: str, prop: str, revised: str) -> DocSpec:
    rows = [
        _r("Association", hoa, "hoa_name", 0.97),
        _r("Property", prop, "property_address", 0.95),
        _r("Rules Revision Date", revised, "effective_date", 0.95),
        _r("Pages", "Pet policy, parking, trash, quiet hours, architectural review"),
    ]
    return DocSpec(entity, "hoa_rules.pdf", "hoa_rules",
                   "HOMEOWNERS ASSOCIATION RULES AND REGULATIONS", rows)


AI_OK = MGMT
SIG = "/s/ signed electronically"


def all_specs() -> List[DocSpec]:
    s: List[DocSpec] = []
    # ---------------------------------------------------------------- vendors
    # V-101 everything valid
    s.append(coi("V-101", "Brightline Electric LLC", "CGL-00-1001", "07/01/2026", "07/01/2027",
                 "$1,000,000", "$2,000,000", AI_OK))
    s.append(w9("V-101", "Brightline Electric LLC", "LLC (partnership)", "EIN", "00-0000101", SIG,
                "01/15/2026"))
    s.append(license_doc("V-101", "Brightline Electric LLC", "Electrical Contractor", "EC-000101",
                         "TX", "09/30/2025", "September 30, 2027"))
    # V-102 COI expires in 18 days (reminder); name variant still matches
    s.append(coi("V-102", "Copperleaf Plumbing Company", "CGL-00-1002", "12/01/2025",
                 "12/01/2026", "$1,000,000", "$2,000,000", AI_OK))
    s.append(w9("V-102", "Copperleaf Plumbing Co.", "C corporation", "EIN", "00-0000102", SIG,
                "02/03/2026"))
    s.append(license_doc("V-102", "Copperleaf Plumbing Co.", "Master Plumber", "PL-000102", "TX",
                         "03/31/2025", "03/31/2027"))
    # V-103 COI expired -> dispatch paused
    s.append(coi("V-103", "Northgate H.V.A.C. Services, Inc.", "CGL-00-1003", "10/31/2025",
                 "10/31/2026", "$1,000,000", "$2,000,000", AI_OK))
    s.append(w9("V-103", "Northgate HVAC Services, Inc.", "C corporation", "EIN", "00-0000103", SIG,
                "11/20/2025"))
    s.append(license_doc("V-103", "Northgate HVAC Services, Inc.",
                         "Air Conditioning and Refrigeration Contractor", "AC-000103", "TX",
                         "2025-06-30", "2027-06-30"))
    # V-104 GL below the $1M per-occurrence minimum
    s.append(coi("V-104", "Greenway Grounds LLC", "CGL-00-1004", "05/01/2026", "04/30/2027",
                 "$500,000", "$1,000,000", AI_OK))
    s.append(w9("V-104", "Greenway Grounds LLC", "LLC (single member)", "EIN", "00-0000104", SIG,
                "05/02/2026"))
    # V-105 insured name does not match the vendor's legal name
    s.append(coi("V-105", "Sparkle Shine Janitorial Services Inc.", "CGL-00-1005", "06/01/2026",
                 "05/31/2027", "$1,000,000", "$2,000,000", AI_OK))
    s.append(w9("V-105", "Sparkle & Shine Cleaning LLC", "LLC (single member)", "EIN", "00-0000105",
                SIG, "06/04/2026"))
    # V-106 management company missing as additional insured
    s.append(coi("V-106", "Riverbend Electrical Contractors Inc.", "CGL-00-1006", "08/15/2026",
                 "08/15/2027", "$1,000,000", "$2,000,000", "None"))
    s.append(w9("V-106", "Riverbend Electrical Contractors Inc.", "S corporation", "EIN",
                "00-0000106", SIG, "08/20/2026"))
    s.append(license_doc("V-106", "Riverbend Electrical Contractors Inc.", "Electrical Contractor",
                         "EC-000106", "TX", "01/31/2026", "01/31/2028"))
    # V-107 W-9 missing (COI and licence fine; Buildium's insurance date is stale)
    s.append(coi("V-107", "Bluepipe Drain & Sewer LLC", "CGL-00-1007", "06/30/2026", "06/30/2027",
                 "$1,000,000", "$2,000,000", AI_OK))
    s.append(license_doc("V-107", "Bluepipe Drain & Sewer LLC", "Journeyman Plumber", "PL-000107",
                         "TX", "11/30/2025", "11/30/2027"))
    # V-108 licensed trade without a licence on file
    s.append(coi("V-108", "Coolbreeze Heating & Air LLC", "CGL-00-1008", "09/30/2026",
                 "09/30/2027", "$1,000,000", "$2,000,000", AI_OK))
    s.append(w9("V-108", "Coolbreeze Heating & Air LLC", "LLC (partnership)", "EIN", "00-0000108",
                SIG, "10/01/2026"))
    # V-109 COI is a scan with no text layer -> vision path, low confidence on expiry
    s.append(coi("V-109", "Fresh Start Cleaning Co.", "CGL-00-1009", "04/01/2026", "03/31/2027",
                 "$1,000,000", "$2,000,000", AI_OK, filename="scan_0042.pdf", scanned=True,
                 conf={"insured_name": 0.91, "insurer": 0.88, "policy_type": 0.86,
                       "policy_number": 0.84, "effective_date": 0.83, "expiry_date": 0.58,
                       "per_occurrence_limit": 0.87, "aggregate_limit": 0.85,
                       "additional_insured": 0.82}))
    s.append(w9("V-109", "Fresh Start Cleaning Co.", "Individual / sole proprietor", "SSN",
                "000-00-0109", SIG, "04/02/2026"))
    # ----------------------------------------------------------------- owners
    # O-201 complete file
    s.append(w9("O-201", "Harbor Lane Holdings LLC", "LLC (partnership)", "EIN", "00-0000201", SIG,
                "01/10/2026"))
    s.append(landlord_insurance("O-201", "Harbor Lane Holdings LLC",
                                "14 and 16 Harbor Lane, Anytown, TX 00000", "DP3-00-2001",
                                "06/01/2026", "05/31/2027"))
    s.append(mgmt_agreement("O-201", "Harbor Lane Holdings LLC",
                            "14 and 16 Harbor Lane, Anytown, TX 00000", "01/10/2026", SIG))
    s.append(direct_deposit("O-201", "Harbor Lane Holdings LLC", "000000004321", SIG))
    # O-202 property has an HOA, rules missing
    s.append(w9("O-202", "Elena Marsh", "Individual / sole proprietor", "SSN", "000-00-0202", SIG,
                "03/02/2026"))
    s.append(landlord_insurance("O-202", "Elena Marsh", "220 Willow Court, Anytown, TX 00000",
                                "DP3-00-2002", "03/01/2026", "02/28/2027"))
    s.append(mgmt_agreement("O-202", "Elena Marsh", "220 Willow Court, Anytown, TX 00000",
                            "03/01/2026", SIG))
    s.append(direct_deposit("O-202", "Elena Marsh", "000000005522", SIG))
    # O-203 W-9 and direct deposit form missing
    s.append(landlord_insurance("O-203", "Westbrook Family Trust",
                                "9 Westbrook Road, Anytown, TX 00000", "DP3-00-2003",
                                "09/01/2026", "08/31/2027"))
    s.append(mgmt_agreement("O-203", "Westbrook Family Trust",
                            "9 Westbrook Road, Anytown, TX 00000", "10/15/2026", SIG))
    # O-204 landlord insurance expired
    s.append(w9("O-204", "Tomas Vidal", "Individual / sole proprietor", "SSN", "000-00-0204", SIG,
                "02/11/2025"))
    s.append(landlord_insurance("O-204", "Tomas Vidal", "77 Quarry Street, Anytown, TX 00000",
                                "DP3-00-2004", "09/30/2025", "09/30/2026"))
    s.append(mgmt_agreement("O-204", "Tomas Vidal", "77 Quarry Street, Anytown, TX 00000",
                            "02/11/2025", SIG))
    s.append(direct_deposit("O-204", "Tomas Vidal", "000000007788", SIG))
    # O-205 agreement not signed by the owner; landlord policy renews in 27 days
    s.append(w9("O-205", "Maple Court Partners LP", "Partnership", "EIN", "00-0000205", SIG,
                "07/07/2026"))
    s.append(landlord_insurance("O-205", "Maple Court Partners LP",
                                "3 Maple Court, Anytown, TX 00000", "DP3-00-2005", "12/10/2025",
                                "12/10/2026"))
    s.append(mgmt_agreement("O-205", "Maple Court Partners LP", "3 Maple Court, Anytown, TX 00000",
                            "07/07/2026", ""))
    s.append(direct_deposit("O-205", "Maple Court Partners LP", "000000009911", SIG))
    s.append(hoa_rules("O-205", "Maple Court Owners Association",
                       "3 Maple Court, Anytown, TX 00000", "January 5, 2026"))
    return s


# --------------------------------------------------------------- rendering
def _line(label: str, value: str) -> str:
    return "%s: %s" % (label, value)


def render(spec: DocSpec) -> bytes:
    pdf = PDF()
    if spec.scanned:
        lines = [(spec.title, 2), ("", 1)]
        for lbl, val, field, conf in spec.rows:
            text = _line(lbl, val)
            if field and conf < 0.7:  # the low-confidence value sits under a smudge
                lines.append((text, 2, len(lbl) + 2))
            else:
                lines.append((text, 2))
        lines += [("", 1), (BANNER, 1)]
        pdf.add_page(raster_page(lines, seed=sum(map(ord, spec.relpath))))
        return pdf.to_bytes()
    page = TextPage()
    page.rect(36, 700, 540, 56, fill=0.93, stroke=None)
    page.text(50, 730, spec.title, size=13, bold=True)
    page.text(50, 712, BANNER, size=7.5, gray=0.35)
    y = 670
    for label, value, _field, _conf in spec.rows:
        page.text(50, y, _line(label, value), size=10.5)
        page.line(50, y - 7, 562, y - 7, gray=0.85)
        y -= 26
    page.rect(36, y - 10, 540, 700 - y, stroke=0.75)
    page.text(50, 60, "Generated for the pm-compliance-agent demo. All names, numbers and "
                      "addresses are invented.", size=7.5, gray=0.4)
    pdf.add_page(page)
    return pdf.to_bytes()


def fixture_for(spec: DocSpec, sha: str) -> dict:
    fields = {}
    for label, value, field, conf in spec.rows:
        if not field:
            continue
        line = _line(label, value)
        if spec.scanned:
            line = line.upper()
        if field in ("tin_last4", "account_last4"):
            value = "".join(ch for ch in value if ch.isdigit())[-4:]
        fields[field] = {"value": value, "page": 1, "line": mask(line), "confidence": conf}
    return {
        "sha256": sha,
        "source": "data/docs/" + spec.relpath,
        "route": "vision" if spec.scanned else "text",
        "extractor": "fixture: generated from the synthetic spec (replace with --record)",
        "doc_type": spec.doc_type,
        "doc_type_confidence": 0.9 if spec.scanned else 0.99,
        "fields": fields,
    }


def build_all(repo_root: str) -> List[Tuple[str, str]]:
    """Write PDFs and fixtures under repo_root. Returns [(relpath, sha256)]."""
    out = []
    fixtures_dir = os.path.join(repo_root, "data", "fixtures")
    os.makedirs(fixtures_dir, exist_ok=True)
    for spec in all_specs():
        data = render(spec)
        sha = hashlib.sha256(data).hexdigest()
        path = os.path.join(repo_root, "data", "docs", spec.entity, spec.filename)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)
        with open(os.path.join(fixtures_dir, sha + ".json"), "w") as fh:
            json.dump(fixture_for(spec, sha), fh, indent=2, sort_keys=True)
            fh.write("\n")
        out.append((spec.relpath, sha))
    return out
