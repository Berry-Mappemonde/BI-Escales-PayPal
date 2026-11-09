<!-- Generated file — do not edit; regenerated with the SDK. -->

# PayoutsItem — operations

Accessor: `client.payouts_item` · Source: `payouts/apis/payouts_item.py` · 2 operations

Each `###` block is one operation and assumes `sdk-map.md` is loaded: blocks omit what its invariants table covers and are otherwise self-contained, so chunk at block level. Signatures are the sync parsed spelling; the async and raw spellings take the same parameters (see sdk-map.md). **Type sources** names the module declaring each type an operation mentions, so resolving a body, return or error payload is a lookup rather than a search; the runtime types `RawError` and `ApiResult` are excluded.

### client.payouts_item.payouts_item_cancel

- **Route**: `POST /v1/payments/payouts-item/{payout_item_id}/cancel`
- **Auth**: `oauth2`
- **Signature**: `def payouts_item_cancel(payout_item_id: str, *, request_options: RequestOptionsOrDict | None = None)`
  - required, positional: `payout_item_id`
- **Params**: `payout_item_id` — path
- **Returns (parsed)**: `PayoutItem2`
- **Returns (raw)**: `ApiResult[PayoutItem2, PayoutsItemCancelErrorBody]`
- **Error**: `PayoutsItemCancelErrorBody` — **Case A (typed)**
- **Error arms**: `Error` [400, 404, 500] · `RawError` [anything unmapped]

| Type | Source |
| --- | --- |
| `PayoutItem2` | `payouts/models/payout_item2.py` |
| `PayoutsItemCancelErrorBody` | `payouts/errors/payouts_item_cancel_error.py` |
| `Error` | `payouts/models/error.py` |

### client.payouts_item.payouts_item_get

- **Route**: `GET /v1/payments/payouts-item/{payout_item_id}`
- **Auth**: `oauth2`
- **Signature**: `def payouts_item_get(payout_item_id: str, *, request_options: RequestOptionsOrDict | None = None)`
  - required, positional: `payout_item_id`
- **Params**: `payout_item_id` — path
- **Returns (parsed)**: `PayoutItem2`
- **Returns (raw)**: `ApiResult[PayoutItem2, PayoutsItemGetErrorBody]`
- **Error**: `PayoutsItemGetErrorBody` — **Case A (typed)**
- **Error arms**: `Error` [404, 500] · `RawError` [anything unmapped]

| Type | Source |
| --- | --- |
| `PayoutItem2` | `payouts/models/payout_item2.py` |
| `PayoutsItemGetErrorBody` | `payouts/errors/payouts_item_get_error.py` |
| `Error` | `payouts/models/error.py` |

