VENV := backend/.venv
PYTHON ?= python3

.PHONY: setup test api ui dev predict eval

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

eval:
	cd backend && .venv/bin/python eval/run_eval.py
