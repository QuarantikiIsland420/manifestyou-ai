"""
ManifestYOU Consistency Benchmark — Analysis

Reads benchmark/results/answers.csv and benchmark/results/embeddings.npy.
Writes benchmark/results/results.json.

Usage:
    python benchmark/analyze.py
"""

import csv
import json
import pathlib
import sys
from itertools import combinations

import numpy as np

ROOT = pathlib.Path(__file__).parent
RESULTS_DIR = ROOT / "results"
ANSWERS_CSV = RESULTS_DIR / "answers.csv"
EMBEDDINGS_NPY = RESULTS_DIR / "embeddings.npy"
RESULTS_JSON = RESULTS_DIR / "results.json"
INVOCATION_FILE = ROOT / "invocation.txt"

BOOTSTRAP_ITERATIONS = 1000
RUNS_PER_CONDITION = 10
RNG_SEED = 42


def cosine_sim(a, b):
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def intra_group_similarity(vectors):
    """Mean pairwise cosine similarity across all C(n,2) pairs."""
    pairs = list(combinations(range(len(vectors)), 2))
    if not pairs:
        return 0.0
    sims = [cosine_sim(vectors[i], vectors[j]) for i, j in pairs]
    return float(np.mean(sims))


def score_questions(rows_by_question, embeddings):
    """
    Returns dict: question_id -> {"treatment": float, "control": float, "type": str}
    """
    scores = {}
    for qid, conditions in rows_by_question.items():
        entry = {"type": conditions.get("_type", "unknown")}
        for cond in ("treatment", "control"):
            runs = conditions.get(cond, [])
            vecs = [embeddings[r["embedding_hash"]] for r in runs
                    if r["embedding_hash"] in embeddings]
            entry[cond] = intra_group_similarity(vecs) if len(vecs) >= 2 else None
        scores[qid] = entry
    return scores


def bootstrap_ci(question_ids, scores, seed=RNG_SEED, n=BOOTSTRAP_ITERATIONS):
    """Bootstrap 95% CI on pct_improvement by resampling questions."""
    rng = np.random.default_rng(seed)
    pct_improvements = []
    ids = [qid for qid in question_ids
           if scores[qid]["treatment"] is not None and scores[qid]["control"] is not None]
    for _ in range(n):
        sample = rng.choice(ids, size=len(ids), replace=True)
        t = np.mean([scores[qid]["treatment"] for qid in sample])
        c = np.mean([scores[qid]["control"] for qid in sample])
        pct_improvements.append((t - c) / c * 100 if c != 0 else 0.0)
    lo, hi = np.percentile(pct_improvements, [2.5, 97.5])
    return float(lo), float(hi)


def main():
    for f in (ANSWERS_CSV, EMBEDDINGS_NPY):
        if not f.exists():
            sys.exit(f"{f} not found — run run.py first")

    with open(ANSWERS_CSV, newline="", encoding="utf-8") as f:
        all_rows = list(csv.DictReader(f))

    embeddings = np.load(EMBEDDINGS_NPY, allow_pickle=True).item()

    # Group rows: question_id -> condition -> list of rows
    rows_by_question = {}
    for row in all_rows:
        qid = row["question_id"]
        cond = row["condition"]
        if qid not in rows_by_question:
            rows_by_question[qid] = {"_type": row["question_type"]}
        rows_by_question[qid].setdefault(cond, []).append(row)

    scores = score_questions(rows_by_question, embeddings)

    valid = {qid: s for qid, s in scores.items()
             if s["treatment"] is not None and s["control"] is not None}

    if not valid:
        sys.exit("No valid scored questions — check embeddings.npy")

    mean_t = float(np.mean([s["treatment"] for s in valid.values()]))
    mean_c = float(np.mean([s["control"] for s in valid.values()]))
    pct_improvement = (mean_t - mean_c) / mean_c * 100 if mean_c != 0 else 0.0

    ci_lo, ci_hi = bootstrap_ci(list(valid.keys()), valid)

    # Per-type breakdown
    by_type = {}
    for qtype in ("factual", "reasoning", "judgment"):
        type_qs = {qid: s for qid, s in valid.items() if s["type"] == qtype}
        if not type_qs:
            continue
        t_vals = [s["treatment"] for s in type_qs.values()]
        c_vals = [s["control"] for s in type_qs.values()]
        mt, mc = float(np.mean(t_vals)), float(np.mean(c_vals))
        by_type[qtype] = {
            "n": len(type_qs),
            "mean_treatment": round(mt, 6),
            "mean_control": round(mc, 6),
            "pct_improvement": round((mt - mc) / mc * 100 if mc != 0 else 0.0, 2),
        }

    invocation_text = INVOCATION_FILE.read_text(encoding="utf-8").strip() if INVOCATION_FILE.exists() else ""

    results = {
        "questions_scored": len(valid),
        "runs_per_condition": RUNS_PER_CONDITION,
        "model": "claude-haiku-4-5-20251001",
        "embed_model": "text-embedding-3-small",
        "temperature": 0.7,
        "mean_treatment": round(mean_t, 6),
        "mean_control": round(mean_c, 6),
        "pct_improvement": round(pct_improvement, 2),
        "ci_95": {"lo": round(ci_lo, 2), "hi": round(ci_hi, 2)},
        "by_type": by_type,
        "invocation": invocation_text,
    }

    RESULTS_JSON.write_text(json.dumps(results, indent=2), encoding="utf-8")

    print(f"\n=== ManifestYOU Benchmark Results ===")
    print(f"Questions scored: {len(valid)}/50")
    print(f"Mean consistency (treatment): {mean_t:.4f}")
    print(f"Mean consistency (control):   {mean_c:.4f}")
    print(f"Improvement: {pct_improvement:+.1f}%  (95% CI: {ci_lo:+.1f}% to {ci_hi:+.1f}%)")
    print()
    for qtype, bt in by_type.items():
        print(f"  {qtype:10s}  {bt['pct_improvement']:+.1f}%  (n={bt['n']})")
    print(f"\nresults.json written to {RESULTS_JSON}")

    headline = (
        f"On 50 questions run 10 times each, agents using a ManifestYOU invocation "
        f"were {pct_improvement:.1f}% more consistent (by mean intra-question embedding similarity, "
        f"95% CI {ci_lo:.1f}% to {ci_hi:.1f}%) than agents with no system prompt."
    )
    print(f"\nHeadline:\n{headline}")


if __name__ == "__main__":
    main()
