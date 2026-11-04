# Déploiement Render — préparé, pas lancé

Source : `bi-escales/render.yaml` (service Python `bi-escales-api` déjà en sandbox)
et le site statique Vite de `bi-escales/frontend`.

Le plus simple est un **second service statique**, pas FastAPI qui sert le build.
L'API tourne déjà sur `https://bi-escales-api.onrender.com`. Le navigateur l'appelle
avec `VITE_API_BASE`. L'API accepte l'origine `https://bi-escales.onrender.com` (CORS).

| Service | Rôle |
| --- | --- |
| `bi-escales-api` | FastAPI, inchangé. Ne pas redéployer depuis cette PR. |
| `bi-escales` | Site statique. `rootDir: bi-escales/frontend`, `npm ci && npm run build`, publication de `dist`. |

`autoDeployTrigger: off` sur le site statique : un push ne déploie pas.
Ne pas synchroniser le blueprint tant que la PR n'est pas acceptée.

En local, laisser `VITE_API_BASE` vide. Vite proxifie `/api` vers la même API.
Si la page et l'API partagent un hôte, garder `VITE_API_BASE` vide : les URL restent relatives.
