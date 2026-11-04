# Sources de données du simulateur

Ce fichier ne couvre que `naviguide-simulator/`. Les chemins partent de ce dossier. Une licence n’est écrite que si le dépôt la nomme. Sinon : **à vérifier** (elle n’est pas devinée). Une durée de cache n’est pas une date de relevé.

This file covers `naviguide-simulator/` only. Paths start in that folder. A licence is stated only when the repository names it. Otherwise: **à vérifier**. A cache TTL is not a survey date.

## Marine Regions — ZEE v12

| | |
|---|---|
| URL | WMS `https://geo.vliz.be/geoserver/MarineRegions/wms` (`server/main.py:794`), proxifié en `/proxy/zee/wms` (`src/layers/useToggleLayers.js:278`, couche `eez_boundaries`). WFS `https://geo.vliz.be/geoserver/MarineRegions/wfs` (`server/main.py:902`). Gazetteer `https://www.marineregions.org/rest/getGazetteerRecordsByLatLong.json` (`server/ici_engine.py:109`). GeoJSON v12 : `GET {BI_API_URL}/poe/zones/geojson`, cache `eez_vliz_v12.geojson` (`server/zee_local.py:1-6`, `server/zee_local.py:45-55`). Page citée : `https://www.marineregions.org/` (`src/layers/tileAttributions.js:27`). |
| Licence écrite | CC-BY 4.0, lien `https://creativecommons.org/licenses/by/4.0/` (`src/layers/tileAttributions.js:11-27`, `server/zee_local.py:6`, `src/engine/toponymsTable.json:4`). |
| Ambiguïté | Le dépôt ne contient pas la chaîne CC-BY-NC-SA. Il ne tranche pas l’écart CC-BY / CC-BY-NC-SA de la v12. **à vérifier**. |
| Attribution affichée | `VLIZ_EEZ_ATTRIBUTION` : Flanders Marine Institute (VLIZ), Marine Regions, lien CC-BY 4.0 (`src/layers/tileAttributions.js:26-27`), posée par `bindTileCredit` (`src/layers/useToggleLayers.js:276`). Test : `src/layers/tileAttributions.test.js:46-76`. |
| Version écrite | v12 (`server/zee_local.py:1`, `src/engine/toponymsTable.json:4`). |
| Date de relevé | **à vérifier**. Cache disque 30 jours (`server/zee_local.py:35`). |

The repository attributes CC-BY 4.0 and does not contain CC-BY-NC-SA. Which notice VLIZ actually applies to EEZ v12 is **à vérifier**.

## World Port Index

| | |
|---|---|
| URL | `https://msi.nga.mil/api/publications/world-port-index` (`server/ici_engine.py:111`), `GET` avec `output=json` (`server/ici_engine.py:1418-1421`). |
| Licence | **à vérifier**. Aucune licence n’est nommée à côté de cette URL. |
| Attribution affichée | Titres de couche « Ports mondiaux — World Port Index (NGA) » et « World Port Index (NGA) » (`src/i18n/fr.js:405`, `src/i18n/en.js:405`). Pas de crédit Leaflet dédié dans `src/layers/tileAttributions.js`. |
| Date de relevé | **à vérifier**. Mémoire 86 400 s (`server/ici_engine.py:148`, `server/main.py:791`). |

## OpenStreetMap (ODbL)

| | |
|---|---|
| URL | Crédit de fond : `https://www.openstreetmap.org/copyright` (`src/layers/styles.js:14`). Balisage : `https://tiles.openseamap.org/seamark/{z}/{x}/{y}.png` (`src/layers/useToggleLayers.js:312`). Requêtes : `https://overpass.openstreetmap.fr/api/interpreter` et `https://overpass-api.de/api/interpreter` (`server/ici_layers.py:74-77`). Constante `OSM_COPYRIGHT_HREF` (`src/layers/tileAttributions.js:9`). |
| Licence écrite | Le sigle ODbL est écrit pour le balisage OpenSeaMap (`README.md:66`, `src/i18n/fr.js:334`, `src/i18n/en.js:334`). Le crédit du fond nomme « OpenStreetMap contributors » et pointe la page copyright ; il ne répète pas le sigle (`src/layers/styles.js:14`). |
| Attribution affichée | Fond : `tileAttribution` (`src/layers/styles.js:12-16`). Balisage : `© OpenSeaMap contributors` (`src/layers/tileAttributions.js:7`), posé en `src/layers/useToggleLayers.js:310`. Test : `src/layers/tileAttributions.test.js:47`, `src/layers/styles.test.js:30`. |
| Date de relevé | **à vérifier**. |

