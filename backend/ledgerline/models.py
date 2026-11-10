"""In-memory representation of an extracted invoice."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class LineItem:
    description: str
    quantity: float | None
    unit_price: float | None
    amount: float


@dataclass
class Invoice:
    document_type: str
    supplier_name: str | None
    supplier_gstin: str | None
    invoice_number: str | None
    invoice_date: date | None
    currency: str
    subtotal: float | None
    cgst: float
    sgst: float
    igst: float
    round_off: float
    total: float | None
    bank_account: str | None
    ifsc: str | None
    po_number: str | None
    notes: str | None
    line_items: list[LineItem] = field(default_factory=list)
