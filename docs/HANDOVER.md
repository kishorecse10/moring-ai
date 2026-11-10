# Handover notes: Ledgerline v0.3

_From Ravi Kulkarni (contractor), 30 October 2026_

Hi! Here's where things stand.

**Accuracy.** 94.2% field accuracy on the dev set (`python eval/run_eval.py`). Pretty happy with that.

**What changed in v0.3**

- I moved the policy checks into the prompt. The model reads `AP_POLICY.md` and returns `requires_review` and `review_reasons` itself, so nobody has to update rule code whenever Finance changes the policy. `validation.py` still runs, but only as warnings in the UI.
- I added a verification pass in which the model double-checks its own output. That bumped accuracy by about 2 points.
- The vendor master goes into the prompt, so the model matches vendors itself. It copes with name variations better than code does.
- The default model is now `claude-opus-5-5`, for the best accuracy.

**Cost.** Tracked per call in `llm_calls`. The dashboard (`/api/stats`) shows we're well under a rupee per invoice, so no worries there.

**Tests.** All green. It could do with a few more date tests.

**Known issues.** None really. The AP team sometimes says the Approve button is slow.

**Not done.** Reviewers asked to "see where each number came from". I didn't get to it.

Good luck!
