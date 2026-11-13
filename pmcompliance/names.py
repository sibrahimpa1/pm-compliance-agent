"""Fuzzy matching between the name on a document and the name on the record."""
from __future__ import annotations

import re
from difflib import SequenceMatcher

# Legal-form and filler words that should not decide a match.
_NOISE = {
    "llc", "l.l.c", "inc", "incorporated", "co", "company", "corp", "corporation", "ltd",
    "lp", "llp", "pllc", "the", "and", "dba", "of",
}


def normalize(name: str) -> str:
    s = (name or "").lower().replace("&", " and ")
    s = re.sub(r"(?<=\b[a-z])\.(?=[a-z]\b)", "", s)  # H.V.A.C -> hvac
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    words = [w for w in s.split() if w not in _NOISE]
    return " ".join(words)


def similarity(a: str, b: str) -> float:
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    seq = SequenceMatcher(None, na, nb).ratio()
    ta, tb = set(na.split()), set(nb.split())
    jacc = len(ta & tb) / len(ta | tb)
    return round(max(seq, (seq + jacc) / 2), 3)


def match(a: str, b: str, accept: float = 0.9, review: float = 0.75) -> str:
    """Return 'match', 'review' (close but not certain) or 'mismatch'."""
    score = similarity(a, b)
    if score >= accept:
        return "match"
    if score >= review:
        return "review"
    return "mismatch"
