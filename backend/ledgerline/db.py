"""SQLite persistence."""
from __future__ import annotations

import json
import logging
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
    evidence_json TEXT,
    explanations_json TEXT,
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
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER NOT NULL REFERENCES invoices(id),
    action TEXT NOT NULL,
    user_id TEXT NOT NULL,
    note TEXT,
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


# Policy 4.2 and 4.6, enforced by the database as well as the API: one approval per person per invoice, and
# exactly one payment instruction per invoice, however many times Approve is clicked or retried.
UNIQUE_INDEXES = [
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_payments_invoice ON payments(invoice_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_approvals_invoice_user ON approvals(invoice_id, user_id)",
]


# Columns added after v0.3. CREATE TABLE IF NOT EXISTS doesn't touch an existing table, so add them if missing.
ADDED_COLUMNS = {"invoices": [("evidence_json", "TEXT"), ("explanations_json", "TEXT")]}


def _migrate(conn: sqlite3.Connection) -> None:
    for table, columns in ADDED_COLUMNS.items():
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        for name, kind in columns:
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")


def connect(path: str) -> sqlite3.Connection:
    # isolation_level=None: we open transactions explicitly (BEGIN IMMEDIATE) where it matters.
    conn = sqlite3.connect(path, check_same_thread=False, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate(conn)
    for statement in UNIQUE_INDEXES:
        try:
            conn.execute(statement)
        except sqlite3.IntegrityError:
            # A database written by v0.3 can already hold duplicate payments. Don't refuse to start; the API
            # still guards inside a transaction. Treasury needs to reconcile those rows (see FINDINGS.md).
            logging.getLogger(__name__).error("existing duplicates block %s; reconcile before rollout", statement)
    return conn


def get_invoice(conn: sqlite3.Connection, invoice_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
    if row is None:
        return None
    inv = dict(row)
    for col in ("line_items_json", "warnings_json", "review_reasons_json", "explanations_json"):
        inv[col.removesuffix("_json")] = json.loads(inv.pop(col, None) or "[]")
    inv["evidence"] = json.loads(inv.pop("evidence_json", None) or "{}")
    inv["needs_review"] = bool(inv["needs_review"])
    inv["approvals"] = [dict(r) for r in conn.execute(
        "SELECT user_id, note, created_at FROM approvals WHERE invoice_id = ? ORDER BY id", (invoice_id,))]
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
