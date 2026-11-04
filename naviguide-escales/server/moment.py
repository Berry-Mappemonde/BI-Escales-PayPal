"""Moment « ici et maintenant ».

Une fonction pure : perle + point d'horloge + jambe + seuils skipper → Moment.
Aucun chiffre inventé — tout vient de la perle et de l'horloge. Les noms de
ZEE / ports / AMP sont localisés (revue du 22 sept. : plus de nom
MarineRegions brut dans une phrase FR, plus de parenthèses doublées).
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# Seuils du plan § 1.0 si le skipper n'en donne pas : Beaufort 8, Hs ≥ 3 m.
DEFAULT_GALE_KT = 34.0
DEFAULT_HS_M = 3.0

TERRITORY = {
    "fr": {
        "france_metropolitaine": "France métropolitaine",
        "guyane": "Guyane",
        "martinique": "Martinique",
        "guadeloupe": "Guadeloupe",
        "saint_barthelemy": "Saint-Barthélemy",
        "saint_martin": "Saint-Martin (partie française)",
        "saint_pierre_et_miquelon": "Saint-Pierre-et-Miquelon",
        "polynesie_francaise": "Polynésie française",
        "nouvelle_caledonie": "Nouvelle-Calédonie",
        "wallis_et_futuna": "Wallis-et-Futuna",
        "la_reunion": "La Réunion",
        "mayotte": "Mayotte",
        "taaf": "Terres australes et antarctiques françaises",
    },
    "en": {
        "france_metropolitaine": "metropolitan France",
        "guyane": "French Guiana",
        "martinique": "Martinique",
        "guadeloupe": "Guadeloupe",
        "saint_barthelemy": "Saint Barthélemy",
        "saint_martin": "Saint-Martin (French side)",
        "saint_pierre_et_miquelon": "Saint Pierre and Miquelon",
        "polynesie_francaise": "French Polynesia",
        "nouvelle_caledonie": "New Caledonia",
        "wallis_et_futuna": "Wallis and Futuna",
        "la_reunion": "Réunion",
        "mayotte": "Mayotte",
        "taaf": "French Southern and Antarctic Lands",
    },
}

# Nationalité MarineRegions → adjectif FR / étiquette EN courte.
_NATION_ADJ = {
    "french": {"fr": "française", "en": "French"},
    "spanish": {"fr": "espagnole", "en": "Spanish"},
    "portuguese": {"fr": "portugaise", "en": "Portuguese"},
    "brazilian": {"fr": "brésilienne", "en": "Brazilian"},
    "italian": {"fr": "italienne", "en": "Italian"},
    "mauritanian": {"fr": "mauritanienne", "en": "Mauritanian"},
    "australian": {"fr": "australienne", "en": "Australian"},
    "japanese": {"fr": "japonaise", "en": "Japanese"},
    "american": {"fr": "américaine", "en": "American"},
    "united states": {"fr": "américaine", "en": "United States"},
    "canadian": {"fr": "canadienne", "en": "Canadian"},
    "mexican": {"fr": "mexicaine", "en": "Mexican"},
    "colombian": {"fr": "colombienne", "en": "Colombian"},
    "venezuelan": {"fr": "vénézuélienne", "en": "Venezuelan"},
    "cuban": {"fr": "cubaine", "en": "Cuban"},
    "haitian": {"fr": "haïtienne", "en": "Haitian"},
    "dominican": {"fr": "dominicaine", "en": "Dominican"},
    "british": {"fr": "britannique", "en": "British"},
    "dutch": {"fr": "néerlandaise", "en": "Dutch"},
    "german": {"fr": "allemande", "en": "German"},
    "irish": {"fr": "irlandaise", "en": "Irish"},
    "icelandic": {"fr": "islandaise", "en": "Icelandic"},
    "norwegian": {"fr": "norvégienne", "en": "Norwegian"},
    "south african": {"fr": "sud-africaine", "en": "South African"},
    "new zealand": {"fr": "néo-zélandaise", "en": "New Zealand"},
    "indonesian": {"fr": "indonésienne", "en": "Indonesian"},
    "filipino": {"fr": "philippine", "en": "Philippine"},
    "philippine": {"fr": "philippine", "en": "Philippine"},
    "chinese": {"fr": "chinoise", "en": "Chinese"},
    "indian": {"fr": "indienne", "en": "Indian"},
    "argentine": {"fr": "argentine", "en": "Argentine"},
    "chilean": {"fr": "chilienne", "en": "Chilean"},
    "peruvian": {"fr": "péruvienne", "en": "Peruvian"},
    "ecuadorian": {"fr": "équatorienne", "en": "Ecuadorian"},
    "moroccan": {"fr": "marocaine", "en": "Moroccan"},
    "algerian": {"fr": "algérienne", "en": "Algerian"},
    "tunisian": {"fr": "tunisienne", "en": "Tunisian"},
    "senegalese": {"fr": "sénégalaise", "en": "Senegalese"},
    "cape verde": {"fr": "cap-verdienne", "en": "Cape Verde"},
    "fijian": {"fr": "fidjienne", "en": "Fijian"},
    "samoan": {"fr": "samoane", "en": "Samoan"},
}

_EEZ_RE = re.compile(
    r"^(?P<nation>.+?)\s+Exclusive Economic Zone\s*$",
    re.IGNORECASE,
)
_FR_ZEE_RE = re.compile(r"^Zone économique exclusive\s+(?P<adj>.+?)\s*$", re.IGNORECASE)
_FR_ADJ_EN = {v["fr"]: v["en"] for v in _NATION_ADJ.values()}
_PAREN_RE = re.compile(r"\s*\(([^)]+)\)\s*$")
_DUP_PAREN_RE = re.compile(r"\s*\(([^)]+)\)\s*\(\1\)", re.IGNORECASE)

_SOURCE_LABEL = {
    "vliz-local": "VLIZ",
    "marineregions": "MarineRegions",
    "openmeteo": "Open-Meteo",
    "openmeteo-gfs": "Open-Meteo",
    "openmeteo-gfs-wave": "Open-Meteo",
    "cdse": "CDSE",
    "emodnet": "EMODnet",
    "atlas": "Atlas BI",
    "bi": "Blue Intelligence",
    "gebco": "GEBCO",
    "osm": "OpenStreetMap",
    "overpass": "OpenStreetMap",
}

# Statuts de perle (ici_engine) : ce ne sont pas des ids de producteur.
_SOURCE_STATUS = frozenset({"ok", "error", "pending", "ready"})
_FORBIDDEN_SOURCE_LABELS = frozenset({"ok", "error", "pending"})


def official_mini_path() -> Path:
    return Path(__file__).resolve().parent / "tests" / "fixtures" / "official_mini.json"


def load_official_mini() -> dict:
    return json.loads(official_mini_path().read_text(encoding="utf-8"))


def _en(lang: str) -> bool:
    return str(lang or "fr").lower().startswith("en")


def _num(value: Any, lang: str, digits: int | None = None) -> str | None:
    if not isinstance(value, (int, float)):
        return None
    if digits is None:
        text = str(int(value)) if float(value).is_integer() else str(round(float(value), 2))
    else:
        text = f"{float(value):.{digits}f}"
    return text if _en(lang) else text.replace(".", ",")


def _dedupe_parens(text: str) -> str:
    out = str(text or "").strip()
    while True:
        nxt = _DUP_PAREN_RE.sub(r" (\1)", out)
        if nxt == out:
            return out
        out = nxt


def _split_paren(name: str) -> tuple[str, str | None]:
    raw = str(name or "").strip()
    found: list[str] = []
    while True:
        match = _PAREN_RE.search(raw)
        if not match:
            break
        found.append(match.group(1).strip())
        raw = raw[: match.start()].rstrip()
    return raw, found[0] if found else None


def _nation_adj(nation: str) -> dict[str, str] | None:
    key = re.sub(r"\s+", " ", str(nation or "").strip().lower())
    key = re.sub(r"^(the|l['e]|la|le)\s+", "", key)
    return _NATION_ADJ.get(key)


def localize_zee_name(zee: dict | None, lang: str = "fr") -> str:
    """Gabarit : « Zone économique exclusive française (Guadeloupe) » /
    « French EEZ (Guadeloupe) ». Jamais de parenthèses doublées. RC32 : table
    `toponyms` (exonyme de la langue du récit, îles partagées distinguées)."""
    en = _en(lang)
    table = TERRITORY["en" if en else "fr"]
    if not isinstance(zee, dict):
        return "High seas" if en else "Haute mer"
    raw = str(zee.get("name") or "").strip()
    if zee.get("ashore") or raw.startswith("À terre"):
        extra = raw[len("À terre"):].strip() if raw.startswith("À terre") else ""
        extra = extra.strip(" ()")
        if extra:
            return f"Ashore ({extra})" if en else f"À terre ({extra})"
        return "Ashore" if en else "À terre"
    if not zee.get("mrgid") or raw in {"", "Haute mer", "High seas"}:
        return "High seas" if en else "Haute mer"

    from toponyms import sheet_label  # noqa: PLC0415
    mrgid = zee.get("mrgid")
    try:
        mrgid = int(mrgid) if mrgid is not None else None
    except (TypeError, ValueError):
        mrgid = None
    spoken = sheet_label(raw, lang, mrgid=mrgid, territory=zee.get("territory"))
    if spoken:
        return _dedupe_parens(spoken)

    base, paren = _split_paren(raw)
    territory = table.get(str(zee.get("territory") or ""))
    extra = territory or paren

    fr_match = _FR_ZEE_RE.match(base)
    if fr_match and en:
        adj_fr = fr_match.group("adj").strip().lower()
        en_adj = _FR_ADJ_EN.get(adj_fr) or adj_fr
        label = f"{en_adj} EEZ"
        if extra and extra.lower() not in label.lower():
            label = f"{label} ({extra})"
        return _dedupe_parens(label)

    match = _EEZ_RE.match(base)
    adj = _nation_adj(match.group("nation")) if match else None
    if adj:
        label = f"{adj['en']} EEZ" if en else f"Zone économique exclusive {adj['fr']}"
    elif en:
        label = re.sub(r"Exclusive Economic Zone", "EEZ", base, flags=re.I).strip() or base
    else:
        if re.search(r"Exclusive Economic Zone", base, re.I):
            nation = re.sub(r"\s*Exclusive Economic Zone\s*", "", base, flags=re.I).strip()
            label = f"Zone économique exclusive ({nation})" if nation else "Zone économique exclusive"
        else:
            label = base
    if extra and extra.lower() not in label.lower():
        label = f"{label} ({extra})"
    return _dedupe_parens(label)


_PLACE_EN = {
    "nouvelle-calédonie": "New Caledonia",
    "nouvelle-caledonie": "New Caledonia",
    "wallis-et-futuna": "Wallis and Futuna",
    "polynésie française": "French Polynesia",
    "polynesie francaise": "French Polynesia",
    "la réunion": "Réunion",
    "la reunion": "Réunion",
    "la sardaigne": "Sardinia",
    "corse": "Corsica",
    "(corse)": "(Corsica)",
}


def localize_place_name(name: str | None, lang: str = "fr") -> str:
    from toponyms import origin_name  # noqa: PLC0415
    text = origin_name(str(name or "").strip())
    if not text:
        return ""
    if _en(lang):
        text = re.sub(r"Marine Protected Area", "Marine protected area", text, flags=re.I)
        text = re.sub(r"Exclusive Economic Zone", "EEZ", text, flags=re.I)
        text = re.sub(r"Aire marine protégée", "Marine protected area", text, flags=re.I)
        low = text.lower()
        for fr, en_name in _PLACE_EN.items():
            if fr in low:
                text = re.sub(re.escape(fr), en_name, text, flags=re.I)
        if re.search(r"Zone économique exclusive", text, re.I):
            text = localize_zee_name({"name": text, "mrgid": 1}, lang)
    else:
        text = re.sub(r"Marine Protected Area", "Aire marine protégée", text, flags=re.I)
        if re.search(r"Exclusive Economic Zone", text, re.I):
            text = localize_zee_name({"name": text, "mrgid": 1}, lang)
    return _dedupe_parens(text)


def signature(moment: dict | None) -> str:
    """SHA-1 des champs stables (contrat § 1.1). Un mille de plus ne change rien."""
    moment = moment or {}
    here = moment.get("here") if isinstance(moment.get("here"), dict) else {}
    zee = here.get("zee") if isinstance(here.get("zee"), dict) else {}
    entry = here.get("entry")
    if entry is None and isinstance(zee.get("entry"), dict):
        entry = zee.get("entry")
    payload = {
        "alerts": [a.get("id") for a in (moment.get("alerts") or []) if isinstance(a, dict)],
        "mrgid": zee.get("mrgid"),
        "entry": entry,
        "around": [x.get("title") for x in (moment.get("around") or []) if isinstance(x, dict)],
        "to": (moment.get("leg") or {}).get("to") if isinstance(moment.get("leg"), dict) else None,
        "regime": (moment.get("leg") or {}).get("regime") if isinstance(moment.get("leg"), dict) else None,
    }
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def build_moment(
    perle: dict | None,
    clock_point: dict | None,
    leg: dict | None,
    skipper_thresholds: dict | list | None,
    lang: str = "fr",
) -> dict:
    """Assemble un Moment. `lang` (défaut fr) localise here.zee / entry / mpa / sentences."""
    pearl = perle if isinstance(perle, dict) else {}
    clock = clock_point if isinstance(clock_point, dict) else {}
    jambe = leg if isinstance(leg, dict) else {}
    here = _here(pearl, clock, lang)
    alerts = _alerts(pearl, clock, jambe, skipper_thresholds, here, lang)
    around = _around(pearl, lang)
    moment = {
        "t": _iso(clock.get("iso") or clock.get("t") or pearl.get("t")),
        "pos": _pos(clock, pearl),
        "mode": clock.get("mode") or jambe.get("mode") or "follow",
        "leg": _leg(jambe, clock),
        "alerts": alerts,
        "here": here,
        "around": around,
        "sources": _sources(pearl, clock),
    }
    moment["signature"] = signature(moment)
    return moment


def _threshold(thresholds: dict | list | None, *keys: str, default: float) -> float:
    if isinstance(thresholds, dict):
        for key in keys:
            value = thresholds.get(key)
            if isinstance(value, (int, float)):
                return float(value)
        rows = thresholds.get("thresholds")
        if isinstance(rows, list):
            return _threshold(rows, *keys, default=default)
    if isinstance(thresholds, list):
        wanted = set(keys)
        for row in thresholds:
            if not isinstance(row, dict) or row.get("id") not in wanted:
                continue
            value = row.get("value")
            if isinstance(value, (int, float)):
                return float(value)
    return default


def _as_float(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _parse_iso(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _iso(value: Any) -> str | None:
    parsed = _parse_iso(value)
    if parsed is None:
        return str(value) if value else None
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _date_token(value: Any) -> str:
    parsed = _parse_iso(value)
    if parsed is None:
        return "undated"
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d")


def _pos(clock: dict, pearl: dict) -> dict:
    at = pearl.get("at") if isinstance(pearl.get("at"), dict) else {}
    lat = _as_float(clock.get("lat"))
    if lat is None:
        lat = _as_float(at.get("lat") if at else pearl.get("lat"))
    lon = _as_float(clock.get("lon"))
    if lon is None:
        lon = _as_float(at.get("lon") if at else pearl.get("lon"))
    return {"lat": lat, "lon": lon}


def _leg(jambe: dict, clock: dict) -> dict:
    kn = _as_float(clock.get("speedKnots"))
    if kn is None:
        kn = _as_float(jambe.get("kn") or jambe.get("plannedKnots"))
    heading = _as_float(clock.get("bearing"))
    if heading is None:
        heading = _as_float(jambe.get("headingDeg"))
    remaining = _as_float(jambe.get("remainingNm"))
    done = _as_float(jambe.get("doneNm"))
    from_nm = _as_float(jambe.get("fromNm"))
    to_nm = _as_float(jambe.get("toNm"))
    sail = _as_float(clock.get("sailNm"))
    if remaining is None and to_nm is not None and sail is not None:
        remaining = max(0.0, to_nm - sail)
    if done is None and from_nm is not None and sail is not None:
        done = max(0.0, sail - from_nm)
    day = jambe.get("day")
    if day is None:
        hours = _as_float(clock.get("tHours") or jambe.get("tHours"))
        if hours is not None:
            day = int(hours // 24)
    basis = clock.get("basis") or jambe.get("basis") or "planned"
    if basis == "polar":
        basis = "measured"
    if basis not in {"planned", "measured"}:
        basis = "planned"
    eta = jambe.get("eta") if isinstance(jambe.get("eta"), dict) else None
    if eta:
        eta = {k: eta.get(k) for k in ("p10", "p90") if eta.get(k)}
    regime = clock.get("regime") or clock.get("kind") or jambe.get("regime") or "climatology"
    return {
        "from": jambe.get("from"),
        "to": jambe.get("to"),
        "day": day,
        "kn": kn,
        "basis": basis,
        "remainingNm": remaining,
        "doneNm": done,
        "headingDeg": heading,
        "eta": eta,
        "regime": regime,
    }


def _poe_list(pearl: dict) -> list[dict]:
    rows = pearl.get("poe") if isinstance(pearl.get("poe"), list) else []
    return [p for p in rows if isinstance(p, dict) and p.get("name")]


def _amp_list(pearl: dict) -> list[dict]:
    rows = pearl.get("amp") if isinstance(pearl.get("amp"), list) else []
    return [a for a in rows if isinstance(a, dict) and a.get("name")]


def _wind_kn(clock: dict, pearl: dict) -> float | None:
    kn = _as_float(clock.get("windKnots"))
    if kn is not None:
        return kn
    weather = pearl.get("weather") if isinstance(pearl.get("weather"), dict) else {}
    wind = weather.get("wind") if isinstance(weather.get("wind"), dict) else {}
    return _as_float(wind.get("speedKnots") if wind else weather.get("speedKnots"))


def _hs_m(clock: dict, pearl: dict) -> float | None:
    for key in ("hs", "hsP50"):
        hs = _as_float(clock.get(key))
        if hs is not None:
            return hs
    weather = pearl.get("weather") if isinstance(pearl.get("weather"), dict) else {}
    wave = weather.get("wave") if isinstance(weather.get("wave"), dict) else {}
    return _as_float(wave.get("hs") if wave else weather.get("hs"))


def _climo(pearl: dict) -> dict | None:
    raw = pearl.get("climo") if isinstance(pearl.get("climo"), dict) else None
    if raw is None and isinstance(pearl.get("climatology"), dict):
        raw = pearl["climatology"]
    return raw


def _cyclone(pearl: dict) -> dict | None:
    raw = _climo(pearl)
    if not raw:
        return None
    if isinstance(raw.get("cyclones"), dict):
        return raw["cyclones"]
    if isinstance(raw.get("cyclone"), dict):
        return raw["cyclone"]
    point = raw.get("point") if isinstance(raw.get("point"), dict) else {}
    if isinstance(point.get("cyclone"), dict):
        return point["cyclone"]
    return None


def _in_cyclone_season(cyc: dict | None) -> bool | None:
    if not isinstance(cyc, dict):
        return None
    if cyc.get("in_season") is True:
        return True
    if cyc.get("in_season") is False:
        return False
    known = False
    for key in ("nearby", "tracks_in_month", "count", "cyclones"):
        val = cyc.get(key)
        if isinstance(val, (int, float)):
            known = True
            if val > 0:
                return True
    return False if known else None


def _amp_restriction(amp: dict, lang: str = "fr") -> str | None:
    from amp_traffic import traffic_kind
    kind = amp.get("traffic") or traffic_kind(amp.get("entry"), amp.get("speed"))
    if kind == "forbidden":
        return "no transit" if lang == "en" else "circulation interdite"
    if kind == "regulated":
        return "regulated transit" if lang == "en" else "circulation régulée"
    if amp.get("restricted") is True or amp.get("restriction") is True:
        return str(amp.get("restriction") if isinstance(amp.get("restriction"), str) else "restricted")
    if isinstance(amp.get("restriction"), str) and amp["restriction"].strip():
        return amp["restriction"].strip()
    iucn = amp.get("iucn_cat") or amp.get("iucn")
    if iucn:
        return f"IUCN {iucn}"
    designation = amp.get("designation")
    if isinstance(designation, str) and designation.strip():
        return designation.strip()
    return None


def _local_hour(when: datetime, lon: float | None) -> float:
    utc = when.astimezone(timezone.utc)
    offset = (float(lon) / 15.0) if lon is not None else 0.0
    local = utc + timedelta(hours=offset)
    return local.hour + local.minute / 60.0


def _is_night(hour: float) -> bool:
    return hour >= 18.0 or hour < 6.0


def _here(pearl: dict, clock: dict, lang: str) -> dict:
    zee_in = pearl.get("zee") if isinstance(pearl.get("zee"), dict) else None
    zee_name = localize_zee_name(zee_in, lang)
    if not (zee_in or {}).get("mrgid") and not zee_is_high_seas(zee_in, pearl) and not (
        (zee_in or {}).get("ashore") or str((zee_in or {}).get("name") or "").startswith("À terre")
    ):
        zee_name = "Unknown EEZ" if _en(lang) else "ZEE inconnue"
    poes = _poe_list(pearl)
    ports = [localize_place_name(p.get("name"), lang) for p in poes]
    entry = {"known": bool(ports), "ports": ports}
    amps = []
    for amp in _amp_list(pearl):
        item = {
            "name": localize_place_name(amp.get("name"), lang),
            "nm": _as_float(amp.get("nm")),
            "url": amp.get("visit_url") or amp.get("url") or amp.get("visitUrl"),
            "site_id": amp.get("siteId") or amp.get("site_id") or amp.get("id"),
            "iucn_cat": amp.get("iucn_cat") or amp.get("iucn"),
            "designation": amp.get("designation"),
            "source": amp.get("source"),
            "entry": amp.get("entry"),
            "speed": amp.get("speed"),
            "traffic": amp.get("traffic"),
        }
        slim = {k: v for k, v in item.items() if v not in (None, "")}
        if "inside" in amp:
            slim["inside"] = bool(amp.get("inside"))
        if slim.get("site_id"):
            slim["siteId"] = slim["site_id"]
        amps.append(slim)
    aton = pearl.get("aton") if isinstance(pearl.get("aton"), dict) else {}
    seamarks = []
    for mark in aton.get("nearby") or []:
        if not isinstance(mark, dict) or not mark.get("name"):
            continue
        seamarks.append({
            "name": localize_place_name(mark.get("name"), lang),
            **({"nm": _as_float(mark["nm"])} if _as_float(mark.get("nm")) is not None else {}),
        })
    emodnet = pearl.get("emodnet") if isinstance(pearl.get("emodnet"), dict) else {}
    seabed = emodnet.get("seabed") if isinstance(emodnet.get("seabed"), dict) else None
    weather = _weather_here(pearl, clock)
    sentences = _sentences(zee_name, zee_in, poes, amps, weather, lang, pearl)
    links = _links(pearl, poes, amps)
    return {
        "zee": {
            "name": zee_name,
            "mrgid": (zee_in or {}).get("mrgid"),
            "entry": entry,
        },
        "entry": entry,
        "mpa": amps,
        "seamarks": seamarks,
        "seabed": seabed,
        "weather": weather,
        "sentences": sentences,
        "links": links,
    }


def _weather_here(pearl: dict, clock: dict) -> dict:
    bag = pearl.get("weather") if isinstance(pearl.get("weather"), dict) else {}
    out: dict[str, Any] = {}
    for key in ("status", "source", "reason", "model"):
        if bag.get(key) not in (None, ""):
            out[key] = bag[key]
    wind = bag.get("wind") if isinstance(bag.get("wind"), dict) else {}
    wave = bag.get("wave") if isinstance(bag.get("wave"), dict) else {}
    kn = _wind_kn(clock, pearl)
    hs = _hs_m(clock, pearl)
    if kn is not None or wind:
        block = dict(wind) if wind else {}
        if kn is not None:
            block["speedKnots"] = kn
        if clock.get("windFromDeg") is not None and block.get("dirFromDeg") is None:
            block["dirFromDeg"] = clock.get("windFromDeg")
        if block:
            out["wind"] = block
    if hs is not None or wave:
        block = dict(wave) if wave else {}
        if hs is not None:
            block["hs"] = hs
        if block:
            out["wave"] = block
    return out


# Territorial sea: a known port this close means the boat is not on the high seas.
TERRITORIAL_SEA_NM = 12.0


def _near_known_port(pearl: dict | None) -> bool:
    """A port, marina, harbour office or port of entry within TERRITORIAL_SEA_NM."""
    if not isinstance(pearl, dict):
        return False
    nearby = pearl.get("nearby") if isinstance(pearl.get("nearby"), dict) else {}
    rows = list(pearl.get("poe") or [])
    for key in ("marinas", "capitaineries", "wpi"):
        rows.extend(nearby.get(key) or [])
    for row in rows:
        if not isinstance(row, dict):
            continue
        nm = _as_float(row.get("nm"))
        if nm is not None and nm <= TERRITORIAL_SEA_NM:
            return True
    return False


def zee_is_high_seas(zee_in: dict | None, pearl: dict | None = None) -> bool:
    """« High seas » only from an EEZ answer that found none, far from any
    known port. Missing or failed EEZ data, ashore, or a port within the
    territorial sea: never high seas."""
    if not isinstance(zee_in, dict) or zee_in.get("unknown"):
        return False
    if zee_in.get("mrgid") or zee_in.get("ashore"):
        return False
    raw = str(zee_in.get("name") or "").strip()
    if raw.startswith("À terre"):
        return False
    sources = (pearl or {}).get("sources") if isinstance((pearl or {}).get("sources"), dict) else {}
    if sources.get("zee") in ("unavailable", "error"):
        return False
    return not _near_known_port(pearl)


def _sentences(
    zee_name: str,
    zee_in: dict | None,
    poes: list[dict],
    amps: list[dict],
    weather: dict,
    lang: str,
    pearl: dict | None = None,
) -> list[str]:
    en = _en(lang)
    out: list[str] = []
    if not zee_in or not zee_in.get("mrgid") or zee_in.get("ashore"):
        # Without a confirmed « no EEZ here », nothing is said about the EEZ.
        if zee_is_high_seas(zee_in, pearl):
            out.append(
                "The boat is on the high seas: no exclusive economic zone, no entry formalities to plan."
                if en else
                "Le bateau est en haute mer : aucune ZEE, pas de formalités d’entrée à prévoir."
            )
    else:
        out.append(
            _dedupe_parens(f"The boat is sailing in {zee_name}.")
            if en else
            _dedupe_parens(f"Le bateau navigue dans {zee_name}.")
        )
        if poes:
            listed = _list_places(poes, lang)
            out.append(
                f"Nearest official ports of entry: {listed}."
                if en else
                f"Ports d’entrée officiels les plus proches : {listed}."
            )
        else:
            out.append(
                "No official port of entry is known for this EEZ."
                if en else
                "Aucun port d’entrée officiel n’est connu pour cette ZEE."
            )
    if amps:
        inside = next((a for a in amps if a.get("inside") is True), None)
        if inside:
            name = localize_place_name(inside.get("name"), lang)
            kind = inside.get("traffic")
            if kind == "forbidden":
                tag = " (no transit)" if en else " (circulation interdite)"
            elif kind == "regulated":
                tag = " (regulated transit)" if en else " (circulation régulée)"
            else:
                tag = ""
            out.append(
                f"In the marine protected area {name}{tag}."
                if en else
                f"Dans l'aire marine protégée {name}{tag}."
            )
        else:
            nearest = amps[0]
            name = localize_place_name(nearest.get("name"), lang)
            nm = _num(nearest.get("nm"), lang)
            if nm is not None:
                out.append(
                    f"{nm} miles from {name}."
                    if en else
                    f"À {nm} milles de {name}."
                )
            else:
                listed = _list_places(amps, lang)
                out.append(
                    f"Marine protected areas nearby: {listed}."
                    if en else
                    f"Aires marines protégées à proximité : {listed}."
                )
    wind = (weather.get("wind") or {}) if isinstance(weather.get("wind"), dict) else {}
    wave = (weather.get("wave") or {}) if isinstance(weather.get("wave"), dict) else {}
    bits: list[str] = []
    kn = _num(wind.get("speedKnots"), lang)
    if kn is not None:
        bits.append(f"wind {kn} kn" if en else f"vent {kn} kn")
    hs = _num(wave.get("hs"), lang, 1)
    if hs is not None:
        bits.append(f"sea {hs} m" if en else f"mer {hs} m")
    if bits:
        out.append(
            ("Weather at the boat: " if en else "Météo au bateau : ") + ", ".join(bits) + "."
        )
    return [_dedupe_parens(s) for s in out if s]


def _list_places(items: list[dict], lang: str, max_n: int = 4) -> str:
    parts = []
    for item in items[:max_n]:
        name = localize_place_name(item.get("name"), lang)
        nm = _num(item.get("nm"), lang)
        parts.append(f"{name} ({nm} nm)" if nm is not None else name)
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    conj = " and " if _en(lang) else " et "
    return ", ".join(parts[:-1]) + conj + parts[-1]


def _links(pearl: dict, poes: list[dict], amps: list[dict]) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()

    def add(label: Any, url: Any) -> None:
        if not isinstance(url, str) or not url.startswith("http") or url in seen:
            return
        seen.add(url)
        out.append({"label": str(label or url), "url": url})

    for poe in poes:
        add(poe.get("name"), poe.get("url"))
    for amp in amps:
        add(amp.get("name"), amp.get("url") or amp.get("visit_url"))
    sat = pearl.get("satellites") if isinstance(pearl.get("satellites"), dict) else {}
    add(sat.get("source") or "CDSE", sat.get("link") or sat.get("url"))
    return out


def _around(pearl: dict, lang: str) -> list[dict]:
    en = _en(lang)
    out: list[dict] = []
    sat = pearl.get("satellites") if isinstance(pearl.get("satellites"), dict) else {}
    scene = sat.get("scene") if isinstance(sat.get("scene"), dict) else None
    if scene is None and isinstance(sat.get("scenes"), list) and sat["scenes"]:
        scene = sat["scenes"][0] if isinstance(sat["scenes"][0], dict) else None
    if scene and (scene.get("id") or scene.get("datetime") or scene.get("product")):
        when = _iso(scene.get("datetime"))
        product = scene.get("product") or scene.get("id")
        fact_bits = [str(product)] if product else []
        if when:
            fact_bits.append(when[:10])
        out.append({
            "kind": "satellite",
            "title": "Satellite image" if en else "Image satellite",
            "fact": " · ".join(fact_bits),
            "url": scene.get("url") or sat.get("link") or sat.get("url"),
        })
    climo = _climo(pearl)
    if climo:
        month = climo.get("month")
        cyc = _cyclone(pearl)
        bits: list[str] = []
        if isinstance(month, (int, float)):
            bits.append(f"month {int(month)}" if en else f"mois {int(month)}")
        rose = climo.get("rose") if isinstance(climo.get("rose"), dict) else None
        if rose is None:
            point = climo.get("point") if isinstance(climo.get("point"), dict) else {}
            rose = point.get("rose") if isinstance(point.get("rose"), dict) else None
        gale = None
        if isinstance(rose, dict):
            gale = rose.get("gale_pct")
        if isinstance(gale, (int, float)):
            g = _num(gale, lang, 1)
            bits.append(f"gale {g} %" if en else f"coup de vent {g} %")
        nearby = cyc.get("nearby") if isinstance(cyc, dict) else None
        if isinstance(nearby, (int, float)):
            bits.append(f"{int(nearby)} tracks" if en else f"{int(nearby)} traces")
        if bits:
            out.append({
                "kind": "climatology",
                "title": "Climatology" if en else "Climatologie",
                "fact": " · ".join(bits),
                "url": None,
            })
    sci = pearl.get("science")
    items = sci.get("nearby") if isinstance(sci, dict) else sci if isinstance(sci, list) else []
    for item in items or []:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        nm = _num(item.get("nm"), lang)
        fact = item["name"] if nm is None else f"{item['name']} ({nm} nm)"
        out.append({
            "kind": "science",
            "title": "Station passed" if en else "Station croisée",
            "fact": fact,
            "url": item.get("url"),
        })
        break
    nearby = pearl.get("nearby") if isinstance(pearl.get("nearby"), dict) else {}
    for marina in nearby.get("marinas") or []:
        if not isinstance(marina, dict) or not marina.get("name"):
            continue
        nm = _num(marina.get("nm"), lang)
        fact = marina["name"] if nm is None else f"{marina['name']} ({nm} nm)"
        out.append({
            "kind": "marina",
            "title": marina["name"],
            "fact": fact,
            "url": marina.get("url"),
        })
        break
    return out


def _is_source_status(raw: Any) -> bool:
    if isinstance(raw, bool) or raw is None:
        return True
    return str(raw).strip().lower() in _SOURCE_STATUS


def _sources(pearl: dict, clock: dict) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()

    def add(raw: Any) -> None:
        if raw in (None, "", False, True):
            return
        if isinstance(raw, bool):
            return
        if isinstance(raw, (list, tuple)):
            for item in raw:
                add(item)
            return
        token = str(raw).strip()
        if not token or token.lower() in _SOURCE_STATUS:
            return
        label = _SOURCE_LABEL.get(token, token)
        if label.strip().lower() in _FORBIDDEN_SOURCE_LABELS:
            return
        if label in seen:
            return
        seen.add(label)
        labels.append(label)

    src = pearl.get("sources") if isinstance(pearl.get("sources"), dict) else {}
    for key, value in src.items():
        if isinstance(value, (list, tuple)):
            add(value)
            continue
        if _is_source_status(value) or (
            isinstance(value, str) and value.strip() not in _SOURCE_LABEL
        ):
            add(key)
        else:
            add(value)
    add(clock.get("sources"))
    weather = pearl.get("weather") if isinstance(pearl.get("weather"), dict) else {}
    add(weather.get("source"))
    sat = pearl.get("satellites") if isinstance(pearl.get("satellites"), dict) else {}
    add(sat.get("source"))
    return labels


def _alerts(
    pearl: dict,
    clock: dict,
    jambe: dict,
    thresholds: dict | list | None,
    here: dict,
    lang: str,
) -> list[dict]:
    en = _en(lang)
    gale = _threshold(thresholds, "galeKt", "windKt", "wind_max_kt", default=DEFAULT_GALE_KT)
    hs_lim = _threshold(thresholds, "hsAlertM", "hsM", "hs_max_m", default=DEFAULT_HS_M)
    when = clock.get("iso") or clock.get("t")
    token = _date_token(when)
    zee = pearl.get("zee") if isinstance(pearl.get("zee"), dict) else {}
    zee_name = (here.get("zee") or {}).get("name") or localize_zee_name(zee, lang)
    out: list[dict] = []

    kn = _wind_kn(clock, pearl)
    if kn is not None and kn >= gale:
        kn_s, lim_s = _num(kn, lang), _num(gale, lang)
        out.append({
            "id": f"wind-{token}",
            "kind": "wind",
            "severity": "alert",
            "title": "Gale" if en else "Coup de vent",
            "fact": (
                f"Wind {kn_s} kn ≥ {lim_s} kn."
                if en else
                f"Vent {kn_s} kn ≥ {lim_s} kn."
            ),
            "until": None,
        })

    hs = _hs_m(clock, pearl)
    if hs is not None and hs >= hs_lim:
        hs_s, lim_s = _num(hs, lang, 1), _num(hs_lim, lang, 1)
        out.append({
            "id": f"sea-{token}",
            "kind": "sea",
            "severity": "alert",
            "title": "Sea" if en else "Mer",
            "fact": (
                f"Hs {hs_s} m ≥ {lim_s} m."
                if en else
                f"Hs {hs_s} m ≥ {lim_s} m."
            ),
            "until": None,
        })

    cyc = _cyclone(pearl)
    in_season = _in_cyclone_season(cyc)
    month = clock.get("month")
    if month is None:
        parsed = _parse_iso(when)
        if parsed is not None:
            month = parsed.month
    climo = _climo(pearl)
    climo_month = climo.get("month") if isinstance(climo, dict) else None
    month_ok = True
    if isinstance(month, (int, float)) and isinstance(climo_month, (int, float)):
        month_ok = int(month) == int(climo_month)
    if in_season and month_ok:
        nearby = cyc.get("nearby") if isinstance(cyc, dict) else None
        if isinstance(nearby, (int, float)):
            fact = (
                f"{int(nearby)} cyclone tracks this month."
                if en else
                f"{int(nearby)} traces de cyclone ce mois-ci."
            )
        else:
            fact = (
                "Cyclone season in this zone this month."
                if en else
                "Saison cyclonique dans cette zone ce mois-ci."
            )
        out.append({
            "id": f"cyclone-{int(month) if isinstance(month, (int, float)) else token}",
            "kind": "cyclone",
            "severity": "alert",
            "title": "Cyclone" if en else "Cyclone",
            "fact": fact,
            "until": None,
        })

    if zee.get("mrgid") and not zee.get("ashore") and not _poe_list(pearl) and not zee.get("gold"):
        out.append({
            "id": f"entry-{zee.get('mrgid')}",
            "kind": "entry",
            "severity": "decision",
            "title": "Entry formalities" if en else "Formalités d’entrée",
            "fact": (
                f"No official port of entry is known for {zee_name}."
                if en else
                f"Aucun port d’entrée officiel n’est connu pour {zee_name}."
            ),
            "until": None,
        })

    for amp in _amp_list(pearl):
        restriction = _amp_restriction(amp, lang)
        if not restriction:
            continue
        name = localize_place_name(amp.get("name"), lang)
        nm = _num(amp.get("nm"), lang)
        where = f"{name} ({nm} nm)" if nm is not None else name
        key = amp.get("site_id") or amp.get("id") or name
        out.append({
            "id": f"mpa-{key}",
            "kind": "mpa",
            "severity": "decision",
            "title": "Marine protected area" if en else "Aire marine protégée",
            "fact": (
                f"{where}: {restriction}."
            ),
            "until": None,
        })

    eta = jambe.get("eta") if isinstance(jambe.get("eta"), dict) else {}
    arrival = _parse_iso(eta.get("p10") or eta.get("p50") or eta.get("p90"))
    lon = _as_float((clock.get("lon") if clock.get("lon") is not None else (pearl.get("at") or {}).get("lon") if isinstance(pearl.get("at"), dict) else pearl.get("lon")))
    if arrival is not None:
        hour = _local_hour(arrival, lon)
        if _is_night(hour):
            stamp = arrival.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
            out.append({
                "id": f"night-{arrival.astimezone(timezone.utc).strftime('%Y-%m-%d')}",
                "kind": "night",
                "severity": "decision",
                "title": "Night arrival" if en else "Arrivée de nuit",
                "fact": (
                    f"ETA {stamp} is at night."
                    if en else
                    f"ETA {stamp} : arrivée de nuit."
                ),
                "until": None,
            })

    for alert in out:
        alert["fact"] = _dedupe_parens(str(alert.get("fact") or ""))
    return [a for a in out if a.get("fact")]
