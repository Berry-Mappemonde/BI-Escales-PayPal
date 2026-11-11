# BI Escales — Pay Only If We Sail

PayPal AI Hackathon 2026 — Association Berry-Mappemonde.

**Built with:** the [APIMatic Context Plugin for the PayPal Server SDK](bi-escales/docs/apimatic/README.md) (vendored Python agent skills). The running app does not call `paypalserversdk`.

## Judges — start here

| Resource | Link |
| --- | --- |
| **Hosted demo (judge URL)** | [https://escales.naviguide.fr](https://escales.naviguide.fr) |
| **Detailed test script** | [bi-escales/docs/TESTING_INSTRUCTIONS.md](bi-escales/docs/TESTING_INSTRUCTIONS.md) |
| **Demo video (v7)** | [https://youtu.be/LszlcLdwzoQ](https://youtu.be/LszlcLdwzoQ) |
| **Devpost project** | [https://devpost.com/software/bi-escales-pay-only-if-we-sail](https://devpost.com/software/bi-escales-pay-only-if-we-sail) |
| **test2 API fallback** | [https://bi-escales-api-test2.onrender.com](https://bi-escales-api-test2.onrender.com) (`GET /api/health`), the same sandbox stack, for when the hosted demo is unreachable |

PayPal **sandbox only**: no live money moves, on any host. The voyage departs on 12 Nov 2026 (the submission deadline); the hosted demo pins the voyage clock to **12 Nov 2026 08:00 UTC** (`GET /api/escales/clock`).

### Judge path

1. **Map.** Open [escales.naviguide.fr](https://escales.naviguide.fr). The map shows the voyage, one flag per stop. The page opens in English; **FR** switches to French.
2. **Back the next stop.** Press **Back the next stop** in the right panel. On the demo clock it opens **La Rochelle**. Any flag on the map opens its stop the same way.
3. **Pay with PayPal.** Choose what you fund and a quantity, then press **Pay with PayPal** and approve with the sandbox buyer (see below). The pledge is **authorised, not charged**: La Rochelle uses Orders v2 `intent=AUTHORIZE`. The stop sheet then confirms the pledge.
4. **Demo treasurer: play the treasurer on your own pledge.** Press **Demo treasurer** at the bottom of the left panel. It shows the queue of held pledges and the AI Captain's review of each stop, with its sources, without supporter names. The pledge you just made from this browser is tagged **Yours** and has live buttons: **Simulate arrival** (for that pledge only), **Approve**, then **Capture** or **Void**, and **Refund** once captured, for real in the PayPal sandbox. Every other pledge is view-only.

Optional: ask the **AI Captain** a question in the left panel (for example the **Where is the boat?** chip). Each answer says whether it came from a fixed rule or from NVIDIA Nemotron.

A far stop shows the other payment mode: **Mayotte** is more than 29 days away on the demo clock, so its pledges save the payment method with PayPal **Vault** instead of opening an authorization. Check both with `GET /api/escales/pledges/mode?milestone_id=dep-la-rochelle&kind=mile` (`AUTHORIZE`) and `...milestone_id=dep-dzaoudzi-mayotte&kind=mile` (`VAULT`).

### What needs the treasurer key

Acting on a pledge **made from another browser** is behind the private treasurer key (HTTP header `x-admin-key`), which is **not in this repository** and is not needed for the judge path. Without the key, the demo acts only on a pledge whose own browser proves it made it (the server checks this on every call). The key is needed for:

- **Capture**, **void** or **refund** of any other pledge, and approval of the Captain's review for a whole stop.
- **Run departure-day settle** and **Settle at this date**.
- The **Judge moment — La Rochelle** tools: **Simulate boat arrival**, **Cancel stop**, **Reset demo**.

To see a capture without the key, watch the treasurer flow in the [demo video (v7)](https://youtu.be/LszlcLdwzoQ).

### Payment rules (summary)

- **Stop pledges** (miles, nights, meals, care, berths): **captured** when the boat **arrives**; **voided** if the stop is **cancelled**.
- **Cabins:** **captured** at leg **departure**.
- **Common fund** and **project donations:** **captured immediately** (no Captain/treasurer gate on those paths).
- For held stop and cabin pledges the AI Captain reviews the evidence and proposes; a human treasurer captures or voids. The Captain never moves money.

**No tax receipts:** BI Escales does not issue tax receipts for pledges, cabins, fund contributions or project donations.

- Authorizations are not opened more than **29 days** before the relevant arrival or departure; farther horizons use PayPal **Vault** (`ESCALES_VAULT_ENABLED`, on for the hosted demo).
- **Abonnement Crew** (English UI: **Crew membership**) is the association **membership**: one PayPal subscription product, not a second membership SKU.
- The expedition **crew is six people** (capacity checks on safety gear in the Channel3 seed catalogue; see [CHANNEL3_WISHLISTS.md](bi-escales/docs/CHANNEL3_WISHLISTS.md)).

### What is switched on for the hosted demo

Read from `GET https://escales.naviguide.fr/api/escales/features` on 11 Nov 2026. Every optional feature is behind an environment flag and is off unless set.

| Feature | Flag | Hosted demo |
| --- | --- | --- |
| PayPal Vault for far stops and cabins | `ESCALES_VAULT_ENABLED` | **On** |
| Demo treasurer (view of the queue; live on a visitor's own pledges, sandbox only) | `ESCALES_DEMO_TREASURER` | **On** |
| Crew membership (PayPal subscription) | plan configured on the host | **On** |
| Gear wishlists (Channel3 catalogue) | `ESCALES_WISHLISTS_ENABLED`, `ESCALES_CHANNEL3_ENABLED` | **On** |
| PayPal webhooks | `ESCALES_WEBHOOKS_ENABLED` | **On** |
| Card Fields (pay by card in the page) | `ESCALES_CARD_FIELDS_ENABLED` | Off |
| Apple Pay / Google Pay | `ESCALES_WALLET_PAY_ENABLED` | Off |
| Project onboarding after payment | `ESCALES_ONBOARD_AFTER_PAYMENT_ENABLED` | Off |
| PayPal Web SDK v6 checkout | `ESCALES_PAYPAL_JS_V6_ENABLED` | Off |
| Save the payment method during an authorised checkout | `ESCALES_VAULT_ON_PURCHASE_ENABLED` | Off |
| Bryntum timeline | `ESCALES_BRYNTUM_ENABLED` | Off |

The onboarding flag is not reported by the features endpoint; its state above is the deployment setting.

**PayPal Web SDK v6.** The checkout runs on PayPal's JS SDK v5 Smart Buttons. A second checkout path on the Web SDK v6 is merged behind `ESCALES_PAYPAL_JS_V6_ENABLED` ([#222](https://github.com/Berry-Mappemonde/BI-Escales-PayPal/pull/222)): off by default, off on the hosted demo, and refused outside the PayPal sandbox. With the flag off the page loads and uses v5 only. The v6 path is covered by tests but has not yet completed a real sandbox payment; see [PAYPAL_JS_V6_FLAG.md](bi-escales/docs/PAYPAL_JS_V6_FLAG.md).

### Sandbox buyer

Credentials are **not** in this repository. See the **private testing instructions** field on [Devpost](https://devpost.com/software/bi-escales-pay-only-if-we-sail) for the sandbox buyer login (valid through the judging window).

### Hosted app vs local clone

A default local setup uses **placeholder** `PAYPAL_CLIENT_ID` / `PAYPAL_CLIENT_SECRET` values. The API and UI start, but **PayPal checkout cannot complete** until real sandbox REST credentials are configured. For judging, use the **hosted app** at [escales.naviguide.fr](https://escales.naviguide.fr) ([test2](https://bi-escales-api-test2.onrender.com) as API fallback).

### Tests

CI runs on every push and pull request (`.github/workflows/ci.yml`). On `test/integration-2` at `e729a5b` (11 Nov 2026):

| Suite | Result |
| --- | --- |
| Backend (`python -m pytest tests -q`) | 1078 passed, 2 skipped |
| Frontend (`npm test`: vitest, then the node test) | 797 passed in 127 files, plus 3 node tests |
| Frontend build (`npm run build`) | passes |

The 2 skipped backend tests make real PayPal sandbox or NVIDIA NIM calls and run only with `ESCALES_RUN_LIVE=1`.

---

## Quick start

CI (`.github/workflows/ci.yml`) uses **Python 3.12** and **Node.js 22**. Use **python3.12** for backend commands below. Python **3.13** is not supported (`paypal-agent-toolkit` dependencies fail on 3.13).

### 1. Backend

```bash
cd bi-escales/backend
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python3.12 -m pytest tests -q
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
- `ESCALES_DEMO_TREASURER=1` (optional: **Demo treasurer** without sharing `x-admin-key`: a view of the queue, and the treasurer loop on pledges made from the visitor's own browser; requires `PAYPAL_ENV=sandbox`)

Replace PayPal placeholders with your own **sandbox** REST app credentials only if you need real checkout locally.

```bash
python3.12 -m uvicorn app.main:app --reload --port 8000 --env-file .env
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

PayPal checkout is **sandbox only**. **Stop** pledges use Orders v2 **`intent=AUTHORIZE`** and are **captured when the boat arrives** (or **voided** if the stop is cancelled). **Cabins** are captured at leg **departure**. **Common fund** and **project donations** are **charged immediately** after the supporter approves in PayPal — they do not wait on Captain review or treasurer capture. For held stop and cabin pledges, the AI Captain reviews voyage-stop evidence and proposes; a human treasurer executes capture or void. The Captain never moves money.

For stop and cabin milestone pledges, an approved **capture** review (and simulated clock at or after arrival or departure, as applicable) can gate treasurer capture. Approving **wait** never permits capture. Settlement and direct capture return HTTP 409 or `await_review_approval` until the clock and review rules allow capture.

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

### Security response headers

The FastAPI app sets HSTS, `X-Content-Type-Options`, `Referrer-Policy`, an enforced `Content-Security-Policy` (`frame-ancestors 'none'` only), and a full `Content-Security-Policy-Report-Only` on every response. Enabled by default when `ESCALES_SECURITY_HEADERS` is unset; set `ESCALES_SECURITY_HEADERS=0` to turn off.

### Void id

PayPal's void of an authorization usually returns no id (HTTP 204). `void_id` is then the authorization id, `void_id_source` is `authorization`, and `void_note` says so. A vault release with no id uses the vault id the same way. When the void body contains an `id`, that value is stored and `void_id_source` is `paypal`. `voided_at` is the voyage clock (`ESCALES_CLOCK_NOW`, or real UTC when unset).

### NIM model

`NIM_MODEL` defaults to `private/nvidia/nemotron-3.5-super-120b-a12b`. On Render the variable is `sync: false`, so the dashboard value overrides. The code refuses legacy ids that 404 at NVIDIA and can fall back to `nvidia/nemotron-3.5-lightning-30b-a3b` (`nim_fallback`). Logs name model ids and never include API keys. Super waits 20 s (`ESCALES_LLM_TIMEOUT_NIM_S`); Lightning 10 s. After HTTP 429 the same NIM model is retried once with `Retry-After` (capped at 3 s). JSON advisory uses `JSON_HTTP_CASCADE` with Lightning before Super to save credits; chat asks Super first.

### Provider limits

NVIDIA API Catalog is rate-limited (operators report ~40 requests/minute; per-model limits not published). OpenRouter free tier: 20 requests/minute and 50/day (higher after paid credits). HTTP 402/429 handling skips or backs off OpenRouter. Requests send `HTTP-Referer` and `X-Title`.

## License

Dual-licensed under MIT (`LICENSE-MIT`) or Apache-2.0 (`LICENSE-APACHE`), at your option.
