# BI Escales — Pay Only If We Sail

PayPal AI Hackathon 2026 project by Association Berry-Mappemonde.

A supporter's PayPal pledge is **authorized** (Orders v2 `intent=AUTHORIZE`), and **captured** only once the AI Captain has reviewed the evidence for a voyage stop and a human treasurer has approved it; otherwise it is **voided**. The AI Captain proposes, it never executes.

- `bi-escales/` — FastAPI backend: pledges (authorize / capture / void), milestones and evidence, AI Captain, audit journal. Partner integrations (e.g. PayPal Agent Toolkit) are optional modules behind environment flags, off by default.
- `naviguide-escales/` — NAVIGUIDE voyage simulator (snapshot, no history).

Status: in development. PayPal **sandbox only**; no real money moves. Planned departure: 15 May 2027.

## Void id

PayPal's void of an authorization usually returns no id (HTTP 204). `void_id` is then the authorization id, `void_id_source` is `authorization`, and `void_note` says so. A vault release with no id uses the vault id the same way. When the void body contains an `id`, that value is stored and `void_id_source` is `paypal`, even if it is the same string as the authorization id. `voided_at` is the voyage clock (`ESCALES_CLOCK_NOW`, or real UTC when that variable is unset), not a second clock.

## NIM model

`NIM_MODEL` defaults to `private/nvidia/nemotron-3.5-super-120b-a12b`. On Render the variable is `sync: false`, so the dashboard value overrides that default and is the id sent on the primary hop. The old id `nvidia/nemotron-3.5-super-vl-120b-a12b` returns 404 at NVIDIA, and so does `nvidia/nemotron-3.5-super-120b-a12b` (the same id without the `private/` prefix). The code refuses those two ids, and also refuses `nvidia/nemotron-3.5-lightning-30b-a3b` when it is set as `NIM_MODEL`, and sends the private Super id instead. The log and `model_source.reason` name the refused id. They never include the API key. If the primary hop still fails (HTTP 404 or a timeout), the `nim_fallback` hop answers with `nvidia/nemotron-3.5-lightning-30b-a3b`. `model_source.provider` is then `nim_fallback`, and `model_source.reason` says which id was sent and whether the cause was `http_404` or `timeout`. Set Render `NIM_MODEL` to `private/nvidia/nemotron-3.5-super-120b-a12b`, or unset it.

`model_source.fallback_reason` names each earlier hop that failed, for example `{"nim": "HTTP 404"}`. The value is the status or the exception class. The response body and the API key are not included. The process log names the model id sent on each hop. At startup it logs the effective Super and Lightning ids, and nothing else.

A Super call waits 20 s (`ESCALES_LLM_TIMEOUT_NIM_S`). Lightning waits 10 s (`ESCALES_LLM_TIMEOUT_NIM_FALLBACK_S`). After HTTP 429 the same NIM model is tried once. The pause follows `Retry-After`, capped at 3 s, and is at least the gap between NIM calls. HTTP 404 or 403 logs `model unavailable for this key` and skips that hop for 10 minutes.

Chat and the milestone report ask Super first. The JSON advisory uses `JSON_HTTP_CASCADE` with Lightning (`nim_fallback`) before Super on purpose, to save credits. The payload has no `reasoning_effort` and no `nvext`. `top_p` is sent only when the temperature is above 0. `guided_json` stays at the root of the NIM request. OpenRouter receives `response_format` with the same JSON schema.

## Provider limits

NVIDIA API Catalog is a free trial, rate-limited per account (about 40 requests per minute is what operators report; per-model limits are not published). It is for trial use only.

OpenRouter free models allow 20 requests per minute and 50 per day (1,000 per day after at least 10 USD of lifetime credits). The default model is `openrouter/free`, not a paid model. `OPENROUTER_MODEL` can name another id. The OpenRouter terms forbid more than one account, so this project does not add a second one. HTTP 402 skips OpenRouter. HTTP 429 waits for `Retry-After` (capped at 3 s) and then skips it. Requests send `HTTP-Referer` and `X-Title`.

## Optional partners (feature flags)

The API runs fully on local pytest and manual treasurer routes without any of the integrations below. Each partner is gated by an environment variable (see `bi-escales/.env.example`).

| Integration | Flag | Role |
|-------------|------|------|
| PayPal webhooks | `ESCALES_WEBHOOKS_ENABLED` + `PAYPAL_WEBHOOK_ID` | Inbound `POST /api/escales/webhooks/paypal` with PayPal `verify-webhook-signature` and transmission idempotence |
| PayPal Agent Toolkit | `ESCALES_TOOLKIT_ENABLED` | Read-only order lookups for the Captain |
| Render deploy | `bi-escales/render.yaml` | Optional blueprint; set env vars in the Render dashboard (names only in the file) |
| AG Grid Community | `VITE_ENABLE_AG_GRID` (frontend build) | Optional AG Grid view of the treasurer milestone table, shipped as a lazy chunk when the flag is on; absent from the build when off (default), which keeps the HTML table |
| Postman | `bi-escales/postman/escales.postman_collection.json` + `escales.sandbox.postman_environment.json` | Sandbox walkthrough (create → authorize → capture / void) against test2; admin key left empty; not loaded by the app |
| Bryntum | `bi-escales/frontend/src/components/escales/BryntumTimeline.jsx` | Read-only stopover timeline (public npm trial `@bryntum/scheduler-trial`), only when `ESCALES_BRYNTUM_ENABLED=true`; falls back to the local list |
| Zapier | `ESCALES_ZAPIER_ENABLED` | Optional automation layer (see below) |

