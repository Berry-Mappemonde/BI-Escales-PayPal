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

- `channel3_buy_url` is omitted until an item is **fully funded** in its native currency.
- When shown, responses include `channel3_buy_disclosure` (referral commission notice).
- No checkout/purchase/order calls to Channel3 are permitted in code (guard in `channel3_client.py`).

## Native currency pledges (PayPal sandbox)

For catalogue `project_id` values (`gear-c3-*`):

- `POST /pledges` with `kind: "project_pledge"` sets PayPal `currency_code` from the catalogue (`price_currency`). Any client-sent currency is ignored.
- Funding totals sum captures **in that currency only** (`funded_amount_minor`, `funded_pct`). No FX conversion.
- `paypal_currency_supported` is `true` when the currency is on PayPal’s allow-list in `channel3_paypal.py` ([currency codes](https://developer.paypal.com/reference/currency-codes/)). Unsupported catalogue currencies return **422** on pledge create.
- **JPY, HUF, TWD**: PayPal order amounts are whole units (no decimal `.value`). Other supported currencies use two decimal places.
- Ledger finance lines store `currency` on each capture; funding totals never mix currencies.
- Stop/cabin/common-fund pledges stay **EUR** unchanged.
