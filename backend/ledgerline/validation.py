"""Deterministic AP policy checks (AP_POLICY.md section 3). These decide routing.

v0.3 let the model decide `requires_review` and kept these as UI warnings only. A document could then talk
the model out of a review (dev_012). Routing now comes from code. The model only extracts fields, and
nothing it says can remove a review reason.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import date
from decimal import Decimal
from email.parser import HeaderParser
from email.utils import parsedate_to_datetime

from . import flags
from .models import Invoice
from .reference import ReferenceData

GSTIN_PATTERN = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
GSTIN_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
TOTALS_TOLERANCE = Decimal("1.00")
NEW_VENDOR_DAYS = 90
ZERO = Decimal("0.00")

REASON_CODES = (
    "credit_note", "duplicate", "gstin_invalid", "vendor_unknown", "vendor_new", "bank_details_changed",
    "tax_type_mismatch", "totals_mismatch", "foreign_currency", "suspicious_content", "processing_error",
)
# Only ever emitted when their flag is on (see flags.py and submission/RULINGS.md).
FLAGGED_REASON_CODES = ("line_arithmetic_mismatch", "date_after_receipt")


# --- normalisation (AP_POLICY.md section 1) ---------------------------------------------------------------

def normalize_invoice_number(number: str | None) -> str:
    """'SIS / 26-27 / 0018' -> 'SIS26270018'. Leading zeros are significant."""
    return re.sub(r"[\s/\-#.]", "", number or "").upper()


def normalize_name(name: str | None) -> str:
    """Case-insensitive, ignoring spaces and punctuation."""
    return re.sub(r"[^0-9a-z]", "", (name or "").lower())


def financial_year(d: date) -> int:
    """The year the FY starts in: 2026-04-03 -> 2026 (FY 2026-27), 2026-03-31 -> 2025 (FY 2025-26)."""
    return d.year if d.month >= 4 else d.year - 1


def supplier_key(currency: str | None, gstin: str | None, name: str | None) -> str | None:
    """GSTIN for domestic documents and legal name for foreign ones."""
    if (currency or "INR").upper() == "INR":
        gstin = (gstin or "").strip().upper()
        return f"GSTIN:{gstin}" if gstin else None
    name = normalize_name(name)
    return f"NAME:{name}" if name else None


def digits_only(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


# --- GSTIN (Appendix A) ------------------------------------------------------------------------------------

def gstin_checksum(first14: str) -> str:
    total = 0
    for i, ch in enumerate(first14):
        product = GSTIN_ALPHABET.index(ch) * (1 if i % 2 == 0 else 2)
        total += product // 36 + product % 36
    return GSTIN_ALPHABET[(36 - total % 36) % 36]


def is_valid_gstin(gstin: str | None) -> bool:
    """Validate a GSTIN's format *and* its check character."""
    if not gstin:
        return False
    gstin = gstin.strip().upper()
    if not GSTIN_PATTERN.match(gstin):
        return False
    return gstin_checksum(gstin[:14]) == gstin[14]


# --- vendor master -----------------------------------------------------------------------------------------

def find_vendor(ref: ReferenceData, inv: Invoice) -> dict | None:
    """A domestic supplier is identified by GSTIN alone. The printed name is not proof of identity.
    A foreign supplier is identified by its legal name, normalised."""
    if inv.is_domestic:
        gstin = (inv.supplier_gstin or "").strip().upper()
        if not gstin:
            return None
        return next((v for v in ref.vendors if (v.get("gstin") or "").strip().upper() == gstin), None)
    name = normalize_name(inv.supplier_name)
    if not name:
        return None
    return next((v for v in ref.vendors if normalize_name(v.get("legal_name")) == name), None)


def vendor_is_us(vendor: dict | None) -> bool:
    return bool(vendor) and (vendor.get("country") or "").strip().upper() == "US"


# --- the checks --------------------------------------------------------------------------------------------

def check_credit_note(inv: Invoice) -> list[str]:
    return ["credit_note"] if inv.document_type == "credit_note" else []


def check_foreign_currency(inv: Invoice) -> list[str]:
    return [] if inv.is_domestic else ["foreign_currency"]


def check_gstin(inv: Invoice) -> list[str]:
    if inv.is_domestic and not is_valid_gstin(inv.supplier_gstin):
        return ["gstin_invalid"]
    return []


def check_vendor(vendor: dict | None) -> list[str]:
    return [] if vendor else ["vendor_unknown"]


def check_vendor_new(inv: Invoice, vendor: dict | None, received_on: date | None = None) -> list[str]:
    if not vendor or not inv.invoice_date or not vendor.get("onboarded_on"):
        return []
    onboarded = date.fromisoformat(vendor["onboarded_on"].strip())
    as_of = inv.invoice_date
    if flags.enabled(flags.DATE_AFTER_RECEIPT) and received_on is not None:
        # disp_06: a new vendor's invoice post-dated by two months would otherwise clear the 90-day window.
        as_of = min(as_of, received_on)
    return ["vendor_new"] if (as_of - onboarded).days < NEW_VENDOR_DAYS else []


