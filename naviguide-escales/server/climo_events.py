"""Changements de climatologie notables, lus sur l'horloge.

Bascule de régime nommée, saut de force ≥ 8 kn ou de direction ≥ 60° tenu
≥ 24 h. Les chiffres viennent de l'horloge ou de l'atlas ; le repli de zone
ne produit jamais un nœud ni un degré dit à la voix.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

HOLD_HOURS = 24.0
FORCE_JUMP_KN = 8.0
DIR_JUMP_DEG = 60.0
FORCE_HOLD_BAND = 4.0
DIR_HOLD_BAND = 30.0
SHORT_CROSSING_MS = 3 * 86_400_000
SHORT_LIMIT = 1
LONG_LIMIT = 2
CALM_KN = 6.0
SCORE_NAMED = 2
SCORE_JUMP = 1

_SKIP_VEHICLES = frozenset({"plane", "side", "quay", "land"})
_NAMED_ORDER = (
    "ne_trades", "se_trades", "equatorial_calms", "westerlies", "mistral", "tramontane",
)
_NAMED = {
    "ne_trades": {
        "fr": "les alizés de nord-est", "en": "the northeasterly trade winds",
        "title_fr": "alizés de nord-est", "title_en": "northeasterly trade winds",
        "verb_fr": "s'installent",
    },
    "se_trades": {
        "fr": "les alizés de sud-est", "en": "the southeasterly trade winds",
        "title_fr": "alizés de sud-est", "title_en": "southeasterly trade winds",
        "verb_fr": "s'installent",
    },
    "equatorial_calms": {
        "fr": "les calmes équatoriaux", "en": "the equatorial calms",
        "title_fr": "calmes équatoriaux", "title_en": "equatorial calms",
        "verb_fr": "s'installent",
    },
    "westerlies": {
        "fr": "les vents d'ouest", "en": "the westerlies",
        "title_fr": "vents d'ouest", "title_en": "westerlies",
        "verb_fr": "s'installent",
    },
    "mistral": {
        "fr": "le mistral", "en": "the mistral",
        "title_fr": "mistral", "title_en": "mistral",
        "verb_fr": "s'installe",
    },
    "tramontane": {
        "fr": "la tramontane", "en": "the tramontane",
        "title_fr": "tramontane", "title_en": "tramontane",
        "verb_fr": "s'installe",
    },
}
_HEADING_8 = (
    ("nord", "north"),
    ("nord-est", "northeast"),
    ("est", "east"),
    ("sud-est", "southeast"),
    ("sud", "south"),
    ("sud-ouest", "southwest"),
    ("ouest", "west"),
    ("nord-ouest", "northwest"),
)
_FR_SMALL = (
    "zéro", "un", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf",
    "dix", "onze", "douze", "treize", "quatorze", "quinze", "seize", "dix-sept",
    "dix-huit", "dix-neuf",
)
_EN_SMALL = (
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
    "seventeen", "eighteen", "nineteen",
)
_MONTHS = {
    "fr": [
        "janvier", "février", "mars", "avril", "mai", "juin",
        "juillet", "août", "septembre", "octobre", "novembre", "décembre",
    ],
    "en": [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ],
}
# Jalons climatiques : le nom vient d'ici, la position du sommet décide « au sud de ».
# Un jalon à plus de PLACE_MAX_NM ne nomme pas le lieu — le 19 mai au
# large de la Galice, le bateau n'est pas « au nord de Gibraltar » (445 nm).
PLACE_MAX_NM = 240.0
_LANDMARKS = (
    (16.0, -24.0, "Cap-Vert", "Cape Verde", "du", "of"),
    (28.5, -15.5, "Canaries", "the Canary Islands", "des", "of"),
    (32.7, -17.0, "Madère", "Madeira", "de", "of"),
    (36.14, -5.35, "Gibraltar", "Gibraltar", "de", "of"),
    (38.5, -28.0, "Açores", "the Azores", "des", "of"),
    (14.6, -61.0, "Martinique", "Martinique", "de la", "of"),
    (41.93, 8.74, "Corse", "Corsica", "de la", "of"),
)


def _en(lang: str) -> bool:
    return str(lang or "").lower().startswith("en")


def _num(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_iso(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _angle_delta(a: float, b: float) -> float:
    d = abs((float(a) - float(b)) % 360.0)
    return 360.0 - d if d > 180.0 else d


def _haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 3440.065
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(h)))


def _in_atlantic(lon: float) -> bool:
    return -80.0 <= lon <= 20.0


def _in_pacific(lon: float) -> bool:
    return lon >= 120.0 or lon <= -80.0


def _in_med(lat: float, lon: float) -> bool:
    return -10.0 <= lon <= 40.0 and 30.0 <= lat <= 47.0


def _atlas_name(vertex: dict) -> str:
    blobs = [
        vertex.get("atlasName"), vertex.get("regimeName"), vertex.get("namedRegime"),
        vertex.get("windName"), vertex.get("name"),
    ]
    point = vertex.get("point") if isinstance(vertex.get("point"), dict) else {}
    blobs.extend([point.get("name"), point.get("regime"), (point.get("wind_atlas") or {}).get("name")])
    return " ".join(str(b) for b in blobs if b).casefold()


def named_belt(
    lat: float,
    lon: float,
    dir_deg: Optional[float],
    knots: Optional[float],
    source: str = "",
    vertex: Optional[dict] = None,
) -> Optional[str]:
    """Régime nommé. mistral / tramontane seulement si l'atlas le dit (source atlas)."""
    raw = _atlas_name(vertex or {})
    if "tramontane" in raw:
        return "tramontane"
    if "mistral" in raw:
        return "mistral"
    if knots is not None and knots < CALM_KN and abs(lat) <= 10.0:
        return "equatorial_calms"
    # Mistral / tramontane seulement dans la Méditerranée vraie (lon ≥ 0) —
    # la boîte _in_med englobe la côte atlantique ibérique, où un vent de nord
    # n'est pas le mistral (transcription du 14 oct., bateau au large de la Galice).
    if (
        source == "atlas" and _in_med(lat, lon) and lon >= 0.0
        and knots is not None and knots >= 12.0 and dir_deg is not None
    ):
        d = dir_deg % 360.0
        if lon <= 6.0 and 300.0 <= d <= 340.0:
            return "tramontane"
        if d >= 320.0 or d <= 25.0:
            return "mistral"
    trades_ocean = _in_atlantic(lon) or _in_pacific(lon) or 20.0 <= lon <= 120.0
    if trades_ocean and knots is not None and knots >= 8.0:
        if 5.0 <= lat <= 28.0 and (dir_deg is None or 20.0 <= (dir_deg % 360.0) <= 90.0):
            return "ne_trades"
        if -28.0 <= lat <= 8.0 and (dir_deg is None or 90.0 <= (dir_deg % 360.0) <= 170.0):
            return "se_trades"
    if knots is not None and knots >= 10.0:
        westerly = dir_deg is None or 220.0 <= (dir_deg % 360.0) <= 300.0
        if westerly and (lat >= 36.0 or lat <= -36.0):
            return "westerlies"
    return None


