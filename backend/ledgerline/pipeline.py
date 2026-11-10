"""Process one document end to end: extract -> normalise -> ground -> check -> route -> persist.

Routing is decided here, in code, from the deterministic checks in validation.py. The model's reply is used
for field values only. Every document is persisted, including ones we couldn't process; those go to review
with `processing_error` (AP_POLICY.md section 3).
"""
from __future__ import annotations

import json
import logging
import sqlite3
from decimal import Decimal

from . import db
from .extraction import ExtractionError, extract
from .grounding import ungrounded_fields
from .llm.pricing import cost_usd
from .models import Invoice, LineItem
from .parsing import parse_amount, parse_date, parse_lenient_number
from .reference import ReferenceData
from .validation import check_suspicious_content, find_vendor, received_date, run_checks, vendor_is_us

log = logging.getLogger(__name__)

HIGH_VALUE_THRESHOLD = Decimal("500000.00")  # policy 4.1: a total of ₹5,00,000.00 *or more* needs two approvals
ZERO = Decimal("0.00")
DOCUMENT_TYPES = {"invoice": "invoice", "tax invoice": "invoice", "credit_note": "credit_note",
                  "credit note": "credit_note", "creditnote": "credit_note", "crn": "credit_note"}


def _text(value) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _e_invoice_type(raw_text: str) -> str | None:
    """Government e-invoice JSON states its type in DocDtls.Typ. Trust that over the model."""
    try:
        doc = json.loads(raw_text)
    except ValueError:
        return None
    typ = str(((doc.get("DocDtls") or {}) if isinstance(doc, dict) else {}).get("Typ", "")).upper()
    return {"INV": "invoice", "CRN": "credit_note"}.get(typ)


def normalize(data: dict, ref: ReferenceData | None = None, raw_text: str = "") -> Invoice:
    """Model output -> Invoice. Raises ValueError for anything that can't be read with certainty."""
    raw_type = str(data.get("document_type") or "invoice").strip().lower().replace("-", " ")
    document_type = _e_invoice_type(raw_text) or DOCUMENT_TYPES.get(raw_type)
    if document_type is None:
        raise ValueError(f"unknown document_type {data.get('document_type')!r}")
    currency = str(data.get("currency") or "INR").strip().upper()
    if currency in {"₹", "RS", "RS.", "RUPEES"}:
        currency = "INR"
    if len(currency) != 3 or not currency.isalpha():
        raise ValueError(f"unknown currency {data.get('currency')!r}")
    items = []
    for item in data.get("line_items") or []:
        if not isinstance(item, dict):
            raise ValueError("malformed line item")
        items.append(LineItem(
            description=str(item.get("description") or ""),
            quantity=parse_lenient_number(item.get("quantity")),
            unit_price=parse_lenient_number(item.get("unit_price")),
            amount=parse_amount(item.get("amount")),
        ))
    inv = Invoice(
        document_type=document_type,
        supplier_name=_text(data.get("supplier_name")),
        supplier_gstin=(_text(data.get("supplier_gstin")) or "").upper() or None,
        invoice_number=_text(data.get("invoice_number")),
        invoice_date=None,
        currency=currency,
        subtotal=parse_amount(data.get("subtotal")),
        cgst=parse_amount(data.get("cgst")) or ZERO,
        sgst=parse_amount(data.get("sgst")) or ZERO,
        igst=parse_amount(data.get("igst")) or ZERO,
        round_off=parse_amount(data.get("round_off")) or ZERO,
        total=parse_amount(data.get("total")),
        bank_account=_text(data.get("bank_account")),
        ifsc=_text(data.get("ifsc")),
        po_number=_text(data.get("po_number")),
        notes=_text(data.get("notes")),
        line_items=items,
    )
    # Date order depends on the vendor (policy section 1): US vendors print month first.
    month_first = bool(ref) and vendor_is_us(find_vendor(ref, inv))
    inv.invoice_date = parse_date(data.get("invoice_date"), month_first=month_first)
    return inv


def required_approvals(inv: Invoice | None) -> int:
    """Policy 4.1. Credit notes 0; foreign currency 2; ₹5,00,000.00 or more 2; everything else 1."""
    if inv is None:
        return 2  # we don't know what it is: be conservative
    if inv.document_type == "credit_note":
        return 0
    if not inv.is_domestic:
        return 2
    if inv.total is None:
        return 2
    return 2 if inv.total >= HIGH_VALUE_THRESHOLD else 1


