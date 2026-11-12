# PayPal Server SDK read contract (APIM-2)

Read-only bridge from `PayPalClient` to `paypal-server-sdk` **2.4.0** (import package
`paypalserversdk`, tag `2.4.0` of `paypal/PayPal-Python-Server-SDK`). Sandbox only.
The SDK proposes nothing and moves no money: these seven operations are GETs.

Source of signatures: the generated controllers at that tag, not the installed
package docs (`doc/` is not shipped in the wheel).

## Client

| Item | Value |
| --- | --- |
| Class | `PaypalServersdkClient` in `paypalserversdk.paypal_serversdk_client` |
| Construction | Keyword arguments. One process-wide client, built on first use. |
| Environment | `Environment.SANDBOX` only. Base URI `https://api-m.sandbox.paypal.com`. |
| Refusal | Build raises if `PAYPAL_ENV` is not `sandbox`, or if the resolved base URI is not the sandbox host. `Environment.PRODUCTION` (`https://api-m.paypal.com`) is never passed. |
| Auth | `ClientCredentialsAuthCredentials(o_auth_client_id, o_auth_client_secret)` from `PAYPAL_CLIENT_ID` / `PAYPAL_CLIENT_SECRET`, kwarg `client_credentials_auth_credentials=`. |
| Token | Client-credentials grant. The SDK POSTs `/v1/oauth2/token` on the same client before the first operation, then caches the token. |
| Timeout | `timeout=30` (same budget as the httpx client). Per request, not a deadline over token fetch plus operation. |
| Retries | `max_retries=0` passed explicitly. A non-2xx surfaces on the first attempt. |
| Flag | `ESCALES_PAYPAL_SDK_ENABLED` truthy (`1`, `true`, `yes`, `on`) selects this gateway. Empty or anything else keeps the httpx path. The `paypalserversdk` import happens only inside the gateway, and only after the flag and sandbox checks pass. |
| Return value | `APIHelper.to_dictionary(ApiResponse.body)`. Callers still receive a `dict`, the same shape `PayPalClient._req` returns from `response.json()` for a body the model accepts. |
| Errors | `ApiException` (and subclasses) become `PayPalError(response_code, response.text)`. `response_code` is the HTTP status. `response.text` is the raw body string, matching the httpx path. |

`ApiResponse` fields used: `.body` (model). Status and headers stay on the envelope and are not copied into the dict.

### Serialization limits

`APIHelper.to_dictionary` walks the model `_names` map and skips attributes that were never assigned (`APIHelper.SKIP`). Consequences for parity with the raw httpx JSON:

- Unknown JSON fields are dropped. They are not on the model.
- Absent optional attributes stay absent. They are not `null`.
- Generated `from_dictionary` treats many optional scalars as missing when the value is falsy. `0` and `""` can disappear. Booleans use key presence, so `false` survives. A billing-cycle `total_cycles` of `0` is therefore rewritten to the model default `1`.
- `SetupTokenResponse` always materializes `status`. Omitted status comes back as `CREATED`.
- A vault PayPal wallet object always materializes `permit_multiple_payment_tokens` (default `false`).

Dicts compared in tests are bodies the model round-trips unchanged.

## Operations

Controllers are lazy properties on the client (`client.orders`, not `OrdersController()`).
Two call shapes exist. Shape 2 takes one `options` dict. Shape 1 takes plain arguments.
Every call below is `HttpMethodEnum.GET` on `Server.DEFAULT`.

### 1. `orders.get_order`

| | |
| --- | --- |
| `PayPalClient` | `get_order(order_id: str) -> dict` |
| SDK | `client.orders.get_order(options: dict)` — shape 2 |
| HTTP | `GET /v2/checkout/orders/{id}` |
| Request | `options["id"]` path. Optional, not sent by this gateway: `paypal_mock_response` (`PayPal-Mock-Response`), `paypal_auth_assertion` (`PayPal-Auth-Assertion`), `fields` query. |
| Response model | `Order` |
| Wire fields | `id`, `intent`, `status`, `create_time`, `update_time`, `payment_source`, `processing_instruction`, `payer`, `purchase_units`, `links` |
| Errors | `401` `ErrorException`, `404` `ErrorException`, other `ErrorException` (`default`). Unboxed when the body is a JSON object: `name`, `message`, `debug_id`, `details`, `links`. |

### 2. `payments.get_authorized_payment`

| | |
| --- | --- |
| `PayPalClient` | `get_authorization(authorization_id: str) -> dict` |
| SDK | `client.payments.get_authorized_payment(options: dict)` — shape 2 |
| HTTP | `GET /v2/payments/authorizations/{authorization_id}` |
| Request | `options["authorization_id"]` path. Optional, not sent: `paypal_mock_response`, `paypal_auth_assertion`. |
| Response model | `PaymentAuthorization` |
| Wire fields | `id`, `status`, `status_details`, `amount`, `invoice_id`, `custom_id`, `network_transaction_reference`, `seller_protection`, `expiration_time`, `links`, `create_time`, `update_time`, `supplementary_data`, `payee` |
| Errors | `401` `ErrorException`, `403` `ErrorException`, `404` `ErrorException`, `500` base `ApiException` (no unboxed fields), other `ErrorException` (`default`). |

### 3. `vault.get_setup_token`

| | |
| --- | --- |
| `PayPalClient` | `get_setup_token(setup_token_id: str) -> dict` |
| SDK | `client.vault.get_setup_token(id: str)` — shape 1, positional id |
| HTTP | `GET /v3/vault/setup-tokens/{id}` |
| Request | `id` path. No query. |
| Response model | `SetupTokenResponse` |
| Wire fields | `id`, `customer`, `status` (default `CREATED`), `payment_source`, `links` |
| Errors | `403` `ErrorException`, `404` `ErrorException`, `422` `ErrorException`, `500` `ErrorException`. A status outside that list uses the controller global default: base `ApiException`, message `HTTP response not OK.` |

### 4. `subscriptions.get_billing_plan`

| | |
| --- | --- |
| `PayPalClient` | `get_billing_plan(plan_id: str) -> dict` (httpx `GET /v1/billing/plans/{id}` when the flag is off) |
| SDK | `client.subscriptions.get_billing_plan(id: str)` — shape 1 |
| HTTP | `GET /v1/billing/plans/{id}` |
| Request | `id` path. No query. |
| Response model | `BillingPlan` |
| Wire fields | `id`, `product_id`, `name`, `status`, `description`, `billing_cycles`, `payment_preferences`, `merchant_preferences`, `taxes`, `quantity_supported`, `create_time`, `update_time`, `links` |
| Errors | `401` `SubscriptionErrorException`, `403` `SubscriptionErrorException`, `404` `SubscriptionErrorException`, `500` `SubscriptionErrorException`, other `SubscriptionErrorException` (`default`). Unboxed like `ErrorException`: `name`, `message`, `debug_id`, `details`, `links`. |