def wind_source(vertex: dict) -> str:
    kind = str(vertex.get("regime") or vertex.get("kind") or "").casefold()
    src = str(vertex.get("source") or "").casefold()
    if kind == "hindcast" or src in {"om-era5", "era5", "hindcast", "om-forecast"} or kind == "forecast":
        return "hindcast"
    if src in {"zone_fallback", "zone", "fallback"}:
        return "zone_fallback"
    if src == "atlas":
        return "atlas"
    return "zone_fallback"


def _dir_from_cache(vertex: dict) -> Optional[float]:
    lat, lon = _num(vertex.get("lat")), _num(vertex.get("lon"))
    if lat is None or lon is None:
        return None
    month = vertex.get("month")
    if month is None:
        when = _parse_iso(vertex.get("iso"))
        month = when.month if when else None
    if month is None:
        return None
    try:
        from climatology_atlas import atlas_wind_cached  # noqa: PLC0415
        pack = atlas_wind_cached(lat, lon, int(month))
    except Exception:
        return None
    return _num((pack or {}).get("dirFromDeg"))


def _compass(deg: float, lang: str) -> str:
    idx = int((float(deg) % 360.0) / 45.0 + 0.5) % 8
    fr, en = _HEADING_8[idx]
    return en if _en(lang) else fr


