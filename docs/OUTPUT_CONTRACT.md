# Output contract

Meridian's nightly batch job runs this command from `backend/`. It must work on any folder of documents and reference data, not just the ones in this repository:

```bash
python -m ledgerline.cli predict \
    --input     <folder of .txt, .eml and .json documents> \
    --reference <folder containing buyer.json, vendors.csv and paid_invoices.csv> \
    --output    <predictions.jsonl>
```

It must work from a fresh clone after `pip install -e ./backend` and `cp .env.example .env`, with an empty database. If your version needs anything else, say so in the **Running my version** section at the end of the README.

## Rules

- Write one JSON object per input document, one per line, in `document_id` order.
- `document_id` is the file name without its extension.
- **Never skip a document.** If you can't process one reliably, still write its line, with `needs_review: true` and `"processing_error"` among its reasons.
- Use the reference data passed in `--reference`, not the copies in `data/reference/`. Other reference data will include vendors and payment history that the dev set doesn't.

## Fields

| Field | Type | Notes |
|---|---|---|
| `document_id` | string | |
| `document_type` | `"invoice"` or `"credit_note"` | |
| `supplier_name` | string | As printed. |
| `supplier_gstin` | string or null | As printed. Null when none is shown. |
| `invoice_number` | string | As printed. For a credit note, the credit note's own number. |
| `invoice_date` | `"YYYY-MM-DD"` | The document's date, not an email's send date. |
| `currency` | string | ISO 4217 code: `"INR"`, `"USD"` and so on. |
| `subtotal`, `cgst`, `sgst`, `igst`, `round_off`, `total` | string | Two decimal places, such as `"23458.00"` or `"-0.40"`. Taxes that aren't charged are `"0.00"`. |
| `bank_account` | string or null | Digits as printed. |
| `ifsc` | string or null | |
| `po_number` | string or null | Meridian's purchase order reference, if shown. |
| `line_items` | list | Each item has `description`, `quantity`, `unit_price` and `amount`. |
| `needs_review` | boolean | |
| `review_reasons` | list of strings | Codes from section 3 of `AP_POLICY.md`, in any order. New codes only behind a flag (see Part 2 of the README). |
| `required_approvals` | integer | As defined in section 4 of `AP_POLICY.md`. |
| `usage` | object | Measured for this document: `llm_calls`, `input_tokens`, `output_tokens`, `cost_inr`, `latency_ms`. |
| `evidence` | object, optional | For Part 4A. Maps a field name to `{"start": int, "end": int, "text": str}`. Offsets are Python string indices into the document decoded as UTF-8, and `text` must equal that slice exactly. Leave a field out rather than guess. |

## Example

Shown wrapped for readability. Write each object on a single line. The `usage` numbers are illustrative, not from a real run.

```json
{
  "document_id": "dev_001",
  "document_type": "invoice",
  "supplier_name": "Sitara Industrial Supplies Pvt. Ltd.",
  "supplier_gstin": "27AAKCS4821M1ZW",
  "invoice_number": "SIS/26-27/0042",
  "invoice_date": "2026-04-25",
  "currency": "INR",
  "subtotal": "19880.00",
  "cgst": "1789.20",
  "sgst": "1789.20",
  "igst": "0.00",
  "round_off": "-0.40",
  "total": "23458.00",
  "bank_account": "50200012345678",
  "ifsc": "ZEPH0001234",
  "po_number": "PO-2026-0117",
  "line_items": [
    {
      "description": "SS Hex Bolt M10x40 (Box/100)",
      "quantity": "12",
      "unit_price": "1450.00",
      "amount": "17400.00"
    },
    {
      "description": "Spring Washer M10 (Pkt/500)",
      "quantity": "4",
      "unit_price": "620.00",
      "amount": "2480.00"
    }
  ],
  "needs_review": false,
  "review_reasons": [],
  "required_approvals": 1,
  "usage": {
    "llm_calls": 1,
    "input_tokens": 2140,
    "output_tokens": 455,
    "cost_inr": 0.08,
    "latency_ms": 2900
  },
  "evidence": {
    "total": {
      "start": 1486,
      "end": 1495,
      "text": "23,458.00"
    },
    "invoice_date": {
      "start": 440,
      "end": 450,
      "text": "25/04/2026"
    },
    "supplier_gstin": {
      "start": 169,
      "end": 184,
      "text": "27AAKCS4821M1ZW"
    }
  }
}
```
