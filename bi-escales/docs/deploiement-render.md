# Déploiement Render — préparé, pas lancé

Source : `bi-escales/render.yaml`. Un seul service web gratuit, `bi-escales-api`.
Le site statique `bi-escales` (hôte `https://bi-escales.onrender.com`) n'est plus
dans le blueprint : cette URL répond 404, et le retour PayPal doit viser le
même hôte que la page.

FastAPI sert l'API sous `/api` et le build Vite (`bi-escales/frontend/dist`)
sur le reste des chemins. `ESCALES_RETURN_URL` et `ESCALES_CANCEL_URL`
valent `https://bi-escales-api.onrender.com/?paypal=return` et `?paypal=cancel`.
`VITE_API_BASE` reste vide : le navigateur appelle `/api` sur la même origine.

`autoDeployTrigger: off`. Un push ne déploie pas. Ne pas synchroniser le
blueprint tant que la PR n'est pas acceptée.

Le build installe le frontend (`npm ci && npm run build`) puis les dépendances
Python. L'image de build Render fournit Node à côté du runtime Python.

En local, laisser `VITE_API_BASE` vide. Vite proxifie `/api` vers
`https://bi-escales-api.onrender.com`.
