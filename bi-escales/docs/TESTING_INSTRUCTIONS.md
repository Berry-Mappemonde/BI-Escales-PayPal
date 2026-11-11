# Devpost testing instructions (judges)

Copy the numbered steps below into Devpost’s private **Testing instructions** field. This file is the repository copy; keep it aligned with the live app behaviour.

**App:** [https://escales.naviguide.fr](https://escales.naviguide.fr). PayPal **sandbox** only, EUR, simulated prices; nothing is ever charged on a live PayPal account.

## Steps for judges

1. **Map:** Open the app. The map shows the voyage with one flag per stop. The page opens in English; the **FR** button switches to French.

2. **Back the next stop:** Press **Back the next stop** in the right panel (French: **Soutenir la prochaine escale**). On the demo clock it opens **La Rochelle**. Clicking any flag on the map opens that stop the same way.

3. **Pay with PayPal:** In the stop sheet, choose what you fund and a quantity, then press **Pay with PayPal** (French: **Payer avec PayPal**) and approve with the **sandbox buyer account** below. For La Rochelle the pledge is **authorised, not charged** (Orders v2 `intent=AUTHORIZE`).

   If PayPal's own button cannot load in your browser, the sheet shows **Continue with PayPal** instead, which opens the PayPal page; come back to the app after approving and press **I approved — authorize**.

   **Payment timing (code rules):**
   - **Stop pledges** (miles, nights, meals, care, berths): captured when the boat **arrives** at the stop; **void** if the stop is cancelled.
   - **Cabins:** captured at **leg departure**.
   - **Common fund** and **project donations:** captured **immediately** after PayPal approval.

   **Authorize vs Vault (checkout):** PayPal authorizations are not opened more than **29 days** before the relevant arrival or departure. Near stops use Orders v2 **`AUTHORIZE`**; stops more than 29 days away save the payment method with PayPal **Vault** and charge on arrival (Vault is on for the hosted demo). On the demo clock **La Rochelle** (`dep-la-rochelle`) is near: `GET /api/escales/pledges/mode?milestone_id=dep-la-rochelle&kind=mile` returns **`AUTHORIZE`**. **Mayotte** is beyond the window: `GET /api/escales/pledges/mode?milestone_id=dep-dzaoudzi-mayotte&kind=mile` returns **`VAULT`**. Checkout follows `/pledges/mode`, whatever a Captain answer says about the intent.

4. **Demo treasurer, on your own pledge:** Press **Demo treasurer** at the bottom of the left panel (French: **Trésorier démo**). You see the queue of held pledges and the AI Captain's review of each stop with its sources, without supporter names. The pledge you made in step 3, from this same browser, is tagged **Yours** (French: **À vous**) and has live buttons, for real in the PayPal sandbox:
   - **Simulate arrival**: the boat arrives for that pledge only; the shared voyage clock and other pledges do not move;
   - **Approve**, then **Capture**; or **Void** instead to release the hold;
   - **Refund** once it is captured.

   Every other pledge is view-only: the server checks on each call that the pledge was made from your browser. **Back** or Escape returns to the map.

5. **AI Captain (optional, left panel):** Tap a suggested question such as **Where is the boat?**, or type your own (for example `Sponsor 20 miles near Mayotte`). Each answer says whether it came from a fixed rule in the code or from the model (NVIDIA Nemotron via NIM).

6. **Seeing a capture:** Capture needs the treasurer key, so on the public demo watch the treasurer capture flow in the [demo video (v7)](https://youtu.be/LszlcLdwzoQ).

## What needs the treasurer key

The key (HTTP header `x-admin-key`) is supplied privately and is **not in this repository**. Judges on the public demo do not need it. It is required for:

- **Capture**, **void** and **refund** of a pledge made from another browser, and approval of the Captain's review for a whole stop;
- **Run departure-day settle** and **Settle at this date**;
- the **Judge moment — La Rochelle** tools: **Simulate boat arrival**, **Cancel stop**, **Reset demo** (French: **Simuler l’arrivée du bateau**, **Annuler l’escale**, **Réinitialiser la démo**).

## What is on, and what is off, on the hosted demo

Read from `GET /api/escales/features` on escales.naviguide.fr on 11 Nov 2026.

| Feature | Hosted demo |
| --- | --- |
| PayPal Vault for far stops and cabins (`ESCALES_VAULT_ENABLED`) | **On** |
| Demo treasurer, live on your own pledges only (`ESCALES_DEMO_TREASURER`) | **On** |
| Crew membership (PayPal subscription) | **On** |
| Gear wishlists | **On** |
| Card Fields, pay by card in the page (`ESCALES_CARD_FIELDS_ENABLED`) | Off |
| Apple Pay / Google Pay (`ESCALES_WALLET_PAY_ENABLED`) | Off |
| Project onboarding after payment (`ESCALES_ONBOARD_AFTER_PAYMENT_ENABLED`) | Off |
| PayPal Web SDK v6 checkout (`ESCALES_PAYPAL_JS_V6_ENABLED`) | Off |

Because Card Fields are off, there is no card form in the page: pay through the PayPal button with the sandbox buyer. The onboarding flag is not reported by the features endpoint; its state is the deployment setting.

The checkout runs on PayPal's JS SDK v5. A Web SDK v6 checkout is merged behind `ESCALES_PAYPAL_JS_V6_ENABLED` (off by default, off on the hosted demo, sandbox only); see [PAYPAL_JS_V6_FLAG.md](PAYPAL_JS_V6_FLAG.md).

## Simulated clock

The voyage clock is **pinned to 12 Nov 2026 08:00 UTC** on the hosted demo (`GET /api/escales/clock`): 12 Nov 2026 is the PayPal AI Hackathon 2026 submission deadline and the virtual departure date. Stop statuses and capture eligibility follow this clock, not the wall clock.

## Run locally (optional)

**Python 3.12** and **Node.js 22** (see repository CI). Follow [README Quick start](../../README.md#quick-start). Set your own PayPal sandbox credentials in `bi-escales/backend/.env` (`PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`) and `VITE_PAYPAL_CLIENT_ID` in `bi-escales/frontend/.env.local`. Placeholders let the API and UI start, but PayPal checkout is rejected until real sandbox client ids are set. Set `ESCALES_DEMO_TREASURER=1` (with `PAYPAL_ENV=sandbox`) to enable the demo treasurer button locally.

Test counts in CI on `test/integration-2` at `e729a5b` (11 Nov 2026): backend **1078 passed, 2 skipped** (the 2 make real PayPal sandbox or NIM calls and need `ESCALES_RUN_LIVE=1`); frontend **797 passed** in 127 files, plus 3 node tests.

## Judging-window rate limits (public demo)

While **real UTC wall-clock time** falls inside the configured judging window (`ESCALES_JUDGING_START` / `ESCALES_JUDGING_END` on production hosts), the API raises captain and LLM budgets so many judges can try the app without exhausting provider quotas. The simulated voyage clock does **not** control this window.

| Limit | Value | Applies to |
| --- | --- | --- |
| Per minute | **36** requests | Shared bucket for `POST /api/escales/captain/chat` and captain review routes, per client IP |
| Per day | **9000** requests | Same captain routes, per client IP (UTC calendar day) |
| LLM daily cap | **9000** calls | Service-wide LLM budget per UTC day while the judging window is active |

Check live values on the deployment: `GET /api/escales/features` → `captain_rate` (`per_minute`, `per_day`, `judging_window_active`). Outside the judging window the production defaults apply: 10 per minute and 100 per day per IP for captain routes. On 11 Nov 2026 the hosted demo reported those defaults, with `judging_window_active: false`.

## Sandbox buyer account for judges

Use this PayPal **sandbox personal** buyer (France, EUR):

- **Email:** `berry-mappemonde-acheteur-fr@personal.example.com`
- **Password:** `<private Devpost testing-instructions field — not in git>`

When PayPal opens, the login field may be **pre-filled with the sandbox seller (merchant) account** used by the app. Log out or clear it, then sign in with the **buyer** email above.

Card Fields are **off** on the hosted demo, so there is no card form in the page. On a deployment where `ESCALES_CARD_FIELDS_ENABLED` is on, PayPal’s sandbox Visa test card **4111 1111 1111 1111** with any future expiry and CVV **123** can be used instead of logging into the buyer wallet.

## Optional credentials (operators only)

| Credential | Placeholder |
| --- | --- |
| Treasurer key (`x-admin-key`) | `<private Devpost testing-instructions field — not in git>` |
| PayPal REST client id / secret (local clone) | Your own sandbox app in the PayPal developer dashboard |

## Optional API smoke (no buyer login)

| Check | Endpoint |
| --- | --- |
| Health | `GET /api/health` |
| PayPal environment | `GET /api/escales/features` → `p2_eligibility.merchant.environment` = `sandbox` |
| Simulated clock | `GET /api/escales/clock` |
| Pledge mode preview | `GET /api/escales/pledges/mode?milestone_id=…&kind=mile` |
| Common fund | `GET /api/escales/common-fund/fund` |
| Captain (POST) | `POST /api/escales/captain/chat` with JSON `{"message":"Sponsor 20 miles near Mayotte","lang":"en"}` |

Treasurer list without key: on the hosted demo (demo treasurer on) `GET /api/escales/pledges` returns **200** with redacted rows (no contributor, payer or order ids). The treasurer's money routes (capture, void, refund, review approval) return **401** without `x-admin-key`, in demo mode too. The demo's own routes (`/api/escales/demo/pledges/{id}/…`) act only on a pledge whose creating browser presents that pledge's request id in `X-Pledge-Key`; anything else is **403**.
