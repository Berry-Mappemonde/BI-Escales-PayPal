# Native wallets on test2

This is an acceptance checklist, not a record of completed device tests.
Use only https://bi-escales-api-test2.onrender.com and French sandbox accounts.
Deployment and flag changes belong to the owner. The Apple domain association and
merchant app wallet enablement have already been configured; do not repeat them
unless merchant validation returns an actual configuration error.

After the owner deploys the payment PRs:

1. On iPhone 12 mini / Safari, select a near-arrival berth (30 EUR) and Apple Pay.
   The native sheet must show the displayed amount/currency. Approve personally.
   The application must record an authorization, without an immediate capture.
2. Repeat using a Google Pay compatible device/account in TEST mode.
3. On each device, approve an immediate common-fund donation. After PAY-03 (#252),
   it must be captured after buyer approval, without a treasurer action.
4. Repeat an ordinary linked project's donation. Native wallets now mount for
   CAPTURE-intent donations and retain the project's currency.
5. Cancel a sheet before approval: no capture or authorization may be recorded.
6. If order creation times out, retry the unchanged form: the browser keeps the
   same request id within that component instance. Reload persistence is not
   established by this change. If the amount/target changes, an old sheet is closed.
7. After each successful payment, report the displayed pledge reference and time
   to the payment implementer for server/PayPal receipt and persistent ledger checks.
   Do not share credentials, wallet tokens, addresses or payment instrument data.
8. Refund only the agreed sandbox capture and reread provider and ledger status.

Apple/Google wallet helpers in the installed v6 contracts are one-time sessions.
They are not offered for far-horizon Vault consent or Crew subscriptions. The
existing PayPal save-payment/subscription sessions remain those entry points.
Pay Later is shown only when the amount and provider eligibility permit it.

If blocked, record the stage (button eligibility, merchant validation, sheet,
3DS, provider confirmation, application receipt), exact sanitized error code,
device/browser, merchant app identity and domain. Do not enable unrelated app
options or change production configuration.
