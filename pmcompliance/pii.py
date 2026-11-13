"""PII handling: mask tax IDs and bank account numbers before anything is
stored, logged, rendered or sent to a model. Only the last 4 digits survive."""
from __future__ import annotations

import re
from typing import List, Tuple

# EIN 00-0000000, SSN/ITIN 000-00-0000, or 9 digits right after a TIN label.
_TIN_PATTERNS = [
    re.compile(r"(?<![\d-])\d{2}-\d{7}(?![\d-])"),
    re.compile(r"(?<![\d-])\d{3}-\d{2}-\d{4}(?![\d-])"),
    re.compile(r"(?i)(?<=TIN: )\d{9}\b|(?<=EIN: )\d{9}\b|(?<=SSN: )\d{9}\b"),
]
# Bank account / routing numbers that follow a label.
_ACCOUNT = re.compile(r"(?i)((?:account|routing)\s*(?:number|no\.?|#)?\s*:\s*)(\d[\d -]{3,20}\d)")


def _mask_digits(s: str, keep: int = 4) -> str:
    digits = [i for i, c in enumerate(s) if c.isdigit()]
    hide = set(digits[:-keep]) if len(digits) > keep else set(digits)
    return "".join("*" if i in hide else c for i, c in enumerate(s))


def find_tins(text: str) -> List[str]:
    found: List[str] = []
    for pat in _TIN_PATTERNS:
        found.extend(m.group(0) for m in pat.finditer(text))
    return found


def mask(text: str) -> str:
    """Return `text` with every TIN and labelled account number masked."""
    if not text:
        return text
    for pat in _TIN_PATTERNS:
        text = pat.sub(lambda m: _mask_digits(m.group(0)), text)
    text = _ACCOUNT.sub(lambda m: m.group(1) + _mask_digits(m.group(2)), text)
    return text


def redact_for_model(text: str) -> Tuple[str, List[str]]:
    """Mask text before it leaves the machine. Returns (masked_text, last4 list)."""
    last4 = ["".join(c for c in t if c.isdigit())[-4:] for t in find_tins(text)]
    return mask(text), last4
