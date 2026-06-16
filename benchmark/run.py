"""
ManifestYOU Consistency Benchmark — Runner

Pre-conditions:
  - benchmark/questions.json exists and is locked
  - benchmark/invocation.txt exists and is locked (run generate_invocation.py first)
  - ANTHROPIC_API_KEY and OPENAI_API_KEY are set in the environment

Usage:
    ANTHROPIC_API_KEY=... OPENAI_API_KEY=... python benchmark/run.py

Outputs:
    benchmark/results/answers.csv
    benchmark/results/embeddings.npy
"""

import asyncio
import csv
import hashlib
import json
import os
import pathlib
import sys
import time

import numpy as np

ROOT = pathlib.Path(__file__).parent
QUESTIONS_FILE = ROOT / "questions.json"
INVOCATION_FILE = ROOT / "invocation.txt"
RESULTS_DIR = ROOT / "results"
ANSWERS_CSV = RESULTS_DIR / "answers.csv"
EMBEDDINGS_NPY = RESULTS_DIR / "embeddings.npy"

MODEL = "claude-haiku-4-5-20251001"
TEMPERATURE = 0.7
MAX_TOKENS = 500
RUNS_PER_CONDITION = 10
EMBED_MODEL = "text-embedding-3-small"
EMBED_BATCH = 100
CONCURRENCY = 10  # simultaneous Haiku calls


def load_existing_answers():
    """Return set of (question_id, condition, run_index) already completed."""
    done = set()
    if not ANSWERS_CSV.exists():
        return done
    with open(ANSWERS_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            done.add((row["question_id"], row["condition"], int(row["run_index"])))
    return done


async def call_haiku(session, question, system_prompt, semaphore):
    """Single Haiku call. Returns answer text or raises."""
    import urllib.request

    api_key = os.environ["ANTHROPIC_API_KEY"]
    payload = json.dumps({
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "temperature": TEMPERATURE,
        **({"system": system_prompt} if system_prompt else {}),
        "messages": [{"role": "user", "content": question}]
    }).encode()

    async with semaphore:
        loop = asyncio.get_event_loop()
        def _call():
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=payload,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read())
        data = await loop.run_in_executor(None, _call)
    return data["content"][0]["text"].strip()


async def run_all_calls(questions, invocation, done):
    """
    Returns list of dicts with question_id, question_type, condition, run_index, answer.
    Skips any (question_id, condition, run_index) already in `done`.
    """
    semaphore = asyncio.Semaphore(CONCURRENCY)
    tasks = []

    for q in questions:
        for condition, system_prompt in [("treatment", invocation), ("control", None)]:
            for run_idx in range(RUNS_PER_CONDITION):
                key = (q["id"], condition, run_idx)
                if key in done:
                    continue
                tasks.append((q, condition, system_prompt, run_idx))

    print(f"{len(tasks)} calls to make ({len(done)} already done)")

    async def run_one(meta):
        q, condition, system_prompt, run_idx = meta
        try:
            answer = await call_haiku(None, q["question"], system_prompt, semaphore)
        except Exception as e:
            print(f"  ERROR {q['id']} {condition} run{run_idx}: {e}")
            answer = ""
        return {
            "question_id": q["id"],
            "question_type": q["type"],
            "condition": condition,
            "run_index": run_idx,
            "answer": answer,
        }

    completed = 0
    results = []
    coros = [asyncio.create_task(run_one(t)) for t in tasks]
    for coro in asyncio.as_completed(coros):
        row = await coro
        results.append(row)
        completed += 1
        if completed % 50 == 0 or completed == len(tasks):
            print(f"  {completed}/{len(tasks)} calls done")

    return results


def embed_batch(texts, api_key):
    """Embed a batch of texts using text-embedding-3-small. Returns numpy array."""
    import urllib.request

    payload = json.dumps({
        "model": EMBED_MODEL,
        "input": texts
    }).encode()
    req = urllib.request.Request(
        "https://api.openai.com/v1/embeddings",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        },
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())
    vecs = [item["embedding"] for item in sorted(data["data"], key=lambda x: x["index"])]
    return np.array(vecs, dtype=np.float32)


def sha256_hex(text):
    return hashlib.sha256(text.encode()).hexdigest()


def main():
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        if not os.environ.get(key):
            sys.exit(f"{key} not set")

    if not QUESTIONS_FILE.exists():
        sys.exit("benchmark/questions.json not found")
    if not INVOCATION_FILE.exists():
        sys.exit("benchmark/invocation.txt not found — run generate_invocation.py first")

    questions = json.loads(QUESTIONS_FILE.read_text())
    invocation = INVOCATION_FILE.read_text(encoding="utf-8").strip()
    RESULTS_DIR.mkdir(exist_ok=True)

    print(f"Questions: {len(questions)}")
    print(f"Invocation: {len(invocation.split())} words")

    # --- Model calls ---
    done = load_existing_answers()
    new_rows = asyncio.run(run_all_calls(questions, invocation, done))

    # Append new rows to CSV
    is_new = not ANSWERS_CSV.exists()
    with open(ANSWERS_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "question_id", "question_type", "condition", "run_index", "answer", "embedding_hash"
        ])
        if is_new:
            writer.writeheader()
        for row in new_rows:
            row["embedding_hash"] = sha256_hex(row["answer"])
            writer.writerow(row)

    print(f"answers.csv: {ANSWERS_CSV}")

    # --- Embeddings ---
    # Read full CSV (existing + new) to build embedding matrix
    with open(ANSWERS_CSV, newline="", encoding="utf-8") as f:
        all_rows = list(csv.DictReader(f))

    # Load existing embeddings if present
    existing_embeddings = {}
    if EMBEDDINGS_NPY.exists():
        emb_data = np.load(EMBEDDINGS_NPY, allow_pickle=True).item()
        existing_embeddings = emb_data  # dict: embedding_hash -> vector

    to_embed = [r for r in all_rows if r["embedding_hash"] not in existing_embeddings]
    print(f"Embedding {len(to_embed)} new answers...")

    openai_key = os.environ["OPENAI_API_KEY"]
    for i in range(0, len(to_embed), EMBED_BATCH):
        chunk = to_embed[i:i + EMBED_BATCH]
        texts = [r["answer"] for r in chunk]
        vecs = embed_batch(texts, openai_key)
        for row, vec in zip(chunk, vecs):
            existing_embeddings[row["embedding_hash"]] = vec
        print(f"  embedded {min(i + EMBED_BATCH, len(to_embed))}/{len(to_embed)}")
        if i + EMBED_BATCH < len(to_embed):
            time.sleep(0.5)

    np.save(EMBEDDINGS_NPY, existing_embeddings)
    print(f"embeddings.npy: {EMBEDDINGS_NPY} ({len(existing_embeddings)} vectors)")
    print("Run complete. Next: python benchmark/analyze.py")


if __name__ == "__main__":
    main()
