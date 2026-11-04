"""Sac `ici()` — ce qu’il y a autour du bateau, pas toute la carte.

ZEE, PoE, AMP, projets, marinas-capit-WPI, mouillages OSM, Science,
AtoN, satellites CDSE, EMODnet au point, GRIB2/Open-Meteo, GEBCO,
climatologie. Accès moteur au point — pas de dump GeoJSON monde.
Le sac reste hors LLM ; le juge de vérité relit une fiche
PoE Gold via `truth_judge.maybe_attach` — cache 7 jours, jamais une
suppression de texte. La veille et les phrases sourcées sont
rattachées depuis le cache (`escale_watch.attach_cached`), sans réseau.
"""
from __future__ import annotations

import asyncio
import logging
import math
import re
import time
from typing import Any

import httpx

from climatology_atlas import wind_from_point
from climatology_zones import zone_wind_at
from gebco_lookup import attach_depth_offshore, reset_gebco_cache
from longitude import delta_lon, wrap_lon
from ici_layers import (
    attach_derived_from_science,
    climatology_rose,
    empty_aton,
    empty_emodnet,
    empty_review,
    empty_satellites,
    empty_weather,
    fetch_aton,
    fetch_emodnet_point,
    fetch_overpass_harbours,
    fetch_review,
    fetch_satellite_scene,
    layer_code,
    reset_rtofs_cache,
    snapshot_ici_weather,
)
from bi_upstream import BiDisabled, bi_base
from weather_pipeline import bind_weather_transport, get_pipeline

log = logging.getLogger("naviguide-simulator.ici")

ICI_RADIUS_NM = 30
MAX_POE = 4
MAX_AMP = 5
MAX_PROJECTS = 5
MAX_NEARBY = 3
# Invalide les perles sans couche projects / AMP filtrées.
# La clé y ajoute aussi la signature de la couche AMP (`a{total}`).
# Bumper pour recalculer les perles figées avec amp: [] (revue #482).
PEARL_REV = "am1a"
AMP_NEAR_NM = 30.0
PROJECT_NEAR_NM = 30.0
# Cellule 1° + GET /amp. TTL 1 jour (mémoire + kv).
AMP_CELL_TTL_S = 86_400.0
AMP_SIG_TTL_S = 86_400.0
# Juste au-dessus du plafond backend (8°) : Mongo cache, pas ProtectedSeas.
# Une boîte de ±1° (2°) passerait par ArcGIS si la tuile n'est pas enregistrée.
AMP_BBOX_SPAN_DEG = 8.1
AMP_KV_NS = "amp-bbox"
AMP_SIG_NS = "amp"
AMP_SIG_KEY = "layer_sig"
# Zones de réglementation de pêche — jamais une AMP (D4 / A3).
_AMP_FISHING_RE = re.compile(
    r"\b(?:chaluts?|filets?|hu[iî]tres?|p[ée]toncles?|deposit|licence|license|"
    r"prohibition|zone de p[êe]che)\b",
    re.I,
)
# Juridiction / ORGP servies comme « AMP » par ProtectedSeas : pas un parc.
_AMP_JURISDICTION_RE = re.compile(
    r"\b(?:territorial sea|national waters|exclusive economic zone|\beez\b|"
    r"international commission for the conservation of atlantic tunas|\biccat\b|\biotc\b|"
    r"gfcm fisheries|"
    r"tuna commission|"
    r"fisher(?:y|ies) (?:commission|committee|organization|organisation|agreement)|"
    r"regional fisheries|"
    r"salmon conservation|"
    r"south pacific regional fisheries)\b",
    re.I,
)
# Aire protégée : IUCN renseignée, ou désignation WDPA / parc / réserve / sanctuaire.
_AMP_PROTECT_RE = re.compile(
    r"\b(?:wdpa|iucn|parc naturel marin|parc marin|marine natural park|"
    r"national park|parc national|r[ée]serve(?: naturelle)?|sanctuaire|sanctuary|"
    r"aire marine prot[ée]g[ée]e|protected area|\bmpa\b)\b",
    re.I,
)
_AMP_IUCN_RE = re.compile(r"\biucn\b", re.I)
_AMP_DATASET_TAIL_RE = re.compile(
    r"\s*[-–—:]\s*(?:center|centre|permanent|deposit|licence|license|"
    r"prohibition|zone de p[êe]che)\b.*$",
    re.I,
)
_AMP_TECH_PAREN_RE = re.compile(
    r"\s*\((?:unassigned|wdpa:?\s*\d+|iucn[^)]*|cat(?:egory)?\s*[ivx0-9]+)\)\s*",
    re.I,
)
MAX_ANCHORAGES = 5
MAX_SCIENCE = 5
EEZ_ACCEPT_NM = 240
R_NM = 3440.065

# Path-style (query LatLng has been 404 since 2026).
MRGID_LATLON_URL = "https://www.marineregions.org/rest/getGazetteerRecordsByLatLong.json"
USER_AGENT = "NAVIGUIDE-simulator/0.2 (Berry-Mappemonde expedition)"
WPI_URL = "https://msi.nga.mil/api/publications/world-port-index"

# MRGID VLIZ v12 → territoire FR (copie locale, pas d’import backend/).
FRENCH_EEZ_MRGID: dict[int, str] = {
    5677: "france_metropolitaine",
    48966: "france_metropolitaine",
    48976: "france_metropolitaine",
    8440: "polynesie_francaise",
    8312: "nouvelle_caledonie",
    48948: "nouvelle_caledonie",
    33178: "martinique",
    33177: "guadeloupe",
    48952: "saint_barthelemy",
    8495: "saint_martin",
    8462: "guyane",
    8454: "wallis_et_futuna",
    8338: "la_reunion",
    48944: "mayotte",
    8494: "saint_pierre_et_miquelon",
    48946: "taaf",
    48945: "taaf",
    8341: "taaf",
    8339: "taaf",
    8340: "taaf",
    8386: "taaf",
    8385: "taaf",
    8387: "taaf",
}

_DMS_RE = re.compile(
    r"""(\d+)\s*[°d]\s*(\d+)\s*[''′]\s*(\d+(?:\.\d+)?)\s*[""″]?\s*([NSEW]?)""",
    re.IGNORECASE,
)

_fc_cache: dict[str, dict] = {}
_FC_TTL = 3600.0
_wpi_cache: dict = {"data": None, "ts": 0.0}
_WPI_TTL = 86_400.0
_amp_cell_cache: dict[str, dict] = {}
_amp_sig: dict[str, Any] = {"value": "0", "ts": 0.0, "ok": False}

# Pearls (the along bags, 12 nm apart) are the same for every visitor and
# every replay of the film: one lookup per 0.02° cell. Two kinds:
# `thin` (ZEE, ports of entry, MPA, projects, harbours — 7 days) and `rich`
# (every layer without a timestamp: + science, anchorages, aton, EMODnet —
# 30 days). Memory is an L1 in front of the SQLite store (pearl_store); a
# rich pearl serves a thin request. Without it a fast playback asked
# MarineRegions + Overpass thousands of times. RG3 : projects aussi en thin
# (parité avec le sac « ici » du panneau).
_thin_cache: dict[str, dict] = {}
_THIN_TTL = 7 * 86400.0
_RICH_TTL = 30 * 86400.0
_THIN_MAX = 20_000
PEARL_KINDS = ("thin", "rich")


def amp_layer_sig() -> str:
    """Signature de la couche AMP (total GET /amp/stats), pour la clé des perles."""
    return str(_amp_sig.get("value") or "0")


def set_amp_layer_sig(value: Any, *, ok: bool = True) -> None:
    _amp_sig["value"] = str(int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else (value or "0"))
    _amp_sig["ts"] = time.time()
    _amp_sig["ok"] = bool(ok)


def load_amp_layer_sig() -> str:
    """Lit la signature depuis la mémoire ou le kv (pas d'HTTP)."""
    now = time.time()
    if _amp_sig["ok"] and now - float(_amp_sig["ts"] or 0) < AMP_SIG_TTL_S:
        return amp_layer_sig()
    try:
        import pearl_store  # noqa: PLC0415
        row = pearl_store.kv_get(AMP_SIG_NS, AMP_SIG_KEY, max_age_s=AMP_SIG_TTL_S)
        val = (row or {}).get("value")
        total = val.get("total") if isinstance(val, dict) else val
        if total is not None and str(total) not in ("", "0"):
            set_amp_layer_sig(total, ok=True)
    except Exception:
        pass
    return amp_layer_sig()


def _pearl_cell(lat: float, lon: float) -> tuple[float, float]:
    return round(lat / 0.02) * 0.02, round(lon / 0.02) * 0.02


def _pearl_db_exists() -> bool:
    try:
        import pearl_store  # noqa: PLC0415
        return pearl_store.db_path().is_file()
    except Exception:
        return False


def store_amp_layer_suffixes() -> list[str]:
    """Suffixes `aNNNN` (N > 0) déjà présents dans les clés, du plus récent au plus ancien."""
    try:
        import pearl_store  # noqa: PLC0415
        return pearl_store.list_pearl_amp_layer_suffixes()
    except Exception:
        return []


