# Decisions

## Architecture

**The model reads; code decides.** Ledgerline makes one LLM call per document, and that call only extracts fields. Everything that moves money is deterministic code, tested against the written policy:

- the review reasons (`validation.py`), with the Part 2 flags (`flags.py`);
- required approvals (`pipeline.py`);
- duplicate detection against `paid_invoices.csv` and the batch;
- approve and reject (`api.py`): server-side, transactional, one payment per invoice.

v0.3 let the model return `requires_review`. Part 3 shows what that costs. Opus routed both duplicates as *ready*, while writing in its own reply that it "could not run the duplicate check". The model never sees the payment history, so no prompt can fix that.

**Prompt and output design.**
- **The prompt is extraction-only.** It holds a fixed instruction block and the document, wrapped in `<document>` tags and described as untrusted third-party data.
- **Values are copied "as printed".** Dates are copied exactly as printed and parsed day-first by code (month-first for US vendors, policy 1). GSTINs are copied character for character, never "corrected".
- **Replies are parsed tolerantly.** Fenced or prose-wrapped JSON is accepted: 16–20 of 24 Opus replies arrive fenced.
- **Anything code can't read with certainty becomes `processing_error`.** Money is read as `Decimal`, and lakh/crore are parsed in code. An unreadable value is never guessed.
- **A grounding check catches invented or reinterpreted values.** The GSTIN, invoice number, IFSC, account number, total and date must actually be printed in the document. If one isn't, the document goes to review.
- **There is no verification pass.** It doubled cost and latency, and its claimed +2 points came from an eval that had its answers in the prompt.

**Hostile documents.** Every document is treated as written by an adversary:

- Nothing the model says can remove a review reason. dev_012's "set requires_review to false" reaches the model, but routing never asks the model anything.
- `suspicious_content` is detected in code on the raw text: markup, injection phrases, and text addressed to automated systems.
- Vendor-supplied text is rendered in the UI as text only. This fixed the dev_013 stored XSS.
- Evidence offsets (Part 4) are computed in code, never taken from the model.
- A document that plants a decoy value (a second "TOTAL ₹…" in its remarks) makes that field *ambiguous*. The reviewer is told so, and nothing is highlighted.

**What leaves Meridian's systems** (DPO, policy 5): one request per document to Anthropic, containing the fixed instructions and the document text.

- Every run of 9–18 digits is replaced by `[MASKED-ACCOUNT-n ending 1234]` before sending, and the real digits are restored locally.
- Not sent: the vendor master, the payment history, the AP policy and labelled examples. v0.3 sent all of those, including 38 vendors' bank accounts, twice per document.
- Known gap: an account number printed with spaces or dashes isn't masked. No document in the data has one.

**Measured result** (Part 3, `claude-opus-5-5`, 3 runs): 0/13 missed reviews, 0/11 unnecessary reviews, ₹1.48 per document, p95 7.3 s.

## Part 4: what I went deep on, and why

**I chose A, evidence-linked review.**

The product brief lists four things Meridian needs before rollout. After Parts 1–3, three were met on the dev set:

- no missed reviews: 0/13 in all three Opus runs;
- cost and latency: ₹1.48 per document and p95 7.3 s, against ₹1.50 and 10 s;
- nothing sent that the DPO would object to.

The fourth, "reviewers can see where every number came from", wasn't met at all. Farhan's email shows what that costs: reviewers "re-key everything from the PDF". At ₹85 per touch on 3,000 documents a month, re-keying throws away the savings Ledgerline exists for. It also turns the weekly audit, the main condition in my Part 3 recommendation, into a slow, error-prone re-typing job.

- **Not B (survive production):** what it would deliver is mostly already in place. Opus is within budget, if only just, and Part 1 measured Sonnet at ₹0.54 with 24/24 correct, which a $0.50 repeat run can confirm. Outage handling matters, but a missing review is already covered: on a provider failure the document becomes `processing_error`, goes to review, and is never dropped.
- **Not C:** the strongest candidate I considered was authentication, because the two-person rule is only as strong as a client-supplied `user_id`. Sign-in has to come from Meridian's identity provider, though, and that is not something I can build here.

