# Round 3: map layers and Channel3 pictures, before/after

Screenshots for the `feat/map-layers` pull request.

- Viewports: 1440x900 and 390x844 (2x, Chrome touch emulation, not a physical
  phone). Dark theme, English.
- Each "before" is the build of the commit just before the fix; each "after" is
  the build of the fix's own commit.
- Local run only: memory store, `PAYPAL_ENV=sandbox`, `ESCALES_ENABLED=true`.
  The builds use PayPal's public placeholder client id (`test`) so PayPal's own
  buttons render; it is not a credential and is not committed.

`fix1-*`: the layer control. Real local data, nothing answered in the browser.

`fix2-*`: Channel3 pictures. The memory store has no Channel3 data, so the
wishlist, catalogue, gear and cart responses are answered in the browser with
four sample items (one without a picture), and the pictures are drawn by the
screenshot script; nothing is fetched from a shop.

- `fix2-*-wishlists`: the public wishlist page.
- `fix2-*-treasurer-lines`: the treasurer's wishlist section. The key field holds
  a placeholder word, not a credential; the local server has no admin key.
- `fix2-*-gear-*`: the gear list, the gear map popup and the cart. **The Gear tab
  is hidden in the product** (`GEAR_TAB_VISIBLE = false`, #209). These views come
  from a scratch build with that constant switched on, only to show how the rows
  look; the constant is not changed in the pull request.
