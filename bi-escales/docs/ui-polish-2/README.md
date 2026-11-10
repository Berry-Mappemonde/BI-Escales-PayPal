# UI polish, round 2: before/after

Screenshots for the `feat/ui-polish-2` pull request, one set per numbered fix
(fix 2, Card Fields theming, was skipped: see the pull request).

- Viewports: 1440x900 (the treasurer page at 1440x1500 so the whole queue shows)
  and 390x844 (2x, Chrome touch emulation, not a physical phone). Dark theme,
  English, unless the file name says `light`.
- Each "before" is the build of the commit just before the fix; each "after" is
  the build of the fix's own commit.
- Local run only: memory store, `PAYPAL_ENV=sandbox`, `ESCALES_ENABLED=true`, and
  the demo clock pinned with `ESCALES_CLOCK_NOW=2026-11-12T10:00:00Z`, the moment
  at which Saint-Maur shows "Arrived" and La Rochelle does not. No key was entered.
- The screenshot builds use PayPal's public placeholder client id (`test`) so that
  PayPal's own buttons render. It is not a credential and is not committed.
- Answered in the browser, because the memory store cannot hold them without
  PayPal credentials: the public Crew plan lookup, the demo treasurer's pledge
  list (four sample pledges) and the Captain review for those pledges.

| Fix | Files |
| --- | --- |
| 1. "Back the next stop" target | `fix1-*` |
| 3. Treasurer page width | `fix3-*` |
| 4. Crew Subscribe button | `fix4-*` |
| 5. Other polish | `fix5-*` |
