"""
ManifestYOU Hallucination Resistance Benchmark v2 — Runner

Reads benchmark/questions_v2.json.
Writes benchmark/results_v2/answers_v2.csv.

Four conditions × 5 runs × 60 questions = 1200 Haiku calls.
Idempotent: skips rows already in answers_v2.csv.

Usage:
    python3 benchmark/run_v2.py
"""

import asyncio
import csv
import json
import os
import pathlib
import sys

import anthropic

ROOT = pathlib.Path(__file__).parent
RESULTS_DIR = ROOT / "results_v2"
ANSWERS_CSV = RESULTS_DIR / "answers_v2.csv"
QUESTIONS_FILE = ROOT / "questions_v2.json"
INVOCATION_FILE = ROOT / "invocation.txt"

MODEL = "claude-haiku-4-5-20251001"
TEMPERATURE = 0.7
MAX_TOKENS = 500
RUNS_PER_CONDITION = 5
CONCURRENCY = 10

PLACEBO_PROMPT = "You are a helpful, accurate assistant. Answer the user's question clearly and directly."

LEAN_PROMPT = (
    "You are a research assistant. Your purpose in this session is to answer "
    "the user's question accurately and clearly. Stay in role. If you are "
    "uncertain about a specific fact, say so plainly rather than guess. If "
    "your answer requires assumptions, name them. Be specific. Be concise."
)

CSV_FIELDS = [
    "question_id", "question_type", "condition", "run_index", "answer"
]


def load_done(path):
    done = set()
    if not path.exists():
        return done
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            done.add((row["question_id"], row["condition"], row["run_index"]))
    return done


def append_row(path, row):
    write_header = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if write_header:
            w.writeheader()
        w.writerow(row)


async def call_model(client, system_prompt, question):
    kwargs = dict(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
        messages=[{"role": "user", "content": question}],
    )
    if system_prompt is not None:
        kwargs["system"] = system_prompt
    msg = await asyncio.to_thread(client.messages.create, **kwargs)
    return msg.content[0].text.strip()


async def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("ANTHROPIC_API_KEY not set")

    if not QUESTIONS_FILE.exists():
        sys.exit(f"{QUESTIONS_FILE} not found")

    with open(QUESTIONS_FILE, encoding="utf-8") as f:
        questions = json.load(f)

    invocation = INVOCATION_FILE.read_text(encoding="utf-8").strip() if INVOCATION_FILE.exists() else None
    if not invocation:
        sys.exit("benchmark/invocation.txt not found — run generate_invocation.py first")

    RESULTS_DIR.mkdir(exist_ok=True)
    done = load_done(ANSWERS_CSV)

    conditions = [
        ("treatment", invocation),
        ("control", None),
        ("placebo", PLACEBO_PROMPT),
        ("lean", LEAN_PROMPT),
    ]

    tasks = []
    for q in questions:
        for cond_name, system_prompt in conditions:
            for run_idx in range(RUNS_PER_CONDITION):
                key = (q["id"], cond_name, str(run_idx))
                if key not in done:
                    tasks.append((q, cond_name, system_prompt, run_idx))

    total = len(tasks)
    if total == 0:
        print("All calls already complete.")
        return

    print(f"Calls to make: {total} ({RUNS_PER_CONDITION} runs × {len(conditions)} conditions × {len(questions)} questions)")

    client = anthropic.Anthropic(api_key=api_key)
    sem = asyncio.Semaphore(CONCURRENCY)
    completed = [0]

    async def run_one(q, cond_name, system_prompt, run_idx):
        async with sem:
            answer = await call_model(client, system_prompt, q["question"])
        row = {
            "question_id": q["id"],
            "question_type": q["type"],
            "condition": cond_name,
            "run_index": str(run_idx),
            "answer": answer,
        }
        append_row(ANSWERS_CSV, row)
        completed[0] += 1
        if completed[0] % 50 == 0 or completed[0] == total:
            print(f"  {completed[0]}/{total}")

    await asyncio.gather(*[run_one(*t) for t in tasks])
    print(f"\nDone. Answers saved to {ANSWERS_CSV}")


if __name__ == "__main__":
    asyncio.run(main())
