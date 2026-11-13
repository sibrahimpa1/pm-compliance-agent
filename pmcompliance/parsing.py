"""Deterministic parsing of values the model returns as raw strings.

The model reads; code decides. Dates and amounts are parsed here so a
"12/01/2026" never turns into a different day because of a model guess.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Optional

_DATE_FORMATS = ("%m/%d/%Y", "%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%m-%d-%Y", "%d %B %Y",
                 "%m/%d/%y")


def parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    s = re.sub(r"\s+", " ", value.strip().rstrip("."))
    s = re.sub(r"(\d)(st|nd|rd|th),", r"\1,", s)
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def parse_money(value: Optional[str]) -> Optional[int]:
    """'$1,000,000' -> 1000000, '$1M' -> 1000000, '500K' -> 500000."""
    if not value:
        return None
    s = value.strip().upper().replace("$", "").replace(",", "").replace("USD", "").strip()
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([KM]?)", s)
    if not m:
        return None
    n = float(m.group(1))
    n *= {"": 1, "K": 1_000, "M": 1_000_000}[m.group(2)]
    return int(round(n))


def parse_yes(value: Optional[str]) -> Optional[bool]:
    if value is None:
        return None
    s = value.strip().lower()
    if s in ("yes", "y", "true", "signed", "x", "on file"):
        return True
    if s in ("no", "n", "false", "", "unsigned", "none", "not signed"):
        return False
    return None


def days_until(d: date, as_of: date) -> int:
    return (d - as_of).days
