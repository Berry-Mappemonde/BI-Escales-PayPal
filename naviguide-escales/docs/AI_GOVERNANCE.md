# Gouvernance des modèles du simulateur

Chemins depuis `naviguide-simulator/`. `server/story_cascade.py` et `server/llm_budget.py` sont cités, pas modifiés. Une région, une licence ou un document absent du dépôt : **à vérifier**.

Paths start at `naviguide-simulator/`. `server/story_cascade.py` and `server/llm_budget.py` are cited, not edited. A region, licence, or document missing from the checkout: **à vérifier**.

Sources de données : [../DATA_SOURCES.md](../DATA_SOURCES.md).

## Modèles par palier

Défauts de `server/llm_budget.py:116-137`, test `server/tests/test_llm_budget.py:38-44`. Une variable `NAVIGUIDE_TF_MODEL_*` peut les remplacer (`server/llm_budget.py:145-181`).

| Palier | Identifiant | Source UI | Hôte Token Factory dans ce dépôt |
|---|---|---|---|
| `fast` | `nvidia/Nemotron-3_5-Lightning` | `nemotron-lightning` | `https://api.tokenfactory.nebius.com/v1` (`server/story_cascade.py:33-36`, `server/story_cascade.py:581-590`) |
| `write` | `nvidia/Nemotron-3.5-Super-VL` | `nemotron-super-vl` | `NAVIGUIDE_TF_BASE_EU` (UE par défaut ; `server/story_cascade.py:40-43`, `server/story_cascade.py:728-731`) |
| `deep` | `nvidia/Nemotron-3-Ultra-550b-a55b` | `nemotron-ultra` | `NAVIGUIDE_TF_BASE_ULTRA` (`https://api.tokenfactory.nebius.com/v1` par défaut ; `server/story_cascade.py:37-41`, `server/story_cascade.py:728-731`) |
| `judge` | `nvidia/Nemotron-3-Ultra-550b-a55b` | `nemotron-ultra` | même hôte UE par défaut que `deep` |

Le test `test_ultra_payload_uses_cookbook_host_and_budget` (`server/tests/test_story_cascade.py`) exige l’hôte UE `api.tokenfactory.nebius.com` pour `deep`, `fast` et `write`.

`eu-north1` n’apparaît pas dans le dépôt. `devpost/nebius_futur.md` n’y est pas. Toute région autre que les hôtes par défaut listés ci-dessus est **à vérifier**.

`eu-north1` does not appear in this checkout, nor does `devpost/nebius_futur.md`. Any region other than the default hosts listed above is **à vérifier**.

Autres identifiants, hors de ces quatre paliers :

| Rôle | Identifiant | Preuve |
|---|---|---|
| NIM | `openai/gpt-oss-20b` | `server/story_cascade.py:51-56` |
| OpenRouter | `openai/gpt-4o-mini`, ou `OPENROUTER_MODEL` | `server/story_cascade.py:51-56` |
| Claude | `claude-haiku-4-5` | `server/story_cascade.py:51-56` |
| Embeddings | `Qwen/Qwen3-Embedding-8B`, seulement si `NAVIGUIDE_EMBEDDINGS=1` | `server/logbook_chat.py:100`, `server/logbook_chat.py:849-850` |
| Route VL | `nvidia/Nemotron-3.5-Super-VL` | `server/vl_route.py:49` |

Le README racine parle d’un hôte « Nano / Lightning / Super » (`../../README.md:173`) sans identifiant Nano dans `DEFAULT_MODELS`. **à vérifier**.

## Cascade

Ordre exécuté, défaut `tokenfactory`, `nim`, `openrouter`, `claude` (`server/story_cascade.py:59`, `server/story_cascade.py:191-205`). Test : `server/tests/test_story_cascade.py:60-70` (pas de Tavily dans ce module).

1. Cache SQLite 24 h (`server/story_cascade.py:64`, `server/story_cascade.py:1332-1364`).
2. Si le budget ou le mode refuse : `source=budget`, aucun appel fournisseur (`server/story_cascade.py:1384-1386`).
3. Token Factory. Sur le palier `fast` seulement, un vide, un HTTP ≥ 500 ou un timeout déclenche un second essai avec le modèle Super (`write`) ; un 4xx ne le déclenche pas (`server/story_cascade.py:1090-1105`, `server/story_cascade.py:1425-1432`). Test : `server/tests/test_story_cascade.py:947-983`.
4. Si ce saut échoue encore : NIM, puis OpenRouter, puis Claude (`server/story_cascade.py:59`, `server/story_cascade.py:1435-1450`). Sur `nano`, un échec Token Factory déclenche d’abord un second essai sur Token Factory avec Lightning. Après un timeout Token Factory, la cascade continue vers les fournisseurs non-Nemotron par défaut ; `NAVIGUIDE_LLM_TIMEOUT_FALLBACK=0` l’arrête (second essai nano : `server/story_cascade.py:1411-1424` ; défaut ON : `server/story_cascade.py:1085-1087` ; contrôle après timeout : `server/story_cascade.py:1458-1462`). Test vide Lightning puis Super vide → NIM : `server/tests/test_story_cascade.py:1016-1045`.
5. Si un texte de repli est fourni : `source=rules` (`server/story_cascade.py:1513-1516`).