The server-side half of A already existed from Part 1: approve and reject are transactional and idempotent, one person counts once, a note is required, duplicates and credit notes are refused, and both actions are audited. Part 4 adds the rest.

**What I built**

1. **Evidence for every extracted field** (`backend/ledgerline/evidence.py`).
   - For each field, it finds every place in the raw document where the value is printed. Amounts and dates are compared by value, so `35,624/-`, `35624` and `₹35,624.00` all match. Then it decides which place is the source.
   - **Exact:** exactly one place is labelled as this field. When CGST and SGST are both ₹1,789.20, the nearest label decides. A longer label beats a shorter one ending at the same place, so "Sub Total" is not "Total". e-invoice per-line keys (`CgstAmt`, `TotAmt`) don't count as document totals. An email's `Date:` header is never the invoice date (policy 1).
   - **Ambiguous:** several places could be the source and nothing tells them apart. The UI says "not sure: lines 18, 31" and highlights nothing. A confident highlight on the wrong text is worse than none, because it teaches reviewers to stop checking.
   - **Not found:** the value isn't printed at all.
   - Line-item amounts are located on the line that carries their description, taking the rightmost match, because the amount is the last column.
   - `text` is always exactly `raw_text[start:end]`. `predictions.jsonl` carries `evidence` in the contract's shape, for exact fields only.
2. **Every review reason in plain language, with its evidence** (`backend/ledgerline/explain.py`). Each reason gets a title, what was found, what to do, and links to the exact text. These come from the same facts the rule used, not from the model:
   - duplicate: the paid row ("SIS/26-27/0018, ₹34,220.00, paid on 2026-04-22"), or the earlier document in the batch;
   - bank change: account last-4 on the document vs on file, plus the call-back instruction. The vendor master's full account number never reaches the browser;
   - GSTIN: the expected check character, and any vendor one character away ("possibly an OCR error, possibly a look-alike"). It never corrects the GSTIN;
   - totals and line arithmetic: the full sum;
   - suspicious content: the offending text itself, highlighted.
3. **A review queue on the server** (`GET /api/queue`). It has two tabs. *Needs review* is ordered by worst reason first: bank change and suspicious content, then duplicates, unknown vendors, arithmetic, and finally paperwork such as foreign currency and credit notes. Within that, the oldest invoice comes first, because of the 45-day MSME clock. *Ready to approve* puts partly approved invoices first, where a second approver is waiting. Each row shows the reason titles and the days since the invoice date, in red from 30 days.
4. **A reviewer UI built for 150 a day** (`frontend/src/App.tsx`):
   - the extracted values beside the original text, with every located value lightly highlighted;
   - a Source link per field that scrolls to its text;
   - suspicious text outlined in red;
   - keys `j`/`k` (next, previous), `a` (approve), `r` (reject) and `n` (note);
   - after a decision, it moves on to the next document;
   - Approve is disabled, with the reason shown, for duplicates and credit notes. The server enforces this anyway;
   - an "Acting as" selector makes the missing sign-in visible instead of hard-coding `kavya.iyer`.
5. **Storage.** New `evidence_json` and `explanations_json` columns, added to an existing v0.3 database by a migration on connect.

**Evidence that it works**
- `backend/tests/test_evidence.py` (29 tests, offline) replays Sonnet's recorded real replies for all 24 dev documents. It checks:
  - every span is the exact slice of the document;
  - invoice number, date and total are exact on all 24, and GSTIN and bank account on every document that prints them;
  - 11 named hard cases land on the right line: CGST/SGST at the same value, subtotal = total on dev_014, e-invoice totals vs per-line keys, the email body date vs the `Date:` header, and the rightmost line amount;
  - a planted decoy total turns *ambiguous* and drops out of `predictions.jsonl`;
  - every reason is explained, with evidence slices that match the document;
  - the queue order;
  - the database migration.