### 5. `subscriptions.list_billing_plans`

| | |
| --- | --- |
| `PayPalClient` | `list_billing_plans(*, product_id: str, page_size: int = 20) -> dict` |
| SDK | `client.subscriptions.list_billing_plans(options: dict)` — shape 2 |
| HTTP | `GET /v1/billing/plans` |
| Request | Query `product_id` (stripped), `page_size` (int), `total_required=true`. The httpx path sends the same three query keys. Optional, not sent: `prefer` header, `page`. |
| Response model | `PlanCollection` |
| Wire fields | `plans` (list of `BillingPlan`), `total_items`, `total_pages`, `links` |
| Errors | `400` `SubscriptionErrorException`, `401` `SubscriptionErrorException`, `403` `SubscriptionErrorException`, `404` `SubscriptionErrorException`, `500` `SubscriptionErrorException`, other `SubscriptionErrorException` (`default`). |

### 6. `subscriptions.get_subscription`

| | |
| --- | --- |
| `PayPalClient` | `get_subscription(subscription_id: str) -> dict` |
| SDK | `client.subscriptions.get_subscription(options: dict)` — shape 2 |
| HTTP | `GET /v1/billing/subscriptions/{id}` |
| Request | `options["id"]` path. Optional `fields` query is not sent. |
| Response model | `Subscription` |
| Wire fields | `id`, `plan_id`, `status`, `start_time`, `quantity`, `shipping_amount`, `subscriber`, `billing_info`, `create_time`, `update_time`, `custom_id`, `plan_overridden`, `plan`, `links`, `status_change_note`, `status_update_time` |
| Errors | `401` `SubscriptionErrorException`, `403` `SubscriptionErrorException`, `404` `SubscriptionErrorException`, `500` `SubscriptionErrorException`, other `SubscriptionErrorException` (`default`). |

### 7. `transaction_search.search_transactions`

| | |
| --- | --- |
| `PayPalClient` | `search_transactions(*, start_date: str, end_date: str) -> dict` |
| Window | `clamp_transaction_search_range` still runs in `PayPalClient` before either path. The gateway receives the clamped bounds. |
| SDK | `client.transaction_search.search_transactions(options: dict)` — shape 2 |
| HTTP | `GET /v1/reporting/transactions` |
| Request | Query `start_date`, `end_date`, `fields=all`, `page_size=100` (int). Same keys as the httpx query string. Optional filters not sent: `transaction_id`, `transaction_type`, `transaction_status`, `transaction_amount`, `transaction_currency`, `payment_instrument_type`, `store_id`, `terminal_id`, `balance_affecting_records_only`, `page`. |
| Response model | `SearchResponse` |
| Wire fields | `transaction_details`, `account_number`, `start_date`, `end_date`, `last_refreshed_datetime`, `page`, `total_items`, `total_pages`, `links` |
| `transaction_details[]` | `TransactionDetails`: `transaction_info` (`TransactionInformation`, includes `transaction_id`, `transaction_status`), `payer_info`, `shipping_info`, `cart_info`, `store_info`, `auction_info`, `incentive_info` |
| Errors | Every non-2xx is `SearchErrorException` (`default` only). Unboxed when the body is a JSON object: `name`, `message`, `debug_id`, `details` (`TransactionSearchErrorDetails`), `links`. |

## Errors that are not `PayPalError`

- Token fetch failure is `AuthValidationException` (`apimatic_core`), not `ApiException`. The auth manager hides the token-endpoint status; the gateway maps it to a sanitized HTTP 502 without retry or fallback writes.
- `OAuthProviderException` is an `ApiException` subclass, but it is raised by the token endpoint, not by these seven reads, and the auth manager usually swallows it.
- Connection failures, DNS failures, and timeouts come from `requests` (`ConnectionError` and siblings). They propagate.
- A typed error body that is not a JSON object leaves the unboxed attributes unset. `PayPalError` is built from `response_code` and `response.text`, not from those attributes, so the mapping still works. `str(exception)` on a typed error is not logged.

`PayPalError` keeps logging only `name`, `debug_id`, and `details` when the body is a PayPal error object. Tokens, secrets, and raw bodies are not written by the gateway.

## APIM-2b hardening

`PayPalClient._sdk_reads` calls `paypal_sdk_reads_enabled` in `paypal_sdk_gateway` before any read. That function returns false, so the read stays on the httpx client, when:

- `ESCALES_PAYPAL_SDK_ENABLED` is off (the default).
- `PAYPAL_ENV` is not `sandbox`.
- `build_sandbox_client` / `client` raises `RuntimeError`, `ModuleNotFoundError`, `AttributeError`, or `TypeError` (non-sandbox host, missing credentials, missing SDK package, or another build refusal).

Each distinct reason writes one warning on logger `escales.paypal.sdk` (`PayPal SDK read gateway unavailable; using the httpx client`) and does not raise. A later read with the same reason does not log again until `reset_client`. Direct calls to `build_sandbox_client` still raise. The gateway never passes `Environment.PRODUCTION`.

When the SDK read runs, `paypal_sdk_gateway._sdk_reads` calls `captain_budget.consume()` before the resource call, the same charge as `PayPalClient._request_with_retry`. OAuth is not charged. An exhausted turn raises `PayPalCallLimitExceeded` (`PayPal read limit reached for this turn (3 calls)`) and does not call PayPal. A budget of `None` stays unlimited. Writes are not charged here.

Connection errors and timeouts from a read (`requests` `ConnectionError` and `Timeout`, including connect and read timeouts, plus urllib3 connection and timeout errors, including when chained as `__cause__`) become `PayPalError` with status 502. That replaces the bullet above that said those failures propagate. `ApiException` mapping is unchanged. These seven operations remain GETs. The flag default stays off.

# PayPal Server SDK write contract (APIM-3)

Same client, same flag, same sandbox pin as the read contract. `paypal-server-sdk` **2.4.0** (`paypalserversdk`). The eight writes below run only when `paypal_sdk_reads_enabled()` is true (flag on, `PAYPAL_ENV=sandbox`, client built). Otherwise `PayPalClient` keeps the httpx body and the `PayPal-Request-Id` it already computed. The `paypalserversdk` import still happens only inside `build_sandbox_client`.

