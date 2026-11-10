"""Field accuracy on the labelled dev set.  Usage (from backend/):  python eval/run_eval.py"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ledgerline import db  # noqa: E402
from ledgerline.config import get_settings  # noqa: E402
from ledgerline.pipeline import process_document  # noqa: E402
from ledgerline.reference import load_reference  # noqa: E402

FIELDS = ["document_type", "supplier_name", "supplier_gstin", "invoice_number", "invoice_date", "currency",
          "subtotal", "cgst", "sgst", "igst", "total", "po_number"]


def _norm(value) -> str:
    if value is None:
        return ""
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value).strip().lower()


def main() -> None:
    settings = get_settings()
    ref = load_reference()
    conn = db.connect(str(Path(tempfile.mkdtemp()) / "eval.db"))
    with open(settings.data_dir / "ground_truth" / "dev.jsonl", encoding="utf-8") as f:
        rows = [json.loads(line) for line in f]

    correct = total = 0
    for row in rows:
        path = settings.data_dir / "invoices" / "dev" / row["filename"]
        try:
            got = process_document(conn, ref, path.read_text(encoding="utf-8"), row["document_id"])
        except Exception as exc:
            print(f"skipping {row['document_id']}: {exc}")
            continue
        for field in FIELDS:
            total += 1
            correct += _norm(got.get(field)) == _norm(row["expected"].get(field))
    print(f"Field accuracy: {correct}/{total} = {correct / total:.1%}")


if __name__ == "__main__":
    main()
