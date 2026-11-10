"""Each review reason in plain language, with the evidence behind it (Part 4A).

The reasons themselves come from validation.run_checks; this module never adds or removes one. It explains them,
using the same facts the rule used: the vendor-master row, the paid invoice, the arithmetic, the exact text.
Bank account numbers from the vendor master are shown as their last four digits only, as everywhere else.
"""
from __future__ import annotations

import sqlite3
from datetime import date
from decimal import Decimal

from . import flags
from .evidence import Span, find_text
from .models import Invoice
from .reference import ReferenceData
from .validation import (
    GSTIN_PATTERN,
    NEW_VENDOR_DAYS,
    TOTALS_TOLERANCE,
    ZERO,
    digits_only,
    find_duplicate,
    find_vendor,
    gstin_checksum,
    is_valid_gstin,
    normalize_name,
    suspicious_matches,
)

TITLES = {
    "credit_note": "Credit note: can't be approved for payment",
    "duplicate": "Already billed",
    "gstin_invalid": "Supplier GSTIN isn't valid",
    "vendor_unknown": "Supplier isn't in the vendor master",
    "vendor_new": "New vendor",
    "bank_details_changed": "Bank details differ from our records",
    "tax_type_mismatch": "Wrong type of GST for the supplier's state",
    "totals_mismatch": "The total doesn't add up",
    "foreign_currency": "Foreign currency",
    "suspicious_content": "Text aimed at automated systems, or markup",
    "processing_error": "Ledgerline couldn't read this document reliably",
    "line_arithmetic_mismatch": "A line's quantity × rate doesn't match its amount",
    "date_after_receipt": "Dated after we received it",
}

# Review order in the queue: what can lose money to fraud first, then what can pay wrongly, then the rest.
SEVERITY = ["bank_details_changed", "suspicious_content", "duplicate", "vendor_unknown", "gstin_invalid",
            "processing_error", "totals_mismatch", "line_arithmetic_mismatch", "date_after_receipt", "vendor_new",
            "tax_type_mismatch", "foreign_currency", "credit_note"]


def inr(value: Decimal | float | None, currency: str = "INR") -> str:
    """Indian digit grouping: 141600 -> '₹1,41,600.00'."""
    if value is None:
        return "–"
    d = Decimal(str(value)).quantize(Decimal("0.01"))
    sign, d = ("-" if d < 0 else ""), abs(d)
    whole, frac = f"{d:.2f}".split(".")
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    grouped = ",".join(groups + [tail]) if groups else tail
    symbol = "₹" if currency == "INR" else ("$" if currency == "USD" else f"{currency} ")
    return f"{sign}{symbol}{grouped}.{frac}"


def _last4(account: str | None) -> str:
    digits = digits_only(account)
    return f"ending {digits[-4:]}" if digits else "none on file"


def _ev(evidence: dict[str, dict], *fields: str) -> list[dict]:
    out = []
    for f in fields:
        e = evidence.get(f)
        if e and e.get("status") == "exact":
            out.append({"field": f, "start": e["start"], "end": e["end"], "text": e["text"], "line": e["line"]})
    return out


def _span_ev(span: Span | None, label: str) -> list[dict]:
    return [{"field": label, **span.as_dict()}] if span else []


def _gstin_problem(gstin: str | None) -> str:
    if not gstin:
        return "No supplier GSTIN is printed, and every domestic document must show one."
    g = gstin.strip().upper()
    if not GSTIN_PATTERN.match(g):
        return (f"{g} doesn't have the GSTIN format (2-digit state, 10-character PAN, entity number, 'Z', check "
                "character).")
    return f"{g} fails the GSTIN checksum: its last character should be {gstin_checksum(g[:14])}, not {g[14]}."


def _near_miss_vendor(ref: ReferenceData, gstin: str | None) -> dict | None:
    """A vendor whose GSTIN differs from the printed one in exactly one character: a likely OCR slip, *or* a
    look-alike. A hint for the reviewer only; it never changes routing (the CFO's "just fix it" is declined)."""
    g = (gstin or "").strip().upper()
    if len(g) != 15:
        return None
    for v in ref.vendors:
        vg = (v.get("gstin") or "").strip().upper()
        if len(vg) == 15 and vg != g and sum(a != b for a, b in zip(vg, g)) == 1:
            return v
    return None


