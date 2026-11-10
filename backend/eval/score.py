"""Score recorded runs (from run_live.py) against the dev labels. Offline: no LLM calls, no network.

    cd backend
    .venv/bin/python eval/score.py mine_opus=../submission/eval_runs/mine_opus_dev_r1 \
                                   starter_opus=../submission/eval_runs/starter_opus_dev [--json out.json]

Several runs of the same configuration can share a name with a #suffix (mine_opus#1=… mine_opus#2=…); they are
reported per run and pooled.

What it measures, and why (see submission/EVAL_REPORT.md):
  routing     missed reviews (needed review, routed ready), lost documents (no routing at all), unnecessary reviews,
              whether every expected reason was reported, required approvals.
  fields      the handover note's number exactly as run_eval.py computes it (12 fields, failed documents skipped,
              leaked few-shot documents included), then the same with leaked documents removed and failed documents
              counted as all-wrong, then that again under my label corrections (LABEL_CORRECTIONS below).
  cost        ₹ per document from every billed call, at list price (llm/pricing.py) and finance's ₹88/$.
  latency     end-to-end process_document wall time per document: p50 and p95 (nearest rank).
  production  the dev rates projected onto the production mix in docs/PRODUCT_BRIEF.md.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ledgerline.config import USD_TO_INR, get_settings  # noqa: E402
from ledgerline.llm.pricing import cost_usd  # noqa: E402

FIELDS = ["document_type", "supplier_name", "supplier_gstin", "invoice_number", "invoice_date", "currency",
          "subtotal", "cgst", "sgst", "igst", "total", "po_number"]  # exactly run_eval.py's list
LEAKED = {"dev_001", "dev_002", "dev_003"}  # v0.3 sent these three, with their labels, as few-shot examples

# Labels I would change (EVAL_REPORT.md, "Labels I disagree with"). Each maps a field to the extra values I accept.
LABEL_CORRECTIONS: dict[str, dict[str, list[str]]] = {
    # OUTPUT_CONTRACT: invoice_number "as printed". The document prints "SIS / 26-27 / 0018"; the label is normalised.
    "dev_015": {"invoice_number": ["SIS / 26-27 / 0018"]},
}

# Production mix (docs/PRODUCT_BRIEF.md and the CFO's email).
MONTHLY_DOCS = 3000
PROBLEM_RATE = 0.13          # 26 of 200 October documents had a genuine problem
REVIEW_COST_INR = 85.0       # one manual touch
MEDIAN_EXPOSURE_INR = 41036  # dev-set median invoice total: what a missed duplicate or overbilling puts at stake
FRAUD_LOSS_INR = 380000      # last quarter's bank-change fraud


# ---------------------------------------------------------------- helpers


def norm_value(value) -> str:
    """run_eval.py's comparison, unchanged."""
    if value is None:
        return ""
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value).strip().lower()


def norm_lenient(field: str, value) -> str:
    """My comparison: names ignore case and repeated spaces; invoice numbers compare in the policy's normal form."""
    v = norm_value(value)
    if field == "supplier_name":
        return re.sub(r"\s+", " ", v)
    if field == "invoice_number":
        return re.sub(r"[\s/\-#.]", "", v.upper())
    return v


def percentile(values: list[float], p: float) -> float | None:
    """Nearest-rank percentile: the smallest value with at least p% of the data at or below it."""
    if not values:
        return None
    s = sorted(values)
    return s[max(0, math.ceil(p / 100 * len(s)) - 1)]


def binom_upper(k: int, n: int, conf: float = 0.95) -> float:
    """One-sided Clopper-Pearson upper bound on a rate after k events in n trials."""
    if n == 0:
        return 1.0
    if k >= n:
        return 1.0

    def cdf(p: float) -> float:
        return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k + 1))

    lo, hi = k / n, 1.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if cdf(mid) > 1 - conf:
            lo = mid
        else:
            hi = mid
    return hi


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_labels() -> dict[str, dict]:
    path = get_settings().data_dir / "ground_truth" / "dev.jsonl"
    return {row["document_id"]: row["expected"] for row in load_jsonl(path)}


# ---------------------------------------------------------------- scoring one run


