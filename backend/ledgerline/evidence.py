"""Where each extracted value came from: character offsets into the original document (Part 4A).

Offsets are computed here, in code, from the parsed values. They are never taken from the model. A model that
returned offsets could point a reviewer at any text it liked, and a hostile document could steer it.

For each field we collect every place in the document where its value is printed (amounts and dates are
compared by value, so "35,624/-", "35624" and "₹35,624.00" all count), then decide which one is the source:

  exact      exactly one place is labelled as this field ("CGST" before the CGST amount), or the value is
             printed once, or it is an identifier printed identically in several places (a GSTIN in the
             header and the footer: either one is a true source).
  ambiguous  several places could be the source and nothing tells them apart, for example two different lines
             both labelled "Total". We list the candidates and highlight nothing: a confident highlight on the
             wrong text is worse than none, because reviewers stop checking.
  not_found  the value isn't printed (the grounding check sends such documents to review).

`text` is always exactly `raw_text[start:end]`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .grounding import _DATE_TOKEN, _NUMBER_TOKEN
from .models import Invoice
from .parsing import parse_amount, parse_date

# A label printed shortly before a value on the same line tells us which field the value is. When several labels
# precede a value, the nearest wins, and a longer label beats a shorter one ending at the same place, so
# "Sub Total" is a subtotal, not a total. "_other" labels exist only to claim values that are none of ours.
_LABELS: dict[str, re.Pattern] = {k: re.compile(v, re.IGNORECASE) for k, v in {
    "subtotal": r"sub\s*-?\s*total|taxable\s+(value|amount)|assessable\s+value|\bassval\b",
    "cgst": r"\bcgst(?!amt)\w*",
    "sgst": r"\b(sgst|utgst)(?!amt)\w*",
    "igst": r"\bigst(?!amt)\w*",
    "round_off": r"\bround(ing|\s*-?\s*off)?\b|\brndoffamt\b",
    "total": r"\b(grand\s+)?total\b|\btotinvval\b|\bamount\s+(due|payable)\b|\binvoice\s+value\b",
    "invoice_date": r"\binv(oice)?\.?\s*(dt|date)\b|\bdated\b|\bdate\b|\bdt\b",
    "invoice_number": r"\binv(oice)?\.?\s*(no|number|#)\.?|\binv#|\bbill\s+no\.?|\bcredit\s+note\s+no\.?|\"no\"",
    "po_number": r"\bp\.?\s*o\.?(\s*(no|number)\.?)?|\border\s+no\.?|\bpurchase\s+order\b",
    "supplier_gstin": r"\bgstin\w*|\bgst\s*no\.?",
    "ifsc": r"\bifs\w*",
    "bank_account": r"\ba/?c\.?(\s*(no|number)\.?)?|\baccount(\s*(no|number)\.?)?|\bacct\b",
    # Values that are none of the fields above: due dates, payment dates, and the per-line figures of an
    # e-invoice, which repeat the document totals for a single-line invoice.
    "_other": r"\bdue\s+date\b|\bpaid\s+on\b|\bpo\s+date\b|\back\s*dt\b|\b(cgst|sgst|igst|tot|ass)amt\b"
              r"|\btotitemval\b|\bunitprice\b",
}.items()}

LABEL_WINDOW = 120  # characters before the value, on the same line (OCR layouts space columns widely)
ADJACENT = 200  # characters: an e-invoice prints a line's value and its total a few keys apart
IDENTIFIER_FIELDS = {"supplier_name", "supplier_gstin", "invoice_number", "po_number", "ifsc", "bank_account"}
MONEY_FIELDS = ["subtotal", "cgst", "sgst", "igst", "round_off", "total"]


@dataclass
class Span:
    start: int
    end: int
    text: str
    line: int

    def as_dict(self) -> dict:
        return {"start": self.start, "end": self.end, "text": self.text, "line": self.line}


def _span(raw: str, start: int, end: int) -> Span:
    return Span(start, end, raw[start:end], raw.count("\n", 0, start) + 1)


def _nearest_label(raw: str, start: int) -> str | None:
    line_start = raw.rfind("\n", 0, start) + 1
    prefix = raw[max(line_start, start - LABEL_WINDOW):start]
    best: tuple[int, int, str] | None = None  # (end, length, field)
    for field, pattern in _LABELS.items():
        for m in pattern.finditer(prefix):
            candidate = (m.end(), m.end() - m.start(), field)
            if best is None or candidate[:2] > best[:2]:
                best = candidate
    return best[2] if best else None


# --- where a value is printed -------------------------------------------------------------------------------


def _amount_spans(raw: str, value: Decimal) -> list[Span]:
    spans = []
    for m in _NUMBER_TOKEN.finditer(raw):
        try:
            parsed = parse_amount(m.group(0))
        except ValueError:
            continue
        if parsed is not None and abs(parsed) == abs(value):
            spans.append(_span(raw, m.start(), m.end()))
    return spans


def _date_spans(raw: str, value: date, month_first: bool) -> list[Span]:
    spans = []
    for m in _DATE_TOKEN.finditer(raw):
        try:
            if parse_date(m.group(0), month_first=month_first) == value:
                spans.append(_span(raw, m.start(), m.end()))
        except ValueError:
            continue
    return spans


def _string_spans(raw: str, field: str, value: str) -> list[Span]:
    value = value.strip()
    if not value:
        return []
    if field == "bank_account":
        digits = re.sub(r"\D", "", value)
        pattern = r"(?<!\d)" + r"[\s\-]?".join(digits) + r"(?!\d)" if digits else None
    elif field == "supplier_name":
        pattern = r"\s+".join(re.escape(w) for w in value.split())
    else:
        pattern = r"(?<![A-Za-z0-9])" + re.escape(value) + r"(?![A-Za-z0-9])"
    spans = [_span(raw, m.start(), m.end()) for m in re.finditer(pattern, raw, re.IGNORECASE)] if pattern else []
    if not spans and field == "invoice_number":
        # The model may have dropped the printed spacing ("SIS/26-27/0018" for "SIS / 26-27 / 0018").
        chars = re.sub(r"[\s/\-#.]", "", value)
        if chars:
            loose = r"(?<![A-Za-z0-9])" + r"[\s/\-#.]*".join(re.escape(c) for c in chars) + r"(?![A-Za-z0-9])"
            spans = [_span(raw, m.start(), m.end()) for m in re.finditer(loose, raw, re.IGNORECASE)]
    return spans


# --- choosing the source ------------------------------------------------------------------------------------


def _identical(spans: list[Span]) -> bool:
    return len({re.sub(r"\s+", " ", s.text).upper() for s in spans}) == 1


def _choose(raw: str, field: str, spans: list[Span], label_field: str | None = None) -> dict:
    label_field = label_field or field
    if not spans:
        return {"status": "not_found"}
    labelled = [s for s in spans if _nearest_label(raw, s.start) == label_field]
    if len(labelled) == 1:
        return {"status": "exact", **labelled[0].as_dict(), "basis": "labelled"}
    pool = labelled or spans
    if len(pool) == 1:
        other = _nearest_label(raw, pool[0].start)
        if other and other != label_field:
            # Printed once, but labelled as something else: say so instead of pretending.
            return {"status": "ambiguous", "candidates": [pool[0].as_dict()],
                    "basis": f"the only match is labelled as {other.replace('_', ' ')}"}
        return {"status": "exact", **pool[0].as_dict(), "basis": "printed once"}
    if _identical(pool) and (field in IDENTIFIER_FIELDS or pool[-1].start - pool[0].start < ADJACENT):
        # The same value printed in several places that are all labelled as this field (or an identifier, which
        # means the same thing wherever it is printed): any of them is a true source.
        return {"status": "exact", **pool[0].as_dict(), "basis": f"printed {len(pool)} times, identically",
                "also_at": [s.as_dict() for s in pool[1:]]}
    return {"status": "ambiguous", "candidates": [s.as_dict() for s in pool[:5]],
            "basis": f"{len(pool)} places could be the source" + (" (each labelled as this field)" if labelled else "")}


def locate(raw: str, inv: Invoice, month_first: bool = False) -> dict[str, dict]:
    """Evidence for every extracted field that has a value. Zero taxes that aren't printed are left out."""
    out: dict[str, dict] = {}
    for field in ("supplier_name", "supplier_gstin", "invoice_number", "po_number", "ifsc", "bank_account"):
        value = getattr(inv, field)
        if value:
            out[field] = _choose(raw, field, _string_spans(raw, field, value))
    if inv.invoice_date:
        spans = _date_spans(raw, inv.invoice_date, month_first)
        headers_end = _email_headers_end(raw)
        in_body = [s for s in spans if s.start >= headers_end]
        if spans and not in_body:
            # Policy 1: the document date is never the date an email was sent.
            out["invoice_date"] = {"status": "ambiguous", "candidates": [s.as_dict() for s in spans],
                                   "basis": "only found in the email's headers, which policy says is not the invoice date"}
        else:
            out["invoice_date"] = _choose(raw, "invoice_date", in_body)
    for field in MONEY_FIELDS:
        value = getattr(inv, field)
        if value is None:
            continue
        found = _choose(raw, field, _amount_spans(raw, value))
        if value == 0 and found["status"] != "exact":
            continue  # "0.00" for a tax that isn't charged: usually not printed at all, and that's fine
        out[field] = found
    for i, item in enumerate(inv.line_items):
        if item.amount is None:
            continue
        spans = _amount_spans(raw, item.amount)
        key = re.sub(r"[^a-z0-9]", "", item.description.lower())[:12]
        on_its_line = [s for s in spans if key and key in re.sub(r"[^a-z0-9]", "", _line_of(raw, s.start).lower())]
        if on_its_line and len({s.line for s in on_its_line}) == 1:
            # A tabular line prints quantity, rate and amount left to right: the amount is the rightmost match.
            out[f"line_items[{i}].amount"] = {"status": "exact", **on_its_line[-1].as_dict(),
                                              "basis": "rightmost match on the line with its description"}
        else:
            out[f"line_items[{i}].amount"] = _choose(raw, "line_amount", on_its_line or spans, label_field="_none")
    return out


_HEADER_START = re.compile(r"(?i)^(from|to|subject|date|received|return-path|message-id)\s*:")


def _email_headers_end(raw: str) -> int:
    """Offset where an email's body starts (0 if the document isn't an email)."""
    if not _HEADER_START.match(raw.lstrip()):
        return 0
    blank = re.search(r"\r?\n\r?\n", raw)
    return blank.end() if blank else 0


def _line_of(raw: str, index: int) -> str:
    start = raw.rfind("\n", 0, index) + 1
    end = raw.find("\n", index)
    return raw[start: end if end != -1 else len(raw)]


def contract_evidence(evidence: dict[str, dict]) -> dict[str, dict]:
    """OUTPUT_CONTRACT.md `evidence`: only the fields we are sure of, as {start, end, text}."""
    return {field: {"start": e["start"], "end": e["end"], "text": e["text"]}
            for field, e in evidence.items() if e.get("status") == "exact" and "[" not in field}


def find_text(raw: str, pattern: str, flags: int = re.IGNORECASE) -> Span | None:
    m = re.search(pattern, raw, flags)
    return _span(raw, m.start(), m.end()) if m else None
