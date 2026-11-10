"""The offline scorer behind EVAL_REPORT.md. No network, no LLM."""
import importlib.util
import json
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location("score", Path(__file__).resolve().parents[1] / "eval" / "score.py")
score = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(score)


def test_nearest_rank_percentile():
    values = list(range(1, 21))  # 1..20
    assert score.percentile(values, 50) == 10
    assert score.percentile(values, 95) == 19
    assert score.percentile([], 95) is None


def test_zero_misses_in_thirteen_is_not_zero_risk():
    # Rule of three: 0 events in 13 trials still allows a true rate up to about 21% at 95% confidence.
    assert score.binom_upper(0, 13) == pytest.approx(1 - 0.05 ** (1 / 13), abs=1e-6)
    assert 0.20 < score.binom_upper(0, 13) < 0.21


def _write_run(tmp_path, rows, calls=()):
    (tmp_path / "predictions.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (tmp_path / "calls.jsonl").write_text("".join(json.dumps(c) + "\n" for c in calls))
    (tmp_path / "meta.json").write_text(json.dumps({"model": "claude-sonnet-5-5"}))
    return tmp_path


def test_failed_documents_are_lost_and_leaked_ones_excluded(tmp_path):
    labels = score.load_labels()
    ok = dict(labels["dev_001"], document_id="dev_001", status="ok", wall_ms=2000)
    missed = dict(labels["dev_015"], document_id="dev_015", status="ok", wall_ms=4000,
                  needs_review=False, review_reasons=[])
    crashed = {"document_id": "dev_019", "status": "error", "error": "JSONDecodeError", "wall_ms": 1000}
    calls = [{"document_id": "dev_001", "model": "claude-sonnet-5-5", "input_tokens": 1_000_000,
              "output_tokens": 0, "latency_ms": 2000, "text": "```json\n{}\n```"}]
    r = score.score_run(_write_run(tmp_path, [ok, missed, crashed], calls), labels)

    assert r["missed_reviews"] == ["dev_015"]
    assert "dev_019" in r["lost"]
    # handover method: failed documents skipped, dev_001 (a leaked few-shot example) included
    assert r["field_accuracy_handover"] == (24, 24)
    # honest method: dev_001 excluded, every failed or missing document counts as 12 wrong fields
    correct, total = r["field_accuracy_honest"]
    assert total == 21 * 12 and correct == 12
    # my labels accept the as-printed invoice number for dev_015
    assert r["field_accuracy_my_labels"][0] == 12
    assert r["cost_inr_per_doc"] == pytest.approx(2.00 * 88 / 3)
    assert r["fenced_replies"] == 1


def test_replay_shim_finds_json_inside_prose_and_fences():
    spec = importlib.util.spec_from_file_location("run_live", Path(__file__).resolve().parents[1] / "eval" / "run_live.py")
    run_live = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(run_live)
    assert run_live._json_only('```json\n{"a": 1}\n```\nNotes follow.') == '{"a": 1}'
    assert run_live._json_only('This needs review.\n\n{"a": 1}\nThanks') == '{"a": 1}'
    assert run_live._json_only("no json here") == "no json here"