## EMODnet

| | |
|---|---|
| URL | Bathymétrie `https://ows.emodnet-bathymetry.eu/wms` (couche `mean_multicolour`) ; géologie `https://drive.emodnet-geology.eu/geoserver/gtk/wms` (`seabed_substrate_1m`) ; activités `https://ows.emodnet-humanactivities.eu/wms` (`telecablesactual,powercables`) — `src/layers/scienceWms.js:11-31`. Échantillon de profondeur : `https://rest.emodnet-bathymetry.eu/depth_sample` (`server/ici_layers.py:70`). Pages : `src/layers/tileAttributions.js:17-23`. Index briefing : `https://emodnet.ec.europa.eu/` (`src/engine/briefingLinks.js:228`). |
| Licence écrite | CC-BY 4.0 (`src/layers/tileAttributions.js:15-23`). Le README du simulateur résume « CC-BY » (`README.md:67`). |
| Attribution affichée | EMODnet Bathymetry Consortium, EMODnet Geology, EMODnet Human Activities, chacune avec le lien CC-BY 4.0 (`src/layers/tileAttributions.js:16-23`). Test : `src/layers/tileAttributions.test.js:63-74` (la bathymétrie affichée n’est pas le crédit GEBCO). |
| Date de relevé | **à vérifier**. |

## Copernicus Marine

| | |
|---|---|
| URL | Produits ouverts par `copernicusmarine.open_dataset` : vent `cmems_obs-wind_glo_phy_nrt_l4_0.125deg_PT1H` (`server/copernicus/getWind.py:166`), vagues `cmems_mod_glo_wav_anfc_0.083deg_PT3H-i` (`server/copernicus/getWave.py:146`), courant `cmems_mod_glo_phy_anfc_0.083deg_PT1H-m` (`server/copernicus/getCurrent.py:5`, `server/copernicus/getCurrent.py:156`). Page liée dans le briefing : `https://marine.copernicus.eu/` (`src/engine/briefingLinks.js:230`). L’atlas affiché s’appelle « Atlas CMEMS » (`src/i18n/fr.js:314`, `src/i18n/en.js:314`). |
| Licence | **à vérifier**. Ces fichiers ne nomment pas de licence. |
| Attribution affichée | Libellés « Atlas CMEMS » / « CMEMS atlas » (`src/i18n/fr.js:323-324`, `src/i18n/en.js:323-324`). Pas de crédit Leaflet dans `src/layers/tileAttributions.js`. |
| Date de relevé | **à vérifier**. |

Le catalogue Copernicus Data Space (Sentinel-2, `server/ici_layers.py:52-58`) est un autre service. Sa licence est **à vérifier** ; il n’est pas un produit Copernicus Marine.

Copernicus Data Space (Sentinel-2) is a different service. Its licence is **à vérifier**.

## GEBCO

| | |
|---|---|
| URL | `https://api.opentopodata.org/v1/gebco2020` (`server/gebco_lookup.py:14`). Page briefing : `https://www.gebco.net/` (`src/engine/briefingLinks.js:229`). Le module client `src/engine/gebco.js:1-4` ne charge pas de grille : sans grille précalculée le sondage reste nul. |
| Licence | **à vérifier**. Le dépôt nomme le produit et le groupe, pas un identifiant de licence. |
| Attribution affichée | « GEBCO Compilation Group » dans la phrase de profondeur au large (`src/engine/iciBriefing.js:1006-1007`). En-tête : `server/gebco_lookup.py:4-5`. README : `README.md:68`. Le crédit bathymétrique de la carte reste EMODnet, pas GEBCO (`src/layers/tileAttributions.test.js:63-70`). |
| Version écrite | GEBCO 2020 (`server/gebco_lookup.py:4-14`). |
| Date de relevé | **à vérifier**. Coupure côtière 20 milles (`server/gebco_lookup.py:13`, `src/engine/gebco.js:4`). |

