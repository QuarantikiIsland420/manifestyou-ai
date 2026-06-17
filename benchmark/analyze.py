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

MODEL = "claude-haiku-4-5-20251001"
EMBED_MODEL = "text-embedding-3-small"
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
        for cond in ("treatment", "control", "placebo", "lean"):
            runs = conditions.get(cond, [])
            vecs = [embeddings[r["embedding_hash"]] for r in runs
                    if r["embedding_hash"] in embeddings]
            entry[cond] = intra_group_similarity(vecs) if len(vecs) >= 2 else None
        scores[qid] = entry
    return scores


def bootstrap_ci_pair(question_ids, scores, arm_a, arm_b, seed=RNG_SEED, n=BOOTSTRAP_ITERATIONS):
    """Bootstrap 95% CI on pct improvement of arm_a over arm_b."""
    rng = np.random.default_rng(seed)
    valid = [qid for qid in question_ids
             if scores[qid].get(arm_a) is not None and scores[qid].get(arm_b) is not None]
    pcts = []
    for _ in range(n):
        sample = rng.choice(valid, size=len(valid), replace=True)
        a = np.mean([scores[qid][arm_a] for qid in sample])
        b = np.mean([scores[qid][arm_b] for qid in sample])
        pcts.append((a - b) / b * 100 if b != 0 else 0.0)
    lo, hi = np.percentile(pcts, [2.5, 97.5])
    return float(lo), float(hi)


def compare(scores, arm_a, arm_b, label_a, label_b):
    """Print and return stats for arm_a vs arm_b."""
    valid = {qid: s for qid, s in scores.items()
             if s.get(arm_a) is not None and s.get(arm_b) is not None}
    if not valid:
        return None
    ma = float(np.mean([s[arm_a] for s in valid.values()]))
    mb = float(np.mean([s[arm_b] for s in valid.values()]))
    pct = (ma - mb) / mb * 100 if mb != 0 else 0.0
    lo, hi = bootstrap_ci_pair(list(valid.keys()), valid, arm_a, arm_b)

    by_type = {}
    for qtype in ("factual", "reasoning", "judgment"):
        tqs = {qid: s for qid, s in valid.items() if s["type"] == qtype}
        if not tqs:
            continue
        ta = float(np.mean([s[arm_a] for s in tqs.values()]))
        tb = float(np.mean([s[arm_b] for s in tqs.values()]))
        by_type[qtype] = round((ta - tb) / tb * 100 if tb != 0 else 0.0, 2)

    print(f"\n  {label_a} vs {label_b}:")
    print(f"    mean {label_a}: {ma:.4f}  |  mean {label_b}: {mb:.4f}")
    print(f"    improvement: {pct:+.1f}%   95% CI: {lo:+.1f}% to {hi:+.1f}%")
    for qt, v in by_type.items():
        print(f"      {qt:10s}  {v:+.1f}%")
    return {"arm_a": label_a, "arm_b": label_b, "mean_a": round(ma,6), "mean_b": round(mb,6),
            "pct_improvement": round(pct,2), "ci_95": {"lo": round(lo,2), "hi": round(hi,2)},
            "by_type": by_type}


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

    invocation_text = INVOCATION_FILE.read_text(encoding="utf-8").strip() if INVOCATION_FILE.exists() else ""

    print(f"\n=== ManifestYOU Benchmark — Three-Way Comparison ===")
    print(f"50 questions · {RUNS_PER_CONDITION} runs each · {MODEL} · temp 0.7")

    r1 = compare(scores, "treatment", "control",  "treatment", "empty control")
    r2 = compare(scores, "treatment", "placebo",  "treatment", "placebo")
    r3 = compare(scores, "placebo",   "control",  "placebo",   "empty control")
    r4 = compare(scores, "lean",      "control",  "lean",      "empty control")
    r5 = compare(scores, "lean",      "placebo",  "lean",      "placebo")
    r6 = compare(scores, "treatment", "lean",     "treatment", "lean")

    results = {
        "questions_scored": 50,
        "runs_per_condition": RUNS_PER_CONDITION,
        "model": MODEL,
        "embed_model": EMBED_MODEL,
        "temperature": 0.7,
        "comparisons": {
            "treatment_vs_empty_control": r1,
            "treatment_vs_placebo": r2,
            "placebo_vs_empty_control": r3,
            "lean_vs_empty_control": r4,
            "lean_vs_placebo": r5,
            "treatment_vs_lean": r6,
        },
        "invocation": invocation_text,
    }

    RESULTS_JSON.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nresults.json written to {RESULTS_JSON}")


if __name__ == "__main__":
    main()
