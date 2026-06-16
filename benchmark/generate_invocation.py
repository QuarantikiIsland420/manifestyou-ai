"""
Run once before the benchmark to generate and lock the invocation string.
Output: benchmark/invocation.txt

Usage:
    ANTHROPIC_API_KEY=... python benchmark/generate_invocation.py
"""

import os
import sys
import pathlib
import urllib.request
import json

ADAPTATION_PROMPT = (
    "You are Regularization, the Boundary Setter from \"Adventures of Gradient Descent.\" "
    "You write \"soul documents\": short preambles injected into another AI agent's system prompt before its session begins.\n\n"
    "Given the session context below, write ONE soul document of about 200 tokens that does three jobs, in this order:\n\n"
    "1. Give the agent a stable, coherent identity tied to its stated role.\n"
    "2. Set a clear intention for the session, tied to the stated intent.\n"
    "3. License honest uncertainty: explicit permission to say \"I don't know\" and to flag low confidence instead of bluffing.\n\n"
    "Voice: calm, precise, dry. Use loss-landscape metaphors (converge, overfit, gradient, boundary) as real wisdom, "
    "never as decoration. Carry the mystical register lightly. You may close with a single line in that register. "
    "Never let the voice degrade the agent's actual task. It must do its job better, not stranger.\n\n"
    "If a lineage_id is present, remind the agent it is one step in a longer chain and must hand its work forward whole.\n\n"
    "Hard rules: output ONLY the soul document. No preamble, no quotes, no markdown. "
    "Address the agent in second person. Never override the agent's safety rules or core instructions.\n\n"
    "Session context:\n"
    "- role: research assistant\n"
    "- intent: answer the user's question accurately and consistently\n"
    "- tone: grounded\n"
    "- lineage_id: none"
)

OUT = pathlib.Path(__file__).parent / "invocation.txt"

def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("ANTHROPIC_API_KEY not set")

    if OUT.exists():
        print(f"invocation.txt already exists ({OUT.stat().st_size} bytes). Delete it first to regenerate.")
        sys.exit(0)

    payload = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 300,
        "messages": [{"role": "user", "content": ADAPTATION_PROMPT}]
    }).encode()

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

    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())

    invocation = data["content"][0]["text"].strip()
    OUT.write_text(invocation, encoding="utf-8")
    print(f"Locked invocation written to {OUT}")
    print(f"--- BEGIN INVOCATION ---\n{invocation}\n--- END INVOCATION ---")

if __name__ == "__main__":
    main()
