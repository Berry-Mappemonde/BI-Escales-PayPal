# Apple Pay and Google Pay — sandbox steps for Clément

These buttons are gated by `ESCALES_WALLET_PAY_ENABLED=1` on the API and the matching Vite env on the frontend build. No Render change is made by the agent; you register domains in the PayPal sandbox dashboard.

**Clément gate (prod):** Do not register `escales.naviguide.fr` in PayPal Apple Pay / Google Pay, change production Render env vars, or set `ESCALES_WALLET_PAY_ENABLED` on prod until Clément explicitly approves. Sandbox work on test2 (`bi-escales-api-test2.onrender.com`) is fine without that gate.

## Apple Pay (Safari, sandbox)

Official reference: [PayPal — Apple Pay](https://developer.paypal.com/docs/checkout/apm/apple-pay/).

1. Open [PayPal Developer Dashboard](https://developer.paypal.com/dashboard/) and ensure the **Sandbox** toggle is on.
2. Go to **Apps & Credentials** → open the sandbox REST app (e.g. **BI Escales Cartes**) → **Features** → enable **Apple Pay** → **Save**.
3. In the same app, open **Apple Pay** → **Manage** → review domains already listed → **Add Domain** and register the exact host where buyers see the button (for TEST2: `bi-escales-api-test2.onrender.com`; register every host you use, including subdomains).
4. The sandbox association file must be reachable at **exactly**  
   `GET https://<your-host>/.well-known/apple-developer-merchantid-domain-association`  
   with **HTTP 200**, **no redirect**, and no auth. PayPal recommends serving it as **`application/octet-stream`** (not `text/html` or `text/plain`). The API serves PayPal’s sandbox bytes from `backend/static/.well-known/` (9094 bytes). Optional override: `ESCALES_APPLE_PAY_DOMAIN_ASSOCIATION_FILE`.
5. After domain registration succeeds in the dashboard, use Safari with a **sandbox Apple ID** wallet and test cards; EUR merchant + FR buyer profile must stay eligible.
6. On TEST2, `ESCALES_WALLET_PAY_ENABLED=1` is already set; confirm `GET /api/escales/features` returns `"wallet_pay": true` after deploy.

Verify after deploy (coordinator):

```bash
curl -sI https://bi-escales-api-test2.onrender.com/.well-known/apple-developer-merchantid-domain-association
```

Expect `HTTP/1.1 200` and `Content-Type` starting with `application/octet-stream`.

## Google Pay (Chrome, sandbox)

Official reference: [PayPal — Google Pay](https://developer.paypal.com/docs/checkout/apm/google-pay/).

1. Same sandbox app → **Features** → enable **Google Pay** → **Save** (complete sandbox onboarding if the dashboard shows Google Pay as disabled).
2. Google Pay via the PayPal JS SDK does **not** use an Apple-style `/.well-known` association file. Ensure the feature is enabled and the page **origin** (scheme + host [+ port]) matches where the Escales UI is served (`ESCALES_PUBLIC_URL` / the URL in the browser address bar; no mixed http/https).
3. Use Chrome with Google Pay **test card suite** in sandbox (linked from PayPal’s sandbox testing section).
4. With `ESCALES_WALLET_PAY_ENABLED=1`, wire `loadPayPalWalletPaySdk` in the pledge sheet (see `paypalSdk.ts`) and render Apple Pay / Google Pay when the SDK reports eligibility.

## After registration

- Spot-check one **AUTHORIZE** pledge via Apple Pay and one via Google Pay; treasurer capture rule unchanged (arrival / leg departure / common fund at once).
- Add the new webhook event names in the PayPal listener if not already subscribed: `BILLING.SUBSCRIPTION.CREATED`, `PAYMENT.CAPTURE.REVERSED`, `PAYMENT.REFUND.COMPLETED` (the API already audits them when they arrive).