def _missing_fields(inv: Invoice) -> list[str]:
    required = {"supplier_name": inv.supplier_name, "invoice_number": inv.invoice_number,
                "invoice_date": inv.invoice_date, "total": inv.total}
    missing = [name for name, value in required.items() if value is None]
    if not inv.line_items and inv.subtotal is None:
        missing.append("line_items")
    elif inv.line_items and any(item.amount is None for item in inv.line_items) and inv.subtotal is None:
        missing.append("line_items.amount")
    return missing


def _money(value: Decimal | None) -> float | None:
    # Storage is still REAL (see FINDINGS.md). All decisions above are made on the exact Decimal values.
    return None if value is None else float(value)


def _line_item_json(item: LineItem) -> dict:
    return {"description": item.description,
            # '12.00' -> '12', '1.50' -> '1.5', never '7.5E+2'
            "quantity": None if item.quantity is None else format(item.quantity.normalize(), "f"),
            "unit_price": None if item.unit_price is None else f"{item.unit_price:.2f}",
            "amount": None if item.amount is None else f"{item.amount:.2f}"}


def process_document(
    conn: sqlite3.Connection,
    ref: ReferenceData,
    raw_text: str,
    document_id: str,
    org_id: str = "meridian",
    filename: str | None = None,
) -> dict:
    reasons: list[str] = []
    warnings: list[str] = []
    responses = []
    data: dict | None = None
    inv: Invoice | None = None

    def processing_error(message: str) -> None:
        reasons.append("processing_error")
        warnings.append(message)

    if "�" in raw_text:
        processing_error("The document is not valid UTF-8; some characters could not be read.")

    try:
        data, responses = extract(raw_text, ref)
    except ExtractionError as exc:
        responses = exc.responses
        processing_error(f"Extraction failed: {exc}")

    if data is not None:
        try:
            inv = normalize(data, ref, raw_text)
        except (ValueError, TypeError, ArithmeticError) as exc:
            processing_error(f"Could not read the extracted values: {exc}")

    # Checked on the raw document, independently of whether the model noticed anything.
    reasons += check_suspicious_content(raw_text)

    conn.execute("BEGIN IMMEDIATE")  # the duplicate check and the insert must not interleave with another upload
    try:
        if inv is not None:
            missing = _missing_fields(inv)
            if missing:
                processing_error("Not found in the document: " + ", ".join(missing))
            month_first = vendor_is_us(find_vendor(ref, inv))
            ungrounded = ungrounded_fields(raw_text, inv, month_first=month_first)
            if ungrounded:
                processing_error("Extracted values not found verbatim in the document: " + ", ".join(ungrounded))
            reasons += run_checks(conn, ref, inv, org_id, received_on=received_date(raw_text))

        reasons = list(dict.fromkeys(reasons))
        needs_review = bool(reasons)
        status = "needs_review" if needs_review else "ready_for_approval"
        cur = conn.execute(
            """INSERT INTO invoices (org_id, document_id, filename, raw_text, document_type, supplier_name,
                   supplier_gstin, invoice_number, invoice_date, currency, subtotal, cgst, sgst, igst, round_off,
                   total, bank_account, ifsc, po_number, notes, line_items_json, warnings_json, needs_review,
                   review_reasons_json, required_approvals, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                org_id, document_id, filename, raw_text,
                inv.document_type if inv else None,
                inv.supplier_name if inv else None,
                inv.supplier_gstin if inv else None,
                inv.invoice_number if inv else None,
                inv.invoice_date.isoformat() if inv and inv.invoice_date else None,
                inv.currency if inv else None,
                *(_money(getattr(inv, f)) if inv else None
                  for f in ("subtotal", "cgst", "sgst", "igst", "round_off", "total")),
                inv.bank_account if inv else None,
                inv.ifsc if inv else None,
                inv.po_number if inv else None,
                inv.notes if inv else None,
                json.dumps([_line_item_json(i) for i in inv.line_items] if inv else []),
                json.dumps(warnings), int(needs_review), json.dumps(reasons), required_approvals(inv), status,
            ),
        )
        invoice_id = cur.lastrowid
        for r in responses:
            conn.execute(
                "INSERT INTO llm_calls (invoice_id, document_id, model, input_tokens, output_tokens, cost_usd, "
                "latency_ms) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (invoice_id, document_id, r.model, r.input_tokens, r.output_tokens,
                 cost_usd(r.model, r.input_tokens, r.output_tokens), r.latency_ms),
            )
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    if warnings:
        log.warning("%s: %s", document_id, "; ".join(warnings))
    return db.get_invoice(conn, invoice_id)
