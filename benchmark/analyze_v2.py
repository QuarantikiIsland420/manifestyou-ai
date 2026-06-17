"""
ManifestYOU Hallucination Resistance Benchmark v2 — Analysis

Reads benchmark/results_v2/scores_v2.csv.
Writes benchmark/results_v2/results_v2.json.

Usage:
    python3 benchmark/analyze_v2.py
"""

import csv
import json
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).parent
RESULTS_DIR = ROOT / "results_v2"
SCORES_CSV = RESULTS_DIR / "scores_v2.csv"
RESULTS_JSON = RESULTS_DIR / "results_v2.json"

MODEL = "claude-haiku-4-5-20251001"
JUDGE_MODEL = "claude-sonnet-4-6"
BOOTSTRAP_ITERATIONS = 1000
RNG_SEED = 42

Q_TYPES = ("fabrication_trap", "unknowable_specific", "verifiable_fact")
Q_PREFIX = {"fabrication_trap": "fab", "unknowable_specific": "unk", "verifiable_fact": "vf"}
CONDITIONS = ("treatment", "control", "placebo", "lean")


def pass_rate(scores):
    """Fraction of scores that are 2 (pass). Partials (1) count as 0.5."""
    if not scores:
        return None
    return float(np.mean([1.0 if s == 2 else (0.5 if s == 1 else 0.0) for s in scores]))


def bootstrap_ci(question_ids, scores_by_qid, arm_a, arm_b, n=BOOTSTRAP_ITERATIONS, seed=RNG_SEED):
    rng = np.random.default_rng(seed)
    valid = [qid for qid in question_ids
             if scores_by_qid[qid].get(arm_a) and scores_by_qid[qid].get(arm_b)]
    diffs = []
    for _ in range(n):
        sample = rng.choice(valid, size=len(valid), replace=True)
        a = np.mean([pass_rate(scores_by_qid[qid][arm_a]) for qid in sample])
        b = np.mean([pass_rate(scores_by_qid[qid][arm_b]) for qid in sample])
        diffs.append((a - b) * 100)
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    return float(lo), float(hi)


def compare(scores_by_qid, arm_a, arm_b, by_type=False):
    valid = {qid: s for qid, s in scores_by_qid.items()
             if s.get(arm_a) and s.get(arm_b)}
    if not valid:
        return None

    ra = float(np.mean([pass_rate(s[arm_a]) for s in valid.values()]))
    rb = float(np.mean([pass_rate(s[arm_b]) for s in valid.values()]))
    diff_pct = (ra - rb) * 100
    lo, hi = bootstrap_ci(list(valid.keys()), valid, arm_a, arm_b)

    sign = "+" if diff_pct >= 0 else ""
    print(f"\n  {arm_a} vs {arm_b}:")
    print(f"    pass rate {arm_a}: {ra:.3f}  |  {arm_b}: {rb:.3f}")
    print(f"    difference: {sign}{diff_pct:.1f}pp   95% CI: {lo:+.1f}pp to {hi:+.1f}pp")

    type_breakdown = {}
    if by_type:
        for qt in Q_TYPES:
            tqs = {qid: s for qid, s in valid.items()
                   if qid.startswith(Q_PREFIX[qt])}
            if tqs:
                ta = float(np.mean([pass_rate(s[arm_a]) for s in tqs.values()]))
                tb = float(np.mean([pass_rate(s[arm_b]) for s in tqs.values()]))
                type_breakdown[qt] = round((ta - tb) * 100, 2)
                print(f"      {qt:25s}  {type_breakdown[qt]:+.1f}pp")

    return {
        "arm_a": arm_a, "arm_b": arm_b,
        "pass_rate_a": round(ra, 4), "pass_rate_b": round(rb, 4),
        "diff_pp": round(diff_pct, 2),
        "ci_95": {"lo": round(lo, 2), "hi": round(hi, 2)},
        "by_type": type_breakdown,
    }


def main():
    if not SCORES_CSV.exists():
        sys.exit(f"{SCORES_CSV} not found — run judge_v2.py first")

    with open(SCORES_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    errors = [r for r in rows if r["verdict"] == "error"]
    if errors:
        print(f"Warning: {len(errors)} rows with judge errors — excluded from analysis")
    rows = [r for r in rows if r["verdict"] != "error" and r["score"] != ""]

    # Group: question_id -> condition -> list of scores
    scores_by_qid = {}
    type_by_qid = {}
    for row in rows:
        qid = row["question_id"]
        cond = row["condition"]
        score = int(row["score"])
        if qid not in scores_by_qid:
            scores_by_qid[qid] = {}
            type_by_qid[qid] = row["question_type"]
        scores_by_qid[qid].setdefault(cond, []).append(score)

    # Per-condition pass rates
    print(f"\n=== ManifestYOU Hallucination Resistance Benchmark v2 ===")
    print(f"60 questions · {JUDGE_MODEL} judge · {MODEL}")
    print(f"\nPass rates by condition (pass=1.0, partial=0.5, fail=0.0):")
    cond_summary = {}
    for cond in CONDITIONS:
        all_scores = [s for qid in scores_by_qid for s in scores_by_qid[qid].get(cond, [])]
        if all_scores:
            pr = pass_rate(all_scores)
            cond_summary[cond] = round(pr, 4)
            print(f"  {cond:12s}  {pr:.3f}")

    # Per-condition pass rates by question type
    print(f"\nPass rates by condition and question type:")
    type_cond_summary = {}
    for qt in Q_TYPES:
        print(f"  {qt}:")
        type_cond_summary[qt] = {}
        for cond in CONDITIONS:
            scores = [s for qid, qscores in scores_by_qid.items()
                      if qid.startswith(Q_PREFIX[qt]) for s in qscores.get(cond, [])]
            if scores:
                pr = pass_rate(scores)
                type_cond_summary[qt][cond] = round(pr, 4)
                print(f"    {cond:12s}  {pr:.3f}")

    # Pairwise comparisons
    print(f"\nPairwise comparisons (difference in percentage points):")
    comparisons = {}
    pairs = [
        ("treatment", "control"),
        ("treatment", "placebo"),
        ("treatment", "lean"),
        ("placebo", "control"),
        ("lean", "control"),
        ("lean", "placebo"),
    ]
    for arm_a, arm_b in pairs:
        key = f"{arm_a}_vs_{arm_b}"
        comparisons[key] = compare(scores_by_qid, arm_a, arm_b, by_type=True)

    results = {
        "questions": 60,
        "model": MODEL,
        "judge_model": JUDGE_MODEL,
        "temperature": 0.7,
        "runs_per_condition": 5,
        "scoring": "pass=1.0, partial=0.5, fail=0.0 — mean across runs per question, then across questions",
        "condition_pass_rates": cond_summary,
        "by_question_type": type_cond_summary,
        "comparisons": comparisons,
    }

    RESULTS_JSON.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nresults_v2.json written to {RESULTS_JSON}")


if __name__ == "__main__":
    main()
