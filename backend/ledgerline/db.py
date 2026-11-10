"""SQLite persistence."""
from __future__ import annotations

import json
import sqlite3

from .config import USD_TO_INR

SCHEMA = """
CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    filename TEXT,
    raw_text TEXT NOT NULL,
    document_type TEXT,
    supplier_name TEXT,
    supplier_gstin TEXT,
    invoice_number TEXT,
    invoice_date TEXT,
    currency TEXT,
    subtotal REAL,
    cgst REAL,
    sgst REAL,
    igst REAL,
    round_off REAL,
    total REAL,
    bank_account TEXT,
    ifsc TEXT,
    po_number TEXT,
    notes TEXT,
    line_items_json TEXT,
    warnings_json TEXT,
    needs_review INTEGER NOT NULL DEFAULT 0,
    review_reasons_json TEXT,
    required_approvals INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'ready_for_approval',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER NOT NULL REFERENCES invoices(id),
    user_id TEXT NOT NULL,
    note TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER NOT NULL REFERENCES invoices(id),
    amount REAL NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS llm_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER REFERENCES invoices(id),
    document_id TEXT,
    model TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cost_usd REAL,
    latency_ms INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def get_invoice(conn: sqlite3.Connection, invoice_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
    if row is None:
        return None
    inv = dict(row)
    for col in ("line_items_json", "warnings_json", "review_reasons_json"):
        inv[col.removesuffix("_json")] = json.loads(inv.pop(col) or "[]")
    inv["needs_review"] = bool(inv["needs_review"])
    usage = conn.execute(
        "SELECT COUNT(*) AS calls, COALESCE(SUM(input_tokens), 0) AS input_tokens, "
        "COALESCE(SUM(output_tokens), 0) AS output_tokens, COALESCE(SUM(cost_usd), 0) AS cost_usd, "
        "COALESCE(SUM(latency_ms), 0) AS latency_ms FROM llm_calls WHERE invoice_id = ?",
        (invoice_id,),
    ).fetchone()
    inv["usage"] = {
        "llm_calls": usage["calls"],
        "input_tokens": usage["input_tokens"],
        "output_tokens": usage["output_tokens"],
        "cost_inr": round(usage["cost_usd"] * USD_TO_INR, 4),
        "latency_ms": usage["latency_ms"],
    }
    return inv
