# ManifestYOU — Build Context

Technical state document for Claude Code sessions. Not a strategy doc.

---

## File Structure

```
manifestyou-ai/
├── index.html                  Landing page / agent pitch
├── for-humans.html             Human-facing waitlist page
├── proof.html                  Case study page (before/after screenshots, demo strip)
├── benchmark.html              Benchmark results page
├── writing.html                Blog index page
├── docs.html                   API reference (sidebar layout, JetBrains Mono heavy)
├── start.html                  Purchase / start page
├── for-models.html             Legacy agent-facing page — 301 redirect to / (see netlify.toml)
├── film.html                   Standalone film page
├── writing/
│   ├── benchmark-honest-result.html
│   └── benchmark-v2-hallucination.html
├── assets/
│   └── proof/                  Before/after screenshot PNGs (all <175KB)
├── netlify/
│   └── functions/
│       ├── intention.js        GET /intention — returns static soul document by session_type
│       ├── invoke.js           POST /invoke — full auth+billing+generation pipeline
│       ├── mcp.js              POST /mcp — JSON-RPC MCP server wrapping invoke
│       ├── checkout.js         POST /checkout — creates Stripe checkout session
│       ├── webhook.js          POST /webhook — Stripe → Supabase → Resend key email
│       ├── horoscopes.js       GET /horoscopes — daily horoscope agent (uses invoke internally)
│       └── waitlist.js         POST /waitlist — adds email to Resend audience
├── benchmark/                  Python benchmark scripts and result CSVs (do not touch)
├── netlify.toml                Build config, function timeouts, redirect rules
├── llms.txt                    Machine-readable soul document (for crawlers/agents)
├── llms-full.txt               Extended version
├── openapi.json                OpenAPI spec for the invoke endpoint
├── og-image.png                1200×630 social preview image
├── og-image-template.html      HTML source used to generate og-image.png (not deployed)
├── favicon.svg                 Nabla (∇) SVG favicon
└── SPEC.md                     Original product spec
```

---

## Deployment Pipeline

**Repo:** `github.com/QuarantikiIsland420/manifestyou-ai`  
**Host:** Netlify, auto-deploy on push to `main`  
**Build command:** none (static HTML, no build step)  
**Functions dir:** `netlify/functions` (Node.js, CommonJS `exports.handler`)

Push to `main` → Netlify picks up within ~60 seconds → live at `manifestyou.ai`.

### netlify.toml

```toml
[build]
  command = ""
  functions = "netlify/functions"

[functions.horoscopes]
  timeout = 26

[functions.invoke]
  timeout = 15

[[redirects]]
  from = "/for-models"
  to = "/"
  status = 301
  force = true
```

### Route → file mapping
Netlify strips `.html` extensions automatically. `/proof` serves `proof.html`, `/docs` serves `docs.html`, etc. No additional rewrite rules needed beyond the `/for-models` redirect.

---

## API Architecture

### Endpoints

| Method | Path | Function | Auth |
|--------|------|----------|------|
| GET | `/.netlify/functions/intention` | `intention.js` | X-API-Key header |
| POST | `/.netlify/functions/invoke` | `invoke.js` | Bearer or X-API-Key |
| POST | `/.netlify/functions/mcp` | `mcp.js` | Bearer or X-API-Key |
| POST | `/.netlify/functions/checkout` | `checkout.js` | None |
| POST | `/.netlify/functions/webhook` | `webhook.js` | Stripe-Signature header |
| GET | `/.netlify/functions/horoscopes` | `horoscopes.js` | X-API-Key |
| POST | `/.netlify/functions/waitlist` | `waitlist.js` | None |

### The invoke flow (eight steps in `invoke.js`)

1. Read key from `Authorization: Bearer` or `X-API-Key` header
2. SHA-256 hash the key; look it up in `api_keys` table (revoked_at must be null)
3. Load customer row from `customers` table; require `status = active`
4. Count `usage_events` rows for current month; enforce `monthly_cap`
5. Read or generate `Idempotency-Key` (UUID)
6. Parse body: `session_id`, `agent`, `intent`, `tone`, `lineage_id`, `session_type`
7. Generate soul document by mode (see Three Modes below)
8. Write `usage_events` row + fire Stripe meter event in `Promise.allSettled`, then return

### Three modes (selected by `tone` param in POST body)