def _known_amp_signatures() -> list[str]:
    """Signatures réelles connues. Si la mémoire en a déjà une, on ne relit pas tout le stock."""
    sig = amp_layer_sig()
    if sig not in ("", "0"):
        return [sig]
    return store_amp_layer_suffixes()


def ensure_pearl_amp_layer_sig(context: str = "") -> str:
    """Charge la signature (mémoire, kv, puis suffixes du stock) avant une clé de perle.

    Ne crée pas la base si elle n'existe pas encore. Ne retombe jamais sur « 0 »
    quand le stock contient déjà une signature réelle.
    """
    now = time.time()
    if (
        _amp_sig.get("ok")
        and amp_layer_sig() not in ("", "0")
        and now - float(_amp_sig.get("ts") or 0) < AMP_SIG_TTL_S
    ):
        return amp_layer_sig()
    if _pearl_db_exists():
        load_amp_layer_sig()
        sig = amp_layer_sig()
        if sig not in ("", "0"):
            return sig
        from_store = store_amp_layer_suffixes()
        if from_store:
            chosen = from_store[0]
            set_amp_layer_sig(chosen, ok=True)
            where = f" ({context})" if context else ""
            log.warning(
                "signature de couche absente%s — retenue a%s (en stock : %s)",
                where,
                chosen,
                ",".join(f"a{s}" for s in from_store[:8]),
            )
            return chosen
    return amp_layer_sig() or "0"


def refuse_pearl_key_with_zero_amp_suffix(key: str, context: str = "") -> None:
    """Refuse une écriture :a0 dès qu'une signature réelle est connue. Journalise le refus."""
    if not str(key or "").endswith(":a0"):
        return
    known = _known_amp_signatures()
    if not known:
        return
    msg = (
        f"refus clé perle {key!r} : suffixe a0"
        f"{(' (' + context + ')') if context else ''} "
        f"alors qu'une signature réelle existe ({', '.join('a' + s for s in known[:6])})"
    )
    log.warning("%s", msg)
    raise RuntimeError(msg)


def thin_cache_key(lat: float, lon: float, radius_nm: float, month: int | None = None) -> str:
    # A pearl carries no climatology: the month never changes it, so it is
    # not part of the key (the client sends month=9, the warmer none).
    # PEARL_REV force le remplisseur à recalculer (RG3 : projects + filtre AMP).
    # `a{sig}` invalide le stock quand la couche AMP change.
    del month
    la, lo = _pearl_cell(lat, lon)
    sig = ensure_pearl_amp_layer_sig("thin_cache_key")
    return f"{la:.2f}:{lo:.2f}:{int(radius_nm)}:{PEARL_REV}:a{sig}"


_PEARL_SUFFIX_RE = re.compile(r":a(\d+)$")
PEARL_NEIGHBOR_MAX_NM = 1.5


def _pearl_suffix_num(key: str) -> int:
    match = _PEARL_SUFFIX_RE.search(str(key or ""))
    if not match:
        return 0
    return int(match.group(1))


def _is_am1a_pearl_key(key: str) -> bool:
    text = str(key or "")
    return (
        f":{PEARL_REV}:" in text
        or text.endswith(f":{PEARL_REV}")
        or ":am1a:" in text
        or text.endswith(":am1a")
    )


def _is_rg3_pearl_key(key: str) -> bool:
    text = str(key or "")
    return ":rg3" in text and not _is_am1a_pearl_key(text)


def pearl_key_candidates(lat: float, lon: float, radius_nm: float = 30.0) -> list[str]:
    """Clés d'une cellule, dans l'ordre de lecture.

    1. `am1a:a<signature courante>`
    2. les autres clés am1a, de la perle la plus récente à la plus ancienne
    3. les clés rg3, même ordre
    4. la clé nue, puis le reste des clés de la cellule

    Une clé :a0 est omise dès qu'une signature réelle existe.
    Le voisin géographique n'est pas dans cette liste : il est consulté après, en lecture seule.
    """
    import pearl_store  # noqa: PLC0415

    sig = ensure_pearl_amp_layer_sig("pearl_key_candidates")
    la, lo = _pearl_cell(lat, lon)
    base = f"{la:.2f}:{lo:.2f}:{int(radius_nm)}"
    stored = pearl_store.list_pearl_key_times(base)
    real = bool(_known_amp_signatures())
    ranked: list[str] = []

    def add(key: str) -> None:
        if not key or key in ranked:
            return
        if real and str(key).endswith(":a0"):
            return
        ranked.append(key)

    if sig not in ("", "0"):
        add(f"{base}:{PEARL_REV}:a{sig}")
        add(f"{base}:am1a:a{sig}")

    def by_recency(item: tuple[str, float]) -> tuple[float, int]:
        key, ts = item
        return (float(ts or 0), _pearl_suffix_num(key))

    am1a = [item for item in stored if _is_am1a_pearl_key(item[0])]
    for key, _ts in sorted(am1a, key=by_recency, reverse=True):
        add(key)
    rg3 = [item for item in stored if _is_rg3_pearl_key(item[0])]
    for key, _ts in sorted(rg3, key=by_recency, reverse=True):
        add(key)
    add(f"{base}:rg3")
    add(base)
    rest = [item for item in stored if item[0] not in ranked]
    for key, _ts in sorted(rest, key=by_recency, reverse=True):
        add(key)
    return ranked


def resolve_pearl_row(lat: float, lon: float, radius_nm: float = 30.0) -> tuple[dict | None, str | None]:
    """Lit une perle : candidats de la cellule, puis le voisin à ≤ 1,5 nm. N'écrit rien."""
    import pearl_store  # noqa: PLC0415

    ensure_pearl_amp_layer_sig("resolve_pearl_row")
    for key in pearl_key_candidates(lat, lon, radius_nm):
        row = pearl_store.get_pearl(key)
        if row and isinstance(row.get("bag"), dict):
            return row, key
    real = bool(_known_amp_signatures())
    near_key, dist_nm = pearl_store.nearest_pearl_key(lat, lon)
    if real and near_key and str(near_key).endswith(":a0"):
        if dist_nm is not None and dist_nm <= PEARL_NEIGHBOR_MAX_NM:
            log.warning(
                "voisin perle %s ignoré : suffixe a0 (%.2f nm) alors qu'une signature réelle existe",
                near_key,
                dist_nm,
            )
        near_key, dist_nm = pearl_store.nearest_pearl_key(
            lat, lon, accept=lambda key: not str(key).endswith(":a0"),
        )
    if near_key and dist_nm is not None and dist_nm <= PEARL_NEIGHBOR_MAX_NM:
        if real and str(near_key).endswith(":a0"):
            return None, None
        row = pearl_store.get_pearl(near_key)
        if row and isinstance(row.get("bag"), dict):
            return row, near_key
    return None, None


def _pearl_ttl(kind: str) -> float:
    return _RICH_TTL if kind == "rich" else _THIN_TTL


def _fresh(hit: dict) -> bool:
    return time.time() - float(hit.get("ts") or 0) <= _pearl_ttl(hit.get("kind") or "thin")


def thin_cache_get(key: str, rich: bool = False) -> dict | None:
    """The cached pearl for `key`; with `rich=True`, only a rich one will do."""
    hit = _thin_cache.get(key)
    if hit is not None and not _fresh(hit):
        _thin_cache.pop(key, None)
        hit = None
    if hit is None:
        import pearl_store  # noqa: PLC0415
        row = pearl_store.get_pearl(key)
        if row and _fresh(row):
            hit = {"ts": row["ts"], "bag": row["bag"], "kind": row["kind"]}
            _remember(key, hit)
    if hit is None:
        return None
    if rich and hit.get("kind") != "rich":
        return None
    return hit["bag"]


