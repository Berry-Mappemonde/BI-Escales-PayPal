# Platform fees (marina berth only)

Partner Referrals onboarding for FR marinas is **blocked by PayPal sandbox 403** in this hackathon environment.
Do not enable multiparty orders until seller `merchant_id` values are ACTIVE.

## Enable multiparty on PayPal order (after onboarding)

```env
ESCALES_PLATFORM_FEES_ENABLED=1
ESCALES_PLATFORM_FEE_EUR=3.00
ESCALES_PLATFORM_PAYEE_MERCHANT_ID=<platform-merchant-id>
ESCALES_MARINA_SELLER_MERCHANT_ID=<marina-seller-merchant-id>
```

Only **`kind=berth`** AUTHORIZE orders include `payment_instruction.platform_fees` when all three env vars above are set and seller/payee merchant IDs are present.
Project, gear, mile, membership, and common-fund pledges never add platform fees.

## Sandbox money flow (default — no partner IDs)

When partner merchant IDs are **missing**, each **berth capture**:

1. Retains **`ESCALES_PLATFORM_FEE_EUR`** in Escales (ledger `marina_platform_fee`).
2. Sends **net to marina** via PayPal **Payouts API** (`POST /v1/payments/payouts`, `recipient_wallet=PAYPAL`, receiver = marina `payout_email` or `ESCALES_MARINA_PAYOUT_EMAIL`).
3. Uses idempotent **`sender_batch_id`** `marina-payout-{pledge_id}-{capture_id}`.
4. Stores **`marina_payout_batch_id`** + **`marina_payout_status`** on the pledge and `marina_payout_sent` in the ledger.
5. Updates status from **`PAYMENT.PAYOUTSBATCH.*`** webhooks.

Treasurer marina grid shows payout status per stopover.

Disable automatic payouts (ledger fee only): `ESCALES_MARINA_PAYOUTS_ENABLED=0`.

No fee or marina payout on project, mile, gear, membership, or common-fund captures.
