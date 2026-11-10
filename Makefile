VENV := backend/.venv
PYTHON ?= python3

.PHONY: setup test api ui dev predict predict-flags eval eval-live eval-score

setup:
	$(PYTHON) -m venv backend/.venv
	$(VENV)/bin/pip install -e "./backend[dev]"
	cd frontend && npm install

test:
	cd backend && .venv/bin/pytest -q

api:
	cd backend && .venv/bin/uvicorn ledgerline.api:app --reload --port 8000

ui:
	cd frontend && npm run dev

dev:
	$(MAKE) -j2 api ui

predict:
	cd backend && .venv/bin/python -m ledgerline.cli predict --input ../data/invoices/dev --reference ../data/reference --output ../submission/predictions_dev.jsonl
	cd backend && .venv/bin/python -m ledgerline.cli predict --input ../data/invoices/disputed --reference ../data/reference --output ../submission/predictions_disputed.jsonl

# Part 2 rulings: the same batch with every LEDGERLINE_FLAG_* switched on (see submission/RULINGS.md).
FLAGS_ON := LEDGERLINE_FLAG_LINE_ARITHMETIC=1 LEDGERLINE_FLAG_DATE_AFTER_RECEIPT=1 LEDGERLINE_FLAG_NARROW_SUSPICIOUS=1

predict-flags:
	$(MAKE) predict $(FLAGS_ON)

eval:
	cd backend && .venv/bin/python eval/run_eval.py

# Part 3 (submission/EVAL_REPORT.md). eval-live makes REAL, billed LLM calls with the model in .env; eval-score is offline.
RUNS := ../submission/eval_runs
STARTER_TREE ?= $(CURDIR)/.eval-starter-tree

eval-live:
	rm -rf $(STARTER_TREE) && mkdir -p $(STARTER_TREE) && git archive e2f4ac2 backend data docs | tar -x -C $(STARTER_TREE)
	cd backend && .venv/bin/python eval/run_live.py --code-root $(STARTER_TREE)/backend --input ../data/invoices/dev --out $(RUNS)/starter_opus_dev_recorded
	cd backend && for r in 1 2 3; do .venv/bin/python eval/run_live.py --code-root . --input ../data/invoices/dev --out $(RUNS)/mine_opus_dev_r$$r; done
	cd backend && $(FLAGS_ON) .venv/bin/python eval/run_live.py --code-root . --input ../data/invoices/disputed --out $(RUNS)/mine_opus_disputed_flags

# Offline: rebuild the starter's two views from its recorded replies, then score everything.
eval-score:
	rm -rf $(STARTER_TREE) && mkdir -p $(STARTER_TREE) && git archive e2f4ac2 backend data docs | tar -x -C $(STARTER_TREE)
	cd backend && .venv/bin/python eval/run_live.py --code-root $(STARTER_TREE)/backend --input ../data/invoices/dev \
		--out $(RUNS)/starter_opus_dev_as_shipped --replay $(RUNS)/starter_opus_dev_recorded/calls.jsonl > /dev/null
	cd backend && .venv/bin/python eval/run_live.py --code-root $(STARTER_TREE)/backend --input ../data/invoices/dev \
		--out $(RUNS)/starter_opus_dev_parsed --replay $(RUNS)/starter_opus_dev_recorded/calls.jsonl --strip-fences > /dev/null
	cd backend && .venv/bin/python eval/score.py starter_as_shipped=$(RUNS)/starter_opus_dev_as_shipped \
		starter_parsed=$(RUNS)/starter_opus_dev_parsed \
		mine#1=$(RUNS)/mine_opus_dev_r1 mine#2=$(RUNS)/mine_opus_dev_r2 mine#3=$(RUNS)/mine_opus_dev_r3 \
		--json $(RUNS)/scores.json