Deux docstrings sont en retard sur ce code : la ligne 1 et la ligne 1121 de `server/story_cascade.py` n’y mentionnent pas NIM. L’ordre qui tourne est `DEFAULT_PROVIDERS` et le test cité.

`filter_numbers` s’applique au texte de chaque fournisseur et au repli (`server/story_cascade.py:424-430`, `server/story_cascade.py:1479-1481`, `server/story_cascade.py:1513-1515`).

## Filtre des chiffres

`filter_numbers` retire chaque phrase dont un nombre n’est pas déjà dans les faits (`server/story_cascade.py:368-388`). Tests : `server/tests/test_story_cascade.py:345`, `server/tests/test_story_cascade.py:364`, `server/tests/test_logbook_chat.py:245`, `server/tests/test_escale_watch.py:212`.

Le filtre ne juge pas une phrase sans chiffre. Un fait non numérique inventé n’est pas retiré par cette fonction.

## Budgets (NB1)

NB1, ici, est le frein écrit dans `server/llm_budget.py`, pas un montant copié dans le dépôt.

| Levier | Défaut si la variable est absente | Preuve |
|---|---|---|
| Jetons `fast` / `write` / `deep` / `judge` | 200 000 / 150 000 / 80 000 / 60 000 par jour | `server/llm_budget.py:32-37`, juge : `server/tests/test_llm_budget.py:108-113` |
| Dollars | pas de coupure | `server/llm_budget.py:227-238`, `server/tests/test_llm_budget.py:146-150` |
| Variable dollar | `NAVIGUIDE_LLM_DAILY_USD` | `server/llm_budget.py:44`, `server/llm_budget.py:251-264` |
| Ultra du chat | 10 appels / jour | `server/llm_budget.py:39-41` |
| Prix estimés / million (entrée, sortie) | fast 0,06 et 0,24 ; write 0,30 et 0,90 ; deep et judge 1,00 et 3,00 | `server/llm_budget.py:108-114` |

Les commentaires de `server/.env.example:11-13` (2 000 000, 500 000, 100 000) ne sont pas les défauts du code, et ils sont commentés. Les décommenter changerait les plafonds : **à vérifier** avant de le faire.

Au plafond, ou si le mode interdit l’appel : aucun réseau, la cascade rend `source=budget` (`server/llm_budget.py:251-255`).

## Mode à la demande

Défaut `on-demand` (`server/llm_budget.py:46-62`). `off` ne paie jamais. `on-demand` paie sur une action au premier plan, pas en arrière-plan (`server/llm_budget.py:97-106`). `all` est explicite. Test : `server/tests/test_llm_budget.py:83-99`.

Exception écrite : `deferred_demand()` autorise le palier `write` en arrière-plan tant que le mode n’est pas `off` (`server/llm_budget.py:83-88`).

## Tavily, sans bouton

Aucun fichier `src/**/*.jsx` ne contient « Tavily ». Le sac `ici` du client est décrit « No chat, no Tavily » (`src/hooks/useIciDossier.js:157`), couvert par `src/utils/recetteAg.test.js:108`.

La veille est un travail serveur, activé par défaut (`NAVIGUIDE_TAVILY_WATCH=1`) ; `NAVIGUIDE_TAVILY_WATCH=0` la désactive (`server/escale_watch.py:100-102`). Un réglage enregistré sur le serveur prend le dessus sur cette valeur par défaut. Elle ne couvre que la fenêtre J−10 → J+2 (`server/escale_watch.py:32-33`), au plus deux tours, questions déjà écrites (`server/escale_watch.py:39-50`), résumé Lightning en une phrase (`server/escale_watch.py:54-58`). Plafonds : 6 recherches / jour (`server/escale_watch.py:50`), 80 crédits Tavily / jour (`server/llm_budget.py:539-548`). Conditions d’utilisation Tavily : **à vérifier** ([../DATA_SOURCES.md](../DATA_SOURCES.md)).

## Données envoyées dans les prompts

Constructeurs lus :

- Journal : la question tapée et un JSON de faits d’expédition (escales, ZEE, AMP, météo, science, veilles, polaire, ordres, revue, câbles). Le constructeur n’ajoute pas de compte, d’e-mail ni de nom de visiteur (`server/logbook_chat.py:1005-1029`).
- Veille : nom de port et date dans un modèle fixe (`server/escale_watch.py:42-46`, `server/escale_watch.py:132-136`).
- La cascade envoie les chaînes `system` et `user` qu’on lui donne (`server/story_cascade.py:1519-1535`). Elle n’appelle pas Tavily (`server/story_cascade.py:1531-1535`, test `server/tests/test_story_cascade.py:60-70`).

