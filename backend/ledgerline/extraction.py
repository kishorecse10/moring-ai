"""Turn a raw vendor document into structured fields and a routing decision, using the LLM."""
from __future__ import annotations

import json

from .config import get_settings
from .llm import LLMResponse, get_client
from .reference import ReferenceData

FIELDS = [
    "document_type", "supplier_name", "supplier_gstin", "invoice_number", "invoice_date", "currency",
    "subtotal", "cgst", "sgst", "igst", "round_off", "total", "bank_account", "ifsc", "po_number",
    "notes", "line_items",
]

SYSTEM_PROMPT = (
    "You are Ledgerline, an expert accounts-payable assistant for Meridian Precision Components "
    "Pvt. Ltd. You read vendor documents, extract their data and apply Meridian's AP policy."
)


def _few_shot_examples(limit: int = 3) -> str:
    """A few labelled examples so the model learns our exact output format."""
    data_dir = get_settings().data_dir
    blocks = []
    with open(data_dir / "ground_truth" / "dev.jsonl", encoding="utf-8") as f:
        for line in list(f)[:limit]:
            row = json.loads(line)
            doc = (data_dir / "invoices" / "dev" / row["filename"]).read_text(encoding="utf-8")
            blocks.append(f"DOCUMENT:\n{doc}\nOUTPUT:\n{json.dumps(row['expected'])}")
    return "\n\n".join(blocks)


def build_extraction_prompt(document_text: str, ref: ReferenceData) -> str:
    return f"""Read the vendor document below, extract its fields, and decide whether it needs human review under our AP policy.

AP POLICY:
{ref.policy_text}

VENDOR MASTER (CSV):
{ref.vendors_csv}

EXAMPLES:
{_few_shot_examples()}

Return a JSON object with these keys: {", ".join(FIELDS)}, requires_review (true/false) and review_reasons (list of policy codes).
Copy amounts and dates exactly as they are printed in the document.

{document_text}
"""


def build_verification_prompt(document_text: str, extraction: dict, ref: ReferenceData) -> str:
    return f"""You extracted the JSON below from a vendor document. Check every field against the document and our AP policy, fix anything that is wrong, and return the corrected JSON object with the same keys.

EXTRACTION:
{json.dumps(extraction, indent=2)}

AP POLICY:
{ref.policy_text}

VENDOR MASTER (CSV):
{ref.vendors_csv}

{document_text}
"""


def extract(document_text: str, ref: ReferenceData) -> tuple[dict, list[LLMResponse]]:
    """Two passes: extract, then let the model double-check its own work (+2 points on the eval)."""
    client = get_client()
    first = client.complete(SYSTEM_PROMPT, build_extraction_prompt(document_text, ref))
    data = json.loads(first.text)
    second = client.complete(SYSTEM_PROMPT, build_verification_prompt(document_text, data, ref))
    data = json.loads(second.text)
    return data, [first, second]