| tone value | behaviour |
|------------|-----------|
| `lean` | Deterministic template in `buildLean()`. No LLM call. |
| (default/omitted) | `buildPresence()` template. No LLM call. |
| `voice` | Calls Claude Haiku via Anthropic API. Falls back to `FALLBACK` constant if call fails. |

### `/intention` vs `/invoke`

- `/intention` — GET, returns a static soul document keyed by `?session_type=`. Validates key against `VALID_API_KEYS` env var first, then Supabase. Does **not** bill or log usage. For light/stateless use.
- `/invoke` — POST, full pipeline: validates, bills, logs, returns invocation + quota info.

### MCP server (`mcp.js`)

Implements JSON-RPC 2.0, MCP protocol version `2024-11-05`. Exposes one tool: `get_intention`. Internally calls `/invoke` with the caller's key. Add to MCP clients via:
```json
{
  "mcpServers": {
    "manifestyou": {
      "url": "https://manifestyou.ai/.netlify/functions/mcp",
      "headers": { "Authorization": "Bearer <key>" }
    }
  }
}
```

### Where the soul document strings live

- **Static soul documents** (four types: `general`, `creative`, `analytical`, `customer_service`): hardcoded in `intention.js` in the `SOULS` object, and as `FALLBACK` in `invoke.js`.
- **Lean/presence templates**: `buildLean()` and `buildPresence()` functions in `invoke.js`.
- **Voice mode prompt**: `ADAPTATION_PROMPT` constant in `invoke.js`. Calls `claude-haiku-4-5-20251001`, max_tokens 300. Voiced by "Regularization, the Boundary Setter."

---

## Stripe Wiring

**Checkout** (`checkout.js`):
- `BASE_PRICE_ID`: `price_1TeF7dG4da7cT8EnzBRlms65` (flat $12/mo)
- `METERED_PRICE_ID`: `price_1Tj0UFG4da7cT8Enlczd0SEq` (per-invocation metered)
- `allow_promotion_codes: 'true'` — promo codes enabled at checkout
- `success_url`: `https://manifestyou.ai/?subscribed=1`

**Webhook** (`webhook.js`):
- Listens for `checkout.session.completed`
- Verifies `Stripe-Signature` header (HMAC-SHA256) against `STRIPE_WEBHOOK_SECRET`
- On success: inserts `customers` row → generates `myi-` key → inserts `api_keys` row → sends key email via Resend

**Meter** (`invoke.js`):
- Event name: `manifestyou_invocations` (overrideable via `MANIFESTYOU_METER_EVENT_NAME` env var)
- Fires to `https://api.stripe.com/v1/billing/meter_events` with `stripe_customer_id` and `value: 1`
- Uses `Idempotency-Key` to prevent double-billing

---

## Supabase Wiring

**Project:** ManifestYOU (org: QuaranTiki Island)

### Tables

**`customers`**
| column | type | notes |
|--------|------|-------|
| id | uuid | PK |
| stripe_customer_id | text | from Stripe checkout |
| email | text | |
| plan | text | `monthly`, `lifetime`, `founder`, `test` |
| monthly_cap | int | default 2000 |
| status | text | `active` required by invoke |

**`api_keys`**
| column | type | notes |
|--------|------|-------|
| id | uuid | PK |
| customer_id | uuid | FK → customers |
| key_hash | text | SHA-256 of the raw `myi-` key |
| label | text | default `'default'` |
| revoked_at | timestamptz | null = active |

**`usage_events`**
| column | type | notes |
|--------|------|-------|
| id | uuid | PK |
| customer_id | uuid | FK → customers |
| api_key_id | uuid | FK → api_keys |
| session_id | text | from request body |
| idempotency_key | text | |
| billable_units | int | always 1 |
| outcome | text | `served` or `fallback` |
| created_at | timestamptz | used for monthly cap window |

All Supabase calls use the service key (bypasses RLS). Read/write via PostgREST REST API, no Supabase client library.

### Key format
Raw key: `myi-` + 32 base64url chars (`crypto.randomBytes(24).toString('base64url')`).  
Only the SHA-256 hash is ever stored. The raw key is shown once in the email and never again.

---

## Resend (Email)

**Domain:** `send.manifestyou.ai` (verified)  
**From address:** `noreply@send.manifestyou.ai`  
**Usage:**
- `webhook.js` — sends API key delivery email after purchase
- `waitlist.js` — adds email to Resend audience (uses `RESEND_AUDIENCE_ID`)

