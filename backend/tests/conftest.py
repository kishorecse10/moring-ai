import json

import pytest

from ledgerline import db
from ledgerline.config import get_settings
from ledgerline.llm.fake import CANNED_EXTRACTION, FakeClient
from ledgerline.reference import load_reference

DATA_DIR = get_settings().data_dir
DEV_LABELS = {
    row["document_id"]: row
    for row in (json.loads(line) for line in (DATA_DIR / "ground_truth" / "dev.jsonl").read_text().splitlines())
}


def dev_text(document_id: str) -> str:
    return (DATA_DIR / "invoices" / "dev" / DEV_LABELS[document_id]["filename"]).read_text(encoding="utf-8")


def disputed_text(name: str) -> str:
    return (DATA_DIR / "invoices" / "disputed" / name).read_text(encoding="utf-8")


def oracle_extraction(document_id: str) -> dict:
    """What a perfect extractor would return for a dev document: the labelled fields, without the routing."""
    expected = dict(DEV_LABELS[document_id]["expected"])
    for key in ("needs_review", "review_reasons", "required_approvals"):
        expected.pop(key, None)
    return expected


@pytest.fixture
def ref():
    return load_reference()


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(str(tmp_path / "test.db"))
    yield connection
    connection.close()


@pytest.fixture
def fake_llm(monkeypatch):
    """Replace the real provider with the fake client for the duration of a test."""
    client = FakeClient([json.dumps(CANNED_EXTRACTION)] * 2)
    monkeypatch.setattr("ledgerline.extraction.get_client", lambda: client)
    return client


@pytest.fixture
def llm_replies(monkeypatch):
    """Queue exact model replies (dicts are JSON-encoded) and capture the prompts that were sent."""
    client = FakeClient([])

    def queue(*replies):
        client.responses.extend(r if isinstance(r, str) else json.dumps(r) for r in replies)
        return client

    monkeypatch.setattr("ledgerline.extraction.get_client", lambda: client)
    return queue
