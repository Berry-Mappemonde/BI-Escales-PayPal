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
