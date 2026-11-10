"""What leaves our systems (AP_POLICY.md section 5, the DPO's question)."""
import re

from ledgerline.pipeline import process_document
from tests.conftest import DEV_LABELS, dev_text, oracle_extraction


def test_no_bank_account_number_is_sent_to_the_provider(conn, ref, llm_replies):
    """v0.3 sent the whole vendor master (38 vendors' bank accounts) plus the document's own account number,
    twice per document. Every account number in the vendor master, and the one on the page, must be absent."""
    client = llm_replies(oracle_extraction("dev_024"))
    got = process_document(conn, ref, dev_text("dev_024"), "dev_024")
    sent = " ".join(system + prompt for system, prompt in client.calls)
    for vendor in ref.vendors:
        if vendor["bank_account"]:
            assert vendor["bank_account"] not in sent, vendor["vendor_id"]
    assert "50200012349999" not in sent
    assert "[MASKED-ACCOUNT-" in sent and "ending 9999" in sent
    # ...and the real number is still what we store and compare locally.
    assert got["bank_account"] == "50200012349999"
    assert got["review_reasons"] == ["bank_details_changed"]


def test_masked_placeholder_from_the_model_is_restored(conn, ref, llm_replies):
    llm_replies({**oracle_extraction("dev_001"), "bank_account": "[MASKED-ACCOUNT-1 ending 5678]"})
    got = process_document(conn, ref, dev_text("dev_001"), "dev_001")
    assert got["bank_account"] == "50200012345678"
    assert got["review_reasons"] == []


def test_e_invoice_account_is_masked_too(conn, ref, llm_replies):
    client = llm_replies(oracle_extraction("dev_006"))
    process_document(conn, ref, dev_text("dev_006"), "dev_006")
    assert "50200098765432" not in client.calls[0][1]


def test_prompt_contains_no_labelled_dev_documents(conn, ref, llm_replies):
    """v0.3 put dev_001..dev_003 and their labels in every prompt, so the eval scored the model on answers it
    had been shown."""
    client = llm_replies(oracle_extraction("dev_010"))
    process_document(conn, ref, dev_text("dev_010"), "dev_010")
    prompt = client.calls[0][1]
    for document_id in ("dev_001", "dev_002", "dev_003"):
        assert DEV_LABELS[document_id]["expected"]["invoice_number"] not in prompt
    assert "VENDOR MASTER" not in prompt and "vendor_id" not in prompt


def test_one_call_per_document(conn, ref, llm_replies):
    client = llm_replies(oracle_extraction("dev_001"))
    process_document(conn, ref, dev_text("dev_001"), "dev_001")
    assert len(client.calls) == 1


def test_only_long_digit_runs_are_masked():
    from ledgerline.extraction import mask_account_numbers
    masked, mapping = mask_account_numbers("A/c No.: 0219201000751  GSTIN 27AABFP2915E1ZK  Total 24,426.00")
    assert "0219201000751" not in masked and mapping == {"1": "0219201000751"}
    assert "27AABFP2915E1ZK" in masked and "24,426.00" in masked
    assert re.search(r"ending 0751", masked)
