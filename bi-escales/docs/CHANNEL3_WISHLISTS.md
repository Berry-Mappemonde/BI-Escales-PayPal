# Channel3 catalogue and wishlists (sandbox)

BI Escales uses Channel3 **read-only** (catalog search / product research). The association **never** purchases through Channel3.

## Feature flags

| Variable | Default | Effect |
|----------|---------|--------|
| `ESCALES_CHANNEL3_ENABLED` | off | Live Channel3 MCP search + catalogue enrichment |
| `ESCALES_WISHLISTS_ENABLED` | off | HTTP API for the C3-02/C3-02b seed catalogue and treasurer wishlists |

Both must be enabled for wishlist routes. Treasurer mutations still require `x-admin-key` (demo treasurer behaviour unchanged).

## Data

- Seed catalogue: `backend/static/channel3-catalogue.seed.json` (**52** items: 9 retained C3-02 + 43 C3-02b offshore; clothing excluded)
- Public catalogue count: **50** items (excludes 2 liferafts pending capacity confirmation)
- Categories: `accastillage`, `crew_safety` (core); `crew_clothing` optional and not in the seed

Example catalogue ids for docs/tests (not hardcoded in frontend):

| Id | Use |
|----|-----|
| `QE0Vp6a` | USD accastillage (Rule 500 GPH bilge pump) |
| `K6gupx4` | GBP crew_safety (HX210E VHF) |
| `9zyqp3q` | EUR accastillage (Regatta binoculars) |
| `Gf8pNpL` | USD crew_safety (handheld VHF) |

### `needs_confirmation`

These seed items exist for research but are **hidden** from public catalogue and wishlist publish until a treasurer clears the flag in the seed:

| Id | Item | Reason |
|----|------|--------|
| `k4nWRDl` | Viking RescYou ISO 9650-1 life raft | Confirm capacity ≥ 6 persons |
| `60BXA1O` | Mustang Offshore Voyager life raft | Capacity unknown on listing |

Wishlist lines that reference a removed id or a `needs_confirmation` item appear on **published** lists with `catalog_available: false` and `unavailable_reason` (no HTTP 500).

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
| Project payouts | Bounded by summed `received_net_eur` (capture EUR net after PayPal fees/FX, minus refund EUR takebacks), not by treating USD/GBP as EUR. |

Settlement fields (`gross_amount`, `paypal_fee`, `net_amount`, `exchange_rate`, `receivable_amount` when present) are stored on the pledge and on `pledge_captured` finance lines. Missing breakdown on non-EUR captures logs a warning and leaves settlement fields null; EUR captures without breakdown keep the previous behaviour (amount minus fee when reported).
