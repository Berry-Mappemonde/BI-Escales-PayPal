"""Fixture chapters must keep tA <= anchors <= tB and non-overlapping leg order."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

_FIXTURES = Path(__file__).parent / "fixtures"


def _parse_iso(raw: str) -> datetime:
    text = (raw or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _chapters_from_payload(payload: dict) -> list[dict]:
    if "chapters" in payload:
        return list(payload["chapters"] or [])
    chapters: list[dict] = []
    for lang in ("fr", "en"):
        block = payload.get(lang) or {}
        chapters.extend(block.get("chapters") or [])
    return chapters


def _assert_leg_chronology(chapters: list[dict], *, source: str) -> None:
    previous_end: datetime | None = None
    for leg in chapters:
        leg_id = leg.get("id", "?")
        t_a = _parse_iso(str(leg["tA"]))
        t_b = _parse_iso(str(leg["tB"]))
        assert t_a <= t_b, f"{source} {leg_id}: tA after tB ({leg['tA']} > {leg['tB']})"
        if previous_end is not None:
            assert t_a >= previous_end, (
                f"{source} {leg_id}: tA {leg['tA']} before previous tB {previous_end.isoformat()}"
            )
        previous_end = t_b
        for anchor in leg.get("anchors") or []:
            if not anchor.get("t"):
                continue
            t_anchor = _parse_iso(str(anchor["t"]))
            assert t_a <= t_anchor <= t_b, (
                f"{source} {leg_id}: anchor {anchor.get('t')} outside [{leg['tA']}, {leg['tB']}]"
            )


@pytest.mark.parametrize(
    "fixture_name",
    [
        "film_150_raw_2026-10-29.json",
        "film_integral_written_2026-10-29.json",
    ],
)
def test_film_fixture_steps_are_chronological(fixture_name: str) -> None:
    path = _FIXTURES / fixture_name
    payload = json.loads(path.read_text(encoding="utf-8"))
    chapters = _chapters_from_payload(payload)
    assert chapters, f"no chapters in {fixture_name}"
    if "chapters" in payload:
        _assert_leg_chronology(chapters, source=fixture_name)
    else:
        for lang in ("fr", "en"):
            block = payload.get(lang) or {}
            legs = list(block.get("chapters") or [])
            _assert_leg_chronology(legs, source=f"{fixture_name}:{lang}")