### Render (documentation)

The blueprint in `bi-escales/render.yaml` describes one free web service (`bi-escales-api`): `npm ci && npm run build` for the Vite shell, then `uvicorn` on `$PORT`. `autoDeployTrigger: off` — pushes do not deploy; Clément triggers deploys manually.

Partner toggles on Render (names only, no values in git):

- **Build** — `VITE_ENABLE_AG_GRID=1` ships AG Grid as a lazy chunk (`TreasurerGridAg`), loaded when the treasurer table opens. Leave it unset or `0` and the chunk is absent from the build; the page keeps the HTML table.
- **Runtime** — `ESCALES_BRYNTUM_ENABLED=1` exposes Bryntum on `/api/escales/features` and the voyage tab loads the read-only timeline; default off keeps the local schedule list.

See `bi-escales/docs/deploiement-render.md` for return URLs and same-origin setup, and `bi-escales/scripts/smoke_same_origin.py` for the smoke script. Removing partner env vars or the Postman folder does not change core pledge behaviour.

### Optional Zapier Zap

When `ESCALES_ZAPIER_ENABLED=1`, webhook responses may include a hint that you can forward verified events to Zapier. A typical **Zap** for demos:

1. **Trigger — Webhooks by Zapier (Catch Hook)** or **PayPal** (sandbox) when you prefer native PayPal triggers.
2. **Filter** — keep events where `event_type` matches your milestone workflow (for example `CHECKOUT.ORDER.APPROVED` or capture-related types).
3. **Action — Webhooks POST** to your BI Escales treasurer tools (still behind `x-admin-key`) or to Slack/email for human approval.

Zapier never replaces the treasurer: capture and void remain explicit `POST` calls with `ESCALES_ADMIN_KEY`. With the flag off, no Zapier-specific behaviour runs.

## PayPal MCP server

PayPal hosts a **remote Model Context Protocol (MCP) server** so a treasurer (or developer) can connect an AI assistant such as **Claude Desktop** or **Cursor** to PayPal **sandbox** data with natural language— for example to inspect checkout orders, payment authorizations, disputes, or transaction search results—without pasting secrets into chat.

Official setup (endpoints, OAuth with dashboard **client ID / secret**, SSE vs streamable HTTP, and local vs remote server) is documented in PayPal’s **[MCP server quickstart guide](https://developer.paypal.com/ai-tools/mcp-server)**. For sandbox, use the remote endpoint `https://mcp.sandbox.paypal.com` (production uses `https://mcp.paypal.com`). Configure the MCP client JSON as PayPal describes; store access tokens and credentials in environment variables or the client’s secret store, not in the repository.

This is **separate** from the in-app Captain integration: `ESCALES_TOOLKIT_ENABLED` turns on read-only PayPal lookups inside BI Escales (see table above). The remote MCP server is optional tooling for humans exploring the same sandbox account from Claude or Cursor.

## Captain limits (production only)

`ESCALES_ENV` defaults to `development`. In development and in tests the captain routes and the LLM cascade are not rate limited, and LLM usage is not capped.

`ESCALES_ENV=production` (set in `bi-escales/render.yaml`) turns both limits on:

- `POST /api/escales/captain/chat` and `POST /api/escales/captain/review/{id}` share 10 requests per minute and 100 per UTC day per IP (`ESCALES_CAPTAIN_RATE_PER_MINUTE`, `ESCALES_CAPTAIN_RATE_PER_DAY`). Over the limit the API returns **429** in French or English.
- Behind Render (or another reverse proxy), client IP for that limit comes from `X-Forwarded-For` using the rightmost trusted hop (`ESCALES_TRUSTED_PROXY_HOPS`, default **1**). Set **0** to use the connection host only.
- LLM calls share one UTC-day budget (`ESCALES_LLM_DAILY_CAP`, default 100). The next call is not sent; the captain answers from its rules.

`ESCALES_RATE_LIMIT_ENABLED=true` forces both on even in development. `ESCALES_RATE_LIMIT_ENABLED=false` forces both off even in production. Counts stay in memory for the life of the process.

## Quick start (backend)
```bash
cd bi-escales/backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m pytest tests -q
```
Copy `.env.example` to `.env` and fill in sandbox values locally; never commit it.

## License
Dual-licensed under MIT (`LICENSE-MIT`) or Apache-2.0 (`LICENSE-APACHE`), at your option.
