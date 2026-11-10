# Ledgerline: the Moring AI engineer challenge

Thanks for taking this on. This is the take-home for the **AI Engineer (full-stack)** role at Moring AI. It is modeled on work we do every week: taking an LLM workflow that "mostly works" and making it something a regulated enterprise can trust in production.

| | |
|---|---|
| **Time** | Plan for about 6 focused hours. Please stop at 8. Your deadline is in your invite email, usually 7 days away. |
| **AI tools** | Expected. Use Claude Code, Cursor, Copilot, ChatGPT: whatever you would use at work. |
| **Domain knowledge** | None needed to start. Learning it quickly is part of the job. Every written business rule is in [`docs/AP_POLICY.md`](docs/AP_POLICY.md). |
| **Stack** | Python 3.11+ (FastAPI, SQLite) and React with TypeScript (Vite). |

> **There is no single right answer.** Two strong engineers could hand in very different submissions. Where something is ambiguous, make a reasonable call and write down why.
>
> **Nobody finishes everything.** There is more here than 6 hours of work, on purpose. Choose what matters most, and say what you left out.

## How to submit

1. **Create your own repository from this one.** Sign in to GitHub, click the green **Use this template** button at the top of this page, then **Create a new repository**. Pick your own account as the owner, give it any name, and set it to **Public**. Please don't fork this repository.
2. **Do all your work in your new repository.** Clone it, work through the tasks below, and commit and push as you go.
3. **Send us your repository before your deadline.** Reply to your invite email with:
   - the link to your repository, for example `https://github.com/your-username/ledgerline`;
   - the ID of your final commit, which `git rev-parse HEAD` prints.

That commit is your submission, so don't push anything after you've sent it, and keep the repository public until you hear back from us. This repository is read-only: please don't open issues or pull requests here.

## The situation

Meridian Precision Components (fictional) is an auto-components manufacturer near Pune and a Moring client. Its accounts-payable (AP) team handles about 3,000 vendor documents a month: OCR text from scanned invoices, invoices typed into emails, and government e-invoice JSON.

Earlier this year a contractor built **Ledgerline**. It reads each document with an LLM, checks it against Meridian's AP policy, and routes it to *ready for approval* or *needs review*. He left at the end of October. Since then:

- the AP team says "the numbers are wrong sometimes", and one invoice was nearly paid twice;
- the CTO's LLM bill doesn't match Ledgerline's own cost dashboard;
- the handover note says accuracy is 94%.

Meridian wants Ledgerline handling every invoice next month. You have just inherited it.

## How we want you to work

Your AI tools can write most of the code in this repository. They can't decide what matters to a company that moves money through it, and they can't be accountable when a payment goes to a fraudster. That part is yours.

So use AI as much as you like, but make the decisions yourself, write them down in your own words, and be ready to explain each one. Where the code, the tests and the docs disagree, decide which to trust and say why. `docs/AP_POLICY.md` is the written policy and your default, but the people who own it are in [`docs/STAKEHOLDER_THREAD.md`](docs/STAKEHOLDER_THREAD.md), and they don't all agree with it. Where you think the policy is wrong, say so, and put any departure from it behind a flag (see Part 2).

## Your tasks

Every part is required in the sense that you must address it, even if only in a few honest lines. How deep you go in each one is your call. We would rather see two parts done properly and the rest addressed briefly and honestly than all seven done thinly. Say in `REFLECTION.md` what you cut, and why.

### Part 0: Your first hour (required, 30 to 45 minutes)

Before you change any code, read around and write [`submission/FIRST_HOUR.md`](submission/FIRST_HOUR.md): what you think is going on, the risks you suspect (most serious first), your plan for the time you have, and the questions you would ask Meridian.

