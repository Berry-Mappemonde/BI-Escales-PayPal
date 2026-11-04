"""Script du film 2:30 — brut (règles), sélection, version rédigée.

Le LLM ne produit jamais un nombre : `filter_numbers` + balises `[[ev:id]]`.
Rédigé **au clic** Rédigé : Super écrit le FR et l'EN en parallèle (brut
de chaque langue) ; Ultra édite puis juge le FR si le plafond juge est ouvert. GET et
`warm_film_story` ne lancent aucun modèle. Repli : le brut.

Au recalcul du stock, VL propose des ids du sac ;
Lightning ne peut qu'en retirer pour le budget. Modèles éteints : repli
déterministe, redites remplacées, arrêt à `film_char_budget`. Ouvrir
Suivre ne rappelle rien.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from climo_events import climo_sentence, dose_climo_changes, notable_climo_changes
from story_cascade import cascade_text, expand_spoken_units, filter_numbers, split_short_sentences
import toponyms
from voyage_clock import OFFICIAL_T0

FILM_MAX_CHARS = 2400
FILM_BUDGET_CHARS = 2400
# Plus de fenêtre fixe 2160–2640. Conservés pour les pads de tests 2:30.
# `written_is_valid` utilise `film_write_window(seconds)`.
FILM_WRITE_MIN = 2160
FILM_WRITE_MAX = 2640
FILM_CHAPTER_FLOOR = 120
FILM_CHAPTER_MAX_CHANGES = 4   # arrivée + un fait de mer + la marina de l'escale + approche (27 sept. ; était 3)
# Ancre au nom du lieu − 12 caractères. Le client ne rajoute plus
# ce décalage : sinon le bateau est ~2 s devant la voix.
FILM_VOICE_LOOKAHEAD_CHARS = 12
KIND_GROUP_FRAC = 0.10
FILM_MIN_EVENTS = 6
FILM_MAX_EVENTS = 9
FILM_GAP_FRAC = 0.03
KIND_RANK = {"wx": 0, "climo": 1, "sci": 2, "amp": 3, "project": 3, "zee": 4, "coast": 4, "poe": 5, "note": 6, "stop": 7}
SCORED = frozenset({"wx", "climo", "sci", "amp", "project", "zee", "coast", "poe", "note"})
CANDIDATE_KINDS = frozenset({"stop", "zee", "coast", "amp", "project", "poe", "wx", "climo", "sci", "note"})
BUBBLE_KINDS = frozenset({"stop", "zee", "coast", "wx", "amp", "project", "sci", "climo"})
ROUTE_NAMING_KINDS = frozenset({"zee-enter", "coast", "port"})
SHORT_CROSSING_MS = 3 * 86_400_000
AMP_NEAR_NM = 30.0
PROJECT_NEAR_NM = 30.0
STATION_NEAR_NM = 30.0  # Les flotteurs Argo du large (15-30 nm) se disent aussi
LONG_AMP_PROJECT = 3
CLUSTER_MS = 86_400_000
SKIPPER_GALE_KT = 34.0
HS_BUBBLE_M = 3.0
# Plus de rotation « Puis / À la jambe suivante ». Formes liées au contenu
# (première étape, traversée longue, saut d'île, dernière étape) — chapter_shape.
CONNECTORS = {
    "fr": ["Le lendemain", "Puis", "D'île en île", "La longue traversée", "Pour la dernière étape"],
    "en": ["The next day", "Then", "From island to island", "The long crossing", "For the last stage"],
}
FORBIDDEN_FILM_RE = re.compile(
    r"\bjambe\b|zone économique exclusive|exclusive economic zone|"
    r"\bCouloirs\b|\bShipping lanes\b|À surveiller|To watch\.|"
    r"à portée de|within reach of|\bde de\b",
    re.I,
)
_EN_TITLE_RE = re.compile(
    r"\b(the|center|deposit|licence|license|prohibition|exclusive economic|careenage)\b",
    re.I,
)
_EN_STOP_RE = re.compile(
    r"\b(the|of|and|for|in|to|with|from|into|on|at|by|a|an|global|project|"
    r"blue|economy|caribbean|coral|reef|marine|coastal|laboratory|ship|test|"
    r"innovations|extreme|conditions|coordination|initiative|management|"
    r"strategies|technologies|solutions|bycatch|tropical|ecosystem|fisheries|"
    r"regional|oceanscape|unleashing|cetacean|future|expedition|restoration|"
    r"combatting|fishing|smartphone|technology|educational|recognition|"
    r"underwater|monitoring|gardeners|conservation|children|yacht|club|small|"
    r"harbour|harbor|lesser|antilles|friends|system|intellireefs|speSeas)\b",
    re.I,
)
_FR_MARK_RE = re.compile(
    r"[àâäéèêëïîôùûüçœ]|\b(le|la|les|un|une|des|du|aux|pour|dans|sur|avec)\b",
    re.I,
)
_GENERIC_HARBOR_RE = re.compile(
    r"^(petite marina|marina|harbour|harbor|autorités portuaires|authorities)\b",
    re.I,
)
_DATE_FR_RE = re.compile(
    r"(1er|\d{1,2}) (janvier|février|mars|avril|mai|juin|juillet|août|septembre|"
    r"octobre|novembre|décembre)(?: \d{4})?",
    re.I,
)
_DATE_EN_RE = re.compile(
    r"(\d{1,2}) (January|February|March|April|May|June|July|August|September|"
    r"October|November|December)(?: \d{4})?",
    re.I,
)

_FR_DAY_WORDS = {
    "premier": "1er", "un": "1", "deux": "2", "trois": "3", "quatre": "4", "cinq": "5",
    "six": "6", "sept": "7", "huit": "8", "neuf": "9", "dix": "10", "onze": "11",
    "douze": "12", "treize": "13", "quatorze": "14", "quinze": "15", "seize": "16",
    "dix-sept": "17", "dix-huit": "18", "dix-neuf": "19", "vingt": "20",
    "vingt et un": "21", "vingt-et-un": "21", "vingt-deux": "22", "vingt-trois": "23",
    "vingt-quatre": "24", "vingt-cinq": "25", "vingt-six": "26", "vingt-sept": "27",
    "vingt-huit": "28", "vingt-neuf": "29", "trente": "30", "trente et un": "31",
    "trente-et-un": "31",
}
_FR_SPELLED_DATE_RE = re.compile(
    r"\b(" + "|".join(sorted((re.escape(k) for k in _FR_DAY_WORDS), key=len, reverse=True)) + r")"
    r"(?= (?:janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)\b)",
    re.I,
)


def _digit_fr_dates(text: str) -> str:
    """« le quinze octobre » → « le 15 octobre » : Nemotron épelle parfois les dates,
    et les contrôles de date (relecture, ancres) ne lisent que les chiffres."""
    return _FR_SPELLED_DATE_RE.sub(lambda m: _FR_DAY_WORDS[m.group(1).casefold()], text or "")

_LEAD_DATE_FR_RE = re.compile(
    r"^(?:Le |À partir du )?((?:1er|\d{1,2}) (?:janvier|février|mars|avril|mai|juin|"
    r"juillet|août|septembre|octobre|novembre|décembre)(?: \d{4})?), ",
    re.I,
)
_LEAD_DATE_EN_RE = re.compile(
    r"^(?:On )?((?:\d{1,2}) (?:January|February|March|April|May|June|July|"
    r"August|September|October|November|December)(?: \d{4})?), ",
    re.I,
)
# Climatologie et projets avant les eaux (gabarit FILM_DISCOURS § 4).
# AMP devant les eaux, dans les mêmes fenêtres (on ne réécrit pas la sélection).
CHANGE_PRIORITY = {
    "escale": 0, "approche": 1, "alert-on": 2, "climo": 3, "amp": 4, "station": 4,
    "project": 5, "zee-enter": 6, "coast": 6, "marina": 7, "cyclone": 8, "culture": 9,
    "port": 10, "regime": 11, "alert-off": 12,
}
BUBBLE_KIND = {
    "escale": "stop", "approche": "stop", "alert-on": "wx", "alert-off": "wx",
    "zee-enter": "zee", "coast": "coast", "station": "sci", "amp": "amp",
    "project": "project", "regime": "climo", "climo": "climo",
    "marina": "stop", "cyclone": "climo", "culture": "stop", "port": "poe",
    "buoy": "sci", "poe": "poe", "anchorage": "stop",
    "aton": "sci", "cable": "note", "depth": "note", "piracy": "wx", "satellite": "sci",
}
AROUND_TO_KIND = {
    "marina": "marina", "science": "station", "station": "station",
    "mpa": "amp", "amp": "amp", "project": "project", "cyclone": "cyclone",
    "culture": "culture", "port": "port",
    "anchorage": "anchorage", "poe": "poe", "buoy": "buoy",
    "aton": "aton", "balise": "aton", "beacon": "aton", "seamark": "aton",
    "cable": "cable", "depth": "depth", "piracy": "piracy", "satellite": "satellite",
}
NAMELESS_CYCLONE = re.compile(
    r"traces de cyclone|cyclone tracks|saison cyclonique|cyclone season|ce mois-ci|this month",
    re.I,
)
CYCLONE_YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")
DIST_UNIT_RE = re.compile(
    r"(?P<num>\d+(?:[ \u00a0]\d{3})*(?:[.,]\d+)?)\s*"
    r"(?P<unit>nm|milles?\s+nautiques?|nautical\s+miles?)\b",
    re.I,
)
DECIMAL_RE = re.compile(r"\d+[.,]\d{1,2}(?!\d)")
GENERIC_CYCLONE = frozenset({"cyclone", "cyclones"})
COLOR_KINDS = frozenset({
    "station", "zee-enter", "coast", "amp", "project", "climo", "regime", "marina", "cyclone", "culture", "port",
})
FILM_CHAPTER_MAX_FREE = 10
# Budget intégral proportionnel à la durée de la jambe — 1 item par
# 1,5 jour de mer, plancher 4 (une jambe d'un jour garde 3-4 items), plafond 16.
FILM_FREE_ITEM_DAYS = 1.5
FILM_FREE_ITEMS_MAX = 16
# Le cap annoncé au départ est le relèvement des 30 premiers milles de la trace.
FILM_INITIAL_HEADING_NM = 30.0
FILM_FREE_MAX_WORDS = 800
FILM_ESTIMATE_CPS = 15  # débit constant (27 sept.) : durée = caractères ÷ 15 ; pas de recalibrage
FILM_TIER_SHORT = 2     # 2:30 — ouverture, eaux, une AMP et un projet, escales
FILM_TIER_MEDIUM = 3    # 3:00 — + côtes et climatologie
FILM_TIER_FULL = 4      # intégral — tout, sans plafond
# Bouée, formalité de port d'entrée, mouillage. Sac VS1 ; intégral
# seulement, une fois par famille sur une longue jambe. Pas le 2:30.
DC2_KINDS = frozenset({"buoy", "poe", "anchorage"})
# Balise, câble, profondeur, piraterie, satellite. Même verrou : sac
# et intégral (une fois par famille / longue jambe). Pas le 2:30.
# Satellite : légende déjà dans le stock, sinon silence — on n'invente pas
# « image satellite au-dessus du bateau ».
DC3_KINDS = frozenset({"aton", "cable", "depth", "piracy", "satellite"})
DC_DOSAGE_KINDS = DC2_KINDS | DC3_KINDS
# Amp + DC2 + DC3 : le sac VS1. Une entrée par famille.
DC_FAMILY_KINDS = frozenset({"amp"}) | DC_DOSAGE_KINDS
# Id d'avis réservé. Le repli VS1 ne le prend pas.
TV1_WATCH_KIND = "watch"
TV1_WATCH_ID = "dc:watch"
FALLBACK_KIND_ORDER = (
    "amp", "buoy", "poe", "anchorage", "aton", "cable", "depth", "piracy", "satellite",
)
FILM_CHOICE_NS = "film-choice"
FILM_CHOICE_TTL_S = 7 * 86400.0
# 2:30 / 3:00 : quelques sujets, pas une phrase par famille pour montrer.
FALLBACK_DC_CAP_SHORT = 2
FALLBACK_DC_CAP_MEDIUM = 3
DC3_KIND_ALIASES = {
    "balise": "aton", "beacon": "aton", "seamark": "aton",
    "cable-alert": "cable", "câble": "cable",
    "profondeur": "depth", "bathy": "depth", "gebco": "depth",
    "piraterie": "piracy",
    "satellite-scene": "satellite",
}
GENERIC_ANCHORAGE_NAMES = frozenset({"anchorage", "anchor_berth", "mooring", "mouillage"})
GENERIC_ATON_NAMES = frozenset({
    "aton", "balise", "beacon", "lighthouse", "light", "feu", "phare",
    "seamark", "balisage", "aid to navigation", "aids to navigation",
    "light_major", "light_minor", "light_vessel",
    "buoy_lateral", "buoy_cardinal", "buoy_special_purpose",
    "buoy_safe_water", "buoy_isolated_danger", "buoy_installation",
    "beacon_lateral", "beacon_cardinal", "beacon_special_purpose",
    "beacon_isolated_danger", "beacon_safe_water",
    "landmark", "daymark", "fog_signal", "radar_reflector", "mooring",
})
GENERIC_CABLE_NAMES = frozenset({
    "cable", "câble", "submarine cable", "câble sous-marin",
    "active", "inactive", "planned", "operational", "unknown", "status",
    "in service", "out of service", "en service",
})
GENERIC_CABLE_LABEL_RE = re.compile(
    r"cables?\s+de\s+tel[eé]fono|telephone\s+cables?|power\s+cables?|"
    r"cables?\s+sous-marins?|submarine\s+cables?",
    re.I,
)
GENERIC_SATELLITE_TITLES = frozenset({
    "image satellite", "satellite image", "satellite", "sentinel",
    "sentinel-2", "sentinel-2-l2a", "observation", "cdse", "scene",
})
ATON_TYPE_KEY_RE = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)+$")
SATELLITE_PRODUCT_RE = re.compile(
    r"^(?:s2[ab]_|sentinel|l2a|l1c|cdse|msil)",
    re.I,
)
ROUTE_NEAR_NM = 15.0
NM_TO_KM = 1.852
ALWAYS_KINDS = frozenset({
    "escale", "approche", "zee-enter", "coast", "alert-on", "cyclone", "culture", "climo",
})
GENERIC_TITLES = frozenset({
    "station croisée", "station", "stations", "croisée", "croisee",
    "marina croisée", "marina", "marinas",
    "aire marine protégée", "amp", "mpa",
    "projet", "project", "projets",
    "formalités d'entrée", "ports d'entrée", "port d'entrée",
    "autour du bateau", "zee",
    "mouillage", "anchorage", "bouée", "buoy",
    "balise", "aton", "beacon", "câble", "cable",
    "profondeur", "depth", "piraterie", "piracy",
    "image satellite", "satellite image", "satellite",
})
NO_DATA_RE = re.compile(
    # Les deux apostrophes : droite « ' » et typographique « ’ » — le journal écrit « d’entrée », « n’est connu »
    # (27 sept. : avec la seule apostrophe droite, le filtre RE7 ne filtrait rien).
    r"aucun port d['’]entr[ée]e|no official port of entry|n['’]est connu",
    re.I,
)
DIST_IN_TEXT = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(?:nm|milles?\s+nautiques?)",
    re.I,
)
DIST_PAREN_RE = re.compile(
    r"\s*\(\s*\d+(?:[.,]\d+)?\s*(?:nm|milles?|km)[^)]*\)\s*",
    re.I,
)
LIST_PREFIX_RE = re.compile(
    r"^(?:ports? d['’]entr[ée]e|formalit[ée]s d['’]entr[ée]e|entr[ée]e dans)\s*:?\s*",
    re.I,
)
IUCN_RE = re.compile(r"\bIUCN\s+\S+", re.I)
TECH_PAREN_RE = re.compile(
    r"\s*\((?:unassigned|overlapping claim|wdpa:?\s*\d+|iucn[^)]*|cat(?:egory)?\s*[ivx0-9]+)\)\s*",
    re.I,
)
OVERLAP_RE = re.compile(r"overlapping claim", re.I)
LANE_LABELS = {
    "fr": {
        "dover strait": "détroit du Pas de Calais",
        "north sea": "mer du Nord",
        "bay of biscay": "golfe de Gascogne",
        "gibraltar": "détroit de Gibraltar",
        "strait of gibraltar": "détroit de Gibraltar",
        "western med": "Méditerranée occidentale",
        "red sea": "mer Rouge",
        "gulf of aden": "golfe d'Aden",
        "indian ocean w": "océan Indien ouest",
        "malacca": "détroit de Malacca",
        "south china sea": "mer de Chine méridionale",
        "cape approaches": "approches du Cap",
        "caribbean w": "Caraïbe ouest",
        "n atlantic main": "Atlantique nord",
        "coral sea lane": "mer de Corail",
        "torres commercial": "détroit de Torrès",
        "pacific": "Pacifique",
    },
    "en": {
        "gibraltar": "Strait of Gibraltar",
        "strait of gibraltar": "Strait of Gibraltar",
        "bay of biscay": "Bay of Biscay",
        "pacific": "Pacific",
    },
}
# Adjectifs / exonymes ZEE — table unique `toponyms` (JO / Marine Regions).

# Titres de source tels qu'ils apparaissent sur la route officielle (Marine Regions / stock).
# Un test échoue si l'un d'eux n'a pas de nom parlé.
OFFICIAL_ROUTE_ZEE_SOURCES = (
    "French Exclusive Economic Zone",
    "Spanish Exclusive Economic Zone",
    "Portuguese Exclusive Economic Zone",
    "Moroccan Exclusive Economic Zone",
    "Italian Exclusive Economic Zone",
    "Canary Islands Exclusive Economic Zone",
    "Madeira Exclusive Economic Zone",
    "Cape Verdean Exclusive Economic Zone",
    "Zone économique exclusive (Barbadian)",
    "Barbadian Exclusive Economic Zone",
    "Saint Vincentian Exclusive Economic Zone",
    "Saint Lucian Exclusive Economic Zone",
    "Dominican Exclusive Economic Zone",
    "Montserrat Exclusive Economic Zone",
    "Antiguan and Barbudan Exclusive Economic Zone",
    "Kittitian and Nevisian Exclusive Economic Zone",
    "Sint-Eustatius Exclusive Economic Zone",
    "Sint-Maarten Exclusive Economic Zone",
    "Saint-Martin Exclusive Economic Zone",
    "Surinamese Exclusive Economic Zone",
    "Guyanese Exclusive Economic Zone",
    "Venezuelan Exclusive Economic Zone",
    "Trinidadian and Tobagonian Exclusive Economic Zone",
    "Bonaire Exclusive Economic Zone",
    "Canadian Exclusive Economic Zone",
    "Cook Islands Exclusive Economic Zone",
    "American Samoa Exclusive Economic Zone",
    "Samoan Exclusive Economic Zone",
    "Tongan Exclusive Economic Zone",
    "Fijian Exclusive Economic Zone",
    "Wallis and Futuna Exclusive Economic Zone",
    "Matthew and Hunter Exclusive Economic Zone",
    "New Caledonia Exclusive Economic Zone",
    "Haute mer",
    "High Seas",
    "Overlapping claim Western Sahara: Western Sahara / Morocco",
    "Zone économique exclusive espagnole",
    "Zone économique exclusive portugaise",
    "Zone économique exclusive marocaine",
    "Zone économique exclusive italienne",
    "Zone économique exclusive française (France métropolitaine)",
    "Zone économique exclusive espagnole (Canary Islands)",
    "Zone économique exclusive portugaise (Madeira)",
    "Zone économique exclusive (Cape Verdean)",
    "Zone économique exclusive (Barbadian)",
    "Zone économique exclusive (Madagascan)",
)

# Dans la phrase de groupe, le site entre parenthèses gagne
# sur la nationalité — « britannique (Montserrat) » se dit « de Montserrat ».

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

# Ports du stock → géographie parlée (comme _ZEE_NATION : overlay, le nom du port vient du stock).
_COAST_GEO = (
    (re.compile(r"camari[nñ]as|mux[ií]a|finisterre|la coru[nñ]a|corme", re.I), ("la Galice", "Galicia", "coast")),
    (re.compile(r"cascais|lisboa|lisbon|peniche|sines", re.I), ("le Portugal", "Portugal", "coast")),
    (re.compile(r"tanger|tangier|algeciras|ceuta|europa point|^gibraltar$", re.I), ("le détroit de Gibraltar", "the Strait of Gibraltar", "strait")),
    (re.compile(r"porto torres|cagliari|olbia|alghero", re.I), ("la Sardaigne", "Sardinia", "island")),
    (re.compile(r"^calvi$|bastia|bonifacio|porto-vecchio|^l['’]?\s*[iî]le[- ]rousse$", re.I), ("la Corse", "Corsica", "island")),
    (re.compile(r"almer[ií]a|motril|m[aá]laga|cartagena", re.I), ("l'Andalousie", "Andalusia", "coast")),
    (re.compile(r"mah[oó]n|palma|ibiza|ciutadella", re.I), ("les Baléares", "the Balearic Islands", "island")),
)

# Forme parlée du port : le titre du stock doit matcher, on ne parle que ce qu'il contient.
_COAST_PORT_SHORT = (
    (re.compile(r"camari[nñ]as", re.I), "Camariñas"),
    (re.compile(r"mux[ií]a", re.I), "Muxía"),
    (re.compile(r"cascais", re.I), "Cascais"),
    (re.compile(r"tanger|tangier", re.I), "Tanger"),
    (re.compile(r"algeciras", re.I), "Algeciras"),
    (re.compile(r"\bceuta\b", re.I), "Ceuta"),
    (re.compile(r"europa point", re.I), "Europa Point"),
    (re.compile(r"almer[ií]a", re.I), "Almería"),
    (re.compile(r"mah[oó]n", re.I), "Mahón"),
    (re.compile(r"porto torres", re.I), "Porto Torres"),
    (re.compile(r"\bcalvi\b", re.I), "Calvi"),
    (re.compile(r"l['’]?\s*[iî]le[- ]rousse", re.I), "L'Île-Rousse"),
    (re.compile(r"bastia", re.I), "Bastia"),
    (re.compile(r"porto[- ]?vecchio", re.I), "Porto-Vecchio"),
    (re.compile(r"bonifacio", re.I), "Bonifacio"),
    (re.compile(r"finisterre", re.I), "Finisterre"),
    (re.compile(r"sines", re.I), "Sines"),
    (re.compile(r"peniche", re.I), "Peniche"),
)


def connector_at(i: int, lang: str = "fr") -> str:
    """Ancien index de rotation — RG6 ne l'emploie plus pour assembler un chapitre."""
    cons = CONNECTORS["en" if _en(lang) else "fr"]
    return cons[int(i) % len(cons)]


def looks_english_title(name: str) -> bool:
    """Titre anglais interdit à la voix (The Careenage, titres de projets EN)."""
    s = str(name or "").strip()
    if not s:
        return False
    if re.match(r"^The\s+[A-Z]", s):
        return True
    if _EN_TITLE_RE.search(s):
        return True
    if re.search(r"\b(marina|yacht club|harbour|harbor|intellireefs)\b", s, re.I) and not _FR_MARK_RE.search(s):
        return True
    hits = len(_EN_STOP_RE.findall(s))
    if hits >= 2 and not _FR_MARK_RE.search(s):
        return True
    if hits >= 4:
        return True
    return False


def film_has_forbidden(text: str) -> bool:
    return bool(FORBIDDEN_FILM_RE.search(text or ""))


def scrub_spoken(text: str) -> str:
    """Filet : « de de » impossible ; le reste des interdits ne se génère pas."""
    return re.sub(r"\bde de\b", "de", text or "", flags=re.I)


MONTHS = {
    "fr": ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"],
    "en": ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"],
}
EV_TAG = re.compile(r"\[\[ev:([^\]]+)\]\]")
TAG_STRIP = re.compile(r"\[\[(?:ev|ch):[^\]]+\]\]\s*")
WRITE_MAX_TOKENS = 1200
WRITTEN_SOURCE = "nemotron-super"
REVIEWED_BY_ULTRA = "nemotron-ultra"
# Ancien id encore reconnu à la lecture. La source servie reste nemotron-super.
REVIEWED_SOURCE = "nemotron-super-reviewed-ultra"
_SUPER_ORIGINS = frozenset({
    WRITTEN_SOURCE,
    "nemotron",
    "nemotron-super-token-factory",
    REVIEWED_SOURCE,
})


def _en(lang: str) -> bool:
    return str(lang or "").lower().startswith("en")


def _ms(iso: Any) -> Optional[int]:
    if isinstance(iso, (int, float)) and iso > 1e11:
        return int(iso)
    if not iso:
        return None
    try:
        t = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    return int(t.timestamp() * 1000)


def _iso(ms: Optional[int]) -> Optional[str]:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def rebase_iso(iso: Any, from_t0: str, to_t0: str) -> Any:
    """Décale une ISO de from_t0 vers to_t0 (mêmes durées, aucune date inventée)."""
    a, fr, to = _ms(iso), _ms(from_t0), _ms(to_t0)
    if a is None or fr is None or to is None or fr == to:
        return iso
    return _iso(a + (to - fr))


def resolve_film_t0(t0: str | None) -> str:
    if not t0 or _ms(t0) is None:
        return OFFICIAL_T0
    return t0


def day_month(iso: Any, lang: str = "fr", *, year: bool = False) -> str:
    t = _ms(iso)
    if t is None:
        return ""
    d = datetime.fromtimestamp(t / 1000.0, tz=timezone.utc)
    m = MONTHS["en" if _en(lang) else "fr"][d.month - 1]
    day = d.day
    y = f" {d.year}" if year else ""
    if _en(lang):
        return f"{day} {m}{y}"
    return f"{'1er' if day == 1 else day} {m}{y}"


def short_name(name: str) -> str:
    return re.sub(r"\s*\(Berry, Indre\)\s*", "", str(name or "")).strip()


def norm_stop(name: str) -> str:
    """« Ajaccio » ≡ « Ajaccio (Corse) ». Berry n'escale pas deux fois au même port."""
    s = re.sub(r"\s*\([^)]*\)\s*", " ", str(name or ""))
    return re.sub(r"\s+", " ", s).strip().casefold()


def same_stop(a: str, b: str) -> bool:
    na, nb = norm_stop(a), norm_stop(b)
    return bool(na) and na == nb


def _fold_stop(value: str) -> str:
    text = unicodedata.normalize("NFD", str(value or ""))
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.replace("œ", "oe").replace("Œ", "oe")
    return re.sub(r"\s+", " ", text).strip().casefold()


# Région officielle d'une escale : ne pas la recoller sur un autre lieu.
_REGION_OWNERS = (
    ("corse", "ajaccio"),
    ("corsica", "ajaccio"),
    ("martinique", "fort-de-france"),
    ("guadeloupe", "pointe-a-pitre"),
    ("saint-barthelemy", "gustavia"),
    ("saint-martin", "marigot"),
    ("saint-pierre-et-miquelon", "saint-pierre"),
    ("guyane", "cayenne"),
    ("polynesie francaise", "papeete"),
    ("wallis-et-futuna", "mata-utu"),
    ("nouvelle-caledonie", "noumea"),
    ("mayotte", "dzaoudzi"),
    ("taaf", "tromelin"),
    ("taaf", "europa"),
    ("la reunion", "saint-gilles"),
    ("reunion", "saint-gilles"),
    ("nouvelle-ecosse", "halifax"),
    ("nova scotia", "halifax"),
    ("berry", "saint-maur"),
    ("indre", "saint-maur"),
    ("berry, indre", "saint-maur"),
)


def _foreign_region(base: str, region: str) -> bool:
    folded_base = _fold_stop(base)
    folded_region = _fold_stop(region)
    owners = [owner for known, owner in _REGION_OWNERS if known == folded_region]
    if not owners:
        return False
    return not any(owner in folded_base for owner in owners)


def display_stop_name(name: str, lang: str = "fr") -> str:
    """Libellé d'escale. L'identité (`norm_stop`) ne change pas.

    Saint-Maur → « Saint-Maur (Indre) ».
    « Açores (Corse) » → « Açores » / « Azores (Portugal) ».
    « Ajaccio (Corse) » reste « Ajaccio (Corse) ».
    """
    raw = re.sub(r"\s+", " ", str(name or "")).strip()
    if not raw:
        return ""
    en = str(lang or "").lower().startswith("en")
    if _fold_stop(raw).replace("-", " ").startswith("saint maur"):
        return "Saint-Maur (Indre)"
    match = re.match(r"^(.*?)\s*\(([^)]+)\)\s*$", raw)
    base, region = raw, ""
    if match:
        base, region = match.group(1).strip(), match.group(2).strip()
        if _foreign_region(base, region):
            region = ""
    if _fold_stop(base).replace("-", " ").startswith("saint maur"):
        return "Saint-Maur (Indre)"
    folded = _fold_stop(base)
    if folded in {"acores", "azores", "the azores", "les acores"}:
        return "Azores (Portugal)" if en else "Açores"
    if not region:
        return base
    return f"{base} ({region})"


def _moment_near_named_place(change: dict, clock: dict | None, marks: list | None) -> bool:
    """Le bateau est au lieu nommé à l'instant du jalon."""
    kind = str(change.get("kind") or "")
    if kind not in {"stop", "escale", "approche", "coast", "port", "marina"}:
        return True
    named = change_place_name(change)
    coords = _named_place_coords(named, marks)
    if coords is None or not clock:
        return True
    t_ms = change.get("tMs")
    if t_ms is None:
        t_ms = _ms(change.get("t"))
    if t_ms is None:
        return True
    snapped = _clock_time_near_coords(clock, coords[0], coords[1], int(t_ms) - 21 * 86_400_000, int(t_ms) + 21 * 86_400_000)
    if snapped is not None:
        t_ms = snapped
    boat = _clock_latlon_at(clock, int(t_ms))
    if boat is None:
        return True
    d = _nm_between(coords[0], coords[1], boat[0], boat[1])
    return d is not None and d <= 30.0


def _coast_is_arrival(
    change: dict, dest_name: str, items: list | None, dest: dict | None, lang: str,
) -> bool:
    """Une côte « longée » qui est le port (ou la marina) d'arrivée de la jambe."""
    place = change_place_name(change) or short_name(change.get("title") or "")
    if not place:
        return False
    if dest_name and (same_stop(place, dest_name) or same_stop(place, short_name(dest_name))):
        return True
    harbor = _arrival_harbor(items, dest, lang) if dest else ""
    folded_place, folded_harbor = _fold_stop(place), _fold_stop(harbor)
    harbor_name = re.sub(r"^(?:(?:la|le|l')\s+)?(?:marina|port)\s+", "", folded_harbor)
    return bool(harbor_name) and folded_place == harbor_name


def _is_departure_port_echo(change: dict, from_name: str, dest_name: str) -> bool:
    """Perle « Escale » qui répète le port de départ alors que la jambe va ailleurs."""
    kind = str(change.get("kind") or "")
    if kind not in {"stop", "escale"}:
        return False
    title_cf = re.sub(r"\s+", " ", str(change.get("title") or "")).strip().casefold()
    if title_cf not in {"escale", "stopover"} and not _is_generic_title(
        str(change.get("title") or ""), kind,
    ):
        return False
    named = change_place_name(change)
    if not named or not from_name or not same_stop(named, from_name):
        return False
    if dest_name and same_stop(named, dest_name):
        return False
    return True


def _is_generic_title(title: str, kind: str = "") -> bool:
    t = re.sub(r"\s+", " ", str(title or "")).strip().casefold()
    if not t:
        return True
    if t in GENERIC_TITLES:
        return True
    k = str(kind or "").casefold()
    return bool(k) and (t == k or t == f"{k} croisée" or t == f"{k} croisee")


def extract_named(title: Any, fact: Any, kind: str = "") -> str:
    """Nom réel, ou vide. Titre égal au type → silence."""
    for raw in (title, fact):
        s = re.sub(r"\s+", " ", str(raw or "")).strip()
        if not s or NO_DATA_RE.search(s) or _is_generic_title(s, kind):
            continue
        s = LIST_PREFIX_RE.sub("", s).strip(" :")
        s = DIST_PAREN_RE.sub("", s).strip()
        s = re.sub(
            r"^(station|marina|aire marine protégée|amp)\s+",
            "",
            s,
            flags=re.I,
        ).strip()
        if s and not _is_generic_title(s, kind):
            return s
    return ""


def clean_spoken_label(raw: str, lang: str = "fr") -> str:
    """Libellé déclamable : IUCN, parenthèses techniques, anglais des couloirs."""
    s = short_name(raw or "")
    s = IUCN_RE.sub("", s)
    s = TECH_PAREN_RE.sub(" ", s)
    s = OVERLAP_RE.sub("", s)
    s = re.sub(r"\s*\(\s*\)\s*", " ", s)
    s = re.sub(r"\s+", " ", s).strip(" :-—,")
    table = LANE_LABELS["en" if _en(lang) else "fr"]
    return table.get(s.casefold(), s)


def zee_waters_label(name: str, lang: str = "fr") -> str:
    """Exonyme de la langue du récit — table `toponyms`, jamais une traduction."""
    raw_in = str(name or "")
    raw = clean_spoken_label(name, lang) or raw_in
    return toponyms.waters_label(raw_in, lang) or toponyms.waters_label(raw, lang)


def zee_group_waters(members: list, lang: str = "fr") -> str:
    """« les eaux françaises, puis celles de Montserrat » — Saint-Martin
    et Sint Maarten restent deux eaux distinctes."""
    return toponyms.group_waters(members, lang)


def _as_latlon(lat: Any, lon: Any) -> Optional[tuple[float, float]]:
    try:
        la, lo = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    if la != la or lo != lo:
        return None
    return la, lo


def _row_latlon(row: dict | None) -> Optional[tuple[float, float]]:
    """Position du moment (pos / here / at) — jamais une coordonnée inventée."""
    if not isinstance(row, dict):
        return None
    sources: list[dict] = [row]
    pos = row.get("pos") if isinstance(row.get("pos"), dict) else None
    if pos:
        sources.append(pos)
    moment = row.get("moment") if isinstance(row.get("moment"), dict) else None
    if moment:
        sources.append(moment)
        here = moment.get("here") if isinstance(moment.get("here"), dict) else None
        if here:
            sources.append(here)
            at = here.get("at") if isinstance(here.get("at"), dict) else None
            if at:
                sources.append(at)
        mom_pos = moment.get("pos") if isinstance(moment.get("pos"), dict) else None
        if mom_pos:
            sources.append(mom_pos)
    for src in sources:
        pair = _as_latlon(src.get("lat"), src.get("lon"))
        if pair:
            return pair
    return None


def _zee_basin_from_lonlat(lat: float, lon: float) -> str:
    """Bassin de la ZEE : Gascogne/Pertuis ≠ Corse/Sardaigne ≠ Pacifique."""
    if lon <= -80.0:
        return "pacific"
    if lon >= 5.0 and 36.0 <= lat <= 45.0:
        return "med"
    if lon < 1.0 and lat >= 43.0:
        return "biscay"
    if lon < -30.0:
        return "west_atlantic"
    return "east_atlantic"


def _zee_basin_from_change(change: dict | None) -> str:
    pair = _as_latlon((change or {}).get("lat"), (change or {}).get("lon"))
    if pair:
        return _zee_basin_from_lonlat(pair[0], pair[1])
    return ""


def _zee_same_basin(a: dict | None, b: dict | None) -> bool:
    ba, bb = _zee_basin_from_change(a), _zee_basin_from_change(b)
    if ba and bb:
        return ba == bb
    return True


_SPINE_WATERS_RE = re.compile(
    r"spanish|espagnol|portuguese|portugai|moroccan|marocain|"
    r"french|fran[cç]ais|gibraltar|gascogne|biscay",
    re.I,
)


def prefer_journal_moments(primary: list | None, stored: list | None) -> list[dict]:
    """Le journal avec zee-enter FR l'emporte sur une grille horloge."""
    a = [m for m in (primary or []) if isinstance(m, dict)]
    b = [m for m in (stored or []) if isinstance(m, dict)]

    def zee_n(rows: list[dict]) -> int:
        n = 0
        for row in rows:
            for change in row.get("changes") or []:
                if not isinstance(change, dict):
                    continue
                kind = str(change.get("kind") or "")
                title = str(change.get("title") or "")
                if kind == "zee-enter" or "économique exclusive" in title.lower():
                    n += 1
        return n

    if zee_n(b) > zee_n(a):
        return b
    return a or b


def _official_moments_for_film(voyage_id: str) -> list[dict]:
    moments: list[dict] = []
    try:
        from moment_journal import read_moments  # noqa: PLC0415
        moments = list(read_moments(voyage_id) or [])
    except Exception:
        moments = []
    stored: list[dict] = []
    try:
        from official_store import official_journal_moments  # noqa: PLC0415
        stored = list(official_journal_moments() or [])
    except Exception:
        stored = []
    return prefer_journal_moments(moments, stored)


def _is_spine_route_item(change: dict | None) -> bool:
    """Eaux de la route LR→Ajaccio : ne cèdent pas à un Argo ou une AMP de trop
. Titres FR du journal (« Zone économique exclusive espagnole »)
    comme titres EN."""
    if not isinstance(change, dict):
        return False
    kind = str(change.get("kind") or "")
    blob = " ".join(
        str(x) for x in (
            change.get("title"), change.get("fact"),
            *(change.get("members") or []),
        ) if x
    )
    if kind == "zee-enter" and _SPINE_WATERS_RE.search(blob):
        return True
    geo = change.get("geo") if isinstance(change.get("geo"), dict) else {}
    # Une île (la Sardaigne, les Baléares) est un jalon rare comme un détroit :
    # elle ne cède pas sa place aux eaux du jour (RG2, intégral).
    return kind == "coast" and geo.get("kind") in {"strait", "island"}


def _pacific_arrival_ms(
    clock: dict | None, t_a: Optional[int], t_b: Optional[int],
) -> Optional[int]:
    """Premier instant où la TRACE de mer est dans le Pacifique (lon ≤ −80) ;
    l'arrivée n'est dite que si le bateau y est encore (Papeete). Pas une boîte AIS."""
    if not isinstance(clock, dict):
        return None
    t0 = _ms(clock.get("t0"))
    first: Optional[int] = None
    last_lon: Optional[float] = None
    last_t: Optional[int] = None
    outside = False
    for v in clock.get("vertices") or []:
        if not isinstance(v, dict) or v.get("vehicle") in {"plane", "land"}:
            continue
        t = _ms(v.get("iso"))
        if t is None and t0 is not None and v.get("tHours") is not None:
            try:
                t = t0 + int(float(v["tHours"]) * 3_600_000)
            except (TypeError, ValueError):
                t = None
        if t is None:
            continue
        if t_a is not None and t < t_a:
            continue
        if t_b is not None and t > t_b:
            continue
        pair = _as_latlon(v.get("lat"), v.get("lon"))
        if pair is None:
            continue
        _lat, lon = pair
        last_lon, last_t = lon, t
        if lon > -80.0 and first is None:
            outside = True
        if lon <= -80.0 and first is None:
            first = t
    # Une jambe déjà toute dans le Pacifique (Papeete → Mata-Utu) n'y « arrive »
    # pas : sinon « Pacifique. » orphelin, redit et collé à l'arrivée.
    if first is None or last_lon is None or last_lon > -80.0 or not outside:
        return None
    if t_b is not None:
        return int(t_b)
    return int(last_t or first)


def _join_then(parts: list[str], lang: str) -> str:
    names = [p for p in parts if p]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    then = "then" if _en(lang) else "puis"
    if len(names) == 2:
        return f"{names[0]} {then} {names[1]}"
    return f"{', '.join(names[:-1])} {then} {names[-1]}"


def heading_phrase(deg: Any, lang: str = "fr") -> str:
    """Huit directions depuis headingDeg. 246° → « cap au sud-ouest »."""
    if not isinstance(deg, (int, float)) or isinstance(deg, bool):
        return ""
    try:
        d = float(deg)
    except (TypeError, ValueError):
        return ""
    if d != d:  # NaN
        return ""
    idx = int((d % 360.0) / 45.0 + 0.5) % 8
    fr, en = _HEADING_8[idx]
    if _en(lang):
        return f"heading {en}"
    if fr in {"est", "ouest"}:
        return f"cap à l'{fr}"
    return f"cap au {fr}"


def _utc_day(change: dict) -> str:
    t = change.get("tMs")
    if t is None:
        t = _ms(change.get("t"))
    if t is None:
        return ""
    return datetime.fromtimestamp(int(t) / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d")


def _coast_geo(name: str) -> Optional[tuple[str, str, str]]:
    for rx, triple in _COAST_GEO:
        if rx.search(str(name or "")):
            return triple
    return None


def _coast_port_short(name: str) -> str:
    raw = str(name or "").strip()
    if not raw:
        return ""
    for rx, spoken in _COAST_PORT_SHORT:
        if rx.search(raw):
            return spoken
    return short_name(raw)


_GALICE_PAIR_RE = re.compile(r"camari[nñ]as|mux[ií]a", re.I)


def _coast_port_is_listed(name: str) -> bool:
    raw = str(name or "").strip()
    if not raw:
        return False
    return any(rx.search(raw) for rx, _spoken in _COAST_PORT_SHORT)


def _prefer_coast_ports(ports: list[str], geo: dict | None) -> list[str]:
    """Au plus deux ports. Groupe Galice : Muxía et Camariñas tiennent ensemble."""
    seen: set[str] = set()
    uniq: list[str] = []
    for p in ports:
        label = str(p).strip()
        key = label.casefold()
        if not label or key in seen:
            continue
        seen.add(key)
        uniq.append(label)
    if len(uniq) <= 2:
        return uniq
    geo_fr = ((geo or {}).get("fr") or "").casefold()
    if "galice" in geo_fr:
        pair = [p for p in uniq if _GALICE_PAIR_RE.search(p)]
        if len(pair) >= 2:
            return pair[:2]
        rest = [p for p in uniq if p not in pair]
        return (pair + rest)[:2]
    listed = [p for p in uniq if _coast_port_is_listed(p)]
    other = [p for p in uniq if p not in listed]
    return (listed + other)[:2]


def _is_coast_source(change: dict) -> bool:
    """Jalon de côte : kind coast, port du stock, ou marina dont le titre porte un lieu connu."""
    kind = str(change.get("kind") or "")
    if kind not in {"coast", "port", "marina"}:
        return False
    name = change_place_name(change) or short_name(change.get("title") or "")
    if re.search(r"\b(oil|terminal|refinery|raffinerie)\b", name, re.I):
        return False
    if kind == "marina":
        return bool(_coast_geo(name))
    return True


def coast_sentence(change: dict, lang: str = "fr") -> str:
    """Jalon de côte : géographie connue + ports du stock, jamais un titre de source."""
    en = _en(lang)
    when = day_month(change.get("t"), lang)
    ports = [str(p).strip() for p in (change.get("ports") or []) if str(p).strip()]
    if not ports:
        one = change_place_name(change) or short_name(change.get("title") or "")
        if one:
            ports = [one]
    if not ports:
        return ""
    geo = change.get("geo") if isinstance(change.get("geo"), dict) else None
    if not geo:
        hit = _coast_geo(ports[0])
        if hit:
            geo = {"fr": hit[0], "en": hit[1], "kind": hit[2]}
    label = (geo.get("en") if en else geo.get("fr")) if geo else ""
    kind = (geo or {}).get("kind") or ""
    if kind == "strait" and label:
        a, b = ports[0], ports[1] if len(ports) > 1 else ""
        prefer = {p.casefold() for p in ports}
        if "tanger" in prefer or "tangier" in prefer:
            a = next((p for p in ports if re.search(r"tanger|tangier", p, re.I)), a)
        if "algeciras" in prefer:
            b = next((p for p in ports if re.search(r"algeciras", p, re.I)), b or a)
        if b and b.casefold() != a.casefold():
            body = f"{label} between {a} and {b}" if en else f"{label} entre {a} et {b}"
        else:
            body = f"{label} — {a}"
    elif label:
        listed = ", ".join(ports) if len(ports) <= 2 else f"{', '.join(ports[:-1])} {_join_then([ports[-1]], lang)}"
        if len(ports) == 1:
            listed = ports[0]
        elif len(ports) == 2:
            listed = f"{ports[0]}, {ports[1]}"
        else:
            listed = f"{', '.join(ports[:-1])} {'then' if en else 'puis'} {ports[-1]}"
        body = f"{label} — {listed}"
        if kind == "coast":
            body = (
                f"the boat skirts {body}"
                if en else
                f"le bateau longe {body}"
            )
        elif kind == "island" and en:
            body = f"{label} — {listed}"
        elif kind == "island":
            body = f"{label} — {listed}"
    else:
        listed = _join_then(ports, lang)
        body = f"the boat skirts {listed}" if en else f"le bateau longe {listed}"
    if when:
        return f"On {when}, {body}." if en else f"Le {when}, {body}."
    return f"{body[0].upper()}{body[1:]}." if body else ""


def _zee_cluster_change(cluster: list[dict]) -> dict:
    first = cluster[0]
    if len(cluster) == 1:
        return first
    names = [str(c.get("title") or c.get("fact") or "") for c in cluster]
    out = {
        "id": f"zee-cluster:{first.get('id')}",
        "kind": "zee-enter",
        "score": max(int(c.get("score") or 0) for c in cluster),
        "title": names[0],
        "fact": " · ".join(n for n in names if n),
        "members": names,
        "t": first.get("t"),
        "tMs": first.get("tMs"),
        "cluster": cluster,
    }
    if first.get("lat") is not None and first.get("lon") is not None:
        out["lat"] = first.get("lat")
        out["lon"] = first.get("lon")
    return out


def _is_zee_waters_change(change: dict) -> bool:
    """Vraie entrée d'eaux — pas un titre « Ports d'entrée / Formalités » collé sur kind zee-enter."""
    if str(change.get("kind") or "") != "zee-enter":
        return False
    blob = f"{change.get('title') or ''} {change.get('fact') or ''}"
    if re.search(r"ports? d['’]entr|formalit", blob, re.I):
        return False
    return True


def dose_zee_changes(changes: list[dict], span_ms: int) -> list[dict]:
    """Toutes les ZEE en traversée courte ; au plus une par jour en longue ; < 24 h → une phrase."""
    zee = [c for c in changes if _is_zee_waters_change(c)]
    zee.sort(key=lambda c: (c.get("tMs") or 0, str(c.get("id") or "")))
    clusters: list[list[dict]] = []
    def _zee_high_seas(change: dict) -> bool:
        return bool(re.search(
            r"haute mer|high seas",
            f"{change.get('title') or ''} {change.get('fact') or ''}",
            re.I,
        ))

    for c in zee:
        prev = clusters[-1][-1] if clusters else None
        dt = (c.get("tMs") or 0) - (prev.get("tMs") or 0) if prev else CLUSTER_MS
        # Gascogne/Pertuis FR ≠ Corse FR (bassins) ; ES/PT/MA restent
        # des phrases distinctes (Gascogne peut s'intercaler) — on ne colle
        # pas deux eaux de la route dans le même groupe.
        both_spine = bool(prev) and _is_spine_route_item(prev) and _is_spine_route_item(c)
        if (
            clusters and dt < CLUSTER_MS
            and not _zee_high_seas(c) and not _zee_high_seas(prev)
            and _zee_same_basin(c, prev)
            and not both_spine
        ):
            clusters[-1].append(c)
        else:
            clusters.append([c])
    grouped = [_zee_cluster_change(cl) for cl in clusters]
    if span_ms < SHORT_CROSSING_MS:
        return grouped
    kept: list[dict] = []
    days_used: set[str] = set()
    for c in grouped:
        if _is_spine_route_item(c):
            kept.append(c)
            continue
        day = _utc_day(c) or f"_{len(days_used)}"
        if day in days_used:
            continue
        days_used.add(day)
        kept.append(c)
    return kept


def dose_coast_changes(changes: list[dict], span_ms: int, lang: str = "fr") -> list[dict]:
    """Au plus un jalon de côte par jour de film ; même géographie le même jour → une phrase."""
    coasts = [c for c in changes if _is_coast_source(c)]
    coasts.sort(key=lambda c: (c.get("tMs") or 0, str(c.get("id") or "")))
    buckets: dict[str, list[dict]] = {}
    for c in coasts:
        raw = change_place_name(c) or short_name(c.get("title") or "")
        name = _coast_port_short(raw) or raw
        geo = _coast_geo(raw) or _coast_geo(name)
        source_geo = c.get("geo") if isinstance(c.get("geo"), dict) else None
        day = _utc_day(c)
        key = f"{day}:{(geo[0] if geo else name).casefold()}"
        buckets.setdefault(key, []).append({**c, "ports": [name] if name else [], "geo": (
            {"fr": geo[0], "en": geo[1], "kind": geo[2]} if geo else source_geo
        )})
    def geo_title(geo: dict | None) -> str:
        if not isinstance(geo, dict):
            return ""
        fr = str(geo.get("fr") or "")
        if not _en(lang):
            return fr
        en = str(geo.get("en") or "")
        if en:
            return en
        return {
            "limite du plateau continental": "continental shelf edge",
            "limite du continent": "continental edge",
        }.get(fr.casefold(), "")

    merged: list[dict] = []
    for group in buckets.values():
        first = group[0]
        ports: list[str] = []
        seen: set[str] = set()
        for g in group:
            for p in g.get("ports") or []:
                k = p.casefold()
                if k in seen:
                    continue
                seen.add(k)
                ports.append(p)
        geo = first.get("geo")
        ports = _prefer_coast_ports(ports, geo if isinstance(geo, dict) else None)
        merged.append({
            **first,
            "id": first.get("id") or f"coast:{ports[0] if ports else first.get('tMs')}",
            "kind": "coast",
            "title": " — ".join([geo_title(geo)] + ports).strip(" —") or (ports[0] if ports else first.get("title")),
            "ports": ports,
            "geo": geo,
        })
    by_day: dict[str, dict] = {}
    islands: list[dict] = []
    island_at: dict[str, int] = {}
    rank = {"strait": 3, "island": 2, "coast": 1}
    for c in merged:
        # Île (Sardaigne, Corse…) : un jalon par géographie, jamais écrasé
        # le même jour par un port d'eaux italiennes / françaises.
        # La même île sur deux jours ne se dit qu'une fois (ports réunis).
        if (c.get("geo") or {}).get("kind") == "island":
            geo_key = str((c.get("geo") or {}).get("fr") or "").casefold()
            if geo_key and geo_key in island_at:
                prev = islands[island_at[geo_key]]
                seen_ports = {p.casefold() for p in prev.get("ports") or []}
                extra = [p for p in c.get("ports") or [] if p.casefold() not in seen_ports]
                if extra:
                    ports = list(prev.get("ports") or []) + extra
                    islands[island_at[geo_key]] = {
                        **prev,
                        "ports": ports,
                        "title": " — ".join([geo_title(prev.get("geo"))] + ports).strip(" —"),
                    }
                continue
            if geo_key:
                island_at[geo_key] = len(islands)
            islands.append(c)
            continue
        day = _utc_day(c) or f"_{len(by_day)}"
        prev = by_day.get(day)
        if prev is None:
            by_day[day] = c
            continue
        cur_r = rank.get((c.get("geo") or {}).get("kind") or "", 0)
        prev_r = rank.get((prev.get("geo") or {}).get("kind") or "", 0)
        if cur_r > prev_r or (cur_r == prev_r and len(c.get("ports") or []) > len(prev.get("ports") or [])):
            by_day[day] = c
    out = list(islands)
    out.extend(by_day[k] for k in sorted(by_day))
    out.sort(key=lambda c: (c.get("tMs") or 0, str(c.get("id") or "")))
    return out


def _heading_deg_at(
    moments: list[dict] | None,
    depart_ms: Optional[int],
    clock: dict | None = None,
) -> Optional[float]:
    best: Optional[float] = None
    best_dt: Optional[int] = None
    t_ref = depart_ms or 0
    for row in moments or []:
        if not isinstance(row, dict):
            continue
        if _moment_is_air(row):
            continue  # Le cap d'une jambe de MER — jamais celui du vol (Cayenne → « cap au nord »)
        t = _ms(row.get("t"))
        if t is None:
            continue
        if depart_ms is not None and t < depart_ms - 3_600_000:
            continue
        mom = row.get("moment") if isinstance(row.get("moment"), dict) else {}
        leg = mom.get("leg") if isinstance(mom.get("leg"), dict) else {}
        deg = leg.get("headingDeg")
        if not isinstance(deg, (int, float)) or isinstance(deg, bool):
            continue
        dt = abs(int(t) - int(t_ref))
        if best_dt is None or dt < best_dt:
            best, best_dt = float(deg), dt
    if best is not None:
        return best
    for v in ((clock or {}).get("vertices") or []):
        if not isinstance(v, dict):
            continue
        if v.get("vehicle") in {"plane", "land"}:
            continue  # Un sommet d'avion (plein nord vers Halifax) n'est pas un cap de mer
        t = _ms(v.get("iso"))
        if t is None:
            continue
        deg = v.get("headingDeg") if v.get("headingDeg") is not None else v.get("bearing")
        if not isinstance(deg, (int, float)) or isinstance(deg, bool):
            continue
        dt = abs(int(t) - int(t_ref))
        if best_dt is None or dt < best_dt:
            best, best_dt = float(deg), dt
    return best


def _bearing_deg(lat1: Any, lon1: Any, lat2: Any, lon2: Any) -> Optional[float]:
    try:
        p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
        dl = math.radians(float(lon2) - float(lon1))
    except (TypeError, ValueError):
        return None
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def _initial_route_heading(
    clock: dict | None, depart_ms: Optional[int], nm: float = FILM_INITIAL_HEADING_NM,
) -> Optional[float]:
    """Le cap annoncé au départ d'une jambe est le relèvement des ~30
    premiers milles de la TRACE après l'appareillage — pas le bearing du premier
    segment (manœuvres de port), ni le relèvement global vers l'arrivée."""
    if depart_ms is None:
        return None
    t0 = _ms((clock or {}).get("t0"))
    verts: list[dict] = []
    for v in (clock or {}).get("vertices") or []:
        if not isinstance(v, dict) or v.get("lat") is None or v.get("lon") is None:
            continue
        if v.get("vehicle") in {"plane", "land"}:
            continue
        t = _ms(v.get("iso"))
        if t is None and v.get("tHours") is not None and t0 is not None:
            try:
                t = t0 + int(float(v["tHours"]) * 3_600_000)
            except (TypeError, ValueError):
                t = None
        if t is None:
            continue
        verts.append({**v, "_t": t})
    if len(verts) < 2:
        return None
    start = next(
        (i for i, v in enumerate(verts) if v["_t"] >= int(depart_ms) and v.get("vehicle") != "quay"),
        None,
    )
    if start is None or start + 1 >= len(verts):
        return None
    acc, j = 0.0, start
    while j + 1 < len(verts) and acc < nm:
        d = _nm_between(verts[j]["lat"], verts[j]["lon"], verts[j + 1]["lat"], verts[j + 1]["lon"])
        if d:
            acc += d
        j += 1
    if acc < nm * 0.5:
        return None
    return _bearing_deg(verts[start]["lat"], verts[start]["lon"], verts[j]["lat"], verts[j]["lon"])


FILM_HEADING_FAR_NM = 400.0
FILM_HEADING_AGREE_DEG = 45.0


def _angle_gap(a: float, b: float) -> float:
    d = abs((float(a) - float(b)) % 360.0)
    return min(d, 360.0 - d)


def _leg_heading_deg(
    moments: list[dict] | None,
    depart_ms: Optional[int],
    clock: dict | None = None,
    leg_nm: Any = None,
) -> Optional[float]:
    """Cap d'ouverture : la trace d'abord, sinon l'ancien plus-proche moment.

    Avec `leg_nm`, le cap dit est celui de la première moitié de la jambe
    (≤ 400 milles), et seulement s'il s'accorde (± 45°) avec les ~30 premiers
    milles : sinon la trace tourne (sortie de rade, contournement) et un seul
    cap serait faux — on n'en dit aucun (Fort-de-France → Pointe-à-Pitre « cap à
    l'ouest », Saint-Gilles → Europa « cap au nord »).
    """
    deg = _initial_route_heading(clock, depart_ms)
    if deg is not None:
        if isinstance(leg_nm, (int, float)) and not isinstance(leg_nm, bool) and leg_nm > 0:
            far_nm = max(float(FILM_INITIAL_HEADING_NM), min(float(leg_nm) / 2.0, FILM_HEADING_FAR_NM))
            far = _initial_route_heading(clock, depart_ms, nm=far_nm)
            if far is None:
                return deg
            if _angle_gap(deg, far) > FILM_HEADING_AGREE_DEG:
                return None
            return far
        return deg
    return _heading_deg_at(moments, depart_ms, clock=clock)


def change_place_name(change: dict) -> str:
    kind = str(change.get("kind") or "")
    title = str(change.get("title") or "")
    fact = str(change.get("fact") or "")
    if kind == "escale":
        title = title.replace("Arrivée à ", "").replace("Arrival at ", "").strip()
    if kind in {"stop", "escale"} and re.match(r"^escale$", title.strip(), re.I):
        port = clean_spoken_label(fact) or fact.strip()
        if port:
            return toponyms.origin_name(port)
    if kind == "zee-enter":
        title = LIST_PREFIX_RE.sub("", title).strip(" :")
    if kind == "coast":
        ports = [str(p).strip() for p in (change.get("ports") or []) if str(p).strip()]
        if ports:
            return toponyms.origin_name(ports[0])
        title = LIST_PREFIX_RE.sub("", title).strip(" :")
    if kind == "climo":
        return str(change.get("title") or change.get("regimeId") or "").strip()
    if kind == "cyclone":
        name, _year = cyclone_name_year(change)
        return name
    if kind == "alert-on" and alert_is_amp(change):
        return toponyms.origin_name(alert_amp_name(change))
    named = clean_spoken_label(extract_named(title, fact, kind))
    if kind == "zee-enter":
        return named
    return toponyms.origin_name(named)


def change_distance_nm(change: dict) -> Optional[float]:
    if isinstance(change.get("nm"), (int, float)):
        return float(change["nm"])
    blob = f"{change.get('fact') or ''} {change.get('title') or ''}"
    found = DIST_IN_TEXT.search(blob)
    if not found:
        return None
    try:
        return float(found.group(1).replace(",", "."))
    except ValueError:
        return None


def change_on_route(change: dict) -> bool:
    kind = str(change.get("kind") or "")
    if kind in ALWAYS_KINDS:
        return True
    nm = change_distance_nm(change)
    if kind == "project" or _is_amp_change(change):
        limit = PROJECT_NEAR_NM if kind == "project" else AMP_NEAR_NM
        return nm is None or nm <= limit
    if kind in {"station", "buoy", "poe", "anchorage"} | DC3_KINDS:
        return nm is None or nm <= STATION_NEAR_NM
    if nm is not None and nm > ROUTE_NEAR_NM:
        return False
    return True


def _station_item(change: dict) -> dict:
    """Métadonnées du sac (source / type / titre) pour qualifier une station."""
    if not isinstance(change, dict):
        return {}
    entity = change.get("entity") if isinstance(change.get("entity"), dict) else {}
    facts = change.get("facts") if isinstance(change.get("facts"), dict) else {}
    raw_kind = str(change.get("kind") or "")
    sci_kind = raw_kind if raw_kind not in {"station", "sci", "science", "nearby"} else ""
    for cand in (
        change.get("sciKind"), change.get("type"),
        entity.get("sciKind"), facts.get("kind"),
    ):
        s = str(cand or "")
        if s and s not in {"station", "sci", "science", "nearby"}:
            sci_kind = sci_kind or s
            break
    return {
        "name": change.get("name") or change.get("title") or entity.get("name") or facts.get("name") or "",
        "title": change.get("title") or "",
        "fact": change.get("fact") or "",
        "source": change.get("source") or entity.get("source") or facts.get("source") or "",
        "kind": sci_kind,
        "type": change.get("sciType") or facts.get("type") or entity.get("type") or "",
        "wmo": change.get("wmo") or entity.get("wmo") or facts.get("wmo") or "",
        "entity": entity,
        "facts": facts,
    }


def _argo_identifier(item: dict) -> str:
    """Identifiant WMO du flotteur (stock : wmo, nom « Argo 6904216 ») — vide sinon."""
    entity = item.get("entity") if isinstance(item.get("entity"), dict) else {}
    facts = item.get("facts") if isinstance(item.get("facts"), dict) else {}
    blob = " ".join(
        str(v) for v in (
            item.get("wmo"), entity.get("wmo"), facts.get("wmo"),
            item.get("name"), item.get("title"), item.get("fact"),
        ) if v
    )
    found = re.search(r"\b(\d{5,9})\b", blob)
    return found.group(1) if found else ""


def station_spoken_label(change: dict, lang: str = "fr") -> str:
    """Type parlé — jamais le titre de jeu de données. RC30 : un flotteur
    Argo se dit avec son identifiant (« le flotteur Argo 6904216 ») ; un
    flotteur anonyme ne se dit pas."""
    from ici_engine import science_type_key, spoken_science_type  # noqa: PLC0415
    item = _station_item(change)
    spoken = spoken_science_type(item, lang)
    if not spoken:
        return ""
    if science_type_key(item) == "argo":
        ident = _argo_identifier(item)
        if not ident:
            return ""
        return f"Argo float {ident}" if _en(lang) else f"le flotteur Argo {ident}"
    if science_type_key(item) == "campaign":
        # « Le lendemain, une campagne. » ne dit rien : la campagne se dit par
        # son nom (« campagne CALICO, 2013 », « research cruise LINKS »), sinon pas.
        code = _campaign_code(item)
        if not code:
            return ""
        return (f"the area of the {code} research cruise" if _en(lang)
                else f"la zone de la campagne océanographique {code}")
    return spoken


_CAMPAIGN_CODE_RE = re.compile(
    r"(?:\bcampagne|\bcruise|\bcampaign)\s+([A-Z][A-Z0-9-]{2,}[A-Z0-9])\b",
)


def _campaign_code(item: dict) -> str:
    """Code de campagne en capitales (CALICO, MAYOBS30, LINKS), lu dans le titre."""
    for key in ("title", "name", "fact"):
        found = _CAMPAIGN_CODE_RE.search(str(item.get(key) or ""))
        if found:
            return found.group(1)
    return ""


def station_name_speakable(name: str) -> bool:
    """Une station se dit seulement si un type est reconnu (Argo, PELGAS, bouée, CTD, observatoire)."""
    from ici_engine import science_type_key  # noqa: PLC0415
    n = (name or "").strip()
    if not n or _is_generic_title(n, "station"):
        return False
    return bool(science_type_key({"name": n, "title": n}))


def alert_is_amp(change: dict) -> bool:
    """AMP réelle seulement — IUCN / WDPA / parc ; jamais Chaluts / Pétoncles / deposit."""
    from ici_engine import is_protected_amp  # noqa: PLC0415
    return is_protected_amp({
        "name": change.get("title") or change.get("name"),
        "title": change.get("title"),
        "fact": change.get("fact"),
        "iucn_cat": change.get("iucn_cat") or change.get("iucn"),
        "designation": change.get("designation"),
        "site_id": change.get("site_id") or change.get("id"),
    })


def alert_amp_name(change: dict) -> str:
    """« Pertuis charentais - Rochebonne (12,2 nm): IUCN Unassigned; » → « Pertuis charentais - Rochebonne »."""
    from ici_engine import spoken_amp_name  # noqa: PLC0415
    fact = str(change.get("fact") or "")
    head = re.split(r"\s*\(\s*\d", fact, maxsplit=1)[0]
    head = re.split(r":\s*IUCN", head, maxsplit=1, flags=re.I)[0]
    raw = spoken_amp_name(head.strip(" ;:-")) or clean_spoken_label(head.strip(" ;:-"))
    return spoken_amp_name(raw) or raw


def _is_amp_change(change: dict) -> bool:
    kind = str(change.get("kind") or "")
    if kind == "amp":
        from ici_engine import is_fishing_amp  # noqa: PLC0415
        return not is_fishing_amp({
            "name": change.get("title") or change.get("name"),
            "title": change.get("title"),
            "fact": change.get("fact"),
        })
    if kind == "alert-on":
        return alert_is_amp(change)
    return False


def _amp_speak_event(change: dict) -> str:
    """enter | nearby | exit | '' — champ event, sinon inside / nm 0."""
    event = str(change.get("event") or "")
    if event in {"enter", "exit", "nearby"}:
        return event
    nested = change.get("entry") if isinstance(change.get("entry"), dict) else {}
    nested_ev = str(nested.get("event") or "")
    if nested_ev in {"enter", "exit", "nearby"}:
        return nested_ev
    if change.get("inside") is True or nested.get("inside") is True:
        return "enter"
    nm = change_distance_nm(change)
    if nm is not None and nm <= 0:
        return "enter"
    if nm is not None and nm > 0:
        return "nearby"
    return ""


def _amp_activity_codes(item: dict) -> tuple[Any, Any]:
    """Codes ProtectedSeas (0–3). Jamais le dict d'événement imbriqué `entry`."""
    from amp_traffic import as_activity  # noqa: PLC0415
    raw_entry = item.get("entry")
    speed = as_activity(item.get("speed"))
    if isinstance(raw_entry, dict):
        nested_e = as_activity(raw_entry.get("entry"))
        nested_s = as_activity(raw_entry.get("speed"))
        if nested_s is not None:
            speed = nested_s
        return nested_e, speed
    return as_activity(raw_entry), speed


def _amp_stock_traffic(item: dict | None) -> str:
    """interdit / régulé seulement si le stock le porte. Pas inventé."""
    if not isinstance(item, dict):
        return ""
    stored = item.get("traffic")
    if stored in {"forbidden", "regulated"}:
        return stored
    nested = item.get("entry") if isinstance(item.get("entry"), dict) else None
    if isinstance(nested, dict) and nested.get("traffic") in {"forbidden", "regulated"}:
        return nested["traffic"]
    from amp_traffic import traffic_kind  # noqa: PLC0415
    entry, speed = _amp_activity_codes(item)
    if entry is None and speed is None:
        return ""
    kind = traffic_kind(entry, speed)
    return kind if kind in {"forbidden", "regulated"} else ""


def _amp_traffic_paren(item: dict | None, lang: str) -> str:
    kind = _amp_stock_traffic(item)
    if kind == "forbidden":
        return " (no transit)" if _en(lang) else " (circulation interdite)"
    if kind == "regulated":
        return " (regulated transit)" if _en(lang) else " (circulation régulée)"
    return ""


def _amp_relation(change: dict) -> str:
    """crossing | near | '' — champ event / inside / nm du stock."""
    ev = _amp_speak_event(change)
    if ev == "enter":
        return "crossing"
    if ev == "nearby":
        return "near"
    return ""


def _amp_distance_nm(change: dict) -> Optional[float]:
    nm = change_distance_nm(change)
    if nm is not None:
        return nm
    nested = change.get("entry") if isinstance(change.get("entry"), dict) else {}
    return _fact_num(change, "nm") or (_fact_num(nested, "nm") if nested else None)


def _amp_film_sentence(name: str, change: dict, lang: str, when: str) -> str:
    """Phrase d'aire déjà retenue : près ou traversée ; circulation si le stock l'a."""
    en = _en(lang)
    if not name:
        return ""
    if _amp_speak_event(change) == "exit":
        return ""
    tag = _amp_traffic_paren(change, lang)
    rel = _amp_relation(change)
    nm = _amp_distance_nm(change)
    dist = spoken_distance(nm, lang) if nm is not None and nm > 0 else ""
    if rel == "crossing":
        text = (
            f"On {when}, the boat crosses the marine protected area {name}{tag}."
            if en else
            f"Le {when}, le bateau traverse l'aire marine protégée {name}{tag}."
        )
    elif rel == "near" and dist:
        text = (
            f"On {when}, the boat passes near the marine protected area {name}, at {dist}{tag}."
            if en else
            f"Le {when}, le bateau passe près de l'aire marine protégée {name}, à {dist}{tag}."
        )
    elif rel == "near":
        text = (
            f"On {when}, the boat passes near the marine protected area {name}{tag}."
            if en else
            f"Le {when}, le bateau passe près de l'aire marine protégée {name}{tag}."
        )
    elif dist:
        text = (
            f"On {when}, {dist} away, the marine protected area {name}{tag}."
            if en else
            f"Le {when}, à {dist}, l'aire marine protégée {name}{tag}."
        )
    else:
        text = (
            f"On {when}, marine protected area: {name}{tag}."
            if en else
            f"Le {when}, aire marine protégée : {name}{tag}."
        )
    return _tidy_empty_when(text) if not when else text


def _is_buoy_change(change: dict) -> bool:
    """Station dont le type du stock est une bouée — pas un titre de jeu."""
    if not isinstance(change, dict):
        return False
    kind = str(change.get("kind") or "")
    if kind == "buoy":
        return True
    if kind not in {"station", "sci", "science"}:
        return False
    from ici_engine import science_type_key  # noqa: PLC0415
    return science_type_key(_station_item(change)) == "buoy"


def _poe_place_name(change: dict) -> str:
    """Nom d'un port d'entrée officiel du stock. Vide = pas de formalité."""
    if not isinstance(change, dict):
        return ""
    kind = str(change.get("kind") or "")
    title = str(change.get("title") or "")
    fact = str(change.get("fact") or "")
    blob = f"{title} {fact}"
    if NO_DATA_RE.search(blob):
        return ""
    if kind != "poe":
        return ""
    return change_place_name(change) or extract_named(title, fact, "port")


def _is_poe_formality_change(change: dict) -> bool:
    return bool(_poe_place_name(change))


def _anchorage_name(change: dict) -> str:
    """Nom de mouillage du stock. Un type OSM anonyme n'est pas un fait."""
    if not isinstance(change, dict):
        return ""
    raw = (
        change_place_name(change)
        or extract_named(change.get("title"), change.get("fact"), "anchorage")
        or short_name(str(change.get("title") or change.get("name") or ""))
    )
    s = str(raw or "").strip()
    if not s or s.casefold() in GENERIC_ANCHORAGE_NAMES or _is_generic_title(s, "anchorage"):
        return ""
    return s


def _is_anchorage_change(change: dict) -> bool:
    if not isinstance(change, dict):
        return False
    if str(change.get("kind") or "") not in {"anchorage", "mouillage"}:
        return False
    return bool(_anchorage_name(change))


def _as_dc2_change(change: dict) -> Optional[dict]:
    """Copie parlable : kind amp | buoy | poe | anchorage. None si pas de fait."""
    if not isinstance(change, dict):
        return None
    if _is_amp_change(change):
        packed = dict(change)
        packed["kind"] = "amp"
        return packed
    if _is_buoy_change(change):
        packed = dict(change)
        packed["kind"] = "buoy"
        packed["id"] = f"dc2:buoy:{change.get('id') or change.get('tMs') or packed.get('title')}"
        return packed
    if _is_poe_formality_change(change):
        name = _poe_place_name(change)
        packed = dict(change)
        packed["kind"] = "poe"
        packed["title"] = name or packed.get("title")
        packed["fact"] = name or packed.get("fact")
        packed["id"] = f"dc2:poe:{change.get('id') or name}"
        return packed
    if _is_anchorage_change(change):
        name = _anchorage_name(change)
        packed = dict(change)
        packed["kind"] = "anchorage"
        packed["title"] = name
        packed["fact"] = packed.get("fact") or name
        packed["id"] = f"dc2:anchorage:{change.get('id') or name}"
        return packed
    return None


def dc_subject_record(change: dict, lang: str = "fr") -> Optional[dict]:
    """Candidat DC : kind, phrase possible, une fois par famille sur une longue jambe."""
    packed = _as_dc_change(change)
    if not packed:
        return None
    phrase = change_sentence(packed, lang).strip()
    if not phrase:
        return None
    kind = str(packed.get("kind") or "")
    name = (
        change_place_name(packed)
        or short_name(packed.get("title") or packed.get("name") or "")
    )
    rec = {
        "id": f"dc:{kind}",
        "kind": kind,
        "phrase": phrase,
        "oncePerFamilyOnLongLeg": True,
        "name": name,
    }
    if packed.get("t"):
        rec["t"] = packed.get("t")
    if kind == "amp":
        rec["relation"] = _amp_relation(change)
    return rec


def dc_subject_candidates(changes: list[dict] | None, lang: str = "fr") -> list[dict]:
    """Sac DC1–DC3 (amp, buoy, poe, anchorage, aton, cable, depth, piracy, satellite).

    Une entrée par famille. VS1 lira cette liste ; le palier 2:30 n'empile pas ces kinds.
    """
    recs: list[dict] = []
    for change in changes or []:
        rec = dc_subject_record(change, lang)
        if rec:
            recs.append(rec)
    rank = {"crossing": 0, "near": 1, "": 2}
    kind_order = {
        "amp": 0, "buoy": 1, "poe": 2, "anchorage": 3,
        "aton": 4, "cable": 5, "depth": 6, "piracy": 7, "satellite": 8,
    }
    recs.sort(key=lambda r: (
        kind_order.get(str(r.get("kind") or ""), 9),
        rank.get(str(r.get("relation") or ""), 9),
    ))
    out: list[dict] = []
    seen: set[str] = set()
    for rec in recs:
        kind = str(rec.get("kind") or "")
        if not kind or kind in seen:
            continue
        seen.add(kind)
        out.append(rec)
    return out


def reserved_watch_candidate() -> dict:
    """Trou TV1 : id d'avis. Phrase lue du cache ; vide si la veille n'a rien."""
    phrase = ""
    url = None
    try:
        import escale_watch  # noqa: PLC0415

        hit = escale_watch.latest_watch_entry()
        if isinstance(hit, dict):
            phrase = str(hit.get("text") or "").strip()
            url = hit.get("url")
    except Exception:
        phrase = ""
        url = None
    rec = {
        "id": TV1_WATCH_ID,
        "kind": TV1_WATCH_KIND,
        "phrase": phrase,
        "oncePerFamilyOnLongLeg": True,
        "reserved": True,
    }
    if url:
        rec["url"] = url
    return rec


def film_choice_bag(subjects: list[dict] | None) -> list[dict]:
    """Sac VS1 : candidats DC (ids stables) + id d'avis réservé."""
    out: list[dict] = []
    seen: set[str] = set()
    for rec in subjects or []:
        if not isinstance(rec, dict):
            continue
        kind = str(rec.get("kind") or "")
        rid = str(rec.get("id") or (f"dc:{kind}" if kind else ""))
        if not rid or rid in seen:
            continue
        seen.add(rid)
        row = dict(rec)
        row["id"] = rid
        out.append(row)
    if TV1_WATCH_ID not in seen:
        out.append(reserved_watch_candidate())
    return out


def tour_snapshot(packed: dict | None) -> dict[str, Any]:
    """Schéma du tour entier — pas une capture carte. VL y lit les lieux."""
    stops: list[dict] = []
    for s in (packed or {}).get("stops") or []:
        if not isinstance(s, dict):
            continue
        stops.append({
            "name": short_name(s.get("name") or ""),
            "lat": s.get("lat"),
            "lon": s.get("lon"),
            "iso": s.get("iso"),
        })
    pts: list[str] = []
    for s in stops:
        if s.get("lat") is None or s.get("lon") is None:
            continue
        try:
            pts.append(f"{float(s['lon']):.2f},{-float(s['lat']):.2f}")
        except (TypeError, ValueError):
            continue
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="-180 -90 360 180">'
        f'<polyline fill="none" stroke="#0a0" points="{" ".join(pts)}"/>'
        "</svg>"
    )
    return {"legs": stops, "image": svg}


def film_choice_fingerprint(bag: list[dict] | None, tour: dict | None = None) -> str:
    """Empreinte du stock : ids du sac + jambes. Un choix par film, pas par visite."""
    bits = [f"{c.get('id')}|{c.get('kind')}" for c in bag or [] if isinstance(c, dict)]
    for leg in (tour or {}).get("legs") or []:
        if isinstance(leg, dict):
            bits.append(f"{leg.get('name')}|{leg.get('iso')}")
    bits.append("vs1")
    return hashlib.sha256("\n".join(bits).encode("utf-8")).hexdigest()


def parse_choice_ids(text: str, allowed: set[str]) -> Optional[list[str]]:
    """JSON d'ids seulement. Ids hors sac ignorés. Aucun texte libre gardé."""
    raw = (text or "").strip()
    data: Any = None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict):
        return None
    ids = data.get("ids")
    if not isinstance(ids, list):
        return None
    kept: list[str] = []
    seen: set[str] = set()
    allow = {str(a) for a in allowed}
    for item in ids:
        sid = str(item)
        if sid in allow and sid not in seen:
            seen.add(sid)
            kept.append(sid)
    return kept


def _fallback_dc_cap(seconds: Any) -> Optional[int]:
    if film_char_budget(seconds) <= 0:
        return None
    if film_priority_tier(seconds) <= FILM_TIER_SHORT:
        return FALLBACK_DC_CAP_SHORT
    return FALLBACK_DC_CAP_MEDIUM


def _trim_ids_to_budget(ids: list[str], bag: list[dict], seconds: Any) -> list[str]:
    """Frein : s'arrête à film_char_budget. N'ajoute rien."""
    by_id = {str(c.get("id")): c for c in bag or [] if isinstance(c, dict) and c.get("id")}
    budget = film_char_budget(seconds)
    chosen: list[str] = []
    chars = 0
    for raw in ids:
        sid = str(raw)
        rec = by_id.get(sid)
        if not rec:
            continue
        n = len(str(rec.get("phrase") or ""))
        if budget and chars + n > budget:
            break
        chosen.append(sid)
        chars += n
    return chosen


def fallback_choose_ids(bag: list[dict] | None, seconds: Any) -> list[str]:
    """Repli : priorité fixe, une fois par famille, pas l'avis TV1, arrêt au budget."""
    rank = {k: i for i, k in enumerate(FALLBACK_KIND_ORDER)}
    recs: list[dict] = []
    for rec in bag or []:
        if not isinstance(rec, dict):
            continue
        if str(rec.get("kind") or "") == TV1_WATCH_KIND:
            continue
        recs.append(rec)
    recs.sort(key=lambda r: (rank.get(str(r.get("kind") or ""), 99), str(r.get("id") or "")))
    unique: list[dict] = []
    seen: set[str] = set()
    for rec in recs:
        kind = str(rec.get("kind") or "")
        if not kind or kind in seen:
            continue
        seen.add(kind)
        unique.append(rec)
    cap = _fallback_dc_cap(seconds)
    picked = unique if cap is None else unique[:cap]
    ids = [str(r.get("id")) for r in picked if r.get("id")]
    return _trim_ids_to_budget(ids, bag or [], seconds)


_DC_FAMILY_SENT = {
    "amp": re.compile(r"aire marine|marine protected area", re.I),
    "buoy": re.compile(r"une bouée|a buoy", re.I),
    "poe": re.compile(r"formalit[ée]s d['’]entr[ée]e|entry formalities", re.I),
    "anchorage": re.compile(r"\bmouillage\b|\banchorage\b", re.I),
    "aton": re.compile(r"\bbalise\b|\bbeacon\b", re.I),
    "cable": re.compile(r"\bcâble\b|\bcable\b", re.I),
    "depth": re.compile(r"profondeur\s*:|depth\s*:", re.I),
    "piracy": re.compile(r"Piraterie —|Piracy —"),
}


def _subject_already_spoken(rec: dict, blob: str) -> bool:
    phrase = str(rec.get("phrase") or "").strip()
    if phrase and phrase in (blob or ""):
        return True
    rx = _DC_FAMILY_SENT.get(str(rec.get("kind") or ""))
    return bool(rx and rx.search(blob or ""))


def _repeat_slots(chapters: list[dict]) -> list[tuple[dict, int]]:
    """Phrases remplaçables : P3/P4 d'abord, puis une eau en trop. Pas l'ouverture."""
    slots: list[tuple[dict, int]] = []
    waters = 0
    for ch in chapters:
        sents = _sentences(ch.get("text") or "")
        for i, sent in enumerate(sents):
            rank = _trim_sentence_rank(sent)
            if rank >= 2:
                slots.append((ch, i))
            elif rank == 1:
                waters += 1
                if waters > 1:
                    slots.append((ch, i))
    return slots


def _chapter_for_subject(chapters: list[dict], rec: dict) -> Optional[dict]:
    t = _ms(rec.get("t")) if rec.get("t") else None
    if t is not None:
        for ch in chapters:
            a, b = _ms(ch.get("tA")), _ms(ch.get("tB"))
            if a is not None and b is not None and a <= t <= b:
                return ch
    return chapters[-1] if chapters else None


def apply_chosen_subjects(
    plan: dict,
    ids: list[str] | None,
    bag: list[dict] | None,
    seconds: Any,
    lang: str = "fr",
) -> dict:
    """Remplace des redites par les ids choisis. N'empile pas. Puis film_char_budget."""
    chapters = [{**c, "text": c.get("text") or ""} for c in (plan.get("chapters") or [])]
    by_id = {str(c.get("id")): c for c in bag or [] if isinstance(c, dict) and c.get("id")}
    blob = " ".join(ch.get("text") or "" for ch in chapters)
    remaining: list[dict] = []
    seen_kind: set[str] = set()
    for raw in ids or []:
        rec = by_id.get(str(raw))
        if not rec:
            continue
        kind = str(rec.get("kind") or "")
        phrase = str(rec.get("phrase") or "").strip()
        if not phrase:
            continue
        if kind == TV1_WATCH_KIND:
            remaining.append(rec)
            continue
        if kind not in DC_FAMILY_KINDS:
            continue
        if kind in seen_kind:
            continue
        if _subject_already_spoken(rec, blob):
            seen_kind.add(kind)
            continue
        seen_kind.add(kind)
        remaining.append(rec)
    slots = _repeat_slots(chapters)
    taken: set[int] = set()
    spoken: list[dict] = []
    # Liste explicite des sujets non placés : depuis la règle de date, un sujet
    # daté sans emplacement dans sa jambe est sauté, donc les placés ne forment
    # plus un préfixe de ``remaining`` (``remaining[used:]`` redisait un sujet
    # placé et en perdait un autre en intégral).
    unplaced: list[dict] = []
    for rec in remaining:
        # Un sujet daté se dit dans le chapitre qui contient sa date, jamais
        # dans une autre jambe (« Le 21 mai, une bouée » au chapitre d'août).
        home = _chapter_for_subject(chapters, rec) if rec.get("t") else None
        if home is not None:
            a, b, t = _ms(home.get("tA")), _ms(home.get("tB")), _ms(rec.get("t"))
            if a is None or b is None or t is None or not (a <= t <= b):
                home = None
        if (
            str(rec.get("kind") or "") == "buoy"
            and home is not None
            and _STATION_SPOKEN_RE.search(home.get("text") or "")
        ):
            # RG5 : au plus une station par chapitre — la bouée en est une.
            continue
        pick = None
        for k, (ch, idx) in enumerate(slots):
            if k in taken:
                continue
            if rec.get("t") and ch is not home:
                continue
            pick = k
            break
        if pick is None:
            unplaced.append(rec)
            continue
        taken.add(pick)
        ch, idx = slots[pick]
        sents = _sentences(ch.get("text") or "")
        if idx < 0 or idx >= len(sents):
            unplaced.append(rec)
            continue
        sents[idx] = rec["phrase"]
        ch["text"] = " ".join(sents).strip()
        spoken.append(rec)
    budget = film_char_budget(seconds)
    if budget <= 0:
        for rec in unplaced:
            ch = _chapter_for_subject(chapters, rec)
            if ch is None:
                continue
            text = (ch.get("text") or "").strip()
            phrase = rec["phrase"]
            if str(rec.get("kind") or "") == "buoy" and _STATION_SPOKEN_RE.search(text):
                continue
            if phrase and phrase not in text:
                ch["text"] = f"{text} {phrase}".strip() if text else phrase
                spoken.append(rec)
    if budget > 0:
        _film_apply_char_budget(chapters, seconds)
    for ch in chapters:
        _reanchor_edited_chapter(ch, lang)
    blob_after = " ".join(ch.get("text") or "" for ch in chapters)
    watch_spoken = any(
        str(r.get("kind") or "") == TV1_WATCH_KIND
        and str(r.get("phrase") or "") in blob_after
        for r in spoken
    )
    try:
        import escale_watch  # noqa: PLC0415

        escale_watch.set_watch_in_film(watch_spoken)
    except Exception:
        pass
    chars = script_chars(chapters)
    return {
        **plan,
        "chapters": chapters,
        "chars": chars,
        "estimatedSeconds": film_estimated_seconds(chars),
        "filmChoice": list(ids or []),
    }


# Stations qualifiées dites à la voix (RG5 : au plus une par chapitre).
_STATION_SPOKEN_RE = re.compile(
    r"flotteur Argo|campagne PELGAS|une bouée|station côtière|un observatoire|une campagne"
    r"|Argo float|PELGAS campaign|a buoy|coastal station|an observatory|a research cruise",
    re.I,
)


def dose_dc2_leg_changes(changes: list[dict], span_ms: int = 0) -> list[dict]:
    """Intégral, jambe longue : au plus une bouée, une formalité, un mouillage."""
    if span_ms < SHORT_CROSSING_MS:
        return []
    by_kind: dict[str, list[dict]] = {"buoy": [], "poe": [], "anchorage": []}
    for change in changes or []:
        packed = _as_dc2_change(change)
        if not packed:
            continue
        kind = str(packed.get("kind") or "")
        if kind not in by_kind:
            continue
        if not _would_speak(packed):
            continue
        by_kind[kind].append(packed)
    out: list[dict] = []
    for kind in ("buoy", "poe", "anchorage"):
        rows = by_kind[kind]
        if not rows:
            continue
        rows.sort(key=lambda c: (
            change_distance_nm(c) if change_distance_nm(c) is not None else 999.0,
            c.get("tMs") or 0,
        ))
        out.append(rows[0])
    return out


def _dc3_kind(change: dict) -> str:
    raw = str((change or {}).get("kind") or "").strip().casefold()
    return DC3_KIND_ALIASES.get(raw, raw)


def _aton_name(change: dict) -> str:
    """Nom de balise du stock. Un type OSM (buoy_lateral) n'est pas un fait."""
    if not isinstance(change, dict):
        return ""
    raw = (
        change.get("name")
        or change_place_name(change)
        or extract_named(change.get("title"), change.get("fact"), "aton")
        or short_name(str(change.get("title") or ""))
    )
    s = str(raw or "").strip()
    if not s:
        return ""
    key = s.casefold()
    if key in GENERIC_ATON_NAMES or _is_generic_title(s, "aton"):
        return ""
    if ATON_TYPE_KEY_RE.match(key):
        return ""
    return s


def _is_aton_change(change: dict) -> bool:
    if not isinstance(change, dict):
        return False
    if _dc3_kind(change) != "aton":
        return False
    return bool(_aton_name(change))


def _cable_name(change: dict) -> str:
    """Nom de câble du stock. nearby=true sans nom → silence."""
    if not isinstance(change, dict):
        return ""
    raw = (
        change.get("name")
        or extract_named(change.get("title"), change.get("fact"), "cable")
        or short_name(str(change.get("title") or ""))
    )
    s = str(raw or "").strip()
    if not s or s.casefold() in GENERIC_CABLE_NAMES or _is_generic_title(s, "cable"):
        return ""
    if len(s) < 3 or re.fullmatch(r"\d+", s) or GENERIC_CABLE_LABEL_RE.search(s):
        return ""
    return s


def _is_cable_change(change: dict) -> bool:
    if not isinstance(change, dict):
        return False
    if _dc3_kind(change) != "cable":
        return False
    return bool(_cable_name(change))


def _as_depth_m(raw: Any) -> Optional[float]:
    if not isinstance(raw, (int, float)):
        return None
    value = abs(float(raw))
    if value != value or value < 1.0:
        return None
    return value


def _depth_m(change: dict) -> Optional[float]:
    """Sonde du stock (emodnet.depth_m ou gebco depthOffshore). Jamais inventée."""
    if not isinstance(change, dict):
        return None
    facts = change.get("facts") if isinstance(change.get("facts"), dict) else {}
    for raw in (
        change.get("depth_m"), change.get("depthM"), change.get("depthOffshore"),
        facts.get("depth_m"), facts.get("depthM"), facts.get("depthOffshore"),
    ):
        hit = _as_depth_m(raw)
        if hit is not None:
            return hit
    return None


def _is_depth_change(change: dict) -> bool:
    if not isinstance(change, dict):
        return False
    if _dc3_kind(change) != "depth":
        return False
    return _depth_m(change) is not None


def _piracy_name(change: dict) -> str:
    if not isinstance(change, dict):
        return ""
    raw = str(change.get("name") or change.get("title") or "").strip()
    if not raw or raw.casefold() in {"piracy", "piraterie", "piraterie —", "piracy —"}:
        return ""
    if _is_generic_title(raw, "piracy"):
        return ""
    return raw


def _piracy_level(change: dict) -> str:
    if not isinstance(change, dict):
        return ""
    token = str(change.get("level") or "").strip().upper()
    if token in {"CRITICAL", "CRIT"}:
        return "HIGH"
    if token in {"MODERATE", "MED"}:
        return "MEDIUM"
    if token in {"HIGH", "MEDIUM", "LOW"}:
        return token
    return token


def _is_piracy_change(change: dict) -> bool:
    if not isinstance(change, dict):
        return False
    if _dc3_kind(change) != "piracy":
        return False
    return bool(_piracy_name(change))


def _satellite_field_playable(raw: Any) -> str:
    """Légende déjà écrite. Produit STAC / « Image satellite » → vide."""
    s = str(raw or "").strip()
    if not s or len(s) < 8:
        return ""
    key = s.casefold()
    if key in GENERIC_SATELLITE_TITLES or _is_generic_title(s, "satellite"):
        return ""
    if SATELLITE_PRODUCT_RE.search(s):
        return ""
    if re.fullmatch(r"[A-Za-z0-9._:-]+", s) and ("sentinel" in key or "l2a" in key or "l1c" in key):
        return ""
    return s


def _satellite_caption(change: dict) -> str:
    """Phrase satellite déjà dans le stock. Image seule → silence."""
    if not isinstance(change, dict):
        return ""
    scene = change.get("scene") if isinstance(change.get("scene"), dict) else {}
    sat = change.get("satellites") if isinstance(change.get("satellites"), dict) else {}
    sat_scene = sat.get("scene") if isinstance(sat.get("scene"), dict) else {}
    derived = (
        sat.get("derived") if isinstance(sat.get("derived"), dict)
        else change.get("derived") if isinstance(change.get("derived"), dict)
        else {}
    )
    for raw in (
        change.get("caption"), change.get("description"), change.get("legend"),
        scene.get("caption"), scene.get("description"), scene.get("legend"),
        sat.get("caption"), sat.get("description"), sat.get("legend"),
        sat_scene.get("caption"), sat_scene.get("description"), sat_scene.get("legend"),
        change.get("title"), scene.get("title"), sat_scene.get("title"),
    ):
        hit = _satellite_field_playable(raw)
        if hit:
            return hit
    for key in ("sdb", "coastline", "intertidal"):
        block = derived.get(key) if isinstance(derived.get(key), dict) else {}
        value = block.get("value") if isinstance(block.get("value"), dict) else {}
        hit = _satellite_field_playable(value.get("name"))
        if hit:
            return hit
    return ""


def _is_satellite_change(change: dict) -> bool:
    if not isinstance(change, dict):
        return False
    if _dc3_kind(change) != "satellite":
        return False
    return bool(_satellite_caption(change))


def _as_dc3_change(change: dict) -> Optional[dict]:
    """Copie parlable DC3. None si le champ du stock manque."""
    if not isinstance(change, dict):
        return None
    if _is_aton_change(change):
        name = _aton_name(change)
        packed = dict(change)
        packed["kind"] = "aton"
        packed["title"] = name
        packed["fact"] = packed.get("fact") or name
        packed["id"] = f"dc3:aton:{change.get('id') or name}"
        return packed
    if _is_cable_change(change):
        name = _cable_name(change)
        packed = dict(change)
        packed["kind"] = "cable"
        packed["title"] = name
        packed["fact"] = packed.get("fact") or name
        packed["id"] = f"dc3:cable:{change.get('id') or name}"
        return packed
    if _is_depth_change(change):
        metres = _depth_m(change)
        packed = dict(change)
        packed["kind"] = "depth"
        packed["depth_m"] = metres
        packed["id"] = f"dc3:depth:{change.get('id') or change.get('tMs') or metres}"
        return packed
    if _is_piracy_change(change):
        name = _piracy_name(change)
        packed = dict(change)
        packed["kind"] = "piracy"
        packed["title"] = name
        packed["name"] = name
        packed["level"] = _piracy_level(change) or packed.get("level")
        packed["id"] = f"dc3:piracy:{change.get('id') or name}"
        return packed
    if _is_satellite_change(change):
        caption = _satellite_caption(change)
        packed = dict(change)
        packed["kind"] = "satellite"
        packed["caption"] = caption
        packed["title"] = caption
        packed["fact"] = caption
        packed["id"] = f"dc3:satellite:{change.get('id') or caption[:40]}"
        return packed
    return None


def _as_dc_change(change: dict) -> Optional[dict]:
    packed = _as_dc2_change(change)
    if packed:
        return packed
    return _as_dc3_change(change)


def dose_dc3_leg_changes(changes: list[dict], span_ms: int = 0) -> list[dict]:
    """Intégral, jambe longue : au plus une phrase par famille DC3."""
    if span_ms < SHORT_CROSSING_MS:
        return []
    by_kind: dict[str, list[dict]] = {k: [] for k in ("aton", "cable", "depth", "piracy", "satellite")}
    for change in changes or []:
        packed = _as_dc3_change(change)
        if not packed:
            continue
        kind = str(packed.get("kind") or "")
        if kind not in by_kind:
            continue
        if not _would_speak(packed):
            continue
        by_kind[kind].append(packed)
    out: list[dict] = []
    for kind in ("aton", "cable", "depth", "piracy", "satellite"):
        rows = by_kind[kind]
        if not rows:
            continue
        rows.sort(key=lambda c: (
            change_distance_nm(c) if change_distance_nm(c) is not None else 999.0,
            c.get("tMs") or 0,
        ))
        out.append(rows[0])
    return out


def _dc3_from_ici_bag(bag: dict | None, *, seq: Any = 0) -> list[dict]:
    """Candidats DC3 déjà dans un sac ici — copie, jamais inventée."""
    if not isinstance(bag, dict):
        return []
    extras: list[dict] = []
    aton = bag.get("aton") if isinstance(bag.get("aton"), dict) else {}
    for i, mark in enumerate(aton.get("nearby") or []):
        if not isinstance(mark, dict):
            continue
        name = _aton_name({"kind": "aton", "title": mark.get("name"), "name": mark.get("name")})
        if not name:
            continue
        extra = {
            "kind": "aton",
            "title": name,
            "fact": name,
            "name": name,
            "score": 2,
            "id": f"ici:aton:{seq}:{i}",
            "nm": mark.get("nm") if isinstance(mark.get("nm"), (int, float)) else None,
        }
        extras.append(extra)
        break
    emo = bag.get("emodnet") if isinstance(bag.get("emodnet"), dict) else {}
    cables = emo.get("cables") if isinstance(emo.get("cables"), dict) else {}
    cable_name = _cable_name({
        "kind": "cable",
        "title": cables.get("name"),
        "name": cables.get("name"),
        "fact": cables.get("name"),
    })
    if cable_name:
        extras.append({
            "kind": "cable",
            "title": cable_name,
            "fact": cable_name,
            "name": cable_name,
            "score": 2,
            "id": f"ici:cable:{seq}",
        })
    depth = None
    source = ""
    bathy = emo.get("bathy") if isinstance(emo.get("bathy"), dict) else {}
    depth = _as_depth_m(bathy.get("depth_m"))
    if depth is not None:
        source = "emodnet"
    else:
        depth = _as_depth_m(bag.get("depthOffshore"))
        if depth is not None:
            source = "gebco"
    if depth is not None:
        extras.append({
            "kind": "depth",
            "title": source,
            "fact": source,
            "depth_m": depth,
            "source": source,
            "score": 2,
            "id": f"ici:depth:{seq}:{source}",
        })
    pir = bag.get("piracy") if isinstance(bag.get("piracy"), dict) else None
    if isinstance(pir, dict) and pir.get("name"):
        extras.append({
            "kind": "piracy",
            "title": pir.get("name"),
            "fact": pir.get("name"),
            "name": pir.get("name"),
            "level": pir.get("level"),
            "source": pir.get("source"),
            "score": 2,
            "id": f"ici:piracy:{seq}:{pir.get('name')}",
        })
    sat = bag.get("satellites") if isinstance(bag.get("satellites"), dict) else {}
    caption = _satellite_caption({"kind": "satellite", "satellites": sat, "scene": sat.get("scene")})
    if caption:
        extras.append({
            "kind": "satellite",
            "title": caption,
            "fact": caption,
            "caption": caption,
            "score": 2,
            "id": f"ici:satellite:{seq}",
        })
    return extras


def _dc_changes_from_ici_route() -> list[dict]:
    """Recherche le long de la route officielle : sacs ici déjà calculés."""
    try:
        from official_store import payload_of  # noqa: PLC0415
        body = payload_of("ici")
    except Exception:
        return []
    if not isinstance(body, dict):
        return []
    rows: list[dict] = []
    for i, point in enumerate(body.get("points") or []):
        if not isinstance(point, dict):
            continue
        bag = point.get("bag")
        if not isinstance(bag, dict) or "amp" not in bag:
            continue
        for extra in _dc3_from_ici_bag(bag, seq=point.get("sailNm") or point.get("nm") or i):
            pair = _as_latlon(point.get("lat"), point.get("lon"))
            if pair:
                extra["lat"], extra["lon"] = pair
            rows.append(extra)
    return rows


def _dc_amp_changes_from_journal(journal: dict | None) -> list[dict]:
    rows: list[dict] = []
    for moment in _journal_moments(journal):
        for change in moment.get("changes") or []:
            if isinstance(change, dict) and _is_amp_change(change):
                packed = dict(change)
                if not packed.get("t"):
                    packed["t"] = moment.get("t")
                rows.append(packed)
    for entry in journal_entries(journal):
        if str(entry.get("kind") or "") != "amp":
            continue
        rows.append({
            **entry,
            "kind": "amp",
            "title": entry.get("title") or entry.get("name") or "",
            "fact": entry.get("fact") or entry.get("name") or "",
        })
    return rows


def _dc_changes_from_journal(journal: dict | None) -> list[dict]:
    """Faits DC du journal et des sacs ici le long de la route."""
    rows = _dc_amp_changes_from_journal(journal)
    dc3_kinds = DC2_KINDS | DC3_KINDS
    for moment in _journal_moments(journal):
        t = moment.get("t")
        for change in moment.get("changes") or []:
            if not isinstance(change, dict):
                continue
            if (
                _is_buoy_change(change)
                or _is_poe_formality_change(change)
                or _is_anchorage_change(change)
                or _is_aton_change(change)
                or _is_cable_change(change)
                or _is_depth_change(change)
                or _is_piracy_change(change)
                or _is_satellite_change(change)
            ):
                packed = dict(change)
                if not packed.get("t"):
                    packed["t"] = t
                rows.append(packed)
        mom = moment.get("moment") if isinstance(moment.get("moment"), dict) else {}
        for item in mom.get("around") or []:
            if not isinstance(item, dict):
                continue
            mapped = AROUND_TO_KIND.get(str(item.get("kind") or ""))
            kind = mapped or str(item.get("kind") or "")
            if kind not in dc3_kinds:
                continue
            packed = dict(item)
            packed["kind"] = kind
            if not packed.get("t"):
                packed["t"] = t
            rows.append(packed)
        here = mom.get("here") if isinstance(mom.get("here"), dict) else {}
        for i, mark in enumerate(here.get("seamarks") or []):
            if not isinstance(mark, dict) or not mark.get("name"):
                continue
            packed = {
                "kind": "aton",
                "title": mark.get("name"),
                "fact": mark.get("name"),
                "name": mark.get("name"),
                "nm": mark.get("nm") if isinstance(mark.get("nm"), (int, float)) else None,
                "id": f"here:aton:{moment.get('seq')}:{i}",
            }
            if not packed.get("t"):
                packed["t"] = t
            rows.append(packed)
    for entry in journal_entries(journal):
        kind = str(entry.get("kind") or "")
        mapped = DC3_KIND_ALIASES.get(kind.casefold(), kind)
        if mapped not in {"poe", "sci", "station", "anchorage", "buoy"} | DC3_KINDS:
            continue
        rows.append({
            **entry,
            "kind": mapped if mapped in DC3_KINDS else kind,
            "title": entry.get("title") or entry.get("name") or "",
            "fact": entry.get("fact") or entry.get("name") or "",
        })
    rows.extend(_dc_changes_from_ici_route())
    return rows


def _with_dc_subjects(plan: dict, journal: dict | None, lang: str) -> dict:
    plan["dcSubjects"] = dc_subject_candidates(_dc_changes_from_journal(journal), lang)
    return plan


_FR_SMALL = (
    "zéro", "un", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf",
    "dix", "onze", "douze", "treize", "quatorze", "quinze", "seize",
    "dix-sept", "dix-huit", "dix-neuf",
)
_EN_SMALL = (
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
    "seventeen", "eighteen", "nineteen",
)


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


def spoken_distance(nm: Any, lang: str = "fr") -> str:
    """« douze milles » / « twelve miles » — chiffres 1–30 en toutes lettres."""
    try:
        v = int(round(float(nm)))
    except (TypeError, ValueError):
        return ""
    if v < 0:
        return ""
    word = _spoken_int(v, lang)
    if _en(lang):
        unit = "mile" if v == 1 else "miles"
        return f"{word} {unit}"
    unit = "mille" if v == 1 else "milles"
    return f"{word} {unit}"


def dose_amp_changes(changes: list[dict], span_ms: int) -> list[dict]:
    """Au plus une AMP par étape courte, trois par traversée longue ; plus proche d'abord."""
    amps = [c for c in changes if _is_amp_change(c)]
    amps.sort(key=lambda c: (
        change_distance_nm(c) if change_distance_nm(c) is not None else 999.0,
        c.get("tMs") or 0,
    ))
    limit = 1 if span_ms < SHORT_CROSSING_MS else LONG_AMP_PROJECT
    return amps[:limit]


def dose_project_changes(changes: list[dict], span_ms: int) -> list[dict]:
    """Au plus un projet par étape courte, trois par traversée ; gold_on puis plus proche."""
    projs = [c for c in changes if str(c.get("kind") or "") == "project"]
    def gold(c: dict) -> int:
        return 0 if c.get("gold_on") in (True, 1, "1", "true", "True") else 1
    projs.sort(key=lambda c: (
        gold(c),
        change_distance_nm(c) if change_distance_nm(c) is not None else 999.0,
        c.get("tMs") or 0,
    ))
    limit = 1 if span_ms < SHORT_CROSSING_MS else LONG_AMP_PROJECT
    return projs[:limit]


def dose_station_changes(
    changes: list[dict], span_ms: int = 0,
    t_a: Optional[int] = None, t_b: Optional[int] = None,
) -> list[dict]:
    """Une station qualifiée par étape, la plus proche de la route ; pas de
    comptage. RC26 : une longue traversée en dit jusqu'à trois, réparties dans le
    temps (une par tranche de la jambe) — le Pacifique ne reste pas muet quinze jours."""
    rows = [
        c for c in changes
        if str(c.get("kind") or "") == "station"
        and station_spoken_label(c, "fr")
        and not (span_ms >= SHORT_CROSSING_MS and _is_buoy_change(c))
    ]
    if not rows:
        return []
    days = max(0.0, float(span_ms or 0) / 86_400_000.0)
    limit = 1 if days < 12 else min(3, math.ceil(days / 10.0))
    if limit <= 1 or len(rows) <= 1:
        rows.sort(key=lambda c: (
            change_distance_nm(c) if change_distance_nm(c) is not None else 999.0,
            c.get("tMs") or 0,
        ))
        return rows[:1]
    lo = int(t_a) if t_a is not None else min(int(c.get("tMs") or 0) for c in rows)
    hi = int(t_b) if t_b is not None else max(int(c.get("tMs") or 0) for c in rows)
    width = max(1, (hi - lo) // limit + 1)
    out: list[dict] = []
    by_slot: dict[int, list[dict]] = {}
    for c in rows:
        slot = min(limit - 1, max(0, (int(c.get("tMs") or 0) - lo) // width))
        by_slot.setdefault(slot, []).append(c)
    for slot in sorted(by_slot):
        cands = by_slot[slot]
        cands.sort(key=lambda c: (
            change_distance_nm(c) if change_distance_nm(c) is not None else 999.0,
            c.get("tMs") or 0,
        ))
        out.append(cands[0])
        if len(out) >= limit:
            break
    out.sort(key=lambda c: (c.get("tMs") or 0, str(c.get("id") or "")))
    return out


def change_is_speakable(change: dict) -> bool:
    kind = str(change.get("kind") or "")
    if kind in {"regime", "alert-off"}:
        return False
    if is_sea_hs_alert(change):
        return True
    if kind == "alert-on":
        body = str(change.get("fact") or change.get("title") or "").strip()
        if not body or NO_DATA_RE.search(body):
            return False      # « Aucun port d'entrée officiel n'est connu pour … » : l'absence ne se raconte pas
        if alert_is_amp(change):
            return bool(alert_amp_name(change))
        return True
    if kind == "amp":
        from ici_engine import is_fishing_amp, spoken_amp_name  # noqa: PLC0415
        if str(change.get("event") or "") == "exit":
            return False
        if is_fishing_amp({"name": change.get("title"), "fact": change.get("fact")}):
            return False
        name = spoken_amp_name(change_place_name(change) or change.get("title") or "")
        return bool(name) and not _is_generic_title(name, "amp") and len(name) > 2
    if kind == "project":
        return bool(change_place_name(change))
    if kind == "climo":
        return bool(climo_sentence(change, "fr") or climo_sentence(change, "en"))
    if kind == "cyclone":
        return bool(cyclone_name_year(change)[0])
    if kind == "culture":
        return bool(change_place_name(change) or change.get("fact"))
    if kind == "station":
        return bool(station_spoken_label(change, "fr"))
    if kind == "buoy":
        return bool(station_spoken_label({**change, "kind": "station"}, "fr"))
    if kind == "poe":
        return bool(_poe_place_name(change))
    if kind == "anchorage":
        return bool(_anchorage_name(change))
    if kind == "aton":
        return bool(_aton_name(change))
    if kind == "cable":
        return bool(_cable_name(change))
    if kind == "depth":
        return _depth_m(change) is not None
    if kind == "piracy":
        return bool(_piracy_name(change))
    if kind == "satellite":
        return bool(_satellite_caption(change))
    return bool(change_place_name(change))


_EARTH_NM = 3440.065
_PORT_LEAVE_NM = 2.0
_PORT_ANCHOR_NM = 5.0
_AIR_ONLY_KEYS = frozenset({"halifax", "saint-pierre"})
_AIR_KEYS = frozenset({"cayenne", "halifax"})
_SIDE_KEYS = frozenset({"halifax", "saint-pierre"})


def _air_stop_key(name: str) -> str:
    s = str(name or "").casefold()
    if "cayenne" in s:
        return "cayenne"
    if "halifax" in s:
        return "halifax"
    if "miquelon" in s or "saint-pierre" in s or "saint pierre" in s:
        return "saint-pierre"
    return ""


def _is_air_only_stop(name: str) -> bool:
    return _air_stop_key(name) in _AIR_ONLY_KEYS


def _is_air_leg(a: str, b: str) -> bool:
    """Jambe avion : uniquement Cayenne ↔ Halifax (aller et retour)."""
    x, y = _air_stop_key(a), _air_stop_key(b)
    return (x == "cayenne" and y == "halifax") or (x == "halifax" and y == "cayenne")


def _is_side_leg(a: str, b: str) -> bool:
    """Traversée du second bateau : Halifax ↔ Saint-Pierre."""
    x, y = _air_stop_key(a), _air_stop_key(b)
    return {x, y} == _SIDE_KEYS


def _is_land_leg(a: str, b: str) -> bool:
    return (
        is_saint_maur(a) and bool(_ROCHELLE_RE.search(str(b or "")))
    ) or (
        is_saint_maur(b) and bool(_ROCHELLE_RE.search(str(a or "")))
    )


def _nm_between(lat1: Any, lon1: Any, lat2: Any, lon2: Any) -> Optional[float]:
    try:
        p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
        dphi = math.radians(float(lat2) - float(lat1))
        dlamb = math.radians(float(lon2) - float(lon1))
    except (TypeError, ValueError):
        return None
    a = math.sin(dphi / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlamb / 2.0) ** 2
    return 2.0 * _EARTH_NM * math.asin(min(1.0, math.sqrt(a)))


def _mode_from_vehicle(veh: Any) -> Optional[str]:
    if veh == "plane":
        return "air"
    if veh == "land":
        return "road"
    if veh in {"main", "boat", "side"}:
        return "sail"
    return None


def _window_mode_name(mode: str) -> str:
    return mode if mode in {"sail", "air", "road"} else "sail"


def _classify_window_mode(
    frm: dict | None,
    to: dict | None,
    clock: dict | None,
    t_a: Optional[int],
    t_b: Optional[int],
) -> str:
    a = (frm or {}).get("name") or ""
    b = (to or {}).get("name") or ""
    if _is_land_leg(a, b):
        return "road"
    if _is_air_leg(a, b):
        return "air"
    plat, plon = (frm or {}).get("lat"), (frm or {}).get("lon")
    for v in ((clock or {}).get("vertices") or []):
        if not isinstance(v, dict):
            continue
        t = _ms(v.get("iso"))
        if t is None:
            continue
        if t_a is not None and t < t_a:
            continue
        if t_b is not None and t > t_b:
            continue
        if v.get("vehicle") == "quay":
            continue
        d = _nm_between(plat, plon, v.get("lat"), v.get("lon"))
        if d is not None and d <= _PORT_LEAVE_NM:
            continue
        found = _mode_from_vehicle(v.get("vehicle"))
        # Sommet route loin du port = autre fenêtre (Saint-Maur → La Rochelle
        # ne doit pas classer La Rochelle → Ajaccio « par la route »).
        if found == "road" and d is not None and d > 80:
            continue
        if found:
            return found
    for src in (frm, to):
        found = _mode_from_vehicle((src or {}).get("vehicle"))
        if found and found != "sail":
            return found
    return "sail"


def _window_vehicle(frm: dict | None, to: dict | None, clock: dict | None = None) -> str:
    a = (frm or {}).get("name") or ""
    b = (to or {}).get("name") or ""
    if _is_side_leg(a, b):
        return "side"
    mode = _classify_window_mode(frm, to, clock, _ms((frm or {}).get("iso")), _ms((to or {}).get("iso")))
    return {"air": "plane", "road": "land", "sail": "main"}.get(mode, "main")


def _window_dest_name(w: dict) -> str:
    return short_name(
        w.get("destName") or (w.get("to") or {}).get("name") or w.get("toName") or ""
    )


def _is_air_window(w: dict | None) -> bool:
    w = w or {}
    if w.get("mode") == "air" or w.get("vehicle") == "plane":
        return True
    return _is_air_leg(
        (w.get("from") or {}).get("name") or w.get("fromName") or "",
        _window_dest_name(w),
    )


def _is_side_window(w: dict | None) -> bool:
    w = w or {}
    if w.get("vehicle") == "side" or w.get("mode") == "side":
        return True
    return _is_side_leg(
        (w.get("from") or {}).get("name") or w.get("fromName") or "",
        _window_dest_name(w),
    )


# Saint-Pierre → Halifax est dans l'Atlantique nord (~45–47° N).
# Cayenne / l'équateur / la Guyane (~5° N) n'y ont pas leur place — ces
# phrases restent sur Marigot → Cayenne et Cayenne → Papeete.
_GUYANA_EQUATOR_RE = re.compile(
    r"french guiana|guyane|guyanese|\bequator\b|[\ée]quateur|\bequatorial\b",
    re.I,
)
_SPM_NORTH_LAT = 35.0


def _is_saint_pierre_depart(w: dict | None) -> bool:
    w = w or {}
    frm = w.get("fromName") or (w.get("from") or {}).get("name") or ""
    return _air_stop_key(frm) == "saint-pierre"


def _change_is_guiana_or_equator(change: dict | None) -> bool:
    """Événement de Guyane / d'équateur (titre, lieu dit, ou latitude trop sud)."""
    if not isinstance(change, dict):
        return False
    blob = " ".join(
        str(x) for x in (
            change.get("title"), change.get("fact"), change.get("name"),
            change.get("placeFr"), change.get("placeEn"),
            change.get("event"), change.get("regimeId"),
            *(change.get("members") or []),
        ) if x
    )
    if _GUYANA_EQUATOR_RE.search(blob):
        return True
    lat = None
    try:
        lat = float(change["lat"])
    except (TypeError, ValueError, KeyError):
        pair = _row_latlon(change)
        lat = pair[0] if pair else None
    return lat is not None and lat < _SPM_NORTH_LAT


def _drop_guiana_equator_changes(changes: list[dict]) -> list[dict]:
    return [c for c in changes if not _change_is_guiana_or_equator(c)]


def _is_road_window(w: dict | None) -> bool:
    w = w or {}
    if w.get("mode") == "road" or w.get("vehicle") == "land":
        return True
    return _is_land_leg(
        (w.get("from") or {}).get("name") or w.get("fromName") or "",
        _window_dest_name(w),
    )


def _clock_leave_ms(
    clock: dict | None,
    port_lat: Any,
    port_lon: Any,
    t_a: Optional[int],
    t_b: Optional[int] = None,
    *,
    mode: str = "sail",
) -> Optional[int]:
    """Premier sommet qui quitte le port (d > 2 nm) pour ce mode. Jamais tA + escale."""
    if t_a is None:
        return None
    want = {"air": {"plane"}, "road": {"land"}, "sail": {"main", "boat", "side"}}.get(
        _window_mode_name(mode), {"main", "boat", "side"},
    )
    prev_at = t_a
    for v in ((clock or {}).get("vertices") or []):
        if not isinstance(v, dict):
            continue
        t = _ms(v.get("iso"))
        if t is None or t < t_a:
            continue
        if t_b is not None and t > t_b:
            continue
        veh = v.get("vehicle")
        if veh == "quay":
            continue
        if want and veh not in want:
            continue
        d = _nm_between(port_lat, port_lon, v.get("lat"), v.get("lon"))
        if d is None:
            continue
        if d <= _PORT_LEAVE_NM:
            prev_at = t
            continue
        if t == t_a or d <= _PORT_ANCHOR_NM:
            return t
        return prev_at
    return t_a


def _first_leg_moment_ms(moments: list | None, w: dict) -> Optional[int]:
    """Premier moment émis SUR la jambe (leg.from = port de départ de la fenêtre) :
    la vérité du terrain — si le bateau émet à 13 h, il n'est plus à quai à 13 h."""
    frm = re.split(r"\s*\(", str(w.get("fromName") or ""))[0].strip().casefold()
    if not frm:
        return None
    t_a, t_b = w.get("tA"), w.get("tB")
    best: Optional[int] = None
    last: Optional[int] = None
    for m in moments or []:
        if not isinstance(m, dict):
            continue
        leg = (m.get("moment") or {}).get("leg") or {}
        mf = re.split(r"\s*\(", str(leg.get("from") or ""))[0].strip().casefold()
        if mf != frm:
            continue
        t = _ms(m.get("t"))
        if t is None:
            continue
        last = t if last is None else max(last, t)
        if (t_a is not None and t <= t_a) or (t_b is not None and t > t_b):
            continue
        if best is None or t < best:
            best = t
    # Moments d'une autre simulation que l'horloge (magasin figé : jambe finie le
    # 19 juillet côté moments, arrivée le 23 côté horloge) : leur premier instant
    # n'avance pas l'appareillage — sinon « départ le 19, un jour de mer, arrivée le 23 ».
    if best is not None and last is not None and t_b is not None and t_b - last > _LEG_DESYNC_MS:
        return None
    return best


_LEG_DESYNC_MS = 86_400_000


def _window_depart_ms(w: dict) -> Optional[int]:
    """Départ = premier sommet d'horloge qui quitte le port, jamais tA + jours d'escale."""
    if w.get("departMs"):
        return int(w["departMs"])
    t_a = w.get("tA")
    frm = w.get("from") or {}
    clock = w.get("clock")
    mode = _window_mode_name(str(w.get("mode") or _mode_from_vehicle(w.get("vehicle")) or "sail"))
    leave = _clock_leave_ms(
        clock, frm.get("lat"), frm.get("lon"), t_a, w.get("tB"), mode=mode,
    )
    # Quand l'horloge répond exactement « départ = tA » (aucune sortie de
    # port trouvée — Papeete, pas de sommet « quay »), l'escale des marks donne
    # l'appareillage (arrivée + holdHours) — les trois jours à quai ne comptent
    # plus comme de la mer dans les fenêtres. Une horloge qui a une vraie trace
    # de sortie garde son départ.
    name = re.split(r"\s*\(", str(w.get("fromName") or ""))[0].strip().casefold()
    t_b = w.get("tB")
    t0 = _ms((clock or {}).get("t0"))
    if name and leave is not None and t_a is not None and leave == t_a:
        for mark in (clock or {}).get("marks") or []:
            mark_name = re.split(r"\s*\(", str(mark.get("name") or ""))[0].strip().casefold()
            if mark_name != name:
                continue
            arr = _ms(mark.get("iso"))
            hold = float(mark.get("holdHours") or 0)
            if arr is not None and t0 is not None and arr <= t0:
                continue  # port de départ du voyage : t0 EST l'appareillage
            if arr is not None and hold > 0:
                depart = arr + int(hold * 3_600_000)
                if (
                    t_a is not None and t_a <= depart and (not t_b or depart < t_b)
                    and (leave is None or depart > leave)
                ):
                    return depart
    if leave is not None:
        return leave
    return t_a


def _clock_has_quay(clock: dict | None, stop: dict | None) -> bool:
    if not clock or not stop:
        return False
    lat, lon = stop.get("lat"), stop.get("lon")
    arrived = _ms(stop.get("iso"))
    for v in (clock.get("vertices") or []):
        if not isinstance(v, dict) or v.get("vehicle") != "quay":
            continue
        d = _nm_between(lat, lon, v.get("lat"), v.get("lon"))
        if d is not None and d <= _PORT_ANCHOR_NM:
            return True
    if arrived is None or lat is None or lon is None:
        return False
    leave = _clock_leave_ms(clock, lat, lon, arrived, mode="sail")
    return leave is not None and leave - arrived >= 12 * 3_600_000


def _quay_hours_for_arrival(stop: dict | None, clock: dict | None) -> Any:
    if not stop:
        return 0
    verts = (clock or {}).get("vertices") or []
    if verts:
        return stop.get("holdHours") if _clock_has_quay(clock, stop) else 0
    return stop.get("holdHours")


def _air_return_ms(
    clock: dict | None,
    stay: dict | None,
    after_ms: Optional[int],
    t_end: Optional[int],
) -> Optional[int]:
    lat, lon = (stay or {}).get("lat"), (stay or {}).get("lon")
    if lat is None or lon is None:
        return None
    for v in ((clock or {}).get("vertices") or []):
        if not isinstance(v, dict) or v.get("vehicle") != "plane":
            continue
        t = _ms(v.get("iso"))
        if t is None or (after_ms is not None and t <= after_ms):
            continue
        if t_end is not None and t > t_end:
            continue
        d = _nm_between(lat, lon, v.get("lat"), v.get("lon"))
        if d is not None and d <= _PORT_ANCHOR_NM:
            return t
    return None


def _moment_leg(row: dict) -> dict:
    moment = row.get("moment") if isinstance(row.get("moment"), dict) else {}
    leg = moment.get("leg") if isinstance(moment.get("leg"), dict) else {}
    return leg if isinstance(leg, dict) else {}


def _moment_is_air(row: dict) -> bool:
    leg = _moment_leg(row)
    if leg.get("vehicle") == "plane":
        return True
    return _is_air_leg(str(leg.get("from") or ""), str(leg.get("to") or ""))


def _air_return_from_moments(
    moments: list | None,
    stay_name: str,
    after_ms: Optional[int],
) -> Optional[int]:
    stay_key = _air_stop_key(stay_name)
    for row in moments or []:
        if not isinstance(row, dict) or not _moment_is_air(row):
            continue
        t = _ms(row.get("t"))
        if t is None or (after_ms is not None and t <= after_ms):
            continue
        dest = str(_moment_leg(row).get("to") or "")
        if stay_key and _air_stop_key(dest) == stay_key:
            return t
        if stay_name and same_stop(dest, stay_name):
            return t
    return None


def _km_label(nm: Any, lang: str) -> str:
    try:
        km = int(round(float(nm or 0) * NM_TO_KM))
    except (TypeError, ValueError):
        return ""
    if _en(lang):
        return f"{km} kilometer" + ("" if km == 1 else "s")
    return f"{km} kilomètre" + ("" if km == 1 else "s")


def script_words(chapters: list[dict]) -> int:
    blob = " ".join(c.get("text") or "" for c in chapters)
    return len(re.findall(r"\S+", blob))


_SAINT_MAUR_RE = re.compile(r"saint[\s\-]*maur", re.I)
_ROCHELLE_RE = re.compile(r"rochelle", re.I)


def is_saint_maur(name: str) -> bool:
    return bool(_SAINT_MAUR_RE.search(str(name or "")))


def _align_quay_stop_to_passage(stop: dict, clock: dict | None) -> dict:
    """Recolle l'iso d'une escale sur le passage horloge au lieu nommé (hub / filmNm)."""
    if not clock or not isinstance(stop, dict):
        return stop
    coords = _canonical_place_coords(stop.get("name") or "")
    if coords is None:
        return stop
    try:
        mlat, mlon = float(stop["lat"]), float(stop["lon"])
        d_mark = _nm_between(coords[0], coords[1], mlat, mlon)
    except (TypeError, ValueError, KeyError):
        d_mark = None
    if d_mark is not None and d_mark <= 50.0:
        return stop
    t = _clock_time_near_coords(clock, coords[0], coords[1], None, None)
    if t is None:
        return stop
    boat = _clock_latlon_at(clock, t)
    if boat is None:
        return stop
    d = _nm_between(coords[0], coords[1], boat[0], boat[1])
    if d is None or d > 30.0:
        return stop
    return {
        **stop,
        "iso": _iso(t),
        "lat": coords[0],
        "lon": coords[1],
    }


def _itinerary_sail_nm(mark: dict) -> Optional[float]:
    """Milles de mer de l'itinéraire. `nm` prime sur `filmNm` (décalé d'un offset)."""
    nm = mark.get("nm")
    film = mark.get("filmNm")
    if isinstance(nm, (int, float)) and not isinstance(nm, bool) and float(nm) > 0.5:
        return float(nm)
    if isinstance(film, (int, float)) and not isinstance(film, bool):
        return float(film)
    if isinstance(nm, (int, float)) and not isinstance(nm, bool):
        return float(nm)
    return None


def _iso_on_itinerary(clock: dict | None, mark: dict) -> Optional[str]:
    """Date du sommet déjà dans l'horloge, au mille d'itinéraire.

    Une marque sans iso (Mata-Utu, Nouméa) ne doit pas disparaître : l'horloge
    datée du poste leur colle parfois le filmNm du retour atlantique, et le
    rapprochement par filmNm rate. Le sommet au mille réel, lui, est dans le
    Pacifique. Aucune date n'est inventée : sans sommet, on ne date pas.
    """
    if not isinstance(mark, dict) or not isinstance(clock, dict):
        return None
    if _ms(mark.get("iso")) is not None:
        return None
    nm = _itinerary_sail_nm(mark)
    if nm is None or not clock.get("vertices"):
        return None
    t0 = _ms(clock.get("t0"))
    if t0 is None:
        return None
    from plan_review import _t_hours_at_sail_nm  # noqa: PLC0415

    hit = _t_hours_at_sail_nm(clock, nm)
    if hit is None:
        return None
    t_hours, _sail = hit
    return _iso(t0 + int(round(float(t_hours) * 3_600_000)))


def official_dated_stops(marks: list | None, clock: dict | None = None) -> list[dict]:
    """Escales datées, Saint-Maur + 15 mai 2026 en tête. Aucune autre date inventée."""
    raw = marks if marks else (clock or {}).get("marks")
    stamped: list = []
    for mark in raw or []:
        if not isinstance(mark, dict):
            continue
        row = dict(mark)
        iso = _iso_on_itinerary(clock, row)
        if iso:
            row["iso"] = iso
        stamped.append(row)
    dated = dated_marks(stamped)
    saint_raw = next(
        (m for m in (raw or []) if isinstance(m, dict) and is_saint_maur(m.get("name") or "")),
        None,
    )
    saint = next((s for s in dated if is_saint_maur(s["name"])), None)
    if saint:
        head = {**saint, "iso": OFFICIAL_T0}
    else:
        src = saint_raw or {}
        film = src.get("filmNm") if src.get("filmNm") is not None else src.get("nm")
        head = {
            "name": src.get("name") or "Saint-Maur",
            "iso": OFFICIAL_T0,
            "filmNm": float(film or 0),
            "nm": float(src["nm"]) if isinstance(src.get("nm"), (int, float)) else 0.0,
            "holdHours": float(src.get("holdHours") or 0),
            "lat": src.get("lat") if isinstance(src.get("lat"), (int, float)) else None,
            "lon": src.get("lon") if isinstance(src.get("lon"), (int, float)) else None,
        }
    rest = [_align_quay_stop_to_passage(s, clock) for s in dated if not is_saint_maur(s["name"])]
    # Premier départ mer (La Rochelle, filmNm ~122) : garder au 15 mai même
    # sans iso, et ne pas lui coller la date du retour (même nom, 2027).
    sea = next(
        (
            s for s in rest
            if _ROCHELLE_RE.search(s.get("name") or "")
            and float(s.get("filmNm") if s.get("filmNm") is not None else s.get("nm") or 0) < 2000
        ),
        None,
    )
    if sea is None:
        sea = _sea_stop([], raw, clock)
    if sea and _ROCHELLE_RE.search(sea.get("name") or ""):
        film = float(sea.get("filmNm") if sea.get("filmNm") is not None else sea.get("nm") or 0)
        if film < 2000:
            others = [s for s in rest if not same_stop(s["name"], sea["name"])]
            next_ms = _ms(others[0]["iso"]) if others else None
            sea_ms = _ms(sea.get("iso"))
            if sea_ms is None or (next_ms is not None and sea_ms >= next_ms):
                sea = {**sea, "iso": OFFICIAL_T0}
            rest = [sea, *others]
    return _recover_air_stops([head, *rest], raw, clock)


def _plane_iso_near(vertices: list | None, lat: Any, lon: Any) -> Optional[str]:
    """Iso d'un sommet avion déjà calculé, près de l'escale — pas une date inventée."""
    try:
        plat, plon = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    best_iso = None
    best_d2 = 0.25
    for v in vertices or []:
        if not isinstance(v, dict) or v.get("vehicle") != "plane":
            continue
        try:
            dlat = float(v.get("lat")) - plat
            dlon = float(v.get("lon")) - plon
        except (TypeError, ValueError):
            continue
        d2 = dlat * dlat + dlon * dlon
        if d2 < best_d2 and _ms(v.get("iso")) is not None:
            best_d2 = d2
            best_iso = v.get("iso")
    return str(best_iso) if best_iso else None


def _air_src_row(src: dict, iso: str) -> dict:
    film = src.get("filmNm") if src.get("filmNm") is not None else src.get("nm")
    return {
        "name": src["name"],
        "iso": iso,
        "filmNm": float(film or 0),
        "nm": float(src["nm"]) if isinstance(src.get("nm"), (int, float)) else float(film or 0),
        "holdHours": float(src.get("holdHours") or 0),
        "lat": src.get("lat") if isinstance(src.get("lat"), (int, float)) else None,
        "lon": src.get("lon") if isinstance(src.get("lon"), (int, float)) else None,
        "vehicle": src.get("vehicle") if src.get("vehicle") in {"plane", "land", "main", "side"} else None,
    }


def _recover_air_stops(dated: list[dict], raw: list | None, clock: dict | None) -> list[dict]:
    """Halifax / Cayenne absents des dates (arrivée avion hors clock_marks) : iso du sommet plane."""
    have = {_air_stop_key(s.get("name") or "") for s in dated}
    pool = [m for m in (raw or []) if isinstance(m, dict)]
    pool.extend(m for m in ((clock or {}).get("marks") or []) if isinstance(m, dict))
    vertices = [v for v in ((clock or {}).get("vertices") or []) if isinstance(v, dict)]
    out = list(dated)
    for key in ("cayenne", "halifax"):
        if key in have:
            continue
        src = next((m for m in pool if _air_stop_key(m.get("name") or "") == key), None)
        if src is None:
            continue
        iso = src.get("iso") if _ms(src.get("iso")) is not None else None
        if iso is None:
            hit = next(
                (
                    m for m in ((clock or {}).get("marks") or [])
                    if isinstance(m, dict)
                    and _air_stop_key(m.get("name") or "") == key
                    and _ms(m.get("iso")) is not None
                ),
                None,
            )
            if hit:
                iso = hit.get("iso")
        if iso is None:
            iso = _plane_iso_near(vertices, src.get("lat"), src.get("lon"))
        if iso is None:
            continue
        row = _air_src_row(src, str(iso))
        cay_i = next((i for i, s in enumerate(out) if _air_stop_key(s.get("name") or "") == "cayenne"), None)
        if key == "halifax" and cay_i is not None:
            out.insert(cay_i + 1, row)
        else:
            out.append(row)
        have.add(key)
    return out


def _sea_stop(stops: list[dict], marks: list | None, clock: dict | None) -> Optional[dict]:
    for s in (stops or [])[1:]:
        if _ROCHELLE_RE.search(s.get("name") or ""):
            return s
    raw = list(marks or []) + list((clock or {}).get("marks") or [])
    for m in raw:
        if isinstance(m, dict) and _ROCHELLE_RE.search(str(m.get("name") or "")):
            film = m.get("filmNm") if m.get("filmNm") is not None else m.get("nm")
            return {
                "name": m["name"],
                "iso": m.get("iso"),
                "filmNm": float(film or 0),
                "nm": float(m["nm"]) if isinstance(m.get("nm"), (int, float)) else 0.0,
                "holdHours": float(m.get("holdHours") or 0),
                "lat": m.get("lat") if isinstance(m.get("lat"), (int, float)) else None,
                "lon": m.get("lon") if isinstance(m.get("lon"), (int, float)) else None,
            }
    if len(stops or []) > 1:
        return stops[1]
    return {"name": "La Rochelle"}


def merge_route_marks(route_marks: list | None, clock: dict | None) -> list[dict]:
    """Marques de la route + iso de l'horloge. Pas de date inventée."""
    clock_marks = [c for c in ((clock or {}).get("marks") or []) if isinstance(c, dict)]
    if not route_marks:
        return list(clock_marks)
    out: list[dict] = []
    for m in route_marks:
        if not isinstance(m, dict):
            continue
        row = dict(m)
        if _ms(row.get("iso")) is None:
            film = float(row.get("filmNm") if row.get("filmNm") is not None else row.get("nm") or 0)
            name = row.get("name") or ""
            hit = next(
                (
                    c for c in clock_marks
                    if abs(float(c.get("filmNm") if c.get("filmNm") is not None else c.get("nm") or 0) - film) < 0.6
                    and (not name or c.get("name") == name)
                ),
                None,
            )
            if hit is None:
                named = [
                    c for c in clock_marks
                    if name and same_stop(c.get("name") or "", name)
                ]
                compat = [
                    c for c in named
                    if abs(float(c.get("filmNm") if c.get("filmNm") is not None else c.get("nm") or 0) - film) < 80
                    or (film < 2000 and float(c.get("filmNm") if c.get("filmNm") is not None else c.get("nm") or 0) < 2000)
                ]
                hit = compat[0] if compat else None
            if hit:
                row["iso"] = hit.get("iso")
                if hit.get("holdHours") is not None:
                    row["holdHours"] = hit.get("holdHours")
                if row.get("lat") is None:
                    row["lat"] = hit.get("lat")
                if row.get("lon") is None:
                    row["lon"] = hit.get("lon")
        out.append(row)
    return out


def _days(hours: Any) -> int:
    try:
        return max(0, round(float(hours or 0) / 24.0))
    except (TypeError, ValueError):
        return 0


def _quay(entry: dict) -> int:
    if isinstance(entry.get("daysAtQuay"), (int, float)):
        return int(round(entry["daysAtQuay"]))
    return _days(entry.get("holdHours"))


def _fact_num(entry: dict, *keys: str) -> Optional[float]:
    facts = entry.get("facts") if isinstance(entry.get("facts"), dict) else {}
    for k in keys:
        v = entry.get(k, facts.get(k))
        if isinstance(v, (int, float)):
            return float(v)
    return None


def _plain(v: Optional[float], digits: int = 0) -> str:
    if v is None:
        return ""
    if digits <= 0:
        return str(int(round(v)))
    s = f"{v:.{digits}f}".rstrip("0").rstrip(".")
    return s


def journal_entries(journal: dict | None) -> list[dict]:
    if not isinstance(journal, dict):
        return []
    all_e = list(journal.get("events") or []) + list(journal.get("latest") or journal.get("entries") or [])
    seen: set[str] = set()
    out: list[dict] = []
    for e in all_e:
        if not isinstance(e, dict):
            continue
        eid = str(e.get("id") or f"{e.get('kind')}:{e.get('t')}")
        if eid in seen:
            continue
        seen.add(eid)
        out.append(e)
    return out


def dated_marks(marks: list | None) -> list[dict]:
    out: list[dict] = []
    for m in marks or []:
        if not isinstance(m, dict) or not m.get("name") or _ms(m.get("iso")) is None:
            continue
        film = float(m.get("filmNm") if m.get("filmNm") is not None else m.get("nm") or 0)
        key = norm_stop(m["name"])
        if not key:
            continue
        # Fusion seulement si c'est le même port (« Ajaccio » ≡ « Ajaccio (Corse) »).
        # Deux noms distincts (Saint-Maur / La Rochelle) restent, même à filmNm 0.
        # Halifax / Cayenne de l'épisode : aller et retour gardés si l'iso diffère.
        same = [x for x in out if same_stop(x["name"], m["name"])]
        if same:
            key = _air_stop_key(m["name"])
            if key not in {"halifax", "cayenne", "saint-pierre"}:
                continue
            t_new = _ms(m.get("iso"))
            t_old = _ms(same[-1].get("iso"))
            if t_new is None or t_old is None or abs(t_new - t_old) < 6 * 3_600_000:
                continue
        out.append({
            "name": m["name"],
            "iso": m["iso"],
            "filmNm": film,
            "nm": float(m["nm"]) if isinstance(m.get("nm"), (int, float)) else film,
            "holdHours": float(m.get("holdHours") or 0),
            "lat": m.get("lat") if isinstance(m.get("lat"), (int, float)) else None,
            "lon": m.get("lon") if isinstance(m.get("lon"), (int, float)) else None,
            "vehicle": m.get("vehicle") if isinstance(m.get("vehicle"), str) else None,
        })
    return sorted(out, key=lambda x: x["filmNm"])


def score_event(entry: dict) -> float:
    kind = entry.get("kind")
    if kind == "wx":
        peak = _fact_num(entry, "maxWindKnots", "windKnots") or 0.0
        dur = _fact_num(entry, "hours") or 6.0
        return peak * dur
    return {"climo": 50, "sci": 40, "amp": 30, "project": 30, "zee": 20, "poe": 10, "note": 5, "stop": 1}.get(kind, 0)


def is_sea_chapter(ch: dict) -> bool:
    """Jambe de mer : tout sauf Saint-Maur → La Rochelle."""
    frm = short_name(ch.get("fromName") or "")
    to = short_name(ch.get("toName") or "")
    if re.search(r"saint-?maur", frm, re.I) and re.search(r"rochelle", to, re.I):
        return False
    return True


def bubble_score(
    entry: dict | None,
    *,
    role: str | None = None,
    wind_max_kt: float | None = None,
) -> Optional[int]:
    """Score bulle {1,2,3} depuis le journal. None = pas une bulle."""
    if not isinstance(entry, dict):
        return None
    kind = entry.get("kind")
    event = entry.get("event")
    if role in {"depart", "today", "stop"} or kind in {"stop", "escale", "approche"}:
        return 3
    if kind == "alert-on":
        return 3
    if kind == "zee":
        if event and event != "enter":
            return None
        return 2
    if kind == "wx":
        wind = _fact_num(entry, "maxWindKnots", "windKnots")
        hs = _fact_num(entry, "hs", "maxHs")
        thr = float(wind_max_kt) if wind_max_kt is not None else SKIPPER_GALE_KT
        if (wind is not None and wind >= thr) or (hs is not None and hs >= HS_BUBBLE_M):
            return 3
        return None
    if kind == "amp":
        if event == "exit":
            return None
        return 1
    if kind == "project":
        return 1
    if kind == "sci":
        return 2
    if kind == "climo":
        return 1
    return None


def _event_char_idx(ev: dict, chapter: dict, fact: str) -> int:
    text = chapter.get("text") or ""
    if not text:
        return 0
    name = short_name(ev.get("name") or "")
    for needle in (name, (fact or "")[:24]):
        if needle and len(needle) >= 3 and needle in text:
            return text.index(needle)
    t_a, t_b = _ms(chapter.get("tA")), _ms(chapter.get("tB"))
    t = ev.get("tMs")
    if t_a is not None and t_b is not None and t is not None and t_b > t_a:
        frac = max(0.0, min(1.0, (t - t_a) / (t_b - t_a)))
        return int(round(frac * max(0, len(text) - 1)))
    return 0


def _in_chapter(ev: dict, chapter: dict, last: bool, first: bool = False) -> bool:
    t_a, t_b = _ms(chapter.get("tA")), _ms(chapter.get("tB"))
    t = ev.get("tMs")
    if t is None or t_a is None or t_b is None:
        return False
    dest = chapter.get("toName") or ""
    if ev.get("kind") == "stop" and ev.get("role") not in {"depart", "today"} and dest and same_stop(dest, ev.get("name") or ""):
        return True
    # Arrivée à tB = cette jambe (]tA, tB]), pas le chapitre « départ vers » suivant.
    if first:
        return t_a <= t <= t_b
    return t_a < t <= t_b


def _bubble_payload(ev: dict, chapter: dict, lang: str, prev: dict | None = None) -> dict:
    entry = ev.get("entry") if isinstance(ev.get("entry"), dict) else ev
    score = ev.get("bubbleScore")
    if score not in {1, 2, 3}:
        score = bubble_score(entry, role=ev.get("role"))
    title = short_name(ev.get("name") or "") or (prev or {}).get("title") or entry.get("kind") or ev.get("kind") or ""
    fact = event_sentence({**ev, "name": ev.get("name") or title}, lang).strip()
    if _en(lang):
        fact = str(entry.get("fact_en") or fact or "").strip()
    if not fact and not _en(lang):
        fact = ((prev or {}).get("card") or {}).get("text") or (prev or {}).get("fact") or ""
    char_idx = (prev or {}).get("charIdx")
    if char_idx is None:
        char_idx = _event_char_idx(ev, chapter, fact)
    card = dict((prev or {}).get("card") or _card(entry))
    card["title"] = card.get("title") or title
    # Les anciennes cartes peuvent conserver le texte FR dans card.text. En EN,
    # ne garder que le texte produit dans cette langue (ou fact_en).
    card["text"] = (fact if _en(lang) else (card.get("text") or fact))
    card["kind"] = card.get("kind") or ev.get("kind")
    card["score"] = score
    if not card.get("at"):
        card["at"] = ev.get("t") or entry.get("t")
    return {
        "id": ev.get("id") or (prev or {}).get("id"),
        "charIdx": int(char_idx or 0),
        "kind": ev.get("kind") or card.get("kind"),
        "title": str(title)[:40],
        "fact": fact,
        "score": score,
        "card": card,
    }


def _synthetic_sea_event(chapter: dict, lang: str) -> dict:
    to = short_name(chapter.get("toName") or "")
    frm = short_name(chapter.get("fromName") or "")
    text = chapter.get("text") or ""
    if to:
        raw = {
            "id": f"stop:{to}:{chapter.get('tB')}",
            "kind": "stop",
            "t": chapter.get("tB"),
            "tMs": _ms(chapter.get("tB")),
            "name": to,
            "role": "stop",
            "event": "arrival",
            "entry": {"id": f"stop:{to}:{chapter.get('tB')}", "kind": "stop", "t": chapter.get("tB"), "event": "arrival", "name": to},
        }
        raw["bubbleScore"] = 3
        placed = _bubble_payload(raw, chapter, lang)
        if to in text:
            placed["charIdx"] = text.rfind(to)
        else:
            placed["charIdx"] = max(0, len(text) - 1)
        return placed
    raw = {
        "id": f"stop:{frm}:{chapter.get('tA')}",
        "kind": "stop",
        "t": chapter.get("tA"),
        "tMs": _ms(chapter.get("tA")),
        "name": frm or "mer",
        "role": "depart",
        "event": "departure",
        "entry": {"id": f"stop:{frm}:{chapter.get('tA')}", "kind": "stop", "t": chapter.get("tA"), "event": "departure", "name": frm},
    }
    raw["bubbleScore"] = 3
    placed = _bubble_payload(raw, chapter, lang)
    placed["charIdx"] = 0
    return placed


def collect_bubble_events(
    journal: dict | None,
    packed: dict | None,
    *,
    wind_max_kt: float | None = None,
) -> list[dict]:
    packed = packed or {}
    t0, t_end = packed.get("t0"), packed.get("tEnd")
    out: list[dict] = []
    seen: set[str] = set()

    def push(raw: dict, role: str | None = None) -> None:
        if not isinstance(raw, dict):
            return
        entry = raw.get("entry") if isinstance(raw.get("entry"), dict) else raw
        score = bubble_score(entry, role=role or raw.get("role"), wind_max_kt=wind_max_kt)
        if score is None:
            return
        t = _ms(raw.get("t") or entry.get("t"))
        if t is None:
            return
        if t0 is not None and t < t0:
            return
        if t_end is not None and t > t_end:
            return
        eid = str(raw.get("id") or entry.get("id") or f"{entry.get('kind')}:{entry.get('t')}")
        if not eid or eid in seen:
            return
        seen.add(eid)
        out.append({
            "id": eid,
            "kind": raw.get("kind") or entry.get("kind"),
            "t": raw.get("t") or entry.get("t"),
            "tMs": t,
            "name": short_name(raw.get("name") or entry.get("name") or ""),
            "role": role or raw.get("role"),
            "entry": entry,
            "bubbleScore": score,
        })

    for e in journal_entries(journal):
        if e.get("kind") not in BUBBLE_KINDS:
            continue
        push(e)
    for c in packed.get("candidates") or []:
        push(c, role=c.get("role"))
    out.sort(key=lambda e: (e["tMs"], e["id"]))
    return out


def attach_chapter_events(
    chapters: list[dict],
    packed: dict | None,
    journal: dict | None,
    lang: str = "fr",
    wind_max_kt: float | None = None,
) -> list[dict]:
    """Chaque chapitre porte {charIdx, kind, title, fact, score}. Mer : ≥ 1."""
    pool = collect_bubble_events(journal, packed, wind_max_kt=wind_max_kt)
    n = len(chapters or [])
    for i, ch in enumerate(chapters or []):
        first = i == 0
        last = i == n - 1
        existing = {str(e.get("id")): e for e in (ch.get("events") or []) if e.get("id")}
        placed: list[dict] = []
        seen: set[str] = set()
        for ev in pool:
            if not _in_chapter(ev, ch, last, first):
                continue
            prev = existing.get(str(ev["id"]))
            row = _bubble_payload(ev, ch, lang, prev)
            if row.get("score") not in {1, 2, 3}:
                continue
            eid = str(row.get("id") or "")
            if eid and eid in seen:
                continue
            if eid:
                seen.add(eid)
            placed.append(row)
        if is_sea_chapter(ch) and not placed:
            placed.append(_synthetic_sea_event(ch, lang))
        ch["events"] = sorted(placed, key=lambda e: (int(e.get("charIdx") or 0), str(e.get("id") or "")))
    return chapters


def _cand(entry: dict, *, role: str | None = None, score: float | None = None, name: str | None = None) -> Optional[dict]:
    t_ms = _ms(entry.get("t"))
    if t_ms is None:
        return None
    return {
        "id": str(entry.get("id") or f"{entry.get('kind')}:{entry.get('t')}"),
        "kind": entry.get("kind"),
        "t": entry.get("t"),
        "tMs": t_ms,
        "name": name if name is not None else (entry.get("name") or ""),
        "score": score if score is not None else score_event(entry),
        "role": role,
        "quayDays": _quay(entry),
        "entry": entry,
    }


def film_candidates(
    journal: dict | None,
    marks: list | None,
    clock: dict | None,
    live: dict | None,
    now_ms: int,
) -> dict[str, Any]:
    raw_marks = marks if marks else (clock or {}).get("marks")
    stops = official_dated_stops(raw_marks, clock)
    start = stops[0] if stops else None
    sea = _sea_stop(stops, raw_marks, clock)
    t0 = _ms(OFFICIAL_T0)
    t_end = _ms((live or {}).get("iso")) or now_ms
    out: list[dict] = []
    seen: set[str] = set()

    def push(c: Optional[dict]) -> None:
        if not c or c["id"] in seen:
            return
        seen.add(c["id"])
        out.append(c)

    depart_iso = OFFICIAL_T0
    if _ms(depart_iso) is not None:
        push(_cand({
            "id": "depart", "kind": "stop", "t": depart_iso, "event": "departure",
            "name": short_name((start or {}).get("name") or "Saint-Maur"),
        }, role="depart", score=10_000, name=short_name((start or {}).get("name") or "Saint-Maur")))

    seen_zee: set[Any] = set()
    seen_poe: set[Any] = set()
    seen_sci: set[Any] = set()
    for e in journal_entries(journal):
        if e.get("kind") not in CANDIDATE_KINDS:
            continue
        if e.get("kind") == "zee":
            if e.get("event") and e.get("event") != "enter":
                continue
            key = e.get("mrgid") or e.get("name")
            if not key or key in seen_zee:
                continue
            seen_zee.add(key)
        if e.get("kind") == "amp" and e.get("event") == "exit":
            continue
        if e.get("kind") == "poe":
            key = e.get("poeId") or e.get("name")
            if not key or key in seen_poe:
                continue
            seen_poe.add(key)
        if e.get("kind") == "sci":
            from ici_engine import science_type_key  # noqa: PLC0415
            if not science_type_key(_station_item(e)):
                continue
            key = (e.get("entity") or {}).get("id") if isinstance(e.get("entity"), dict) else e.get("name")
            if not key or key in seen_sci:
                continue
            seen_sci.add(key)
        if e.get("kind") == "stop" and e.get("event") == "departure":
            continue
        t = _ms(e.get("t"))
        if t is None:
            continue
        if t0 is not None and t < t0:
            continue
        if t_end is not None and t > t_end:
            continue
        push(_cand(e, role="stop" if e.get("kind") == "stop" else None))

    for s in stops[1:]:
        t = _ms(s["iso"])
        if t is None or (t_end is not None and t > t_end):
            continue
        if any(
            c["kind"] == "stop" and c.get("role") not in {"depart", "today"}
            and same_stop(c["name"], s["name"]) and abs(c["tMs"] - t) < 3_600_000
            for c in out
        ):
            continue
        push(_cand({
            "id": f"stop:{s['name']}:{s['iso']}", "kind": "stop", "t": s["iso"],
            "event": "arrival", "name": s["name"], "holdHours": s["holdHours"],
            "daysAtQuay": _days(s["holdHours"]),
        }, role="stop", score=1))

    today_iso = (live or {}).get("iso") or (_iso(t_end) if t_end else _iso(now_ms))
    if today_iso:
        push(_cand({
            "id": "today", "kind": "stop", "t": today_iso, "event": "arrival",
            "name": short_name((live or {}).get("fromStop") or ""),
        }, role="today", score=9_000))

    out.sort(key=lambda c: c["tMs"])
    return {"candidates": out, "t0": t0, "tEnd": t_end, "start": start, "sea": sea, "stops": stops}


def _pick_stops(cands: list[dict], max_n: int = 6) -> list[dict]:
    lst = [c for c in cands if c["kind"] == "stop" and c.get("role") not in {"depart", "today"}]
    if len(lst) <= max_n:
        return lst
    first, last = lst[0], lst[-1]
    long = sorted(
        [s for s in lst if s["quayDays"] > 2 and s is not first and s is not last],
        key=lambda s: (-s["quayDays"], s["tMs"]),
    )
    picked: list[dict] = []

    def add(s: dict) -> None:
        if s and all(x["id"] != s["id"] for x in picked):
            picked.append(s)

    add(first)
    add(last)
    for s in long:
        if len(picked) >= max_n:
            break
        add(s)
    for s in lst:
        if len(picked) >= max_n:
            break
        add(s)
    return sorted(picked, key=lambda s: s["tMs"])[:max_n]


def select_film_events(candidates: list[dict], t0: Optional[int], t_end: Optional[int]) -> list[dict]:
    lst = [c for c in candidates if c.get("tMs") is not None]
    span = (t_end or 0) - (t0 or 0)
    gap = span * FILM_GAP_FRAC if span > 0 else 0
    depart = next((c for c in lst if c.get("role") == "depart" or c["id"] == "depart"), None)
    today = next((c for c in lst if c.get("role") == "today" or c["id"] == "today"), None)
    must: list[dict] = []
    if depart:
        must.append(depart)
    must.extend(_pick_stops(lst, 6))
    if today:
        must.append(today)
    selected = list(must)
    must_ids = {m["id"] for m in must}

    def close(ev: dict) -> bool:
        return gap > 0 and any(abs(s["tMs"] - ev["tMs"]) < gap for s in selected)

    scored = [c for c in lst if c["kind"] in SCORED and c["id"] not in must_ids]
    scored.sort(key=lambda c: (-(c.get("score") or 0), KIND_RANK.get(c["kind"], 9), c["tMs"]))
    for ev in scored:
        if len(selected) >= FILM_MAX_EVENTS:
            break
        if close(ev):
            continue
        selected.append(ev)
    if len(selected) < FILM_MIN_EVENTS:
        for ev in scored:
            if len(selected) >= FILM_MIN_EVENTS:
                break
            if any(s["id"] == ev["id"] for s in selected):
                continue
            selected.append(ev)
    return sorted(selected, key=lambda c: c["tMs"])


def _join(parts: list[str], lang: str) -> str:
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    sep = " and " if _en(lang) else " et "
    return f"{', '.join(parts[:-1])}{sep}{parts[-1]}"


def _day_word(n: int, lang: str) -> str:
    if _en(lang):
        return f"{n} day" + ("s" if n > 1 else "")
    return f"{n} jour" + ("s" if n > 1 else "")


def _film_seconds(seconds: Any) -> int:
    """0 = pas de budget. Toute valeur invalide ou négative → 0."""
    try:
        n = int(seconds)
    except (TypeError, ValueError):
        return 0
    return n if n > 0 else 0


def _film_compact_template(seconds: Any) -> bool:
    """Variante 2:30 : ouvertures et arrivées courtes. 3:00 et intégral = gabarit RG6."""
    s = _film_seconds(seconds)
    return 0 < s <= 150


def film_char_budget(seconds: Any) -> int:
    """Plafond en caractères à 15 car./s. 0 = intégral, sans plafond."""
    s = _film_seconds(seconds)
    if s <= 0:
        return 0
    return int(s * FILM_ESTIMATE_CPS)


def film_write_window(seconds: Any) -> Optional[tuple[int, int]]:
    """Fenêtre acceptée du rédigé. None = intégral, pas de rejet de longueur."""
    budget = film_char_budget(seconds)
    if budget <= 0:
        return None
    return int(budget * 0.9), int(budget * 1.1)


def film_priority_tier(seconds: Any) -> int:
    """P2 (2:30), P3 (3:00) ou P4 (intégral)."""
    s = _film_seconds(seconds)
    if s <= 0:
        return FILM_TIER_FULL
    if s <= 150:
        return FILM_TIER_SHORT
    return FILM_TIER_MEDIUM


def film_estimated_seconds(chars: int, cps: float | None = None) -> int:
    """Durée parlée = caractères ÷ débit mesuré ou 15 car./s. Jamais un chiffre inventé."""
    n = int(chars or 0)
    if n <= 0:
        return 0
    rate = float(cps) if cps and float(cps) > 0 else float(FILM_ESTIMATE_CPS)
    return max(1, int(round(n / rate)))


def _best_named_change(rows: list[dict], *, gold_first: bool) -> Optional[dict]:
    usable = [c for c in rows if isinstance(c, dict)]
    if not usable:
        return None

    def gold(c: dict) -> int:
        return 0 if c.get("gold_on") in (True, 1, "1", "true", "True") else 1

    usable.sort(key=lambda c: (
        gold(c) if gold_first else 0,
        change_distance_nm(c) if change_distance_nm(c) is not None else 999.0,
        c.get("tMs") or 0,
    ))
    return usable[0]


def _amp_and_project(amp: list[dict], proj: list[dict]) -> list[dict]:
    """2:30 : une AMP et un projet s'ils existent (plus proche ; projet : gold_on
    d'abord). RC26 : seulement des items qui donneront une phrase — un projet au
    titre anglais que speak_change refuse gaspillait le créneau de la variante."""
    out: list[dict] = []
    picked_amp = _best_named_change([c for c in amp if _would_speak(c)], gold_first=False)
    picked_proj = _best_named_change([c for c in proj if _would_speak(c)], gold_first=True)
    if picked_amp is not None:
        out.append(picked_amp)
    if picked_proj is not None:
        out.append(picked_proj)
    return out


def _tier_route_extras(
    zee: list[dict],
    coast: list[dict],
    amp: list[dict],
    proj: list[dict],
    climo: list[dict],
    stations: list[dict],
    *,
    tier: Optional[int],
) -> list[dict]:
    if tier is None or tier >= FILM_TIER_FULL:
        return zee + coast + amp + proj + climo + stations
    extras = list(zee)
    if tier <= FILM_TIER_SHORT:
        extras.extend(_amp_and_project(amp, proj))
        return extras
    return extras + coast + amp + proj + climo


def _tier_allows_kind(kind: str, tier: Optional[int]) -> bool:
    if tier is None or tier >= FILM_TIER_FULL:
        return True
    k = str(kind or "")
    if k in {"escale", "approche", "zee-enter", "alert-on", "cyclone", "marina", "amp", "project"}:
        return True
    if tier >= FILM_TIER_MEDIUM and k in {"coast", "climo"}:
        return True
    return False


def _facts_with_rounded(change: dict) -> str:
    """Faits + arrondis : filter_numbers accepte le chiffre déclamé."""
    blob = json.dumps(change, ensure_ascii=False, default=str)
    extras: list[str] = []
    for token in re.findall(r"\d+(?:[.,]\d+)?", blob):
        raw = token.replace(",", ".")
        try:
            extras.append(str(int(round(float(raw)))))
        except ValueError:
            continue
    return f"{blob} {' '.join(extras)}"


def _review_legs(review: dict | None) -> list[dict]:
    if not isinstance(review, dict):
        return []
    legs = review.get("legs")
    return [leg for leg in legs if isinstance(leg, dict)] if isinstance(legs, list) else []


def review_leg_for_chapter(review: dict | None, from_name: str, to_name: str) -> dict | None:
    """Jambe de review_official dont from/to sont la fenêtre du chapitre. Sinon silence."""
    frm, to = from_name or "", to_name or ""
    if not frm or not to:
        return None
    legs = _review_legs(review)
    for leg in legs:
        if (
            same_stop(leg.get("from") or "", frm) and same_stop(leg.get("to") or "", to)
        ) or (
            same_stop(leg.get("from") or "", to) and same_stop(leg.get("to") or "", frm)
        ):
            return leg
    # Vol : le bateau repart de Cayenne, la revue date encore Saint-Pierre → dest.
    if _air_stop_key(frm) == "cayenne":
        for leg in legs:
            if same_stop(leg.get("to") or "", to) and _is_air_only_stop(leg.get("from") or ""):
                return leg
    return None


def _window_leg_nm(w: dict) -> Optional[float]:
    """Écart de milles de l'horloge / des marques — même source que plan-review."""
    frm = w.get("from") or {}
    dest = w.get("to") or {}

    def num(row: dict | None, *keys: str) -> Optional[float]:
        for key in keys:
            val = (row or {}).get(key)
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                return float(val)
        return None

    a_nm, b_nm = num(frm, "nm"), num(dest, "nm")
    if a_nm is not None and b_nm is not None and (b_nm - a_nm) > 1:
        return b_nm - a_nm
    # Keep both endpoints on the same odometer when the window mixes scales.
    a_film, b_film = num(frm, "filmNm"), num(dest, "filmNm")
    if a_film is not None and b_film is not None and (b_film - a_film) > 1:
        return b_film - a_film
    a = a_film if b_film is not None else a_nm
    b = b_film if b_film is not None else b_nm
    if b is None and isinstance(w.get("destNm"), (int, float)):
        b = float(w["destNm"])
    if a is None or b is None:
        return None
    gap = b - a
    return gap if gap > 1 else None


def chapter_metrics(w: dict, review: dict | None = None) -> dict[str, Any]:
    """legNm, daysAtSea, plannedKnots : revue d'abord, sinon la même formule que plan-review."""
    to = w.get("toName") or w.get("destName") or ""
    frm = w.get("fromName") or (w.get("from") or {}).get("name") or ""
    leg = review_leg_for_chapter(review, frm, to)
    nm = days = kn = None
    if leg:
        if isinstance(leg.get("legNm"), (int, float)):
            nm = float(leg["legNm"])
        if isinstance(leg.get("daysAtSea"), (int, float)):
            days = float(leg["daysAtSea"])
        if isinstance(leg.get("plannedKnots"), (int, float)):
            kn = float(leg["plannedKnots"])
    if nm is None and not _is_air_window(w):
        nm = _window_leg_nm(w)
    if nm is not None and not _is_road_window(w) and (days is None or kn is None):
        from plan_review import PLANNED_KNOTS, planned_sea_days  # noqa: PLC0415
        if kn is None:
            kn = float(PLANNED_KNOTS)
        if days is None:
            days = planned_sea_days(float(nm), float(kn))
    # La trace dit plus long que le plan (attente météo, escale technique) : on dit
    # les jours de la trace et la moyenne qui en découle — jamais « six jours de mer »
    # entre un départ le 30 juillet et une arrivée le 15 août.
    # Seuil 15 % / 1 jour (et plus 50 %) : Ajaccio → Fort-de-France partait le
    # 4 juin et arrivait le 14 juillet (40 jours) mais se disait « une trentaine
    # de jours, à 8 nœuds ». Une moyenne sous 4 nœuds ne se dit pas : c'est la
    # trace qui s'allonge (détour, calmes), pas la vitesse du bateau.
    span = _clock_sea_days(w)
    slow = False
    if span is not None and nm and isinstance(days, (int, float)) and span > max(days * 1.15, days + 1):
        days = round(span, 1)
        avg = float(nm) / (span * 24.0)
        kn = float(round(avg)) if avg >= FILM_MIN_SPOKEN_AVG_KNOTS else None
        # 10b (tranché le 29/10) : sous 4 nœuds, la durée est celle de l'horloge
        # climatologique (calmes, détour), pas des « jours de mer » du bateau —
        # « 8 393 milles, 96 jours de mer » (3,6 nd) ne se dit plus. Les dates de
        # départ et d'arrivée, elles, restent dites. `daysAtSea` garde la durée
        # (forme « longue traversée ») ; seule la parole la tait.
        slow = kn is None
    return {"legNm": nm, "daysAtSea": days, "plannedKnots": kn, "slowTrace": slow}


def _spoken_metrics_days(metrics: dict, lang: str) -> str:
    """Jours de mer à dire — rien quand la durée vient d'une trace lente (10b)."""
    days = metrics.get("daysAtSea")
    if days is None or metrics.get("slowTrace"):
        return ""
    return spoken_sea_days(days, lang)


FILM_MIN_SPOKEN_AVG_KNOTS = 4.0


def _clock_sea_days(w: dict) -> Optional[float]:
    if _is_air_window(w) or _is_road_window(w) or not w.get("arrived", True):
        return None
    dep, t_b = w.get("departMs"), w.get("tB")
    if not dep or not t_b or t_b <= dep:
        return None
    return (int(t_b) - int(dep)) / 86_400_000.0


def chapter_shape(w: dict, i: int, n: int, metrics: dict | None = None) -> str:
    """Connecteur lié au contenu : first / long / hop / last / ''."""
    if _is_air_window(w) or _is_road_window(w):
        return ""
    metrics = metrics or {}
    # Film arrêté au « now » réel (Mata-Utu, 29 oct.) : le dernier chapitre n'est pas
    # la dernière étape du plan. `_windows` pose `last` ; l'index ne sert qu'à défaut.
    if w.get("last") or ("last" not in w and n and i == n - 1):
        return "last"
    days = metrics.get("daysAtSea")
    nm = metrics.get("legNm")
    if (isinstance(days, (int, float)) and days >= 10) or (
        isinstance(nm, (int, float)) and nm >= 2000
    ):
        return "long"
    if i > 1 and (
        (isinstance(days, (int, float)) and days <= 3)
        or (isinstance(nm, (int, float)) and nm <= 250)
    ):
        return "hop"
    return ""


def spoken_sea_days(days: Any, lang: str = "fr") -> str:
    """Jours de mer arrondis à la voix : 9,5 → « une dizaine de jours de mer »."""
    try:
        d = float(days)
    except (TypeError, ValueError):
        return ""
    en = _en(lang)
    # 41 milles à 8 nœuds (Gustavia → Marigot) font 5 heures : pas « un jour de mer ».
    if d < 0.75:
        return "less than a day at sea" if en else "moins d'un jour de mer"
    if d < 1.5:
        return "one day at sea" if en else "un jour de mer"
    if d < 8:
        n = int(round(d))
        if en:
            return f"{_spoken_int(n, lang)} day{'' if n == 1 else 's'} at sea"
        return f"{_spoken_int(n, lang)} jour{'' if n == 1 else 's'} de mer"
    if d < 12.5:
        return "about ten days at sea" if en else "une dizaine de jours de mer"
    if d < 17.5:
        return "about fifteen days at sea" if en else "une quinzaine de jours de mer"
    if d < 25:
        return "about twenty days at sea" if en else "une vingtaine de jours de mer"
    if d < 35:
        return "about thirty days at sea" if en else "une trentaine de jours de mer"
    if d < 45:
        return "about forty days at sea" if en else "une quarantaine de jours de mer"
    n = int(round(d))
    return f"{n} days at sea" if en else f"{n} jours de mer"


def _opening_nm_label(nm: Any, lang: str) -> str:
    """« 1 820 milles » / « 1,820 miles » — chiffres du plan-review, pas « nm »."""
    try:
        v = int(round(float(nm)))
    except (TypeError, ValueError):
        return ""
    if v <= 0:
        return ""
    if _en(lang):
        return f"{v:,} miles"
    return f"{v:,} milles".replace(",", " ")


def _spoken_days_word(n: int, lang: str) -> str:
    if _en(lang):
        return f"{_spoken_int(n, lang)} day" + ("" if n == 1 else "s")
    return f"{_spoken_int(n, lang)} jour" + ("" if n == 1 else "s")


def _spoken_day_adjective(n: int, lang: str) -> str:
    if _en(lang):
        return f"{_spoken_int(n, lang)}-day"
    return _spoken_days_word(n, lang)


def review_fingerprint(review: dict | None) -> str:
    bits: list[str] = []
    for leg in _review_legs(review):
        pack = leg.get("antiShipping") if isinstance(leg.get("antiShipping"), dict) else {}
        season = leg.get("season") if isinstance(leg.get("season"), dict) else {}
        lanes = ",".join(
            n.strip() for n in (pack.get("lanes") or []) if isinstance(n, str) and n.strip()
        )
        flags = ",".join(
            str(f.get("kind") or "") for f in (leg.get("flags") or []) if isinstance(f, dict)
        )
        bits.append(
            f"{leg.get('from')}|{leg.get('to')}|{lanes}|{season.get('galePct')}|{season.get('cyclones')}|{flags}"
        )
    return hashlib.sha256("\n".join(bits).encode("utf-8")).hexdigest() if bits else ""


def eta_fingerprint(eta: dict | None) -> str:
    stops = (eta or {}).get("stops") if isinstance(eta, dict) else None
    if not isinstance(stops, dict) or not stops:
        return ""
    bits: list[str] = []
    for name in sorted(stops):
        raw = stops[name]
        if not isinstance(raw, dict):
            continue
        bits.append(
            f"{name}|{raw.get('p10')}|{raw.get('p50')}|{raw.get('p90')}|{raw.get('members')}"
        )
    return hashlib.sha256("\n".join(bits).encode("utf-8")).hexdigest() if bits else ""


def _stop_spoken(name: str) -> str:
    """Nom d'escale à la voix : « Nouméa », sans parenthèse de territoire."""
    raw = re.sub(r"\s*\([^)]*\)\s*", " ", short_name(name) or "")
    return re.sub(r"\s+", " ", raw).strip()


def review_plan_stats(review: dict | None) -> dict[str, Any]:
    """Totaux du plan-review : destinations uniques, somme des legNm, destination finale.

    Aucun chiffre inventé : une jambe sans `legNm` n'entre pas dans la somme ;
    sans jambe, `nStops` et `totalNm` restent vides.
    """
    dests: list[str] = []
    seen: set[str] = set()
    total = 0.0
    has_nm = False
    for leg in _review_legs(review):
        to = _stop_spoken(leg.get("to") or "")
        if to:
            key = norm_stop(to)
            if key and key not in seen:
                seen.add(key)
                dests.append(to)
        nm = leg.get("legNm")
        if isinstance(nm, (int, float)) and not isinstance(nm, bool) and float(nm) > 0:
            total += float(nm)
            has_nm = True
    return {
        "nStops": len(dests) if dests else None,
        "totalNm": total if has_nm else None,
        "finalDest": dests[-1] if dests else "",
        "dests": dests,
    }


def _non_air_stop_labels(stops: list | None) -> list[str]:
    """Escales du bateau, dans l'ordre. Halifax et Saint-Pierre restent des escales
    aériennes réelles, mais la liste dite « à venir » ne les reprend pas."""
    out: list[str] = []
    for raw in stops or []:
        if isinstance(raw, dict):
            name = raw.get("name") or raw.get("to") or ""
        else:
            name = str(raw or "")
        label = _stop_spoken(name)
        if not label or _is_air_only_stop(label):
            continue
        if any(same_stop(label, prev) for prev in out):
            continue
        out.append(label)
    return out


def _upcoming_from_route(
    route_stops: list | None,
    current_dest: str,
    arrived: bool,
    review_names: list[str],
) -> list[str] | None:
    """File réelle depuis la position. Une revue qui saute Mata-Utu et Nouméa
    ne les efface pas : ils sont réinsérés, puis les noms de revue encore après."""
    real = _non_air_stop_labels(route_stops)
    if not real or not current_dest:
        return None
    ic = next((i for i, name in enumerate(real) if same_stop(name, current_dest)), None)
    if ic is None:
        return None
    start = ic + 1 if arrived else ic
    tail = list(real[start:])
    for name in review_names:
        if not name or _is_air_only_stop(name):
            continue
        label = _stop_spoken(name)
        if not label or any(same_stop(item, label) for item in tail):
            continue
        # La Rochelle du départ est déjà derrière : le retour, lui, est encore devant.
        tail.append(label)
    return tail


def upcoming_stop_names(
    review: dict | None,
    current_dest: str,
    *,
    arrived: bool = False,
    route_stops: list | None = None,
) -> list[str]:
    """Escales à venir dans l'ordre du plan-review, depuis la dest courante.

    Si la dest courante n'est pas dans la revue, on se tait (rien n'est inventé).
    Les escales avion seules (Halifax…) sont omises : le bateau n'y va pas.
    `route_stops` (marques réelles) réinsère une escale que la revue a sautée.
    """
    dests = [
        name for name in (review_plan_stats(review).get("dests") or [])
        if name and not _is_air_only_stop(name)
    ]
    review_names: list[str] = []
    if dests and current_dest:
        idx = next((i for i, name in enumerate(dests) if same_stop(name, current_dest)), None)
        if idx is not None:
            start = idx + 1 if arrived else idx
            review_names = dests[start:]
    if route_stops:
        filled = _upcoming_from_route(route_stops, current_dest, arrived, review_names)
        if filled is not None:
            return filled
    return review_names


def eta_payload_for_stop(eta: dict | None, name: str) -> dict | None:
    """Entrée du stock eta pour une escale. `members` ≤ 0 → absente (pas de date inventée)."""
    if not isinstance(eta, dict) or not name:
        return None
    stops = eta.get("stops") if isinstance(eta.get("stops"), dict) else {}
    raw = stops.get(name) if name in stops else None
    if not isinstance(raw, dict):
        needle = name.strip().casefold()
        for key, payload in stops.items():
            if not isinstance(payload, dict):
                continue
            if same_stop(key, name) or needle in key.casefold() or key.casefold() in needle:
                raw = payload
                break
    if not isinstance(raw, dict):
        return None
    try:
        members = int(raw.get("members") or 0)
    except (TypeError, ValueError):
        members = 0
    if members <= 0:
        return None
    return raw


def _honest_bookend(text: str, facts: Any, lang: str) -> str:
    filtered, _dropped = filter_numbers(text, facts, spelled=True)
    sentence = (filtered or "").strip()
    if not sentence:
        return ""
    return speak_film_text(sentence, lang)


def _film_open_sentences(
    *,
    start_name: str,
    sea_name: str,
    lang: str,
    display_t0: str | None = None,
    review: dict | None = None,
    compact: bool = False,
) -> list[str]:
    """Ouverture du film (2 phrases) : qui, d'où, par la route, totaux du plan-review.

    Variante 2:30 (`compact`) : UNE phrase (chapitre 0, Saint-Maur → La Rochelle).
    """
    en = _en(lang)
    shown = display_t0 or OFFICIAL_T0
    when = day_month(rebase_iso(OFFICIAL_T0, OFFICIAL_T0, shown), lang, year=True)
    frm = short_name(start_name or "Saint-Maur") or "Saint-Maur"
    sea = short_name(sea_name or "La Rochelle") or "La Rochelle"
    stats = review_plan_stats(review)
    n = stats.get("nStops")
    total = stats.get("totalNm")
    final = short_name(stats.get("finalDest") or "")
    nm_s = _opening_nm_label(total, lang) if total is not None else ""
    n_s = ""
    if isinstance(n, int) and n > 0:
        if n <= 30:
            n_s = f"{_spoken_int(n, lang)} {'stops' if en else 'escales'}"
        else:
            n_s = f"{n} stops" if en else f"{n} escales"
    if en:
        first = f"The Berry-Mappemonde expedition left {frm} on {when} by road to {sea}."
    else:
        first = (
            f"L’expédition Berry-Mappemonde a quitté {frm} le {when} "
            f"par la route jusqu’à {sea}."
        )
    second = ""
    if n_s and nm_s and final:
        second = (
            f"The plan has {n_s} and {nm_s}, through to {final}."
            if en else
            f"Le plan compte {n_s} et {nm_s}, jusqu’à {final}."
        )
    elif n_s and nm_s:
        second = (
            f"The plan has {n_s} and {nm_s}."
            if en else
            f"Le plan compte {n_s} et {nm_s}."
        )
    elif final:
        second = f"The destination is {final}." if en else f"La destination est {final}."
    facts = _facts_with_rounded({
        "t0": shown,
        "officialT0": OFFICIAL_T0,
        "nStops": n,
        "totalNm": int(round(float(total))) if total is not None else None,
        "totalNmLabel": nm_s,
        "finalDest": final,
    })
    out: list[str] = []
    for raw in (first, second):
        if not raw:
            continue
        spoken = _honest_bookend(raw, facts, lang)
        if spoken:
            out.append(spoken)
    if compact:
        return out[:1]
    return out


def _eta_sentence(name: str, eta: dict | None, lang: str) -> str:
    raw = eta_payload_for_stop(eta, name)
    if not raw or not name:
        return ""
    d10 = day_month(raw.get("p10"), lang)
    d50 = day_month(raw.get("p50"), lang)
    d90 = day_month(raw.get("p90"), lang)
    en = _en(lang)
    if d10 and d90:
        return (
            f"Arrival at {name} between {d10} and {d90}."
            if en else
            f"Arrivée à {name} entre le {d10} et le {d90}."
        )
    when = d50 or d10 or d90
    if not when:
        return ""
    return (
        f"Arrival at {name} on {when}."
        if en else
        f"Arrivée à {name} le {when}."
    )


def _upcoming_sentence(names: list[str], lang: str) -> str:
    if not names:
        return ""
    label = ", ".join(names)
    return f"Stops still to come: {label}." if _en(lang) else f"Les escales à venir : {label}."


def _stored_review_and_eta() -> tuple[dict | None, dict | None]:
    """Lit le stock RF2. Absence → (None, None), jamais une valeur inventée."""
    review = eta = None
    try:
        from official_store import payload_of  # noqa: PLC0415
        stored = payload_of("plan_review")
        if isinstance(stored, dict) and stored.get("legs"):
            review = stored
        stored_eta = payload_of("eta")
        if isinstance(stored_eta, dict):
            eta = stored_eta
    except Exception:
        return None, None
    return review, eta


def _lane_crossings(clock: dict | None, t_a: Optional[int], t_b: Optional[int]) -> dict[str, int] | None:
    """{nom de couloir (SHIPPING_LANES, casefold) : premier instant du chapitre
    dans la boîte} — None si l'horloge n'a pas de sommet daté dans la fenêtre
    (on ne filtre pas : les tests et le chemin sans trace gardent la revue)."""
    from shipping_lanes import SHIPPING_LANES  # noqa: PLC0415
    if not isinstance(clock, dict):
        return None
    t0 = _ms(clock.get("t0"))
    out: dict[str, int] = {}
    saw = False
    for v in clock.get("vertices") or []:
        if not isinstance(v, dict) or v.get("vehicle") in {"plane", "land"}:
            continue
        t = _ms(v.get("iso"))
        if t is None and t0 is not None and v.get("tHours") is not None:
            try:
                t = t0 + int(float(v["tHours"]) * 3_600_000)
            except (TypeError, ValueError):
                t = None
        if t is None:
            continue
        if t_a is not None and t < t_a:
            continue
        if t_b is not None and t > t_b:
            continue
        try:
            lat, lon = float(v["lat"]), float(v["lon"])
        except (TypeError, ValueError, KeyError):
            continue
        saw = True
        for lon_min, lat_min, lon_max, lat_max, _w, name in SHIPPING_LANES:
            key = name.casefold()
            if key in out:
                continue
            if lon_min <= lon <= lon_max and lat_min <= lat <= lat_max:
                out[key] = t
    return out if saw else None


def _lane_named_in_chapter(name: str, already: str) -> bool:
    """Un couloir déjà dit (Gibraltar en côte) : on le retire, on ne jette pas Gascogne."""
    blob = str(already or "")
    if not blob:
        return False
    for part in re.findall(r"[A-ZÀ-Ÿ][\w'’\-]{3,}", str(name or "")):
        if part and part in blob:
            return True
    return False


def review_sentences(
    leg: dict | None, lang: str = "fr", crossings: dict[str, int] | None = None,
    already: str = "",
) -> list[str]:
    """Faits de revue fondus dans la route : plus d'annexe « À surveiller / Couloirs ».

    `crossings` (couloir → instant du premier croisement dans le
    chapitre) filtre « La route passe par … » aux seuls bassins que la TRACE du
    chapitre traverse, dans l'ordre de la route — Papeete n'entend plus
    « Atlantique nord » hérité d'une autre portion de la jambe de revue.
    Un nom déjà dit (Gibraltar) est retiré de la liste, les autres
    (Gascogne) restent ; le Pacifique n'est pas une boîte AIS (voir
    `_append_review_sentences`)."""
    if not isinstance(leg, dict):
        return []
    en = _en(lang)
    bits: list[str] = []
    season = leg.get("season") if isinstance(leg.get("season"), dict) else None
    gale = season.get("galePct") if season else None
    cyclones = season.get("cyclones") if season else None
    pack = leg.get("antiShipping") if isinstance(leg.get("antiShipping"), dict) else None
    raw_lanes = [
        n.strip() for n in ((pack or {}).get("lanes") or [])
        if isinstance(n, str) and n.strip()
    ] if pack else []
    if crossings is not None:
        raw_lanes = [n for n in raw_lanes if n.casefold() in crossings]
        raw_lanes.sort(key=lambda n: crossings[n.casefold()])
    lanes = [clean_spoken_label(n, lang) for n in raw_lanes]
    lanes = [n for n in lanes if n and not looks_english_title(n)]
    if already:
        lanes = [n for n in lanes if not _lane_named_in_chapter(n, already)]

    if lanes:
        def _lane(n: str) -> str:
            if re.match(r"^(le |la |l['’]|the )", n, re.I):
                return n
            if re.match(r"^(détroit|golfe|canal|cap)\b", n, re.I):
                return f"the {n}" if en else f"le {n}"
            if re.match(r"^(mer|méditerranée|caraïbe|atlantique)\b", n, re.I):
                return n if en else (n if n[:1].islower() else n)
            return n
        names = ", ".join(_lane(n) for n in lanes)
        bits.append(
            f"The route goes through {names}."
            if en else
            f"La route passe par {names}."
        )

    if isinstance(gale, (int, float)):
        n = int(round(float(gale)))
        bits.append(
            f"Gale {n} percent of the time."
            if en else
            f"Coup de vent {n} % du temps."
        )

    if isinstance(cyclones, (int, float)) and cyclones > 0:
        bits.append("Cyclone season." if en else "Saison cyclonique.")

    return bits


def _append_review_sentences(
    bits: list[str],
    review: dict | None,
    window: dict,
    lang: str,
    anchored: list | None = None,
) -> None:
    """Ajoute les phrases de revue au chapitre. Chiffres via filter_numbers."""
    to = window.get("toName") or window.get("destName") or ""
    leg = review_leg_for_chapter(review, window.get("fromName") or "", to)
    if not leg:
        return
    already = " ".join(bits)
    facts = _facts_with_rounded(leg)
    clock = window.get("clock")
    marks = (clock or {}).get("marks")
    t_a, t_b = window.get("tA"), window.get("tB")
    crossings = _lane_crossings(clock, t_a, t_b)
    pack = leg.get("antiShipping") if isinstance(leg.get("antiShipping"), dict) else None
    spoken_lanes = [
        n for n in ((pack or {}).get("lanes") or [])
        if isinstance(n, str) and n.strip()
        and (crossings is None or n.strip().casefold() in crossings)
        and not _lane_named_in_chapter(clean_spoken_label(n, lang), already)
    ]
    lane_ts = [
        crossings[str(n).strip().casefold()]
        for n in spoken_lanes
        if crossings and str(n).strip().casefold() in crossings
    ]
    lane_anchor = min(lane_ts) if lane_ts else None
    for sentence in review_sentences(leg, lang, crossings=crossings, already=already):
        filtered, _dropped = filter_numbers(sentence, facts, spelled=True)
        sentence = (filtered or "").strip()
        if not sentence:
            continue
        if (
            not re.search(r"passe par|goes through", sentence, re.I)
            and any(part and part in already for part in re.findall(r"[A-ZÀ-Ý][\w'-]{3,}", sentence))
        ):
            continue
        bits.append(sentence)
        already = " ".join(bits)
        if anchored is None:
            continue
        if lane_anchor is not None and re.search(r"passe par|goes through", sentence, re.I):
            # La phrase des bassins se dit QUAND la route les croise —
            # jamais collée à l'arrivée (tri des phrases par ancre ensuite).
            anchored.append((sentence, lane_anchor, {"kind": "coast"}))
            continue
        place = ""
        geo = re.search(
            r"((?:détroit|strait|golfe|bay)(?: de| of)? [A-ZÀ-Ÿ][\w'’\-]+)",
            sentence,
            re.I,
        )
        if geo:
            place = geo.group(1)
        else:
            named = re.search(r"\b([A-ZÀ-Ÿ][\w'’\-]{4,})\b", sentence)
            if named and named.group(1).casefold() not in {"route", "the", "gale", "coup", "then", "puis"}:
                place = named.group(1)
        t_ms = _clock_time_near_place(clock, place, t_a, t_b, marks) if place else None
        if t_ms is None:
            t_ms = t_a
        extra = {"place": place, "kind": "coast"} if place else {}
        anchored.append((sentence, t_ms, extra) if extra else (sentence, t_ms))
    pacific_ms = _pacific_arrival_ms(clock, t_a, t_b)
    if pacific_ms is not None and not re.search(r"\b(pacifique|pacific)\b", already, re.I):
        sentence = "The Pacific." if _en(lang) else "Pacifique."
        bits.append(sentence)
        if anchored is not None:
            anchored.append((
                sentence,
                t_b if t_b is not None else pacific_ms,
                {"kind": "coast", "place": "Pacifique"},
            ))


def cyclone_name_year(change: dict) -> tuple[str, str]:
    """Nom + année d'une trace : champ inconnu → vide (silence)."""
    title = short_name(change.get("title") or "")
    fact = str(change.get("fact") or "")
    blob = f"{title} {fact}".strip()
    if not blob or (NAMELESS_CYCLONE.search(blob) and not CYCLONE_YEAR_RE.search(blob)):
        return "", ""
    year = ""
    found = CYCLONE_YEAR_RE.search(blob)
    if found:
        year = found.group(1)
    name = title
    if name.casefold() in GENERIC_CYCLONE or not name:
        named = re.search(
            r"(?:cyclone\s+)?([A-ZÀ-Ý][\w\-']+)\s*\((?:19|20)\d{2}\)",
            fact, re.I,
        )
        if named:
            name = named.group(1)
        else:
            named = re.search(r"(?:cyclone\s+)([A-ZÀ-Ý][\w\-']+)", fact, re.I)
            name = named.group(1) if named else ""
    if name.casefold() in GENERIC_CYCLONE:
        name = ""
    return name, year


def _parse_dist_num(raw: str) -> Optional[float]:
    cleaned = (raw or "").replace("\u00a0", "").replace(" ", "")
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        left, right = cleaned.split(",", 1)
        cleaned = left + right if len(right) == 3 and left.isdigit() else f"{left}.{right}"
    try:
        return float(cleaned)
    except ValueError:
        return None


def round_spoken_distances(text: str, lang: str = "fr") -> str:
    """Distances à la voix : entier, unité en toutes lettres, jamais « nm »."""

    def repl(m: re.Match) -> str:
        v = _parse_dist_num(m.group("num"))
        if v is None:
            return m.group(0)
        return _nm_label(int(round(v)), lang)

    return DIST_UNIT_RE.sub(repl, text or "")


def round_spoken_decimals(text: str) -> str:
    """Aucune décimale déclamée (Hs, kn) : on arrondit à l'entier."""

    def repl(m: re.Match) -> str:
        raw = m.group(0).replace(",", ".")
        try:
            return str(int(round(float(raw))))
        except ValueError:
            return m.group(0)

    return DECIMAL_RE.sub(repl, text or "")


_EN_WATERS_CANON: Optional[dict[str, str]] = None
_EN_WATERS_RE: Optional[re.Pattern[str]] = None
_RC53_EN_WATERS = (
    "French", "Italian", "Moroccan", "Madeira", "Martinique", "Guadeloupe",
)


def _en_waters_canon() -> dict[str, str]:
    """Exonymes EN de la table (adj / nom) → casse canonique. RC53."""
    global _EN_WATERS_CANON, _EN_WATERS_RE
    if _EN_WATERS_CANON is None:
        canon: dict[str, str] = {}
        for row in toponyms.territories():
            for key in ("adj_en", "en"):
                val = str(row.get(key) or "").strip()
                if val and "water" not in val.casefold():
                    canon[val.casefold()] = val
        for extra in _RC53_EN_WATERS:
            canon.setdefault(extra.casefold(), extra)
        names = sorted((n for n in canon if n), key=len, reverse=True)
        alt = "|".join(re.escape(n) for n in names)
        _EN_WATERS_CANON = canon
        _EN_WATERS_RE = re.compile(rf"\b(?:{alt})\s+waters\b", re.I) if alt else re.compile(r"(?!x)x")
    return _EN_WATERS_CANON


def fix_en_waters_casing(text: str) -> str:
    """« french waters » → « French waters ». La forme déjà capitale ne bouge pas.

    Filet à la lecture : `thin_chapter_dates` mettait en minuscule la
    tête de phrase après « Then, » — on rétablit le nom propre sans rebuild.
    """
    blob = text or ""
    if not blob:
        return blob
    _en_waters_canon()
    rx = _EN_WATERS_RE
    if rx is None:
        return blob

    def repl(m: re.Match) -> str:
        raw = m.group(0)
        head = re.sub(r"\s+waters$", "", raw, flags=re.I)
        canon = (_EN_WATERS_CANON or {}).get(head.casefold())
        return f"{canon} waters" if canon else raw

    return rx.sub(repl, blob)


def speak_film_text(text: str, lang: str = "fr") -> str:
    """Texte du film : distances arrondies, unités parlées, pas de décimale."""
    spoken = round_spoken_distances(text or "", lang)
    spoken = expand_spoken_units(spoken, lang)
    spoken = round_spoken_decimals(spoken)
    spoken = scrub_spoken(spoken)
    if _en(lang):
        spoken = fix_en_waters_casing(spoken)
    return spoken


def _nm_label(nm: Any, lang: str) -> str:
    """Distance déclamée : « 1 820 milles nautiques », jamais de décimale ni « nm »."""
    try:
        v = int(round(float(nm or 0)))
    except (TypeError, ValueError):
        return ""
    if _en(lang):
        unit = "nautical mile" if v == 1 else "nautical miles"
        return f"{v:,} {unit}"
    unit = "mille nautique" if v == 1 else "milles nautiques"
    return f"{v:,} {unit}".replace(",", " ")


def event_sentence(ev: dict, lang: str = "fr", display_t0: str | None = None) -> str:
    en = _en(lang)
    e = ev.get("entry") or ev
    shown = display_t0 or OFFICIAL_T0
    when = day_month(rebase_iso(e.get("t") or ev.get("t"), OFFICIAL_T0, shown), lang)
    name = short_name(e.get("name") or ev.get("name") or "")
    if ev.get("role") == "depart":
        frm = name or "Saint-Maur"
        d = day_month(rebase_iso(e.get("t"), OFFICIAL_T0, shown), lang, year=True)
        # Pas de seaName figé : la dest de CETTE fenêtre est « départ vers X ».
        sea = short_name(ev.get("seaName") or ev.get("toName") or "")
        if sea:
            return (
                f"The Berry-Mappemonde expedition left {frm} on {d} and took the road to {sea}."
                if en else
                f"L’expédition Berry-Mappemonde a quitté {frm} le {d} et a pris la route vers {sea}."
            )
        return (
            f"The Berry-Mappemonde expedition left {frm} on {d}."
            if en else
            f"L’expédition Berry-Mappemonde a quitté {frm} le {d}."
        )
    if ev.get("role") == "today":
        place = name
        head = "Today" if en else "Aujourd’hui"
        if place:
            return f"{head}, the boat is at {place}." if en else f"{head}, le bateau est à {place}."
        return ""
    if ev.get("kind") == "stop":
        quay = _quay(e)
        sights = e.get("sights") or (e.get("facts") or {}).get("sights") or []
        named = [s if isinstance(s, str) else (s or {}).get("name") for s in sights][:2]
        named = [s for s in named if s]
        extra = f" {_join(named, lang)}." if named else ""
        q = f", {_day_word(quay, lang)} {'in port' if en else 'à quai'}" if quay else ""
        return (f"Stopover in {name} on {when}{q}.{extra}" if en else f"Escale à {name} le {when}{q}.{extra}")
    if ev.get("kind") == "wx":
        kn = _plain(_fact_num(e, "maxWindKnots", "windKnots"))
        hours = _fact_num(e, "hours")
        hs = _fact_num(e, "hs", "maxHs")
        dur = (f" for {_plain(hours)} hours" if en else f" pendant {_plain(hours)} heures") if hours is not None else ""
        sea = f", Hs {_plain(hs, 0)} m" if hs is not None else ""
        place = ""
        return (
            f"On {when}{place}, the wind rose to {kn} kn{dur}{sea}."
            if en else
            f"Le {when}{place}, le vent est monté à {kn} kn{dur}{sea}."
        )
    if ev.get("kind") == "climo":
        packed = {**e, **ev, "t": e.get("t") or ev.get("t"), "kind": "climo"}
        spoken = climo_sentence(packed, lang)
        if spoken:
            return spoken
        event = e.get("event") or ""
        detail = {
            "calms": " — equatorial calms" if en else " — calmes équatoriaux",
            "cyclone-enter": " — cyclone season" if en else " — saison cyclonique",
        }.get(event, "")
        if not detail:
            return ""
        return (
            f"On {when}, the climate regime changed{detail}."
            if en else
            f"Le {when}, le régime climatique a changé{detail}."
        )
    if ev.get("kind") == "sci":
        spoken = station_spoken_label({**e, **ev}, lang)
        if not spoken:
            return ""
        if when:
            return f"On {when}, {spoken}." if en else f"Le {when}, {spoken}."
        return f"{spoken[0].upper()}{spoken[1:]}."
    if ev.get("kind") == "amp":
        from ici_engine import spoken_amp_name  # noqa: PLC0415
        spoken = spoken_amp_name(name) or name
        if not spoken:
            return ""
        packed = dict(ev)
        if isinstance(e, dict) and e is not ev:
            for key in ("event", "inside", "nm", "traffic", "speed", "facts", "name"):
                if e.get(key) not in (None, ""):
                    packed.setdefault(key, e[key])
        return _amp_film_sentence(spoken, packed, lang, when)
    if ev.get("kind") == "project":
        name = project_spoken_title(name)
        nm = _fact_num(e, "nm")
        dist = spoken_distance(nm, lang) if nm is not None else ""
        if dist:
            return (
                f"On {when}, {dist} away, project {name}."
                if en else
                f"Le {when}, à {dist}, le projet {name}."
            )
        return (
            f"On {when}, project {name}."
            if en else
            f"Le {when}, le projet {name}."
        )
    if ev.get("kind") == "zee":
        if not name or NO_DATA_RE.search(name):
            return ""
        waters = zee_waters_label(name, lang)
        if not waters:
            return ""
        return f"On {when}, {waters}." if en else f"Le {when}, {waters}."
    if ev.get("kind") == "coast":
        return coast_sentence({
            **ev, "title": name, "t": ev.get("t"), "ports": [name] if name else [],
        }, lang)
    if ev.get("kind") == "poe":
        if not name or NO_DATA_RE.search(name):
            return ""
        return f"On {when}, off {name}." if en else f"Le {when}, devant {name}."
    if ev.get("kind") == "note" and e.get("text"):
        note = " ".join(str(e["text"]).split())[:120]
        return (
            f"On {when}, the skipper wrote: « {note} »"
            if en else
            f"Le {when}, le skipper a noté : « {note} »"
        )
    return ""


_EMPTY_WHEN_RE = re.compile(r"^(Le|On) ,\s*")


def _tidy_empty_when(text: str) -> str:
    """event_sentence prefixes « Le {when}, » — drop the comma if the date is missing."""
    s = str(text or "").strip()
    s = _EMPTY_WHEN_RE.sub("", s).strip()
    if s and s[0].islower():
        return s[0].upper() + s[1:]
    return s


def _ici_event_iso(ev: dict) -> str | None:
    payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
    for raw in (ev.get("t"), ev.get("iso"), payload.get("t"), payload.get("iso")):
        if raw:
            return str(raw)
    return None


def phrase_for_ici_event(ev: dict | None, lang: str = "fr") -> str:
    """Same film-script sentence the film would say for this ici() event.

    Maps zee-enter / amp-enter / poe-ahead / … onto event_sentence,
    change_sentence or _arrival_sentence. Empty when the film would stay silent
    (the client template remains the fallback).
    """
    if not isinstance(ev, dict):
        return ""
    typ = str(ev.get("type") or ev.get("event") or "")
    payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
    t = _ici_event_iso(ev)
    name = ev.get("name")

    if typ in {"zee-enter", "zee-ahead"}:
        zee = payload.get("zee") if isinstance(payload.get("zee"), dict) else {}
        spoken = name or zee.get("name")
        film_ev = {
            "kind": "zee",
            "name": spoken,
            "t": t,
            "entry": {"t": t, "name": spoken},
        }
        return _tidy_empty_when(event_sentence(film_ev, lang))

    if typ == "zee-exit":
        return ""

    if typ in {"amp-enter", "amp-ahead"}:
        amp = payload.get("amp") if isinstance(payload.get("amp"), dict) else {}
        spoken = name or amp.get("name")
        try:
            from ici_engine import is_fishing_amp  # noqa: PLC0415
            if is_fishing_amp({"name": spoken, "title": spoken}):
                return ""
        except Exception:
            pass
        nm = amp.get("nm")
        if nm is None:
            nm = payload.get("whenNm") if payload.get("whenNm") is not None else ev.get("whenNm")
        ev_kind = "enter" if typ == "amp-enter" else "nearby"
        entry_code = amp.get("entry") if not isinstance(amp.get("entry"), dict) else None
        film_ev = {
            "kind": "amp",
            "name": spoken,
            "t": t,
            "traffic": amp.get("traffic"),
            "speed": amp.get("speed"),
            "entry": {
                "t": t,
                "name": spoken,
                "event": ev_kind,
                "inside": typ == "amp-enter",
                "facts": {"nm": nm},
                "nm": nm,
                "traffic": amp.get("traffic"),
                "speed": amp.get("speed"),
                "entry": entry_code,
            },
        }
        raw = event_sentence(film_ev, lang)
        if not raw:
            raw = change_sentence({
                "kind": "amp",
                "t": t,
                "title": spoken or "",
                "event": ev_kind,
                "inside": typ == "amp-enter",
                "nm": nm,
                "fact": spoken or "",
                "traffic": amp.get("traffic"),
                "speed": amp.get("speed"),
                "entry": entry_code,
            }, lang)
        return _tidy_empty_when(raw)

    if typ == "poe-ahead":
        poe = payload.get("poe") if isinstance(payload.get("poe"), dict) else {}
        spoken = name or poe.get("name")
        raw = event_sentence({
            "kind": "poe",
            "name": spoken,
            "t": t,
            "entry": {"t": t, "name": spoken},
        }, lang)
        return _tidy_empty_when(raw)

    if typ in {"wind-shift", "wind-gale", "wx-alert"}:
        kn = payload.get("tws")
        if kn is None:
            kn = payload.get("maxWindKnots")
        hs = payload.get("hs")
        raw = event_sentence({
            "kind": "wx",
            "t": t,
            "entry": {
                "t": t,
                "facts": {"maxWindKnots": kn, "hs": hs},
                "maxWindKnots": kn,
            },
        }, lang)
        return _tidy_empty_when(raw)

    if typ in {"stop", "escale", "arrival"}:
        spoken = name or (payload.get("harbour") or {}).get("name") or payload.get("stop") or ""
        stop = {"name": spoken, "iso": t, "holdHours": payload.get("holdHours") or 0}
        raw = _arrival_sentence(stop, lang)
        if not raw:
            raw = change_sentence({"kind": "escale", "t": t, "title": spoken}, lang)
        return _tidy_empty_when(raw)

    return ""


def _iso_for_ici_bag(bag: dict) -> str | None:
    if not isinstance(bag, dict):
        return None
    for key in ("t", "iso"):
        if bag.get(key):
            return str(bag[key])
    at = bag.get("at") if isinstance(bag.get("at"), dict) else {}
    if at.get("iso") or at.get("t"):
        return str(at.get("iso") or at.get("t"))
    lat, lon = at.get("lat"), at.get("lon")
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return None
    try:
        from official_store import payload_of  # noqa: PLC0415
        from ici_engine import haversine_nm  # noqa: PLC0415
        body = payload_of("climo") or {}
        best, best_d = None, 40.0
        for f in body.get("fiches") or []:
            if not isinstance(f, dict) or f.get("lat") is None or not f.get("iso"):
                continue
            d = haversine_nm(float(lat), float(lon), float(f["lat"]), float(f["lon"]))
            if d < best_d:
                best, best_d = f, d
        if best:
            return str(best["iso"])
        clock = body.get("clock") if isinstance(body.get("clock"), dict) else {}
        live = clock.get("live") if isinstance(clock.get("live"), dict) else {}
        return live.get("iso") or clock.get("nowIso") or clock.get("iso")
    except Exception:
        return None


def _amp_phrase_key(amp: dict, kind: str) -> str:
    ident = amp.get("site_id") or amp.get("id") or amp.get("wdpaid") or amp.get("name")
    if ident:
        return f"{kind}:{ident}"
    return kind


def _poe_phrase_key(poe: dict) -> str:
    name = poe.get("name")
    return f"poe-ahead:{name}" if name else "poe-ahead"


def _bilingual_ici_phrase(ev: dict) -> dict[str, str]:
    return {
        "fr": phrase_for_ici_event(ev, "fr"),
        "en": phrase_for_ici_event(ev, "en"),
    }


def attach_ici_film_phrases(bag: dict | None, *, t: str | None = None) -> dict | None:
    """Copy of the ici bag plus filmPhrases { key: {fr, en} } from film_script.

    Served on GET /ici (no new route). Does not mutate the cached pearl.
    """
    if not isinstance(bag, dict):
        return bag
    out = dict(bag)
    iso = t or _iso_for_ici_bag(out)
    phrases: dict[str, dict[str, str]] = {}

    zee = out.get("zee") if isinstance(out.get("zee"), dict) else None
    if zee and (zee.get("name") or zee.get("mrgid")):
        ev = {"type": "zee-enter", "name": zee.get("name"), "t": iso, "payload": {"zee": zee}}
        pair = _bilingual_ici_phrase(ev)
        if pair["fr"] or pair["en"]:
            phrases["zee-enter"] = pair
        ahead = {"type": "zee-ahead", "name": zee.get("name"), "t": iso, "payload": {"zee": zee}}
        ahead_pair = _bilingual_ici_phrase(ahead)
        if ahead_pair["fr"] or ahead_pair["en"]:
            phrases["zee-ahead"] = ahead_pair

    for amp in out.get("amp") or []:
        if not isinstance(amp, dict):
            continue
        for kind in ("amp-enter", "amp-ahead"):
            ev = {
                "type": kind,
                "name": amp.get("name"),
                "t": iso,
                "whenNm": amp.get("nm"),
                "payload": {"amp": amp, "whenNm": amp.get("nm")},
            }
            pair = _bilingual_ici_phrase(ev)
            if pair["fr"] or pair["en"]:
                phrases[_amp_phrase_key(amp, kind)] = pair

    for poe in out.get("poe") or []:
        if not isinstance(poe, dict) or not poe.get("name"):
            continue
        ev = {
            "type": "poe-ahead",
            "name": poe.get("name"),
            "t": iso,
            "whenNm": poe.get("nm"),
            "payload": {"poe": poe},
        }
        pair = _bilingual_ici_phrase(ev)
        if pair["fr"] or pair["en"]:
            phrases[_poe_phrase_key(poe)] = pair

    out["filmPhrases"] = phrases
    return out


def _departure_iso(stop: dict) -> Optional[str]:
    t = _ms(stop.get("iso"))
    if t is None:
        return None
    return _iso(t + int(float(stop.get("holdHours") or 0) * 3_600_000))


def _stop_from_mark(m: dict) -> dict:
    film = m.get("filmNm") if m.get("filmNm") is not None else m.get("nm")
    return {
        "name": m.get("name") or "",
        "iso": m.get("iso"),
        "filmNm": float(film or 0),
        "nm": float(m["nm"]) if isinstance(m.get("nm"), (int, float)) else float(film or 0),
        "holdHours": float(m.get("holdHours") or 0),
        "lat": m.get("lat") if isinstance(m.get("lat"), (int, float)) else None,
        "lon": m.get("lon") if isinstance(m.get("lon"), (int, float)) else None,
        "kind": m.get("kind"),
        "vehicle": m.get("vehicle"),
    }


def _inject_episode_stops(stops: list[dict], clock: dict | None) -> list[dict]:
    """Halifax aller/retour, Saint-Pierre, Cayenne de retour — isos des marques d'horloge."""
    out = [_stop_from_mark(s) if "iso" in s or "name" in s else dict(s) for s in (stops or [])]

    def has_near(name: str, iso: Any, hours: float = 6.0) -> bool:
        t = _ms(iso)
        if t is None:
            return False
        for s in out:
            if not same_stop(s.get("name") or "", name):
                continue
            st = _ms(s.get("iso"))
            if st is not None and abs(st - t) < hours * 3_600_000:
                return True
        return False

    def add_row(row: dict) -> None:
        name = str(row.get("name") or "").strip()
        if not name or _ms(row.get("iso")) is None:
            return
        if has_near(name, row.get("iso")):
            return
        out.append(_stop_from_mark(row))

    for m in ((clock or {}).get("marks") or []):
        if not isinstance(m, dict):
            continue
        if _air_stop_key(m.get("name") or "") in {"halifax", "saint-pierre", "cayenne"}:
            add_row(m)
    cayenne = next((s for s in out if _air_stop_key(s.get("name") or "") == "cayenne"), None)
    cayenne_name = (cayenne or {}).get("name") or "Cayenne (Guyane)"
    verts = [v for v in ((clock or {}).get("vertices") or []) if isinstance(v, dict)]
    planes = [
        v for v in verts
        if v.get("vehicle") == "plane" and _ms(v.get("iso")) is not None
        and isinstance(v.get("lat"), (int, float)) and isinstance(v.get("lon"), (int, float))
    ]
    planes.sort(key=lambda v: _ms(v["iso"]))
    hub_hit = None
    park_hit = None
    for v in planes:
        d_park = _nm_between(
            (cayenne or {}).get("lat"), (cayenne or {}).get("lon"), v.get("lat"), v.get("lon"),
        )
        if d_park is None and hub_hit is not None:
            d_hub = _nm_between(hub_hit.get("lat"), hub_hit.get("lon"), v.get("lat"), v.get("lon"))
            near_park = d_hub is None or d_hub > 80
        else:
            near_park = d_park is not None and d_park <= 80
        if not near_park and hub_hit is None:
            hub_hit = v
            add_row({
                "name": "Halifax (Nouvelle-Écosse)",
                "iso": v.get("iso"),
                "lat": v.get("lat"),
                "lon": v.get("lon"),
                "filmNm": v.get("filmNm"),
                "nm": v.get("sailNm"),
                "holdHours": 0,
                "kind": "hub",
                "vehicle": "plane",
            })
        elif near_park:
            park_hit = v
            add_row({
                "name": cayenne_name,
                "iso": v.get("iso"),
                "lat": v.get("lat"),
                "lon": v.get("lon"),
                "filmNm": v.get("filmNm"),
                "nm": v.get("sailNm"),
                "holdHours": 0,
                "vehicle": "plane",
            })
    if hub_hit and park_hit:
        hub_t = _ms(hub_hit.get("iso"))
        park_t = _ms(park_hit.get("iso"))
        ret = None
        for v in verts:
            t = _ms(v.get("iso"))
            if t is None or hub_t is None or park_t is None:
                continue
            if t <= hub_t + 6 * 3_600_000 or t >= park_t:
                continue
            d = _nm_between(hub_hit.get("lat"), hub_hit.get("lon"), v.get("lat"), v.get("lon"))
            if d is not None and d <= 80:
                ret = v
        if ret is not None:
            add_row({
                "name": "Halifax (Nouvelle-Écosse)",
                "iso": ret.get("iso"),
                "lat": ret.get("lat"),
                "lon": ret.get("lon"),
                "filmNm": ret.get("filmNm"),
                "nm": ret.get("sailNm"),
                "holdHours": 0,
                "kind": "hub",
            })
    out.sort(key=lambda s: (
        _ms(s.get("iso")) if _ms(s.get("iso")) is not None else 10**15,
        float(s.get("filmNm") if s.get("filmNm") is not None else s.get("nm") or 0),
    ))
    return out


def _annotate_episode_windows(
    windows: list[dict],
    *,
    clock: dict | None,
    marks: list | None,
    moments: list | None,
    lang: str,
) -> list[dict]:
    boat = _side_boat_spoken(clock, marks, moments, lang)
    for w in windows or []:
        if _is_side_window(w):
            w["sideBoat"] = boat
    return windows


def _windows(stops: list[dict], t0: int, t_end: int, clock: dict | None = None) -> list[dict]:
    pts = _inject_episode_stops(
        list(stops or [{"name": "Saint-Maur", "iso": _iso(t0), "filmNm": 0}]),
        clock,
    )
    # A « via » point is route geometry, not an arrival. Keeping it as a
    # chapter boundary splits one Halifax ↔ Saint-Pierre hop into fragments.
    pts = [point for point in pts if str(point.get("kind") or "").casefold() != "via"]
    pts.sort(key=lambda s: (
        _ms(s.get("iso")) if _ms(s.get("iso")) is not None else 10**15,
        float(s.get("filmNm") if s.get("filmNm") is not None else s.get("nm") or 0),
    ))
    out: list[dict] = []

    def pack(
        frm: dict,
        to: dict | None,
        t_a: int,
        t_b: int,
        dest_name: str,
        arrived: bool,
        last: bool,
        mode: str,
        return_ms: Optional[int],
    ) -> dict:
        vehicle = {"air": "plane", "road": "land", "sail": "main"}.get(mode, "main")
        if _is_side_leg(frm.get("name") or "", dest_name):
            vehicle = "side"
        return {
            "id": f"leg-{len(out)}",
            "from": frm,
            "to": to if arrived else None,
            "tA": t_a,
            "tB": t_b,
            "fromName": frm.get("name") or "",
            "toName": dest_name if arrived else "",
            "destName": dest_name,
            "destNm": (to.get("nm") if isinstance((to or {}).get("nm"), (int, float)) else (to or {}).get("filmNm")) if to else None,
            "arrived": arrived,
            "last": last,
            "vehicle": vehicle,
            "mode": mode,
            "clock": clock,
            "returnMs": return_ms,
            "fromLat": frm.get("lat"),
            "fromLon": frm.get("lon"),
            "toLat": (to or {}).get("lat"),
            "toLon": (to or {}).get("lon"),
        }

    stay_idx = 0
    dest_i = 1
    stay_ready_ms: Optional[int] = None
    while dest_i < len(pts):
        frm = pts[stay_idx]
        t_a = _ms(frm.get("iso")) if frm.get("iso") else (t0 if stay_idx == 0 else None)
        if t_a is None:
            dest_i += 1
            continue
        if stay_ready_ms is not None and stay_ready_ms > t_a:
            t_a = stay_ready_ms
        if t_a >= t_end:
            break
        probe = pts[dest_i]
        mode = _classify_window_mode(frm, probe, clock, t_a, _ms(probe.get("iso")) or t_end)
        named_i = dest_i
        last_i = dest_i
        to = pts[named_i]
        last_stop = pts[last_i]
        dest_ms = _ms(to["iso"]) if to else None
        last_ms = _ms(last_stop.get("iso")) if last_stop else dest_ms
        arrived = dest_ms is not None and dest_ms <= t_end
        dest_name = (to.get("name") or "") if to else ""
        raw_b = last_ms if last_ms is not None else t_end
        t_b = min(raw_b if raw_b is not None else t_end, t_end)
        return_ms = None
        if t_b <= t_a:
            # Iso égaux (Saint-Maur forcé à T0, La Rochelle le 15 mai à la même
            # heure) : plancher 1 s — `_iso` tronque à la seconde ; 1 ms
            # donnait tA == tB et filmPlan jetait le chapitre 0.
            t_b = t_a + 1000
        out.append(pack(
            frm, to, t_a, t_b, dest_name, arrived,
            dest_i >= len(pts) - 1 and last_i >= len(pts) - 1,
            mode, return_ms,
        ))
        stay_idx = dest_i
        stay_ready_ms = t_b
        dest_i += 1
        if not to or (dest_ms is not None and dest_ms >= t_end):
            break
    if not out and t_end > t0:
        mode = _classify_window_mode(pts[0], None, clock, t0, t_end)
        out.append(pack(
            pts[0], None, t0, t_end, "", False, True, mode, None,
        ))
        out[0]["fromLat"] = None
        out[0]["fromLon"] = None
    for i, w in enumerate(out):
        if i == 0:
            continue
        prev = out[i - 1]
        if (
            _is_air_window(prev)
            and _air_stop_key(_window_dest_name(prev)) == "cayenne"
            and _air_stop_key(w.get("fromName") or "") == "cayenne"
            and not _is_air_window(w)
        ):
            w["resumeAfterAir"] = True
    return out


def _window_owns(w: dict, ev: dict, i: int) -> bool:
    dest = w.get("toName") or ""
    if ev.get("kind") == "stop" and ev.get("role") not in {"depart", "today"} and dest and same_stop(dest, ev.get("name") or ""):
        return True
    if i == 0:
        return ev["tMs"] >= w["tA"] and ev["tMs"] <= w["tB"]
    return ev["tMs"] > w["tA"] and ev["tMs"] <= w["tB"]


def _assign(events: list[dict], windows: list[dict]) -> list[list[dict]]:
    buckets: list[list[dict]] = [[] for _ in windows]
    for ev in events:
        idx = next((i for i, w in enumerate(windows) if _window_owns(w, ev, i)), None)
        if idx is None:
            idx = len(windows) - 1 if ev.get("role") == "today" else 0
        buckets[idx].append(ev)
    return buckets


def _chapter_dest(w: dict) -> dict | None:
    dest = w.get("to") if (w.get("to") or {}).get("name") else None
    return dest


def _air_place_spoken(name: str, lang: str) -> str:
    key = _air_stop_key(name)
    if key == "saint-pierre":
        return "Saint-Pierre and Miquelon" if _en(lang) else "Saint-Pierre-et-Miquelon"
    if key == "cayenne":
        return "Cayenne"
    if key == "halifax":
        return "Halifax"
    stripped = re.sub(r"\s*\([^)]*\)\s*", " ", short_name(name))
    return " ".join(stripped.split())


_SIDE_BOAT_KEYS = ("boat", "boatName", "vessel", "vesselName", "yacht", "ship", "sideBoat")


def _looks_named_side_boat(val: str) -> bool:
    s = " ".join(str(val or "").split())
    if len(s) < 2 or len(s) > 80:
        return False
    if re.search(r"berry|mappemonde|catamaran|second voilier|second sailing", s, re.I):
        return False
    return True


def _side_boat_spoken(
    clock: dict | None,
    marks: list | None,
    moments: list | None,
    lang: str,
) -> str:
    """Nom du second bateau s'il existe dans les données ; sinon « un second voilier »."""
    pool: list[dict] = []
    for src in (marks or []):
        if isinstance(src, dict):
            pool.append(src)
    for src in ((clock or {}).get("marks") or []):
        if isinstance(src, dict):
            pool.append(src)
    for row in moments or []:
        if not isinstance(row, dict):
            continue
        pool.append(_moment_leg(row))
        moment = row.get("moment") if isinstance(row.get("moment"), dict) else {}
        if isinstance(moment, dict):
            pool.append(moment)
    for src in pool:
        for key in _SIDE_BOAT_KEYS:
            val = src.get(key)
            if isinstance(val, str) and _looks_named_side_boat(val):
                return val.strip()
    return "a second sailing boat" if _en(lang) else "un second voilier"


def _window_span_days(w: dict) -> Optional[float]:
    """Jours de la fenêtre du chapitre (tA → tB), pas le cumul du voyage."""
    def as_ms(v: Any) -> Optional[float]:
        if isinstance(v, bool):
            return None
        if isinstance(v, (int, float)):
            return float(v)
        parsed = _ms(v)
        return float(parsed) if parsed is not None else None

    a, b = as_ms(w.get("tA")), as_ms(w.get("tB"))
    if a is None or b is None or b <= a:
        return None
    return (b - a) / 86_400_000.0


def _hop_nm_cap(window_days: Optional[float]) -> float:
    """Au-delà de 1,5 × (8 kn sur la fenêtre), c'est l'odomètre du voyage."""
    if isinstance(window_days, (int, float)) and not isinstance(window_days, bool) and window_days > 0:
        return float(window_days) * 8.0 * 24.0 * 1.5
    return 1500.0


def _same_odometer(nm: float, row: dict | None) -> bool:
    for key in ("nm", "filmNm"):
        val = (row or {}).get(key)
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            if abs(float(val) - nm) <= max(1.0, abs(nm) * 0.01):
                return True
    return False


def _side_scale_gap(w: dict) -> Optional[float]:
    """Écart de la jambe sur une seule échelle. filmNm et nm ne se soustraient pas."""
    frm = w.get("from") or {}
    dest = w.get("to") or {}

    def num(row: dict | None, key: str) -> Optional[float]:
        val = (row or {}).get(key)
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            return float(val)
        return None

    def gap(a: Optional[float], b: Optional[float]) -> Optional[float]:
        if a is None or b is None:
            return None
        d = b - a
        return d if d > 1 else None

    a_nm, b_nm = num(frm, "nm"), num(dest, "nm")
    a_film, b_film = num(frm, "filmNm"), num(dest, "filmNm")
    sail, film = gap(a_nm, b_nm), gap(a_film, b_film)

    def copied(nm: Optional[float], filmv: Optional[float]) -> bool:
        return nm is not None and filmv is not None and abs(nm - filmv) < 0.2

    if sail is not None and film is not None and copied(a_nm, a_film) != copied(b_nm, b_film):
        return film if film < sail else sail
    return sail if sail is not None else film


def _side_scale_disagrees(nm: Any, scale: Optional[float]) -> bool:
    """Vrai si le chiffre dit n'est pas l'écart d'une seule échelle (filmNm ou nm)."""
    if not isinstance(nm, (int, float)) or isinstance(nm, bool):
        return False
    if not isinstance(scale, (int, float)) or isinstance(scale, bool):
        return False
    return abs(float(nm) - float(scale)) > max(1.0, abs(float(scale)) * 0.02)


def _review_hop_trusted(
    w: dict, review: dict | None, nm: Any, cap: float, dest: dict,
) -> bool:
    """La revue porte les milles de cette jambe, sous le plafond, pas l'odomètre."""
    if not isinstance(review, dict):
        return False
    if not isinstance(nm, (int, float)) or isinstance(nm, bool):
        return False
    frm = w.get("fromName") or (w.get("from") or {}).get("name") or ""
    to = w.get("toName") or w.get("destName") or (dest or {}).get("name") or ""
    leg = review_leg_for_chapter(review, frm, to)
    if not isinstance(leg, dict):
        return False
    raw = leg.get("legNm")
    if not isinstance(raw, (int, float)) or isinstance(raw, bool):
        return False
    if abs(float(nm) - float(raw)) > 0.6:
        return False
    if float(nm) > cap:
        return False
    if _same_odometer(float(nm), dest) and float(nm) > 1500:
        return False
    return True


def _side_hop_metrics(w: dict, review: dict | None) -> dict[str, Any]:
    """Milles et jours de Halifax ↔ Saint-Pierre. Jamais le cumul du voyage."""
    chosen = review if isinstance(review, dict) else None
    metrics = dict(chapter_metrics(w, chosen))
    window_days = _window_span_days(w)
    cap = _hop_nm_cap(window_days)
    nm = metrics.get("legNm")
    dest = w.get("to") if isinstance(w.get("to"), dict) else {}
    scale = _side_scale_gap(w)
    voyage = isinstance(nm, (int, float)) and not isinstance(nm, bool) and (
        float(nm) > cap or (_same_odometer(float(nm), dest) and float(nm) > 1500)
    )
    mixed = not _review_hop_trusted(w, chosen, nm, cap, dest) and _side_scale_disagrees(nm, scale)
    if voyage or mixed or not isinstance(nm, (int, float)) or isinstance(nm, bool):
        hop = scale
        if hop is None or hop > cap:
            hop = _nm_between(
                (w.get("from") or {}).get("lat"), (w.get("from") or {}).get("lon"),
                (dest or {}).get("lat"), (dest or {}).get("lon"),
            )
            if hop is not None and hop > cap:
                hop = None
        metrics["legNm"] = hop
        metrics["daysAtSea"] = None
    days = metrics.get("daysAtSea")
    if window_days and (
        not isinstance(days, (int, float)) or isinstance(days, bool)
        or float(days) > max(window_days * 1.5, window_days + 2)
    ):
        metrics["daysAtSea"] = window_days
    elif (
        not isinstance(days, (int, float)) or isinstance(days, bool)
    ) and isinstance(metrics.get("legNm"), (int, float)) and not isinstance(metrics.get("legNm"), bool):
        from plan_review import PLANNED_KNOTS, planned_sea_days  # noqa: PLC0415
        metrics["daysAtSea"] = planned_sea_days(float(metrics["legNm"]), float(PLANNED_KNOTS))
    return metrics


def _side_opening_sentence(
    w: dict, *, lang: str, display_t0: str | None = None, review: dict | None = None,
) -> str:
    """Ouverture Halifax → Saint-Pierre (et retour) à bord du second bateau."""
    en = _en(lang)
    origin = short_name(w.get("fromName") or (w.get("from") or {}).get("name") or "")
    dest = _window_dest_name(w)
    if not origin or not dest:
        return ""
    boat = w.get("sideBoat") or (
        "a second sailing boat" if en else "un second voilier"
    )
    chosen = review if isinstance(review, dict) else (
        w.get("review") if isinstance(w.get("review"), dict) else None
    )
    metrics = _side_hop_metrics(w, chosen)
    nm = _opening_nm_label(metrics.get("legNm"), lang)
    days = spoken_sea_days(metrics.get("daysAtSea"), lang) if metrics.get("daysAtSea") is not None else ""
    stats = ", ".join(x for x in (nm, days) if x)
    dep_ms = _window_depart_ms(w)
    when = ""
    if dep_ms:
        when = day_month(rebase_iso(_iso(int(dep_ms)), OFFICIAL_T0, display_t0 or OFFICIAL_T0), lang)
    outbound = _air_stop_key(dest) == "saint-pierre"
    if en:
        verb = "boards" if outbound else "sails again on"
        if not outbound and boat == "a second sailing boat":
            boat = "the second sailing boat"
        body = f"in {origin}, the crew {verb} {boat} for {dest}"
        head = f"On {when}, {body}." if when else f"{body[0].upper()}{body[1:]}."
        return f"{head} {stats[0].upper() + stats[1:]}." if stats else head
    verb = "embarque sur" if outbound else "reprend"
    if not outbound and boat == "un second voilier":
        # Retour : c'est le même bateau qu'à l'aller — « reprend le second voilier »,
        # pas « reprend un second voilier » (tournure relevée au chapitre 8).
        boat = "le second voilier"
    body = f"à {origin}, l'équipage {verb} {boat} pour {dest}"
    if when:
        head = f"Le {when}, {body}."
    else:
        head = f"À {origin}, l'équipage {verb} {boat} pour {dest}."
    if stats:
        return f"{head} {stats[0].upper() + stats[1:]}."
    return head


def _side_hop_stats_label(w: dict, review: dict | None, lang: str) -> str:
    metrics = _side_hop_metrics(w, review if isinstance(review, dict) else None)
    nm = _opening_nm_label(metrics.get("legNm"), lang)
    days = spoken_sea_days(metrics.get("daysAtSea"), lang) if metrics.get("daysAtSea") is not None else ""
    return ", ".join(x for x in (nm, days) if x)


def _window_from_side_chapter(
    chapter: dict, clock: dict | None, marks: list | None,
) -> dict | None:
    """Fenêtre Halifax ↔ Saint-Pierre à partir du chapitre déjà servi et des marques."""
    frm_name = chapter.get("fromName") or ""
    to_name = chapter.get("toName") or ""
    if not _is_side_leg(frm_name, to_name):
        return None
    rows = [
        row for row in list(marks or []) + list((clock or {}).get("marks") or [])
        if isinstance(row, dict)
    ]

    def nearest(name: str, iso: Any) -> dict | None:
        t = _ms(iso)
        best = None
        best_dt = None
        for row in rows:
            if not same_stop(str(row.get("name") or ""), name):
                continue
            rt = _ms(row.get("iso"))
            if t is None or rt is None:
                if best is None:
                    best = row
                continue
            dt = abs(rt - t)
            if best_dt is None or dt < best_dt:
                best, best_dt = row, dt
        return best

    a = nearest(frm_name, chapter.get("tA"))
    b = nearest(to_name, chapter.get("tB"))
    if not a or not b:
        return None
    fa, fb = _stop_from_mark(a), _stop_from_mark(b)
    t_a = _ms(chapter.get("tA")) or _ms(fa.get("iso"))
    t_b = _ms(chapter.get("tB")) or _ms(fb.get("iso"))
    if t_a is None or t_b is None or t_b <= t_a:
        return None
    return {
        "from": fa,
        "to": fb,
        "fromName": fa.get("name") or frm_name,
        "toName": fb.get("name") or to_name,
        "destName": fb.get("name") or to_name,
        "tA": t_a,
        "tB": t_b,
        "vehicle": "side",
    }


_HOP_STATS_RE = re.compile(
    r"(?:\d{1,3}(?:[ \u00a0\u202f,]\d{3})+|\d{1,6})\s*(?:miles|milles)"
    r"(?:\s*,\s*[^.]{0,80}?(?:days at sea|day at sea|jours de mer|jour de mer))?",
    re.I,
)


def repair_side_hop_plan(
    plan: dict | None,
    *,
    clock: dict | None = None,
    marks: list | None = None,
    review: dict | None = None,
    lang: str = "en",
) -> dict | None:
    """Le snapshot déjà servi dit les milles de la jambe, pas l'odomètre du voyage.

    Ne réécrit que la clause « N milles, M jours » d'un chapitre Halifax ↔ Saint-Pierre.
    """
    if not isinstance(plan, dict):
        return plan
    chapters = plan.get("chapters")
    if not isinstance(chapters, list):
        return plan
    changed = False
    out: list = []
    for chapter in chapters:
        if not isinstance(chapter, dict):
            out.append(chapter)
            continue
        window = _window_from_side_chapter(chapter, clock, marks)
        text = str(chapter.get("text") or "")
        if window is None or not text:
            out.append(chapter)
            continue
        stats = _side_hop_stats_label(window, review, lang)
        match = _HOP_STATS_RE.search(text) if stats else None
        if not match:
            out.append(chapter)
            continue
        current = re.sub(r"\s+", " ", match.group(0)).strip()
        wanted = re.sub(r"\s+", " ", stats).strip()
        if current.casefold() == wanted.casefold():
            out.append(chapter)
            continue
        new_text = text[:match.start()] + stats + text[match.end():]
        if new_text == text:
            out.append(chapter)
            continue
        out.append({**chapter, "text": new_text})
        changed = True
    if not changed:
        return plan
    copied = dict(plan)
    copied["chapters"] = out
    copied["chars"] = script_chars(out)
    return copied


def _resume_after_episode(w: dict, *, lang: str, display_t0: str | None = None) -> str:
    """Reprise du catamaran à Cayenne — destination = prochaine marque, jamais un lieu inventé."""
    dest = _window_dest_name(w)
    if not dest:
        return ""
    en = _en(lang)
    dep_ms = _window_depart_ms(w)
    when = ""
    if dep_ms:
        when = day_month(rebase_iso(_iso(int(dep_ms)), OFFICIAL_T0, display_t0 or OFFICIAL_T0), lang)
    metrics = chapter_metrics(w, w.get("review") if isinstance(w.get("review"), dict) else None)
    nm = _opening_nm_label(metrics.get("legNm"), lang)
    # Cayenne → Papeete : milles, jours de mer et moyenne, comme toute étape
    # (la reprise ne disait que « 6 671 milles »).
    stats = [nm] if nm else []
    days = _spoken_metrics_days(metrics, lang) if nm else ""
    if days:
        stats.append(days)
        kn = metrics.get("plannedKnots")
        if isinstance(kn, (int, float)) and not isinstance(kn, bool):
            kn_i = int(round(float(kn)))
            stats.append(f"at {kn_i} knots on average" if en else f"à {kn_i} nœuds de moyenne")
    extra = f". {', '.join(stats)}" if stats else ""
    if en:
        body = f"the catamaran puts to sea again, departure for {dest}{extra}"
        return f"On {when}, {body}." if when else f"{body[0].upper()}{body[1:]}."
    body = f"le catamaran reprend la mer, départ vers {dest}{extra}"
    return f"Le {when}, {body}." if when else f"{body[0].upper()}{body[1:]}."


def _air_window_sentence(w: dict, *, lang: str, display_t0: str | None = None) -> str:
    """Une phrase de vol : destination Halifax (pas Saint-Pierre). Attente dite une fois, à l'aller."""
    origin_raw = (w.get("from") or {}).get("name") or w.get("fromName") or ""
    dest_raw = _window_dest_name(w) or w.get("destName") or ""
    origin = _air_place_spoken(origin_raw, lang)
    dest = _air_place_spoken(dest_raw, lang)
    if not origin or not dest:
        return ""
    en = _en(lang)
    wait = _air_stop_key(origin_raw) == "cayenne"
    dep_ms = _window_depart_ms(w) or w.get("departMs") or w.get("tA")
    when = ""
    if dep_ms:
        when = day_month(rebase_iso(_iso(int(dep_ms)), OFFICIAL_T0, display_t0 or OFFICIAL_T0), lang)
    if en:
        head = f"The crew flies from {origin} to {dest}"
        if wait:
            head = f"{head}; the catamaran waits at {origin}"
        if when:
            return f"On {when}, {head[0].lower() + head[1:]}."
        return f"{head}."
    # « s'envole d'Halifax », pas « de Halifax » (élision devant h muet / voyelle),
    # et la même apostrophe que « l'équipage s'envole » (pas « s'envole d’Halifax »).
    head = f"l'équipage s'envole {_de(origin).replace('’', chr(39))} pour {dest}"
    if wait:
        head = f"{head} ; le catamaran attend à {origin}"
    if when:
        return f"Le {when}, {head}."
    return f"{head[0].upper() + head[1:]}."


def _air_sentence(w: dict, *, i: int, lang: str, display_t0: str | None = None) -> str:
    return _air_window_sentence(w, lang=lang, display_t0=display_t0)


def _close_position(w: dict, live: dict | None, lang: str, now_ms: Optional[int] = None) -> str:
    """Où est le bateau aujourd'hui — horloge / live, jamais une position inventée.

    `now_ms` : instant réel du film. Un film qui va jusqu'au bout du plan alors
    que l'arrivée finale est encore à venir ne dit pas « Aujourd'hui, le bateau
    est à La Rochelle » (faux le 29 oct. 2026) ; avec une horloge décalée dont
    l'arrivée est passée, la phrase reste.
    """
    en = _en(lang)
    live = live or {}
    if now_ms is not None and not live.get("atStop") and w.get("arrived"):
        arr = _ms(((_chapter_dest(w) or {}).get("iso"))) or w.get("tB")
        if arr is not None and int(now_ms) < int(arr):
            return ""
    at_quay = short_name(live.get("atStop") or "")
    if at_quay:
        return f"Today, the boat is at {at_quay}." if en else f"Aujourd’hui, le bateau est à {at_quay}."
    dest = short_name(w.get("destName") or w.get("toName") or "")
    sail = live.get("sailNm") if live.get("sailNm") is not None else live.get("filmNm")
    dest_nm = w.get("destNm")
    if dest and not w.get("arrived") and isinstance(sail, (int, float)) and isinstance(dest_nm, (int, float)) and dest_nm > sail:
        left = _nm_label(dest_nm - sail, lang)
        return (f"Today, the boat is at sea, {left} from {dest}." if en
                else f"Aujourd’hui, le bateau est en mer, à {left} {_de(dest)}.")
    if dest and not w.get("arrived"):
        return f"Today, the boat is at sea, bound for {dest}." if en else f"Aujourd’hui, le bateau est en mer, en route vers {dest}."
    place = short_name(live.get("fromStop") or live.get("name") or "")
    if not place and w.get("arrived"):
        place = short_name(w.get("toName") or "")
    if not place:
        place = short_name(w.get("fromName") or "")
    if not place:
        return ""
    return f"Today, the boat is at {place}." if en else f"Aujourd’hui, le bateau est à {place}."


def _close_sentence(
    w: dict,
    live: dict | None,
    lang: str,
    review: dict | None = None,
    eta: dict | None = None,
    route_stops: list | None = None,
    now_ms: Optional[int] = None,
) -> str:
    """Fin du film (2–3 phrases) : aujourd'hui, ETA du stock, escales à venir du plan-review."""
    live = live or {}
    first = _close_position(w, live, lang, now_ms=now_ms)
    at_quay = short_name(live.get("atStop") or "")
    dest = short_name(w.get("destName") or w.get("toName") or "")
    next_name = _stop_spoken(at_quay or dest)
    arrived = bool(at_quay or w.get("arrived"))
    eta_s = _eta_sentence(next_name, eta, lang) if next_name else ""
    upcoming = upcoming_stop_names(
        review, next_name, arrived=arrived, route_stops=route_stops,
    )
    up_s = _upcoming_sentence(upcoming, lang)
    raw = " ".join(bit for bit in (first, eta_s, up_s) if bit)
    if not raw:
        return ""
    sail = live.get("sailNm") if live.get("sailNm") is not None else live.get("filmNm")
    dest_nm = w.get("destNm")
    left = None
    if isinstance(sail, (int, float)) and isinstance(dest_nm, (int, float)) and dest_nm > sail:
        left = dest_nm - sail
    eta_raw = eta_payload_for_stop(eta, next_name) if next_name else None
    facts = _facts_with_rounded({
        "live": live,
        "destNm": dest_nm,
        "sailNm": sail,
        "leftNm": left,
        "leftLabel": _nm_label(left, lang) if left is not None else "",
        "eta": eta,
        "etaStop": eta_raw,
        "upcoming": upcoming,
        "review": review_plan_stats(review),
        "first": first,
    })
    return _honest_bookend(raw, facts, lang)


def _harbor_differs_from_city(harbor: str, dest_name: str) -> bool:
    """True si le port / la marina a un nom distinct de la ville d'escale."""
    if not (harbor or "").strip() or not (dest_name or "").strip():
        return False
    city = _stop_spoken(dest_name)
    core = re.sub(r"^(le |la |l['’]|the )", "", harbor.strip(), flags=re.I)
    core = re.sub(
        r"^(port |marina |harbour |harbor )(d['’]|de |of )?",
        "",
        core,
        flags=re.I,
    )
    core = re.sub(r" marina$", "", core, flags=re.I).strip()
    if not core:
        return False
    if same_stop(core, city):
        return False
    city_cf = city.casefold()
    core_cf = core.casefold()
    if city_cf and (city_cf in core_cf or core_cf in city_cf):
        return False
    return True


def _harbor_spoken(name: str, dest: str, kind: str, lang: str) -> str:
    """« le port d'Ajaccio » / « la marina Les Minimes ». Titre anglais → port de l'escale."""
    en = _en(lang)
    raw = (name or "").strip()
    if looks_english_title(raw) or not raw or _GENERIC_HARBOR_RE.search(raw):
        raw = (dest or "").strip()
        kind = "port"
    if not raw:
        return ""
    if re.match(r"^(le |la |l['’]|the )(port|marina|harbour|harbor)\b", raw, re.I):
        return raw
    if re.match(r"^(port|marina|harbour|harbor)\b", raw, re.I):
        return raw if not en else raw
    marina = kind == "marina" or bool(re.search(r"marina|minimes", raw, re.I))
    if marina:
        if en:
            raw = re.sub(r"^(?:de |du |des |d['’])", "", raw, flags=re.I).strip()
        return f"the {raw} marina" if en else f"la marina {raw}"
    return f"the port of {raw}" if en else f"le port {_de(raw)}"


def _moored_phrase(harbor: str, lang: str) -> str:
    if not harbor:
        return ""
    if _en(lang):
        return f"moored at {harbor}"
    if harbor.startswith("le "):
        return f"amarré au {harbor[3:]}"
    if harbor.startswith("la "):
        return f"amarré à {harbor}"
    if harbor.startswith("l’") or harbor.startswith("l'"):
        return f"amarré à {harbor}"
    return f"amarré à {harbor}"


def _hold_phrase(days: int, chapter_i: int, lang: str) -> str:
    """Durée dite une fois, formulations qui tournent — jamais « 3 jours à quai »."""
    if not days:
        return ""
    spoken = _spoken_days_word(int(days), lang)
    if _en(lang):
        variants = (
            f"a {_spoken_day_adjective(int(days), lang)} stopover",
            f"a stay of {spoken}",
            f"{spoken} at the harbour",
            f"{spoken} alongside",
        )
    else:
        variants = (
            f"{spoken} d'escale",
            f"escale de {spoken}",
            f"{spoken} au port",
            f"on reste {spoken}",
        )
    return variants[int(chapter_i) % len(variants)]


def _item_place(item: dict) -> tuple[str, str]:
    kind = str(item.get("kind") or "")
    if item.get("title") or item.get("fact"):
        name = change_place_name(item)
        if name:
            return name, kind or "port"
    return short_name(item.get("name") or ""), kind or "port"


_HARBOR_OF_TOWN_RE = re.compile(
    r"^(?:le\s+)?port\s+(?:de\s+la\s+|de\s+l['’]|de\s+|du\s+|d['’])(?P<town>.+)$",
    re.I,
)


def _harbor_names_other_town(name: str, dest_name: str) -> bool:
    """Vrai si le port porte le nom d'une AUTRE commune que l'escale
    (« Port de Saint-Martin-de-Ré » pour La Rochelle). Les marinas nommées
    autrement (« marina Étang Z'Abricots », « Port Brunelet ») ne sont pas visées."""
    found = _HARBOR_OF_TOWN_RE.match((name or "").strip())
    if not found:
        return False
    town = norm_stop(found.group("town"))
    dest = norm_stop(dest_name or "")
    if not town or not dest:
        return False
    return not (town in dest or dest in town)


def _arrival_harbor(items: list | None, dest: dict | None, lang: str) -> str:
    """Marina / port le plus proche de l'escale ; sinon le port d'arrivée nommé."""
    dest = dest or {}
    dest_name = short_name(dest.get("name") or "")
    dest_lat, dest_lon = dest.get("lat"), dest.get("lon")
    scored: list[tuple[tuple, str, str]] = []
    for item in items or []:
        kind = str(item.get("kind") or "")
        if kind not in {"marina", "port", "poe"}:
            continue
        name, k = _item_place(item)
        if not name or looks_english_title(name):
            continue
        dist = _nm_between(dest_lat, dest_lon, item.get("lat"), item.get("lon"))
        near = bool(dest_name) and (
            dest_name.casefold() in name.casefold() or name.casefold() in dest_name.casefold()
        )
        if not near and (dist is None or dist > 25.0):
            continue
        if not near and _harbor_names_other_town(name, dest_name):
            # N13 : « Port de Saint-Martin-de-Ré » est le port d'une autre commune
            # (île de Ré) — on n'arrive pas à La Rochelle « amarré à » lui.
            continue
        t = item.get("tMs") or _ms(item.get("t")) or 0
        scored.append(((0 if near else 1, dist if dist is not None else 999.0, -int(t)), name, k))
    if scored:
        scored.sort(key=lambda row: row[0])
        return _harbor_spoken(scored[0][1], dest_name, scored[0][2], lang)
    if dest_name:
        return _harbor_spoken(dest_name, dest_name, "port", lang)
    return ""


def _compact_sea_opening(
    w: dict,
    *,
    lang: str,
    display_t0: str | None = None,
    review: dict | None = None,
    include_date: bool = True,
) -> str:
    """Ouverture 2:30 : une phrase — date, destination, milles, jours. Sans redite."""
    dest_name = _stop_spoken(_window_dest_name(w))
    if not dest_name:
        return ""
    en = _en(lang)
    metrics = chapter_metrics(w, review)
    nm_val = metrics.get("legNm")
    days_val = metrics.get("daysAtSea")
    nm = _opening_nm_label(nm_val, lang) if nm_val is not None else ""
    days = _spoken_metrics_days(metrics, lang)
    dep_ms = _window_depart_ms(w)
    when = ""
    if include_date and dep_ms:
        when = day_month(rebase_iso(_iso(dep_ms), OFFICIAL_T0, display_t0 or OFFICIAL_T0), lang)
    stats = ", ".join(x for x in (nm, days) if x)
    if en:
        if when and stats:
            raw = f"On {when}, departure for {dest_name}: {stats}."
        elif when:
            raw = f"On {when}, departure for {dest_name}."
        elif stats:
            raw = f"Departure for {dest_name}: {stats}."
        else:
            raw = f"Departure for {dest_name}."
    elif when and stats:
        raw = f"Le {when}, départ vers {dest_name} : {stats}."
    elif when:
        raw = f"Le {when}, départ vers {dest_name}."
    elif stats:
        raw = f"Départ vers {dest_name} : {stats}."
    else:
        raw = f"Départ vers {dest_name}."
    facts = _facts_with_rounded({
        "iso": _iso(dep_ms) if dep_ms else None,
        "when": when,
        "dest": dest_name,
        "legNm": int(round(float(nm_val))) if isinstance(nm_val, (int, float)) else None,
        "nmLabel": nm,
        "daysAtSea": days_val,
        "daysLabel": days,
    })
    return _honest_bookend(raw, facts, lang)


def _opening_sentence(
    w: dict,
    *,
    i: int,
    lang: str,
    display_t0: str | None = None,
    heading_deg: Any = None,
    review: dict | None = None,
    n: int = 0,
    include_date: bool = True,
    compact: bool = False,
) -> str:
    """Ouverture d'étape : date, port, cap, dest, milles, jours, vitesse — gabarit § 4.

    `compact` (2:30) : une phrase, sans quitte / nœuds / longue traversée.
    """
    dest_name = _window_dest_name(w)
    if _is_air_window(w):
        return _air_window_sentence(w, lang=lang, display_t0=display_t0)
    if _is_side_window(w):
        return _side_opening_sentence(w, lang=lang, display_t0=display_t0, review=review)
    if w.get("resumeAfterAir"):
        return _resume_after_episode(w, lang=lang, display_t0=display_t0)
    if not dest_name:
        return ""
    if compact and not _is_road_window(w):
        return _compact_sea_opening(
            w, lang=lang, display_t0=display_t0, review=review, include_date=include_date,
        )
    en = _en(lang)
    origin = short_name(
        w.get("fromName") or (w.get("from") or {}).get("name") or ""
    )
    metrics = chapter_metrics(w, review)
    shape = chapter_shape(w, i, n or 0, metrics)
    dep_ms = _window_depart_ms(w)
    when = ""
    if include_date and dep_ms:
        when = day_month(rebase_iso(_iso(dep_ms), OFFICIAL_T0, display_t0 or OFFICIAL_T0), lang)
    cap = ""
    if not _is_road_window(w):
        cap = heading_phrase(heading_deg if heading_deg is not None else w.get("headingDeg"), lang)
    dest_for = dest_name
    if shape == "long":
        dest_for = f"the long crossing to {dest_name}" if en else f"la longue traversée vers {dest_name}"
    boat = "Berry-Mappemonde"
    if _is_road_window(w):
        km = ""
        gap = metrics.get("legNm")
        if gap and not compact:
            km = _km_label(gap, lang)
        if en:
            body = f"{boat} leaves {origin} by road for {dest_name}" if origin else f"{boat} takes the road to {dest_name}"
            if km:
                body = f"{body}. {km[0].upper()}{km[1:]}" if km else body
        else:
            body = (
                f"{boat} quitte {origin} par la route pour {dest_name}"
                if origin else
                f"{boat} prend la route pour {dest_name}"
            )
            if km:
                body = f"{body}. {km[0].upper()}{km[1:]}"
        if when:
            return f"On {when}, {body}." if en else f"Le {when}, {body}."
        return f"{body[0].upper()}{body[1:]}."

    stats: list[str] = []
    nm = _opening_nm_label(metrics.get("legNm"), lang)
    days = _spoken_metrics_days(metrics, lang)
    kn = metrics.get("plannedKnots")
    kn_s = ""
    if isinstance(kn, (int, float)) and not isinstance(kn, bool):
        kn_i = int(round(float(kn)))
        kn_s = f"{kn_i} knots on average" if en else f"{kn_i} nœuds de moyenne"
    if nm:
        stats.append(nm)
    if days:
        stats.append(days)
    if kn_s:
        stats.append(kn_s if not days else (f"at {kn_s}" if en else f"à {kn_s}"))
    extra = ""
    if stats:
        # Point, pas « : » : split_short_sentences reboucle sinon sur le même texte.
        extra = ". " + ", ".join(stats)

    hop = ""
    last = ""
    if shape == "hop":
        hop = "from island to island, " if en else "d'île en île, "
    if shape == "last":
        last = "for the last stage, " if en else "pour la dernière étape, "

    if en:
        mid = f", {cap}" if cap else ""
        leave = f"{hop}{last}{boat} leaves {origin}{mid} for {dest_for}{extra}" if origin else f"{hop}{last}{boat} sails for {dest_for}{extra}"
        if when:
            return f"On {when}, {leave}."
        return f"{leave[0].upper()}{leave[1:]}."
    mid = f", {cap}" if cap else ""
    leave = (
        f"{hop}{last}{boat} quitte {origin}{mid} pour {dest_for}{extra}"
        if origin else
        f"{hop}{last}{boat} met le cap sur {dest_for}{extra}"
    )
    if when:
        return f"Le {when}, {leave}."
    return f"{leave[0].upper()}{leave[1:]}."


def _depart_towards(
    w: dict, *, i: int, lang: str, display_t0: str | None = None,
    heading_deg: Any = None,
    review: dict | None = None,
    n: int = 0,
    include_date: bool = True,
    compact: bool = False,
) -> str:
    return _opening_sentence(
        w, i=i, lang=lang, display_t0=display_t0, heading_deg=heading_deg,
        review=review, n=n, include_date=include_date, compact=compact,
    )


_SEA_VEHICLES = frozenset({"main", "boat", "side"})


def _first_sea_leg_sentence(
    w: dict,
    *,
    clock: dict | None,
    sea_name: str,
    lang: str,
    display_t0: str | None = None,
    review: dict | None = None,
    n: int = 0,
    compact: bool = False,
) -> Optional[tuple[str, int]]:
    """Chapitre 0 « par la route » : la part en mer depuis le port de mise à l'eau.

    Le premier sommet d'horloge en mer de la fenêtre donne l'appareillage, ses
    milles cumulés donnent l'écart jusqu'à l'arrivée (rien d'inventé). Rend
    (phrase, instant d'appareillage) ou None si l'horloge n'a pas de mer.
    """
    sea = short_name(sea_name or "")
    dest_name = _window_dest_name(w)
    if not sea or not dest_name or same_stop(sea, dest_name):
        return None
    t_a, t_b = w.get("tA"), w.get("tB")
    leave = None
    for v in (clock or {}).get("vertices") or []:
        if not isinstance(v, dict) or v.get("vehicle") not in _SEA_VEHICLES:
            continue
        t = _ms(v.get("iso"))
        if t is None or (t_a is not None and t < t_a) or (t_b is not None and t >= t_b):
            continue
        leave = (t, v)
        break
    if leave is None:
        return None
    t_leave, v = leave
    a_nm = v.get("sailNm") if isinstance(v.get("sailNm"), (int, float)) else v.get("filmNm")
    sw = {
        **w,
        "fromName": sea,
        "from": {"name": sea, "lat": v.get("lat"), "lon": v.get("lon"),
                 "nm": a_nm if isinstance(a_nm, (int, float)) else None},
        "fromLat": v.get("lat"),
        "fromLon": v.get("lon"),
        "mode": "sail",
        "vehicle": "main",
        "tA": t_leave,
        "departMs": t_leave,
        "clock": clock,
    }
    to = dict(w.get("to") or {})
    if isinstance(w.get("destNm"), (int, float)):
        to["nm"] = float(w["destNm"])
    sw["to"] = to
    head = _opening_sentence(
        sw, i=1, lang=lang, display_t0=display_t0,
        heading_deg=_leg_heading_deg([], t_leave, clock=clock, leg_nm=_window_leg_nm(sw)),
        review=review, n=n, include_date=True, compact=compact,
    )
    if not head:
        return None
    t0 = w.get("tA")
    if t0 is not None and _utc_day({"tMs": t0}) == _utc_day({"tMs": t_leave}):
        rx = _LEAD_DATE_EN_RE if _en(lang) else _LEAD_DATE_FR_RE
        body = rx.sub("", head, count=1)
        if body != head and body:
            lead = "The same day, " if _en(lang) else "Le jour même, "
            head = lead + body
    return head, t_leave


def _arrival_sentence(
    stop: dict | None,
    lang: str,
    display_t0: str | None = None,
    clock: dict | None = None,
    harbor: str = "",
    chapter_i: int = 0,
    compact: bool = False,
    final: bool = False,
) -> str:
    if not stop or not stop.get("name") or _ms(stop.get("iso")) is None:
        return ""
    en = _en(lang)
    if compact:
        when = day_month(rebase_iso(stop["iso"], OFFICIAL_T0, display_t0 or OFFICIAL_T0), lang)
        dest = _stop_spoken(stop.get("name") or "")
        name = short_name(stop.get("name") or "") or dest
        extra = ""
        if harbor and _harbor_differs_from_city(harbor, dest):
            extra = f", at {harbor}" if en else f", à {harbor}"
        if en:
            if name and when:
                raw = f"Arrival at {name} on {when}{extra}."
            elif name:
                raw = f"Arrival at {name}{extra}."
            else:
                raw = f"Arrival on {when}{extra}." if when else (f"Arrival{extra}." if extra else "")
        else:
            if name and when:
                raw = f"Arrivée à {name} le {when}{extra}."
            elif name:
                raw = f"Arrivée à {name}{extra}."
            elif when:
                raw = f"Arrivée le {when}{extra}."
            else:
                raw = f"Arrivée{extra}." if extra else ""
        if not raw:
            return ""
        facts = _facts_with_rounded({
            "iso": stop.get("iso"),
            "when": when,
            "dest": dest,
            "harbor": harbor,
        })
        return _honest_bookend(raw, facts, lang)
    name = short_name(stop["name"])
    when = day_month(rebase_iso(stop["iso"], OFFICIAL_T0, display_t0 or OFFICIAL_T0), lang)
    quay = _days(_quay_hours_for_arrival(stop, clock))
    moored = _moored_phrase(harbor, lang)
    # Arrivée finale : le voyage s'achève, pas d'« Escale de trois jours » avant
    # « Aujourd'hui, le bateau est à La Rochelle ».
    hold = "" if final else _hold_phrase(quay, chapter_i, lang)
    if en:
        head = f"Arrival at {name} on {when}" if when else f"Arrival at {name}"
        if moored:
            head = f"{head}, {moored}"
        if hold:
            head = f"{head}. {hold[0].upper()}{hold[1:]}"
        return f"{head}."
    head = f"Arrivée à {name} le {when}" if when else f"Arrivée à {name}"
    if moored:
        head = f"{head}, {moored}"
    if hold:
        head = f"{head}. {hold[0].upper()}{hold[1:]}"
    return f"{head}."


def _card(entry: dict) -> dict:
    return {
        "id": entry.get("id"),
        "kind": entry.get("kind"),
        "title": entry.get("name") or (entry.get("title") or {}).get("fr") or entry.get("kind"),
        "text": "",
        "facts": entry.get("facts"),
        "entity": entry.get("entity"),
        "at": entry.get("t"),
    }


def _compose(windows: list[dict], buckets: list[list[dict]], *, lang: str, sea_name: str, start_name: str, live: dict | None, display_t0: str | None = None, review: dict | None = None, eta: dict | None = None, seconds: int = 0, route_stops: list | None = None) -> list[dict]:
    chapters: list[dict] = []
    cited: set[str] = set()
    compact = _film_compact_template(seconds)
    dist = ""
    if live:
        dist = _nm_label(live.get("sailNm") if live.get("sailNm") is not None else live.get("filmNm"), lang)

    def push_arrival(
        bits: list[str],
        dest: dict | None,
        clock: dict | None = None,
        harbor: str = "",
        chapter_i: int = 0,
        final: bool = False,
    ) -> None:
        key = norm_stop((dest or {}).get("name") or "")
        sentence = _arrival_sentence(
            dest, lang, display_t0, clock=clock, harbor=harbor, chapter_i=chapter_i,
            compact=compact, final=final,
        )
        if not sentence or not key or key in cited:
            return
        bits.append(sentence)
        cited.add(key)

    for i, w in enumerate(windows):
        bits: list[str] = []
        placed: list[dict] = []
        anchored: list[tuple[str, Optional[int]]] = []
        dest = _chapter_dest(w)
        dest_name = _window_dest_name(w)
        arrived = bool(w.get("arrived")) if "arrived" in w else bool(dest)
        depart_ms = _window_depart_ms(w) or 0

        def finish_chapter() -> None:
            thinned = thin_chapter_dates(bits, lang)
            if len(thinned) == len(bits) and len(anchored) == len(bits):
                anchored[:] = [_retarget_anchor(anchored[j], thinned[j]) for j in range(len(thinned))]
            bits[:] = thinned
            text = speak_film_text(re.sub(r"\s{2,}", " ", " ".join(bits)).strip(), lang)
            if film_opens:
                head = " ".join(film_opens)
                if head and head not in text:
                    text = speak_film_text(f"{head} {text}".strip(), lang)
                    for sent in reversed(film_opens):
                        anchored.insert(0, (sent, w["tA"], {"role": "depart"}))
            if i == len(windows) - 1:
                close = _close_sentence(
                    w, live, lang, review=review, eta=eta, route_stops=route_stops,
                )
                if close and close not in text:
                    text = speak_film_text(f"{text} {close}".strip(), lang)
                    anchored.append((close, w["tB"]))
            chapters.append({
                "id": w["id"],
                "tA": _iso(w["tA"]),
                "tB": _iso(w["tB"]),
                "text": text,
                "anchors": chapter_anchors(text, anchored, w["tA"], w["tB"], lang),
                "_anchorText": text,
                "events": placed,
                "fromName": w.get("fromName") or "",
                "toName": w.get("toName") or "",
                "fromLat": w.get("fromLat"),
                "fromLon": w.get("fromLon"),
                "toLat": w.get("toLat"),
                "toLon": w.get("toLon"),
            })

        film_opens: list[str] = []
        skip_depart = False
        if i == 0:
            film_opens = _film_open_sentences(
                start_name=start_name, sea_name=sea_name, lang=lang,
                display_t0=display_t0, review=review, compact=compact,
            )
            skip_depart = _is_road_window(w) and bool(film_opens)
        if _is_air_window(w):
            head = _depart_towards(
                w, i=i, lang=lang, display_t0=display_t0,
                review=review, n=len(windows), compact=compact,
            )
            if head:
                bits.append(head)
                anchored.append((head, depart_ms or w["tA"], {"role": "depart"}))
            finish_chapter()
            continue

        def speak_ev(ev: dict) -> None:
            if ev.get("kind") == "stop" and ev.get("role") not in {"depart", "today"}:
                return
            if ev.get("role") in {"depart", "today"}:
                return
            if ev.get("kind") == "marina":
                return
            ev_name = short_name(ev.get("name") or "")
            if ev.get("kind") in {"approche", "stop"} and dest_name and ev_name and (
                same_stop(ev_name, dest_name) or dest_name.casefold() in ev_name.casefold()
            ):
                return
            if looks_english_title(ev_name):
                return
            rich = {
                **ev,
                "seaName": dest_name or sea_name,
                "toName": dest_name,
                "distLabel": dist,
                "name": ev.get("name"),
            }
            sentence = event_sentence(rich, lang, display_t0=display_t0).strip()
            if not sentence:
                return
            char_idx = len(" ".join(bits)) + (1 if bits else 0)
            bits.append(sentence)
            entry = ev.get("entry") or {}
            card = _card(entry)
            card["text"] = sentence
            placed.append({"id": ev["id"], "charIdx": char_idx, "card": card})

        sci_keep_id = ""
        sci_here = [ev for ev in buckets[i] if ev.get("kind") == "sci" and station_spoken_label(ev, lang)]
        if sci_here:
            def _sci_nm(ev: dict) -> float:
                raw = _fact_num(ev, "nm")
                if raw is None:
                    raw = _fact_num(ev.get("entry") or {}, "nm")
                return float(raw) if raw is not None else 999.0
            sci_here.sort(key=lambda ev: (_sci_nm(ev), ev.get("tMs") or 0))
            sci_keep_id = str(sci_here[0].get("id") or "")

        if not skip_depart:
            head = _depart_towards(
                w, i=i, lang=lang, display_t0=display_t0,
                heading_deg=_leg_heading_deg(None, depart_ms, clock=w.get("clock")),
                review=review, n=len(windows), include_date=i != 0, compact=compact,
            )
            if head:
                bits.append(head)
                anchored.append((head, depart_ms or w["tA"], {"role": "depart"}))
        spoken_evs = (
            _drop_guiana_equator_changes(buckets[i])
            if _is_saint_pierre_depart(w) else buckets[i]
        )
        for ev in spoken_evs:
            if ev.get("kind") == "sci" and str(ev.get("id") or "") != sci_keep_id:
                continue
            speak_ev(ev)
        _append_review_sentences(bits, review, w, lang, anchored)
        if arrived:
            harbor = _arrival_harbor(buckets[i], dest, lang)
            before = len(bits)
            push_arrival(bits, dest, clock=w.get("clock"), harbor=harbor, chapter_i=i, final=bool(w.get("last")))
            if len(bits) > before:
                dest_place = short_name((dest or {}).get("name") or "")
                anchored.append((bits[-1], w["tB"], {"role": "arrive", "place": dest_place, "kind": "escale"}))
        finish_chapter()
    return chapters


def script_chars(chapters: list[dict]) -> int:
    return sum(len(c.get("text") or "") for c in chapters)


def _journal_moments(journal: dict | None) -> list[dict]:
    if not isinstance(journal, dict):
        return []
    rows = journal.get("moments")
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def allocate_chapter_budgets(
    days: list[float],
    total: int = FILM_BUDGET_CHARS,
    floor: int = FILM_CHAPTER_FLOOR,
) -> list[int]:
    n = len(days)
    if n <= 0:
        return []
    weights = [max(1.0, float(d or 1)) for d in days]
    if n * floor >= total:
        base, rem = divmod(max(total, n), n)
        return [base + (1 if i < rem else 0) for i in range(n)]
    rest = total - n * floor
    total_w = sum(weights) or 1.0
    extra = [int(rest * w / total_w) for w in weights]
    leftover = rest - sum(extra)
    for i in sorted(range(n), key=lambda j: -weights[j]):
        if leftover <= 0:
            break
        extra[i] += 1
        leftover -= 1
    return [floor + e for e in extra]


def _change_t(row: dict) -> Optional[int]:
    return _ms(row.get("t") or ((row.get("moment") or {}).get("t") if isinstance(row.get("moment"), dict) else None))


def _moment_extra_changes(row: dict) -> list[dict]:
    """Faits du Moment (around) : marina, station, AMP, cyclone nommé, culture."""
    moment = row.get("moment") if isinstance(row.get("moment"), dict) else {}
    extras: list[dict] = []
    seen: set[tuple] = set()
    for i, item in enumerate(moment.get("around") or []):
        if not isinstance(item, dict):
            continue
        kind = AROUND_TO_KIND.get(str(item.get("kind") or ""))
        if not kind:
            continue
        title = short_name(item.get("title") or "")
        fact = str(item.get("fact") or title or "").strip()
        if kind == "cyclone":
            name, year = cyclone_name_year({"title": title, "fact": fact})
            if not name:
                continue
            title = name
            fact = f"{name} ({year})" if year else name
        title = extract_named(title, fact, kind) or title
        if not title and not fact:
            continue
        extra = {
            "kind": kind,
            "title": title or fact,
            "fact": fact,
            "score": item.get("score") if item.get("score") in {1, 2, 3} else 2,
            "id": str(item.get("id") or f"around:{row.get('seq')}:{kind}:{i}"),
            "nm": item.get("nm") if isinstance(item.get("nm"), (int, float)) else None,
            "lat": item.get("lat") if isinstance(item.get("lat"), (int, float)) else None,
            "lon": item.get("lon") if isinstance(item.get("lon"), (int, float)) else None,
        }
        if not change_is_speakable(extra):
            continue
        key = (kind, norm_stop(title), fact)
        if key in seen:
            continue
        seen.add(key)
        extras.append(extra)
    return extras


def _ici_dc2_extras(row: dict) -> list[dict]:
    """Mouillage / port d'entrée déjà dans le sac ici — copie, jamais inventée."""
    pair = _row_latlon(row)
    if not pair:
        return []
    try:
        from official_store import ici_bag_near  # noqa: PLC0415
        bag = ici_bag_near(pair[0], pair[1])
    except Exception:
        return []
    if not isinstance(bag, dict):
        return []
    extras: list[dict] = []
    nearby = bag.get("nearby") if isinstance(bag.get("nearby"), dict) else {}
    for i, anc in enumerate(nearby.get("anchorages") or []):
        if not isinstance(anc, dict):
            continue
        name = str(anc.get("name") or "").strip()
        if not name or name.casefold() in GENERIC_ANCHORAGE_NAMES:
            continue
        extra = {
            "kind": "anchorage",
            "title": name,
            "fact": name,
            "score": 2,
            "id": f"ici:anchorage:{row.get('seq')}:{i}",
            "nm": anc.get("nm") if isinstance(anc.get("nm"), (int, float)) else None,
        }
        if change_is_speakable(extra):
            extras.append(extra)
            break
    for i, poe in enumerate(bag.get("poe") or []):
        if not isinstance(poe, dict):
            continue
        name = str(poe.get("name") or "").strip()
        if not name or NO_DATA_RE.search(name):
            continue
        extra = {
            "kind": "poe",
            "title": name,
            "fact": name,
            "score": 2,
            "id": f"ici:poe:{row.get('seq')}:{i}",
            "nm": poe.get("nm") if isinstance(poe.get("nm"), (int, float)) else None,
        }
        if change_is_speakable(extra):
            extras.append(extra)
            break
    extras.extend(_ici_dc3_extras(row, bag))
    return extras


def _ici_dc3_extras(row: dict, bag: dict | None = None) -> list[dict]:
    """Balise / câble / profondeur / piraterie / satellite du sac ici — copie."""
    if bag is None:
        pair = _row_latlon(row)
        if not pair:
            return []
        try:
            from official_store import ici_bag_near  # noqa: PLC0415
            bag = ici_bag_near(pair[0], pair[1])
        except Exception:
            return []
    extras: list[dict] = []
    for extra in _dc3_from_ici_bag(bag, seq=row.get("seq")):
        extra = {
            **extra,
            "id": extra.get("id") or f"ici:{extra.get('kind')}:{row.get('seq')}",
        }
        if change_is_speakable(extra):
            extras.append(extra)
    return extras


def _dest_culture_changes(dest: dict | None) -> list[dict]:
    """Faits de fiche d'escale (sights) : culture nommée, jamais inventée."""
    if not isinstance(dest, dict):
        return []
    sights = dest.get("sights") or (dest.get("facts") or {}).get("sights") or []
    out: list[dict] = []
    for i, item in enumerate(sights[:2]):
        if isinstance(item, str):
            name, extra = item.strip(), ""
        elif isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            extra = str(item.get("fact") or item.get("text") or "").strip()
        else:
            continue
        body = extra or name
        if not body:
            continue
        out.append({
            "kind": "culture",
            "title": name or body,
            "fact": body,
            "id": f"culture:{dest.get('name')}:{i}",
            "score": 1,
        })
    return out


def _starting_zee_from_moments(
    moments: list[dict], t_a: int, t_b: int, first: bool,
) -> Optional[dict]:
    """ZEE déjà occupée au départ de la jambe (pas un enter) — Gascogne / Pertuis.

    Calculée depuis le premier moment de mer de la fenêtre, jamais une constante."""
    for row in moments:
        if not isinstance(row, dict) or _moment_is_air(row):
            continue
        t = _change_t(row)
        if t is None:
            continue
        # Y compris tA : l'appareillage de la jambe (non-première) est à tA,
        # alors que flatten laisse ce moment au chapitre précédent.
        if t < t_a or t > t_b:
            continue
        if first and t >= t_b:
            continue
        moment = row.get("moment") if isinstance(row.get("moment"), dict) else {}
        here = moment.get("here") if isinstance(moment.get("here"), dict) else {}
        zee = here.get("zee") if isinstance(here.get("zee"), dict) else {}
        name = str(zee.get("name") or "").strip()
        if not name or re.search(r"haute mer|high seas", name, re.I):
            continue
        pair = _row_latlon(row)
        extra = {"lat": pair[0], "lon": pair[1]} if pair else {}
        return {
            "id": f"zee-start:{row.get('seq')}:{zee.get('mrgid') or name}",
            "kind": "zee-enter",
            "score": 2,
            "title": name,
            "fact": name,
            "t": row.get("t"),
            "tMs": t,
            **extra,
        }
    return None


def _flatten_changes(moments: list[dict], t_a: int, t_b: int, first: bool) -> list[dict]:
    out: list[dict] = []
    seen: set[tuple] = set()
    for row in moments:
        t = _change_t(row)
        if t is None:
            continue
        if first:
            if t < t_a or t > t_b:
                continue
        elif t <= t_a or t > t_b:
            continue
        raw = list(row.get("changes") or []) + _moment_extra_changes(row) + _ici_dc2_extras(row)
        for i, change in enumerate(raw):
            if not isinstance(change, dict) or not change.get("kind"):
                continue
            title = short_name(change.get("title") or "")
            fact = str(change.get("fact") or "")
            row_change = {
                **change,
                "id": str(change.get("id") or f"{row.get('seq')}:{change.get('kind')}:{i}"),
                "t": row.get("t"),
                "tMs": change.get("tMs") if change.get("tMs") is not None else t,
                "legIdx": row.get("legIdx"),
            }
            pair = _row_latlon(row)
            if pair and row_change.get("lat") is None:
                row_change["lat"], row_change["lon"] = pair
            if not change_is_speakable(row_change):
                continue
            key = (
                str(change.get("kind")),
                norm_stop(change_place_name(row_change) or title),
                fact,
                _zee_basin_from_change(row_change) if str(change.get("kind") or "") == "zee-enter" else "",
            )
            if key in seen:
                continue
            seen.add(key)
            out.append(row_change)
    start_zee = _starting_zee_from_moments(moments, t_a, t_b, first)
    if start_zee:
        key = (
            "zee-enter",
            norm_stop(change_place_name(start_zee) or start_zee.get("title") or ""),
            str(start_zee.get("fact") or ""),
            _zee_basin_from_change(start_zee),
        )
        if key not in seen:
            seen.add(key)
            out.append(start_zee)
    out.sort(key=lambda c: (c["tMs"], str(c.get("id") or "")))
    return out


def _group_changes(changes: list[dict], span_ms: int, clock: dict | None = None) -> list[dict]:
    by_kind: dict[str, list[dict]] = {}
    for change in changes:
        by_kind.setdefault(str(change.get("kind") or ""), []).append(change)
    out: list[dict] = []
    grouped_ids: set[str] = set()
    for kind, group in by_kind.items():
        if len(group) < 3:
            continue
        if kind in {
            "alert-on", "marina", "port", "amp", "project", "zee-enter", "coast",
            "climo", "station", "buoy", "poe", "anchorage",
            "aton", "cable", "depth", "piracy", "satellite",
        }:
            # Pas de « 10 alertes », « N ZEE » ni « N stations » : une station qualifiée, jamais un comptage.
            continue
        # Dater au membre le plus proche du bateau ; sinon éclater (RG2 a déjà réduit).
        spoken_ms = group[0].get("tMs")
        member = _closest_member_to_boat(group, clock, spoken_ms)
        if member is None:
            continue
        title = fact = f"{len(group)} {kind}"
        out.append({
            "id": f"group:{kind}:{member.get('id')}",
            "kind": kind,
            "score": max(int(g.get("score") or 0) for g in group),
            "title": title,
            "fact": fact,
            "t": member.get("t"),
            "tMs": member.get("tMs"),
        })
        grouped_ids.update(str(g.get("id")) for g in group)
    gap = span_ms * KIND_GROUP_FRAC if span_ms > 0 else 0
    last_t: dict[str, int] = {}
    for change in changes:
        cid = str(change.get("id") or "")
        if cid in grouped_ids:
            continue
        kind = str(change.get("kind") or "")
        prev = last_t.get(kind)
        if prev is not None and gap > 0 and abs((change.get("tMs") or 0) - prev) < gap:
            continue
        last_t[kind] = int(change.get("tMs") or 0)
        out.append(change)
    out.sort(key=lambda c: (c.get("tMs") or 0, str(c.get("id") or "")))
    return out


def _station_ident(change: dict) -> str:
    """Identité d'une station dite : code de campagne (CALICO, MAYOBS33) ou
    numéro WMO du flotteur ; vide pour les autres changements."""
    if str((change or {}).get("kind") or "") != "station":
        return ""
    item = _station_item(change)
    return (_campaign_code(item) or _argo_identifier(item)).casefold()


def _place_dedup_key(change: dict) -> str:
    kind = str(change.get("kind") or "")
    if kind == "zee-enter":
        # Identité + bassin : les eaux françaises de Gascogne/Pertuis ne sont
        # pas celles de Corse/Sardaigne ni du Pacifique. Sans coordonnées,
        # le titre brut reste le repli (RC26 : parenthèse = territoire).
        raw = re.sub(r"\s+", " ", str(change.get("title") or change.get("fact") or "")).strip()
        if not raw:
            return ""
        ident = toponyms.identity_key(raw) or raw.casefold()
        basin = _zee_basin_from_change(change)
        return f"zee:{ident}:{basin}" if basin else f"zee:{ident}"
    # Un groupe côte / île porte sa géographie : « l'Andalousie — Cartagena »
    # et « l'Andalousie — Almería » sont le même site.
    geo = change.get("geo") if isinstance(change.get("geo"), dict) else None
    geo_name = str((geo or {}).get("fr") or (geo or {}).get("en") or "").strip()
    name = norm_stop(geo_name) if geo_name else norm_stop(change_place_name(change))
    if not name:
        return ""
    # Dédoublonnage par SITE — « Lilleau-des-Niges » et « Lilleau-des-Niges
    # - Zone de Protection » partagent le préfixe significatif (avant « - », « — », « ( »).
    if kind == "station":
        # N12 : deux jeux « Bathymétrie - … (campagne CALICO) » et « Bathymétrie -
        # … (campagne MAYOBS33) » ne sont pas le même site — le préfixe commun
        # fusionnait Mayotte dans le départ de Nouméa. La campagne / le flotteur
        # fait l'identité.
        ident = _station_ident(change)
        if ident:
            return f"station:{ident}"
    name = re.split(r"\s+[-—–]\s+|\s*\(", name, maxsplit=1)[0].strip() or name
    if kind in {"escale", "approche"}:
        return f"{kind}:{name}"
    return name


def _usable_changes(changes: list[dict]) -> list[dict]:
    seen_ids: set[str] = set()
    rows: list[dict] = []
    for change in sorted(changes, key=lambda c: (c.get("tMs") or 0, str(c.get("id") or ""))):
        if not change_is_speakable(change) or not change_on_route(change):
            continue
        cid = str(change.get("id") or "")
        if cid and cid in seen_ids:
            continue
        if cid:
            seen_ids.add(cid)
        rows.append(change)
    # Même site dit une fois : le nom le plus court gagne, à l'instant
    # du premier croisement.
    best: dict[str, dict] = {}
    out: list[dict] = []
    for change in rows:
        key = _place_dedup_key(change)
        if not key:
            out.append(change)
            continue
        prev = best.get(key)
        if prev is None:
            best[key] = change
            out.append(change)
            continue
        if _is_amp_change(change) or _is_amp_change(prev):
            rank = {"enter": 0, "nearby": 1, "exit": 2}
            prev_r = rank.get(_amp_speak_event(prev), 9)
            cur_r = rank.get(_amp_speak_event(change), 9)
            if cur_r < prev_r:
                best[key] = change
                out[out.index(prev)] = change
                continue
            if cur_r > prev_r:
                continue
        if len(change_place_name(change)) < len(change_place_name(prev)):
            merged = {
                **change,
                "t": prev.get("t") or change.get("t"),
                "tMs": prev.get("tMs") if prev.get("tMs") is not None else change.get("tMs"),
            }
            best[key] = merged
            out[out.index(prev)] = merged
    out.sort(key=lambda c: (c.get("tMs") or 0, str(c.get("id") or "")))
    return out


def film_free_item_target(span_ms: int) -> int:
    """Budget d'items du chapitre intégral, proportionnel à la durée —
    1 item par 1,5 jour de mer, plancher 4, plafond 16."""
    days = max(0.0, float(span_ms or 0) / 86_400_000.0)
    return min(FILM_FREE_ITEMS_MAX, max(FILM_CHAPTER_MAX_CHANGES, math.ceil(days / FILM_FREE_ITEM_DAYS)))


# Types encore absents du chapitre, dans l'ordre du gabarit (FILM_DISCOURS § 4).
# L'AMP (8 au stock) passe avant le projet (129) : le type rare ne perd pas
# toujours la fenêtre contre le type abondant.
_DIVERSITY_ORDER = ("climo", "station", "amp", "project", "alert-on", "coast", "zee-enter")


def _diversity_kind(change: dict) -> str:
    kind = str(change.get("kind") or "")
    if kind == "alert-on" and _is_amp_change(change):
        return "amp"
    return kind


def _diversity_bonus(change: dict) -> int:
    """Îles et détroits (Sardaigne, Gibraltar…) : jalons rares, jamais sacrifiés
    en premier."""
    geo = change.get("geo") if isinstance(change.get("geo"), dict) else {}
    return 1 if (geo.get("kind") in {"island", "strait"}) else 0


def _pick_diverse(cands: list[dict], picked: list[dict]) -> Optional[dict]:
    """Le meilleur item d'une fenêtre : types encore absents d'abord (climato,
    station, projet, AMP, alerte, côte/eaux), pas deux fois le même type
    d'affilée quand un autre existe, puis score et priorité."""
    if not cands:
        return None
    seen = {_diversity_kind(p) for p in picked}
    last = _diversity_kind(picked[-1]) if picked else ""
    has_other = any(_diversity_kind(c) != last for c in cands)

    def key(c: dict):
        k = _diversity_kind(c)
        absent = 0 if k not in seen else 1
        rank = _DIVERSITY_ORDER.index(k) if (absent == 0 and k in _DIVERSITY_ORDER) else len(_DIVERSITY_ORDER)
        repeat = 1 if (k == last and has_other) else 0
        # Une île / un détroit ne cède jamais sa place aux eaux du jour —
        # le jalon rare passe AVANT la pénalité de répétition.
        return (
            0 if _is_spine_route_item(c) else 1,
            absent, rank, -_diversity_bonus(c), repeat,
            -int(c.get("score") or 0),
            CHANGE_PRIORITY.get(str(c.get("kind") or ""), 9),
            c.get("tMs") or 0, str(c.get("id") or ""),
        )

    return min(cands, key=key)


def _pin_spine_waters(picked: list[dict], pool: list[dict]) -> list[dict]:
    """ES/PT/MA/FR/Gibraltar restent dans le chapitre — un Argo ou une
    AMP de trop cède sa place, la première AMP (Lilleau) est gardée."""
    have = {k for k in (_place_dedup_key(c) for c in picked) if k}
    missing: list[dict] = []
    for c in pool:
        if not _is_spine_route_item(c):
            continue
        k = _place_dedup_key(c)
        if k and k in have:
            continue
        missing.append(c)
        if k:
            have.add(k)
    if not missing:
        return picked
    extras = [
        c for c in picked
        if _diversity_kind(c) in {"amp", "station"} and not _is_spine_route_item(c)
    ]
    drop_ids = {id(c) for c in extras[1:]}
    out = [c for c in picked if id(c) not in drop_ids]
    keep_extra_ids = {id(c) for c in extras[:1]}
    for c in missing:
        if len(out) < FILM_FREE_ITEMS_MAX:
            out.append(c)
            continue
        replaced = False
        for i in range(len(out) - 1, -1, -1):
            if id(out[i]) in keep_extra_ids:
                continue
            if _diversity_kind(out[i]) in {"amp", "station"} and not _is_spine_route_item(out[i]):
                out[i] = c
                replaced = True
                break
        if not replaced:
            continue
    out.sort(key=lambda c: (c.get("tMs") or 0, str(c.get("id") or "")))
    return out


def _spread_free_changes(
    cands: list[dict], t_a: int, t_b: int, *, depart_ms: Optional[int] = None,
    spare: Optional[list[dict]] = None,
) -> list[dict]:
    """Sélection par fenêtres de temps, pas par type puis date.

    - la période à quai [tA, départ] ne garde qu'UN item de proximité
      (« à cinq milles ») en plus de l'ouverture ;
    - la mer [départ, tB] est découpée en autant de fenêtres que d'items du
      budget (1 / 1,5 jour, plancher 4) : le meilleur item par fenêtre
      (score puis diversité) ; les items non retenus d'une fenêtre comblent
      une fenêtre vide voisine ; `spare` (stations, projets… hors dose) ne
      sert QUE dans les fenêtres restées vides — le Pacifique ne se tait pas ;
    - le tout est plafonné à FILM_FREE_ITEMS_MAX (16).
    """
    rows = sorted(cands, key=lambda c: (c.get("tMs") or 0, str(c.get("id") or "")))
    if not rows and not spare:
        return []
    dock_end = int(depart_ms) if depart_ms and int(t_a or 0) < int(depart_ms) < int(t_b or 0) else int(t_a or 0)
    dock = [c for c in rows if (c.get("tMs") or 0) <= dock_end]
    sea = [c for c in rows if (c.get("tMs") or 0) > dock_end]
    picked: list[dict] = []
    # Au quai : au plus deux phrases après l'ouverture (recette RC26), dont UNE
    # seule de proximité (« à cinq milles » : AMP, alerte, projet) — plus jamais six.
    proximity = {"amp", "alert-on", "project", "marina"}
    if dock:
        first = _pick_diverse(dock, picked)
        if first is not None:
            picked.append(first)
            first_prox = str(first.get("kind") or "") in proximity
            other = [
                c for c in dock
                if c is not first and (str(c.get("kind") or "") in proximity) != first_prox
            ]
            if not other:
                # Pas d'autre famille au quai : un 2e item de proximité d'un
                # AUTRE type (le projet ne fait pas taire l'AMP voisine).
                other = [
                    c for c in dock
                    if c is not first and _diversity_kind(c) != _diversity_kind(first)
                ]
            second = _pick_diverse(other, picked)
            if second is not None:
                picked.append(second)
    span = max(1, int(t_b or 0) - dock_end)
    n = max(1, film_free_item_target(span) - len(picked))
    width = span / n
    buckets: list[list[dict]] = [[] for _ in range(n)]
    taken = [0] * n   # au plus 2 items par fenêtre : un amas d'un jour ne mange pas la jambe
    for c in sea:
        i = min(n - 1, int(((c.get("tMs") or 0) - dock_end) / width))
        buckets[max(0, i)].append(c)
    filled: list[Optional[dict]] = [None] * n

    def _take(j: int, into: int) -> Optional[dict]:
        choice = _pick_diverse(buckets[j], picked)
        if choice is None:
            return None
        buckets[j] = [c for c in buckets[j] if c is not choice]
        taken[j] += 1
        filled[into] = choice
        picked.append(choice)
        return choice

    for i in range(n):
        if buckets[i]:
            _take(i, i)
    # Fenêtres vides ← d'abord la réserve DE LA MÊME fenêtre (stations, projets,
    # AMP, climato au-delà de la dose : mieux vaut un flotteur Argo que dix jours
    # muets — et son instant tombe vraiment dans le trou), puis les items non
    # retenus des fenêtres voisines.
    spare_buckets: list[list[dict]] = [[] for _ in range(n)]
    for c in sorted(spare or [], key=lambda c: (c.get("tMs") or 0, str(c.get("id") or ""))):
        t = c.get("tMs") or 0
        if t <= dock_end:
            continue
        i = min(n - 1, int((t - dock_end) / width))
        spare_buckets[max(0, i)].append(c)
    for i in range(n):
        if filled[i] is not None or not spare_buckets[i]:
            continue
        choice = _pick_diverse(spare_buckets[i], picked)
        if choice is not None:
            filled[i] = choice
            taken[i] += 1
            picked.append(choice)
            spare_buckets[i] = [c for c in spare_buckets[i] if c is not choice]
    for i in range(n):
        if filled[i] is not None:
            continue
        for j in (i - 1, i + 1):
            if 0 <= j < n and buckets[j] and taken[j] < 2:
                if _take(j, i) is not None:
                    break
    # Capacité restante (jusqu'au plafond) : au plus un item de plus par fenêtre —
    # Sardaigne, Gibraltar et les eaux d'un même jour survivent, sans refaire l'amas.
    while len(picked) < FILM_FREE_ITEMS_MAX:
        open_buckets = [j for j in range(n) if buckets[j] and taken[j] < 2]
        if not open_buckets:
            break
        j = min(open_buckets, key=lambda k: (taken[k], k))
        choice = _pick_diverse(buckets[j], picked)
        if choice is None:
            # Cette fenêtre n'a que des doublons de site — elle ne doit
            # pas faire taire les fenêtres suivantes (la Seychelloise attend).
            buckets[j] = []
            continue
        buckets[j] = [c for c in buckets[j] if c is not choice]
        taken[j] += 1
        picked.append(choice)
    # La réserve complète jusqu'au plafond (même quota ≤ 2 par fenêtre) —
    # le flotteur Argo unique par jambe ne laisse plus la traversée muette.
    while len(picked) < FILM_FREE_ITEMS_MAX:
        open_spare = [j for j in range(n) if spare_buckets[j] and taken[j] < 2]
        if not open_spare:
            break
        j = min(open_spare, key=lambda k: (taken[k], k))
        choice = _pick_diverse(spare_buckets[j], picked)
        if choice is None:
            spare_buckets[j] = []
            continue
        spare_buckets[j] = [c for c in spare_buckets[j] if c is not choice]
        taken[j] += 1
        picked.append(choice)
    # Quand TOUT le chapitre tient sous le plafond, on ne jette rien : le
    # quota par fenêtre protège contre l'amas, pas contre un stock clairsemé.
    # Jamais deux fois le même site (l'Andalousie d'hier ne revient pas demain).
    leftovers = [c for b in buckets for c in b]
    if leftovers and len(picked) + len(leftovers) <= FILM_FREE_ITEMS_MAX:
        keys = {k for k in (_place_dedup_key(p) for p in picked) if k}
        for c in leftovers:
            k = _place_dedup_key(c)
            if k and k in keys:
                continue
            picked.append(c)
            if k:
                keys.add(k)
    # Dédoublonnage final par site : les jalons quotidiens d'une même
    # côte (l'Andalousie du 21, l'Andalousie du 22) ne se disent qu'une fois —
    # le nom le plus court gagne, au temps du premier croisement.
    by_site: dict[str, dict] = {}
    out: list[dict] = []
    for c in sorted(picked, key=lambda c: (c.get("tMs") or 0, str(c.get("id") or ""))):
        k = _place_dedup_key(c)
        if not k:
            out.append(c)
            continue
        prev = by_site.get(k)
        if prev is None:
            by_site[k] = c
            out.append(c)
            continue
        if _is_amp_change(c) or _is_amp_change(prev):
            rank = {"enter": 0, "nearby": 1, "exit": 2}
            prev_r = rank.get(_amp_speak_event(prev), 9)
            cur_r = rank.get(_amp_speak_event(c), 9)
            if cur_r < prev_r:
                out[out.index(prev)] = c
                by_site[k] = c
                continue
            if cur_r > prev_r:
                continue
        if len(str(c.get("title") or "")) < len(str(prev.get("title") or "")):
            merged = {**c, "t": prev.get("t"), "tMs": prev.get("tMs")}
            out[out.index(prev)] = merged
            by_site[k] = merged
    out.sort(key=lambda c: (c.get("tMs") or 0, str(c.get("id") or "")))
    return _pin_spine_waters(out, rows)


def _would_speak(change: dict) -> bool:
    """Un item ne prend une fenêtre que s'il donnera vraiment une phrase
    Mêmes gardes que speak_change — escale d'avion, titre anglais,
    phrase vide ou interdite."""
    kind = str(change.get("kind") or "")
    place = change_place_name(change) or short_name(str(change.get("title") or ""))
    geo = change.get("geo") if isinstance(change.get("geo"), dict) else None
    if geo and (geo.get("fr") or geo.get("en")):
        place = geo.get("fr") or geo.get("en") or place
    if looks_english_title(place) and kind in {
        "port", "approche", "culture", "project", "amp", "marina",
        "poe", "anchorage", "aton",
    }:
        return False
    sentence = change_sentence(change, "fr").strip()
    return bool(sentence) and not film_has_forbidden(sentence)


def _is_argo_station(change: dict) -> bool:
    from ici_engine import science_type_key  # noqa: PLC0415
    return (
        str(change.get("kind") or "") == "station"
        and science_type_key(_station_item(change)) == "argo"
    )


def _limit_argo_once(rows: list[dict]) -> list[dict]:
    """Au plus UN flotteur Argo par chapitre — le premier croisé ;
    jamais six « un flotteur Argo » anonymes (transcription du 14 oct.)."""
    out: list[dict] = []
    seen = False
    for c in rows:
        if _is_argo_station(c):
            if seen:
                continue
            seen = True
        out.append(c)
    return out


def _cap_argo_candidates(pool: list[dict], spare: list[dict]) -> tuple[list[dict], list[dict]]:
    """Un seul flotteur Argo candidat AVANT la répartition par fenêtres.
    On garde celui du passage le plus SILENCIEUX (le plus loin, dans le temps,
    de tout autre stock racontable) : c'est lui qui remplissait le trou de la
    traversée que les Argo surnuméraires comblaient avant — la jambe ne perd
    pas sa densité."""
    argos = [c for c in pool if _is_argo_station(c)] + [c for c in spare if _is_argo_station(c)]
    if len(argos) <= 1:
        return pool, spare
    others = [
        c.get("tMs") or 0
        for c in pool + (spare or [])
        if not _is_argo_station(c) and c.get("tMs")
    ]

    def quietness(c: dict) -> float:
        t = c.get("tMs") or 0
        return min((abs(t - o) for o in others), default=0.0)

    best = max(argos, key=lambda c: (
        quietness(c),
        -(change_distance_nm(c) if change_distance_nm(c) is not None else 999.0),
        -(c.get("tMs") or 0),
    ))
    return (
        [c for c in pool if not _is_argo_station(c) or c is best],
        [c for c in spare if not _is_argo_station(c) or c is best],
    )


def select_chapter_changes(
    changes: list[dict], t_a: int, t_b: int, *, budget: bool = True, tier: Optional[int] = None,
    clock: dict | None = None, depart_ms: Optional[int] = None, lang: str = "fr",
) -> list[dict]:
    usable = _usable_changes(changes)
    span = (t_b or 0) - (t_a or 0)
    zee = dose_zee_changes(usable, span)
    coast = dose_coast_changes(usable, span, lang=lang)
    amp = dose_amp_changes(usable, span)
    proj = dose_project_changes(usable, span)
    climo = dose_climo_changes(usable, span)
    stations = dose_station_changes(usable, span, t_a=t_a, t_b=t_b)
    extras = _tier_route_extras(zee, coast, amp, proj, climo, stations, tier=tier)
    rest_src = [
        c for c in usable
        if str(c.get("kind") or "") not in ROUTE_NAMING_KINDS
        and not _is_coast_source(c)
        and not _is_amp_change(c)
        and str(c.get("kind") or "") not in ({"project", "climo", "station"} | DC_DOSAGE_KINDS)
        and _tier_allows_kind(str(c.get("kind") or ""), tier)
    ]
    if not budget:
        # Fenêtres de temps sur toute la jambe — plus de « type puis date ».
        pool_route = extras if tier is not None else zee + coast + amp + proj + climo + stations
        keep = [c for c in rest_src if str(c.get("kind") or "") in {"escale", "approche"}]
        marinas = [c for c in rest_src if str(c.get("kind") or "") == "marina"]
        if marinas:
            # La marina de l'escale : la dernière à portée (elle nomme le port, pas une phrase).
            keep.append(max(marinas, key=lambda c: (c.get("tMs") or 0, str(c.get("id") or ""))))
        pool = [
            c for c in pool_route + [
                x for x in rest_src
                if str(x.get("kind") or "") not in {"escale", "approche", "marina"}
            ]
            if _would_speak(c)
        ]
        in_pool = {id(c) for c in pool}
        # Une 2e station au-delà de la dose ne se justifie que sur une
        # longue jambe (le Pacifique muet) — jamais sur une traversée courte.
        spare_station_ok = span > 5 * 86_400_000
        spare = [
            c for c in usable
            if id(c) not in in_pool
            and (str(c.get("kind") or "") in {"station", "project", "climo"} or _is_amp_change(c))
            and (str(c.get("kind") or "") != "station"
                 or (spare_station_ok and station_spoken_label(c, "fr")))
            and not (span >= SHORT_CROSSING_MS and _is_buoy_change(c))
            and _would_speak(c)
        ]
        pool, spare = _cap_argo_candidates(pool, spare)
        picked_free = _spread_free_changes(pool, t_a, t_b, depart_ms=depart_ms, spare=spare)
        dc2 = dose_dc2_leg_changes(usable, span)
        if any(str(c.get("kind") or "") == "station" or _is_buoy_change(c) for c in picked_free):
            # RG5 : au plus une station par chapitre — la bouée DC2 en est une.
            dc2 = [c for c in dc2 if str(c.get("kind") or "") != "buoy"]
        dc3 = dose_dc3_leg_changes(usable, span)
        out = picked_free + keep + dc2 + dc3  # escale, approche, marina ; DC hors fenêtres
        seen_ids: set[str] = set()
        uniq: list[dict] = []
        for c in out:
            cid = str(c.get("id") or "")
            if cid and cid in seen_ids:
                continue
            if cid:
                seen_ids.add(cid)
            uniq.append(c)
        uniq.sort(key=lambda c: (c.get("tMs") or 0, str(c.get("id") or "")))
        return _limit_argo_once(uniq)
    grouped = _group_changes(rest_src, span, clock=clock)
    must = [c for c in grouped if c.get("kind") in {"escale", "approche"}]
    rest = [c for c in grouped if c.get("kind") not in {"escale", "approche"}]
    rest.sort(key=lambda c: (
        -int(c.get("score") or 0), CHANGE_PRIORITY.get(str(c.get("kind") or ""), 9), c.get("tMs") or 0,
    ))
    arrival = next((c for c in must if c.get("kind") == "escale"), None)
    approach = next((c for c in must if c.get("kind") == "approche"), None)
    alert = next((c for c in rest if c.get("kind") == "alert-on"), None)
    color_skip = {"marina", "zee-enter", "coast"}
    if tier is not None and tier <= FILM_TIER_SHORT:
        color_skip = color_skip | {"station", "climo", "culture", "port"} | DC_DOSAGE_KINDS
    color = next((c for c in rest if c.get("kind") in COLOR_KINDS and c.get("kind") not in color_skip), None)
    # La marina de l'escale (« cultures d'escale », 26 sept.) : la dernière marina à portée de la fenêtre.
    marina = next((c for c in sorted(rest, key=lambda c: -(c.get("tMs") or 0)) if c.get("kind") == "marina"), None)
    picked: list[dict] = []

    def add(item: dict | None) -> None:
        if item is None or len(picked) >= FILM_CHAPTER_MAX_CHANGES:
            return
        if any(x.get("id") == item.get("id") for x in picked):
            return
        key = _place_dedup_key(item)
        if key and any(_place_dedup_key(x) == key for x in picked):
            return
        picked.append(item)

    add(arrival)
    add(color)
    add(marina)
    add(approach)
    add(alert)
    for item in must + rest:
        add(item)
    seen = {str(x.get("id") or "") for x in picked}
    for item in extras:
        cid = str(item.get("id") or "")
        if cid and cid in seen:
            continue
        picked.append(item)
        if cid:
            seen.add(cid)
    picked.sort(key=lambda c: (c.get("tMs") or 0, str(c.get("id") or "")))
    return _limit_argo_once(picked)


def _de(name: str) -> str:
    """« de Papeete » mais « d’Ajaccio ». Un nom déjà « de Fineveke » ne devient pas « de de »."""
    n = (name or "").strip()
    if not n:
        return "de"
    if re.match(r"^(de |d['’]|du |des )", n, re.I):
        return n
    if re.match(r"^[aeiouyâàäéèêëîïôöûùüœh]", n, re.I):
        return f"d’{n}"
    return f"de {n}"


def _group_sentence(change: dict, lang: str) -> str:
    """Plus aucun comptage à la voix (ZEE : RG2 ; stations : RG5)."""
    del change, lang
    return ""


_HS_VALUE_RE = re.compile(r"Hs\s+(\d+(?:[.,]\d+)?)\s*m", re.I)
_SEA_TITLE_RE = re.compile(r"^(mer|sea)$", re.I)


def sea_alert_hs_m(change: dict) -> Optional[float]:
    """Hs observée (pas le seuil) : champ structuré, sinon le premier « Hs N m » du fait."""
    n = _fact_num(change, "hs", "maxHs")
    if n is not None:
        return n
    blob = f"{change.get('fact') or ''} {change.get('title') or ''}"
    found = _HS_VALUE_RE.search(blob)
    if not found:
        return None
    try:
        return float(found.group(1).replace(",", "."))
    except ValueError:
        return None


def is_sea_hs_alert(change: dict) -> bool:
    """Alerte mer (kind sea / alert-on « Hs … m ≥ ») — pas une AMP."""
    if not isinstance(change, dict):
        return False
    kind = str(change.get("kind") or "")
    title = str(change.get("title") or "")
    fact = str(change.get("fact") or "")
    if kind == "alert-on" and alert_is_amp(change):
        return False
    if kind == "sea":
        return True
    if kind == "wx" and str(change.get("event") or "") == "sea":
        return True
    if kind == "alert-on" and (_SEA_TITLE_RE.match(title.strip()) or _HS_VALUE_RE.search(fact + " " + title)):
        return True
    return False


def sea_alert_sentence(change: dict, lang: str = "fr") -> str:
    """« mer formée (3 m) » / « Hs 3 m » — jamais ≥, jamais le seuil répété."""
    en = _en(lang)
    when = day_month(change.get("t"), lang)
    hs = sea_alert_hs_m(change)
    hs_s = _plain(hs, 0) if hs is not None else ""
    if hs_s:
        body = f"Hs {hs_s} m" if en else f"mer formée ({hs_s} m)"
    else:
        body = "Hs" if en else "mer formée"
    if when:
        return f"On {when}, {body}." if en else f"Le {when}, {body}."
    return f"{body[0].upper()}{body[1:]}."


def change_sentence(change: dict, lang: str = "fr") -> str:
    en = _en(lang)
    if str(change.get("id") or "").startswith("group:"):
        return _group_sentence(change, lang)
    when = day_month(change.get("t"), lang)
    title = short_name(change.get("title") or "")
    fact = expand_spoken_units(str(change.get("fact") or "").rstrip("."), lang)
    kind = change.get("kind")
    name = title.replace("Arrivée à ", "").replace("Arrival at ", "").strip()
    if is_sea_hs_alert(change):
        return sea_alert_sentence(change, lang)
    if kind == "escale":
        if when:
            return f"Arrival at {name} on {when}." if en else f"Arrivée à {name} le {when}."
        return f"Arrival at {name}." if en else f"Arrivée à {name}."
    if kind == "approche":
        if looks_english_title(title):
            return ""
        if when:
            return (
                f"On {when}, the approach is by {title}."
                if en else
                f"Le {when}, l'approche se fait par {title}."
            )
        return f"The approach is by {title}." if en else f"L'approche se fait par {title}."
    if kind == "alert-on":
        from ici_engine import is_fishing_amp  # noqa: PLC0415
        if is_fishing_amp({"name": title, "title": title, "fact": fact}):
            return ""
        if alert_is_amp(change):
            amp = alert_amp_name(change)
            if not amp:
                return ""
            return _amp_film_sentence(amp, change, lang, when)
        body = IUCN_RE.sub("", fact or title).strip(" ;:")
        if not body or NO_DATA_RE.search(body):
            return ""
        return f"On {when}, {body}." if en else f"Le {when}, {body}."
    if kind == "zee-enter" and re.search(r"ports? d['’]entr|formalit", title, re.I):
        name = extract_named(title, fact, "port")
        if not name:
            return ""
        return f"On {when}, off {name}." if en else f"Le {when}, devant {name}."
    if kind == "zee-enter":
        members = change.get("members")
        if isinstance(members, list) and len(members) > 1:
            # « les eaux françaises, puis celles de Montserrat » — jamais
            # un adjectif orphelin ni une minuscule en tête de nom propre.
            body = zee_group_waters(members, lang)
            if not body:
                return ""
            return f"On {when}, {body}." if en else f"Le {when}, {body}."
        raw = title or fact
        waters = zee_waters_label(raw, lang)
        if not waters:
            return ""
        return f"On {when}, {waters}." if en else f"Le {when}, {waters}."
    if kind == "coast":
        return coast_sentence(change, lang)
    if kind == "station":
        spoken = station_spoken_label(change, lang)
        if not spoken:
            return ""
        if when:
            return f"On {when}, {spoken}." if en else f"Le {when}, {spoken}."
        return f"{spoken[0].upper()}{spoken[1:]}."
    if kind == "buoy":
        spoken = station_spoken_label({**change, "kind": "station"}, lang)
        if not spoken:
            return ""
        if when:
            return f"On {when}, {spoken}." if en else f"Le {when}, {spoken}."
        return f"{spoken[0].upper()}{spoken[1:]}."
    if kind == "poe":
        name = _poe_place_name(change)
        if not name or looks_english_title(name):
            return ""
        body = (
            f"entry formalities go through {name}"
            if en else
            f"les formalités d'entrée passent par {name}"
        )
        if when:
            return f"On {when}, {body}." if en else f"Le {when}, {body}."
        return f"{body[0].upper()}{body[1:]}."
    if kind == "anchorage":
        name = _anchorage_name(change)
        if not name or looks_english_title(name):
            return ""
        if when:
            return (
                f"On {when}, anchorage {name}."
                if en else
                f"Le {when}, mouillage {name}."
            )
        return f"Anchorage {name}." if en else f"Mouillage {name}."
    if kind == "aton":
        name = _aton_name(change)
        if not name or looks_english_title(name):
            return ""
        body = f"beacon {name}" if en else f"balise {name}"
        if when:
            return f"On {when}, {body}." if en else f"Le {when}, {body}."
        return f"{body[0].upper()}{body[1:]}."
    if kind == "cable":
        name = _cable_name(change)
        if not name:
            return ""
        body = f"cable {name}" if en else f"câble {name}"
        if when:
            return f"On {when}, {body}." if en else f"Le {when}, {body}."
        return f"{body[0].upper()}{body[1:]}."
    if kind == "depth":
        metres = _depth_m(change)
        if metres is None:
            return ""
        if abs(metres - round(metres)) < 0.05:
            spoken = str(int(round(metres)))
        else:
            spoken = f"{metres:.1f}".rstrip("0").rstrip(".")
            if not en:
                spoken = spoken.replace(".", ",")
        body = f"Depth: {spoken} m" if en else f"Profondeur : {spoken} m"
        if when:
            return f"On {when}, {body}." if en else f"Le {when}, {body}."
        return f"{body}."
    if kind == "piracy":
        name = _piracy_name(change)
        if not name:
            return ""
        level = _piracy_level(change)
        source = str(change.get("source") or "").strip()
        label = "Piracy" if en else "Piraterie"
        body = f"{label} — {name}"
        if level:
            body += f" · {level}"
        if source:
            body += f" · {source}"
        if when:
            return f"On {when}, {body}." if en else f"Le {when}, {body}."
        return f"{body}."
    if kind == "satellite":
        caption = _satellite_caption(change)
        if not caption:
            return ""
        body = caption.rstrip(".")
        if when:
            return f"On {when}, {body}." if en else f"Le {when}, {body}."
        return caption if caption.endswith((".", "!", "?", "…")) else f"{caption}."
    if kind == "amp":
        from ici_engine import is_fishing_amp, spoken_amp_name  # noqa: PLC0415
        if is_fishing_amp({"name": title, "title": title, "fact": fact}):
            return ""
        name = spoken_amp_name(change_place_name(change) or title) or change_place_name(change)
        if not name or looks_english_title(name):
            return ""
        if _amp_speak_event(change) == "exit":
            return ""
        return _amp_film_sentence(name, change, lang, when)
    if kind == "project":
        name = change_place_name(change)
        if not name or looks_english_title(name):
            return ""
        name = project_spoken_title(name)
        nm = change_distance_nm(change)
        dist = spoken_distance(nm, lang) if nm is not None else ""
        if dist:
            return (
                f"On {when}, {dist} away, project {name}."
                if en else
                f"Le {when}, à {dist}, le projet {name}."
            )
        return f"On {when}, project {name}." if en else f"Le {when}, le projet {name}."
    if kind == "climo":
        return climo_sentence(change, lang)
    if kind == "marina":
        return ""
    if kind == "cyclone":
        cyc_name, year = cyclone_name_year(change)
        if not cyc_name:
            return ""
        if year:
            return (
                f"Historical track of cyclone {cyc_name} ({year})."
                if en else
                f"Trace historique du cyclone {cyc_name} ({year})."
            )
        return (
            f"Historical track of cyclone {cyc_name}."
            if en else
            f"Trace historique du cyclone {cyc_name}."
        )
    if kind == "culture":
        body = fact or title
        if not body:
            return ""
        return body if body.endswith(".") else f"{body}."
    if kind == "port":
        name = change_place_name(change)
        if not name or looks_english_title(name):
            return ""
        return f"On {when}, off {name}." if en else f"Le {when}, devant {name}."
    if fact:
        return f"{fact}."
    return ""


def _bubble_from_change(change: dict, chapter: dict, lang: str, char_idx: int) -> dict:
    kind = BUBBLE_KIND.get(str(change.get("kind") or ""), change.get("kind") or "stop")
    title = short_name(change.get("title") or "")
    if change.get("kind") in {"approche", "escale"}:
        title = short_name(
            title.replace("Arrivée à ", "").replace("Arrival at ", "")
            or chapter.get("toName") or ""
        )
    fact = change_sentence(change, lang)
    score = change.get("score") if change.get("score") in {1, 2, 3} else bubble_score({"kind": kind})
    return {
        "id": change.get("id"),
        "charIdx": int(char_idx or 0),
        "kind": kind,
        "title": str(title)[:40],
        "fact": fact,
        "score": score if score in {1, 2, 3} else 3,
        "card": {
            "id": change.get("id"), "kind": kind, "title": title, "text": fact,
            "at": change.get("t"), "score": score if score in {1, 2, 3} else 3,
        },
    }


def _sentences(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"(?<=[.!?…])\s+", text or "") if p.strip()]


_PROJECT_YEAR_SUFFIX_RE = re.compile(
    r"\s*[-–—:,]?\s*\(?\b(Année|Annee|Year|Phase|An)\s+(\d{1,2})\)?\s*$",
    re.I,
)


_PROJECT_YEAR_IN_TEXT_RE = re.compile(
    r"(?<=[a-zà-ÿ]) (Année|Year) (\d{1,2})(?!\d)([.,;]|$)",
)


def project_spoken_title(name: str) -> str:
    """« Restaurer les coraux … poissons-demoiselles Année 1 » collait l'année du
    projet au titre (N10) : le suffixe d'année ou de phase passe entre parenthèses,
    « … poissons-demoiselles (Année 1) ». Le reste du titre ne bouge pas."""
    text = str(name or "").strip()
    m = _PROJECT_YEAR_SUFFIX_RE.search(text)
    if not m or m.start() == 0:
        return text
    head = text[: m.start()].rstrip(" -–—:,")
    if not head:
        return text
    word = m.group(1)
    word = word[0].upper() + word[1:].lower()
    if word == "Annee":
        word = "Année"
    return f"{head} ({word} {m.group(2)})"


def _sentence_has_date(text: str, lang: str) -> bool:
    if _en(lang):
        return bool(_DATE_EN_RE.search(text or ""))
    return bool(_DATE_FR_RE.search(_digit_fr_dates(text)))


_RELATIVE_ANCHOR_MS_CEIL = 1_000_000_000_000  # ancres test / relatives (< ~2001 UTC)


def _spoken_anchor_ms(sentence: str, lang: str, ref_ms: Optional[int] = None) -> Optional[int]:
    """Millisecondes UTC de la date dite dans la phrase, si lisible.

    Sans année écrite, `_parse_spoken_date` suppose 2026 : « le 9 février » d'un
    chapitre de 2027 tomberait un an trop tôt. Avec `ref_ms` (instant du trajet),
    on prend l'année (ref − 1, ref, ref + 1) la plus proche de la référence.
    """
    spoken = _parse_spoken_date(sentence, lang)
    if spoken is None:
        return None
    rx = _DATE_EN_RE if _en(lang) else _DATE_FR_RE
    found = rx.search(sentence if _en(lang) else _digit_fr_dates(sentence))
    has_year = bool(found and re.search(r"\d{4}$", found.group(0)))
    if ref_ms is not None and ref_ms >= _RELATIVE_ANCHOR_MS_CEIL and not has_year:
        ref_year = datetime.fromtimestamp(ref_ms / 1000, tz=timezone.utc).year
        best: Optional[int] = None
        for year in (ref_year - 1, ref_year, ref_year + 1):
            try:
                cand = int(spoken.replace(year=year).timestamp() * 1000)
            except ValueError:
                continue
            if best is None or abs(cand - ref_ms) < abs(best - ref_ms):
                best = cand
        if best is not None:
            return best
    return int(spoken.timestamp() * 1000)


def _parse_spoken_date(text: str, lang: str) -> Optional[datetime]:
    rx = _DATE_EN_RE if _en(lang) else _DATE_FR_RE
    found = rx.search(text if _en(lang) else _digit_fr_dates(text))
    if not found:
        return None
    day_s, month_s = found.group(1), found.group(2)
    rest = found.group(0)
    year_m = re.search(r"(\d{4})$", rest)
    year = int(year_m.group(1)) if year_m else 2026
    try:
        day = 1 if str(day_s).lower() == "1er" else int(day_s)
    except (TypeError, ValueError):
        return None
    months = MONTHS["en" if _en(lang) else "fr"]
    key = str(month_s).casefold()
    idx = next((i for i, m in enumerate(months) if m.casefold() == key), -1)
    if idx < 0:
        return None
    try:
        return datetime(year, idx + 1, day, tzinfo=timezone.utc)
    except ValueError:
        return None


def _known_stop(place: str, stops: list | None) -> bool:
    """Le lieu est une escale de la route, Halifax compris. « Noumea » ≡ « Nouméa »."""
    if not place or not stops:
        return False
    labels: list[str] = []
    for raw in stops:
        if isinstance(raw, dict):
            name = str(raw.get("name") or raw.get("to") or "")
        else:
            name = str(raw or "")
        if name.strip():
            labels.append(name.strip())
    head = re.split(r"\s+[-–—]\s+", place.strip(), maxsplit=1)[0]
    folded = _fold_stop(place)
    for name in labels:
        if same_stop(place, name) or (head and head != place.strip() and same_stop(head, name)):
            return True
        key = _fold_stop(norm_stop(name))
        if len(key) >= 5 and key in folded:
            return True
    return False


def _off_leg_stop(place: str, frm: Any, dest: Any, route_rows: list | None, kind: str) -> bool:
    """Une autre escale de la route, dite pendant qu'on est encore ailleurs."""
    if str(kind or "") not in {"approche", "coast", "port", "escale", "stop"}:
        return False
    if not _known_stop(place, route_rows):
        return False
    if frm and same_stop(place, str(frm)):
        return False
    dest_s = str(dest or "")
    if dest_s and (
        same_stop(place, dest_s)
        or dest_s.casefold() in str(place or "").casefold()
        or str(place or "").casefold() in dest_s.casefold()
    ):
        return False
    return True


def _spoken_before_anchor(sentence: str, t_ms: Any, lang: str) -> bool:
    """La date dite est avant le jour de la barre (1 à 60 jours)."""
    if not sentence or t_ms is None:
        return False
    spoken = _parse_spoken_date(sentence, lang)
    if spoken is None:
        return False
    try:
        bar = datetime.fromtimestamp(int(t_ms) / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return False
    if spoken.year != bar.year:
        try:
            spoken = spoken.replace(year=bar.year)
        except ValueError:
            return False
    delta = (bar.date() - spoken.date()).days
    return 1 <= delta <= 60


def _is_arrival_sentence(text: str) -> bool:
    return bool(re.match(r"^(Arrivée à|Arrivée le|Arrival at|Arrival on)\b", text or "", re.I))


_DEPART_SENT_RE = re.compile(
    r"\bquitte\b|\bquitté\b|\bdépart vers\b|\bleaves\b|\bleft\b|\bdeparture for\b|"
    r"\bmet le cap\b|\bsails for\b|\bprend la route\b|\btakes the road\b|\bby road\b|"
    r"\bcap sur\b|\bheading for\b",
    re.I,
)
_DURATION_SENT_RE = re.compile(
    r"d['’]escale|escale de |au port\b|on reste |stopover|at the harbour|"
    r"alongside|stay of |jours? à quai|days? (?:at |in )?port",
    re.I,
)
# Coordonnées de lieux nommés (faits géographiques, pas un voyage inventé) — recette RG14.
_NAMED_PLACE_COORDS = {
    "gibraltar": (36.14, -5.35),
    "tanger": (35.78, -5.81),
    "tangier": (35.78, -5.81),
    "algeciras": (36.13, -5.45),
    "ceuta": (35.89, -5.32),
    "la rochelle": (46.15, -1.16),
    "ajaccio": (41.92, 8.74),
    "fort-de-france": (14.60, -61.07),
    "pointe-à-pitre": (16.24, -61.53),
    "pointe-a-pitre": (16.24, -61.53),
    "cayenne": (4.94, -52.33),
    "papeete": (-17.54, -149.57),
    "nouméa": (-22.27, 166.44),
    "noumea": (-22.27, 166.44),
}


def _canonical_place_coords(name: str) -> Optional[tuple[float, float]]:
    """Coordonnées géographiques, sans lat/lon d'horloge parfois décalés."""
    raw = str(name or "").strip()
    if not raw:
        return None
    key = norm_stop(raw)
    folded = raw.casefold()
    for token, pair in _NAMED_PLACE_COORDS.items():
        if token in folded or token in key:
            return pair
    return None


def _is_depart_sentence(text: str) -> bool:
    return bool(_DEPART_SENT_RE.search(text or ""))


def _is_duration_sentence(text: str) -> bool:
    return bool(_DURATION_SENT_RE.search(text or ""))


def _voice_lookahead_idx(idx: int, floor: int = 0) -> int:
    return max(int(floor), int(idx) - FILM_VOICE_LOOKAHEAD_CHARS)


def _first_word_idx(sentence: str, origin: int) -> int:
    found = re.search(r"\S", sentence or "")
    return origin + (found.start() if found else 0)


def _last_word_idx(sentence: str, origin: int) -> int:
    found = re.search(r"(\S+)[.\s]*$", sentence or "")
    if not found:
        return origin + max(0, len(sentence or "") - 1)
    return origin + found.start(1)


def _end_idx(sentence: str, origin: int) -> int:
    body = (sentence or "").rstrip()
    return origin + max(0, len(body) - 1)


def _find_ci(hay: str, needle: str) -> int:
    if not hay or not needle:
        return -1
    return hay.casefold().find(needle.casefold())


def _place_idx_in_sentence(sentence: str, origin: int, place: str = "") -> int:
    """Index du nom du lieu dans la phrase, sinon le milieu."""
    sent = sentence or ""
    # Détroit / golfe : le nom géographique, pas le premier port (Tanger ≠ Gibraltar).
    geo = re.search(
        r"(?:détroit de |strait of |golfe de |bay of )([A-ZÀ-Ÿ][\w'’\-]+)",
        sent,
        re.I,
    )
    if geo:
        return origin + geo.start(1)
    candidates: list[str] = []
    if place:
        candidates.append(place)
        tail = place.split()[-1] if place.split() else ""
        if tail and tail.casefold() != place.casefold():
            candidates.append(tail)
    for cand in candidates:
        at = _find_ci(sent, cand)
        if at >= 0:
            return origin + at
    geo = re.search(
        r"(?:eaux |waters of |port d['’]?|marina |quitte |"
        r"leaves |longe |skirts |arrivée à |arrival at )"
        r"([A-ZÀ-Ÿ][\w'’\-]+(?:\s+[A-ZÀ-Ÿ][\w'’\-]+)?)",
        sent,
        re.I,
    )
    if geo:
        return origin + geo.start(1)
    named = re.search(r"\b([A-ZÀ-Ÿ][\w'’\-]{3,}(?:\s+[A-ZÀ-Ÿ][\w'’\-]+)?)\b", sent)
    if named and not re.match(r"^(Le|La|Les|The|On|Puis|Then|Berry|Arrivée|Arrival)$", named.group(1)):
        return origin + named.start(1)
    return origin + max(0, len(sent) // 2)


def _prefix_hit_is_same_sentence(text: str, idx: int, spoken: str) -> bool:
    """Le repli sur 12 caractères ne vaut que pour la même phrase.

    « Puis, les eaux … » commence plusieurs phrases : une phrase coupée par le
    budget (« Puis, les eaux capverdiennes. ») ne doit pas voler l'ancre d'une
    phrase restée (« Puis, les eaux françaises. ») — sinon la barre prend la
    date de la phrase coupée (relecture « date », 150 s au now réel).
    """
    found = text[idx:]
    end = re.search(r"[.!?;](\s|$)", found)
    sent = found[: end.end()] if end else found
    if spoken[:20] and sent.startswith(spoken[:20]):
        return True
    tail = spoken.rstrip(" .!?;:\u2026")[-10:]
    return bool(tail) and sent.rstrip().endswith(tail)


def _locate_spoken(text: str, spoken: str, start: int = 0) -> int:
    needle = spoken[:28] if len(spoken) > 28 else spoken
    idx = text.find(needle, start) if needle else -1
    if idx < 0 and len(needle) > 12:
        hit = text.find(needle[:12], start)
        while hit >= 0 and not _prefix_hit_is_same_sentence(text, hit, spoken):
            hit = text.find(needle[:12], hit + 1)
        idx = hit
    if idx < 0 and len(spoken) > 24:
        hit = text.find(spoken[-24:], start)
        while hit >= 0 and not _prefix_hit_is_same_sentence(text, hit, spoken):
            hit = text.find(spoken[-24:], hit + 1)
        idx = hit
    return idx


def _unpack_anchored(item) -> dict:
    if isinstance(item, dict):
        return {
            "sentence": str(item.get("sentence") or item.get("text") or ""),
            "t": item.get("t") if item.get("t") is not None else item.get("tMs"),
            "t_end": item.get("t_end") if item.get("t_end") is not None else item.get("tEnd"),
            "place": str(item.get("place") or ""),
            "kind": str(item.get("kind") or ""),
            "role": str(item.get("role") or ""),
        }
    sentence = str(item[0]) if item else ""
    t_ms = item[1] if len(item) > 1 else None
    extra = item[2] if len(item) > 2 else {}
    if not isinstance(extra, dict):
        extra = {"role": extra} if extra else {}
    return {
        "sentence": sentence,
        "t": t_ms,
        "t_end": extra.get("t_end") if extra.get("t_end") is not None else extra.get("tEnd"),
        "place": str(extra.get("place") or ""),
        "kind": str(extra.get("kind") or ""),
        "role": str(extra.get("role") or ""),
    }


def _retarget_anchor(item, sentence: str):
    if isinstance(item, dict):
        return {**item, "sentence": sentence}
    t_ms = item[1] if len(item) > 1 else None
    extra = item[2] if len(item) > 2 else None
    if extra is None:
        return (sentence, t_ms)
    return (sentence, t_ms, extra)


def _bits_offsets(bits: list[str]) -> list[int]:
    """Index du premier caractère de chaque phrase dans « " ".join(bits) »."""
    out: list[int] = []
    acc = 0
    for k, b in enumerate(bits):
        if k:
            acc += 1
        out.append(acc)
        acc += len(b)
    return out


_SPINE_SPOKEN_RE = (
    re.compile(r"eaux françaises|French waters", re.I),
    re.compile(r"Gascogne|Biscay", re.I),
    re.compile(r"eaux espagnoles|Spanish waters", re.I),
    re.compile(r"eaux portugaises|Portuguese waters", re.I),
    re.compile(r"Gibraltar", re.I),
    re.compile(r"eaux marocaines|Moroccan waters", re.I),
)


def _apply_spine_first_order(bits: list[str], order: list[int]) -> list[int]:
    """Premières mentions FR, Gascogne, ES, PT, Gibraltar, MA dans cet ordre."""
    seq = list(order)

    def first_pos(pat: re.Pattern) -> Optional[int]:
        for pos, i in enumerate(seq):
            if 0 <= i < len(bits) and pat.search(bits[i] or ""):
                return pos
        return None

    for _ in range(len(_SPINE_SPOKEN_RE)):
        ranks = [(r, first_pos(p)) for r, p in enumerate(_SPINE_SPOKEN_RE)]
        ranks = [(r, p) for r, p in ranks if p is not None]
        swapped = False
        for a, b in zip(ranks, ranks[1:]):
            if a[1] > b[1]:
                seq[a[1]], seq[b[1]] = seq[b[1]], seq[a[1]]
                swapped = True
                break
        if not swapped:
            break
    return seq


def _is_lr_ajaccio_chapter(from_name: str = "", to_name: str = "") -> bool:
    return bool(
        re.search(r"rochelle", from_name or "", re.I)
        and re.search(r"ajaccio", to_name or "", re.I)
    )


def _sync_anchored_times_from_speech(bits: list[str], anchored: list, lang: str) -> None:
    """Aligne l'instant d'ancre sur la date dite quand elle est explicite."""
    if len(bits) != len(anchored):
        return
    for j, item in enumerate(anchored):
        row = _unpack_anchored(item)
        role = (row.get("role") or "").strip().lower()
        if role in {"depart", "arrive"}:
            continue
        t_ms = row.get("t")
        if isinstance(t_ms, int) and t_ms < _RELATIVE_ANCHOR_MS_CEIL:
            continue
        spoken_ms = _spoken_anchor_ms(bits[j], lang, t_ms if isinstance(t_ms, int) else None)
        if spoken_ms is None:
            continue
        if isinstance(item, tuple):
            meta = item[2] if len(item) > 2 and isinstance(item[2], dict) else {}
            anchored[j] = (item[0], spoken_ms, meta)
        elif isinstance(item, dict):
            anchored[j] = {**item, "t": spoken_ms}


def _order_chapter_sentences(
    bits: list[str],
    anchored: list,
    placed: list[dict],
    *,
    from_name: str = "",
    to_name: str = "",
    lang: str = "fr",
) -> None:
    """Les phrases d'un chapitre se disent dans l'ordre STRICT du temps
    du voyage — tri stable par instant d'ancre, l'ouverture (role depart) reste
    en tête, l'arrivée (role arrive) en queue. Les connecteurs de date sont
    recalculés APRÈS, par thin_chapter_dates. Les charIdx des bulles (`placed`)
    suivent leurs phrases. Ne fait rien si bits et ancres ne sont pas alignés
    (chemin sans ancres). RC48 : la colonne d'eaux LR→Ajaccio (premières
    mentions) reste FR → Gascogne → ES → PT → Gibraltar → MA."""
    if len(bits) != len(anchored) or len(bits) < 3:
        return
    keys: list[tuple[int, int, int]] = []
    last_t = 0
    for i, item in enumerate(anchored):
        row = _unpack_anchored(item)
        role = (row.get("role") or "").strip().lower()
        cls = 0 if role == "depart" else (2 if role == "arrive" else 1)
        t = row.get("t")
        t_val = int(t) if t is not None else None
        spoken_ms = (
            _spoken_anchor_ms(bits[i], lang, t_val if t_val is not None else last_t)
            if cls == 1 and i < len(bits) else None
        )
        use_spoken = (
            spoken_ms is not None
            and (t_val is None or t_val >= _RELATIVE_ANCHOR_MS_CEIL)
        )
        sort_t = spoken_ms if use_spoken else None
        if sort_t is None and t is not None:
            sort_t = int(t)
        if sort_t is not None:
            last_t = sort_t
        keys.append((cls, last_t if cls == 1 else 0, i))
    timed = sorted(range(len(bits)), key=lambda i: keys[i])
    order = (
        _apply_spine_first_order(bits, timed)
        if _is_lr_ajaccio_chapter(from_name, to_name)
        else timed
    )
    if order == list(range(len(bits))):
        _sync_anchored_times_from_speech(bits, anchored, lang)
        return
    old_off = _bits_offsets(bits)
    new_bits = [bits[i] for i in order]
    new_off = _bits_offsets(new_bits)
    remap = {old_off[i]: new_off[pos] for pos, i in enumerate(order)}
    for bubble in placed:
        old_idx = bubble.get("charIdx")
        if isinstance(old_idx, int) and old_idx in remap:
            bubble["charIdx"] = remap[old_idx]
    anchored[:] = [anchored[i] for i in order]
    bits[:] = new_bits
    _sync_anchored_times_from_speech(bits, anchored, lang)


def _named_place_coords(name: str, marks: list | None = None) -> Optional[tuple[float, float]]:
    raw = str(name or "").strip()
    if not raw:
        return None
    key = norm_stop(raw)
    geo = _canonical_place_coords(raw)
    mark_pair: Optional[tuple[float, float]] = None
    for mark in marks or []:
        if not isinstance(mark, dict):
            continue
        if key and key in norm_stop(mark.get("name") or ""):
            try:
                mark_pair = (float(mark["lat"]), float(mark["lon"]))
            except (TypeError, ValueError, KeyError):
                continue
            break
    if geo and mark_pair:
        d = _nm_between(geo[0], geo[1], mark_pair[0], mark_pair[1])
        if d is not None and d > 50.0:
            return geo
    if mark_pair:
        return mark_pair
    return geo


def _clock_latlon_at(clock: dict | None, t_ms: Optional[int]) -> Optional[tuple[float, float]]:
    if clock is None or t_ms is None:
        return None
    t0 = _ms(clock.get("t0"))
    best: Optional[tuple[float, float]] = None
    best_dt: Optional[int] = None
    for v in clock.get("vertices") or []:
        if not isinstance(v, dict):
            continue
        t = _ms(v.get("iso"))
        if t is None and t0 is not None and v.get("tHours") is not None:
            try:
                t = t0 + int(float(v["tHours"]) * 3_600_000)
            except (TypeError, ValueError):
                t = None
        if t is None:
            continue
        try:
            lat, lon = float(v["lat"]), float(v["lon"])
        except (TypeError, ValueError, KeyError):
            continue
        dt = abs(int(t) - int(t_ms))
        if best_dt is None or dt < best_dt:
            best, best_dt = (lat, lon), dt
    return best


def _clock_time_near_coords(
    clock: dict | None,
    lat: Any,
    lon: Any,
    t_a: Optional[int],
    t_b: Optional[int],
) -> Optional[int]:
    if clock is None:
        return None
    try:
        plat, plon = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    t0 = _ms(clock.get("t0"))
    best_t: Optional[int] = None
    best_d: Optional[float] = None
    for v in clock.get("vertices") or []:
        if not isinstance(v, dict):
            continue
        t = _ms(v.get("iso"))
        if t is None and t0 is not None and v.get("tHours") is not None:
            try:
                t = t0 + int(float(v["tHours"]) * 3_600_000)
            except (TypeError, ValueError):
                t = None
        if t is None:
            continue
        if t_a is not None and t < t_a:
            continue
        if t_b is not None and t > t_b:
            continue
        d = _nm_between(plat, plon, v.get("lat"), v.get("lon"))
        if d is None:
            continue
        if best_d is None or d < best_d:
            best_d, best_t = d, t
    return best_t


def _clock_time_near_place(
    clock: dict | None,
    place: str,
    t_a: Optional[int],
    t_b: Optional[int],
    marks: list | None = None,
) -> Optional[int]:
    coords = _named_place_coords(place, marks or (clock or {}).get("marks"))
    if coords is None:
        return None
    return _clock_time_near_coords(clock, coords[0], coords[1], t_a, t_b)


def _snap_change_anchor_ms(
    change: dict,
    clock: dict | None,
    t_a: Optional[int],
    t_b: Optional[int],
    marks: list | None = None,
) -> Optional[int]:
    """Instant du jalon sur la trace : le bateau est au lieu quand la phrase le nomme."""
    kind = str(change.get("kind") or "")
    if kind in {"escale", "stop", "approche"}:
        named = change_place_name(change)
        snapped = _clock_time_near_place(clock, named, t_a, t_b, marks) if named else None
        if snapped is not None:
            return int(snapped)
    if kind not in {"coast", "port", "marina", "approche", "escale", "stop"}:
        return change.get("tMs")
    t_ms = change.get("tMs")
    if t_ms is None:
        return None
    place = change_place_name(change)
    snapped = _clock_time_near_place(clock, place, t_a, t_b, marks) if place else None
    if snapped is None and change.get("lat") is not None and change.get("lon") is not None:
        snapped = _clock_time_near_coords(clock, change.get("lat"), change.get("lon"), t_a, t_b)
    if snapped is None:
        return t_ms
    coords = _named_place_coords(place, marks) if place else None
    if coords is None and change.get("lat") is not None and change.get("lon") is not None:
        try:
            coords = (float(change["lat"]), float(change["lon"]))
        except (TypeError, ValueError):
            coords = None
    if coords is None:
        return snapped
    boat_now = _clock_latlon_at(clock, int(t_ms))
    boat_snap = _clock_latlon_at(clock, int(snapped))
    if boat_now is None or boat_snap is None:
        return snapped
    d_now = _nm_between(coords[0], coords[1], boat_now[0], boat_now[1])
    d_snap = _nm_between(coords[0], coords[1], boat_snap[0], boat_snap[1])
    if d_now is not None and d_snap is not None and d_snap + 0.01 < d_now:
        return int(snapped)
    if d_now is not None and d_now > 30.0 and d_snap is not None and d_snap <= 30.0:
        return int(snapped)
    return t_ms


def anchor_moment_changes(rows: list[dict], clock: dict | None) -> None:
    """Recolle tMs des jalons côte/port sur le passage horloge (stock officiel)."""
    if not rows or not clock:
        return
    marks = clock.get("marks") or []
    span = 21 * 86_400_000
    for row in rows:
        t_row = _ms(row.get("t"))
        if t_row is None:
            continue
        t_a, t_b = t_row - span, t_row + span
        for change in row.get("changes") or []:
            if not isinstance(change, dict):
                continue
            if str(change.get("kind") or "") not in {"coast", "port", "marina"}:
                continue
            base = change.get("tMs")
            if base is None:
                base = t_row
            packed = {**change, "tMs": base}
            snapped = _snap_change_anchor_ms(packed, clock, t_a, t_b, marks)
            if snapped is not None and snapped != base:
                change["tMs"] = snapped


def _closest_member_to_boat(
    group: list[dict],
    clock: dict | None,
    spoken_ms: Optional[int],
) -> Optional[dict]:
    """Membre le plus proche du bateau à l'instant où le groupe est dit ; sinon None (éclater)."""
    if not group:
        return None
    boat = _clock_latlon_at(clock, spoken_ms if spoken_ms is not None else group[0].get("tMs"))
    if boat is None:
        return None
    best = None
    best_d: Optional[float] = None
    for member in group:
        d = _nm_between(boat[0], boat[1], member.get("lat"), member.get("lon"))
        if d is None:
            continue
        if best_d is None or d < best_d:
            best, best_d = member, d
    return best


def _relative_lead(prev: Optional[datetime], cur: Optional[datetime], lang: str) -> str:
    if prev and cur:
        try:
            if (cur.date() - prev.date()) == timedelta(days=1):
                return "The next day, " if _en(lang) else "Le lendemain, "
        except (TypeError, ValueError):
            pass
    return "Then, " if _en(lang) else "Puis, "


def _strip_lead_date(text: str, lang: str) -> str:
    rx = _LEAD_DATE_EN_RE if _en(lang) else _LEAD_DATE_FR_RE
    return rx.sub("", text or "", count=1)


_NEXT_DAY_LEAD_RE = re.compile(r"^\s*(?:Le lendemain|The next day)\b", re.I)


def _heard_date_before(out: list[str], k: int, lang: str) -> Optional[datetime]:
    """Date que l'auditeur a en tête juste avant la phrase k.

    Une date dite la remet à jour ; « Le lendemain » l'avance d'un jour ;
    « Puis » la garde. Sans ce suivi, deux « Le lendemain » de suite pour le
    même jour (Nouméa : 6 nov., lendemain, lendemain, arrivée le 7) faisaient
    entendre le 8 novembre, après l'arrivée.
    """
    heard: Optional[datetime] = None
    for j in range(max(0, k)):
        s = out[j] or ""
        if _sentence_has_date(s, lang):
            heard = _parse_spoken_date(s, lang) or heard
        elif heard is not None and _NEXT_DAY_LEAD_RE.match(s):
            heard = heard + timedelta(days=1)
    return heard


_WIND_TURN_RE = re.compile(
    r"\b(?:le vent tourne (?:à l['’]|au |à la )|the wind shifts to the )(?P<dir>[a-zé-]+)", re.I,
)
_WIND_BELT_RE = re.compile(
    r"\b(?:les vents d['’]|les alizés de |les alizés d['’]|the )"
    r"(?P<dir>[a-zé-]+?)(?:erlies|erly trade winds)?\s+(?:s['’]installent|set in)\b",
    re.I,
)


def _wind_dir_key(word: str) -> str:
    return re.sub(r"[^a-zé]", "", (word or "").casefold())


def drop_turn_before_same_belt(sentences: list[str]) -> list[str]:
    """« Puis, le vent tourne à l'ouest : 8 nœuds. Puis, les vents d'ouest s'installent : 12 nœuds. »
    disait deux fois la même bascule (Halifax → Saint-Pierre) : la rotation s'efface devant
    le régime nommé de même direction qui la suit (une ou deux phrases plus loin)."""
    out = list(sentences)
    i = 0
    while i < len(out):
        m = _WIND_TURN_RE.search(out[i] or "")
        if m:
            key = _wind_dir_key(m.group("dir"))
            nxt = out[i + 1:i + 3]
            if key and any(
                (b := _WIND_BELT_RE.search(x or "")) and _wind_dir_key(b.group("dir")) == key
                for x in nxt
            ):
                out.pop(i)
                continue
        i += 1
    return out


_COMMON_LEAD_WORD_RE = re.compile(
    r"^(?:Le|La|Les|L['’]|À|Au|Aux|Un|Une|Des|Du|De|D['’]|Haute|The|A|An|At|High)\b",
)


def drop_repeated_heard_dates(sentences: list[str], lang: str = "fr") -> list[str]:
    """« Le 17 juillet, … quitte Fort-de-France. … Le 17 juillet, à 21 milles, le projet … »
    redisait le jour que l'auditeur a déjà en tête (N11, six étapes du film intégral).
    Une date en tête de phrase égale à la date ENTENDUE (date dite ou « le lendemain »
    déjà compté) devient « Puis, ». Ni la première phrase ni l'arrivée ne bougent.
    """
    out = list(sentences)
    lead_rx = _LEAD_DATE_EN_RE if _en(lang) else _LEAD_DATE_FR_RE
    for k in range(1, len(out)):
        s = out[k] or ""
        if not s or _is_arrival_sentence(s):
            continue
        probe = s if _en(lang) else _digit_fr_dates(s)
        m = lead_rx.match(probe)
        if not m or re.search(r"\d{4}$", m.group(1)):
            continue
        heard = _heard_date_before(out, k, lang)
        cur = _parse_spoken_date(probe[: m.end()], lang)
        if heard is None or cur is None:
            continue
        if (heard.month, heard.day) != (cur.month, cur.day):
            continue
        body = probe[m.end():]
        if not body:
            continue
        lead = "Then, " if _en(lang) else "Puis, "
        if _COMMON_LEAD_WORD_RE.match(body):
            body = body[0].lower() + body[1:]
        out[k] = lead + body
    return out


def thin_chapter_dates(sentences: list[str], lang: str = "fr") -> list[str]:
    """Au plus une date calendaire toutes les deux phrases. L'arrivée garde sa date."""
    out = drop_turn_before_same_belt([scrub_spoken(s) for s in sentences])
    dated = [_sentence_has_date(s, lang) for s in out]
    i = 1
    while i < len(out):
        if dated[i] and dated[i - 1]:
            if i - 1 == 0 and _is_arrival_sentence(out[i]):
                # Ouverture + arrivée : les deux dates restent (la passe de
                # densité garde déjà l'une et l'autre). Sinon « Puis, le
                # catamaran reprend la mer » perdait le 29 août dans la 2:30.
                i += 1
                continue
            if _is_arrival_sentence(out[i]):
                # La phrase i-1 perd SA date — « Le lendemain » se mesure
                # contre la date ENTENDUE avant elle (dates dites et
                # « lendemain » déjà posés), pas contre l'arrivée.
                prev_d = _heard_date_before(out, i - 1, lang)
                cur_d = _parse_spoken_date(out[i - 1], lang)
                body = _strip_lead_date(out[i - 1], lang)
                if body == out[i - 1]:
                    body = (_DATE_EN_RE if _en(lang) else _DATE_FR_RE).sub("", out[i - 1], count=1)
                    body = re.sub(r"\s{2,}", " ", body).replace("Le ,", "Puis,").strip()
                else:
                    body = _relative_lead(prev_d, cur_d, lang) + body[0].lower() + body[1:] if body else out[i - 1]
                out[i - 1] = body[0].upper() + body[1:] if body else out[i - 1]
                dated[i - 1] = False
            else:
                prev_d = _heard_date_before(out, i, lang)
                cur_d = _parse_spoken_date(out[i], lang)
                body = _strip_lead_date(out[i], lang)
                if body != out[i]:
                    lead = _relative_lead(prev_d, cur_d, lang)
                    out[i] = lead + (body[0].lower() + body[1:] if body else "")
                    if out[i] and not out[i].endswith((".", "!", "?", "…")):
                        pass
                dated[i] = False
        i += 1
    # Deuxième passe : densité globale ≤ 1 date / 2 phrases (ouverture et arrivée gardées).
    while True:
        dated = [_sentence_has_date(s, lang) for s in out]
        if date_density_ok(" ".join(out), lang):
            break
        drop = next(
            (
                j for j in range(1, len(out) - 1)
                if dated[j] and not _is_arrival_sentence(out[j])
            ),
            None,
        )
        if drop is None:
            break
        body = _strip_lead_date(out[drop], lang)
        if body == out[drop]:
            break
        lead = "Puis, " if not _en(lang) else "Then, "
        out[drop] = lead + (body[0].lower() + body[1:] if body else "")
    # Après l'alternance : seules les dates qui redisent le jour entendu tombent (N11).
    out = drop_repeated_heard_dates(out, lang)
    kept = [s for s in out if s]
    if _en(lang):
        return [fix_en_waters_casing(s) for s in kept]
    return kept


def _year_insertions(texts: list[str], lang: str = "fr") -> list[list[tuple[int, str]]]:
    """Positions où dire l'année : la première date après le passage du 31 décembre.

    « Le 3 janvier, Berry-Mappemonde quitte Dzaoudzi » suivait « le 31 décembre » sans
    année : un juge croyait tout le film en 2026 (N14). Seule une date écrite (« le 15 mai
    2026 ») fixe l'année de départ ; sans elle, rien n'est ajouté. Le passage se lit à un
    mois qui recule d'au moins six (décembre → janvier), jamais à un petit retour en arrière.
    """
    rx = _DATE_EN_RE if _en(lang) else _DATE_FR_RE
    months = [m.casefold() for m in MONTHS["en" if _en(lang) else "fr"]]
    year: Optional[int] = None
    prev: Optional[tuple[int, int]] = None
    out: list[list[tuple[int, str]]] = []
    for text in texts:
        ins: list[tuple[int, str]] = []
        for m in rx.finditer(text or ""):
            key = str(m.group(2)).casefold()
            if key not in months:
                continue
            mo = months.index(key) + 1
            day_s = str(m.group(1))
            try:
                day = 1 if day_s.lower() == "1er" else int(day_s)
            except ValueError:
                continue
            y_m = re.search(r"(\d{4})$", m.group(0))
            if y_m:
                year = int(y_m.group(1))
            elif year is not None and prev is not None and prev[0] - mo >= 6:
                year += 1
                ins.append((m.end(), f" {year}"))
            prev = (mo, day)
        out.append(ins)
    return out


def _apply_insertions(text: str, ins: list[tuple[int, str]]) -> str:
    for pos, add in sorted(ins, reverse=True):
        text = text[:pos] + add + text[pos:]
    return text


def mark_year_changes(chapters: list[dict], lang: str = "fr") -> list[dict]:
    """Ajoute l'année au passage du nouvel an, ancres et événements décalés d'autant."""
    rows = [c for c in chapters if isinstance(c, dict)]
    plan = _year_insertions([str(c.get("text") or "") for c in rows], lang)
    for ch, ins in zip(rows, plan):
        if not ins:
            continue
        ch["text"] = _apply_insertions(str(ch.get("text") or ""), ins)
        for key in ("anchors", "events"):
            for item in ch.get(key) or []:
                if not isinstance(item, dict):
                    continue
                try:
                    idx = int(item.get("charIdx"))
                except (TypeError, ValueError):
                    continue
                item["charIdx"] = idx + sum(len(add) for pos, add in ins if pos <= idx)
    return chapters


def date_density_ok(text: str, lang: str = "fr") -> bool:
    sents = _sentences(text)
    if not sents:
        return True
    n_dates = sum(1 for s in sents if _sentence_has_date(s, lang))
    return n_dates * 2 <= len(sents) + 1


_AMP_OR_PROJECT_SENT = re.compile(
    r"aire marine|marine protected area|le projet |project ",
    re.I,
)
_WATERS_SENT = re.compile(
    r"eaux |waters|haute mer|high seas",
    re.I,
)
# P1/P2 : ouverture, escales, cap — pas les côtes / climo / stations, pas les eaux en trop.
_CORE_KEEP_SENT = re.compile(
    r"arriv|Berry-Mappemonde|quitte|leaves |jours de mer|days at sea|"
    r"nœuds de moyenne|knots on average|amarré|moored|d['’]escale|stopover|"
    r"départ|departure|left |quitté|approche|approaching|avion|flies|flight|"
    r"envole|par la route|by road|attend à|waits at|aujourd|today|"
    r"expédition|expedition|escales|stops|destination|entre le |between |"
    r"à venir|still to come|le plan compte|the plan has|"
    r"cap au |cap sur |heading |"
    # Ouverture du second bateau (Halifax ↔ Saint-Pierre) : jamais une redite.
    r"second voilier|second sailing boat|embarque sur|boards |sails again on|l['’]équipage reprend",
    re.I,
)
_KEEP_SENT = re.compile(
    r"aire marine|marine protected area|le projet |project |"
    r"arriv|Berry-Mappemonde|quitte|leaves |jours de mer|days at sea|"
    r"nœuds de moyenne|knots on average|amarré|moored|d['’]escale|stopover|"
    r"départ|departure|left |quitté|approche|approaching|avion|flies|flight|"
    r"envole|par la route|by road|attend à|waits at|aujourd|today|"
    r"expédition|expedition|escales|stops|destination|entre le |between |"
    r"à venir|still to come|le plan compte|the plan has|"
    r"cap au |cap sur |heading ",
    re.I,
)

# Galice (Muxía, Camariñas) et Sardaigne ne cèdent pas la place aux eaux.
_RG2_LANDMARK_SENT = re.compile(
    r"Galice|Galicia|Mux[ií]a|Camari[nñ]as|Sardaigne|Sardinia|Porto Torres",
    re.I,
)


def _trim_sentence_rank(sent: str) -> int:
    """0 = ne jamais retirer (AMP, projet, ouverture, escales).
    1 = eaux (seulement en trop, après P3/P4).
    2 = P3/P4 (côtes, climo, stations) et le reste — d'abord.
    """
    s = sent or ""
    if _AMP_OR_PROJECT_SENT.search(s) or _CORE_KEEP_SENT.search(s) or _RG2_LANDMARK_SENT.search(s):
        return 0
    if _WATERS_SENT.search(s):
        return 1
    return 2


def _drop_over_budget_sentence(sents: list[str], *, keep_head: int = 0) -> bool:
    """Retire une phrase entière : P3/P4 d'abord, puis une eau en trop. Jamais au milieu."""
    if len(sents) <= keep_head:
        return False
    best_i: Optional[int] = None
    best_rank = 0
    start = min(keep_head, len(sents))
    for i in range(len(sents) - 1, start - 1, -1):
        rank = _trim_sentence_rank(sents[i])
        if rank > best_rank:
            best_rank = rank
            best_i = i
            if rank >= 2:
                break
    if best_i is None or best_rank <= 0:
        return False
    sents.pop(best_i)
    return True


def _count_amp_project(chapters: list[dict]) -> tuple[int, int]:
    amp = proj = 0
    for ch in chapters:
        for s in _sentences(ch.get("text") or ""):
            if re.search(r"aire marine|marine protected area", s or "", re.I):
                amp += 1
            if re.search(r"le projet |project ", s or "", re.I):
                proj += 1
    return amp, proj


def _drop_extra_amp_or_project(
    sents: list[str], amp_n: int, proj_n: int, *, keep_head: int = 0,
) -> bool:
    """Retire une AMP ou un projet en trop — jamais l'unique, jamais au milieu."""
    if len(sents) <= keep_head:
        return False
    start = min(keep_head, len(sents))
    for i in range(len(sents) - 1, start - 1, -1):
        s = sents[i] or ""
        is_amp = bool(re.search(r"aire marine|marine protected area", s, re.I))
        is_proj = bool(re.search(r"le projet |project ", s, re.I))
        if is_amp and amp_n > 1:
            sents.pop(i)
            return True
        if is_proj and proj_n > 1 and not is_amp:
            sents.pop(i)
            return True
    return False


def _trim_script_to_char_budget(
    chapters: list[dict], hi: int, *, keep_head: int = 2,
) -> None:
    """P3/P4 d'abord, puis eaux en trop ; AMP/projet uniques jamais retirés."""
    guard = 0
    while script_chars(chapters) > hi and chapters and guard < 200:
        dropped = False
        for ch in reversed(chapters):
            sents = _sentences(ch.get("text") or "")
            if _drop_over_budget_sentence(sents, keep_head=keep_head):
                ch["text"] = " ".join(sents).strip()
                dropped = True
                break
        if not dropped:
            amp_n, proj_n = _count_amp_project(chapters)
            for ch in reversed(chapters):
                sents = _sentences(ch.get("text") or "")
                if _drop_extra_amp_or_project(sents, amp_n, proj_n, keep_head=keep_head):
                    ch["text"] = " ".join(sents).strip()
                    dropped = True
                    break
        if not dropped:
            break
        guard += 1


def _keep_one_amp_in_script(chapters: list[dict]) -> None:
    """2:30 : une seule phrase d'aire. On n'explique pas une seconde fois."""
    amp_n, _proj = _count_amp_project(chapters)
    guard = 0
    while amp_n > 1 and guard < 20:
        dropped = False
        for idx in range(len(chapters) - 1, -1, -1):
            keep = 1 if idx == 0 else 0
            sents = _sentences(chapters[idx].get("text") or "")
            if _drop_extra_amp_or_project(sents, amp_n, 1, keep_head=keep):
                chapters[idx]["text"] = " ".join(sents).strip()
                dropped = True
                break
        if not dropped:
            break
        amp_n, _proj = _count_amp_project(chapters)
        guard += 1


_FILM_STRUCTURE_OPEN_RE = re.compile(
    r"quitte|quitté|leaves|left |s['’]envole|flies |par la route|by road|"
    r"expédition|expedition|reprend la mer|sets sail again|départ vers|departure for",
    re.I,
)
_FILM_STRUCTURE_ARRIVAL_RE = re.compile(r"Arrivée à|Arrival at", re.I)
_FILM_STRUCTURE_TODAY_RE = re.compile(r"Aujourd|Today,", re.I)
_FILM_STRUCTURE_AIR_RE = re.compile(
    r"s['’]envole|flies from|the crew flies|prend l['’]avion|return flight|attend à|"
    r"second voilier|second sailing boat|embarque sur",
    re.I,
)


def _chapter_structure_fault_sentence(text: str, lang: str) -> str | None:
    """Même règle que test_film_discours._structure_fault (ouverture avant arrivée)."""
    sents = _sentences(text)
    if not sents:
        return "(chapitre vide)"
    if _FILM_STRUCTURE_AIR_RE.search(text):
        return None
    open_i = next((i for i, s in enumerate(sents) if _FILM_STRUCTURE_OPEN_RE.search(s)), None)
    if open_i is None:
        return sents[0]
    close_i = next(
        (
            i for i, s in enumerate(sents)
            if _FILM_STRUCTURE_ARRIVAL_RE.search(s) or _FILM_STRUCTURE_TODAY_RE.search(s)
        ),
        None,
    )
    if close_i is None:
        return sents[0]
    if close_i < open_i:
        return sents[close_i]
    return None


def _prepend_film_opens_to_chapter(
    chapter: dict,
    opens: list[str],
    t_a: int,
    t_b: int,
    lang: str,
) -> None:
    if not opens:
        return
    text = (chapter.get("text") or "").strip()
    head = " ".join(opens).strip()
    if not head or head in text:
        return
    if _chapter_structure_fault_sentence(text, lang) is None:
        return
    old = text
    new_text = speak_film_text(f"{head} {old}".strip(), lang)
    at = new_text.find(old)
    shift = at if at >= 0 else len(new_text) - len(old)
    open_anchored = [(sent, t_a, {"role": "depart"}) for sent in opens]
    open_anchors = chapter_anchors(head, open_anchored, t_a, t_b, lang)
    shifted: list[dict] = []
    for a in chapter.get("anchors") or []:
        if not isinstance(a, dict):
            continue
        row = dict(a)
        row["charIdx"] = int(row.get("charIdx") or 0) + shift
        shifted.append(row)
    merged = open_anchors + shifted
    merged.sort(key=lambda r: (int(r.get("charIdx") or 0), str(r.get("t") or "")))
    chapter["text"] = new_text
    chapter["anchors"] = merged


def _drop_degenerate_chapters(chapters: list[dict]) -> list[dict]:
    """Jambe from==to sans vol ni escale : ne pas laisser un seul « départ vers »."""
    kept: list[dict] = []
    for ch in chapters:
        if same_stop(ch.get("fromName") or "", ch.get("toName") or ""):
            text = ch.get("text") or ""
            if _FILM_STRUCTURE_AIR_RE.search(text):
                kept.append(ch)
                continue
            sents = _sentences(text)
            if len(sents) <= 1 and not _FILM_STRUCTURE_ARRIVAL_RE.search(text):
                continue
        kept.append(ch)
    return kept


def _finalize_chapter_zero_opens(
    chapters: list[dict],
    windows: list[dict],
    *,
    start_name: str,
    sea_name: str,
    lang: str,
    display_t0: str | None,
    review: dict | None,
    seconds: Any,
) -> None:
    """Après budget : le chapitre 0 garde l'ouverture (RG10 / variante 2:30)."""
    if not chapters or not windows:
        return
    w0 = windows[0]
    opens = _film_open_sentences(
        start_name=start_name,
        sea_name=sea_name,
        lang=lang,
        display_t0=display_t0,
        review=review,
        compact=_film_compact_template(seconds),
    )
    _prepend_film_opens_to_chapter(chapters[0], opens, w0["tA"], w0["tB"], lang)


# 3:00 (gabarit RG6 long) : presque tout est au rang 0, donc rien n'est coupable
# et le film brut restait à ~3 450 car. pour 2 700. On raccourcit des incises
# de rang 0 sans retirer de phrase ni de fait de jambe (lieu, date, milles) :
# l'amarrage (« , amarré au port de … »), la vitesse moyenne de gabarit, puis
# les tournures de forme (« la longue traversée vers », « d'île en île, »).
_RANK0_TRIMS = (
    re.compile(r",\s*(?:amarré|amarrée|moored)\s+(?:au|à la|à l['’]|à|aux|at)\s+[^.;!?]*(?=[.;!?])", re.I),
    re.compile(r",\s*(?:à \d+ nœuds de moyenne|at \d+ knots on average)(?=[.;!?])", re.I),
    re.compile(r"(?:(?<=milles)|(?<=miles)), (?:jusqu['’]à|through to) [^.;!?]*(?=[.;!?])", re.I),
    re.compile(r"\b(?:la longue traversée vers|the long crossing to)\s+", re.I),
    re.compile(r"(?<=, )(?:d['’]île en île|pour la dernière étape|from island to island|for the last stage),\s+", re.I),
)


def _compact_rank0_to_budget(chapters: list[dict], target: int) -> None:
    """Retire des incises de rang 0, une par une depuis la fin, jusqu'au plafond."""
    for rx in _RANK0_TRIMS:
        for ch in reversed(chapters):
            if script_chars(chapters) <= target:
                return
            text = ch.get("text") or ""
            new = rx.sub("", text)
            if new != text:
                ch["text"] = re.sub(r"\s{2,}", " ", new).strip()


def _film_apply_char_budget(chapters: list[dict], seconds: Any) -> None:
    """Plafond film_char_budget (15 car./s), pas 110 %. 2:30 : keep_head=1."""
    target = film_char_budget(seconds)
    if target <= 0 or not chapters:
        return
    keep = 1 if _film_compact_template(seconds) else 2
    if _film_compact_template(seconds):
        _keep_one_amp_in_script(chapters)
    _trim_script_to_char_budget(chapters, target, keep_head=keep)
    if _film_compact_template(seconds):
        _relative_day_to_then(chapters)
    if script_chars(chapters) > target and not _film_compact_template(seconds):
        _compact_rank0_to_budget(chapters, target)
        _trim_script_to_char_budget(chapters, target, keep_head=keep)


def fit_chapter_text(text: str, budget: int, extras: list[str], lang: str) -> str:
    """Assemble le chapitre. Jamais de phrase de remplissage. Budget = plafond, pas un plancher.

    Au-dessus du plafond : on retire des phrases entières, P3/P4 d'abord (côtes,
    climo, stations), puis des eaux en trop — jamais une AMP ni un projet, jamais
    au milieu d'une phrase.
    """
    blob = re.sub(r"\s{2,}", " ", (text or "").strip())
    for bit in extras:
        if bit and bit not in blob:
            blob = f"{blob} {bit}".strip()
    cap = int(budget or 0)
    if cap > 0:
        hi = max(int(cap * 1.1), cap)
        while len(blob) > hi:
            sents = _sentences(blob)
            if not _drop_over_budget_sentence(sents, keep_head=2):
                break
            blob = " ".join(sents).strip()
    blob = speak_film_text(split_short_sentences(blob), lang)
    blob = " ".join(thin_chapter_dates(_sentences(blob), lang))
    return blob


def chapter_anchors(text: str, anchored: list, t_a: int, t_b: int, lang: str) -> list[dict]:
    """[{charIdx, t}] : nœud dans le texte FINAL → instant du trajet (ISO).

    RG14 / D1 : l'ancre d'un lieu est l'index du nom (− avance voix 12 car., bornée à 0) ;
    une phrase de durée a deux ancres (arrivée au début, départ à la fin) ; un départ
    s'ancre au premier mot, une arrivée au dernier. Instants bornés à [tA, tB],
    croissants. Les phrases coupées par le budget n'ont pas d'ancre.
    """
    out: list[tuple[int, int, str, str]] = []
    if not text or not anchored:
        return []
    search_from = 0
    for item in anchored:
        row = _unpack_anchored(item)
        raw_sent = (row["sentence"] or "").strip()
        if not raw_sent or row["t"] is None:
            continue
        spoken = speak_film_text(raw_sent, lang)
        blob_idx = _locate_spoken(text, spoken, search_from)
        if blob_idx < 0:
            blob_idx = _locate_spoken(text, spoken, 0)
        if blob_idx < 0:
            continue
        search_from = blob_idx + 1
        t = int(row["t"])
        t_end = int(row["t_end"]) if row["t_end"] is not None else t
        if t_a is not None:
            t = max(int(t_a), t)
            t_end = max(int(t_a), t_end)
        if t_b is not None:
            t = min(int(t_b), t)
            t_end = min(int(t_b), t_end)
        if t_end < t:
            t_end = t
        role = (row["role"] or "").strip().lower()
        place = row["place"]
        kind = row["kind"]
        parts = _sentences(spoken) or [spoken]
        cursor = blob_idx
        for part in parts:
            part_idx = text.find(part, cursor)
            if part_idx < 0:
                part_idx = _locate_spoken(text, part, cursor)
            if part_idx < 0:
                part_idx = cursor
            cursor = part_idx + max(1, len(part) // 2)
            part_t = t
            spoken_ms = _spoken_anchor_ms(part, lang, t)
            absolute_window = t_b is None or int(t_b) >= _RELATIVE_ANCHOR_MS_CEIL
            if spoken_ms is not None and absolute_window:
                part_t = int(spoken_ms)
                if t_a is not None:
                    part_t = max(int(t_a), part_t)
                if t_b is not None:
                    part_t = min(int(t_b), part_t)
            if role == "depart" or (not role and _is_depart_sentence(part) and not _is_arrival_sentence(part)):
                idx = _voice_lookahead_idx(_first_word_idx(part, part_idx))
                out.append((idx, part_t, place, kind or "depart"))
                continue
            if _is_duration_sentence(part):
                start = _voice_lookahead_idx(_first_word_idx(part, part_idx), part_idx)
                end = _voice_lookahead_idx(_end_idx(part, part_idx), part_idx)
                out.append((start, part_t, place, kind or "escale"))
                if end > start:
                    out.append((end, t_end, place, kind or "escale"))
                continue
            if role == "arrive" or _is_arrival_sentence(part):
                idx = _voice_lookahead_idx(_last_word_idx(part, part_idx), part_idx)
                out.append((idx, part_t, place, kind or "escale"))
                continue
            idx = _voice_lookahead_idx(_place_idx_in_sentence(part, part_idx, place), part_idx)
            out.append((idx, part_t, place, kind))
    out.sort(key=lambda p: p[0])
    result: list[dict] = []
    last_t: Optional[int] = None
    for idx, t, place, kind in out:
        if last_t is not None and t < last_t:
            t = last_t
        last_t = t
        if result and result[-1]["charIdx"] == idx:
            result[-1]["t"] = _iso(t)
            if place and not result[-1].get("place"):
                result[-1]["place"] = place
            if kind and not result[-1].get("kind"):
                result[-1]["kind"] = kind
            continue
        row_out: dict = {"charIdx": idx, "t": _iso(t)}
        if place:
            row_out["place"] = place
        if kind:
            row_out["kind"] = kind
        result.append(row_out)
    return result


def _reanchor_edited_chapter(ch: dict, lang: str) -> None:
    """Move existing sentence anchors onto the final edited chapter text."""
    original = str(ch.get("_anchorText") or "")
    final = str(ch.get("text") or "")
    anchors = ch.get("anchors") or []
    if not original or not anchors:
        # Without the source text, there is no safe way to validate offsets.
        ch["anchors"] = []
        ch["_anchorText"] = final
        return
    sentences = _sentences(original)
    spans: list[tuple[int, int, str]] = []
    cursor = 0
    for sentence in sentences:
        start = original.find(sentence, cursor)
        if start < 0:
            continue
        end = start + len(sentence)
        spans.append((start, end, sentence))
        cursor = end
    anchored: list[tuple[str, Any]] = []
    final_sentences = _sentences(final)
    for anchor in anchors:
        if not isinstance(anchor, dict) or anchor.get("t") is None:
            continue
        try:
            idx = int(anchor.get("charIdx") or 0)
        except (TypeError, ValueError, OverflowError):
            continue
        # chapter_anchors stores a voice-lookahead position (12 characters
        # before the spoken place), so resolve the anchor to its sentence at
        # the corresponding spoken position.
        sentence_idx = min(len(original) - 1, idx + FILM_VOICE_LOOKAHEAD_CHARS)
        sentence_span = next(((a, b, s) for a, b, s in spans if a <= sentence_idx < b), None)
        sentence = sentence_span[2] if sentence_span else None
        # If the lookahead crosses a sentence boundary, the original anchor
        # cannot be attributed safely. Also drop duplicate sentences when the
        # final text has a different occurrence count: the surviving copy
        # cannot be distinguished from the removed one by text alone.
        if sentence_span and not (sentence_span[0] <= idx < sentence_span[1]):
            sentence = None
        if sentence:
            normalized = speak_film_text(sentence, lang)
            original_count = sum(speak_film_text(s, lang) == normalized for _, _, s in spans)
            final_count = sum(speak_film_text(s, lang) == normalized for s in final_sentences)
            # A sentence can be attributed to its anchor by text alone only
            # when it has one unambiguous occurrence on both sides. Equal
            # duplicate counts are not enough: edits may have reordered them.
            if original_count != 1 or final_count != 1:
                sentence = None
        anchor_t = _ms(anchor["t"])
        if sentence and anchor_t is not None and _locate_spoken(final, speak_film_text(sentence, lang), 0) >= 0:
            anchored.append((sentence, anchor_t))
    ch["anchors"] = chapter_anchors(final, anchored, _ms(ch.get("tA")), _ms(ch.get("tB")), lang)
    ch["_anchorText"] = final


def _trim_free_script(chapters: list[dict], max_words: int = FILM_FREE_MAX_WORDS) -> list[dict]:
    guard = 0
    while script_words(chapters) > max_words and guard < 200:
        guard += 1
        dropped = False
        for ch in reversed(chapters):
            sents = _sentences(ch.get("text") or "")
            if _drop_over_budget_sentence(sents, keep_head=1):
                ch["text"] = " ".join(sents).strip()
                dropped = True
                break
        if not dropped:
            break
    return chapters


_AIR_OUT_RE = re.compile(
    r"s['’]envole de Cayenne|prend l['’]avion pour Halifax|the crew flies from Cayenne|flies to Halifax",
    re.I,
)
_AIR_BACK_RE = re.compile(
    r"s['’]envole (?:de |d['’])Halifax|prend l['’]avion pour Cayenne|flies from Halifax|"
    r"retour en avion vers Cayenne|return flight to Cayenne",
    re.I,
)


def _route_has_air_pair(marks: list | None, moments: list | None = None) -> bool:
    keys = {_air_stop_key(m.get("name") or "") for m in (marks or []) if isinstance(m, dict)}
    if "cayenne" in keys and ("halifax" in keys or "saint-pierre" in keys):
        return True
    for row in moments or []:
        if not isinstance(row, dict):
            continue
        moment = row.get("moment") if isinstance(row.get("moment"), dict) else {}
        leg = moment.get("leg") if isinstance(moment.get("leg"), dict) else {}
        if _is_air_leg(str(leg.get("from") or ""), str(leg.get("to") or "")) or leg.get("vehicle") == "plane":
            return True
    return False


def _air_place_name(marks: list | None, key: str, fallback: str) -> str:
    for m in marks or []:
        if isinstance(m, dict) and _air_stop_key(m.get("name") or "") == key:
            return short_name(m.get("name") or fallback)
    return fallback


def _air_pair_sentences(marks: list | None, lang: str) -> tuple[str, str]:
    cayenne = _air_place_name(marks, "cayenne", "Cayenne (Guyane)")
    halifax = _air_place_name(marks, "halifax", "Halifax (Nouvelle-Écosse)")
    outbound = _air_window_sentence(
        {
            "from": {"name": cayenne}, "fromName": cayenne,
            "destName": halifax, "mode": "air", "vehicle": "plane",
        },
        lang=lang,
    )
    back = _air_window_sentence(
        {
            "from": {"name": halifax}, "fromName": halifax,
            "destName": cayenne, "mode": "air", "vehicle": "plane",
        },
        lang=lang,
    )
    return outbound, back


def _chapter_for_air_leg(chapters: list[dict], origin: str, dest: str) -> dict | None:
    """Chapitre vol dont from/to correspond à cette jambe — jamais le premier Cayenne par défaut."""
    for ch in chapters:
        if (
            _air_stop_key(ch.get("fromName") or "") == origin
            and _air_stop_key(ch.get("toName") or "") == dest
        ):
            return ch
    return None


def _chapter_for_air_fallback(chapters: list[dict]) -> dict | None:
    """Pas de jambe vol (Halifax sans iso) — un seul chapitre Cayenne, jamais la reprise."""
    for ch in chapters:
        frm = _air_stop_key(ch.get("fromName") or "")
        to = _air_stop_key(ch.get("toName") or "")
        if frm == "cayenne" and to != "papeete":
            return ch
    for ch in chapters:
        if _air_stop_key(ch.get("toName") or "") == "cayenne":
            return ch
    for ch in chapters:
        blob = f"{ch.get('text') or ''} {ch.get('fromName') or ''} {ch.get('toName') or ''}"
        if re.search(r"cayenne", blob, re.I) and _air_stop_key(ch.get("toName") or "") != "papeete":
            return ch
    return None


def _chapter_for_air(chapters: list[dict]) -> dict | None:
    """Aller Cayenne→Halifax s'il existe ; sinon un seul repli Cayenne (pas les deux vols)."""
    return _chapter_for_air_leg(chapters, "cayenne", "halifax") or _chapter_for_air_fallback(chapters)


def _inject_sentence_before_close(chapter: dict | None, sentence: str, lang: str) -> None:
    if not chapter or not sentence:
        return
    text = chapter.get("text") or ""
    if sentence in text:
        return
    sents = _sentences(text)
    close = ""
    if sents and re.search(r"aujourd|today", sents[-1] or "", re.I):
        close = sents.pop()
        text = " ".join(sents).strip()
    blob = f"{text} {sentence}".strip()
    if close:
        blob = f"{blob} {close}".strip()
    chapter["text"] = speak_film_text(blob, lang)


def _ensure_air_sentences(
    chapters: list[dict],
    *,
    marks: list | None,
    moments: list | None,
    lang: str,
) -> list[dict]:
    """Après fusion / budget : chaque phrase avion manquante va dans SON chapitre from/to."""
    if not chapters or not _route_has_air_pair(marks, moments):
        return chapters
    outbound, back = _air_pair_sentences(marks, lang)
    out_ch = _chapter_for_air_leg(chapters, "cayenne", "halifax")
    back_ch = _chapter_for_air_leg(chapters, "halifax", "cayenne")
    blob = " ".join(c.get("text") or "" for c in chapters)
    if outbound and out_ch and not _AIR_OUT_RE.search(out_ch.get("text") or ""):
        _inject_sentence_before_close(out_ch, outbound, lang)
    elif outbound and not out_ch and not _AIR_OUT_RE.search(blob):
        fallback = _chapter_for_air_fallback(chapters)
        if fallback is not None and fallback is not back_ch:
            _inject_sentence_before_close(fallback, outbound, lang)
    if (
        back
        and back_ch
        and back_ch is not out_ch
        and not _AIR_BACK_RE.search(back_ch.get("text") or "")
    ):
        _inject_sentence_before_close(back_ch, back, lang)
    return chapters


def _air_bits_from_moments(
    moments: list[dict],
    w: dict,
    *,
    i: int,
    lang: str,
    display_t0: str | None,
    already: str,
) -> list[str]:
    """Le vol est une fenêtre typée, plus un ajout en queue de chapitre."""
    return []


def _climo_from_clock(clock: dict | None, t_a: int, t_b: int, first: bool) -> list[dict]:
    """Bascule d'horloge dans la fenêtre du chapitre — source unique pour la voix."""
    out: list[dict] = []
    for ev in notable_climo_changes(clock or {}):
        t = _ms(ev.get("t") or ev.get("iso"))
        if t is None:
            continue
        if first:
            if t < t_a or t > t_b:
                continue
        elif t <= t_a or t > t_b:
            continue
        change = {**ev, "tMs": t, "id": str(ev.get("id") or f"climo:{ev.get('event')}:{t}")}
        if change_is_speakable(change):
            out.append(change)
    return out


def _leg_key(name: Any) -> str:
    return norm_stop(re.split(r"\s*\(", str(name or ""))[0].strip())


def _moment_leg_ends(m: dict) -> tuple[str, str]:
    leg = (m.get("moment") or {}).get("leg") if isinstance(m.get("moment"), dict) else None
    leg = leg or {}
    return _leg_key(leg.get("from")), _leg_key(leg.get("to"))


def _align_moments_to_window(moments: list[dict], w: dict, depart_ms: Optional[int]) -> list[dict]:
    """Rattache les moments à la fenêtre par l'identité de leur jambe (départ → arrivée),
    pas par la seule date.

    Le journal des moments et l'horloge peuvent venir de deux simulations (magasin
    figé : horloge du 27/09, moments du 15/10). Leurs calendriers divergent de
    plusieurs jours : couper par date seule versait les eaux de Samoa ou Tonga dans
    Cayenne → Papeete. Un moment qui porte sa jambe ne parle que dans la fenêtre de
    la même jambe ; ses dates sont reportées proportionnellement dans cette fenêtre.
    Les moments sans jambe gardent le découpage par date, avec un contrôle
    géographique dès que la fenêtre possède une géométrie connue.
    """
    frm, dest = _leg_key(w.get("fromName")), _leg_key(w.get("destName") or w.get("toName"))
    t_a, t_b = w.get("tA"), w.get("tB")
    points = []
    for v in ((w.get("clock") or {}).get("vertices") or []):
        if not isinstance(v, dict) or v.get("vehicle") in {"plane", "land"}:
            continue
        t = _ms(v.get("iso"))
        if t is None or t_a is None or t_b is None or not t_a <= t <= t_b:
            continue
        pair = _row_latlon(v)
        if pair:
            points.append(pair)
    for prefix in ("from", "to"):
        pair = _row_latlon(w.get(prefix)) or _as_latlon(w.get(f"{prefix}Lat"), w.get(f"{prefix}Lon"))
        if pair:
            points.append(pair)
    free: list[dict] = []
    mine: list[tuple[int, dict]] = []
    for m in moments:
        if not isinstance(m, dict):
            continue
        mf, mt = _moment_leg_ends(m)
        if not mf and not mt:
            pair = _row_latlon(m)
            if not points or (pair and any(_nm_between(*pair, *p) <= 300 for p in points)):
                free.append(m)
            continue
        if frm and dest and mf == frm and mt == dest:
            t = _change_t(m)
            if t is not None:
                mine.append((t, m))
    if not mine or t_a is None or t_b is None:
        return free
    lo = max(int(depart_ms or t_a), int(t_a))
    g0, g1 = min(t for t, _ in mine), max(t for t, _ in mine)
    if lo < g0 and g1 <= t_b:
        return free + [m for _, m in mine]
    span = max(1, g1 - g0)
    out = list(free)
    for t, m in mine:
        nt = lo + int((t - g0) * (t_b - lo) / span) if g1 > g0 else (lo + t_b) // 2
        nt = min(max(nt, int(t_a) + 1), int(t_b))
        row = {**m, "t": _iso(nt), "tSim": m.get("t")}
        if isinstance(m.get("moment"), dict):
            row["moment"] = {**m["moment"], "t": _iso(nt)}
        out.append(row)
    return out


def build_raw_from_moments(
    clock: dict | None,
    marks: list | None,
    live: dict | None,
    journal: dict | None,
    *,
    lang: str = "fr",
    seconds: int = 150,
    now_ms: Optional[int] = None,
    display_t0: str | None = None,
    review: dict | None = None,
    eta: dict | None = None,
) -> dict[str, Any]:
    moments = _journal_moments(journal)
    now = now_ms if now_ms is not None else int(datetime.now(timezone.utc).timestamp() * 1000)
    packed = film_candidates(journal, marks, clock, live, now)
    t0, t_end = packed["t0"], packed["tEnd"]
    if t0 is None or t_end is None or t_end <= t0:
        return {"chapters": [], "source": "rules", "chars": 0, "targetSeconds": _film_seconds(seconds), "_fromMoments": True}
    start_name = short_name((packed["start"] or {}).get("name") or "Saint-Maur")
    sea_name = short_name((packed["sea"] or {}).get("name") or "La Rochelle")
    windows = _annotate_episode_windows(
        _windows(packed["stops"], t0, t_end, clock),
        clock=clock, marks=marks, moments=moments, lang=lang,
    )
    has_budget = _film_seconds(seconds) > 0
    budget_s = _film_seconds(seconds)
    compact = _film_compact_template(seconds)
    tier = film_priority_tier(seconds)
    if has_budget:
        # Plafond = durée × 15 car./s (pas FILM_BUDGET_CHARS identique pour 150 et 180).
        target = film_char_budget(budget_s)
        days = [max(1.0, (w["tB"] - w["tA"]) / 86_400_000.0) for w in windows]
        budgets = allocate_chapter_budgets(days, target)
    else:
        target = 0
        budgets = [0] * len(windows)
    en = _en(lang)
    cited: set[str] = set()
    chapters: list[dict] = []
    selected_all: list[dict] = []
    route_rows = official_dated_stops(marks, clock) if marks else []
    stations_said: set[str] = set()
    for i, w in enumerate(windows):
        dest = _chapter_dest(w)
        dest_name = _window_dest_name(w)
        arrived = bool(w.get("arrived")) if "arrived" in w else bool(dest)
        if _is_air_window(w) and not w.get("returnMs"):
            w["returnMs"] = _air_return_from_moments(
                moments, w.get("fromName") or "", w.get("tA"),
            )
        depart_ms = _window_depart_ms(w) or 0
        # La vérité du terrain borne le plan — si un moment de la jambe
        # existe avant l'appareillage déduit des marks, le bateau est déjà parti.
        first_leg = _first_leg_moment_ms(moments, w)
        if depart_ms and first_leg and (w.get("tA") or 0) < first_leg < depart_ms:
            depart_ms = first_leg
        w["departMs"] = depart_ms
        if _is_air_window(w):
            sail_moments: list[dict] = []
        else:
            sail_moments = _align_moments_to_window(
                [m for m in moments if isinstance(m, dict) and not _moment_is_air(m)], w, depart_ms,
            )
        flat = _flatten_changes(sail_moments, w["tA"], w["tB"], first=i == 0)
        clock_climo = _climo_from_clock(w.get("clock") or clock, w["tA"], w["tB"], first=i == 0)
        if clock_climo:
            flat = [c for c in flat if str(c.get("kind") or "") != "climo"]
            flat.extend(clock_climo)
        for extra in _dest_culture_changes(dest):
            extra = {**extra, "t": (dest or {}).get("iso"), "tMs": w["tB"]}
            flat.append(extra)
        # Le second bateau (Saint-Pierre → Halifax, ou Saint-Pierre →
        # Cayenne si le titre n'a pas encore Halifax) ne reprend pas les eaux
        # de Guyane ni l'équateur du catamaran resté à quai.
        if _is_saint_pierre_depart(w):
            flat = _drop_guiana_equator_changes(flat)
        # N12 : une campagne (ou un flotteur) se dit une fois dans le film —
        # CALICO dit à l'approche de Nouméa ne se redit pas au départ de Nouméa.
        if stations_said:
            flat = [c for c in flat if _station_ident(c) not in stations_said]
        selected = select_chapter_changes(
            flat, w["tA"], w["tB"], budget=has_budget, tier=tier if has_budget else None,
            clock=w.get("clock") or clock, depart_ms=depart_ms, lang=lang,
        )
        # Une aire déjà dite, une fois. Le 2:30 n'en empile pas une seconde.
        if compact and any(_is_amp_change(c) for c in selected_all):
            selected = [c for c in selected if not _is_amp_change(c)]
        bits: list[str] = []
        placed: list[dict] = []

        def speak_change(change: dict) -> None:
            if change.get("kind") in {"escale", "marina"}:
                return
            if _is_departure_port_echo(
                change,
                str(w.get("fromName") or ""),
                dest_name or "",
            ):
                return
            if str(change.get("kind") or "") in {"stop", "escale"} and not _moment_near_named_place(
                change, w.get("clock") or clock, marks,
            ):
                return
            if _is_air_window(w) and _is_air_only_stop(str(change.get("title") or "")):
                return
            title = short_name(change.get("title") or "")
            if _is_air_only_stop(title) and not (_is_air_window(w) or _is_side_window(w)):
                return
            if change.get("kind") == "approche" and dest_name and title and (
                same_stop(title, dest_name) or dest_name.casefold() in title.casefold()
            ):
                return
            # « Le bateau longe Mata-Utu. […] Arrivée à Mata-Utu » : on ne longe pas
            # le port où l'on arrive (ni sa marina : Dégrad des Cannes, Cayenne).
            if change.get("kind") == "coast" and _coast_is_arrival(
                change, dest_name or "", selected, dest, lang,
            ):
                return
            place = change_place_name(change) or title
            geo = change.get("geo") if isinstance(change.get("geo"), dict) else None
            if geo and (geo.get("fr") or geo.get("en")):
                place = geo.get("fr") or geo.get("en") or place
            if looks_english_title(place) and change.get("kind") in {
                "port", "approche", "culture", "project", "amp", "marina",
                "poe", "anchorage", "aton",
            }:
                return
            if _off_leg_stop(place, w.get("fromName"), dest_name, route_rows, str(change.get("kind") or "")):
                return
            sentence = change_sentence(change, lang).strip()
            if not sentence or film_has_forbidden(sentence):
                return
            filtered, _dropped = filter_numbers(sentence, _facts_with_rounded(change), spelled=True)
            sentence = (filtered or "").strip()
            if not sentence or film_has_forbidden(sentence):
                return
            extra = {"place": place, "kind": str(change.get("kind") or "")}
            if change.get("lat") is not None:
                extra["lat"] = change.get("lat")
                extra["lon"] = change.get("lon")
            t_ms = change.get("tMs")
            if change.get("kind") in {"stop", "escale", "approche"} and dest_name:
                named = change_place_name(change) or title
                if named and same_stop(named, dest_name):
                    t_ms = w["tB"]
            t_ms = _snap_change_anchor_ms(
                {**change, "tMs": t_ms},
                w.get("clock") or clock,
                w["tA"],
                w["tB"],
                marks,
            )
            # Une date dite avant le jour de l'ancre : la barre serait déjà plus loin.
            if _known_stop(place, route_rows) and _spoken_before_anchor(sentence, t_ms, lang):
                return
            # L'instant du jalon, pas le plus proche homonyme plus
            # loin sur l'horloge (Gibraltar recollé après le Maroc ; Mata-Utu /
            # Nouméa recollés en octobre au milieu d'août–septembre).
            char_idx = len(" ".join(bits)) + (1 if bits else 0)
            bits.append(sentence)
            anchored.append((sentence, t_ms, extra))
            placed.append(_bubble_from_change(change, w, lang, char_idx))
            selected_all.append(change)
            ident = _station_ident(change)
            if ident:
                stations_said.add(ident)

        # Ancres (27 sept.) : chaque phrase porte l'instant du trajet dont elle parle — le client y cale le
        # bateau pendant qu'elle est dite (« approche d'Ajaccio » quand le bateau approche d'Ajaccio).
        anchored: list[tuple[str, Optional[int]]] = []
        skip_depart = False
        film_opens: list[str] = []
        if i == 0:
            film_opens = _film_open_sentences(
                start_name=start_name, sea_name=sea_name, lang=lang,
                display_t0=display_t0, review=review, compact=compact,
            )
            skip_depart = _is_road_window(w) and bool(film_opens)
        if _is_air_window(w):
            head = _depart_towards(
                w, i=i, lang=lang, display_t0=display_t0,
                review=review, n=len(windows), compact=compact,
            )
            if head:
                bits.append(head)
                anchored.append((head, depart_ms or w["tA"], {"role": "depart"}))
            bits[:] = thin_chapter_dates(bits, lang)
            chapter_budget = budgets[i] if i < len(budgets) else (FILM_CHAPTER_FLOOR if has_budget else 0)
            text = fit_chapter_text(" ".join(bits), chapter_budget, [], lang)
            if film_opens:
                head = " ".join(film_opens)
                if head and head not in text:
                    text = speak_film_text(f"{head} {text}".strip(), lang)
                    for sent in reversed(film_opens):
                        anchored.insert(0, (sent, w["tA"], {"role": "depart"}))
            if i == len(windows) - 1:
                close = _close_sentence(
                    w, live, lang, review=review, eta=eta, route_stops=route_rows,
                    now_ms=now,
                )
                if close and close not in text:
                    text = speak_film_text(f"{text} {close}".strip(), lang)
                    anchored.append((close, w["tB"]))
            chapters.append({
                "id": w["id"],
                "tA": _iso(w["tA"]),
                "tB": _iso(w["tB"]),
                "text": text,
                "anchors": chapter_anchors(text, anchored, w["tA"], w["tB"], lang),
                "_anchorText": text,
                "events": placed,
                "fromName": w.get("fromName") or "",
                "toName": w.get("toName") or "",
                "fromLat": w.get("fromLat"),
                "fromLon": w.get("fromLon"),
                "toLat": w.get("toLat"),
                "toLon": w.get("toLon"),
            })
            continue
        if not skip_depart:
            head = _depart_towards(
                w, i=i, lang=lang, display_t0=display_t0,
                heading_deg=_leg_heading_deg(
                    sail_moments, depart_ms, clock=w.get("clock") or clock,
                    leg_nm=chapter_metrics(w, review).get("legNm"),
                ),
                review=review, n=len(windows), include_date=i != 0, compact=compact,
            )
            if head:
                bits.append(head)
                anchored.append((head, depart_ms or w["tA"], {"role": "depart"}))
        elif i == 0:
            # La route s'arrête à La Rochelle : l'étape en mer La Rochelle →
            # Ajaccio se dit (départ, cap, milles, jours), sinon « par la
            # route jusqu'à La Rochelle » enchaînait sur « Arrivée à Ajaccio ».
            sea_leg = _first_sea_leg_sentence(
                w, clock=w.get("clock") or clock, sea_name=sea_name, lang=lang,
                display_t0=display_t0, review=review, n=len(windows), compact=compact,
            )
            if sea_leg:
                bits.append(sea_leg[0])
                anchored.append((sea_leg[0], sea_leg[1], {"role": "depart"}))
        for change in selected:
            speak_change(change)
        _append_review_sentences(bits, review, w, lang, anchored)
        key = norm_stop((dest or {}).get("name") or "")
        harbor = _arrival_harbor(selected, dest, lang) if arrived else ""
        arrival = (
            _arrival_sentence(
                dest, lang, display_t0, clock=w.get("clock"),
                harbor=harbor, chapter_i=i, compact=compact,
                final=bool(w.get("last")),
            ) if arrived else ""
        )
        if arrival and key and key not in cited:
            char_idx = len(" ".join(bits)) + (1 if bits else 0)
            bits.append(arrival)
            dest_place = short_name((dest or {}).get("name") or "")
            anchored.append((arrival, w["tB"], {"role": "arrive", "place": dest_place, "kind": "escale"}))
            cited.add(key)
            arr_id = f"stop:{dest['name']}:{dest.get('iso')}"
            dest_title = short_name(dest["name"])
            placed.append({
                "id": arr_id, "charIdx": char_idx, "kind": "stop", "title": dest_title,
                "fact": arrival, "score": 3,
                "card": {"id": arr_id, "kind": "stop", "title": dest_title, "text": arrival, "at": dest.get("iso"), "score": 3},
            })
        # Tri strict par instant d'ancre AVANT les connecteurs de date —
        # un item déplacé entre fenêtres ou une phrase de revue ancrée tôt ne
        # se dit plus hors de son ordre ; « le lendemain » est recalculé après.
        _order_chapter_sentences(
            bits, anchored, placed,
            from_name=str(w.get("fromName") or ""),
            to_name=str(w.get("toName") or w.get("destName") or ""),
            lang=lang,
        )
        thinned = thin_chapter_dates(bits, lang)
        if len(thinned) == len(bits) and len(anchored) == len(bits):
            anchored[:] = [_retarget_anchor(anchored[j], thinned[j]) for j in range(len(thinned))]
        bits[:] = thinned
        chapter_budget = budgets[i] if i < len(budgets) else (FILM_CHAPTER_FLOOR if has_budget else 0)
        text = fit_chapter_text(" ".join(bits), chapter_budget, [], lang)
        if film_opens:
            head = " ".join(film_opens)
            if head and head not in text:
                text = speak_film_text(f"{head} {text}".strip(), lang)
                for sent in reversed(film_opens):
                    anchored.insert(0, (sent, w["tA"], {"role": "depart"}))
        if i == len(windows) - 1:
            close = _close_sentence(
                w, live, lang, review=review, eta=eta, route_stops=route_rows,
                now_ms=now,
            )
            if close and close not in text:
                text = speak_film_text(f"{text} {close}".strip(), lang)
                anchored.append((close, w["tB"]))
        chapters.append({
            "id": w["id"],
            "tA": _iso(w["tA"]),
            "tB": _iso(w["tB"]),
            "text": text,
            "anchors": chapter_anchors(text, anchored, w["tA"], w["tB"], lang),
            "_anchorText": text,
            "events": placed,
            "fromName": w.get("fromName") or "",
            "toName": w.get("toName") or "",
            "fromLat": w.get("fromLat"),
            "fromLon": w.get("fromLon"),
            "toLat": w.get("toLat"),
            "toLon": w.get("toLon"),
        })
    # Après opens recollés, puis après l'avion recollé.
    if has_budget and target > 0:
        _film_apply_char_budget(chapters, seconds)
    _ensure_air_sentences(chapters, marks=marks, moments=moments, lang=lang)
    if has_budget and target > 0:
        _film_apply_char_budget(chapters, seconds)
    _finalize_chapter_zero_opens(
        chapters,
        windows,
        start_name=start_name,
        sea_name=sea_name,
        lang=lang,
        display_t0=display_t0,
        review=review,
        seconds=seconds,
    )
    # L'ouverture recollée après le plafond peut le dépasser : on recoupe.
    if has_budget and target > 0:
        _film_apply_char_budget(chapters, seconds)
    chapters[:] = _drop_degenerate_chapters(chapters)
    mark_year_changes(chapters, lang)
    for ch in chapters:
        _reanchor_edited_chapter(ch, lang)
    chars = script_chars(chapters)
    return _with_dc_subjects({
        "chapters": chapters,
        "source": "rules",
        "chars": chars,
        "targetSeconds": budget_s,
        "estimatedSeconds": film_estimated_seconds(chars),
        "_events": selected_all,
        "_packed": packed,
        "_fromMoments": True,
    }, journal, lang)


def build_raw_script(
    clock: dict | None,
    marks: list | None,
    live: dict | None,
    journal: dict | None,
    *,
    lang: str = "fr",
    seconds: int = 150,
    now_ms: Optional[int] = None,
    selected: list[dict] | None = None,
    display_t0: str | None = None,
    review: dict | None = None,
    eta: dict | None = None,
) -> dict[str, Any]:
    now = now_ms if now_ms is not None else int(datetime.now(timezone.utc).timestamp() * 1000)
    if _journal_moments(journal):
        return build_raw_from_moments(
            clock, marks, live, journal, lang=lang, seconds=seconds, now_ms=now,
            display_t0=display_t0, review=review, eta=eta,
        )
    packed = film_candidates(journal, marks, clock, live, now)
    t0, t_end = packed["t0"], packed["tEnd"]
    if t0 is None or t_end is None or t_end <= t0:
        return {"chapters": [], "source": "rules", "chars": 0, "targetSeconds": _film_seconds(seconds)}
    start_name = short_name((packed["start"] or {}).get("name") or "Saint-Maur")
    sea_name = short_name((packed["sea"] or {}).get("name") or "La Rochelle")
    events = selected if selected is not None else select_film_events(packed["candidates"], t0, t_end)
    events = [{**e, "name": start_name} if e.get("role") == "depart" else e for e in events]
    must_ids = {e["id"] for e in events if e.get("role") in {"depart", "today", "stop"}}
    windows = _annotate_episode_windows(
        _windows(packed["stops"], t0, t_end, clock),
        clock=clock, marks=marks, moments=_journal_moments(journal), lang=lang,
    )

    def compose(evs: list[dict]) -> list[dict]:
        return _compose(
            windows, _assign(evs, windows), lang=lang, sea_name=sea_name,
            start_name=start_name, live=live, display_t0=display_t0,
            review=review, eta=eta, seconds=seconds,
            route_stops=official_dated_stops(marks, clock),
        )

    chapters = compose(events)
    attach_chapter_events(chapters, packed, journal, lang)
    while _film_seconds(seconds) > 0 and script_chars(chapters) > FILM_MAX_CHARS:
        droppable = [e for e in events if e["id"] not in must_ids]
        if not droppable:
            break
        droppable.sort(key=lambda e: (e.get("score") or 0, -e["tMs"]))
        drop = droppable[0]
        events = [e for e in events if e["id"] != drop["id"]]
        chapters = compose(events)
        attach_chapter_events(chapters, packed, journal, lang)
    if _film_seconds(seconds) > 0:
        _film_apply_char_budget(chapters, seconds)
    _ensure_air_sentences(
        chapters, marks=marks, moments=_journal_moments(journal), lang=lang,
    )
    if _film_seconds(seconds) > 0:
        _film_apply_char_budget(chapters, seconds)
    chars = script_chars(chapters)
    return _with_dc_subjects({
        "chapters": chapters,
        "source": "rules",
        "chars": chars,
        "targetSeconds": _film_seconds(seconds),
        "estimatedSeconds": film_estimated_seconds(chars),
        "_events": events,
        "_packed": packed,
    }, journal, lang)


def journal_fingerprint(journal: dict | None, last_stop: str | None = None) -> str:
    bits = []
    for row in _journal_moments(journal):
        bits.append(f"{row.get('seq')}|{row.get('signature')}|{row.get('t')}")
    for e in sorted(journal_entries(journal), key=lambda x: (str(x.get("t") or ""), str(x.get("id") or ""))):
        bits.append(f"{e.get('id')}|{e.get('kind')}|{e.get('t')}")
    bits.append(f"stop:{last_stop or ''}")
    return hashlib.sha256("\n".join(bits).encode("utf-8")).hexdigest()


def last_stop_id(journal: dict | None, marks: list | None) -> str:
    for row in reversed(_journal_moments(journal)):
        for change in row.get("changes") or []:
            if isinstance(change, dict) and change.get("kind") == "escale":
                return str(change.get("title") or "")
    stops = [e for e in journal_entries(journal) if e.get("kind") == "stop" and e.get("event") == "arrival"]
    if stops:
        stops.sort(key=lambda e: e.get("t") or "")
        return str(stops[-1].get("id") or stops[-1].get("name") or "")
    dated = dated_marks(marks)
    return dated[-1]["name"] if dated else ""


def film_facts(raw: dict, events: list[dict]) -> dict[str, Any]:
    blob = {
        "raw": " ".join(c.get("text") or "" for c in raw.get("chapters") or []),
        "ids": [e["id"] for e in events],
        "entries": [e.get("entry") or {} for e in events],
    }
    return blob


def _uniq_facts(rows: list[Any]) -> list[Any]:
    seen: set[str] = set()
    out: list[Any] = []
    for row in rows:
        if row is None:
            continue
        key = str(row).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(row if not isinstance(row, str) else key)
    return out


def chapter_structured_facts(chapter: dict, *, lang: str = "fr") -> dict[str, Any]:
    """Faits JSON d'une étape : dates, lieux, eaux, AMP, projets, stations, climo, distances, cap."""
    text = chapter.get("text") or ""
    events = [e for e in (chapter.get("events") or []) if isinstance(e, dict)]
    dates: list[str] = []
    for iso in (chapter.get("tA"), chapter.get("tB")):
        spoken = day_month(iso, lang, year=True)
        if spoken:
            dates.append(spoken)
            bare = day_month(iso, lang, year=False)
            if bare:
                dates.append(bare)
    rx = _DATE_EN_RE if _en(lang) else _DATE_FR_RE
    dates.extend(m.group(0) for m in rx.finditer(text))

    places: list[str] = []
    for key in ("fromName", "toName"):
        name = chapter.get(key)
        if name:
            places.append(str(name))
            places.append(short_name(name))

    waters: list[str] = []
    amp: list[str] = []
    projects: list[str] = []
    stations: list[str] = []
    climo: list[str] = []
    for ev in events:
        kind = str(ev.get("kind") or "").lower()
        card = ev.get("card") if isinstance(ev.get("card"), dict) else {}
        title = str(ev.get("title") or card.get("title") or "")
        fact = str(ev.get("fact") or card.get("text") or "")
        name = title or fact
        if kind in {"zee", "zee-enter"}:
            waters.append(name)
        elif kind == "amp":
            amp.append(name)
        elif kind == "project":
            projects.append(name)
        elif kind in {"sci", "station"}:
            stations.append(name)
        elif kind == "climo":
            climo.append(name)
        elif kind in {"coast", "port", "marina", "stop", "escale", "approche"}:
            places.append(name)

    distances: list[str] = []
    for m in re.finditer(
        r"\b\d{1,3}(?:[ \u202f\u00a0]\d{3})+(?![\d.,]\d)\s*(?:milles nautiques|milles|nautical miles)|\d+(?:[.,]\d+)?\s*(?:milles nautiques|milles|nautical miles|nœuds|noeuds|knots|jours|days)",
        text,
        re.I,
    ):
        distances.append(m.group(0))

    heading: list[str] = []
    for m in re.finditer(r"cap au [\w\-]+|heading [\w\-]+|cap sur [\w'’\- ]+", text, re.I):
        heading.append(m.group(0).strip())

    return {
        "dates": _uniq_facts(dates),
        "places": _uniq_facts(places),
        "waters": _uniq_facts(waters),
        "amp": _uniq_facts(amp),
        "projects": _uniq_facts(projects),
        "stations": _uniq_facts(stations),
        "climatology": _uniq_facts(climo),
        "distances": _uniq_facts(distances),
        "heading": _uniq_facts(heading),
        "raw": text,
    }


_NAME_STOP = frozenset({
    "le", "la", "les", "un", "une", "des", "du", "de", "d", "au", "aux", "et", "ou", "en",
    "sur", "dans", "par", "pour", "avec", "sans", "sous", "vers", "chez", "entre",
    "puis", "ensuite", "plus", "loin", "arrivée", "arrivé", "arrivée", "départ", "arrival", "departure", "leaving", "in",
    "aujourd", "hui", "aujourd'hui", "the", "a", "an", "and", "or", "then", "next",
    "after", "from", "into", "on", "at", "by", "for", "with", "cap", "heading",
    "milles", "nautiques", "nautical", "miles", "jours", "days", "nœuds", "noeuds",
    "knots", "janvier", "février", "fevrier", "mars", "avril", "mai", "juin",
    "juillet", "août", "aout", "septembre", "octobre", "novembre", "décembre",
    "decembre", "january", "february", "march", "april", "may", "june", "july",
    "august", "september", "october", "november", "december", "l", "expédition",
    "expedition", "catamaran", "bateau", "boat", "équipage", "equipage", "crew",
    "approche", "approach", "quitte", "leaves", "left", "departed", "today",
    "aujourd’hui", "upcoming",  # « Upcoming stops: … » : l’adjectif en tête de phrase, pas un nom
})
_NAME_TOKEN_RE = re.compile(
    r"[A-ZÉÈÊÀÂÙÛÎÔÇ][A-Za-zÀ-ÿ'’]*(?:-[A-ZÉÈÊÀÂÙÛÎÔÇ]?[A-Za-zÀ-ÿ'’]*)*"
)


def _name_tokens(text: str) -> set[str]:
    out: set[str] = set()
    for m in _NAME_TOKEN_RE.finditer(text or ""):
        tok = m.group(0)
        folded = tok.casefold()
        if folded in _NAME_STOP or len(tok) <= 1:
            continue
        out.add(folded)
        for part in tok.split("-"):
            pf = part.casefold()
            if len(part) > 2 and pf not in _NAME_STOP:
                out.add(pf)
    return out


def written_names_subset(written: str, facts: Any) -> bool:
    """Chaque nom propre du rédigé doit déjà figurer dans les faits (y compris le brut)."""
    blob = facts if isinstance(facts, str) else json.dumps(facts, ensure_ascii=False, default=str)
    return _name_tokens(written) <= _name_tokens(blob)


def public_written_source(src: str | None) -> str:
    """Source servie : Super reste nemotron-super. Un repli garde son id."""
    raw = str(src or "").strip()
    low = raw.lower()
    if low in _SUPER_ORIGINS or low.startswith("nemotron-super"):
        return WRITTEN_SOURCE
    return raw


def _write_model() -> str:
    import llm_budget  # noqa: PLC0415

    return llm_budget.model_for("write")


def written_source_label(src: str) -> str:
    public = public_written_source(src)
    return public or str(src or "")


def _sentence_starts(text: str, sents: list[str]) -> list[int]:
    starts: list[int] = []
    pos = 0
    for sent in sents:
        idx = (text or "").find(sent, pos)
        if idx < 0:
            idx = pos
        starts.append(idx)
        pos = idx + max(1, len(sent))
    return starts


def apply_written_guard(
    raw_text: str, written_text: str, facts: Any, *, lang: str = "fr",
) -> tuple[str, int, int]:
    """Une phrase rédigée par phrase du brut ; nombre ou nom inventé → phrase du brut."""
    # Ultra écrit parfois « Mata‑Utu » (trait d'union insécable U+2011) : le nom ne se reconnaît plus.
    written_text = (written_text or "").replace("\u2011", "-").replace("\u2010", "-")
    raw_sents = _sentences(raw_text)
    if not raw_sents:
        return raw_text or "", 0, 0
    written_sents = _sentences(speak_film_text(written_text or "", lang))
    rewritten = 0
    fallen = 0
    kept: list[str] = []
    for i, raw_s in enumerate(raw_sents):
        cand = written_sents[i] if i < len(written_sents) else raw_s
        filtered, dropped = filter_numbers(cand, facts, spelled=True)
        ok = (
            not dropped
            and bool((filtered or "").strip())
            and written_names_subset(cand, facts)
        )
        if ok:
            kept.append(cand if cand.endswith((".", "!", "?", "…")) else f"{cand}.")
            rewritten += 1
        else:
            kept.append(raw_s)
            fallen += 1
    return " ".join(kept), rewritten, fallen


_ARRIVAL_KEY_RE = re.compile(r"^\s*(?:Arrivée à|Arrival (?:at|in))\s+(.+?)(?:\s+(?:le|on)\s+(.+?))?(?:,|\.|$)", re.I)


def _arrival_key(sentence: str) -> Optional[tuple[str, str]]:
    m = _ARRIVAL_KEY_RE.match(sentence or "")
    if not m:
        return None
    place = re.sub(r"\s*\([^)]*\)", "", m.group(1) or "").strip().casefold()
    return place, (m.group(2) or "").strip().casefold()


def dedupe_arrival_sentences(sents: list[str]) -> list[str]:
    """Deux arrivées au même lieu dans un chapitre : on garde la plus complète,
    à la place de la première. Une phrase répétée telle quelle tombe aussi."""
    out: list[str] = []
    keys: list[Optional[tuple[str, str]]] = []
    for s in sents:
        if out and s == out[-1]:
            continue
        k = _arrival_key(s)
        hit = next(
            (j for j, kj in enumerate(keys) if k and kj and kj[0] == k[0] and (not k[1] or not kj[1] or k[1] == kj[1])),
            None,
        ) if k else None
        if hit is not None:
            if len(s) > len(out[hit]):
                out[hit] = s
                keys[hit] = k
            continue
        out.append(s)
        keys.append(k)
    return out


def _trim_written_to_budget(raw_text: str, written_text: str, cap: int) -> tuple[str, int]:
    """Si le rédigé dépasse le budget RC27, on remet des phrases du brut depuis la fin."""
    if cap <= 0 or len(written_text or "") <= cap:
        return written_text, 0
    raw_sents = _sentences(raw_text)
    wr_sents = _sentences(written_text)
    if len(wr_sents) != len(raw_sents):
        wr_sents = (wr_sents + raw_sents)[: len(raw_sents)]
    fallen = 0
    kept = list(wr_sents)
    while kept and len(" ".join(kept)) > cap:
        reverted = False
        for i in range(len(kept) - 1, -1, -1):
            if i < len(raw_sents) and kept[i] != raw_sents[i]:
                kept[i] = raw_sents[i]
                fallen += 1
                reverted = True
                break
        if not reverted:
            break
    return " ".join(kept), fallen


def reanchor_written_chapter(chapter: dict, written_text: str, lang: str) -> list[dict]:
    """Ancres du brut reportées phrase à phrase, puis recalculées sur le rédigé."""
    raw = chapter.get("text") or ""
    raw_sents = _sentences(raw)
    wr_sents = _sentences(written_text)
    raw_starts = _sentence_starts(raw, raw_sents)
    old = [a for a in (chapter.get("anchors") or []) if isinstance(a, dict)]
    t_a, t_b = _ms(chapter.get("tA")), _ms(chapter.get("tB"))
    anchored: list = []
    if old and raw_starts:
        for a in old:
            try:
                idx = int(a.get("charIdx") or 0)
            except (TypeError, ValueError):
                idx = 0
            sent_i = 0
            for i, start in enumerate(raw_starts):
                end = start + (len(raw_sents[i]) if i < len(raw_sents) else 0)
                if start <= idx < max(end, start + 1) or i == len(raw_starts) - 1:
                    sent_i = i
                    if start <= idx < max(end, start + 1):
                        break
            sent = wr_sents[sent_i] if sent_i < len(wr_sents) else (wr_sents[-1] if wr_sents else "")
            t = a.get("t")
            t_ms = t if isinstance(t, int) else _ms(t)
            extra = {
                "place": a.get("place") or "",
                "kind": a.get("kind") or "",
                "role": a.get("role") or "",
            }
            anchored.append((sent, t_ms, extra))
    elif wr_sents:
        anchored = [(sent, t_a, {}) for sent in wr_sents]
    out = chapter_anchors(written_text, anchored, t_a, t_b, lang) if written_text and anchored else []
    if out:
        out = _snap_anchors_to_spoken_dates(written_text, out, lang, t_a=t_a, t_b=t_b)
        return _strict_increasing_anchors(out, written_text, lang)
    fallback = _fallback_anchors(written_text, wr_sents, old, t_a)
    fallback = _snap_anchors_to_spoken_dates(written_text, fallback, lang, t_a=t_a, t_b=t_b)
    return _strict_increasing_anchors(fallback, written_text, lang)


# Marge sous la durée cible : le débit vocal mesuré (FILM_ESTIMATE_CPS = 15 car./s,
# constant depuis le 27 sept.) fixe la durée ; 5 % de marge pour les pauses de phrase.
FILM_CONDENSE_MARGIN = 0.95


def film_spoken_char_cap(seconds: Any) -> int:
    """Caractères qui tiennent dans `seconds` au débit mesuré, marge comprise."""
    s = _film_seconds(seconds)
    return int(s * FILM_ESTIMATE_CPS * FILM_CONDENSE_MARGIN) if s > 0 else 0


def _condense_to_spoken_seconds(chapters: list[dict], seconds: Any) -> None:
    """Le plafond doit tenir la DURÉE parlée : 2 917 car. ≈ 194 s pour un « 150 s ».

    Après le rognage par priorités, on retire encore des phrases entières du
    milieu du chapitre le plus long — jamais la première (départ) ni la
    dernière (arrivée) — jusqu'à passer sous le plafond.
    """
    cap = film_spoken_char_cap(seconds)
    if cap <= 0:
        return
    for ch in chapters:
        ch["text"] = _drop_avg_speed(_fold_leg_stats(ch.get("text") or ""))
    if script_chars(chapters) > cap:
        _drop_repeated_regions(chapters)
    for ch in chapters:
        if script_chars(chapters) <= cap:
            break
        ch["text"] = _compact_leg_openings(ch.get("text") or "")
    # « 1 819 milles, une vingtaine de jours » : « de mer » va de soi au 2:30.
    for ch in chapters:
        if script_chars(chapters) <= cap:
            break
        text = _SEA_DAYS_FR_RE.sub(r"\1", ch.get("text") or "")
        ch["text"] = _SEA_DAYS_EN_RE.sub(r"\1", text)
    # Sujets du 2:30 (une aire marine, un projet — corail d'abord) : retirés en
    # tout dernier, après les marinas et les régions (ils disparaissaient tous).
    keys = _condense_subject_keys(chapters)
    while script_chars(chapters) > cap:
        best, best_len, best_i = None, 0, -1
        for ch in chapters:
            sents = _sentences(ch.get("text") or "")
            i = _condensable_sentence(ch, sents, keys)
            if i < 0:
                continue
            n = len(ch.get("text") or "")
            if n > best_len:
                best, best_len, best_i = ch, n, i
        if best is None:
            break
        sents = _sentences(best.get("text") or "")
        del sents[best_i]
        best["text"] = " ".join(sents).strip()
    for ch in chapters:  # phrase répétée mot pour mot (Ultra) : une seule fois
        sents = _sentences(ch.get("text") or "")
        bare = [re.sub(r"\s*\([^()]*\)", "", x) for x in sents]
        dedup = [x for i, x in enumerate(sents) if i == 0 or bare[i] != bare[i - 1]]
        if len(dedup) != len(sents):
            ch["text"] = " ".join(dedup)
    # Encore trop long : l'arrivée garde lieu et date, pas la marina (« , à Port de… »).
    for ch in sorted(chapters, key=lambda c: -len(c.get("text") or "")):
        if script_chars(chapters) <= cap:
            break
        ch["text"] = _ARRIVAL_BERTH_RE.sub(r"\1.", ch.get("text") or "")
    for ch in chapters:
        if script_chars(chapters) <= cap:
            break
        ch["text"] = (ch.get("text") or "").replace(" milles nautiques", " milles")
    # Puis la région déjà sous-entendue : « départ vers Gustavia … Arrivée à Gustavia (Saint-Barthélemy) ».
    for ch in sorted(chapters, key=lambda c: -len(c.get("text") or "")):
        if script_chars(chapters) <= cap:
            break
        text = ch.get("text") or ""
        for m in re.finditer(r"départ vers ([^:,.(]+?)\s*[:,.]", text):
            name = m.group(1).strip()
            text = re.sub(rf"(Arrivée à {re.escape(name)})\s*\([^)]*\)", r"\1", text)
        ch["text"] = text
    # Dernier recours, toujours au-dessus de 2:30 (pas seulement de la marge) : la région de première
    # mention part aussi, chapitre le plus long d'abord — jamais un lieu, une date, un chiffre.
    hard = film_char_budget(seconds) - int(FILM_ESTIMATE_CPS)
    for ch in sorted(chapters, key=lambda c: -len(c.get("text") or "")):
        if script_chars(chapters) <= hard:
            break
        ch["text"] = re.sub(r"\s{2,}", " ", _PLACE_REGION_RE.sub(r"\1", ch.get("text") or "")).strip()
    # Toujours au-dessus de 2:30 (le plafond dur, pas la marge) : les sujets protégés
    # partent un à un (le projet d'abord, puis l'aire).
    for key in reversed(keys):
        if script_chars(chapters) <= hard:
            break
        for ch in chapters:
            sents = _sentences(ch.get("text") or "")
            kept = [x for i, x in enumerate(sents) if i == 0 or i == len(sents) - 1 or key not in _subject_key_blob(x)]
            if len(kept) != len(sents):
                ch["text"] = " ".join(kept).strip()
                break
    _relative_day_to_then(chapters)


_RELATIVE_DAY_START_RE = re.compile(r"^(?:Le lendemain|The next day|The following day),\s+")


def _relative_day_to_then(chapters: list[dict]) -> None:
    """Au 2:30, les phrases intermédiaires sont retirées : « Le lendemain » ne suit plus
    sa vraie veille (« Le 24 février, départ… Le lendemain, Pointe d'Arçay » = 30 mai).
    « Puis » reste vrai ; jamais en tête de chapitre."""
    for ch in chapters:
        sents = _sentences(ch.get("text") or "")
        changed = False
        for i in range(1, len(sents)):
            m = _RELATIVE_DAY_START_RE.match(sents[i])
            if not m:
                continue
            then = "Then, " if m.group(0).startswith("The") else "Puis, "
            sents[i] = then + sents[i][m.end():]
            changed = True
        if changed:
            ch["text"] = " ".join(sents).strip()


_CONDENSE_AMP_RE = re.compile(r"aire marine protégée|aire marine|marine protected area", re.I)
_CONDENSE_PROJECT_RE = re.compile(r"\ble projet\b|\bthe project\b|\bproject\b", re.I)
_CONDENSE_CORAL_RE = re.compile(r"cora(?:il|ux|l|ls)\b", re.I)


def _subject_key_blob(sent: str) -> str:
    """Forme comparable d'une phrase de sujet : sans chiffres ni parenthèses, en minuscules."""
    t = re.sub(r"\s*\([^()]*\)", "", sent or "")
    t = re.sub(r"[\d\u00a0\u202f]", " ", t)
    return re.sub(r"\s+", " ", t).casefold()


def _subject_key(sent: str, rx: re.Pattern) -> str:
    """Le nom après « aire marine protégée » / « le projet » : stable malgré les retouches."""
    m = rx.search(sent or "")
    if not m:
        return ""
    tail = _subject_key_blob((sent or "")[m.end():])
    tail = re.sub(r"^[\s,:]+", "", tail)
    return tail[:40].strip(" .,;:")


def _condense_subject_keys(chapters: list[dict]) -> list[str]:
    """Au plus deux sujets gardés au 2:30 : la première aire marine, puis un projet (corail d'abord).

    Ni la première ni la dernière phrase d'un chapitre (départ, arrivée) ne compte.
    """
    amp = proj = coral = ""
    for ch in chapters:
        sents = _sentences(ch.get("text") or "")
        for sent in sents[1:-1]:
            if not amp and _CONDENSE_AMP_RE.search(sent):
                amp = _subject_key(sent, _CONDENSE_AMP_RE)
                continue
            if _CONDENSE_PROJECT_RE.search(sent) and not _CONDENSE_AMP_RE.search(sent):
                k = _subject_key(sent, _CONDENSE_PROJECT_RE)
                if k and not coral and _CONDENSE_CORAL_RE.search(sent):
                    coral = k
                if k and not proj:
                    proj = k
    out = [k for k in (amp, coral or proj) if k]
    return out


_ARRIVAL_BERTH_RE = re.compile(
    r"(\d{1,2}(?:er)?\s+(?:janvier|février|mars|avril|mai|juin|juillet|août|septembre|"
    r"octobre|novembre|décembre)(?:\s+\d{4})?),\s+"
    r"(?:à|au|amarrée?s?\s+(?:à|au))\s+(?:la\s+|le\s+|l['’])?"
    r"(?:marina|port|ponton|quai|mouillage|Port)\b[^.]*\.",
)


def _condensable_sentence(ch: dict, sents: list[str], protected: list[str] | None = None) -> int:
    """Dernière phrase du milieu qui ne nomme ni le départ ni l'arrivée ; -1 sinon.

    La phrase de bilan de l'étape (« 6 671 milles, 46 jours de mer… ») n'est jamais
    retirée : c'était la distance Cayenne → Papeete perdue au 2:30.
    """
    keep = {
        norm_stop(short_name(ch.get(k) or ""))
        for k in ("fromName", "destName", "toName") if ch.get(k)
    }
    keep.discard("")
    for i in range(len(sents) - 2, 0, -1):
        low = norm_stop(sents[i])
        if any(k and k in low for k in keep):
            continue
        if _LEG_STATS_SENT_RE.search(sents[i]):
            continue
        if protected and any(k and k in _subject_key_blob(sents[i]) for k in protected):
            continue
        return i
    return -1


# Bilan d'étape : « 6 671 milles, 46 jours de mer » / « 6,671 miles, 46 days at sea ».
_LEG_STATS_SENT_RE = re.compile(
    r"\d[\d \u00a0\u202f,]*\s+(?:milles|miles|nautical miles)\b.*?"
    r"(?:\bjours?\b|\bdays?\b|sea voyage|de traversée)",
    re.I,
)
# « départ vers Papeete (Polynésie française). 6 671 milles, 46 jours de mer, à 6 nœuds
# de moyenne. » → « départ vers Papeete (Polynésie française) : 6 671 milles, 46 jours de mer. »
_FOLD_STATS_FR_RE = re.compile(
    r"(départ vers [^.:;!?]+?|second voilier pour [^.:;!?]+?)\.\s+(\d[\d \u00a0\u202f]*\s+milles[^.!?]*?jours? de mer)"
    r"(?:,\s*à\s+[\w-]+\s+nœuds\s+de\s+moyenne)?\."
)
_FOLD_STATS_EN_RE = re.compile(
    r"([Dd]eparture (?:for|to) [^.:;!?]+?|second sailing boat for [^.:;!?]+?)\.\s+(\d[\d,]*\s+(?:nautical )?miles[^.!?]*?days? at sea)"
    r"(?:,\s*(?:at\s+)?(?:an average of\s+)?[\w-]+\s+knots(?:\s+(?:on\s+)?average)?)?\."
)
_AVG_SPEED_FR_RE = re.compile(r",\s*à\s+[\w-]+\s+nœuds\s+de\s+moyenne(?=[.;])")
_AVG_SPEED_EN_RE = re.compile(
    r",\s*(?:at\s+)?(?:an average of\s+)?[\w-]+\s+knots(?:\s+(?:on\s+)?average)?(?=[.;])"
)


def _fold_leg_stats(text: str) -> str:
    """Le 2:30 dit chaque étape sur un seul gabarit : « départ vers X : N milles, M jours de mer »."""
    out = _FOLD_STATS_FR_RE.sub(r"\1 : \2.", text or "")
    return _FOLD_STATS_EN_RE.sub(r"\1: \2.", out)


def _drop_avg_speed(text: str) -> str:
    """« …jours de mer, à 6 nœuds de moyenne. » → « …jours de mer. » (2:30 seulement)."""
    out = _AVG_SPEED_FR_RE.sub("", text or "")
    return _AVG_SPEED_EN_RE.sub("", out)


_PLACE_REGION_RE = re.compile(
    r"\b([A-ZÀ-Ý][\w'’\-]*(?: [A-ZÀ-Ý][\w'’\-]*)*) \(([^()]{2,48})\)"
)
_PLACE_COMMA_REGION_RE = re.compile(
    r"\b([A-ZÀ-Ý][\w'’\-]*(?: [A-ZÀ-Ý][\w'’\-]*)*), (?:en|à|au|aux|in) "
    r"([A-ZÀ-Ý][^,.;()]{2,40})(,\s*|(?=[.;]))"
)


# « Berry-Mappemonde quitte Marigot, cap au sud pour la longue traversée vers Cayenne »
# → « départ vers Cayenne » : le gabarit court du 2:30 (les caps étaient d'ailleurs douteux).
_LONG_OPENING_FR_RE = re.compile(
    r"(?:d['’]île en île, |pour la dernière étape, )?Berry-Mappemonde quitte [^,.;:]+?"
    r"(?:, cap (?:au |à l['’]|à la |sur )[\w-]+)?"
    r" (?:pour la (?:longue )?traversée vers|pour la traversée vers|vers|pour) "
)
_LONG_OPENING_EN_RE = re.compile(
    r"(?:(?:from )?island to island, |for the (?:last|final) leg, )?Berry-Mappemonde (?:leaves|left) [^,.;:]+?"
    r"(?:, (?:heading|steering|bound) [\w-]+)?"
    r" (?:for the long crossing to|for the crossing to|on the long crossing to|towards|bound for|for|to) "
)
_STOPOVER_SENT_RE = re.compile(
    r"^(?:(?:Trois|Deux|Quatre|Cinq|\d+) jours d['’]escale|Escale de [\w-]+ jours?|"
    r"(?:Three|Two|Four|Five|\d+)[- ]days?['’]? (?:stopover|at port|in port)|"
    r"(?:Trois|Deux|Quatre|Cinq|\d+) jours au port)\.?$",
    re.I,
)


_EN_HOP_RE = re.compile(r"(?:island by island|island-hopping|from island to island|island to island), ", re.I)
_EN_BERTH_RE = re.compile(
    r"((?:on|On) (?:January|February|March|April|May|June|July|August|September|October|November|"
    r"December) \d{1,2}(?:, \d{4})?), moored (?:at|in) [^.;]*\."
)
# Pluriel seulement : « un jour de mer » reste entier (« 192 milles, un jour. » sonnait faux).
_SEA_DAYS_FR_RE = re.compile(r"(\bjours) de mer\b")
_SEA_DAYS_EN_RE = re.compile(r"(\bdays) at sea\b")


def _compact_leg_openings(text: str) -> str:
    out = _EN_HOP_RE.sub("", text or "")
    out = _EN_BERTH_RE.sub(r"\1.", out)
    out = _LONG_OPENING_FR_RE.sub("départ vers ", out)
    out = _LONG_OPENING_EN_RE.sub("departure for ", out)
    sents = [x for x in _sentences(out) if not _STOPOVER_SENT_RE.match(x.strip())]
    out = " ".join(sents).strip() if sents else out
    return _drop_avg_speed(_fold_leg_stats(out))


_PLACE_INLINE_REGION_RE = re.compile(
    r"\b(?!(?:Arrival|Arrivée|Departure|Départ|On|Then|Puis|Le|La|Les|The|In|At)\b)([A-ZÀ-Ý][\w'’\-]*(?: [A-ZÀ-Ý][\w'’\-]*)*) (?:en|in) "
    r"(?!(?:janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre|"
    r"January|February|March|April|May|June|July|August|September|October|November|December)\b)"
    r"([A-ZÀ-Ý][\w'’\-]*(?: [a-zà-ÿ]{3,}| [A-ZÀ-Ý][\w'’\-]*)?)(?=[\s:,.;])"
)


def _drop_repeated_regions(chapters: list[dict]) -> None:
    """Région dite une fois : « Halifax (Nouvelle-Écosse) » au premier passage, « Halifax » ensuite.

    Le 2:30 répétait « Cayenne (Guyane) », « Halifax (Nouvelle-Écosse) »… à chaque
    phrase : ≈ 200 caractères, soit ≈ 13 s de voix pour rien.
    """
    seen: set[str] = set()
    pairs: set[tuple[str, str]] = set()

    def _inline(m: re.Match) -> str:
        """« Papeete en Polynésie française » redit mot pour mot : « Papeete »."""
        key = (norm_stop(m.group(1)), m.group(2).casefold())
        if key in pairs:
            return m.group(1)
        pairs.add(key)
        seen.add(key[0])
        return m.group(0)

    def _paren(m: re.Match) -> str:
        key = norm_stop(m.group(1))
        if key in seen:
            return m.group(1)
        seen.add(key)
        return m.group(0)

    def _comma(m: re.Match) -> str:
        key = norm_stop(m.group(1))
        if key in seen:
            rest = m.string[m.end():]
            if not m.group(3):
                return m.group(1)
            # « Arrivée à Saint-Pierre, à Saint-Pierre-et-Miquelon, le 21 août » → « … Saint-Pierre le 21 août »
            if re.match(r"(?:le |on )?\d|le |on ", rest):
                return f"{m.group(1)} "
            return f"{m.group(1)}, "
        seen.add(key)
        return m.group(0)

    for ch in chapters:
        text = ch.get("text") or ""
        if not text:
            continue
        # Ordre du texte : on traite les deux formes dans l'ordre d'apparition.
        pieces: list[tuple[int, int, str]] = []
        kinds = (("p", _PLACE_REGION_RE), ("c", _PLACE_COMMA_REGION_RE), ("i", _PLACE_INLINE_REGION_RE))
        for kind, rx in kinds:
            for m in rx.finditer(text):
                pieces.append((m.start(), m.end(), kind))
        pieces.sort()
        out, pos = [], 0
        for start, end, kind in pieces:
            if start < pos:
                continue
            rx, fn = {
                "p": (_PLACE_REGION_RE, _paren),
                "c": (_PLACE_COMMA_REGION_RE, _comma),
                "i": (_PLACE_INLINE_REGION_RE, _inline),
            }[kind]
            m = rx.match(text, start)
            if not m:
                continue
            out.append(text[pos:start])
            out.append(fn(m))
            pos = m.end()
        out.append(text[pos:])
        ch["text"] = re.sub(r"\s{2,}", " ", "".join(out)).strip()


def condense_written_plan(full_plan: dict, seconds: int, *, lang: str = "fr") -> dict:
    """Raccourcit le rédigé intégral au plafond (~15 car./s) sans rappeler Super."""
    import copy

    plan = copy.deepcopy(full_plan)
    secs = _film_seconds(seconds)
    chapters = [c for c in (plan.get("chapters") or []) if isinstance(c, dict)]
    _film_apply_char_budget(chapters, secs)
    _condense_to_spoken_seconds(chapters, secs)
    for ch in chapters:
        text = ch.get("text") or ""
        if text:
            ch["anchors"] = reanchor_written_chapter(ch, text, lang)
    plan["chapters"] = chapters
    plan["chars"] = script_chars(chapters)
    plan["targetSeconds"] = secs
    plan["estimatedSeconds"] = film_estimated_seconds(plan["chars"])
    return plan


def _fallback_anchors(
    written_text: str, wr_sents: list[str], old: list[dict], t_a: Optional[int],
) -> list[dict]:
    starts = _sentence_starts(written_text, wr_sents)
    if not old:
        return [
            {"charIdx": starts[i] if i < len(starts) else 0, "t": _iso(t_a) or ""}
            for i in range(len(wr_sents))
        ]
    out: list[dict] = []
    for i, a in enumerate(old):
        idx = starts[i] if i < len(starts) else (starts[-1] if starts else 0)
        row = {"charIdx": idx, "t": a.get("t")}
        if a.get("place"):
            row["place"] = a["place"]
        out.append(row)
    return out


def _snap_anchors_to_spoken_dates(
    text: str,
    anchors: list[dict],
    lang: str,
    *,
    t_a: Any = None,
    t_b: Any = None,
) -> list[dict]:
    """Recolle la barre de sync sur la date dite dans la phrase ancrée.

    L'année vient de l'instant de l'ancre (pas 2026 par défaut) et l'instant
    reste dans la fenêtre du chapitre [tA, tB].
    """
    lo = t_a if isinstance(t_a, int) else _ms(t_a) if t_a else None
    hi = t_b if isinstance(t_b, int) else _ms(t_b) if t_b else None
    if not text or not anchors:
        return anchors
    out: list[dict] = []
    for a in anchors:
        if not isinstance(a, dict):
            continue
        row = {**a}
        try:
            idx = int(row.get("charIdx") or 0)
        except (TypeError, ValueError):
            idx = 0
        t_raw = row.get("t")
        ref = t_raw if isinstance(t_raw, int) else _ms(t_raw) if t_raw else lo
        spoken_ms = _spoken_anchor_ms(_sentence_at_idx(text, idx), lang, ref)
        if spoken_ms is not None:
            if lo is not None:
                spoken_ms = max(int(lo), spoken_ms)
            if hi is not None:
                spoken_ms = min(int(hi), spoken_ms)
            row["t"] = _iso(spoken_ms)
        out.append(row)
    return out


def _strict_increasing_anchors(
    anchors: list[dict],
    text: str = "",
    lang: str = "fr",
) -> list[dict]:
    ordered = sorted(
        [a for a in anchors if isinstance(a, dict)],
        key=lambda a: int(a.get("charIdx") or 0),
    )
    out: list[dict] = []
    last = -1
    last_t: Optional[int] = None
    for a in ordered:
        try:
            idx = int(a.get("charIdx") or 0)
        except (TypeError, ValueError):
            idx = 0
        if idx <= last:
            idx = last + 1
        last = idx
        t_raw = a.get("t")
        t_ms = t_raw if isinstance(t_raw, int) else _ms(t_raw)
        if last_t is not None and t_ms is not None and t_ms < last_t:
            # La barre de sync ne recule jamais : une date dite plus tôt que la
            # précédente est un défaut du texte (relecture « date »), pas une
            # raison de faire reculer le bateau.
            t_ms = last_t
        if t_ms is not None:
            last_t = t_ms
        row = {**a, "charIdx": idx}
        if t_ms is not None:
            row["t"] = _iso(t_ms) if not isinstance(t_raw, str) else (t_raw or _iso(t_ms))
            if isinstance(t_raw, str) and t_ms == _ms(t_raw):
                row["t"] = t_raw
            elif t_ms is not None:
                row["t"] = _iso(t_ms)
        out.append(row)
    return out


def strip_tags(text: str) -> str:
    return TAG_STRIP.sub("", text or "")


def locate_events(tagged: str, events: list[dict]) -> tuple[str, list[dict]]:
    """Strip [[ev:]] / [[ch:]] and attach charIdx on the displayed text."""
    display_parts: list[str] = []
    located: list[dict] = []
    pos = 0
    by_id = {e["id"]: e for e in events}
    for m in re.finditer(r"\[\[(?:ev|ch):([^\]]+)\]\]\s*", tagged or ""):
        display_parts.append(tagged[pos:m.start()])
        if tagged[m.start():].startswith("[[ev:"):
            eid = m.group(1)
            ev = by_id.get(eid)
            if ev:
                entry = ev.get("entry") or {}
                score = ev.get("bubbleScore") if ev.get("bubbleScore") in {1, 2, 3} else bubble_score(entry, role=ev.get("role"))
                located.append({
                    "id": eid,
                    "charIdx": len("".join(display_parts)),
                    "kind": ev.get("kind") or entry.get("kind"),
                    "title": short_name(ev.get("name") or entry.get("name") or ""),
                    "fact": event_sentence(ev, "fr"),
                    "score": score,
                    "card": _card(entry),
                })
        pos = m.end()
    display_parts.append((tagged or "")[pos:])
    display = "".join(display_parts)
    return display, located


REREAD_SYSTEM = (
    "You re-read an expedition film against the real stops and the distance of each leg. "
    "Return JSON only: {\"ok\": true|false, \"faults\": [\"skip: <stop>\"]}, "
    "each fault a kind (skip, off-route, upcoming, date) and a short quote. "
    "You read one part of the film: `legs` lists the legs it covers, `stops` the stops of this part, "
    "`routeStops` the whole route (the other stops are told in other parts, never a skip here). "
    "Waters, islands, coasts and projects passed at sea between two stops are on the route. "
    "ok is false when a stop of these legs is skipped, a place is not on the route, "
    "an upcoming list omits a stop still ahead, or a date goes backward inside this part. "
    "Stops of other legs are told in other parts: their absence here is not a fault. "
    "A skip is only a stop of `stops` missing from the text. "
    "A date fault needs a later sentence giving an EARLIER calendar date than a previous one; "
    "dates that move forward are never a fault. A place listed in stops is never off-route. "
    "At most three faults, each under 120 characters. "
    "Do not rewrite the film. Answer in one short line of JSON, no reasoning."
)
_LEAVE_FOR_RE = re.compile(
    r"(?:leaves|quitte|quitté)\s+(?P<frm>.+?)"
    r"(?:,\s*heading\s+\w+)?\s+"
    r"(?:for|pour)\s+(?P<to>.+?)"
    r"(?=[.,;:]|\s+on\b|\s+le\b|$)",
    re.I,
)
_CAP_RE = re.compile(
    r"(?:cap sur|départ vers|departure for|heading for)\s+(?P<to>.+?)"
    r"(?=\s*[:.,;]|\s+on\b|\s+le\b|$)",
    re.I,
)
_FORMALITY_RE = re.compile(
    r"(?:entry formalities go through|les formalités d['’]entrée passent par)\s+(.+?)(?=[.,;]|$)",
    re.I,
)
_ARRIVAL_PLACE_RE = re.compile(
    r"(?:Arrival at|Arrivée à)\s+(.+?)(?:\s+on\b|\s+le\b|[.,;]|$)",
    re.I,
)
_APPROACH_BY_RE = re.compile(
    r"(?:the approach is by|l['’]approche se fait par)\s+(.+?)(?=[.,;]|$)",
    re.I,
)
_SKIRTS_RE = re.compile(
    r"(?:the boat skirts|le bateau longe)\s+(.+?)(?=[.,;]|$)",
    re.I,
)
_UPCOMING_RE = re.compile(
    r"(?:Stops still to come|Les escales à venir)\s*:\s*(.+?)(?:\.|$)",
    re.I,
)
_MILES_RE = re.compile(
    r"(\d{1,3}(?:[ \u00a0\u202f,]\d{3})+|\d{3,6})\s*(?:nautical miles|miles|milles nautiques|milles)\b",
    re.I,
)


def _place_core(raw: str) -> str:
    s = re.sub(
        r"^(?:the long crossing to|la longue traversée vers)\s+",
        "",
        str(raw or "").strip(),
        flags=re.I,
    )
    return re.split(r"[.;:]", s, maxsplit=1)[0].strip()


def _as_stop_rows(stops: list | None) -> list[dict]:
    rows: list[dict] = []
    for raw in stops or []:
        if isinstance(raw, dict):
            name = str(raw.get("name") or raw.get("to") or "").strip()
            if not name:
                continue
            row: dict[str, Any] = {"name": name}
            for key in ("nm", "filmNm"):
                val = raw.get(key)
                if isinstance(val, (int, float)) and not isinstance(val, bool):
                    row["nm"] = float(val)
                    break
            rows.append(row)
        elif str(raw or "").strip():
            rows.append({"name": str(raw).strip()})
    return rows


def _row_nm(row: dict) -> Optional[float]:
    val = row.get("nm")
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return float(val)
    return None


def _index_row(rows: list[dict], name: str, *, after: int = -1) -> Optional[int]:
    """Première escale de ce nom. `after` cherche la suivante (retour à La Rochelle)."""
    start = after + 1
    for i in range(max(0, start), len(rows)):
        if _known_stop(name, [rows[i]]):
            return i
    if after >= 0:
        for i, row in enumerate(rows):
            if _known_stop(name, [row]):
                return i
    return None


def _pair_indexes(rows: list[dict], frm: str, to: str) -> tuple[Optional[int], Optional[int]]:
    ia = _index_row(rows, frm)
    if ia is None:
        return None, None
    ib = _index_row(rows, to, after=ia)
    if ib is not None:
        # Cayenne revient après l'aller-retour Halifax : on part du dernier passage.
        while True:
            nxt = _index_row(rows, frm, after=ia)
            if nxt is None or nxt <= ia or nxt >= ib:
                break
            ia = nxt
    return ia, ib


def _sea_between(rows: list[dict], frm: str, to: str) -> list[str]:
    ia, ib = _pair_indexes(rows, frm, to)
    if ia is None or ib is None or ib <= ia + 1:
        return []
    missed: list[str] = []
    for row in rows[ia + 1:ib]:
        label = _stop_spoken(row.get("name") or "")
        if not label or _is_air_only_stop(label):
            continue
        missed.append(label)
    return missed


def _span_nm(rows: list[dict], frm: str, to: str) -> Optional[float]:
    ia, ib = _pair_indexes(rows, frm, to)
    if ia is None or ib is None or ib <= ia:
        return None
    a, b = _row_nm(rows[ia]), _row_nm(rows[ib])
    if a is None or b is None:
        return None
    gap = b - a
    return gap if gap > 1 else None


def _mile_ints(text: str) -> list[int]:
    out: list[int] = []
    for match in _MILES_RE.finditer(text or ""):
        digits = re.sub(r"[^\d]", "", match.group(1))
        if not digits:
            continue
        val = int(digits)
        if val >= 100:
            out.append(val)
    return out


def _sentence_at_idx(text: str, idx: int) -> str:
    pos = 0
    sents = _sentences(text)
    for i, sent in enumerate(sents):
        start = (text or "").find(sent, pos)
        if start < 0:
            start = pos
        end = start + len(sent)
        if start <= idx < end or i == len(sents) - 1:
            return sent
        pos = end
    return ""


def _dates_regress(text: str, lang: str) -> bool:
    prev: Optional[datetime] = None
    for sent in _sentences(text):
        cur = _parse_spoken_date(sent, lang)
        if cur is None:
            continue
        if prev is not None and cur.date() < prev.date():
            back = (prev.date() - cur.date()).days
            rolled = None
            if back > 60:
                try:
                    rolled = cur.replace(year=cur.year + 1)
                except ValueError:
                    rolled = None
            if rolled is not None and 0 <= (rolled.date() - prev.date()).days <= 200:
                cur = rolled
            else:
                return True
        prev = cur
    return False


def _anchor_dates_regress(chapters: list | None, lang: str) -> bool:
    for ch in chapters or []:
        if not isinstance(ch, dict):
            continue
        text = ch.get("text") or ""
        for anchor in ch.get("anchors") or []:
            if not isinstance(anchor, dict):
                continue
            t_raw = anchor.get("t")
            t_ms = t_raw if isinstance(t_raw, int) else _ms(t_raw)
            if t_ms is None:
                continue
            try:
                idx = int(anchor.get("charIdx") or 0)
            except (TypeError, ValueError):
                idx = 0
            if _spoken_before_anchor(_sentence_at_idx(text, idx), t_ms, lang):
                return True
    return False


def _split_upcoming(blob: str) -> list[str]:
    parts = re.split(r"\s*,\s*|\s+\bet\b\s+|\s+\band\b\s+", blob or "")
    return [part.strip(" .") for part in parts if part.strip(" .")]


def _skip_pairs(text: str, rows: list[dict]) -> bool:
    for leave in _LEAVE_FOR_RE.finditer(text or ""):
        frm = _place_core(leave.group("frm"))
        to = _place_core(leave.group("to"))
        if _is_air_leg(frm, to) or _is_side_leg(frm, to):
            continue
        if _sea_between(rows, frm, to):
            return True
    return False


def _upcoming_omits(text: str, rows: list[dict], *, here: str | None = None) -> bool:
    real = _non_air_stop_labels(rows)
    if not real:
        return False
    departed_here = here or ""
    departed = bool(here)
    for sent in _sentences(text):
        leave = _LEAVE_FOR_RE.search(sent)
        if leave:
            departed_here = _place_core(leave.group("frm"))
            departed = True
        found = _UPCOMING_RE.search(sent)
        if not found or not departed_here:
            continue
        listed = _split_upcoming(found.group(1))
        if not listed:
            continue
        ic = next((i for i, name in enumerate(real) if same_stop(name, departed_here)), None)
        i0 = next((i for i, name in enumerate(real) if same_stop(name, listed[0])), None)
        if ic is None or i0 is None:
            continue
        start = ic + 1 if departed else ic
        if any(real[start:i0]):
            return True
        prev = i0
        for name in listed[1:]:
            j = next((i for i, item in enumerate(real) if same_stop(item, name)), None)
            if j is None or j <= prev:
                continue
            if real[prev + 1:j]:
                return True
            prev = j
    return False


def _absent_places(text: str, rows: list[dict]) -> bool:
    candidates: list[str] = []
    for rx in (_FORMALITY_RE, _ARRIVAL_PLACE_RE):
        candidates.extend(_place_core(m.group(1)) for m in rx.finditer(text or ""))
    for leave in _LEAVE_FOR_RE.finditer(text or ""):
        candidates.append(_place_core(leave.group("frm")))
        candidates.append(_place_core(leave.group("to")))
    for cap in _CAP_RE.finditer(text or ""):
        candidates.append(_place_core(cap.group("to")))
    for upcoming in _UPCOMING_RE.finditer(text or ""):
        candidates.extend(_place_core(part) for part in _split_upcoming(upcoming.group(1)))
    return any(place and not _known_stop(place, rows) for place in candidates)


def _distance_mismatch(text: str, rows: list[dict]) -> bool:
    sents = _sentences(text)
    for i, sent in enumerate(sents):
        leave = _LEAVE_FOR_RE.search(sent)
        if not leave:
            continue
        frm = _place_core(leave.group("frm"))
        to = _place_core(leave.group("to"))
        blob = sent
        if i + 1 < len(sents) and not _LEAVE_FOR_RE.search(sents[i + 1]):
            blob = f"{sent} {sents[i + 1]}"
        nums = _mile_ints(blob)
        if not nums:
            continue
        stated = float(nums[0])
        span = _span_nm(rows, frm, to)
        if span is None:
            continue
        close = abs(stated - span) <= max(50.0, 0.08 * span)
        if _sea_between(rows, frm, to):
            if close:
                return True
        elif not close:
            return True
    return False


def _cap_leg_faults(text: str, rows: list[dict], frm: str, chapter_to: str = "") -> list[str]:
    """« cap sur Dzaoudzi » depuis Papeete : la destination n'est pas l'escale suivante."""
    if not frm:
        return []
    faults: list[str] = []
    for sent in _sentences(text):
        match = _CAP_RE.search(sent)
        if not match:
            continue
        cap_raw = (match.group(0) or "").strip().casefold()
        if cap_raw.startswith(("départ vers", "departure for", "departure to")):
            continue
        # « Papeete (French Polynesia) » : la région traduite ne doit pas défaire le nom.
        to = _place_core(re.sub(r"\s*\([^)]*\)", "", match.group("to") or ""))
        if not to or _is_air_leg(frm, to) or _is_side_leg(frm, to):
            continue
        if chapter_to and same_stop(to, chapter_to) and not _sea_between(rows, frm, to):
            continue
        skipped = _sea_between(rows, frm, to)
        if skipped and "skip" not in faults:
            faults.append("skip")
        nums = _mile_ints(sent)
        span = _span_nm(rows, frm, to)
        if not nums or span is None:
            continue
        close = abs(float(nums[0]) - span) <= max(50.0, 0.08 * span)
        if (skipped and close) or (not skipped and not close):
            if "distance" not in faults:
                faults.append("distance")
    return faults


def _offleg_in_chapter(chapter: dict, rows: list[dict]) -> bool:
    frm = chapter.get("fromName") or ""
    dest = chapter.get("toName") or ""
    text = chapter.get("text") or ""
    for rx in (_APPROACH_BY_RE, _SKIRTS_RE):
        for match in rx.finditer(text):
            if _off_leg_stop(_place_core(match.group(1)), frm, dest, rows, "approche"):
                return True
    return False


def nemotron_reread_report(
    text: str,
    stops: list | None,
    *,
    lang: str = "en",
    here: str | None = None,
    chapters: list | None = None,
) -> dict[str, Any]:
    """Relecture simulée, sans appel. Même verdict que celui exigé avant le stock."""
    rows = _as_stop_rows(stops)
    blob = text or ""
    if not blob and chapters:
        blob = " ".join(
            c.get("text") or "" for c in chapters if isinstance(c, dict)
        )
    faults: list[str] = []
    chapters_list = [c for c in (chapters or []) if isinstance(c, dict)]
    if chapters_list:
        for ch in chapters_list:
            ch_text = ch.get("text") or ""
            if _skip_pairs(ch_text, rows) and "skip" not in faults:
                faults.append("skip")
            if _upcoming_omits(ch_text, rows, here=here) and "upcoming" not in faults:
                faults.append("upcoming")
            if _absent_places(ch_text, rows) and "absent" not in faults:
                faults.append("absent")
            if _distance_mismatch(ch_text, rows) and "distance" not in faults:
                faults.append("distance")
            if _dates_regress(ch_text, lang) and "date" not in faults:
                faults.append("date")
        if _dates_regress(blob, lang) and "date" not in faults:
            faults.append("date")
        if _anchor_dates_regress(chapters_list, lang) and "date" not in faults:
            faults.append("date")
    else:
        if _skip_pairs(blob, rows):
            faults.append("skip")
        if _upcoming_omits(blob, rows, here=here):
            faults.append("upcoming")
        if _absent_places(blob, rows):
            faults.append("absent")
        if _distance_mismatch(blob, rows):
            faults.append("distance")
        if _dates_regress(blob, lang):
            faults.append("date")
    for chapter in chapters_list:
        if not isinstance(chapter, dict):
            continue
        for fault in _cap_leg_faults(
            chapter.get("text") or "",
            rows,
            str(chapter.get("fromName") or ""),
            str(chapter.get("toName") or ""),
        ):
            if fault not in faults:
                faults.append(fault)
        if _offleg_in_chapter(chapter, rows) and "offleg" not in faults:
            faults.append("offleg")
    return {"ok": not faults, "faults": faults, "source": "simulate"}


def _stops_from_chapters(chapters: list | None) -> list[dict]:
    rows: list[dict] = []
    for chapter in chapters or []:
        if not isinstance(chapter, dict):
            continue
        for key in ("fromName", "toName"):
            name = str(chapter.get(key) or "").strip()
            if not name:
                continue
            if rows and same_stop(rows[-1]["name"], name):
                continue
            rows.append({"name": name})
    return rows


def _insert_missing_air(rows: list[dict], clock_marks: list | None) -> list[dict]:
    """Halifax est une vraie escale aérienne : le clock la porte, pas toujours `marks`."""
    out = [dict(row) for row in rows]
    clock = [m for m in (clock_marks or []) if isinstance(m, dict) and m.get("name")]
    for i, mark in enumerate(clock):
        name = str(mark.get("name") or "")
        if not _is_air_only_stop(name) or _known_stop(name, out):
            continue
        anchor = None
        for prev in reversed(clock[:i]):
            anchor = _index_row(out, str(prev.get("name") or ""))
            if anchor is not None:
                break
        row: dict[str, Any] = {"name": name}
        nm = mark.get("filmNm") if isinstance(mark.get("filmNm"), (int, float)) else mark.get("nm")
        if isinstance(nm, (int, float)) and not isinstance(nm, bool):
            row["nm"] = float(nm)
        if anchor is None:
            out.append(row)
        else:
            out.insert(anchor + 1, row)
    return out


def _chapter_stop_names(plan: dict | None) -> list[dict]:
    """Départs et arrivées des chapitres, dans l'ordre du film."""
    return [
        {"name": str(ch.get(key) or "")}
        for ch in (plan or {}).get("chapters") or []
        if isinstance(ch, dict)
        for key in ("fromName", "toName")
        if str(ch.get(key) or "").strip()
    ]


def _route_stops_for_reread(plan: dict | None) -> list[dict]:
    """Escales du plan s'il les donne, sinon les marques du voyage (ordre de route).

    L'horloge datée du poste recolle Mata-Utu et Nouméa en fin de retour et n'en
    garde qu'une poignée : elle ne peut pas servir de contrôle.
    """
    explicit = (plan or {}).get("routeStops")
    if isinstance(explicit, list) and explicit:
        return _as_stop_rows(explicit)
    try:
        from voyage_store import load_voyage  # noqa: PLC0415
        from voyage_clock import OFFICIAL_VOYAGE_ID  # noqa: PLC0415

        voy = load_voyage(OFFICIAL_VOYAGE_ID) or {}
        marks = voy.get("marks") if isinstance(voy.get("marks"), list) else []
        clock = voy.get("clock") if isinstance(voy.get("clock"), dict) else {}
        rows = _insert_missing_air(_as_stop_rows(marks), clock.get("marks"))
        # Halifax manque aussi aux marques d'horloge du voyage officiel : le chapitre
        # du second bateau le nomme, on l'insère après l'escale qui le précède.
        rows = _insert_missing_air(rows, _chapter_stop_names(plan))
        if len(rows) >= 8:
            return rows
        named = [
            str(ch.get(key) or "")
            for ch in (plan or {}).get("chapters") or []
            if isinstance(ch, dict)
            for key in ("fromName", "toName")
            if str(ch.get(key) or "").strip()
        ]
        if len(rows) >= 2 and named and all(_known_stop(name, rows) for name in named):
            return rows
    except Exception:
        pass
    return _stops_from_chapters((plan or {}).get("chapters") or [])


def _parse_reread_verdict(text: str) -> Optional[bool]:
    raw = (text or "").strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        found = re.search(r"\{.*\}", raw, re.S)
        if not found:
            return None
        try:
            data = json.loads(found.group(0))
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict) or "ok" not in data:
        return None
    val = data.get("ok")
    if val is True or val == "true" or val == 1:
        return True
    if val is False or val == "false" or val == 0:
        return False
    return None


async def reread_before_store(
    plan: dict,
    stops: list | None,
    *,
    cascade: Callable | None = None,
    lang: str = "en",
) -> tuple[bool, dict]:
    """Contrôle local, puis Nemotron si la cascade répond. Un échec n'entre pas en stock."""
    chapters = [c for c in (plan.get("chapters") or []) if isinstance(c, dict)]
    blob = " ".join(c.get("text") or "" for c in chapters)
    report = nemotron_reread_report(blob, stops, lang=lang, chapters=chapters)
    if not report["ok"]:
        return False, report
    if cascade is None:
        return True, report
    stop_names = [_stop_spoken(row.get("name") or "") for row in _as_stop_rows(stops)]
    faults: list[str] = []
    source_seen = ""
    llm_groups = 0
    for group in _reread_groups(chapters):
        legs = [
            f"{short_name(c.get('fromName') or '')} → {short_name(c.get('toName') or c.get('destName') or '')}"
            for c in group
        ]
        here = []
        for c in group:
            for name in (c.get("fromName"), c.get("toName") or c.get("destName")):
                n = _stop_spoken(name or "")
                if n and n not in here:
                    here.append(n)
        user = json.dumps(
            {"stops": here, "legs": legs, "routeStops": stop_names,
             "text": " ".join(c.get("text") or "" for c in group)},
            ensure_ascii=False,
        )
        text, source = "", "rules"
        try:
            for _attempt in range(2):
                # Le verdict cite des dates du texte : pas de filtre des nombres.
                # Seconde demande (hors cache) si rien ou un verdict tronqué : plus court.
                ask = user if _attempt == 0 else (
                    user + "\nAnswer with one short JSON line; each fault under 12 words."
                )
                text, source = await cascade(
                    REREAD_SYSTEM, ask, tier=_reread_tier(), fallback="", facts=_verdict_facts(user),
                    max_tokens=REREAD_MAX_TOKENS,
                )
                if source not in {"rules", ""} and _parse_reread_verdict(text) is not None:
                    break
        except Exception:
            return True, report
        if source in {"rules", "budget", ""}:
            if cascade is cascade_text and _live_llm_configured():
                # Un modèle était joignable et n'a rien rendu de lisible : pas un pass.
                faults.append("verdict-illisible")
                source_seen = source_seen or "nemotron"
                break
            return True, report
        source_seen = str(source or "nemotron-super")
        llm_groups += 1
        verdict = _parse_reread_verdict(text)
        if verdict is None:
            # Verdict vide, tronqué ou illisible : jamais un pass.
            faults.append("verdict-illisible")
            break
        if verdict is False:
            said = _reread_faults(text) or ["nemotron"]
            group_text = " ".join(c.get("text") or "" for c in group)
            if _only_unconfirmed_date_faults(said, group_text, lang, here, _as_stop_rows(stops)):
                # Chaque faute dite se vérifie sur le texte : une « date qui recule »
                # que _dates_regress (dates épelées comprises) ne retrouve pas, une
                # « escale sautée » nommée en toutes lettres dans la partie, ne sont
                # pas retenues. Elles restent écrites dans le rapport.
                report.setdefault("unconfirmed", []).extend(said)
                continue
            faults.extend(said)
            break
    if faults:
        return False, {"ok": False, "faults": faults, "source": source_seen or "nemotron-super"}
    if source_seen and llm_groups:
        # N16 : le verdict vient du modèle (Ultra, porte ouverte), le contrôle local
        # n'en est que le premier filtre — le rapport ne dit plus « simulate ».
        return True, {**report, "source": source_seen, "local": report.get("source"),
                      "groups": llm_groups}
    return True, report


REREAD_MAX_TOKENS = 400


def _reread_tier() -> str:
    """Relecture par Ultra quand la porte film_ultra_open() est ouverte (par défaut) : Super,
    relecteur de lui-même, signalait des fautes qu'il démentait dans la même phrase (dates
    en ordre, escales pourtant dans la liste). Porte fermée : palier historique (Super)."""
    return "judge" if film_ultra_open() else "reread"
REREAD_GROUP_CHARS = 3500


def _verdict_facts(user: str) -> Any:
    """Un verdict n'est pas publié : pas de filtre des nombres (il le vidait)."""
    from story_cascade import NO_NUMBER_FILTER  # noqa: PLC0415
    return NO_NUMBER_FILTER


def _live_llm_configured() -> bool:
    from story_cascade import nebius_key  # noqa: PLC0415
    return bool(nebius_key())


def _reread_groups(chapters: list[dict]) -> list[list[dict]]:
    """Relecture par paquets de chapitres entiers : tout le film est lu, rien n'est coupé."""
    groups: list[list[dict]] = []
    cur: list[dict] = []
    n = 0
    for c in chapters:
        size = len(c.get("text") or "")
        if cur and n + size > REREAD_GROUP_CHARS:
            groups.append(cur)
            cur, n = [], 0
        cur.append(c)
        n += size
    if cur:
        groups.append(cur)
    return groups


def _fault_confirmed(
    fault: str, text: str, lang: str, stops_here: list[str], rows: list | None = None,
) -> bool:
    """« skip », « date », « upcoming » se vérifient sur le texte ; les autres sont gardées."""
    kind, _, what = str(fault).partition(":")
    kind = kind.strip().lower()
    if kind == "upcoming" and rows is not None:
        return bool(_upcoming_omits(text, rows))
    if kind == "date":
        return _dates_regress(text, lang)
    if kind == "skip":
        name = norm_stop(short_name(what.strip().strip("'\"«» ")))
        if not name:
            return True
        body = norm_stop(text)
        if name not in {norm_stop(short_name(s)) for s in stops_here}:
            return False  # escale d'une autre partie : jamais sautée ici
        return name not in body
    if kind == "off-route":
        # « off-route: Saint-Denis » alors que le texte dit « le bateau longe
        # Saint-Denis » / « the boat sails past Saint-Denis » : une côte vue en mer,
        # posée par le constructeur, pas une escale inventée.
        name = what.strip().strip("'\"«» .")
        if name and _passed_at_sea(name, text):
            return False
    return True


_PASSING_LEAD_RE = (
    r"(?:longe|longeant|passe au large de|sails? (?:past|alongside|along|by)|follows|hugs|skirts|"
    r"passes|passing|eaux d[eu']s?|eaux de la|waters of(?: the)?)"
)


def _passed_at_sea(name: str, text: str) -> bool:
    """Le nom n'apparaît, dans la partie, qu'en passage (côte longée, eaux)."""
    if not name or name.casefold() not in (text or "").casefold():
        return False
    hits = [m.start() for m in re.finditer(re.escape(name), text, re.I)]
    for at in hits:
        before = text[max(0, at - 40):at]
        if not re.search(_PASSING_LEAD_RE + r"\s*(?:l['’]|la |le |les |the )?$", before, re.I):
            return False
    return bool(hits)


def _only_unconfirmed_date_faults(
    faults: list[str], text: str, lang: str, stops_here: list[str] | None = None,
    rows: list | None = None,
) -> bool:
    """Vrai si AUCUNE faute dite par le relecteur ne se vérifie sur le texte."""
    if not faults:
        return False
    return not any(_fault_confirmed(f, text, lang, stops_here or [], rows) for f in faults)


def _reread_faults(text: str) -> list[str]:
    found = re.search(r"\{.*\}", (text or "").strip(), re.S)
    try:
        data = json.loads(found.group(0)) if found else {}
    except json.JSONDecodeError:
        return []
    faults = data.get("faults") if isinstance(data, dict) else None
    return [str(f)[:200] for f in faults] if isinstance(faults, list) else []


def written_is_valid(
    text: str, facts: Any, event_ids: list[str], seconds: Any = 150,
) -> tuple[bool, str, int]:
    """No new number, every [[ev:id]] present, window from film_char_budget."""
    filtered, dropped = filter_numbers(text, facts, spelled=True)
    if dropped:
        return False, filtered, dropped
    for eid in event_ids:
        if f"[[ev:{eid}]]" not in (text or ""):
            return False, filtered, dropped
    n = len(strip_tags(text))
    window = film_write_window(seconds)
    if window is not None:
        lo, hi = window
        if n < lo or n > hi:
            return False, filtered, dropped
    return True, filtered, 0


def _parse_selection(text: str, allowed: set[str]) -> Optional[list[str]]:
    raw = (text or "").strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    ids = data.get("ids") if isinstance(data, dict) else None
    if not isinstance(ids, list):
        return None
    kept = [str(i) for i in ids if str(i) in allowed]
    if FILM_MIN_EVENTS <= len(kept) <= FILM_MAX_EVENTS:
        return kept
    return None


def _snap_to_sentence(text: str, pos: int) -> int:
    if pos <= 0:
        return 0
    if pos >= len(text):
        return len(text)
    prev = max(text.rfind(".", 0, pos), text.rfind("!", 0, pos), text.rfind("?", 0, pos))
    nxt_hits = [i for i in (text.find(".", pos), text.find("!", pos), text.find("?", pos)) if i >= 0]
    nxt = min(nxt_hits) if nxt_hits else -1
    if prev >= 0 and (nxt < 0 or pos - prev <= nxt - pos + 8):
        return min(len(text), prev + 1)
    if nxt >= 0:
        return min(len(text), nxt + 1)
    return pos


def _distribute_written(raw_chapters: list[dict], display: str, located: list[dict]) -> list[dict]:
    total = sum(max(1, len(c.get("text") or "")) for c in raw_chapters) or 1
    pos = 0
    out: list[dict] = []
    for i, ch in enumerate(raw_chapters):
        if i == len(raw_chapters) - 1:
            end = len(display)
        else:
            raw_n = max(1, round(len(display) * max(1, len(ch.get("text") or "")) / total))
            end = _snap_to_sentence(display, pos + raw_n)
            if end <= pos:
                end = min(len(display), pos + max(raw_n, 1))
        chunk = display[pos:end]
        evs = []
        for e in located:
            if pos <= e["charIdx"] < max(end, pos + 1) or (i == len(raw_chapters) - 1 and e["charIdx"] >= pos):
                evs.append({**e, "charIdx": max(0, e["charIdx"] - pos)})
        out.append({**ch, "text": chunk, "events": evs})
        pos = end
    return out


SELECT_SYSTEM = (
    "You select event ids for an expedition film from the given bag. "
    "You receive a schematic image of the whole tour and the candidate ids "
    "(marine area, buoy, formality, anchorage, beacon, cable, depth, piracy, "
    "satellite included). "
    "Return JSON only: {\"ids\":[...]}. "
    "Choose only among the given ids. Drop any other id. "
    "Do not invent numbers. Do not write narrative. Keep no free text."
)
TRIM_SYSTEM = (
    "You only remove ids so the film fits the character budget. "
    "Return JSON only: {\"ids\":[...]}. "
    "Every id must already be in the given list. Do not add an id. "
    "Do not write narrative."
)
WRITE_SYSTEM = (
    "You rewrite ONE film chapter from structured facts, sentence by sentence. "
    "Output EXACTLY one sentence per raw sentence, in the same order. "
    "Keep EVERY number, proper name and date exactly as given. "
    "Do not add a fact. Do not invent a figure, a place or a date. "
    "Write for the ear: spoken French or English as requested. "
    "Units in full words (milles nautiques / nautical miles), never nm. "
    "Thinking OFF. No tags. No new figure."
)
EDIT_SYSTEM = (
    "You edit an already-written French expedition film. "
    "Keep every number, proper name and date exactly. "
    "Same sentence count and order. Do not add a fact. "
    "Output only the edited French. Thinking OFF."
)
JUDGE_SYSTEM = (
    "You judge an already-written film text, one chapter at a time. Do not rewrite it. "
    "`facts` and `reference` are the verified sources for this chapter: every name, "
    "number and date found there is true. "
    "Return JSON only, one short line: {\"ok\": true|false, \"reason\": \"one line\"}. "
    "ok=false only if the text states a number, name or date absent from facts and reference."
)


async def select_with_llm(
    candidates: list[dict],
    fallback_ids: list[str],
    *,
    cascade: Callable = cascade_text,
    tour: dict | None = None,
) -> tuple[list[str], str]:
    slim = [
        {
            "id": c.get("id"), "kind": c.get("kind"), "t": c.get("t"),
            "name": c.get("name"), "score": c.get("score"), "role": c.get("role"),
        }
        for c in candidates
        if isinstance(c, dict) and c.get("id")
    ]
    payload: dict[str, Any] = {"candidates": slim[:150], "need": "ids from bag only"}
    if tour:
        payload["tour"] = tour
    user = json.dumps(payload, ensure_ascii=False)
    if len(user) > 8000:
        user = user[:8000]
    text, source = await cascade(SELECT_SYSTEM, user, tier="nano", fallback="", facts=user, max_tokens=256)
    parsed = _parse_selection(text, {str(c["id"]) for c in slim})
    if parsed:
        return parsed, source
    return fallback_ids, "rules"


async def select_ids_with_vl(
    bag: list[dict],
    tour: dict | None,
    *,
    cascade: Callable = cascade_text,
    seconds: Any = 150,
) -> tuple[list[str], str]:
    """Nano : JSON d'ids du sac. Un id absent est jeté. Aucune prose gardée."""
    fallback = fallback_choose_ids(bag, seconds)
    slim = [c for c in bag if isinstance(c, dict) and c.get("id")]
    payload: dict[str, Any] = {"candidates": [
        {"id": c.get("id"), "kind": c.get("kind"), "name": c.get("name")}
        for c in slim
    ], "need": "ids from bag only"}
    if tour:
        payload["tour"] = tour
    user = json.dumps(payload, ensure_ascii=False)
    if len(user) > 8000:
        user = user[:8000]
    text, source = await cascade(SELECT_SYSTEM, user, tier="nano", fallback="", facts=user, max_tokens=256)
    parsed = parse_choice_ids(text, {str(c["id"]) for c in slim})
    if parsed is not None:
        return parsed, source
    return fallback, "rules"


async def trim_ids_with_lightning(
    ids: list[str],
    bag: list[dict],
    seconds: Any,
    *,
    cascade: Callable = cascade_text,
) -> tuple[list[str], str]:
    """Nano ne peut que retirer (repli Lightning, puis NIM). Un id ajouté est jeté. Puis film_char_budget."""
    allowed = [str(i) for i in ids]
    allowed_set = set(allowed)
    budget = film_char_budget(seconds)
    user = json.dumps(
        {"ids": allowed, "budgetChars": budget, "seconds": _film_seconds(seconds)},
        ensure_ascii=False,
    )
    text, source = await cascade(
        TRIM_SYSTEM, user, tier="nano", fallback="", facts=user, max_tokens=256,
    )
    parsed = parse_choice_ids(text, allowed_set)
    if parsed is None:
        parsed = list(allowed)
    parsed = [i for i in parsed if i in allowed_set]
    return _trim_ids_to_budget(parsed, bag, seconds), source


def _vb1_extra_ids(bag: list[dict]) -> list[str]:
    """Ids du cache de route déjà dans le sac. Cache absent : liste vide."""
    try:
        import vl_route  # noqa: PLC0415
        found = vl_route.ids_for_bag(bag)
    except Exception:
        return []
    if not isinstance(found, list):
        return []
    allowed = {str(c.get("id")) for c in bag or [] if isinstance(c, dict) and c.get("id")}
    out: list[str] = []
    seen: set[str] = set()
    for item in found:
        sid = str(item)
        if sid in allowed and sid not in seen:
            seen.add(sid)
            out.append(sid)
    return out


def _append_route_ids(ids: list[str], extra: list[str], bag: list[dict]) -> list[str]:
    allowed = {str(c.get("id")) for c in bag or [] if isinstance(c, dict) and c.get("id")}
    out: list[str] = []
    seen: set[str] = set()
    for raw in list(ids) + list(extra):
        sid = str(raw)
        if sid not in allowed or sid in seen:
            continue
        seen.add(sid)
        out.append(sid)
    return out


async def choose_film_ids(
    bag: list[dict],
    tour: dict | None,
    seconds: Any,
    *,
    cascade: Callable = cascade_text,
    allow_llm: Optional[bool] = None,
) -> tuple[list[str], str]:
    """Un choix par film (empreinte du stock), pas par chapitre ni par visite.

    Cache de route absent : même empreinte, mêmes ids. Présent : ids du sac
    ajoutés après le choix ou le repli. Le suffixe de ce cache n'entre
    que dans la clef de coupe, pas dans celle du choix. Nano (JSON d'ids),
    puis le budget, tranchent.
    """
    import llm_budget  # noqa: PLC0415
    import pearl_store  # noqa: PLC0415

    extra = _vb1_extra_ids(bag)
    base_fp = film_choice_fingerprint(bag, tour)
    fp = base_fp
    if extra:
        fp = f"{base_fp}|vb1:{hashlib.sha256(','.join(extra).encode('utf-8')).hexdigest()[:12]}"
    secs = _film_seconds(seconds)
    trim_key = f"trim|{fp}|{secs}"
    hit_trim = pearl_store.kv_get(FILM_CHOICE_NS, trim_key, FILM_CHOICE_TTL_S)
    cached = (hit_trim or {}).get("value")
    if isinstance(cached, dict) and isinstance(cached.get("ids"), list):
        return [str(i) for i in cached["ids"]], "cache"

    if allow_llm is None:
        allow_llm = llm_budget.allow("nano")

    if not allow_llm:
        ids = fallback_choose_ids(bag, seconds)
        if extra:
            ids = _trim_ids_to_budget(_append_route_ids(ids, extra, bag), bag, seconds)
        pearl_store.kv_put(FILM_CHOICE_NS, trim_key, {"ids": ids, "source": "rules"})
        return ids, "rules"

    vl_key = f"vl|{base_fp}"
    vl_ids: Optional[list[str]] = None
    vl_src = "rules"
    hit_vl = pearl_store.kv_get(FILM_CHOICE_NS, vl_key, FILM_CHOICE_TTL_S)
    stored_vl = (hit_vl or {}).get("value")
    if isinstance(stored_vl, dict) and isinstance(stored_vl.get("ids"), list):
        vl_ids = [str(i) for i in stored_vl["ids"]]
        vl_src = str(stored_vl.get("source") or "cache")
    if vl_ids is None:
        try:
            vl_ids, vl_src = await select_ids_with_vl(bag, tour, cascade=cascade, seconds=seconds)
        except Exception:
            vl_ids, vl_src = None, "rules"
        if vl_ids is None:
            ids = fallback_choose_ids(bag, seconds)
            if extra:
                ids = _trim_ids_to_budget(_append_route_ids(ids, extra, bag), bag, seconds)
            pearl_store.kv_put(FILM_CHOICE_NS, trim_key, {"ids": ids, "source": "rules"})
            return ids, "rules"
        pearl_store.kv_put(FILM_CHOICE_NS, vl_key, {"ids": vl_ids, "source": vl_src})

    if extra and vl_ids is not None:
        vl_ids = _append_route_ids(vl_ids, extra, bag)

    try:
        ids, src = await trim_ids_with_lightning(vl_ids, bag, seconds, cascade=cascade)
    except Exception:
        ids, src = _trim_ids_to_budget(vl_ids, bag, seconds), vl_src
    pearl_store.kv_put(FILM_CHOICE_NS, trim_key, {"ids": ids, "source": src})
    return ids, src


def _chapter_next_summary(raw_chapters: list[dict], i: int, lang: str) -> str:
    if i + 1 >= len(raw_chapters):
        return "end of the voyage" if _en(lang) else "fin du voyage"
    nxt = raw_chapters[i + 1]
    frm = short_name(nxt.get("fromName") or "")
    to = short_name(nxt.get("toName") or "")
    if to:
        return f"the next leg leads to {to}" if _en(lang) else f"la jambe suivante mène à {to}"
    return f"under way from {frm}" if _en(lang) else f"en route depuis {frm}"


def _pad_tagged(text: str, budget: int) -> str:
    """Plus de remplissage : on coupe si trop long, on ne meuble jamais."""
    body = text or ""
    cap = int(budget or 0)
    if cap <= 0:
        return body
    hi = max(int(cap * 1.1), cap)
    display = strip_tags(body)
    if len(display) > hi:
        body = body[: max(0, len(body) - (len(display) - hi))]
    return body


def _chapter_provenance(result: Any) -> dict[str, str]:
    """Exact metadata for accepted chapter text; judges/reviews never call this.

    Rules/budget fallbacks and validation-only calls have no chapter attribution.
    """
    model = str(getattr(result, "model", "") or "").strip()
    source = str(result[1] or "").strip() if isinstance(result, (tuple, list)) and len(result) > 1 else ""
    tier = str(getattr(result, "tier", "") or "").strip()
    return {"served_model": model, "served_source": source, "served_tier": tier} if model and source else {}


async def write_stored_plan(
    plan: dict,
    *,
    lang: str = "fr",
    cascade: Callable = cascade_text,
    seconds: Any = None,
) -> tuple[Optional[dict], dict[str, Any]]:
    """Réécrit un plan public (stock) phrase par phrase. Aucun appel si la cascade rend rules/budget."""
    raw_chapters = [c for c in (plan.get("chapters") or []) if isinstance(c, dict)]
    stats = {"rewritten": 0, "fallen": 0, "source": "rules", "model": None}
    if not raw_chapters:
        return None, stats
    secs = seconds if seconds is not None else plan.get("targetSeconds")
    budget_total = film_char_budget(secs)
    raw_lens = [max(1.0, len(c.get("text") or "") or 1) for c in raw_chapters]
    budgets = allocate_chapter_budgets(raw_lens, budget_total) if budget_total else [0] * len(raw_chapters)
    chapters_out: list[dict] = []
    source_last = "rules"
    any_llm = False
    for i, ch in enumerate(raw_chapters):
        raw = ch.get("text") or ""
        raw_sents = _sentences(raw)
        facts = chapter_structured_facts(ch, lang=lang)
        if not raw_sents:
            chapters_out.append(ch)
            continue
        user = (
            f"lang={'en' if _en(lang) else 'fr'}\n"
            f"facts={json.dumps(facts, ensure_ascii=False, default=str)}\n"
            f"sentences={json.dumps(raw_sents, ensure_ascii=False)}"
        )
        max_tok = min(WRITE_MAX_TOKENS, max(400, 80 * len(raw_sents)))
        result = await cascade(
            WRITE_SYSTEM, user, tier="write", fallback="", facts=facts, max_tokens=max_tok,
        )
        text, source = result
        stats["model"] = getattr(result, "model", None) or stats["model"]
        if not (text or "").strip() or source in {"rules", "budget"}:
            chapters_out.append(ch)
            stats["fallen"] += len(raw_sents)
            if source == "budget":
                source_last = "budget"
            continue
        any_llm = True
        source_last = source if public_written_source(source_last) in {"rules", "budget", WRITTEN_SOURCE} else source_last
        guarded, rw, fb = apply_written_guard(raw, text, facts, lang=lang)
        cap = budgets[i] if i < len(budgets) else 0
        if cap:
            hi = max(int(cap * 1.1), cap, len(raw))
            guarded, extra_fb = _trim_written_to_budget(raw, guarded, hi)
            if extra_fb:
                fb += extra_fb
                rw = max(0, rw - extra_fb)
        anchors = reanchor_written_chapter(ch, guarded, lang)
        chapters_out.append({**ch, **_chapter_provenance(result), "text": guarded, "anchors": anchors})
        stats["rewritten"] += rw
        stats["fallen"] += fb
    stats["source"] = source_last
    if not any_llm or stats["rewritten"] <= 0:
        return None, stats
    n = script_chars(chapters_out)
    return {
        "chapters": chapters_out,
        "source": written_source_label(source_last),
        "chars": n,
        "targetSeconds": _film_seconds(plan.get("targetSeconds") if secs is None else secs),
        "hasWritten": True,
    }, stats


async def write_with_llm(
    raw: dict,
    events: list[dict],
    *,
    lang: str = "fr",
    cascade: Callable = cascade_text,
) -> tuple[Optional[dict], str]:
    """RG11A : rédigé phrase par phrase depuis les faits. Repli local, jamais un échec global."""
    _ = events
    plan, stats = await write_stored_plan(raw, lang=lang, cascade=cascade)
    if plan is None:
        return None, stats.get("source") or "rules"
    return plan, stats.get("source") or plan.get("source") or "rules"


def film_ultra_open() -> bool:
    """Ultra (éditer + juger le film rédigé) ouvert PAR DÉFAUT, borné par le plafond judge.

    - Variable NAVIGUIDE_LLM_DAILY_TOKENS_JUDGE absente ou vide : plafond par défaut de
      llm_budget (DEFAULT_CAPS["judge"]), donc ouvert tant que le plafond du jour n'est pas
      atteint. C'est ce que README et la visite « Qui fait quoi » annoncent.
    - Valeur explicite <= 0 : interrupteur de l'opérateur, fermé (repli Super VL).
    - Valeur invalide (« off », « 250k »…) : fermé. Choix prudent : l'opérateur a voulu
      régler le plafond ; on ne dépense pas Ultra sur une valeur qu'on ne comprend pas.
    - Plafond du jour atteint, plafond dollar, ou NAVIGUIDE_LLM_MODE=off : llm_budget.allow
      renvoie False, fermé, aucun appel payant.
    """
    import os  # noqa: PLC0415
    import llm_budget  # noqa: PLC0415

    raw = (os.environ.get("NAVIGUIDE_LLM_DAILY_TOKENS_JUDGE") or "").strip()
    if raw:
        try:
            if int(raw) <= 0:
                return False
        except ValueError:
            return False
    if llm_budget.daily_cap("judge") <= 0:
        return False
    return llm_budget.allow("judge")


def _parse_judge_ok(text: str) -> Optional[bool]:
    raw = (text or "").strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict) or "ok" not in data:
        return None
    val = data.get("ok")
    if val is True or val == "true" or val == 1:
        return True
    if val is False or val == "false" or val == 0:
        return False
    return None


def _stamp_written_plan(
    plan: dict,
    source: str,
    seconds: Any,
    *,
    reviewed_by: str | None = None,
    model: str | None = None,
) -> dict:
    chapters = [c for c in (plan.get("chapters") or []) if isinstance(c, dict)]
    n = script_chars(chapters)
    out = dict(plan)
    out["chapters"] = chapters
    public = public_written_source(source) or str(source or "")
    out["source"] = public
    out["chars"] = n
    out["targetSeconds"] = _film_seconds(seconds if seconds is not None else plan.get("targetSeconds"))
    # Durée estimée du texte stampé (l'anglais héritait des 158 s du français).
    out["estimatedSeconds"] = film_estimated_seconds(n)
    out["hasWritten"] = True
    if reviewed_by:
        out["reviewedBy"] = reviewed_by
    else:
        out.pop("reviewedBy", None)
    if public == WRITTEN_SOURCE:
        out["model"] = model or out.get("model") or _write_model()
    elif model:
        out["model"] = model
    return out


def _redistribute_written_blob(raw_plan: dict, blob: str, *, lang: str = "fr") -> Optional[dict]:
    raw_chapters = [c for c in (raw_plan.get("chapters") or []) if isinstance(c, dict)]
    if not raw_chapters:
        return None
    sents = _sentences(blob)
    idx = 0
    out: list[dict] = []
    rewritten = 0
    for ch in raw_chapters:
        raw = ch.get("text") or ""
        n = len(_sentences(raw))
        chunk = " ".join(sents[idx:idx + n]) if n else raw
        idx += n
        facts = chapter_structured_facts(ch, lang=lang)
        guarded, rw, _fb = apply_written_guard(raw, chunk, facts, lang=lang)
        anchors = reanchor_written_chapter(ch, guarded, lang)
        out.append({**ch, "text": guarded, "anchors": anchors})
        rewritten += rw
    if rewritten <= 0:
        return None
    return _stamp_written_plan({**raw_plan, "chapters": out}, WRITTEN_SOURCE, raw_plan.get("targetSeconds"))


def _raw_for(ch: dict, i: int, raw_chapters: list[dict]) -> Optional[dict]:
    cid = ch.get("id")
    if cid is not None:
        for r in raw_chapters:
            if r.get("id") == cid:
                return r
    return raw_chapters[i] if i < len(raw_chapters) else None


ULTRA_EDIT_MAX_TOKENS = 4096
ULTRA_JUDGE_MAX_TOKENS = 512


def _looks_cut(src: str, out: str) -> bool:
    """Sortie tronquée : fin sans ponctuation, ou nettement plus courte que la source."""
    o = (out or "").strip()
    if not o:
        return True
    if not o.endswith((".", "!", "?", "…", "»", ")")):
        return True
    return len(o) < 0.7 * len((src or "").strip())


async def edit_written_once(
    super_plan: dict,
    raw_plan: dict,
    *,
    cascade: Callable = cascade_text,
) -> Optional[dict]:
    """Ultra édite le français de Super chapitre par chapitre.

    Le film entier (~11 000 car.) dépassait la sortie permise : l'édition revenait
    tronquée (finish=length) et le juge la refusait. Par chapitre, chaque sortie
    tient ; un chapitre tronqué garde le texte de Super.
    """
    chapters = [c for c in (super_plan.get("chapters") or []) if isinstance(c, dict)]
    if not any((c.get("text") or "").strip() for c in chapters):
        return None
    raw_chapters = [c for c in (raw_plan.get("chapters") or []) if isinstance(c, dict)]
    out: list[dict] = []
    rewritten = 0
    for i, ch in enumerate(chapters):
        src = (ch.get("text") or "").strip()
        raw_ch = _raw_for(ch, i, raw_chapters) or ch
        if not src:
            out.append(ch)
            continue
        facts = chapter_structured_facts(raw_ch, lang="fr")
        user = f"facts={json.dumps(facts, ensure_ascii=False, default=str)}\ntext={src}"
        max_tok = min(ULTRA_EDIT_MAX_TOKENS, max(600, len(src) + 200))
        # Pas de filtre brut des nombres dans la cascade : Super a déjà ses chiffres
        # (« 12 nœuds » pour « douze nœuds » des faits) et le filtre coupait ces
        # phrases ; le garde-fou ci-dessous refaisait alors l'alignement de travers
        # (« Arrivée à Ajaccio… » dite deux fois, les alizés perdus). Le garde-fou
        # vérifie les nombres, épelés compris.
        from story_cascade import NO_NUMBER_FILTER  # noqa: PLC0415
        result = await cascade(
            EDIT_SYSTEM, user, tier="judge", fallback="", facts=NO_NUMBER_FILTER, max_tokens=max_tok,
        )
        text, source = result
        if not str(source).endswith("-ultra") or _looks_cut(src, text):
            out.append(ch)
            continue
        if len(_sentences(text or "")) < len(_sentences(src)):
            # Une phrase perdue : l'alignement phrase à phrase du garde-fou glisserait.
            out.append(ch)
            continue
        # Le garde-fou aligne phrase à phrase : si la 2:30 a déjà retiré des
        # phrases du brut (Super condensé), l'aligner sur le brut décalait tout
        # et recollait l'arrivée du brut après celle d'Ultra (« Arrivée à
        # Pointe-à-Pitre le 18 juillet. » ×2). On s'aligne alors sur Super.
        # Ultra ne remet pas les phrases que la condensation a retirées : un
        # nombre de phrases différent de Super garde le chapitre de Super
        # (sinon le garde-fou coupait l'arrivée — Saint-Pierre le 21 août).
        ref = raw_ch.get("text") or src
        if len(_sentences(ref)) != len(_sentences(src)):
            if len(_sentences(text or "")) != len(_sentences(src)):
                out.append(ch)
                continue
            ref = src
        guarded, rw, _fb = apply_written_guard(ref, text.strip(), facts, lang="fr")
        guarded = " ".join(dedupe_arrival_sentences(_sentences(guarded)))
        if rw <= 0:
            out.append(ch)
            continue
        out.append({**ch, **_chapter_provenance(result), "text": guarded, "anchors": reanchor_written_chapter(raw_ch, guarded, "fr")})
        rewritten += 1
    if rewritten <= 0:
        return None
    return _stamp_written_plan(
        {**super_plan, "chapters": out}, WRITTEN_SOURCE, super_plan.get("targetSeconds"),
    )


async def judge_written_chapters(
    plan: dict,
    *,
    cascade: Callable = cascade_text,
    raw_plan: dict | None = None,
    only: set[int] | None = None,
) -> Optional[list[int]]:
    """Ultra juge chaque chapitre contre SES faits ; rend les indices refusés.

    None : verdict impossible (réseau, budget, film vide). Un verdict vide,
    tronqué ou illisible compte comme un refus du chapitre.
    """
    chapters = [c for c in (plan.get("chapters") or []) if isinstance(c, dict)]
    raw_chapters = [c for c in ((raw_plan or {}).get("chapters") or []) if isinstance(c, dict)]
    if not any((c.get("text") or "").strip() for c in chapters):
        return None
    failed: list[int] = []
    for i, ch in enumerate(chapters):
        if only is not None and i not in only:
            continue
        txt = (ch.get("text") or "").strip()
        if not txt:
            continue
        raw_ch = _raw_for(ch, i, raw_chapters)
        facts = chapter_structured_facts(raw_ch or ch, lang="fr")
        ref = (raw_ch or {}).get("text") or ""
        user = json.dumps({"facts": facts, "reference": ref, "text": txt}, ensure_ascii=False, default=str)
        text, source = "", "rules"
        for _attempt in range(2):
            # Une coupure réseau (cascade → « rules ») est retentée une fois.
            text, source = await cascade(
                JUDGE_SYSTEM, user, tier="judge", fallback="", facts=_verdict_facts(user),
                max_tokens=ULTRA_JUDGE_MAX_TOKENS,
            )
            if source != "rules":
                break
        if source in {"rules", "budget"}:
            return None
        if _parse_judge_ok(text) is not True:
            failed.append(i)
    return failed


async def judge_written_once(
    plan: dict,
    *,
    cascade: Callable = cascade_text,
    raw_plan: dict | None = None,
) -> bool:
    """Ultra juge chaque chapitre contre SES faits, sans le réécrire.

    Sans les faits, le juge prenait les eaux et projets croisés pour des lieux
    inventés. Un verdict vide, tronqué ou illisible n'est jamais un accord.
    """
    failed = await judge_written_chapters(plan, cascade=cascade, raw_plan=raw_plan)
    return failed == []


def _restore_chapters(edited: dict, fallback: dict, failed: list[int]) -> dict:
    """Chapitres refusés par le juge : on reprend le texte d'avant l'édition (même id)."""
    by_id = {c.get("id"): c for c in (fallback.get("chapters") or []) if isinstance(c, dict)}
    fb_list = [c for c in (fallback.get("chapters") or []) if isinstance(c, dict)]
    chapters = [c for c in (edited.get("chapters") or []) if isinstance(c, dict)]
    out = []
    for i, ch in enumerate(chapters):
        if i in failed:
            prev = by_id.get(ch.get("id")) or (fb_list[i] if i < len(fb_list) else None)
            out.append(prev or ch)
        else:
            out.append(ch)
    return {**edited, "chapters": out}


_EN_GEO_WORDS = frozenset({
    "islands", "island", "isles", "waters", "sea", "ocean", "coast", "bay", "harbour", "harbor",
    "port", "marina", "north", "south", "east", "west", "northern", "southern", "eastern",
    "western", "french", "african", "malagasy", "canary", "cape", "verde", "atlantic",
    "pacific", "indian", "southern", "antarctic", "lands", "territories", "nova", "scotia",
    "guiana", "polynesia", "caledonia", "new", "corsica", "reunion", "réunion", "barts",
    "saint", "st", "and", "of", "the", "a", "on", "at", "by", "for", "to", "with", "then",
    "today", "after", "before", "next", "day", "days", "high", "seas", "float", "station",
    "project", "protected", "area", "marine", "crew", "boat", "catamaran", "expedition",
    # adjectifs de nationalité : « eaux espagnoles » → « Spanish waters »
    "spanish", "moroccan", "portuguese", "italian", "brazilian", "mauritanian", "senegalese",
    "verdean", "barbadian", "venezuelan", "guyanese", "surinamese", "samoan", "tongan",
    "fijian", "mozambican", "comorian", "seychellois", "mauritian", "australian", "namibian",
    "angolan", "canadian", "american", "british", "irish", "bermudian", "bahamian",
    "dominican", "haitian", "cuban", "jamaican", "colombian", "panamanian", "ecuadorian",
    "chilean", "peruvian", "polynesian", "indonesian", "madeira", "azores", "balearic",
    "sicilian", "sardinian", "greek", "tunisian", "algerian", "maltese", "kiwi", "zealand",
    "year", "one", "two", "three", "four", "five", "phase",
    "trinidad", "tobago", "kitts", "nevis", "eustatius", "lucia", "vincent", "grenadines",
    "christopher", "virgin", "turks", "caicos", "cayman", "falkland", "helena", "ascension",
    "dutch", "german", "norwegian", "swedish", "danish", "icelandic", "japanese", "chinese",
    # Ajouts de #136 que le préfixe FR ne retrouve pas (« sri-lankaises » → « Lankan »).
    "lankan", "omani", "thai", "myanmar", "malaysian", "palauan", "gambian",
}) | frozenset(
    # Une seule source : les démonymes anglais de la table des toponymes.
    w.casefold()
    for row in toponyms.territories()
    for w in re.findall(r"[^\W\d_]+", str(row.get("adj_en") or ""))
)

# « une trentaine de jours » → « about thirty days » : l'approximation dite en anglais.
_FR_APPROX = {
    "huitaine": (8, 7, 1), "dizaine": (10,), "douzaine": (12,), "quinzaine": (15, 2, 14),
    "vingtaine": (20,), "trentaine": (30,), "quarantaine": (40,), "cinquantaine": (50,),
    "soixantaine": (60,), "centaine": (100,),
}


def _fr_approx_numbers(fr_src: str) -> list[str]:
    low = (fr_src or "").casefold()
    return [str(n) for w, ns in _FR_APPROX.items() if w in low for n in ns]


def _en_translation_names(en_text: str, fr_src: str) -> set[str]:
    """Noms anglais tolérés : exonyme ou adjectif d'un mot déjà dans le français (« Samoan » ← « samoanes »)."""
    import difflib  # noqa: PLC0415
    import unicodedata  # noqa: PLC0415

    def _fold(x: str) -> str:
        return "".join(c for c in unicodedata.normalize("NFKD", x) if not unicodedata.combining(c))

    fr_words = {_fold(w.casefold()) for w in re.findall(r"[^\W\d_]+", fr_src or "")}
    out: set[str] = set()
    for tok in _name_tokens(en_text):
        parts = [_fold(p.replace("’", "'").split("'")[-1]) for p in tok.split("-") if p] or [tok]
        if all(
            p in _EN_GEO_WORDS or p in fr_words
            or any(len(p) >= 6 and w.startswith(p[:6]) for w in fr_words)
            # « Movement » ← « Mouvement » : même mot, graphie anglaise
            or any(len(p) >= 5 and difflib.SequenceMatcher(None, p, w).ratio() >= 0.75 for w in fr_words)
            for p in parts if p
        ):
            out.add(tok)
    return out


_APPROX_EN_DAYS = {
    "huitaine": "about a week", "dizaine": "about ten days", "vingtaine": "about twenty days",
    "trentaine": "about thirty days", "quarantaine": "about forty days",
    "cinquantaine": "about fifty days", "soixantaine": "about sixty days",
}


def _fix_fortnight(text: str, fr_src: str) -> str:
    low = (fr_src or "").casefold()
    hits = [en for fr, en in _APPROX_EN_DAYS.items() if f"{fr} de jours" in low]
    if len(hits) != 1:
        return text
    return re.sub(r"\b(?:a|about a|nearly a)\s+fortnight\b", hits[0], text, flags=re.I)


_FR_MONTHS_EN = {
    "janvier": "january", "février": "february", "mars": "march", "avril": "april",
    "mai": "may", "juin": "june", "juillet": "july", "août": "august",
    "septembre": "september", "octobre": "october", "novembre": "november", "décembre": "december",
}
_FR_DAY_RE = re.compile(r"\b(1er|\d{1,2})\s+(" + "|".join(_FR_MONTHS_EN) + r")\b", re.I)
_EN_MONTHS = "|".join(m.capitalize() for m in _FR_MONTHS_EN.values())
_EN_DAY_RE = re.compile(
    rf"\b(?:(?P<m1>{_EN_MONTHS})\s+(?P<d1>\d{{1,2}})(?:st|nd|rd|th)?|(?P<d2>\d{{1,2}})(?:st|nd|rd|th)?\s+(?P<m2>{_EN_MONTHS}))\b",
)


def en_month_first(text: str) -> str:
    """Une seule forme de date en anglais : « On 4 June » / « On June 4 » mêlés
    d'un chapitre à l'autre → toujours « June 4 » (« May 15, 2026 » avec l'année)."""
    def _swap(m: re.Match) -> str:
        day, month, year = m.group(1), m.group(2), m.group(3)
        return f"{month} {day}, {year}" if year else f"{month} {day}"

    out = re.sub(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_EN_MONTHS})\b(?:\s+(\d{{4}})\b)?", _swap, text or "")
    # « July 30th » / « August 15th » : une seule forme, sans ordinal.
    return re.sub(rf"\b({_EN_MONTHS})\s+(\d{{1,2}})(?:st|nd|rd|th)\b", r"\1 \2", out)


def _repair_en_days(src: str, text: str) -> str:
    """Lightning déplace parfois un jour (« 17 juin » → « June 16 ») : le garde-fou
    recollait la phrase française et tout l'anglais tombait. Phrase à phrase (même
    nombre de phrases), le jour du même mois reprend celui du français."""
    fr_s, en_s = _sentences(src or ""), _sentences(text or "")
    if not fr_s or len(fr_s) != len(en_s):
        return text
    out = []
    changed = False
    for fr, en in zip(fr_s, en_s):
        fr_days = [(1 if d.casefold() == "1er" else int(d), _FR_MONTHS_EN[m.casefold()])
                   for d, m in _FR_DAY_RE.findall(fr)]
        en_hits = list(_EN_DAY_RE.finditer(en))
        if len(fr_days) != len(en_hits) or not fr_days:
            out.append(en)
            continue
        new = en
        for (day, month), m in reversed(list(zip(fr_days, en_hits))):
            grp = "d1" if m.group("d1") else "d2"
            if (m.group("m1") or m.group("m2") or "").casefold() != month:
                continue
            if int(m.group(grp)) != day:
                a, b = m.span(grp)
                new = new[:a] + str(day) + new[b:]
        changed = changed or new != en
        out.append(new)
    return " ".join(out) if changed else text


_TRANSLATE_LEADS = (
    "French text:\n",
    "Translate into English only:\n",
    "Write this French sailing log in English (every sentence, same order):\n",
)


def _sentence_key(x: str) -> str:
    k = re.sub(r"\s*\([^)]*\)", "", x or "").replace("’", "'").casefold().strip(" .")
    if re.match(r"^(?:arrivée|arrival)\b", k):
        k = k.split(",", 1)[0]
    return re.sub(r"\s+", " ", k)


def dedupe_chapter_sentences(text: str) -> str:
    """Deux phrases voisines qui disent la même chose (« Arrivée à Pointe-à-Pitre le
    18 juillet. » puis la même avec « (Guadeloupe), à Port de Sainte-Rose ») : on
    garde la plus complète. Le garde-fou phrase à phrase, face à un texte condensé,
    recollait parfois la phrase brute voisine."""
    sents = _sentences(text or "")
    out: list[str] = []
    for x in sents:
        if out and _sentence_key(out[-1]) == _sentence_key(x):
            if len(x) > len(out[-1]):
                out[-1] = x
            continue
        out.append(x)
    return " ".join(out) if len(out) != len(sents) else text


def _dedupe_plan(plan: Optional[dict], raw_plan: dict, lang: str) -> Optional[dict]:
    if not plan:
        return plan
    raws = {c.get("id"): c for c in (raw_plan.get("chapters") or []) if isinstance(c, dict)}
    chapters = []
    changed = False
    for ch in plan.get("chapters") or []:
        if not isinstance(ch, dict):
            continue
        text = ch.get("text") or ""
        new = dedupe_chapter_sentences(text)
        if new == text:
            chapters.append(ch)
            continue
        changed = True
        chapters.append({**ch, "text": new,
                         "anchors": reanchor_written_chapter(raws.get(ch.get("id")) or ch, new, lang)})
    return {**plan, "chapters": chapters} if changed else plan


def _translate_keep_names(facts: Any, src: str) -> str:
    """Noms propres de projets / AMP à garder tels quels dans l'anglais.

    Lightning traduisait « le projet Agence de Recherche pour la Biodiversité » en
    « French National Research Agency… » : le garde-fou y voyait des noms inventés,
    recollait le français et tout l'anglais du film tombait (lightning = 0).
    """
    if not isinstance(facts, dict):
        return ""
    names: list[str] = []
    for key in ("projects", "amp", "stations"):
        for n in facts.get(key) or []:
            n = str(n or "").strip()
            at = (src or "").casefold().find(n.casefold()) if n else -1
            if at < 0:
                continue
            # Le nom des faits est parfois coupé (« …Areas Networ ») : on le prend
            # tel que le texte le dit, jusqu'au bout du mot.
            end = at + len(n)
            while end < len(src) and (src[end].isalnum() or src[end] in "'’-"):
                end += 1
            full = src[at:end].strip()
            if full and full not in names:
                names.append(full)
    if not names:
        return ""
    return "\nKeep these names exactly as written, untranslated: " + "; ".join(names)


# --- Garde de traduction EN déterministe (VERIF-FILM-0515 N1-N9) ---------------------
# Lightning varie d'un run à l'autre : « Le 29 août, the catamaran… », « une vingtaine
# de jours » → « a couple of weeks », « eaux de la Guyane » → « Guyanese waters ».
# Ces corrections ne disent jamais un fait absent du français : elles ramènent
# l'anglais à ce que dit la phrase française (date, approximation, nom de pays).

_FR_DATE_IN_EN_RE = re.compile(
    r"\b(?P<le>[Ll]e\s+)?(?P<d>1er|\d{1,2})\s+(?P<m>" + "|".join(_FR_MONTHS_EN) + r")\b(?:\s+(?P<y>\d{4})\b)?",
    re.I,
)


def en_french_dates(text: str) -> str:
    """« Le 29 août, the catamaran… » → « On August 29, the catamaran… » (N1)."""
    def _one(m: re.Match) -> str:
        day = "1" if m.group("d").casefold() == "1er" else str(int(m.group("d")))
        month = _FR_MONTHS_EN[m.group("m").casefold()].capitalize()
        date = f"{month} {day}, {m.group('y')}" if m.group("y") else f"{month} {day}"
        le = m.group("le")
        if not le:
            return date
        return ("On " if le[0] == "L" else "on ") + date

    return _FR_DATE_IN_EN_RE.sub(_one, text or "")


# Approximations FR sans équivalent anglais figé ici (quinzaine ≈ fortnight, douzaine) : intouchées.
_APPROX_EN_CANON = {**_APPROX_EN_DAYS, "centaine": "about a hundred days"}
_FR_APPROX_DAYS_RE = re.compile(
    r"\b(" + "|".join(_APPROX_EN_CANON) + r")(?=\s+de\s+jours\b|\s*[.,;:!?)]|\s*$)", re.I,
)
_EN_DURATION_WORDS = (
    r"one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|"
    r"sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred"
)
# Une durée approximative anglaise : « a couple of weeks », « about three weeks »,
# « a fortnight », « some fifteen days », « about 25 days », « nearly a month ».
_EN_APPROX_DURATION_RE = re.compile(
    r"\b(?:(?:about|around|roughly|some|nearly|almost|approximately|close to|over|just over|under)\s+)?"
    r"(?:a\s+couple\s+of\s+weeks|a\s+few\s+weeks|several\s+weeks|a\s+fortnight|a\s+month|a\s+week|"
    r"(?:a\s+)?(?:" + _EN_DURATION_WORDS + r"|\d+)(?:-odd)?\s+(?:weeks|days|months))\b",
    re.I,
)
_EN_APPROX_LEAD = re.compile(
    r"^(?:about|around|roughly|some|nearly|almost|approximately|close to|over|just over|under)\b|"
    r"couple|few|several|fortnight|month|week|-odd",
    re.I,
)


def _fix_approx_pair(en: str, fr: str) -> str:
    hits = {m.group(1).casefold() for m in _FR_APPROX_DAYS_RE.finditer(fr or "")}
    if len(hits) != 1:
        return en
    canon = _APPROX_EN_CANON[hits.pop()]
    if canon in (en or "").casefold():
        return en
    for m in _EN_APPROX_DURATION_RE.finditer(en or ""):
        phrase = m.group(0)
        # Une durée exacte (« 46 days at sea ») n'est pas une approximation : intouchée.
        if not _EN_APPROX_LEAD.search(phrase):
            continue
        return en[: m.start()] + canon + en[m.end():]
    return en


def fix_en_approx_days(text: str, fr_src: str) -> str:
    """« une vingtaine de jours » se dit « about twenty days », jamais « a couple of
    weeks » (N2). Phrase à phrase quand les découpages s'alignent, sinon le chapitre."""
    fr_s, en_s = _sentences(fr_src or ""), _sentences(text or "")
    if fr_s and len(fr_s) == len(en_s):
        out = [_fix_approx_pair(en, fr) for fr, en in zip(fr_s, en_s)]
        return " ".join(out) if out != en_s else text
    return _fix_approx_pair(text or "", fr_src or "")


def _fr_name_pattern(name: str) -> str:
    return r"[\s\-]+".join(re.escape(p) for p in re.split(r"[\s\-]+", name.strip()) if p)


_EN_EXONYM_RE: Optional[list[tuple[re.Pattern[str], str]]] = None


def _en_exonym_rules() -> list[tuple[re.Pattern[str], str]]:
    """Table des toponymes : nom français → exonyme anglais, seulement après
    « the waters of » / « those of » (jamais un nom d'escale, qui ancre le film)."""
    global _EN_EXONYM_RE
    if _EN_EXONYM_RE is None:
        rules = []
        rows = sorted(toponyms.territories(), key=lambda r: len(str(r.get("fr") or "")), reverse=True)
        for row in rows:
            fr, en = str(row.get("fr") or "").strip(), str(row.get("en") or "").strip()
            if not fr or not en or fr == en or row.get("kind") == "high_seas":
                continue
            rx = re.compile(
                r"\b(?P<lead>(?:waters|those)\s+of\s+(?:the\s+)?)(?:l[ae]\s+|les\s+)?" + _fr_name_pattern(fr) + r"(?![\w\-])",
            )
            rules.append((rx, en))
        _EN_EXONYM_RE = rules
    return _EN_EXONYM_RE


def fix_en_toponyms(text: str, fr_src: str) -> str:
    """Noms de pays et d'eaux justes en anglais (N3-N7, N9), selon le français source."""
    out = text or ""
    for rx, en in _en_exonym_rules():
        out = rx.sub(lambda m, en=en: m.group("lead") + en, out)
    low = (fr_src or "").casefold()
    # N4 : la Guyane (française) n'est pas le Guyana.
    if re.search(r"\b(?:de la guyane|eaux guyanaises)\b", low) and not re.search(r"guyanien|eaux du guyana", low):
        out = re.sub(r"\bGuyanese waters\b", "French Guiana waters", out)
    # N4 bis (run réel 06 h 03) : « Cayenne (Guyane) » rendu « Cayenne (Guyana) ».
    if "(guyane)" in low and "(guyana)" not in low:
        out = out.replace("(Guyana)", "(French Guiana)")
    # N5 : « eaux indiennes » = les eaux de l'Inde, pas l'océan Indien.
    if "eaux indiennes" in low and "océan indien" not in low:
        out = re.sub(r"\bIndian Ocean waters\b", "Indian waters", out)
    # « eaux grenadiennes » = la Grenade (Grenadian), pas les Grenadines.
    if "grenadiennes" in low:
        out = re.sub(r"\bGrenadine waters\b", "Grenadian waters", out)
    # N7 : une seule unité dans le film anglais (« miles » partout ailleurs).
    out = re.sub(r"\bnautical miles\b", "miles", out)
    # N9 : « reprend le second voilier » = remonte à bord, pas « prend le contrôle ».
    if "reprend le second" in low:
        out = re.sub(
            r"\btakes over the second (vessel|sailboat|boat|yacht)\b",
            r"boards the second \1 again", out,
        )
    return out


def en_translation_guard(text: str, fr_src: str) -> str:
    """Toutes les corrections déterministes de l'anglais, dans l'ordre (idempotent)."""
    out = en_french_dates(text)
    out = fix_en_approx_days(out, fr_src)
    return fix_en_toponyms(out, fr_src)


def _glued_french_share(src_words: set[str], text: str) -> float:
    """Part des mots français (≥ 3 lettres) retrouvés comme mots entiers.

    Une vraie traduction anglaise en garde ≤ 0,51 (noms propres, « marina »…) sur les
    films du 29/10 ; un français recopié, même soudé, en garde 1,0."""
    if not src_words:
        return 0.0
    folded_src = {_fold_stop(word) for word in src_words if len(_fold_stop(word)) >= 3}
    if not folded_src:
        return 0.0
    folded_text = _fold_stop(text or "")
    whole_words = set(re.findall(r"[^\W\d_]{3,}", folded_text, flags=re.UNICODE))
    compact_text = re.sub(r"[^\w]", "", folded_text, flags=re.UNICODE)
    matched = sum(
        1 for word in folded_src
        if word in whole_words or (len(word) > 4 and word in compact_text)
    )
    return matched / len(folded_src)


async def translate_written_plan(
    fr_plan: dict,
    raw_plan: dict,
    *,
    cascade: Callable = cascade_text,
) -> Optional[dict]:
    """Lightning : français accepté → anglais, puis filter_numbers."""
    from story_cascade import NO_NUMBER_FILTER, TRANSLATE_SYSTEM  # noqa: PLC0415

    raw_chapters = [c for c in (raw_plan.get("chapters") or []) if isinstance(c, dict)]
    raw_by_id = {c.get("id"): c for c in raw_chapters if c.get("id") is not None}
    fr_chapters = [c for c in (fr_plan.get("chapters") or []) if isinstance(c, dict)]
    if not fr_chapters:
        return None
    out: list[dict] = []
    any_ok = False
    for i, ch in enumerate(fr_chapters):
        # Le français accepté (édité, condensé) est la référence phrase à phrase ;
        # les faits viennent du chapitre brut de même id.
        raw_ch = raw_by_id.get(ch.get("id")) or (raw_chapters[i] if i < len(raw_chapters) else ch)
        src = ch.get("text") or ""
        facts = chapter_structured_facts(raw_ch, lang="fr")
        guarded, rw = "", 0
        keep = _translate_keep_names(facts, src)
        for _attempt in range(3):
            # Lightning rend parfois le français tel quel : nouvelles demandes, chacune
            # avec une autre consigne, sinon le cache rend la même réponse. Un seul
            # chapitre raté faisait tomber tout l'anglais du film intégral.
            result = await cascade(
                TRANSLATE_SYSTEM,
                (_TRANSLATE_LEADS[_attempt] + src) + keep,
                tier="fast",
                fallback="",
                # Le garde-fou ci-dessous vérifie les nombres (épelés compris) ; le filtre
                # brut de la cascade couperait « 3 days » face à « Trois jours ».
                facts=NO_NUMBER_FILTER,
                max_tokens=min(1200, max(256, (len(src) // 2) + 80)),
            )
            text, source = result
            if not (text or "").strip() or source in {"rules", "budget"}:
                return None
            # Date et durée remises d'aplomb AVANT le garde-fou (il les compare au
            # français) ; les noms de pays, eux, après (ses listes de noms tolérés
            # partent du texte de Lightning).
            text = _repair_en_days(src, fix_en_approx_days(en_french_dates(text or ""), src))
            facts_en = {**facts, "en_names": sorted(n.title() for n in _en_translation_names(text or "", src)),
                        "approx": _fr_approx_numbers(src)} \
                if isinstance(facts, dict) else facts
            guarded, rw, fb = apply_written_guard(src, text, facts_en, lang="en")
            src_w = set(re.findall(r"[^\W\d_]{3,}", src.casefold()))
            out_w = set(re.findall(r"[^\W\d_]{3,}", (text or "").casefold()))
            if src_w and len(src_w & out_w) / len(src_w) > 0.6:
                fb = max(fb, 1)  # Lightning a rendu le français
            if src_w and _glued_french_share(src_w, text or "") > 0.8:
                # Lightning a rendu le français aux espaces mangées (« l'équipagereprend
                # le secondvoilierpourHalifax ») : les mots soudés échappent au
                # recouvrement ci-dessus (150 s du 29/10, leg-8).
                fb = max(fb, 1)
            if re.search(r"\bfortnight\b", text or "", re.I) and "quinzaine" not in src.casefold():
                # Lightning rend « une dizaine de jours » par « a fortnight » : on remet la
                # traduction exacte de l'approximation dite en français, sinon refus.
                fixed = _fix_fortnight(text or "", src)
                if fixed != text:
                    text = fixed
                    guarded, rw, fb = apply_written_guard(src, text, facts_en, lang="en")
                else:
                    fb = max(fb, 1)
            if len(_sentences(speak_film_text(text, "en"))) < len(_sentences(src)):
                fb = max(fb, 1)  # phrase manquante : le garde-fou recollerait le français
            if rw > 0 and fb == 0:
                break
        if rw <= 0 or fb > 0:
            # Jamais un anglais mêlé de phrases françaises de repli.
            return None
        any_ok = True
        sents = _sentences(guarded)
        guarded = " ".join(x for i, x in enumerate(sents) if i == 0 or x != sents[i - 1])
        guarded = dedupe_chapter_sentences(guarded)
        guarded = en_thousands_commas(guarded)
        guarded = en_month_first(guarded)
        guarded = en_le_month(guarded)
        guarded = unit_numbers_to_digits(guarded)
        guarded = en_argo_float(guarded)
        # Garde EN déterministe après le garde-fou (recollages compris) : N1-N9.
        guarded = en_translation_guard(guarded, src)
        # « par la route jusqu'à La Rochelle » rendu « by the route to » : « by road ».
        guarded = re.sub(r"\bby (?:the )?route to\b|\bby the road to\b", "by road to", guarded)
        # « le bateau longe X » rendu « the boat follows X » : on dit la côte longée.
        guarded = re.sub(
            r"\b(the boat|the catamaran|the sailboat) (?:follows|hugs|skirts|runs along)\b",
            r"\1 sails past", guarded,
        )
        anchors = reanchor_written_chapter(ch, guarded, "en")
        provenance = _chapter_provenance(result)
        out.append({**{k: v for k, v in ch.items() if k not in {"served_model", "served_source", "served_tier"}}, **provenance, "text": guarded, "anchors": anchors})
    if not any_ok:
        return None
    stamped = _stamp_written_plan(
        {**fr_plan, "chapters": out},
        fr_plan.get("source") or WRITTEN_SOURCE,
        fr_plan.get("targetSeconds"),
        reviewed_by=fr_plan.get("reviewedBy"),
        model=fr_plan.get("model"),
    )
    return stamped


_NUM_WORDS = (
    r"un|une|deux|trois|quatre|cinq|six|sept|huit|neuf|dix|onze|douze|treize|quatorze|quinze|seize|"
    r"vingt|trente|quarante|cinquante|soixante|cent|"
    r"one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|"
    r"sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred"
)
# Nombre épelé collé à une unité au pluriel : « vingt-sept milles », « douze nœuds », « twenty-six miles ».
_UNIT_SPELLED_RE = re.compile(
    rf"\b((?:{_NUM_WORDS})(?:(?:-et-|-| et | and |-and-)(?:{_NUM_WORDS}))*)"
    r"(\s+)(nœuds|noeuds|milles|knots|miles|nautical miles)\b",
    re.I,
)
_LONE_UNIT_WORDS = {"neuf": 9, "nine": 9}


def unit_numbers_to_digits(text: str) -> str:
    """Une seule graphie pour les quantités : « à vingt-sept milles » et « à 28 milles »
    cohabitaient (le brut épelle, Super/Ultra remettent parfois des chiffres).
    Les nombres suivis d'une unité (milles, nœuds, miles, knots) passent en chiffres ;
    « une vingtaine de jours », « trois jours de mer » ne bougent pas."""
    from story_cascade import spelled_numbers_to_digits  # noqa: PLC0415

    def _one(m: re.Match) -> str:
        words = m.group(1)
        low = words.lower()
        if low in _LONE_UNIT_WORDS:
            return f"{_LONE_UNIT_WORDS[low]}{m.group(2)}{m.group(3)}"
        num = spelled_numbers_to_digits(words)
        if not re.fullmatch(r"\d+", num.strip()):
            return m.group(0)
        if int(num) < 2:
            return m.group(0)
        return f"{int(num)}{m.group(2)}{m.group(3)}"

    return _UNIT_SPELLED_RE.sub(_one, text or "")


_FR_ELIDE_DE_RE = re.compile(r"\b([Dd])e (?=Halifax\b|[AEIOUÉÈÊÎÔ][a-zà-ÿ])")


_FR_APOS_ASCII_RE = re.compile(r"(?<=[A-Za-zÀ-ÿ])'(?=[A-Za-zÀ-ÿ])")
_FR_APOS_TYPO_RE = re.compile(r"(?<=[A-Za-zÀ-ÿ])’(?=[A-Za-zÀ-ÿ])")


def fr_apostrophe_style(text: str) -> str:
    """Apostrophe majoritaire du texte (entre deux lettres) : « ' » ou « ’ » (égalité : « ’ »)."""
    ascii_n = len(_FR_APOS_ASCII_RE.findall(text or ""))
    typo_n = len(_FR_APOS_TYPO_RE.findall(text or ""))
    return "'" if ascii_n > typo_n else "’"


def fr_unify_apostrophes(text: str, style: str) -> str:
    """Une seule apostrophe dans tout le film : pas « l'équipage s'envole d’Halifax »."""
    if style == "'":
        return _FR_APOS_TYPO_RE.sub("'", text or "")
    return _FR_APOS_ASCII_RE.sub("’", text or "")


def fr_elide_de(text: str, style: str | None = None) -> str:
    """« s'envole de Halifax » → « s'envole d'Halifax » ; « de Ajaccio » → « d'Ajaccio ».

    L'apostrophe suit celle du texte (`style`, sinon la majoritaire)."""
    apos = style or fr_apostrophe_style(text)
    return _FR_ELIDE_DE_RE.sub(lambda m: f"{m.group(1)}{apos}", text or "")


_EN_LE_MONTH_RE = re.compile(
    r"\bLe ((?:January|February|March|April|May|June|July|August|September|October|November|"
    r"December) \d{1,2})\b"
)


def en_le_month(text: str) -> str:
    """Lightning laissait « Le August 29, the catamaran… » : « On August 29 »."""
    return _EN_LE_MONTH_RE.sub(r"On \1", text or "")


def _polish_written_plan(plan: dict | None, raw_plan: dict, lang: str = "fr") -> dict | None:
    """Post-traitements sûrs du rédigé (graphie seulement, jamais un fait) ; ancres recalculées."""
    if not plan:
        return plan
    raws = {c.get("id"): c for c in (raw_plan.get("chapters") or []) if isinstance(c, dict)}
    # Apostrophe majoritaire du film entier (gabarits « ’ » + Super « ' » se mêlaient).
    style = fr_apostrophe_style(" ".join(
        str(c.get("text") or "") for c in (plan.get("chapters") or []) if isinstance(c, dict)
    ))
    chapters = []
    rows = [ch for ch in (plan.get("chapters") or []) if isinstance(ch, dict)]
    # Graphie du rédigé : jour redit (N11), « Année 1 » collé (N10), année au nouvel an (N14).
    fixed = [
        " ".join(drop_repeated_heard_dates(_sentences(str(ch.get("text") or "")), lang))
        if ch.get("text") else ""
        for ch in rows
    ]
    fixed = [_PROJECT_YEAR_IN_TEXT_RE.sub(r" (\1 \2)\3", t) for t in fixed]
    fixed = [_apply_insertions(t, ins) for t, ins in zip(fixed, _year_insertions(fixed, lang))]
    for ch, pre in zip(rows, fixed):
        old = ch.get("text") or ""
        text = unit_numbers_to_digits(pre or old)
        text = en_le_month(text) if _en(lang) else fr_unify_apostrophes(fr_elide_de(text, style), style)
        if text == old:
            chapters.append(ch)
            continue
        raw_ch = raws.get(ch.get("id")) or ch
        chapters.append({**ch, "text": text, "anchors": reanchor_written_chapter(raw_ch, text, lang)})
    out = {**plan, "chapters": chapters}
    out["chars"] = script_chars(chapters)
    out["estimatedSeconds"] = film_estimated_seconds(out["chars"])
    return out


def _digits_for_speech(text: str) -> str:
    """Super écrit parfois « huit mille trois cent… » : on remet des chiffres (« 8 393 »)."""
    from story_cascade import spelled_numbers_to_digits  # noqa: PLC0415

    out = spelled_numbers_to_digits(text or "")

    def _group(m: re.Match) -> str:
        n = m.group(0)
        if len(n) == 4 and 1900 <= int(n) <= 2099:
            return n
        # Un identifiant (flotteur Argo / WMO 4903331) n'est pas une quantité :
        # jamais « le flotteur Argo 4 903 331 ».
        before = out[max(0, m.start() - 24):m.start()]
        if len(n) >= 7 or _IDENT_BEFORE_RE.search(before):
            return n
        return f"{int(n):,}".replace(",", " ")

    return re.sub(r"(?<![\d.,])\d{4,}(?!\d)", _group, out)


_IDENT_BEFORE_RE = re.compile(
    r"(?:\bArgo|\bWMO|\bflotteur|\bfloat|\bbou[ée]e|\bbuoy|\bstation|\bn°|\bno\.?)\s*$",
    re.I,
)

_EN_SPACED_THOUSANDS_RE = re.compile(r"(?<![\d.,])\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?![\d])")


def en_thousands_commas(text: str) -> str:
    """Anglais : « 1 642 miles » → « 1,642 miles » (même longueur, ancres intactes).

    Un identifiant collé (Argo 4903331) n'a pas d'espace et ne bouge pas.
    """
    return _EN_SPACED_THOUSANDS_RE.sub(
        lambda m: re.sub(r"[ \u00a0\u202f]", ",", m.group(0)), text or "",
    )


def en_argo_float(text: str) -> str:
    """« Then, Argo 7902126. » / « Argo 4903967 float » → « Argo float 7902126 »."""
    out = re.sub(r"\bArgo (\d{7}) float\b", r"Argo float \1", text or "")
    return re.sub(r"\bArgo (?!float\b)(\d{7})\b", r"Argo float \1", out)


def _plan_digits_for_speech(plan: dict, raw_plan: dict, lang: str = "fr") -> dict:
    raws = {c.get("id"): c for c in (raw_plan.get("chapters") or []) if isinstance(c, dict)}
    chapters = []
    for ch in plan.get("chapters") or []:
        if not isinstance(ch, dict):
            continue
        text = _digits_for_speech(ch.get("text") or "")
        if text == (ch.get("text") or ""):
            chapters.append(ch)
            continue
        raw_ch = raws.get(ch.get("id")) or ch
        chapters.append({**ch, "text": text, "anchors": reanchor_written_chapter(raw_ch, text, lang)})
    return {**plan, "chapters": chapters}


async def _write_film_single(
    plan: dict,
    *,
    lang: str,
    seconds: Any,
    cascade: Callable,
) -> tuple[Optional[dict], dict[str, Any]]:
    """Rédige un film dans une langue (Super, Ultra si FR, relecture). Sans traduction."""
    stats: dict[str, Any] = {
        "super": 0, "ultra_edit": 0, "ultra_judge": 0,
        "source": "rules", "reviewed": False,
    }
    raw = dict(plan)
    secs = _film_seconds(seconds if seconds is not None else plan.get("targetSeconds"))
    raw["targetSeconds"] = secs
    if secs == 150:
        full_raw = {**raw, "targetSeconds": 0}
        super_plan, super_stats = await write_stored_plan(
            full_raw, lang=lang, cascade=cascade, seconds=0,
        )
    else:
        full_raw = raw
        super_plan, super_stats = await write_stored_plan(
            raw, lang=lang, cascade=cascade, seconds=seconds,
        )
    stats["rewritten"] = int((super_stats or {}).get("rewritten") or 0)
    stats["fallen"] = int((super_stats or {}).get("fallen") or 0)
    if super_plan is None or int((super_stats or {}).get("rewritten") or 0) <= 0:
        return None, stats
    stats["super"] = 1
    ref_raw = full_raw if secs == 150 else raw
    super_plan = _plan_digits_for_speech(super_plan, ref_raw, lang)
    if secs == 150:
        super_plan = condense_written_plan(super_plan, 150, lang=lang)
    origin = public_written_source(super_plan.get("source") or (super_stats or {}).get("source"))
    if origin == WRITTEN_SOURCE:
        stats["source"] = WRITTEN_SOURCE
        accepted = _stamp_written_plan(super_plan, WRITTEN_SOURCE, seconds, model=_write_model())
    else:
        stats["source"] = origin or "rules"
        from story_cascade import nim_model  # noqa: PLC0415
        nim_name = (super_stats or {}).get("model") or nim_model("write")
        nim_source = f"nvidia-{nim_name.split('/')[-1]}"
        model = nim_name if (origin or "") == nim_source else (origin or None)
        accepted = _stamp_written_plan(super_plan, origin or "rules", seconds, model=model)

    if _en(lang) is False and film_ultra_open():
        edited = await edit_written_once(accepted, ref_raw, cascade=cascade)
        stats["ultra_edit"] = 1
        if edited and secs == 150:
            edited = condense_written_plan(edited, 150, lang=lang)
        edited = _dedupe_plan(edited, ref_raw, lang)
        if edited:
            failed = await judge_written_chapters(edited, cascade=cascade, raw_plan=ref_raw)
            stats["ultra_judge"] = 1
            if failed:
                stats["judge_failed"] = list(failed)
                edited = _restore_chapters(edited, accepted, failed)
                again = await judge_written_chapters(
                    edited, cascade=cascade, raw_plan=ref_raw, only=set(failed),
                )
                failed = again if again is not None else None
                if failed and secs != 150:
                    raw_digits = _plan_digits_for_speech(ref_raw, ref_raw, lang)
                    edited = _restore_chapters(edited, raw_digits, failed)
                    again = await judge_written_chapters(
                        edited, cascade=cascade, raw_plan=ref_raw, only=set(failed),
                    )
                    failed = again if again is not None else None
                stats["judge_failed_after_restore"] = None if failed is None else list(failed)
            ok = failed == []
            if ok and accepted.get("source") == WRITTEN_SOURCE:
                accepted = _stamp_written_plan(
                    edited, WRITTEN_SOURCE, seconds,
                    reviewed_by=REVIEWED_BY_ULTRA,
                    model=accepted.get("model") or _write_model(),
                )
                stats["reviewed"] = True
                stats["source"] = WRITTEN_SOURCE

    accepted = _dedupe_plan(accepted, ref_raw, lang)
    accepted = _polish_written_plan(accepted, ref_raw, lang)
    if secs == 150:
        accepted = {
            **condense_written_plan(accepted, 150, lang=lang),
            "targetSeconds": accepted.get("targetSeconds", 150),
        }
    stops = _route_stops_for_reread(raw)
    ok, review = await reread_before_store(accepted, stops, cascade=cascade, lang=lang)
    stats["reread"] = "pass" if ok else "fail"
    stats["rereadBy"] = str(review.get("source") or "")
    if not ok:
        stats["faults"] = review.get("faults") or []
        return None, stats
    return accepted, stats


async def write_film_chain(
    plan: dict,
    *,
    seconds: Any = 150,
    cascade: Callable = cascade_text,
    lang: str = "fr",
    en_raw: dict | None = None,
) -> tuple[Optional[dict], Optional[dict], dict[str, Any]]:
    """Au clic : rédaction directe FR et EN en parallèle (brut EN), jamais traduite du FR."""
    stats: dict[str, Any] = {
        "super": 0, "ultra_edit": 0, "ultra_judge": 0, "lightning": 0,
        "source": "rules", "reviewed": False,
    }
    if _en(lang):
        en_plan, en_stats = await _write_film_single(plan, lang="en", seconds=seconds, cascade=cascade)
        stats.update(en_stats)
        if en_plan:
            stats["lightning"] = 1
        return None, en_plan, stats

    en_payload = en_raw if isinstance(en_raw, dict) and (en_raw.get("chapters") or []) else None
    if en_payload:
        en_payload = {
            **en_payload,
            "targetSeconds": _film_seconds(seconds if seconds is not None else plan.get("targetSeconds")),
        }
        (fr_plan, fr_stats), (en_plan, en_stats) = await asyncio.gather(
            _write_film_single(plan, lang="fr", seconds=seconds, cascade=cascade),
            _write_film_single(en_payload, lang="en", seconds=seconds, cascade=cascade),
        )
        stats.update(fr_stats)
        if en_plan:
            stats["lightning"] = 1
            stats["reread_en"] = en_stats.get("reread")
            stats["rereadBy_en"] = en_stats.get("rereadBy")
        else:
            stats["faults"] = en_stats.get("faults") or stats.get("faults")
        return fr_plan, en_plan, stats

    fr_plan, fr_stats = await _write_film_single(plan, lang="fr", seconds=seconds, cascade=cascade)
    stats.update(fr_stats)
    return fr_plan, None, stats


def _public_plan(plan: dict, source: str) -> dict:
    chapters = []
    for c in plan.get("chapters") or []:
        chapters.append({
            "id": c.get("id"),
            "tA": c.get("tA"),
            "tB": c.get("tB"),
            "text": fix_en_waters_casing(c.get("text") or ""),
            **({key: c[key] for key in ("served_model", "served_source", "served_tier") if c.get(key)}),
            "anchors": [
                {"charIdx": a.get("charIdx"), "t": a.get("t")}
                for a in (c.get("anchors") or [])
                if isinstance(a, dict) and a.get("t") is not None
            ],
            "events": [
                {
                    "id": e.get("id"),
                    "charIdx": e.get("charIdx"),
                    "kind": e.get("kind") or (e.get("card") or {}).get("kind"),
                    "title": e.get("title") or (e.get("card") or {}).get("title"),
                    "fact": e.get("fact") or (e.get("card") or {}).get("text"),
                    "score": e.get("score") if e.get("score") in {1, 2, 3} else bubble_score(e.get("card") or e),
                    "card": e.get("card"),
                }
                for e in (c.get("events") or [])
            ],
            "fromName": c.get("fromName"),
            "toName": c.get("toName"),
            "fromLat": c.get("fromLat"),
            "fromLon": c.get("fromLon"),
            "toLat": c.get("toLat"),
            "toLon": c.get("toLon"),
        })
    chars = script_chars(chapters)
    out = {
        "chapters": chapters,
        "source": source,
        "chars": chars,
        "targetSeconds": int(plan["targetSeconds"]) if plan.get("targetSeconds") is not None else 150,
    }
    if plan.get("dcSubjects"):
        out["dcSubjects"] = plan["dcSubjects"]
    if plan.get("filmChoice") is not None:
        out["filmChoice"] = plan["filmChoice"]
    return out


async def build_film_response(
    clock: dict | None,
    live: dict | None,
    journal: dict | None,
    *,
    marks: list | None = None,
    lang: str = "fr",
    seconds: int = 150,
    style: str = "raw",
    now_ms: Optional[int] = None,
    cascade: Callable = cascade_text,
    want_write: bool = False,
    display_t0: str | None = None,
    review: dict | None = None,
    eta: dict | None = None,
    choose: bool = False,
) -> dict[str, Any]:
    """Assemble the API payload. `want_write` triggers Nemotron (tier write).
    `choose` : Nano (ids) ou repli, au remplissage du stock seulement."""
    from story_cache import film_cache_key, get_film_cached, put_film_cached  # noqa: PLC0415

    shown = resolve_film_t0(display_t0)
    marks = marks if marks is not None else (clock or {}).get("marks")
    clock = {**(clock or {}), "t0": OFFICIAL_T0}
    last = last_stop_id(journal, marks)
    fp = journal_fingerprint(journal, last)
    rev = review_fingerprint(review)
    if rev:
        fp = f"{fp}|rev={rev}"
    eta_fp = eta_fingerprint(eta)
    if eta_fp:
        fp = f"{fp}|eta={eta_fp}"
    if shown != OFFICIAL_T0:
        fp = f"{fp}|t0={shown}"
    key = film_cache_key(fp, lang, seconds)
    cached = get_film_cached(key) or {}
    raw_full = build_raw_script(
        clock, marks, live, journal, lang=lang, seconds=seconds, now_ms=now_ms,
        display_t0=shown, review=review, eta=eta,
    )
    events = raw_full.get("_events") or []
    packed = raw_full.get("_packed") or {}
    from_moments = bool(raw_full.get("_fromMoments"))
    if choose:
        try:
            bag = film_choice_bag(raw_full.get("dcSubjects") or [])
            tour = tour_snapshot(packed)
            ids, _src = await choose_film_ids(bag, tour, seconds, cascade=cascade)
            raw_full = apply_chosen_subjects(raw_full, ids, bag, seconds, lang=lang)
        except Exception:
            pass
    raw = _public_plan(raw_full, "rules")
    if not from_moments:
        attach_chapter_events(raw.get("chapters") or [], packed, journal, lang)
    written = cached.get("written") if isinstance(cached.get("written"), dict) else None
    written_source = cached.get("writtenSource") or "nemotron"

    if want_write and written is None:
        if not from_moments:
            fallback_ids = [e["id"] for e in events]
            try:
                ids, _sel_src = await select_with_llm(packed.get("candidates") or events, fallback_ids, cascade=cascade)
                by_id = {e["id"]: e for e in (packed.get("candidates") or events)}
                picked = [by_id[i] for i in ids if i in by_id]
                if picked:
                    raw_full = build_raw_script(
                        clock, marks, live, journal, lang=lang, seconds=seconds, now_ms=now_ms, selected=picked,
                        review=review, eta=eta,
                    )
                    events = raw_full.get("_events") or picked
                    raw = _public_plan(raw_full, "rules")
            except Exception:
                pass
        try:
            wplan, wsrc = await write_with_llm(raw_full, events, lang=lang, cascade=cascade)
        except Exception:
            wplan, wsrc = None, "rules"
        if wplan:
            written = _public_plan(wplan, "nemotron" if str(wsrc).startswith("nemotron") else wsrc)
            written_source = written["source"]
            put_film_cached(key, {"raw": raw, "written": written, "writtenSource": written_source, "lastStop": last})
        else:
            put_film_cached(key, {"raw": raw, "written": None, "writtenSource": None, "lastStop": last})
    elif not cached:
        put_film_cached(key, {"raw": raw, "written": written, "writtenSource": written_source if written else None, "lastStop": last})

    if isinstance(written, dict) and not from_moments:
        attach_chapter_events(written.get("chapters") or [], packed, journal, lang)
    use_written = style in {"written", "nemotron", "rédigé", "redige"} and written is not None
    plan = written if use_written else raw
    source = (written_source if use_written else "rules") or "rules"
    out = {**plan, "source": source, "hasWritten": written is not None, "style": "written" if use_written else "raw"}
    return out


async def official_film(
    *,
    lang: str = "fr",
    seconds: int = 150,
    style: str = "raw",
    cascade: Callable = cascade_text,
    t0: str | None = None,
) -> dict[str, Any]:
    from voyage_api import _climo_clock, _journal_safely, _now  # noqa: PLC0415
    from voyage_clock import OFFICIAL_VOYAGE_ID, sample_clock_at_time  # noqa: PLC0415
    from voyage_store import load_voyage  # noqa: PLC0415
    import voyage_journal as journal  # noqa: PLC0415

    voy = load_voyage(OFFICIAL_VOYAGE_ID)
    if voy is None:
        raise FileNotFoundError("voyage officiel absent")
    when = _now()
    raw_clock = voy.get("clock")
    if not raw_clock:
        # Depuis RF2 l'horloge vit dans le stock : la relire (ms) plutôt que la recalculer (5 min, 27 sept.).
        try:
            from official_store import stored_clock  # noqa: PLC0415
            raw_clock = stored_clock()
        except Exception:
            raw_clock = None
    raw_clock = raw_clock or _climo_clock(voy)
    voy = {**voy, "clock": raw_clock}
    clock = {**raw_clock, "t0": OFFICIAL_T0}
    marks = merge_route_marks(voy.get("marks") or [], raw_clock)
    _journal_safely(lambda: journal.tick(voy, when))
    live = sample_clock_at_time(raw_clock, when) or {}
    payload = journal.summary(500)
    moments = _official_moments_for_film(OFFICIAL_VOYAGE_ID)
    if moments:
        payload = {**payload, "moments": moments}
    review, eta = _stored_review_and_eta()
    if review is None:
        try:
            from plan_review import review_official  # noqa: PLC0415
            # Saison atlas hors HTTP (budget 6 s) : les couloirs viennent des points.
            review = review_official(voy, when, season=False)
        except Exception:
            review = None
    return await build_film_response(
        clock, live, payload, marks=marks, lang=lang, seconds=_film_seconds(seconds),
        style=style, cascade=cascade, want_write=False, choose=True,
        now_ms=int(when.timestamp() * 1000) if hasattr(when, "timestamp") else None,
        display_t0=resolve_film_t0(t0),
        review=review,
        eta=eta,
    )


async def warm_film_story(
    voyage_id: str | None = None,
    *,
    langs: tuple[str, ...] = ("fr", "en"),
    seconds: int = 150,
    cascade: Callable = cascade_text,
) -> dict[str, Any]:
    """Préchauffe le brut seulement — ED1 : plus de chaîne Super/Ultra ici."""
    from voyage_api import _climo_clock, _now  # noqa: PLC0415
    from voyage_clock import OFFICIAL_VOYAGE_ID, sample_clock_at_time  # noqa: PLC0415
    from voyage_store import load_voyage  # noqa: PLC0415
    import voyage_journal as journal  # noqa: PLC0415

    vid = voyage_id or OFFICIAL_VOYAGE_ID
    voy = load_voyage(vid)
    if voy is None:
        return {"voyageId": vid, "status": "no-voyage", "count": 0}
    when = _now()
    raw_clock = voy.get("clock") or _climo_clock(voy)
    clock = {**raw_clock, "t0": OFFICIAL_T0}
    marks = merge_route_marks(voy.get("marks") or [], raw_clock)
    live = sample_clock_at_time(raw_clock, when) or {}
    try:
        payload = journal.summary(500)
    except Exception:
        payload = {}
    moments = _official_moments_for_film(vid)
    if moments:
        payload = {**payload, "moments": moments}
    review, eta = _stored_review_and_eta()
    if review is None:
        try:
            from plan_review import review_official  # noqa: PLC0415
            review = review_official(voy, when, season=False)
        except Exception:
            review = None
    now_ms = int(when.timestamp() * 1000) if hasattr(when, "timestamp") else None
    out: dict[str, Any] = {}
    import llm_budget  # noqa: PLC0415
    # Écriture LLM du film en ARRIÈRE-PLAN : sous on-demand (défaut, 28 sept.) la cascade rend le brut.
    with llm_budget.background():
        for lang in langs:
            plan = await build_film_response(
                clock, live, payload, marks=marks, lang=lang, seconds=_film_seconds(seconds),
                style="written", cascade=cascade, want_write=False, now_ms=now_ms,
                review=review, eta=eta,
            )
            out[lang] = {"hasWritten": plan.get("hasWritten"), "chars": plan.get("chars"), "source": plan.get("source")}
    return {"voyageId": vid, "status": "ready", "langs": out}
