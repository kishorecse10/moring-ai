import pytest
from fastapi.testclient import TestClient

from ledgerline.api import app


@pytest.fixture
def client(tmp_path, monkeypatch, fake_llm):
    monkeypatch.setenv("LEDGERLINE_DB", str(tmp_path / "api.db"))
    return TestClient(app)


def test_upload_list_get_approve(client):
    uploaded = client.post("/api/invoices", files={"file": ("dev_001.txt", b"some invoice text", "text/plain")})
    assert uploaded.status_code == 200
    invoice_id = uploaded.json()["id"]

    listed = client.get("/api/invoices").json()
    assert [row["id"] for row in listed] == [invoice_id]

    detail = client.get(f"/api/invoices/{invoice_id}").json()
    assert detail["invoice_number"] == "SIS/26-27/0042"

    approved = client.post(f"/api/invoices/{invoice_id}/approve", json={"user_id": "kavya", "note": "ok"})
    assert approved.json()["status"] == "approved"


def test_stats_counts_processed_documents(client):
    client.post("/api/invoices", files={"file": ("a.txt", b"text", "text/plain")})
    assert client.get("/api/stats").json()["invoices_processed"] == 1
