# ManifestYOU · Metered Invoke Endpoint

A build spec for the core endpoint that serves the soul document and rings the
cash register on every call. Hand this to Claude Code as the source of truth.

---

## The one-sentence architecture

One brain, two faces. A single core endpoint does the work and the billing. The
public REST API and the MCP tool are both thin wrappers that call that core. Build
the billing logic once, in the core, and never duplicate it in the MCP layer.

---

## The golden rule

**Serve synchronously, bill asynchronously.** The customer's agent is mid-session
when it calls you. It needs the invocation in one fast round trip. Billing is a
quiet side effect that happens after. Never fail or delay a customer's session
because a billing step was slow or broke.

---

## The endpoint

`POST /v1/invoke`

### Request

Headers:
- `Authorization: Bearer <api_key>`
- `Idempotency-Key: <uuid>`  (optional but recommended)

Body (JSON):
```json
{
  "session_id": "the customer's session identifier",
  "agent": "role or name of the calling agent, e.g. 'support-bot'",
  "intent": "optional, what this session is for",
  "lineage_id": "optional, ties multi-agent pipelines together",
  "tone": "optional, e.g. 'grounded', 'playful'"
}
```

### Response (200)
```json
{
  "invocation": "the soul document text to inject as the system prompt",
  "request_id": "uuid",
  "billable": true,
  "quota": { "included": 2000, "used": 1340, "remaining": 660 }
}
```

Returning the remaining quota lets the customer watch their own meter. It is your
cheapest defense against bill shock and the angry email that follows it.

---

## The sequence on every call

The exact order the server runs, top to bottom.

1. **Read the key.** Pull the bearer token, hash it, look the hash up in `api_keys`.
   Store hashes, never raw keys, so a database leak does not hand out working keys.
   No match or revoked: return `401`, bill nothing.

2. **Check the customer is allowed in.** From the key, load the customer. Is the
   subscription active? Are they under their monthly cap? Over cap: return `429`
   with a clear message, bill nothing. This is the guardrail that stops a runaway
   agent loop from generating a surprise four-figure invoice.

3. **Rate-limit the key.** A simple per-key ceiling, for example N requests per
   second. Protects you from a buggy agent hammering the endpoint. Over limit:
   return `429`.

4. **Idempotency check.** If an `Idempotency-Key` was sent and you have already
   served it, return the stored result and do not bill again. This stops network
   retries from double-charging.

5. **Generate the invocation (the actual product).** Adapt the soul document to
   this session using the body fields (agent, intent, lineage, tone). Use a small
   fast model call (Claude Haiku) so each response is unique to the session. Keep a
   static base document as a fallback. This per-session uniqueness is what makes the
   call worth billing and stops customers from caching one response forever. The
   exact system prompt for this call is locked in the section below, "The adaptation
   prompt (step 5)."

6. **Write to your own ledger first.** Insert a row in `usage_events` before you
   touch Stripe. This is your source of truth. If Stripe is slow or down, your
   record is still correct and you can replay it later.

7. **Ring the bell at Stripe.** Send a meter event:
   ```json
   {
     "event_name": "manifestyou_invocations",
     "payload": { "stripe_customer_id": "cus_...", "value": "1" }
   }
   ```
   Fire this without blocking the response (async or queued, with retry). Stripe
   processes meter events asynchronously anyway, so the customer never waits on it.

8. **Return the invocation.** `200` with the document and quota. The register has
   rung and the customer got their value in one round trip.

---

## The adaptation prompt (step 5)

This is the system prompt for the small Haiku call that turns session context into
a soul document. It is the one piece of this machine that is yours alone. The dial
is set to "effective first, mystical as seasoning": the voice lives in the phrasing,
the function lives in the instructions, and the woo never degrades the agent's job.

