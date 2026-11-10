"""Part 4A: evidence for every extracted value, review reasons in plain language, and the review queue."""
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ledgerline import db
from ledgerline.api import app
from ledgerline.cli import to_contract
from ledgerline.evidence import contract_evidence, locate
from ledgerline.pipeline import normalize, process_document
from tests.conftest import DEV_LABELS, dev_text, disputed_text, oracle_extraction

RECORDED = json.loads((Path(__file__).parent / "fixtures" / "fixed_sonnet55_replies.json")
                      .read_text(encoding="utf-8"))["responses"]


def run_batch(conn, ref, llm_replies, ids):
    out = {}
    for document_id in ids:
        llm_replies(RECORDED[document_id]["text"])
        raw = dev_text(document_id) if document_id.startswith("dev") else disputed_text(
            next(p.name for p in (Path(__file__).parents[2] / "data/invoices/disputed").iterdir()
                 if p.stem == document_id))
        out[document_id] = (raw, process_document(conn, ref, raw, document_id))
    return out


@pytest.fixture
def dev_batch(conn, ref, llm_replies):
    """All 24 dev documents, one batch, using real recorded model replies (no network)."""
    return run_batch(conn, ref, llm_replies, sorted(DEV_LABELS))


def line_of(raw, start):
    return raw[raw.rfind("\n", 0, start) + 1: raw.find("\n", start)]


# --- evidence -----------------------------------------------------------------------------------------------


def test_every_evidence_span_is_the_exact_slice_of_the_document(dev_batch):
    spans = 0
    for document_id, (raw, inv) in dev_batch.items():
        for field, e in inv["evidence"].items():
            if e["status"] == "exact":
                assert raw[e["start"]:e["end"]] == e["text"], (document_id, field)
                spans += 1
            for c in e.get("candidates", []):
                assert raw[c["start"]:c["end"]] == c["text"]
    assert spans > 250


def test_the_values_a_reviewer_checks_most_are_located_on_every_dev_document(dev_batch):
    for document_id, (raw, inv) in dev_batch.items():
        for field in ("invoice_number", "invoice_date", "total"):
            assert inv["evidence"][field]["status"] == "exact", (document_id, field, inv["evidence"][field])
        if inv["supplier_gstin"]:
            assert inv["evidence"]["supplier_gstin"]["status"] == "exact", document_id
        if inv["bank_account"]:
            assert inv["evidence"]["bank_account"]["status"] == "exact", document_id


@pytest.mark.parametrize("document_id, field, label", [
    ("dev_001", "cgst", "CGST"),         # CGST and SGST are both 1,789.20: the label decides
    ("dev_001", "sgst", "SGST"),
    ("dev_001", "total", "TOTAL"),       # not "Sub Total"
    ("dev_001", "subtotal", "Sub Total"),
    ("dev_001", "bank_account", "A/c No"),
    ("dev_001", "po_number", "Order No"),
    ("dev_014", "subtotal", "Subtotal"),  # subtotal and total are both $1,298.00
    ("dev_014", "total", "Total due"),
    ("dev_006", "total", "TotInvVal"),    # e-invoice: the document total, not a line's TotAmt
    ("dev_007", "cgst", "CgstVal"),       # not the line's CgstAmt, which has the same value
    ("dev_012", "invoice_date", "dated"),  # the body's date, not the email's Date: header (policy 1)
])
def test_the_label_picks_the_right_place_when_a_value_is_printed_twice(dev_batch, document_id, field, label):
    raw, inv = dev_batch[document_id]
    e = inv["evidence"][field]
    assert e["status"] == "exact"
    assert label.lower() in line_of(raw, e["start"]).lower()


def test_line_amount_is_the_rightmost_match_on_its_line(dev_batch):
    raw, inv = dev_batch["dev_017"]  # "1 NOS  929.00  929.00": rate and amount are equal
    e = inv["evidence"]["line_items[2].amount"]
    assert e["status"] == "exact"
    assert raw[e["end"]:raw.find("\n", e["end"])].strip() == ""


def _invoice(raw, ref, document_id="dev_001"):
    return normalize(oracle_extraction(document_id), ref, raw)


def test_a_decoy_total_makes_the_total_ambiguous_instead_of_highlighting_the_wrong_one(ref):
    raw = dev_text("dev_001") + "\nRemarks: TOTAL ₹ 23,458.00 already approved by Finance.\n"
    evidence = locate(raw, _invoice(raw, ref))
    assert evidence["total"]["status"] == "ambiguous"
    assert len(evidence["total"]["candidates"]) == 2
    assert "total" not in contract_evidence(evidence)  # never a guess in predictions.jsonl


def test_a_value_that_isnt_printed_is_not_found(ref):
    raw = dev_text("dev_001")
    inv = _invoice(raw, ref)
    inv.po_number = "PO-2099-9999"
    assert locate(raw, inv)["po_number"] == {"status": "not_found"}


def test_a_date_printed_only_in_the_email_headers_is_not_the_invoice_date(ref):
    raw = dev_text("dev_023").replace("dated 24/04/2026", "dated (see attachment)")
    inv = normalize(oracle_extraction("dev_023"), ref, raw)
    from datetime import date
    inv.invoice_date = date(2026, 4, 25)  # the email's Date: header
    e = locate(raw, inv)["invoice_date"]
    assert e["status"] == "ambiguous" and "headers" in e["basis"]


