"""Film fixtures: narrative dates and sea durations vs cabin schedule (runs in CI)."""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
FIXTURES = REPO / "naviguide-escales/server/tests/fixtures"
CABIN = Path(__file__).resolve().parents[1] / "app/escales/cabin_legs.json"

sys.path.insert(0, str(REPO / "naviguide-escales/server"))
from film_script import spoken_sea_days  # noqa: E402

FILM_CABIN: dict[str, str | None] = {
    "leg-0": "leg-la-rochelle-to-ajaccio-corse",
    "leg-1": "leg-ajaccio-corse-to-fort-de-france-martinique",
    "leg-2": "leg-fort-de-france-martinique-to-pointe-a-pitre-guadeloupe",
    "leg-3": "leg-pointe-a-pitre-guadeloupe-to-gustavia-saint-barthelemy",
    "leg-4": "leg-gustavia-saint-barthelemy-to-marigot-saint-martin",
    "leg-5": "leg-marigot-saint-martin-to-cayenne-guyane",
    "leg-6": None,
    "leg-7": None,
    "leg-8": None,
    "leg-9": None,
    "leg-10": "leg-cayenne-guyane-to-papeete-polynesie-francaise",
    "leg-11": "leg-papeete-polynesie-francaise-to-mata-utu-wallis-et-futuna",
    "leg-12": "leg-mata-utu-wallis-et-futuna-to-noumea-nouvelle-caledonie",
    "leg-13": "leg-noumea-nouvelle-caledonie-to-dzaoudzi-mayotte",
    "leg-14": "leg-dzaoudzi-mayotte-to-tromelin-taaf",
    "leg-15": "leg-tromelin-taaf-to-saint-gilles-la-reunion",
    "leg-16": "leg-saint-gilles-la-reunion-to-europa-taaf",
    "leg-17": "leg-europa-taaf-to-la-rochelle",
}

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


def _parse_iso(raw: str) -> datetime:
    text = (raw or "").strip().replace("Z", "+00:00")
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _leg_days(t_a: str, t_b: str) -> float:
    return (_parse_iso(t_b) - _parse_iso(t_a)).total_seconds() / 86400.0


def _cabin_sea_bounds(cabin: dict) -> dict[str, tuple[str, str]]:
    by = {row["id"]: row for row in cabin["legs"]}
    out: dict[str, tuple[str, str]] = {}
    prev_t_b: str | None = None
    cayenne_arr = by["leg-marigot-saint-martin-to-cayenne-guyane"]["arrival_iso"]
    cayenne_dep = by["leg-cayenne-guyane-to-papeete-polynesie-francaise"]["departure_iso"]
    halifax_start = _parse_iso(cayenne_arr)
    halifax_end = _parse_iso(cayenne_dep)
    halifax_span = max((halifax_end - halifax_start).total_seconds(), 1.0)

    for film_id in [f"leg-{i}" for i in range(18)]:
        if film_id in {"leg-6", "leg-7", "leg-8", "leg-9"}:
            idx = int(film_id.split("-")[1]) - 6
            frac0, frac1 = idx / 4, (idx + 1) / 4
            t_a = halifax_start + timedelta(seconds=halifax_span * frac0)
            t_b = halifax_start + timedelta(seconds=halifax_span * frac1)
            out[film_id] = (t_a.isoformat().replace("+00:00", "Z"), t_b.isoformat().replace("+00:00", "Z"))
            continue
        cabin_id = FILM_CABIN.get(film_id)
        if not cabin_id:
            continue
        row = by[cabin_id]
        out[film_id] = (row["departure_iso"], row["arrival_iso"])
    return out


def _anchor_dt(leg: dict, kind: str) -> datetime | None:
    for anchor in leg.get("anchors") or []:
        if anchor.get("kind") == kind and anchor.get("t"):
            return _parse_iso(str(anchor["t"]))
    return None


def _fr_departure_date(text: str) -> tuple[int, int] | None:
    m = re.search(
        r"\bLe (\d+|1er) (janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)(?=, [^\.]{0,80}départ)",
        text,
        flags=re.IGNORECASE,
    )
    if m:
        day = 1 if m.group(1) == "1er" else int(m.group(1))
        return _FR_MONTHS[m.group(2).lower()], day
    m = re.search(
        r"quitté [^\.]+ le (\d+|1er) (janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)",
        text,
        flags=re.IGNORECASE,
    )
    if m:
        day = 1 if m.group(1) == "1er" else int(m.group(1))
        return _FR_MONTHS[m.group(2).lower()], day
    return None


