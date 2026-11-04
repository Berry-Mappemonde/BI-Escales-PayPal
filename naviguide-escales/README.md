# NAVIGUIDE simulator

NAVIGUIDE is live at **https://naviguide.fr**: the Berry-Mappemonde expedition cockpit <!-- pragma: allowlist secret -->
(Leaflet map, layer buttons, moving boat, searoute, polars).
Every merge on `main` deploys this version.

## Models

NAVIGUIDE runs three open NVIDIA Nemotron models on Nebius Token Factory:

- Nemotron 3.5 Lightning: fast routing (chat intent, stopover question pick, film moment ids, JSON only), short sentences and FR→EN translation of every story. It replaces Nemotron 3 Nano 30B, retired from Token Factory on 9 November 2026.
- Nemotron 3.5 Super VL: writes the "Here" stories, the written film and the plan review (it replaces Nemotron 3 Super 120B, retired on 9 November 2026), and looks at a local drawing of the route.
- Nemotron 3 Ultra 550B: writes stopover and alert stories, then edits and judges the written film.

Every label on screen names the model that really answered; NIM fallback is labelled as such.

The Blue Intelligence API stays at https://blueintelligence.online/api
(separate repository and server).


## Run (macOS)

**Automatique** (recommandé) : des hooks d’éditeur locaux démarrent API + Vite à l’ouverture de la session et ouvrent le navigateur. Tu codes, tu regardes l’onglet `http://localhost:5174` (rechargement auto).

**Manuel** :

```bash
cd naviguide-simulator
bash ensure-dev.sh --open    # tout en arrière-plan
bash dev-mac.sh              # Vite dans ce terminal
bash stop-dev.sh             # arrêter
```

Merge sur `main` → déploiement CI vers `simulator.naviguide.fr` (voir `.github/workflows/deploy.yml`).

## Publish on the VPS

When the `simulator.naviguide.fr` DNS already points at `135.125.226.16`
(from the Mac, or any machine with Node + SSH):

```bash
cd /path/to/NAVIGUIDE
bash infra/vps/naviguide/publish-simulator-from-mac.sh
```

That builds the site on the Mac, copies only this folder and the
simulator infra files, then on the VPS: Python venv, `:8010` service, **separate** nginx,
extended Let's Encrypt certificate (free). `www.naviguide.fr` is not
redeployed. Details: `infra/vps/README.md` (simulator section).

| It works | It does not exist yet |
|---|---|
| NAVIGUIDE film (2 sidebars, Berry, simulation, briefing) | 4 Ports / Safety / Weather / Cruisers chats |
| Climatology clock: departure date, days at sea, ETA by month | GRIB / GFS / “arrival Tuesday 2 pm” (simulation B) |
| Searoute + draw your own route | Polar chat |
| Polar upload + VMG table (Leopard 46) | GeoJSON or KML import / export |
| Civil clock + virtual boat (Follow, named 10-day forecast, recompute **one** leg) | Globe GRIB, 39 000 nm isochrone, port 3010 |
| Layer chips (Sextant, Argo, ODATIS, EDMED, CSR, bathymetry, seabed, cables + Climatology stub) | |
| `ici()`: EEZ, Gold PoE, MPA / projects / ports within 30 nm — the briefing tells this bag | Tavily / Nemotron / Token Factory (steps 5–6) |
| Route click → wind / wave / current | Dump of the whole map into the story |

**Not for navigation.**

## Licences and attributions

The repository is **MIT / Apache-2.0**. The simulator does not ship LeafletPlayback,
TrackPlayBack, deck.gl or signalk-polar-performance: those are *ideas*
(clock, wake, TWA→knots). The film / polar code is original.

To display (already in the footer, the map and the modal):

| Source | Licence / credit |
|---|---|
| Leaflet | BSD-2-Clause — “Leaflet” in the attribution control |
| Esri Canvas tiles | “Tiles © Esri” |
| OpenSeaMap (marks) | ODbL — “© OpenSeaMap contributors” |
| EMODnet (bathy / seabed / cables) | CC-BY — WMS attribution |
| GEBCO (offshore sounding in the bag) | GEBCO Compilation Group — OpenTopoData point lookup (GEBCO 2020), `null` within 20 M of a port |
| Leopard 46 polar | ORC file loaded by the user / local default |

Per-source URL, the licence string actually written in the repo, the credit on screen, and the survey date (or « à vérifier »): [DATA_SOURCES.md](DATA_SOURCES.md). Model ids, cascade, budgets, and the AI disclosure: [docs/AI_GOVERNANCE.md](docs/AI_GOVERNANCE.md).

**Veille Tavily par escale (U0)** : active par défaut (`NAVIGUIDE_TAVILY_WATCH=1`). Mettre `NAVIGUIDE_TAVILY_WATCH=0` pour la désactiver. Les tests forcent l'arrêt (`conftest.py`).
