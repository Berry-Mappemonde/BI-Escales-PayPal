# Specs archivés

Hors du répertoire `e2e/` : Playwright ne les joue plus (ni en CI, ni sur le poste). Gardés pour mémoire,
avec la décision qui les a sortis de la suite.

| Spec | Lot | Sorti le | Pourquoi |
|---|---|---|---|
| `l3-juge.spec.js` | L3 | 28 sept. 2026 | Le badge du juge de vérité (Tavily + Nemotron Ultra) n'est plus rendu depuis R8c ; le calcul est coupé par défaut (PR #401, `NAVIGUIDE_TRUTH_JUDGE=1` pour rallumer). Si le badge revient dans le panneau « ici », réécrire le spec sur la nouvelle surface, pas le réactiver tel quel. |
| `l4-veille.spec.js` | L4 | 28 sept. 2026 | La carte de veille par escale (Tavily) n'est plus rendue depuis R8c ; la veille est coupée par défaut (PR #401, `NAVIGUIDE_TAVILY_WATCH=1`). Même règle. |
