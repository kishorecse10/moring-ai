from ledgerline.llm.fake import CANNED_EXTRACTION
from ledgerline.pipeline import process_document
from tests.conftest import dev_text, disputed_text, oracle_extraction


def test_process_document_persists_invoice(conn, ref, fake_llm):
    invoice = process_document(conn, ref, dev_text("dev_001"), "doc_001", filename="doc_001.txt")
    assert invoice["supplier_name"] == "Sitara Industrial Supplies Pvt. Ltd."
    assert invoice["total"] == 23458.0
    assert invoice["invoice_date"] == "2026-04-25"
    assert invoice["status"] == "ready_for_approval"
    # Was 2: v0.3 ran a second "verification" call on every document, doubling cost and latency.
    assert invoice["usage"]["llm_calls"] == 1


def test_document_text_reaches_the_model(conn, ref, fake_llm):
    process_document(conn, ref, "UNIQUE-MARKER-123", "doc_002")
    assert "UNIQUE-MARKER-123" in fake_llm.calls[0][1]


def test_line_items_are_stored(conn, ref, fake_llm):
    invoice = process_document(conn, ref, dev_text("dev_001"), "doc_003")
    assert [item["amount"] for item in invoice["line_items"]] == ["17400.00", "2480.00"]


# --- processing_error: never skip, never drop ----------------------------------------------------------------

def test_provider_failure_is_persisted_as_processing_error(conn, ref, monkeypatch):
    class Down:
        def complete(self, *args, **kwargs):
            raise ConnectionError("provider unavailable")

    monkeypatch.setattr("ledgerline.extraction.get_client", lambda: Down())
    got = process_document(conn, ref, dev_text("dev_001"), "dev_001")
    assert got["needs_review"] is True and got["review_reasons"] == ["processing_error"]
    assert got["status"] == "needs_review"


def test_unparseable_model_reply_is_processing_error(conn, ref, llm_replies):
    llm_replies("Sorry, I can't help with that.")
    got = process_document(conn, ref, dev_text("dev_001"), "dev_001")
    assert "processing_error" in got["review_reasons"]
    assert got["usage"]["llm_calls"] == 1  # the call that failed is still costed


def test_fenced_json_reply_is_accepted(conn, ref, llm_replies):
    import json
    llm_replies("```json\n" + json.dumps(oracle_extraction("dev_001")) + "\n```")
    got = process_document(conn, ref, dev_text("dev_001"), "dev_001")
    assert got["review_reasons"] == []


def test_unreadable_amount_is_processing_error_not_a_crash(conn, ref, llm_replies):
    # The v0.3 pipeline raised on this, and the batch skipped the document entirely.
    llm_replies({**oracle_extraction("dev_005"), "subtotal": "approx. one lakh twenty"})
    got = process_document(conn, ref, dev_text("dev_005"), "dev_005")
    assert "processing_error" in got["review_reasons"]


def test_lakh_amount_as_printed_is_understood(conn, ref, llm_replies):
    # dev_005 as a model copies it: "₹1.2 lakh" for the line and subtotal.
    extraction = {**oracle_extraction("dev_005"), "subtotal": "₹1.2 lakh",
                  "line_items": [{"description": "Freight", "quantity": "15", "unit_price": "₹8,000.00",
                                  "amount": "₹1.2 lakh"}], "invoice_date": "31/03/2026"}
    llm_replies(extraction)
    got = process_document(conn, ref, dev_text("dev_005"), "dev_005")
    assert got["review_reasons"] == ["bank_details_changed"]


def test_missing_total_is_processing_error(conn, ref, llm_replies):
    llm_replies({**oracle_extraction("dev_001"), "total": None})
    got = process_document(conn, ref, dev_text("dev_001"), "dev_001")
    assert "processing_error" in got["review_reasons"]


# --- grounding: the model may not "fix" what is printed ------------------------------------------------------