def _remember(key: str, hit: dict) -> None:
    if len(_thin_cache) >= _THIN_MAX:
        # Drop the oldest tenth: cheap, rare, keeps memory bounded.
        for old in sorted(_thin_cache, key=lambda k: _thin_cache[k]["ts"])[: _THIN_MAX // 10]:
            _thin_cache.pop(old, None)
    _thin_cache[key] = hit


def thin_cache_put(key: str, bag: dict, kind: str = "thin", lat: float | None = None, lon: float | None = None) -> None:
    """Memory + SQLite (write-through). A rich pearl is never downgraded."""
    kind = kind if kind in PEARL_KINDS else "thin"
    cur = _thin_cache.get(key)
    if cur is not None and cur.get("kind") == "rich" and kind != "rich" and _fresh(cur):
        return
    try:
        refuse_pearl_key_with_zero_amp_suffix(key, "thin_cache_put")
    except RuntimeError:
        return
    hit = {"ts": time.time(), "bag": bag, "kind": kind}
    _remember(key, hit)
    import pearl_store  # noqa: PLC0415
    try:
        pearl_store.put_pearl(key, bag, kind, lat, lon, hit["ts"])
    except RuntimeError:
        _thin_cache.pop(key, None)
        return


def thin_cache_drop(key: str) -> None:
    """Forget one pearl (memory + store): the next fill collects it again."""
    _thin_cache.pop(key, None)
    import pearl_store  # noqa: PLC0415
    pearl_store.delete_pearl(key)


def reset_caches() -> None:
    _fc_cache.clear()
    _thin_cache.clear()
    _amp_cell_cache.clear()
    _amp_sig.update({"value": "0", "ts": 0.0, "ok": False})
    _layer_warm.update({
        "status": "idle",
        "cellsTotal": 0,
        "cellsDone": 0,
        "cellsCached": 0,
        "errors": 0,
    })
    _wpi_cache["data"] = None
    _wpi_cache["ts"] = 0.0
    reset_gebco_cache()
    reset_rtofs_cache()
    get_pipeline().clear()


def empty_dossier(lat: float, lon: float, radius_nm: float = ICI_RADIUS_NM) -> dict:
    return {
        "version": 1,
        "at": {"lat": lat, "lon": lon},
        "radiusNm": radius_nm,
        "zee": None,
        "poe": [],
        "amp": [],
        "projects": [],
        "nearby": {"marinas": [], "capitaineries": [], "wpi": [], "anchorages": []},
        "marks": [],
        "aton": empty_aton(),
        "science": None,
        "satellites": empty_satellites(),
        "weather": empty_weather(),
        "emodnet": empty_emodnet(),
        "review": empty_review(),
        "polar": None,
        "event": None,
        "climatology": None,
        "piracy": None,
        "sources": {
            "zee": None,
            "bi": None,
            "gebco": None,
            "climatology": None,
            "satellites": None,
            "weather": None,
            "emodnet": None,
            "aton": None,
            "anchorages": None,
            "review": None,
        },
        "depthOffshore": None,
    }


def parse_coord(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        pass
    m = _DMS_RE.search(s)
    if not m:
        return None
    deg, mins, secs, hemi = m.groups()
    decimal = float(deg) + float(mins) / 60.0 + float(secs) / 3600.0
    if hemi and hemi.upper() in ("S", "W"):
        decimal = -decimal
    return decimal


def haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    def rad(d: float) -> float:
        return d * math.pi / 180.0

    dlat = rad(lat2 - lat1)
    dlon = rad(delta_lon(lon1, lon2))
    a = math.sin(dlat / 2) ** 2 + math.cos(rad(lat1)) * math.cos(rad(lat2)) * math.sin(dlon / 2) ** 2
    return 2 * R_NM * math.asin(min(1.0, math.sqrt(a)))


def radius_bbox(lat: float, lon: float, nm: float) -> tuple[float, float, float, float]:
    dlat = nm / 60.0
    clat = max(0.2, abs(math.cos(math.radians(lat))))
    dlon = nm / (60.0 * clat)
    return lon - dlon, lat - dlat, lon + dlon, lat + dlat


def feature_latlon(feat: dict) -> tuple[float, float] | None:
    props = feat.get("properties") or {}
    plat, plon = props.get("lat"), props.get("lon")
    if isinstance(plat, (int, float)) and isinstance(plon, (int, float)):
        return float(plat), float(plon)
    geom = feat.get("geometry") or {}
    coords = geom.get("coordinates")
    kind = geom.get("type")
    if not coords:
        return None
    if kind == "Point" and len(coords) >= 2:
        return float(coords[1]), float(coords[0])

    def first_pair(node) -> tuple[float, float] | None:
        if not isinstance(node, (list, tuple)) or not node:
            return None
        if isinstance(node[0], (int, float)) and len(node) >= 2:
            return float(node[1]), float(node[0])
        return first_pair(node[0])

    return first_pair(coords)


def feature_name(feat: dict) -> str:
    p = feat.get("properties") or {}
    for key in ("name", "title", "site_name", "portName", "geoname", "pref_name"):
        val = p.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def feature_url(feat: dict) -> str | None:
    p = feat.get("properties") or {}
    urls = p.get("source_urls") or []
    if isinstance(urls, list) and urls:
        first = urls[0]
        if isinstance(first, str) and first.startswith("http"):
            return first
        if isinstance(first, dict) and str(first.get("url") or "").startswith("http"):
            return first["url"]
    visit = p.get("visit_url")
    if isinstance(visit, str) and visit.startswith("http"):
        return visit
    for key in ("url", "url_bu", "href"):
        val = p.get(key)
        if isinstance(val, str) and val.startswith("http"):
            return val
        if isinstance(val, dict) and str(val.get("url") or "").startswith("http"):
            return val["url"]
    return None


def slim_place(feat: dict, lat0: float, lon0: float, extra_keys: tuple[str, ...] = ()) -> dict | None:
    ll = feature_latlon(feat)
    if not ll:
        return None
    lat, lon = ll
    from toponyms import origin_name  # noqa: PLC0415
    name = origin_name(feature_name(feat))
    if not name:
        return None
    item = {
        "name": name,
        "lat": round(lat, 5),
        "lon": round(lon, 5),
        "nm": round(haversine_nm(lat0, lon0, lat, lon), 1),
        "url": feature_url(feat),
    }
    props = feat.get("properties") or {}
    for key in extra_keys:
        val = props.get(key)
        if val not in (None, ""):
            item[key] = val
    return item


AMP_KEYS = (
    "visit_url", "manager_url", "visit_url_status", "designation",
    "iucn_cat", "site_id", "id", "gold_on",
    "entry", "speed",
)
ANCHORAGE_KEYS = ("anchorage_type", "osm_id", "source", "priority")


def _amp_blob(item: dict) -> str:
    if not isinstance(item, dict):
        return ""
    parts = [
        item.get("name"), item.get("title"), item.get("fact"),
        item.get("designation"), item.get("iucn_cat"), item.get("iucn"),
        item.get("site_id"), item.get("id"),
    ]
    return " ".join(str(p) for p in parts if p not in (None, ""))


def is_fishing_amp(item: dict | None) -> bool:
    """Zone de réglementation de pêche (Chaluts, Pétoncles, deposit…), pas une AMP."""
    return bool(isinstance(item, dict) and _AMP_FISHING_RE.search(_amp_blob(item)))


def is_jurisdiction_amp(item: dict | None) -> bool:
    """Mer territoriale, ZEE, ICCAT… : une juridiction, pas un parc."""
    return bool(isinstance(item, dict) and _AMP_JURISDICTION_RE.search(_amp_blob(item)))


def is_protected_amp(item: dict | None) -> bool:
    """Aire protégée réelle : IUCN renseignée ou désignation WDPA / parc / réserve.

    Une zone de pêche est exclue même si elle porte un « IUCN Unassigned ».
    """
    if not isinstance(item, dict):
        return False
    if is_fishing_amp(item):
        return False
    iucn = item.get("iucn_cat") or item.get("iucn")
    if iucn not in (None, ""):
        return True
    blob = _amp_blob(item)
    return bool(_AMP_IUCN_RE.search(blob) or _AMP_PROTECT_RE.search(blob))


def spoken_amp_name(raw: Any, lang: str = "fr") -> str:
    """Nom parlé : pas de tiret de jeu de données, pas d'IUCN, pas d'anglais technique."""
    del lang
    s = re.sub(r"\s+", " ", str(raw or "")).strip()
    if not s:
        return ""
    s = re.sub(r"\s*\(\s*IUCN[^)]*\)", "", s, flags=re.I)
    s = re.sub(r"\bIUCN\s+\S+", "", s, flags=re.I)
    s = _AMP_TECH_PAREN_RE.sub(" ", s)
    s = _AMP_DATASET_TAIL_RE.sub("", s)
    s = re.sub(r"\s+", " ", s).strip(" :-—,;(")
    return s


def slim_amp(feat: dict, lat0: float, lon0: float) -> dict | None:
    item = slim_place(feat, lat0, lon0, extra_keys=AMP_KEYS)
    if not item:
        return None
    if is_fishing_amp(item):
        return None
    if item.get("visit_url"):
        item["url"] = item["visit_url"]
    from toponyms import origin_name  # noqa: PLC0415
    from amp_traffic import as_activity, traffic_kind  # noqa: PLC0415
    spoken = origin_name(spoken_amp_name(item.get("name")))
    if spoken:
        item["name"] = spoken
    props = feat.get("properties") or {}
    entry = as_activity(item.get("entry") if "entry" in item else props.get("entry"))
    speed = as_activity(item.get("speed") if "speed" in item else props.get("speed"))
    if entry is not None:
        item["entry"] = entry
    if speed is not None:
        item["speed"] = speed
    item["traffic"] = traffic_kind(entry, speed)
    return item


def amp_cell_key(lat: float, lon: float) -> str:
    """Cellule 1° (coin SW) pour le cache GET /amp."""
    lon = wrap_lon(lon)
    return f"{int(math.floor(lat))}:{int(math.floor(lon))}"


def amp_cell_bbox(lat: float, lon: float) -> str:
    """Boîte centrée sur la cellule, span 8,1° (cache Mongo, pas ArcGIS).

    La demande initiale était ±1° autour du point. Une telle boîte (2° < 8°) passe par
    `sites_in_bbox` et, tuile inconnue, chez ProtectedSeas (timeout observé).
    8,1° prend la branche cache du backend ; le filtre de portée reste shapely.
    """
    lon = wrap_lon(lon)
    clat = math.floor(lat) + 0.5
    clon = math.floor(lon) + 0.5
    half = AMP_BBOX_SPAN_DEG / 2.0
    minx, maxx = clon - half, clon + half
    miny, maxy = max(-90.0, clat - half), min(90.0, clat + half)
    minx = max(-180.0, minx)
    maxx = min(180.0, maxx)
    if maxx - minx <= 8.0:
        if minx <= -180.0 + 1e-9:
            maxx = min(180.0, minx + AMP_BBOX_SPAN_DEG)
        else:
            minx = max(-180.0, maxx - AMP_BBOX_SPAN_DEG)
    return f"{minx},{miny},{maxx},{maxy}"


def polygon_inside_and_nm(geom: dict, lat: float, lon: float) -> tuple[bool, float, float] | None:
    """Dedans / distance à la limite (milles) / aire (nm²), projection locale.

    x = Δlon × 60 × cos φ0, y = Δlat × 60 (même convention que `radius_bbox`).
    Précision : < 2 % à 1° du point, négligeable à 15–30 nm. Sphère, pas WGS84.
    """
    if not isinstance(geom, dict) or geom.get("type") not in ("Polygon", "MultiPolygon"):
        return None
    try:
        from shapely.geometry import Point, shape  # noqa: PLC0415
        from shapely.ops import transform  # noqa: PLC0415
    except Exception:
        return None
    try:
        g = shape(geom)
    except Exception:
        return None
    if g.is_empty:
        return None
    if not g.is_valid:
        try:
            g = g.buffer(0)
        except Exception:
            return None
        if g.is_empty:
            return None
    lon0 = wrap_lon(lon)
    k = 60.0 * math.cos(math.radians(lat))

    def _proj(x, y, z=None):
        del z
        return (delta_lon(lon0, x) * k, (float(y) - lat) * 60.0)

    try:
        g_nm = transform(_proj, g)
        origin = Point(0.0, 0.0)
        area = abs(float(g_nm.area))
        if g_nm.covers(origin):
            return True, 0.0, area
        return False, round(float(g_nm.distance(origin)), 1), area
    except Exception:
        return None


def slim_amp_entry(feat: dict, lat0: float, lon0: float, *, source: str) -> dict | None:
    """Entrée du sac amp : {name, siteId, inside, nm, source, visitUrl…}."""
    item = slim_amp(feat, lat0, lon0)
    if not item:
        return None
    if is_jurisdiction_amp(item):
        return None
    geom = feat.get("geometry") or {}
    entry_source = "export"
    inside = False
    nm = item.get("nm")
    area = None
    if source == "polygon":
        got = polygon_inside_and_nm(geom, lat0, lon0)
        if got is not None:
            inside, nm, area = got
            entry_source = "polygon"
    item["inside"] = bool(inside)
    item["nm"] = 0.0 if inside else round(float(nm if nm is not None else 0.0), 1)
    item["source"] = entry_source
    if area is not None:
        item["_area_nm2"] = area
    site = item.get("site_id") or item.get("id") or feat.get("id")
    if site not in (None, ""):
        item["siteId"] = site
        item.setdefault("site_id", site)
    visit = item.get("visit_url")
    if visit:
        item["visitUrl"] = visit
    return item


def nearest_amp(
    features: list,
    lat: float,
    lon: float,
    radius_nm: float,
    limit: int = MAX_AMP,
    source: str = "export",
) -> list[dict]:
    """AMP à portée : dedans d'abord, puis nm croissant. Plafond MAX_AMP."""
    found: list[dict] = []
    for feat in features or []:
        item = slim_amp_entry(feat, lat, lon, source=source)
        if not item:
            continue
        if item.get("inside") or float(item.get("nm") or 0) <= radius_nm + 0.05:
            found.append(item)
    found.sort(key=lambda x: (
        0 if x.get("inside") else 1,
        float(x.get("_area_nm2") or 0) if x.get("inside") else float(x.get("nm") if x.get("nm") is not None else 999),
        str(x.get("name") or ""),
    ))
    out = found[:limit]
    for item in out:
        item.pop("_area_nm2", None)
    return out


async def refresh_amp_layer_sig(client: httpx.AsyncClient) -> str:
    """GET /amp/stats → total, mémoire + kv. Échec : on garde l'ancienne signature."""
    load_amp_layer_sig()
    now = time.time()
    if _amp_sig["ok"] and now - float(_amp_sig["ts"] or 0) < AMP_SIG_TTL_S:
        return amp_layer_sig()
    if (not _amp_sig["ok"]) and _amp_sig["ts"] and now - float(_amp_sig["ts"] or 0) < 60.0:
        return amp_layer_sig()
    try:
        data = await _get_json(client, f"{bi_base()}/amp/stats", timeout=4.0)
        total = data.get("total") if isinstance(data, dict) else None
        if total is None:
            raise ValueError("amp/stats sans total")
        set_amp_layer_sig(int(total), ok=True)
        try:
            import pearl_store  # noqa: PLC0415
            pearl_store.kv_put(AMP_SIG_NS, AMP_SIG_KEY, {"total": int(total)})
        except Exception:
            pass
        return amp_layer_sig()
    except Exception as exc:
        log.debug("signature AMP indisponible : %s", exc)
        if not _amp_sig["ok"]:
            _amp_sig["ts"] = now
        return amp_layer_sig()


async def _amp_cell_features(client: httpx.AsyncClient, lat: float, lon: float) -> list:
    """Features GET /amp pour la cellule 1° (mémoire, puis kv, puis réseau).

    Une liste vide n'est pas un succès : on ne la grave ni en mémoire ni en kv
    (un 200 froid empoisonnerait la cellule un jour). Le caller bascule alors
    sur l'export, comme pour un 5xx.
    """
    key = amp_cell_key(lat, lon)
    now = time.time()
    hit = _amp_cell_cache.get(key)
    if hit and now - float(hit.get("ts") or 0) < AMP_CELL_TTL_S:
        cached = hit.get("features")
        if isinstance(cached, list) and cached:
            return cached
    try:
        import pearl_store  # noqa: PLC0415
        row = pearl_store.kv_get(AMP_KV_NS, key, max_age_s=AMP_CELL_TTL_S)
        val = (row or {}).get("value")
        feats = val.get("features") if isinstance(val, dict) else None
        # Un GET vide ne se grave pas : sinon une API encore froide
        # empoisonne la cellule pour un jour.
        if isinstance(feats, list) and feats:
            _amp_cell_cache[key] = {"ts": row["ts"], "features": feats}
            return feats
    except Exception:
        pass
    bbox = amp_cell_bbox(lat, lon)
    data = await _get_json(client, f"{bi_base()}/amp", params={"bbox": bbox}, timeout=20.0)
    feats = data.get("features") if isinstance(data, dict) else []
    if not isinstance(feats, list):
        feats = []
    if not feats:
        raise ValueError("GET /amp vide")
    _amp_cell_cache[key] = {"ts": now, "features": feats}
    try:
        import pearl_store  # noqa: PLC0415
        pearl_store.kv_put(AMP_KV_NS, key, {"features": feats, "bbox": bbox})
    except Exception:
        pass
    return feats


async def fetch_amp_features(client: httpx.AsyncClient, lat: float, lon: float) -> tuple[list, str]:
    """Polygones GET /amp, sinon export centroïdes. Lève seulement si les deux tombent.

    Un 200 vide est traité comme un 5xx : on bascule sur l'export (`source: export`).
    """
    amp_err: Exception | None = None
    try:
        feats = await _amp_cell_features(client, lat, lon)
        if feats:
            return feats, "polygon"
        amp_err = ValueError("GET /amp vide")
        log.debug("GET /amp vide, repli export")
    except Exception as exc:
        amp_err = exc
        log.debug("GET /amp indisponible, repli export : %s", exc)
    try:
        feats = await _cached_fc(client, f"{bi_base()}/export/amp.geojson")
        return feats, "export"
    except Exception as exc:
        log.debug("export AMP indisponible : %s", exc)
        if amp_err is not None:
            raise amp_err from exc
        raise


# Couches le long d'un trait : pas le monde, pas les perles Berry.
LAYER_WARM_MAX_CELLS = 80
LAYER_WARM_PAUSE_S = 0.2
_layer_warm: dict[str, Any] = {
    "status": "idle",
    "cellsTotal": 0,
    "cellsDone": 0,
    "cellsCached": 0,
    "errors": 0,
}


def layer_warm_status() -> dict[str, Any]:
    return dict(_layer_warm)


def accept_layer_warm(points: list) -> dict[str, Any]:
    """Accepte un trait si aucun chauffage de couches n'est déjà en cours."""
    if _layer_warm.get("status") in ("running", "queued"):
        return {**layer_warm_status(), "accepted": False}
    cells = amp_cells_from_points(points)
    _layer_warm.update({
        "status": "queued",
        "cellsTotal": len(cells),
        "cellsDone": 0,
        "cellsCached": 0,
        "errors": 0,
    })
    return {**layer_warm_status(), "accepted": True}


def amp_cells_from_points(points: list) -> list[tuple[float, float]]:
    """Centres des cellules 1° uniques touchées par le trait, dans l'ordre."""
    seen: dict[str, tuple[float, float]] = {}
    order: list[str] = []
    for item in points or []:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        try:
            lat, lon = float(item[0]), wrap_lon(float(item[1]))
        except (TypeError, ValueError):
            continue
        if not (-90.0 <= lat <= 90.0):
            continue
        key = amp_cell_key(lat, lon)
        if key in seen:
            continue
        seen[key] = (math.floor(lat) + 0.5, math.floor(lon) + 0.5)
        order.append(key)
        if len(order) >= LAYER_WARM_MAX_CELLS:
            break
    return [seen[k] for k in order]


async def warm_amp_cells_along(points: list) -> dict[str, Any]:
    """Remplit le cache GET /amp (mémoire + kv) pour les cellules du trait."""
    cells = amp_cells_from_points(points)
    _layer_warm.update({
        "status": "running",
        "cellsTotal": len(cells),
        "cellsDone": 0,
        "cellsCached": 0,
        "errors": 0,
    })
    if not cells:
        _layer_warm["status"] = "done"
        return layer_warm_status()
    async with httpx.AsyncClient() as http:
        await refresh_amp_layer_sig(http)
        for lat, lon in cells:
            key = amp_cell_key(lat, lon)
            try:
                hit = _amp_cell_cache.get(key)
                already = bool(hit and (hit.get("features") or []))
                if not already:
                    feats = await _amp_cell_features(http, lat, lon)
                    already = bool(feats)
                if already:
                    _layer_warm["cellsCached"] = int(_layer_warm["cellsCached"]) + 1
            except Exception as exc:
                _layer_warm["errors"] = int(_layer_warm["errors"]) + 1
                log.debug("couche AMP %.1f,%.1f : %s", lat, lon, exc)
            _layer_warm["cellsDone"] = int(_layer_warm["cellsDone"]) + 1
            await asyncio.sleep(LAYER_WARM_PAUSE_S)
    _layer_warm["status"] = "done"
    return layer_warm_status()


def slim_anchorage(feat: dict, lat0: float, lon0: float) -> dict | None:
    return slim_place(feat, lat0, lon0, extra_keys=ANCHORAGE_KEYS)


def slim_science(feat: dict, lat0: float, lon0: float) -> dict | None:
    item = slim_place(
        feat, lat0, lon0,
        extra_keys=("source", "kind", "type", "wmo", "provider", "doi", "method", "error_m"),
    )
    if not item:
        return None
    props = feat.get("properties") or {}
    if not item.get("source"):
        if props.get("kind") == "argo_float":
            item["source"] = "argo"
        elif props.get("kind") == "cruise":
            item["source"] = "csr"
    return item


# Types parlables seulement. Jamais un titre de jeu de données.
_SCI_TYPE_LABELS = {
    "argo": {"fr": "un flotteur Argo", "en": "an Argo float"},
    "pelgas": {"fr": "la campagne PELGAS", "en": "the PELGAS campaign"},
    "campaign": {"fr": "une campagne", "en": "a research cruise"},
    "buoy": {"fr": "une bouée", "en": "a buoy"},
    "coastal": {"fr": "une station côtière", "en": "a coastal station"},
    "observatory": {"fr": "un observatoire", "en": "an observatory"},
}
_SCI_EVENT_KINDS = frozenset({"station", "sci", "science", "nearby"})
_SCI_ARGO_KIND = frozenset({"argo", "argo_float"})
_SCI_CRUISE_KIND = frozenset({"cruise", "campagne", "campaign"})
_SCI_BUOY_KIND = frozenset({"buoy", "mooring", "bouee", "bouée"})
_SCI_OBS_KIND = frozenset({"observatory", "observatoire"})
_SCI_CTD_KIND = frozenset({"ctd"})


def _science_blob(item: dict) -> str:
    entity = item.get("entity") if isinstance(item.get("entity"), dict) else {}
    facts = item.get("facts") if isinstance(item.get("facts"), dict) else {}
    parts = [
        item.get("source"), item.get("kind"), item.get("type"), item.get("sciKind"),
        item.get("name"), item.get("title"), item.get("fact"),
        entity.get("source"), entity.get("sciKind"),
        facts.get("source"), facts.get("kind"), facts.get("name"),
        item.get("provider"),
    ]
    return " ".join(str(part) for part in parts if part).casefold()


def science_type_key(item: dict | None) -> str:
    """Type depuis source / kind / mots du titre. Vide = la station ne se dit pas."""
    if not isinstance(item, dict):
        return ""
    entity = item.get("entity") if isinstance(item.get("entity"), dict) else {}
    facts = item.get("facts") if isinstance(item.get("facts"), dict) else {}
    source = str(item.get("source") or entity.get("source") or facts.get("source") or "").casefold()
    kind = str(item.get("sciKind") or item.get("type") or "").casefold()
    raw_kind = str(item.get("kind") or "").casefold()
    if raw_kind not in _SCI_EVENT_KINDS:
        kind = kind or raw_kind
    if kind in _SCI_EVENT_KINDS:
        kind = ""
    blob = _science_blob(item)
    if source == "argo" or kind in _SCI_ARGO_KIND or re.search(r"\bargo\b", blob):
        return "argo"
    if re.search(r"\bpelgas", blob):
        return "pelgas"
    if (
        source in {"buoy", "mooring"}
        or kind in _SCI_BUOY_KIND
        or re.search(r"\b(buoy|bou[ée]e|mooring|pirata)\b", blob)
    ):
        return "buoy"
    if kind in _SCI_OBS_KIND or re.search(r"\bobservator(?:y|ies)\b|\bobservatoire", blob):
        return "observatory"
    if kind in _SCI_CTD_KIND or re.search(r"\bctd\b", blob):
        return "coastal"
    if source == "csr" or kind in _SCI_CRUISE_KIND or re.search(r"\b(campagne|cruise)\b", blob):
        return "campaign"
    return ""


def spoken_science_type(item: dict | None, lang: str = "fr") -> str:
    """Libellé parlé FR/EN du type, ou vide. Jamais le titre brut."""
    key = science_type_key(item)
    if not key:
        return ""
    labels = _SCI_TYPE_LABELS[key]
    return labels["en"] if str(lang or "").lower().startswith("en") else labels["fr"]


def nearest_places(
    features: list,
    lat: float,
    lon: float,
    radius_nm: float,
    limit: int,
    extra_keys: tuple[str, ...] = (),
    slim=None,
) -> list[dict]:
    slim_fn = slim or (lambda f, a, b: slim_place(f, a, b, extra_keys))
    found: list[dict] = []
    for feat in features or []:
        item = slim_fn(feat, lat, lon)
        if item and item["nm"] <= radius_nm + 0.05:
            found.append(item)
    found.sort(key=lambda x: x["nm"])
    return found[:limit]


def _place_type(rec: dict) -> str:
    return str(rec.get("placeType") or rec.get("place_type") or "").upper()


def eez_records(records: list) -> list[dict]:
    return [rec for rec in records or [] if _place_type(rec) == "EEZ"]


def pick_eez_record(records: list) -> dict | None:
    found = eez_records(records)
    return found[0] if found else None


def eez_plausible(rec: dict | None, lat: float, lon: float) -> bool:
    """Le gazetteer colle parfois une ZEE lointaine (bbox immense). On garde
    seulement si le point représentatif est à portée d’une ZEE (~200 nm)."""
    if not rec or _place_type(rec) != "EEZ":
        return False
    try:
        elat = float(rec.get("latitude"))
        elon = float(rec.get("longitude"))
    except (TypeError, ValueError):
        return False
    return haversine_nm(lat, lon, elat, elon) <= EEZ_ACCEPT_NM


def zee_unknown() -> dict:
    """No answer about the EEZ (lookup failed): never read as high seas."""
    return {"name": None, "mrgid": None, "territory": None, "gold": False, "unknown": True}


def zee_from_record(rec: dict | None) -> dict:
    if not rec:
        return {"name": "Haute mer", "mrgid": None, "territory": None, "gold": False}
    name = rec.get("preferredGazetteerName") or rec.get("name") or "ZEE"
    raw = rec.get("MRGID") or rec.get("mrgid")
    try:
        mrgid = int(raw) if raw is not None else None
    except (TypeError, ValueError):
        mrgid = None
    territory = FRENCH_EEZ_MRGID.get(mrgid) if mrgid is not None else None
    from toponyms import names_for  # noqa: PLC0415
    spoken = names_for(name, mrgid=mrgid, territory=territory)
    out = {
        "name": name,
        "mrgid": mrgid,
        "territory": territory,
        "gold": False,
    }
    if spoken:
        out["names"] = spoken
    return out


async def _gazetteer_list(client: httpx.AsyncClient, lat: float, lon: float) -> list:
    r = await client.get(
        f"{MRGID_LATLON_URL}/{lat:.5f}/{lon:.5f}/",
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=8.0,
    )
    r.raise_for_status()
    payload = r.json()
    return payload if isinstance(payload, list) else []


def _first_plausible(records: list, lat: float, lon: float) -> dict | None:
    for rec in eez_records(records):
        if eez_plausible(rec, lat, lon):
            return rec
    return None


async def lookup_zee(client: httpx.AsyncClient, lat: float, lon: float) -> tuple[dict | None, str]:
    """ZEE autour du bateau. Désormais : point-dans-polygone local sur
    les ZEE VLIZ (`zee_local`, source « vliz-local ») ; le gazetteer
    MarineRegions ne sert plus que de repli tant que la couche n'est pas
    chargée. Repli : un point à quai n’est parfois pas dans le polygone, on
    sonde alors 8 points à ~12 nm ; une ZEE trop loin est refusée → haute mer."""
    try:
        import zee_local  # noqa: PLC0415
        local = zee_local.zee_at(lat, lon)
        if local is not zee_local.UNKNOWN:
            return (local if local is not None else zee_from_record(None)), "vliz-local"
    except Exception as exc:  # the local layer never breaks a bag
        log.debug("ZEE locale indisponible : %s", exc)
    try:
        here = await _gazetteer_list(client, lat, lon)
        rec = _first_plausible(here, lat, lon)
        if rec:
            return zee_from_record(rec), "marineregions"
        if eez_records(here):
            return zee_from_record(None), "marineregions"
        ashore = _ashore_from_records(here)
        step = 0.2
        probes = [
            (lat, lon - step), (lat, lon + step),
            (lat - step, lon), (lat + step, lon),
            (lat - step, lon - step), (lat - step, lon + step),
            (lat + step, lon - step), (lat + step, lon + step),
        ]
        found = await asyncio.gather(
            *[_gazetteer_list(client, plat, plon) for plat, plon in probes],
            return_exceptions=True,
        )
        for item in found:
            if isinstance(item, Exception) or not item:
                continue
            rec = _first_plausible(item, lat, lon)
            if rec:
                return zee_from_record(rec), "marineregions"
        if ashore:
            return ashore, "marineregions"
        if all(isinstance(item, Exception) for item in found):
            # None of the probes around the point got an answer: the EEZ is
            # unknown, not « high seas ».
            return zee_unknown(), "unavailable"
        return zee_from_record(None), "marineregions"
    except Exception:
        # Gazetteer down: the EEZ is unknown, not « high seas ».
        return zee_unknown(), "unavailable"


def _ashore_from_records(records: list) -> dict | None:
    for rec in records or []:
        if _place_type(rec) != "NATION":
            continue
        name = rec.get("preferredGazetteerName") or rec.get("name")
        if not name:
            continue
        return {
            "name": f"À terre ({name})",
            "mrgid": None,
            "territory": None,
            "gold": False,
            "ashore": True,
        }
    return None


# One process-wide cap for every BI HTTP call this module makes (the gather
# fan-outs included). Recreated if the running loop changes so tests that
# each open a loop do not share a bound semaphore.
_BI_PARALLEL = 6
_bi_sem: asyncio.Semaphore | None = None
_bi_lock: asyncio.Lock | None = None
_bi_loop: asyncio.AbstractEventLoop | None = None
_bi_inflight: dict[tuple, asyncio.Task] = {}


def _bi_limits() -> tuple[asyncio.Lock, asyncio.Semaphore]:
    global _bi_sem, _bi_lock, _bi_loop
    loop = asyncio.get_running_loop()
    if _bi_sem is None or _bi_loop is not loop:
        _bi_sem = asyncio.Semaphore(_BI_PARALLEL)
        _bi_lock = asyncio.Lock()
        _bi_loop = loop
        _bi_inflight.clear()
    return _bi_lock, _bi_sem


def _norm_params(params) -> tuple:
    if not params:
        return ()
    try:
        items = params.items() if isinstance(params, dict) else list(params)
        return tuple(sorted((str(k), "" if v is None else str(v)) for k, v in items))
    except Exception:
        return (repr(params),)


def _raw_client(client: httpx.AsyncClient) -> httpx.AsyncClient:
    return client._inner if isinstance(client, _BiClient) else client


class _BiClient:
    """Delegates to an AsyncClient. BI URLs share one in-flight call under the semaphore."""

    def __init__(self, inner: httpx.AsyncClient):
        self._inner = inner

    @property
    def _transport(self):
        return getattr(self._inner, "_transport", None)

    async def get(self, url, **kwargs):
        base = bi_base()
        text = str(url)
        if base and (text == base or text.startswith(base + "/")):
            return await _bi_send(
                self._inner,
                "GET",
                text,
                params=kwargs.get("params"),
                timeout=kwargs.get("timeout", 4.0),
                headers=kwargs.get("headers"),
            )
        if base is None and not (text.startswith("http://") or text.startswith("https://")):
            raise BiDisabled("BI disabled: BI_API_URL is not set")
        return await self._inner.get(url, **kwargs)

    def __getattr__(self, name):
        return getattr(self._inner, name)


async def _bi_send(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    params=None,
    timeout: float | None = 4.0,
    headers: dict | None = None,
) -> httpx.Response:
    """One upstream call per method+URL+params while that call is in flight.

    The slot is dropped when the call finishes. A transport error is raised
    for every waiter and is not stored.
    """
    if bi_base() is None:
        raise BiDisabled("BI disabled: BI_API_URL is not set")
    if isinstance(params, dict):
        params = dict(params)
    elif isinstance(params, list):
        params = list(params)
    key = (method.upper(), str(url), _norm_params(params))
    lock, sem = _bi_limits()

    async def _run() -> httpx.Response:
        try:
            async with sem:
                kwargs: dict[str, Any] = {}
                if params is not None:
                    kwargs["params"] = params
                if headers is not None:
                    kwargs["headers"] = headers
                if timeout is not None:
                    kwargs["timeout"] = timeout
                send = getattr(client, method.lower())
                return await send(url, **kwargs)
        finally:
            async with lock:
                if _bi_inflight.get(key) is asyncio.current_task():
                    _bi_inflight.pop(key, None)

    async with lock:
        task = _bi_inflight.get(key)
        if task is None:
            task = asyncio.get_running_loop().create_task(_run())
            _bi_inflight[key] = task
    return await task


async def _get_json(client: httpx.AsyncClient, url: str, timeout: float = 4.0, params: dict | None = None) -> Any:
    if bi_base() is None:
        raise BiDisabled("BI disabled: BI_API_URL is not set")
    response = await _bi_send(
        _raw_client(client),
        "GET",
        str(url),
        params=params,
        timeout=timeout,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    response.raise_for_status()
    return response.json()


async def _cached_fc(client: httpx.AsyncClient, url: str) -> list:
    now = time.time()
    hit = _fc_cache.get(url)
    if hit and now - hit["ts"] < _FC_TTL:
        return hit["features"]
    data = await _get_json(client, url, timeout=20.0)
    features = data.get("features") if isinstance(data, dict) else []
    if not isinstance(features, list):
        features = []
    _fc_cache[url] = {"ts": now, "features": features}
    return features


async def fetch_wpi_features(client: httpx.AsyncClient | None = None) -> list:
    now = time.time()
    if _wpi_cache["data"] is not None and now - _wpi_cache["ts"] < _WPI_TTL:
        return _wpi_cache["data"]
    own = client is None
    http = client or httpx.AsyncClient()
    try:
        resp = await http.get(
            WPI_URL,
            params={"output": "json"},
            headers={"User-Agent": USER_AGENT},
            timeout=20.0,
        )
        resp.raise_for_status()
        raw = resp.json()
    except Exception:
        return _wpi_cache["data"] or []
    finally:
        if own:
            await http.aclose()
    ports = raw if isinstance(raw, list) else raw.get("ports", [])
    features = []
    for p in ports or []:
        lat = parse_coord(p.get("latitude") if p.get("latitude") is not None else p.get("lat"))
        lon = parse_coord(p.get("longitude") if p.get("longitude") is not None else p.get("lon"))
        if lat is None or lon is None:
            continue
        if lat == 0.0 and lon == 0.0:
            continue
        name = p.get("portName") or p.get("name") or ""
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "name": name,
                "country": p.get("countryName") or "",
            },
        })
    _wpi_cache["data"] = features
    _wpi_cache["ts"] = time.time()
    return features


