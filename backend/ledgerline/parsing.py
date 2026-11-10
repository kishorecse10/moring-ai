"""Turn the strings the model copies off the page into Python values.

AP_POLICY.md section 1 governs both functions here:
- Amounts are exact decimals with two places. They are never binary floating point.
- Indian vendors print dates day first. Vendors whose country is US print them month first.
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

_TWO_PLACES = Decimal("0.01")
_MULTIPLIERS = {"lakh": Decimal(100_000), "lakhs": Decimal(100_000), "lac": Decimal(100_000),
                "crore": Decimal(10_000_000), "crores": Decimal(10_000_000), "cr": Decimal(10_000_000)}
_CURRENCY_TOKENS = re.compile(r"(₹|\$|\bRs\.?|\bINR\b|\bUSD\b)", re.IGNORECASE)
_AMOUNT = re.compile(r"^(-)?\s*(\d[\d,]*(?:\.\d+)?|\.\d+)\s*(lakhs?|lac|crores?|cr)?$", re.IGNORECASE)


def parse_amount(value) -> Decimal | None:
    """'₹ 1,23,456.00' -> Decimal('123456.00'); '₹1.2 lakh' -> Decimal('120000.00'); 'Rs. 66,375/-' -> 66375.00.

    Raises ValueError for anything it can't read with certainty, so the caller can route the document to
    `processing_error` instead of guessing.
    """
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError(f"not an amount: {value!r}")
    if isinstance(value, Decimal):
        return value.quantize(_TWO_PLACES)
    if isinstance(value, int):
        return Decimal(value).quantize(_TWO_PLACES)
    if isinstance(value, float):
        # JSON numbers arrive as floats. repr() is the shortest string that round-trips, so 1789.2 -> '1789.2'.
        return Decimal(repr(value)).quantize(_TWO_PLACES)
    text = str(value).strip()
    text = _CURRENCY_TOKENS.sub("", text)
    text = text.replace("/-", "").replace(" ", "").strip()
    if text.startswith("(") and text.endswith(")"):  # accounting negative
        text = "-" + text[1:-1]
    # Keep the multiplier word separable from the digits for the regex.
    text = re.sub(r"(?i)(\d)(lakhs?|lac|crores?|cr)$", r"\1 \2", text)
    match = _AMOUNT.match(text)
    if not match:
        raise ValueError(f"not an amount: {value!r}")
    sign, digits, word = match.groups()
    try:
        amount = Decimal(digits.replace(",", ""))
    except InvalidOperation as exc:
        raise ValueError(f"not an amount: {value!r}") from exc
    if word:
        amount *= _MULTIPLIERS[word.lower()]
    if sign:
        amount = -amount
    return amount.quantize(_TWO_PLACES)


_ISO_DATE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_NUMERIC_DATE = re.compile(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})$")
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_WORD_DATE_DMY = re.compile(r"^(\d{1,2})(?:st|nd|rd|th)?[\s\-]+([A-Za-z]{3,9})\.?,?[\s\-]+(\d{4})$")
_WORD_DATE_MDY = re.compile(r"^([A-Za-z]{3,9})\.?[\s\-]+(\d{1,2})(?:st|nd|rd|th)?,?[\s\-]+(\d{4})$")


def parse_date(value, month_first: bool = False) -> date | None:
    """Parse a printed document date.

    Numeric dates are day first (DD/MM/YYYY, DD-MM-YYYY, DD.MM.YYYY) unless `month_first` is set, which the
    caller does for vendors whose country in the vendor master is US. ISO dates and dates with a month name
    are unambiguous. Anything else raises ValueError: we never let a library guess the order.
    """
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if m := _ISO_DATE.match(text):
        return date(int(m[1]), int(m[2]), int(m[3]))
    if m := _NUMERIC_DATE.match(text):
        first, second, year = int(m[1]), int(m[2]), int(m[3])
        month, day = (first, second) if month_first else (second, first)
        return date(year, month, day)
    if m := _WORD_DATE_DMY.match(text):
        return date(int(m[3]), _month(m[2]), int(m[1]))
    if m := _WORD_DATE_MDY.match(text):
        return date(int(m[3]), _month(m[1]), int(m[2]))
    raise ValueError(f"unrecognised date format: {value!r}")


def _month(name: str) -> int:
    key = name[:3].lower()
    if key not in _MONTHS:
        raise ValueError(f"unknown month: {name!r}")
    return _MONTHS[key]


_LEADING_NUMBER = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")


def parse_lenient_number(value) -> Decimal | None:
    """For quantity and unit price, which no policy rule uses: '750 kg' -> 750, 'Rs 112.50 / kg' -> 112.50.

    These are display fields. Failing a document over '10 PKT' would send a clean invoice to review (~₹85 of AP
    time) for no control benefit, so anything unreadable becomes None instead of an error. Money fields that
    drive routing (line amounts, taxes, round-off, totals) still go through the strict parse_amount.
    """
    if value is None or value == "":
        return None
    try:
        return parse_amount(value)
    except ValueError:
        pass
    match = _LEADING_NUMBER.search(_CURRENCY_TOKENS.sub("", str(value)))
    if not match:
        return None
    try:
        return Decimal(match.group(0).replace(",", ""))
    except InvalidOperation:
        return None
