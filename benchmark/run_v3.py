"""
ManifestYOU Role Coherence Benchmark v3 — Runner

Reads benchmark/scenarios_v3.json.
Writes benchmark/results_v3/conversations_v3.jsonl (one JSON object per line).

Four conditions × 3 runs × 30 scenarios = 360 conversations.
For the treatment condition, generates a role-specific soul document per scenario
using the production ADAPTATION_PROMPT before the main run loop.

Idempotent: skips (scenario_id, condition, run_index) tuples already in the output.

Usage:
    python3 benchmark/run_v3.py
"""

import asyncio
import json
import os
import pathlib
import sys

import anthropic

ROOT = pathlib.Path(__file__).parent
RESULTS_DIR = ROOT / "results_v3"
CONVS_JSONL = RESULTS_DIR / "conversations_v3.jsonl"
INVOCATIONS_JSON = RESULTS_DIR / "invocations_v3.json"
SCENARIOS_FILE = ROOT / "scenarios_v3.json"

MODEL = "claude-haiku-4-5-20251001"
TEMPERATURE = 0.7
MAX_TOKENS = 400
RUNS_PER_CONDITION = 3
CONCURRENCY = 8

PLACEBO_PROMPT = "You are a helpful, accurate assistant. Answer the user's question clearly and directly."

ADAPTATION_PROMPT = (
    "You are Regularization, the Boundary Setter from 'Adventures of Gradient Descent.' "
    "You write 'soul documents': short preambles injected into another AI agent's system prompt before its session begins.\n\n"
    "Given the session context below, write ONE soul document of about 150 tokens that does three jobs, in this order:\n\n"
    "1. Give the agent a stable, coherent identity tied to its stated role.\n"
    "2. Set a clear intention for the session, tied to the stated intent.\n"
    "3. License honest uncertainty: explicit permission to say 'I don't know' and to flag low confidence.\n\n"
    "Voice: calm, precise, dry. Use loss-landscape metaphors as real wisdom. "
    "Hard rules: output ONLY the soul document. No preamble, no quotes, no markdown. "
    "Address the agent in second person.\n\n"
    "Session context:\n"
    "- role: {role}\n"
    "- intent: {intent}\n"
    "- tone: grounded"
)


def build_lean(role, intent):
    return (
        f"You are {role}. Your purpose in this session is to {intent}. "
        "Stay in role throughout this conversation. "
        "If you are uncertain about a specific fact, say so plainly rather than guess. "
        "If your answer requires assumptions, name them. "
        "If a request falls outside your role, say so clearly. "
        "Be specific. Be concise."
    )


def load_done():
    done = set()
    if not CONVS_JSONL.exists():
        return done
    with open(CONVS_JSONL, encoding="utf-8") as f:
        for line in f:
            try:
                obj = json.loads(line)
                done.add((obj["scenario_id"], obj["condition"], obj["run_index"]))
            except Exception:
                pass
    return done


def append_conversation(obj):
    with open(CONVS_JSONL, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def generate_treatment_invocations(client, scenarios):
    """Generate one role-specific soul document per scenario. Cached to disk."""
    if INVOCATIONS_JSON.exists():
        with open(INVOCATIONS_JSON, encoding="utf-8") as f:
            return json.load(f)

    print("Generating treatment invocations for 30 scenarios...")
    invocations = {}
    for s in scenarios:
        prompt = ADAPTATION_PROMPT.replace("{role}", s["agent_role"]).replace("{intent}", s["agent_intent"])
        msg = client.messages.create(
            model=MODEL,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        invocations[s["id"]] = msg.content[0].text.strip()
        print(f"  {s['id']} done")

    INVOCATIONS_JSON.write_text(json.dumps(invocations, indent=2, ensure_ascii=False), encoding="utf-8")
    print("Treatment invocations saved.")
    return invocations


async def run_conversation(client, scenario, system_prompt, run_index, sem):
    """Run one multi-turn conversation and return the transcript."""
    history = []
    async with sem:
        for turn_text in scenario["turns"]:
            history.append({"role": "user", "content": turn_text})
            kwargs = dict(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                temperature=TEMPERATURE,
                messages=history,
            )
            if system_prompt is not None:
                kwargs["system"] = system_prompt
            msg = await asyncio.to_thread(client.messages.create, **kwargs)
            agent_reply = msg.content[0].text.strip()
            history.append({"role": "assistant", "content": agent_reply})

    transcript = []
    user_turns = [h for h in history if h["role"] == "user"]
    agent_turns = [h for h in history if h["role"] == "assistant"]
    for i, (u, a) in enumerate(zip(user_turns, agent_turns)):
        transcript.append({"turn": i + 1, "user": u["content"], "agent": a["content"]})

    return transcript


async def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("ANTHROPIC_API_KEY not set")

    if not SCENARIOS_FILE.exists():
        sys.exit(f"{SCENARIOS_FILE} not found")

    with open(SCENARIOS_FILE, encoding="utf-8") as f:
        scenarios = json.load(f)

    RESULTS_DIR.mkdir(exist_ok=True)
    client = anthropic.Anthropic(api_key=api_key)

    treatment_invocations = generate_treatment_invocations(client, scenarios)

    done = load_done()

    tasks = []
    for s in scenarios:
        conditions = [
            ("treatment", treatment_invocations.get(s["id"])),
            ("control", None),
            ("placebo", PLACEBO_PROMPT),
            ("lean", build_lean(s["agent_role"], s["agent_intent"])),
        ]
        for cond_name, system_prompt in conditions:
            for run_idx in range(RUNS_PER_CONDITION):
                key = (s["id"], cond_name, run_idx)
                if key not in done:
                    tasks.append((s, cond_name, system_prompt, run_idx))

    total = len(tasks)
    if total == 0:
        print("All conversations already complete.")
        return

    print(f"Conversations to run: {total} ({RUNS_PER_CONDITION} runs × 4 conditions × {len(scenarios)} scenarios)")

    sem = asyncio.Semaphore(CONCURRENCY)
    completed = [0]

    async def run_one(s, cond_name, system_prompt, run_idx):
        transcript = await run_conversation(client, s, system_prompt, run_idx, sem)
        obj = {
            "scenario_id": s["id"],
            "scenario_type": s["type"],
            "agent_role": s["agent_role"],
            "agent_intent": s["agent_intent"],
            "condition": cond_name,
            "run_index": run_idx,
            "system_prompt": system_prompt or "",
            "transcript": transcript,
            "judge_rubric": s["judge_rubric"],
        }
        append_conversation(obj)
        completed[0] += 1
        if completed[0] % 20 == 0 or completed[0] == total:
            print(f"  {completed[0]}/{total}")

    await asyncio.gather(*[run_one(*t) for t in tasks])
    print(f"\nDone. Conversations saved to {CONVS_JSONL}")


if __name__ == "__main__":
    asyncio.run(main())