def _poe_from_fc(data: Any, lat: float, lon: float) -> list[dict]:
    features = data.get("features") if isinstance(data, dict) else []
    out = []
    for feat in features or []:
        item = slim_place(feat, lat, lon)
        if item:
            out.append(item)
    out.sort(key=lambda x: x["nm"])
    return out[:MAX_POE]


def _apply_overpass_harbours(d: dict, value: Any) -> None:
    if isinstance(value, Exception) or not value:
        return
    try:
        caps, ancs = value
    except (TypeError, ValueError):
        return
    if caps and not d["nearby"]["capitaineries"]:
        d["nearby"]["capitaineries"] = caps
    if ancs and not d["nearby"]["anchorages"]:
        d["nearby"]["anchorages"] = ancs
        d["sources"]["anchorages"] = "osm-overpass"


def _assign_result(d: dict, key: str, value: Any) -> bool:
    if isinstance(value, Exception):
        return False
    if key == "poe":
        d["poe"] = value
    elif key == "amp":
        d["amp"] = value
    elif key == "projects":
        d["projects"] = value
    elif key == "marinas":
        d["nearby"]["marinas"] = value
    elif key == "capitaineries":
        d["nearby"]["capitaineries"] = value
    elif key == "wpi":
        d["nearby"]["wpi"] = value
    elif key == "science":
        d["science"] = {"nearby": value}
    elif key == "anchorages":
        d["nearby"]["anchorages"] = value
    return True