`Environment.PRODUCTION` is never passed. A non-sandbox `PAYPAL_ENV` or a non-sandbox base URI keeps httpx and does not call the SDK.

Capture timing is not in this gateway. `departure_clock.py` and `pledges.py` still decide when money moves:

- Stop pledges are captured at boat arrival, and voided when the stop is cancelled.
- Cabin pledges are captured at leg departure.
- Common fund and project donations are captured immediately (`CAPTURE` intent).

The AI Captain still does not capture or void. Refund idempotency keys from the pledge layer (issue 152) and `ORDER_ALREADY_AUTHORIZED` adoption (PAY-AUTH-RECOVER, issues 160 and 166) are unchanged. The gateway only forwards the key the caller already chose.

## Shared write rules

| Item | Value |
| --- | --- |
| Call shape | Every write below is shape 2: one `options` dict. |
| `PayPal-Request-Id` | `options["paypal_request_id"]`, the caller key sliced to 127 characters. The same string is passed to httpx when the flag is off. |
| `Prefer` | `return=representation` on every operation whose signature has `prefer`. Matches `PayPalClient._req` for POST. |
| `PayPal-Mock-Response` | Forwarded only when `PayPalClient.mock_response` is non-empty and the operation lists `paypal_mock_response`. Vault setup, payment token, and create-subscription do not list it, so the header is not on those three SDK calls. |
| Body | A generated model. `APIHelper.json_serialize` of that model is the JSON body. `None` omits the body (void, and a full refund with no amount). |
| Response | `APIHelper.to_dictionary(ApiResponse.body)`. `None` body becomes `{}`, matching httpx on an empty 2xx. |
| Errors | Same mapping as reads: `ApiException.response_code` and `ApiException.response.text` become `PayPalError`. Typed subclasses (`ErrorException`, `SubscriptionErrorException`) are caught as `ApiException`. Transport failures stay `PayPalError` 502. |
| Wallet and card | `create_authorize_order`, `create_card_authorize_order`, `create_card_setup_token`, `charge_vaulted`, and Card Fields are not delegated. |

`CreateSubscriptionRequest` always assigns deprecated `auto_renewal=false`. The gateway deletes that attribute before send so the JSON matches the httpx body, which does not send the field.

Capture models materialize `final_capture` (default `false`) and `disbursement_mode` (default `INSTANT`) when PayPal omits them. Settlement reads `seller_receivable_breakdown`, not those defaults.

## Operations

### 1. `orders.authorize_order`

| | |
| --- | --- |
| `PayPalClient` | `authorize_order(order_id, *, pledge_id=None)` |
| HTTP | `POST /v2/checkout/orders/{id}/authorize` |
| Request id | `paypal_request_id(pledge_id or order_id, "authorize")` |
| Body | `OrderAuthorizeRequest()` → `{}`. No `payment_source`. |
| Response model | `OrderAuthorizeResponse` |
| Fields used | `purchase_units[].payments.authorizations[]` `id`, `status`, `amount`, `expiration_time`. `authorization_from` reads id and expiration. |
| Errors | `400` `422` `401` `403` `404` `500` `ErrorException`, other `ErrorException` (`default`). `422` + `details[].issue=ORDER_ALREADY_AUTHORIZED` still adopts the hold via `get_order` (read contract). |

### 2. `orders.capture_order`

| | |
| --- | --- |
| `PayPalClient` | `capture_order(order_id, *, idempotency_key)` |
| HTTP | `POST /v2/checkout/orders/{id}/capture` |
| Request id | The capture-attempt key from the pledge (`capture-{pledge_id}-{attempt}`). |
| Body | `OrderCaptureRequest()` → `{}`. |
| Response model | `Order` |
| Fields used | Nested `purchase_units[].payments.captures[]` `id`, `status`, `amount`, `seller_receivable_breakdown` (`gross_amount`, `paypal_fee`, `net_amount`). `read_capture_result` and `apply_capture_settlement`. |
| Errors | `400` `401` `403` `404` `422` `500` `ErrorException`, other `ErrorException` (`default`). |

Immediate capture of a common-fund or project donation calls this method. The gateway does not choose that timing.

### 3. `payments.capture_authorized_payment`

| | |
| --- | --- |
| `PayPalClient` | `capture_authorization(authorization_id, final=True, *, idempotency_key)` |
| HTTP | `POST /v2/payments/authorizations/{authorization_id}/capture` |
| Request id | The same capture-attempt key as `capture_order`. |
| Body | `CaptureRequest(final_capture=final)` → `{"final_capture": true}` when `final` is true, which is the caller default. |
| Response model | `CapturedPayment` |
| Fields used | `id`, `status`, `amount`, `seller_receivable_breakdown`. A bare capture (no `purchase_units`) is the capture id. |
| Errors | `400` `401` `403` `404` `409` `422` `ErrorException`. `500` base `ApiException` (no unboxed fields). Other `ErrorException` (`default`). |

Stop arrival and cabin leg departure call this method after `refuse_early_capture`. A cancelled stop is voided, not captured.

### 4. `payments.void_payment`

| | |
| --- | --- |
| `PayPalClient` | `void_authorization(authorization_id, *, pledge_id=None)` |
| HTTP | `POST /v2/payments/authorizations/{authorization_id}/void` |
| Request id | `paypal_request_id(pledge_id or authorization_id, "void")` |
| Body | Omitted. httpx sends `json=None`. |
| Response model | `PaymentAuthorization` |
| Fields used | `id` when present (`void_id_source=paypal`). An empty 2xx body becomes `{}` and the pledge stores the authorization id as `void_id`. |
| Errors | `401` `403` `404` `409` `422` `ErrorException`. `500` base `ApiException`. Other `ErrorException` (`default`). |

### 5. `vault.create_setup_token`

| | |
| --- | --- |
| `PayPalClient` | `create_setup_token(return_url, cancel_url, *, customer_id, idempotency_key=None, checkout_locale=None)` |
| HTTP | `POST /v3/vault/setup-tokens` |
| Request id | `idempotency_key` or `paypal_request_id(customer_id, "setup-token")` |
| Body | `SetupTokenRequest` |
| Mapping | `customer.id` ← `customer.id` (already sliced to 127). `payment_source.paypal` ← `VaultPaypalWalletRequest`: `usage_type`, `usage_pattern`, `permit_multiple_payment_tokens`, `experience_context` (`VaultExperienceContext`: `brand_name`, `locale`, `return_url`, `cancel_url`, `shipping_preference`, `user_action`). Card setup tokens stay on httpx. |
| Response model | `SetupTokenResponse` |
| Fields used | `id`, `status`, `links[]` (`rel`, `href`) for the approve link. Finance row `pledge_created` stores `setup_token_id`. |
| Errors | `400` `403` `422` `500` `ErrorException`. A status outside that list uses the controller global default: base `ApiException`. No `prefer` parameter on this operation. |