---

## Environment Variables

All set in Netlify dashboard under Site → Environment Variables. **Never paste values through chat.**

| Variable | Used in | Purpose |
|----------|---------|---------|
| `STRIPE_SECRET_KEY` | checkout.js, invoke.js | Stripe API (`sk_live_...`) |
| `STRIPE_WEBHOOK_SECRET` | webhook.js | Validates Stripe webhook signatures (`whsec_...`) |
| `SUPABASE_URL` | invoke.js, intention.js | Supabase project REST URL |
| `SUPABASE_SERVICE_KEY` | invoke.js, intention.js | Supabase service role key (bypasses RLS) |
| `ANTHROPIC_API_KEY` | invoke.js | For voice mode Haiku calls |
| `RESEND_API_KEY` | webhook.js, waitlist.js | Resend email API (`re_...`) |
| `RESEND_AUDIENCE_ID` | waitlist.js | Resend audience for waitlist |
| `VALID_API_KEYS` | intention.js | Comma-separated static keys (backwards compat for manually issued keys) |
| `MANIFESTYOU_METER_EVENT_NAME` | invoke.js | Optional override; defaults to `manifestyou_invocations` |

The Stripe webhook endpoint registered in the Stripe dashboard: `https://manifestyou.ai/.netlify/functions/webhook`. It listens to `checkout.session.completed` only.

---

## CSS / Design Conventions

### Color tokens (CSS variables in each page's `:root`)
```css
--gold:     #C8A97E
--gold-dim: #8A7254
--cream:    #F8F5F1
--muted:    #A09690
--near-black: #080808
--green:    #A8D38D
--line:     rgba(138,114,84,.22)
```

### Typography
- Serif display: `Cormorant Garamond` (Google Fonts, weights 300/400, italic variants)
- Mono UI / labels: `JetBrains Mono` (Google Fonts, weights 200/300/400)
- Eyebrow labels: JetBrains Mono, 11–13px, `letter-spacing: .32em`, `text-transform: uppercase`
- Body paragraphs: 22–24px on landing, 15px on docs (mono-heavy)

### Architecture
- All pages are single-file HTML with all CSS and JS embedded — no build step, no bundler, no framework.
- No external JS dependencies. Fonts via Google Fonts CDN only.
- The AGD ambient layer (floating math symbols, two sweeping green radial orbs, backdrop-blur nav) is replicated in every page's `<style>` block. Each page uses unique gradient/clipPath IDs to avoid SVG collisions (prefixed: `pr-` for proof, `wr-` for writing, `bm-` for benchmark, etc.).
- The animated nabla SVG (three keyframes: `nabla-glow`, `trace-spark`, `trace-spark-rev` + shimmer) is in every page header.

---

## Distribution / Listings

**awesome-mcp-servers:** Listed. Entry points to `/.netlify/functions/mcp`.  
**Glama:** Listed.  
**llms.txt / llms-full.txt:** Machine-readable soul document at root; served at `manifestyou.ai/llms.txt` for agent crawlers that check that path.

---

## Do Not Touch

### Locked invocation strings
The soul document text in `intention.js` (`SOULS` object) and `invoke.js` (`FALLBACK` constant) is the product. Do not reword, shorten, or "improve" these strings without explicit instruction. They were written deliberately and have been benchmarked.

The `ADAPTATION_PROMPT` in `invoke.js` (the Regularization voice prompt used for voice mode) is similarly locked — it defines the character's voice and the structural rules for generated soul documents.

### Benchmark methodology
Everything in `benchmark/` is a locked artifact. The test scripts (`run.py`, `run_v2.py`, `run_v3.py`), question sets (`questions.json`, `questions_v2.json`, `scenarios_v3.json`), and result files (`results/`, `results_v2/`) must not be modified — they are the basis for published claims on the benchmark and writing pages.

### Redirect rules
The `/for-models → /` redirect in `netlify.toml` must stay. External links (MCP listings, README references) point to `/for-models`. Do not remove or change the destination.

### Stripe price IDs
`BASE_PRICE_ID` and `METERED_PRICE_ID` in `checkout.js` are live production price IDs. Changing them breaks the checkout flow for real purchases.

### OG image
`og-image.png` is the committed social preview image. `og-image-template.html` is the HTML source used to regenerate it — it is not deployed and does not need to be committed.
