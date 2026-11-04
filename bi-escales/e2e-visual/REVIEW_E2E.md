# End-to-end review — BI Escales (Pay Only If We Sail)

## Ledger persistence (decision)

Render’s free web service disk is ephemeral. The docs say local files, including a SQLite database, are lost on redeploy, restart, and whenever the free instance spins down after 15 minutes without traffic. A JSON snapshot on that disk has the same fate. Free Render Key Value is in-memory and also drops its data on restart.

Free Render Postgres is the option that keeps the ledger across those events. Limits, from [Render’s free-instance docs](https://render.com/docs/free): one free database per workspace, 1 GB, no backups, and the database expires 30 days after creation (14-day grace, then deletion). That window covers a hackathon demo if the database is created near the jury date. The web service can reach it on the private network. `render.yaml` creates `bi-escales-db` (plan `free`) and injects `DATABASE_URL`. `ESCALES_POSTGRES_ENABLED` stays empty in `.env.example`, so local pytest and the demo script keep the in-memory ledger. The blueprint turns the flag on for the deployed demo.

SQLite was rejected for this host. It would only be durable with a paid persistent disk, which free web services cannot attach.

## PayPal webhook signatures

`PayPalClient.verify_webhook_signature` posts the original raw body to `POST /v1/notifications/verify-webhook-signature`. `signature_client` uses that live client when a client id, a secret, and `PAYPAL_WEBHOOK_ID` are set. Test doubles and `DemoPayPalClient` set `webhook_signature_mock` and never call PayPal. `test_live_webhook_verify_reaches_sandbox` is skipped until those sandbox values exist; it then calls the real endpoint. A forged body is expected to come back `FAILURE` (or HTTP below 500), which is enough to prove the call left the process. No sandbox credentials are in this environment, so that live test is skipped here.

The AG Studio / AG Grid trial watermark stays. No license key is set for the hackathon.

## This fix branch

`hackathon/e2e-fixes` starts from `cursor/visual-review-playwright-4bec` and merges `hackathon/l8-llm` at `76b8a49`.

Checks on this branch:

| Suite | Result |
| --- | --- |
| `bi-escales/backend` pytest | 147 passed, 2 skipped (live PayPal order, live webhook verify — no sandbox credentials) |
| `bi-escales/frontend` vitest | 13 passed |
| `advisoryLabel.node-test.mjs` (`node --test`) | 3 passed |
| `npm run build` | passed; `TreasurerStudio-*.js` is a separate chunk (~6 MB), not the main bundle |
| Playwright `user-journey` + `paypal-journey` | 2 passed |
| `naviguide-escales` pytest | 1692 passed, 2 failed, 3 skipped, 1 collection error. The failures and `test_wind_float16` are the gaps PR #5 already fixes. That PR is not in this branch. |

Date of the run: 2026-11-04. Desktop Chromium, 1440×900. This file is the full review Clément asked for. The shorter visual pass remains in `REVIEW.md`.

## Scope and how the branches were combined

Open PRs **#1–#8** were merged **locally**, in this order, and **that merge was not pushed**:

| Order | PR | Branch | Already on this review branch before this run |
| --- | --- | --- | --- |
| 1 | #1 | `hackathon/l6-ops` | Yes (webhooks, ledger) |
| 2 | #2 | `hackathon/l2-front` | Yes (React) |
| 3 | #3 | `hackathon/l45-escales` | Yes (NAVIGUIDE bridge) |
| 4 | #4 | `hackathon/l7-vault` | Yes (Vault) |
| 5 | #5 | `hackathon/naviguide-tests` | Merged locally for this run only |
| 6 | #6 | `hackathon/l8-llm` | Yes (LLM cascade) |
| 7 | #7 | `hackathon/l9-fixes` | Yes (Hamid’s fixes for #1–#4) |
| 8 | #8 | `hackathon/l3b-ag-studio` | Merged locally for this run only |

PR **#9** (this draft) is the review branch. Checking out PR #9 alone does **not** contain PR #5 or PR #8. The AG Studio screenshots below were taken on the local merge. Nothing was merged on GitHub. `main` was not updated.

PayPal Orders were **not** sent to the live sandbox: this environment has `NVIDIA_API_KEY` and does **not** have `PAYPAL_CLIENT_ID` or `PAYPAL_CLIENT_SECRET`. The UI and the route matrix used the in-memory PayPal stand-in (`ESCALES_PAYPAL_MOCK=1`). A real HTTPS call was made to the sandbox OAuth host with a dummy client (see below). LLM calls used the real NVIDIA NIM endpoint.

## Code review

The product rule is intact: the captain proposes, the treasurer captures or voids. That split is visible in the UI copy and in `captain.py` (`decision_for` runs before the model).

What the combined tree gets right:

- AUTHORIZE vs Vault is chosen from the milestone arrival and `ESCALES_VAULT_ENABLED` (`payment_mode.py`). A missing date or a horizon of 29 days or more with Vault off raises `PaymentDeferred` (HTTP 422) instead of creating an authorization that would expire.
- Capture reads the PayPal status. Only `COMPLETED` and `PENDING` move the pledge. Anything else stays retryable.
- Webhooks dedupe on the event id and update the pledge (`VOIDED`, `CAPTURE.COMPLETED` → `settled`, `CAPTURE.DENIED` → `failed`, `CAPTURE.PENDING` → `pending`).
- The treasurer queue reads `GET /api/escales/pledges`. It is not the browser’s id list.
- AG Studio (PR #8) is behind `VITE_ENABLE_AG_STUDIO` and is not the same thing as `ag-grid-community`. The browser does not receive a provider key; `VITE_AG_STUDIO_LLM_ENDPOINT` is an optional proxy.

What the combined tree gets wrong, or leaves invisible:

- `suggest_pledge` turns “Mayotte” into the slug `mayotte`, not `dep-mayotte`. A real NIM call still returned that slug. The model only rewrites the sentence.
- `void_pledge` accepts only `authorized` (or `vaulted`). The queue still shows Void on `pending`, so the API returns 409.
- The calendar export (`LOCAL_SCHEDULE`) is August/September 2026. The ledger dates used for payment mode are about ten days ahead, or 15 May 2027 for the long leg. Both are on screen at once.
- `TreasurerGridAg.tsx` never calls `ModuleRegistry.registerModules`. With `VITE_ENABLE_AG_GRID=1` the console reports AG Grid error #272.
- AG Studio logs `License Key Not Found` as `console.error` and repeats it on every mount (language switch included). Features stay in trial with a watermark. The production bundle for `TreasurerStudio` is about 6 MB (1.7 MB gzip).
- `test_escales_l9_reviews.py` lists feature flags but not `ESCALES_LLM_ENABLED` or `ESCALES_LLM_NEBIUS_ENABLED`, which #6 added. `test_llm_cascade.py` creates a pledge on `dep-mayotte` without seeding an arrival, which #7 now rejects. The integrated tree does not have a green backend suite.
- The live captain, with NIM actually enabled, emitted a HelloAsso URL even though `HELLOASSO_MEMBERSHIP_URL` is empty. `filter_numbers` does not strip URLs.
- There is no `refunded` status.
- The demo ledger is in memory. A restart drops it. Webhook signatures in the demo client always return `SUCCESS`; that is not a PayPal verification.
- Gauges still count only authorized, captured, and voided. The Studio “Validation humaine” widget rendered “No data to display” while the status chart next to it showed captured and voided amounts.

## Tests run

| Suite | Command | Result |
| --- | --- | --- |
| Backend | `PYTHONPATH=. python3 -m pytest tests -q` in `bi-escales/backend` | **106 passed, 2 failed, 1 skipped** |
| Frontend | `npm test` then `npm run build` in `bi-escales/frontend` (after the local #8 merge) | **15 passed**. Build succeeded. `TreasurerStudio-*.js` is 6,086.71 kB (gzip 1,715.24 kB). Vite warned that the chunk exceeds 500 kB. |
| NAVIGUIDE | `python3 -m pytest -q` in `naviguide-escales` after `pip install -r server/requirements.txt` | **1696 passed, 3 skipped, 33 warnings** (151 s). The first attempt died at collection with `ModuleNotFoundError: dotenv` before that install. |
| HTTP matrix | `python3 /tmp/e2e_matrix.py` against uvicorn on port 8000 | Every route below. |
| Playwright | `journeys/full-life.spec.ts` against the already running Vite + API, flags `VITE_ENABLE_AG_GRID=1` and `VITE_ENABLE_AG_STUDIO=1` | **1 passed** (6.6 s). |
| Earlier Playwright on PR #9 (before #5 and #8) | `journeys/user-journey.spec.ts`, `journeys/paypal-journey.spec.ts` | **2 passed**. Still valid for the mock PayPal UI. They do not turn AG Studio on. |

Backend failures:

1. `test_every_escales_enabled_flag_is_off_by_default` — `FLAG_GETTERS` in `tests/test_escales_l9_reviews.py` omits the two LLM flags. The getters themselves default to off.
2. `test_captain_review_exposes_nim_and_never_captures` — `create_pledge(..., milestone_id="dep-mayotte")` raises `PaymentDeferred` because the test never seeds `arrival_iso`.

Skipped: `test_live_sandbox_create_authorize_order` because `PAYPAL_CLIENT_ID` is unset.

NAVIGUIDE warnings worth keeping: deprecated FastAPI `on_event("startup")` in `server/main.py`, deprecated `shapely.ops.transform`, and a duplicate OpenAPI operation id `polar_chat_removed_api_v1_polar_chat_get`.

### PayPal sandbox

`POST https://api-m.sandbox.paypal.com/v1/oauth2/token` with `grant_type=client_credentials` and a **dummy** client id/secret returned **401**. The sandbox host is reachable. No access token was issued and none is stored here. No order, authorization, vault setup, capture, or webhook signature was executed against PayPal. The pledge lifecycle in the browser used `DemoPayPalClient`.

### Real LLM

`ESCALES_LLM_ENABLED=1`, only `NVIDIA_API_KEY` set, Nebius left off. `active_providers()` was `['nim']`. Model `nvidia/nemotron-3.5-lightning-30b-a3b`.

| Call | Result |
| --- | --- |
| `llm.ask_text` (“la mer est calme”) | provider `nim`, 17 characters: “La mer est calme.” |
| `captain.chat` (“20 milles près de Mayotte”) | provider `nim`, same model. Suggested `milestone_id` is still **`mayotte`**. The prose included a HelloAsso URL that the environment did not configure. |
| `captain.review("dep-mayotte")` after simulated evidence | provider `nim`. `proposal` is `capture` (the rule, not the model). `pledge_ids` is empty because no pledge existed. |

The Vite demo used for screenshots kept `ESCALES_LLM_ENABLED` unset, so the on-screen wording source is `rules`. That is the default a jury gets if the key is not injected.

### 29-day rule (`select_payment_mode`, clock fixed at 2026-11-04)

| Case | Result |
| --- | --- |
| 28 days, Vault on | `AUTHORIZE` |
| 29 days, Vault on | `VAULT` |
| 30 days, Vault on | `VAULT` |
| missing date, Vault on | `PaymentDeferred` |
| 30 days, Vault off | `PaymentDeferred` (asks to enable Vault) |
| 10 days, Vault off | `AUTHORIZE` |

The boundary is `days >= 29`, not `> 29`.

### Every API route (uvicorn, mock PayPal, Vault and webhooks on)

| Route | Status |
| --- | --- |
| `GET /api/health` | 200 |
| `GET /api/escales/features` | 200 |
| `GET /api/escales/schedule` | 200 |
| `POST /api/escales/schedule/sync` | 200 |
| `GET /api/escales/milestones` | 200 |
| `POST /api/escales/milestones/dep-mayotte/evidence` | 200 |
| `POST /api/escales/captain/chat` (normal message) | 200 |
| `POST /api/escales/captain/chat` (blank message) | 422 |
| `POST /api/escales/captain/review/dep-mayotte` | 200 |
| `POST /api/escales/pledges` milestone `mayotte` | **422** |
| `POST /api/escales/pledges` milestone `dep-mayotte` | 200 `created` |
| `GET /api/escales/pledges/{id}` | 200 |
| `POST /api/escales/pledges/{id}/authorize` | 200 `authorized` |
| `GET /api/escales/pledges` no key | 401 |
| `GET /api/escales/pledges` bad key | 403 |
| `GET /api/escales/pledges` treasurer key | 200 |
| `POST .../capture` no key | 401 |
| `POST .../capture` with key | 200 `captured` |
| `POST .../void` on an authorized pledge | 200 `voided` |
| `POST /api/escales/webhooks/paypal` without transmission headers | 400 |
| `POST /api/escales/webhooks/paypal` `PAYMENT.CAPTURE.PENDING` | 200, pledge becomes `pending` |
| `POST .../void` on that pending pledge | **409** |
| `POST /api/escales/pledges` milestone `dep-long-haul` | 200 Vault setup token |
| `POST /api/escales/pledges/{id}/vault` | 200 `vaulted` |
| `GET /api/escales/finance` no key | 401 |
| `GET /api/escales/finance` with key | 200 |
| `GET /api/escales/pledges/does-not-exist` | 404 |
| `POST /api/escales/demo/reset` no key | 401 |

`POST /api/escales/demo/reset` exists only when `ESCALES_PAYPAL_MOCK=1`.

## User journeys (browser)

Server: real FastAPI (`scripts/e2e-backend.sh`) and real Vite. PayPal button is the in-app demo button, not `paypal.com/sdk/js`. AG Grid and AG Studio flags were on.

1. French home (`01-fr-home.png`). Health is “Backend disponible”.
2. English. Calendar shows Mayotte `2026-09-01` and Fort-de-France `2026-08-15` as already past, and the ledger date `2026-11-14` beside them (`02-en-calendar-mismatch.png`).
3. Empty treasurer queue after reset (`03-en-empty-queue.png`).
4. Captain chat, then PayPal approve. The form now says milestone `mayotte`. API 422, red error “a valid milestone arrival date is required” (`04-en-mayotte-422.png`).
5. Milestone corrected to `dep-mayotte`. Pledge authorized (`05-en-authorized.png`).
6. Treasurer capture (`06-en-captured.png`).
7. Second pledge voided (`07-en-voided.png`).
8. Long-haul milestone opens the Vault setup panel (`08-en-vault-setup.png`) and saves the method (`09-en-vaulted.png`). Nothing is captured yet.
9. Captain review. On this server the wording source is `rules`. The selected milestone was the long-haul leg, so the proposal is `wait` (`10-en-captain-review.png`).
10. AG Grid community mount (`11-en-ag-grid.png`) and AG Studio (`12-en-ag-studio.png`, French `13-fr-ag-studio.png`). Studio shows “Validation humaine” (“No data to display”), a “Montants par statut” column chart (captured and voided), and a pledge grid.
11. French ledger load (`14-fr-ledger.png`).

Console on that journey:

- Step 1: AG Grid error **#272**, no community modules registered. Source `ag-grid-react.js` via `TreasurerGridAg.tsx`. **Fix:** `ModuleRegistry.registerModules([AllCommunityModule])` before rendering the grid.
- Step 2 and the French Studio step: `console.error` banner “AG Studio Pro with AI / License Key Not Found”, trial unlocked, watermark unless `info@ag-grid.com` issues a key. Source `ag-studio` (`chunk-HL36OKWO.js`). **Fix:** set `VITE_AG_GRID_LICENSE_KEY` for the jury build, or stop calling `console.error` for an expected empty trial key. The message is repeated because the Studio tree remounts (React strict mode and the language `key`).
- Step 4: `422` on `POST /api/escales/pledges` plus Chrome “Failed to load resource”. **Fix:** map the place slug onto `dep-mayotte` in `captain.py` `_place` / `suggest_pledge`.
- No `pageerror` and no `requestfailed`.

Accessibility scan on the Studio page: several AG inputs have no label (`ag-input-field-input`). That comes from AG Studio / AG Grid, not from the pledge form. The app’s own buttons and fields stayed labelled. `html lang` now follows the language switch in the source that was reviewed; the screenshots were taken with that code.

## Bugs ranked by severity

1. **Blocker — sandbox orders were not executed.** No PayPal client id or secret is available here, so authorize, capture, void, and Vault were not proven against `api-m.sandbox.paypal.com`. The dummy OAuth call returned 401, which only proves the host answers. **Fix:** run `pytest -m live` with sandbox credentials and one buyer approval in the PayPal sandbox. Do not commit the secrets.
2. **Blocker — default supporter path cannot pay.** Chat suggests `mayotte`. Create returns 422. Reproduced on the API and in the browser, including when NIM is really on. **Fix:** suggest `dep-mayotte` (or resolve aliases to a milestone that has `arrival_iso`) before `create_pledge`.
3. **High — calendar and ledger dates disagree, and two stops are in the past.** A juror cannot tell whether the next leg is inside the 29-day window. **Fix:** one `arrival_iso` per stop, the same value `select_payment_mode` reads. Drop the August/September 2026 fixture for a May 2027 voyage.
4. **High — Void (and Capture) on a pending pledge returns 409.** The webhook path into `pending` works; the buttons do not. **Fix:** render those buttons only for `authorized` and `vaulted`.
5. **High — integrated backend suite is red.** Two tests fail when #6 and #7 sit together (`FLAG_GETTERS`, unseeded `dep-mayotte` in the NIM review test). **Fix:** add the LLM flags to `FLAG_GETTERS` and call `seed_near()` in the LLM test.
6. **High — AG Grid flag draws a broken grid.** Error #272. The HTML fallback is fine when the flag is off. **Fix:** register `AllCommunityModule` in `TreasurerGridAg.tsx`.
7. **Medium — AG Studio is a trial watermark, a 6 MB chunk, and a “No data” validation widget.** The status chart does show money. Console is flooded with license errors. The agent does not call NIM unless `VITE_AG_STUDIO_LLM_ENDPOINT` is set. **Fix:** license key for the demo, code-split confirmation, and a data mapping that feeds the validation widget the same rows as the chart.
8. **Medium — NIM does not choose the pledge or the capture/void decision, and it can invent a URL.** Confirmed with a live call. **Fix:** keep the decision rule-gated, but reject milestone ids that are not in the catalogue, and drop URLs that are not `HELLOASSO_MEMBERSHIP_URL`.
9. **Medium — gauges and the queue hide states the timeline now shows.** `created` is absent from the queue. Vaulted and pending are absent from the gauges. **Fix:** count them, and don’t say the queue is empty when `created` rows exist.
10. **Medium — no refund, and demo PayPal is not PayPal.** `settled` (webhook completed) and `captured` (treasurer) are different. Webhook signatures are not verified in the mock. The ledger is RAM. **Fix:** say so on the demo banner; add `PAYMENT.CAPTURE.REFUNDED` only if the script needs a refund; keep a real sandbox recording for the submission video.

## Recommended fix order

1. Put sandbox credentials in the deploy vault and record one real AUTHORIZE → capture and one Vault setup. Leave them out of git.
2. Map captain places onto real milestone ids. Add a test that “20 milles près de Mayotte” creates a pledge.
3. Make the calendar read the ledger arrival. Add a test that the schedule date and `meta.arrival_iso` match.
4. Gate Capture and Void. Add a test that voiding a `pending` pledge is not offered, or returns a dedicated message without a button.
5. Repair the two red backend tests so #6 and #7 can merge.
6. Register AG Grid modules. Put an AG Studio license in `VITE_AG_GRID_LICENSE_KEY` for the jury build only.
7. Show vaulted, pending, failed, and settled in the gauges. Point the empty queue at `created` rows.
8. Strip unconfigured URLs from captain prose.

## Screenshots

`bi-escales/e2e-visual/screenshots/03-full-e2e/`

- `01-fr-home.png`
- `02-en-calendar-mismatch.png`
- `03-en-empty-queue.png`
- `04-en-mayotte-422.png`
- `05-en-authorized.png`
- `06-en-captured.png`
- `07-en-voided.png`
- `08-en-vault-setup.png`
- `09-en-vaulted.png`
- `10-en-captain-review.png`
- `11-en-ag-grid.png`
- `12-en-ag-studio.png`
- `13-fr-ag-studio.png`
- `14-fr-ledger.png`

Per-step console tables, including the earlier mock journeys, are in `diagnostics/BROWSER-DIAGNOSTICS.md`.
