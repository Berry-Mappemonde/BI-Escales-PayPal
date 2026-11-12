"""Film fixtures: narrative dates and sea durations vs cabin schedule (runs in CI)."""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tests.film_cabin_schedule import FILM_CABIN, film_leg_bounds, fixture_tb_matches_cabin

REPO = Path(__file__).resolve().parents[3]
FIXTURES = REPO / "naviguide-escales/server/tests/fixtures"
CABIN = Path(__file__).resolve().parents[1] / "app/escales/cabin_legs.json"

sys.path.insert(0, str(REPO / "naviguide-escales/server"))
from film_script import spoken_sea_days  # noqa: E402

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
    return moment.astimezone(timezone.utc).replace(microsecond=0)


def _instants_equal(left: str, right: str) -> bool:
    return _parse_iso(left) == _parse_iso(right)


def _leg_days(t_a: str, t_b: str) -> float:
    return (_parse_iso(t_b) - _parse_iso(t_a)).total_seconds() / 86400.0


def _cabin_sea_bounds(cabin: dict) -> dict[str, tuple[str, str]]:
    bounds = film_leg_bounds(cabin)
    out: dict[str, tuple[str, str]] = {}
    for leg_id, (_, _, dep, arr) in bounds.items():
        if leg_id in {"leg-6", "leg-7", "leg-8", "leg-9"}:
            continue
        out[leg_id] = (dep, arr)
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
    m = re.search(
        r"\bLe (\d+|1er) (janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre), (?=(?:d'île|Berry|pour la).{0,60}quitte)",
        text,
        flags=re.IGNORECASE,
    )
    if m:
        day = 1 if m.group(1) == "1er" else int(m.group(1))
        return _FR_MONTHS[m.group(2).lower()], day
    m = re.search(
        r"\bLe (\d+|1er) (janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre), [^\.]{0,80}(?:s'envole|embarque|reprend)",
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


def _fr_all_cited_dates(text: str) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for m in re.finditer(
        r"\b(?:Le|le) (\d+|1er) (janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)",
        text,
        flags=re.IGNORECASE,
    ):
        day = 1 if m.group(1).lower() == "1er" else int(m.group(1))
        out.append((_FR_MONTHS[m.group(2).lower()], day))
    return out


def _en_all_cited_dates(text: str) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for m in re.finditer(r"\bOn ([A-Za-z]+) (\d{1,2})\b", text):
        month = _EN_MONTHS.get(m.group(1).lower())
        if month:
            out.append((month, int(m.group(2))))
    return out


def _year_window(t_a: datetime, t_b: datetime, month: int, day: int) -> bool:
    for year in (t_a.year, t_a.year + 1):
        try:
            cited = datetime(year, month, day, 12, tzinfo=timezone.utc)
        except ValueError:
            continue
        pad = timedelta(days=1)
        if t_a - pad <= cited <= t_b + pad:
            return True
    return False


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


def run_film_fixture_narrative_coherence(
    payload: dict,
    *,
    fixture_name: str,
    cabin_bounds: dict[str, tuple[str, str]],
    expected_tb: dict[str, tuple[str, str]],
) -> None:
    cabin = json.loads(CABIN.read_text(encoding="utf-8"))
    for source, leg in _iter_all_chapters(payload):
        leg_id = leg.get("id") or ""
        if not leg_id.startswith("leg-"):
            continue
        text = leg.get("text") or ""
        en = source == "en"
        dep_anchor = _anchor_dt(leg, "depart")
        escale_anchor = _anchor_dt(leg, "escale")
        t_a = _parse_iso(str(leg.get("tA") or ""))
        t_b = _parse_iso(str(leg.get("tB") or ""))

        if leg_id in expected_tb:
            exp_a, exp_b = expected_tb[leg_id]
            assert _instants_equal(str(leg.get("tA")), exp_a), f"{fixture_name}:{source} {leg_id} tA"
            assert _instants_equal(str(leg.get("tB")), exp_b), f"{fixture_name}:{source} {leg_id} tB"

        if leg_id in {f"leg-{n}" for n in range(1, 13)} and source in {"fr", "en"} and leg_id in cabin_bounds:
            dep_iso, arr_iso = cabin_bounds[leg_id]
            sea_days = _leg_days(dep_iso, arr_iso)
            expected_phrase = spoken_sea_days(sea_days, "en" if en else "fr")
            if ("de mer" in text or "at sea" in text) and any(
                k in expected_phrase for k in ("dizaine", "quinzaine", "trentaine", "quarantaine", "about")
            ):
                assert expected_phrase in text, (
                    f"{fixture_name}:{source} {leg_id}: integral fuzzy sea {expected_phrase!r}"
                )

        if leg_id in cabin_bounds and leg_id not in {"leg-6", "leg-7", "leg-8", "leg-9"}:
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

            if leg_id in {f"leg-{n}" for n in range(13, 18)}:
                by = {row["id"]: row for row in cabin["legs"]}
                cid = FILM_CABIN[leg_id]
                assert cid
                assert dep_iso == by[cid]["departure_iso"]
                assert arr_iso == by[cid]["arrival_iso"]

        strict_dates = (
            source == "raw"
            or leg_id in {f"leg-{n}" for n in range(13, 18)}
            or (source == "fr" and leg_id in {f"leg-{n}" for n in range(1, 13)})
            or (source == "en" and leg_id in {f"leg-{n}" for n in range(1, 13)})
        )
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

        if leg_id in {f"leg-{n}" for n in range(1, 13)} and source in {"fr", "en"}:
            cited = _en_all_cited_dates(text) if en else _fr_all_cited_dates(text)
            dep_cited = _en_departure_date(text) if en else _fr_departure_date(text)
            arr_cited = _en_arrival_date(text) if en else _fr_arrival_date(text)
            for pair in cited:
                if dep_cited and pair == dep_cited:
                    continue
                if arr_cited and pair == arr_cited:
                    continue
                assert _year_window(t_a, t_b, pair[0], pair[1]), (
                    f"{fixture_name}:{source} {leg_id}: stray date {pair} outside [{leg.get('tA')}, {leg.get('tB')}]"
                )

        if source == "fr" and leg_id in {f"leg-{n}" for n in range(1, 13)} and "quitte" in text:
            dep_cited = _fr_departure_date(text)
            assert dep_cited and dep_anchor, f"{fixture_name}: leg {leg_id} quitte without depart anchor"
            assert dep_cited == (dep_anchor.month, dep_anchor.day)

        if leg_id == "leg-7":
            if en:
                assert "497 miles" in text and "three days at sea" in text
            else:
                assert "497 milles" in text and "trois jours de mer" in text

        if leg_id == "leg-17":
            blob = text.lower()
            assert blob.count("pointe d'arçay") <= 1
            for anchor in leg.get("anchors") or []:
                assert anchor.get("kind") != "alert-on", "leg-17 must not use synthetic alert-on anchor"

        if en and "Le August" in text:
            raise AssertionError(f"{fixture_name}:{source} {leg_id}: Le August leak")

        for anchor in leg.get("anchors") or []:
            if anchor.get("t"):
                t_anchor = _parse_iso(str(anchor["t"]))
                assert t_a <= t_anchor <= t_b, (
                    f"{fixture_name}:{source} {leg_id}: anchor {anchor.get('t')} outside window"
                )
            idx = anchor.get("charIdx")
            if idx is not None and text:
                assert 0 <= int(idx) < len(text), f"{fixture_name}:{source} {leg_id}: charIdx {idx}"


@pytest.fixture(scope="module")
def cabin_bounds() -> dict[str, tuple[str, str]]:
    cabin = json.loads(CABIN.read_text(encoding="utf-8"))
    return _cabin_sea_bounds(cabin)


@pytest.fixture(scope="module")
def expected_tb() -> dict[str, tuple[str, str]]:
    cabin = json.loads(CABIN.read_text(encoding="utf-8"))
    return fixture_tb_matches_cabin(cabin)


@pytest.mark.parametrize(
    "fixture_name",
    ["film_150_raw_2026-10-29.json", "film_integral_written_2026-10-29.json"],
)
def test_film_fixture_narrative_coherence(
    fixture_name: str,
    cabin_bounds: dict[str, tuple[str, str]],
    expected_tb: dict[str, tuple[str, str]],
) -> None:
    path = FIXTURES / fixture_name
    payload = json.loads(path.read_text(encoding="utf-8"))
    run_film_fixture_narrative_coherence(
        payload,
        fixture_name=fixture_name,
        cabin_bounds=cabin_bounds,
        expected_tb=expected_tb,
    )


def test_film_fixtures_forbid_may_2027_literals() -> None:
    forbidden = re.compile(
        r"2027-05-15|mai 2027|may 2027|15 mai 2027|may 15, 2027",
        re.IGNORECASE,
    )
    for name in ("film_150_raw_2026-10-29.json", "film_integral_written_2026-10-29.json"):
        blob = (FIXTURES / name).read_text(encoding="utf-8")
        assert not forbidden.search(blob), name


def test_integral_sentences_start_with_a_capital() -> None:
    """Removing a stale date from the start of a sentence must not leave it in lower case."""
    blob = (FIXTURES / "film_integral_written_2026-10-29.json").read_text(encoding="utf-8")
    lower_starts = re.findall(r"[^.!?]{0,30}[.!?] [a-zà-ÿ][^.!?]{0,20}", blob)
    assert lower_starts == []
