"""In-memory representation of an extracted invoice. Money is Decimal (AP_POLICY.md section 1)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal


@dataclass
class LineItem:
    description: str
    quantity: Decimal | None
    unit_price: Decimal | None
    amount: Decimal | None


@dataclass
class Invoice:
    document_type: str
    supplier_name: str | None
    supplier_gstin: str | None
    invoice_number: str | None
    invoice_date: date | None
    currency: str
    subtotal: Decimal | None
    cgst: Decimal
    sgst: Decimal
    igst: Decimal
    round_off: Decimal
    total: Decimal | None
    bank_account: str | None
    ifsc: str | None
    po_number: str | None
    notes: str | None
    line_items: list[LineItem] = field(default_factory=list)

    @property
    def is_domestic(self) -> bool:
        return self.currency == "INR"
