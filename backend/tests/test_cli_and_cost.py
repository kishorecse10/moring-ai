import json

import pytest

from ledgerline import cli
from ledgerline.llm.pricing import cost_usd
from tests.conftest import dev_text, oracle_extraction


def test_batch_never_skips_a_document(tmp_path, llm_replies, monkeypatch):
    """The starter printed '[skip]' and wrote nothing for a document that raised (dev_005 did, on '1.2 lakh').
    Every input document must get a line, in document_id order."""
    folder = tmp_path / "in"
    folder.mkdir()
    (folder / "b_doc.txt").write_text(dev_text("dev_001"))
    (folder / "a_doc.eml").write_text(dev_text("dev_005"))
    (folder / "c_bad.txt").write_bytes(b"\xff\xfe not utf-8 \x80")
    (folder / "notes.md").write_text("ignored: not a supported document type")
    llm_replies({**oracle_extraction("dev_005"), "subtotal": "garbled"}, oracle_extraction("dev_001"),
                oracle_extraction("dev_001"))

    def explode_on_third(original=cli.process_document):
        calls = {"n": 0}

        def wrapper(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 3:
                raise RuntimeError("unexpected bug")
            return original(*args, **kwargs)
        return wrapper

    monkeypatch.setattr(cli, "process_document", explode_on_third())
    out = tmp_path / "predictions.jsonl"
    cli.main(["predict", "--input", str(folder), "--reference", "../data/reference", "--output", str(out)])
    lines = [json.loads(line) for line in out.read_text().splitlines()]
    assert [line["document_id"] for line in lines] == ["a_doc", "b_doc", "c_bad"]
    assert "processing_error" in lines[0]["review_reasons"]
    assert lines[1]["review_reasons"] == []
    assert lines[2]["needs_review"] is True and lines[2]["review_reasons"] == ["processing_error"]
    for line in lines:
        assert set(line) >= {"document_id", "needs_review", "review_reasons", "required_approvals", "usage"}


def test_contract_money_and_line_items_are_two_place_strings(tmp_path, llm_replies):
    folder = tmp_path / "in"
    folder.mkdir()
    (folder / "dev_001.txt").write_text(dev_text("dev_001"))
    llm_replies(oracle_extraction("dev_001"))
    out = tmp_path / "p.jsonl"
    cli.main(["predict", "--input", str(folder), "--reference", "../data/reference", "--output", str(out)])
    line = json.loads(out.read_text())
    assert line["total"] == "23458.00" and line["round_off"] == "-0.40"
    assert line["line_items"][0] == {"description": "SS Hex Bolt M10x40 (Box/100)", "quantity": "12",
                                     "unit_price": "1450.00", "amount": "17400.00"}


@pytest.mark.parametrize("model, usd", [("claude-opus-5-5", 4.0 + 20.0), ("claude-sonnet-5-5", 2.0 + 10.0),
                                        ("claude-haiku-5-5", 0.10 + 0.50)])
def test_price_per_million_tokens(model, usd):
    """v0.3's table was 1000x too low, so the dashboard showed ~₹15 for a month billed at ~$165."""
    assert cost_usd(model, 1_000_000, 1_000_000) == pytest.approx(usd)


def test_unknown_model_is_not_counted_as_free():
    assert cost_usd("claude-sonet-5.5", 1000, 1000) is None