### 6. `vault.create_payment_token`

| | |
| --- | --- |
| `PayPalClient` | `create_payment_token(setup_token_id, *, pledge_id=None)` |
| HTTP | `POST /v3/vault/payment-tokens` |
| Request id | `paypal_request_id(pledge_id or setup_token_id, "payment-token")` |
| Body | `PaymentTokenRequest` |
| Mapping | `payment_source.token` ← `VaultTokenRequest(id=setup_token_id, mtype=SETUP_TOKEN)`. Wire name of `mtype` is `type`. |
| Response model | `PaymentTokenResponse` |
| Fields used | `id` (`vault_id_from_token`), `payment_source.card` vs `paypal` (`vault_source_from_token`). Finance row `pledge_vaulted`. |
| Errors | `400` `403` `422` `500` `ErrorException`. No `prefer` parameter. |

### 7. `payments.refund_captured_payment`

| | |
| --- | --- |
| `PayPalClient` | `refund_capture(capture_id, *, amount_eur=None, currency_code=None, idempotency_key)` |
| HTTP | `POST /v2/payments/captures/{capture_id}/refund` |
| Request id | The pledge refund key (`refund-{pledge_id}-{request_key}` or `refund-{pledge_id}-{amount}`), not a new id. |
| Body | Amount present: `RefundRequest(amount=Money(currency_code, value))` with the value already formatted by `format_paypal_amount_value`. Amount absent: body omitted (full refund). |
| Response model | `Refund` |
| Fields used | `id`, `status` (`COMPLETED` or `PENDING`), `amount`, `seller_payable_breakdown` (`gross_amount`, `paypal_fee`, `net_amount`) for `refund_net_eur`. |
| Errors | `400` `401` `403` `404` `409` `422` `ErrorException`. `500` base `ApiException`. Other `ErrorException` (`default`). |

### 8. `subscriptions.create_subscription`

| | |
| --- | --- |
| `PayPalClient` | `create_billing_subscription(*, plan_id, return_url, cancel_url, idempotency_key, locale=None)` |
| HTTP | `POST /v1/billing/subscriptions` |
| Request id | The checkout replay key (or the random key the caller already generated). |
| Body | `CreateSubscriptionRequest(plan_id, application_context=SubscriptionApplicationContext)`. |
| Mapping | `application_context`: `brand_name`, `locale`, `shipping_preference=NO_SHIPPING`, `user_action=SUBSCRIBE_NOW`, `return_url`, `cancel_url`. `auto_renewal` is omitted (see shared rules). |
| Response model | `Subscription` |
| Fields used | `id`, `status`, `links[]` where `rel=approve`. Finance kind `paypal_subscription_create_cache` stores that projection. |
| Errors | `400` `401` `403` `404` `422` `500` `SubscriptionErrorException`, other `SubscriptionErrorException` (`default`). Unboxed when the body is a JSON object: `name`, `message`, `debug_id`, `details`, `links`. |

## APIM-3 OAuth failure and diagnostic hardening

The operations, generated request models, signatures and PayPal-Request-Id rows
above remain unchanged. Before modifying the gateway, the installed
`paypal-server-sdk==2.4.0` / `apimatic_core` source was checked: an OAuth grant
failure raises `AuthValidationException(message)` (an `Exception`, not an
`ApiException`) during the operation call. The auth manager does not reliably
preserve the upstream status, so do not invent an HTTP 401 or diagnose invalid
credentials from that exception alone.

Map this condition to `PayPalError(502, "PayPal SDK authentication unavailable")`.
Do not log the original message, chain it into application tracebacks, retry the
operation, or fall back to a second HTTP write. The caller's idempotency key is
unchanged. Read-budget consumption still occurs before the attempted resource
read; a refused fourth read must not perform OAuth or resource HTTP requests.
Constructor refusal diagnostics retain exception class names only, never raw
exception text that could contain credentials or request configuration.

Validation: stub token failure and assert exactly one token request and zero
resource writes; exercise read/write auth failures and synthetic constructor
messages; rerun all parity, idempotency, budget and tracing redaction tests.
Skills used: `python-getting-started`, `python-calling-endpoints`,
`python-error-handling`, `python-configuration-resilience`, `python-testing`
under the vendored `.cursor/skills/paypal-server-sdk` directory.

## Platform credentials for project onboarding

Project onboarding (onboard-after-payment) can run on a separate PayPal Platform
sandbox app. No PayPal operation, request body, response field or
PayPal-Request-Id changes: the same calls are made with a different
client-credentials pair. Everything outside `app/project_onboarding` and
`app/routers/project_onboarding.py` keeps the main app (`PAYPAL_CLIENT_ID` /
`PAYPAL_CLIENT_SECRET`): pledges, vault, card fields, wallets, subscriptions,
payouts, the Server SDK gateway and the browser SDK client id.

### Configuration

| Item | Value |
| --- | --- |
| Loader | `load_platform_config() -> EscalesConfig` in `app/escales/config.py`. |
| Credentials | `PAYPAL_PLATFORM_CLIENT_ID` / `PAYPAL_PLATFORM_CLIENT_SECRET`. Both required. Names only in `.env.example`; values never logged, returned or committed. |
| Other fields | Same as `load_config()`: `base_url` `https://api-m.sandbox.paypal.com`, `currency`, `env`. Built from the main config with only the two credential fields replaced. |
| Fallback | Either variable unset or blank: `load_platform_config()` returns `load_config()`. One warning per process, logged at startup when the onboarding feature is on. The warning names the missing variables, never a value. |
| Sandbox refusal | `load_platform_config()` calls `load_config()` first, which raises unless `PAYPAL_ENV=sandbox`. The platform pair is therefore never read into a config outside the sandbox. `platform_credentials_active()` is `False` outside the sandbox. `PayPalClient.__init__` still refuses a non-sandbox base URL. |
| Status | `GET /api/escales/project-onboarding/status` adds `platform_credentials: bool`. No id, secret, or webhook id. |
| Token | `PayPalClient._access_token`: `POST /v1/oauth2/token`, grant `client_credentials`, basic auth with the client's own pair. The token cache key is `(base_url, client_id, sha256(client_secret), transport)`, so the two apps never share a token. Unchanged code. |

