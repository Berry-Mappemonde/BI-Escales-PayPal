# Visual review — BI Escales (Pay Only If We Sail)

Desktop only (1440×900). Mobile viewports were not run.

Reviewed build: open PRs **#1–#4 and #7** (webhooks, ledger, NAVIGUIDE bridge, Vault, Hamid’s L9 fixes) plus **#2** (React) and **#6** (LLM cascade), integrated on this branch. PayPal is an in-memory sandbox stand-in (`ESCALES_PAYPAL_MOCK=1`). No live keys, no capture of real money.

Browser evidence is in [`diagnostics/BROWSER-DIAGNOSTICS.md`](diagnostics/BROWSER-DIAGNOSTICS.md) and [`diagnostics/browser-diagnostics.json`](diagnostics/browser-diagnostics.json). Listeners on every step: `console` (warning, error, assert), `pageerror`, `requestfailed`, and HTTP status ≥ 400.

## How the journeys were run

```bash
cd bi-escales/e2e-visual && npm test
```

Both Playwright tests passed on Chromium desktop. The API and Vite dev server are started by Playwright. `POST /api/escales/demo/reset` exists only when `ESCALES_PAYPAL_MOCK` is on and requires the local treasurer key.

## PayPal states

| State | In this build | Where it shows |
| --- | --- | --- |
| created | Yes | Timeline only. The treasurer queue stays empty. |
| authorized | Yes | Queue, badge, timeline |
| vaulted | Yes | Queue, Vault badge, timeline. Not counted by the gauges. |
| pending | Yes | Queue (webhook `PAYMENT.CAPTURE.PENDING` or a pending capture) |
| captured | Yes | Timeline and gauge. Leaves the queue. |
| settled | Yes | Webhook `PAYMENT.CAPTURE.COMPLETED`. Timeline only. |
| failed (denied) | Yes | Webhook `PAYMENT.CAPTURE.DENIED` stores `failed` and `paypal_status=DENIED`. |
| voided | Yes | Timeline and gauge. Leaves the queue. |
| refunded | **Not implemented** | The timeline says so. No refund API and no refund status. |

## Browser console, failed requests, uncaught exceptions

No `pageerror` (uncaught exception) and no `requestfailed` (dropped connection) on any step.

The only console errors are Chrome’s “Failed to load resource” lines for HTTP responses the journeys provoke on purpose. Each is listed with the screen, source, and a fix. Full tables are in the diagnostics file.

| Screen | Kind | Message | Source | Suggested fix |
| --- | --- | --- | --- | --- |
| `01-user-journey` / `07-wrong-admin-key` | http 403 + console error | `403 GET http://127.0.0.1:5173/api/escales/pledges` and `Failed to load resource: 403 (Forbidden)` | `http://127.0.0.1:5173/api/escales/pledges` | Expected probe of a bad treasurer key. The queue already shows the error. A rejected key is **403**, a missing key is **401**. Do not retry. Fetch cannot hide the browser’s network error; keep the inline message. |
| `01-user-journey` / `11-pledge-rejected-unknown-milestone` | http 422 + console error | `422 POST http://127.0.0.1:5173/api/escales/pledges` and `Failed to load resource: 422` | same URL | The captain wrote milestone id `mayotte`. That id has no arrival date, so create is refused. Map the slug to `dep-mayotte` (or another dated stop) before creating the order. |
| `02-paypal-journey` / `12-pending-void-rejected` | http 409 + console error | `409 POST …/pledges/{id}/void` and `Failed to load resource: 409 (Conflict)` | `bi-escales/frontend/src/components/TreasurerQueue.tsx` (buttons) and `bi-escales/backend/app/escales/pledges.py` (`void_pledge` allows only `authorized`) | Do not render Capture or Void unless the pledge is `authorized` or `vaulted`. |

Every other step of both journeys recorded **no** console warning, console error, failed request, or uncaught exception. See the diagnostics file for the empty tables.

The Vite process (not the page) also logged `Duplicate key "@testing-library/dom"` from `bi-escales/frontend/package.json`. That duplicate entry is removed in this branch. It never appeared in the page console.

## Top 10 issues by severity

