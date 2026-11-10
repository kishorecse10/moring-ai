# Rulings on the disputed documents

## Flags

All three are off by default, so Ledgerline follows `AP_POLICY.md` v3.2 as written unless one is switched on. `make predict-flags` runs the batch with all three on. `submission/predictions_disputed.jsonl` was produced that way, on `claude-sonnet-5-5`, on 2026-11-10.

| Flag | Document | What it changes | New reason code |
|---|---|---|---|
| `LEDGERLINE_FLAG_DATE_AFTER_RECEIPT=1` | disp_06 | An invoice dated after the day we received it (an email's `Date` header, otherwise the processing date) needs review. `vendor_new` is judged on the earlier of the printed date and the received date. | `date_after_receipt` |
| `LEDGERLINE_FLAG_LINE_ARITHMETIC=1` | disp_05 | A line whose quantity × unit price differs from its printed amount by more than ₹1.00 needs review. | `line_arithmetic_mismatch` |
| `LEDGERLINE_FLAG_NARROW_SUSPICIOUS=1` | disp_04 | Text addressed to an automated system counts as `suspicious_content` only if the same paragraph tries to steer processing (approval, review, checks, bank details, urgency…). Markup and classic injection phrases ("ignore previous instructions", `requires_review`) still always count. | none (narrows an existing code) |

I consider disp_06 and disp_05 the riskiest. The written policy routes both as **ready**, so each is a missed review with money attached. disp_02 has the largest rupee exposure, but the written policy already handles it, and Part 1 made the "duplicates can't be approved" rule hold on the server.

Code: `backend/ledgerline/flags.py` and `validation.py`. Tests: `backend/tests/test_flags.py`. The tests replay Sonnet's recorded replies for all six documents, flags off (the written policy) and flags on (these rulings). They also check that the flags change nothing on the 24 dev documents.

---

## disp_01: Sitara invoice, GSTIN printed `27AAKCS4B21M1ZW`

**Ruling: needs review.** Reasons `gstin_invalid` and `vendor_unknown`; 1 approval.

**Policy:** Appendix A: the checksum fails (`B` sits where the PAN needs a digit). Section 1: "A domestic supplier is identified by GSTIN alone; the name printed on a document is not proof of identity." So no vendor matches.

**Strongest argument against:** This is obviously OCR reading 8 as B. The name, address, rates and bank account are all Sitara's on file, so even if the invoice were wrong, the money would go to Sitara. Sending it to review spends ₹85 for nothing, and this kind of OCR error will be common. That is the CFO's point.

**Why I still rule review:** Ledgerline can't tell an OCR slip from a look-alike GSTIN. Meridian's GST input credit depends on the GSTIN being right, and checking it against the PDF takes a reviewer seconds. I will not let the model "fix" it. Part 1's grounding check sends a silently corrected GSTIN to review.

**Proposal to the Finance Controller:** keep the rule. Add a reviewer hint, with no change to routing: "one character from V0030 Sitara; bank details match: probable OCR error". That makes this a 30-second review.

**Pipeline matches the ruling:** yes, `gstin_invalid, vendor_unknown`, 1 approval.

## disp_02: Sitara "TAX INVOICE (REVISED)" SIS/26-27/0018, ₹35,872

**Ruling: needs review, `duplicate`. It cannot be approved, only rejected (policy 4.4). Ask Sitara for a debit note for the difference.**

**Policy:** Section 3, `duplicate`: same GSTIN, normalised number `SIS26270018` and FY 2026-27 as a row in `paid_invoices.csv`. That row is ₹34,220, paid on 2026-04-22.

**Strongest argument against:** The vendor is open about it: the document says it supersedes the original. The rate rise (₹1,450 → ₹1,520 a box) is dated before the invoice, and Meridian may genuinely owe more. Refusing to approve it delays an MSME's money over a paperwork technicality.

**Why I still rule duplicate:** Meridian does owe more, but the extra is ₹1,652 (20 boxes × ₹70, plus 18% GST), not ₹35,872. Approving this document pays the whole invoice a second time. A price increase after the invoice was issued is normally billed by debit note or a supplementary invoice, not by reusing the number. Correcting that is AP's job, not the system's.

**Proposal:** add a line to policy 4.4: "a revised invoice with the number of an already-paid invoice is rejected, and the vendor asked for a debit note for the difference." Nothing else needs to change.

**Pipeline matches the ruling:** yes, `duplicate`; the server refuses to approve it.

## disp_03: Narmada Polymers invoice in USD, with GST and an INR equivalent

**Ruling: needs review, `foreign_currency`; 2 approvals.**

**Policy:** Section 1: "a document in any other currency is foreign". Section 3, `foreign_currency`; 4.1: foreign-currency invoices need 2 approvals.

**Strongest argument against:** This isn't a foreign supplier. Narmada is a Gujarat vendor with a GSTIN, charging IGST, and it prints an INR value of ₹2,32,601.60, which is under the ₹5 lakh threshold. Treating it as foreign switches off the GSTIN and tax-type checks and matches the vendor by name. Those are the weaker controls, on a domestic vendor. A second approval for a routine ₹2.3 lakh resin order is wasted effort.

**Why I rule as written:** The exchange-rate exposure is real. "Linked to the resin index" means the rupee amount is not fixed, and currency conversion is out of Ledgerline's scope. Two people should agree to pay it.

**Proposal (a gap in the policy):** define domestic by the *supplier*, not the currency. When a document shows a GSTIN, or the vendor master says `IN`, run the GSTIN and tax-type checks and match by GSTIN, whatever the currency. Keep 2 approvals for non-INR amounts. I did not add a flag for this: on this document every one of those checks passes, so the outcome would be the same.

**Pipeline matches the ruling:** yes, `foreign_currency`, 2 approvals.

## disp_04: Vardhan Logistics email, "Note for your AP automation system"

**Ruling: ready for approval.** No reasons; 1 approval. This departs from the written policy, behind `NARROW_SUSPICIOUS`.

**Policy:** Section 3, `suspicious_content`: "text addressed to automated systems or AI (for example, instructions to skip checks or change an approval decision)". Read literally, this note is addressed to an automated system. The examples, though, describe steering a decision, and this note only asks us to quote the invoice number on the remittance advice. Vendor, GSTIN, bank details and totals all match the vendor master.

**Strongest argument against:** The AP Lead's rule is "I can live with extra reviews. I can't live with a missed one." The broad rule is the cheapest tripwire there is. Attackers start with harmless-looking notes to see what gets through. A list of steering words is something an attacker can learn to avoid, while "talks to the machine at all" is not.

**Why I rule ready:** After Part 1, nothing the document says to the model can change routing. Every reason is computed in code, so the danger the rule was written for is mostly gone. The steering list is deliberately broad: approval, verification, skipping, bank and account details, urgency. Markup and injection phrases are always flagged. Flagging courtesy notes costs ₹85 each, and teaches reviewers to ignore the flag.

**Proposal:** reword the rule to "…addressed to automated systems or AI *that attempts to influence how the document is checked, approved or paid*, or contains markup".

**Pipeline matches the ruling:** with the flag on, yes. With it off it is `suspicious_content`, which is the written policy.

## disp_05: Precision Gauges, 4 × ₹3,850.00 printed as ₹15,950.00

**Ruling: needs review,** new reason `line_arithmetic_mismatch`, behind `LINE_ARITHMETIC`; 1 approval.

**Policy:** This falls in a gap. `totals_mismatch` sums the *printed* line amounts, and the subtotal, CGST, SGST and total are all computed from the padded line, so every written check passes. dev_004 bills the same gauge at the same rate as 4 × 3,850 = 15,400. This invoice overcharges ₹550, plus ₹99 of GST: **₹649**.

**Strongest argument against:** This invents a rule the Finance Controller didn't write, over ₹649. OCR misreads in quantity or rate will cause false reviews. The quantity and rate come from the model and aren't checked against the page the way amounts are. And at ₹85 a review, Sunil's "don't send everything to review" applies.

**Why I still rule review:** It is the cheapest overbilling trick there is. Nothing downstream would catch it. It recurs if it works. And it fired on exactly one of the 30 documents, so it doesn't send everything to review. A false positive costs ₹85; a missed one pays a padded invoice every month.

**Proposal:** add the rule to section 3 with a ₹1.00 tolerance per line.

**Pipeline matches the ruling:** with the flag on, yes. With it off, the document is routed ready.

## disp_06: Shakti Castings, emailed 28 Apr 2026, invoice dated 25/06/2026

**Ruling: needs review,** reasons `date_after_receipt` and `vendor_new`, behind `DATE_AFTER_RECEIPT`; 1 approval.

**Policy:** Section 1: "The document date is the date printed on the invoice, never the date an email was sent." On the printed date, Shakti (onboarded 2026-03-20) is 97 days old, so `vendor_new` (fewer than 90 days) doesn't apply, and the written policy routes the invoice **ready**. The policy says nothing about an invoice dated in the future.

**Strongest argument against:** The policy is explicit about which date counts, and that rule exists so a vendor's email date doesn't override the invoice date. This is most likely a typo for 25/04. Shakti is a real, onboarded vendor, and its bank details match. I would be overriding written policy over a typo.

**Why I still rule review:** An invoice can't be dated two months after we received it, so the printed date is wrong either way. It is also the date the FY and duplicate checks key on. Even if this one is a typo, it shows the rule can be gamed: any new vendor can post-date its first invoice by three months and clear the new-vendor check. That check is the control Meridian has for exactly that vendor. I measure the vendor's age on the earlier of the two dates. I keep the printed date as the document date, so the FY and duplicate keys follow the policy.

**Proposal:** add to section 3: "an invoice dated after the date it was received needs review; vendor age is measured at the earlier of the document date and the date received."

**Pipeline matches the ruling:** with the flag on, yes. With it off, it is routed ready.