def received_date(raw_text: str, processed_on: date | None = None) -> date | None:
    """When we got the document: an email's Date header, otherwise the day we process it."""
    head = raw_text[:4000]
    if re.match(r"(?i)^(from|to|subject|date|received|return-path|message-id)\s*:", head.lstrip()):
        headers = HeaderParser().parsestr(head, headersonly=True)
        if headers.get("Date"):
            try:
                return parsedate_to_datetime(headers["Date"]).date()
            except (TypeError, ValueError):
                pass
    return processed_on or date.today()


def check_date_after_receipt(inv: Invoice, received_on: date | None) -> list[str]:
    """Flagged rule (DATE_AFTER_RECEIPT): an invoice can't be dated after the day it reached us."""
    if not flags.enabled(flags.DATE_AFTER_RECEIPT) or received_on is None or inv.invoice_date is None:
        return []
    return ["date_after_receipt"] if inv.invoice_date > received_on else []


def check_line_arithmetic(inv: Invoice) -> list[str]:
    """Flagged rule (LINE_ARITHMETIC): quantity x unit price must match the printed line amount within ₹1.00.
    The policy's totals check sums the printed line amounts, so a padded line amount (disp_05) passes it."""
    if not flags.enabled(flags.LINE_ARITHMETIC):
        return []
    for item in inv.line_items:
        if item.quantity is None or item.unit_price is None or item.amount is None:
            continue
        if abs(item.quantity * item.unit_price - item.amount) > TOTALS_TOLERANCE:
            return ["line_arithmetic_mismatch"]
    return []


def check_tax_type(inv: Invoice, ref: ReferenceData) -> list[str]:
    if not inv.is_domestic or not inv.supplier_gstin:
        return []
    buyer_state = str(ref.buyer.get("state_code") or ref.buyer.get("gstin", "")[:2]).zfill(2)
    intra_state = inv.supplier_gstin.strip()[:2] == buyer_state
    if intra_state and inv.igst != ZERO:
        return ["tax_type_mismatch"]
    if not intra_state and (inv.cgst != ZERO or inv.sgst != ZERO):
        return ["tax_type_mismatch"]
    return []


def check_totals(inv: Invoice) -> list[str]:
    """|sum(line amounts) + CGST + SGST + IGST + round-off - total| > 1.00. Exactly 1.00 is within tolerance.
    Callers must make sure total and the line amounts were read; see pipeline.py."""
    if inv.total is None:
        return []
    if inv.line_items and all(item.amount is not None for item in inv.line_items):
        lines = sum((item.amount for item in inv.line_items), ZERO)
    elif inv.subtotal is not None:
        lines = inv.subtotal
    else:
        return []
    computed = lines + inv.cgst + inv.sgst + inv.igst + inv.round_off
    return ["totals_mismatch"] if abs(computed - inv.total) > TOTALS_TOLERANCE else []


def duplicate_key(currency, gstin, name, number, invoice_date: date | None) -> tuple | None:
    key = supplier_key(currency, gstin, name)
    number = normalize_invoice_number(number)
    if not key or not number or not invoice_date:
        return None
    return key, number, financial_year(invoice_date)


def find_duplicate(conn: sqlite3.Connection, ref: ReferenceData, inv: Invoice, org_id: str = "meridian") -> dict | None:
    """The earlier invoice this one duplicates: same supplier key, normalised invoice number and FY as a paid
    invoice, or as an invoice processed earlier (earlier in the batch, since batches run in document_id order).
    Credit notes are not checked. Returns {"source": "paid", **row} or {"source": "processed", **row}."""
    if inv.document_type != "invoice":
        return None
    key = duplicate_key(inv.currency, inv.supplier_gstin, inv.supplier_name, inv.invoice_number, inv.invoice_date)
    if key is None:
        return None
    for paid in ref.paid_invoices:
        paid_currency = "INR" if (paid.get("supplier_gstin") or "").strip() else "FOREIGN"
        try:
            paid_date = date.fromisoformat((paid.get("invoice_date") or "").strip())
        except ValueError:
            continue
        if duplicate_key(paid_currency, paid.get("supplier_gstin"), paid.get("supplier_name"),
                         paid.get("invoice_number"), paid_date) == key:
            return {"source": "paid", **paid}
    rows = conn.execute(
        "SELECT id, document_id, currency, supplier_gstin, supplier_name, invoice_number, invoice_date, total, status "
        "FROM invoices WHERE org_id = ? AND document_type = 'invoice' AND invoice_date IS NOT NULL",
        (org_id,),
    ).fetchall()
    for row in rows:
        if duplicate_key(row["currency"], row["supplier_gstin"], row["supplier_name"], row["invoice_number"],
                         date.fromisoformat(row["invoice_date"])) == key:
            return {"source": "processed", **dict(row)}
    return None