def score_run(run_dir: Path, labels: dict[str, dict]) -> dict:
    preds = {row["document_id"]: row for row in load_jsonl(run_dir / "predictions.jsonl")}
    calls = load_jsonl(run_dir / "calls.jsonl")
    meta = json.loads((run_dir / "meta.json").read_text()) if (run_dir / "meta.json").exists() else {}
    docs = sorted(labels)

    # Routing
    missed, lost, unnecessary, reasons_short, reasons_extra, approvals_wrong = [], [], [], [], [], []
    needed = [d for d in docs if labels[d]["needs_review"]]
    clean = [d for d in docs if not labels[d]["needs_review"]]
    processing_errors = []
    for d in docs:
        exp, got = labels[d], preds.get(d)
        if got is None or got.get("status") != "ok":
            lost.append(d)
            continue
        if "processing_error" in (got.get("review_reasons") or []):
            processing_errors.append(d)
        if exp["needs_review"] and not got["needs_review"]:
            missed.append(d)
        if not exp["needs_review"] and got["needs_review"]:
            unnecessary.append(d)
        want, have = set(exp["review_reasons"]), set(got.get("review_reasons") or [])
        if want - have:
            reasons_short.append(f"{d} missing {sorted(want - have)}")
        if have - want:
            reasons_extra.append(f"{d} extra {sorted(have - want)}")
        if got.get("required_approvals") != exp["required_approvals"]:
            approvals_wrong.append(f"{d} {got.get('required_approvals')} vs {exp['required_approvals']}")

    # Fields
    def field_score(include_leaked: bool, failures_count: bool, lenient: bool) -> tuple[int, int, list[str]]:
        correct = total = 0
        wrong: list[str] = []
        for d in docs:
            if not include_leaked and d in LEAKED:
                continue
            got = preds.get(d)
            ok_doc = got is not None and got.get("status") == "ok"
            if not ok_doc and not failures_count:
                continue  # run_eval.py: `skipping …`
            for field in FIELDS:
                total += 1
                if not ok_doc:
                    continue
                exp_val, got_val = labels[d].get(field), got.get(field)
                if lenient:
                    accepted = {norm_lenient(field, exp_val)}
                    accepted |= {norm_lenient(field, v) for v in LABEL_CORRECTIONS.get(d, {}).get(field, [])}
                    hit = norm_lenient(field, got_val) in accepted
                else:
                    hit = norm_value(got_val) == norm_value(exp_val)
                correct += hit
                if not hit:
                    wrong.append(f"{d}.{field}: got {got_val!r}, label {exp_val!r}")
        return correct, total, wrong

    handover = field_score(include_leaked=True, failures_count=False, lenient=False)
    honest = field_score(include_leaked=False, failures_count=True, lenient=False)
    honest_mine = field_score(include_leaked=False, failures_count=True, lenient=True)

    # Cost and latency
    per_doc_cost: dict[str, float] = defaultdict(float)
    per_doc_calls: dict[str, int] = defaultdict(int)
    unpriced = 0
    tokens_in = tokens_out = 0
    calls = [c for c in calls if not c.get("synthetic")]  # replay stand-ins: never made, never billed
    for c in calls:
        usd = cost_usd(c["model"], c.get("input_tokens", 0), c.get("output_tokens", 0))
        if usd is None:
            unpriced += 1
            usd = 0.0
        per_doc_cost[c["document_id"]] += usd * USD_TO_INR
        per_doc_calls[c["document_id"]] += 1
        tokens_in += c.get("input_tokens", 0)
        tokens_out += c.get("output_tokens", 0)
    n_docs = len(preds) or len(docs)
    total_cost = sum(per_doc_cost.values())
    wall = [row["wall_ms"] / 1000 for row in preds.values() if "wall_ms" in row]
    llm_lat = [c["latency_ms"] / 1000 for c in calls if "latency_ms" in c]

    return {
        "run": str(run_dir), "model": meta.get("model"), "documents": n_docs,
        "needed_review": len(needed), "clean": len(clean),
        "missed_reviews": missed, "lost": lost, "unnecessary_reviews": unnecessary,
        "processing_errors": processing_errors,
        "routed_exactly": len(docs) - len(missed) - len(lost) - len(unnecessary),
        "reasons_missing": reasons_short, "reasons_extra": reasons_extra, "approvals_wrong": approvals_wrong,
        "field_accuracy_handover": handover[:2], "field_accuracy_honest": honest[:2],
        "field_accuracy_my_labels": honest_mine[:2], "field_errors_my_labels": honest_mine[2],
        "llm_calls": len(calls), "llm_calls_per_doc": len(calls) / n_docs if n_docs else 0,
        # The as-shipped starter json.loads()-ed the raw reply, so any fenced first reply means a crashed document.
        "fenced_replies": sum(1 for c in calls if str(c.get("text", "")).lstrip().startswith("```")),
        "docs_first_reply_fenced": sorted({c["document_id"] for c in calls
                                           if str(c.get("text", "")).lstrip().startswith("```")}),
        "failed_calls": sum(1 for c in calls if "error" in c), "unpriced_calls": unpriced,
        "input_tokens_per_doc": tokens_in / n_docs if n_docs else 0,
        "output_tokens_per_doc": tokens_out / n_docs if n_docs else 0,
        "cost_inr_total": total_cost, "cost_inr_per_doc": total_cost / n_docs if n_docs else 0,
        "wall_s": wall, "latency_p50_s": percentile(wall, 50), "latency_p95_s": percentile(wall, 95),
        "latency_max_s": max(wall) if wall else None,
        "llm_call_p95_s": percentile(llm_lat, 95),
    }


