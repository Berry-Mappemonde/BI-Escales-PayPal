<!-- Generated file — do not edit; regenerated with the SDK. -->

# Payouts — operations

Accessor: `client.payouts` · Source: `payouts/apis/payouts.py` · 2 operations

Each `###` block is one operation and assumes `sdk-map.md` is loaded: blocks omit what its invariants table covers and are otherwise self-contained, so chunk at block level. Signatures are the sync parsed spelling; the async and raw spellings take the same parameters (see sdk-map.md). **Type sources** names the module declaring each type an operation mentions, so resolving a body, return or error payload is a lookup rather than a search; the runtime types `RawError` and `ApiResult` are excluded.

### client.payouts.payouts_get

- **Route**: `GET /v1/payments/payouts/{id}`
- **Auth**: `oauth2`
- **Signature**: `def payouts_get(id_: str, *, fields: str | None = None, page: int | None = 1, page_size: int | None = None, total_required: bool | None = False, request_options: RequestOptionsOrDict | None = None)`
  - required, positional: `id_`
- **Params**: `id_` — path `id` · `fields` — query · `page` — query · `page_size` — query · `total_required` — query
- **Returns (parsed)**: `PayoutBatch`
- **Returns (raw)**: `ApiResult[PayoutBatch, PayoutsGetErrorBody]`
- **Error**: `PayoutsGetErrorBody` — **Case A (typed)**
- **Error arms**: `Error` [404, 500] · `RawError` [anything unmapped]

| Type | Source |
| --- | --- |
| `PayoutBatch` | `payouts/models/payout_batch.py` |
| `PayoutsGetErrorBody` | `payouts/errors/payouts_get_error.py` |
| `Error` | `payouts/models/error.py` |

### client.payouts.payouts_post

- **Route**: `POST /v1/payments/payouts`
- **Auth**: `oauth2`
- **Signature**: `def payouts_post(*, pay_pal_request_id: str | None = None, body: CreatePayoutRequest | CreatePayoutRequestDict | None = None, request_options: RequestOptionsOrDict | None = None)`
- **Params**: `pay_pal_request_id` — header `PayPal-Request-Id` · `body` — JSON body
- **Returns (parsed)**: `CreatePayoutResponse`
- **Returns (raw)**: `ApiResult[CreatePayoutResponse, PayoutsPostErrorBody]`
- **Error**: `PayoutsPostErrorBody` — **Case A (typed)**
- **Error arms**: `Error` [400, 403, 500] · `RawError` [anything unmapped]

| Type | Source |
| --- | --- |
| `CreatePayoutRequest` | `payouts/models/create_payout_request.py` |
| `CreatePayoutRequestDict` | `payouts/models/create_payout_request.py` |
| `CreatePayoutResponse` | `payouts/models/create_payout_response.py` |
| `PayoutsPostErrorBody` | `payouts/errors/payouts_post_error.py` |
| `Error` | `payouts/models/error.py` |

