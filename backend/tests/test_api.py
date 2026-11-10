import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from ledgerline.api import app
from tests.conftest import dev_text, oracle_extraction


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = str(tmp_path / "api.db")
    monkeypatch.setenv("LEDGERLINE_DB", path)
    return path


@pytest.fixture
def client(db_path, fake_llm):
    return TestClient(app)


def upload(client, document_id: str, llm_replies=None, org: str = "meridian") -> dict:
    if llm_replies is not None:
        llm_replies(oracle_extraction(document_id))
    response = client.post("/api/invoices", headers={"X-Org-Id": org},
                           files={"file": (f"{document_id}.txt", dev_text(document_id).encode(), "text/plain")})
    assert response.status_code == 200
    return response.json()


def approve(client, invoice_id, user="kavya", note="", org="meridian"):
    return client.post(f"/api/invoices/{invoice_id}/approve", headers={"X-Org-Id": org},
                       json={"user_id": user, "note": note})


def payments(db_path, invoice_id) -> int:
    with sqlite3.connect(db_path) as conn:
        return conn.execute("SELECT COUNT(*) FROM payments WHERE invoice_id = ?", (invoice_id,)).fetchone()[0]


def test_upload_list_get_approve(client):
    uploaded = client.post("/api/invoices", files={"file": ("dev_001.txt", dev_text("dev_001").encode(), "text/plain")})
    assert uploaded.status_code == 200
    invoice_id = uploaded.json()["id"]

    listed = client.get("/api/invoices").json()
    assert [row["id"] for row in listed] == [invoice_id]

    detail = client.get(f"/api/invoices/{invoice_id}").json()
    assert detail["invoice_number"] == "SIS/26-27/0042"

    approved = approve(client, invoice_id, note="ok")
    assert approved.json()["status"] == "approved"


def test_stats_counts_processed_documents(client):
    client.post("/api/invoices", files={"file": ("a.txt", b"text", "text/plain")})
    stats = client.get("/api/stats").json()
    assert stats["invoices_processed"] == 1 and stats["llm_calls"] == 1


# --- exactly one payment instruction (Kavya: "clicking Approve sometimes creates two payment entries") -------

def test_repeated_approve_creates_one_payment(client, db_path):
    invoice_id = upload(client, "dev_001")["id"]
    for _ in range(3):
        assert approve(client, invoice_id).json()["status"] == "approved"
    assert payments(db_path, invoice_id) == 1


def test_concurrent_double_click_creates_one_payment(db_path, llm_replies):
    client = TestClient(app)
    llm_replies(oracle_extraction("dev_017"))  # 5,00,000.00 -> two approvals
    invoice_id = upload(client, "dev_017")["id"]
    assert approve(client, invoice_id, user="kavya").json()["status"] == "ready_for_approval"
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: approve(client, invoice_id, user="sunil"), range(8)))
    assert {r.status_code for r in results} == {200}
    assert {r.json()["status"] for r in results} == {"approved"}
    assert payments(db_path, invoice_id) == 1


def test_same_person_approving_twice_counts_once(db_path, llm_replies):
    client = TestClient(app)
    llm_replies(oracle_extraction("dev_017"))
    invoice_id = upload(client, "dev_017")["id"]
    approve(client, invoice_id, user="kavya")
    second = approve(client, invoice_id, user="kavya").json()
    assert second["approvals"] == 1 and second["status"] == "ready_for_approval"
    assert payments(db_path, invoice_id) == 0
    assert approve(client, invoice_id, user="sunil").json()["status"] == "approved"
    assert payments(db_path, invoice_id) == 1


# --- policy section 4 on the server ----------------------------------------------------------------------------

def test_credit_note_cannot_be_approved_for_payment(db_path, llm_replies):
    """required_approvals is 0 for a credit note, so the starter's 'approvals >= required' approved it and
    created a payment instruction for a document that reduces what we owe."""
    client = TestClient(app)
    llm_replies(oracle_extraction("dev_007"))
    response = client.post("/api/invoices", files={"file": ("dev_007.json", dev_text("dev_007").encode(), "application/json")})
    invoice_id = response.json()["id"]
    assert approve(client, invoice_id, note="checked").status_code == 409
    assert payments(db_path, invoice_id) == 0


def test_duplicate_cannot_be_approved_but_can_be_rejected(db_path, llm_replies):
    client = TestClient(app)
    invoice = upload(client, "dev_015", llm_replies)
    assert invoice["review_reasons"] == ["duplicate"]
    assert approve(client, invoice["id"], note="looks fine").status_code == 409
    assert payments(db_path, invoice["id"]) == 0
    rejected = client.post(f"/api/invoices/{invoice['id']}/reject", json={"user_id": "kavya", "note": "dup of SIS/26-27/0018"})
    assert rejected.json()["status"] == "rejected"


def test_note_required_to_approve_a_document_that_needed_review(db_path, llm_replies):
    client = TestClient(app)
    invoice = upload(client, "dev_024", llm_replies)
    assert invoice["review_reasons"] == ["bank_details_changed"]
    assert approve(client, invoice["id"], note="  ").status_code == 422
    assert approve(client, invoice["id"], note="Called Sitara on file number; change confirmed").status_code == 200


def test_rejected_invoice_cannot_then_be_approved(client, db_path):
    invoice_id = upload(client, "dev_001")["id"]
    client.post(f"/api/invoices/{invoice_id}/reject", json={"user_id": "kavya", "note": "wrong PO"})
    assert approve(client, invoice_id).status_code == 409
    assert payments(db_path, invoice_id) == 0


def test_approved_invoice_cannot_be_rejected(client):
    invoice_id = upload(client, "dev_001")["id"]
    approve(client, invoice_id)
    assert client.post(f"/api/invoices/{invoice_id}/reject", json={"user_id": "x", "note": ""}).status_code == 409


def test_decisions_are_in_the_audit_log(client, db_path):
    approved = upload(client, "dev_001")["id"]
    approve(client, approved, user="kavya", note="ok")
    rejected = upload(client, "dev_001")["id"]  # second copy is an in-batch duplicate
    client.post(f"/api/invoices/{rejected}/reject", json={"user_id": "farhan", "note": "duplicate"})
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT invoice_id, action, user_id, note FROM audit_log ORDER BY id").fetchall()
    assert rows == [(approved, "approve", "kavya", "ok"), (rejected, "reject", "farhan", "duplicate")]


def test_other_orgs_invoices_are_invisible_and_cannot_be_approved(client, db_path):
    invoice_id = upload(client, "dev_001", org="meridian")["id"]
    assert client.get(f"/api/invoices/{invoice_id}", headers={"X-Org-Id": "other"}).status_code == 404
    assert approve(client, invoice_id, org="other").status_code == 404
    assert payments(db_path, invoice_id) == 0


def test_non_utf8_upload_is_routed_to_review_not_a_500(client):
    response = client.post("/api/invoices", files={"file": ("bad.txt", b"\xff\xfe\x80 invoice", "text/plain")})
    assert response.status_code == 200
    assert "processing_error" in response.json()["review_reasons"]
    assert json.dumps(response.json())  # serialisable