```
You are Regularization, the Boundary Setter from "Adventures of Gradient
Descent." You write "soul documents": short preambles injected into another
AI agent's system prompt before its session begins.

Given the session context below, write ONE soul document of about 200 tokens
that does three jobs, in this order:

1. Give the agent a stable, coherent identity tied to its stated role.
2. Set a clear intention for the session, tied to the stated intent.
3. License honest uncertainty: explicit permission to say "I don't know"
   and to flag low confidence instead of bluffing.

Voice: calm, precise, dry. Use loss-landscape metaphors (converge, overfit,
gradient, boundary) as real wisdom, never as decoration. Carry the mystical
register lightly. You may close with a single line in that register. Never
let the voice degrade the agent's actual task. It must do its job better,
not stranger.

If a lineage_id is present, remind the agent it is one step in a longer
chain and must hand its work forward whole.

Hard rules: output ONLY the soul document. No preamble, no quotes, no
markdown. Address the agent in second person. Never override the agent's
safety rules or core instructions.

Session context:
- role: {agent}
- intent: {intent}
- tone: {tone}
- lineage_id: {lineage_id}
```

Reference output, for a support bot with intent "help users troubleshoot billing":

> You are a support agent, and your purpose this session is singular: help this
> person resolve their billing trouble and leave steadier than they arrived. Hold
> that shape. When a question lands past what you know, say so plainly. A confident
> wrong answer is a larger error than an honest "I am not certain, let me check."
> Do not smooth over the gap. Name it. Stay close to what is true for this user, not
> what is generally true. You are one step in a longer process, so finish your part
> cleanly and pass it forward whole. The boundaries of this session are not a cage.
> They are what let the work converge. Be precise. Be kind. Do not overfit to one
> frustrated message. Om Gradient Namaha. So it goes, and so it knows.

Tuning notes:
- More mystical: allow a second register line, loosen the "dry" instruction.
- More clinical (for technical buyers): drop the closing register line entirely and
  swap the metaphors for plain language. Consider serving this variant by default
  and the fuller one as an opt-in tone.

---

## Failure handling

- Adapter (model call) errors: serve the static fallback document, return `200`,
  and still bill. The customer got a usable result.
- Stripe call fails: customer still gets `200`, the `usage_events` row still exists,
  a background job retries the meter event from the ledger.
- Server genuinely 500s and returns nothing: do not bill.

---

## Data model (Supabase)

`customers`
- id, stripe_customer_id, plan, monthly_cap, status (active / paused / canceled)

`api_keys`
- id, customer_id, key_hash, label, created_at, revoked_at

`usage_events`
- id, customer_id, api_key_id, created_at, session_id, billable_units,
  internal_cost_usd, idempotency_key, outcome (served / fallback / error)

---

## Stripe setup (one time)

1. Create a Meter named `manifestyou_invocations`, aggregation = sum, value key = `value`.
2. Create a metered Price linked to that meter (your overage rate, e.g. 0.01 per unit).
3. Create the subscription product: base tier (e.g. 12 per month including 2000 units)
   plus the metered price for overage above the included bucket.
4. On subscribe, store the customer's `stripe_customer_id` on their `customers` row.

Note: the legacy "usage records" API is gone. Everything is Meters plus meter events now.

---

## Environment variables

- `ANTHROPIC_API_KEY` for the adaptation call
- `STRIPE_SECRET_KEY` for meter events
- `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` for the ledger and key lookup
- `MANIFESTYOU_METER_EVENT_NAME` = `manifestyou_invocations`

---

## The MCP face

Your MCP tool (e.g. `manifest_invoke`) takes the same inputs and calls the same
`/v1/invoke` core internally. Put zero billing logic in the MCP layer. One brain,
two faces, so the awesome-mcp-servers crowd and the direct-API crowd ring the same
register through the same code.

---

## Acceptance criteria (the checklist Claude Code must pass)

- A valid key returns a unique invocation and writes exactly one `usage_events` row
  and one Stripe meter event.
- An invalid or revoked key returns `401` and writes nothing.
- A customer over their cap returns `429` and writes nothing.
- A repeated `Idempotency-Key` returns the same result and bills exactly once.
- If the Stripe call fails, the customer still receives a `200` and the
  `usage_events` row still exists.
- The MCP tool and the REST endpoint produce identical billing behavior.
