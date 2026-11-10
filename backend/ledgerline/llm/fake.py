"""Deterministic stand-in for tests, and for clicking around the UI without an API key."""
from __future__ import annotations

import json

from .base import LLMResponse

CANNED_EXTRACTION = {
    "document_type": "invoice",
    "supplier_name": "Sitara Industrial Supplies Pvt. Ltd.",
    "supplier_gstin": "27AAKCS4821M1ZW",
    "invoice_number": "SIS/26-27/0042",
    "invoice_date": "25/04/2026",
    "currency": "INR",
    "subtotal": "19,880.00",
    "cgst": "1,789.20",
    "sgst": "1,789.20",
    "igst": "0.00",
    "round_off": "-0.40",
    "total": "23,458.00",
    "bank_account": "50200012345678",
    "ifsc": "ZEPH0001234",
    "po_number": "PO-2026-0117",
    "notes": "",
    "line_items": [
        {"description": "SS Hex Bolt M10x40 (Box/100)", "quantity": "12", "unit_price": "1,450.00",
         "amount": "17,400.00"},
        {"description": "Spring Washer M10 (Pkt/500)", "quantity": "4", "unit_price": "620.00",
         "amount": "2,480.00"},
    ],
    "requires_review": False,
    "review_reasons": [],
}


class FakeClient:
    """Returns queued responses in order, then the canned extraction forever."""

    def __init__(self, responses: list[str] | None = None, model: str = "fake"):
        self.responses = list(responses or [])
        self.model = model
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, prompt: str, max_tokens: int = 2000) -> LLMResponse:
        self.calls.append((system, prompt))
        text = self.responses.pop(0) if self.responses else json.dumps(CANNED_EXTRACTION)
        return LLMResponse(text, self.model, len(prompt) // 4, len(text) // 4, 5)