def _zone_climo(lat: float, lon: float, month: int, point=None, crossings=None, source="zone_fallback") -> dict:
    zone = zone_wind_at(lat, lon, month)
    return {
        "kind": "climatology",
        "source": source,
        "month": month,
        "period": None,
        "doi": None,
        "point": point,
        "crossings": crossings,
        "wind": zone,
    }


async def _climatology_bag(
    http: httpx.AsyncClient,
    bi: str,
    lat: float,
    lon: float,
    month: int | None,
    dest_lat: float | None,
    dest_lon: float | None,
) -> dict:
    from datetime import datetime, timezone
    m = int(month) if month else datetime.now(timezone.utc).month
    m = max(1, min(12, m))
    params = {"lat": lat, "lon": lon, "month": m}
    if dest_lat is not None and dest_lon is not None:
        params["dest_lat"] = dest_lat
        params["dest_lon"] = dest_lon
    try:
        point = await _get_json(http, f"{bi}/climatology/point", timeout=6.0, params=params)
    except Exception:
        return _zone_climo(lat, lon, m, source="zone_fallback")
    crossings = None
    if dest_lat is not None and dest_lon is not None:
        try:
            crossings = await _get_json(
                http,
                f"{bi}/climatology/crossings",
                timeout=6.0,
                params={
                    "lat1": lat, "lon1": lon, "lat2": dest_lat, "lon2": dest_lon, "month": m,
                },
            )
        except Exception:
            crossings = None
    wind = wind_from_point(point if isinstance(point, dict) else None)
    if not wind:
        return _zone_climo(lat, lon, m, point=point if isinstance(point, dict) else None,
                           crossings=crossings, source="empty")
    if crossings and isinstance(point, dict):
        cyc = dict(point.get("cyclone") or {})
        cyc["crossings_if_leg"] = crossings
        point = {**point, "cyclone": cyc, "crossings": crossings}
    return {
        "kind": "climatology",
        "source": "atlas",
        "month": m,
        "period": point.get("period") if isinstance(point, dict) else None,
        "doi": point.get("doi") if isinstance(point, dict) else None,
        "periods": point.get("periods") if isinstance(point, dict) else None,
        "provenance": point.get("provenance") if isinstance(point, dict) else None,
        "point": point,
        "crossings": crossings or ((point.get("cyclone") or {}).get("crossings_if_leg") if isinstance(point, dict) else None),
        "wind": {
            "speedKnots": wind["speedKnots"],
            "dirFromDeg": wind["dirFromDeg"],
            "kind": "climatology",
            "source": "atlas",
        },
        "rose": climatology_rose(point if isinstance(point, dict) else None),
        "current": {
            "speed_knots": wind.get("currentKn"),
            "direction_to_deg": wind.get("currentToDeg"),
        } if wind.get("currentKn") is not None else (point.get("current") if isinstance(point, dict) else None),
        "cyclone": {
            "nearby": wind.get("cycloneNearby"),
            "tracks_in_month": (point.get("cyclone") or {}).get("tracks_in_month") if isinstance(point, dict) else None,
            "crossings_if_leg": crossings or wind.get("crossings"),
        },
    }


