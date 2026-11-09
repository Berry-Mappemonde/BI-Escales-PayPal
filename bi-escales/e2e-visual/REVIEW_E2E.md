# REVIEW_E2E

## Live sandbox + Render

Checked 2026-11-04 against PayPal sandbox (`https://api-m.sandbox.paypal.com`) and the public API `https://bi-escales-api.onrender.com`. `PAYPAL_CLIENT_ID` and `PAYPAL_CLIENT_SECRET` were present. Every PayPal call used `PAYPAL_ENV=sandbox`. No secret values are recorded here.

`python3 -m pytest tests -q` in `bi-escales/backend`: **151 passed**, 0 failed, 0 skipped. That includes `test_live_sandbox_create_authorize_order` (order `2BM569920J8802701`, status `CREATED`, intent `AUTHORIZE`) and `test_live_nim_answers`.

The live probe failed once before the fix: PayPal's default create response is minimal and omits `intent`. The idempotency key `escales-live-probe` had cached that minimal body (order `1G7777481M996702A`). POST and PATCH now send `Prefer: return=representation`, and the probe uses the new key `escales-live-probe-v2`. If `intent` is still absent, the test reads the order with GET.

### Local app

Local uvicorn, memory store, `ESCALES_VAULT_ENABLED=1`, `ESCALES_ENV=development`. A schedule file supplied two milestones: `dep-mayotte-soon` arriving 2026-11-20 (16 days, AUTHORIZE) and `dep-mayotte-far` beyond the 29-day horizon (VAULT when vault is enabled).

PayPal wallet approval cannot be completed from this environment: there is no sandbox buyer login. The automatable path is PayPal's documented server-side card flow (sandbox Visa test card, last digits 1881): `confirm-payment-source` for an AUTHORIZE order, and a card setup token for Vault. The app's own routes then authorize, capture, void, register, and delete.

| Flow | Result | PayPal ids and status |
| --- | --- | --- |
| Create order, intent AUTHORIZE | PASS | Order `4M9711032E398663V`, status `CREATED`, intent `AUTHORIZE`. Approve link host `www.sandbox.paypal.com`. Pledge `d5c1de493a0e4d08aef56173984c9067`, status `created`. |
| Authorize before buyer approval | FAIL, expected | App `POST /authorize` returned 502. PayPal `422 ORDER_NOT_APPROVED` (debug id `f7465059fc5b1`): the payer must open the approve link, or the authorize call must include a `payment_source`. |
| Authorize then capture | PASS | Card confirm moved order `8LU76896JR596910X` to `APPROVED`. App authorize created authorization `3TS017223A9769142` (expires `2026-12-03T03:47:58Z`). App capture (treasurer) left the authorization `CAPTURED` and capture `5RH3633705491930K` `COMPLETED`, 1.00 EUR. Order status `COMPLETED`. Pledge `d6ebbb39b6044a1eb272328abb37c48c` history `created → authorized → captured`. |
| Void | PASS | Order `2U6394394L107323K`. Authorization `6J488400JJ941812U` status `VOIDED`. Pledge `2e525cc32f4244efb80803b13cc97c0c` status `voided`. |
| Vault, PayPal wallet, milestone ≥ 29 days | BLOCKED, human approval | Pledge `cb0896ffb48a4167bc740b6468378de1`, mode `VAULT`. Setup token `2X953818LM923664T` status `PAYER_ACTION_REQUIRED` (approve link on `www.sandbox.paypal.com`). App register returned 502. Exchanging the token returned `422 PAYER_ACTION_REQUIRED` (debug id `f5315094e3e5e`). |
| Vault payment token, card setup, then app capture | PASS | Setup token `49403278KX167763R` status `APPROVED`. App register stored payment token `3mf31625fa6237830`, `vault_source=card`, pledge `3e4cb510366e4fa88bfbca310bdc5f2d` status `vaulted`. App capture created order `0GF079967T3338723` intent `CAPTURE`, status `COMPLETED`, capture `0DT95954V47751352` `COMPLETED`, 1.00 EUR. |
| Vault void (delete payment token) | PASS | Setup token `6U207466DC286361P` `APPROVED`. Payment token `1ee49771f7717413v`. Pledge `63b6144353814e9488c016024c0c15c4` status `voided`. |

The first card-token capture through the app returned 502. PayPal's reason was `MISMATCHED_VAULT_ID_TO_PAYMENT_SOURCE`: `charge_vaulted` always sent `payment_source.paypal.vault_id`, and this token is a card (direct charge of token `2ny13145tf1428310` did succeed: order `4E764124UK5564722`, capture `7BA718547X870844F`, both `COMPLETED`). The client now charges `payment_source.card` when the payment-token response contains a card, and `payment_source.paypal` otherwise. The PASS row above is the app route after that fix. A PayPal-wallet token still cannot be stored until a buyer approves the setup token.

### Webhook signatures

`POST /v1/notifications/verify-webhook-signature` is reachable with the sandbox client credentials.

