# Source of the vendored APIMatic PayPal SDKs (APIM-9)

Both Python SDKs in this directory were generated **outside this repository**, on the maintainer's machine, on **2026-11-09**. This tree does not contain an APIMatic key, and generation does not need to be repeated here.

## Specs

Repository: [paypal/paypal-rest-api-specifications](https://github.com/paypal/paypal-rest-api-specifications) at commit `90e8041ffe02d80c452d2b476bedd59a8d219bdc`.

| API | Spec path | Vendored package | Import name | SDK version |
| --- | --- | --- | --- | --- |
| Payouts batch v1 | `openapi/payments_payouts_batch_v1.json` | `payouts-sdk-python/` | `payouts` | 1.9 |
| Partner Referrals v2 | `openapi/customer_partner_referrals_v2.json` | `partner-referrals-sdk-python/` | `partner_referrals` | 2.5 |

Spec URLs:

- https://github.com/paypal/paypal-rest-api-specifications/blob/90e8041ffe02d80c452d2b476bedd59a8d219bdc/openapi/payments_payouts_batch_v1.json
- https://github.com/paypal/paypal-rest-api-specifications/blob/90e8041ffe02d80c452d2b476bedd59a8d219bdc/openapi/customer_partner_referrals_v2.json

## Enum-description patch

APIMatic codegen rejects generated enum names longer than 100 characters. Before `apimatic sdk generate`, the same description was shortened in **both** specs:

- Original: `The requested action could not be performed, semantically incorrect, or failed business validation.`
- Patched: `The requested action failed business validation.`

`apimatic api validate` reported lint warnings only (missing examples and descriptions). Codegen validation passed after this patch.

## Generator

- CLI: `@apimatic/cli` **2.2.0**
- Command: `apimatic sdk generate -l python -f`
- Date: 2026-11-09

Each package keeps its upstream `LICENSE` (MIT, Copyright (c) 2026 APIMatic). The generated trees are vendored as produced. Do not regenerate them in CI.

## Runtime

Application code reaches these packages only through `app.escales.paypal_apimatic_extras`, and only when `ESCALES_APIMATIC_EXTRAS_ENABLED` is on and `PAYPAL_ENV` is `sandbox`. `paypal-server-sdk` 2.4.0 is a separate dependency and is not changed by this vendor drop.
