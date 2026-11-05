# Platform fees (marina berth only)

Partner Referrals onboarding for FR marinas is **blocked by PayPal sandbox 403** in this hackathon environment.
Do not enable multiparty orders until seller `merchant_id` values are ACTIVE.

## Enable (test2 only, after onboarding)

```env
ESCALES_PLATFORM_FEES_ENABLED=1
ESCALES_PLATFORM_FEE_EUR=3.00
ESCALES_PLATFORM_PAYEE_MERCHANT_ID=<platform-merchant-id>
ESCALES_MARINA_SELLER_MERCHANT_ID=<marina-seller-merchant-id>
```

Only **`kind=berth`** AUTHORIZE orders include `payment_instruction.platform_fees` when all three env vars above are set and seller/payee merchant IDs are present.
Project, gear, mile, membership, and common-fund pledges never add platform fees.

## Sandbox simulation (default in hackathon)

When **`ESCALES_PLATFORM_PAYEE_MERCHANT_ID`** or **`ESCALES_MARINA_SELLER_MERCHANT_ID`** is missing (or fees are not enabled), each **berth capture** still applies the configured **`ESCALES_PLATFORM_FEE_EUR`** inside the app:

- Ledger lines: `platform_fee_simulated` (fee) and `marina_net_simulated` (net to marina)
- Pledge fields: `platform_fee_eur`, `marina_net_eur`, `platform_fee_simulated=true`
- Treasurer marina dashboard labels these rows as **sandbox simulation** (not sent to PayPal)

No simulation on project, mile, gear, membership, or common-fund captures.
