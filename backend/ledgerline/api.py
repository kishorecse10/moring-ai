"""HTTP API used by the reviewer UI.  Run: uvicorn ledgerline.api:app --reload"""
from __future__ import annotations

from fastapi import Depends, FastAPI, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import db
from .config import USD_TO_INR, get_settings
from .pipeline import process_document
from .reference import load_reference

app = FastAPI(title="Ledgerline API", version="0.3.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def get_conn():
    conn = db.connect(get_settings().db_path)
    try:
        yield conn
    finally:
        conn.close()


def get_org(x_org_id: str = Header(default="meridian")) -> str:
    return x_org_id


class DecisionRequest(BaseModel):
    user_id: str
    note: str = ""


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.post("/api/invoices")
async def upload_invoice(file: UploadFile, org_id: str = Depends(get_org), conn=Depends(get_conn)):
    # errors="replace": a badly encoded upload is still stored and routed to review, not a 500.
    raw_text = (await file.read()).decode("utf-8", errors="replace")
    document_id = (file.filename or "upload").rsplit(".", 1)[0]
    return process_document(conn, load_reference(), raw_text, document_id, org_id=org_id, filename=file.filename)


@app.get("/api/invoices")
def list_invoices(org_id: str = Depends(get_org), conn=Depends(get_conn)):
    rows = conn.execute(
        "SELECT id, document_id, supplier_name, invoice_number, invoice_date, currency, total, status, "
        "needs_review FROM invoices WHERE org_id = ? ORDER BY id DESC",
        (org_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _invoice_for_org(conn, invoice_id: int, org_id: str) -> dict:
    invoice = db.get_invoice(conn, invoice_id)
    if invoice is None or invoice["org_id"] != org_id:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return invoice


@app.get("/api/invoices/{invoice_id}")
def get_invoice(invoice_id: int, org_id: str = Depends(get_org), conn=Depends(get_conn)):
    return _invoice_for_org(conn, invoice_id, org_id)


def _approval_count(conn, invoice_id: int) -> int:
    return conn.execute("SELECT COUNT(DISTINCT user_id) FROM approvals WHERE invoice_id = ?",
                        (invoice_id,)).fetchone()[0]


@app.post("/api/invoices/{invoice_id}/approve")
def approve_invoice(invoice_id: int, body: DecisionRequest, org_id: str = Depends(get_org), conn=Depends(get_conn)):
    """AP_POLICY.md section 4, enforced here rather than in the UI.

    Safe under double-clicks and retries: the whole decision runs in one write transaction, the same person
    approving twice counts once, and an invoice that is already approved gets no second payment instruction.
    """
    user_id = body.user_id.strip()
    if not user_id:
        raise HTTPException(status_code=422, detail="user_id is required")
    conn.execute("BEGIN IMMEDIATE")
    try:
        invoice = _invoice_for_org(conn, invoice_id, org_id)
        reasons = invoice["review_reasons"]
        if invoice["status"] == "approved":
            # A retry or a double-click on an approved invoice: report the state, change nothing.
            conn.execute("ROLLBACK")
            return {"id": invoice_id, "approvals": _approval_count(conn, invoice_id),
                    "required_approvals": invoice["required_approvals"], "status": "approved"}
        if invoice["status"] == "rejected":
            raise HTTPException(status_code=409, detail="This document was rejected and can't be approved.")
        if invoice["document_type"] != "invoice" or invoice["required_approvals"] < 1:
            raise HTTPException(status_code=409, detail="Credit notes can't be approved for payment (policy 4.1).")
        if "duplicate" in reasons:
            raise HTTPException(status_code=409, detail="Duplicate invoices can't be approved, only rejected (policy 4.4).")
        if invoice["needs_review"] and not body.note.strip():
            raise HTTPException(status_code=422, detail="A note is required to approve a document that needed review (policy 4.5).")
        inserted = conn.execute(
            "INSERT OR IGNORE INTO approvals (invoice_id, user_id, note) VALUES (?, ?, ?)",
            (invoice_id, user_id, body.note),
        ).rowcount
        if inserted:
            conn.execute("INSERT INTO audit_log (invoice_id, action, user_id, note) VALUES (?, 'approve', ?, ?)",
                         (invoice_id, user_id, body.note))
        approvals = _approval_count(conn, invoice_id)
        status = invoice["status"]
        if approvals >= invoice["required_approvals"]:
            status = "approved"
            conn.execute("UPDATE invoices SET status = 'approved' WHERE id = ?", (invoice_id,))
            # Exactly one payment instruction (policy 4.6); the unique index backs this up.
            conn.execute("INSERT OR IGNORE INTO payments (invoice_id, amount) VALUES (?, ?)",
                         (invoice_id, invoice["total"]))
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    return {"id": invoice_id, "approvals": approvals, "required_approvals": invoice["required_approvals"],
            "status": status}


@app.post("/api/invoices/{invoice_id}/reject")
def reject_invoice(invoice_id: int, body: DecisionRequest, org_id: str = Depends(get_org), conn=Depends(get_conn)):
    user_id = body.user_id.strip()
    if not user_id:
        raise HTTPException(status_code=422, detail="user_id is required")
    conn.execute("BEGIN IMMEDIATE")
    try:
        invoice = _invoice_for_org(conn, invoice_id, org_id)
        if invoice["status"] == "approved":
            raise HTTPException(status_code=409, detail="This invoice is already approved and has a payment instruction.")
        if invoice["status"] != "rejected":
            conn.execute("UPDATE invoices SET status = 'rejected' WHERE id = ?", (invoice_id,))
            conn.execute("INSERT INTO audit_log (invoice_id, action, user_id, note) VALUES (?, 'reject', ?, ?)",
                         (invoice_id, user_id, body.note))
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    return {"id": invoice_id, "status": "rejected"}


@app.get("/api/stats")
def stats(org_id: str = Depends(get_org), conn=Depends(get_conn)):
    """Feeds the cost dashboard. Calls to a model with no known price are counted, not treated as free."""
    row = conn.execute(
        "SELECT COUNT(DISTINCT i.id) AS invoices, COALESCE(SUM(c.cost_usd), 0) AS cost_usd, "
        "COUNT(c.id) AS calls, COALESCE(SUM(CASE WHEN c.id IS NOT NULL AND c.cost_usd IS NULL THEN 1 ELSE 0 END), 0) "
        "AS unpriced FROM invoices i LEFT JOIN llm_calls c ON c.invoice_id = i.id WHERE i.org_id = ?",
        (org_id,),
    ).fetchone()
    total_inr = row["cost_usd"] * USD_TO_INR
    return {
        "invoices_processed": row["invoices"],
        "llm_calls": row["calls"],
        "unpriced_llm_calls": row["unpriced"],
        "llm_cost_inr": round(total_inr, 2),
        "avg_llm_cost_per_invoice_inr": round(total_inr / row["invoices"], 4) if row["invoices"] else 0.0,
    }
