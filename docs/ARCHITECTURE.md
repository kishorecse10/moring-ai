# Ledgerline architecture (v0.1 design)

_Written in March 2026, before the first release. It has not been updated since._

## Components

- **Backend** (FastAPI, `backend/ledgerline/`): upload API, extraction pipeline and reviewer endpoints.
- **Extraction** (`extraction.py`): one LLM call per document, returning structured JSON.
- **Validation** (`validation.py`): deterministic policy checks that decide routing.
- **Storage**: SQLite. All money is stored as integer paise (₹1 = 100 paise), so totals are exact.
- **Frontend** (React, `frontend/`): the review queue and approval screen.

## Key decisions

1. **The LLM only extracts; code decides.** Every policy rule lives in `validation.py`, so routing is deterministic and testable.
2. **Vendors are matched by GSTIN** against the vendor master. Names are for display only.
3. **Approvals are idempotent.** The approval endpoint uses the invoice's state, so repeated requests are safe.
4. **Costs are tracked per call** in `llm_calls`, so finance can see spend per document.

## Data flow

document → extract (LLM) → normalize → validate → route → store → review → approve → payment instruction
