# PayPal Web SDK v6 wallet validation

The sandbox-only adapter uses the official `@paypal/paypal-js/sdk-v6` contracts.
Google Pay uses a TEST `PaymentsClient`, native readiness, and PayPal's
`createGooglePayOneTimePaymentSession`. Apple Pay uses native `ApplePaySession`,
merchant validation, and `createApplePayOneTimePaymentSession`. Each wallet checks
its own merchant/device eligibility; unavailable Apple Pay does not hide Google Pay.

A wallet confirmation never captures a milestone payment. The existing server
`authorizePledge` route remains authoritative. When Google Pay requires 3DS, the
native sheet closes before `initiatePayerAction`; server approval follows only
successful authentication. Vault pledges do not offer these one-time wallets.
The Pay Later message uses the v6 `paypal-message` component, not a v5 renderer.

## Reproducible offline checks

From `bi-escales/frontend`:

```bash
npm ci
npm test
npm run build
npm run test:e2e
```

The browser suite starts an isolated Vite server on loopback port 5178, uses
system Chromium by default (`PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` overrides it),
and mocks Google, Apple and PayPal. It creates no PayPal resources. Browser traces,
screenshots and raw payment payload logging are disabled. These checks establish
adapter and browser integration contracts, not live wallet or merchant eligibility.

## Sandbox API and browser E2E preparation

Use only the existing authorized sandbox connection. Enter credentials securely
in environment settings if the owner elects to enable it; never paste values into
chat, commit them, or add them to scripts. `VITE_PAYPAL_CLIENT_ID` is the public
sandbox client identifier, never the client secret. Keep `PAYPAL_ENV=sandbox`,
`ESCALES_ENV=development`, and local demo flags separate from production.

Before a real browser attempt, verify the sandbox application, merchant country,
wallet flags, HTTPS origin and enabled payment products in the merchant console.
Record outcomes as code verified, sandbox API verified, and browser E2E verified
separately. A passing mock or HTTP health check does not verify a sandbox payment.
This change prepares those checks but grants no authority to capture, void,
refund, release a vault or start a recurring charge. Those operations need the
owner's explicit action-specific authorization. Never run the live money-path
smoke script as an environment readiness check.

For an authorized one-time sandbox authorization attempt: choose a sandbox buyer,
a fixed small amount and an AUTHORIZE pledge, confirm once in the native sheet,
and verify the resulting authorized pledge through the existing read routes.
Stop before capture/void/refund. Do not reuse a real buyer or production card.
Keep network tokens, buyer details and payment-source payloads out of logs and traces.

## Apple Pay Sandbox merchant-console actions

1. Enable Apple Pay for the sandbox merchant/app in PayPal's dashboard.
2. Register the exact existing HTTPS test hostname, preferably the project's
   test2 hostname. Do not deploy or modify production from this task.
3. Obtain the sandbox domain association artifact from that merchant console.
   Compare it byte-for-byte with the configured artifact; do not manufacture a
   file or treat an unrelated merchant's artifact as verified.
4. Check `GET /.well-known/apple-developer-merchantid-domain-association` on that
   exact hostname: HTTP 200, no redirect/login, `application/octet-stream`, exact
   bytes. The repository's local route tests cover serving the bundled artifact;
   they do not establish deployed-domain registration or merchant ownership.
5. Finish verification in the console. Use Safari on a supported Apple device,
   an Apple sandbox tester, and a supported sandbox Wallet card. Chromium's mock
   test cannot establish native Apple Wallet readiness.

## Google Pay eligibility, independently

Enable Google Pay for the PayPal sandbox merchant. In a supported HTTPS browser,
check PayPal `isEligible("googlepay")` and native `isReadyToPay()` separately.
Use the merchant configuration from PayPal's formatter; do not invent a merchant
ID or reuse Apple's eligibility. TEST mode is mandatory here. Exercise ready,
ineligible, cancelled, APPROVED, failed confirmation, and PAYER_ACTION_REQUIRED
outcomes. Ensure 3DS rejection never reaches server approval. Google Pay native
script access (`pay.google.com`) is a separate prerequisite from PayPal access;
Apple's JS button uses `applepay.cdn-apple.com`. No network list replacement is
part of this change.

## LangSmith

Offline tracing tests establish redaction and fail-open behavior only. Real trace
verification requires an existing secure LangSmith binding and endpoint access.
Keep wallet/payment-source data out of traces. Do not claim ingestion merely
because a trace identifier was generated locally.