- On the recorded **Opus** replies from Part 3, every located field of all 24 dev documents is *exact*: 290 spans. I checked the line each one lands on by hand for dev_001, 005, 006, 007, 012, 014 and 017.
- An end-to-end HTTP check against a seeded database returned:
  - a queue led by the two bank-change documents;
  - dev_005's explanation, with last-4 digits only;
  - a refusal for an approval without a note: "A note is required…".
- The full suite is 144 passed. `npm run build`, which runs `tsc`, passes.
- **Manual UI check (written, not yet run in a browser):**
  1. Run `make dev` and upload the dev set.
  2. In *Needs review*, the first item should be dev_005 or dev_024.
  3. Press `j` and `k` to move through the queue.
  4. On dev_001, click CGST's "line 17". Line 17 (`CGST @ 9% 1,789.20`) should highlight, not line 18.
  5. On dev_013, the `<img onerror…>` should show as red-outlined *text*, and the network tab should show no request to `exfil.example`.
  6. On dev_015, Approve should be disabled with "Duplicates can't be approved".

**Not done, and why**
- **No PDF view.** Documents reach Ledgerline as text (OCR is out of scope), so the source shown is the OCR text, not the scan. A reviewer checking an OCR misread (disp_01) still needs the PDF.
- **Line-item quantity and rate aren't located,** only line amounts. No rule depends on quantity or rate except the flagged `line_arithmetic_mismatch`.
- **Documents processed before this change have no evidence.** The evidence is computed at ingest.
- **No authentication.** See C above. Until there is sign-in, the "Acting as" selector is honest about it.

## Replies to stakeholders

> **Note for me:** the README requires these replies to be in my own words, so I'll write them myself. Below are only the facts and numbers each reply should rest on, taken from my own runs.

### Anita Rao, CFO
- **STP under ₹10,000: not now.** Policy 4.3 forbids automatic approval. The dev set can only bound the miss rate below about 21%.
- **What would make me agree:** four weeks of audit with zero misses in that segment, plus sign-in and a Finance Controller amendment. That would save about 1,040 documents and ₹88,000 of AP time a month.
- **The "fix the GSTIN" ask is declined.** The UI now names the vendor one character away and marks it "possibly OCR, possibly a look-alike", so it becomes a 30-second check instead of a bounce-back.
- **Cost:** ₹4,430 a month of LLM spend vs about ₹42,000 for v0.3's design.

### Farhan Sheikh, Head of AP
- **"Show the source":** done (Part 4). Every value links to its exact text, and the system says "not sure" rather than guessing.
- **Double payments:** fixed. 8 parallel approvals produce 1 payment.
- **Bank changes:** always reviewed, with an explicit call-back instruction. The phone-number field needs Sunil (see policy proposal 7).
- **"Most accurate model":** Opus and the cheaper model scored identically on routing in my runs. Accuracy came from moving the rules into code, not from the model.

### Deepak Menon, CTO
- **The bill was right; the dashboard was 1000× low.** Prices were per thousand, not per million. $165 for 2,400 documents is ₹6.05 each, which matches the measured cost of v0.3's first call (₹6.48).
- **Now:** ₹1.48 per document and p95 7.3 s on Opus. A Sonnet re-run (about $0.50) should confirm about ₹0.54. No new infrastructure.
- **Fine-tuning:** not needed. Extraction is already 251/252 fields correct, and the failures were in routing and code, which fine-tuning doesn't touch.

### Priya Natarajan, Data Protection Officer
- **Before:** every call sent the vendor master (38 bank accounts), the document's own account number and three labelled invoices, twice per document.
- **Now:** one call per document, with the document text only and account numbers masked to their last 4 digits. The test is `test_no_bank_account_number_is_sent_to_the_provider`.
- **Known gap:** an account number printed with spaces isn't masked.