def production_projection(missed: int, needed: int, unnecessary: int, clean: int, cost_per_doc: float) -> dict:
    """Dev rates applied to the production mix. Uses the 95% upper bound for misses: the dev set is far too small to
    show a miss rate is zero, and a miss is the expensive error."""
    problems = MONTHLY_DOCS * PROBLEM_RATE
    fine = MONTHLY_DOCS - problems
    miss_point = missed / needed if needed else 0.0
    miss_upper = binom_upper(missed, needed)
    fp_point = unnecessary / clean if clean else 0.0
    return {
        "monthly_docs": MONTHLY_DOCS, "monthly_problem_docs": problems,
        "miss_rate_point": miss_point, "miss_rate_upper95": miss_upper,
        "missed_per_month_point": problems * miss_point, "missed_per_month_upper95": problems * miss_upper,
        "unnecessary_rate_point": fp_point, "unnecessary_per_month": fine * fp_point,
        "unnecessary_cost_inr": fine * fp_point * REVIEW_COST_INR,
        "needed_review_cost_inr": problems * (1 - miss_point) * REVIEW_COST_INR,
        "llm_cost_inr": MONTHLY_DOCS * cost_per_doc,
        "exposure_point_inr": problems * miss_point * MEDIAN_EXPOSURE_INR,
        "exposure_upper95_inr": problems * miss_upper * MEDIAN_EXPOSURE_INR,
        "reviews_one_fraud_pays_for": FRAUD_LOSS_INR / REVIEW_COST_INR,
    }


# ---------------------------------------------------------------- report


def _frac(pair) -> str:
    c, t = pair
    return f"{c}/{t} = {c / t:.1%}" if t else "n/a (0 fields scored)"


