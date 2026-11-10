"""Run a Ledgerline code tree over a folder of documents with REAL LLM calls, recording everything the eval needs.

    cd backend
    .venv/bin/python eval/run_live.py --code-root . --input ../data/invoices/dev --out ../submission/eval_runs/mine_opus_dev_r1

The same script runs the v0.3 starter, unmodified, from an extracted tree:

    git archive e2f4ac2 backend data docs | tar -x -C /tmp/starter
    .venv/bin/python eval/run_live.py --code-root /tmp/starter/backend --input ../data/invoices/dev \
        --out ../submission/eval_runs/starter_opus_dev [--strip-fences]

It writes, into --out:
  predictions.jsonl  one line per document, in document_id order, with what the pipeline returned (or the exception),
                     and `wall_ms`: the end-to-end time process_document took, all LLM calls included.
  calls.jsonl        every LLM call: document, model, tokens, latency, and the raw reply text (as the model sent it).
  meta.json          model, provider, code root, git commit, flags, date.

Nothing here decides anything; score.py turns these files into numbers, offline. Batches run in one database, in
document_id order, exactly like `cli predict`, so in-batch duplicates are detected the same way.

--strip-fences removes a ```json fence from each reply before the starter sees it. The as-shipped starter crashes on
fenced replies (FINDINGS F3); with this shim we can also measure what its *design* (policy in the prompt, the model
routes, a second verification pass) would have produced once that one-line parse bug is out of the way.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

SUFFIXES = {".txt", ".eml", ".json"}
KEEP = ["document_type", "supplier_name", "supplier_gstin", "invoice_number", "invoice_date", "currency",
        "subtotal", "cgst", "sgst", "igst", "round_off", "total", "bank_account", "ifsc", "po_number",
        "line_items", "needs_review", "review_reasons", "required_approvals", "warnings"]
_FENCE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)


def _json_only(text: str) -> str:
    """The JSON object inside a reply that wraps it in a fence and/or prose; the reply unchanged if there is none."""
    m = _FENCE.search(text)
    if m:
        return m.group(1)
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if 0 <= start < end else text


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--code-root", required=True, help="the backend/ folder of the Ledgerline tree to run")
    p.add_argument("--input", required=True)
    p.add_argument("--reference", default=None, help="default: <repo>/data/reference")
    p.add_argument("--out", required=True)
    p.add_argument("--strip-fences", action="store_true")
    p.add_argument("--limit", type=int, default=None, help="only the first N documents (smoke test)")
    p.add_argument("--replay", default=None,
                   help="a calls.jsonl from an earlier run: serve its recorded replies instead of calling the provider. "
                        "Free and offline. A call the recording doesn't have (the starter's verify pass after a crash) "
                        "gets the previous reply back, i.e. 'the verification changed nothing', marked synthetic.")
    args = p.parse_args()

    code_root = Path(args.code_root).resolve()
    input_dir = Path(args.input).resolve()
    out = Path(args.out).resolve()
    replay_path = Path(args.replay).resolve() if args.replay else None
    reference = Path(args.reference).resolve() if args.reference else code_root.parent / "data" / "reference"
    out.mkdir(parents=True, exist_ok=True)

    # The provider key lives in this repository's .env. An extracted starter tree has none, and its config would only
    # look in its own root, so load ours first (variables already set in the environment win).
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")

    os.chdir(code_root)
    sys.path.insert(0, str(code_root))  # ahead of the editable install, so the starter tree is what gets imported
    import ledgerline  # noqa: E402
    import ledgerline.extraction as extraction  # noqa: E402
    from ledgerline import db  # noqa: E402
    from ledgerline.config import get_settings  # noqa: E402
    from ledgerline.llm.base import LLMResponse  # noqa: E402
    from ledgerline.pipeline import process_document  # noqa: E402
    from ledgerline.reference import load_reference  # noqa: E402

    if Path(ledgerline.__file__).resolve().parent.parent != code_root:
        sys.exit(f"imported {ledgerline.__file__}, not the tree under {code_root}")

    settings = get_settings()
    calls: list[dict] = []
    current = {"doc": None}
    real_get_client = extraction.get_client
    replay_latency: dict[str, int] = {}

    class ReplayClient:
        def __init__(self, path: Path):
            self.by_doc: dict[str, list[dict]] = {}
            for line in path.read_text(encoding="utf-8").splitlines():
                c = json.loads(line)
                if "text" in c and not c.get("synthetic"):
                    self.by_doc.setdefault(c["document_id"], []).append(c)
            self.used: dict[str, int] = {}

        def complete(self, system, prompt, **kw):
            doc = current["doc"]
            i = self.used.get(doc, 0)
            self.used[doc] = i + 1
            recorded = self.by_doc.get(doc, [])
            if i < len(recorded):
                c = recorded[i]
                replay_latency[doc] = replay_latency.get(doc, 0) + c["latency_ms"]
                return LLMResponse(c["text"], c["model"], c["input_tokens"], c["output_tokens"], c["latency_ms"])
            if not recorded:
                raise RuntimeError(f"no recorded reply for {doc}")
            r = LLMResponse(recorded[-1]["text"], recorded[-1]["model"], 0, 0, 0)
            r.synthetic = True
            return r

    class Recorder:
        def __init__(self, inner):
            self.inner = inner

        def complete(self, system, prompt, **kw):
            started = time.perf_counter()
            try:
                r = self.inner.complete(system, prompt, **kw)
            except Exception as exc:
                calls.append({"document_id": current["doc"], "model": settings.llm_model, "error": repr(exc),
                              "input_tokens": 0, "output_tokens": 0,
                              "latency_ms": int((time.perf_counter() - started) * 1000)})
                raise
            calls.append({"document_id": current["doc"], "model": r.model, "input_tokens": r.input_tokens,
                          "output_tokens": r.output_tokens, "latency_ms": r.latency_ms,
                          "prompt_chars": len(system) + len(prompt), "text": r.text,
                          **({"synthetic": True} if getattr(r, "synthetic", False) else {})})
            if args.strip_fences:
                r = LLMResponse(_json_only(r.text), r.model, r.input_tokens, r.output_tokens, r.latency_ms)
            return r

    if args.replay:
        replayer = ReplayClient(replay_path)
        extraction.get_client = lambda: Recorder(replayer)
    else:
        extraction.get_client = lambda: Recorder(real_get_client())

    ref = load_reference(reference)
    conn = db.connect(str(Path(tempfile.mkdtemp(prefix="ledgerline-eval-")) / "eval.db"))
    docs = sorted((q for q in input_dir.iterdir() if q.is_file() and q.suffix.lower() in SUFFIXES),
                  key=lambda q: (q.stem, q.name))[: args.limit]

    with open(out / "predictions.jsonl", "w", encoding="utf-8") as f:
        for path in docs:
            current["doc"] = path.stem
            raw = path.read_bytes().decode("utf-8", errors="replace")
            started = time.perf_counter()
            row: dict = {"document_id": path.stem}
            try:
                got = process_document(conn, ref, raw, path.stem, filename=path.name)
                row["status"] = "ok"
                row.update({k: got.get(k) for k in KEEP})
            except Exception as exc:  # the starter's CLI would have skipped this document
                conn.rollback()
                row["status"] = "error"
                row["error"] = repr(exc)[:500]
                row["traceback_tail"] = traceback.format_exc().strip().splitlines()[-1][:300]
            row["wall_ms"] = int((time.perf_counter() - started) * 1000) + replay_latency.get(path.stem, 0)
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            f.flush()
            print(f"{path.stem}: {row['status']} {row['wall_ms']} ms "
                  f"{'review ' + str(row.get('review_reasons')) if row.get('needs_review') else ''}", flush=True)

    with open(out / "calls.jsonl", "w", encoding="utf-8") as f:
        for c in calls:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                                cwd=code_root).stdout.strip() or None
    except OSError:
        commit = None
    meta = {"provider": settings.llm_provider, "model": settings.llm_model, "code_root": str(code_root),
            "commit": commit, "input": str(input_dir), "documents": len(docs), "strip_fences": args.strip_fences,
            "replayed_from": str(replay_path) if replay_path else None,
            "flags": {k: v for k, v in os.environ.items() if k.startswith("LEDGERLINE_FLAG_")},
            "run_at": dt.datetime.now().isoformat(timespec="seconds")}
    (out / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(json.dumps(meta))


if __name__ == "__main__":
    main()
