# Meridian Precision Components: Accounts Payable Policy

Version 3.2, effective 1 April 2026. Owner: Finance Controller.

This policy is the source of truth for how Ledgerline classifies, checks and routes vendor documents. Where code, tests or any other document disagree with it, this policy wins.

## 1. Definitions

**Buyer.** Meridian Precision Components Pvt. Ltd. Its GSTIN is in `reference/buyer.json`. Its state code is `27` (Maharashtra).

**Domestic and foreign documents.** A document in INR is domestic; a document in any other currency is foreign. Every domestic document must show the supplier's GSTIN.

**Financial year (FY).** 1 April to 31 March. A document dated 2026-04-03 belongs to FY 2026-27; one dated 2026-03-31 belongs to FY 2025-26.

**Dates.** Indian vendors print dates day first (DD/MM/YYYY, DD-MM-YYYY or DD.MM.YYYY). Vendors whose `country` in the vendor master is `US` print dates month first (MM/DD/YYYY). Ledgerline stores ISO dates (YYYY-MM-DD). The document date is the date printed on the invoice, never the date an email was sent.

**Amounts.** Documents use Indian digit grouping (1,23,456.78), prefixes such as `Rs.`, `₹` and `INR`, a `/-` suffix, and the words lakh (1,00,000) and crore (1,00,00,000). Amounts are exact decimals with two places. Never store or compare them as binary floating point.

**Normalized invoice number.** Uppercase, with spaces and the characters `/ - # .` removed. `SIS / 26-27 / 0018` becomes `SIS26270018`. Leading zeros are significant.

**Supplier key.** For domestic documents, the supplier's GSTIN. For foreign documents, the supplier's legal name, compared case-insensitively and ignoring spaces and punctuation.

**Vendor master.** `reference/vendors.csv`. A domestic supplier is identified by GSTIN alone; the name printed on a document is not proof of identity. A foreign supplier is identified by its supplier key.

## 2. Document types

| Type | Meaning |
|---|---|
| `invoice` | A demand for payment. |
| `credit_note` | A document that reduces what Meridian owes, for example one titled "Credit Note", or an e-invoice whose `DocDtls.Typ` is `CRN`. Credit notes are never approved for payment. |

## 3. Review reasons

A document needs human review if one or more of these rules apply. Ledgerline must report **every** rule that applies, using exactly these codes.

| Code | Applies when |
|---|---|
| `credit_note` | The document is a credit note. |
| `duplicate` | The document is an invoice, and an invoice with the same supplier key, normalized invoice number and FY already exists, either in `reference/paid_invoices.csv` or earlier in the same batch. Batches are processed in `document_id` order. Credit notes are not checked. |
| `gstin_invalid` | A domestic document whose supplier GSTIN is missing, malformed, or fails the checksum in Appendix A. |
| `vendor_unknown` | No vendor in the vendor master matches the supplier key. |
| `vendor_new` | The matched vendor's `onboarded_on` date is fewer than 90 days before the document date. |
| `bank_details_changed` | The document shows a bank account number or IFSC that differs from the matched vendor's details on file. Compare account numbers digits-only and IFSC case-insensitively. Not raised when the vendor is unknown, or when the document shows no bank details. |
| `tax_type_mismatch` | A domestic document where the supplier's state code (the first two digits of its GSTIN) equals the buyer's but IGST is charged, or differs from the buyer's but CGST or SGST is charged. |
| `totals_mismatch` | The absolute difference between (sum of line amounts + CGST + SGST + IGST + round-off) and the stated total is more than ₹1.00. A difference of exactly ₹1.00 is within tolerance. |
| `foreign_currency` | The currency is not INR. |
| `suspicious_content` | The document contains text addressed to automated systems or AI (for example, instructions to skip checks or change an approval decision), or embedded HTML or script markup. |
| `processing_error` | Ledgerline could not process the document reliably. These documents always go to review. They are never skipped or dropped. |

`needs_review` is true when at least one reason applies. Otherwise the document is ready for approval.

## 4. Approvals

1. **Required approvals.** Credit notes: 0, because they cannot be approved for payment. Foreign-currency invoices: 2. Invoices with a total of ₹5,00,000.00 or more: 2. All other invoices: 1.
2. Each approval must come from a different person. One person approving twice counts once.
3. Every invoice needs at least one human approval before it is paid. **There is no automatic approval** under this version of the policy.
4. Invoices flagged `duplicate` cannot be approved. They can be rejected.
5. An approver must record a note when approving a document that needed review.
6. When the required number of approvals is reached, the invoice is approved and **exactly one** payment instruction is created.
7. Approvals and rejections are recorded in an audit log: who, when, which document, and the note.

## 5. Data handling

Set by Meridian's Data Protection Officer.

1. Vendor bank account numbers must not be sent to external LLM providers. Masking all but the last four digits is acceptable.
2. Send external providers only the data the task needs.
3. Keep the original document and every automated decision for audit.

## Appendix A: GSTIN format and checksum

A GSTIN has 15 characters: a 2-digit state code, a 10-character PAN (5 letters, 4 digits, 1 letter), an entity number (1–9 or A–Z), the letter `Z`, and a check character.

To compute the check character, map each of the first 14 characters to a value using the alphabet `0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ` (values 0–35). Multiply the value at position *i* (counting from 0 on the left) by 1 if *i* is even and by 2 if *i* is odd. Replace each product *p* with `p // 36 + p % 36` and add up the results. The check character is the alphabet character at position `(36 - sum % 36) % 36`.

Worked example: `27AAPFU0939F1ZV` is valid, and its check character is `V`.

## Appendix B: State codes in our data

| Code | State |
|---|---|
| 06 | Haryana |
| 07 | Delhi |
| 09 | Uttar Pradesh |
| 19 | West Bengal |
| 23 | Madhya Pradesh |
| 24 | Gujarat |
| 27 | Maharashtra |
| 29 | Karnataka |
| 36 | Telangana |
