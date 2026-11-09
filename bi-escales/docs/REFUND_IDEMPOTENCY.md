# Refund idempotency (treasurer API)

Treasurer refunds use PayPal Orders v2 capture refunds in **sandbox** only. Each
API call can carry an idempotency token so retries do not double-refund.

## PayPal-Request-Id mapping

| Input | PayPal-Request-Id value |
|-------|-------------------------|
| `request_key` body field or `Idempotency-Key` header | `refund-{pledge_id}-{request_key}` |
| Amount only (no key) | `refund-{pledge_id}-{amount}` |

Send a **unique** `request_key` for each distinct refund action when refunding the
same amount twice on one capture.

## `paypal_refund_id`

PayPal assigns a refund **resource id** (for example `REF-…`) when a refund
completes. BI Escales stores it on the pledge (`refund_id` and each row in
`refunds`).

| Situation | HTTP | `paypal_refund_id` in response |
|-----------|------|--------------------------------|
| Successful new refund | 200 | Public pledge `refund_id` is set |
| Idempotent replay (same key or matching body `paypal_refund_id`) | 200 | Public pledge `refund_id` unchanged |
| Pledge already fully refunded, new key | 409 | Top-level JSON field alongside `detail` |

The 409 body shape:

```json
{
  "detail": "pledge already fully refunded",
  "paypal_refund_id": "<existing PayPal refund id>"
}
```

Replay detection never calls PayPal again when the intent is already recorded.