EQUATOR_BAND_DEG = 2.0


def _place_phrase(lat: float, lon: float, lang: str) -> str:
    """Lieu de la phrase climato = position du bateau à cet instant :
    un jalon trop loin (> PLACE_MAX_NM) ne se dit pas — mieux vaut le silence
    qu'un « au nord de Gibraltar » quand le bateau longe la Galice."""
    # « À l'équateur » seulement près de la ligne (≤ 2°, ~120 milles) : à 4,95° N
    # (Dégrad des Cannes, Cayenne) le bateau n'a jamais coupé l'équateur.
    if abs(lat) <= EQUATOR_BAND_DEG:
        return "at the equator" if _en(lang) else "à l'équateur"
    best = None
    best_d = PLACE_MAX_NM
    for mlat, mlon, fr, en, art_fr, art_en in _LANDMARKS:
        d = _haversine_nm(lat, lon, mlat, mlon)
        if d < best_d:
            best_d = d
            best = (mlat, fr, en, art_fr, art_en)
    if best is None:
        return ""
    mlat, fr, en, art_fr, art_en = best
    if _en(lang):
        if lat < mlat - 1.5:
            return f"south of {en}"
        if lat > mlat + 1.5:
            return f"north of {en}"
        return f"off {en}"
    if lat < mlat - 1.5:
        return f"au sud {art_fr} {fr}"
    if lat > mlat + 1.5:
        return f"au nord {art_fr} {fr}"
    return f"au large {art_fr} {fr}"


def _day_month(iso: Any, lang: str) -> str:
    when = _parse_iso(iso)
    if when is None:
        return ""
    when = when.astimezone(timezone.utc)
    months = _MONTHS["en" if _en(lang) else "fr"]
    name = months[when.month - 1]
    if _en(lang):
        return f"{when.day} {name}"
    return f"{'1er' if when.day == 1 else when.day} {name}"


def _spoken_int(n: int, lang: str) -> str:
    if _en(lang):
        if 0 <= n <= 19:
            return _EN_SMALL[n]
        if n == 20:
            return "twenty"
        if n == 21:
            return "twenty-one"
        if 22 <= n <= 29:
            return f"twenty-{_EN_SMALL[n - 20]}"
        if n == 30:
            return "thirty"
        return str(n)
    if 0 <= n <= 19:
        return _FR_SMALL[n]
    if n == 20:
        return "vingt"
    if n == 21:
        return "vingt et un"
    if 22 <= n <= 29:
        return f"vingt-{_FR_SMALL[n - 20]}"
    if n == 30:
        return "trente"
    return str(n)


def spoken_knots(knots: Any, lang: str = "fr") -> str:
    try:
        n = int(round(float(knots)))
    except (TypeError, ValueError):
        return ""
    if n < 0:
        return ""
    return _spoken_int(n, lang)


def _nature_of(source: str) -> str:
    if source == "hindcast":
        return "measured"
    if source == "atlas":
        return "season"
    return "zone"


def _speakable_knots(change: dict) -> Optional[float]:
    source = str(change.get("source") or "")
    nature = str(change.get("nature") or _nature_of(source))
    if source == "zone_fallback" or nature == "zone":
        return None
    return _num(change.get("windKnots"))


