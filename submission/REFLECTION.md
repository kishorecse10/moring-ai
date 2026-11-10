# Reflection

## Three things I didn't know when I started, and how I learned each one

- **Field accuracy can be nearly perfect while the system pays twice.**
  - With its parse fixed, the starter scores 99.7% on the handover's own metric and still routes both duplicates as ready.
  - In its reply the model *said* it couldn't run the duplicate check, and still returned `requires_review: false`.
  - *How I learned it:* I scored routing separately from fields (`eval/score.py`), and read the replies for dev_015 and dev_019.
  - My first-hour note guessed the 94% was flattering. I didn't expect it to be irreproducible, with a divide by zero on the shipped code.
- **Eval infrastructure needs the same care as the product.**
  - An overlapping `make eval-live` truncated one run's predictions, and my first Makefile target gave the starter tree no API key.
  - Recording raw replies made it recoverable: `--replay` rebuilt the run at no cost, with nothing invented.
- **Evidence is a judgement call, not a lookup.**
  - The first version of the source-locating code marked 2–4 fields per document as "not sure".
  - A bare `No` label claimed `A/c No.`, the `@` in "CGST @ 9%" sat nearer than "CGST", and an email's `Date:` header competed with the invoice date.
  - *How I learned it:* by printing the line each span landed on and checking by hand, not by trusting an "all exact" count.

## The decision I'm least sure of

- **Choosing Part 4 A over B, against my own first-hour plan.**
  - *What would show it's wrong:* a provider outage or cost overrun in month one, while reviewers barely use the evidence links.

## With one more week

1. **Re-run the eval three times on Sonnet**, **add the cost and latency alarms, and plan the shadow week.** It's cheap, and it settles the ₹1.50 budget question before rollout.
2. **Label Meridian's 200-document October sample and add it to the eval.** It turns the "below 21%" bound into a real production-mix number, and tests the evidence locator on real layouts.
3. **Sign-in via Meridian's identity provider.** Until then the two-person rule (policy 4.2) is only as strong as a dropdown.
4. **Close the account-masking gap** (numbers printed with spaces or dashes). That's a DPO commitment I made in writing.
5. **Browser tests for the review UI** (Playwright), including the dev_013 XSS and the duplicate-disabled checks, plus a session with two real reviewers.
6. **Resilience (Part 4B):**
   - Parse government e-invoice JSON without an LLM (10% of volume, exact, free).
   - Fall back to a second model on provider errors.
   - Escalate to Opus only when grounding fails.
7. **A red-team set for `suspicious_content`** before anyone switches `NARROW_SUSPICIOUS` on.
