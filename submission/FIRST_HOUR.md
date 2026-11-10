# My first hour

## What I think is going on

The main issue is that `pipeline.py` just accepts whatever `requires_review` value the model returns, while `validation.py` only raises warnings. There’s no actual safeguard in the code to prevent the LLM from making a wrong decision.

I also do not think that simply re-enabling the deterministic checks will solve the problem, because those checks have issues of their own. Status codes are compared as strings in one place and integers in another, the GSTIN checksum is not validated at all, and vendors are matched by name instead of using a stable / Unique ID.

I am also not convinced the reported 94% accuracy tells us much. It seems to measure field-level extraction accuracy rather than whether documents are routed correctly. Then the development examples are already included in the prompt, and documents that fail are excluded from scoring. So the number is likely giving us a much better picture than reality.

So, extracting fields correctly isn’t enough. What really matters is whether the system makes the right routing decision, and the current metric does not tell us that.

## The risks I suspect, most serious first

1. A document can approve itself. - `dev_012` contains text telling the model to skip review. Since the model owns the routing decision, that instruction can actually work.
2. We could pay the same invoice twice. - Once an invoice is over the threshold, every click on Approve inserts a new payment row. On top of that, duplicate detection ignores GSTIN, does not normalise invoice numbers, and does not consider the financial year.
3. Bank-change fraud can slip through. - The only thing compared is the IFSC code. I suspect `dev_005` crashes when it parses "1.2 lakh", and the batch skips it without saying anything.
4. Documents disappear. - When something fails, the document is dropped from the batch. It should be kept and marked `processing_error`.
5. Bank account numbers go to the LLM. - Both the vendor master and the document itself are sent, which goes against Section 5.
6. The cost numbers are off. - The pricing constants looks too low. Going by real usage, we are spending more than our target which is ₹1.50.

## My plan for the time I have

First, I will run the starter once on a LLM so I have real evidence instead of guesses. After that, the biggest change is moving the routing decision into code. The LLM should only extract fields. It can add review reasons, but it should never be able to remove one. Then I will fix each broken check, writing a failing test for it first. I will make the Approve operation reliable and develop an evaluation that assesses routing accuracy in addition to extraction.

For Part 4 I am choosing option B, because cost is what is actually blocking rollout. I am deliberately skipping UI polish and fine-tuning.

## What I would ask Meridian

- Is automatic approval strictly prohibited, or could we allow it for clean invoices below ₹10,000?
- If the invoice date is later than the date it was received, which date should take precedence?