Keep it under about 300 words. Commit it on its own, before any commit that touches `backend/` or `frontend/` (context files for your AI tools and your `.env` don't count), and **don't edit it afterwards**. Save the AI sessions from this stretch as their own file in `submission/ai-logs/`, with a name starting `00_first_hour`. It's fine if the note turns out to be wrong.

### Part 1: Make it trustworthy (required)

As it stands, Ledgerline should not be handling every invoice next month. Decide what "trustworthy" has to mean for Meridian, find out what stands in the way, and fix what you judge most important first. We won't tell you how many problems there are or which ones matter.

- Every fix gets a test that fails before the fix and passes after it. For a prompt or model-behaviour change, use a recorded model response as a test fixture, or show the change in your eval on named documents. For a UI fix, a test or a written manual check is fine.
- In [`submission/FINDINGS.md`](submission/FINDINGS.md), rank your top eight findings by business risk, in your own judgment, and explain the order. List the rest as one-liners. Include what you found but chose not to fix, and at least one thing you're not sure is a problem at all.
- For your top three, show evidence from your own run of the starter (the document, and what the starter actually produced for it) and estimate what the problem could cost Meridian in rupees.
- Prefer root causes to symptoms, and small, focused changes to rewrites.

### Part 2: Rule on the disputed documents (required)

[`data/invoices/disputed/`](data/invoices/disputed/) holds six documents that Meridian's own AP team argues about. They have no labels, and we don't have a right answer for them either. In [`submission/RULINGS.md`](submission/RULINGS.md), in about 150 words per document, give:

- your ruling: needs review or ready, with which reasons and how many approvals;
- the policy text your ruling rests on, or the gap in the policy it falls into;
- the strongest argument against your ruling, put as well as you can;
- the policy change you'd propose to the Finance Controller, if any;
- whether your own pipeline's line for it in `predictions_disputed.jsonl` matches your ruling, and if not, why.

Then make Ledgerline behave the way you ruled, at least for the two documents you consider riskiest, with tests.

Don't quietly change `AP_POLICY.md`. Where a ruling departs from the written policy, put the change behind a clearly named flag that is off by default and switched on with an environment variable (for example `LEDGERLINE_FLAG_<NAME>=1`). New review-reason codes are allowed only behind a flag. List your flags at the top of `RULINGS.md`, and produce `predictions_disputed.jsonl` with them switched on.

### Part 3: Measure, and make a call (required)

Build an evaluation you would be willing to defend to Meridian's CFO, and use it to make a recommendation in [`submission/EVAL_REPORT.md`](submission/EVAL_REPORT.md).

- Decide what to measure and why. At the very least we expect: how often a document that needed review was routed as ready; cost per document (₹) and latency (p50 and p95), measured from real calls; and the starter's numbers next to yours, on the same model. The rest is up to you.
- Explain what the handover note's "94%" actually measured. Reproduce the starter's number on your model, then re-score the starter with its leaked examples removed and failed documents counted as failures.
- The dev labels in `data/ground_truth/dev.jsonl` follow the written policy literally. If you disagree with any of them, say which and why, and show how it changes your numbers.
- The dev and disputed sets are deliberately rich in problem cases. For anything about Meridian's real volumes, use the production mix in [`docs/PRODUCT_BRIEF.md`](docs/PRODUCT_BRIEF.md).
- End with a recommendation: should Meridian put every invoice through Ledgerline next month? Yes, no, or yes with conditions. Say what evidence would change your mind. A missed review can mean paying a fraudster; an unnecessary review costs about ₹85 of AP time (see the CFO's email) and can delay a vendor's payment. Show how your recommendation weighs the two.

### Part 4: Go deep on one thing (required: choose one)

Choose one, and say in [`submission/DECISIONS.md`](submission/DECISIONS.md) why you chose it over the others.

- **A. Evidence-linked review.** Reviewers don't trust numbers they can't trace, so they re-key invoices by hand. Build the reviewer experience: for every extracted field, its exact source in the original document (character offsets plus the text; when you're not sure, say so rather than highlight the wrong text); a queue of documents that need attention; each review reason in plain language with the evidence behind it; and approve and reject actions that enforce the policy's approval rules **on the server** and stay correct under double-clicks and retries. It needs to work for a reviewer who clears 150 invoices a day.
- **B. Survive production.** Find the cheapest model that is good enough, escalate when validation fails, and keep working through a provider outage, within the CTO's budget. Show the cost and quality trade-off with numbers.
- **C. Your own idea.** Anything you can argue matters more to Meridian next month than A or B.

Whichever you choose, treat every document as hostile. Some in the dev set are.

### Part 5: Respond to stakeholders (required, written)

Read [`docs/STAKEHOLDER_THREAD.md`](docs/STAKEHOLDER_THREAD.md). In `submission/DECISIONS.md`, reply to each person in no more than about 120 words: what you did, what you won't do yet, and why. Use your own numbers where they help. Some requests conflict with each other or with the written policy, and at least one person argues against the approach you are most likely to take. Give that argument a real answer. Don't quietly change the policy; propose changes instead.

### Part 6: Reflect (required, about 20 minutes)

In [`submission/REFLECTION.md`](submission/REFLECTION.md): three things you didn't know when you started and do now, and how you learned each one; the decision you're least sure of, and what would show you it was wrong; and what you'd do with one more week, in order.

## Ground rules

- **AI tools are expected.** Save your sessions in `submission/ai-logs/` (Claude Code: `/export`; Cursor: export the chat; chat apps: share links or copied text). Redact secrets. Commit any context files you write for your tools, such as `CLAUDE.md`, `AGENTS.md` or rules files.
- **Commit as you go**, with real commit messages. `FIRST_HOUR.md` must be committed before your first code change.
- **Write the documents yourself.** Use AI to check your thinking, but `FIRST_HOUR.md`, `RULINGS.md`, `REFLECTION.md` and the stakeholder replies in `DECISIONS.md` must be in your own words. AI drafting is fine for the rest.
- **Use any LLM provider.** Anthropic, OpenAI, Gemini, Groq, OpenRouter and local models through Ollama all work (see `.env.example`). Tell us which you used. If API costs are a problem, ask us for a capped key.
- **Unit tests must pass without network access or API keys.** Use the fake client.
- **Keep the stack**: a Python backend and a React with TypeScript frontend. Within it, add any libraries you like and tell us why.
- **Keep the batch command in [`docs/OUTPUT_CONTRACT.md`](docs/OUTPUT_CONTRACT.md) working.** It must also work on documents and reference data other than the ones in this repository.
- **Questions:** email careers@moring.ai with "Ledgerline" in the subject. We reply within one working day. If something is ambiguous, a written, reasonable assumption is a perfectly good answer, and often a better one than a question.

## What your final commit should contain

1. Your code changes, with an updated **Running my version** section at the end of this file if setup changed.
2. In `submission/`: `FIRST_HOUR.md`, `FINDINGS.md`, `RULINGS.md`, `EVAL_REPORT.md`, `DECISIONS.md`, `REFLECTION.md` and `AI_USAGE.md`.
3. `submission/ai-logs/`, containing your AI session transcripts.
4. `submission/predictions_dev.jsonl` and `submission/predictions_disputed.jsonl` from your final pipeline (`make predict`).

## Setup

You need Python 3.11+, Node 20+ and `make`. On Windows, use WSL. If your `python3` is older than 3.11, run `make setup PYTHON=python3.12` (or whichever newer version you have). Clone your own repository (see "How to submit"), then, in it:

```bash
cp .env.example .env      # choose a provider and model
make setup                # Python virtualenv and npm install
make test                 # starter tests (offline)
make dev                  # API on :8000, UI on http://localhost:5173
make predict              # writes submission/predictions_dev.jsonl and predictions_disputed.jsonl
make eval                 # the starter's eval script
```

`LLM_PROVIDER=fake` lets you click around the UI without a key. It returns the same canned extraction for every document.

**Watch your spend.** The starter is expensive to run. Set a spending limit with your provider before you run it over all the documents.

## What's in the repository

```
docs/
  AP_POLICY.md            the written business rules (version 3.2)
  OUTPUT_CONTRACT.md      the batch command and predictions format
  PRODUCT_BRIEF.md        users, volumes and workflow
  ARCHITECTURE.md         the original design doc (March 2026)
  HANDOVER.md             the contractor's handover note (October 2026)
  STAKEHOLDER_THREAD.md   emails you need to respond to
data/
  invoices/dev/           24 labeled documents (.txt OCR text, .eml email, .json e-invoice)
  invoices/disputed/      6 unlabeled documents the AP team argues about
  ground_truth/dev.jsonl  labels for the dev set, following the written policy literally
  reference/              buyer.json, vendors.csv, paid_invoices.csv
backend/                  FastAPI app, pipeline, CLI, eval script and tests
frontend/                 React review UI (Vite)
submission/               templates for your write-ups
```

## FAQ

**Can I rewrite it from scratch?** You can, but working in an existing codebase is the job. If you rewrite, show that you kept everything the business relies on, and explain why a rewrite beat fixing.

**Can I use a local model?** Yes. Report its quality honestly, next to whatever you would recommend for production.

**What if I run out of time?** Stop, and tell us what you would do next and why.

**How long should I spend?** About 6 hours, and please stop at 8. Tell us roughly how long you took in `AI_USAGE.md`.

**Is the data real?** No. Every company, GSTIN and bank account in this repository is fictional.

## Running my version

_Describe anything that changed about setup or commands._
