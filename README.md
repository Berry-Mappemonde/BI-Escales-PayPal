# BI Escales — Pay Only If We Sail

PayPal AI Hackathon 2026 project by Association Berry-Mappemonde.

A supporter's PayPal pledge is **authorized** (Orders v2 `intent=AUTHORIZE`), and **captured** only once the AI Captain has reviewed the evidence for a voyage stop and a human treasurer has approved it; otherwise it is **voided**. The AI Captain proposes, it never executes.

- `bi-escales/` — FastAPI backend: pledges (authorize / capture / void), milestones and evidence, AI Captain, audit journal. Partner integrations (e.g. PayPal Agent Toolkit) are optional modules behind environment flags, off by default.
- `naviguide-escales/` — NAVIGUIDE voyage simulator (snapshot, no history).

Status: in development. PayPal **sandbox only**; no real money moves. Planned departure: 15 May 2027.

## NIM model

`NIM_MODEL` defaults to `private/nvidia/nemotron-3.5-super-120b-a12b`. On Render the variable is `sync: false`, so the dashboard value overrides that default and is the id sent on the primary hop. The old id `nvidia/nemotron-3.5-super-vl-120b-a12b` returns 404 at NVIDIA, and so does `nvidia/nemotron-3.5-super-120b-a12b` (the same id without the `private/` prefix). The code refuses those two ids, and also refuses `nvidia/nemotron-3.5-lightning-30b-a3b` when it is set as `NIM_MODEL`, and sends the private Super id instead. The log and `model_source.reason` name the refused id. They never include the API key. If the primary hop still fails (HTTP 404 or a timeout), the `nim_fallback` hop answers with `nvidia/nemotron-3.5-lightning-30b-a3b`. `model_source.provider` is then `nim_fallback`, and `model_source.reason` says which id was sent and whether the cause was `http_404` or `timeout`. Set Render `NIM_MODEL` to `private/nvidia/nemotron-3.5-super-120b-a12b`, or unset it.

## Optional partners (feature flags)

The API runs fully on local pytest and manual treasurer routes without any of the integrations below. Each partner is gated by an environment variable (see `bi-escales/.env.example`).

| Integration | Flag | Role |
|-------------|------|------|
| PayPal webhooks | `ESCALES_WEBHOOKS_ENABLED` + `PAYPAL_WEBHOOK_ID` | Inbound `POST /api/escales/webhooks/paypal` with PayPal `verify-webhook-signature` and transmission idempotence |
| PayPal Agent Toolkit | `ESCALES_TOOLKIT_ENABLED` | Read-only order lookups for the Captain |
| Render deploy | `bi-escales/render.yaml` | Optional blueprint; set env vars in the Render dashboard (names only in the file) |
| Postman | `bi-escales/postman/escales.postman_collection.json` | Sandbox walkthrough (create → authorize → capture / void); not loaded by the app |
| Zapier | `ESCALES_ZAPIER_ENABLED` | Optional automation layer (see below) |

### Optional Zapier Zap

When `ESCALES_ZAPIER_ENABLED=1`, webhook responses may include a hint that you can forward verified events to Zapier. A typical **Zap** for demos:

1. **Trigger — Webhooks by Zapier (Catch Hook)** or **PayPal** (sandbox) when you prefer native PayPal triggers.
2. **Filter** — keep events where `event_type` matches your milestone workflow (for example `CHECKOUT.ORDER.APPROVED` or capture-related types).
3. **Action — Webhooks POST** to your BI Escales treasurer tools (still behind `x-admin-key`) or to Slack/email for human approval.

Zapier never replaces the treasurer: capture and void remain explicit `POST` calls with `ESCALES_ADMIN_KEY`. With the flag off, no Zapier-specific behaviour runs.

## Captain limits (production only)

`ESCALES_ENV` defaults to `development`. In development and in tests the captain routes and the LLM cascade are not rate limited, and LLM usage is not capped.

`ESCALES_ENV=production` (set in `bi-escales/render.yaml`) turns both limits on:

- `POST /api/escales/captain/chat` and `POST /api/escales/captain/review/{id}` share 10 requests per minute and 100 per UTC day per IP (`ESCALES_CAPTAIN_RATE_PER_MINUTE`, `ESCALES_CAPTAIN_RATE_PER_DAY`). Over the limit the API returns **429** in French or English.
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
