"""Film et horloge, hors de la file du briefing.

Le processus :8010 est occupé par /ici. nginx envoie /voyage/official/film
et /voyage/official/clock à :8011. Le GET reste une lecture du snapshot.
Le POST du clic Rédigé appelle official_store.write_film_on_click ici :
sinon ce processus répond 405 et le clic n'atteint pas la chaîne.
"""
from __future__ import annotations

import inspect
import logging
import sys
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import Response

_DIR = Path(__file__).resolve().parent
if str(_DIR) not in sys.path:
    sys.path.insert(0, str(_DIR))

import official_store  # noqa: E402
from admin_guard import rate_limited  # noqa: E402

log = logging.getLogger("naviguide-film-front")
app = FastAPI()

# Même gabarit que le POST de :8010 : 12 / min / IP, 60 / min et 240 / h
# pour tout ce processus. Compteurs propres à :8011 (nginx n'envoie pas
# ce chemin à :8010). Pas de clé admin : le bouton public reste ouvert.
_film_write_limited = rate_limited("film-write", 12, 60.0, global_limit=60)
_film_write_hourly = rate_limited("film-write-hour", 10**9, 3600.0, global_limit=240)


def _serve_film(lang: str, seconds: int, style: str) -> dict:
    sig = inspect.signature(official_store.serve_film)
    kwargs = {"lang": lang, "seconds": seconds}
    if "style" in sig.parameters:
        kwargs["style"] = style
    return official_store.serve_film(**kwargs)


@app.get("/voyage/official/film")
def get_official_film(
    lang: str = Query("fr"),
    seconds: int = Query(0, ge=0, le=300),
    style: str = Query("raw"),
):
    try:
        out = _serve_film(lang, seconds, style)
    except Exception as exc:
        log.exception("GET /voyage/official/film")
        official_store.nudge_fill_process()
        return official_store.preparing_payload("film", {
            "chapters": [], "source": "rules", "chars": 0,
            "targetSeconds": seconds, "hasWritten": False,
            "reason": f"film indisponible: {exc}",
        })
    if out.get("status") == official_store.PREPARING:
        official_store.nudge_fill_process()
    return out


@app.post(
    "/voyage/official/film",
    dependencies=[Depends(_film_write_limited), Depends(_film_write_hourly)],
)
async def post_official_film(
    lang: str = Query("fr"),
    seconds: int = Query(150, ge=0, le=300),
):
    """Clic Rédigé : la chaîne déjà écrite, jamais au GET.

    Durées acceptées : 0, 150 et 180. Toute autre valeur répond 422, comme
    sur :8010, pour ne pas ranger un rédigé sous une clé que le GET ne relit pas.
    """
    if int(seconds) not in official_store.FILM_VARIANT_SECONDS:
        raise HTTPException(422, "unsupported film duration")
    try:
        out = await official_store.start_film_write(lang=lang, seconds=seconds)
    except Exception as exc:
        log.exception("POST /voyage/official/film")
        official_store.nudge_fill_process()
        return official_store.preparing_payload("film", {
            "chapters": [], "source": "rules", "chars": 0,
            "targetSeconds": seconds, "hasWritten": False,
            "reason": f"film indisponible: {exc}",
        })
    if out.get("status") == official_store.PREPARING:
        official_store.nudge_fill_process()
    return out


@app.get("/voyage/official/clock")
def get_official_clock():
    try:
        raw = official_store.serve_clock_bytes()
    except Exception as exc:
        log.exception("GET /voyage/official/clock")
        official_store.nudge_fill_process()
        return official_store.preparing_payload("climo", {
            "reason": f"horloge indisponible: {exc}",
        })
    if raw:
        return Response(content=raw, media_type="application/json")
    official_store.nudge_fill_process()
    return official_store.preparing_payload("climo", {
        "reason": "horloge officielle en préparation",
    })
