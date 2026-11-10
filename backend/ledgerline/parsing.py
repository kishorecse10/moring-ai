"""Turn the strings the model copies off the page into Python values."""
from __future__ import annotations

from datetime import date

from dateutil import parser as dateparser


def parse_amount(value) -> float | None:
    """'₹ 1,23,456.00' -> 123456.0"""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = str(value).replace("₹", "").replace("INR", "").replace(",", "").strip()
    return float(cleaned)


def parse_date(value) -> date | None:
    """Accept whatever date format the vendor printed."""
    if not value:
        return None
    return dateparser.parse(str(value)).date()
