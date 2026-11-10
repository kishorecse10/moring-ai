"""Reproduce the evidence for FINDINGS F1-F3 against the UNMODIFIED v0.3 starter (commit e2f4ac2), offline.

No billed LLM calls: the starter's LLM client is replaced by one that serves the real claude-sonnet-5-5 replies
recorded from the starter on 2026-11-10 (backend/tests/fixtures/starter_sonnet55_replies.json), or by the starter's
own FakeClient for the API reproduction.

    make evidence        # or, by hand:
    rm -rf /tmp/starter && mkdir /tmp/starter && git archive e2f4ac2 backend data docs | tar -x -C /tmp/starter
    backend/.venv/bin/python submission/evidence/reproduce_starter.py --starter /tmp/starter/backend

Writes, next to this script:
  f3_batch_as_shipped.txt / .jsonl   the starter's own `cli predict` over dev/ and disputed/ on the recorded replies
  f1_routing_on_recorded_replies.jsonl + f1_routing_summary.txt   the starter's routing once the fence bug is shimmed
  f2_approve_api.txt                 repeated approve, credit note, and cross-org read against the starter's API
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
FIXTURE = REPO / "backend" / "tests" / "fixtures" / "starter_sonnet55_replies.json"
_FENCE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)


def load_starter(starter_backend: Path, db_path: str):
    os.environ["LEDGERLINE_DB"] = db_path
    os.environ["LEDGERLINE_DATA"] = str(REPO / "data")
    os.environ["LLM_PROVIDER"] = "fake"
    sys.path.insert(0, str(starter_backend))
    for name in [m for m in sys.modules if m == "ledgerline" or m.startswith("ledgerline.")]:
        del sys.modules[name]
    import ledgerline.extraction as extraction  # noqa: E402  (the starter's, not ours)

    assert Path(extraction.__file__).resolve().is_relative_to(starter_backend.resolve()), extraction.__file__
    return extraction


class ReplayClient:
    """Serves the recorded first-pass reply for whichever document is in the prompt.

    The starter's second (verification) pass was never recorded, because on the real run the first json.loads
    crashed. When it is reached here (only with --strip-fences) it gets the first reply back: 'verification
    changed nothing'. That is stated in the output."""

    def __init__(self, replies: dict, docs: dict[str, str], strip: bool):
        self.replies, self.docs, self.strip = replies, docs, strip

    def complete(self, system, prompt, max_tokens=2000):
        from ledgerline.llm.base import LLMResponse

        tail = prompt[-4000:]
        doc_id = next(d for d, text in self.docs.items() if text.strip()[-300:] in tail)
        r = self.replies[doc_id]
        text = r["text"]
        if self.strip:
            m = _FENCE.search(text)
            text = m.group(1) if m else text
        return LLMResponse(text, r.get("model", "claude-sonnet-5-5"), r.get("input_tokens", 0),
                           r.get("output_tokens", 0), r.get("latency_ms", 0))


def docs_in(folder: Path) -> dict[str, str]:
    return {p.stem: p.read_text(encoding="utf-8") for p in sorted(folder.iterdir())
            if p.suffix in {".txt", ".eml", ".json"}}


def run_batch(extraction, folder: Path, out_jsonl: Path, strip: bool) -> str:
    from ledgerline import cli

    replies = json.loads(FIXTURE.read_text())["responses"]
    extraction.get_client = lambda: ReplayClient(replies, docs_in(folder), strip)
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        cli.main(["predict", "--input", str(folder), "--reference", str(REPO / "data" / "reference"),
                  "--output", str(out_jsonl), "--db", tempfile.mktemp(suffix=".db")])
    return f"$ python -m ledgerline.cli predict --input {folder.relative_to(REPO)}\n" \
           f"--- stderr ---\n{stderr.getvalue()}--- stdout ---\n{stdout.getvalue()}"


