# Channel3 catalogue and wishlists (sandbox)

BI Escales uses Channel3 **read-only** (catalog search / product research). The association **never** purchases through Channel3.

## Feature flags

| Variable | Default | Effect |
|----------|---------|--------|
| `ESCALES_CHANNEL3_ENABLED` | off | Live Channel3 MCP search + catalogue enrichment |
| `ESCALES_WISHLISTS_ENABLED` | off | HTTP API for the C3-02 seed catalogue and treasurer wishlists |

Both must be enabled for wishlist routes. Treasurer mutations still require `x-admin-key` (demo treasurer behaviour unchanged).

## Data

- Seed catalogue: `backend/static/channel3-catalogue.seed.json` (37 items, evidence C3-02)
- Categories: `accastillage`, `crew_safety` (core); `crew_clothing` (optional, not in default published lists)

## Public safety

- Items whose seed `catalog_status` or `review_status` is `needs_confirmation` are omitted from the public catalogue and wishlists, and `POST /pledges` returns 422.
- `channel3_buy_url` is omitted until funded minor units cover the target (`funded_minor >= target_minor` in the item currency, whole units for JPY/HUF/TWD). `funded_pct` is floored and is 100 only at that point.
- When shown, responses include `channel3_buy_disclosure` (referral commission notice).
- No checkout/purchase/order calls to Channel3 are permitted in code (guard in `channel3_client.py`).

## Native currency pledges (PayPal sandbox)

For catalogue `project_id` values (`gear-c3-*`):

- `POST /pledges` with `kind: "project_pledge"` sets PayPal `currency_code` from the catalogue (`price_currency`). Any client-sent currency is ignored.
- Request field **`amount_eur`** is the legacy JSON name; for catalogue items it carries the **native** amount in `price_currency` (not always euros).
- Funding totals sum captures **in that currency only** (`funded_amount_minor`, `funded_pct`). No FX conversion.
- `paypal_currency_supported` is `true` when the currency is on PayPal’s allow-list in `channel3_paypal.py` ([currency codes](https://developer.paypal.com/reference/currency-codes/)). Unsupported catalogue currencies return **422** on pledge create.
- **JPY, HUF, TWD**: PayPal order amounts are whole units (no decimal `.value`). Other supported currencies use two decimal places.
- Ledger finance lines store `currency` on each capture; funding totals never mix currencies.
- Stop/cabin/common-fund pledges stay **EUR** unchanged.

## Native totals vs received net EUR (PayPal settlement)

PayPal sandbox captures in USD/GBP (and other native catalogue currencies) are **settled into EUR** on the association merchant account. The EUR the treasurer can spend is **not** the native captured amount:

| Field | Meaning |
|-------|---------|
| `totals_by_currency` / `funded_pct` | Native currency only (catalogue goal and progress). No FX. |
| `received_net_eur` (pledge + fund) | EUR net from PayPal `seller_receivable_breakdown.net_amount` after fees and PayPal’s exchange rate. |
| Refunds | Stay in the pledge’s native currency on the refund API; EUR takeback from `seller_payable_breakdown` reduces `received_net_eur`. |
| Project payouts | Bounded by summed `received_net_eur`, not by treating USD/GBP as EUR. |

Settlement fields (`gross_amount`, `paypal_fee`, `net_amount`, `exchange_rate`, `receivable_amount` when present) are stored on the pledge and on `pledge_captured` finance lines. Missing breakdown on non-EUR captures logs a warning and leaves settlement fields null; EUR captures without breakdown keep the previous behaviour (amount minus fee when reported).