1. **Calendar dates disagree with the ledger, and two stops are already in the past** (blocker for a jury). The schedule shows Mayotte `2026-09-01` and Fort-de-France `2026-08-15` with “date already past”, while the ledger arrival used for PayPal mode is `2026-11-14`. A supporter cannot tell whether AUTHORIZE (under 29 days) or Vault applies. Source: `naviguide_bridge.LOCAL_SCHEDULE` versus the milestone `meta.arrival_iso`. Screenshot: `screenshots/01-user-journey/02-language-en.png`. **Fix:** one date per stop, the same value the payment-mode function reads. Do not show August/September 2026 for a May 2027 voyage.

2. **The default captain chat cannot create a pledge** (blocker on the happy path). “20 milles près de Mayotte” suggests `milestone_id: "mayotte"`. `POST /pledges` returns 422 “a valid milestone arrival date is required”. The UI shows that error and a console 422. Source: `captain.py` `_place` plus `EscalesPanel` copying the suggestion into the form. Screenshot: `screenshots/01-user-journey/11-pledge-rejected-unknown-milestone.png`. **Fix:** suggest `dep-mayotte`, or resolve aliases onto a milestone that has `arrival_iso`.

3. **Pending pledges still have Capture and Void** (broken state, console 409). After `PAYMENT.CAPTURE.PENDING`, Void returns 409. The row stays pending. Source: `TreasurerQueue.tsx`. Screenshot: `screenshots/02-paypal-journey/12-pending-void-rejected.png`. **Fix:** only `authorized` and `vaulted` get those buttons. Pending needs a “waiting on PayPal” label and no action.

4. **Gauges drop most PayPal states.** They count only authorized, captured, and voided. A vaulted or pending hold shows as zero. The page now says so, but the chart still under-reports. Source: `frontend/src/utils/gauges.ts`. Screenshot: `screenshots/02-paypal-journey/11-webhooks-pending-denied-settled.png`. **Fix:** add vaulted, pending, failed, and settled, or drive the bars from the timeline totals.

