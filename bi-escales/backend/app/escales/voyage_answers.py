"""Deterministic Captain answers about the boat's position and the schedule.

"Where is the boat?", "next stop?" and "when do you arrive at <stop>?" are
answered from the voyage clock (``simulated_now``, which honours
``ESCALES_CLOCK_NOW``), the local schedule export built from
``route_schedule.json``, the clock legs (port departures) and the navigation
logbook. No model sees these questions and no date is invented: an unknown
stop gets the list of stops that exist.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any, Optional

from .config import simulated_now

RULE_SOURCE = "voyage_schedule"
RULE_LABEL = {"en": "From the voyage schedule", "fr": "D'après le calendrier du voyage"}

_BOAT = r"(?:the\s+)?(?:boat|ship|vessel|sailboat|yacht)"
_BATEAU = r"(?:le\s+)?(?:bateau|voilier|navire)"

_WHERE_Q = re.compile(
    rf"\bwhere(?:\s+is|['’]s)\s+{_BOAT}\b"
    rf"|\bwhere\s+are\s+you\s+now\b"
    rf"|\bo[uù]\s+(?:est|en\s+est|se\s+trouve)\s+{_BATEAU}\b"
    rf"|\bo[uù]\s+[eê]tes[-\s]vous\b",
    re.IGNORECASE,
)
_NEXT_Q = re.compile(
    r"\bnext\s+(?:stop|stopover|port|port\s+of\s+call|escale)\b"
    r"|\bprochaine?\s+(?:escale|[ée]tape|port)\b",
    re.IGNORECASE,
)
_ETA_EN = re.compile(
    r"\bwhen\s+(?:do|will|does|are|is)\s+(?:you|we|they|it|the\s+(?:boat|ship|crew))\s+"
    r"(?:arrive|arriving|reach|reaching|get|getting|be|dock|docking)\b"
    r"(?:\s+(?:at|in|to|into|on))?(?P<place>[^?!.]*)"
    r"|\b(?:eta|arrival\s+date)\b(?:\s+(?:at|in|for|to|of))?(?P<place2>[^?!.]*)",
    re.IGNORECASE,
)
_ETA_FR = re.compile(
    r"\bquand\s+(?:est[-\s]ce\s+que\s+(?:vous|le\s+bateau|nous|on)\s+)?"
    r"(?:arrivez|arriverez|arrive|arrivera|arriverons|arrivons|serez|sera|serons)"
    r"(?:[-\s](?:vous|t[-\s]il|il|nous|on))?"
    r"(?:\s+(?:à|a|au|aux|en|sur|dans))?(?P<place>[^?!.]*)",
    re.IGNORECASE,
)
_LEADING_WORDS = re.compile(
    r"^(?:\s*(?:at|in|to|into|on|the\s+port\s+of|port\s+of|à|a|au|aux|en|sur|dans|le\s+port\s+de|l['’]escale\s+de)\b)+",
    re.IGNORECASE,
)
_TRAILING_WORDS = re.compile(
    r"\b(?:please|svp|s['’]il\s+vous\s+pla[iî]t|exactly|exactement)\s*$",
    re.IGNORECASE,
)


def voyage_question_kind(message: str) -> Optional[str]:
    """``where``, ``next`` or ``eta`` for a schedule question, else ``None``."""
    text = message or ""
    if _WHERE_Q.search(text):
        return "where"
    if _ETA_EN.search(text) or _ETA_FR.search(text):
        return "eta"
    if _NEXT_Q.search(text):
        return "next"
    return None


def _parse(raw: Any) -> Optional[dt.datetime]:
    text = str(raw or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        moment = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    return moment.astimezone(dt.timezone.utc)


def _when(moment: dt.datetime, lang: str) -> str:
    """Same wording as the rest of the Captain: ``on 12 November 2026 at 12:00 UTC``."""
    from .captain import arrival_phrase

    stamp = moment.replace(microsecond=0).isoformat()
    return arrival_phrase({"facts": {"arrival_iso": stamp}}, lang)


def _day(moment: dt.datetime, lang: str) -> str:
    from .captain import arrival_phrase

    return arrival_phrase({"facts": {"arrival_iso": moment.date().isoformat()}}, lang)


def _stops() -> list[dict[str, Any]]:
    """Schedule stops in order, each with ``arrival`` and ``departure`` instants."""
    from .naviguide_bridge import clock_legs, local_schedule_export

    rows = []
    for row in local_schedule_export().get("escales") or []:
        if not isinstance(row, dict):
            continue
        arrival = _parse(row.get("arrival_iso"))
        if arrival is None:
            continue
        rows.append({**row, "arrival": arrival})
    rows.sort(key=lambda row: row["arrival"])
    departures: dict[str, dt.datetime] = {}
    for leg in clock_legs():
        slug = str(leg.get("from_slug") or "")
        moment = _parse(leg.get("departure_iso"))
        if slug and moment and slug not in departures:
            departures[slug] = moment
    for index, row in enumerate(rows):
        later = rows[index + 1]["arrival"] if index + 1 < len(rows) else None
        leaving = departures.get(str(row.get("slug") or ""))
        # A port stay counts only when the leg leaves after this arrival and
        # before the next one. Otherwise the boat sails on at arrival.
        if leaving is None or leaving < row["arrival"] or (later is not None and leaving > later):
            leaving = row["arrival"]
        row["departure"] = leaving
    return rows


def _last_logged_position(milestone_id: str, now: dt.datetime) -> Optional[dict[str, Any]]:
    from .navigation_logbook import navigation_logbook

    best = None
    for entry in navigation_logbook().get(milestone_id) or []:
        if entry.get("kind") != "position":
            continue
        moment = _parse(entry.get("t"))
        if moment is not None and moment <= now:
            best = {**entry, "moment": moment}
    return best


def _stop_list(stops: list[dict[str, Any]]) -> str:
    seen: list[str] = []
    for row in stops[1:]:
        name = str(row.get("name") or row.get("milestone_id"))
        if name not in seen:
            seen.append(name)
    return ", ".join(seen)


def _not_departed(stops: list[dict[str, Any]], lang: str) -> str:
    origin = stops[0]
    name = origin.get("name")
    if lang == "en":
        return f"The boat has not departed yet. Departure from {name} {_day(origin['departure'], lang)}."
    return f"Le bateau n'est pas encore parti. Départ de {name} {_day(origin['departure'], lang)}."


def _next_after(stops: list[dict[str, Any]], now: dt.datetime) -> Optional[dict[str, Any]]:
    for row in stops[1:]:
        if row["arrival"] > now:
            return row
    return None


def _next_sentence(row: Optional[dict[str, Any]], lang: str) -> str:
    if row is None:
        return ""
    if lang == "en":
        return f"Next stop: {row['name']}, scheduled arrival {_when(row['arrival'], lang)}."
    return f"Prochaine escale : {row['name']}, arrivée prévue {_when(row['arrival'], lang)}."


def _where(stops: list[dict[str, Any]], now: dt.datetime, lang: str) -> str:
    if now <= stops[0]["departure"]:
        return f"{_not_departed(stops, lang)} {_next_sentence(_next_after(stops, now), lang)}"
    current = max((row for row in stops if row["arrival"] <= now), key=lambda row: row["arrival"])
    upcoming = _next_after(stops, now)
    if upcoming is None:
        if lang == "en":
            return f"The voyage is complete: the boat reached {current['name']} {_when(current['arrival'], lang)}."
        return f"Le voyage est terminé : le bateau est arrivé à {current['name']} {_when(current['arrival'], lang)}."
    if now < current["departure"]:
        if lang == "en":
            return (
                f"The boat is in port at {current['name']} since {_when(current['arrival'], lang).removeprefix('on ')}. "
                f"Departure {_when(current['departure'], lang)}. {_next_sentence(upcoming, lang)}"
            )
        return (
            f"Le bateau est au port à {current['name']} depuis {_when(current['arrival'], lang)}. "
            f"Départ {_when(current['departure'], lang)}. {_next_sentence(upcoming, lang)}"
        )
    if lang == "en":
        text = f"The boat is underway from {current['name']} to {upcoming['name']}."
    else:
        text = f"Le bateau fait route de {current['name']} vers {upcoming['name']}."
    logged = _last_logged_position(str(upcoming.get("milestone_id") or ""), now)
    if logged:
        lat = logged["pos"]["lat"]
        lon = logged["pos"]["lon"]
        if lang == "en":
            text += f" Last logbook position {_when(logged['moment'], lang)}: {lat}, {lon}."
        else:
            text += f" Dernière position du journal de bord {_when(logged['moment'], lang)} : {lat}, {lon}."
    return f"{text} {_next_sentence(upcoming, lang)}"


def _next(stops: list[dict[str, Any]], now: dt.datetime, lang: str) -> str:
    upcoming = _next_after(stops, now)
    if upcoming is None:
        last = stops[-1]
        if lang == "en":
            return f"There is no next stop: the voyage ended at {last['name']} {_when(last['arrival'], lang)}."
        return f"Il n'y a plus d'escale : le voyage s'est terminé à {last['name']} {_when(last['arrival'], lang)}."
    sentence = _next_sentence(upcoming, lang)
    if now <= stops[0]["departure"]:
        return f"{_not_departed(stops, lang)} {sentence}"
    return sentence


def _place_in(message: str) -> str:
    for pattern in (_ETA_EN, _ETA_FR):
        match = pattern.search(message or "")
        if not match:
            continue
        place = match.groupdict().get("place") or match.groupdict().get("place2") or ""
        place = _LEADING_WORDS.sub("", place)
        place = _TRAILING_WORDS.sub("", place).strip(" ,;:-")
        if place:
            return place
    return ""


def _eta(message: str, stops: list[dict[str, Any]], now: dt.datetime, lang: str) -> str:
    from .naviguide_bridge import resolve_milestone

    place = _place_in(message)
    if not place:
        return _next(stops, now, lang)
    wanted = resolve_milestone(place)
    matches = [row for row in stops[1:] if wanted and row.get("milestone_id") == wanted]
    if wanted == "dep-la-rochelle":
        matches += [row for row in stops if row.get("milestone_id") == "ret-la-rochelle"]
    if not matches:
        if lang == "en":
            return f"I cannot find \"{place}\" on the voyage schedule. The stops are: {_stop_list(stops)}."
        return f"Je ne trouve pas « {place} » dans le calendrier du voyage. Les escales sont : {_stop_list(stops)}."
    parts = []
    for row in matches:
        if row["arrival"] <= now:
            parts.append(
                f"The boat arrived at {row['name']} {_when(row['arrival'], lang)}."
                if lang == "en"
                else f"Le bateau est arrivé à {row['name']} {_when(row['arrival'], lang)}."
            )
        else:
            parts.append(
                f"Scheduled arrival at {row['name']}: {_when(row['arrival'], lang)}."
                if lang == "en"
                else f"Arrivée prévue à {row['name']} : {_when(row['arrival'], lang)}."
            )
    return " ".join(parts)


def voyage_reply(message: str, lang: str, now: Optional[dt.datetime] = None) -> Optional[str]:
    """The schedule answer, or ``None`` when the message is not a voyage question."""
    kind = voyage_question_kind(message)
    if kind is None:
        return None
    stops = _stops()
    if not stops:
        return None
    moment = now or simulated_now()
    lang = "en" if lang == "en" else "fr"
    if kind == "where":
        return _where(stops, moment, lang)
    if kind == "next":
        return _next(stops, moment, lang)
    return _eta(message, stops, moment, lang)