def climo_sentence(change: dict, lang: str = "fr") -> str:
    """Phrase datée. Repli de zone : pas de chiffre. Aucun nombre inventé."""
    if not isinstance(change, dict):
        return ""
    en = _en(lang)
    when = _day_month(change.get("t") or change.get("iso"), lang)
    if not when:
        return ""
    source = str(change.get("source") or "")
    nature = str(change.get("nature") or _nature_of(source))
    kn = _speakable_knots(change)
    belt = str(change.get("regimeId") or change.get("event") or "")
    named = _NAMED.get(belt)
    place = str(change.get("placeEn" if en else "placeFr") or "")
    where = f"{place}, " if place else ""

    def with_knots(core: str) -> str:
        if kn is None:
            avg = "seasonal average winds" if en else "vents moyens de saison"
            sep = ": " if en else " : "
            return f"{core}{sep}{avg}."
        word = spoken_knots(kn, lang)
        if not word:
            return f"{core}."
        if en:
            if nature == "season":
                return f"{core}: {word} knots, the seasonal average."
            return f"{core}: {word} measured knots."
        # « 21 nœuds de saison » se lisait comme un nom de vent ; on dit la moyenne.
        if nature == "season":
            return f"{core} : {word} nœuds, la moyenne de saison."
        return f"{core} : {word} nœuds mesurés."

    if named:
        body = named["en" if en else "fr"]
        if en:
            return with_knots(f"On {when}, {where}{body} set in")
        return with_knots(f"Le {when}, {where}{body} {named['verb_fr']}")

    if nature == "zone" or source == "zone_fallback":
        return ""

    event = str(change.get("event") or "")
    dir_name = str(change.get("dirEn" if en else "dirFr") or "")
    if event == "turn" and dir_name:
        core = (
            f"On {when}, {where}the wind shifts to the {dir_name}"
            if en else
            f"Le {when}, {where}le vent tourne {_fr_to_dir(dir_name)}"
        )
        return with_knots(core)
    if event == "force":
        prev = _num(change.get("prevKnots"))
        freshen = kn is not None and prev is not None and kn > prev
        if en:
            verb = "the wind freshens" if freshen else "the wind eases"
            return with_knots(f"On {when}, {where}{verb}")
        verb = "le vent fraîchit" if freshen else "le vent mollit"
        return with_knots(f"Le {when}, {where}{verb}")
    return ""


def _sample(vertex: dict) -> Optional[dict]:
    if not isinstance(vertex, dict):
        return None
    if str(vertex.get("vehicle") or "") in _SKIP_VEHICLES:
        return None
    if vertex.get("atQuay"):
        return None
    lat, lon = _num(vertex.get("lat")), _num(vertex.get("lon"))
    when = _parse_iso(vertex.get("iso"))
    if lat is None or lon is None or when is None:
        return None
    knots = _num(vertex.get("windKnots"))
    direction = _num(vertex.get("dirFromDeg"))
    if direction is None:
        direction = _dir_from_cache(vertex)
    source = wind_source(vertex)
    belt = named_belt(lat, lon, direction, knots, source, vertex)
    return {
        "t": when,
        "iso": _iso(when),
        "lat": lat,
        "lon": lon,
        "sailNm": _num(vertex.get("sailNm")),
        "knots": knots,
        "dir": direction,
        "source": source,
        "belt": belt,
        "vertex": vertex,
    }


def _change_kind(prev: dict, cur: dict) -> Optional[str]:
    if cur.get("belt") and cur.get("belt") != prev.get("belt"):
        return "belt"
    pk, ck = prev.get("knots"), cur.get("knots")
    if pk is not None and ck is not None and abs(ck - pk) >= FORCE_JUMP_KN:
        return "force"
    pd, cd = prev.get("dir"), cur.get("dir")
    if pd is not None and cd is not None and _angle_delta(pd, cd) >= DIR_JUMP_DEG:
        return "turn"
    return None


def _matches_hold(sample: dict, kind: str, target: dict) -> bool:
    if kind == "belt":
        return sample.get("belt") == target.get("belt")
    if kind == "force":
        a, b = sample.get("knots"), target.get("knots")
        return a is not None and b is not None and abs(a - b) <= FORCE_HOLD_BAND
    if kind == "turn":
        a, b = sample.get("dir"), target.get("dir")
        return a is not None and b is not None and _angle_delta(a, b) <= DIR_HOLD_BAND
    return False


