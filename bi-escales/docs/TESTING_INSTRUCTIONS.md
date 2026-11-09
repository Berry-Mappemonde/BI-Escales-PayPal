# Devpost testing instructions (judges)

Copy the numbered steps below into Devpost’s private **Testing instructions** field. This file is the repository copy; keep it aligned with the live app behaviour.

**App:** [https://escales.naviguide.fr](https://escales.naviguide.fr) — PayPal **sandbox** only, EUR, simulated prices; nothing is ever charged on a live PayPal account.

## Steps for judges

1. **AI Captain (left panel):** Type `Sponsor 20 miles near Mayotte` or tap the **Where is the boat?** chip. The answer shows the model used (NVIDIA Nemotron via NIM when configured) and a ready cart (amount, stop, PayPal flow hint).

2. **Back a stop:** Click a flag on the map, choose a kind and quantity, then pay with PayPal using the **sandbox buyer account** below (and, when Card Fields are enabled on the deployment, the sandbox test card `4111 1111 1111 1111`, any future expiry, CVV `123`).

   **Payment timing (code rules):**
   - **Stop pledges** (miles, nights, meals, care, berths): captured when the boat **arrives** at the stop; **void** if the stop is cancelled.
   - **Cabins:** captured at **leg departure**.
   - **Common fund** and **project donations:** captured **immediately**.

   **Authorize vs Vault (checkout):** PayPal authorizations must not be opened more than **29 days** before the relevant arrival or departure. Near stops use Orders v2 **`AUTHORIZE`**; stops whose arrival is **more than 29 days away** (with Vault enabled) use **`VAULT`** and charge on arrival. On the public demo with the simulated clock pinned to departure day, Mayotte is beyond that window — confirm with `GET /api/escales/pledges/mode?milestone_id=dep-dzaoudzi-mayotte&kind=mile` (expect `VAULT` when Vault is on). The Captain’s rules-based cart text may still say **intent AUTHORIZE**; checkout follows `/pledges/mode`.

3. **Treasurer:** Press **Demo treasurer** for a read-only view of the queue and the Captain’s review (no supporter names). To capture, void, settle, or refund, use the treasurer key supplied privately (HTTP header `x-admin-key`).

4. **Simulated clock:** The demo voyage **departs on 12 Nov 2026**. Deployed services pin the voyage clock to **12 Nov 2026 08:00 UTC** (`GET /api/escales/clock`) so arrival captures can be exercised during judging. Do not rely on wall-clock dates for capture eligibility.

5. **Run locally (optional):** **Python 3.12** and **Node.js 22** (see repository CI). Follow [README Quick start](../../README.md#quick-start). Set your own PayPal sandbox credentials in `bi-escales/backend/.env` (`PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`) and `VITE_PAYPAL_CLIENT_ID` in `bi-escales/frontend/.env.local`. Placeholders let the API and UI start, but PayPal checkout is rejected until real sandbox client ids are set. Set `ESCALES_DEMO_TREASURER=1` (with `PAYPAL_ENV=sandbox`) to enable the demo treasurer button locally.

## Sandbox buyer account for judges

Use this PayPal **sandbox personal** buyer (France, EUR):

- **Email:** `berry-mappemonde-acheteur-fr@personal.example.com`

The password is **not** stored in git. The hackathon owner provides it in Devpost’s private testing-instructions field (valid through the judging window).

For **Card Fields** checkouts only (when `ESCALES_CARD_FIELDS_ENABLED` is on and the frontend build exposes card fields), you may use PayPal’s sandbox Visa test card **4111 1111 1111 1111** with any future expiry and CVV **123**, instead of logging into the buyer wallet.

## Optional API smoke (no buyer login)

| Check | Endpoint |
| --- | --- |
| Health | `GET /api/health` |
| PayPal environment | `GET /api/escales/features` → `merchant.environment` = `sandbox` |
| Simulated clock | `GET /api/escales/clock` |
| Pledge mode preview | `GET /api/escales/pledges/mode?milestone_id=…&kind=mile` |
| Common fund | `GET /api/escales/common-fund/fund` |
| Captain (POST) | `POST /api/escales/captain/chat` with JSON `{"message":"Sponsor 20 miles near Mayotte","lang":"en"}` |

Treasurer list without key: `GET /api/escales/pledges` returns **200** with redacted fields; mutating routes without `x-admin-key` return **401** (unless demo treasurer mode is enabled on a sandbox host).
