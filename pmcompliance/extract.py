"""Document extraction: PDF text -> structured fields with evidence.

Routing
  * text route: the PDF has a text layer; pypdf reads it.
  * vision route: no usable text layer (a scan); the page image goes to a
    vision-capable model (live) or a recorded result is replayed (offline).

Modes
  * offline (default): replay JSON fixtures keyed by the PDF's SHA-256, so the
    demo and CI are deterministic and need no network or key.
  * live: call Claude (needs ANTHROPIC_API_KEY and the `anthropic` package).
    With record=True the live result is written back as the new fixture.

Whatever the source, every field keeps its evidence (page + source line), all
evidence is PII-masked, and text-route evidence is checked against the real
page text so a hallucinated quote is caught in code.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from . import pii

DOC_TYPES = ["coi", "w9", "trade_license", "landlord_insurance", "management_agreement",
             "direct_deposit", "hoa_rules", "unknown"]

FIELD_GUIDE = {
    "coi": "insured_name, insurer, policy_type, policy_number, effective_date, expiry_date, "
           "per_occurrence_limit, aggregate_limit, additional_insured",
    "w9": "legal_name, tax_classification, tin_last4 (last 4 digits only), signature, signed_date",
    "trade_license": "licensee_name, trade, license_number, state, issue_date, expiry_date",
    "landlord_insurance": "insured_name, property_address, policy_type, policy_number, "
                          "effective_date, expiry_date, liability_limit, additional_insured",
    "management_agreement": "owner_name, property_address, effective_date, signature "
                            "(owner signature text, empty if blank)",
    "direct_deposit": "payee_name, account_last4 (last 4 digits only), signature",
    "hoa_rules": "hoa_name, property_address, effective_date",
}

MIN_TEXT_CHARS = 40  # below this a page set is treated as having no text layer


@dataclass
class Field:
    value: str
    page: int
    line: str
    confidence: float
    verified: Optional[bool] = None  # None = could not be checked (vision route)


@dataclass
class Extraction:
    path: str
    sha256: str
    route: str  # "text" | "vision"
    extractor: str
    doc_type: str
    doc_type_confidence: float
    fields: Dict[str, Field] = field(default_factory=dict)
    error: Optional[str] = None

    def get(self, name: str) -> Optional[Field]:
        return self.fields.get(name)


class ExtractionError(Exception):
    pass


def sha256_file(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def read_pages(path: str) -> List[str]:
    from pypdf import PdfReader

    reader = PdfReader(path)
    return [(page.extract_text() or "") for page in reader.pages]


def choose_route(pages: List[str]) -> str:
    chars = sum(len(re.sub(r"\s+", "", p)) for p in pages)
    return "text" if chars >= MIN_TEXT_CHARS else "vision"


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def _verify(fields: Dict[str, Field], masked_pages: List[str]) -> None:
    for f in fields.values():
        if not f.line:
            f.verified = False
            continue
        idx = f.page - 1
        haystack = masked_pages[idx] if 0 <= idx < len(masked_pages) else ""
        f.verified = _norm(f.line) in _norm(haystack)


def _from_json(data: dict, path: str, sha: str, route: str, extractor: str) -> Extraction:
    raw_fields = data.get("fields", {})
    if isinstance(raw_fields, list):  # live schema returns a list
        raw_fields = {f["name"]: f for f in raw_fields}
    fields = {}
    for name, f in raw_fields.items():
        value = str(f.get("value", "") or "")
        if name in ("tin_last4", "account_last4"):
            value = "".join(c for c in value if c.isdigit())[-4:]
        fields[name] = Field(value=pii.mask(value), page=int(f.get("page", 1) or 1),
                             line=pii.mask(str(f.get("line", "") or "")),
                             confidence=float(f.get("confidence", 0.0) or 0.0))
    doc_type = data.get("doc_type", "unknown")
    if doc_type not in DOC_TYPES:
        doc_type = "unknown"
    return Extraction(path=path, sha256=sha, route=route, extractor=extractor, doc_type=doc_type,
                      doc_type_confidence=float(data.get("doc_type_confidence", 0.0) or 0.0),
                      fields=fields)


def extract(path: str, fixtures_dir: str, mode: str = "offline", record: bool = False,
            model: Optional[str] = None) -> Extraction:
    sha = sha256_file(path)
    try:
        pages = read_pages(path)
    except Exception as exc:  # corrupt PDF: never crash the audit
        return Extraction(path, sha, "text", "none", "unknown", 0.0, error="unreadable PDF: %s" % exc)
    route = choose_route(pages)
    masked_pages = [pii.mask(p) for p in pages]

    if mode == "live":
        data = _live_extract(path, masked_pages, route, model)
        extractor = "live:%s" % (model or default_model())
        if record:
            data = dict(data, sha256=sha, source=path, route=route, extractor="recorded " + extractor)
            _write_fixture(fixtures_dir, sha, data)
    else:
        fx = os.path.join(fixtures_dir, sha + ".json")
        if not os.path.exists(fx):
            return Extraction(path, sha, route, "none", "unknown", 0.0,
                              error="no recorded extraction for this file (run live with --record)")
        with open(fx) as fh:
            data = json.load(fh)
        if data.get("route") != route:
            # The recording must have taken the same path the file needs today.
            return Extraction(path, sha, route, "none", "unknown", 0.0,
                              error="fixture route %s != detected route %s" % (data.get("route"), route))
        extractor = "replay:%s" % ("vision" if route == "vision" else "text")

    ex = _from_json(data, path, sha, route, extractor)
    if route == "text":
        _verify(ex.fields, masked_pages)
    return ex


def _write_fixture(fixtures_dir: str, sha: str, data: dict) -> None:
    os.makedirs(fixtures_dir, exist_ok=True)
    with open(os.path.join(fixtures_dir, sha + ".json"), "w") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
        fh.write("\n")


# ------------------------------------------------------------------ live mode
def default_model() -> str:
    return os.environ.get("PMC_MODEL", "claude-opus-5-5")


_SCHEMA = {
    "type": "object",
    "properties": {
        "doc_type": {"type": "string", "enum": DOC_TYPES},
        "doc_type_confidence": {"type": "number"},
        "fields": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "value": {"type": "string"},
                    "page": {"type": "integer"},
                    "line": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["name", "value", "page", "line", "confidence"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["doc_type", "doc_type_confidence", "fields"],
    "additionalProperties": False,
}

_PROMPT = """You extract fields from documents a residential property manager collects
from vendors and rental owners. Classify the document as one of: {types}.
Then return the fields for that type, copying each value exactly as printed
(do not reformat dates or amounts; code parses them):
{guide}
For every field give the 1-based page number, the full source line it came
from, copied verbatim, and a confidence between 0 and 1. If a field is not
on the document, omit it. Tax IDs and account numbers are already masked;
never try to reconstruct them."""


def _live_extract(path: str, masked_pages: List[str], route: str, model: Optional[str]) -> dict:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise ExtractionError("live mode needs ANTHROPIC_API_KEY; use offline mode instead")
    try:
        import anthropic
    except ImportError as exc:
        raise ExtractionError("live mode needs the anthropic package (pip install anthropic)") from exc

    guide = "\n".join("- %s: %s" % (k, v) for k, v in FIELD_GUIDE.items())
    prompt = _PROMPT.format(types=", ".join(DOC_TYPES), guide=guide)
    if route == "text":
        body = "\n\n".join("--- page %d ---\n%s" % (i + 1, t) for i, t in enumerate(masked_pages))
        content = [{"type": "text", "text": prompt + "\n\nDocument text:\n" + body}]
    else:
        # A scan: send the PDF itself so the model reads the page image.
        # Note: the image is not PII-masked; see README "PII handling".
        with open(path, "rb") as fh:
            b64 = base64.standard_b64encode(fh.read()).decode("ascii")
        content = [
            {"type": "document",
             "source": {"type": "base64", "media_type": "application/pdf", "data": b64}},
            {"type": "text", "text": prompt},
        ]
    client = anthropic.Anthropic()
    response = client.beta.messages.create(
        model=model or default_model(),
        max_tokens=4000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": _SCHEMA}},
        messages=[{"role": "user", "content": content}],
    )
    if response.stop_reason == "refusal":
        raise ExtractionError("model declined the request")
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)