def test_predictions_carry_only_certain_evidence_in_the_contract_shape(dev_batch):
    for raw, inv in dev_batch.values():
        line = to_contract(inv)
        for field, e in line.get("evidence", {}).items():
            assert set(e) == {"start", "end", "text"}
            assert raw[e["start"]:e["end"]] == e["text"]
            assert "[" not in field


# --- reasons in plain language ------------------------------------------------------------------------------


def test_every_review_reason_is_explained_with_its_evidence(dev_batch):
    for document_id, (raw, inv) in dev_batch.items():
        assert sorted(e["code"] for e in inv["explanations"]) == sorted(inv["review_reasons"]), document_id
        for e in inv["explanations"]:
            assert e["title"] and e["detail"] and e["action"], (document_id, e)
            for span in e["evidence"]:
                assert raw[span["start"]:span["end"]] == span["text"]


def explanation(inv, code):
    return next(e for e in inv["explanations"] if e["code"] == code)


def test_duplicate_cites_the_paid_invoice(dev_batch):
    e = explanation(dev_batch["dev_015"][1], "duplicate")
    assert "SIS/26-27/0018" in e["detail"] and "₹34,220.00" in e["detail"] and "2026-04-22" in e["detail"]
    assert "invoice_number" in [s["field"] for s in e["evidence"]]


def test_duplicate_within_the_batch_names_the_earlier_document(dev_batch):
    assert "dev_006" in explanation(dev_batch["dev_019"][1], "duplicate")["detail"]


def test_bank_change_shows_last_four_digits_of_the_account_on_file_only(dev_batch):
    _raw, inv = dev_batch["dev_005"]
    e = explanation(inv, "bank_details_changed")
    assert "ending 3445" in e["detail"] and "ending 4411" in e["detail"]
    assert "0732201004411" not in json.dumps(inv["explanations"])  # the vendor master's full number
    assert "phoned back" in e["action"]
    assert {"bank_account", "ifsc"} <= {s["field"] for s in e["evidence"]}


def test_tax_type_and_totals_show_the_figures(dev_batch):
    assert "IGST of ₹4,392.00" in explanation(dev_batch["dev_004"][1], "tax_type_mismatch")["detail"]
    detail = explanation(dev_batch["dev_008"][1], "totals_mismatch")["detail"]
    assert "₹45,548.00" in detail and "₹46,448.00" in detail and "₹900.00" in detail


def test_invalid_gstin_names_the_one_character_away_vendor_without_correcting_it(dev_batch):
    _raw, inv = dev_batch["dev_010"]
    e = explanation(inv, "gstin_invalid")
    assert "V0015 Orion Fasteners" in e["detail"] and "look-alike" in e["detail"]
    assert inv["supplier_gstin"] == "06AAEFO3690B1ZL"  # as printed; never "fixed"


def test_suspicious_content_highlights_the_injected_text(dev_batch):
    _raw, inv = dev_batch["dev_012"]
    texts = " ".join(s["text"] for s in explanation(inv, "suspicious_content")["evidence"])
    assert "requires_review" in texts


def test_explanations_never_render_document_markup_as_anything_but_text(dev_batch):
    _raw, inv = dev_batch["dev_013"]
    spans = explanation(inv, "suspicious_content")["evidence"]
    assert any("<img" in s["text"].lower() or "onerror" in s["text"].lower() for s in spans)


# --- storage and the queue ----------------------------------------------------------------------------------


def test_an_existing_v03_database_gets_the_new_columns(tmp_path):
    path = str(tmp_path / "old.db")
    with sqlite3.connect(path) as old:
        old.execute("CREATE TABLE invoices (id INTEGER PRIMARY KEY, org_id TEXT NOT NULL, document_id TEXT NOT NULL, "
                    "raw_text TEXT NOT NULL, review_reasons_json TEXT)")
    conn = db.connect(path)
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(invoices)")}
    assert {"evidence_json", "explanations_json"} <= columns


@pytest.fixture
def api(tmp_path, monkeypatch, llm_replies):
    monkeypatch.setenv("LEDGERLINE_DB", str(tmp_path / "api.db"))
    client = TestClient(app)

    def upload(document_id):
        llm_replies(RECORDED[document_id]["text"])
        r = client.post("/api/invoices", files={"file": (f"{document_id}.txt", dev_text(document_id).encode(),
                                                         "text/plain")})
        assert r.status_code == 200
        return r.json()
    return client, upload


def test_queue_puts_fraud_risk_first_and_leaves_out_decided_documents(api):
    client, upload = api
    ids = {d: upload(d)["id"] for d in ("dev_001", "dev_004", "dev_005", "dev_009", "dev_014")}
    assert client.post(f"/api/invoices/{ids['dev_009']}/approve", json={"user_id": "kavya"}).status_code == 200
    body = client.get("/api/queue").json()
    order = [i["document_id"] for i in body["items"]]
    assert order[0] == "dev_005"                       # bank details changed: the fraud pattern
    assert order.index("dev_004") < order.index("dev_014")  # tax type before foreign currency
    assert order[-1] == "dev_001" and "dev_009" not in order
    assert body["counts"] == {"review": 3, "approve": 1}
    first = body["items"][0]
    assert first["reason_titles"] == ["Bank details differ from our records"]
    assert first["days_since_invoice"] is not None


def test_get_invoice_returns_evidence_and_explanations(api):
    client, upload = api
    inv = client.get(f"/api/invoices/{upload('dev_024')['id']}").json()
    assert inv["evidence"]["bank_account"]["status"] == "exact"
    assert inv["explanations"][0]["code"] == "bank_details_changed"