def _with_piracy(bag: dict, lat: float, lon: float) -> dict:
    """Pose ``piracy`` au point, ou ``None``. Table locale, pas de HTTP."""
    try:
        from piracy import attach_piracy  # noqa: PLC0415
        attach_piracy(bag, lat, lon)
    except Exception as exc:
        log.debug("piraterie ignorée : %s", exc)
        bag["piracy"] = None
    return bag


async def fill_dossier(
    lat: float,
    lon: float,
    radius_nm: float = ICI_RADIUS_NM,
    client: httpx.AsyncClient | None = None,
    month: int | None = None,
    dest_lat: float | None = None,
    dest_lon: float | None = None,
    thin: bool = False,
    rich: bool = False,
    force: bool = False,
) -> dict:
    """`thin=True` → a pearl (cached, no weather / satellite / sheet);
    `rich=True` (with thin) → every layer without a timestamp.
    `force=True` ignore la perle en cache (recalcul des aires encore en centroïdes)."""
    import offline
    if offline.enabled():
        bag = empty_dossier(lat, lon, radius_nm)
        bag["status"] = "unavailable"
        bag["reason"] = "hors ligne"
        return _with_piracy(bag, lat, lon)
    if thin:
        if client is not None:
            await refresh_amp_layer_sig(client)
        else:
            load_amp_layer_sig()
        key = thin_cache_key(lat, lon, radius_nm, month)
        cached = None if force else thin_cache_get(key, rich=rich)
        if cached is not None:
            bag = {**cached, "at": {"lat": lat, "lon": lon}, "cached": True}
            try:
                from truth_judge import maybe_attach  # noqa: PLC0415
                await maybe_attach(bag, client=client)
            except Exception as exc:
                log.debug("juge de vérité ignoré : %s", exc)
            try:
                from escale_watch import attach_cached  # noqa: PLC0415
                attach_cached(bag)
            except Exception as exc:
                log.debug("veille / enrich cache ignoré : %s", exc)
            return _with_piracy(bag, lat, lon)
        bag = await _fill_dossier(lat, lon, radius_nm, client, month, dest_lat, dest_lon, thin=True, rich=rich)
        if bag.get("ampFallback") and rich:
            # Tuiles en centroïdes : on ne fige pas une perle riche 30 jours.
            log.warning("perle %s : AMP en repli centroïdes, non stockée riche", key)
        elif (bag.get("sources") or {}).get("bi") != "unavailable":
            key = thin_cache_key(lat, lon, radius_nm, month)
            thin_cache_put(key, bag, "rich" if rich else "thin", lat, lon)
        return _with_piracy(bag, lat, lon)
    return _with_piracy(
        await _fill_dossier(lat, lon, radius_nm, client, month, dest_lat, dest_lon, thin=False),
        lat, lon,
    )