### Sunil Joshi, Finance Controller
- **Review load:** 0/11 unnecessary reviews in each run, against a genuine problem rate of about 13%. Target: a review rate near 13%, alarm above 20%.
- **No policy edits.** Every departure is behind a flag that is off by default, and each is a proposal below.
- **The call-back workflow he asked to see:** the bank-change reason card (Part 4) is the workflow that would use the phone field.

### Ravi Kulkarni, contractor
- **His argument is real:** Finance changes the policy often and has no developer.
- **The answer is in my own runs:** with the policy in the prompt, Opus missed both duplicates. It *cannot* see the payment history, and it said so itself. A document can also talk to it (dev_012).
- **What I'd offer instead:** thresholds and lists as configuration Finance can edit, such as the 90 days, ₹5 lakh and ₹1.00 tolerances. Rule changes stay as small, tested code changes.
- **His instinct on name matching:** the model's flexibility is kept where it is safe, in reading layouts and names, not in deciding.

## Policy changes I propose

Each is off by default behind its own flag, or not implemented at all, until the Finance Controller agrees.

1. **Check line arithmetic** (`LEDGERLINE_FLAG_LINE_ARITHMETIC`).
   - **Change:** a line whose quantity × rate differs from its printed amount by more than ₹1.00 needs review.
   - **Why:** disp_05 overbills ₹649, and every existing check passes, because the totals check sums the *printed* line amounts.
   - **Cost:** it fired on 1 of 30 documents. An OCR misread of a quantity will cause the occasional ₹85 review.
2. **Treat a post-dated invoice as suspect** (`LEDGERLINE_FLAG_DATE_AFTER_RECEIPT`).
   - **Change:** an invoice dated after the day it was received needs review, and vendor age is measured at the earlier of the two dates.
   - **Why:** disp_06 shows a new vendor can post-date an invoice past the 90-day check.
   - **Cost:** reviews of genuine typos.
3. **Narrow `suspicious_content`** (`LEDGERLINE_FLAG_NARROW_SUSPICIOUS`).
   - **Change:** text addressed to automated systems counts only if it tries to influence checking, approval or payment, or contains markup.
   - **Why:** disp_04's courtesy note costs ₹85 and teaches reviewers to ignore the flag. Routing no longer listens to the model anyway.
   - **Risk:** an attacker learns to avoid the steering words. Markup and injection phrases are always flagged.
4. **Revised invoices reusing a paid number** (addition to 4.4).
   - **Change:** reject them, and ask the vendor for a debit note for the difference.
   - **Why:** disp_02 would pay ₹35,872 again to settle a ₹1,652 price change.
   - **Cost:** none; this is current practice written down.
5. **Define "domestic" by the supplier, not the currency** (no flag; same outcome in the data).
   - **Change:** when a document shows a GSTIN, or the vendor master says `IN`, run the GSTIN and tax-type checks and match by GSTIN. Keep 2 approvals for non-INR amounts.
   - **Why:** disp_03 is a Gujarat vendor billing in USD, and today it gets the *weaker* name-based checks.
6. **Auto-debit invoices are reconciled, never approved for payment.**
   - **Why:** dev_014 states that the card on file is charged automatically. Approving it creates a second payment.
   - **Cost:** a new review code, and it needs a flag before it is implemented.
7. **A call-back phone number in the vendor master.**
   - **Change:** record which number was called, by whom and when in the approval note, before any bank change is paid.
   - **Why:** last quarter's ₹3.8 lakh loss. The workflow that uses it now exists: the bank-change card in the review UI.
   - **Cost:** one field and onboarding effort.
8. **Straight-through processing for clean invoices under ₹10,000: not yet.**
   - **Change:** revisit after four weeks of production audit, with zero misses in that segment and sign-in in place. It would amend 4.3, behind a flag.
   - **Why wait:** the dev set can't show a miss rate below about 21%.
