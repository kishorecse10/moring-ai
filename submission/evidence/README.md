# Evidence

Reproductions of the starter (v0.3, commit `e2f4ac2`, unmodified) behind the top three findings in `FINDINGS.md`,
plus the test and eval output of my version. Everything here runs **offline, with no billed LLM calls**:

```bash
make evidence      # regenerates every file below except eval_score.txt
make eval-score    # eval_score.txt is its output
```

The starter's LLM client is swapped for one that serves the real `claude-sonnet-5-5` replies recorded from the
starter on 2026-11-10 (`backend/tests/fixtures/starter_sonnet55_replies.json`). The starter's code is otherwise run
as shipped. See `reproduce_starter.py`.

| File | Finding | What it shows |
|---|---|---|
| `f1_routing_summary.txt`, `f1_routing_on_recorded_replies.jsonl` | F1: the model decides routing | With the ```` ```json ```` fence stripped (so the starter can parse at all), its model-decided routing sends the two real duplicates **dev_015** (`SIS / 26-27 / 0018`, already in `paid_invoices.csv`) and **dev_019** (resend of dev_006) to *ready*, with no reasons. The other 22 dev documents match their labels. |
| `f2_approve_api.txt` | F2: approve is not idempotent | Against the starter's API: three approves of dev_001 by the same user make **3 payments of ₹23,458**; one approve of the dev_007 credit note makes **a ₹11,446 payment**; `GET /api/invoices/1` with `X-Org-Id: acme` returns **200** with Meridian's invoice. |
| `f3_batch_as_shipped.txt`, `f3_batch_as_shipped_{dev,disputed}.jsonl` | F3: the batch drops documents | The starter's own `cli predict`: `wrote 0/24` and `wrote 0/6`, every document `[skip] … Expecting value`, and empty output files. 30 of 30 recorded replies start with a fence. |
| `tests_mine.txt` | all | `pytest -v` on my version: 144 passed, offline, with the fake client. |
| `eval_score.txt` | Part 3 | `make eval-score` output over the recorded Opus runs in `eval_runs/`. |

Caveats:

- The starter's second (verification) pass was never recorded, because on the real run the first `json.loads`
  crashed. In the F1 replay it returns the first reply unchanged. The F1 result is therefore "the first pass routed
  the duplicates as ready", not a measurement of the verify pass.
- In F2 the uploads are extracted from the same recorded replies. FINDINGS.md's original reproduction used the fake
  client, and the result is the same.