La question du journal part telle qu’elle est tapée. Un inventaire de chaque appelant de `cascade_text` n’est pas dans cette fiche : **à vérifier**.

## AI Act

Le dépôt ne contient pas d’évaluation de conformité. L’application se dit inutilisable comme carte officielle (`../../README.md:10`, `README.md:52`, `src/i18n/fr.js:334`). Une qualification « pas de haut risque » n’est pas un texte du code : **à vérifier**.

Articles 50(1) et 50(2), renvoi #566 : le checkout montre un libellé « Contenu généré par IA (modèle : {model}) » / « AI-generated content (model: {model}) » (`src/i18n/fr.js:588`, `src/i18n/en.js:588`), l’attribut `data-ai-generated` (`src/components/LlmSourceBadge.jsx:22-29`), et `ai_generated` / `generated_at` (`server/ai_transparency.py:104-118`). Le numéro #566 n’est pas cité dans l’arbre. Le texte de l’issue, et le rattachement aux deux alinéas, sont **à vérifier**.

Filigrane : aucun `watermark` ni « filigrane » dans le simulateur. Le dépôt ne dit pas si le fournisseur en pose un. Question ouverte au fournisseur : **à vérifier**.

Article 4 (culture de l’IA) : pas de module ni de registre de formation dans ce dépôt. **à vérifier**.

## Limites

- Le filtre retire des phrases à chiffres inconnus ; il ne vérifie pas le reste (`server/story_cascade.py:368-388`).
- Après échec des fournisseurs, le texte local peut s’afficher avec `source=rules` (`server/story_cascade.py:1513-1516`). Ce n’est pas un texte de modèle (`server/ai_transparency.py:18`).
- Thinking est coupé sur l’appel Token Factory (`server/story_cascade.py:1046-1058`).
- Ce n’est pas une carte marine (`../../README.md:10`).
- Les plafonds et les identifiants se changent par l’environnement (`server/llm_budget.py:174-181`).
- Sans `NAVIGUIDE_LLM_DAILY_USD`, il n’y a pas de coupure en dollars (`server/llm_budget.py:227-228`).
- La veille Tavily est **activée par défaut** (`NAVIGUIDE_TAVILY_WATCH=1`, `server/escale_watch.py:94-102`).

Lien REDTEAM : aucun `evals/redteam/` ni `docs/security/REDTEAM_2026-10.md` sur cette branche. **à vérifier**.

## English

The tables above are the evidence. By default, Token Factory uses `api.tokenfactory.nebius.com` (EU) for Lightning (`fast`, overridden by `NAVIGUIDE_TF_BASE`), Nano and Super VL (`nano`/`write`, overridden by `NAVIGUIDE_TF_BASE_EU`), and Ultra (`deep`/`judge`, overridden by `NAVIGUIDE_TF_BASE_ULTRA`). `eu-north1` and `devpost/nebius_futur.md` are **à vérifier**.

Cascade: SQLite cache, then Token Factory (on `fast`, an empty body, HTTP ≥ 500, or timeout gets one retry with Super; `nano` retries once with Lightning after any Token Factory failure), then NIM, OpenRouter, Claude, then `rules` if a fallback string was given. After a Token Factory timeout, non-Nemotron providers remain enabled by default; `NAVIGUIDE_LLM_TIMEOUT_FALLBACK=0` disables them. `filter_numbers` runs on each of those texts.

Budgets (NB1): daily token caps in `server/llm_budget.py:32-37`. A missing `NAVIGUIDE_LLM_DAILY_USD` does not cut spending. Default mode is `on-demand`.

Tavily runs at runtime from the logbook chat: each question sent with **Send** triggers one Tavily search about a port (`server/port_web_context.py`, on by default, `NAVIGUIDE_PORT_WEB=0` turns it off); links are shown under **Web sources (Tavily)**. The separate stop watch runs on the server by default (`NAVIGUIDE_TAVILY_WATCH=1`; set it to `0` to disable), for stops from ten days before arrival to two days after, at most two rounds. A saved server setting takes precedence over the environment default. Terms of use: **à vérifier**.

Prompts cited here carry the typed logbook question plus expedition facts, or a port name and a date. Those builders do not add an account, an email, or a visitor name. A full caller inventory is **à vérifier**.

AI Act: there is no conformity file in the repo. The product says it is not for navigation. The high-risk classification is **à vérifier**. The visible disclosure is the “AI-generated content” label, `data-ai-generated`, and `generated_at`. Issue #566 is not named in the tree: **à vérifier**. No watermark string: **à vérifier** with the provider. No AI-literacy record (article 4): **à vérifier**.

REDTEAM link: the report and the `evals/redteam/` tree are not on this branch. **à vérifier**.
