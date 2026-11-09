# BI Escales — Pay Only If We Sail

PayPal AI Hackathon 2026 — Association Berry-Mappemonde.

**Built with:** the [APIMatic Context Plugin for the PayPal Server SDK](bi-escales/docs/apimatic/README.md) (vendored Python agent skills). The running app does not call `paypalserversdk`.

## Judges — start here

| Resource | Link |
| --- | --- |
| **Hosted demo (preferred)** | [https://escales.naviguide.fr](https://escales.naviguide.fr) |
| **test2 API fallback** | [https://bi-escales-api-test2.onrender.com](https://bi-escales-api-test2.onrender.com) (`GET /api/health`) — same sandbox stack when the public shell is unreachable; use the hosted UI at escales when it is up |
| **Demo video (v7)** | [https://youtu.be/LszlcLdwzoQ](https://youtu.be/LszlcLdwzoQ) |
| **Devpost project** | [https://devpost.com/software/bi-escales-pay-only-if-we-sail](https://devpost.com/software/bi-escales-pay-only-if-we-sail) |
| **Detailed test script** | [bi-escales/docs/TESTING_INSTRUCTIONS.md](bi-escales/docs/TESTING_INSTRUCTIONS.md) |

PayPal **sandbox only** — no live money moves. The voyage departs on 12 Nov 2026 (the submission deadline); judging hosts pin the voyage clock to that date (`GET /api/escales/clock`).

### Five-step judge path

1. **Near stop — AUTHORIZE:** On the demo clock, **La Rochelle** (`dep-la-rochelle`) is within PayPal’s ~29-day authorization window. Open the cart and pay with the yellow **PayPal** button; checkout uses Orders v2 **`intent=AUTHORIZE`** (hold until treasurer capture after Captain review). Confirm with `GET /api/escales/pledges/mode?milestone_id=dep-la-rochelle&kind=mile` (expect `AUTHORIZE` on prod and test2).
2. **Card Fields (when enabled):** On the same or another checkout, use **Card Fields** with PayPal’s sandbox Visa **4111 1111 1111 1111**, any future expiry, CVV **123**, instead of logging into a wallet.
3. **Far stop — VAULT:** On the demo clock, **Mayotte** (`dep-dzaoudzi-mayotte`) is beyond that window — miles there use **Vault** when enabled (confirm with `GET /api/escales/pledges/mode?milestone_id=dep-dzaoudzi-mayotte&kind=mile`, expect `VAULT`). **Cabins** on a far leg use **Vault** too; settlement follows leg **departure** rules.
4. **Treasurer:** Open **Demo treasurer** for a read-only queue and Captain reviews. Capture / void / settle need the treasurer key supplied privately (`x-admin-key`), or use demo treasurer where the host allows it in sandbox.
5. **Refund / void:** From the treasurer view, **void** an authorization when a stop is cancelled, or exercise **refund** / release flows on an eligible sandbox capture — still sandbox-only, with human approval on the money path.

### Payment rules (summary)

- **Stop pledges** (miles, nights, meals, care, berths): **captured** when the boat **arrives**; **voided** if the stop is **cancelled**.
- **Cabins:** **captured** at leg **departure**.
- **Common fund** and **project donations:** **captured immediately**.
- Authorizations are not opened more than **29 days** before the relevant arrival or departure; farther horizons use PayPal **Vault** when `ESCALES_VAULT_ENABLED=1`.

### Sandbox buyer

Credentials are **not** in this repository. See the **private testing instructions** field on [Devpost](https://devpost.com/software/bi-escales-pay-only-if-we-sail) for the sandbox buyer login (valid through the judging window).

### Hosted app vs local clone

A default local setup uses **placeholder** `PAYPAL_CLIENT_ID` / `PAYPAL_CLIENT_SECRET` values. The API and UI start, but **PayPal checkout cannot complete** until real sandbox REST credentials are configured. For judging, use the **hosted app** at [escales.naviguide.fr](https://escales.naviguide.fr) ([test2](https://bi-escales-api-test2.onrender.com) as API fallback).

---

## Quick start

Target time: under 10 minutes from clone to a running local shell. CI (`.github/workflows/ci.yml`) uses **Python 3.12** and **Node.js 22**; **Python 3.11+** is fine if `python -m pytest tests -q` passes (e.g. via `uv` or `pyenv`). Python **3.13** is not supported today (`paypal-agent-toolkit` dependencies fail on 3.13).

### 1. Backend

```bash
cd bi-escales/backend
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m pytest tests -q
```

Copy the example environment file:

```bash
cp ../.env.example .env
```

In `.env`, set at minimum:

- `ESCALES_ENABLED=1`
- `ESCALES_STORE=memory`
- `PAYPAL_ENV=sandbox`
- `PAYPAL_CLIENT_ID=sandbox_placeholder`
- `PAYPAL_CLIENT_SECRET=sandbox_placeholder`
- `ESCALES_ADMIN_KEY=dev-secret`
- `ESCALES_DEMO_TREASURER=1` (optional: **Demo treasurer** without sharing `x-admin-key`; requires `PAYPAL_ENV=sandbox`)

Replace PayPal placeholders with your own **sandbox** REST app credentials only if you need real checkout locally.

```bash
python -m uvicorn app.main:app --reload --port 8000 --env-file .env
```

Verify: `http://127.0.0.1:8000/api/health`.

### 2. Frontend

```bash
cd bi-escales/frontend
cp .env.example .env.local
npm ci
VITE_API_PROXY_TARGET=http://127.0.0.1:8000 npm run dev
```

Set `VITE_PAYPAL_CLIENT_ID` to match `PAYPAL_CLIENT_ID`, or leave `sandbox_placeholder` to load the shell without working PayPal buttons.

Open `http://localhost:5173`.

---

## How it works

A supporter's PayPal pledge is **authorized** (Orders v2 `intent=AUTHORIZE`), and **captured** only after the AI Captain has reviewed voyage-stop evidence and a human treasurer has approved; otherwise it is **voided**. The AI Captain proposes; it never executes money movement.

For milestone pledges, approval records the verdict, its proposal time, and the approval time on the simulated voyage clock. Only the latest approved **capture** review permits capture, and both times must be at or after the stop's arrival (the leg's departure for cabins). Approving **wait** never permits capture. Settlement returns `await_review_approval` and direct capture returns HTTP 409 until a qualifying review is approved.

| Path | Role |
| --- | --- |
| `bi-escales/` | FastAPI backend + Vite/React frontend: pledges, milestones, Captain, audit journal |
| `naviguide-escales/` | NAVIGUIDE voyage simulator snapshot (no separate git history) |

Partner integrations (PayPal Agent Toolkit, webhooks, AG Grid, Bryntum, Zapier, …) are optional and gated by environment flags (see `bi-escales/.env.example`).

**Simulated clock:** `ESCALES_CLOCK_NOW` / `ESCALES_CLOCK_START` pin the voyage timeline. Deployed judging hosts use **12 Nov 2026** with the clock at **2026-11-12T08:00:00Z** (`GET /api/escales/clock`).

## Optional partners (feature flags)

The API runs fully on local pytest and manual treasurer routes without any of the integrations below.

| Integration | Flag | Role |
|-------------|------|------|
| PayPal webhooks | `ESCALES_WEBHOOKS_ENABLED` + `PAYPAL_WEBHOOK_ID` | Inbound `POST /api/escales/webhooks/paypal` with PayPal `verify-webhook-signature` |
| PayPal Agent Toolkit | `ESCALES_TOOLKIT_ENABLED` | Read-only order lookups for the Captain |
| Render deploy | `bi-escales/render.yaml` | Optional blueprint; `autoDeployTrigger: off` |
| AG Grid Community | `VITE_ENABLE_AG_GRID` | Optional treasurer grid (lazy chunk when on) |
| Postman | `bi-escales/postman/` | Sandbox walkthrough against test2; not loaded by the app |
| Bryntum | `ESCALES_BRYNTUM_ENABLED` | Read-only stopover timeline when enabled |
| Zapier | `ESCALES_ZAPIER_ENABLED` | Optional automation layer |

See `bi-escales/docs/deploiement-render.md` and `bi-escales/scripts/smoke_same_origin.py` for deploy and same-origin notes.

### PayPal MCP server

PayPal’s remote **MCP** server lets developers connect Claude Desktop or Cursor to **sandbox** PayPal data. Setup: [PayPal MCP server quickstart](https://developer.paypal.com/ai-tools/mcp-server). Sandbox endpoint: `https://mcp.sandbox.paypal.com`. Separate from in-app `ESCALES_TOOLKIT_ENABLED`.

## Operations

Notes for operators and maintainers (not required for judging).

### `ESCALES_ENV` and Captain limits

`ESCALES_ENV` defaults to `development`. Locally and in tests, captain routes and the LLM cascade are not rate limited and LLM usage is not capped.

`ESCALES_ENV=production` is set in `bi-escales/render.yaml` on Render; that turns both limits on:

- `POST /api/escales/captain/chat` and `POST /api/escales/captain/review/{id}` share 10 requests per minute and 100 per UTC day per IP (`ESCALES_CAPTAIN_RATE_PER_MINUTE`, `ESCALES_CAPTAIN_RATE_PER_DAY`). Over the limit the API returns **429** in French or English.
- Behind Render (or another reverse proxy), client IP for that limit comes from `X-Forwarded-For` using the rightmost trusted hop (`ESCALES_TRUSTED_PROXY_HOPS`, default **1**). Set **0** to use the connection host only.
- LLM calls share one UTC-day budget (`ESCALES_LLM_DAILY_CAP`, default 100). The next call is not sent; the captain answers from its rules.

`ESCALES_RATE_LIMIT_ENABLED=true` forces both on even in `development`. `ESCALES_RATE_LIMIT_ENABLED=false` forces both off even in production. Counts stay in memory for the life of the process.

### Void id

PayPal's void of an authorization usually returns no id (HTTP 204). `void_id` is then the authorization id, `void_id_source` is `authorization`, and `void_note` says so. A vault release with no id uses the vault id the same way. When the void body contains an `id`, that value is stored and `void_id_source` is `paypal`. `voided_at` is the voyage clock (`ESCALES_CLOCK_NOW`, or real UTC when unset).

### NIM model

`NIM_MODEL` defaults to `private/nvidia/nemotron-3.5-super-120b-a12b`. On Render the variable is `sync: false`, so the dashboard value overrides. The code refuses legacy ids that 404 at NVIDIA and can fall back to `nvidia/nemotron-3.5-lightning-30b-a3b` (`nim_fallback`). Logs name model ids and never include API keys. Super waits 20 s (`ESCALES_LLM_TIMEOUT_NIM_S`); Lightning 10 s. After HTTP 429 the same NIM model is retried once with `Retry-After` (capped at 3 s). JSON advisory uses `JSON_HTTP_CASCADE` with Lightning before Super to save credits; chat asks Super first.

### Provider limits

NVIDIA API Catalog is rate-limited (operators report ~40 requests/minute; per-model limits not published). OpenRouter free tier: 20 requests/minute and 50/day (higher after paid credits). HTTP 402/429 handling skips or backs off OpenRouter. Requests send `HTTP-Referer` and `X-Title`.

## License

Dual-licensed under MIT (`LICENSE-MIT`) or Apache-2.0 (`LICENSE-APACHE`), at your option.
