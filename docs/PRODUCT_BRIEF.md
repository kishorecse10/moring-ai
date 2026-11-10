# Ledgerline product brief

## Who uses it

- **AP clerks** (six people) upload or forward documents and correct extraction errors.
- **Approvers** (the AP Lead and the Finance Controller) approve payments.
- **Finance leadership** watches throughput, exceptions and cost.

## Volumes

About 3,000 documents a month: 70% OCR text from scanned PDF invoices, 20% invoices typed into email bodies, and 10% government e-invoice JSON. Month-end peaks reach about 400 documents a day. Most vendors are Indian; a few US software vendors bill in USD.

## Workflow

1. A document arrives, uploaded by a clerk or forwarded from the AP mailbox.
2. Ledgerline extracts its fields and checks them against the AP policy.
3. It routes the document to **ready for approval** or **needs review**, with reasons.
4. An approver approves or rejects it. Each approved invoice gets exactly one payment instruction, which treasury picks up daily.

## What "ready for rollout" means to Meridian

- No document that needed review is ever routed as ready. In the AP Lead's words: "I can live with extra reviews. I can't live with a missed one."
- Reviewers can see where every number came from.
- Average LLM cost is ₹1.50 or less per document, and p95 processing time is under 10 seconds.
- Nothing the Data Protection Officer would object to.

## About the data in this repository

The documents and reference data are a snapshot taken in mid-May 2026. The dev and disputed sets are deliberately rich in problem cases, so their review rate is not Meridian's. In production, about 40% of invoices are under ₹10,000. When the AP team re-checked a random sample of 200 October documents by hand, 26 of them (13%) had a genuine problem that needed review.

## Out of scope

OCR itself (documents arrive as text), executing payments, vendor onboarding and currency conversion.