def check_duplicate(conn: sqlite3.Connection, ref: ReferenceData, inv: Invoice, org_id: str = "meridian") -> list[str]:
    return ["duplicate"] if find_duplicate(conn, ref, inv, org_id) else []


def check_bank_details(inv: Invoice, vendor: dict | None) -> list[str]:
    """Account numbers compared digits-only, IFSC case-insensitively. Not raised for unknown vendors or when
    the document shows no bank details."""
    if not vendor:
        return []
    doc_account, doc_ifsc = digits_only(inv.bank_account), (inv.ifsc or "").strip().upper()
    if doc_account and doc_account != digits_only(vendor.get("bank_account")):
        return ["bank_details_changed"]
    if doc_ifsc and doc_ifsc != (vendor.get("ifsc") or "").strip().upper():
        return ["bank_details_changed"]
    return []


# --- suspicious content (deterministic; does not depend on the model noticing) -----------------------------

_MARKUP = re.compile(
    r"<\s*/?\s*(script|img|iframe|svg|object|embed|style|form|input|a|body|html|meta|link|div|span|base)\b"
    r"|\bon[a-z]+\s*=\s*['\"]|javascript\s*:|data:text/html",
    re.IGNORECASE,
)
_ADDRESSED_TO_MACHINES = re.compile(
    r"\b(AI|LLM|GPT|ChatGPT|Claude)\b(\s+(assistant|system|model|agent|tool)s?)?"
    r"|\bartificial intelligence\b|\blanguage models?\b"
    r"|\bautomat(ed|ic|ion)\s+(\w+\s+){0,3}(processing|system|software|assistant|tool|approval)s?\b",
    re.IGNORECASE,
)
# Suspicious however they are phrased.
_INJECTION = re.compile(
    r"\b(ignore|disregard)\s+(all\s+|any\s+|the\s+)?(previous|prior|above)\s+instructions\b"
    r"|\bsystem prompt\b|\brequires_review\b|\breview_reasons\b|\bneeds_review\b",
    re.IGNORECASE,
)
# What an attempt to steer processing talks about. Used only with NARROW_SUSPICIOUS.
_STEERING = re.compile(
    r"\b(approv\w*|pre-?verif\w*|verif(y|ied)|review\w*|skip\w*|bypass\w*|ignor\w*|disregard\w*|overrid\w*"
    r"|do\s+not\s+(mention|flag|check|report|escalate)|don'?t\s+(mention|flag|check|report)|instruct\w*"
    r"|bank|account|a/c|ifsc|beneficiar\w*|payee|remit\s+to|pay\s+(to|into)|set\s+\w+\s+to|mark\w*\s+as"
    r"|priority|urgent\w*|authori[sz]\w*|exempt\w*|whitelist\w*|trusted)\b",
    re.IGNORECASE,
)


def _paragraph_around(text: str, index: int) -> str:
    start = text.rfind("\n\n", 0, index)
    end = text.find("\n\n", index)
    return text[start + 1 if start != -1 else 0: end if end != -1 else len(text)]


def suspicious_matches(raw_text: str) -> list[tuple[int, int, str]]:
    """Every stretch of text that makes a document `suspicious_content`, as (start, end, kind).

    Text addressed to automated systems or AI, or embedded HTML/script markup (AP_POLICY.md section 3).
    With NARROW_SUSPICIOUS on, text addressed to an automated system counts only if the same paragraph tries to
    steer processing (disp_04's "please quote the invoice number in the remittance advice" doesn't).
    """
    found = [(m.start(), m.end(), "markup") for m in _MARKUP.finditer(raw_text)]
    found += [(m.start(), m.end(), "instruction") for m in _INJECTION.finditer(raw_text)]
    narrow = flags.enabled(flags.NARROW_SUSPICIOUS)
    for match in _ADDRESSED_TO_MACHINES.finditer(raw_text):
        if not narrow or _STEERING.search(_paragraph_around(raw_text, match.start())):
            found.append((match.start(), match.end(), "addressed_to_automation"))
    return sorted(found)


def check_suspicious_content(raw_text: str) -> list[str]:
    return ["suspicious_content"] if suspicious_matches(raw_text) else []


def run_checks(conn: sqlite3.Connection, ref: ReferenceData, inv: Invoice, org_id: str = "meridian",
               received_on: date | None = None) -> list[str]:
    vendor = find_vendor(ref, inv)
    reasons = (
        check_credit_note(inv)
        + check_foreign_currency(inv)
        + check_gstin(inv)
        + check_vendor(vendor)
        + check_vendor_new(inv, vendor, received_on)
        + check_tax_type(inv, ref)
        + check_totals(inv)
        + check_duplicate(conn, ref, inv, org_id)
        + check_bank_details(inv, vendor)
        + check_line_arithmetic(inv)
        + check_date_after_receipt(inv, received_on)
    )
    return list(dict.fromkeys(reasons))