| Call | Result |
| --- | --- |
| Forged signature, webhook id `60S11973T4940444M`, alphanumeric transmission id | HTTP 200, `verification_status=FAILURE` |
| Same forged signature through the local app (`ESCALES_WEBHOOKS_ENABLED=1`, that webhook id) | HTTP 401, detail `PayPal webhook signature rejected` |
| Webhook id literal `WEBHOOK_ID` (the string in PayPal's simulator docs) | HTTP 400 `INVALID_REQUEST`, field `/webhook_id`, pattern `^[a-zA-Z0-9]+$` (debug id `f604220d5f536`). The underscore is rejected. |
| Earlier malformed probe (`WEBHOOK_ID` plus a hyphenated transmission id) | HTTP 400. The local app maps that PayPal HTTP error to 502 `PayPal signature verification failed`, which is a transport failure, not a signature decision. |
| `GET /v1/notifications/webhooks` | One webhook, id `60S11973T4940444M`, host `bi-escales.onrender.com`. Event names: `CHECKOUT.ORDER.APPROVED`, `PAYMENT.AUTHORIZATION.CREATED`, `PAYMENT.AUTHORIZATION.VOIDED`, `PAYMENT.CAPTURE.COMPLETED`, `PAYMENT.CAPTURE.DENIED`, `VAULT.PAYMENT-TOKEN.CREATED`. |

Limits:

- The simulator's documented webhook id `WEBHOOK_ID` does not pass the live verify schema. A real alphanumeric webhook id does, and a forged signature is `FAILURE`.
- `simulate-event` was not called. The only registered webhook points at `bi-escales.onrender.com`, not at `https://bi-escales-api.onrender.com`. Firing it would deliver a mock event to that other host. The public API has webhooks disabled, and a webhook on the API URL is still to be created.
- No signed simulator payload was available, so this run does not show `verification_status=SUCCESS`. The checked path is: well-formed request, PayPal returns `FAILURE`, the app answers 401 and does not record the event.

### Render (`https://bi-escales-api.onrender.com`)

Read-mostly. Four captain calls, under the production limit of 10 per minute. No admin key was sent, so capture and void were not attempted. The service answered on the first request (no cold-start failure in this run). `server: cloudflare`.

| Check | Result |
| --- | --- |
| `GET /api/health` | PASS. `{"status":"ok"}`. |
| `GET /api/escales/features` | PASS. `vault: true`. Naviguide, elastic, kernel, channel3, and bryntum are false. |
| `GET /api/escales/milestones` | PASS. HTTP 200, empty list. Memory store, nothing synced. |
| `GET /api/escales/schedule` | PASS. `source: local`. Built-in rows: `dep-mayotte` arrival `2026-09-01`, `dep-fort-de-france` arrival `2026-08-15`. |
| `GET /api/escales/pledges/does-not-exist` | PASS. HTTP 404 `Pledge not found`. |
| Captain chat, French | PASS. HTTP 200, `model_source.provider=rules`. Suggested 20.00 EUR, intent `AUTHORIZE`, description `20 milles parrainés`. Excerpt: `Promesse calculée, sans débit : 20 milles parrainés (20,00 €), Unspecified, autorisation.` |
| Captain chat, English | PASS. HTTP 200, rules. Suggested 20.00 EUR, intent `AUTHORIZE`, description `20 sponsored miles`. Excerpt: `Computed pledge, no charge: 20 sponsored miles (20.00 EUR), Unspecified, intent AUTHORIZE.` |
| Captain review `dep-mayotte`, `Accept-Language: fr` | PASS. HTTP 200, proposal `wait`, rules. French report, treasurer-only capture/void. |
| Captain review `dep-mayotte`, `Accept-Language: en` | PASS. HTTP 200, proposal `wait`, rules. English report, same decision. |
| `POST /api/escales/pledges` (1.00 EUR, `dep-mayotte`) | PASS. Pledge `6fd1bd2aa9724232be53353a1c41976e`, mode `AUTHORIZE`, status `created`. Order `5WU83974N88528910`, confirmed on sandbox as `CREATED` / `AUTHORIZE`. |
| `POST /authorize` on that pledge | FAIL, expected. HTTP 502. A later GET still shows status `created`. Same buyer-approval gate as local. |
| `POST /api/escales/webhooks/paypal` | PASS for the disabled flag. HTTP 404 `Not Found`. |

No 429. The four captain calls stayed inside 10 per minute.

Differences versus the local probe:

- Render does not have the Naviguide bridge on, so the schedule is the built-in export. Both arrivals are already past (4 Nov 2026), so the horizon is 0 days and a pledge stays `AUTHORIZE` even though `vault` is true. Locally, `dep-mayotte-far` (far stop on the itinerary, beyond the 29-day horizon) selected `VAULT`.
- The milestone collection on Render is empty until something syncs it. The schedule route still returns the static export.
- Webhooks are off on Render (404). Locally the route was turned on only to exercise verify-webhook-signature.
- Chat and review on both sides came back from the rules provider, not from an LLM completion, in this run. Place detection only matches `près de` / `near`, so these Mayotte sentences stay `unspecified`. That is the same code on both hosts. The local chat samples said `20 euros`, which is not a mile count, so the captain defaulted to 1.00 EUR. The Render samples said `20 milles` / `20 miles` and correctly suggested 20.00 EUR.
- Render pledges sit in process memory. A restart drops pledge `6fd1bd2aa9724232be53353a1c41976e`; the PayPal order remains.
- These Render checks ran against the deployment of `1139c15` (before this push). Create and the unapproved authorize result do not depend on the `Prefer` header or the card-vault charge fix. Those two fixes ship with the push that follows this note and will redeploy Render.