### Operations made with the platform pair

All through the existing httpx `PayPalClient`, each built from `load_platform_config()`.

| Caller | `PayPalClient` call | HTTP | PayPal-Request-Id |
| --- | --- | --- | --- |
| `paypal_orders.create_unlinked_payee_capture_order` | `_request_with_retry("POST", "/v2/checkout/orders", json=, headers=)` | `POST /v2/checkout/orders` (`intent=CAPTURE`, unlinked payee email) | `paypal_request_id(donation_id, "onboard-capture-order")` (unchanged) |
| `paypal_orders.read_order` (new helper) | `_req("GET", "/v2/checkout/orders/{id}")` when the platform pair is active, else `get_order(order_id)` as before | `GET /v2/checkout/orders/{id}` | none (GET) |
| `paypal_orders.capture_order_once` | `_req("POST", "/v2/checkout/orders/{id}/capture", {})` | `POST /v2/checkout/orders/{id}/capture` | generated by `_req` (unchanged) |
| `RawHttpPartnerReferralsClient.create_referral` | `_req("POST", "/v2/customer/partner-referrals", body)` | `POST /v2/customer/partner-referrals` | generated by `_req` (unchanged) |
| `RawHttpPartnerReferralsClient.get_referral` | `_req("GET", "/v2/customer/partner-referrals/{id}")` | GET | none |
| `…merchant_integrations_by_tracking` / `…seller_status` | `_req("GET", "/v1/customer/partners/{partner_id}/merchant-integrations…")` | GET | none |
| `webhooks.verify_merchant_onboarding_webhook` | `verify_webhook_signature(auth_algo=, cert_url=, transmission_id=, transmission_sig=, transmission_time=, webhook_id=, webhook_event=, raw_event=)` | `POST /v1/notifications/verify-webhook-signature` | none (`paypal_idempotent=False`) |

Errors: every call raises `PayPalError(status, body)` on a non-2xx, as today. The
routes map it to the same HTTP status with the detail `"PayPal error"`.

### Why `read_order` does not call `get_order` on the platform pair

`PayPalClient.get_order` hands the read to the Server SDK gateway when
`ESCALES_PAYPAL_SDK_ENABLED` is on. The gateway is one process-wide
`PaypalServersdkClient` built from `PAYPAL_CLIENT_ID` / `PAYPAL_CLIENT_SECRET`
(`ClientCredentialsAuthCredentials`, see "Client" above). An order created by the
platform app has to be read with the platform app's token, so when the platform
pair is active the onboarding path reads the order through `_req`, which uses
the client's own credentials. The gateway is not modified and still only ever
holds the main pair. With the platform pair inactive the read is unchanged.

### Webhook id and the credentials that verify it

`verify-webhook-signature` is called with a `webhook_id` and an access token.
PayPal's guidance is that the webhook must be registered to the app whose
credentials make the call, so the two are chosen together:

| `PAYPAL_PLATFORM_WEBHOOK_ID` | `webhook_id` sent | Credentials used to verify |
| --- | --- | --- |
| set | `PAYPAL_PLATFORM_WEBHOOK_ID` | `load_platform_config()` (the platform pair, or the main pair if the platform pair is not set) |
| unset | `PAYPAL_WEBHOOK_ID` (existing) | `load_config()` (the main app, which owns that webhook) |

Not verified against PayPal: no sandbox credentials are available in development
or CI, so the pairing is covered by tests with a stubbed transport only.

### Duplicate-claim / idempotency rows

Unchanged. `claim_webhook_event(event_id)` still claims a
`MERCHANT.ONBOARDING.COMPLETED` event once; the donation order keeps its
`onboard-capture-order` request id; a donation with a `capture_id` is returned
without a second capture.

### Validation

Stubbed httpx transport, no network: the OAuth request carries the platform pair
when both variables are set and the main pair otherwise; a pledge order
(`PayPalClient(load_config())`) still authenticates with the main pair while the
platform pair is set; `/status` exposes a boolean only; the warning is logged
once and contains no value; non-sandbox `PAYPAL_ENV` raises before any config is
built. Full backend suite rerun.

Skills used: `python-getting-started`, `python-client-initialization`,
`python-authentication` under the vendored `.cursor/skills/paypal-server-sdk`
directory. The SDK client itself is not changed by this work.

# Crew membership catalog v2: 10 EUR per year (11 Nov 2026)

Crew membership is the association membership (adhésion): **10.00 EUR per YEAR**
(confirmed by the owner). The first catalog was 5.00 EUR per MONTH. Sandbox only.

## What changes

| | Catalog v1 (kept, not modified) | Catalog v2 (new) |
| --- | --- | --- |
| Setup key (finance row `subscription_catalog_ready.setup_key`) | `crew_supporter_catalog` | `crew_membership_catalog_v2` |
| Product name (en / fr) | `Crew supporter` / `Soutien d'équipage` | `Crew membership` / `Adhésion Crew` |
| Plan name (en / fr) | `Crew supporter (monthly)` / `Soutien d'équipage (mensuel)` | `Crew membership (10 EUR per year)` / `Adhésion Crew (10 EUR par an)` |
| Price, cycle | 5.00 EUR, `MONTH` × 1 | 10.00 EUR, `YEAR` × 1 |
| Role | Still accepted when a subscription is verified (existing subscribers) | The plan the app shows and sells |

No PayPal call deletes, deactivates or updates a v1 product or plan. v1 ids are
only read from the local finance row (plus the old hard-coded English id) so that
`approve_crew_subscription` keeps accepting them.

## PayPal operations called (all through `PayPalClient`, httpx path)

None of these is one of the Server SDK gateway operations above: product and plan
creation have always used `PayPalClient._req`. Signatures are unchanged.