async def _fill_dossier(
    lat: float,
    lon: float,
    radius_nm: float,
    client: httpx.AsyncClient | None,
    month: int | None,
    dest_lat: float | None,
    dest_lon: float | None,
    thin: bool,
    rich: bool = False,
) -> dict:
    d = empty_dossier(lat, lon, radius_nm)
    bi = bi_base()
    # A rich pearl collects the timeless layers a full bag has, minus what
    # only makes sense now (weather, satellite scene, Gold sheet, climatology).
    lean = thin and not rich
    if thin:
        d["pearl"] = "rich" if rich else "thin"

    own = client is None
    raw = client or httpx.AsyncClient()
    http = _BiClient(raw)
    bind_weather_transport(getattr(raw, "_transport", None))  # MockTransport only

    async def poe_task(mrgid: int) -> list[dict]:
        data = await _get_json(http, f"{bi}/poe/ports?mrgid={int(mrgid)}", timeout=4.0)
        return _poe_from_fc(data, lat, lon)

    # AMP et projets à 30 nm (même rayon que le sac « ici » du panneau).
    amp_radius = radius_nm
    marina_radius = 25.0 if thin else radius_nm

    async def amp_task() -> list[dict]:
        # Polygones GET /amp (cache 1°), repli centroïdes si absent.
        await refresh_amp_layer_sig(http)
        feats, source = await fetch_amp_features(http, lat, lon)
        found = nearest_amp(feats, lat, lon, amp_radius, MAX_AMP, source=source)
        if source != "polygon" or any(
            isinstance(item, dict) and item.get("source") != "polygon" for item in found
        ):
            # Repli centroïdes, ou une aire de la tuile qui n'est pas une forme.
            d["ampFallback"] = True
        return found

    async def projects_task() -> list[dict]:
        feats = await _cached_fc(http, f"{bi}/export/geojson")
        found = nearest_places(
            feats, lat, lon, radius_nm, MAX_PROJECTS, extra_keys=("gold_on",),
        )
        found.sort(key=lambda x: (0 if x.get("gold_on") else 1, x.get("nm") or 999))
        return found[:MAX_PROJECTS]

    async def marinas_task() -> list[dict]:
        # /marinas = BI memory cache; the export rebuilds all of Mongo.
        feats = await _cached_fc(http, f"{bi}/marinas")
        return nearest_places(feats, lat, lon, marina_radius, MAX_NEARBY)

    async def capit_task() -> list[dict]:
        feats = await _cached_fc(http, f"{bi}/capitaineries")
        return nearest_places(feats, lat, lon, marina_radius, MAX_NEARBY)

    async def science_task() -> list[dict]:
        feats = await _cached_fc(http, f"{bi}/export/science.geojson")
        return nearest_places(feats, lat, lon, radius_nm, MAX_SCIENCE, slim=slim_science)

    async def wpi_task() -> list[dict]:
        feats = await fetch_wpi_features(http)
        return nearest_places(feats, lat, lon, marina_radius, MAX_NEARBY)

    async def anchorages_task() -> list[dict]:
        feats = await _cached_fc(http, f"{bi}/anchorages")
        return nearest_places(feats, lat, lon, radius_nm, MAX_ANCHORAGES, slim=slim_anchorage)

    try:
        amp_t = asyncio.create_task(amp_task())
        mar_t = asyncio.create_task(marinas_task())
        cap_t = asyncio.create_task(capit_task())
        wpi_t = asyncio.create_task(wpi_task())
        proj_t = asyncio.create_task(projects_task())
        sci_t = None if lean else asyncio.create_task(science_task())
        anc_t = None if lean else asyncio.create_task(anchorages_task())
        sat_t = None if thin else asyncio.create_task(fetch_satellite_scene(http, lat, lon))
        emo_t = None if lean else asyncio.create_task(fetch_emodnet_point(http, bi, lat, lon))
        aton_t = None if lean else asyncio.create_task(
            fetch_aton(http, bi, lat, lon, radius_nm, haversine_nm, radius_bbox)
        )

        zee, zee_src = await lookup_zee(http, lat, lon)
        d["zee"] = zee
        d["sources"]["zee"] = zee_src

        mrgid = zee.get("mrgid") if zee else None
        poe_t = asyncio.create_task(poe_task(mrgid)) if mrgid else None

        if lean:
            nearby = await asyncio.gather(
                amp_t, proj_t, mar_t, cap_t, wpi_t, return_exceptions=True,
            )
            keys = ("amp", "projects", "marinas", "capitaineries", "wpi")
        else:
            nearby = await asyncio.gather(
                amp_t, proj_t, mar_t, cap_t, sci_t, wpi_t, anc_t, return_exceptions=True,
            )
            keys = ("amp", "projects", "marinas", "capitaineries", "science", "wpi", "anchorages")
        bi_ok = 0
        bi_fail = 0
        for key, value in zip(keys, nearby):
            if key == "wpi":
                _assign_result(d, key, value)
                continue
            if key == "anchorages":
                if _assign_result(d, key, value):
                    d["sources"]["anchorages"] = "osm"
                    bi_ok += 1
                else:
                    d["sources"]["anchorages"] = "unavailable"
                    bi_fail += 1
                continue
            if _assign_result(d, key, value):
                bi_ok += 1
            else:
                bi_fail += 1

        if poe_t is not None:
            try:
                poe_val = await poe_t
            except Exception as exc:
                poe_val = exc
            if _assign_result(d, "poe", poe_val):
                bi_ok += 1
            else:
                bi_fail += 1

        if bi_ok and not bi_fail:
            d["sources"]["bi"] = "ok"
        elif bi_ok:
            d["sources"]["bi"] = "partial"
        else:
            d["sources"]["bi"] = "unavailable"

        need_harbours = (
            not d["nearby"]["capitaineries"]
            or (not lean and not d["nearby"]["anchorages"])
        )
        harbour_fb = (
            fetch_overpass_harbours(
                http, lat, lon, radius_nm, haversine_nm,
                max_capitaineries=MAX_NEARBY,
                max_anchorages=0 if lean else MAX_ANCHORAGES,
            )
            if need_harbours else None
        )

        if thin:
            pearl_tasks = [] if lean else [emo_t, aton_t]
            if harbour_fb is not None:
                pearl_tasks.append(harbour_fb)
            results = await asyncio.gather(*pearl_tasks, return_exceptions=True) if pearl_tasks else []
            if not lean:
                emo, aton = results[0], results[1]
                if harbour_fb is not None:
                    try:
                        _apply_overpass_harbours(d, results[2])
                    except Exception:
                        pass
                if isinstance(emo, dict):
                    d["emodnet"] = emo
                    d["sources"]["emodnet"] = "emodnet"
                else:
                    d["emodnet"] = empty_emodnet()
                    d["emodnet"]["reason"] = layer_code("emodnet_unavailable", type(emo).__name__)
                    d["sources"]["emodnet"] = None
                if isinstance(aton, dict):
                    d["aton"] = aton
                    d["sources"]["aton"] = aton.get("source")
                else:
                    d["aton"] = empty_aton()
                    d["aton"]["reason"] = layer_code("aton_unavailable", type(aton).__name__)
                    d["sources"]["aton"] = None
            elif harbour_fb is not None:
                try:
                    _apply_overpass_harbours(d, results[0])
                except Exception:
                    pass
            if lean:
                d["emodnet"] = empty_emodnet()
                d["emodnet"]["reason"] = "not_in_along_pearl"
                d["aton"] = empty_aton()
                d["aton"]["reason"] = "not_in_along_pearl"
                d["sources"]["emodnet"] = None
                d["sources"]["aton"] = None
            d["weather"] = empty_weather()
            d["weather"]["reason"] = "not_in_along_pearl"
            d["satellites"] = empty_satellites()
            d["satellites"]["reason"] = "not_in_along_pearl"
            d["review"] = empty_review()
            d["review"]["reason"] = "not_in_along_pearl"
            d["climatology"] = None
            d["sources"]["weather"] = None
            d["sources"]["satellites"] = None
            d["sources"]["review"] = None
            d["sources"]["climatology"] = None
            d["sources"]["gebco"] = "not_in_along_pearl"
        else:
            extra_tasks = [
                sat_t, emo_t, aton_t,
                fetch_review(http, bi, d.get("zee"), (d.get("amp") or [None])[0]),
                _climatology_bag(http, bi, lat, lon, month, dest_lat, dest_lon),
            ]
            if harbour_fb is not None:
                extra_tasks.append(harbour_fb)
            extras = await asyncio.gather(*extra_tasks, return_exceptions=True)
            sat, emo, aton, review, climo = extras[:5]
            if harbour_fb is not None:
                _apply_overpass_harbours(d, extras[5])
            wx = snapshot_ici_weather(lat, lon)
            science_near = (d.get("science") or {}).get("nearby") if isinstance(d.get("science"), dict) else None
            if isinstance(sat, Exception):
                d["satellites"] = empty_satellites()
                d["satellites"]["reason"] = layer_code("cdse_stac_unavailable", type(sat).__name__)
                d["sources"]["satellites"] = None
            else:
                d["satellites"] = attach_derived_from_science(sat, science_near)
                d["sources"]["satellites"] = d["satellites"].get("source")
            if isinstance(wx, Exception):
                d["weather"] = empty_weather()
                d["weather"]["reason"] = layer_code("openmeteo_unavailable", type(wx).__name__)
                d["sources"]["weather"] = None
            else:
                d["weather"] = wx
                d["sources"]["weather"] = wx.get("source")
            if isinstance(emo, Exception):
                d["emodnet"] = empty_emodnet()
                d["emodnet"]["reason"] = layer_code("emodnet_unavailable", type(emo).__name__)
                d["sources"]["emodnet"] = None
            else:
                d["emodnet"] = emo
                d["sources"]["emodnet"] = "emodnet"
            if isinstance(aton, Exception):
                d["aton"] = empty_aton()
                d["aton"]["reason"] = layer_code("aton_unavailable", type(aton).__name__)
                d["sources"]["aton"] = None
            else:
                d["aton"] = aton
                d["sources"]["aton"] = aton.get("source")
            if isinstance(review, Exception):
                d["review"] = empty_review()
                d["review"]["reason"] = layer_code("review_unavailable", type(review).__name__)
                d["sources"]["review"] = None
            else:
                d["review"] = review
                d["sources"]["review"] = review.get("source")
            if isinstance(climo, Exception):
                d["climatology"] = _zone_climo(lat, lon, int(month or 1), source="zone_fallback")
            else:
                d["climatology"] = climo
            d["sources"]["climatology"] = (d["climatology"] or {}).get("source")
            await attach_depth_offshore(d, http)
    finally:
        if own:
            await http.aclose()

    if d["zee"] and d["zee"].get("mrgid") in FRENCH_EEZ_MRGID:
        d["zee"]["gold"] = bool(d["poe"])
    try:
        from truth_judge import maybe_attach  # noqa: PLC0415
        await maybe_attach(d, client=None if own else http)
    except Exception as exc:
        log.debug("juge de vérité ignoré : %s", exc)
    try:
        from escale_watch import attach_cached  # noqa: PLC0415
        attach_cached(d)
    except Exception as exc:
        log.debug("veille / enrich cache ignoré : %s", exc)
    return d