5. **The captain is rules, not a model, and the decision is not the model’s.** With `ESCALES_LLM_ENABLED` unset, wording source is `rules`. Capture vs void still comes from `decision_for` before any LLM call (Hamid on PR #6). The English UI then shows a French fallback sentence. Source: `captain.py` `review`. Screenshots: `05-captain-chat.png`, `10-captain-review.png`. **Fix for the demo:** turn one provider on and show a validated `{summary, evidence_cited, concerns, confidence}` next to the proposal. Keep capture/void rule-gated.

6. **`created` is invisible in the queue.** A pledge that exists but is not yet authorized leaves the queue on “No authorized, vaulted, or pending pledges”. The new timeline shows it; the queue does not point at that timeline. Screenshot: `screenshots/02-paypal-journey/03-created-hidden-from-queue.png`. **Fix:** say “1 pledge is still waiting for approval” and link to the timeline.

7. **No refund, and settled ≠ captured.** Denied is `failed`. A completed webhook is `settled`, a treasurer capture is `captured`. There is no refund status, event, or button. The timeline states that on purpose. **Fix:** if the story needs a refund, add `PAYMENT.CAPTURE.REFUNDED` → `refunded` and a badge. Until then, do not claim refunds in the submission.

8. **The ledger is a JSON dump, and PayPal ids are truncated.** `DEMO-AUTH-DE…` cannot be checked against a webhook. The finance table stringifies `detail`. Screenshot: `screenshots/02-paypal-journey/14-finance-ledger.png`. **Fix:** columns for kind, PayPal status, order id, authorization id, capture id, amount. Full id on hover is not enough.

9. **“Capture (per proposal)” with no pledge ids.** The captain can propose capture before any pledge exists (`IDs: —`). The button is still shown and does nothing. Screenshot: `11-pledge-rejected-unknown-milestone.png`. **Fix:** hide the button when `pledge_ids` is empty, and say why.

10. **Supporter and treasurer share one screen, and the demo key is in the banner.** That is useful locally and wrong if this UI is deployed. `demo-local.sh` already refuses Render; the banner does not. The milestone list is also half-translated (`1 preuve(s)`). **Fix:** a role switch (supporter / treasurer), and keep `demo-admin-key` on the local banner only. Translate the evidence count.

### Also observed (not in the top 10)

- `html lang` stayed `fr` after the English switch in the screenshots. `setLanguage` now updates `document.documentElement.lang` (not re-screenshot).
- Focus rings were added (`:focus-visible`). Buttons and fields that were scanned have names. No skipped heading levels in the scan.
- AG Grid copy tells the jury this is not AG Studio. Bryntum never loads (flag off); the stop list is the real calendar.
- Health no longer flashes “backend down” before the first response.
- Vault approval is an external PayPal link plus “I approved — save it”. In mock mode the link is not a real approval. Say that on the link when `VITE_PAYPAL_MOCK=1`.

## Hamid’s reviews (PRs #1–#4, #6) and PR #7

PR **#7** (`hackathon/l9-fixes`) is included here. What the UI can now show:

- Treasurer queue reads `GET /api/escales/pledges`. Clearing `localStorage` does not drop rows (`13-queue-survives-without-localstorage.png`).
- Vault setup no longer dies with “order_id missing” (`06-vault-setup.png`, `07-vaulted.png`).
- `GET /api/escales/finance` is on screen (`14-finance-ledger.png`, `15-finance-ledger.png`).
- Webhooks update the pledge: pending, failed/DENIED, settled (`11-webhooks-pending-denied-settled.png`).
- Capture stores PayPal `COMPLETED` instead of assuming success (badge “PayPal: COMPLETED”).

Still not something a jury can see: webhook signature bytes, dedup on `event.id`, CORS, Mongo, and the reauthorize path. Those stay in pytest.

PR **#6**: the cascade is in the branch and idle. The screen shows `rules`. Hamid’s note stands: the model does not change the treasurer’s decision.

PR **#5** (NAVIGUIDE pytest) has no screen in this app.

## PayPal visibility proposal

What this branch already puts on the page:

- Sandbox demo banner, including the local treasurer key.
- In-app “Approve with PayPal (demo)” so the jury does not depend on `paypal.com/sdk/js`.
- PayPal badge (status, AUTHORIZE vs VAULT, auth / vault / capture id, PayPal status).
- Pledge timeline for every status, plus an explicit “refunded does not exist” line.
- Finance ledger panel.
- Wording-source line on the captain (`rules` in this demo).
- Calendar warning when the schedule date is past or differs from the ledger.

What should land next, in this order:

1. One arrival date per stop, shared by the calendar and `select_payment_mode`.
2. Captain suggestions that use real milestone ids.
3. Action buttons gated by status. Pending and failed are read-only.
4. Gauges that include vaulted, pending, failed, and settled.
5. Ledger columns instead of raw JSON.
6. A supporter / treasurer split, and a demo-mode flag on the Vault link.
7. Optional: `PAYMENT.CAPTURE.REFUNDED` if the script must show a refund.

## Screenshot index

`bi-escales/e2e-visual/screenshots/`

User journey:

- `01-user-journey/01-home-fr.png`
- `01-user-journey/02-language-en.png`
- `01-user-journey/03-milestones.png`
- `01-user-journey/04-evidence.png`
- `01-user-journey/05-captain-chat.png`
- `01-user-journey/06-queue-needs-key.png`
- `01-user-journey/07-wrong-admin-key.png`
- `01-user-journey/08-queue-loading.png`
- `01-user-journey/09-queue-empty.png`
- `01-user-journey/10-captain-review.png`
- `01-user-journey/11-pledge-rejected-unknown-milestone.png`
- `01-user-journey/12-pledge-authorized.png`
- `01-user-journey/13-queue-with-pledge.png`
- `01-user-journey/14-after-capture.png`
- `01-user-journey/15-finance-ledger.png`

PayPal journey:

- `02-paypal-journey/01-home-needs-key.png`
- `02-paypal-journey/02-empty-queue-and-ledger-ready.png`
- `02-paypal-journey/03-created-hidden-from-queue.png`
- `02-paypal-journey/04-authorized.png`
- `02-paypal-journey/05-authorize-batch.png`
- `02-paypal-journey/06-vault-setup.png`
- `02-paypal-journey/07-vaulted.png`
- `02-paypal-journey/08-captured.png`
- `02-paypal-journey/09-voided.png`
- `02-paypal-journey/10-vault-captured.png`
- `02-paypal-journey/11-webhooks-pending-denied-settled.png`
- `02-paypal-journey/12-pending-void-rejected.png`
- `02-paypal-journey/13-queue-survives-without-localstorage.png`
- `02-paypal-journey/14-finance-ledger.png`