def summarise(name: str, runs: list[dict]) -> dict:
    """Pool repeated runs of one configuration."""
    walls = [w for r in runs for w in r["wall_s"]]
    needed = sum(r["needed_review"] for r in runs)
    clean = sum(r["clean"] for r in runs)
    missed = sum(len(r["missed_reviews"]) for r in runs)
    lost = sum(len(r["lost"]) for r in runs)
    unnecessary = sum(len(r["unnecessary_reviews"]) for r in runs)
    docs = sum(r["documents"] for r in runs)
    cost = sum(r["cost_inr_total"] for r in runs) / docs if docs else 0
    # Repeats re-test the same documents, so they are not independent trials: the bound uses one run's documents,
    # and counts a document as missed if any run missed it.
    ever_missed = {d for r in runs for d in r["missed_reviews"]}
    ever_unnecessary = {d for r in runs for d in r["unnecessary_reviews"]}
    production = production_projection(len(ever_missed), runs[0]["needed_review"], len(ever_unnecessary),
                                        runs[0]["clean"], cost)
    return {
        "name": name, "runs": len(runs), "model": runs[0]["model"],
        "missed": missed, "needed": needed, "lost": lost, "unnecessary": unnecessary, "clean": clean,
        "per_run_missed": [len(r["missed_reviews"]) for r in runs],
        "cost_per_doc": cost, "cost_per_doc_range": (min(r["cost_inr_per_doc"] for r in runs),
                                                     max(r["cost_inr_per_doc"] for r in runs)),
        "p50": percentile(walls, 50), "p95": percentile(walls, 95),
        "p95_range": (min(r["latency_p95_s"] or 0 for r in runs), max(r["latency_p95_s"] or 0 for r in runs)),
        "production": production,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("runs", nargs="+", help="name=run_dir (name may carry #n for repeats)")
    parser.add_argument("--json", default=None, help="also write every number to this file")
    args = parser.parse_args()
    labels = load_labels()

    scored: dict[str, list[dict]] = defaultdict(list)
    for spec in args.runs:
        name, _, path = spec.partition("=")
        result = score_run(Path(path), labels)
        result["name"] = name
        scored[name.split("#")[0]].append(result)

    for group, runs in scored.items():
        for r in runs:
            print(f"\n=== {r['name']}  ({r['model']}, {r['documents']} docs)")
            print(f"  missed reviews (needed review, routed ready): {len(r['missed_reviews'])}/{r['needed_review']}"
                  f"  {r['missed_reviews']}")
            print(f"  lost (no routing at all): {len(r['lost'])}  {r['lost'][:6]}{'…' if len(r['lost']) > 6 else ''}")
            print(f"  unnecessary reviews: {len(r['unnecessary_reviews'])}/{r['clean']}  {r['unnecessary_reviews']}")
            print(f"  processing_error: {r['processing_errors']}")
            print(f"  reasons missing: {r['reasons_missing']}")
            print(f"  reasons extra:   {r['reasons_extra']}")
            print(f"  approvals wrong: {r['approvals_wrong']}")
            print(f"  field accuracy, handover method: {_frac(r['field_accuracy_handover'])}")
            print(f"  field accuracy, no leak + failures count: {_frac(r['field_accuracy_honest'])}")
            print(f"  field accuracy, ditto under my labels: {_frac(r['field_accuracy_my_labels'])}")
            for e in r["field_errors_my_labels"][:12]:
                print(f"     - {e}")
            print(f"  fenced replies: {r['fenced_replies']} of {r['llm_calls']}")
            print(f"  calls/doc {r['llm_calls_per_doc']:.2f} (failed {r['failed_calls']}, unpriced {r['unpriced_calls']})"
                  f"  tokens/doc in {r['input_tokens_per_doc']:.0f} out {r['output_tokens_per_doc']:.0f}")
            p50 = r["latency_p50_s"] or 0
            p95 = r["latency_p95_s"] or 0
            print(f"  cost ₹{r['cost_inr_per_doc']:.2f}/doc  latency p50 {p50:.1f}s"
                  f" p95 {p95:.1f}s max {r['latency_max_s'] or 0:.1f}s")
        s = summarise(group, runs)
        pr = s["production"]
        print(f"--- {group} pooled over {s['runs']} run(s): missed {s['missed']}/{s['needed']} "
              f"(per run {s['per_run_missed']}), lost {s['lost']}, unnecessary {s['unnecessary']}/{s['clean']}, "
              f"₹{s['cost_per_doc']:.2f}/doc, p50 {s['p50'] or 0:.1f}s p95 {s['p95'] or 0:.1f}s")
        print(f"    production: miss rate ≤ {pr['miss_rate_upper95']:.1%} (95% upper) → ≤ "
              f"{pr['missed_per_month_upper95']:.0f} missed/month; unnecessary {pr['unnecessary_per_month']:.0f}/month"
              f" = ₹{pr['unnecessary_cost_inr']:,.0f}; LLM ₹{pr['llm_cost_inr']:,.0f}/month")
        scored[group] = runs
        runs.append({"_summary": s})

    if args.json:
        Path(args.json).write_text(json.dumps(scored, indent=2, default=str) + "\n")


if __name__ == "__main__":
    main()