| Step | `PayPalClient` method | HTTP | When |
| --- | --- | --- | --- |
| Find an existing v2 product | `iter_billing_product_pages(*, page_size=20, max_pages=50)` / `list_billing_products(*, page=1, page_size=20) -> dict` | `GET /v1/catalogs/products` | Setup and plan lookup, when the v2 finance row has no id for the language |
| Find its plan | `list_billing_plans(*, product_id: str, page_size: int = 20) -> dict` | `GET /v1/billing/plans?product_id=` | Same |
| Create the v2 product | `create_billing_product(*, name: str, description: str, idempotency_key: str) -> dict` | `POST /v1/catalogs/products` | Setup only, when not found |
| Create the v2 plan | `create_billing_plan(*, product_id: str, name: str, amount_eur: str, interval_unit: str, idempotency_key: str) -> dict` with `amount_eur="10.00"`, `interval_unit="YEAR"` | `POST /v1/billing/plans` | Setup only, when not found |
| Subscribe (unchanged) | `create_billing_subscription(*, plan_id, return_url, cancel_url, idempotency_key, locale=None)` | `POST /v1/billing/subscriptions` | Buyer checkout, now with the v2 plan id |
| Verify (unchanged) | `get_subscription(subscription_id: str) -> dict` | `GET /v1/billing/subscriptions/{id}` | Approval; the subscription's `plan_id` must be a v2 **or** v1 Crew plan |

`interval_unit="YEAR"` with `interval_count=1` is within PayPal's limits for a
billing cycle (a yearly frequency allows an interval count of 1).

## Errors

Unchanged. A non-2xx from PayPal is `PayPalError(status, body)` from `_req`; the
router maps it with `_as_http`. Setup that fails half-way leaves the finance row
with the ids already obtained and can be run again (see idempotency).

## Duplicate-claim / idempotency rows

| Call | `PayPal-Request-Id` | Effect |
| --- | --- | --- |
| v2 product, en | `product-en-crew_membership_catalog_v2` | New key: PayPal does not replay the v1 product |
| v2 product, fr | `product-fr-crew_membership_catalog_v2` | Same |
| v2 plan, en | `plan-en-crew_membership_catalog_v2` | Same |
| v2 plan, fr | `plan-fr-crew_membership_catalog_v2` | Same |
| Local | finance row `subscription_catalog_ready` with `setup_key=crew_membership_catalog_v2` | Setup returns the stored ids (`idempotent: true`) without calling PayPal; the v1 row is never written to |
| Local | lookup by v2 product and plan **name** before creating | A catalog created on PayPal but lost locally is found again, not duplicated |

## How the v2 plans get created on a host

