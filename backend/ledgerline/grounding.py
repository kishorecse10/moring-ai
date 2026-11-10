"""Check that what the model extracted is actually printed in the document.

The model is asked to copy values exactly. If it "corrects" a GSTIN (an OCR'd 'B' read as '8'), takes a GSTIN
or bank account from somewhere other than the page, converts a date, or invents a total, the checks that
follow would be checking the wrong data. A value we can't find in the source means the document wasn't
processed reliably, so it goes to review as `processing_error` instead of silently passing.
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from .models import Invoice
from .parsing import parse_amount, parse_date
from .validation import digits_only, normalize_invoice_number

_NUMBER_TOKEN = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?(?:\s*(?:lakhs?|lac|crores?|cr)\b)?", re.IGNORECASE)
_DATE_TOKEN = re.compile(
    r"\b\d{4}-\d{1,2}-\d{1,2}\b|\b\d{1,2}[/\-.]\d{1,2}[/\-.]\d{4}\b"
    r"|\b\d{1,2}(?:st|nd|rd|th)?[\s\-]+[A-Za-z]{3,9}\.?,?[\s\-]+\d{4}\b"
    r"|\b[A-Za-z]{3,9}\.?[\s\-]+\d{1,2}(?:st|nd|rd|th)?,?[\s\-]+\d{4}\b"
)


def _amounts_in(text: str) -> set[Decimal]:
    found = set()
    for token in _NUMBER_TOKEN.findall(text):
        try:
            value = parse_amount(token)
        except ValueError:
            continue
        if value is not None:
            found.add(abs(value))
    return found


def _dates_in(text: str, month_first: bool) -> set[date]:
    found = set()
    for token in _DATE_TOKEN.findall(text):
        try:
            found.add(parse_date(token, month_first=month_first))
        except ValueError:
            continue
    return found


def ungrounded_fields(raw_text: str, inv: Invoice, month_first: bool = False) -> list[str]:
    """Names of extracted fields whose value can't be found in the document text."""
    problems = []
    compact_upper = re.sub(r"\s+", "", raw_text).upper()
    if inv.supplier_gstin and re.sub(r"\s+", "", inv.supplier_gstin).upper() not in compact_upper:
        problems.append("supplier_gstin")
    if inv.invoice_number and normalize_invoice_number(inv.invoice_number) not in normalize_invoice_number(raw_text):
        problems.append("invoice_number")
    if inv.ifsc and inv.ifsc.strip().upper() not in compact_upper:
        problems.append("ifsc")
    if inv.bank_account and digits_only(inv.bank_account) not in re.sub(r"[\s\-]", "", raw_text):
        problems.append("bank_account")
    if inv.total is not None and abs(inv.total) not in _amounts_in(raw_text):
        problems.append("total")
    if inv.invoice_date is not None and inv.invoice_date not in _dates_in(raw_text, month_first):
        problems.append("invoice_date")
    return problems
