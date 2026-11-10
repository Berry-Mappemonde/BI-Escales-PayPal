# UI polish before/after

Screenshots for the `feat/ui-polish` pull request (fixes 1, 3, 4, 5, 6) and the
`feat/ui-mobile` pull request (fix 2), one set per numbered fix.

- Viewports: 1440x900 and 390x844 (2x), dark theme, English.
- Each "before" is the build of the commit just before the fix; each "after" is
  the build of the fix's own commit, so a pair shows that fix only.
- Local run only: memory store, `PAYPAL_ENV=sandbox`, no keys entered. The
  public Crew plan lookup is answered in the browser so the Crew block renders
  (the memory store has no plan); nothing else is mocked.
- For fixes 1, 3, 4, 5 and 6 the 390px "after" views still show the left sidebar
  over the map and the pledge rail. That is fix 2 (mobile bottom sheet), which
  ships separately in the `feat/ui-mobile` pull request; its "before" is the
  tip of `feat/ui-polish`.
- The phone views are Chrome's 390x844 touch emulation, not a physical phone.

| Fix | Files |
| --- | --- |
| 1. Stop sheet money story | `fix1-*` |
| 2. Mobile: map first, bottom sheet | `fix2-*` |
| 3. Hierarchy (primary action, Crew membership) | `fix3-*` |
| 4. Plain wording | `fix4-*` |
| 5. Map | `fix5-*` |
| 6. Header and sidebar | `fix6-*` |
