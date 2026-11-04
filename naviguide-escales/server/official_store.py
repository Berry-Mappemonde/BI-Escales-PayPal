"""Stock persistant du voyage officiel — une interface, deux dos (D5').

Lecture/écriture des six familles (moments, film, eta, climo, ici, plan_review).
Clé : (route officielle, t0, date des données). Une entrée porte un horodatage ;
le remplacement est atomique. Derrière : MongoDB si SIMULATOR_MONGO_URL est posé
(base naviguide_simulator), fichiers sur disque sinon.

Aucune donnée n'est inventée : `put` n'accepte que le résultat d'un vrai calcul.
Une famille absente reste « en préparation ». Le travail de fond calcule hors
des requêtes. Aucun test ne se connecte à une vraie base.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import threading
import time
import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from longitude import delta_lon

log = logging.getLogger("naviguide-simulator.official-store")

FAMILIES = ("moments", "film", "eta", "climo", "ici", "plan_review")
FILM_VARIANT_SECONDS = (150, 180, 0)  # 2:30 / 3:00 / intégral ; 0 = sans plafond ; la première reste le repli
PREPARING = "preparing"
READY = "ready"
UNAVAILABLE = "unavailable"
# Clé film : VS1 (choix VL/Lightning ou repli, budget 2:30 / 3:00) invalide ed1.
# VB1 : cache de route ; absent, le récit ne change pas. Invalide vs1-rg10.
# vs1-ed2 : le rédigé resservi garde source, reviewedBy et model. Invalide vs1-vb1.
# Le remplisseur recalcule la famille film, pas les perles. Pas un WARM monde.
# Pas de kind de moment nouveau : moments reste rg4.
# ici : am1a (contrat AMP `source` ; sac pré-AM1A ignoré).
# plan_review : rc54 — marques recollées sur les milles d'itinéraire
# (Mata-Utu / Nouméa plus sur le retour atlantique). Pas de repli sur rc44.
# clock (famille climo) : départ après la jambe terrestre, séjour des ports.
# moments suit cette horloge. Le remplisseur recalcule ; pas un parcours complet.
FILM_SCRIPT_REV = "vs1-ed2"
WRITTEN_SOURCE = "nemotron-super"
REVIEWED_SOURCE = "nemotron-super-reviewed-ultra"
REVIEWED_BY_ULTRA = "nemotron-ultra"
MOMENTS_REV = "rg4-depart"
CLOCK_REV = "depart-land"
ICI_REV = "am1a"
PLAN_REVIEW_REV = "rc54"
DB_NAME = "naviguide_simulator"
COLLECTION = "official_voyage"
# Par défaut, le stock disque vit DANS le checkout (server/voyage_data/, ignoré par git) : un agent qui teste
# dans son worktree ne peut plus écrire dans le stock du poste (27 sept. : l'agent RF2 y avait figé un journal
# sans événements, servi 14 h). Le poste pose NAVIGUIDE_OFFICIAL_STORE_DIR (ensure-dev.sh) → ~/.cache/naviguide/voyage-store.
DEFAULT_DISK = Path(__file__).resolve().parent / "voyage_data" / "official-store"
PERIOD_S = float(os.environ.get("NAVIGUIDE_OFFICIAL_STORE_PERIOD_S") or 6 * 3600)
ROUTE_NEAR_NM = 8.0

_LOCK = threading.RLock()
_INSTANCE: Optional["OfficialStore"] = None
_WORKER_STARTED = False
_FILM_FORCED = False
_REFRESH_LOCK = threading.Lock()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None = None) -> str:
    when = dt or _utc_now()
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _data_date(now: datetime | None = None) -> str:
    when = now or _utc_now()
    return when.astimezone(timezone.utc).strftime("%Y-%m-%d")


def route_fingerprint(voy: dict | None) -> str:
    """Empreinte stable de la route officielle (points + marques + t0)."""
    voy = voy or {}
    raw = json.dumps(
        {
            "t0": voy.get("t0") or "",
            "n": len(voy.get("points") or []),
            "rev": voy.get("routeRev") or 0,
            "marks": [
                (m.get("name"), round(float(m.get("nm") or 0), 3))
                for m in (voy.get("marks") or [])
                if isinstance(m, dict)
            ],
            "first": (voy.get("points") or [{}])[0].get("lat") if voy.get("points") else None,
            "last": (voy.get("points") or [{}])[-1].get("lat") if voy.get("points") else None,
        },
        ensure_ascii=False, separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def make_key(route_id: str, t0: str, data_date: str) -> str:
    return f"{route_id}:{t0}:{data_date}"


def _is_data_date(value: str) -> bool:
    return (
        len(value) == 10
        and value[4] == "-"
        and value[7] == "-"
        and value[:4].isdigit()
        and value[5:7].isdigit()
        and value[8:10].isdigit()
    )


def parse_key(key: str) -> tuple[str, str, str, Optional[str]]:
    """Décompose `route:t0:data_date[:rev]` — t0 peut contenir des `:`."""
    if not key or ":" not in key:
        raise ValueError(f"clé invalide: {key}")
    suffix = None
    rest = key
    last = rest.rsplit(":", 1)
    if len(last) == 2 and not _is_data_date(last[1]):
        suffix = last[1]
        rest = last[0]
    if ":" not in rest:
        raise ValueError(f"clé invalide: {key}")
    route_and_t0, data_date = rest.rsplit(":", 1)
    if not _is_data_date(data_date) or ":" not in route_and_t0:
        raise ValueError(f"clé invalide: {key}")
    route_id, t0 = route_and_t0.split(":", 1)
    return route_id, t0, data_date, suffix


def _stamp(hit: Optional[dict]) -> dict:
    """storedAt / dataDate à recopier dans une réponse HTTP."""
    if not hit:
        return {}
    out: dict[str, str] = {}
    stored = hit.get("storedAt")
    if stored:
        out["storedAt"] = stored
    date = hit.get("dataDate")
    if not date:
        try:
            date = parse_key(str(hit.get("key") or ""))[2]
        except (TypeError, ValueError):
            date = None
    if date:
        out["dataDate"] = date
    return out


def preparing_payload(family: str, extra: Optional[dict] = None) -> dict:
    """Réponse honnête — jamais un 500, jamais un calcul. Le client sait déjà
    afficher un journal vide / un film pending / une fourchette absente."""
    body = {"status": PREPARING, "reason": "en préparation", "family": family}
    if extra:
        body.update(extra)
    return body


def worker_enabled() -> bool:
    raw = (os.environ.get("NAVIGUIDE_OFFICIAL_WORKER") or "1").strip().lower()
    if raw in ("0", "false", "no"):
        return False
    if os.environ.get("PYTEST_CURRENT_TEST") and raw != "force":
        return False
    return True


def _store_rev_relaxed() -> bool:
    """Sans remplisseur (CI, stock figé) : une ancienne rev film/moments/ici/climo reste joignable.

    La clé `…:rg4` n'existe pas encore dans l'archive gelée ; sans ça, GET
    /film, /moments, /ici et /clock restent « en préparation » et Revoir reste grisé.
    Sur le poste le remplisseur tourne (WORKER≠0) : pas de repli, il recalcule.
    plan_review n'est pas dans ce repli : un snapshot Halifax /
    Saint-Pierre → Papeete ne doit plus sortir ready.
    """
    raw = (os.environ.get("NAVIGUIDE_OFFICIAL_WORKER") or "1").strip().lower()
    return raw in ("0", "false", "no")


def disk_root() -> Path:
    env = (os.environ.get("NAVIGUIDE_OFFICIAL_STORE_DIR") or "").strip()
    if env:
        return Path(env)
    if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("CI"):
        return Path(tempfile.mkdtemp(prefix="naviguide-voyage-store-"))
    return DEFAULT_DISK


# ── dos disque ───────────────────────────────────────────────────────────────

class DiskBackend:
    def __init__(self, root: Optional[Path] = None):
        self.root = Path(root) if root is not None else disk_root()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str, family: str) -> Path:
        safe = key.replace("/", "_").replace("\\", "_").replace(":", "_")
        d = self.root / safe
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{family}.json"

    def get(self, key: str, family: str) -> Optional[dict]:
        dest = self._path(key, family)
        if not dest.exists():
            return None
        try:
            return json.loads(dest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("stock disque illisible %s/%s : %s", key, family, exc)
            return None

    def stamp(self, key: str, family: str) -> Optional[str]:
        """Empreinte de l'entrée telle qu'elle est sur disque (mtime + taille) : un autre PROCESSUS
        (le remplisseur, RC18) a pu la remplacer — l'API relit alors au lieu de servir sa copie mémoire."""
        dest = self._path(key, family)
        try:
            st = dest.stat()
        except OSError:
            return None
        return f"{st.st_mtime_ns}:{st.st_size}"

    def list_family(self, family: str) -> list[tuple[str, dict]]:
        out: list[tuple[str, dict]] = []
        if not self.root.exists():
            return out
        for folder in self.root.iterdir():
            dest = folder / f"{family}.json"
            if not dest.is_file():
                continue
            try:
                doc = json.loads(dest.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                log.warning("stock disque illisible %s : %s", dest, exc)
                continue
            if not isinstance(doc, dict) or not doc.get("key"):
                continue
            out.append((str(doc["key"]), doc))
        return out

    def put(self, key: str, family: str, doc: dict) -> dict:
        dest = self._path(key, family)
        tmp = dest.with_suffix(".tmp")
        payload = json.dumps(doc, ensure_ascii=False, indent=2)
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(dest)
        return doc


# ── dos Mongo (client injecté en tests — jamais une vraie base) ───────────────

class MongoBackend:
    """Dos MongoDB : base naviguide_simulator uniquement.

    `client` injecté (mongomock / faux client). En production, pymongo à partir
    de SIMULATOR_MONGO_URL — jamais MONGO_URL_LOCAL ni mongo.env.
    """

    def __init__(self, client: Any, db_name: str = DB_NAME):
        self._col = client[db_name][COLLECTION]

    def get(self, key: str, family: str) -> Optional[dict]:
        doc = self._col.find_one({"_id": f"{key}:{family}"})
        if not doc:
            return None
        return {
            "key": doc.get("key") or key,
            "family": doc.get("family") or family,
            "storedAt": doc.get("storedAt"),
            "payload": doc.get("payload"),
        }

    def stamp(self, key: str, family: str) -> Optional[str]:
        """storedAt de l'entrée (requête légère par _id) : change quand le remplisseur a réécrit."""
        try:
            doc = self._col.find_one({"_id": f"{key}:{family}"}, {"storedAt": 1})
        except TypeError:   # faux client de test sans projection
            doc = self._col.find_one({"_id": f"{key}:{family}"})
        if not doc:
            return None
        return str(doc.get("storedAt") or "")

    def list_family(self, family: str) -> list[tuple[str, dict]]:
        out: list[tuple[str, dict]] = []
        for doc in self._col.find({"family": family}):
            key = (doc or {}).get("key")
            if not key:
                continue
            out.append((str(key), {
                "key": key,
                "family": doc.get("family") or family,
                "storedAt": doc.get("storedAt"),
                "payload": doc.get("payload"),
            }))
        return out

    def put(self, key: str, family: str, doc: dict) -> dict:
        stored = {
            "_id": f"{key}:{family}",
            "key": key,
            "family": family,
            "storedAt": doc.get("storedAt"),
            "payload": doc.get("payload"),
        }
        self._col.replace_one({"_id": stored["_id"]}, stored, upsert=True)
        return {k: stored[k] for k in ("key", "family", "storedAt", "payload")}


def _mongo_client_from_url(url: str):
    from pymongo import MongoClient  # noqa: PLC0415
    return MongoClient(url, serverSelectionTimeoutMS=2000)


# ── interface unique ─────────────────────────────────────────────────────────

class OfficialStore:
    def __init__(self, backend: Any, *, now: Optional[Callable[[], datetime]] = None):
        self.backend = backend
        self._now = now or _utc_now
        self._mem: dict[tuple[str, str], dict] = {}
        self._stamps: dict[tuple[str, str], Optional[str]] = {}
        self._clock_bytes: Optional[bytes] = None
        self._clock_bytes_key: Optional[str] = None

    def current_key(self, voy: Optional[dict] = None, now: Optional[datetime] = None) -> str:
        voy = voy if voy is not None else _load_official()
        t0 = (voy or {}).get("t0") or ""
        return make_key(route_fingerprint(voy), t0, _data_date(now or self._now()))

    def family_key(
        self,
        family: str,
        voy: Optional[dict] = None,
        now: Optional[datetime] = None,
    ) -> str:
        """Clé de rangement : film, moments, ici et plan_review portent la révision du calcul."""
        base = self.current_key(voy, now)
        if family == "film":
            return f"{base}:{FILM_SCRIPT_REV}"
        if family == "moments":
            return f"{base}:{MOMENTS_REV}"
        if family == "ici":
            return f"{base}:{ICI_REV}"
        if family == "plan_review":
            return f"{base}:{PLAN_REVIEW_REV}"
        if family == "climo":
            return f"{base}:{CLOCK_REV}"
        return base

    def _with_date(self, hit: Optional[dict]) -> Optional[dict]:
        if not hit:
            return None
        out = dict(hit)
        if not out.get("dataDate"):
            try:
                out["dataDate"] = parse_key(str(out.get("key") or ""))[2]
            except (TypeError, ValueError):
                pass
        return out

    def _latest_hit(self, family: str, current: str) -> Optional[dict]:
        """Plus récente entrée même route + même t0 (minuit UTC / CI)."""
        try:
            route_id, t0, _, want_suf = parse_key(current)
        except ValueError:
            return None
        lister = getattr(self.backend, "list_family", None)
        if not callable(lister):
            return None
        best: Optional[tuple[tuple, str, dict]] = None
        for stored_key, doc in lister(family):
            try:
                r, t, date, suf = parse_key(stored_key)
            except ValueError:
                continue
            if r != route_id or t != t0:
                continue
            exact = (want_suf or None) == (suf or None)
            if not exact and not (family in {"film", "moments", "ici", "climo"} and _store_rev_relaxed()):
                continue
            rank = (1 if exact else 0, date)
            if best is None or rank > best[0]:
                best = (rank, stored_key, doc)
        if not best:
            return None
        rank, stored_key, doc = best
        out = dict(doc)
        out["key"] = stored_key
        out["dataDate"] = rank[1]
        return out

    def get(self, family: str, key: Optional[str] = None) -> Optional[dict]:
        if family not in FAMILIES:
            raise ValueError(f"famille inconnue: {family}")
        dest = key if key is not None else self.family_key(family)
        with _LOCK:
            hit = self._cached(dest, family)
            if hit is not None:
                return self._with_date(hit)
            if key is not None:
                return None
            found = self._latest_hit(family, dest)
            if found is not None and found.get("key"):
                self._remember(found["key"], family, found)
            return self._with_date(found)

    def _stamp(self, key: str, family: str) -> Optional[str]:
        stamper = getattr(self.backend, "stamp", None)
        if not callable(stamper):
            return None
        try:
            return stamper(key, family)
        except Exception:
            return None

    def _remember(self, key: str, family: str, hit: dict) -> None:
        self._mem[(key, family)] = hit
        self._stamps[(key, family)] = self._stamp(key, family)

    def _cached(self, key: str, family: str) -> Optional[dict]:
        """Copie mémoire, relue si le dos a changé sous nos pieds (le remplisseur est un autre processus, RC18)."""
        stamp = self._stamp(key, family)
        hit = self._mem.get((key, family))
        if hit is not None and self._stamps.get((key, family)) == stamp:
            return hit
        hit = self.backend.get(key, family)
        if hit is None:
            self._mem.pop((key, family), None)
            self._stamps.pop((key, family), None)
            return None
        self._mem[(key, family)] = hit
        self._stamps[(key, family)] = stamp
        if family == "climo":
            self._clock_bytes = None
            self._clock_bytes_key = None
        return hit

    def put(self, family: str, payload: dict, key: Optional[str] = None) -> dict:
        if family not in FAMILIES:
            raise ValueError(f"famille inconnue: {family}")
        if payload is None:
            raise ValueError("payload vide — une famille non calculée reste en préparation")
        dest_key = key if key is not None else self.family_key(family)
        doc = {
            "key": dest_key,
            "family": family,
            "storedAt": _iso(self._now()),
            "payload": payload,
        }
        with _LOCK:
            stored = self.backend.put(dest_key, family, doc)
            self._remember(dest_key, family, stored)
            if family == "climo":
                self._clock_bytes = None
                self._clock_bytes_key = None
            return stored

    def status(self, key: Optional[str] = None) -> dict:
        dest = key if key is not None else self.current_key()
        families = {}
        for name in FAMILIES:
            if key is not None:
                hit = self.get(name, key)
            else:
                hit = self.get(name)
            families[name] = {
                "status": READY if hit and hit.get("payload") is not None else PREPARING,
                "storedAt": (hit or {}).get("storedAt"),
                "dataDate": (hit or {}).get("dataDate"),
                "key": (hit or {}).get("key"),
            }
        return {"key": dest, "families": families}


def get_store(*, reset: bool = False) -> OfficialStore:
    """Dos choisi tout seul : Mongo si SIMULATOR_MONGO_URL, disque sinon."""
    global _INSTANCE
    if reset:
        _INSTANCE = None
    if _INSTANCE is not None:
        return _INSTANCE
    url = (os.environ.get("SIMULATOR_MONGO_URL") or "").strip()
    if url:
        _INSTANCE = OfficialStore(MongoBackend(_mongo_client_from_url(url)))
    else:
        _INSTANCE = OfficialStore(DiskBackend())
    return _INSTANCE


def reset_store() -> None:
    """Tests : oublier le singleton (nouveau répertoire / faux client)."""
    global _INSTANCE
    _INSTANCE = None
    # Les états du job Rédigé async sont au niveau module : un test ne doit
    # pas hériter de l'échec ou de la tâche d'un test précédent.
    _FILM_WRITE_FAILED.clear()
    _FILM_WRITE_TASKS.clear()


def get(family: str, key: Optional[str] = None) -> Optional[dict]:
    return get_store().get(family, key)


def put(family: str, payload: dict, key: Optional[str] = None) -> dict:
    return get_store().put(family, payload, key)


def family_status() -> dict:
    return get_store().status()


def payload_of(family: str) -> Optional[dict]:
    hit = get(family)
    if not hit:
        return None
    body = hit.get("payload")
    return body if isinstance(body, dict) else None


def _zee_enter_count(moments: list | None) -> int:
    n = 0
    for row in moments or []:
        if not isinstance(row, dict):
            continue
        for change in row.get("changes") or []:
            if not isinstance(change, dict):
                continue
            kind = str(change.get("kind") or "")
            title = str(change.get("title") or "")
            if kind == "zee-enter" or "économique exclusive" in title.lower() or "exclusive economic" in title.lower():
                n += 1
        moment = row.get("moment") if isinstance(row.get("moment"), dict) else {}
        here = moment.get("here") if isinstance(moment.get("here"), dict) else {}
        zee = here.get("zee") if isinstance(here.get("zee"), dict) else {}
        name = str((zee or {}).get("name") or "")
        if "économique exclusive" in name.lower() or "exclusive economic" in name.lower():
            n += 1
    return n


def official_journal_moments() -> list[dict]:
    """Journal officiel pour le film — lecture seule, jamais un seed.

    L'entrée du jour peut être une grille horloge (grib / chat) sans zee-enter.
    On relit alors la dernière entrée riche, même route et même t0, qui porte
    les titres FR du journal (Zone économique exclusive espagnole / …).
    """
    current = payload_of("moments")
    rows = list((current or {}).get("moments") or []) if isinstance(current, dict) else []
    if _zee_enter_count(rows) > 0:
        return rows
    st = get_store()
    try:
        dest = st.family_key("moments")
        route_id, t0, _, _ = parse_key(dest)
    except Exception:
        return rows
    lister = getattr(st.backend, "list_family", None)
    if not callable(lister):
        return rows
    best, best_date = rows, ""
    for stored_key, doc in lister("moments"):
        try:
            r, t, date, _suf = parse_key(stored_key)
        except ValueError:
            continue
        if r != route_id or t != t0:
            continue
        payload = doc.get("payload") if isinstance(doc, dict) else None
        cand = list((payload or {}).get("moments") or []) if isinstance(payload, dict) else []
        if _zee_enter_count(cand) <= 0:
            continue
        if date > best_date:
            best, best_date = cand, date
    return best


def _payload_has_chapters(payload: Optional[dict]) -> bool:
    """Vrai si un plan FR, EN ou une variante a au moins un chapitre."""
    if not isinstance(payload, dict):
        return False
    variants = payload.get("variants") if isinstance(payload.get("variants"), dict) else {}
    for by_secs in variants.values():
        if not isinstance(by_secs, dict):
            continue
        for plan in by_secs.values():
            if isinstance(plan, dict) and (plan.get("chapters") or []):
                return True
    for key in ("fr", "en", "default"):
        plan = payload.get(key)
        if isinstance(plan, dict) and (plan.get("chapters") or []):
            return True
    return False


def _patch_air_on_film(payload: dict, voy: Optional[dict]) -> dict:
    """Ajoute les phrases d'avion manquantes. Le reste du script n'est pas réécrit."""
    out = dict(payload)
    variants = out.get("variants") if isinstance(out.get("variants"), dict) else None
    if variants:
        patched: dict = {}
        for lang, by_secs in variants.items():
            if not isinstance(by_secs, dict):
                patched[lang] = by_secs
                continue
            lg = str(lang)[:2].lower() or "fr"
            patched[lang] = {
                sec: _apply_air_sentences(plan, lg, voy) if isinstance(plan, dict) else plan
                for sec, plan in by_secs.items()
            }
        out["variants"] = patched
        for key, lg in (("fr", "fr"), ("en", "en"), ("default", "fr")):
            picked = (patched.get(lg) or patched.get("fr") or {})
            if not isinstance(picked, dict):
                continue
            plan = picked.get("150") or picked.get("0") or next(iter(picked.values()), None)
            if isinstance(plan, dict) and (plan.get("chapters") or []):
                out[key] = plan
    for key, lg in (("fr", "fr"), ("en", "en"), ("default", "fr")):
        plan = out.get(key)
        if isinstance(plan, dict) and (plan.get("chapters") or []):
            out[key] = _apply_air_sentences(plan, lg, voy)
    return out


def _newest_film_hit() -> Optional[dict]:
    """Dernier script qui a des chapitres, même révision ancienne.

    La révision du checkout (vs1, rc55…) met du temps à s'écrire. Tant qu'elle
    n'est pas là, Revoir joue le dernier film complet au lieu de rester
    « en préparation ».
    """
    st = get_store()
    voy = _load_official()
    try:
        route_id, t0, _, _suf = parse_key(st.family_key("film", voy))
    except ValueError:
        return None
    lister = getattr(st.backend, "list_family", None)
    if not callable(lister):
        return None
    best: Optional[dict] = None
    best_date = ""
    for stored_key, doc in lister("film"):
        try:
            route, stamp, date, _suf = parse_key(stored_key)
        except ValueError:
            continue
        if route != route_id or stamp != t0:
            continue
        payload = doc.get("payload") if isinstance(doc, dict) else None
        if not _payload_has_chapters(payload):
            continue
        if best is None or date > best_date:
            hit = dict(doc)
            hit["key"] = stored_key
            hit["dataDate"] = date
            best, best_date = hit, date
    return best


def _film_chapters_blob(payload: Optional[dict]) -> str:
    if not isinstance(payload, dict):
        return ""
    parts: list[str] = []
    for key in ("fr", "default", "en"):
        plan = payload.get(key)
        if not isinstance(plan, dict):
            continue
        for ch in plan.get("chapters") or []:
            if isinstance(ch, dict):
                parts.append(str(ch.get("text") or ""))
    return " ".join(parts)


def _itinerary_marks() -> list:
    """Cayenne / Halifax de l'itinéraire Berry (route.geojson), escales ou intermédiaires.

    Halifax est un waypoint `intermediate` : `official_itinerary_body` ne le met
    pas dans les marques d'escales — ce n'est pas une invention, le point est
    dans le GeoJSON officiel.
    """
    try:
        from voyage_api import _ROUTE_GEOJSON  # noqa: PLC0415
        fc = json.loads(_ROUTE_GEOJSON.read_text(encoding="utf-8"))
    except Exception:
        return []
    out: list[dict] = []
    for feat in fc.get("features") or []:
        geom = (feat or {}).get("geometry") or {}
        props = (feat or {}).get("properties") or {}
        if geom.get("type") != "Point":
            continue
        name = str(props.get("name") or "")
        low = name.lower()
        if "cayenne" not in low and "halifax" not in low:
            continue
        coords = geom.get("coordinates") or []
        if len(coords) < 2:
            continue
        try:
            out.append({
                "name": name,
                "lon": float(coords[0]),
                "lat": float(coords[1]),
            })
        except (TypeError, ValueError):
            continue
    return out


# Port de Saint-Pierre (même point que la route officielle).
SAINT_PIERRE_LAT = 46.7761
SAINT_PIERRE_LON = -56.1628


def _name_has(name: str, needle: str) -> bool:
    return needle in (name or "").lower()


def _plan_blob(marks: list, plan: Optional[dict] = None) -> str:
    parts = [str(m.get("name") or "") for m in marks if isinstance(m, dict)]
    if isinstance(plan, dict):
        for ch in plan.get("chapters") or []:
            if isinstance(ch, dict):
                parts.append(" ".join(str(ch.get(k) or "") for k in ("fromName", "toName", "text")))
    return " ".join(parts).lower()


def plan_includes_halifax(marks: list, plan: Optional[dict] = None) -> bool:
    """Halifax entre dans les marques seulement si le plan a l'épisode (Halifax ou Saint-Pierre)."""
    blob = _plan_blob(marks, plan)
    return "halifax" in blob or "saint-pierre" in blob or "miquelon" in blob


def repair_call_marks(marks: list, plan: Optional[dict] = None) -> list:
    """Saint-Pierre au port réel, Halifax si le plan l'inclut, Cayenne sans doublon."""
    out: list[dict] = []
    seen_cayenne = False
    named = [m for m in (marks or []) if isinstance(m, dict)]
    for raw in named:
        mark = dict(raw)
        name = str(mark.get("name") or "")
        low = name.lower()
        if "saint-pierre" in low or "miquelon" in low:
            mark["lat"] = SAINT_PIERRE_LAT
            mark["lon"] = SAINT_PIERRE_LON
        if _name_has(name, "cayenne"):
            if seen_cayenne:
                continue
            seen_cayenne = True
        out.append(mark)
    if plan_includes_halifax(out, plan) and not any(_name_has(m.get("name") or "", "halifax") for m in out):
        for stop in _itinerary_marks():
            if _name_has(stop.get("name") or "", "halifax"):
                out.append(dict(stop))
                break
    return out


def _voy_stored_marks(voy: Optional[dict]) -> list:
    voy = voy or {}
    marks = [m for m in (voy.get("marks") or []) if isinstance(m, dict)]
    clock = voy.get("clock") if isinstance(voy.get("clock"), dict) else None
    if clock:
        marks.extend(m for m in (clock.get("marks") or []) if isinstance(m, dict))
    else:
        stored = stored_clock()
        if stored:
            marks.extend(m for m in (stored.get("marks") or []) if isinstance(m, dict))
    return repair_call_marks(marks, voy if isinstance(voy, dict) else None)


def _name_is_cayenne(name: str) -> bool:
    return "cayenne" in (name or "").lower()


def _marks_have_cayenne(marks: list) -> bool:
    return any(_name_is_cayenne(m.get("name") or "") for m in marks if isinstance(m, dict))


def _voy_air_marks(voy: Optional[dict], plan: Optional[dict] = None) -> list:
    """Marques du voyage. Halifax n'est ajouté que si le plan a l'épisode."""
    marks = repair_call_marks(_voy_stored_marks(voy), plan)
    if not _marks_have_cayenne(marks):
        blob = _plan_blob([], plan)
        if "cayenne" in blob or "guyane" in blob:
            marks = repair_call_marks(marks + _itinerary_marks(), plan)
    elif plan_includes_halifax(marks, plan) and not any(
        _name_has(m.get("name") or "", "halifax") for m in marks if isinstance(m, dict)
    ):
        halifax = [m for m in _itinerary_marks() if _name_has(m.get("name") or "", "halifax")]
        marks = repair_call_marks(marks + halifax, plan)
    return marks


def _plan_char_count(plan: Optional[dict]) -> int:
    if not isinstance(plan, dict):
        return 0
    n = plan.get("chars")
    if isinstance(n, (int, float)) and int(n) > 0:
        return int(n)
    return sum(
        len(str(c.get("text") or ""))
        for c in (plan.get("chapters") or [])
        if isinstance(c, dict)
    )


def _with_film_estimate(plan: Optional[dict]) -> dict:
    from film_script import film_estimated_seconds, fix_en_waters_casing  # noqa: PLC0415

    if not isinstance(plan, dict):
        return {}
    out = dict(plan)
    chapters = []
    for ch in out.get("chapters") or []:
        if not isinstance(ch, dict):
            chapters.append(ch)
            continue
        chapters.append({**ch, "text": fix_en_waters_casing(ch.get("text") or "")})
    if chapters:
        out["chapters"] = chapters
    chars = _plan_char_count(out)
    out["chars"] = chars
    out["estimatedSeconds"] = film_estimated_seconds(chars)
    return out


def _variants_estimates(variants: Optional[dict]) -> dict:
    out: dict[str, dict[str, dict]] = {}
    if not isinstance(variants, dict):
        return out
    for lang, by_secs in variants.items():
        if not isinstance(by_secs, dict):
            continue
        rows: dict[str, dict] = {}
        for key, plan in by_secs.items():
            annotated = _with_film_estimate(plan if isinstance(plan, dict) else None)
            rows[str(key)] = {
                "chars": int(annotated.get("chars") or 0),
                "estimatedSeconds": int(annotated.get("estimatedSeconds") or 0),
            }
        if rows:
            out[str(lang)] = rows
    return out


def _pick_variant_key(keys: list[int], want: int) -> Optional[int]:
    """0 / absent = intégral (clé 0 si stockée, sinon la plus longue)."""
    if not keys:
        return None
    if want <= 0:
        return 0 if 0 in keys else max(keys)
    if want in keys:
        return want
    positive = [k for k in keys if k > 0]
    pool = positive or keys
    return min(pool, key=lambda k: (abs(k - want), k))


def _apply_air_sentences(plan: dict, lang: str, voy: Optional[dict]) -> dict:
    """Garde l'aller/retour avion si la route officielle a la paire — pas d'invention."""
    from film_script import _ensure_air_sentences  # noqa: PLC0415

    if not isinstance(plan, dict):
        return plan
    chapters = [dict(c) for c in (plan.get("chapters") or []) if isinstance(c, dict)]
    if not chapters:
        return plan
    _ensure_air_sentences(
        chapters, marks=_voy_air_marks(voy, plan), moments=None, lang=lang,
    )
    out = dict(plan)
    out["chapters"] = chapters
    return out


def film_snapshot_stale(payload: Optional[dict], voy: Optional[dict] = None) -> bool:
    """True si la route a Cayenne↔Halifax mais le snapshot ne dit pas l'avion.

    Pas d'invention : sans la paire, le snapshot n'est jamais « périmé ».
    """
    from film_script import _AIR_BACK_RE, _AIR_OUT_RE, _route_has_air_pair  # noqa: PLC0415

    if not _route_has_air_pair(_voy_air_marks(voy, payload.get("fr") if isinstance(payload, dict) else None)):
        return False
    blob = _film_chapters_blob(payload)
    if not blob.strip():
        return True
    return not (_AIR_OUT_RE.search(blob) and _AIR_BACK_RE.search(blob))


def stored_clock() -> Optional[dict]:
    body = payload_of("climo")
    clock = (body or {}).get("clock")
    return clock if isinstance(clock, dict) and clock.get("t0") else None


def serve_clock_bytes() -> Optional[bytes]:
    """Horloge déjà sérialisée — GET /clock sans recalcul ni ré-encodage."""
    st = get_store()
    hit = st.get("climo")
    clock = ((hit or {}).get("payload") or {}).get("clock") if hit else None
    if not isinstance(clock, dict) or not clock.get("t0"):
        return None
    # La clé seule ne suffit pas : une horloge recalculée sous la même clé (remplisseur, réparation à la main)
    # resterait invisible jusqu'au redémarrage — l'empreinte porte aussi le storedAt (29 sept.).
    key = f"{(hit or {}).get('key') or st.current_key()}@{(hit or {}).get('storedAt') or ''}"
    with _LOCK:
        if st._clock_bytes is not None and st._clock_bytes_key == key:
            return st._clock_bytes
        body = dict(clock)
        body.update(_stamp(hit))
        raw = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        st._clock_bytes = raw
        st._clock_bytes_key = key
        return raw


# ── proximité route officielle (sac ici) ─────────────────────────────────────

def _haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    from isochrone import haversine  # noqa: PLC0415
    return haversine(lat1, lon1, lat2, lon1 + delta_lon(lon1, lon2))


def _load_official() -> Optional[dict]:
    from voyage_clock import OFFICIAL_VOYAGE_ID  # noqa: PLC0415
    from voyage_store import load_voyage  # noqa: PLC0415
    return load_voyage(OFFICIAL_VOYAGE_ID)


_ROUTE_SAMPLE: tuple[int, list[tuple[float, float]]] | None = None


def _route_sample(voy: dict, points: list) -> list[tuple[float, float]]:
    """Échantillon lat/lon du voyage déjà en mémoire. Reconstruit seulement si le voyage change."""
    global _ROUTE_SAMPLE
    key = id(voy)
    if _ROUTE_SAMPLE is not None and _ROUTE_SAMPLE[0] == key:
        return _ROUTE_SAMPLE[1]
    step = max(1, len(points) // 400)
    sample: list[tuple[float, float]] = []
    for p in points[::step]:
        try:
            sample.append((float(p["lat"]), float(p["lon"])))
        except (KeyError, TypeError, ValueError):
            continue
    _ROUTE_SAMPLE = (key, sample)
    return sample


def on_official_route(lat: float, lon: float, max_nm: float = ROUTE_NEAR_NM) -> bool:
    voy = _load_official()
    points = (voy or {}).get("points") or []
    if not points:
        return False
    for plat, plon in _route_sample(voy, points):
        if _haversine_nm(lat, lon, plat, plon) <= max_nm:
            return True
    return False


def _ici_bag_is_am1a(bag: dict) -> bool:
    """Le sac porte le contrat AM1A (clé `source` sur les AMP), pas un snapshot pré-polygone.

    Une liste `amp` vide est acceptée : un point océanique recalculé ne doit pas
    relancer le remplisseur en boucle. Un sac sans clé `amp`, ou dont une entrée
    n'a pas `source`, est pré-AM1A : on le laisse recalculer. On n'invente aucune AMP.
    """
    amps = bag.get("amp")
    if not isinstance(amps, list):
        return False
    if not amps:
        return True
    return all(isinstance(item, dict) and "source" in item for item in amps)


_ICI_BUCKETS: tuple[int, dict[tuple[int, int], list[tuple[float, float, dict]]]] | None = None
_ICI_CELL = 4.0  # 0,25° : une case. La fenêtre de recherche s'élargit avec max_nm.


def _ici_buckets(body: dict) -> dict[tuple[int, int], list[tuple[float, float, dict]]]:
    global _ICI_BUCKETS
    key = id(body)
    if _ICI_BUCKETS is not None and _ICI_BUCKETS[0] == key:
        return _ICI_BUCKETS[1]
    buckets: dict[tuple[int, int], list[tuple[float, float, dict]]] = {}
    for row in body.get("points") or []:
        if not isinstance(row, dict):
            continue
        bag = row.get("bag")
        if not isinstance(bag, dict):
            continue
        try:
            plat = float(row["lat"])
            plon = float(row["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        buckets.setdefault((int(plat * _ICI_CELL), int(plon * _ICI_CELL)), []).append((plat, plon, bag))
    _ICI_BUCKETS = (key, buckets)
    return buckets


def ici_bag_near(lat: float, lon: float, max_nm: float = ROUTE_NEAR_NM) -> Optional[dict]:
    body = payload_of("ici")
    if not body:
        return None
    import math  # noqa: PLC0415
    buckets = _ici_buckets(body)
    cos = max(0.2, math.cos(math.radians(float(lat))))
    pad_lat = int((max_nm / 60.0) * _ICI_CELL) + 2
    pad_lon = int((max_nm / (60.0 * cos)) * _ICI_CELL) + 2
    lat_i = int(float(lat) * _ICI_CELL)
    lon_i = int(float(lon) * _ICI_CELL)
    best = None
    best_d = max_nm
    for di in range(-pad_lat, pad_lat + 1):
        for dj in range(-pad_lon, pad_lon + 1):
            for plat, plon, bag in buckets.get((lat_i + di, lon_i + dj), ()):
                d = _haversine_nm(lat, lon, plat, plon)
                if d < best_d:
                    best_d = d
                    best = bag
    if not isinstance(best, dict):
        return None
    if not _ici_bag_is_am1a(best):
        return None
    return best


def preparing_ici(lat: float, lon: float, radius_nm: float = 30.0) -> dict:
    from ici_engine import empty_dossier  # noqa: PLC0415
    bag = empty_dossier(lat, lon, radius_nm)
    bag["status"] = PREPARING
    bag["reason"] = "en préparation"
    return bag


# ── calculs (mêmes fonctions que le serveur d'aujourd'hui) ───────────────────

def compute_climo(voy: dict, now: datetime) -> Optional[dict]:
    """Horloge officielle : passé RÉEL figé (ERA5) + avenir
    climatologique déterministe. Sans vent réel (hindcast coupé, quota, CI) :
    horloge climatologique comme avant. Si l'atlas a reculé depuis la veille,
    on NE recalcule PAS l'avenir : on garde l'horloge de la veille et le
    statut le dit."""
    from climo_events import notable_climo_changes  # noqa: PLC0415
    from voyage_api import _climo_clock, _polar_raw, _regime_portions  # noqa: PLC0415
    from voyage_store import save_voyage  # noqa: PLC0415
    import real_track  # noqa: PLC0415

    try:
        polar_raw = _polar_raw(voy.get("expedition_id") or "")
    except Exception:
        polar_raw = None
    track = None
    try:
        track = real_track.ensure_track(voy, now, polar_raw)
    except Exception as exc:
        log.warning("trajet réel : %s", exc)

    extra: dict = {}
    fields: dict = {}
    if track is not None:
        fields = real_track.status_fields(track, voy, now)
        future = real_track.future_clock(voy, track, polar_raw)
        ratio = real_track.atlas_ratio(future)
        prev = payload_of("climo")
        prev_ratio = (prev or {}).get("atlasRatio")
        if future is not None and not real_track.accept_future(ratio, prev_ratio):
            reason = "atlas incomplet — horloge de la veille"
            fields["hindcastReason"] = (
                f"{fields.get('hindcastReason')} · {reason}" if fields.get("hindcastReason") else reason
            )
            _save_official_status(voy, fields)
            log.warning(
                "horloge avenir NON recalculée : atlas %.1f %% (veille %.1f %%) — horloge de la veille servie",
                ratio * 100.0, float(prev_ratio) * 100.0,
            )
            return None
        clock = real_track.assemble_clock(track, future)
        extra["atlasRatio"] = round(ratio, 4)
    else:
        clock = _climo_clock(voy)
        if hindcast_enabled_for_status():
            fields = real_track.status_fields(None, voy, now)

    if not clock or not clock.get("t0"):
        return None
    if fields:
        clock["realUntil"] = fields.get("realUntil")
        clock["hindcastCoverage"] = fields.get("hindcastCoverage")
        extra.update(fields)
    voy = dict(voy)
    if isinstance(clock, dict) and clock.get("marks"):
        clock = dict(clock)
        clock["marks"] = repair_call_marks(clock.get("marks") or [], voy)
    if voy.get("marks"):
        voy["marks"] = repair_call_marks(voy.get("marks") or [], voy)
    voy["clock"] = clock
    voy.update({k: v for k, v in fields.items() if k != "realUntil"})
    save_voyage(voy)
    fiches = []
    for v in clock.get("vertices") or []:
        if not isinstance(v, dict) or v.get("lat") is None:
            continue
        fiches.append({
            "lat": v.get("lat"), "lon": v.get("lon"),
            "iso": v.get("iso"), "sailNm": v.get("sailNm"),
            "regime": v.get("regime") or v.get("kind"),
            "windKnots": v.get("windKnots"),
            "dirFromDeg": v.get("dirFromDeg"),
        })
    return {
        "clock": clock,
        "regimes": _regime_portions(clock),
        "fiches": fiches,
        "events": notable_climo_changes(clock),
        **extra,
    }


def hindcast_enabled_for_status() -> bool:
    from hindcast import hindcast_enabled  # noqa: PLC0415
    return hindcast_enabled()


def payload_has_real_until(payload: Optional[dict]) -> bool:
    """True si le climo a déjà le champ HC1 (date réelle ou null honnête).

    Un climo pré-HC1 n'a ni `clock.realUntil` ni `realUntil` au sommet : le
    remplisseur doit alors relancer `compute_climo`. La présence
    de la clé, même à `null`, compte : `ensure_track` a déjà rendu None et
    le statut `empty` est rangé — on ne recalcule pas en boucle.
    """
    if not isinstance(payload, dict):
        return False
    clock = payload.get("clock")
    if isinstance(clock, dict) and "realUntil" in clock:
        return True
    return "realUntil" in payload


def _climo_should_recompute(payload: Optional[dict]) -> bool:
    """Climo du jour sans frontière HC1, hindcast actif → ne pas figer `unchanged`."""
    if not hindcast_enabled_for_status():
        return False
    return not payload_has_real_until(payload)


def nudge_climo_if_missing_real_until() -> None:
    """GET /clock : si l'horloge servie n'a pas `realUntil` et que le hindcast
    est actif, réveiller le remplisseur — sans recalculer dans le processus HTTP.
    L'horloge déjà rangée reste servie (pas de trou « preparing »)."""
    if not hindcast_enabled_for_status():
        return
    if payload_has_real_until(payload_of("climo")):
        return
    kick_worker()


def _save_official_status(voy: dict, fields: dict) -> None:
    """Statut hindcast honnête sur le voyage officiel — via save_voyage, rien d'autre."""
    from voyage_store import save_voyage  # noqa: PLC0415
    out = dict(voy)
    out.update({k: v for k, v in fields.items() if k != "realUntil"})
    try:
        save_voyage(out)
    except Exception as exc:
        log.warning("statut hindcast non rangé : %s", exc)


RICH_EVENT_KINDS = frozenset({"zee", "sci", "science", "poe", "amp", "climo", "wx", "grib", "marina", "port"})


def journal_degraded(summary: dict | None) -> bool:
    """Vrai si le journal ne connaît que des escales / positions alors que le poste a des perles riches
    (donc des ZEE, stations, ports d'entrée, AMP à raconter). Un tel journal est un accident de calcul,
    pas un état du voyage : il ne doit pas être figé comme « prêt »."""
    rows = list((summary or {}).get("events") or []) + list((summary or {}).get("latest") or (summary or {}).get("entries") or [])
    kinds = {str(r.get("kind")) for r in rows if isinstance(r, dict)}
    if kinds & RICH_EVENT_KINDS:
        return False
    try:
        import pearl_store  # noqa: PLC0415
        rich = int((pearl_store.count_pearls() or {}).get("rich") or 0)
    except Exception:
        rich = 0
    return bool(rich)


def compute_moments(voy: dict, now: datetime) -> Optional[dict]:
    import voyage_journal as journal  # noqa: PLC0415
    from moment_journal import read_moments, warm_moments  # noqa: PLC0415
    from voyage_clock import OFFICIAL_VOYAGE_ID  # noqa: PLC0415

    if not voy.get("clock"):
        return None
    journal.tick(voy, now, force=True)
    summary = journal.summary(500)
    days = {}
    for row in summary.get("days") or []:
        day = row.get("day")
        if day:
            try:
                days[day] = journal.read_day(day)
            except Exception:
                days[day] = []
    try:
        warm_moments(OFFICIAL_VOYAGE_ID, voy)   # avec l'horloge : sinon 740 moments sans date (27 sept.)
        moments = read_moments(OFFICIAL_VOYAGE_ID)
    except Exception as exc:
        log.warning("moments : %s", exc)
        moments = []
    if (summary.get("count") or 0) <= 0 and not moments:
        return None
    # Garde-fou (27 sept.) : le stock a servi pendant 14 h un journal réduit aux escales et 740 moments
    # sans date, calculés dans un worktree sans perles — puis plus jamais recalculés parce que « prêts ».
    # Une famille dégradée reste « en préparation » : le prochain passage la recalculera.
    if moments and not any(m.get("t") for m in moments):
        log.warning("stock moments : %d moments sans date — non rangés (horloge ?)", len(moments))
        return None
    if journal_degraded(summary):
        log.warning("stock moments : journal sans événements (escales seulement) alors que des perles riches existent — non rangé")
        return None
    payload = {"moments": moments, "journal": summary, "journal_days": days}
    if not moments:
        payload["moments"] = _rows_from_journal(payload)
    return payload


def film_variant_timeout_s() -> float:
    """Délai maximum d'une variante. Au-delà, on passe à la suivante.

    Le remplisseur calculait les six d'un coup et ne rangeait rien tant que
    la plus lente n'avait pas fini (19 oct. : des heures, 0 chapitre).
    """
    try:
        raw = float(os.environ.get("NAVIGUIDE_FILM_VARIANT_TIMEOUT_S") or 600)
    except (TypeError, ValueError):
        raw = 600.0
    return max(0.05, raw)


_FILM_JOURNAL: list[str] = []
_FILM_PROGRESS_N = 0
_FILM_JOURNAL_LOCK = threading.Lock()
_FILM_JOURNAL_MAX = 400
# Un blocage simulé attend cet événement pour quitter, au lieu de dormir jusqu'au bout.
_STEP_CANCEL = threading.Event()
# File du fils : ses lignes remontent au père, sinon le délai ne les voit pas.
_FILM_PROGRESS_QUEUE = None
# --rebuild-film : une ligne du fils remet le délai. La boucle de fond, non.
_FOLLOW_FILM_PROGRESS = False


class FilmProgressStalled(RuntimeError):
    """Aucun progrès de fabrication écrit avant le délai maximum."""


def film_journal() -> list[str]:
    """Lignes d'avancement (variante, appel Nemotron, écriture). Le test les lit."""
    with _FILM_JOURNAL_LOCK:
        return list(_FILM_JOURNAL)


def reset_film_journal() -> None:
    with _FILM_JOURNAL_LOCK:
        _FILM_JOURNAL.clear()


def _film_progress_mark() -> int:
    with _FILM_JOURNAL_LOCK:
        return _FILM_PROGRESS_N


def _delay_label(seconds: float) -> str:
    value = float(seconds)
    if value >= 10:
        return f"{value:.0f} s"
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return f"{text} s"


def _film_say(msg: str) -> None:
    """Une ligne d'avancement. Elle remet le délai de silence à zéro."""
    global _FILM_PROGRESS_N
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    with _FILM_JOURNAL_LOCK:
        _FILM_PROGRESS_N += 1
        _FILM_JOURNAL.append(line)
        if len(_FILM_JOURNAL) > _FILM_JOURNAL_MAX:
            del _FILM_JOURNAL[: len(_FILM_JOURNAL) - _FILM_JOURNAL_MAX]
    log.info("%s", msg)
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    print(line, flush=True)
    try:
        path = fill_logfile()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


def _emit_film_progress(msg: str) -> None:
    """Une ligne d'avancement. Depuis le fils, elle revient au père par la file.

    Le journal et le délai de silence vivent dans le père. Une ligne écrite
    seulement dans le fils s'affichait, puis la commande s'arrêtait quand même.
    """
    queue = _FILM_PROGRESS_QUEUE
    if queue is not None:
        try:
            queue.put(("progress", msg))
            return
        except Exception:
            pass
    _film_say(msg)


def _logging_cascade(lang: str, seconds: int):
    """Journalise l'appel que le film fait déjà. N'en ajoute pas."""

    async def _call(*args, **kwargs):
        _emit_film_progress(f"appel Nemotron {lang} {int(seconds)}s")
        from story_cascade import cascade_text  # noqa: PLC0415
        return await cascade_text(*args, **kwargs)

    return _call


def _run_until_progress_or_stall(fn: Callable, timeout_s: float, label: str):
    """Exécute `fn`. Sans ligne nouvelle pendant le délai, lève FilmProgressStalled.

    Une ligne nouvelle remet le délai à zéro : le silence compte, pas la durée totale.
    """
    _STEP_CANCEL.clear()
    mark = _film_progress_mark()
    started = time.monotonic()
    limit = max(0.05, float(timeout_s))
    box: dict = {}

    def _run() -> None:
        try:
            box["value"] = fn()
        except Exception as exc:  # le parent relance
            box["error"] = exc
        finally:
            box["done"] = True

    thread = threading.Thread(target=_run, name="film-progress", daemon=True)
    thread.start()
    while not box.get("done"):
        if _film_progress_mark() > mark:
            mark = _film_progress_mark()
            started = time.monotonic()
        if time.monotonic() - started > limit:
            _STEP_CANCEL.set()
            msg = (
                f"{label} : aucun progrès avant le délai maximum "
                f"({_delay_label(limit)}) — arrêt"
            )
            _film_say(msg)
            raise FilmProgressStalled(msg)
        thread.join(0.05)
    if box.get("error"):
        raise box["error"]
    return box.get("value")


def _nemotron_for_variant(lang: str, seconds: int, plan: dict):
    """Rédige cette variante. Sous pytest : aucun appel réseau."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return None
    import asyncio  # noqa: PLC0415
    import llm_budget  # noqa: PLC0415

    if llm_budget.mode() == "off" or not llm_budget.llm_allowed_here("write"):
        _film_say(f"appel Nemotron {lang} {int(seconds)}s : non effectué (mode)")
        return None
    if not llm_budget.allow("write"):
        _film_say(f"appel Nemotron {lang} {int(seconds)}s : non effectué (plafond)")
        return None
    from film_script import write_with_llm  # noqa: PLC0415
    from story_cascade import cascade_text  # noqa: PLC0415

    async def _run():
        return await write_with_llm(plan, [], lang=lang, cascade=cascade_text)

    try:
        written, source = asyncio.run(_run())
    except Exception as exc:
        _film_say(f"appel Nemotron {lang} {int(seconds)}s : {type(exc).__name__}")
        return None
    if not isinstance(written, dict) or not (written.get("chapters") or []):
        _film_say(f"appel Nemotron {lang} {int(seconds)}s : sans chapitre ({source})")
        return None
    _film_say(f"appel Nemotron {lang} {int(seconds)}s : {source}")
    return written


def _film_variant_sequence() -> list[tuple[str, int]]:
    """150 d'abord (le GET public), puis 180, puis l'intégral. Une à la fois."""
    raw = (os.environ.get("NAVIGUIDE_FILM_ONLY") or "").strip().lower()
    if raw:
        lang, sep, secs = raw.partition(":")
        if sep == ":" and lang in {"fr", "en"}:
            try:
                n = int(secs)
            except ValueError:
                n = -1
            if n in FILM_VARIANT_SECONDS:
                return [(lang, n)]
        log.warning("film : NAVIGUIDE_FILM_ONLY ignoré (%s)", raw)
    return [(lang, int(secs)) for secs in FILM_VARIANT_SECONDS for lang in ("fr", "en")]


def _existing_film_variants(voy: dict, now: datetime) -> dict:
    """Variantes déjà rangées pour cette clé. Un échec ne les efface pas."""
    try:
        st = get_store()
        hit = st.get("film", st.family_key("film", voy, now))
    except Exception:
        return {}
    body = hit.get("payload") if hit and isinstance(hit.get("payload"), dict) else None
    raw = body.get("variants") if isinstance(body, dict) else None
    if not isinstance(raw, dict):
        return {}
    out: dict = {}
    for lang, by_secs in raw.items():
        if isinstance(by_secs, dict):
            out[str(lang)] = dict(by_secs)
    return out


def _film_payload_from_variants(variants: dict) -> Optional[dict]:
    frozen = {
        str(lang): dict(by)
        for lang, by in variants.items()
        if isinstance(by, dict)
    }
    fr = (frozen.get("fr") or {}).get(str(FILM_VARIANT_SECONDS[0]))
    if not isinstance(fr, dict) or not (fr.get("chapters") or []):
        return None
    out = {
        "fr": fr,
        "default": fr,
        "variants": frozen,
        "estimates": _variants_estimates(frozen),
        "film_script_rev": FILM_SCRIPT_REV,
    }
    en = (frozen.get("en") or {}).get(str(FILM_VARIANT_SECONDS[0]))
    if isinstance(en, dict) and (en.get("chapters") or []):
        out["en"] = en
    return out


def _store_film_progress(voy: dict, now: datetime, payload: dict) -> bool:
    """Range au fur et à mesure. Sous pytest, seulement si le test l'ouvre :
    un test ne doit pas écrire le stock du poste."""
    if os.environ.get("PYTEST_CURRENT_TEST") and os.environ.get("NAVIGUIDE_FILM_PROGRESS_PUT") != "1":
        return False
    try:
        st = get_store()
        st.put("film", payload, st.family_key("film", voy, now))
    except Exception as exc:
        log.warning("film : non rangé (%s)", exc)
        return False
    return True


# Calcul local lancé avant ce correctif. Ce lot ne lui envoie aucun signal.
_PROTECTED_FILM_PIDS = frozenset({46246, 46268})


def _stop_spawned(proc) -> None:
    pid = getattr(proc, "pid", None)
    if pid in _PROTECTED_FILM_PIDS:
        log.warning("film : pid %s protégé — aucun signal", pid)
        return
    if not proc.is_alive():
        return
    proc.terminate()
    proc.join(2)
    if proc.is_alive() and proc.pid not in _PROTECTED_FILM_PIDS:
        proc.kill()
        proc.join(2)


def _bounded_sleep_worker(seconds: float, queue) -> None:
    """Cible de test : un calcul qui ne rend pas la main."""
    import time as _time  # noqa: PLC0415
    _time.sleep(float(seconds))
    queue.put("done")


def _bounded_blob_worker(nbytes: int, queue) -> None:
    """Cible de test : un plan déjà prêt, plus gros que le tampon du tube."""
    queue.put(("ok", {"chapters": [{"text": "x" * int(nbytes)}]}))


def _bounded_progress_worker(beats: int, pause_s: float, queue) -> None:
    """Cible de test : une ligne, une pause, puis un plan. Le silence se mesure entre deux lignes."""
    import time as _time  # noqa: PLC0415

    n = int(beats)
    pause = float(pause_s)
    for i in range(n):
        _time.sleep(pause)
        queue.put(("progress", f"calcul {i}"))
    queue.put(("ok", {"chapters": [{"text": "Berry-Mappemonde"}]}))


def _film_variant_worker(lang: str, seconds: int, timeout_s: float, queue) -> None:
    """Un processus neuf, sans la boucle du parent. Une variante, un délai."""
    global _FILM_PROGRESS_QUEUE
    os.environ["NAVIGUIDE_OFFICIAL_WORKER"] = "0"
    _FILM_PROGRESS_QUEUE = queue
    try:
        import asyncio  # noqa: PLC0415
        from film_script import official_film  # noqa: PLC0415
        plan = asyncio.run(asyncio.wait_for(
            official_film(
                lang=str(lang), seconds=int(seconds), style="raw",
                cascade=_logging_cascade(str(lang), int(seconds)),
            ),
            timeout=max(0.05, float(timeout_s)),
        ))
        queue.put(("ok", plan if isinstance(plan, dict) else None))
    except TimeoutError:
        queue.put(("timeout", None))
    except Exception as exc:
        queue.put(("error", f"{type(exc).__name__}: {exc}"[:400]))
    finally:
        _FILM_PROGRESS_QUEUE = None


def _queue_item_is_progress(item) -> bool:
    return isinstance(item, tuple) and len(item) == 2 and item[0] == "progress"


def run_bounded_process(target, args: tuple, timeout_s: float, *, follow_progress: bool = False):
    """Lance `target` hors de ce processus et l'arrête au délai.

    Retourne `(fini, valeur)`. `fini` est faux si le délai a coupé le processus.
    Le pid protégé du calcul déjà en cours n'est jamais signalé.

    La file est lue pendant que le fils vit. L'attendre d'abord bloque :
    un plan déjà calculé plus gros que le tampon du tube (~65 Ko) empêche
    le fils de quitter, le délai le tue, et les chapitres sont perdus.

    Une ligne `progress` est un avancement, pas le résultat. Avec
    `follow_progress` (fabrication d'une variante), elle remet le délai à zéro.
    Sans ce drapeau, le délai dur de la boucle de fond ne bouge pas.
    """
    import multiprocessing  # noqa: PLC0415
    import queue as queue_mod  # noqa: PLC0415

    server = str(Path(__file__).resolve().parent)
    old_path = os.environ.get("PYTHONPATH")
    old_worker = os.environ.get("NAVIGUIDE_OFFICIAL_WORKER")
    os.environ["PYTHONPATH"] = server if not old_path else server + os.pathsep + old_path
    os.environ["NAVIGUIDE_OFFICIAL_WORKER"] = "0"
    ctx = multiprocessing.get_context("spawn")
    pipe = ctx.Queue()
    proc = ctx.Process(target=target, args=(*args, pipe), daemon=True)
    try:
        proc.start()
    finally:
        if old_path is None:
            os.environ.pop("PYTHONPATH", None)
        else:
            os.environ["PYTHONPATH"] = old_path
        if old_worker is None:
            os.environ.pop("NAVIGUIDE_OFFICIAL_WORKER", None)
        else:
            os.environ["NAVIGUIDE_OFFICIAL_WORKER"] = old_worker
    try:
        deadline = time.monotonic() + float(timeout_s)
        value = None
        got = False

        def _take(block_s: float):
            nonlocal deadline, got, value
            item = pipe.get(timeout=block_s)
            if _queue_item_is_progress(item):
                _film_say(str(item[1]))
                if follow_progress:
                    deadline = time.monotonic() + float(timeout_s)
                return False
            value = item
            got = True
            return True

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                if _take(min(0.2, remaining)):
                    break
            except queue_mod.Empty:
                if not proc.is_alive():
                    break
        if not got:
            while True:
                try:
                    if _take(0.2):
                        break
                except queue_mod.Empty:
                    break
        if not got:
            if proc.is_alive():
                return False, None
            return True, None
        proc.join(2)
        return True, value
    finally:
        if proc.is_alive():
            _stop_spawned(proc)
        try:
            pipe.close()
            pipe.cancel_join_thread()
        except Exception:
            pass


def _await_official_film(lang: str, seconds: int, timeout_s: float):
    """Même processus (tests, fonction simulée). Hors de la boucle courante."""
    import asyncio  # noqa: PLC0415
    from film_script import official_film  # noqa: PLC0415

    async def _bounded():
        return await asyncio.wait_for(
            official_film(
                lang=lang, seconds=int(seconds), style="raw",
                cascade=_logging_cascade(lang, int(seconds)),
            ),
            timeout_s,
        )

    def _run():
        try:
            return "ok", asyncio.run(_bounded())
        except TimeoutError:
            return "timeout", None
        except Exception as exc:
            return "error", f"{type(exc).__name__}: {exc}"[:400]

    try:
        asyncio.get_running_loop()
        in_loop = True
    except RuntimeError:
        in_loop = False
    if not in_loop:
        return _run()
    box: dict = {}

    def _thread():
        box["value"] = _run()

    thread = threading.Thread(target=_thread, name="compute-film-variant", daemon=True)
    thread.start()
    thread.join(timeout_s + 2.0)
    if thread.is_alive():
        return "timeout", None
    return box.get("value", ("error", "fil sans résultat"))


def _compute_one_variant(lang: str, seconds: int, timeout_s: float):
    """Une variante, hors de la boucle d'événements, avec un délai maximum."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        kind, payload = _await_official_film(lang, seconds, timeout_s)
    else:
        # Grâce courte pour que le fils puisse rendre un résultat déjà fini.
        kw = {"follow_progress": True} if _FOLLOW_FILM_PROGRESS else {}
        finished, value = run_bounded_process(
            _film_variant_worker,
            (lang, int(seconds), float(timeout_s)),
            float(timeout_s) + 5.0,
            **kw,
        )
        if not finished:
            kind, payload = "timeout", None
        elif isinstance(value, tuple) and len(value) == 2:
            kind, payload = value
        else:
            kind, payload = "error", value
    if kind == "ok" and isinstance(payload, dict) and (payload.get("chapters") or []):
        return payload
    if kind == "timeout":
        _film_say(
            f"film {lang} {seconds}s : délai maximum {_delay_label(timeout_s)} dépassé"
        )
    elif kind == "error":
        _film_say(f"film {lang} {seconds}s : {payload}")
    else:
        _film_say(f"film {lang} {seconds}s : sans chapitre")
    return None


def compute_film(voy: dict, now: datetime) -> Optional[dict]:
    """Une variante à la fois, hors de la boucle, chacune sous un délai maximum.

    La 2:30 française est rangée dès qu'elle a des chapitres : les suivantes
    peuvent expirer sans effacer ce qui est déjà en stock.
    """
    if not voy.get("clock"):
        return None
    timeout_s = film_variant_timeout_s()
    variants = _existing_film_variants(voy, now)
    for lang, secs in _film_variant_sequence():
        _film_say(f"variante {lang} {secs}s")
        _film_say(f"REFRESH film {lang} {secs}s")
        plan = _compute_one_variant(lang, secs, timeout_s)
        if not isinstance(plan, dict) or not (plan.get("chapters") or []):
            continue
        annotated = _with_film_estimate(_apply_air_sentences(plan, lang, voy))
        variants.setdefault(lang, {})[str(secs)] = annotated
        payload = _film_payload_from_variants(variants)
        if payload is None:
            continue
        n = len(annotated.get("chapters") or [])
        if _store_film_progress(voy, now, payload):
            _film_say(f"écriture stock {lang} {secs}s chapitres={n} STORED")
        else:
            _film_say(f"écriture stock {lang} {secs}s chapitres={n} non rangée")
    return _film_payload_from_variants(variants)


def _payload_keeping_variant(variants: dict) -> dict:
    """Garde la variante calculée même si le français 2:30 n'est pas encore là."""
    payload = _film_payload_from_variants(variants)
    if payload is not None:
        return payload
    frozen = {
        str(lang): dict(by)
        for lang, by in variants.items()
        if isinstance(by, dict)
    }
    return {
        "variants": frozen,
        "estimates": _variants_estimates(frozen),
        "film_script_rev": FILM_SCRIPT_REV,
    }


def rebuild_film_variant(
    lang: str,
    seconds: int,
    *,
    voy: Optional[dict] = None,
    now: Optional[datetime] = None,
) -> dict:
    """Une variante : journal, appel Nemotron, écriture. Silence = erreur.

    Le remplisseur de fond, lui, saute une variante en retard et continue.
    Ici la commande s'arrête : c'est une fabrication demandée, pas la boucle.
    """
    global _FOLLOW_FILM_PROGRESS
    lg = (lang or "").strip().lower()
    try:
        secs = int(seconds)
    except (TypeError, ValueError):
        secs = -1
    if lg not in {"fr", "en"} or secs not in FILM_VARIANT_SECONDS:
        raise ValueError(f"variante invalide : {lang}:{seconds}")
    timeout_s = film_variant_timeout_s()
    current = voy if voy is not None else _load_official()
    when = now or _utc_now()
    _FOLLOW_FILM_PROGRESS = True
    try:
        return _rebuild_film_variant_logged(lg, secs, timeout_s, current, when)
    finally:
        _FOLLOW_FILM_PROGRESS = False


def _rebuild_film_variant_logged(lg: str, secs: int, timeout_s: float, current: dict, when: datetime) -> dict:
    """Journal, appel, écriture. Le délai suit les lignes, y compris celles du fils."""
    if not current or not current.get("clock"):
        msg = "film : horloge absente — arrêt"
        _film_say(msg)
        raise FilmProgressStalled(msg)
    _film_say(f"variante {lg} {secs}s")
    plan = _run_until_progress_or_stall(
        lambda: _compute_one_variant(lg, secs, timeout_s),
        timeout_s,
        f"variante {lg} {secs}s",
    )
    if not isinstance(plan, dict) or not (plan.get("chapters") or []):
        msg = (
            f"film {lg} {secs}s : aucun progrès avant le délai maximum "
            f"({_delay_label(timeout_s)}) — arrêt"
        )
        _film_say(msg)
        raise FilmProgressStalled(msg)
    _film_say(f"appel Nemotron {lg} {secs}s")
    written = _run_until_progress_or_stall(
        lambda: _nemotron_for_variant(lg, secs, plan),
        timeout_s,
        f"appel Nemotron {lg} {secs}s",
    )
    annotated = _with_film_estimate(_apply_air_sentences(plan, lg, current))
    variants = _existing_film_variants(current, when)
    variants.setdefault(lg, {})[str(secs)] = annotated
    payload = _payload_keeping_variant(variants)
    if isinstance(written, dict) and (written.get("chapters") or []):
        payload = _put_written_variant(
            payload, lg, secs, written, when, _stored_last_stop(),
        )
    n = len(annotated.get("chapters") or [])
    if _store_film_progress(current, when, payload):
        _film_say(f"écriture stock {lg} {secs}s chapitres={n} STORED")
    else:
        _film_say(f"écriture stock {lg} {secs}s chapitres={n} non rangée")
    return payload


def _stored_eta_stop(name: str) -> Optional[dict]:
    if not (name or "").strip():
        return None
    hit = get("eta")
    body = hit.get("payload") if hit and isinstance(hit.get("payload"), dict) else None
    stops = (body or {}).get("stops") or {}
    if name in stops and isinstance(stops[name], dict):
        return dict(stops[name])
    needle = name.strip().lower()
    for n, payload in stops.items():
        if needle and needle in str(n).lower() and isinstance(payload, dict):
            return dict(payload)
    return None


def _eta_stop_record(raw: Optional[dict], now: datetime) -> dict:
    """Une escale du stock : ready seulement si des membres ont produit p10–p90."""
    from ensemble_eta import explain_eta_reason  # noqa: PLC0415
    from voyage_clock import to_iso  # noqa: PLC0415

    src = raw if isinstance(raw, dict) else {}
    try:
        members = int(src.get("members") or 0)
    except (TypeError, ValueError):
        members = 0
    p10, p50, p90 = src.get("p10"), src.get("p50"), src.get("p90")
    ready = members > 0 and bool(p10) and bool(p90)
    computed = src.get("computedAt") or to_iso(now)
    out = {
        "p10": p10 if ready else None,
        "p50": p50 if ready else None,
        "p90": p90 if ready else None,
        "members": members if ready else 0,
        "status": READY if ready else UNAVAILABLE,
        "reason": None,
        "nextRetry": None,
        "computedAt": computed,
    }
    if ready:
        if src.get("source"):
            out["source"] = src["source"]
        if src.get("memberKnots"):
            out["memberKnots"] = src["memberKnots"]
        return out
    out["reason"] = explain_eta_reason(src)
    out["nextRetry"] = src.get("nextRetry")
    if src.get("lastAttempt"):
        out["lastAttempt"] = src["lastAttempt"]
    if src.get("detail"):
        out["detail"] = src["detail"]
    return out


def compute_eta(voy: dict, now: datetime) -> Optional[dict]:
    from ensemble_eta import (  # noqa: PLC0415
        eta_retry_due,
        next_official_stop,
        peek_official_eta,
        preheat_official_eta,
        tighten_eta_payload,
    )
    from voyage_api import _polar_raw  # noqa: PLC0415

    if not voy.get("clock"):
        return None
    nxt = next_official_stop(voy, now)
    last = _stored_eta_stop(nxt) if nxt else None
    if last is None and nxt:
        try:
            last = peek_official_eta(voy, nxt, now)
        except Exception as exc:
            log.warning("peek ETA %s : %s", nxt, exc)
            last = None
    if last is None or eta_retry_due(last, now):
        try:
            preheat_official_eta(
                voy, now, polar_raw=_polar_raw(voy.get("expedition_id") or ""),
            )
        except Exception as exc:
            log.warning("préchauffage ETA : %s", exc)
    stops: dict[str, dict] = {}
    names = []
    if nxt:
        names.append(nxt)
    for m in voy.get("marks") or []:
        n = (m or {}).get("name")
        if n and n not in names:
            names.append(n)
    for name in names[:12]:
        try:
            raw = peek_official_eta(voy, name, now)
            stops[name] = _eta_stop_record(tighten_eta_payload(raw, now), now)
        except Exception as exc:
            log.warning("ETA %s : %s", name, exc)
            stored = _stored_eta_stop(name)
            if stored:
                stops[name] = _eta_stop_record(stored, now)
    if nxt and nxt not in stops:
        fallback = last if isinstance(last, dict) else {}
        stops[nxt] = _eta_stop_record(tighten_eta_payload(fallback, now), now)
    return {"stops": stops}


def compute_ici(voy: dict, now: datetime) -> Optional[dict]:
    from ici_engine import thin_cache_get, thin_cache_key  # noqa: PLC0415
    from ici_warm import official_pearls, sample_route_nm  # noqa: PLC0415

    points = []
    seen = set()

    def _add(lat: float, lon: float, nm: Any, bag: dict) -> None:
        key = (round(lat, 4), round(lon, 4))
        if key in seen:
            return
        seen.add(key)
        points.append({"lat": lat, "lon": lon, "nm": nm, "bag": bag})

    try:
        pearls = official_pearls()
        for p in (pearls.get("pearls") if isinstance(pearls, dict) else pearls) or []:
            if isinstance(p, (list, tuple)) and len(p) >= 2:
                lat, lon = float(p[0]), float(p[1])
                bag = thin_cache_get(thin_cache_key(lat, lon, 30.0))
                if bag:
                    _add(lat, lon, None, bag)
                continue
            if not isinstance(p, dict):
                continue
            bag = p.get("bag") if isinstance(p.get("bag"), dict) else None
            lat, lon = p.get("lat"), p.get("lon")
            if lat is None:
                at = (bag or {}).get("at") or {}
                lat, lon = at.get("lat"), at.get("lon")
            if lat is None or lon is None:
                continue
            if bag is None:
                bag = thin_cache_get(thin_cache_key(float(lat), float(lon), 30.0))
            if bag:
                _add(float(lat), float(lon), p.get("sailNm") or p.get("nm"), bag)
    except Exception as exc:
        log.debug("perles officielles : %s", exc)

    for p in sample_route_nm(voy.get("points") or []):
        bag = thin_cache_get(thin_cache_key(p["lat"], p["lon"], 30.0))
        if bag:
            _add(float(p["lat"]), float(p["lon"]), p.get("sailNm"), bag)

    if not points:
        return None
    return {"points": points}


def compute_plan_review(voy: dict, now: datetime) -> Optional[dict]:
    from plan_alerts import evaluate_plan  # noqa: PLC0415
    from plan_review import review_official  # noqa: PLC0415

    if not voy.get("clock"):
        return None
    out = review_official(voy, now, season=False)
    if not isinstance(out, dict) or not (out.get("legs") or []):
        return None
    try:
        ev = evaluate_plan(voy, now=now)
        counts: dict = {}
        for lg in ev.get("legs") or []:
            n = len(lg.get("alerts") or [])
            if lg.get("idx") is not None:
                counts[int(lg["idx"])] = n
            counts[(lg.get("from"), lg.get("to"))] = n
        for i, row in enumerate(out.get("legs") or []):
            n = counts.get(i)
            if n is None:
                n = counts.get((row.get("from"), row.get("to")))
            if n is not None:
                row["alertCount"] = int(n)
    except Exception as exc:
        log.debug("alertCount stock : %s", exc)
    out.setdefault("comment", {"text": "", "source": "rules", "cached": False})
    return out


COMPUTE: dict[str, Callable[[dict, datetime], Optional[dict]]] = {
    "climo": compute_climo,
    "moments": compute_moments,
    "film": compute_film,
    "eta": compute_eta,
    "ici": compute_ici,
    "plan_review": compute_plan_review,
}

# Horloge d'abord. Plan-review et eta avant le film (RG7 : le script les lit).
COMPUTE_ORDER = ("climo", "moments", "plan_review", "eta", "film", "ici")


def _eta_progress_detail(store: Optional["OfficialStore"] = None) -> str:
    """Une ligne pour le remplisseur : membres, ou raison + date de nouvel essai."""
    st = store or get_store()
    hit = st.get("eta")
    body = hit.get("payload") if hit and isinstance(hit.get("payload"), dict) else None
    stops = (body or {}).get("stops") or {}
    if not stops:
        return ""
    stop = next(iter(stops.values()))
    if not isinstance(stop, dict):
        return ""
    try:
        members = int(stop.get("members") or 0)
    except (TypeError, ValueError):
        members = 0
    if members > 0:
        return f"{members} membres"
    reason = str(stop.get("reason") or "").strip()
    retry = str(stop.get("nextRetry") or "")[:10]
    if reason and retry:
        return f"{reason}, nouvel essai {retry}"
    return reason


def refresh_family(
    family: str,
    *,
    force: bool = False,
    compute: Optional[Callable[[dict, datetime], Optional[dict]]] = None,
    now: Optional[datetime] = None,
    store: Optional[OfficialStore] = None,
    voy: Optional[dict] = None,
) -> str:
    """Calcule une famille et la range. `unchanged` si la clé est déjà servie."""
    st = store or get_store()
    when = now or st._now()
    current = voy if voy is not None else _load_official()
    if current is None:
        return PREPARING
    key = st.family_key(family, current, when)
    if not force:
        hit = st.get(family, key)
        if hit and hit.get("payload") is not None:
            if family == "film":
                if not film_snapshot_stale(hit.get("payload"), current):
                    return "unchanged"
            elif family == "eta":
                from ensemble_eta import eta_store_retry_due, next_official_stop  # noqa: PLC0415
                nxt = next_official_stop(current, when)
                if not eta_store_retry_due(hit.get("payload"), when, nxt):
                    return "unchanged"
            elif family == "climo" and _climo_should_recompute(hit.get("payload")):
                pass
            else:
                return "unchanged"
    fn = compute or COMPUTE[family]
    if family != "climo" and not current.get("clock"):
        clock = stored_clock()
        if clock:
            current = dict(current)
            current["clock"] = clock
    payload = fn(current, when)
    if payload is None:
        return PREPARING
    st.put(family, payload, key)
    return READY


def refresh_missing(
    *,
    force: bool = False,
    progress: Optional[Callable[[str, str, str], None]] = None,
    now: Optional[datetime] = None,
    store: Optional[OfficialStore] = None,
    computes: Optional[dict] = None,
    should_stop: Optional[Callable[[], bool]] = None,
    skip: tuple[str, ...] = (),
) -> dict:
    """Remplit ce qui manque ou a vieilli — hors chemin HTTP. `should_stop` (remplisseur) : vérifié entre deux
    familles, pour qu'un SIGTERM prenne effet en secondes et non à la fin d'un passage de plusieurs heures."""
    from voyage_api import seed_official_voyage  # noqa: PLC0415

    def _log(family: str, status: str, detail: str = "") -> None:
        if progress:
            progress(family, status, detail)
        else:
            log.info("stock %s : %s %s", family, status, detail)

    if not _REFRESH_LOCK.acquire(blocking=False):
        _log("*", "busy", "déjà en cours")
        return family_status()
    try:
        voy = seed_official_voyage()
        if voy is None:
            _log("*", PREPARING, "itinéraire officiel absent")
            return family_status()
        st = store or get_store()
        when = now or st._now()
        fns = computes or COMPUTE
        skipped = set(skip or ())
        for family in COMPUTE_ORDER:
            if family in skipped:
                continue
            if should_stop and should_stop():
                log.warning("stock : arrêt demandé — passage interrompu avant %s", family)
                break
            try:
                status = refresh_family(
                    family, force=force, compute=fns.get(family),
                    now=when, store=st, voy=_load_official() or voy,
                )
                detail = _eta_progress_detail(st) if family == "eta" else ""
                _log(family, status, detail)
            except Exception as exc:
                log.warning("stock %s : %s", family, exc)
                _log(family, PREPARING, str(exc)[:160])
        # Plus de fill_written_film ici — Super / Ultra seulement au clic.
        return st.status()
    finally:
        _REFRESH_LOCK.release()


# ── remplisseur : un PROCESSUS séparé (RC18) ─────────────────────────────────
# Le calcul (horloge sur 8 878 sommets, 845 moments, films, ETA) tient le GIL : dans le processus de l'API,
# la boucle d'événements ne reprend la main que par miettes — 27 sept. : 97 % CPU, /clock en 7 s au lieu de
# 5 ms, POST /voyage coupé par Cloudflare à 100 s, 1 430 lignes rouges chez le bot. L'API ne calcule donc
# JAMAIS : elle lance scripts/prepare_official_store.py --loop (priorité basse), le réveille par un fichier
# « nudge », et relit le stock quand il change (stamp). Mode « thread » conservé pour les tests.

WORKER_MODE = (os.environ.get("NAVIGUIDE_OFFICIAL_WORKER_MODE") or "process").strip().lower()
FILL_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prepare_official_store.py"
FILL_NICE = int(os.environ.get("NAVIGUIDE_OFFICIAL_FILL_NICE") or 10)


def fill_pidfile() -> Path:
    return disk_root() / "fill-worker.pid"


def fill_nudgefile() -> Path:
    return disk_root() / "fill-worker.nudge"


def fill_logfile() -> Path:
    return disk_root() / "fill-worker.log"


def _process_command(pid: int) -> str:
    import subprocess  # noqa: PLC0415
    try:
        out = subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True, timeout=5)
        return (out.stdout or "").strip()
    except Exception:
        return ""


def fill_process_alive() -> Optional[int]:
    """PID du remplisseur s'il tourne ET vient de CE checkout (un remplisseur d'un ancien worktree écrirait
    un stock d'un autre format : on le remplace)."""
    try:
        raw = fill_pidfile().read_text(encoding="utf-8").strip().splitlines()
        pid = int(raw[0])
        script = raw[1] if len(raw) > 1 else ""
        stamp = raw[2] if len(raw) > 2 else ""
    except (OSError, ValueError, IndexError):
        return None
    try:
        os.kill(pid, 0)
    except OSError:
        return None
    cmd = _process_command(pid)
    if FILL_SCRIPT.name not in cmd:
        return None
    # Autre checkout, OU même chemin mais code changé (le poste réutilise toujours ~/bim-lots/recette : après un
    # rebuild, le remplisseur en mémoire est celui de l'ancienne branche) → on le remplace.
    if (script and script != str(FILL_SCRIPT)) or (stamp and stamp != _fill_script_stamp()):
        log.warning("stock officiel : remplisseur d'un autre code (%s, pid %s) — arrêté", script or "?", pid)
        try:
            os.kill(pid, 15)
        except OSError:
            pass
        return None
    return pid


def _fill_script_stamp() -> str:
    """Empreinte du code du remplisseur : mtime le plus récent du script ET des modules serveur qu'il importe
    (le poste réutilise le même chemin de worktree : seul le contenu change entre deux rebuilds)."""
    try:
        latest = FILL_SCRIPT.stat().st_mtime_ns
        for p in Path(__file__).resolve().parent.glob("*.py"):
            latest = max(latest, p.stat().st_mtime_ns)
        return str(latest)
    except OSError:
        return ""


def command_store(command: str, default: Optional[Path] = None) -> Optional[Path]:
    """Dossier de stock visé par une ligne `ps`.

    `--store <chemin>` est explicite. Sans cet argument, le script écrit le stock par
    défaut (`~/.cache/naviguide/voyage-store`) : c'est le passage orphelin du 17 oct.,
    lancé sans `--loop` ni `--store`, que le filtre « --loop » laissait vivre.
    """
    if FILL_SCRIPT.name not in command:
        return None
    parts = command.split()
    try:
        i = parts.index("--store")
    except ValueError:
        return Path(default) if default is not None else Path.home() / ".cache" / "naviguide" / "voyage-store"
    if i + 1 >= len(parts):
        return None
    return Path(parts[i + 1])


def other_fill_processes(keep: Optional[int] = None, store: Optional[Path] = None) -> list[int]:
    """Les `prepare_official_store.py` vivants qui écrivent CE stock, sauf `keep` et nous.

    Boucle ou passage unique : les deux écrivent le même fichier. 29 sept. : quatre boucles
    en même temps ont corrompu le voyage officiel. 17 oct. : trois passages sans `--loop`
    ont survécu au timeout et au filtre qui ne voyait que `--loop`.
    Un `--store` différent (stock d'un worktree d'agent) n'est pas touché."""
    import subprocess  # noqa: PLC0415
    try:
        out = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return []
    me = os.getpid()
    want = Path(store or disk_root())
    default = Path.home() / ".cache" / "naviguide" / "voyage-store"
    found: list[int] = []
    for line in out.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            continue
        got = command_store(parts[1], default)
        if got is None or got != want:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        if pid in (me, keep):
            continue
        found.append(pid)
    return found


def stop_other_fill_processes(keep: Optional[int] = None, grace_s: float = 8.0) -> list[int]:
    """SIGTERM (arrêt propre entre deux familles) puis SIGKILL aux remplisseurs concurrents du MÊME stock.
    Jamais sous pytest / CI : un test ne touche pas aux processus de la machine."""
    import signal as _signal  # noqa: PLC0415
    import time as _time  # noqa: PLC0415
    if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("CI"):
        return []
    pids = other_fill_processes(keep)
    for pid in pids:
        try:
            os.kill(pid, _signal.SIGTERM)
        except OSError:
            pass
    if pids:
        deadline = _time.monotonic() + grace_s
        while _time.monotonic() < deadline and any(_alive(p) for p in pids):
            _time.sleep(0.5)
        for pid in pids:
            if _alive(pid):
                try:
                    os.kill(pid, _signal.SIGKILL)
                except OSError:
                    pass
        log.warning("stock officiel : %d remplisseur(s) concurrent(s) arrêté(s) : %s", len(pids), pids)
    return pids


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def ensure_fill_process() -> Optional[int]:
    """Lance le remplisseur s'il ne tourne pas. Jamais de calcul dans l'API. Un seul remplisseur par machine :
    les autres (anciens worktrees, doubles) sont arrêtés d'abord."""
    import subprocess  # noqa: PLC0415
    import sys as _sys  # noqa: PLC0415
    with _LOCK:
        pid = fill_process_alive()
        try:
            stop_other_fill_processes(keep=pid)
        except Exception as exc:  # jamais bloquant
            log.warning("stock officiel : ménage des remplisseurs impossible : %s", exc)
        if pid:
            return pid
        if not FILL_SCRIPT.exists():
            log.warning("stock officiel : %s absent — pas de remplisseur", FILL_SCRIPT)
            return None
        # Le remplisseur est de l'arrière-plan (NAVIGUIDE_LLM_BACKGROUND=1). En on-demand le chat / le
        # préchauffage restent muets ; le rédigé du film (RG11A) passe par deferred_demand().
        env = {**os.environ, "NAVIGUIDE_OFFICIAL_STORE_DIR": str(disk_root()), "NAVIGUIDE_OFFICIAL_WORKER": "0",
               "NAVIGUIDE_LLM_BACKGROUND": "1"}
        try:
            fill_logfile().parent.mkdir(parents=True, exist_ok=True)
            logf = open(fill_logfile(), "a", encoding="utf-8")   # noqa: SIM115 — hérité par l'enfant
            p = subprocess.Popen(
                [_sys.executable, str(FILL_SCRIPT), "--loop", "--period", str(int(max(60.0, PERIOD_S))), "--nice", str(FILL_NICE),
                 "--store", str(disk_root())],
                cwd=str(FILL_SCRIPT.parents[1]), env=env, stdout=logf, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, start_new_session=True,
            )
            logf.close()
        except Exception as exc:
            log.warning("stock officiel : remplisseur non lancé : %s", exc)
            return None
        try:
            fill_pidfile().write_text(f"{p.pid}\n{FILL_SCRIPT}\n{_fill_script_stamp()}\n", encoding="utf-8")
        except OSError:
            pass
        log.info("stock officiel : remplisseur lancé (pid %s, nice %s, période %s s)", p.pid, FILL_NICE, int(PERIOD_S))
        return p.pid


_LAST_NUDGE_AT = None


def _nudge_min_s() -> float:
    """Plancher entre deux réveils. 0 = chaque kick écrit le fichier (tests)."""
    try:
        return max(0.0, float(os.environ.get("NAVIGUIDE_FILL_NUDGE_MIN_S") or 180))
    except ValueError:
        return 180.0


def _nudge_due() -> bool:
    """True une fois par fenêtre. /ici/moment rate souvent une perle (une toutes les 12 nm,
    recherche à 8 nm) et appelait kick_worker à chaque position : `ps -ax` sous le verrou,
    plus un passage du remplisseur de 12 à 30 s. L'API ne répondait plus, Cloudflare renvoyait 524."""
    global _LAST_NUDGE_AT
    gap = _nudge_min_s()
    now = time.monotonic()
    with _LOCK:
        # None = jamais réveillé. 0.0 ferait `now - 0 < 180` tant que le
        # processus a moins de 3 min (pytest CI ~90 s) : aucun réveil.
        if gap and _LAST_NUDGE_AT is not None and now - _LAST_NUDGE_AT < gap:
            return False
        _LAST_NUDGE_AT = now
        return True


def nudge_fill_process() -> None:
    """Demande un passage tout de suite : le remplisseur surveille la date de ce fichier.

    Le plafond est dans kick_worker, pas ici : un appel direct écrit toujours.
    """
    try:
        f = fill_nudgefile()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(_iso(_utc_now()), encoding="utf-8")
    except OSError:
        pass


def start_worker() -> None:
    """Au boot. Mode process (défaut) : lance le remplisseur externe. Mode thread : fil daemon (tests)."""
    global _WORKER_STARTED
    if not worker_enabled():
        return
    if WORKER_MODE != "thread":
        ensure_fill_process()
        return
    with _LOCK:
        if _WORKER_STARTED:
            return
        _WORKER_STARTED = True
    threading.Thread(target=_worker_loop, name="naviguide-official-store", daemon=True).start()


def _force_film_once() -> None:
    """Au boot / premier kick : recalcule le script RF5. Pas à chaque passage."""
    global _FILM_FORCED
    with _LOCK:
        if _FILM_FORCED:
            return
        _FILM_FORCED = True
    try:
        refresh_family("film", force=True)
    except Exception:
        log.exception("stock officiel : force film")
        with _LOCK:
            _FILM_FORCED = False


def kick_worker() -> None:
    """Relance un passage en fond — le client n'attend pas, et l'API ne calcule pas (mode process).

    En mode process, un seul réveil toutes les NAVIGUIDE_FILL_NUDGE_MIN_S secondes :
    ensure_fill_process fait un `ps -ax` sous le verrou, et le remplisseur tient le disque
    12 à 30 s même quand le stock est déjà prêt.
    """
    if not worker_enabled():
        return
    if WORKER_MODE != "thread":
        if not _nudge_due():
            return
        ensure_fill_process()
        nudge_fill_process()
        return
    start_worker()
    threading.Thread(
        target=_kick_refresh,
        name="naviguide-official-store-kick",
        daemon=True,
    ).start()


_LAST_REPAIR_AT = None


def _repair_due() -> bool:
    """Même plancher que les réveils (NAVIGUIDE_FILL_NUDGE_MIN_S), fenêtre distincte."""
    global _LAST_REPAIR_AT
    gap = _nudge_min_s()
    now = time.monotonic()
    with _LOCK:
        if gap and _LAST_REPAIR_AT is not None and now - _LAST_REPAIR_AT < gap:
            return False
        _LAST_REPAIR_AT = now
        return True


def today_climo_missing(now: Optional[datetime] = None) -> bool:
    """Vrai si la clé climo du jour UTC n'est pas rangée (une entrée d'hier ne compte pas)."""
    voy = _load_official()
    if voy is None:
        return False
    st = get_store()
    when = now or st._now()
    hit = st.get("climo", st.family_key("climo", voy, when))
    return not (hit and hit.get("payload") is not None)


def repair_worker() -> None:
    """Réparation bon marché sur le chemin visiteur (PUT anonyme).

    Au plus une fois par fenêtre : relance le remplisseur s'il est mort, et ne le
    réveille que si le climo du jour manque (nouveau jour UTC). Jamais de calcul ici.
    """
    if not worker_enabled():
        return
    if not _repair_due():
        return
    missing = today_climo_missing()
    if WORKER_MODE != "thread":
        ensure_fill_process()
        if missing:
            nudge_fill_process()
        return
    if missing:
        kick_worker()
    else:
        start_worker()


def _kick_refresh() -> None:
    refresh_missing()
    _force_film_once()


def _worker_loop() -> None:
    try:
        refresh_missing()
        _force_film_once()
    except Exception:
        log.exception("stock officiel : premier passage")
    while True:
        time.sleep(max(60.0, PERIOD_S))
        try:
            refresh_missing()
        except Exception:
            log.exception("stock officiel : passage périodique")


def reset_worker_flag() -> None:
    global _WORKER_STARTED, _FILM_FORCED, _LAST_NUDGE_AT, _LAST_REPAIR_AT
    _WORKER_STARTED = False
    _FILM_FORCED = False
    _LAST_REPAIR_AT = None
    _LAST_NUDGE_AT = None


# ── lecture pour les routes ──────────────────────────────────────────────────

def _journal_row_key(entry: dict) -> str:
    return str(entry.get("id") or entry.get("signature") or f"{entry.get('kind')}:{entry.get('t')}")


def _merge_journal_rows(*pools: list) -> list:
    """Longest pool keeps its order. Rows only the others have are added, newest first."""
    lists = []
    for pool in pools:
        rows = [e for e in (pool or []) if isinstance(e, dict) and e.get("t")]
        lists.append(rows)
    if not lists:
        return []
    base = max(lists, key=len)
    seen = {_journal_row_key(e) for e in base}
    extra = []
    for rows in lists:
        for entry in rows:
            key = _journal_row_key(entry)
            if key in seen:
                continue
            seen.add(key)
            extra.append(entry)
    if not extra:
        return list(base)
    merged = list(base) + extra
    merged.sort(key=lambda e: (str(e.get("t") or ""), 1 if e.get("kind") == "note" else 0), reverse=True)
    return merged


def _journal_day_names(*sources) -> list:
    names = []
    for source in sources:
        if isinstance(source, dict):
            names.extend(str(k) for k in source.keys())
            continue
        for item in source or []:
            if isinstance(item, str) and len(item) >= 10:
                names.append(item[:10] if "T" in item else item)
            elif isinstance(item, dict):
                day = item.get("day") or (str(item.get("t") or "")[:10] if item.get("t") else None)
                if day:
                    names.append(str(day))
    return sorted({n for n in names if n and len(n) >= 10})


def serve_journal(limit: int = 50, kinds: Optional[tuple] = None) -> dict:
    from voyage_clock import OFFICIAL_VOYAGE_ID  # noqa: PLC0415
    import voyage_journal as journal  # noqa: PLC0415

    extra = {
        "voyageId": OFFICIAL_VOYAGE_ID,
        "days": [], "count": 0, "first": None, "last": None,
        "latest": [], "events": [], "kinds": list(journal.KINDS),
    }
    hit = get("moments")
    body = hit.get("payload") if hit and isinstance(hit.get("payload"), dict) else None
    if not body:
        return preparing_payload("moments", extra)
    summary = dict(body.get("journal") or {})
    latest = list(summary.get("latest") or [])
    events = list(summary.get("events") or [])
    if kinds:
        latest = [e for e in latest if (e or {}).get("kind") in kinds]
        events = [e for e in events if (e or {}).get("kind") in kinds]
    day_rows: list = []
    journal_days = body.get("journal_days") or {}
    if isinstance(journal_days, dict):
        for day in sorted(journal_days):
            day_rows.extend(e for e in (journal_days.get(day) or []) if isinstance(e, dict))
    if kinds:
        day_rows = [e for e in day_rows if e.get("kind") in kinds]
    live_rows: list = []
    try:
        live_rows = journal.entries_until(datetime.now(timezone.utc), kinds=kinds)
    except Exception:
        live_rows = []
    merged = _merge_journal_rows(latest, live_rows, list(reversed(day_rows)))
    day_names = _journal_day_names(summary.get("days") or [], journal_days, merged)
    try:
        day_names = _journal_day_names(day_names, journal.list_days())
    except Exception:
        pass
    day_objs = []
    counts: dict = {}
    for entry in merged:
        day = str(entry.get("t") or "")[:10]
        if len(day) >= 10:
            counts[day] = counts.get(day, 0) + 1
    for name in day_names:
        day_objs.append({"day": name, "count": counts.get(name, 0)})
    cap = max(1, int(limit))
    summary.update({
        "voyageId": OFFICIAL_VOYAGE_ID,
        "status": READY,
        "latest": merged[:cap],
        "events": events,
        "days": day_objs or list(summary.get("days") or []),
        "count": max(int(summary.get("count") or 0), len(merged)),
        "first": day_objs[0]["day"] if day_objs else summary.get("first"),
        "last": day_objs[-1]["day"] if day_objs else summary.get("last"),
        "kinds": list(journal.KINDS),
        **_stamp(hit),
    })
    return summary


def serve_journal_day(day: str) -> Optional[list]:
    body = payload_of("moments")
    if not body:
        return None
    days = body.get("journal_days") or {}
    return days.get(day)


def _rows_from_journal(body: dict) -> list:
    """Même journal (tick réel) au format attendu par l'onglet Journal (signature)."""
    from voyage_clock import OFFICIAL_VOYAGE_ID  # noqa: PLC0415

    days = body.get("journal_days") or {}
    raw: list = []
    if days:
        for day in sorted(days):
            raw.extend(e for e in (days.get(day) or []) if isinstance(e, dict))
    if not raw:
        journal = body.get("journal") or {}
        raw = list(journal.get("events") or []) + list(journal.get("latest") or [])
    rows = []
    seen = set()
    for e in raw:
        t = e.get("t")
        if not t:
            continue
        sig = str(e.get("id") or e.get("signature") or f"{e.get('kind')}:{t}")
        if sig in seen:
            continue
        seen.add(sig)
        lat, lon = e.get("lat"), e.get("lon")
        title = e.get("title")
        if isinstance(title, dict):
            title = title.get("fr") or title.get("en")
        fact = e.get("name") or ""
        kind = e.get("kind") or ""
        changes = []
        if kind and kind != "position":
            changes.append({
                "kind": kind, "score": 1,
                "title": str(title or kind), "fact": str(fact),
            })
        rows.append({
            "voyageId": OFFICIAL_VOYAGE_ID,
            "seq": len(rows),
            "t": t,
            "signature": sig,
            "pos": {"lat": lat, "lon": lon} if lat is not None and lon is not None else None,
            "changes": changes,
            "moment": e,
        })
    return rows


def serve_moments(until: Optional[str] = None) -> dict:
    from voyage_clock import OFFICIAL_VOYAGE_ID  # noqa: PLC0415
    from moment_journal import _iso_le  # noqa: PLC0415

    extra = {"voyageId": OFFICIAL_VOYAGE_ID, "until": until, "count": 0, "moments": []}
    hit = get("moments")
    body = hit.get("payload") if hit and isinstance(hit.get("payload"), dict) else None
    if not body:
        return preparing_payload("moments", extra)
    stored = list(body.get("moments") or [])
    from_journal = _rows_from_journal(body)
    sqlite_rows: list = []
    try:
        from moment_journal import read_moments  # noqa: PLC0415
        sqlite_rows = list(read_moments(OFFICIAL_VOYAGE_ID) or [])
    except Exception:
        sqlite_rows = []
    primary = stored or from_journal or sqlite_rows
    seen = set()
    rows = []

    def _add(row) -> None:
        if not isinstance(row, dict):
            return
        key = str(row.get("signature") or row.get("id") or row.get("t") or id(row))
        if key in seen:
            return
        seen.add(key)
        rows.append(row)

    for pool in (primary, stored, sqlite_rows):
        for row in pool or []:
            _add(row)
    # Journal lines are the same facts as the moments, one row per fact: they
    # only fill the days no moment covers, never a second copy of a day.
    covered = {str(row.get("t") or "")[:10] for row in rows}
    for row in from_journal:
        if isinstance(row, dict) and str(row.get("t") or "")[:10] not in covered:
            _add(row)
    if until:
        rows = [row for row in rows if _iso_le(row.get("t"), until)]
    return {
        "voyageId": OFFICIAL_VOYAGE_ID,
        "until": until,
        "count": len(rows),
        "moments": rows,
        "status": READY,
        **_stamp(hit),
    }


def _is_written_style(style: str) -> bool:
    return str(style or "raw").strip().lower() in {"written", "nemotron", "rédigé", "redige"}


def _pick_written_plan(body: dict, lang: str, seconds: int) -> Optional[dict]:
    """Variante written exacte pour (lang, seconds) — pas de voisin, sinon le brut."""
    written = body.get("written") if isinstance(body.get("written"), dict) else {}
    by = written.get(lang) or {}
    if not isinstance(by, dict):
        return None
    want = str(int(seconds or 0))
    plan = by.get(want)
    if isinstance(plan, dict) and (plan.get("chapters") or []):
        return plan
    return None


def _iter_raw_film_variants(body: dict):
    variants = body.get("variants") if isinstance(body.get("variants"), dict) else {}
    yielded = False
    if variants:
        for lang, by_secs in variants.items():
            if not isinstance(by_secs, dict):
                continue
            for secs, plan in by_secs.items():
                if isinstance(plan, dict) and (plan.get("chapters") or []):
                    yielded = True
                    yield str(lang), str(secs), plan
    if yielded:
        return
    for lang in ("fr", "en"):
        plan = body.get(lang) or body.get("default")
        if isinstance(plan, dict) and (plan.get("chapters") or []):
            yield lang, str(int(plan.get("targetSeconds") or 0)), plan


def _stored_last_stop() -> str:
    body = payload_of("moments") or {}
    journal = body.get("journal") if isinstance(body.get("journal"), dict) else {}
    latest = list(journal.get("latest") or [])
    for row in reversed(latest):
        if not isinstance(row, dict):
            continue
        if row.get("kind") == "stop" or row.get("event") == "arrival":
            name = str(row.get("name") or row.get("title") or "").strip()
            if name:
                return name
    for row in reversed(list(body.get("moments") or [])):
        if not isinstance(row, dict):
            continue
        moment = row.get("moment") if isinstance(row.get("moment"), dict) else {}
        leg = moment.get("leg") if isinstance(moment.get("leg"), dict) else {}
        name = str(row.get("name") or leg.get("to") or "").strip()
        if name:
            return name
    film = payload_of("film") or {}
    plan = film.get("fr") or film.get("default") or {}
    chapters = plan.get("chapters") or []
    if chapters and isinstance(chapters[-1], dict):
        return str(chapters[-1].get("toName") or "")
    return ""


def _written_is_fresh(entry: Any, day: str, last_stop: str) -> bool:
    if not isinstance(entry, dict) or not (entry.get("chapters") or []):
        return False
    if str(entry.get("writtenDay") or "") != day:
        return False
    return str(entry.get("lastStop") or "") == str(last_stop or "")


def _log_fill_written(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    log.info("%s", msg)
    try:
        path = fill_logfile()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


def fill_written_film(
    *,
    force: bool = False,
    cascade=None,
    now: Optional[datetime] = None,
) -> dict:
    """Le remplisseur ne paie plus Super ni Ultra. Le rédigé part au clic."""
    _ = force, cascade, now
    _log_fill_written("written : ED1 — au clic seulement, remplisseur ne paie pas Super ni Ultra")
    return {"status": "click-only", "written": 0, "rewritten": 0, "fallen": 0}


def _raw_plan_for(body: dict, lang: str, seconds: int) -> Optional[dict]:
    variants = body.get("variants") if isinstance(body.get("variants"), dict) else {}
    by = variants.get(lang) or variants.get("fr") or {}
    if isinstance(by, dict):
        want = str(int(seconds or 0))
        plan = by.get(want)
        if isinstance(plan, dict) and (plan.get("chapters") or []):
            return plan
        keys = sorted(int(k) for k in by if str(k).lstrip("-").isdigit())
        pick = _pick_variant_key(keys, int(seconds or 0))
        if pick is not None:
            plan = by.get(str(pick))
            if isinstance(plan, dict) and (plan.get("chapters") or []):
                return plan
    plan = body.get(lang) or body.get("default") or body.get("fr")
    if isinstance(plan, dict) and (plan.get("chapters") or []):
        return plan
    return None


def _put_written_variant(body: dict, lang: str, seconds: int, plan: dict, when: datetime, last_stop: str) -> dict:
    written_map = dict(body.get("written") or {}) if isinstance(body.get("written"), dict) else {}
    lang_map = dict(written_map.get(lang) or {}) if isinstance(written_map.get(lang), dict) else {}
    stamped = dict(plan)
    stamped["hasWritten"] = True
    stamped["source"] = stamped.get("source") or WRITTEN_SOURCE
    stamped["writtenAt"] = _iso(when)
    stamped["writtenDay"] = _data_date(when)
    stamped["lastStop"] = last_stop
    lang_map[str(int(seconds or 0))] = stamped
    written_map[lang] = lang_map
    new_body = dict(body)
    new_body["written"] = written_map
    return new_body


async def attach_film_web_context(
    *,
    now: Optional[datetime] = None,
    client=None,
) -> Optional[dict]:
    """Clic Rédigé : provenance Tavily du dernier port du film, rangée dans le snapshot.

    Une recherche par port et par jour au plus (cache de port_web_context,
    plafond `llm_budget.allow_tavily`). Ni clé, ni plafond, ni résultat :
    rien n'est rangé et le film ne montre aucune source. Jamais au GET.
    """
    try:
        import film_web_context  # noqa: PLC0415

        hit = get("film")
        body = hit.get("payload") if hit and isinstance(hit.get("payload"), dict) else None
        if not isinstance(body, dict):
            return None
        port = _stored_last_stop()
        ctx = await film_web_context.fetch_for_port(port, now=now, client=client)
        if ctx is None:
            return film_web_context.public(body.get("webContext"))
        if body.get("webContext") != ctx:
            new_body = dict(body)
            new_body["webContext"] = ctx
            put("film", new_body, hit.get("key"))
        return ctx
    except Exception as exc:  # la source web ne bloque jamais le film
        log.warning("film web context: %s", exc)
        return None


def _with_film_web_context(out: dict, body: Optional[dict]) -> dict:
    """Champ `webContext` (+ `webSources`) servi avec le film, s'il est rangé."""
    import film_web_context  # noqa: PLC0415

    ctx = film_web_context.public((body or {}).get("webContext"))
    if ctx:
        out["webContext"] = ctx
        out["webSources"] = [dict(s) for s in ctx["sources"]]
    return out


# Idée n° 3 (IDEATION-CRITERES-0615) : reçu « Comment ce film a été fait ».
# Seulement ce que le serveur a réellement compté pendant la chaîne du clic :
# chaque appel de la cascade (palier, source, id de modèle, cache), les phrases
# réécrites ou retombées sur les règles, la relecture et ses défauts.
_RECEIPT_STAT_INTS = ("rewritten", "fallen", "super", "ultra_edit", "ultra_judge", "lightning")


def _receipt_recorder(cascade_fn):
    calls: list[dict] = []

    async def recorded(*args, **kwargs):
        result = await cascade_fn(*args, **kwargs)
        try:
            source = str(result[1] or "")
        except Exception:
            source = ""
        calls.append({
            "tier": str(getattr(result, "tier", "") or kwargs.get("tier") or ""),
            "source": source,
            "model": str(getattr(result, "model", "") or ""),
            "cache": bool(getattr(result, "cache_hit", False)) or source == "cache",
        })
        return result

    return recorded, calls


def film_receipt(calls: list[dict], stats: Optional[dict], when: datetime, base: Optional[dict] = None) -> dict:
    """Reçu public du rédigé : compteurs mesurés, jamais un chiffre estimé ni inventé."""
    st = stats if isinstance(stats, dict) else {}
    prev = base if isinstance(base, dict) else {}
    models: dict[tuple, dict] = {}
    for row in prev.get("models") or []:
        if isinstance(row, dict):
            k = (row.get("model") or "", row.get("source") or "", row.get("tier") or "")
            models[k] = dict(row)
    llm = int(prev.get("llmCalls") or 0)
    cached = int(prev.get("cacheHits") or 0)
    rules = int(prev.get("ruleFallbacks") or 0)
    for c in calls:
        src = c.get("source") or ""
        if src in {"rules", "budget"}:
            rules += 1
            continue
        if c.get("cache"):
            cached += 1
        else:
            llm += 1
        k = (c.get("model") or "", src, c.get("tier") or "")
        row = models.setdefault(k, {"model": k[0], "source": k[1], "tier": k[2], "calls": 0, "cached": 0})
        row["calls"] += 1
        if c.get("cache"):
            row["cached"] = int(row.get("cached") or 0) + 1
    out: dict[str, Any] = {k: v for k, v in prev.items() if k not in {"models", "llmCalls", "cacheHits", "ruleFallbacks", "at"}}
    out.update({
        "llmCalls": llm,
        "cacheHits": cached,
        "ruleFallbacks": rules,
        "models": sorted(models.values(), key=lambda r: (-int(r["calls"]), r["model"], r["source"])),
        "at": _iso(when),
    })
    for key in _RECEIPT_STAT_INTS:
        if isinstance(st.get(key), (int, bool)):
            out[key] = int(st[key])
    for key in ("reread", "reread_en"):
        if st.get(key) in {"pass", "fail"}:
            out[key] = st[key]
    if isinstance(st.get("reviewed"), bool):
        out["reviewed"] = st["reviewed"]
    if "faults" in st:
        out["faults"] = len(st.get("faults") or [])
    if isinstance(st.get("judge_failed"), list):
        out["judgeFailed"] = len(st["judge_failed"])
    return out


# One bilingual film write per duration. SQLite shares reservations and state
# between API workers using the same official store directory.
_FILM_WRITE_TASKS: dict[tuple[str, int], asyncio.Task] = {}
_FILM_WRITE_FAILED: set[tuple[str, int]] = set()
# A write normally completes well before this; older reservations are assumed
# abandoned after a process restart and become eligible for retry.
FILM_WRITE_STALE_AFTER = timedelta(minutes=15)


def _film_write_db() -> Path:
    store = get_store()
    backend = getattr(store, "backend", None)
    root = getattr(backend, "root", None) or disk_root()
    path = Path(root) / "film-write-tasks.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path, timeout=10) as db:
        db.execute("CREATE TABLE IF NOT EXISTS film_write_tasks (seconds INTEGER PRIMARY KEY, status TEXT NOT NULL, owner_pid INTEGER, updated_at TEXT NOT NULL)")
    return path


def _film_write_state(seconds: int, *, now: datetime | None = None) -> str | None:
    with sqlite3.connect(_film_write_db(), timeout=10) as db:
        row = db.execute("SELECT status, owner_pid, updated_at FROM film_write_tasks WHERE seconds=?", (seconds,)).fetchone()
        if not row:
            return None
        status, owner_pid, updated_at = row
        if status == "writing":
            try:
                written_at = datetime.fromisoformat(str(updated_at).replace("Z", "+00:00"))
                if written_at.tzinfo is None:
                    written_at = written_at.replace(tzinfo=timezone.utc)
                current = now or _utc_now()
                if current.tzinfo is None:
                    current = current.replace(tzinfo=timezone.utc)
                if current.astimezone(timezone.utc) - written_at.astimezone(timezone.utc) >= FILM_WRITE_STALE_AFTER:
                    db.execute("UPDATE film_write_tasks SET status='failed', owner_pid=NULL, updated_at=? WHERE seconds=? AND status='writing'", (_iso(current), seconds))
                    return "failed"
            except (TypeError, ValueError, OverflowError):
                # An unreadable timestamp cannot establish that a write is fresh.
                db.execute("UPDATE film_write_tasks SET status='failed', owner_pid=NULL, updated_at=? WHERE seconds=? AND status='writing'", (_iso(now), seconds))
                return "failed"
        if status == "writing" and owner_pid != os.getpid():
            try:
                os.kill(int(owner_pid), 0)
            except (OSError, TypeError, ValueError):
                db.execute("UPDATE film_write_tasks SET status='failed', owner_pid=NULL, updated_at=? WHERE seconds=? AND status='writing'", (_iso(), seconds))
                return "failed"
        return status


def _set_film_write_state(seconds: int, status: str) -> None:
    with sqlite3.connect(_film_write_db(), timeout=10) as db:
        db.execute(
            "INSERT INTO film_write_tasks(seconds,status,owner_pid,updated_at) VALUES(?,?,?,?) "
            "ON CONFLICT(seconds) DO UPDATE SET status=excluded.status, owner_pid=excluded.owner_pid, updated_at=excluded.updated_at",
            (seconds, status, os.getpid() if status == "writing" else None, _iso()),
        )


def film_write_running(lang: str, seconds: int) -> bool:
    """Check if a film write task is running for the given key."""
    key = ("pair", int(seconds or 0))
    task = _FILM_WRITE_TASKS.get(key)
    return (task is not None and not task.done()) or _film_write_state(seconds) == "writing"


async def start_film_write(
    lang: str = "fr",
    seconds: int = 150,
    *,
    cascade=None,
    now: Optional[datetime] = None,
) -> dict:
    """Start async film write, return cache immediately if ready, else launch background task.
    
    Returns: {...cached, status:"writing", writing:true, hasWritten:false, targetSeconds}
    """
    import llm_budget  # noqa: PLC0415
    from film_script import write_film_chain  # noqa: PLC0415

    lg = (lang or "fr")[:2].lower()
    secs = int(seconds or 0)
    key = (lg, secs)
    task_key = ("pair", secs)

    # Check cache first — if written film ready, serve it immediately
    cached = serve_film(lang=lg, seconds=secs, style="written")
    if cached.get("hasWritten") and cached.get("status") == READY:
        return cached

    # If a task is already running for this key, return writing status
    existing_task = _FILM_WRITE_TASKS.get(task_key)
    if existing_task and not existing_task.done():
        return {
            **cached,
            "status": "writing",
            "writing": True,
            "hasWritten": False,
            "targetSeconds": secs,
        }
    if _film_write_state(secs) == "writing":
        return {**cached, "status": "writing", "writing": True, "hasWritten": False, "targetSeconds": secs}

    if llm_budget.mode() == "off":
        _log_fill_written(f"written clic {lg} {secs}s : mode off — brut servi")
        return serve_film(lang=lg, seconds=secs, style="written")

    hit = get("film")
    body = hit.get("payload") if hit and isinstance(hit.get("payload"), dict) else None
    if not isinstance(body, dict):
        return serve_film(lang=lg, seconds=secs, style="written")

    when = now or _utc_now()
    last_stop = _stored_last_stop()
    fr_raw = _raw_plan_for(body, "fr", secs)
    if not isinstance(fr_raw, dict) or not (fr_raw.get("chapters") or []):
        return serve_film(lang=lg, seconds=secs, style="written")
    en_raw = _raw_plan_for(body, "en", secs)

    cascade_fn = cascade
    if cascade_fn is None:
        from story_cascade import cascade_text  # noqa: PLC0415
        cascade_fn = cascade_text
    cascade_fn, receipt_calls = _receipt_recorder(cascade_fn)

    if not llm_budget.allow("write"):
        _log_fill_written(f"written clic {lg} {secs}s : plafond write — brut")
        return serve_film(lang=lg, seconds=secs, style="written")

    # Reserve synchronously before creating/yielding to the background task.
    # BEGIN IMMEDIATE serializes competing processes; the duration is the key
    # because each job generates FR and EN together.
    db = sqlite3.connect(_film_write_db(), timeout=10, isolation_level=None)
    try:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT status, updated_at FROM film_write_tasks WHERE seconds=?", (secs,)).fetchone()
        if row and row[0] == "writing":
            try:
                reserved_at = datetime.fromisoformat(str(row[1]).replace("Z", "+00:00"))
                if reserved_at.tzinfo is None:
                    reserved_at = reserved_at.replace(tzinfo=timezone.utc)
                current = _utc_now()
                if current - reserved_at.astimezone(timezone.utc) < FILM_WRITE_STALE_AFTER:
                    db.execute("ROLLBACK")
                    return {**cached, "status": "writing", "writing": True, "hasWritten": False, "targetSeconds": secs}
            except (TypeError, ValueError, OverflowError):
                db.execute("ROLLBACK")
                return {**cached, "status": "writing", "writing": True, "hasWritten": False, "targetSeconds": secs}
        db.execute("INSERT INTO film_write_tasks(seconds,status,owner_pid,updated_at) VALUES(?,?,?,?) ON CONFLICT(seconds) DO UPDATE SET status=excluded.status, owner_pid=excluded.owner_pid, updated_at=excluded.updated_at", (secs, "writing", os.getpid(), _iso()))
        db.execute("COMMIT")
    finally:
        db.close()

    _FILM_WRITE_FAILED.discard(("fr", secs))
    _FILM_WRITE_FAILED.discard(("en", secs))

    # Launch background task
    async def _write_task():
        try:
            # Tavily au clic Rédigé : dans la tâche de fond pour ne pas bloquer le POST.
            await attach_film_web_context(now=when)
            fr_plan, en_plan, stats = await write_film_chain(
                fr_raw, seconds=secs, cascade=cascade_fn, en_raw=en_raw,
            )
            fr_ok = isinstance(fr_plan, dict) and bool(fr_plan.get("chapters") or [])
            en_ok = isinstance(en_plan, dict) and bool(en_plan.get("chapters") or [])
            if not fr_ok and not en_ok:
                _log_fill_written(f"written clic {lg} {secs}s : pas de rédigé ({stats.get('source')})")
                _FILM_WRITE_FAILED.add(key)
                _FILM_WRITE_FAILED.add(("en", secs))
                _set_film_write_state(secs, "failed")
                return
            receipt = film_receipt(receipt_calls, stats, when)
            if fr_ok:
                fr_plan = {**fr_plan, "receipt": receipt}
            # Re-fetch hit and body to avoid UnboundLocalError from closure rebinding
            hit = get("film")
            body = hit.get("payload") if hit and isinstance(hit.get("payload"), dict) else None
            if not isinstance(body, dict):
                _set_film_write_state(secs, "failed")
                return
            if fr_ok:
                body = _put_written_variant(body, "fr", secs, fr_plan, when, last_stop)
            if en_ok:
                en_plan = {**en_plan, "receipt": receipt}
                body = _put_written_variant(body, "en", secs, en_plan, when, last_stop)
            put("film", body, hit.get("key"))
            for language, succeeded in (("fr", fr_ok), ("en", en_ok)):
                result_key = (language, secs)
                if succeeded:
                    _FILM_WRITE_FAILED.discard(result_key)
                else:
                    _FILM_WRITE_FAILED.add(result_key)
            _set_film_write_state(secs, "ready" if fr_ok or en_ok else "failed")
            _log_fill_written(
                f"written clic {lg} {secs}s : source={stats.get('source')} "
                f"ultra={stats.get('ultra_edit')}/{stats.get('ultra_judge')} lightning={stats.get('lightning')}"
            )
        except Exception as exc:
            log.exception("Film write task failed for %s %ds", lg, secs)
            _FILM_WRITE_FAILED.add(key)
            _FILM_WRITE_FAILED.add(("en", secs))
            _set_film_write_state(secs, "failed")
        finally:
            # Clean up task reference
            _FILM_WRITE_TASKS.pop(task_key, None)

    task = asyncio.create_task(_write_task())
    _FILM_WRITE_TASKS[task_key] = task

    # Return immediately with writing status; hasWritten=False until 1st successful poll (docstring l. 2997)
    return {
        **cached,
        "status": "writing",
        "writing": True,
        "hasWritten": False,
        "targetSeconds": secs,
    }


async def write_film_on_click(
    lang: str = "fr",
    seconds: int = 150,
    *,
    cascade=None,
    now: Optional[datetime] = None,
) -> dict:
    """Chaîne Super → Ultra? → Lightning, une fois par (langue, durée). Au clic seulement."""
    import llm_budget  # noqa: PLC0415
    from film_script import write_film_chain  # noqa: PLC0415

    lg = (lang or "fr")[:2].lower()
    secs = int(seconds or 0)
    # Tavily au clic Rédigé (règle hackathon : appel à l'exécution, visible dans le film).
    await attach_film_web_context(now=now)
    cached = serve_film(lang=lg, seconds=secs, style="written")
    if cached.get("hasWritten") and cached.get("status") == READY:
        return cached

    if llm_budget.mode() == "off":
        _log_fill_written("written clic : mode off — brut servi")
        return serve_film(lang=lg, seconds=secs, style="written")

    hit = get("film")
    body = hit.get("payload") if hit and isinstance(hit.get("payload"), dict) else None
    if not isinstance(body, dict):
        return serve_film(lang=lg, seconds=secs, style="written")

    when = now or _utc_now()
    last_stop = _stored_last_stop()
    fr_raw = _raw_plan_for(body, "fr", secs)
    if not isinstance(fr_raw, dict) or not (fr_raw.get("chapters") or []):
        return serve_film(lang=lg, seconds=secs, style="written")
    en_raw = _raw_plan_for(body, "en", secs)

    cascade_fn = cascade
    if cascade_fn is None:
        from story_cascade import cascade_text  # noqa: PLC0415
        cascade_fn = cascade_text
    cascade_fn, receipt_calls = _receipt_recorder(cascade_fn)

    if not llm_budget.allow("write"):
        _log_fill_written(f"written clic {lg} {secs}s : plafond write — brut")
        return serve_film(lang=lg, seconds=secs, style="written")

    fr_plan, en_plan, stats = await write_film_chain(
        fr_raw, seconds=secs, cascade=cascade_fn, en_raw=en_raw,
    )
    if not isinstance(fr_plan, dict) or not (fr_plan.get("chapters") or []):
        _log_fill_written(f"written clic {lg} {secs}s : pas de rédigé ({stats.get('source')})")
        unavailable = serve_film(lang=lg, seconds=secs, style="written")
        if stats.get("super", 0) == 0 and stats.get("source") == "rules":
            unavailable["reason"] = "all-providers-failed"
        return unavailable
    receipt = film_receipt(receipt_calls, stats, when)
    fr_plan = {**fr_plan, "receipt": receipt}
    body = _put_written_variant(body, "fr", secs, fr_plan, when, last_stop)
    if isinstance(en_plan, dict) and (en_plan.get("chapters") or []):
        en_plan = {**en_plan, "receipt": receipt}
        body = _put_written_variant(body, "en", secs, en_plan, when, last_stop)
    put("film", body, hit.get("key"))
    _log_fill_written(
        f"written clic {lg} {secs}s : source={stats.get('source')} "
        f"ultra={stats.get('ultra_edit')}/{stats.get('ultra_judge')} lightning={stats.get('lightning')}"
    )
    return serve_film(lang=lg, seconds=secs, style="written")


def _repair_served_hop(plan: Optional[dict], lang: str, voy: Optional[dict]) -> Optional[dict]:
    """Snapshot déjà en stock : la jambe Halifax dit ses milles, pas l'odomètre."""
    if not isinstance(plan, dict) or not isinstance(voy, dict):
        return plan
    from film_script import _stored_review_and_eta, repair_side_hop_plan  # noqa: PLC0415

    clock = voy.get("clock") if isinstance(voy.get("clock"), dict) else None
    marks = voy.get("marks") if isinstance(voy.get("marks"), list) else None
    try:
        review, _eta = _stored_review_and_eta()
    except Exception:
        review = None
    return repair_side_hop_plan(plan, clock=clock, marks=marks, review=review, lang=lang)


def serve_film(lang: str = "fr", seconds: int = 0, style: str = "raw") -> dict:
    # Check if a write task failed for this key
    lg = (lang or "fr")[:2].lower()
    secs = int(seconds or 0)
    # A failed written pass must never hide the already available raw film.
    state = _film_write_state(secs) if _is_written_style(style) else None
    if _is_written_style(style) and (state == "failed" or (lg, secs) in _FILM_WRITE_FAILED):
        return {
            "status": "failed",
            "hasWritten": False,
            "style": "written",
        }
    if _is_written_style(style) and state == "writing":
        return {"status": "writing", "writing": True, "hasWritten": False, "style": "written", "targetSeconds": secs}

    extra = {
        "chapters": [], "source": "rules", "chars": 0,
        "targetSeconds": seconds, "hasWritten": False,
    }
    voy = _load_official()
    hit = get("film")
    body = hit.get("payload") if hit and isinstance(hit.get("payload"), dict) else None
    if not _payload_has_chapters(body):
        hit = _newest_film_hit()
        body = hit.get("payload") if hit and isinstance(hit.get("payload"), dict) else None
    if not _payload_has_chapters(body):
        return preparing_payload("film", extra)
    if film_snapshot_stale(body, voy):
        body = _patch_air_on_film(body, voy)
    # Un script déjà écrit se joue. Une phrase d'avion manquante ne bloque pas Revoir.
    lg = (lang or "fr")[:2].lower()
    plan = None
    variants = body.get("variants") if isinstance(body.get("variants"), dict) else {}
    by_secs = variants.get(lg) or variants.get("fr") or {}
    if by_secs:
        want = int(seconds or 0)
        keys = sorted(
            int(k) for k in by_secs
            if str(k).lstrip("-").isdigit()
        )
        pick = _pick_variant_key(keys, want)
        if pick is not None:
            plan = by_secs.get(str(pick))
    if plan is None:
        plan = body.get(lg) or body.get("default") or body.get("fr")
    if not isinstance(plan, dict) or not (plan.get("chapters") or []):
        return preparing_payload("film", extra)
    stored_est = body.get("estimates") if isinstance(body.get("estimates"), dict) else {}
    lang_est = stored_est.get(lg) or stored_est.get("fr") or _variants_estimates({lg: by_secs}).get(lg)
    if _is_written_style(style):
        wplan = _pick_written_plan(body, lg, int(seconds or 0))
        if isinstance(wplan, dict) and (wplan.get("chapters") or []):
            wplan = _repair_served_hop(wplan, lg, voy)
            out = _with_film_estimate(wplan)
            if isinstance(lang_est, dict) and lang_est:
                out["estimates"] = lang_est
            out["status"] = READY
            out["hasWritten"] = True
            from film_script import public_written_source  # noqa: PLC0415
            raw_source = wplan.get("source")
            out["source"] = public_written_source(raw_source) or WRITTEN_SOURCE
            reviewed = wplan.get("reviewedBy")
            if not reviewed and str(raw_source or "") == REVIEWED_SOURCE:
                reviewed = REVIEWED_BY_ULTRA
            if reviewed:
                out["reviewedBy"] = reviewed
            if wplan.get("model"):
                out["model"] = wplan["model"]
            if wplan.get("generated_at"):
                out["generated_at"] = wplan["generated_at"]
            if isinstance(wplan.get("receipt"), dict):
                out["receipt"] = wplan["receipt"]
            out["writtenAt"] = wplan.get("writtenAt")
            out["style"] = "written"
            _with_film_web_context(out, body)
            out.update(_stamp(hit))
            return out
    out = _with_film_estimate(_repair_served_hop(plan, lg, voy))
    if isinstance(lang_est, dict) and lang_est:
        out["estimates"] = lang_est
    out["status"] = READY
    out["hasWritten"] = False
    out["source"] = out.get("source") or "rules"
    out["style"] = "raw"
    rev = body.get("film_script_rev")
    if rev:
        out["film_script_rev"] = rev
    _with_film_web_context(out, body)
    out.update(_stamp(hit))
    return out


def _serve_eta_stop(payload: dict, stamp: dict) -> dict:
    out = dict(payload)
    try:
        members = int(out.get("members") or 0)
    except (TypeError, ValueError):
        members = 0
    ready = members > 0 and bool(out.get("p10")) and bool(out.get("p90"))
    if ready:
        out["status"] = READY
        out["members"] = members
    else:
        out["status"] = out.get("status") if out.get("status") == UNAVAILABLE else UNAVAILABLE
        if not out.get("reason") or out.get("reason") == "en préparation":
            from ensemble_eta import explain_eta_reason  # noqa: PLC0415
            out["reason"] = explain_eta_reason(out)
        out["p10"] = None if members <= 0 else out.get("p10")
        out["p50"] = None if members <= 0 else out.get("p50")
        out["p90"] = None if members <= 0 else out.get("p90")
        if members <= 0:
            out["members"] = 0
    out.update(stamp)
    return out


def serve_eta(stop: str) -> dict:
    from ensemble_eta import empty_eta  # noqa: PLC0415

    empty = empty_eta(_utc_now(), reason="en préparation")
    empty["status"] = PREPARING
    hit = get("eta")
    body = hit.get("payload") if hit and isinstance(hit.get("payload"), dict) else None
    if not body:
        return empty
    stamp = _stamp(hit)
    stops = body.get("stops") or {}
    if stop in stops and isinstance(stops[stop], dict):
        return _serve_eta_stop(stops[stop], stamp)
    needle = (stop or "").strip().lower()
    for name, payload in stops.items():
        if needle and needle in name.lower() and isinstance(payload, dict):
            return _serve_eta_stop(payload, stamp)
    return empty


def serve_plan_review() -> dict:
    extra = {"legs": []}
    hit = get("plan_review")
    body = hit.get("payload") if hit and isinstance(hit.get("payload"), dict) else None
    if not body:
        return preparing_payload("plan_review", extra)
    out = dict(body)
    out["status"] = READY
    out.update(_stamp(hit))
    return out


def serve_climo() -> Optional[dict]:
    return payload_of("climo")


def append_note_to_store(note: dict) -> None:
    """Écriture humaine : on met à jour le snapshot, on ne recalcule rien."""
    body = payload_of("moments")
    if not body:
        return
    payload = json.loads(json.dumps(body))
    journal = payload.setdefault("journal", {})
    latest = journal.setdefault("latest", [])
    latest.insert(0, note)
    events = journal.setdefault("events", [])
    events.insert(0, note)
    journal["count"] = int(journal.get("count") or 0) + 1
    day = (note.get("t") or "")[:10]
    if day:
        days = payload.setdefault("journal_days", {})
        days.setdefault(day, []).append(note)
    put("moments", payload)
