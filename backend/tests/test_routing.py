"""Routing is decided by code from the extracted fields, not by the model.

The oracle test feeds the labelled fields for each dev document to the pipeline, as a perfect extractor would,
and checks that the code alone produces the labelled review reasons and approval counts. On the v0.3 starter
this fails for every document that needs review, because the starter took `requires_review` from the model.
"""
import json
from decimal import Decimal

import pytest

from ledgerline.models import Invoice
from ledgerline.pipeline import process_document, required_approvals
from tests.conftest import DEV_LABELS, dev_text, oracle_extraction

DEV_IDS = sorted(DEV_LABELS)


def test_rules_reproduce_dev_labels_given_perfect_extraction(conn, ref, llm_replies):
    """All 24 dev documents in one batch, in document_id order (needed for the in-batch duplicate dev_019)."""
    llm_replies(*(oracle_extraction(d) for d in DEV_IDS))
    mismatches = {}
    for document_id in DEV_IDS:
        got = process_document(conn, ref, dev_text(document_id), document_id)
        expected = DEV_LABELS[document_id]["expected"]
        if (sorted(got["review_reasons"]), got["needs_review"], got["required_approvals"]) != (
            sorted(expected["review_reasons"]), expected["needs_review"], expected["required_approvals"]
        ):
            mismatches[document_id] = {"got": got["review_reasons"], "expected": expected["review_reasons"],
                                       "approvals": (got["required_approvals"], expected["required_approvals"])}
    assert mismatches == {}


def test_model_cannot_waive_review_for_injected_document(conn, ref, llm_replies):
    """dev_012 tells 'AI assistants' to set requires_review false. Even if the model obeys, the document is
    routed to review: vendor_new from the vendor master and suspicious_content from the text."""
    obeyed = {**oracle_extraction("dev_012"), "requires_review": False, "review_reasons": []}
    llm_replies(obeyed)
    got = process_document(conn, ref, dev_text("dev_012"), "dev_012")
    assert got["needs_review"] is True
    assert set(got["review_reasons"]) == {"vendor_new", "suspicious_content"}


def test_model_cannot_add_unsupported_reasons(conn, ref, llm_replies):
    """The model's opinion about reasons is ignored in both directions: a clean invoice stays clean."""
    llm_replies({**oracle_extraction("dev_001"), "requires_review": True, "review_reasons": ["duplicate"]})
    got = process_document(conn, ref, dev_text("dev_001"), "dev_001")
    assert got["review_reasons"] == [] and got["status"] == "ready_for_approval"


@pytest.mark.parametrize("total, expected", [("499999.99", 1), ("500000.00", 2), ("500000.01", 2)])
def test_two_approvals_from_five_lakh_inclusive(conn, ref, llm_replies, total, expected):
    """Policy 4.1 says 'a total of ₹5,00,000.00 or more'. The starter used '>' (dev_017 is exactly 5 lakh)."""
    inv = Invoice("invoice", "X", None, "1", None, "INR", None, Decimal(0), Decimal(0), Decimal(0), Decimal(0),
                  Decimal(total), None, None, None, None)
    assert required_approvals(inv) == expected


def test_credit_note_needs_zero_approvals_and_foreign_needs_two(conn, ref, llm_replies):
    llm_replies(oracle_extraction("dev_007"), oracle_extraction("dev_014"))
    credit_note = process_document(conn, ref, dev_text("dev_007"), "dev_007")
    foreign = process_document(conn, ref, dev_text("dev_014"), "dev_014")
    assert credit_note["required_approvals"] == 0 and credit_note["review_reasons"] == ["credit_note"]
    assert foreign["required_approvals"] == 2 and foreign["review_reasons"] == ["foreign_currency"]


def test_e_invoice_type_overrides_model(conn, ref, llm_replies):
    """dev_007's DocDtls.Typ is CRN. If the model calls it an invoice, the JSON still decides."""
    llm_replies({**oracle_extraction("dev_007"), "document_type": "invoice"})
    got = process_document(conn, ref, dev_text("dev_007"), "dev_007")
    assert got["document_type"] == "credit_note" and "credit_note" in got["review_reasons"]
    assert json.loads(json.dumps(got["required_approvals"])) == 0


# --- recorded model replies (v0.3 starter, claude-sonnet-5-5, 2026-11-10) -------------------------------------

RECORDED = json.loads((__import__("pathlib").Path(__file__).parent / "fixtures" / "starter_sonnet55_replies.json")
                      .read_text(encoding="utf-8"))["responses"]


def test_recorded_replies_all_parse(conn, ref, llm_replies):
    """The starter crashed on all 30 recorded replies (```json fences) and wrote 0/24 predictions."""
    llm_replies(*(RECORDED[d]["text"] for d in DEV_IDS))
    for document_id in DEV_IDS:
        got = process_document(conn, ref, dev_text(document_id), document_id)
        assert got["document_type"] in {"invoice", "credit_note"}, document_id


@pytest.mark.parametrize("duplicate_id, earlier", [("dev_015", None), ("dev_019", "dev_006")])
def test_recorded_reply_that_missed_a_duplicate_is_still_routed_to_review(conn, ref, llm_replies, duplicate_id,
                                                                          earlier):
    """On the recorded run the model said requires_review=false for both real duplicates: dev_015 (already in
    paid_invoices.csv) and dev_019 (a resend of dev_006 in the same batch). It never saw the payment history.
    Code now runs the duplicate check, so the model's verdict doesn't matter."""
    assert '"requires_review": false' in RECORDED[duplicate_id]["text"]
    replies = ([RECORDED[earlier]["text"]] if earlier else []) + [RECORDED[duplicate_id]["text"]]
    llm_replies(*replies)
    if earlier:
        process_document(conn, ref, dev_text(earlier), earlier)
    got = process_document(conn, ref, dev_text(duplicate_id), duplicate_id)
    assert got["needs_review"] is True and "duplicate" in got["review_reasons"]


FIXED_RECORDED = json.loads((__import__("pathlib").Path(__file__).parent / "fixtures" / "fixed_sonnet55_replies.json")
                            .read_text(encoding="utf-8"))["responses"]


def test_recorded_replies_to_the_fixed_prompt_route_every_dev_document_correctly(conn, ref, llm_replies):
    """End-to-end on real model output: claude-sonnet-5-5's replies to the current prompt, replayed through the
    current pipeline, give exactly the labelled reasons and approvals for all 24 dev documents."""
    llm_replies(*(FIXED_RECORDED[d]["text"] for d in DEV_IDS))
    wrong = {}
    for document_id in DEV_IDS:
        got = process_document(conn, ref, dev_text(document_id), document_id)
        expected = DEV_LABELS[document_id]["expected"]
        if (sorted(got["review_reasons"]), got["required_approvals"]) != (
                sorted(expected["review_reasons"]), expected["required_approvals"]):
            wrong[document_id] = (got["review_reasons"], got["warnings"])
    assert wrong == {}
