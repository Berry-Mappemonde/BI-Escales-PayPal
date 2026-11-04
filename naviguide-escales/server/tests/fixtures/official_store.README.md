# Stock officiel figé (lot RF11)

Date du gel : 2026-10-15 (UTC).
Archive : `server/tests/fixtures/official_store.tar.gz` (903436 octets).
Familles présentes : climo, eta, film, ici, moments, plan_review.
Familles absentes du poste (restent « en préparation ») : aucune.
Clés :

- `c4a0d2dc06cea61b:2026-05-15T08:00:00Z:2026-09-27`
- `c4a0d2dc06cea61b:2026-05-15T08:00:00Z:2026-09-27:rf5`
- `c4a0d2dc06cea61b:2026-05-15T08:00:00Z:2026-10-15`
- `c4a0d2dc06cea61b:2026-05-15T08:00:00Z:2026-10-15:rg4`

Route du gel : `server/tests/fixtures/official_store.route.geojson`, copie de
`public/route.geojson` au moment du gel. La recette hors ligne sert les deux
ensemble ; `test_frozen_archive_is_paired_with_its_route` échoue s'ils divergent.

État au 25 oct. 2026 : la route publiée a changé depuis le gel (c94b9fd, 429c1e3,
fb82b26, 4a88e93). La recette tourne sur la route du gel (empreinte
c4a0d2dc06cea61b) en attendant un stock recalculé sur la route publiée ; l'étape
CI « Stock figé de la recette et route publiée » donne l'empreinte publiée du jour.

Film 150 s rédigé (29 oct. 2026, feat/film-150s) : la clé film `…:2026-10-29:vs1-ed2`
porte aussi `written.fr["150"]` et `written.en["150"]`, issus d'un run réel Token Factory
(Super-VL rédige, Ultra édite/juge/relit, Lightning traduit ; relecture FR et EN « pass »,
reçu de 56 appels, 0 repli). FR ≈ 139 s, EN ≈ 132 s (15 car./s). Seule la clé `written`
a été ajoutée : les variantes brutes 150/180/intégral et les autres familles sont
inchangées, la route du gel aussi. `test_frozen_store_holds_reviewed_150s_film_fr_and_en`
vérifie leur présence.

Commande pour régénérer (après un vrai calcul, si la route ou t0 change) :

```bash
cd naviguide-simulator
NAVIGUIDE_LLM_MODE=off .venv/bin/python scripts/prepare_official_store.py
.venv/bin/python scripts/freeze_official_store.py
```

`NAVIGUIDE_LLM_MODE=off` : sans lui, une clé présente sur le poste fait des
appels Nano/Lightning payants pendant le calcul.

Le script lit `~/.cache/naviguide/voyage-store` (ou `NAVIGUIDE_OFFICIAL_STORE_DIR`).
Aucune donnée n'est inventée : on gèle le stock déjà calculé.
