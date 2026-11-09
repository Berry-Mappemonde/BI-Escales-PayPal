"""Film fixtures: quoted sea durations and calendar dates must match tA/tB/anchors."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from film_script import spoken_sea_days

_FIXTURES = Path(__file__).parent / "fixtures"
_FOCUS = tuple(f"leg-{n}" for n in range(13, 18))

_FR_MONTHS = {
    "janvier": 1,
    "février": 2,
    "mars": 3,
    "avril": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7,
    "août": 8,
    "septembre": 9,
    "octobre": 10,
    "novembre": 11,
    "décembre": 12,
}
_EN_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

_FR_CARDINAL = {
    "un": 1,
    "une": 1,
    "deux": 2,
    "trois": 3,
    "quatre": 4,
    "cinq": 5,
    "six": 6,
    "sept": 7,
    "huit": 8,
    "neuf": 9,
    "dix": 10,
    "onze": 11,
    "douze": 12,
    "treize": 13,
    "quatorze": 14,
    "quinze": 15,
    "seize": 16,
    "dix-sept": 17,
    "dix-huit": 18,
    "dix-neuf": 19,
    "vingt": 20,
}


def _parse_iso(raw: str) -> datetime:
    text = (raw or "").strip().replace("Z", "+00:00")
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _leg_days(t_a: str, t_b: str) -> float:
    return (_parse_iso(t_b) - _parse_iso(t_a)).total_seconds() / 86400.0


def _anchor_calendar_sets(leg: dict) -> tuple[set[tuple[int, int]], set[tuple[int, int, int]]]:
    """Day/month and optional year sets from anchor ISO timestamps."""
    dm: set[tuple[int, int]] = set()
    dmy: set[tuple[int, int, int]] = set()
    for anchor in leg.get("anchors") or []:
        raw = anchor.get("t")
        if not raw:
            continue
        dt = _parse_iso(str(raw))
        dm.add((dt.month, dt.day))
        dmy.add((dt.year, dt.month, dt.day))
    return dm, dmy


def _fr_dates_in_text(text: str) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for m in re.finditer(
        r"\bLe (\d+|1er) (janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)\b",
        text,
        flags=re.IGNORECASE,
    ):
        day = 1 if m.group(1) == "1er" else int(m.group(1))
        month = _FR_MONTHS[m.group(2).lower()]
        out.append((month, day))
    for m in re.finditer(
        r"\ble (\d+|1er) (janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)\b",
        text,
        flags=re.IGNORECASE,
    ):
        day = 1 if m.group(1) == "1er" else int(m.group(1))
        month = _FR_MONTHS[m.group(2).lower()]
        out.append((month, day))
    return out


def _en_dates_in_text(text: str) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for m in re.finditer(
        r"\bOn ([A-Za-z]+) (\d{1,2})\b",
        text,
    ):
        month = _EN_MONTHS.get(m.group(1).lower())
        if month:
            out.append((month, int(m.group(2))))
    for m in re.finditer(
        r"\bon ([A-Za-z]+) (\d{1,2})\b",
        text,
    ):
        month = _EN_MONTHS.get(m.group(1).lower())
        if month:
            out.append((month, int(m.group(2))))
    for m in re.finditer(
        r"\bArrival (?:at|in) [^,]+ on ([A-Za-z]+) (\d{1,2})\b",
        text,
    ):
        month = _EN_MONTHS.get(m.group(1).lower())
        if month:
            out.append((month, int(m.group(2))))
    return out


def _parse_quoted_sea_days(text: str, *, en: bool) -> tuple[float | None, str]:
    """Return (midpoint estimate, phrase kind: exact|fuzzy|subday)."""
    if not en:
        m = re.search(
            r"(\d+)\s+jours de mer",
            text,
        )
        if m:
            return float(m.group(1)), "exact"
        m = re.search(
            r"(" + "|".join(_FR_CARDINAL) + r")\s+jours de mer",
            text,
        )
        if m:
            return float(_FR_CARDINAL[m.group(1)]), "exact"
        for label, mid in (
            ("moins d'un jour de mer", 0.5),
            ("un jour de mer", 1.0),
            ("une dizaine de jours de mer", 10.0),
            ("une quinzaine de jours de mer", 15.0),
            ("une vingtaine de jours de mer", 20.0),
            ("une trentaine de jours de mer", 30.0),
            ("une quarantaine de jours de mer", 40.0),
        ):
            if label in text:
                return mid, "fuzzy"
    else:
        m = re.search(r"(\d+)\s+days at sea", text)
        if m:
            return float(m.group(1)), "exact"
        m = re.search(
            r"(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
            r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty)"
            r"\s+days at sea",
            text,
            flags=re.IGNORECASE,
        )
        if m:
            words = {
                "one": 1,
                "two": 2,
                "three": 3,
                "four": 4,
                "five": 5,
                "six": 6,
                "seven": 7,
                "eight": 8,
                "nine": 9,
                "ten": 10,
                "eleven": 11,
                "twelve": 12,
                "thirteen": 13,
                "fourteen": 14,
                "fifteen": 15,
                "sixteen": 16,
                "seventeen": 17,
                "eighteen": 18,
                "nineteen": 19,
                "twenty": 20,
            }
            return float(words[m.group(1).lower()]), "exact"
        for label, mid in (
            ("less than a day at sea", 0.5),
            ("one day at sea", 1.0),
            ("about ten days at sea", 10.0),
            ("about fifteen days at sea", 15.0),
            ("about twenty days at sea", 20.0),
            ("about thirty days at sea", 30.0),
            ("about forty days at sea", 40.0),
        ):
            if label in text:
                return mid, "fuzzy"
    return None, ""


def _iter_focus_chapters(payload: dict) -> list[tuple[str, dict]]:
    rows: list[tuple[str, dict]] = []
    if "chapters" in payload:
        for leg in payload["chapters"]:
            if leg.get("id") in _FOCUS:
                rows.append(("film_150_raw", leg))
    else:
        for lang in ("fr", "en"):
            for leg in (payload.get(lang) or {}).get("chapters") or []:
                if leg.get("id") in _FOCUS:
                    rows.append((f"film_integral_written:{lang}", leg))
    return rows


@pytest.mark.parametrize(
    "fixture_name",
    ["film_150_raw_2026-10-29.json", "film_integral_written_2026-10-29.json"],
)
def test_film_fixture_leg_narrative_matches_schedule(fixture_name: str) -> None:
    path = _FIXTURES / fixture_name
    payload = json.loads(path.read_text(encoding="utf-8"))
    for source, leg in _iter_focus_chapters(payload):
        leg_id = leg["id"]
        actual_days = _leg_days(str(leg["tA"]), str(leg["tB"]))
        text = leg.get("text") or ""
        en = ":en" in source or source.endswith(":en")
        quoted, kind = _parse_quoted_sea_days(text, en=en)
        assert quoted is not None, f"{source} {leg_id}: no sea-day phrase in {text!r}"
        if kind == "exact":
            assert abs(quoted - actual_days) <= 1.0, (
                f"{source} {leg_id}: {quoted} days in text vs {actual_days:.2f} from tA/tB"
            )
        else:
            assert abs(quoted - actual_days) <= 5.0, (
                f"{source} {leg_id}: fuzzy {quoted} vs {actual_days:.2f}"
            )
        expected_phrase = spoken_sea_days(actual_days, "en" if en else "fr")
        assert expected_phrase in text, (
            f"{source} {leg_id}: expected {expected_phrase!r} for {actual_days:.2f}d in {text!r}"
        )

        dm, _ = _anchor_calendar_sets(leg)
        cited = _en_dates_in_text(text) if en else _fr_dates_in_text(text)
        assert cited, f"{source} {leg_id}: no calendar dates in narrative"
        for month, day in cited:
            assert (month, day) in dm, (
                f"{source} {leg_id}: cited {(day, month)} not in anchor day/month {sorted(dm)}"
            )
