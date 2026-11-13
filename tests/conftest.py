import os
import sys
from datetime import date

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pmcompliance.checks import load_requirements  # noqa: E402
from pmcompliance.extract import Extraction, Field  # noqa: E402
from pmcompliance.pipeline import Paths  # noqa: E402

AS_OF = date(2026, 11, 13)


@pytest.fixture
def req():
    return load_requirements(os.path.join(ROOT, "config", "requirements.json"))


@pytest.fixture
def paths(tmp_path):
    return Paths(data=os.path.join(ROOT, "data"),
                 config=os.path.join(ROOT, "config", "requirements.json"),
                 out=str(tmp_path / "out"))


def make_ex(doc_type, route="text", **fields):
    """Build an Extraction by hand: field=value or field=(value, confidence)."""
    out = {}
    for name, v in fields.items():
        value, conf = v if isinstance(v, tuple) else (v, 0.97)
        out[name] = Field(value=value, page=1, line="%s: %s" % (name, value), confidence=conf,
                          verified=True if route == "text" else None)
    return Extraction(path="x.pdf", sha256="0" * 64, route=route, extractor="test",
                      doc_type=doc_type, doc_type_confidence=0.99, fields=out)


def coi(expiry="07/01/2027", limit="$1,000,000", name="Acme Electric LLC",
        ai="Sample Residential Management LLC", route="text", exp_conf=0.97):
    return make_ex("coi", route=route, insured_name=name, expiry_date=(expiry, exp_conf),
                   per_occurrence_limit=limit, additional_insured=ai)