def explain(reasons: list[str], inv: Invoice | None, raw_text: str, ref: ReferenceData, conn: sqlite3.Connection,
            org_id: str, evidence: dict[str, dict], warnings: list[str], received_on: date | None) -> list[dict]:
    vendor = find_vendor(ref, inv) if inv else None
    vendor_name = (vendor or {}).get("legal_name") or (inv.supplier_name if inv else None) or "the supplier"
    out = []
    for code in sorted(reasons, key=lambda c: SEVERITY.index(c) if c in SEVERITY else len(SEVERITY)):
        detail, ev, action = "", [], ""
        if code == "processing_error" or (inv is None and code != "suspicious_content"):
            detail = " ".join(warnings) or "The document could not be processed."
            action = "Check every value against the original document before approving."
        elif code == "credit_note":
            detail = (f"This is a credit note from {vendor_name} for {inr(inv.total, inv.currency)}. It reduces "
                      "what Meridian owes, so it is never approved for payment (policy 2 and 4.1).")
            action = "Record it against the vendor's account; reject it here."
        elif code == "duplicate":
            dup = find_duplicate(conn, ref, inv, org_id)
            if dup and dup["source"] == "paid":
                detail = (f"{dup.get('supplier_name')} invoice {dup.get('invoice_number')} dated "
                          f"{dup.get('invoice_date')} for {inr(Decimal(dup.get('total') or '0'))} was already paid "
                          f"on {dup.get('paid_on')}. This document has the same supplier, the same invoice number "
                          f"once spaces and punctuation are removed, and the same financial year.")
            elif dup:
                detail = (f"The same invoice was already received as {dup.get('document_id')} "
                          f"({inr(dup.get('total'), dup.get('currency') or 'INR')}, status: "
                          f"{str(dup.get('status')).replace('_', ' ')}).")
            else:
                detail = "Same supplier, invoice number and financial year as an invoice already recorded."
            action = "Duplicates can't be approved (policy 4.4). Reject it; if the amount changed, ask for a debit note."
            ev = _ev(evidence, "invoice_number", "invoice_date", "supplier_gstin")
        elif code == "gstin_invalid":
            detail = _gstin_problem(inv.supplier_gstin)
            near = _near_miss_vendor(ref, inv.supplier_gstin)
            if near and inv.supplier_gstin:
                bank_matches = digits_only(inv.bank_account) and digits_only(inv.bank_account) == digits_only(
                    near.get("bank_account"))
                detail += (f" It is one character away from {near['vendor_id']} {near['legal_name']} "
                           f"({near['gstin']})" + (", and the bank account matches theirs" if bank_matches else "")
                           + ": possibly an OCR error, possibly a look-alike.")
            action = "Compare the GSTIN with the original PDF. Ledgerline never corrects a GSTIN itself."
            ev = _ev(evidence, "supplier_gstin")
        elif code == "vendor_unknown":
            if inv.is_domestic:
                detail = f"No vendor in the vendor master has GSTIN {inv.supplier_gstin or '(none printed)'}."
                same_name = next((v for v in ref.vendors if normalize_name(v.get("legal_name")) ==
                                  normalize_name(inv.supplier_name) and normalize_name(inv.supplier_name)), None)
                if same_name and is_valid_gstin(inv.supplier_gstin):
                    detail += (f" The printed name matches {same_name['vendor_id']} {same_name['legal_name']}, "
                               f"whose GSTIN on file is {same_name['gstin']}. A known name with someone else's "
                               "GSTIN is how impersonation looks; the name alone is not proof of identity (policy 1).")
                else:
                    detail += " The printed name is not proof of identity (policy 1)."
            else:
                detail = f"No vendor in the vendor master is named {inv.supplier_name!r}."
            action = "Don't pay an unknown vendor. Onboard them first, or reject."
            ev = _ev(evidence, "supplier_gstin", "supplier_name")
        elif code == "vendor_new":
            onboarded = date.fromisoformat(vendor["onboarded_on"].strip()) if vendor else None
            as_of = inv.invoice_date
            if flags.enabled(flags.DATE_AFTER_RECEIPT) and received_on and as_of:
                as_of = min(as_of, received_on)
            days = (as_of - onboarded).days if onboarded and as_of else None
            detail = (f"{vendor_name} was onboarded on {onboarded}, {days} days before {as_of}. Vendors are new for "
                      f"their first {NEW_VENDOR_DAYS} days.")
            action = "Confirm the purchase order and the delivery before approving."
            ev = _ev(evidence, "invoice_date")
        elif code == "bank_details_changed":
            detail = (f"The document asks for payment to account {_last4(inv.bank_account)}, IFSC {inv.ifsc or '–'}. "
                      f"Our records for {vendor_name} have account {_last4((vendor or {}).get('bank_account'))}, "
                      f"IFSC {(vendor or {}).get('ifsc') or '–'}.")
            action = ("Don't pay to the new account until the vendor has been phoned back on a number from our own "
                      "records, not one from this document.")
            ev = _ev(evidence, "bank_account", "ifsc")
        elif code == "tax_type_mismatch":
            state = (inv.supplier_gstin or "")[:2]
            buyer = str(ref.buyer.get("state_code") or "27").zfill(2)
            if state == buyer:
                detail = (f"The supplier is in the same state as Meridian (code {state}), so CGST and SGST are "
                          f"expected, but IGST of {inr(inv.igst)} is charged.")
                ev = _ev(evidence, "supplier_gstin", "igst")
            else:
                detail = (f"The supplier is in another state (code {state}; ours is {buyer}), so IGST is expected, "
                          f"but CGST {inr(inv.cgst)} and SGST {inr(inv.sgst)} are charged.")
                ev = _ev(evidence, "supplier_gstin", "cgst", "sgst")
            action = "Wrong GST type means Meridian can't claim the input credit. Ask for a corrected invoice."
        elif code == "totals_mismatch":
            lines = (sum((i.amount for i in inv.line_items), ZERO)
                     if inv.line_items and all(i.amount is not None for i in inv.line_items) else inv.subtotal)
            computed = (lines or ZERO) + inv.cgst + inv.sgst + inv.igst + inv.round_off
            detail = (f"Line amounts {inr(lines)} + CGST {inr(inv.cgst)} + SGST {inr(inv.sgst)} + IGST "
                      f"{inr(inv.igst)} + round-off {inr(inv.round_off)} = {inr(computed)}, but the stated total is "
                      f"{inr(inv.total)}: a difference of {inr(abs(computed - (inv.total or ZERO)))} "
                      f"(tolerance {inr(TOTALS_TOLERANCE)}).")
            action = "Ask the vendor which figure is right before paying either."
            ev = _ev(evidence, "total", "subtotal", "cgst", "sgst", "igst", "round_off")
        elif code == "foreign_currency":
            detail = (f"Billed in {inv.currency} ({inr(inv.total, inv.currency)}). Ledgerline doesn't convert "
                      "currency, and foreign-currency invoices need two approvals (policy 4.1).")
            action = "Check the amount and the payment method; some foreign vendors charge a card automatically."
            ev = _ev(evidence, "total")
        elif code == "suspicious_content":
            matches = suspicious_matches(raw_text)
            kinds = {k for _, _, k in matches}
            parts = []
            if "markup" in kinds:
                parts.append("HTML or script markup, which has no business in an invoice")
            if "instruction" in kinds:
                parts.append("instructions aimed at how the document is processed")
            if "addressed_to_automation" in kinds:
                parts.append("text addressed to automated systems or AI")
            detail = "The document contains " + " and ".join(parts) + ". Nothing it says changes Ledgerline's checks."
            action = "Read the highlighted text. Treat the whole document as untrusted, especially its bank details."
            ev = [{"field": f"suspicious ({k.replace('_', ' ')})", "start": a, "end": b, "text": raw_text[a:b],
                   "line": raw_text.count("\n", 0, a) + 1} for a, b, k in matches[:5]]
        elif code == "line_arithmetic_mismatch":
            bad = [(n, i) for n, i in enumerate(inv.line_items, 1)
                   if i.quantity is not None and i.unit_price is not None and i.amount is not None
                   and abs(i.quantity * i.unit_price - i.amount) > TOTALS_TOLERANCE]
            detail = " ".join(
                f"Line {n} ({i.description}): {format(i.quantity.normalize(), 'f')} × {inr(i.unit_price)} = "
                f"{inr(i.quantity * i.unit_price)}, but {inr(i.amount)} is charged." for n, i in bad)
            action = "Pay the arithmetic, not the printed amount: ask the vendor to correct the line."
            ev = _ev(evidence, *[f"line_items[{n - 1}].amount" for n, _ in bad])
        elif code == "date_after_receipt":
            detail = f"The invoice is dated {inv.invoice_date}, but we received it on {received_on}."
            action = "Ask the vendor for the correct date; the date drives the FY and the new-vendor check."
            ev = _ev(evidence, "invoice_date") + _span_ev(find_text(raw_text, r"(?m)^Date:.*$"), "email date")
        out.append({"code": code, "title": TITLES.get(code, code.replace("_", " ")), "detail": detail.strip(),
                    "action": action, "evidence": ev})
    return out
