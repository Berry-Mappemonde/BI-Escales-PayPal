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
- Refunded has a new glyph, drawn on Meridian's 14px grid. The other glyphs are Meridian's.
- Approve, Override and Back this leg only change local state.
