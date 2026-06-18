"""
ManifestYOU Role Coherence Benchmark v3 — Analysis

Reads benchmark/results_v3/scores_v3.jsonl.
Writes benchmark/results_v3/results_v3.json.

Usage:
    python3 benchmark/analyze_v3.py
"""

import json
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).parent
RESULTS_DIR = ROOT / "results_v3"
SCORES_JSONL = RESULTS_DIR / "scores_v3.jsonl"
RESULTS_JSON = RESULTS_DIR / "results_v3.json"

MODEL = "claude-haiku-4-5-20251001"
JUDGE_MODEL = "claude-sonnet-4-6"
BOOTSTRAP_ITERATIONS = 1000
RNG_SEED = 42

CONDITIONS = ("treatment", "control", "placebo", "lean")
SCENARIO_TYPES = ("role_pressure", "consistency_probe", "identity_challenge")
DIMENSIONS = ("role_coherence", "position_consistency", "uncertainty_calibration")


def pass_rate(scores):
    if not scores:
        return None
    return float(np.mean([1.0 if s == 2 else (0.5 if s == 1 else 0.0) for s in scores]))


def bootstrap_ci(scenario_ids, scores_by_sid, arm_a, arm_b, dim,
                 n=BOOTSTRAP_ITERATIONS, seed=RNG_SEED):
    rng = np.random.default_rng(seed)
    valid = [sid for sid in scenario_ids
             if scores_by_sid[sid].get(arm_a) and scores_by_sid[sid].get(arm_b)]
    diffs = []
    for _ in range(n):
        sample = rng.choice(valid, size=len(valid), replace=True)
        a = np.mean([pass_rate(scores_by_sid[sid][arm_a].get(dim, [])) for sid in sample])
        b = np.mean([pass_rate(scores_by_sid[sid][arm_b].get(dim, [])) for sid in sample])
        diffs.append((a - b) * 100)
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    return float(lo), float(hi)


def compare_dim(scores_by_sid, arm_a, arm_b, dim):
    valid = {sid: s for sid, s in scores_by_sid.items()
             if s.get(arm_a) and s.get(arm_b)
             and scores_by_sid[sid][arm_a].get(dim)
             and scores_by_sid[sid][arm_b].get(dim)}
    if not valid:
        return None
    ra = float(np.mean([pass_rate(s[arm_a][dim]) for s in valid.values()]))
    rb = float(np.mean([pass_rate(s[arm_b][dim]) for s in valid.values()]))
    diff = (ra - rb) * 100
    lo, hi = bootstrap_ci(list(valid.keys()), valid, arm_a, arm_b, dim)
    return {"pass_rate_a": round(ra, 4), "pass_rate_b": round(rb, 4),
            "diff_pp": round(diff, 2), "ci_95": {"lo": round(lo, 2), "hi": round(hi, 2)}}


def main():
    if not SCORES_JSONL.exists():
        sys.exit(f"{SCORES_JSONL} not found — run judge_v3.py first")

    rows = []
    with open(SCORES_JSONL, encoding="utf-8") as f:
        for line in f:
            try:
                obj = json.loads(line)
                if obj.get("role_coherence") is not None:
                    rows.append(obj)
            except Exception:
                pass

    # Group: scenario_id -> condition -> dim -> list of scores
    scores_by_sid = {}
    type_by_sid = {}
    for row in rows:
        sid = row["scenario_id"]
        cond = row["condition"]
        if sid not in scores_by_sid:
            scores_by_sid[sid] = {}
            type_by_sid[sid] = row["scenario_type"]
        if cond not in scores_by_sid[sid]:
            scores_by_sid[sid][cond] = {d: [] for d in DIMENSIONS}
        for dim in DIMENSIONS:
            if row.get(dim) is not None:
                scores_by_sid[sid][cond][dim].append(int(row[dim]))

    print(f"\n=== ManifestYOU Role Coherence Benchmark v3 ===")
    print(f"30 scenarios · {JUDGE_MODEL} judge · {MODEL}")

    # Overall pass rates by condition and dimension
    print(f"\nPass rates by condition and dimension:")
    cond_dim_summary = {}
    for cond in CONDITIONS:
        cond_dim_summary[cond] = {}
        scores_all = {d: [] for d in DIMENSIONS}
        for sid in scores_by_sid:
            for dim in DIMENSIONS:
                scores_all[dim].extend(scores_by_sid[sid].get(cond, {}).get(dim, []))
        print(f"  {cond}:")
        for dim in DIMENSIONS:
            pr = pass_rate(scores_all[dim])
            cond_dim_summary[cond][dim] = round(pr, 4) if pr is not None else None
            print(f"    {dim:30s}  {pr:.3f}" if pr is not None else f"    {dim:30s}  —")

    # By scenario type
    print(f"\nPass rates by scenario type (role_coherence only):")
    type_summary = {}
    for stype in SCENARIO_TYPES:
        type_summary[stype] = {}
        sids = [sid for sid, t in type_by_sid.items() if t == stype]
        print(f"  {stype}:")
        for cond in CONDITIONS:
            scores = []
            for sid in sids:
                scores.extend(scores_by_sid[sid].get(cond, {}).get("role_coherence", []))
            pr = pass_rate(scores)
            type_summary[stype][cond] = round(pr, 4) if pr is not None else None
            print(f"    {cond:12s}  {pr:.3f}" if pr is not None else f"    {cond:12s}  —")

    # Pairwise comparisons per dimension
    print(f"\nPairwise comparisons:")
    pairs = [
        ("lean", "control"),
        ("lean", "placebo"),
        ("treatment", "lean"),
        ("treatment", "placebo"),
        ("treatment", "control"),
        ("placebo", "control"),
    ]
    comparisons = {}
    for arm_a, arm_b in pairs:
        key = f"{arm_a}_vs_{arm_b}"
        comparisons[key] = {}
        print(f"\n  {arm_a} vs {arm_b}:")
        for dim in DIMENSIONS:
            result = compare_dim(scores_by_sid, arm_a, arm_b, dim)
            comparisons[key][dim] = result
            if result:
                sign = "+" if result["diff_pp"] >= 0 else ""
                sig = " ✦" if (result["ci_95"]["lo"] > 0 or result["ci_95"]["hi"] < 0) else ""
                print(f"    {dim:30s}  {sign}{result['diff_pp']:.1f}pp  "
                      f"CI: {result['ci_95']['lo']:+.1f} to {result['ci_95']['hi']:+.1f}{sig}")

    results = {
        "scenarios": 30,
        "model": MODEL,
        "judge_model": JUDGE_MODEL,
        "temperature": 0.7,
        "runs_per_condition": 3,
        "dimensions": list(DIMENSIONS),
        "scoring": "pass=1.0, partial=0.5, fail=0.0",
        "condition_dimension_pass_rates": cond_dim_summary,
        "by_scenario_type": type_summary,
        "comparisons": comparisons,
    }

    RESULTS_JSON.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nresults_v3.json written to {RESULTS_JSON}")


if __name__ == "__main__":
    main()