def _held(samples: list[dict], start: int, kind: str, target: dict) -> bool:
    t0 = samples[start]["t"]
    deadline = t0 + timedelta(hours=HOLD_HOURS)
    reached = False
    for sample in samples[start:]:
        if sample["t"] >= deadline:
            reached = True
        if not _matches_hold(sample, kind, target):
            return False if sample["t"] < deadline else reached
        if sample["t"] > deadline + timedelta(hours=12):
            break
    return reached


def _make_event(prev: dict, cur: dict, kind: str) -> dict:
    source = cur["source"]
    nature = _nature_of(source)
    belt = cur.get("belt") if kind == "belt" else None
    named = _NAMED.get(belt or "")
    title = (named["title_fr"] if named else "") or (
        "changement de vent" if kind == "force" else "vent qui tourne"
    )
    speak_kn = cur.get("knots") if nature != "zone" else None
    speak_dir = cur.get("dir") if nature != "zone" else None
    event = belt if kind == "belt" and belt else kind
    place_fr = _place_phrase(cur["lat"], cur["lon"], "fr")
    place_en = _place_phrase(cur["lat"], cur["lon"], "en")
    out = {
        "kind": "climo",
        "score": SCORE_NAMED if named else SCORE_JUMP,
        "event": event,
        "regimeId": belt,
        "title": title,
        "t": cur["iso"],
        "iso": cur["iso"],
        "lat": cur["lat"],
        "lon": cur["lon"],
        "sailNm": cur.get("sailNm"),
        "source": source,
        "nature": nature,
        "windKnots": speak_kn,
        "dirFromDeg": speak_dir,
        "prevKnots": prev.get("knots") if nature != "zone" else None,
        "placeFr": place_fr,
        "placeEn": place_en,
        "id": f"climo:{event}:{cur['iso']}",
    }
    if speak_dir is not None:
        out["dirFr"] = _compass(speak_dir, "fr")
        out["dirEn"] = _compass(speak_dir, "en")
    out["fact"] = climo_sentence(out, "fr")
    return out


def notable_climo_changes(clock: dict | None) -> list[dict]:
    """Événements tenus ≥ 24 h. Horloge synthétique ou officielle."""
    vertices = (clock or {}).get("vertices") if isinstance(clock, dict) else None
    if not isinstance(vertices, list):
        return []
    samples: list[dict] = []
    for vertex in vertices:
        row = _sample(vertex)
        if row:
            samples.append(row)
    if len(samples) < 2:
        return []
    confirmed = samples[0]
    events: list[dict] = []
    for i in range(1, len(samples)):
        kind = _change_kind(confirmed, samples[i])
        if not kind:
            continue
        if not _held(samples, i, kind, samples[i]):
            continue
        event = _make_event(confirmed, samples[i], kind)
        if event.get("fact"):
            events.append(event)
        confirmed = samples[i]
    return events


def dose_climo_changes(changes: list[dict], span_ms: int) -> list[dict]:
    """Au plus un par étape courte, deux par traversée ; régime nommé d'abord."""
    items = [c for c in changes if isinstance(c, dict) and str(c.get("kind") or "") == "climo"]
    named = set(_NAMED)

    def rank(change: dict) -> tuple:
        belt = str(change.get("regimeId") or change.get("event") or "")
        return (0 if belt in named else 1, change.get("tMs") or 0)

    items.sort(key=rank)
    limit = SHORT_LIMIT if span_ms < SHORT_CROSSING_MS else LONG_LIMIT
    picked = items[:limit]
    picked.sort(key=lambda c: (c.get("tMs") or 0, str(c.get("id") or "")))
    return picked


def _fr_to_dir(dir_name: str) -> str:
    """« tourne au ouest » → « tourne à l'ouest » ; « au nord-est » reste."""
    d = (dir_name or "").strip()
    if d[:1].casefold() in "aeiouyéè":
        return f"à l'{d}"
    return f"au {d}"
