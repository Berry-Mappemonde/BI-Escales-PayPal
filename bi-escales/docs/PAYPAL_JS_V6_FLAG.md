# PayPal Web SDK v6 behind a flag

The browser checkout can run on PayPal Web SDK v6 instead of the JS SDK v5 Smart Buttons. It is **off by default** and **sandbox only**. With the flag off the app behaves as it did before this change.

This is the v6 work of PR #182, moved to a separate code path chosen by a flag. It has **not** been proven with a real PayPal sandbox payment; see "What still needs a real sandbox payment".

## The flag

| | |
|---|---|
| Backend env var | `ESCALES_PAYPAL_JS_V6_ENABLED` (`1`, `true`, `yes`, `on`) |
| Features endpoint | `GET /api/escales/features` → `"paypal_js_v6": true/false` |
| Default | `false` |
| Outside the sandbox | Always `false`: `PAYPAL_ENV` other than `sandbox` keeps it off |

There is no frontend build variable. The page reads the flag from the features request it already makes when it starts.

## What the flag changes in the browser

| | Flag off (default) | Flag on |
|---|---|---|
| SDK script | `https://www.paypal.com/sdk/js?…` (v5, one per intent) | `https://www.sandbox.paypal.com/web-sdk/v6/core` (one) |
| Pledge button | `PledgeButtonInner` in `PledgeButton.tsx` | `PledgeButtonV6Inner` in `PledgeButtonV6.tsx` |
| Crew subscription | `CrewSubscribeButtonInner` in `CrewSubscribeButton.tsx` | `CrewSubscribeButtonV6Inner` in `CrewSubscribeButtonV6.tsx` |
| Apple Pay / Google Pay | `PayPalWalletPayBlock.tsx` | `PayPalWalletPayBlockV6.tsx` |
| Card fields | `PayPalCardFieldsBlock.tsx` | the same component, fed by the v6 adapter |
| SDK adapter | `src/paypal/paypalSdk.ts` | `src/paypal/v6/paypalSdkV6.ts`, `paypalWallets.ts`, `checkoutAttempts.ts` |

The v6 components keep the v5 markup, test ids, copy and the redirect fallback ("Continue with PayPal"). A v6 button carries `data-paypal-js="v6"` so QA can tell which path is on screen.

The backend payment routes are the same for both paths. Stop pledges are still authorised and captured by the treasurer; the Captain still only proposes.

## How the page chooses

`src/paypal/paypalJsVersion.ts` holds one decision per page load.

1. The default is v5.
2. The page announces its features request as it starts (`main.tsx`). Until that answer arrives, PayPal buttons render nothing, so none of them loads the v5 SDK before the flag is known. The wait is capped at 4 seconds; no answer, or a failed request, means v5.
3. v5 and v6 are never mixed on one page load.

**Timing with the flag off.** The Crew button now also waits for the features answer. Measured on escales.naviguide.fr on 11 Nov 2026, the features answer took 0.43–0.46 s and the Crew plan lookup 0.49–0.84 s, so the button is not expected to appear later. The pledge button already waited for the same endpoint before loading its SDK.

## What v6 adds over v5

- **Redirect returns (audit F01).** Each checkout is stored as an attempt in session storage (pledge id, order id, amount, currency, target; nothing secret). A v6 session that reports a return is resumed once, and the App return handler and the resumed session share one server call.
- **Stale form on approve (audit F02).** An approval is always reconciled against the pledge it was made for. If the payer changed the form while the PayPal window was open and then approved the older window, the older pledge is recorded, the edited form is not credited, and the page says which pledge was approved.
- **Subscription.** The plan shown is sent as a constraint and compared with the plan the server created. "Saved" is shown only after the server has verified the subscription is ACTIVE on that plan.
- **Eligibility.** Buttons are offered only when `findEligibleMethods` says so, for the payment flow, currency and amount.

## Not carried over from PR #182

- The backend subscription hardening (`expected_plan_id` validation, creation lock, cache check). It changes the subscription route that the v5 path also uses. The v6 browser code still checks the returned plan against the plan on screen.
- The Playwright mock end-to-end tests and the CI steps that install Chromium.
- The review documents under `docs/v6-readiness/`; their file and line references describe the in-place migration, not this layout. They remain in PR #182.

## What still needs a real sandbox payment

Nothing below can be shown by unit tests. Run each on test2 with `ESCALES_PAYPAL_JS_V6_ENABLED=true` and record PASS, FAIL or BLOCKED with the deployed SHA.

1. The v6 SDK accepts the sandbox client id and renders `<paypal-button>`.
2. Stop pledge, AUTHORIZE in EUR: approve in the popup, the pledge is held, then treasurer capture and void.
3. Project donation (capture) and the Pay Later button and message at €30 or more.
4. Cabin on a leg more than 29 days away: save the payment method (vault), then the later charge.
5. Crew subscription: approval, ACTIVE verification, plan check.
6. Redirect presentation (mobile or popup blocked): leave to PayPal, come back, refresh. Check whether the v6 session still reports the return after the App has removed the PayPal query parameters, and that the pledge is authorised once.
7. Change the amount while the PayPal window is open, then approve the old window: one ledger entry for the old pledge, the receipt line on screen.
8. Card fields with 3-D Secure, Apple Pay on a registered domain with Safari, Google Pay on a capable device.
9. The Crew button's appearance: the quiet black or silver style of the v5 button is passed to the adapter but v6 may ignore it.
10. English and French, desktop and phone.

## Turning it off

Unset `ESCALES_PAYPAL_JS_V6_ENABLED` and restart the API. The next page load uses v5.
