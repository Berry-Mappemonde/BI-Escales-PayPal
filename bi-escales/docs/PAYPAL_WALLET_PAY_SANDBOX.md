# Apple Pay and Google Pay — sandbox steps for Clément

These buttons are gated by `ESCALES_WALLET_PAY_ENABLED=1` on the API and the matching Vite env on the frontend build. No Render change is made by the agent; you register domains in the PayPal sandbox dashboard.

## Apple Pay (Safari, sandbox)

1. Open [PayPal Developer Dashboard](https://developer.paypal.com/dashboard/) → your sandbox REST app → **Apple Pay**.
2. Register the **domain** where the Escales UI is served (for TEST: `bi-escales-api.onrender.com` if the app is served from there, or your local tunnel hostname if you test locally).
3. Download/host the **domain association file** at `https://<domain>/.well-known/apple-developer-merchantid-domain-association` (PayPal shows the exact file content).
4. In sandbox, use an Apple Pay–capable Safari session with a **sandbox Apple ID** wallet; EUR merchant + FR buyer profile must stay eligible.
5. Set `ESCALES_WALLET_PAY_ENABLED=1`, rebuild the frontend with `VITE_PAYPAL_CLIENT_ID`, redeploy TEST, and confirm `GET /api/escales/features` returns `"wallet_pay": true`.

## Google Pay (Chrome, sandbox)

1. Same PayPal app → **Google Pay** → add the same **origin** (scheme + host + port) as the Escales page.
2. Use Chrome with a **Google Pay test card** in sandbox mode (PayPal docs: Google Pay sandbox card suite).
3. Confirm the origin matches `ESCALES_PUBLIC_URL` / the page the buyer uses (no mixed http/https).
4. With the flag on, the pledge sheet shows Google Pay when the SDK reports eligibility.

## After registration

- Spot-check one **AUTHORIZE** pledge via Apple Pay and one via Google Pay; treasurer capture rule unchanged (arrival / leg departure / common fund at once).
- Add the new webhook event names in the PayPal listener if not already subscribed: `BILLING.SUBSCRIPTION.CREATED`, `PAYMENT.CAPTURE.REVERSED`, `PAYMENT.REFUND.COMPLETED` (the API already audits them when they arrive).
