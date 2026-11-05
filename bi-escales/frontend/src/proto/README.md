# Direction preview (mock)

Three screens for reviewing a design direction: the Ajaccio stop panel, the Captain review card and the pledge status chips. Static mock data only, with no PayPal SDK and no API calls.

## Open it

```bash
npm run dev
```

Then go to `http://localhost:5173/src/proto/`. Add `?screen=stop|captain|pledges` and `&lang=fr|en` to link to a specific view.

This page is its own Vite HTML entry, so `main.tsx`, `index.html` and the config are unchanged. It exists on the dev server only: `vite build` does not include it.

## Notes

- `tokens.css` is the Team_ops `@theme` block as plain custom properties, because this frontend has no Tailwind.
- Strings live in `strings.ts` on a private i18next instance. The app's locale files and language are untouched.
- The display labels map to `PledgeStatus` in `src/api/types.ts`: held = `authorized`, saved = `vaulted`, released = `voided`. Captured and refunded keep their names.
- En route and Refunded have new glyphs, drawn on Meridian's 14px grid. The other glyphs are Meridian's.
- Amber means money held and nothing else. En route uses `--color-st-route`, the one colour added to Meridian, defined in `proto.css` so `tokens.css` stays an exact copy.
- Approve, Override and Back this leg only change local state.
- Override can only release the hold, so the Captain card never offers capture. Pledges are captured on arrival (on departure for cabins), only after a person approves.
- A release can be undone for 5 seconds. After that it is final, and only a page reload clears it, because nothing is stored.
