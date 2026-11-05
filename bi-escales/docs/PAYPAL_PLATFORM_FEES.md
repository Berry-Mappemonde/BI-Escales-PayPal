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

Only **`kind=berth`** AUTHORIZE orders include `payment_instruction.platform_fees`.
Project, gear, mile, membership, and common-fund pledges never add platform fees.