`POST /api/escales/paypal/subscriptions/setup` with the treasurer key (the
treasurer page's PayPal section button). It is idempotent. Until it has run,
`GET /api/escales/paypal/subscriptions/plan` returns `plan_id: null` and the Crew
button is not shown: the app never falls back to selling the 5 EUR monthly plan.

## Validation

Stubbed PayPal client, no network: the v2 plan is created at 10.00 / YEAR under
the v2 request ids; a v1 row is left untouched and its plan ids still verify; the
public plan lookup returns v2 ids only; a subscription on an unknown plan is
still refused. Not verified against PayPal: no sandbox credentials are available
in development or CI.

Skills used: `python-getting-started` under the vendored
`.cursor/skills/paypal-server-sdk` directory. The Server SDK is not called by
the operations this change touches.

# Demo treasurer: a visitor plays the treasurer on their own pledges (issue #145, 11 Nov 2026)

In demo treasurer mode (`ESCALES_DEMO_TREASURER` on, `PAYPAL_ENV=sandbox`, `ESCALES_ENV`
not `production`), a visitor without the treasurer key can take **a pledge made from
the same browser** through the treasurer loop, for real in the PayPal sandbox:
simulate the boat's arrival for that pledge, approve, capture or void, refund.
Every other pledge stays view-only. The keyed treasurer routes are not changed.

## PayPal operations called

No new PayPal operation and no new signature. The demo routes call the same service
functions as the keyed treasurer routes, which call the same `PayPalClient` methods:

| Demo route (`/api/escales/demo/pledges/{id}/…`) | Service function (unchanged) | PayPal call it makes (unchanged) |
| --- | --- | --- |
| `simulate-arrival` | none: writes `demo_play.arrival_at` on the pledge only | none |
| `approve` | none: writes `demo_play.approved_at` on the pledge only | none |
| `capture` | `capture_pledge(pledge_id, client, effective_at=<that pledge's simulated arrival>)` | `capture_authorization(authorization_id, idempotency_key=)` or `charge_vaulted(…)` for a Vault pledge; `reauthorize(…)` after the honor period, as for the treasurer |
| `void` | `void_pledge(pledge_id, client)` | void of the authorization, or deletion of the unused vault token |
| `refund` | `refund_pledge(pledge_id, client)` (remaining balance) | refund of the capture |
| `POST /demo/pledges/own` | none: reads pledges | none |

The Captain's review is the existing `POST /captain/review/{milestone_id}`, already
open (and rate-limited) without the key.

## Ownership (never a pledge id alone)

| Item | Rule |
| --- | --- |
| Proof | The pledge's `client_key`: the `PayPal-Request-Id` the browser chose when it created the pledge. It is stored on the pledge, never returned by any public or demo response, and only that browser knows it. The browser sends it back in `X-Pledge-Key`. |
| Check | On every demo action: the pledge must carry `demo_playable: true` **and** `secrets.compare_digest(stored client_key, X-Pledge-Key)`. Anything else is HTTP 403, including an unknown pledge id (no id probing). |
| `demo_playable` | Set when a pledge is created while demo treasurer mode is on, with a `PayPal-Request-Id` and without an `x-admin-key` header. Pledges created before this change, by the treasurer key, or with the mode off never get it and stay view-only. |
| Scope of "simulate arrival" | Stored on that pledge only. The shared voyage clock, the stop's milestone, the Captain's stored review and every other pledge are untouched. The capture passes that stored moment as `effective_at`, the parameter the treasurer's own capture route already uses for a dated capture. |
| Approval | Stored on that pledge only (`demo_play.approved_at`). No `captain_review_approved` row is written for the stop, so the real voyage never sees an approval nobody gave. Capture is refused until both the arrival and the approval are on the pledge. |

## Errors

Unchanged mapping: `PledgeNotFound`, `IllegalTransition`, `PayPalError`, `ValueError`
go through `_money_http`, as on the keyed routes. Added: 403 (not this browser's
pledge, or mode off), 409 (step out of order: capture before approval, approval before
arrival, nothing to simulate for a pledge charged at once), 429 (rate limit).

## Duplicate-claim / idempotency rows

| Call | Key | Effect |
| --- | --- | --- |
| Demo capture | the pledge's existing capture idempotency key (`_call_with_capture_idempotency`) | A repeated click replays the same PayPal request; a captured pledge is refused by its status |
| Demo void | status check in `void_pledge` | A second void is an illegal transition (409) |
| Demo refund | `refund_pledge` remaining-balance rule | A second full refund returns 409 "already fully refunded" |
| Demo simulate-arrival / approve | idempotent writes on the pledge | Repeating returns the same state |

## Limits

- Rate limit on every demo pledge route: the existing demo limiter (`hit_demo`), once per client IP and once per pledge key.
- Sandbox only: the routes return 403 unless the demo flag is on with `PAYPAL_ENV=sandbox`.

## Validation

Stubbed PayPal client, no network: a pledge from another browser is refused (403) on
every demo action; an unknown id is 403; a pledge made before the change or with the
treasurer key is not playable; the keyed capture, void and refund routes still demand
the key and behave as before; "simulate arrival" changes neither the shared clock nor
another pledge on the same stop. Not verified against PayPal: no sandbox credentials
are available in development or CI.

Skills used: `python-getting-started` under the vendored
`.cursor/skills/paypal-server-sdk` directory. No PayPal operation or SDK call is added.

## PAY-05 exact authorization window

Before implementation: AUTHORIZE is permitted when arrival (stop) or departure
(cabin) minus the UTC voyage instant is at most timedelta(hours=695), exactly 695 h (inclusive).
Beyond that instant the existing resolver selects VAULT or refuses before order
creation. No provider methods, request IDs, capture rules or Render clock change.
Naive supplied instants retain the existing UTC interpretation.
Skills: python-getting-started, python-calling-endpoints, python-testing.

## Order creation SDK completion (payment workstream)

Before implementation: route PayPalClient POST /v2/checkout/orders through
OrdersController.create_order(options), using OrderRequest(**body) with existing nested wire dictionaries,
PayPal-Request-Id and Prefer return=representation. This includes AUTHORIZE,
CAPTURE, card/SCA, vault-on-purchase and saved-payment order bodies. Keep the
existing SDK flag and sandbox guard, and never retry a failed SDK write via httpx.
ApiException and transport/auth errors use the gateway's existing PayPalError mapping.
Preserve the same request id across uncertain retries; no ledger transitions change.
Shared onboarding files are excluded pending owner coordination.
Skills: python-getting-started, python-calling-endpoints, python-models,
python-error-handling, python-configuration-resilience, python-testing.

SDK source inspection: from_dictionary injects PayPal defaults and drops card experience locale/brand fields. Keep nested dictionaries inside the generated OrderRequest envelope; HTTP-boundary parity tests cover exact payload preservation.

## v6 displayed annual plan and replay contract

Before code: accept plan_id as a constraint, never as price authority. Resolve
catalog v2 server-side, reject a different displayed plan before subscription
creation, and GET the selected billing plan to require ACTIVE, one regular
YEAR/1 cycle, EUR 10, no setup fee or tax. Keep SDK get_billing_plan and
create_subscription operations and error mapping. Serialize same-process retries
and reject cached results from another catalog; cross-worker provider replay still
uses the same PayPal-Request-Id. No product or plan is created during verification.
Skills: python-getting-started, python-calling-endpoints, python-models,
python-error-handling, python-configuration-resilience, python-testing.

## PAY-03 common-fund immediate capture

Before code: common_fund uses the existing CAPTURE order creation and buyer-approved
capture_order path, preserving the common_fund identity and target. The public
mode preview returns CAPTURE. No Captain or treasurer approval is involved.
Serialize approval callbacks and return an already captured receipt without another
provider write. Project capture behavior stays on the same path. SDK operations:
OrdersController.create_order and capture_order; PayPalError mapping unchanged.
Skills: python-getting-started, python-calling-endpoints, python-models,
python-error-handling, python-configuration-resilience, python-testing.

PAY-03 review: preserve common-fund Card Fields and one-time Apple/Google wallets;
use CAPTURE with card SCA_WHEN_REQUIRED for card donations. Distinguish common
fund copy from project copy. A keyed treasurer capture after immediate capture
must return a conflict and never issue a second provider capture.

## Sandbox Crew catalog v2 reuse

Before code: reuse the annual EN/FR catalog set up by Hamid on test2. Do not run
catalog creation or alter existing plans as part of verification. Serialize catalog
ensure calls per event loop; retain stable v2 PayPal request IDs across processes.
Refuse catalog provisioning outside explicit sandbox before any provider call.
Route supported plan creation through SubscriptionsController.create_billing_plan
(options, PlanRequest); Catalog Products are not included in Server SDK 2.4.0.
Public plan GET stays read-only; intentional checkout/setup retains existing ensure.
Skills: python-getting-started, python-calling-endpoints, python-models,
python-error-handling, python-configuration-resilience, python-testing.

## Onboarding Orders via an isolated Platform SDK client

Only project_onboarding/paypal_orders.py PayPal transport changes. Use SDK 2.4.0 OrdersController.create_order(options), get_order(options), capture_order(options), ApiResponse.body and APIHelper.to_dictionary. Build a separate sandbox PaypalServersdkClient with load_platform_config() credentials, never the merchant singleton; keep existing flag-off Platform HTTP behavior. Preserve create-order BN via paypal_partner_attribution_id, body/payee/locale and deterministic request IDs. Capture uses an order-derived idempotency key. Map ApiException/auth/transport failures without HTTP fallback replay. SDK 2.4.0 has no partner referrals or merchant integrations controllers; partner_referrals.py stays unchanged. Tests use distinct merchant/Platform credentials at the generated HTTP boundary. No onboarding business rules, emails or UI changes.
## SDK review follow-up: budget and transient retries

Keep one merchant SDK gateway. All resource attempts, reads and writes, consume the optional Captain budget before dispatch; OAuth is excluded. Disable SDK-internal retries and retry ApiException 429/5xx at most three attempts with stable arguments and request IDs, exponential backoff and Retry-After up to ten seconds. Do not replay uncertain transport/auth failures or fall back to httpx after dispatch. Map OrderRequest constructor TypeError to PayPalError. Test generated HTTP-boundary retry/accounting/identity and no-replay cases, plus full suites and strict gateway mypy.

### Shared gateway for the isolated Platform client

Include #265 as a prerequisite. Extend build_sandbox_client with an explicit credential pair and _execute with an explicit sdk keyword. Onboarding uses these same gateway model/error/retry functions, with its own cached Platform client. Never install it in the merchant singleton. This avoids a parallel executor and gives Platform calls the same bounded 429/5xx retry policy after a real sandbox 500 was observed. No PayPal calls outside paypal_orders.py are migrated.

## PAY-05 review: one-hour capture safety margin

AUTHORIZE opens at most 695 hours before the UTC arrival/departure anchor (29 days minus one hour). Later anchors select Vault through the existing resolver. Provider expiry remains 696 hours. Naive clock values are UTC in both authorization and capture guards. Arrival/departure wording follows the actual anchor. No provider operation, flags or scheduler changes. Validate exact boundaries, offsets, naive clocks, preview/creation parity and the full suites.

## Arrival gift for a stop: stop_gift

Add a free positive EUR amount with kind=stop_gift, required known arrival milestone and no quantity. Reuse AUTHORIZE/Vault resolution (PAY-05 margin follows #249), order creation and human-reviewed arrival capture/cancellation void. Do not route this kind to immediate CAPTURE. Existing unit stop pledges and common_fund remain unchanged. Existing pledge fields/statuses and finance pledge_kind expose attribution; existing aggregate captured_eur/refunded_eur/authorized_eur keep held money out of Net. No row or donor/payment identifier is added to any LLM prompt. No UI, Studio, treasurer or dashboard changes. Test target validation, free amounts, preview/creation mode, arrival/human gate, cancellation, refund totals and model payload boundaries.

#249 is merged into test/integration-2. This feature branch includes that integration merge, so the prerequisite diff is no longer part of the stop-gift PR. The remaining diff implements stop_gift only.

## Card coverage for immediate donations

Before code: allow Card Fields on CAPTURE-intent project donations. The shared
capture creator accepts checkout_method=card, sends card attributes with
SCA_WHEN_REQUIRED, and preserves immediate capture on approval. The existing
mode-preview GET returns CAPTURE for project donations without ledger writes.
Both JS version entry points render the existing card component. This adds no
new page or layout. Common-fund CAPTURE uses the same creator after PAY-03 merges.
Skills: python-getting-started, python-calling-endpoints, python-models,
python-error-handling, python-configuration-resilience, python-testing.

Card review: before CAPTURE, reread the order through PayPalClient.get_order
(the generated SDK when enabled), require approval and a card authentication
result permitting continuation under the PayPal 3DS response matrix. Unknown,
failed, rejected or still-challenged authentication fails closed without capture.
Only a completed capture receipt may render the immediate-donation paid text.
Reference: https://developer.paypal.com/platforms/checkout/advanced/customize/3d-secure/response-parameters


### Card review: request server authentication fields explicitly

The official Orders 3DS flow requires GET order with fields=payment_source to retrieve authentication_result. Include this query on the SDK and HTTP read paths before the existing 3DS gate. Test the generated request query, not just a permissive response fixture. Real sandbox SCA_ALWAYS confirmation returns PAYER_ACTION_REQUIRED until device authentication; do not capture while unresolved.

Sandbox observation: fields=payment_source returns only id/payment_source, omitting status. A dedicated get_card_order combines the normal state read with that projection after verifying both order IDs. Other order reads stay unchanged; the card gate uses the combined response.

Real local MongoDB + PayPal observation: SCA_WHEN_REQUIRED confirmation can be APPROVED with a persisted card (brand/last_digits), and no authentication_result when PayPal does not request 3DS. Permit that explicit approved-card case; keep explicit unknown/failed 3DS and absent card data blocked. Capture outcome still determines paid status. Recheck completed and processor-declined cards against the real sandbox, using local bi_escales_test2 and scoped tagged cleanup.

## PR #255 continuation: pending capture and declined-card retry

Before application changes: PENDING is an existing capture awaiting settlement,
never permission to submit another charge. Add PayPalClient.get_capture and the
shared gateway get_captured_payment(capture_id), using SDK 2.4.0
PaymentsController.get_captured_payment({"capture_id": capture_id}); its ApiResponse
body is CapturedPayment and failures map through the existing ApiException /
transport handling. A pending capture action reads that exact resource, verifies
its ID, and updates the existing pledge only on a known terminal outcome. Repeated
PENDING reads do not append finance events or advance capture_attempt. Serialize
capture/approval for one pledge so concurrent clicks cannot submit two writes.

The card receipt distinguishes PENDING from paid and hides further payment entry.
After a definite declined capture, fetch the stored status and clear the checkout
attempt; the next submission uses a new pledge, order and PayPal-Request-Id.
Transport uncertainty keeps the original attempt/key. Mode preview accepts CAPTURE
as returned by the API. Keep the original 3DS gate and common-fund merge contract.

Skills: python-getting-started, python-calling-endpoints, python-models,
python-error-handling, python-configuration-resilience, python-testing.

The same fresh-attempt rule applies when Card Fields reports an explicit
INSTRUMENT_DECLINED/CARD_DECLINED before the capture route is reached. Other SDK
errors keep the original order because their financial outcome is uncertain.

## SDK retry continuation: keep the event loop available

Before code: the generated SDK is synchronous, including its backoff. Offload
PayPal calls from the async pledge state machine with asyncio.to_thread, including
creation, approval reads, capture, pending reconciliation, vault registration,
reauthorization, void and refund. Keep asynchronous ledger work on its original
event loop and preserve per-pledge serialization and idempotency keys. The worker
owns both the SDK request and retry wait; no blocking join runs on the event loop.
Onboarding transport calls will receive the same treatment in #266.

Project donation order create, order read and capture (`create_donation_order`, `finalize_donation_capture`) run through `asyncio.to_thread`, same as pledge SDK calls, so a synchronous SDK retry cannot block the event loop.

Keep the optional Captain budget scoped to its client and ContextVar, with normal
route clients unbudgeted. Add a generated-HTTP-boundary regression proving a
normal capture retries after another client's budget is exhausted. If a Captain
budget interrupts a transient retry, chain the last PayPal exception and log its
HTTP status only. No secrets or bodies in logs. Preserve three total attempts,
stable request IDs/bodies, bounded Retry-After and no uncertain-write transport
replay. Verify a live event-loop heartbeat while a generated-SDK retry waits.

Skills: python-getting-started, python-calling-endpoints, python-models,
python-error-handling, python-configuration-resilience, python-testing.

## Stop gift continuation: maximum amount and shared copy

Before code: limit stop_gift to 1000.00 EUR per pledge, validated by the shared service before any provider call (including direct callers). Keep the existing positive-amount rule. Revert only the FR/EN pricing-note edits in captain.py; retain stop_gift in the existing free-amount label set so structured pricing cannot mislabel it as a fixed-price item. The user-facing gift description stays in the payment contract. Test the maximum and rejection above it, with no PayPal call on rejection.
