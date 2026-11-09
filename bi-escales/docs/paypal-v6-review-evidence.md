# PR 182 — PayPal Web SDK v6 review evidence

## Integration handoff

Preserve the existing feature branch and all commits. Future integration is through
`test/integration-3`, after Hamid finishes the safe baseline and reviews the larger
PRs individually. Review #182 last because it affects every checkout path.
Do not merge, push to an integration branch, retarget by rewriting history,
deploy, or change TEST2/production as part of this review. The future integration
branch was not present in the remote refs at the time of this evidence capture;
no branch was created and the existing PR base was not changed.

## Contract sources

- `@paypal/paypal-js@11.3.0`, public `sdk-v6` export. The adapter uses official
  `PayPalV6Namespace`, `SdkInstance`, card field and wallet types. One-time,
  save-payment and subscription sessions retain their distinct typed start
  promises; there is no invented shared start signature.
- Official PayPal examples: `paypal-examples/v6-web-sdk-sample-integration`,
  subscription, Apple Pay one-time, Google Pay/3DS, Pay Later and messages examples.
- Server SDK contracts remain a separate change in PR #173. Nothing here assumes
  that the two PRs have been merged or deployed together.

## Application v5 surface mapped to v6

| Existing capability | v6 contract / behavior | Evidence |
|---|---|---|
| Single SDK / locale / merchant / currency | Sandbox core; typed createInstance; BCP-47 locale; separate cached intent/flow instances | Adapter tests; build |
| Standard authorization | One-time session, Promise<{orderId}>, commit=false; server authorization remains authoritative | Unit tests; real React + Chromium with mocked SDK/API |
| Project capture checkout | One-time session, commit=true; same existing server route | Intent tests; React/Chromium project case |
| Wallet vault setup | Save-payment session, Promise<{vaultSetupToken}>; server vault registration | Unit tests; React/Chromium cabin vault case |
| Card authorization | Hosted number/expiry/CVV/name components; submit(orderId); succeeded state and matching token required | Card adapter tests; React/Chromium card case |
| Card vault setup | Save-payment card session; submit(vaultSetupToken); cancelled/failed states do not approve | Parametrized adapter tests |
| Subscriptions | paypal-subscriptions component; RECURRING_PAYMENT eligibility; createSubscription callback/action facade delegates to server; subscriptionId mapped to subscriptionID | Adapter + CrewSubscribeButton tests |
| Pay Later button | App amount/kind guard plus merchant eligibility; native button country/product from SDK; dedicated Pay Later session | Adapter metadata / intent / cleanup test |
| Pay Later message | paypal-messages component; createPayPalMessages + native paypal-message; amount/currency propagated | Adapter test |
| Google Pay (optional flag) | Independent merchant/native readiness; TEST native client; typed config formatter and confirmOrder; close sheet before 3DS; matching order and successful auth before server approval | Unit success, cancellation, duplicate, mismatch and 3DS tests; Chromium approval/3DS cases |
| Apple Pay (optional flag) | Native availability; merchant/domain validation; typed confirmation; matching order before server approval | Mocked native callback test and Chromium case; real device pending |
| Cleanup / retries / error handling | No simultaneous starts; closed sessions ignore approval/cancel callbacks; field and session destroy; no post-disposal submit | Adapter tests; browser checkout pending-order regression |

The browser suite deliberately delays mocked order creation. This guards a real
React lifecycle defect: toggling internal `busy` must not destroy the payment
session that is creating the order. External disablement still closes it.

Only one-time native wallet flows are offered here; vault pledges retain their
save-payment flow. Optional wallet flags stay off by default. Native wallet
confirmation does not bypass the application's treasurer approval or server routes.

## Reproduction and evidence boundaries

From `bi-escales/frontend`: `npm ci`, `npm test`, `npm run build`,
`npm run test:e2e`. Browser tests start an isolated loopback Vite server at port
5178 with a synthetic public sandbox identifier. SDKs, native wallets and HTTP
writes are mocked; no real PayPal resource is created and no TEST2 request occurs.
Browser traces/screenshots and raw payment-payload logging are disabled.

The seven browser cases cover React authorization, project capture, card, cabin
vault setup, Google Pay approval, Google Pay 3DS, and Apple Pay validation.
Unit/component tests cover the additional failures, disposal and subscription
paths. No test count or passing mock establishes live merchant eligibility.

Report code verification, sandbox API verification, browser contract E2E, native
wallet E2E and LangSmith ingestion separately. Local Apple association GET checks
establish exact serving of the bundled artifact, not sandbox domain registration.
See `paypal-v6-wallet-validation.md` for pending merchant-console actions.

## External blockers

GitHub REST is rejected during cloud proxy CONNECT (HTTP 403/Envoy), before
GitHub authentication. Existing scoped Git reads and feature-branch pushes work;
no credentials were replaced. No GitHub REST PR metadata edit is claimed.

APIMatic's public context host is blocked by policy, and the environment draft
read/save fails INVALID_ARGUMENT even with a single field. The saved network
list cannot be read, so no replacement list was submitted. The sole requested
infrastructure addition is chatbotapi.apimatic.io. Existing setup scripts and a
sanitized diagnostic report are retained outside Git under /workspace/.cloud-setup.

No PayPal sandbox credentials or LangSmith binding are available in this instance.
No authenticated sandbox API or remote trace ingestion has been verified. The
existing deployment and production configuration are untouched.

## Recorded results for this review

- `npm test`: 101 Vitest files, 550 tests passed; 3 advisory-label Node tests passed.
- `npm run build`: TypeScript and Vite passed. The existing large-chunk and
  optional trial-package source-map warnings remain nonblocking.
- `npm run test:e2e`: 7 Chromium tests passed with mocked providers and APIs.
- `pytest tests -m 'not live' -q -ra` on this branch's unchanged backend:
  922 passed, 2 external tests deselected; deprecation warnings only.
- Separately on #173: 957 backend tests passed, 2 external tests deselected;
  510 Vitest tests plus 3 Node tests and the frontend build passed.
- #173's local read-only preflight verified health and exact Apple association
  bytes at loopback. It explicitly did not verify sandbox APIs, native merchant
  wallets, or LangSmith ingestion.

No integration branch push, deployment, environment publication, merchant-console
change or real PayPal payment operation was performed.
