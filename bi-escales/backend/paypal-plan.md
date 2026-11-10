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