## ProtectedSeas / AMP

| | |
|---|---|
| URL | Pas d’hôte `protectedseas` dans le simulateur. Les polygones viennent de Blue Intelligence : `GET {BI_API_URL}/amp` (`server/ici_engine.py:892`) et, en repli, `GET {BI_API_URL}/export/amp.geojson` (`server/ici_engine.py:923`). Interdites : `GET {BI_API_URL}/amp/nogo` (`server/amp_nogo.py:4`). |
| Rôle ProtectedSeas | Champs `entry` / `speed` (0 autorisé, 1 interdit, 2 restreint, 3 inconnu) : `server/amp_traffic.py:1-5`, `src/engine/ampRules.js:1-3`. Commentaire : une tuile inconnue passerait par ProtectedSeas côté backend (`server/ici_engine.py:716`). Couleurs LFP 0–5 : `src/layers/styles.js:37-44`. |
| Licence | **à vérifier**. |
| Attribution affichée | **à vérifier**. Aucun crédit ProtectedSeas dans `src/layers/tileAttributions.js`. |
| Date de relevé | **à vérifier**. |

## Saildocs / GRIB

| | |
|---|---|
| URL | **à vérifier**. Le dépôt ne contient pas d’URL Saildocs. Il construit une requête texte (`server/saildocs.py:327-355`), par exemple un produit, une boîte, une grille et une fenêtre horaire. |
| Produits écrits | GFS (vent, pression, pluie), WW3 / GFS-Wave (vagues), RTOFS (courants), décrits comme produits NOAA (`server/saildocs.py:29-66`). En-tête : dernier GRIB2 autour du bateau, pas un GRIB globe (`server/saildocs.py:1-5`). |
| Licence | **à vérifier**. « Gratuit » (`server/saildocs.py:34`, `server/saildocs.py:366`) n’est pas une licence. |
| Attribution affichée | **à vérifier**. Pas de crédit Saildocs dans `src/layers/tileAttributions.js`. |
| Date de relevé | **à vérifier**. Le fichier gardé est le dernier cycle prêt (`server/saildocs.py:5`). |

## Tavily

| | |
|---|---|
| URL | `https://api.tavily.com` (`server/tavily_client.py:18`), `POST /extract` et `POST /search` (`server/tavily_client.py:70`, `server/tavily_client.py:133`). Surcharge : `TAVILY_API_BASE`. |
| Conditions d’utilisation | **à vérifier**. Le dépôt ne les copie pas. |
| Attribution affichée | Badge « Vérifié le {date} · Tavily + Nemotron 3 Ultra » / « Checked {date} · Tavily + Nemotron 3 Ultra » (`src/i18n/fr.js:164`, `src/i18n/en.js:164`). Aucun fichier `src/**/*.jsx` ne contient le mot Tavily : pas de bouton. |
| Date de relevé | **à vérifier**. La veille est active par défaut (`server/escale_watch.py:100-102`) ; `NAVIGUIDE_TAVILY_WATCH=0` la désactive. |

Le détail (fenêtre, tours, plafonds, données envoyées) est dans [docs/AI_GOVERNANCE.md](docs/AI_GOVERNANCE.md).

## Blue Intelligence (API interne)

| | |
|---|---|
| URL | `BI_API_URL` (`server/bi_upstream.py:23-28`). Sans variable, aucun hôte n’est appelé. Le README racine du dépôt indique l’API séparée `https://blueintelligence.online/api` et le dépôt Berry-Mappemonde/Blue-Intelligence (`../README.md:15`, `../README.md:224-233`). Exports lus ici : `server/main.py:796-802`. |
| Licence | **à vérifier**. Le simulateur ne nomme pas de licence ouverte pour ce contenu. |
| Attribution affichée | Libellé de groupe « Blue Intelligence » (`src/i18n/fr.js:413`, `src/i18n/en.js:413`). Les couches scientifiques affichées reprennent les crédits EMODnet ci-dessus (`src/layers/scienceWms.js:7`). |
| Date de relevé | **à vérifier**. |

## Hors de cette fiche

Open-Meteo, NOAA NOMADS/RTOFS et les tuiles Esri sont appelés (`server/ici_layers.py:59-61`, `src/layers/styles.js:3-14`). Leurs licences ne sont pas reprises ici.
