"""Meridian's reference data: buyer details, vendor master, payment history and the AP policy text."""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

from .config import get_settings


@dataclass
class ReferenceData:
    buyer: dict
    vendors: list[dict]
    vendors_csv: str
    paid_invoices: list[dict]
    policy_text: str


def load_reference(reference_dir: str | Path | None = None) -> ReferenceData:
    settings = get_settings()
    ref_dir = Path(reference_dir) if reference_dir else settings.data_dir / "reference"
    vendors_csv = (ref_dir / "vendors.csv").read_text(encoding="utf-8")
    with open(ref_dir / "vendors.csv", newline="", encoding="utf-8") as f:
        vendors = list(csv.DictReader(f))
    with open(ref_dir / "paid_invoices.csv", newline="", encoding="utf-8") as f:
        paid = list(csv.DictReader(f))
    buyer = json.loads((ref_dir / "buyer.json").read_text(encoding="utf-8"))
    policy_text = (settings.docs_dir / "AP_POLICY.md").read_text(encoding="utf-8")
    return ReferenceData(buyer, vendors, vendors_csv, paid, policy_text)
