# Evaluation report

## Setup

- **Provider and model:** Anthropic API, `claude-opus-5-5` (Meridian's production model) for every number in this report. The starter and my version run on the same model, with default settings (adaptive thinking, default effort). Prices are list prices, $4 / $20 per million input / output tokens, at finance's ₹88/$.
- **Date:** 2026-11-10.
- **Documents:** the 24 labelled dev documents (13 need review, 11 are clean under the written policy), plus the 6 disputed documents with the Part 2 flags on.
- **Runs:**
  - My version: 3 independent live runs over dev, and 1 over disputed.
  - The starter: 1 live run over dev, using the v0.3 code from commit `e2f4ac2`, unmodified. Every raw reply was recorded.
  - The files are in `submission/eval_runs/`. Each run folder has `predictions.jsonl`, `calls.jsonl` (every call's tokens, latency and raw reply) and `meta.json`.
- **Reproduce:** `make eval-score` re-scores the recorded runs offline, for free. `make eval-live` repeats the live runs (billed, about $5 on Opus).
- **Code:**
  - `backend/eval/run_live.py` runs either code tree with real calls. With `--replay <calls.jsonl>`, it feeds recorded replies back through a tree at no cost.
  - `backend/eval/score.py` does the scoring.
  - `backend/tests/test_eval_score.py` tests the scorer offline.
- **Two things went wrong during the runs, and how I handled them:**
  - A second, overlapping `make eval-live` cut my run 2's `predictions.jsonl` short. Its `calls.jsonl` (all 24 real replies) survived. I rebuilt the predictions by replaying those replies through the same code. Routing is deterministic once the replies are fixed, so nothing is invented. Run 2's latency is the recorded LLM time plus local processing.
  - The starter crashes on its first reply, so its verification pass ran on only 5 of 24 documents (see below). I did not pay to re-run it. The parse-fixed starter numbers come from replaying its 29 recorded Opus replies through its own code. Where a verification reply was never recorded, the replay assumes "the verification changed nothing" and bills nothing for it. Its cost and latency are therefore an **underestimate** of the full design.

## What the "94%" actually measured

`run_eval.py` compares 12 extracted fields as strings, after lower-casing them and formatting numbers to two decimals. It does three things that make the number meaningless for Meridian:

1. **It skips any document that fails** (`skipping …: continue`). A document that crashes simply drops out of the denominator.
2. **It grades answers it gave the model.** v0.3 put dev_001 to dev_003, with their labels, into every prompt as few-shot examples.
3. **It never looks at routing.** `needs_review`, `review_reasons` and `required_approvals` aren't scored. Those are the only outputs that move money.

| Starter on `claude-opus-5-5` | Handover method | Leaked docs removed, failures counted |
|---|---|---|
| As shipped | **No number.** Every Opus first reply is wrapped in a ```` ```json ```` fence or prose (18 of 24 fenced, the rest prose first), so `json.loads` fails on all 24. `run_eval.py` skips all of them and divides by zero. | **0/252 = 0.0%** |
| JSON parse fixed (replay of the same replies) | 287/288 = **99.7%** | 251/252 = **99.6%** |
| Mine (3 runs, identical) | 287/288 = 99.7% | 251/252 = 99.6% (252/252 under my labels) |

I could not reproduce 94.2%. On the shipped code the number doesn't exist. Once the parse is fixed it is higher than 94%, and **that starter still routes both duplicate invoices as ready**. Two documents that field accuracy scores as about 100% correct are exactly the ones that would pay an invoice twice. Field accuracy is the wrong yardstick, so it is not the headline below.

The October bill is consistent with the crash. $165 for about 2,400 documents is **₹6.05 per document**. I measured ₹6.48 for the starter's first call alone, while the full two-call design costs about ₹14. October's spend looks like one call per document, with the verification pass never reached. That is an inference, not proof.

## What I chose to measure, and why

These are in order of what they cost Meridian when they go wrong:

1. **Missed reviews:** a document that needed review, routed *ready*. This is the AP Lead's "I can't live with a missed one", and the only error that can pay a fraudster or pay twice.
2. **Lost documents:** documents that got no routing at all. These are invisible work and late MSME payments.
3. **Whether every required review reason was reported.** A review flagged for the wrong reason sends the reviewer to check the wrong thing. On a duplicate, that check is the one that stops payment.
4. **Required approvals:** under-counting lets one person release a ₹5 lakh or foreign-currency invoice.
5. **Unnecessary reviews:** ₹85 of AP time each, and the Finance Controller's MSME 45-day concern.
6. **Cost per document (₹) and latency p50/p95**, from real calls. Latency is the end-to-end `process_document` wall time, with every LLM call included. It is not the API's latency alone. p95 is nearest-rank.
7. **Field accuracy**, last, and only on documents the model never saw.

## Starter versus mine, on the same model

All on `claude-opus-5-5`, dev set, 24 documents.

| Metric | Starter as shipped | Starter, parse fixed | Mine (3 runs) |
|---|---|---|---|
| **Missed reviews** (needed review, routed ready) | 0/13, but only because nothing was routed | **2/13** (dev_015, dev_019: both duplicates) | **0/13 in each run** |
| **Lost documents** (no routing) | **24/24** | 0 | 0 |
| Unnecessary reviews | n/a | 0/11 | 0/11 in each run |
| Every required reason reported | n/a | 11/13 | 13/13 |
| Required approvals correct | n/a | 21/24 (credit note dev_007 got 1; USD dev_014 got 1; dev_017 at exactly ₹5,00,000 got 1) | 24/24 |
| LLM calls per document | 1 (crashes before the second) | 2 by design (5 of 24 observed) | 1 |
| Tokens per document, in / out | 8,854 / 1,913 | first call 8,853 / 1,963; second call about 6,650 / 2,884 | 1,308 / 571–587 |
| **Cost per document (₹)** | **6.48** (and nothing to show for it) | 8.03 measured (underestimate); about **14.0** for the full design (6.57 + 7.42) | **1.46 / 1.49 / 1.47** (mean 1.48) |
| **Latency p50 / p95 (s)** | 16.8 / 21.1 | 17.7 / 41.6 measured; about 45–50 s p95 for the full design | **5.6 / 7.3** (per-run p95 6.7–7.4) |
| Field accuracy, no leak, failures counted | 0.0% | 99.6% | 99.6% (100% under my labels) |
| Monthly LLM spend at 3,000 documents | ₹19,400 | about ₹42,000 | **₹4,430** |

On the disputed set, with the flags on, my version routed all six exactly as `RULINGS.md` rules, at ₹1.36 per document and 4.4–7.2 s each.

On the CTO's targets, my version meets both on this set, but the cost margin is thin. ₹1.48 against a ₹1.50 ceiling leaves 2 paise of headroom on short documents. About 580 of each document's output tokens go to the model's thinking and the JSON, and a long, multi-page OCR invoice will cost more. Part 1 measured `claude-sonnet-5-5` on the same prompt at ₹0.54 and p95 3.5 s, with 24/24 routed correctly. That was a single run, so I treat it as promising, not proven (see the recommendation).

## Labels I disagree with

The labels follow the written policy, and I agree with every routing label. I disagree with one field label, and with what one label leaves unsaid.

- **dev_015 `invoice_number`.** The label is `SIS/26-27/0018`, but the document prints `SIS / 26-27 / 0018`, and `OUTPUT_CONTRACT.md` says "as printed". Every run of both pipelines returned the printed form, and the scorer counted it wrong. It is the only field error left in my runs. Accepting the printed form (`LABEL_CORRECTIONS` in `score.py`) moves my field accuracy from 251/252 to **252/252**. The parse-fixed starter moves the same way. Routing doesn't change, because the duplicate check uses the normalised number `SIS26270018` either way.
- **dev_014 (CloudNimbus, USD).** The label is review, `foreign_currency`, 2 approvals. That is right under policy 4.1, and my pipeline matches it. But the document says "the card on file will be charged automatically on the due date". Approving it creates a payment instruction for a bill that is already being paid. The label can't express that, and there is no review code for it. I'd propose a policy rule: auto-debit invoices are reconciled, never approved for payment. Under this eval it changes no numbers.
- **Considered and agreed:**
  - dev_016: Malwa reuses `0007` from FY 2025-26. Numbering restarts each FY, and the policy keys duplicates by FY.
  - dev_023: Vardhan's ₹84,960 equals a paid March invoice. It is a different number, and plausible as recurring freight.
  - dev_017: exactly ₹5,00,000.00 needs 2 approvals, because the threshold is "or more".
  - Supplier-name casing (`SITARA …` printed vs `Sitara …` in the label): `run_eval.py` already lower-cases names, so this costs nothing.

## Failure analysis

**Starter.** All three of its failures are in code and design, not in the model's reading:

- **Parsing (code):** 24/24 documents lost, because the replies arrive fenced or after prose. This alone explains the "AP team says numbers are wrong sometimes" and the October bill.
- **Rules given to the wrong component (design):** both missed reviews are duplicates. The model is never shown `paid_invoices.csv`, and it sees each document alone, so it *cannot* catch dev_015 (already paid) or dev_019 (a resend within the batch). No prompt fixes that. Opus says so itself in the recorded replies, and still returns `requires_review: false`. For dev_019 it wrote: "the rest of the batch were not provided, so I could not run the duplicate check … I have not raised the duplicate code because the policy requires a confirmed match". The verification pass can't fix this either, because it gets the same inputs.
- **Rules in code:** the approvals rule is `> 500000` instead of `>=`, and has no rule for credit notes (0) or foreign currency (2).

**Mine.** There are no routing errors on dev in 3 runs. These are the things most likely to cause the first one:

| Risk | Cause | What guards it now | Evidence |
|---|---|---|---|
| A grounded but wrong value: the model picks a real number from the page, but the wrong one (the buyer's GSTIN, a second account number) | model | rule checks run on the extracted value, and the grounding check only proves the value is on the page | 0 field errors in 3 × 21 unseen documents |
| A reply wrapped in a fence or prose | model | tolerant JSON parse, and `processing_error` if it still fails | 16–20 of 24 replies fenced in every run; 0 failures |
| Cost creep on long documents | model and data | none yet; needs an alarm | ₹1.46–1.49 on 1.3k-token documents |
| Stale payment history, so a duplicate is missed | data | none in Ledgerline; it depends on `--reference` being current | n/a |
| An account number printed with spaces is sent to the provider unmasked | normalisation | none (known gap, FINDINGS F6) | not in the data |

## How much to trust these numbers

- **The sample is small.** There are 13 documents that need review. Zero misses in 13 still allows a true miss rate of up to **20.6%** (95% one-sided Clopper-Pearson; `score.py` computes it). Repeating runs doesn't shrink that, because the same 13 documents are re-tested. That is why the scorer bounds the rate on one run's documents, not on 39 trials.
- **Why I trust my version more than that bound suggests:** routing is deterministic code, separately tested to reproduce all 24 labels from a perfect extraction (`test_routing.py`). So a miss needs an extraction error that is both grounded and flips a rule toward ready. Across 3 runs I saw 0 such errors in 756 field readings of unseen documents. Those runs re-read the same documents, though, so this is an argument, not a measurement. Production auditing (below) is the measurement.
- **Variation between runs:**
  - Routing was identical in all 3 runs.
  - Output tokens varied 571–587 per document, cost ₹1.46–1.49, and p95 6.7–7.4 s.
  - The starter was measured once, and its verification pass on only 5 documents, so its full-design cost and latency are extrapolated from those 5.
- **What the dev set doesn't cover:**
  - the production mix (it is 54% problem documents; production is 13%);
  - multi-page or badly scanned OCR;
  - more than one US vendor;
  - credit notes that reference an invoice;
  - concurrency (runs were sequential from one machine, though even the month-end peak of 400 a day is about 17 an hour);
  - reference data other than the May snapshot.

## My recommendation

**Yes, with conditions.** Put every invoice through Ledgerline next month as the system that reads, checks and routes it. Keep a human approval on every invoice, as policy 4.3 requires. Do not turn on straight-through processing yet.

**How the two errors are weighed.** At 3,000 documents a month, about 390 genuinely need review: that is ₹33,000 of AP time Meridian spends whatever system it uses. Then compare the error prices:

- one missed duplicate at the median invoice is ₹41,036, which is **about 480 unnecessary reviews**;
- one bank-change fraud like last quarter's is ₹3.8 lakh, which is **about 4,470**.

So any rule that catches one real problem for fewer than about 480 false alarms pays for itself. For example, `LINE_ARITHMETIC` fired on 1 document in 30, and caught real overbilling. The Finance Controller's limit still applies, though: review delays cost MSME interest, so the target is a review rate near the genuine 13%, not 50%.

| Per month, 3,000 documents | Starter (parse fixed) | Mine |
|---|---|---|
| Missed reviews | every duplicate resubmission: about 30 a month if 1% of documents are resends, so about **₹12 lakh** resting on an approver noticing (FINDINGS F1) | 0 observed; the dev set can only bound it below 20.6%. Production audit below. |
| Unnecessary reviews | 0/11 observed | 0/11 observed. Each 1% of clean documents is 26 reviews, or ₹2,200. |
| LLM cost | about ₹42,000 | ₹4,430 |
| p95 latency | about 45–50 s (target 10 s) | 7.3 s |

**Conditions:**

1. **Audit what it calls ready.** Each week, AP re-checks 50 randomly chosen *ready* documents, about ₹4,250 of time. After four weeks that is 200 documents. If none of them needed review, then with 95% confidence fewer than 1.5% of ready documents are missed reviews. That is measured on Meridian's real mix, which the dev set can't give.
2. **Shadow the first five working days.** The current manual process runs alongside, and any disagreement is root-caused before the next batch.
3. **Cost and latency alarms.** Alert if the daily average exceeds ₹1.40 per document or p95 exceeds 8 s. Opus clears the ₹1.50 ceiling by only 2 paise. Before the month starts, re-run this eval 3 times on `claude-sonnet-5-5` (about $0.50). If it again routes 24/24 and 6/6, run on Sonnet at about ₹0.54. That's Part 4B.
4. **Settle the two-person rule until there is real sign-in.** `user_id` is still client-supplied (FINDINGS, found but not fixed). Until SSO, second approvals for ≥ ₹5 lakh and foreign-currency invoices should be confirmed outside Ledgerline.
5. **Treasury reconciles the existing duplicate payment rows** before the one-payment index is switched on.
6. **Keep the reference data current.** The nightly `--reference` export of `paid_invoices.csv` is part of the control. A stale export lets a duplicate through.

**What would change my mind:**

- **To "no" or "pause":**
  - any audited ready document that needed review;
  - any hostile document routed ready;
  - an overall review rate above about 20%, which would make the MSME delay Sunil warned about real;
  - a week averaging over ₹1.50 per document, or p95 over 10 s.
- **Toward straight-through processing for clean invoices under ₹10,000** (the CFO's ask, about 1,040 clean documents and ₹88,000 of AP time a month): four weeks of audit with zero misses in that segment, real authentication, and a Finance Controller decision to amend policy 4.3. It is a policy change, so it belongs behind a flag. I won't propose it on 24 documents.