def _fr_arrival_date(text: str) -> tuple[int, int] | None:
    m = re.search(
        r"Arrivée à [^\.]+ le (\d+|1er) (janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)",
        text,
        flags=re.IGNORECASE,
    )
    if not m:
        return None
    day = 1 if m.group(1) == "1er" else int(m.group(1))
    return _FR_MONTHS[m.group(2).lower()], day


def _en_departure_date(text: str) -> tuple[int, int] | None:
    m = re.search(r"\bOn ([A-Za-z]+) (\d{1,2})\b", text)
    if not m:
        return None
    month = _EN_MONTHS.get(m.group(1).lower())
    if not month:
        return None
    return month, int(m.group(2))


def _en_arrival_date(text: str) -> tuple[int, int] | None:
    m = re.search(r"\bArrival (?:at|in) [^,]+ on ([A-Za-z]+) (\d{1,2})\b", text)
    if not m:
        return None
    month = _EN_MONTHS.get(m.group(1).lower())
    if not month:
        return None
    return month, int(m.group(2))


def _spoken_day_span(dep: tuple[int, int], arr: tuple[int, int], *, year: int) -> int:
    m1, d1 = dep
    m2, d2 = arr
    t0 = datetime(year, m1, d1, tzinfo=timezone.utc)
    t1 = datetime(year, m2, d2, tzinfo=timezone.utc)
    if t1 < t0:
        t1 = datetime(year + 1, m2, d2, tzinfo=timezone.utc)
    return (t1 - t0).days


def _iter_all_chapters(payload: dict) -> list[tuple[str, dict]]:
    rows: list[tuple[str, dict]] = []
    if "chapters" in payload:
        for leg in payload["chapters"]:
            rows.append(("raw", leg))
    else:
        for lang in ("fr", "en"):
            for leg in (payload.get(lang) or {}).get("chapters") or []:
                rows.append((lang, leg))
    return rows


def _parse_sea_days_numeric(text: str, *, en: bool) -> float | None:
    phrase = spoken_sea_days(0, "en" if en else "fr")  # unused; patterns below
    del phrase
    if en:
        m = re.search(
            r"(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
            r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|\d+)"
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
            g = m.group(1).lower()
            if g.isdigit():
                return float(g)
            return float(words[g])
        for label, mid in (
            ("about ten days at sea", 10),
            ("about fifteen days at sea", 15),
            ("about twenty days at sea", 20),
            ("about thirty days at sea", 30),
            ("about forty days at sea", 40),
        ):
            if label in text:
                return float(mid)
    else:
        m = re.search(r"(\d+)\s+jours de mer", text)
        if m:
            return float(m.group(1))
        cardinals = {
            "un": 1,
            "deux": 2,
            "trois": 3,
            "quatre": 4,
            "cinq": 5,
            "six": 6,
            "sept": 7,
            "huit": 8,
            "neuf": 9,
            "dix": 10,
        }
        m = re.search(r"(" + "|".join(cardinals) + r")\s+jours de mer", text)
        if m:
            return float(cardinals[m.group(1)])
        for label, mid in (("une dizaine de jours de mer", 10), ("une quinzaine de jours de mer", 15)):
            if label in text:
                return float(mid)
    return None


@pytest.fixture(scope="module")
def cabin_bounds() -> dict[str, tuple[str, str]]:
    cabin = json.loads(CABIN.read_text(encoding="utf-8"))
    return _cabin_sea_bounds(cabin)


