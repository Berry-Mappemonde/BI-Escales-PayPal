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

- Token fetch failure is often `AuthValidationException` (`apimatic_core`), not `ApiException`. The auth manager hides the token-endpoint status. This gateway does not remap that type.
- `OAuthProviderException` is an `ApiException` subclass, but it is raised by the token endpoint, not by these seven reads, and the auth manager usually swallows it.
- Connection failures, DNS failures, and timeouts come from `requests` (`ConnectionError` and siblings). They propagate.
- A typed error body that is not a JSON object leaves the unboxed attributes unset. `PayPalError` is built from `response_code` and `response.text`, not from those attributes, so the mapping still works. `str(exception)` on a typed error is not logged.

`PayPalError` keeps logging only `name`, `debug_id`, and `details` when the body is a PayPal error object. Tokens, secrets, and raw bodies are not written by the gateway.

## APIM-2b hardening

`PayPalClient._sdk_reads` calls `paypal_sdk_reads_enabled` in `paypal_sdk_gateway` before any read. That function returns false, so the read stays on the httpx client, when:

- `ESCALES_PAYPAL_SDK_ENABLED` is off (the default).
- `PAYPAL_ENV` is not `sandbox`.
- `build_sandbox_client` raises `RuntimeError` (non-sandbox host, missing credentials, or another build refusal).

Each distinct reason writes one warning on logger `escales.paypal.sdk` (`PayPal SDK read gateway unavailable; using the httpx client`) and does not raise. A later read with the same reason does not log again until `reset_client`. Direct calls to `build_sandbox_client` still raise. The gateway never passes `Environment.PRODUCTION`.

Connection errors and timeouts from a read (`requests` `ConnectionError` and `Timeout`, including connect and read timeouts, plus urllib3 connection and timeout errors, including when chained as `__cause__`) become `PayPalError` with status 502. That replaces the bullet above that said those failures propagate. `ApiException` mapping is unchanged. These seven operations remain GETs. The flag default stays off.