def f3(extraction, out: Path) -> None:
    log = []
    for name in ["dev", "disputed"]:
        target = out / f"f3_batch_as_shipped_{name}.jsonl"
        log.append(run_batch(extraction, REPO / "data" / "invoices" / name, target, strip=False))
        log.append(f"lines in {target.name}: {sum(1 for _ in target.open())}\n")
    replies = json.loads(FIXTURE.read_text())["responses"]
    fenced = sum(r["text"].lstrip().startswith("```") for r in replies.values())
    log.append(f"recorded replies starting with a ``` fence: {fenced}/{len(replies)}\n")
    (out / "f3_batch_as_shipped.txt").write_text("\n".join(log))


def f1(extraction, out: Path) -> None:
    target = out / "f1_routing_on_recorded_replies.jsonl"
    log = [run_batch(extraction, REPO / "data" / "invoices" / "dev", target, strip=True)]
    truth = {json.loads(l)["document_id"]: json.loads(l)["expected"]
             for l in (REPO / "data" / "ground_truth" / "dev.jsonl").open()}
    log.append("Starter routing (model-decided) vs labels, with the ```json fence stripped from each reply.\n"
               "The verification pass was not recorded; it is replayed as 'no change'.\n")
    log.append(f"{'doc':8} {'label':6} {'starter':8} reasons")
    wrong = []
    for line in target.open():
        row = json.loads(line)
        exp = truth[row["document_id"]]["needs_review"]
        mark = "" if exp == row["needs_review"] else "   <-- MISMATCH"
        if mark:
            wrong.append(row["document_id"])
        log.append(f"{row['document_id']:8} {str(exp):6} {str(row['needs_review']):8} {row['review_reasons']}{mark}")
    log.append(f"\nmismatches: {wrong}")
    (out / "f1_routing_summary.txt").write_text("\n".join(log) + "\n")


def f2(starter_backend: Path, out: Path) -> None:
    from fastapi.testclient import TestClient
    from ledgerline import api, db

    client = TestClient(api.app)
    lines = []

    def call(method, url, **kw):
        r = getattr(client, method)(url, **kw)
        body = r.json()
        if isinstance(body, dict) and "raw_text" in body:  # keep the log readable
            body = {k: body[k] for k in ("id", "org_id", "document_id", "document_type", "total", "status",
                                         "needs_review", "required_approvals") if k in body}
        lines.append(f"{method.upper()} {url} {kw.get('json', '')} {kw.get('headers', '')}\n"
                     f"  -> {r.status_code} {json.dumps(body)}")
        return r

    # Uploads are extracted from the recorded Sonnet replies (fence stripped so the starter can parse them).
    import ledgerline.extraction as extraction

    dev = REPO / "data" / "invoices" / "dev"
    replies = json.loads(FIXTURE.read_text())["responses"]
    extraction.get_client = lambda: ReplayClient(replies, docs_in(dev), strip=True)

    def upload(name):
        return call("post", "/api/invoices", files={"file": (name, (dev / name).read_bytes(), "text/plain")}).json()

    lines.append("# 1. dev_001 approved three times by the same user")
    inv = upload("dev_001.txt")
    for _ in range(3):
        call("post", f"/api/invoices/{inv['id']}/approve", json={"user_id": "kavya.iyer", "note": ""})
    lines.append("\n# 2. another org reads it")
    call("get", f"/api/invoices/{inv['id']}", headers={"X-Org-Id": "acme"})
    lines.append("\n# 3. the dev_007 credit note, one approve")
    cn = upload("dev_007.json")
    call("post", f"/api/invoices/{cn['id']}/approve", json={"user_id": "kavya.iyer", "note": ""})
    conn = db.connect(os.environ["LEDGERLINE_DB"])

    lines.append("\nSELECT invoice_id, amount FROM payments:")
    for row in conn.execute("SELECT invoice_id, amount FROM payments ORDER BY id"):
        lines.append(f"  {tuple(row)}")
    (out / "f2_approve_api.txt").write_text("\n".join(lines) + "\n")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--starter", required=True, help="backend/ of an extracted e2f4ac2 tree")
    p.add_argument("--out", default=str(HERE))
    args = p.parse_args()
    starter, out = Path(args.starter).resolve(), Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    extraction = load_starter(starter, tempfile.mktemp(suffix=".db"))
    f3(extraction, out)
    f1(extraction, out)
    f2(starter, out)
    print(f"evidence written to {out}")


if __name__ == "__main__":
    main()
