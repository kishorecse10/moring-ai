# How I worked with AI

## Tools and models

- **Claude Code** (CLI) for everything: reading the codebase, writing code and tests, running the starter and the evals, and drafting the write-ups. My last session ran on Claude Opus 5.5.
- **Ledgerline's own LLM calls** went to the Anthropic API:
  - `claude-sonnet-5-5` for the Part 1 and Part 2 runs, because it was cheaper while I was still breaking things;
  - `claude-opus-5-5`, Meridian's production model, for every number in the eval report. I set the budget myself at about $5.5 for that, and asked Claude to stay inside it. It did, by replaying recorded replies instead of paying twice.
- No local models. `LLM_PROVIDER=fake` for all the unit tests.

## How I set up context

I didn't write a `CLAUDE.md` for this repo. Each session started by pointing Claude at `README.md` and naming the part I was on. My global `CLAUDE.md` only mentions the Postman CLI, which didn't matter here.

The policy, the stakeholder thread and the handover note went in by reference. I told Claude to read them, rather than pasting them. Before any code I spent one session just asking it to analyse the whole challenge.

The thing that made the most difference was keeping evidence on disk:

- the raw starter replies became test fixtures;
- every live eval run writes its calls to `submission/eval_runs/`;

so later sessions could check claims against real output instead of memory. I didn't use plan mode. Claude did stop to ask me one real question, how much API money to spend, and I answered that one.

## My workflow

I picked the part and the priority, Claude did the reading-heavy and typing-heavy work, and I checked the result against something I could run.

- **Parts 1–2:** I asked for fixes, and every fix had to come with a test that fails on the starter. Ruling on the disputed documents was my call; Claude implemented the flags.
- **Part 3:** I asked for an eval I could defend to a CFO. I chose the model and the budget. Claude built `run_live.py` and `score.py`, ran them, and wrote the report from the numbers.
- **Part 4:** Claude argued for option A over the B I had planned in my first hour, using the rollout criteria in the product brief and the Part 3 numbers.
- **Part 5:** Claude drafted the stakeholder replies from my numbers.
- **Part 6:** Claude collected notes for the reflection.

How I checked the output:

- running the tests and `make eval-score` myself;
- reading the diff before every commit (I told Claude not to commit);
- spot-checking numbers against the files in `submission/eval_runs/`;
- using the UI. That's how I found the "approved invoice stays on screen" bug below.

## Where the AI was wrong

1. **The `make eval-live` target it wrote didn't work, and I ran it anyway.**
   - *What happened:* I trusted the new Makefile target and started it while Claude's own background runs were still writing. The starter copy has no `.env`, so every starter call failed with an auth error. My run also overwrote one of Claude's result folders mid-write, cutting run 2 to 5 lines.
   - *How it was noticed:* Claude noticed when its scores changed between two reads, and traced it to my process.
   - *The fix:* the runner now loads the repo's `.env` itself. Run 2 was rebuilt from its 24 recorded replies with `--replay`, so nothing was invented and nothing paid for twice.
   - *Transcript:* Part 3 session, around the "Run 2 now shows only 2 documents" step.
2. **An overconfident statistic.**
   - *What happened:* Claude's first scorer pooled three runs as "0 misses out of 39" and projected a miss rate of at most 7.4%. Those are the same 13 documents tested three times, not 39 independent trials. The honest bound is about 21%.
   - *How it was noticed:* Claude caught this itself, before it reached the report. I'm listing it because I'd have accepted 7.4% without thinking.
   - *Transcript:* Part 3 session, the `summarise()` fix.
3. **A fix that didn't fix it.**
   - *What happened:* to measure the starter "with its parse bug fixed", Claude stripped the ```` ```json ```` fence. Opus often puts prose before the fence, so the "fixed" starter still crashed on all 24 documents, after about $2 of calls.
   - *The fix:* it widened the shim and replayed the recorded replies instead of re-running.
   - *Transcript:* Part 3 session, "My fence shim is too narrow for Opus".
4. **A test that couldn't fail.**
   - *What happened:* one evidence test compared `list.sort() == list.sort()`, which is always `None == None`.
   - *How it was noticed:* Claude spotted it while running the suite, and replaced it with a real comparison.
   - *Transcript:* Part 4 session.
5. **The approve screen didn't clear.**
   - *What happened:* after the last approval in a tab, the approved invoice stayed on screen with Approve still showing. The UI picked the "next" document from the queue as it was before the decision.
   - *How it was noticed:* I found it by using the UI, and asked for the fix (commit `473cd1f`).
   - *Transcript:* last session, the final request.
6. **Smaller ones I caught in review:**
   - `FINDINGS.md` said 15 dev documents needed review; it's 13.
   - Claude's first strict number parsing in Part 1 sent 14 of 24 documents to `processing_error` because of quantities like "750 kg" (see FINDINGS F7).
   - Its first evidence locator marked 2–4 fields per document "not sure", because of label rules like a bare "No".

## What I deliberately didn't delegate, and why

- **What counts as trustworthy for Meridian, and the order of risk.** That's the call I'd be accountable for if a fraudulent invoice got paid.
- **The rulings on the six disputed documents,** and which departures from policy go behind flags.
- **Spend and model choice.** It's real money, and the CTO's budget is part of the answer.
- **The final recommendation's conditions** (audit, shadow week, no straight-through processing yet).
- **What gets committed.** Claude never committed or pushed; I reviewed and committed each part myself.

Where I did lean on Claude for wording, I'm saying so:

- The stakeholder replies and the reflection started as Claude drafts and notes, built from my numbers.

## Time

About 7 hours:

| What | When | About |
|---|---|---|
| Reading the challenge, first-hour note | 10:00–12:29 | 2 h |
| Part 1, over three sessions | 12:30–15:35 | 3 h |
| Part 2 rulings and flags | to 15:59 | 25 min |
| Part 3 eval | 15:59–16:24 | 25 min |
| Part 4 | to 16:51 | 25 min |
| Parts 5–6 | to 16:59 | 10 min |
| Fixing the approval-screen bug | to 17:04 | 5 min |

## Transcripts