@pytest.mark.parametrize(
    "fixture_name",
    ["film_150_raw_2026-10-29.json", "film_integral_written_2026-10-29.json"],
)
def test_film_fixture_narrative_coherence(fixture_name: str, cabin_bounds: dict[str, tuple[str, str]]) -> None:
    path = FIXTURES / fixture_name
    payload = json.loads(path.read_text(encoding="utf-8"))
    for source, leg in _iter_all_chapters(payload):
        leg_id = leg.get("id") or ""
        if leg_id not in cabin_bounds and leg_id not in {"leg-6"}:
            continue
        text = leg.get("text") or ""
        en = source == "en"
        dep_anchor = _anchor_dt(leg, "depart")
        escale_anchor = _anchor_dt(leg, "escale")

        if leg_id in cabin_bounds:
            dep_iso, arr_iso = cabin_bounds[leg_id]
            sea_days = _leg_days(dep_iso, arr_iso)
            expected_phrase = spoken_sea_days(sea_days, "en" if en else "fr")
            strict_sea = source == "raw" or leg_id in {f"leg-{n}" for n in range(13, 18)}
            if strict_sea and ("de mer" in text or "at sea" in text):
                quoted = _parse_sea_days_numeric(text, en=en)
                fuzzy = any(
                    k in expected_phrase
                    for k in ("dizaine", "quinzaine", "vingtaine", "trentaine", "quarantaine", "about")
                )
                phrase_ok = expected_phrase in text
                if not phrase_ok and quoted is not None:
                    tol = 6.0 if fuzzy else 2.0
                    phrase_ok = abs(quoted - sea_days) <= tol
                assert phrase_ok, (
                    f"{fixture_name}:{source} {leg_id}: expected {expected_phrase!r} "
                    f"(cabin {sea_days:.2f}d) in {text!r}"
                )
                if quoted is not None:
                    tol = 6.0 if fuzzy else 1.5
                    assert abs(quoted - sea_days) <= tol, (
                        f"{fixture_name}:{source} {leg_id}: {quoted} vs cabin {sea_days:.2f}d"
                    )

                if leg_id in {f"leg-{n}" for n in range(13, 18)}:
                    cabin = json.loads(CABIN.read_text(encoding="utf-8"))
                    by = {row["id"]: row for row in cabin["legs"]}
                    cid = FILM_CABIN[leg_id]
                    assert cid
                    assert dep_iso == by[cid]["departure_iso"]
                    assert arr_iso == by[cid]["arrival_iso"]

        strict_dates = leg_id in {f"leg-{n}" for n in range(13, 18)} or source == "raw"
        if strict_dates and dep_anchor:
            dep_cited = _en_departure_date(text) if en else _fr_departure_date(text)
            if dep_cited:
                assert dep_cited == (dep_anchor.month, dep_anchor.day), (
                    f"{fixture_name}:{source} {leg_id}: departure cite {dep_cited} "
                    f"!= depart anchor {(dep_anchor.month, dep_anchor.day)}"
                )
        if strict_dates and escale_anchor:
            arr_cited = _en_arrival_date(text) if en else _fr_arrival_date(text)
            if arr_cited:
                assert arr_cited == (escale_anchor.month, escale_anchor.day), (
                    f"{fixture_name}:{source} {leg_id}: arrival cite {arr_cited} "
                    f"!= escale anchor {(escale_anchor.month, escale_anchor.day)}"
                )

        if strict_dates:
            dep_cited = (_en_departure_date(text) if en else _fr_departure_date(text)) if text else None
            arr_cited = (_en_arrival_date(text) if en else _fr_arrival_date(text)) if text else None
            quoted = _parse_sea_days_numeric(text, en=en)
            if (
                dep_cited
                and arr_cited
                and quoted is not None
                and quoted == int(round(quoted))
                and "dizaine" not in text
                and "about ten" not in text
            ):
                year = (escale_anchor or dep_anchor or datetime(2027, 1, 1, tzinfo=timezone.utc)).year
                spoken_span = _spoken_day_span(dep_cited, arr_cited, year=year)
                assert abs(spoken_span - quoted) <= 1, (
                    f"{fixture_name}:{source} {leg_id}: dates span {spoken_span} vs stated {quoted}"
                )

        if leg_id == "leg-17" and escale_anchor and dep_anchor:
            for anchor in leg.get("anchors") or []:
                if anchor.get("kind") == "alert-on" and anchor.get("t"):
                    t_amp = _parse_iso(str(anchor["t"]))
                    assert dep_anchor <= t_amp <= escale_anchor, (
                        f"{fixture_name}:{source} leg-17: Pointe anchor outside sea leg"
                    )
                    assert (escale_anchor - t_amp).days <= 3, "Pointe d'Arçay should be near La Rochelle arrival"


def test_film_fixtures_forbid_may_2027_literals() -> None:
    forbidden = re.compile(
        r"2027-05-15|mai 2027|may 2027|15 mai 2027|may 15, 2027",
        re.IGNORECASE,
    )
    for name in ("film_150_raw_2026-10-29.json", "film_integral_written_2026-10-29.json"):
        blob = (FIXTURES / name).read_text(encoding="utf-8")
        assert not forbidden.search(blob), name
