# I18N-LEAKS-2 evidence

- `fr-treasurer-ag-studio-dashboard.png` — FR UI, AG Studio treasurer dashboard (`VITE_ENABLE_AG_STUDIO=1`, test2 API proxy).
- `en-gear-tab.png` — EN UI, Gear tab with localized seed titles.

Regenerate (local):

```bash
cd bi-escales/frontend
VITE_ENABLE_AG_STUDIO=1 VITE_API_PROXY_TARGET=https://bi-escales-api-test2.onrender.com npm run dev
node scripts/i18n-leaks-2-screenshots.mjs
```