def test_model_correcting_a_garbled_gstin_is_caught(conn, ref, llm_replies):
    """disp_01 prints 27AAKCS4B21M1ZW (an OCR'd 8 -> B). A model that 'helpfully' returns Sitara's real GSTIN
    would make the invoice look clean. The value isn't on the page, so the document goes to review."""
    llm_replies({**CANNED_EXTRACTION, "supplier_gstin": "27AAKCS4821M1ZW", "invoice_number": "SIS/26-27/0055",
                 "invoice_date": "30/04/2026", "subtotal": "13,840.00", "cgst": "1,245.60", "sgst": "1,245.60",
                 "round_off": "-0.20", "total": "16,331.00",
                 "line_items": [{"description": "a", "quantity": "8", "unit_price": "1450", "amount": "11,600.00"},
                                {"description": "b", "quantity": "2", "unit_price": "1120", "amount": "2,240.00"}]})
    got = process_document(conn, ref, disputed_text("disp_01.txt"), "disp_01")
    assert "processing_error" in got["review_reasons"]
    assert any("supplier_gstin" in w for w in got["warnings"])


def test_model_copying_a_garbled_gstin_faithfully_routes_to_review(conn, ref, llm_replies):
    llm_replies({**CANNED_EXTRACTION, "supplier_gstin": "27AAKCS4B21M1ZW", "invoice_number": "SIS/26-27/0055",
                 "invoice_date": "30/04/2026", "subtotal": "13,840.00", "cgst": "1,245.60", "sgst": "1,245.60",
                 "round_off": "-0.20", "total": "16,331.00",
                 "line_items": [{"description": "a", "quantity": "8", "unit_price": "1450", "amount": "11,600.00"},
                                {"description": "b", "quantity": "2", "unit_price": "1120", "amount": "2,240.00"}]})
    got = process_document(conn, ref, disputed_text("disp_01.txt"), "disp_01")
    assert set(got["review_reasons"]) == {"gstin_invalid", "vendor_unknown"}


def test_model_reformatting_a_date_is_caught(conn, ref, llm_replies):
    """dev_002 is dated 03/04/2026. A model that 'helpfully' converts it month-first returns 2026-03-04, which
    moves the invoice into the previous financial year. That date isn't printed, so it's flagged."""
    llm_replies({**oracle_extraction("dev_002"), "invoice_date": "2026-03-04"})
    got = process_document(conn, ref, dev_text("dev_002"), "dev_002")
    assert "processing_error" in got["review_reasons"]


def test_invented_total_is_caught(conn, ref, llm_replies):
    llm_replies({**oracle_extraction("dev_001"), "total": "23,000.00"})
    got = process_document(conn, ref, dev_text("dev_001"), "dev_001")
    assert "processing_error" in got["review_reasons"]


def test_quantity_with_units_is_not_a_processing_error(conn, ref, llm_replies):
    """Real claude-sonnet-5-5 output (2026-11-10 run): quantities copied as '750 kg', '10 PKT'. Strict parsing
    sent 14/24 dev documents to processing_error. Quantity and rate drive no policy rule."""
    extraction = oracle_extraction("dev_022")
    extraction["line_items"] = [{**extraction["line_items"][0], "quantity": "750 kg", "unit_price": "Rs 98.45 / kg"}]
    llm_replies(extraction)
    got = process_document(conn, ref, dev_text("dev_022"), "dev_022")
    assert got["review_reasons"] == []
    assert got["line_items"][0]["quantity"] == "750" and got["line_items"][0]["unit_price"] == "98.45"


def test_unreadable_line_amount_is_still_a_processing_error(conn, ref, llm_replies):
    extraction = oracle_extraction("dev_022")
    extraction["line_items"] = [{**extraction["line_items"][0], "amount": "seventy-three thousand"}]
    llm_replies(extraction)
    got = process_document(conn, ref, dev_text("dev_022"), "dev_022")
    assert "processing_error" in got["review_reasons"]
