"""Script du film : longueur, balises, aucun nombre nouveau, cache, sélection."""
import asyncio
import json
import re
from datetime import datetime, timezone

import pearl_store
import story_cache
from film_script import (
    OFFICIAL_ROUTE_ZEE_SOURCES,
    chapter_anchors,
    FILM_VOICE_LOOKAHEAD_CHARS,
    CONNECTORS,
    FILM_BUDGET_CHARS,
    FILM_CHAPTER_MAX_CHANGES,
    FILM_MAX_CHARS,
    FILM_WRITE_MAX,
    FILM_WRITE_MIN,
    SHORT_CROSSING_MS,
    allocate_chapter_budgets,
    film_char_budget,
    film_write_window,
    film_ultra_open,
    write_film_chain,
    _harbor_spoken,
    _hold_phrase,
    film_estimated_seconds,
    film_priority_tier,
    fit_chapter_text,
    alert_is_amp,
    bubble_score,
    build_film_response,
    build_raw_script,
    change_sentence,
    chapter_metrics,
    chapter_shape,
    coast_sentence,
    connector_at,
    cyclone_name_year,
    dated_marks,
    date_density_ok,
    dc_subject_candidates,
    film_choice_bag,
    tour_snapshot,
    parse_choice_ids,
    fallback_choose_ids,
    apply_chosen_subjects,
    choose_film_ids,
    select_ids_with_vl,
    trim_ids_with_lightning,
    TV1_WATCH_ID,
    TV1_WATCH_KIND,
    DC_FAMILY_KINDS,
    dose_amp_changes,
    dose_dc2_leg_changes,
    dose_dc3_leg_changes,
    dose_climo_changes,
    dose_coast_changes,
    dose_project_changes,
    dose_station_changes,
    dose_zee_changes,
    film_candidates,
    film_facts,
    film_has_forbidden,
    heading_phrase,
    is_sea_chapter,
    journal_fingerprint,
    last_stop_id,
    looks_english_title,
    norm_stop,
    review_leg_for_chapter,
    review_plan_stats,
    review_sentences,
    upcoming_stop_names,
    eta_payload_for_stop,
    official_dated_stops,
    prefer_journal_moments,
    spoken_sea_days,
    thin_chapter_dates,
    _arrival_harbor,
    _close_sentence,
    _de,
    _film_open_sentences,
    _ms,
    _nm_between,
    _window_depart_ms,
    _windows,
    warm_film_story,
    select_chapter_changes,
    select_film_events,
    station_name_speakable,
    station_spoken_label,
    speak_film_text,
    written_is_valid,
    write_stored_plan,
    WRITTEN_SOURCE,
    apply_written_guard,
    chapter_structured_facts,
    zee_waters_label,
    _nm_label,
)


def test_raw_harbor_and_stopover_templates_respect_en_and_fr():
    assert _harbor_spoken("de La Rochelle", "La Rochelle", "marina", "en") == "the La Rochelle marina"
    assert _harbor_spoken("de La Rochelle", "La Rochelle", "marina", "fr") == "la marina de La Rochelle"
    assert _hold_phrase(3, 0, "en") == "a three-day stopover"
    assert _hold_phrase(3, 0, "fr") == "trois jours d'escale"
from tests.test_voyage_journal import PUBLIC, _official
from voyage_clock import OFFICIAL_T0

CLOCK = {
    "t0": "2026-05-15T08:00:00Z",
    "marks": [
        {"name": "Saint-Maur (Berry, Indre)", "nm": 0, "filmNm": 0, "iso": "2026-05-15T08:00:00Z", "holdHours": 0, "lat": 46.8, "lon": 1.6},
        {"name": "La Rochelle", "nm": 0, "filmNm": 122, "iso": "2026-05-15T12:00:00Z", "holdHours": 72, "lat": 46.15, "lon": -1.16},
        {"name": "Ajaccio (Corse)", "nm": 1820, "filmNm": 1942, "iso": "2026-05-24T12:51:00Z", "holdHours": 72, "lat": 41.9, "lon": 8.7},
        {"name": "Fort-de-France (Martinique)", "nm": 6973, "filmNm": 7095, "iso": "2026-06-23T08:34:00Z", "holdHours": 72, "lat": 14.6, "lon": -61.0},
        {"name": "Nouméa (Nouvelle-Calédonie)", "nm": 19055, "filmNm": 19177, "iso": "2026-09-17T22:48:00Z", "holdHours": 72, "lat": -22.2, "lon": 166.4},
    ],
}
LIVE = {"filmNm": 19400, "sailNm": 19260, "iso": "2026-09-19T02:00:00Z", "status": "live"}
NOW_MS = int(datetime(2026, 9, 19, 2, 0, tzinfo=timezone.utc).timestamp() * 1000)
JOURNAL = {
    "latest": [
        {"id": "zee:es", "kind": "zee", "t": "2026-05-17T15:00:00Z", "event": "enter", "name": "Spanish Exclusive Economic Zone", "mrgid": 5693},
        {"id": "amp:cabrera", "kind": "amp", "t": "2026-05-18T02:00:00Z", "event": "nearby", "name": "Cabrera", "nm": 8},
        {"id": "poe:lr", "kind": "poe", "t": "2026-05-15T12:00:00Z", "event": "passed", "name": "La Rochelle - La Pallice", "poeId": "lr"},
        {"id": "wx:gale", "kind": "wx", "t": "2026-05-22T06:00:00Z", "event": "gale", "windKnots": 36.5, "maxWindKnots": 38, "hours": 6, "hs": 2.4},
        {"id": "climo:rose", "kind": "climo", "t": "2026-06-02T12:00:00Z", "event": "rose", "facts": {"deltaDeg": 120}, "name": "alizés"},
        {"id": "sci:pirata", "kind": "sci", "t": "2026-06-10T06:00:00Z", "name": "PIRATA", "facts": {"nm": 6, "name": "PIRATA"}},
        {"id": "wx:sea", "kind": "wx", "t": "2026-07-01T06:00:00Z", "event": "sea", "windKnots": 22, "maxHs": 4.2, "hours": 12, "hs": 4.2},
        {"id": "note:1", "kind": "note", "t": "2026-05-21T10:00:00Z", "text": "Première nuit au large."},
        {"id": "zee:fr", "kind": "zee", "t": "2026-05-16T09:00:00Z", "event": "enter", "name": "French Exclusive Economic Zone", "mrgid": 5677},
        {"id": "amp:pertuis", "kind": "amp", "t": "2026-05-15T18:00:00Z", "event": "nearby", "name": "Pertuis Charentais", "nm": 3},
        {"id": "poe:aj", "kind": "poe", "t": "2026-05-24T12:00:00Z", "event": "passed", "name": "Ajaccio", "poeId": "aj"},
        {"id": "sci:argo", "kind": "sci", "t": "2026-08-01T06:00:00Z", "name": "Argo", "facts": {"nm": 4}},
    ],
}


def _raw():
    return build_raw_script(CLOCK, CLOCK["marks"], LIVE, JOURNAL, lang="fr", seconds=150, now_ms=NOW_MS)


def test_raw_length_bounded_and_chapter1_names():
    plan = _raw()
    assert plan["chars"] <= FILM_MAX_CHARS
    assert plan["source"] == "rules"
    assert plan["chapters"]
    assert "Saint-Maur" in plan["chapters"][0]["text"]
    assert "La Rochelle" in plan["chapters"][0]["text"]


def test_connectors_alternate():
    """Plus de rotation mécanique ; les formes suivent le contenu.

    Le gabarit complet (quitte / longue traversée) est l'intégral, pas le 2:30.
    """
    plan = build_raw_script(CLOCK, CLOCK["marks"], LIVE, JOURNAL, lang="fr", seconds=0, now_ms=NOW_MS)
    blob = " ".join(c.get("text") or "" for c in plan["chapters"])
    assert "À la jambe suivante" not in blob
    assert "On the next leg" not in blob
    assert connector_at(0, "fr") != "À la jambe suivante"
    long_hit = any("longue traversée" in (c.get("text") or "") for c in plan["chapters"])
    last_hit = any("dernière étape" in (c.get("text") or "") for c in plan["chapters"])
    assert long_hit or last_hit or "Berry-Mappemonde quitte" in blob


def test_raw_english_chapter1():
    plan = build_raw_script(CLOCK, CLOCK["marks"], LIVE, JOURNAL, lang="en", seconds=150, now_ms=NOW_MS)
    text = plan["chapters"][0]["text"]
    assert "Saint-Maur" in text
    assert "La Rochelle" in text
    assert ("left" in text.lower() or "departed" in text.lower() or "leaves" in text.lower())
    assert "quitté" not in text


def test_selection_deterministic():
    packed = film_candidates(JOURNAL, CLOCK["marks"], CLOCK, LIVE, NOW_MS)
    a = [e["id"] for e in select_film_events(packed["candidates"], packed["t0"], packed["tEnd"])]
    b = [e["id"] for e in select_film_events(packed["candidates"], packed["t0"], packed["tEnd"])]
    assert a == b
    assert "depart" in a and "today" in a
    assert 6 <= len(a) <= 9
    assert any(i.startswith("wx") for i in a)


def _honest_written(raw: dict, events: list[dict]) -> str:
    pad = " La mer reste la mer, le vent reste le vent, la route reste la route."
    chunks = []
    for ch in raw["chapters"]:
        bits = [ch.get("text") or ""]
        for ev in ch.get("events") or []:
            bits.append(f"[[ev:{ev['id']}]]")
        chunks.append(" ".join(bits))
    body = " ".join(chunks)
    for ev in events:
        if f"[[ev:{ev['id']}]]" not in body:
            body = f"[[ev:{ev['id']}]] " + body
    while len(body.replace("[[ev:", "").replace("]]", "")) < FILM_WRITE_MIN:
        body += pad
    # Keep visible length in range (tags don't count the same after strip — pad then trim display).
    from film_script import strip_tags
    while len(strip_tags(body)) < FILM_WRITE_MIN:
        body += pad
    display = strip_tags(body)
    if len(display) > FILM_WRITE_MAX:
        overflow = len(display) - FILM_WRITE_MAX
        body = body[: max(0, len(body) - overflow)]
        # Ensure tags still present after a tail trim: re-append missing tags then re-pad carefully.
        for ev in events:
            tag = f"[[ev:{ev['id']}]]"
            if tag not in body:
                body = tag + " " + body
        while len(strip_tags(body)) < FILM_WRITE_MIN:
            body += pad
        display = strip_tags(body)
        if len(display) > FILM_WRITE_MAX:
            # cut padding only
            body = body[: len(body) - (len(display) - FILM_WRITE_MAX)]
    return body


def test_written_valid_when_tags_and_length_and_no_new_number():
    raw = _raw()
    events = raw["_events"]
    facts = film_facts(raw, events)
    text = _honest_written(raw, events)
    ok, _, dropped = written_is_valid(text, facts, [e["id"] for e in events])
    assert dropped == 0
    assert ok, f"len={len(text)} stripped invalid"


def _sentences_from_user(user: str) -> list[str]:
    import json
    match = re.search(r"sentences=(\[.*\])\s*$", user or "", re.S)
    if not match:
        match = re.search(r"sentences=(\[.*\])", user or "", re.S)
    if not match:
        return []
    try:
        rows = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []
    return [str(s) for s in rows] if isinstance(rows, list) else []


def test_cheating_llm_falls_back_to_raw():
    raw = _raw()
    events = raw["_events"]
    facts = film_facts(raw, events)
    cheat = _honest_written(raw, events) + " Le vent atteindra 99 nœuds demain."
    ok, _, dropped = written_is_valid(cheat, facts, [e["id"] for e in events])
    assert dropped >= 1
    assert ok is False

    async def fake_cascade(system, user, **kw):
        if "JSON only" in system or ("ids" in system.lower() and "select" in system.lower()):
            return '{"ids":["depart"],"reason":"too few"}', "nemotron-lightning"
        sents = _sentences_from_user(user)
        if not sents:
            return cheat, "nemotron-super"
        sents = list(sents)
        sents[0] = sents[0].rstrip(".!?…") + " 99 nœuds."
        return " ".join(sents), "nemotron-super"

    async def run():
        return await build_film_response(
            CLOCK, LIVE, JOURNAL, lang="fr", seconds=150, style="written",
            now_ms=NOW_MS, cascade=fake_cascade, want_write=True,
        )

    out = asyncio.run(run())
    raw_sents = []
    for ch in raw["chapters"]:
        raw_sents.extend([s for s in re.split(r"(?<=[.!?…])\s+", ch.get("text") or "") if s.strip()])
    out_sents = []
    for ch in out["chapters"]:
        out_sents.extend([s for s in re.split(r"(?<=[.!?…])\s+", ch.get("text") or "") if s.strip()])
    assert "99" not in " ".join(c["text"] for c in out["chapters"])
    assert len(out_sents) == len(raw_sents)


def test_honest_llm_keeps_tags_and_length():
    raw = _raw()
    events = raw["_events"]

    async def fake_cascade(system, user, **kw):
        if "select" in system.lower() or "JSON only" in system:
            ids = [e["id"] for e in events]
            return json_ids(ids), "nemotron-lightning"
        sents = _sentences_from_user(user)
        if not sents:
            return _honest_written(raw, events), "nemotron-super"
        out = []
        for sent in sents:
            out.append(sent.replace("quitte", "laisse", 1) if "quitte" in sent else sent)
        return " ".join(out), "nemotron-super"

    async def run():
        return await build_film_response(
            CLOCK, LIVE, JOURNAL, lang="fr", seconds=150, style="written",
            now_ms=NOW_MS, cascade=fake_cascade, want_write=True,
        )

    out = asyncio.run(run())
    assert out["source"] in {"nemotron", "nemotron-super", WRITTEN_SOURCE}
    assert out["hasWritten"] is True
    raw_n = sum(len([s for s in re.split(r"(?<=[.!?…])\s+", c.get("text") or "") if s.strip()]) for c in raw["chapters"])
    out_n = sum(len([s for s in re.split(r"(?<=[.!?…])\s+", c.get("text") or "") if s.strip()]) for c in out["chapters"])
    assert out_n == raw_n


def json_ids(ids):
    import json
    return json.dumps({"ids": ids, "reason": "rules-shaped pick"})


def test_film_cache_hit_skips_second_write():
    raw = _raw()
    events = raw["_events"]
    honest = _honest_written(raw, events)
    calls = {"n": 0}

    async def fake_cascade(system, user, **kw):
        calls["n"] += 1
        if "JSON only" in system:
            return json_ids([e["id"] for e in events]), "nemotron-lightning"
        sents = _sentences_from_user(user)
        if sents:
            return " ".join(sents), "nemotron-super"
        return honest, "nemotron-super"

    async def run():
        a = await build_film_response(
            CLOCK, LIVE, JOURNAL, lang="fr", seconds=150, style="written",
            now_ms=NOW_MS, cascade=fake_cascade, want_write=True,
        )
        n1 = calls["n"]
        b = await build_film_response(
            CLOCK, LIVE, JOURNAL, lang="fr", seconds=150, style="written",
            now_ms=NOW_MS, cascade=fake_cascade, want_write=True,
        )
        return a, b, n1, calls["n"]

    a, b, n1, n2 = asyncio.run(run())
    assert a["chapters"][0]["text"] == b["chapters"][0]["text"]
    assert n2 == n1, "second call served from ns film"
    key = story_cache.film_cache_key(journal_fingerprint(JOURNAL, last_stop_id(JOURNAL, CLOCK["marks"])), "fr", 150)
    assert story_cache.get_film_cached(key)
    assert pearl_store.kv_count("film-story") >= 1


def test_new_stop_changes_fingerprint():
    a = journal_fingerprint(JOURNAL, "stop:Ajaccio")
    extra = {"latest": JOURNAL["latest"] + [
        {"id": "stop:noumea:arrival", "kind": "stop", "t": "2026-09-17T22:48:00Z", "event": "arrival", "name": "Nouméa"},
    ]}
    b = journal_fingerprint(extra, "stop:noumea:arrival")
    assert a != b


def test_http_film_route_raw(monkeypatch):
    from fastapi.testclient import TestClient
    import voyage_api
    from main import app

    monkeypatch.setattr(voyage_api, "_now", lambda: datetime(2026, 9, 19, 2, 0, tzinfo=timezone.utc))
    client = TestClient(app)
    body = _official()
    body["t0"] = OFFICIAL_T0
    client.put("/voyage/official", json=body, headers=PUBLIC)
    import official_store
    official_store.refresh_family("film", force=True)
    r = client.get("/voyage/official/film?lang=fr&seconds=150", headers=PUBLIC)
    assert r.status_code == 200
    data = r.json()
    assert data["source"] == "rules"
    assert data["chapters"]
    assert "Saint-Maur" in data["chapters"][0]["text"]
    assert "15 mai 2026" in data["chapters"][0]["text"]
    assert "2027" not in data["chapters"][0]["text"]
    assert not re.search(r"\bnm\b", " ".join(c.get("text") or "" for c in data["chapters"]))
    assert "targetSeconds" in data
    assert data["chars"] <= FILM_MAX_CHARS
    sea = [c for c in data["chapters"] if is_sea_chapter(c)]
    for ch in sea:
        evs = ch.get("events") or []
        assert evs, f"chapitre de mer sans événement : {ch.get('id')}"
        assert all(e.get("score") in {1, 2, 3} for e in evs)


def test_http_film_route_replay_t0(monkeypatch):
    from fastapi.testclient import TestClient
    import voyage_api
    from main import app

    monkeypatch.setattr(voyage_api, "_now", lambda: datetime(2026, 9, 19, 2, 0, tzinfo=timezone.utc))
    client = TestClient(app)
    body = _official()
    body["t0"] = OFFICIAL_T0
    client.put("/voyage/official", json=body, headers=PUBLIC)
    import official_store
    official_store.refresh_family("film", force=True)
    r = client.get(
        "/voyage/official/film?lang=fr&seconds=150&t0=2025-05-15T08:00:00.000Z",
        headers=PUBLIC,
    )
    assert r.status_code == 200
    text0 = r.json()["chapters"][0]["text"]
    assert "Saint-Maur" in text0
    # Le script stocké est celui du t0 officiel — plus de recalcul à la requête.
    assert "15 mai 2026" in text0


def test_bubble_scores_are_one_two_or_three():
    assert bubble_score({"kind": "stop", "event": "arrival"}) == 3
    assert bubble_score({"kind": "stop", "event": "departure"}) == 3
    assert bubble_score({"kind": "zee", "event": "enter"}) == 2
    assert bubble_score({"kind": "sci"}) == 2
    assert bubble_score({"kind": "amp"}) == 1
    assert bubble_score({"kind": "climo"}) == 1
    assert bubble_score({"kind": "wx", "maxWindKnots": 38}) == 3
    assert bubble_score({"kind": "wx", "hs": 3.2}) == 3
    assert bubble_score({"kind": "wx", "windKnots": 20, "hs": 1.2}) is None
    assert bubble_score({"kind": "wx", "maxWindKnots": 30}, wind_max_kt=28) == 3


def test_official_sea_chapters_have_scored_events():
    plan = _raw()
    sea = [c for c in plan["chapters"] if is_sea_chapter(c)]
    assert sea, "le voyage officiel a des chapitres de mer"
    for ch in sea:
        evs = ch.get("events") or []
        assert evs, f"chapitre de mer sans événement : {ch.get('id')} {ch.get('fromName')} → {ch.get('toName')}"
        for e in evs:
            assert e.get("score") in {1, 2, 3}, e
            assert "charIdx" in e
            assert e.get("kind")
            assert e.get("title") is not None
            assert e.get("fact") is not None


ROUTE_STOPS = ["Saint-Maur", "La Rochelle", "Ajaccio", "Fort-de-France", "Nouméa"]


def _first_index(text: str, needle: str) -> int:
    return text.lower().find(needle.lower())


def _assert_route_order(text: str, label: str) -> None:
    hits = [(n, _first_index(text, n)) for n in ROUTE_STOPS if _first_index(text, n) >= 0]
    assert len(hits) >= 4, f"{label} : escales manquantes ({[n for n, _ in hits]})"
    for (a, ia), (b, ib) in zip(hits, hits[1:]):
        assert ia < ib, f"{label} : {b} avant {a}"


def _assert_departure_arrival_pairs(text: str, lang: str = "fr") -> None:
    import re
    dep_re = (
        r"Berry-Mappemonde leaves .+? for (?:the long crossing to )?(.+?)(?:\s*:|,|\.|$)"
        if lang == "en" else
        r"Berry-Mappemonde quitte .+? pour (?:la longue traversée vers )?(.+?)(?:\s*:|,|\.|$)"
    )
    arr_re = r"Arrival at (.+?) on " if lang == "en" else r"Arrivée à (.+?) le "
    deps = [(m.group(1).strip(), m.start()) for m in re.finditer(dep_re, text, re.I)]
    arrs = [(m.group(1).strip(), m.start()) for m in re.finditer(arr_re, text, re.I)]
    assert len(deps) >= 2, f"départs pour : {[n for n, _ in deps]}"
    assert len(arrs) >= 2, f"arrivées : {[n for n, _ in arrs]}"
    seen = []
    for name, _ in arrs:
        key = norm_stop(name)
        assert key not in seen, f"escale répétée : {name}"
        seen.append(key)
    def _pair_name(name: str) -> str:
        s = re.sub(r"\s+(par la route|by road)\s*$", "", name, flags=re.I)
        s = re.sub(r",\s+(cap au [\w'-]+|heading [\w-]+)\s*$", "", s, flags=re.I)
        return s.strip()

    for name, i in deps:
        nxt = next(((n, j) for n, j in arrs if j > i), None)
        assert nxt, f"pas d’arrivée après départ pour {name}"
        assert norm_stop(_pair_name(nxt[0])) == norm_stop(_pair_name(name)), (
            f"départ pour {name} suivi de arrivée à {nxt[0]}"
        )
    assert not re.search(r"pour Fort-de-France[\s\S]{0,240}(?:Escale à|Arrivée à) Ajaccio", text, re.I)
    assert not re.search(r"for Fort-de-France[\s\S]{0,240}(?:Stopover in|Arrival at) Ajaccio", text, re.I)


def test_dated_marks_merges_ajaccio_aliases():
    extra = CLOCK["marks"] + [
        {"name": "Ajaccio", "nm": 1820, "filmNm": 1942.3, "iso": "2026-05-24T13:00:00Z", "holdHours": 72},
        {"name": "Ajaccio (Corse)", "nm": 9000, "filmNm": 9000, "iso": "2026-07-01T00:00:00Z", "holdHours": 0},
    ]
    dated = dated_marks(extra)
    assert sum(1 for s in dated if "ajaccio" in s["name"].lower()) == 1
    assert norm_stop("Ajaccio (Corse)") == "ajaccio"


def test_dated_marks_keeps_distinct_stops_at_filmnm_zero():
    dated = dated_marks([
        {"name": "Saint-Maur (Berry, Indre)", "nm": 0, "filmNm": 0, "iso": OFFICIAL_T0},
        {"name": "La Rochelle", "nm": 0, "filmNm": 0, "iso": OFFICIAL_T0},
        {"name": "Ajaccio (Corse)", "nm": 1820, "filmNm": 1942, "iso": "2026-05-24T12:51:00Z"},
    ])
    keys = [norm_stop(s["name"]) for s in dated]
    assert "saint-maur" in keys
    assert "la rochelle" in keys
    assert "ajaccio" in keys


def _live_like_clock(lr: dict) -> dict:
    return {
        "t0": OFFICIAL_T0,
        "marks": [CLOCK["marks"][0], lr, *CLOCK["marks"][2:]],
    }


def _assert_no_rochelle_to_ajaccio_skip(blob: str) -> None:
    assert "Arrivée à La Rochelle" in blob, blob[:500]
    assert re.search(r"pour Ajaccio", blob), blob[:500]
    assert blob.find("Arrivée à La Rochelle") < blob.find("pour Ajaccio"), blob[:800]
    assert not re.search(r"pour La Rochelle[^.]*\.\s*Arrivée à Ajaccio", blob)
    _assert_departure_arrival_pairs(blob, "fr")


def test_live_like_clock_pairs_rochelle_before_ajaccio():
    """La Rochelle iso = T0 ou filmNm 0 : Arrivée à La Rochelle avant départ vers Ajaccio."""
    variants = (
        {"name": "La Rochelle", "nm": 0, "filmNm": 0, "iso": OFFICIAL_T0, "holdHours": 72, "lat": 46.15, "lon": -1.16},
        {"name": "La Rochelle", "nm": 0, "filmNm": 122, "iso": OFFICIAL_T0, "holdHours": 72, "lat": 46.15, "lon": -1.16},
    )
    for lr in variants:
        clock = _live_like_clock(lr)
        for journal in (JOURNAL, {**JOURNAL, **MOMENTS}):
            plan = build_raw_script(clock, clock["marks"], LIVE, journal, lang="fr", seconds=0, now_ms=NOW_MS)
            blob = _script_blob(plan)
            _assert_no_rochelle_to_ajaccio_skip(blob)
            ch0 = plan["chapters"][0]["text"]
            assert re.search(r"par la route jusqu|quitte Saint-Maur|quitté Saint-Maur", ch0, re.I), ch0
            assert re.search(r"Arrivée à La Rochelle", ch0), ch0


def test_chapter_iso_tb_after_ta():
    """Plancher 1 s : après _iso, chaque chapitre a tB > tA (filmPlan garde le ch. 0)."""
    from film_script import _iso, _ms

    plan = _raw()
    assert plan["chapters"]
    for ch in plan["chapters"]:
        ta, tb = _ms(ch["tA"]), _ms(ch["tB"])
        assert ta is not None and tb is not None
        assert tb > ta, (ch.get("id"), ch["tA"], ch["tB"])
        assert _iso(ta) != _iso(tb), (ch.get("id"), ch["tA"], ch["tB"])

    lr = {"name": "La Rochelle", "nm": 0, "filmNm": 0, "iso": OFFICIAL_T0, "holdHours": 72}
    live_plan = build_raw_script(
        _live_like_clock(lr), _live_like_clock(lr)["marks"], LIVE, JOURNAL,
        lang="fr", seconds=150, now_ms=NOW_MS,
    )
    assert live_plan["chapters"]
    assert live_plan["chapters"][0]["id"] == "leg-0"
    for ch in live_plan["chapters"]:
        ta, tb = _ms(ch["tA"]), _ms(ch["tB"])
        assert tb > ta, (ch.get("id"), ch["tA"], ch["tB"])
        assert ch["tA"] != ch["tB"]


def test_official_route_order_no_repeat_departure_then_arrival():
    fr = build_raw_script(CLOCK, CLOCK["marks"], LIVE, JOURNAL, lang="fr", seconds=0, now_ms=NOW_MS)
    blob_fr = " ".join(c.get("text") or "" for c in fr["chapters"])
    _assert_route_order(blob_fr, "film FR")
    _assert_departure_arrival_pairs(blob_fr, "fr")
    for ch in fr["chapters"]:
        text = ch.get("text") or ""
        if "Berry-Mappemonde quitte" in text and "Arrivée à" in text:
            import re
            dep = re.search(
                r"Berry-Mappemonde quitte .+? pour (?:la longue traversée vers )?(.+?)(?:\s*:|,|\.|$)",
                text,
            )
            arr = re.search(r"Arrivée à (.+?) le ", text)
            assert dep and arr
            dep_name = re.sub(r",\s+(cap au [\w'-]+|heading [\w-]+)\s*$", "", dep.group(1), flags=re.I)
            assert norm_stop(dep_name) == norm_stop(arr.group(1)), ch.get("id")

    en = build_raw_script(CLOCK, CLOCK["marks"], LIVE, JOURNAL, lang="en", seconds=0, now_ms=NOW_MS)
    blob_en = " ".join(c.get("text") or "" for c in en["chapters"])
    _assert_route_order(blob_en, "film EN")
    _assert_departure_arrival_pairs(blob_en, "en")


SIM_CLOCK = {
    "t0": "2027-04-25T08:00:00Z",
    "marks": [
        {"name": "La Rochelle", "nm": 0, "filmNm": 122, "iso": "2027-04-25T08:00:00Z", "holdHours": 72, "lat": 46.15, "lon": -1.16},
        {"name": "Ajaccio (Corse)", "nm": 1820, "filmNm": 1942, "iso": "2027-05-04T12:00:00Z", "holdHours": 72, "lat": 41.9, "lon": 8.7},
        {"name": "Fort-de-France (Martinique)", "nm": 6973, "filmNm": 7095, "iso": "2027-06-02T08:00:00Z", "holdHours": 72, "lat": 14.6, "lon": -61.0},
    ],
}


def _script_blob(plan: dict) -> str:
    return " ".join(c.get("text") or "" for c in (plan.get("chapters") or []))


def test_official_script_ignores_simulation_clock():
    plan = build_raw_script(SIM_CLOCK, SIM_CLOCK["marks"], LIVE, JOURNAL, lang="fr", seconds=150, now_ms=NOW_MS)
    assert plan["chapters"]
    text0 = plan["chapters"][0]["text"]
    assert "Saint-Maur" in text0
    assert "15 mai 2026" in text0
    assert "La Rochelle" in text0
    assert "2027" not in text0
    assert "25 avril" not in text0
    assert not re.search(r"a quitté La Rochelle", text0, re.I)
    blob = _script_blob(plan)
    assert not re.search(r"\bnm\b", blob), blob


def test_no_bare_nm_in_official_script():
    fr = _raw()
    en = build_raw_script(CLOCK, CLOCK["marks"], LIVE, JOURNAL, lang="en", seconds=150, now_ms=NOW_MS)
    blob_fr = _script_blob(fr)
    blob_en = _script_blob(en)
    assert "Saint-Maur" in fr["chapters"][0]["text"]
    assert "15 mai 2026" in fr["chapters"][0]["text"]
    assert not re.search(r"\bnm\b", blob_fr), blob_fr
    assert not re.search(r"\bnm\b", blob_en), blob_en
    if re.search(r"\d[\d\s]*", blob_fr) and "quitte" in blob_fr.lower():
        assert "milles" in blob_fr or "Aujourd" in blob_fr
    assert "miles" in blob_en or "Today" in blob_en or "left" in blob_en.lower() or "leaves" in blob_en.lower()


def test_official_dated_stops_pins_saint_maur():
    stops = official_dated_stops(SIM_CLOCK["marks"], SIM_CLOCK)
    assert is_saint_or_first(stops)
    assert stops[0]["iso"].startswith("2026-05-15")


def test_official_dated_stops_pins_first_rochelle_not_return():
    """La Rochelle départ (filmNm 122) ne doit pas hériter de l'iso du retour."""
    marks = [
        {"name": "Saint-Maur (Berry, Indre)", "nm": 0, "filmNm": 0, "iso": None},
        {"name": "La Rochelle", "nm": 122, "filmNm": 122, "iso": "2027-05-10T02:40:39Z", "holdHours": 72},
        {"name": "Ajaccio (Corse)", "nm": 1942, "filmNm": 1942, "iso": "2026-05-30T13:56:06Z", "holdHours": 72},
        {"name": "Fort-de-France (Martinique)", "nm": 7095, "filmNm": 7095, "iso": "2026-07-10T23:11:45Z", "holdHours": 72},
    ]
    stops = official_dated_stops(marks)
    assert is_saint_or_first(stops)
    assert "rochelle" in stops[1]["name"].lower()
    assert stops[1]["iso"].startswith("2026-05-15")
    assert "ajaccio" in stops[2]["name"].lower()
    clock = {"t0": OFFICIAL_T0, "marks": marks}
    plan = build_raw_script(clock, marks, LIVE, JOURNAL, lang="fr", seconds=0, now_ms=NOW_MS)
    blob = _script_blob(plan)
    _assert_no_rochelle_to_ajaccio_skip(blob)


def is_saint_or_first(stops):
    assert stops
    assert "saint-maur" in stops[0]["name"].lower().replace(" ", "-")
    return True


def test_http_film_route_en(monkeypatch):
    from fastapi.testclient import TestClient
    import voyage_api
    from main import app

    monkeypatch.setattr(voyage_api, "_now", lambda: datetime(2026, 9, 19, 2, 0, tzinfo=timezone.utc))
    client = TestClient(app)
    body = _official()
    body["t0"] = OFFICIAL_T0
    client.put("/voyage/official", json=body, headers=PUBLIC)
    import official_store
    official_store.refresh_family("film", force=True)
    r = client.get("/voyage/official/film?lang=en&seconds=150", headers=PUBLIC)
    assert r.status_code == 200
    data = r.json()
    assert data["chapters"]
    text = data["chapters"][0]["text"]
    blob = _script_blob(data)
    if "Saint-Maur" in text:
        assert ("left" in text.lower() or "departed" in text.lower() or "leaves" in text.lower())
    # Chapitre 0 seul : le blob intégral mélange d'autres escales (La Rochelle, etc.).
    deps = list(re.finditer(r"departure for (.+?)(?:\s*:|\.|$)", text, re.I))
    arrs = list(re.finditer(r"Arrival at (.+?) on ", text))
    if len(deps) >= 2:
        _assert_departure_arrival_pairs(text, "en")
    elif deps and arrs:
        assert norm_stop(deps[0].group(1)) == norm_stop(arrs[0].group(1))
    if len(list(re.finditer(r"departure for ", blob, re.I))) >= 2:
        _assert_departure_arrival_pairs(blob, "en")


MOMENTS = {
    "moments": [
        {"seq": 0, "t": "2026-05-15T08:00:00Z", "signature": "s0", "legIdx": 0, "changes": [],
         "moment": {"leg": {"from": "Saint-Maur", "to": "La Rochelle"}}},
        {"seq": 1, "t": "2026-05-15T11:30:00Z", "signature": "s1", "legIdx": 0, "changes": [
            {"kind": "approche", "score": 3, "title": "La Rochelle", "fact": "Approche de La Rochelle, reste 12 milles nautiques."},
        ], "moment": {"leg": {"from": "Saint-Maur", "to": "La Rochelle"}}},
        {"seq": 2, "t": "2026-05-15T12:00:00Z", "signature": "s2", "legIdx": 0, "changes": [
            {"kind": "escale", "score": 3, "title": "Arrivée à La Rochelle", "fact": "Saint-Maur → La Rochelle"},
        ], "moment": {"leg": {"from": "Saint-Maur", "to": "La Rochelle"}}},
        {"seq": 3, "t": "2026-05-17T15:00:00Z", "signature": "s3", "legIdx": 1, "changes": [
            {"kind": "zee-enter", "score": 2, "title": "Spanish Exclusive Economic Zone", "fact": "Spanish Exclusive Economic Zone"},
        ], "moment": {"leg": {"from": "La Rochelle", "to": "Ajaccio (Corse)", "headingDeg": 246}}},
        {"seq": 4, "t": "2026-05-22T06:00:00Z", "signature": "s4", "legIdx": 1, "changes": [
            {"kind": "alert-on", "score": 3, "title": "Vent 38 kn", "fact": "Vent 38 kn attendu pendant 6 heures."},
        ], "moment": {"leg": {"from": "La Rochelle", "to": "Ajaccio (Corse)"}}},
        {"seq": 5, "t": "2026-05-24T10:00:00Z", "signature": "s5", "legIdx": 1, "changes": [
            {"kind": "approche", "score": 3, "title": "Ajaccio", "fact": "Approche de Ajaccio, reste 40 milles nautiques."},
        ], "moment": {"leg": {"from": "La Rochelle", "to": "Ajaccio (Corse)"}}},
        {"seq": 6, "t": "2026-05-24T12:51:00Z", "signature": "s6", "legIdx": 1, "changes": [
            {"kind": "escale", "score": 3, "title": "Arrivée à Ajaccio", "fact": "La Rochelle → Ajaccio"},
        ], "moment": {"leg": {"from": "La Rochelle", "to": "Ajaccio (Corse)"}}},
        {"seq": 7, "t": "2026-06-10T06:00:00Z", "signature": "s7", "legIdx": 2, "changes": [
            {"kind": "station", "score": 2, "title": "PIRATA", "fact": "Station PIRATA à 6 milles nautiques."},
        ], "moment": {"leg": {"from": "Ajaccio (Corse)", "to": "Fort-de-France (Martinique)"}}},
        {"seq": 8, "t": "2026-06-22T12:00:00Z", "signature": "s8", "legIdx": 2, "changes": [
            {"kind": "approche", "score": 3, "title": "Fort-de-France", "fact": "Approche de Fort-de-France, reste 90 milles nautiques."},
        ], "moment": {"leg": {"from": "Ajaccio (Corse)", "to": "Fort-de-France (Martinique)"}}},
        {"seq": 9, "t": "2026-06-23T08:34:00Z", "signature": "s9", "legIdx": 2, "changes": [
            {"kind": "escale", "score": 3, "title": "Arrivée à Fort-de-France", "fact": "Ajaccio → Fort-de-France"},
        ], "moment": {"leg": {"from": "Ajaccio (Corse)", "to": "Fort-de-France (Martinique)"}}},
        {"seq": 10, "t": "2026-08-01T06:00:00Z", "signature": "s10", "legIdx": 3, "changes": [
            {"kind": "amp", "score": 1, "title": "Cabrera", "fact": "Cabrera (8 milles nautiques)"},
        ], "moment": {"leg": {"from": "Fort-de-France (Martinique)", "to": "Nouméa (Nouvelle-Calédonie)"}}},
        {"seq": 11, "t": "2026-09-17T18:00:00Z", "signature": "s11", "legIdx": 3, "changes": [
            {"kind": "approche", "score": 3, "title": "Nouméa", "fact": "Approche de Nouméa, reste 70 milles nautiques."},
        ], "moment": {"leg": {"from": "Fort-de-France (Martinique)", "to": "Nouméa (Nouvelle-Calédonie)"}}},
        {"seq": 12, "t": "2026-09-17T22:48:00Z", "signature": "s12", "legIdx": 3, "changes": [
            {"kind": "escale", "score": 3, "title": "Arrivée à Nouméa", "fact": "Fort-de-France → Nouméa"},
        ], "moment": {"leg": {"from": "Fort-de-France (Martinique)", "to": "Nouméa (Nouvelle-Calédonie)"}}},
    ],
}


def _moments_raw(lang="fr"):
    return build_raw_script(CLOCK, CLOCK["marks"], LIVE, {**JOURNAL, **MOMENTS}, lang=lang, seconds=150, now_ms=NOW_MS)


def test_allocate_budgets_floor_and_total():
    budgets = allocate_chapter_budgets([1, 9, 30, 86], FILM_BUDGET_CHARS, 120)
    assert len(budgets) == 4
    assert all(b >= 120 for b in budgets)
    assert sum(budgets) == FILM_BUDGET_CHARS
    assert budgets[-1] > budgets[0]


FILLER = (
    "Le ciel reste haut", "La mer porte le bateau", "La route tient le cap",
    "Le vent reste le vent", "The sky stays high", "The sea carries the boat",
    "The course holds", "The wind stays the wind", "La mer reste la mer",
    "le vent reste le vent, la route reste la route",
)


def _assert_no_filler(blob: str) -> None:
    for phrase in FILLER:
        assert phrase not in blob, phrase


def test_moments_raw_no_atmos_budget_flag():
    plan = _moments_raw()
    blob = " ".join(c.get("text") or "" for c in plan["chapters"])
    assert plan["targetSeconds"] == 150
    assert plan["chars"] > 0
    assert plan["chars"] <= FILM_MAX_CHARS
    _assert_no_filler(blob)
    assert not re.search(r"\bnm\b", blob)


def test_moments_chapter_one_sentence_max_three_changes():
    plan = _moments_raw()
    assert plan["chapters"]
    for ch in plan["chapters"]:
        text = (ch.get("text") or "").strip()
        assert text
        assert re.search(r"[.!?]", text)
        named = {"zee", "coast"}
        others = [
            e for e in (ch.get("events") or [])
            if e.get("kind") not in named and not str(e.get("id") or "").startswith("stop:")
        ]
        assert len(others) <= FILM_CHAPTER_MAX_CHANGES


def test_moments_anchors_follow_the_route_chronologically():
    """27 sept. : chaque phrase gardée porte l'instant du trajet dont elle parle (ancres), croissant,
    borné au chapitre ; « approche de Fort-de-France » est ancrée à l'instant de l'approche."""
    plan = _moments_raw()
    seen_any = False
    for ch in plan["chapters"]:
        anchors = ch.get("anchors") or []
        t_a, t_b = _parse_iso_ms(ch["tA"]), _parse_iso_ms(ch["tB"])
        last_idx, last_t = -1, None
        for a in anchors:
            seen_any = True
            assert isinstance(a["charIdx"], int) and 0 <= a["charIdx"] < len(ch["text"])
            assert a["charIdx"] > last_idx, "ancres triées et sans doublon"
            t = _parse_iso_ms(a["t"])
            assert t_a <= t <= t_b, "ancre bornée au chapitre"
            assert last_t is None or t >= last_t, "chronologie stricte"
            last_idx, last_t = a["charIdx"], t
        text = ch["text"]
        name_at = text.find("Fort-de-France")
        if "approche" in text.casefold() and name_at >= 0:
            expect = max(0, name_at - FILM_VOICE_LOOKAHEAD_CHARS)
            hit = [a for a in anchors if abs(int(a["charIdx"]) - expect) <= 16]
            if not hit:
                hit = [a for a in anchors if "Fort-de-France" in text[max(0, int(a["charIdx"]) - 8): int(a["charIdx"]) + 40]]
            assert hit, "la phrase d'approche a son ancre au nom"
            assert _parse_iso_ms(hit[0]["t"]) == _parse_iso_ms("2026-06-22T12:00:00Z")
    assert seen_any


def _parse_iso_ms(value: str) -> int:
    from datetime import datetime, timezone
    return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc).timestamp() * 1000)


def test_chapter_anchors_unit_sorted_bounded_deduped():
    text = "Départ vers Ajaccio. Le 31 mai, approche d’Ajaccio. Arrivée le 1er juin."
    anchored = [
        ("Arrivée le 1er juin.", 5_000),      # après tB → borné
        ("Le 31 mai, approche d’Ajaccio.", 900),
        ("Départ vers Ajaccio.", -50),        # avant tA → borné
        ("Phrase coupée par le budget.", 500),  # absente du texte → ignorée
        ("Le 31 mai, approche d’Ajaccio.", 950),  # même position → une seule ancre
    ]
    out = chapter_anchors(text, anchored, 0, 2_000, "fr")
    idxs = [a["charIdx"] for a in out]
    assert idxs == sorted(idxs)
    assert idxs[0] == 0
    approach = text.find("approche")
    ajaccio = text.find("Ajaccio", approach)
    assert any(abs(i - max(0, ajaccio - FILM_VOICE_LOOKAHEAD_CHARS)) <= 4 for i in idxs)
    arrive = text.find("Arrivée")
    last = text.rfind("juin")
    assert any(i >= arrive for i in idxs)
    assert any(abs(i - max(arrive, last - FILM_VOICE_LOOKAHEAD_CHARS)) <= 8 for i in idxs)
    assert [a["t"] for a in out][-1] == "1970-01-01T00:00:02Z"
    times = [_parse_iso_ms(a["t"]) for a in out]
    assert times == sorted(times)
    assert times[0] == 0
    assert times[-1] == 2_000


def test_moments_arrival_each_stop_route_order():
    plan = build_raw_script(
        CLOCK, CLOCK["marks"], LIVE, {**JOURNAL, **MOMENTS},
        lang="fr", seconds=0, now_ms=NOW_MS,
    )
    blob = " ".join(c.get("text") or "" for c in plan["chapters"])
    _assert_route_order(blob, "journal FR")
    _assert_departure_arrival_pairs(blob, "fr")
    for name in ("La Rochelle", "Ajaccio", "Fort-de-France", "Nouméa"):
        assert re.search(rf"Arrivée à {name}", blob), name


def test_moments_connectors_differ():
    plan = build_raw_script(
        CLOCK, CLOCK["marks"], LIVE, {**JOURNAL, **MOMENTS},
        lang="fr", seconds=0, now_ms=NOW_MS,
    )
    blob = _script_blob(plan)
    assert "À la jambe suivante" not in blob
    shapes = []
    for ch in plan["chapters"]:
        text = ch.get("text") or ""
        if "longue traversée" in text:
            shapes.append("long")
        elif "d'île en île" in text:
            shapes.append("hop")
        elif "dernière étape" in text:
            shapes.append("last")
        elif "Berry-Mappemonde quitte" in text:
            shapes.append("open")
    assert len(shapes) >= 2


def test_moments_approche_bubble_title_is_stop():
    plan = _moments_raw()
    titles = []
    for ch in plan["chapters"]:
        for ev in ch.get("events") or []:
            eid = str(ev.get("id") or "")
            if "approche" in eid or ev.get("kind") == "stop":
                titles.append(ev.get("title"))
            if str(ev.get("title") or "") in {"La Rochelle", "Ajaccio", "Fort-de-France", "Nouméa"}:
                titles.append(ev.get("title"))
    assert "Ajaccio" in titles or any(t and "Ajaccio" in str(t) for t in titles)
    for ch in plan["chapters"]:
        dest = (ch.get("toName") or "").split("(")[0].strip()
        if not dest:
            continue
        approach = next(
            (e for e in (ch.get("events") or []) if dest.split()[0] in str(e.get("title") or "")),
            None,
        )
        if approach:
            assert dest.split()[0] in (approach.get("title") or "")


def test_moments_short_sentences_no_cut():
    plan = _moments_raw()
    for ch in plan["chapters"]:
        text = ch.get("text") or ""
        assert text.endswith((".", "!", "?", "…"))
        for sent in re.split(r"(?<=[.!?…])\s+", text):
            if sent.strip():
                assert sent.strip()[-1] in ".!?…"


def test_select_chapter_changes_caps_at_three():
    changes = [
        {"id": "a", "kind": "escale", "score": 3, "tMs": 1, "title": "Arrivée à Ajaccio", "fact": "x"},
        {"id": "b", "kind": "approche", "score": 3, "tMs": 2, "title": "Ajaccio", "fact": "y"},
        {"id": "c", "kind": "alert-on", "score": 3, "tMs": 3, "title": "Vent", "fact": "38 kn"},
        {"id": "d", "kind": "station", "score": 2, "tMs": 4, "title": "PIRATA", "fact": "z"},
        {"id": "e", "kind": "amp", "score": 1, "tMs": 5, "title": "AMP", "fact": "w"},
    ]
    picked = select_chapter_changes(changes, 0, 10)
    assert len(picked) <= FILM_CHAPTER_MAX_CHANGES   # 4 depuis le 27 sept. (arrivée, fait de mer, marina d'escale, approche)
    kinds = {c["kind"] for c in picked}
    assert "escale" in kinds
    assert "approche" in kinds or "alert-on" in kinds
    assert [c["tMs"] for c in picked] == sorted(c["tMs"] for c in picked)   # dits dans l'ordre du voyage


def test_written_no_number_outside_facts():
    raw = _moments_raw()
    events = raw.get("_events") or []
    facts = film_facts(raw, events)
    cheat = "Le vent atteindra 99 nœuds demain."
    ok, _, dropped = written_is_valid(cheat, facts, [])
    assert dropped >= 1
    assert ok is False


def test_film_written_served_from_cache_without_llm():
    raw = _raw()
    events = raw["_events"]
    honest = _honest_written(raw, events)
    calls = {"n": 0}

    async def fake_cascade(system, user, **kw):
        calls["n"] += 1
        if "JSON only" in system:
            return json_ids([e["id"] for e in events]), "nemotron-lightning"
        sents = _sentences_from_user(user)
        if sents:
            return " ".join(s.replace("quitte", "laisse", 1) if "quitte" in s else s for s in sents), "nemotron-super"
        return honest, "nemotron-super"

    async def boom(*_a, **_k):
        calls["n"] += 1
        raise AssertionError("LLM au clic")

    async def run():
        await build_film_response(
            CLOCK, LIVE, JOURNAL, lang="fr", seconds=150, style="written",
            now_ms=NOW_MS, cascade=fake_cascade, want_write=True,
        )
        n1 = calls["n"]
        out = await build_film_response(
            CLOCK, LIVE, JOURNAL, lang="fr", seconds=150, style="written",
            now_ms=NOW_MS, cascade=boom, want_write=False,
        )
        return n1, calls["n"], out

    n1, n2, out = asyncio.run(run())
    assert n1 >= 1
    assert n2 == n1
    assert out["hasWritten"] is True
    assert out["style"] == "written"


def _rich_journal():
    extra = [
        {"seq": 13, "t": "2026-05-15T11:00:00Z", "signature": "marina", "legIdx": 0, "changes": [],
         "moment": {"leg": {"from": "Saint-Maur", "to": "La Rochelle"},
                    "around": [{"kind": "marina", "title": "Les Minimes", "fact": "Les Minimes (2 nm)",
                                "lat": 46.14, "lon": -1.17}]}},
        {"seq": 14, "t": "2026-05-15T12:10:00Z", "signature": "port", "legIdx": 1, "changes": [
            {"kind": "port", "score": 2, "title": "La Rochelle", "fact": "La Rochelle"},
        ], "moment": {"leg": {"from": "La Rochelle", "to": "Ajaccio (Corse)"}}},
        {"seq": 15, "t": "2026-07-10T06:00:00Z", "signature": "irma", "legIdx": 3, "changes": [
            {"kind": "cyclone", "score": 3, "title": "Irma", "fact": "Irma (2017)"},
        ], "moment": {"leg": {"from": "Fort-de-France (Martinique)", "to": "Nouméa (Nouvelle-Calédonie)"}}},
        {"seq": 16, "t": "2026-06-23T08:00:00Z", "signature": "culture", "legIdx": 2, "changes": [
            {"kind": "culture", "score": 1, "title": "Fort Saint-Louis", "fact": "Fort Saint-Louis."},
        ], "moment": {"leg": {"from": "Ajaccio (Corse)", "to": "Fort-de-France (Martinique)"}}},
        {"seq": 17, "t": "2026-07-11T06:00:00Z", "signature": "nameless", "legIdx": 3, "changes": [
            {"kind": "cyclone", "score": 1, "title": "Cyclone", "fact": "3 traces de cyclone ce mois-ci."},
        ], "moment": {"leg": {"from": "Fort-de-France (Martinique)", "to": "Nouméa (Nouvelle-Calédonie)"}}},
    ]
    return {**JOURNAL, "moments": MOMENTS["moments"] + extra}


def _rich_raw(seconds=0, lang="fr"):
    return build_raw_script(
        CLOCK, CLOCK["marks"], LIVE, _rich_journal(), lang=lang, seconds=seconds, now_ms=NOW_MS,
    )


def test_official_script_has_no_atmos_or_pad():
    for plan in (_raw(), _moments_raw(), _rich_raw(0), _rich_raw(150)):
        blob = " ".join(c.get("text") or "" for c in plan["chapters"])
        _assert_no_filler(blob)


def test_rich_moments_without_budget_cites_each_type():
    plan = _rich_raw(0)
    blob = " ".join(c.get("text") or "" for c in plan["chapters"])
    assert plan["targetSeconds"] == 0
    assert "Les Minimes" in blob
    assert "à portée de" not in blob
    assert re.search(r"amarré à la marina Les Minimes|marina Les Minimes", blob)
    assert re.search(r"longe La Rochelle|devant La Rochelle", blob)
    assert re.search(r"aire marine protégée(?: :| ) Cabrera|l'aire marine protégée Cabrera", blob)
    assert re.search(r"une bouée", blob)
    assert "PIRATA" not in blob
    assert "stations scientifiques croisées" not in blob
    assert "Irma" in blob and "2017" in blob
    assert "Fort Saint-Louis" in blob
    assert "traces de cyclone ce mois-ci" not in blob
    assert "marina croisée" not in blob
    assert "station croisée : Station croisée" not in blob
    _assert_no_filler(blob)
    _assert_departure_arrival_pairs(blob, "fr")
    _assert_route_order(blob, "journal riche FR")
    assert not re.search(r"\bnm\b", blob)
    assert not re.search(r"\d+[.,]\d{1,2}(?!\d)", blob)
    assert "1 820 milles" in blob or "1820 milles" in blob


def test_budget_150_reached_and_no_decimals():
    plan = _rich_raw(150)
    blob = " ".join(c.get("text") or "" for c in plan["chapters"])
    assert plan["targetSeconds"] == 150
    _assert_no_filler(blob)
    assert not re.search(r"\d+[.,]\d{1,2}(?!\d)", blob)
    assert not re.search(r"\bnm\b", blob)


def test_spoken_distances_rounded_no_abbrev():
    assert _nm_label(1820.4, "fr") == "1 820 milles nautiques"
    assert _nm_label(1, "fr") == "1 mille nautique"
    spoken = speak_film_text("Approche, reste 12.4 nm.", "fr")
    assert "nm" not in spoken
    assert "12.4" not in spoken
    assert "12 milles nautiques" in spoken


def test_nameless_cyclone_is_silence():
    assert cyclone_name_year({"title": "Cyclone", "fact": "3 traces de cyclone ce mois-ci."}) == ("", "")
    assert cyclone_name_year({"title": "Irma", "fact": "Irma (2017)"}) == ("Irma", "2017")
    assert change_sentence({"kind": "cyclone", "title": "Cyclone", "fact": "3 traces de cyclone ce mois-ci."}, "fr") == ""


REVIEW_GIBRALTAR = {
    "legs": [
        {
            "from": "Ajaccio (Corse)",
            "to": "Fort-de-France (Martinique)",
            "antiShipping": {"score": 0.4, "lanes": ["Gibraltar"]},
            "season": {"galePct": 22, "cyclones": 3, "cells": 4, "missing": 0},
            "flags": [{"kind": "formalities", "names": ["Espagne"]}],
        }
    ]
}


def test_review_sentences_facts_only():
    assert review_sentences(None) == []
    assert review_sentences({}) == []
    assert review_sentences({"from": "Ajaccio", "to": "Fort-de-France"}) == []
    bits = review_sentences(REVIEW_GIBRALTAR["legs"][0], "fr")
    assert any("Gibraltar" in s for s in bits)
    assert any("Saison cyclonique" in s for s in bits)
    assert any("Coup de vent" in s and "22" in s for s in bits)
    assert not any("À surveiller" in s or s == "Alerte." or s.startswith("Couloirs") for s in bits)
    assert any("passe par" in s for s in bits)
    assert review_leg_for_chapter(REVIEW_GIBRALTAR, "Ajaccio", "Fort-de-France")
    assert review_leg_for_chapter(REVIEW_GIBRALTAR, "La Rochelle", "Ajaccio") is None


def test_review_lane_named_in_correct_chapter():
    plan = build_raw_script(
        CLOCK, CLOCK["marks"], LIVE, {**JOURNAL, **MOMENTS},
        lang="fr", seconds=0, now_ms=NOW_MS, review=REVIEW_GIBRALTAR,
    )
    hit = [c for c in plan["chapters"] if "Gibraltar" in (c.get("text") or "")]
    assert len(hit) == 1, [c.get("fromName") for c in plan["chapters"]]
    ch = hit[0]
    assert "Ajaccio" in (ch.get("fromName") or "")
    assert "Fort-de-France" in (ch.get("toName") or "")
    assert "Saison cyclonique" in ch["text"]
    assert "Coup de vent" in ch["text"]
    assert "22" in ch["text"]
    for c in plan["chapters"]:
        if c is not ch:
            assert "Gibraltar" not in (c.get("text") or "")
    _assert_no_filler(" ".join(c.get("text") or "" for c in plan["chapters"]))


def test_review_lane_named_without_moments_journal():
    """Sans moments, _compose doit encore citer le couloir."""
    plan = build_raw_script(
        CLOCK, CLOCK["marks"], LIVE, JOURNAL,
        lang="fr", seconds=0, now_ms=NOW_MS, review=REVIEW_GIBRALTAR,
    )
    hit = [c for c in plan["chapters"] if "Gibraltar" in (c.get("text") or "")]
    assert len(hit) == 1, [c.get("fromName") for c in plan["chapters"]]
    assert "Ajaccio" in (hit[0].get("fromName") or "")
    assert "Fort-de-France" in (hit[0].get("toName") or "")
    _assert_no_filler(" ".join(c.get("text") or "" for c in plan["chapters"]))


def test_warm_film_story_passes_review_without_clock(monkeypatch):
    """Le préchauffe envoie review_official à build_film_response."""
    import film_script
    import voyage_store

    voy = {
        "voyageId": "seed-no-clock",
        "t0": OFFICIAL_T0,
        "marks": [
            {"name": "Ajaccio (Corse)", "nm": 1820, "filmNm": 1942},
            {"name": "Fort-de-France (Martinique)", "nm": 6973, "filmNm": 7095},
        ],
        "points": [
            {"lat": 41.92, "lon": 8.74, "cumNm": 1820},
            {"lat": 36.05, "lon": -5.6, "cumNm": 2500},
            {"lat": 14.59, "lon": -61.07, "cumNm": 6973},
        ],
    }
    captured: list = []
    captured_kw: list = []

    async def fake_build(*_a, **kw):
        captured.append(kw.get("review"))
        captured_kw.append(kw)
        return {"hasWritten": False, "chars": 0, "source": "rules"}

    monkeypatch.setattr(film_script, "build_film_response", fake_build)
    monkeypatch.setattr(voyage_store, "load_voyage", lambda _vid: voy)
    monkeypatch.setattr("voyage_api._climo_clock", lambda _v: {
        "t0": OFFICIAL_T0, "vertices": [], "marks": voy["marks"],
    })
    out = asyncio.run(warm_film_story("seed-no-clock", langs=("fr",)))
    assert out["status"] == "ready"
    assert captured_kw and captured_kw[0].get("want_write") is False
    assert captured and captured[0] is not None
    legs = (captured[0] or {}).get("legs") or []
    assert any("Ajaccio" in (leg.get("from") or "") and "Fort-de-France" in (leg.get("to") or "") for leg in legs)
    pack = next(
        (leg.get("antiShipping") or {}) for leg in legs
        if "Ajaccio" in (leg.get("from") or "")
    )
    assert "Gibraltar" in (pack.get("lanes") or [])


def test_review_unknown_fields_are_silence():
    empty = {"legs": [{"from": "Ajaccio (Corse)", "to": "Fort-de-France (Martinique)"}]}
    plan = build_raw_script(
        CLOCK, CLOCK["marks"], LIVE, {**JOURNAL, **MOMENTS},
        lang="fr", seconds=0, now_ms=NOW_MS, review=empty,
    )
    blob = " ".join(c.get("text") or "" for c in plan["chapters"])
    assert "Gibraltar" not in blob
    assert "Saison cyclonique" not in blob
    assert "Couloirs" not in blob
    assert "À surveiller" not in blob
    _assert_no_filler(blob)


def test_select_chapter_changes_unlimited_without_budget():
    changes = [
        {"id": "a", "kind": "escale", "score": 3, "tMs": 1, "title": "Arrivée à Ajaccio", "fact": "x"},
        {"id": "b", "kind": "approche", "score": 3, "tMs": 2, "title": "Ajaccio", "fact": "y"},
        {"id": "c", "kind": "alert-on", "score": 3, "tMs": 3, "title": "Vent", "fact": "38 kn"},
        {"id": "d", "kind": "station", "score": 2, "tMs": 4, "title": "PIRATA", "fact": "z"},
        {"id": "e", "kind": "amp", "score": 1, "tMs": 5, "title": "Cabrera", "fact": "Cabrera"},
        {"id": "f", "kind": "marina", "score": 2, "tMs": 6, "title": "Les Minimes", "fact": "Les Minimes"},
        {"id": "g", "kind": "cyclone", "score": 3, "tMs": 7, "title": "Irma", "fact": "Irma (2017)"},
        {"id": "h", "kind": "culture", "score": 1, "tMs": 8, "title": "Fort Saint-Louis", "fact": "Fort Saint-Louis."},
        {"id": "i", "kind": "marina", "score": 2, "tMs": 9, "title": "Les Minimes", "fact": "Les Minimes encore"},
        {"id": "j", "kind": "station", "score": 2, "tMs": 10, "title": "Station croisée", "fact": "Station croisée"},
    ]
    picked = select_chapter_changes(changes, 0, 10, budget=False)
    names = [c.get("title") for c in picked]
    assert names.count("Les Minimes") == 1
    assert not any(
        (c.get("title") or "").casefold() == "station croisée" for c in picked
    )
    assert {c["kind"] for c in picked} >= {"marina", "cyclone", "culture", "amp", "station"}


RE7_CLOCK = {
    "t0": OFFICIAL_T0,
    "marks": [
        {"name": "Saint-Maur (Berry, Indre)", "nm": 0, "filmNm": 0, "iso": "2026-05-15T08:00:00Z", "holdHours": 0, "lat": 46.8, "lon": 1.6},
        {"name": "La Rochelle", "nm": 122, "filmNm": 122, "iso": "2026-05-15T12:00:00Z", "holdHours": 72, "lat": 46.15, "lon": -1.16},
        {"name": "Cayenne (Guyane)", "nm": 4000, "filmNm": 4000, "iso": "2026-07-01T08:00:00Z", "holdHours": 24, "lat": 4.9, "lon": -52.3},
        {"name": "Halifax (Nouvelle-Écosse)", "nm": 4000, "filmNm": 4100, "iso": "2026-07-02T08:00:00Z", "holdHours": 24, "lat": 44.6, "lon": -63.6},
        {"name": "Nouméa (Nouvelle-Calédonie)", "nm": 19055, "filmNm": 19177, "iso": "2026-09-17T22:48:00Z", "holdHours": 72, "lat": -22.2, "lon": 166.4},
    ],
}
RE7_LIVE = {
    "filmNm": 19400, "sailNm": 19260, "iso": "2026-09-19T02:00:00Z",
    "status": "live", "fromStop": "Nouméa",
}
RE7_REVIEW = {
    "legs": [
        {
            "from": "La Rochelle",
            "to": "Cayenne (Guyane)",
            "antiShipping": {"score": 0.4, "lanes": ["Bay of Biscay", "Gibraltar"]},
            "season": {"galePct": 18, "cyclones": 0, "cells": 2, "missing": 0},
        }
    ]
}


def _re7_journal():
    moments = [
        {"seq": 0, "t": "2026-05-15T08:00:00Z", "signature": "s0", "legIdx": 0, "changes": [],
         "moment": {"leg": {"from": "Saint-Maur", "to": "La Rochelle"}}},
        {"seq": 1, "t": "2026-05-15T12:00:00Z", "signature": "s1", "legIdx": 0, "changes": [
            {"kind": "escale", "score": 3, "title": "Arrivée à La Rochelle", "fact": "Saint-Maur → La Rochelle"},
        ], "moment": {"leg": {"from": "Saint-Maur", "to": "La Rochelle"}}},
        {"seq": 2, "t": "2026-05-16T09:00:00Z", "signature": "s2", "legIdx": 1, "changes": [
            {"kind": "zee-enter", "score": 2, "title": "Entrée dans Zone économique exclusive espagnole",
             "fact": "Entrée dans Zone économique exclusive espagnole"},
        ], "moment": {"leg": {"from": "La Rochelle", "to": "Cayenne (Guyane)"}}},
        {"seq": 3, "t": "2026-05-16T10:00:00Z", "signature": "s3", "legIdx": 1, "changes": [
            {"kind": "marina", "score": 2, "title": "Gran Roque", "fact": "Gran Roque (2 nm)"},
        ], "moment": {"leg": {"from": "La Rochelle", "to": "Cayenne (Guyane)"}}},
        {"seq": 4, "t": "2026-05-16T11:00:00Z", "signature": "s4", "legIdx": 1, "changes": [
            {"kind": "marina", "score": 2, "title": "Gran Roque", "fact": "Gran Roque (2 nm)", "id": "gr2"},
        ], "moment": {"leg": {"from": "La Rochelle", "to": "Cayenne (Guyane)"}}},
        {"seq": 5, "t": "2026-05-16T12:00:00Z", "signature": "s5", "legIdx": 1, "changes": [
            {"kind": "marina", "score": 2, "title": "Gran Roque", "fact": "Gran Roque encore", "id": "gr3"},
        ], "moment": {"leg": {"from": "La Rochelle", "to": "Cayenne (Guyane)"}}},
        {"seq": 6, "t": "2026-05-16T13:00:00Z", "signature": "s6", "legIdx": 1, "changes": [
            {"kind": "station", "score": 2, "title": "Station croisée", "fact": "Station croisée"},
        ], "moment": {"leg": {"from": "La Rochelle", "to": "Cayenne (Guyane)"}}},
        {"seq": 7, "t": "2026-05-16T14:00:00Z", "signature": "s7", "legIdx": 1, "changes": [
            {"kind": "zee-enter", "score": 2, "title": "Ports d'entrée : Les Sables-d'Olonne",
             "fact": "Les Sables-d'Olonne"},
        ], "moment": {"leg": {"from": "La Rochelle", "to": "Cayenne (Guyane)"}}},
        {"seq": 8, "t": "2026-05-16T15:00:00Z", "signature": "s8", "legIdx": 1, "changes": [
            {"kind": "zee-enter", "score": 2, "title": "Formalités d'entrée",
             "fact": "Aucun port d'entrée officiel n'est connu pour cette ZEE."},
        ], "moment": {"leg": {"from": "La Rochelle", "to": "Cayenne (Guyane)"}}},
        {"seq": 9, "t": "2026-05-16T16:00:00Z", "signature": "s9", "legIdx": 1, "changes": [
            {"kind": "marina", "score": 1, "title": "Monaco", "fact": "Monaco (80 nm)", "nm": 80},
        ], "moment": {"leg": {"from": "La Rochelle", "to": "Cayenne (Guyane)"}}},
        {"seq": 10, "t": "2026-07-01T08:00:00Z", "signature": "s10", "legIdx": 2, "changes": [
            {"kind": "escale", "score": 3, "title": "Arrivée à Cayenne", "fact": "La Rochelle → Cayenne"},
        ], "moment": {"leg": {"from": "La Rochelle", "to": "Cayenne (Guyane)"}}},
        {"seq": 11, "t": "2026-07-01T10:00:00Z", "signature": "s11", "legIdx": 2, "changes": [],
         "moment": {"leg": {"from": "Cayenne (Guyane)", "to": "Halifax (Nouvelle-Écosse)", "vehicle": "plane"}}},
        {"seq": 12, "t": "2026-07-02T08:00:00Z", "signature": "s12", "legIdx": 3, "changes": [
            {"kind": "escale", "score": 3, "title": "Arrivée à Halifax", "fact": "Cayenne → Halifax"},
        ], "moment": {"leg": {"from": "Cayenne (Guyane)", "to": "Halifax (Nouvelle-Écosse)", "vehicle": "plane"}}},
        {"seq": 13, "t": "2026-07-03T10:00:00Z", "signature": "s13", "legIdx": 3, "changes": [],
         "moment": {"leg": {"from": "Halifax (Nouvelle-Écosse)", "to": "Cayenne (Guyane)", "vehicle": "plane"}}},
        {"seq": 14, "t": "2026-07-10T06:00:00Z", "signature": "s14", "legIdx": 4, "changes": [
            {"kind": "cyclone", "score": 3, "title": "Irma", "fact": "Irma (2017)"},
        ], "moment": {"leg": {"from": "Halifax (Nouvelle-Écosse)", "to": "Nouméa (Nouvelle-Calédonie)"}}},
        {"seq": 15, "t": "2026-07-11T06:00:00Z", "signature": "s15", "legIdx": 4, "changes": [
            {"kind": "cyclone", "score": 1, "title": "Cyclone", "fact": "3 traces de cyclone ce mois-ci."},
        ], "moment": {"leg": {"from": "Halifax (Nouvelle-Écosse)", "to": "Nouméa (Nouvelle-Calédonie)"}}},
        {"seq": 16, "t": "2026-08-01T06:00:00Z", "signature": "s16", "legIdx": 4, "changes": [
            {"kind": "amp", "score": 1, "title": "Cabrera (IUCN Unassigned)", "fact": "Cabrera (IUCN Unassigned)"},
        ], "moment": {"leg": {"from": "Halifax (Nouvelle-Écosse)", "to": "Nouméa (Nouvelle-Calédonie)"}}},
        {"seq": 17, "t": "2026-08-02T06:00:00Z", "signature": "s17", "legIdx": 4, "changes": [
            {"kind": "station", "score": 2, "title": "PIRATA", "fact": "Station PIRATA à 6 milles nautiques."},
        ], "moment": {"leg": {"from": "Halifax (Nouvelle-Écosse)", "to": "Nouméa (Nouvelle-Calédonie)"}}},
        {"seq": 18, "t": "2026-08-03T06:00:00Z", "signature": "s18", "legIdx": 4, "changes": [
            {"kind": "culture", "score": 1, "title": "Fort Saint-Louis", "fact": "Fort Saint-Louis."},
        ], "moment": {"leg": {"from": "Halifax (Nouvelle-Écosse)", "to": "Nouméa (Nouvelle-Calédonie)"}}},
        {"seq": 19, "t": "2026-09-17T22:48:00Z", "signature": "s19", "legIdx": 4, "changes": [
            {"kind": "escale", "score": 3, "title": "Arrivée à Nouméa", "fact": "Halifax → Nouméa"},
        ], "moment": {"leg": {"from": "Halifax (Nouvelle-Écosse)", "to": "Nouméa (Nouvelle-Calédonie)"}}},
    ]
    return {"moments": moments, "latest": []}


def test_re7_discourse_eleven_defects():
    from film_script import script_words

    plan = build_raw_script(
        RE7_CLOCK, RE7_CLOCK["marks"], RE7_LIVE, _re7_journal(),
        lang="fr", seconds=0, now_ms=NOW_MS, review=RE7_REVIEW,
    )
    blob = _script_blob(plan)
    assert plan["targetSeconds"] == 0
    assert script_words(plan["chapters"]) <= 800
    assert "station croisée : Station croisée" not in blob
    assert "Aucun port d'entrée" not in blob
    assert "entrée dans Entrée dans" not in blob
    assert "IUCN" not in blob
    # Marina de route tues ; seule la marina d'escale est nommée à l'arrivée.
    assert "Gran Roque" not in blob
    assert "Monaco" not in blob
    assert re.search(r"s'envole de Cayenne pour Halifax", blob)
    assert re.search(r"le catamaran attend à Cayenne", blob)
    assert re.search(r"Aujourd’hui, le bateau est à Nouméa", blob)
    assert "Irma" in blob and "2017" in blob
    assert "une bouée" in blob
    assert "PIRATA" not in blob
    assert "stations scientifiques croisées" not in blob
    assert "Cabrera" in blob
    assert "Fort Saint-Louis" in blob
    assert "golfe de Gascogne" in blob
    assert "détroit de Gibraltar" in blob
    assert "Bay of Biscay" not in blob
    assert re.search(r"eaux espagnoles", blob)
    idx_zee = blob.find("eaux espagnoles")
    m_dep = re.search(r"La Rochelle.{0,120}Cayenne|quitte La Rochelle", blob)
    idx_dep = m_dep.start() if m_dep else blob.find("quitte")
    assert 0 <= idx_dep < idx_zee
    _assert_no_filler(blob)
    assert not re.search(r"\bnm\b", blob)


def _rf5_air_marks_no_halifax_iso():
    marks = []
    for m in RE7_CLOCK["marks"]:
        row = dict(m)
        if "Halifax" in row["name"]:
            row.pop("iso", None)
            row.pop("vehicle", None)
        marks.append(row)
    return marks


def test_rf5_air_survives_tight_budget():
    """Jambe avion aller + retour, budget 150 s et 108 s."""
    for seconds in (150, 108):
        plan = build_raw_script(
            RE7_CLOCK, RE7_CLOCK["marks"], RE7_LIVE, _re7_journal(),
            lang="fr", seconds=seconds, now_ms=NOW_MS, review=RE7_REVIEW,
        )
        blob = _script_blob(plan)
        assert plan["targetSeconds"] == seconds
        assert re.search(r"s'envole de Cayenne pour Halifax", blob), blob
        assert re.search(r"le catamaran attend à Cayenne", blob), blob
        _assert_no_filler(blob)


def test_rf5_air_when_halifax_has_no_iso():
    """Arrivée avion sans iso (hors clock_marks) : Cayenne nommée ne suffit pas — l'avion reste dit."""
    marks = _rf5_air_marks_no_halifax_iso()
    clock = {**RE7_CLOCK, "marks": marks}
    plan = build_raw_script(clock, marks, RE7_LIVE, None, lang="fr", seconds=0, now_ms=NOW_MS)
    blob = _script_blob(plan)
    assert "Cayenne" in blob
    assert re.search(r"s'envole de Cayenne pour Halifax", blob), blob
    assert re.search(r"le catamaran attend à Cayenne", blob), blob
    assert "avion pour Nouméa" not in blob
    _assert_no_filler(blob)


def test_rf5_air_return_without_moments():
    """Sans moments, dated_marks dédoublonne Cayenne : le retour avion doit quand même être dit."""
    plan = build_raw_script(
        RE7_CLOCK, RE7_CLOCK["marks"], RE7_LIVE, None,
        lang="fr", seconds=150, now_ms=NOW_MS,
    )
    blob = _script_blob(plan)
    assert re.search(r"s'envole de Cayenne pour Halifax", blob), blob
    assert re.search(r"le catamaran attend à Cayenne", blob), blob
    assert "avion pour Nouméa" not in blob
    _assert_no_filler(blob)


def test_rf5_no_air_invented_on_ajaccio_route():
    """Route sans Cayenne/Halifax : pas de phrase d'avion inventée."""
    plan = build_raw_script(CLOCK, CLOCK["marks"], LIVE, JOURNAL, lang="fr", seconds=0, now_ms=NOW_MS)
    blob = _script_blob(plan)
    assert "Cayenne" not in blob
    assert "Halifax" not in blob
    assert not re.search(r"prend l'avion|retour en avion|s'envole|flies to|return flight|the boat waits", blob)


def test_rg1_road_phrase_on_first_chapter():
    plan = build_raw_script(CLOCK, CLOCK["marks"], LIVE, JOURNAL, lang="fr", seconds=0, now_ms=NOW_MS)
    ch0 = plan["chapters"][0]["text"]
    assert re.search(r"par la route", ch0, re.I), ch0
    assert re.search(r"La Rochelle", ch0), ch0


def test_rg1_depart_ms_is_clock_leave_not_hold():
    """Écart nul quand l'horloge quitte à tA — jamais tA + 3 jours d'escale."""
    t_a = _ms(OFFICIAL_T0)
    t_end = _ms("2026-09-19T02:00:00Z")
    lr = {
        "name": "La Rochelle", "iso": OFFICIAL_T0, "holdHours": 72,
        "lat": 46.15, "lon": -1.16, "filmNm": 122, "nm": 0,
    }
    aj = {
        "name": "Ajaccio (Corse)", "iso": "2026-05-24T12:00:00Z", "holdHours": 72,
        "lat": 41.9, "lon": 8.7, "filmNm": 1942, "nm": 1820,
    }
    clock = {
        "t0": OFFICIAL_T0,
        "marks": [lr, aj],
        "vertices": [
            {"iso": OFFICIAL_T0, "lat": 46.20, "lon": -1.16, "vehicle": "main"},
        ],
    }
    windows = _windows([lr, aj], t_a, t_end, clock)
    sail = next(w for w in windows if "ajaccio" in (w.get("destName") or "").lower())
    assert _window_depart_ms(sail) == t_a
    bare = _windows([lr, aj], t_a, t_end, {"t0": OFFICIAL_T0, "vertices": [], "marks": [lr, aj]})
    sail_bare = next(w for w in bare if "ajaccio" in (w.get("destName") or "").lower())
    assert _window_depart_ms(sail_bare) == t_a
    hold_ms = 72 * 3_600_000
    assert _window_depart_ms(sail_bare) != t_a + hold_ms


def test_rg1_air_window_not_told_as_navigation():
    """Le catamaran ne navigue pas Cayenne → Saint-Pierre ; vol vers Halifax."""
    marks = [
        {"name": "Saint-Maur (Berry, Indre)", "nm": 0, "filmNm": 0, "iso": OFFICIAL_T0, "holdHours": 0, "lat": 46.8, "lon": 1.6},
        {"name": "La Rochelle", "nm": 122, "filmNm": 122, "iso": "2026-05-15T12:00:00Z", "holdHours": 0, "lat": 46.15, "lon": -1.16},
        {"name": "Cayenne (Guyane)", "nm": 4000, "filmNm": 4000, "iso": "2026-07-19T08:00:00Z", "holdHours": 72, "lat": 4.93, "lon": -52.33},
        {"name": "Halifax (Nouvelle-Écosse)", "nm": 4000, "filmNm": 4080, "iso": "2026-07-22T08:00:00Z", "holdHours": 24, "lat": 44.65, "lon": -63.57, "kind": "hub"},
        {"name": "Saint-Pierre (Saint-Pierre-et-Miquelon)", "nm": 4400, "filmNm": 4480, "iso": "2026-07-25T08:00:00Z", "holdHours": 72, "lat": 46.78, "lon": -56.18},
        {"name": "Halifax (Nouvelle-Écosse)", "nm": 4800, "filmNm": 4880, "iso": "2026-07-29T08:00:00Z", "holdHours": 24, "lat": 44.65, "lon": -63.57, "kind": "hub"},
        {"name": "Cayenne (Guyane)", "nm": 4800, "filmNm": 4960, "iso": "2026-07-30T08:00:00Z", "holdHours": 0, "lat": 4.93, "lon": -52.33},
        {"name": "Papeete (Polynésie française)", "nm": 11000, "filmNm": 11100, "iso": "2026-09-08T08:00:00Z", "holdHours": 72, "lat": -17.5, "lon": -149.5},
    ]
    clock = {"t0": OFFICIAL_T0, "marks": marks, "vertices": [
        {"iso": "2026-07-19T08:00:00Z", "lat": 4.93, "lon": -52.33, "vehicle": "quay"},
        {"iso": "2026-07-22T08:00:00Z", "lat": 44.65, "lon": -63.57, "vehicle": "plane"},
        {"iso": "2026-07-23T08:00:00Z", "lat": 45.7, "lon": -60.0, "vehicle": "side"},
        {"iso": "2026-07-25T08:00:00Z", "lat": 46.78, "lon": -56.18, "vehicle": "side"},
        {"iso": "2026-07-29T08:00:00Z", "lat": 44.65, "lon": -63.57, "vehicle": "side"},
        {"iso": "2026-07-30T08:00:00Z", "lat": 4.93, "lon": -52.33, "vehicle": "plane"},
        {"iso": "2026-08-02T08:00:00Z", "lat": 4.80, "lon": -52.50, "vehicle": "main"},
    ]}
    live = {"filmNm": 12000, "sailNm": 11800, "iso": "2026-09-19T02:00:00Z", "status": "live"}
    journal = {
        "moments": [
            {"seq": 0, "t": "2026-07-23T08:00:00Z", "changes": [
                {"kind": "zee-enter", "score": 2, "title": "Entrée dans Zone économique exclusive canadienne",
                 "fact": "Entrée dans Zone économique exclusive canadienne"},
            ], "moment": {"leg": {"from": "Halifax (Nouvelle-Écosse)", "to": "Saint-Pierre (Saint-Pierre-et-Miquelon)",
                                  "vehicle": "side"}}},
            {"seq": 1, "t": "2026-07-25T08:00:00Z", "changes": [
                {"kind": "escale", "score": 3, "title": "Arrivée à Saint-Pierre", "fact": "Halifax → Saint-Pierre"},
            ], "moment": {"leg": {"from": "Halifax (Nouvelle-Écosse)", "to": "Saint-Pierre (Saint-Pierre-et-Miquelon)",
                                  "vehicle": "side"}}},
            {"seq": 2, "t": "2026-08-02T09:00:00Z", "changes": [
                {"kind": "zee-enter", "score": 2, "title": "Entrée dans Zone économique exclusive du Panama",
                 "fact": "Entrée dans Zone économique exclusive du Panama"},
            ], "moment": {"leg": {"from": "Cayenne (Guyane)", "to": "Papeete (Polynésie française)"}}},
        ],
        "latest": [],
    }
    plan = build_raw_script(clock, marks, live, journal, lang="fr", seconds=0, now_ms=NOW_MS)
    blob = _script_blob(plan)
    assert re.search(r"s'envole de Cayenne pour Halifax", blob), blob
    assert re.search(r"le catamaran attend à Cayenne", blob), blob
    assert blob.lower().count("catamaran attend à cayenne") == 1
    assert re.search(r"second voilier", blob), blob
    assert re.search(r"s'envole d'Halifax pour Cayenne", blob), blob
    assert not re.search(r"s'envole de Cayenne pour Saint-Pierre", blob), blob
    assert not re.search(r"Berry-Mappemonde quitte Cayenne.{0,80}pour Saint-Pierre", blob), blob
    names = [(c.get("fromName") or "", c.get("toName") or "") for c in plan["chapters"]]
    air_out = next(i for i, (a, b) in enumerate(names) if "Cayenne" in a and "Halifax" in b)
    side_out = next(i for i, (a, b) in enumerate(names) if "Halifax" in a and "Saint-Pierre" in b)
    side_back = next(i for i, (a, b) in enumerate(names) if "Saint-Pierre" in a and "Halifax" in b)
    air_back = next(i for i, (a, b) in enumerate(names) if "Halifax" in a and "Cayenne" in b)
    assert air_out < side_out < side_back < air_back
    chs = plan["chapters"]
    assert re.search(r"19 juillet|22 juillet", chs[air_out]["text"] or "")
    assert re.search(r"22 juillet|23 juillet", chs[side_out]["text"] or "")
    assert re.search(r"25 juillet|29 juillet", chs[side_back]["text"] or "")
    assert re.search(r"29 juillet|30 juillet", chs[air_back]["text"] or "")
    next_sail = next(
        c for c in plan["chapters"]
        if re.search(r"pour Papeete|reprend la mer|départ vers Papeete|quitte Cayenne", c.get("text") or "")
    )
    assert "Cayenne" in (next_sail.get("fromName") or "")
    assert "Saint-Pierre" not in (next_sail.get("fromName") or "")
    assert not re.search(r"s'envole (?:de |d’)Halifax", chs[air_out]["text"] or ""), chs[air_out]["text"]
    assert not re.search(r"s'envole de Cayenne pour Halifax", chs[air_back]["text"] or ""), chs[air_back]["text"]
    assert not re.search(r"s'envole", chs[side_out]["text"] or ""), chs[side_out]["text"]
    assert re.search(r"second voilier", chs[side_out]["text"] or ""), chs[side_out]["text"]
    assert re.search(r"reprend la mer|départ vers Papeete", next_sail.get("text") or ""), next_sail.get("text")
    assert not re.search(r"s'envole", next_sail.get("text") or ""), next_sail.get("text")


def test_rg1_ensure_air_sentences_stay_on_matching_chapter():
    """Une phrase manquante n'est injectée que dans le chapitre from/to du vol."""
    from film_script import _ensure_air_sentences

    chapters = [
        {"fromName": "Cayenne (Guyane)", "toName": "Halifax (Nouvelle-Écosse)",
         "text": "Vol aller sans phrase."},
        {"fromName": "Halifax (Nouvelle-Écosse)",
         "toName": "Saint-Pierre (Saint-Pierre-et-Miquelon)",
         "text": "À Halifax, l'équipage embarque sur un second voilier pour Saint-Pierre."},
        {"fromName": "Saint-Pierre (Saint-Pierre-et-Miquelon)",
         "toName": "Halifax (Nouvelle-Écosse)", "text": "Retour mer."},
        {"fromName": "Halifax (Nouvelle-Écosse)", "toName": "Cayenne (Guyane)",
         "text": "Vol retour sans phrase."},
        {"fromName": "Cayenne (Guyane)", "toName": "Papeete (Polynésie française)",
         "text": "Le catamaran reprend la mer, départ vers Papeete."},
    ]
    marks = [
        {"name": "Cayenne (Guyane)"},
        {"name": "Halifax (Nouvelle-Écosse)"},
        {"name": "Saint-Pierre (Saint-Pierre-et-Miquelon)"},
    ]
    out = _ensure_air_sentences(chapters, marks=marks, moments=None, lang="fr")
    assert re.search(r"s'envole de Cayenne pour Halifax", out[0]["text"] or ""), out[0]["text"]
    assert not re.search(r"s'envole (?:de |d’)Halifax", out[0]["text"] or ""), out[0]["text"]
    assert not re.search(r"s'envole", out[1]["text"] or ""), out[1]["text"]
    assert re.search(r"second voilier", out[1]["text"] or ""), out[1]["text"]
    assert re.search(r"s'envole d'Halifax pour Cayenne", out[3]["text"] or ""), out[3]["text"]
    assert not re.search(r"s'envole de Cayenne pour Halifax", out[3]["text"] or ""), out[3]["text"]
    assert not re.search(r"s'envole", out[4]["text"] or ""), out[4]["text"]
    assert re.search(r"reprend la mer", out[4]["text"] or ""), out[4]["text"]


def test_rg1_depart_anchor_stays_at_port():
    t_end = _ms("2026-09-19T02:00:00Z")
    lr = {
        "name": "La Rochelle", "iso": "2026-05-15T12:00:00Z", "holdHours": 72,
        "lat": 46.15, "lon": -1.16, "filmNm": 122, "nm": 0,
    }
    aj = {
        "name": "Ajaccio (Corse)", "iso": "2026-05-24T12:00:00Z", "holdHours": 72,
        "lat": 41.9, "lon": 8.7, "filmNm": 1942, "nm": 1820,
    }
    leave_iso = "2026-05-15T13:00:00Z"
    clock = {
        "t0": OFFICIAL_T0,
        "marks": [CLOCK["marks"][0], lr, aj],
        "vertices": [
            {"iso": "2026-05-15T12:00:00Z", "lat": 46.15, "lon": -1.16, "vehicle": "main"},
            {"iso": leave_iso, "lat": 46.15, "lon": -1.24, "vehicle": "main"},
        ],
    }
    live = {"filmNm": 2000, "sailNm": 1900, "iso": "2026-05-25T00:00:00Z", "status": "live"}
    plan = build_raw_script(clock, clock["marks"], live, None, lang="fr", seconds=0, now_ms=t_end)
    ch = next(
        c for c in plan["chapters"]
        if re.search(r"pour Ajaccio|quitte La Rochelle", c.get("text") or "")
    )
    anchors = ch.get("anchors") or []
    assert anchors, ch
    text = ch.get("text") or ""
    depart_anchor = next(
        a for a in anchors
        if re.search(r"Ajaccio|La Rochelle", text[max(0, int(a.get("charIdx") or 0)):])
    )
    t_anchor = _ms(depart_anchor["t"])
    vert = min(
        clock["vertices"],
        key=lambda v: abs((_ms(v["iso"]) or 0) - (t_anchor or 0)),
    )
    d = _nm_between(46.15, -1.16, vert["lat"], vert["lon"])
    assert d is not None and d <= 5.0, (d, depart_anchor, vert)


def test_official_route_zee_all_have_spoken_names():
    """Toute ZEE de la route officielle a un nom parlé, sans jargon de source."""
    for src in OFFICIAL_ROUTE_ZEE_SOURCES:
        spoken = zee_waters_label(src, "fr")
        assert spoken, f"pas de nom parlé pour {src!r}"
        assert "zone économique exclusive" not in spoken.lower(), (src, spoken)
        assert "exclusive economic" not in spoken.lower(), (src, spoken)
        en = zee_waters_label(src, "en")
        assert en, f"no spoken EN name for {src!r}"
        assert "exclusive economic" not in en.lower(), (src, en)


def test_zee_haute_mer_and_sahara_spoken():
    assert zee_waters_label("Haute mer", "fr") == "haute mer"
    assert zee_waters_label("High Seas", "en") == "the high seas"
    assert "disputées du Sahara occidental" in zee_waters_label(
        "Overlapping claim Western Sahara: Western Sahara / Morocco", "fr",
    )
    assert "Barbade" in zee_waters_label("Zone économique exclusive (Barbadian)", "fr") or (
        "barbadiennes" in zee_waters_label("Zone économique exclusive (Barbadian)", "fr")
    )
    assert "vénézuéliennes" in zee_waters_label("Zone économique exclusive vénézuélienne", "fr")
    assert "indiennes" in zee_waters_label(
        "Zone économique exclusive indienne (Andaman and Nicobar Islands)", "fr",
    )


def test_heading_phrase_eight_directions():
    assert heading_phrase(246, "fr") == "cap au sud-ouest"
    assert heading_phrase(0, "fr") == "cap au nord"
    assert heading_phrase(90, "fr") == "cap à l'est"
    assert heading_phrase(270, "fr") == "cap à l'ouest"
    assert heading_phrase(90, "en") == "heading east"
    assert heading_phrase(None, "fr") == ""


def test_zee_dosage_short_keeps_all_long_one_per_day():
    day = 86_400_000
    short = [
        {"id": "a", "kind": "zee-enter", "tMs": 1, "t": "2026-07-01T08:00:00Z",
         "title": "Antiguan and Barbudan Exclusive Economic Zone", "fact": "x", "score": 2},
        {"id": "b", "kind": "zee-enter", "tMs": 2, "t": "2026-07-01T14:00:00Z",
         "title": "Kittitian and Nevisian Exclusive Economic Zone", "fact": "y", "score": 2},
        {"id": "c", "kind": "zee-enter", "tMs": 3, "t": "2026-07-01T20:00:00Z",
         "title": "Sint-Eustatius Exclusive Economic Zone", "fact": "z", "score": 2},
    ]
    for i, c in enumerate(short):
        c["tMs"] = _ms(c["t"])
    clustered = dose_zee_changes(short, span_ms=2 * day)
    assert len(clustered) == 1
    sent = change_sentence(clustered[0], "fr")
    # Groupe grammatical « les eaux X, puis celles de Y » — noms FR.
    assert "les eaux d'Antigua-et-Barbuda" in sent
    assert "puis celles de Saint-Christophe-et-Niévès" in sent
    assert "puis celles de Saint-Eustache" in sent
    assert "zones économiques exclusives" not in sent
    assert "zone économique exclusive" not in sent
    it_fr = [
        {"id": "it", "kind": "zee-enter", "tMs": _ms("2026-05-24T22:04:29Z"),
         "t": "2026-05-24T22:04:29Z", "title": "Zone économique exclusive italienne",
         "fact": "Zone économique exclusive italienne", "score": 2},
        {"id": "fr", "kind": "zee-enter", "tMs": _ms("2026-05-25T21:27:29Z"),
         "t": "2026-05-25T21:27:29Z", "title": "Zone économique exclusive française (France métropolitaine)",
         "fact": "Zone économique exclusive française (France métropolitaine)", "score": 2},
    ]
    it_fr_c = dose_zee_changes(it_fr, span_ms=2 * day)
    assert len(it_fr_c) == 1
    it_sent = change_sentence(it_fr_c[0], "fr")
    assert "les eaux" in it_sent and "italiennes" in it_sent and "françaises" in it_sent

    long_span = 10 * day
    long_zee = [
        {"id": f"z{i}", "kind": "zee-enter", "score": 2,
         "title": title, "fact": title,
         "t": t, "tMs": _ms(t)}
        for i, (title, t) in enumerate((
            ("Spanish Exclusive Economic Zone", "2026-05-16T08:00:00Z"),
            ("Portuguese Exclusive Economic Zone", "2026-05-18T08:00:00Z"),
            ("Moroccan Exclusive Economic Zone", "2026-05-21T08:00:00Z"),
            ("Italian Exclusive Economic Zone", "2026-05-24T08:00:00Z"),
            ("French Exclusive Economic Zone", "2026-05-25T08:00:00Z"),
        ))
    ]
    dosed = dose_zee_changes(long_zee, span_ms=long_span)
    assert len(dosed) == 5
    same_day = [
        {**long_zee[0], "id": "extra", "t": "2026-05-16T20:00:00Z", "tMs": _ms("2026-05-16T20:00:00Z"),
         "title": "Portuguese Exclusive Economic Zone"},
    ]
    one_day = dose_zee_changes([long_zee[0], same_day[0]], span_ms=long_span)
    # ES et PT sont des eaux de la route — deux phrases, pas un groupe du jour.
    assert len(one_day) == 2
    assert {c["title"] for c in one_day} == {
        "Spanish Exclusive Economic Zone", "Portuguese Exclusive Economic Zone",
    }


def test_zee_named_in_date_order_no_count():
    t0 = _ms("2026-05-15T08:00:00Z")
    changes = [
        {"id": "es", "kind": "zee-enter", "score": 2, "tMs": _ms("2026-05-16T08:00:00Z"),
         "t": "2026-05-16T08:00:00Z", "title": "Spanish Exclusive Economic Zone",
         "fact": "Spanish Exclusive Economic Zone"},
        {"id": "pt", "kind": "zee-enter", "score": 2, "tMs": _ms("2026-05-18T08:00:00Z"),
         "t": "2026-05-18T08:00:00Z", "title": "Portuguese Exclusive Economic Zone",
         "fact": "Portuguese Exclusive Economic Zone"},
        {"id": "ma", "kind": "zee-enter", "score": 2, "tMs": _ms("2026-05-21T08:00:00Z"),
         "t": "2026-05-21T08:00:00Z", "title": "Moroccan Exclusive Economic Zone",
         "fact": "Moroccan Exclusive Economic Zone"},
        {"id": "arr", "kind": "escale", "score": 3, "tMs": _ms("2026-05-26T08:00:00Z"),
         "t": "2026-05-26T08:00:00Z", "title": "Arrivée à Ajaccio", "fact": "x"},
    ]
    picked = select_chapter_changes(changes, t0, _ms("2026-05-26T12:00:00Z"), budget=True)
    kinds = [c["kind"] for c in picked]
    assert kinds.count("zee-enter") >= 3
    texts = [change_sentence(c, "fr") for c in picked if c["kind"] == "zee-enter"]
    blob = " ".join(texts)
    assert blob.find("espagnoles") < blob.find("portugaises") < blob.find("marocaines")
    assert "zones économiques exclusives" not in blob
    assert "zone économique exclusive" not in blob


def test_coast_milestones_ordered_by_route():
    t0 = _ms("2026-05-15T08:00:00Z")
    coasts = [
        {"id": "cam", "kind": "coast", "score": 2, "tMs": _ms("2026-05-16T12:00:00Z"),
         "t": "2026-05-16T12:00:00Z", "title": "Camariñas", "fact": "Camariñas (4 nm)"},
        {"id": "mux", "kind": "coast", "score": 2, "tMs": _ms("2026-05-16T14:00:00Z"),
         "t": "2026-05-16T14:00:00Z", "title": "Muxía", "fact": "Muxía (3 nm)"},
        {"id": "tan", "kind": "coast", "score": 2, "tMs": _ms("2026-05-21T08:00:00Z"),
         "t": "2026-05-21T08:00:00Z", "title": "Tanger", "fact": "Tanger (2 nm)"},
        {"id": "alg", "kind": "coast", "score": 2, "tMs": _ms("2026-05-21T09:00:00Z"),
         "t": "2026-05-21T09:00:00Z", "title": "Algeciras", "fact": "Algeciras (3 nm)"},
        {"id": "ptt", "kind": "coast", "score": 2, "tMs": _ms("2026-05-24T10:00:00Z"),
         "t": "2026-05-24T10:00:00Z", "title": "Porto Torres", "fact": "Porto Torres (5 nm)"},
    ]
    dosed = dose_coast_changes(coasts, span_ms=11 * 86_400_000)
    assert [ _utc_day_from(c) for c in dosed ] == sorted(_utc_day_from(c) for c in dosed)
    galice = next(c for c in dosed if "Camariñas" in (c.get("title") or "") or "Galice" in (c.get("title") or ""))
    sent = coast_sentence(galice, "fr")
    assert "Galice" in sent
    assert "Camariñas" in sent and "Muxía" in sent
    gib = next(c for c in dosed if any(p in (c.get("title") or "") or p in " ".join(c.get("ports") or [])
                                        for p in ("Tanger", "Algeciras", "Gibraltar")))
    gsent = coast_sentence(gib, "fr")
    assert "Gibraltar" in gsent
    assert "Tanger" in gsent and "Algeciras" in gsent
    sar = next(c for c in dosed if "Porto Torres" in (c.get("title") or "") or "Sardaigne" in (c.get("title") or ""))
    assert "Sardaigne" in coast_sentence(sar, "fr")
    picked = select_chapter_changes(coasts, t0, _ms("2026-05-26T12:00:00Z"), budget=True)
    coast_picked = [c for c in picked if c.get("kind") == "coast"]
    assert len(coast_picked) >= 3
    times = [c.get("tMs") or 0 for c in coast_picked]
    assert times == sorted(times)


def test_coast_merge_uses_language_for_continental_geography():
    changes = [
        {"id": "shelf", "kind": "coast", "tMs": 1, "title": "Brest", "geo": {
            "fr": "limite du plateau continental", "en": "Continental Shelf", "kind": "coast",
        }},
        {"id": "edge", "kind": "coast", "tMs": 86_400_001, "title": "Brest", "geo": {
            "fr": "limite du continent", "kind": "coast",
        }},
        {"id": "fallback", "kind": "coast", "tMs": 172_800_001, "title": "Brest", "geo": {
            "fr": "géographie inconnue", "kind": "coast",
        }},
    ]

    en = dose_coast_changes(changes, span_ms=3 * 86_400_000, lang="en")
    fr = dose_coast_changes(changes, span_ms=3 * 86_400_000, lang="fr")

    assert en[0]["title"] == "Continental Shelf — Brest"
    assert en[1]["title"] == "continental edge — Brest"
    assert en[2]["title"] == "Brest"
    assert fr[0]["title"] == "limite du plateau continental — Brest"
    assert fr[1]["title"] == "limite du continent — Brest"
    assert fr[2]["title"] == "géographie inconnue — Brest"


def test_stock_ports_and_marinas_become_named_coasts():
    """Les 44 ports et les marinas du stock (Camariñas, Tanger…) sont des jalons, pas un comptage."""
    t0 = _ms("2026-05-15T08:00:00Z")
    changes = [
        {"id": "cam", "kind": "marina", "score": 2, "tMs": _ms("2026-05-18T11:42:00Z"),
         "t": "2026-05-18T11:42:00Z", "title": "Club Náutico de Camariñas",
         "fact": "Club Náutico de Camariñas (4 nm)"},
        {"id": "mux", "kind": "marina", "score": 2, "tMs": _ms("2026-05-18T12:42:00Z"),
         "t": "2026-05-18T12:42:00Z", "title": "Porto de Muxía", "fact": "Porto de Muxía (3 nm)"},
        {"id": "tan", "kind": "port", "score": 2, "tMs": _ms("2026-05-21T14:37:58Z"),
         "t": "2026-05-21T14:37:58Z", "title": "Tanger", "fact": "Tanger"},
        {"id": "alg", "kind": "port", "score": 2, "tMs": _ms("2026-05-21T19:05:47Z"),
         "t": "2026-05-21T19:05:47Z", "title": "Algeciras", "fact": "Algeciras"},
        {"id": "ptt", "kind": "port", "score": 2, "tMs": _ms("2026-05-25T15:48:38Z"),
         "t": "2026-05-25T15:48:38Z", "title": "Porto Torres", "fact": "Porto Torres"},
    ]
    dosed = dose_coast_changes(changes, span_ms=11 * 86_400_000)
    blob = " ".join(coast_sentence(c, "fr") for c in dosed)
    assert "zone économique exclusive" not in blob
    assert "Galice" in blob and "Camariñas" in blob and "Muxía" in blob
    assert "Gibraltar" in blob and "Tanger" in blob and "Algeciras" in blob
    assert "Sardaigne" in blob and "Porto Torres" in blob
    picked = select_chapter_changes(changes, t0, _ms("2026-05-26T12:00:00Z"), budget=True)
    assert [c.get("kind") for c in picked if c.get("kind") == "coast"]
    times = [c.get("tMs") or 0 for c in picked if c.get("kind") == "coast"]
    assert times == sorted(times)


def test_rg2_coast():
    """Muxía+Camariñas ensemble ; île Sardaigne pas écrasée le même jour."""
    coasts = [
        {"id": "cor", "kind": "coast", "score": 2, "tMs": _ms("2026-05-16T10:00:00Z"),
         "t": "2026-05-16T10:00:00Z", "title": "La Coruña", "fact": "La Coruña (6 nm)"},
        {"id": "cam", "kind": "coast", "score": 2, "tMs": _ms("2026-05-16T12:00:00Z"),
         "t": "2026-05-16T12:00:00Z", "title": "Camariñas", "fact": "Camariñas (4 nm)"},
        {"id": "mux", "kind": "coast", "score": 2, "tMs": _ms("2026-05-16T14:00:00Z"),
         "t": "2026-05-16T14:00:00Z", "title": "Muxía", "fact": "Muxía (3 nm)"},
        {"id": "cal", "kind": "coast", "score": 2, "tMs": _ms("2026-05-24T09:00:00Z"),
         "t": "2026-05-24T09:00:00Z", "title": "Calvi", "fact": "Calvi (6 nm)"},
        {"id": "bas", "kind": "coast", "score": 2, "tMs": _ms("2026-05-24T09:30:00Z"),
         "t": "2026-05-24T09:30:00Z", "title": "Bastia", "fact": "Bastia (8 nm)"},
        {"id": "ptt", "kind": "coast", "score": 2, "tMs": _ms("2026-05-24T10:00:00Z"),
         "t": "2026-05-24T10:00:00Z", "title": "Porto Torres", "fact": "Porto Torres (5 nm)"},
        {"id": "liv", "kind": "port", "score": 2, "tMs": _ms("2026-05-24T11:00:00Z"),
         "t": "2026-05-24T11:00:00Z", "title": "Livorno", "fact": "Livorno (12 nm)"},
    ]
    dosed = dose_coast_changes(coasts, span_ms=11 * 86_400_000)
    blob = " ".join(coast_sentence(c, "fr") for c in dosed)
    assert "zone économique exclusive" not in blob
    assert "Galice" in blob and "Camariñas" in blob and "Muxía" in blob
    galice = next(
        c for c in dosed
        if "Camariñas" in " ".join(c.get("ports") or [])
        or "Galice" in (c.get("title") or "")
        or ((c.get("geo") or {}).get("fr") == "la Galice")
    )
    ports = galice.get("ports") or []
    named = [p for p in ports if re.search(r"camari[nñ]as|mux[ií]a", p, re.I)]
    assert len(named) == 2
    assert not any(re.search(r"coru[nñ]a", p, re.I) for p in ports)
    assert "Sardaigne" in blob and "Porto Torres" in blob
    assert "Corse" in blob or "Calvi" in blob


def _utc_day_from(change: dict) -> str:
    from film_script import _utc_day
    return _utc_day(change)


def test_rg2_film_names_route_and_heading():
    journal = {
        "moments": [
            {"seq": 0, "t": "2026-05-15T08:00:00Z", "signature": "s0", "legIdx": 0, "changes": [],
             "moment": {"leg": {"from": "Saint-Maur", "to": "La Rochelle"}}},
            {"seq": 1, "t": "2026-05-15T12:00:00Z", "signature": "s1", "legIdx": 0, "changes": [
                {"kind": "escale", "score": 3, "title": "Arrivée à La Rochelle", "fact": "x"},
            ], "moment": {"leg": {"from": "Saint-Maur", "to": "La Rochelle"}}},
            {"seq": 2, "t": "2026-05-15T13:00:00Z", "signature": "s2", "legIdx": 1, "changes": [],
             "moment": {"leg": {"from": "La Rochelle", "to": "Ajaccio (Corse)", "headingDeg": 246}}},
            {"seq": 3, "t": "2026-05-16T08:00:00Z", "signature": "s3", "legIdx": 1, "changes": [
                {"kind": "zee-enter", "score": 2, "title": "Spanish Exclusive Economic Zone",
                 "fact": "Spanish Exclusive Economic Zone"},
            ], "moment": {"leg": {"from": "La Rochelle", "to": "Ajaccio (Corse)", "headingDeg": 246}}},
            {"seq": 35, "t": "2026-05-16T10:00:00Z", "signature": "s35", "legIdx": 1, "changes": [
                {"kind": "coast", "score": 2, "title": "La Coruña", "fact": "La Coruña (6 nm)"},
            ], "moment": {"leg": {"from": "La Rochelle", "to": "Ajaccio (Corse)", "headingDeg": 240}}},
            {"seq": 4, "t": "2026-05-16T12:00:00Z", "signature": "s4", "legIdx": 1, "changes": [
                {"kind": "coast", "score": 2, "title": "Camariñas", "fact": "Camariñas (4 nm)"},
            ], "moment": {"leg": {"from": "La Rochelle", "to": "Ajaccio (Corse)", "headingDeg": 240}}},
            {"seq": 5, "t": "2026-05-16T14:00:00Z", "signature": "s5", "legIdx": 1, "changes": [
                {"kind": "coast", "score": 2, "title": "Muxía", "fact": "Muxía (3 nm)"},
            ], "moment": {"leg": {"from": "La Rochelle", "to": "Ajaccio (Corse)", "headingDeg": 240}}},
            {"seq": 6, "t": "2026-05-18T08:00:00Z", "signature": "s6", "legIdx": 1, "changes": [
                {"kind": "zee-enter", "score": 2, "title": "Portuguese Exclusive Economic Zone",
                 "fact": "Portuguese Exclusive Economic Zone"},
            ], "moment": {"leg": {"from": "La Rochelle", "to": "Ajaccio (Corse)", "headingDeg": 180}}},
            {"seq": 7, "t": "2026-05-21T08:00:00Z", "signature": "s7", "legIdx": 1, "changes": [
                {"kind": "zee-enter", "score": 2, "title": "Moroccan Exclusive Economic Zone",
                 "fact": "Moroccan Exclusive Economic Zone"},
                {"kind": "coast", "score": 2, "title": "Tanger", "fact": "Tanger (2 nm)"},
            ], "moment": {"leg": {"from": "La Rochelle", "to": "Ajaccio (Corse)", "headingDeg": 90}}},
            {"seq": 8, "t": "2026-05-21T09:00:00Z", "signature": "s8", "legIdx": 1, "changes": [
                {"kind": "coast", "score": 2, "title": "Algeciras", "fact": "Algeciras (3 nm)"},
            ], "moment": {"leg": {"from": "La Rochelle", "to": "Ajaccio (Corse)", "headingDeg": 90}}},
            {"seq": 9, "t": "2026-05-24T10:00:00Z", "signature": "s9", "legIdx": 1, "changes": [
                {"kind": "zee-enter", "score": 2, "title": "Italian Exclusive Economic Zone",
                 "fact": "Italian Exclusive Economic Zone"},
                {"kind": "coast", "score": 2, "title": "Calvi", "fact": "Calvi (6 nm)"},
                {"kind": "coast", "score": 2, "title": "Bastia", "fact": "Bastia (8 nm)"},
                {"kind": "coast", "score": 2, "title": "Porto Torres", "fact": "Porto Torres (5 nm)"},
            ], "moment": {"leg": {"from": "La Rochelle", "to": "Ajaccio (Corse)", "headingDeg": 45}}},
            {"seq": 10, "t": "2026-05-25T08:00:00Z", "signature": "s10", "legIdx": 1, "changes": [
                {"kind": "zee-enter", "score": 2, "title": "French Exclusive Economic Zone",
                 "fact": "French Exclusive Economic Zone"},
                {"kind": "coast", "score": 2, "title": "Calvi", "fact": "Calvi (6 nm)"},
            ], "moment": {"leg": {"from": "La Rochelle", "to": "Ajaccio (Corse)", "headingDeg": 20}}},
            {"seq": 11, "t": "2026-05-24T12:51:00Z", "signature": "s11", "legIdx": 1, "changes": [
                {"kind": "escale", "score": 3, "title": "Arrivée à Ajaccio", "fact": "x"},
            ], "moment": {"leg": {"from": "La Rochelle", "to": "Ajaccio (Corse)"}}},
        ],
        "latest": [],
    }
    plan = build_raw_script(CLOCK, CLOCK["marks"], LIVE, journal, lang="fr", seconds=0, now_ms=NOW_MS)
    blob = _script_blob(plan)
    assert "zone économique exclusive" not in blob.lower()
    assert "zones économiques exclusives" not in blob
    assert blob.find("espagnoles") < blob.find("portugaises") < blob.find("marocaines")
    assert "Galice" in blob
    assert "Muxía" in blob
    assert "Camariñas" in blob
    assert "Gibraltar" in blob
    assert "Sardaigne" in blob
    assert "cap au sud-ouest" in blob


def test_rg2_island_survives_waters_trim():
    """La Sardaigne n'est pas retirée pour garder les eaux italiennes / françaises."""
    head = "Le 15 mai, Berry-Mappemonde quitte La Rochelle, cap au sud-ouest."
    arrival = "Arrivée à Ajaccio le 26 mai."
    island = "Le 24 mai, la Sardaigne — Porto Torres."
    galice = "Le 17 mai, le bateau longe la Galice — Camariñas, Muxía."
    waters = [
        "Le 24 mai, les eaux italiennes.",
        "Le 25 mai, les eaux françaises.",
    ]
    extra = [f"Le {20 + i} mai, longe la côte — Port-{i}." for i in range(40)]
    blob = " ".join([head, *waters, galice, island, *extra, arrival])
    assert len(blob) > 360 * 1.1
    out = fit_chapter_text(blob, 360, [], "fr")
    assert "Sardaigne" in out and "Porto Torres" in out
    assert "Muxía" in out and "Galice" in out
    assert "Port-39" not in out


def test_chaluts_never_spoken_as_amp():
    fishing = {
        "kind": "amp", "score": 1, "title": "Pertuis Charentais - Chaluts",
        "fact": "Pertuis Charentais - Chaluts (2 nm): IUCN Unassigned.",
    }
    alert = {
        "kind": "alert-on", "score": 3, "title": "Aire marine protégée",
        "fact": "Pertuis Charentais - Pétoncles - Center Pertuis Breton deposit (3 nm): IUCN Unassigned.",
    }
    assert change_sentence(fishing, "fr") == ""
    assert not alert_is_amp(alert)
    assert "Pétoncles" not in change_sentence(alert, "fr")
    assert "deposit" not in change_sentence(alert, "fr").lower()
    real = {
        "kind": "amp", "score": 1, "title": "Pertuis charentais - Rochebonne",
        "fact": "Pertuis charentais - Rochebonne (12 nm)", "nm": 12,
    }
    sent = change_sentence(real, "fr")
    assert "Rochebonne" in sent
    assert "douze milles" in sent
    assert "Pétoncles" not in sent


def test_project_sentence_and_dosage():
    near = {
        "kind": "project", "score": 1, "title": "Récif sentinelle",
        "fact": "Récif sentinelle (10 nm)", "nm": 10, "gold_on": True,
    }
    sent = change_sentence(near, "fr")
    assert "le projet Récif sentinelle" in sent
    assert "dix milles" in sent
    far = {**near, "id": "far", "nm": 60, "title": "Loin", "fact": "Loin (60 nm)"}
    from film_script import change_is_speakable, change_on_route
    assert change_on_route(near)
    assert not change_on_route(far)
    short_span = SHORT_CROSSING_MS - 1
    many = [
        {**near, "id": f"p{i}", "title": f"Projet {i}", "fact": f"Projet {i} (1 nm)",
         "nm": 1 + i, "gold_on": i == 2, "tMs": i}
        for i in range(5)
    ]
    assert len(dose_project_changes(many, short_span)) == 1
    assert dose_project_changes(many, short_span)[0]["gold_on"] is True
    long_span = 12 * 86_400_000
    assert len(dose_project_changes(many, long_span)) == 3
    amps = [
        {"kind": "amp", "id": f"a{i}", "title": f"Réserve {i}", "fact": f"Réserve {i} ({i} nm)",
         "nm": i + 1, "tMs": i}
        for i in range(5)
    ]
    assert len(dose_amp_changes(amps, short_span)) == 1
    assert len(dose_amp_changes(amps, long_span)) == 3
    assert dose_amp_changes(amps, short_span)[0]["nm"] == 1


def test_climo_sentence_and_dosage():
    atlas = {
        "kind": "climo", "id": "climo:ne", "event": "ne_trades", "regimeId": "ne_trades",
        "t": "2026-06-14T12:00:00Z", "tMs": _ms("2026-06-14T12:00:00Z"),
        "source": "atlas", "nature": "season", "windKnots": 15,
        "placeFr": "au sud du Cap-Vert", "placeEn": "south of Cape Verde",
        "title": "alizés de nord-est", "fact": "alizés de nord-est",
    }
    fr = change_sentence(atlas, "fr")
    en = change_sentence(atlas, "en")
    assert "alizés de nord-est" in fr
    assert "quinze nœuds, la moyenne de saison" in fr
    assert "northeasterly trade winds" in en
    assert "fifteen knots, the seasonal average" in en
    zone = {
        **atlas, "id": "climo:zone", "source": "zone_fallback", "nature": "zone",
        "windKnots": None, "dirFromDeg": None,
    }
    zfr = change_sentence(zone, "fr")
    assert "vents moyens de saison" in zfr
    assert "quinze" not in zfr
    assert not re.search(r"\d+\s*n", zfr)
    many = [
        {**atlas, "id": f"c{i}", "tMs": i, "event": "ne_trades" if i < 2 else "force",
         "regimeId": "ne_trades" if i < 2 else None}
        for i in range(5)
    ]
    assert len(dose_climo_changes(many, SHORT_CROSSING_MS - 1)) == 1
    assert len(dose_climo_changes(many, 20 * 86_400_000)) == 2
    picked = select_chapter_changes(many, 0, 20 * 86_400_000, budget=True)
    assert sum(1 for c in picked if c.get("kind") == "climo") <= 2


def test_rg5_dataset_title_never_spoken():
    assert not station_name_speakable("Bacteria in Rias of Galicia")
    silent = {
        "kind": "station",
        "title": "Bacteria in Rias of Galicia",
        "fact": "Bacteria in Rias of Galicia (2 nm)",
        "t": "2026-05-16T12:00:00Z",
    }
    assert change_sentence(silent, "fr") == ""
    assert change_sentence(silent, "en") == ""
    assert "Bacteria" not in (change_sentence(silent, "fr") or "")


def test_rg5_argo_speaks_type_and_rc30_identifier():
    """RC30 (revue du 14 oct.) : le flotteur Argo se dit AVEC son identifiant —
    jamais six « un flotteur Argo » anonymes ; sans identifiant, silence."""
    ch = {
        "kind": "station",
        "title": "Argo 6904216",
        "fact": "Argo 6904216 (4 nm)",
        "t": "2026-05-18T12:00:00Z",
        "source": "argo",
    }
    fr = change_sentence(ch, "fr")
    en = change_sentence(ch, "en")
    assert fr == "Le 18 mai, le flotteur Argo 6904216."
    assert en == "On 18 May, Argo float 6904216."
    assert station_spoken_label(ch, "fr") == "le flotteur Argo 6904216"
    assert station_name_speakable("Argo 6904216")
    nameless = {
        "kind": "station",
        "title": "Argo",
        "fact": "Argo (4 nm)",
        "t": "2026-05-18T12:00:00Z",
        "source": "argo",
    }
    assert station_spoken_label(nameless, "fr") == ""
    assert change_sentence(nameless, "fr") == ""
    # Le titre du jeu de données reste interdit : le type + l'identifiant, rien d'autre.
    wmo_only = {**nameless, "title": "Flotteur dérivant", "wmo": "6904216"}
    assert station_spoken_label(wmo_only, "fr") == "le flotteur Argo 6904216"


def test_rg5_named_types_from_title_words():
    assert station_spoken_label({"kind": "station", "title": "PELGAS2025"}, "fr") == "la campagne PELGAS"
    assert station_spoken_label({"kind": "station", "title": "PELGAS2025"}, "en") == "the PELGAS campaign"
    assert station_spoken_label({"kind": "station", "title": "Wave buoy 12"}, "fr") == "une bouée"
    assert station_spoken_label({"kind": "station", "title": "CTD and nutrients sections"}, "fr") == "une station côtière"
    assert station_spoken_label({"kind": "station", "title": "Coastal observatory Brest"}, "fr") == "un observatoire"
    assert station_spoken_label({"kind": "station", "title": "Station croisée"}, "fr") == ""


def test_rg5_one_station_per_chapter_closest_no_count():
    from film_script import _group_changes

    bacteria = {
        "id": "s0", "kind": "station", "score": 2, "tMs": 1, "nm": 1,
        "title": "Bacteria in Rias of Galicia", "fact": "Bacteria in Rias of Galicia",
    }
    far = {
        "id": "s1", "kind": "station", "score": 2, "tMs": 2, "nm": 8,
        "title": "Argo 6904216", "fact": "Argo 6904216", "source": "argo",
    }
    near = {
        "id": "s2", "kind": "station", "score": 2, "tMs": 3, "nm": 2,
        "title": "Argo 6901234", "fact": "Argo 6901234", "source": "argo",
    }
    escale = {
        "id": "e", "kind": "escale", "score": 3, "tMs": 4,
        "title": "Arrivée à Ajaccio", "fact": "x",
    }
    picked = select_chapter_changes([bacteria, far, near, escale], 0, 10, budget=False)
    stations = [c for c in picked if c.get("kind") == "station"]
    assert len(stations) == 1
    assert stations[0]["id"] == "s2"
    assert dose_station_changes([bacteria, far, near], 99) == [near]

    crowd = [
        {**far, "id": f"g{i}", "tMs": i, "title": f"Argo {6904216 + i}"}
        for i in range(6)
    ]
    grouped = _group_changes(crowd, 20 * 86_400_000)
    blob = " ".join(change_sentence(c, "fr") for c in grouped)
    assert "stations scientifiques croisées" not in blob
    assert not any(str(c.get("id") or "").startswith("group:station") for c in grouped)

    moments = {
        "moments": [
            {"seq": 0, "t": "2026-05-15T08:00:00Z", "signature": "s0", "legIdx": 0, "changes": [],
             "moment": {"leg": {"from": "Saint-Maur", "to": "La Rochelle"}}},
            {"seq": 1, "t": "2026-05-15T12:00:00Z", "signature": "s1", "legIdx": 0, "changes": [
                {"kind": "escale", "score": 3, "title": "Arrivée à La Rochelle", "fact": "x"},
            ], "moment": {"leg": {"from": "Saint-Maur", "to": "La Rochelle"}}},
            {"seq": 2, "t": "2026-05-16T09:00:00Z", "signature": "s2", "legIdx": 1, "changes": [
                {"kind": "station", "score": 2, "title": "Bacteria in Rias of Galicia",
                 "fact": "Bacteria in Rias of Galicia", "nm": 1},
                {"kind": "station", "score": 2, "title": "Argo 6904216",
                 "fact": "Argo 6904216 (8 nm)", "nm": 8, "source": "argo"},
                {"kind": "station", "score": 2, "title": "Argo 6901234",
                 "fact": "Argo 6901234 (2 nm)", "nm": 2, "source": "argo"},
            ], "moment": {"leg": {"from": "La Rochelle", "to": "Ajaccio (Corse)"}}},
            {"seq": 3, "t": "2026-05-24T12:51:00Z", "signature": "s3", "legIdx": 1, "changes": [
                {"kind": "escale", "score": 3, "title": "Arrivée à Ajaccio", "fact": "x"},
            ], "moment": {"leg": {"from": "La Rochelle", "to": "Ajaccio (Corse)"}}},
        ],
        "latest": [],
    }
    plan = build_raw_script(CLOCK, CLOCK["marks"], LIVE, moments, lang="fr", seconds=0, now_ms=NOW_MS)
    blob = _script_blob(plan)
    assert "Bacteria" not in blob
    assert "stations scientifiques croisées" not in blob
    # Au plus UN flotteur par jambe, dit avec son identifiant.
    assert "un flotteur Argo" not in blob
    assert blob.count("flotteur Argo") <= 1
    if "flotteur Argo" in blob:
        assert "le flotteur Argo 6901234" in blob
    assert "6904216" not in blob


def _rg6_review():
    return {
        "legs": [
            {
                "from": "La Rochelle", "to": "Ajaccio (Corse)",
                "legNm": 1820, "daysAtSea": 9.5, "plannedKnots": 8,
            },
            {
                "from": "Ajaccio (Corse)", "to": "Fort-de-France (Martinique)",
                "legNm": 5153, "daysAtSea": 26.8, "plannedKnots": 8,
            },
            {
                "from": "Fort-de-France (Martinique)", "to": "Nouméa (Nouvelle-Calédonie)",
                "legNm": 12082, "daysAtSea": 63.0, "plannedKnots": 8,
            },
        ]
    }


def test_rg6_de_never_doubles():
    assert _de("Fineveke") == "de Fineveke"
    assert _de("de Fineveke") == "de Fineveke"
    assert "de de" not in _de("de Fineveke")
    assert _de("Ajaccio").startswith("d’") or _de("Ajaccio").startswith("d'")
    assert _de("Papeete") == "de Papeete"


def test_rg6_english_title_and_forbidden():
    assert looks_english_title("The Careenage")
    assert looks_english_title("Center Pertuis Breton deposit")
    assert looks_english_title("Laboratory Ship to Test Innovations in Extreme Conditions")
    assert looks_english_title("Coordination of a Global Socioeconomic Monitoring Initiative for Coastal Management")
    assert looks_english_title("Lesser Antilles Expedition")
    assert looks_english_title("Coral Gardeners")
    assert looks_english_title("Port Zante Marina")
    assert looks_english_title("IntelliReefs")
    assert not looks_english_title("port d'Ajaccio")
    assert not looks_english_title("Les Minimes")
    assert not looks_english_title("CÔTE À CÔTE")
    assert film_has_forbidden("À surveiller. Couloirs : Gibraltar. La jambe compte 12 milles.")
    assert film_has_forbidden("à portée de de Fineveke")
    assert not film_has_forbidden("Le 15 mai, Berry-Mappemonde quitte La Rochelle pour Ajaccio.")


def test_rg6_spoken_sea_days_and_date_thin():
    assert spoken_sea_days(9.5, "fr") == "une dizaine de jours de mer"
    assert spoken_sea_days(1.0, "fr") == "un jour de mer"
    assert spoken_sea_days(26.8, "fr") == "une trentaine de jours de mer"
    thinned = thin_chapter_dates([
        "Le 15 mai, Berry-Mappemonde quitte La Rochelle pour Ajaccio : 1 820 milles.",
        "Le 16 mai, les eaux espagnoles.",
        "Le 18 mai, les eaux portugaises.",
        "Arrivée à Ajaccio le 26 mai, amarré au port d'Ajaccio : trois jours d'escale.",
    ], "fr")
    assert "Le 15 mai" in thinned[0]
    assert not re.search(r"\b16 mai\b", thinned[1])
    assert "lendemain" in thinned[1].lower() or thinned[1].startswith("Puis")
    assert date_density_ok(" ".join(thinned), "fr")


def test_rg6_chapter_shape_and_metrics():
    w_long = {
        "fromName": "Ajaccio (Corse)", "toName": "Fort-de-France (Martinique)",
        "from": {"name": "Ajaccio (Corse)", "nm": 1820},
        "to": {"name": "Fort-de-France (Martinique)", "nm": 6973},
        "mode": "sail", "vehicle": "main",
    }
    m = chapter_metrics(w_long, _rg6_review())
    assert m["legNm"] == 5153
    assert m["daysAtSea"] == 26.8
    assert m["plannedKnots"] == 8
    assert chapter_shape(w_long, 2, 4, m) == "long"
    w_hop = {
        "fromName": "Fort-de-France", "toName": "Pointe-à-Pitre",
        "from": {"name": "Fort-de-France", "nm": 100},
        "to": {"name": "Pointe-à-Pitre", "nm": 292},
        "mode": "sail",
    }
    mh = chapter_metrics(w_hop, None)
    assert mh["legNm"] == 192
    assert chapter_shape(w_hop, 3, 8, mh) == "hop"


def test_rg6_gabarit_opening_route_arrival():
    journal = {
        "moments": [
            {"seq": 0, "t": "2026-05-15T08:00:00Z", "signature": "s0", "legIdx": 0, "changes": [],
             "moment": {"leg": {"from": "Saint-Maur", "to": "La Rochelle"}}},
            {"seq": 1, "t": "2026-05-15T12:00:00Z", "signature": "s1", "legIdx": 0, "changes": [
                {"kind": "escale", "score": 3, "title": "Arrivée à La Rochelle", "fact": "x"},
            ], "moment": {"leg": {"from": "Saint-Maur", "to": "La Rochelle"}}},
            {"seq": 2, "t": "2026-05-15T13:00:00Z", "signature": "s2", "legIdx": 1, "changes": [],
             "moment": {"leg": {"from": "La Rochelle", "to": "Ajaccio (Corse)", "headingDeg": 246}}},
            {"seq": 3, "t": "2026-05-16T08:00:00Z", "signature": "s3", "legIdx": 1, "changes": [
                {"kind": "zee-enter", "score": 2, "title": "Spanish Exclusive Economic Zone",
                 "fact": "Spanish Exclusive Economic Zone"},
            ], "moment": {"leg": {"from": "La Rochelle", "to": "Ajaccio (Corse)", "headingDeg": 246}}},
            {"seq": 4, "t": "2026-05-16T12:00:00Z", "signature": "s4", "legIdx": 1, "changes": [
                {"kind": "coast", "score": 2, "title": "Camariñas", "fact": "Camariñas (4 nm)"},
            ], "moment": {"leg": {"from": "La Rochelle", "to": "Ajaccio (Corse)"}}},
            {"seq": 5, "t": "2026-05-21T08:00:00Z", "signature": "s5", "legIdx": 1, "changes": [
                {"kind": "marina", "score": 2, "title": "port d'Ajaccio", "fact": "port d'Ajaccio (1 nm)",
                 "lat": 41.92, "lon": 8.74},
            ], "moment": {"leg": {"from": "La Rochelle", "to": "Ajaccio (Corse)"}}},
            {"seq": 6, "t": "2026-05-24T12:51:00Z", "signature": "s6", "legIdx": 1, "changes": [
                {"kind": "escale", "score": 3, "title": "Arrivée à Ajaccio", "fact": "x"},
            ], "moment": {"leg": {"from": "La Rochelle", "to": "Ajaccio (Corse)"}}},
        ],
        "latest": [],
    }
    plan = build_raw_script(
        CLOCK, CLOCK["marks"], LIVE, journal, lang="fr", seconds=0, now_ms=NOW_MS,
        review=_rg6_review(),
    )
    ch = next(c for c in plan["chapters"] if "Ajaccio" in (c.get("toName") or c.get("text") or ""))
    text = ch["text"]
    assert re.search(r"Berry-Mappemonde quitte La Rochelle", text)
    assert "cap au sud-ouest" in text
    assert "1 820 milles" in text
    assert "dizaine de jours de mer" in text
    assert "8 nœuds de moyenne" in text
    assert "eaux espagnoles" in text
    assert "Arrivée à Ajaccio" in text
    assert "port d'Ajaccio" in text or "port d’Ajaccio" in text
    assert "à quai" not in text
    assert "À surveiller" not in text
    assert "Couloirs" not in text
    assert "La jambe" not in text
    assert "à portée de" not in text
    assert not film_has_forbidden(text)
    assert date_density_ok(text, "fr")
    sents = [s for s in re.split(r"(?<=[.!?…])\s+", text) if s.strip()]
    assert any("quitte" in s for s in sents)
    assert any("eaux" in s or "Galice" in s or "Camariñas" in s for s in sents)
    assert any(s.startswith("Arrivée") for s in sents)


def test_rg6_all_sail_chapters_have_distance_days_no_jargon():
    plan = build_raw_script(
        CLOCK, CLOCK["marks"], LIVE, {**JOURNAL, **MOMENTS},
        lang="fr", seconds=0, now_ms=NOW_MS, review=_rg6_review(),
    )
    blob = _script_blob(plan)
    assert not film_has_forbidden(blob)
    assert "3 jours à quai" not in blob
    assert blob.count("à quai") == 0
    hold_forms = set()
    for ch in plan["chapters"]:
        text = ch.get("text") or ""
        assert date_density_ok(text, "fr"), text
        if not is_sea_chapter(ch):
            continue
        if _is_airish(ch):
            continue
        assert re.search(r"\d[\d\s]*\s*milles", text), text
        assert re.search(
            r"jours de mer|jour de mer|dizaine de jours|vingtaine|trentaine|quarantaine",
            text,
        ), text
        if "Arrivée à" in text:
            for form in ("d'escale", "escale de", "au port", "on reste"):
                if form in text:
                    hold_forms.add(form)
    assert "Berry-Mappemonde quitte" in blob


def _is_airish(ch: dict) -> bool:
    t = ch.get("text") or ""
    return "s'envole" in t or "flies" in t


def test_rg6_hold_silent_when_clock_does_not_stop():
    from film_script import _arrival_sentence
    stop = {
        "name": "La Rochelle", "iso": "2026-05-15T12:00:00Z", "holdHours": 72,
        "lat": 46.15, "lon": -1.16,
    }
    clock = {
        "vertices": [
            {"iso": "2026-05-15T12:00:00Z", "lat": 46.15, "lon": -1.16, "vehicle": "main"},
            {"iso": "2026-05-15T13:00:00Z", "lat": 46.10, "lon": -1.30, "vehicle": "main"},
        ]
    }
    sent = _arrival_sentence(stop, "fr", clock=clock, harbor="le port de La Rochelle", chapter_i=0)
    assert "Arrivée à La Rochelle" in sent
    assert "escale" not in sent
    assert "à quai" not in sent


def test_rg6_arrival_harbor_ignores_far_marina():
    dest = {"name": "Ajaccio (Corse)", "lat": 41.92, "lon": 8.74}
    far = {"kind": "marina", "title": "Porto de Barizo", "lat": 43.32, "lon": -8.87, "tMs": 1}
    near = {"kind": "marina", "title": "port d'Ajaccio", "lat": 41.92, "lon": 8.74, "tMs": 2}
    spoken = _arrival_harbor([far, near], dest, "fr")
    assert "Ajaccio" in spoken
    assert "Barizo" not in spoken
    only_far = _arrival_harbor([far], dest, "fr")
    assert "Ajaccio" in only_far
    assert "Barizo" not in only_far


def _rg7_review():
    """Plan-review de test : chiffres lus tels quels, jamais servis au poste."""
    return {
        "legs": [
            {"from": "Saint-Maur", "to": "La Rochelle", "legNm": 0},
            {"from": "La Rochelle", "to": "Ajaccio (Corse)", "legNm": 1820},
            {"from": "Ajaccio (Corse)", "to": "Fort-de-France (Martinique)", "legNm": 5153},
            {"from": "Fort-de-France (Martinique)", "to": "Nouméa (Nouvelle-Calédonie)", "legNm": 12082},
            {"from": "Nouméa (Nouvelle-Calédonie)", "to": "Dzaoudzi (Mayotte)", "legNm": 9152},
            {"from": "Dzaoudzi (Mayotte)", "to": "Europa", "legNm": 400},
            {"from": "Europa", "to": "Tromelin", "legNm": 300},
            {"from": "Tromelin", "to": "La Réunion", "legNm": 250},
        ]
    }


def _rg7_eta():
    return {
        "stops": {
            "Nouméa (Nouvelle-Calédonie)": {
                "members": 24,
                "p10": "2026-10-03T00:00:00Z",
                "p50": "2026-10-05T00:00:00Z",
                "p90": "2026-10-08T00:00:00Z",
            }
        }
    }


def test_rg7_plan_stats_sum_and_count():
    stats = review_plan_stats(_rg7_review())
    assert stats["nStops"] == 8
    assert stats["totalNm"] == 1820 + 5153 + 12082 + 9152 + 400 + 300 + 250
    assert stats["finalDest"] == "La Réunion"
    assert review_plan_stats(None)["nStops"] is None
    assert review_plan_stats({"legs": []})["totalNm"] is None


def test_rg7_upcoming_from_current_and_air_skipped():
    review = _rg7_review()
    names = upcoming_stop_names(review, "Nouméa (Nouvelle-Calédonie)", arrived=False)
    assert names == ["Nouméa", "Dzaoudzi", "Europa", "Tromelin", "La Réunion"]
    after = upcoming_stop_names(review, "Nouméa", arrived=True)
    assert after == ["Dzaoudzi", "Europa", "Tromelin", "La Réunion"]
    assert upcoming_stop_names(review, "Inconnu") == []
    with_air = {
        "legs": [
            {"from": "Cayenne", "to": "Halifax (Nouvelle-Écosse)", "legNm": 10},
            {"from": "Cayenne", "to": "Nouméa (Nouvelle-Calédonie)", "legNm": 100},
        ]
    }
    assert upcoming_stop_names(with_air, "Nouméa") == ["Nouméa"]


def test_rg7_eta_payload_requires_members():
    assert eta_payload_for_stop(_rg7_eta(), "Nouméa")["p10"].startswith("2026-10-03")
    empty = {"stops": {"Nouméa": {"members": 0, "p10": "2026-10-01T00:00:00Z", "p90": "2026-10-02T00:00:00Z"}}}
    assert eta_payload_for_stop(empty, "Nouméa") is None
    assert eta_payload_for_stop(None, "Nouméa") is None


def test_rg7_opening_uses_plan_review_totals():
    review = _rg7_review()
    stats = review_plan_stats(review)
    opens = _film_open_sentences(
        start_name="Saint-Maur", sea_name="La Rochelle", lang="fr", review=review,
    )
    blob = " ".join(opens)
    assert "Berry-Mappemonde" in blob
    assert "Saint-Maur" in blob
    assert "La Rochelle" in blob
    assert "par la route" in blob
    assert "15 mai 2026" in blob
    assert "huit escales" in blob
    assert "29 157 milles" in blob
    assert "La Réunion" in blob
    assert stats["totalNm"] == 29157
    plan = build_raw_script(
        CLOCK, CLOCK["marks"], LIVE, {**JOURNAL, **MOMENTS},
        lang="fr", seconds=0, now_ms=NOW_MS, review=review,
    )
    text0 = plan["chapters"][0]["text"]
    assert "L’expédition Berry-Mappemonde a quitté Saint-Maur" in text0 or "L'expédition Berry-Mappemonde a quitté Saint-Maur" in text0
    assert "par la route jusqu" in text0
    assert "huit escales" in text0
    assert "29 157 milles" in text0
    assert "La Réunion" in text0


def test_rg10_chapter_zero_opening_survives_150_budget():
    from film_script import _chapter_structure_fault_sentence

    plan = build_raw_script(
        CLOCK, CLOCK["marks"], LIVE, JOURNAL, lang="fr", seconds=150, now_ms=NOW_MS,
    )
    ch0 = (plan.get("chapters") or [{}])[0].get("text") or ""
    assert _chapter_structure_fault_sentence(ch0, "fr") is None
    assert "Berry-Mappemonde" in ch0
    assert "par la route" in ch0


def test_rg7_opening_silent_on_missing_review_numbers():
    opens = _film_open_sentences(
        start_name="Saint-Maur", sea_name="La Rochelle", lang="fr", review=None,
    )
    blob = " ".join(opens)
    assert "Berry-Mappemonde" in blob
    assert "Saint-Maur" in blob
    assert "par la route" in blob
    assert "Le plan compte" not in blob
    assert "escales" not in blob
    assert "milles" not in blob
    plan = build_raw_script(CLOCK, CLOCK["marks"], LIVE, JOURNAL, lang="fr", seconds=150, now_ms=NOW_MS)
    text0 = plan["chapters"][0]["text"]
    assert "Le plan compte" not in text0


def test_rg7_opening_english():
    opens = _film_open_sentences(
        start_name="Saint-Maur", sea_name="La Rochelle", lang="en", review=_rg7_review(),
    )
    blob = " ".join(opens)
    assert "Berry-Mappemonde expedition left Saint-Maur" in blob
    assert "15 May 2026" in blob
    assert "by road to La Rochelle" in blob
    assert "eight stops" in blob
    assert "29,157 miles" in blob
    assert "La Réunion" in blob
    assert "quitté" not in blob


def test_rg7_close_eta_range_and_upcoming():
    review = _rg7_review()
    eta = _rg7_eta()
    w = {
        "destName": "Nouméa (Nouvelle-Calédonie)", "toName": "Nouméa (Nouvelle-Calédonie)",
        "destNm": 19055, "arrived": False,
    }
    live = {"sailNm": 18000, "filmNm": 18000, "status": "live"}
    close = _close_sentence(w, live, "fr", review=review, eta=eta)
    assert "Aujourd’hui" in close or "Aujourd'hui" in close
    assert "Nouméa" in close
    assert "entre le 3 octobre et le 8 octobre" in close
    assert "Les escales à venir :" in close
    assert close.index("Nouméa") < close.index("Dzaoudzi")
    assert "Dzaoudzi" in close and "Europa" in close and "Tromelin" in close and "La Réunion" in close
    plan = build_raw_script(
        CLOCK, CLOCK["marks"], live, {**JOURNAL, **MOMENTS},
        lang="fr", seconds=0, now_ms=NOW_MS, review=review, eta=eta,
    )
    last = plan["chapters"][-1]["text"]
    assert "entre le 3 octobre et le 8 octobre" in last
    assert "Les escales à venir :" in last
    assert "Dzaoudzi" in last


def test_rg7_close_no_invented_eta_when_missing():
    review = _rg7_review()
    w = {
        "destName": "Nouméa (Nouvelle-Calédonie)", "toName": "Nouméa (Nouvelle-Calédonie)",
        "destNm": 19055, "arrived": False,
    }
    live = {"sailNm": 18000, "filmNm": 18000}
    close = _close_sentence(w, live, "fr", review=review, eta=None)
    assert "entre le" not in close
    assert "octobre" not in close
    empty = {"stops": {"Nouméa": {"members": 0, "p10": "2026-11-01T00:00:00Z", "p90": "2026-11-04T00:00:00Z"}}}
    silent = _close_sentence(w, live, "fr", review=review, eta=empty)
    assert "novembre" not in silent
    assert "entre le" not in silent
    en_empty = _close_sentence(w, live, "en", review=review, eta=None)
    assert "between" not in en_empty.lower()
    assert "October" not in en_empty


def test_rg7_close_english_with_eta():
    close = _close_sentence(
        {
            "destName": "Nouméa (Nouvelle-Calédonie)",
            "toName": "Nouméa (Nouvelle-Calédonie)",
            "destNm": 19055, "arrived": False,
        },
        {"sailNm": 18000},
        "en",
        review=_rg7_review(),
        eta=_rg7_eta(),
    )
    assert "Today" in close
    assert "between 3 October and 8 October" in close
    assert "Stops still to come:" in close
    assert "Nouméa, Dzaoudzi, Europa, Tromelin, La Réunion" in close


def test_rg8_priority_tiers_and_char_budget():
    assert film_priority_tier(150) == 2
    assert film_priority_tier(180) == 3
    assert film_priority_tier(0) == 4
    assert film_char_budget(150) == 2250
    assert film_char_budget(180) == 2700
    assert film_char_budget(0) == 0
    assert film_estimated_seconds(2250) == 150
    assert film_estimated_seconds(0) == 0


def test_rg8_select_chapter_changes_by_tier():
    t0 = 0
    t1 = 10
    changes = [
        {"id": "esc", "kind": "escale", "score": 3, "tMs": 1, "title": "Arrivée à Ajaccio", "fact": "Ajaccio"},
        {"id": "zee", "kind": "zee-enter", "score": 2, "tMs": 2, "t": "2026-05-16T08:00:00Z",
         "title": "Spanish Exclusive Economic Zone", "fact": "Spanish Exclusive Economic Zone"},
        {"id": "amp", "kind": "amp", "score": 2, "tMs": 3, "nm": 8, "title": "Cabrera", "fact": "Cabrera"},
        {"id": "proj", "kind": "project", "score": 2, "tMs": 4, "nm": 12, "gold_on": True,
         "title": "Récif sentinelle", "fact": "Récif sentinelle"},
        {"id": "coa", "kind": "coast", "score": 2, "tMs": 5, "t": "2026-05-16T12:00:00Z",
         "title": "Camariñas", "fact": "Camariñas"},
        {"id": "cli", "kind": "climo", "score": 2, "tMs": 6, "t": "2026-05-18T08:00:00Z",
         "title": "alizés de nord-est", "fact": "alizés de nord-est",
         "event": "ne_trades", "regimeId": "ne_trades", "source": "atlas", "nature": "season",
         "windKnots": 15},
        {"id": "sta", "kind": "station", "score": 2, "tMs": 7, "nm": 2,
         "title": "Argo 6904216", "fact": "Argo 6904216", "source": "argo"},
    ]
    short = select_chapter_changes(changes, t0, t1, budget=True, tier=2)
    kinds_s = {c["kind"] for c in short}
    assert "escale" in kinds_s
    assert "zee-enter" in kinds_s
    assert "coast" not in kinds_s
    assert "climo" not in kinds_s
    assert "station" not in kinds_s
    assert {c["kind"] for c in short if c["kind"] in {"amp", "project"}} == {"amp", "project"}

    mid = select_chapter_changes(changes, t0, t1, budget=True, tier=3)
    kinds_m = {c["kind"] for c in mid}
    assert "coast" in kinds_m
    assert "climo" in kinds_m
    assert "station" not in kinds_m

    full = select_chapter_changes(changes, t0, t1, budget=False)
    kinds_f = {c["kind"] for c in full}
    assert "station" in kinds_f
    assert "coast" in kinds_f


def test_rg8_three_variants_strictly_increasing():
    a = _rich_raw(150)
    b = _rich_raw(180)
    c = _rich_raw(0)
    assert a["chars"] < b["chars"] < c["chars"]
    assert a["estimatedSeconds"] < b["estimatedSeconds"] <= c["estimatedSeconds"] or b["chars"] < c["chars"]
    cps = 15
    dur = a["chars"] / cps
    assert dur <= 150 * 1.1
    if c["chars"] >= film_char_budget(150):
        assert 150 * 0.9 <= dur
    blob150 = " ".join(ch.get("text") or "" for ch in a["chapters"])
    blob180 = " ".join(ch.get("text") or "" for ch in b["chapters"])
    assert "aliz" in blob180.lower() or "longe" in blob180 or "Galice" in blob180 or blob180 != blob150


# ── RG14 : ancres au mot ────────────────────────────────────────────────────


def test_rg14_anchor_at_place_name_minus_lookahead():
    text = "Le 21 mai, le détroit de Gibraltar entre Tanger et Algeciras."
    t_gib = 1_000
    out = chapter_anchors(text, [(text, t_gib, {"place": "Gibraltar", "kind": "coast"})], 0, 2_000, "fr")
    assert out
    name_at = text.find("Gibraltar")
    expect = max(0, name_at - FILM_VOICE_LOOKAHEAD_CHARS)
    assert abs(out[0]["charIdx"] - expect) <= 2
    assert out[0]["charIdx"] != 0 or name_at <= FILM_VOICE_LOOKAHEAD_CHARS
    assert _parse_iso_ms(out[0]["t"]) == t_gib


def test_rg14_duration_two_anchors_depart_first_arrive_last():
    text = "Le 15 mai, Berry-Mappemonde quitte La Rochelle. Arrivée à Ajaccio le 26 mai. Trois jours d'escale."
    t_dep, t_arr = 100_000, 900_000
    out = chapter_anchors(
        text,
        [
            ("Le 15 mai, Berry-Mappemonde quitte La Rochelle.", t_dep, {"role": "depart", "place": "La Rochelle"}),
            ("Arrivée à Ajaccio le 26 mai. Trois jours d'escale.", t_arr, {"role": "arrive", "place": "Ajaccio"}),
        ],
        0,
        1_000_000,
        "fr",
    )
    idxs = [a["charIdx"] for a in out]
    assert idxs == sorted(idxs)
    assert idxs[0] == 0
    hold = text.find("Trois jours")
    hold_end = text.rfind("escale")
    hold_anchors = [a for a in out if a["charIdx"] >= hold - 2]
    assert len(hold_anchors) >= 2, out
    assert hold_anchors[0]["charIdx"] <= hold + 2
    assert hold_anchors[-1]["charIdx"] >= hold_end - FILM_VOICE_LOOKAHEAD_CHARS - 2
    arrive = text.find("Arrivée")
    last_arr = text.find("mai", arrive)
    arrive_hit = [a for a in out if arrive <= a["charIdx"] < hold]
    assert arrive_hit
    assert arrive_hit[0]["charIdx"] >= last_arr - FILM_VOICE_LOOKAHEAD_CHARS - 2
    times = [_parse_iso_ms(a["t"]) for a in out]
    assert times == sorted(times)
    assert times[0] == t_dep
    assert times[-1] == t_arr


def test_rg14_group_dated_at_closest_or_split():
    from film_script import _group_changes

    t0 = 0
    far = {"id": "a", "kind": "wx", "score": 2, "tMs": 10, "lat": 46.15, "lon": -1.16, "t": "1970-01-01T00:00:00Z"}
    mid = {"id": "b", "kind": "wx", "score": 2, "tMs": 20, "lat": 36.14, "lon": -5.35, "t": "1970-01-01T00:00:20Z"}
    near = {"id": "c", "kind": "wx", "score": 2, "tMs": 30, "lat": 41.9, "lon": 8.7, "t": "1970-01-01T00:00:30Z"}
    clock = {
        "t0": "1970-01-01T00:00:00Z",
        "vertices": [{"iso": "1970-01-01T00:00:00Z", "lat": 36.2, "lon": -5.4}],
    }
    grouped = _group_changes([far, mid, near], 86_400_000, clock=clock)
    groups = [c for c in grouped if str(c.get("id") or "").startswith("group:")]
    assert len(groups) == 1
    assert groups[0]["tMs"] == mid["tMs"]

    exploded = _group_changes([far, mid, near], 86_400_000, clock=None)
    assert not any(str(c.get("id") or "").startswith("group:") for c in exploded)
    assert any(c.get("id") == "a" for c in exploded)


def test_rg14_anchor_position_on_example_moments():
    """Chaque ancre nommée : bateau à ≤ N nm du lieu (escale 5, marina 15, AMP/projet 30)."""
    t_gib = _ms("2026-05-21T12:00:00Z")
    t_aj = _ms("2026-05-24T12:51:00Z")
    lr = {"name": "La Rochelle", "iso": "2026-05-15T12:00:00Z", "holdHours": 72, "lat": 46.15, "lon": -1.16, "filmNm": 122, "nm": 0}
    aj = {"name": "Ajaccio (Corse)", "iso": "2026-05-24T12:51:00Z", "holdHours": 72, "lat": 41.9, "lon": 8.7, "filmNm": 1942, "nm": 1820}
    clock = {
        "t0": OFFICIAL_T0,
        "marks": [CLOCK["marks"][0], lr, aj],
        "vertices": [
            {"iso": "2026-05-15T12:00:00Z", "lat": 46.15, "lon": -1.16, "vehicle": "main"},
            {"iso": "2026-05-15T13:00:00Z", "lat": 46.14, "lon": -1.18, "vehicle": "main"},
            {"iso": "2026-05-21T12:00:00Z", "lat": 36.12, "lon": -5.40, "vehicle": "main"},
            {"iso": "2026-05-24T12:51:00Z", "lat": 41.90, "lon": 8.70, "vehicle": "quay"},
        ],
    }
    journal = {
        "moments": [
            {"seq": 0, "t": "2026-05-15T12:00:00Z", "changes": [
                {"kind": "escale", "score": 3, "title": "Arrivée à La Rochelle", "fact": "x"},
            ], "moment": {"leg": {"from": "Saint-Maur", "to": "La Rochelle"}}},
            {"seq": 1, "t": "2026-05-21T12:00:00Z", "changes": [
                {"kind": "coast", "score": 2, "title": "Algeciras", "fact": "Algeciras",
                 "ports": ["Tanger", "Algeciras"], "lat": 36.14, "lon": -5.35, "tMs": t_gib},
            ], "moment": {"leg": {"from": "La Rochelle", "to": "Ajaccio (Corse)"}}},
            {"seq": 2, "t": "2026-05-24T12:51:00Z", "changes": [
                {"kind": "escale", "score": 3, "title": "Arrivée à Ajaccio", "fact": "x"},
            ], "moment": {"leg": {"from": "La Rochelle", "to": "Ajaccio (Corse)"}}},
        ],
        "latest": [],
    }
    live = {"filmNm": 2000, "sailNm": 1900, "iso": "2026-05-25T00:00:00Z", "status": "live"}
    plan = build_raw_script(clock, clock["marks"], live, journal, lang="fr", seconds=0, now_ms=t_aj + 3_600_000)
    limits = {"escale": 5.0, "stop": 5.0, "depart": 5.0, "marina": 15.0, "amp": 30.0, "project": 30.0, "coast": 30.0}
    places = {
        "gibraltar": (36.14, -5.35),
        "tanger": (35.78, -5.81),
        "algeciras": (36.13, -5.45),
        "la rochelle": (46.15, -1.16),
        "ajaccio": (41.9, 8.7),
    }
    checked = 0
    for ch in plan["chapters"]:
        text = ch.get("text") or ""
        for a in ch.get("anchors") or []:
            t = _parse_iso_ms(a["t"])
            vert = min(clock["vertices"], key=lambda v: abs((_ms(v["iso"]) or 0) - t))
            kind = str(a.get("kind") or "")
            place = str(a.get("place") or "")
            slice_txt = text[max(0, int(a["charIdx"])): int(a["charIdx"]) + 48]
            blob = f"{place} {slice_txt}".casefold()
            coords = None
            for key, pair in places.items():
                if key in blob:
                    coords = pair
                    break
            if coords is None:
                continue
            d = _nm_between(coords[0], coords[1], vert["lat"], vert["lon"])
            cap = 5.0 if any(k in blob for k in ("rochelle", "ajaccio")) else limits.get(kind, 30.0)
            if "gibraltar" in blob or "tanger" in blob or "algeciras" in blob:
                cap = 30.0
            assert d is not None and d <= cap, (d, cap, place, slice_txt, vert, a)
            checked += 1
    assert checked >= 2
    gib_ch = next((c for c in plan["chapters"] if "Gibraltar" in (c.get("text") or "")), None)
    if gib_ch:
        text = gib_ch["text"]
        name_at = text.find("Gibraltar")
        expect = max(0, name_at - FILM_VOICE_LOOKAHEAD_CHARS)
        assert any(abs(int(a["charIdx"]) - expect) <= 8 for a in gib_ch.get("anchors") or []), gib_ch.get("anchors")


# ── RC22 : budget 2:30, AMP et projet gardés ─────────────────────────────────


def test_rc22_fit_chapter_text_keeps_amp_project_drops_p3():
    amp = "Le 16 mai, à dix milles, l'aire marine protégée Pertuis charentais - Rochebonne."
    proj = "Le 16 mai, à dix milles, le projet Récif sentinelle."
    head = "Le 15 mai, Berry-Mappemonde quitte La Rochelle, cap au sud-ouest."
    arrival = "Arrivée à Ajaccio le 26 mai."
    p3 = [
        "Le 17 mai, longe la Galice — Camariñas, Muxía.",
        "Le 18 mai, au sud du Cap-Vert, les alizés de nord-est s'installent : quinze nœuds, la moyenne de saison.",
        "Le 19 mai, un flotteur Argo.",
    ]
    extra = [f"Le {20 + i} mai, longe la côte — Port-{i}." for i in range(40)]
    waters = [
        "Le 16 mai, les eaux espagnoles.",
        "Le 17 mai, les eaux portugaises.",
        "Le 18 mai, les eaux marocaines.",
    ]
    blob = " ".join([head, *waters, *p3, *extra, amp, proj, arrival])
    budget = 320
    assert len(blob) > budget * 1.1
    out = fit_chapter_text(blob, budget, [], "fr")
    assert "Rochebonne" in out
    assert "Récif sentinelle" in out
    assert "le projet" in out
    assert "aire marine" in out
    assert "Arrivée à Ajaccio" in out
    assert "Berry-Mappemonde quitte" in out
    assert "Port-39" not in out
    assert "Port-20" not in out
    assert len(out) <= max(int(budget * 1.1), budget)
    en_amp = "On 16 May, ten miles away, the marine protected area Pertuis charentais - Rochebonne."
    en_proj = "On 16 May, ten miles away, project Récif sentinelle."
    en_blob = " ".join([
        "On 15 May, Berry-Mappemonde leaves La Rochelle, heading southwest.",
        *extra,
        en_amp, en_proj,
        "Arrival at Ajaccio on 26 May.",
    ])
    en_out = fit_chapter_text(en_blob, budget, [], "en")
    assert "Rochebonne" in en_out
    assert "Récif sentinelle" in en_out
    assert "marine protected area" in en_out
    assert "project " in en_out


def _rc22_rich_journal():
    zee_names = [
        n for n in OFFICIAL_ROUTE_ZEE_SOURCES
        if "Haute" not in n and "High" not in n and "Overlapping" not in n
    ][:24]
    start = datetime(2026, 6, 25, tzinfo=timezone.utc)
    extra = []
    for i, name in enumerate(zee_names):
        t = start.timestamp() + i * 86_400
        iso = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%dT08:00:00Z")
        extra.append({
            "seq": 100 + i, "t": iso, "signature": f"zee-rc22-{i}", "legIdx": 3,
            "changes": [{"kind": "zee-enter", "score": 2, "title": name, "fact": name}],
            "moment": {"leg": {
                "from": "Fort-de-France (Martinique)", "to": "Nouméa (Nouvelle-Calédonie)",
            }},
        })
    extra.append({
        "seq": 200, "t": "2026-05-16T10:00:00Z", "signature": "amp-rochebonne", "legIdx": 1,
        "changes": [{
            "kind": "amp", "score": 2, "title": "Pertuis charentais - Rochebonne",
            "fact": "Pertuis charentais - Rochebonne (10 nm)", "nm": 10,
        }],
        "moment": {"leg": {"from": "La Rochelle", "to": "Ajaccio (Corse)"}},
    })
    extra.append({
        "seq": 201, "t": "2026-05-16T14:00:00Z", "signature": "proj-recif", "legIdx": 1,
        "changes": [{
            "kind": "project", "score": 2, "title": "Récif sentinelle",
            "fact": "Récif sentinelle (10 nm)", "nm": 10, "gold_on": True,
        }],
        "moment": {"leg": {"from": "La Rochelle", "to": "Ajaccio (Corse)"}},
    })
    extra.append({
        "seq": 202, "t": "2026-07-02T12:00:00Z", "signature": "coast-p3", "legIdx": 3,
        "changes": [{
            "kind": "coast", "score": 2, "title": "Camariñas", "fact": "Camariñas (5 nm)",
        }],
        "moment": {"leg": {
            "from": "Fort-de-France (Martinique)", "to": "Nouméa (Nouvelle-Calédonie)",
        }},
    })
    moments = [m for m in MOMENTS["moments"] if "Cabrera" not in str(m)]
    return {**JOURNAL, "moments": moments + extra}


def test_rc22_rich_plan_150_seconds_keeps_amp_and_project():
    plan = build_raw_script(
        CLOCK, CLOCK["marks"], LIVE, _rc22_rich_journal(),
        lang="fr", seconds=150, now_ms=NOW_MS,
    )
    blob = _script_blob(plan)
    assert plan["targetSeconds"] == 150
    assert plan["chars"] / 15 <= 150 * 1.1
    assert "Rochebonne" in blob
    assert "Récif sentinelle" in blob
    assert "le projet" in blob
    assert "aire marine" in blob
    assert "Pétoncles" not in blob
    assert "deposit" not in blob.lower()
    assert "Chaluts" not in blob


# ── RC27 : gabarit compact 2:30, intégral inchangé ───────────────────────────


def test_rc27_compact_150_vs_full_integral():
    """2:30 : une phrase d'ouverture, arrivée courte ; l'intégral garde RG6."""
    review = _rg6_review()
    journal = {**JOURNAL, **MOMENTS}
    short = build_raw_script(
        CLOCK, CLOCK["marks"], LIVE, journal,
        lang="fr", seconds=150, now_ms=NOW_MS, review=review,
    )
    full = build_raw_script(
        CLOCK, CLOCK["marks"], LIVE, journal,
        lang="fr", seconds=0, now_ms=NOW_MS, review=review,
    )
    blob150 = _script_blob(short)
    blob0 = _script_blob(full)
    assert short["chars"] / 15 <= 150 * 1.1
    assert re.search(r"départ vers Fort-de-France : .+ milles", blob150)
    assert "jours de mer" in blob150
    assert "Berry-Mappemonde quitte Ajaccio" not in blob150
    assert "longue traversée vers" not in blob150
    assert "nœuds de moyenne" not in blob150
    assert not re.search(r"escale de |d['’]escale", blob150)
    assert re.search(r"Arrivée à .+ le \d+", blob150)
    assert "Berry-Mappemonde quitte" in blob0
    assert "nœuds de moyenne" in blob0
    assert "Arrivée à" in blob0
    for ch in short["chapters"]:
        for sent in re.split(r"(?<=[.!?…])\s+", ch.get("text") or ""):
            for name in ("Fort-de-France", "Ajaccio", "Nouméa"):
                assert sent.lower().count(name.lower()) <= 1, sent
    opens = _film_open_sentences(
        start_name="Saint-Maur", sea_name="La Rochelle", lang="fr",
        review=review, compact=True,
    )
    assert len(opens) == 1
    assert "par la route" in opens[0]
    assert "Le plan compte" not in opens[0]
    en = build_raw_script(
        CLOCK, CLOCK["marks"], LIVE, journal,
        lang="en", seconds=150, now_ms=NOW_MS, review=review,
    )
    blob_en = _script_blob(en)
    assert "departure for Fort-de-France" in blob_en
    assert "long crossing to" not in blob_en
    assert "knots on average" not in blob_en
    assert re.search(r"Arrival at .+ on ", blob_en)
    assert en["chars"] / 15 <= 150 * 1.1


def test_rc27_rich_150_keeps_amp_project_integral_gabarit_intact():
    journal = _rc22_rich_journal()
    review = _rg6_review()
    short = build_raw_script(
        CLOCK, CLOCK["marks"], LIVE, journal,
        lang="fr", seconds=150, now_ms=NOW_MS, review=review,
    )
    full = build_raw_script(
        CLOCK, CLOCK["marks"], LIVE, journal,
        lang="fr", seconds=0, now_ms=NOW_MS, review=review,
    )
    blob = _script_blob(short)
    blob0 = _script_blob(full)
    assert short["targetSeconds"] == 150
    assert short["chars"] / 15 <= 150 * 1.1
    assert "Rochebonne" in blob
    assert "Récif sentinelle" in blob
    assert "le projet" in blob
    assert "aire marine" in blob
    assert "Pétoncles" not in blob
    assert "deposit" not in blob.lower()
    assert "Chaluts" not in blob
    assert "Berry-Mappemonde quitte" in blob0
    assert "nœuds de moyenne" in blob0
    assert "Arrivée à" in blob0
    assert full["chars"] > short["chars"]


# ── RC26 : récit dense et réparti ───────────────────────────────────────────


def test_rc26_zee_group_waters_grammar_fr_en():
    """« les eaux françaises, puis celles de Montserrat » — jamais d'adjectif
    orphelin ni de minuscule en tête de nom (recette Antilles)."""
    from film_script import zee_group_waters

    members = [
        "Zone économique exclusive de la Dominique",
        "Zone économique exclusive française",
        "Zone économique exclusive (Montserrat)",
    ]
    fr = zee_group_waters(members, "fr")
    assert "les eaux de la Dominique" in fr
    assert "les eaux françaises" in fr
    assert "celles de Montserrat" in fr
    assert ", puis " in fr
    # jamais « celles de françaises » ni « les eaux de montserrat » (minuscule)
    assert "celles de française" not in fr
    assert "de montserrat" not in fr
    en = zee_group_waters(members, "en")
    # EN : toujours « … waters », jamais « those of Montserratian »
    assert "waters" in en
    assert ", then " in en
    assert "those of" not in en


def test_rc26_film_free_item_target_floor_and_cap():
    from film_script import film_free_item_target

    day = 86_400_000
    assert film_free_item_target(1 * day) == 4      # plancher
    assert film_free_item_target(9 * day) == 6      # 1 item / 1,5 jour
    assert film_free_item_target(30 * day) == 16    # plafonné
    assert film_free_item_target(90 * day) == 16


def test_rc26_initial_heading_follows_track_not_port_maneuver():
    """La Rochelle → Ajaccio : la trace part au sud — jamais « nord-ouest »
    à cause des manœuvres de port."""
    from film_script import _initial_route_heading, heading_phrase

    day_h = 24.0
    vertices = [
        # manœuvre de port vers le nord-ouest sur le premier mille
        {"tHours": 0.0, "lat": 46.15, "lon": -1.16, "vehicle": "main"},
        {"tHours": 0.2, "lat": 46.16, "lon": -1.18, "vehicle": "main"},
        # puis la vraie route : plein sud sur 60 milles
        {"tHours": 4.0, "lat": 45.80, "lon": -1.30, "vehicle": "main"},
        {"tHours": 12.0, "lat": 45.10, "lon": -1.40, "vehicle": "main"},
        {"tHours": day_h, "lat": 44.40, "lon": -1.50, "vehicle": "main"},
    ]
    clock = {"t0": "2026-05-15T08:00:00Z", "vertices": vertices}
    t0_ms = _ms("2026-05-15T08:00:00Z")
    deg = _initial_route_heading(clock, t0_ms, nm=30.0)
    assert deg is not None
    phrase = heading_phrase(deg, "fr")
    assert "nord-ouest" not in phrase
    assert "sud" in phrase


def test_rc26_site_dedup_shortest_name_wins():
    """« Lilleau-des-Niges » et « Lilleau-des-Niges - Zone de Protection » :
    un seul jalon, le nom le plus court, au temps du premier croisement."""
    long_first = {
        "id": "a1", "kind": "amp", "score": 2, "tMs": 1_000,
        "title": "Lilleau-des-Niges - Zone de Protection",
        "fact": "Lilleau-des-Niges - Zone de Protection (4,9 nm)",
    }
    short_after = {
        "id": "a2", "kind": "amp", "score": 2, "tMs": 2_000,
        "title": "Lilleau-des-Niges", "fact": "Lilleau-des-Niges (4.9 nm)",
    }
    from film_script import _usable_changes

    rows = _usable_changes([long_first, short_after])
    hits = [c for c in rows if "Lilleau" in str(c.get("title") or "")]
    assert len(hits) == 1
    assert hits[0]["title"] == "Lilleau-des-Niges"
    assert hits[0]["tMs"] == 1_000  # premier croisement conservé


def test_rc26_dock_keeps_at_most_two_items_one_proximity():
    """Au quai : plus jamais six phrases — au plus deux, dont UNE de proximité."""
    day = 86_400_000
    t_a, depart, t_b = 0, day, 11 * day
    changes = [
        {"id": f"amp{i}", "kind": "amp", "score": 2, "tMs": 1000 + i,
         "title": f"Réserve du pertuis {i}", "fact": f"Réserve du pertuis {i} (5 nm)"}
        for i in range(4)
    ] + [
        {"id": "proj", "kind": "project", "score": 2, "tMs": 2000,
         "title": "Projet balise côtière", "fact": "Projet balise côtière (6 nm)"},
        {"id": "sta", "kind": "station", "score": 2, "tMs": 3000,
         "title": "Campagne PELGAS", "fact": "Campagne PELGAS (5 nm)", "source": "campaign"},
        {"id": "zee1", "kind": "zee-enter", "score": 2, "tMs": 3 * day,
         "title": "Zone économique exclusive espagnole", "fact": "x"},
        {"id": "zee2", "kind": "zee-enter", "score": 2, "tMs": 6 * day,
         "title": "Zone économique exclusive portugaise", "fact": "y"},
    ]
    out = select_chapter_changes(changes, t_a, t_b, budget=False, depart_ms=depart)
    dock = [c for c in out if (c.get("tMs") or 0) <= depart]
    assert len(dock) <= 2
    proximity = [c for c in dock if c.get("kind") in {"amp", "alert-on", "project", "marina"}]
    assert len(proximity) <= 1
    # la mer n'est pas muette pour autant
    assert any((c.get("tMs") or 0) > depart for c in out)


# ---------------------------------------------------------------------------
# Le film dit les choses dans l'ordre, et finit ses phrases
# (revue du porteur, 14 oct.).
# ---------------------------------------------------------------------------

def test_rc30_order_chapter_sentences_sorts_by_anchor():
    """Un chapitre riche : les phrases se disent dans l'ordre STRICT des ancres —
    l'ouverture reste en tête, l'arrivée en queue, les bulles suivent."""
    from film_script import _bits_offsets, _order_chapter_sentences

    day = 86_400_000
    bits = [
        "Le 15 mai, Berry-Mappemonde quitte La Rochelle, cap au sud-ouest.",
        "Le 19 mai, le vent tourne au nord.",
        "Le 18 mai, les eaux portugaises.",
        "La route passe par golfe de Gascogne.",
        "Arrivée à Ajaccio le 26 mai.",
    ]
    anchored = [
        (bits[0], 0, {"role": "depart"}),
        (bits[1], 4 * day, {"kind": "climo"}),
        (bits[2], 3 * day, {"kind": "zee-enter", "place": "les eaux portugaises"}),
        (bits[3], 1 * day, {"kind": "coast"}),
        (bits[4], 11 * day, {"role": "arrive", "place": "Ajaccio", "kind": "escale"}),
    ]
    offsets = _bits_offsets(bits)
    placed = [
        {"id": "climo", "charIdx": offsets[1]},
        {"id": "zee", "charIdx": offsets[2]},
    ]
    _order_chapter_sentences(bits, anchored, placed)
    assert bits[0].startswith("Le 15 mai, Berry-Mappemonde quitte")
    assert bits[-1].startswith("Arrivée à Ajaccio")
    assert bits[1] == "La route passe par golfe de Gascogne."
    assert bits[2] == "Le 18 mai, les eaux portugaises."
    assert bits[3] == "Le 19 mai, le vent tourne au nord."
    # les ancres suivent leurs phrases, et leurs instants sont croissants
    times = [a[1] for a in anchored]
    assert times == sorted(times)
    # les bulles pointent toujours le premier caractère de LEUR phrase
    new_off = _bits_offsets(bits)
    assert placed[0]["charIdx"] == new_off[3]
    assert placed[1]["charIdx"] == new_off[2]


def test_rc30_lendemain_only_when_day_changes_by_one():
    """« Le lendemain » seulement si le jour change bien de +1 — jamais en
    première phrase, jamais mesuré contre l'arrivée qui suit."""
    # avant l'arrivée : la phrase amincie se mesure contre la date dite AVANT elle
    out = thin_chapter_dates([
        "Le 15 mai, Berry-Mappemonde quitte La Rochelle.",
        "Le 19 mai, les eaux portugaises.",
        "Arrivée à Ajaccio le 20 mai.",
    ], "fr")
    assert not any(s.startswith("Le lendemain") for s in out)
    # le vrai lendemain, lui, se dit
    out = thin_chapter_dates([
        "Le 18 mai, les eaux espagnoles.",
        "Le 19 mai, les eaux portugaises.",
        "Arrivée à Ajaccio le 26 mai.",
    ], "fr")
    assert any(s.startswith("Le lendemain") for s in out)
    # sans date dite avant elle, une phrase ne devient jamais « Le lendemain »
    out = thin_chapter_dates([
        "Le 19 mai, les eaux portugaises.",
        "Arrivée à Ajaccio le 20 mai.",
    ], "fr")
    assert not out[0].startswith("Le lendemain")


def test_rc30_lane_crossings_filter_and_order():
    """« La route passe par … » : seuls les bassins que la TRACE du chapitre
    croise, dans l'ordre de la route — Papeete n'entend plus « Atlantique
    nord » hérité de la jambe de revue."""
    from film_script import _lane_crossings

    clock = {
        "t0": "2026-07-28T08:00:00Z",
        "vertices": [
            {"iso": "2026-07-28T08:00:00Z", "lat": 4.9, "lon": -52.3, "vehicle": "main"},
            {"iso": "2026-08-02T08:00:00Z", "lat": 9.5, "lon": -79.9, "vehicle": "main"},
            {"iso": "2026-08-20T08:00:00Z", "lat": -17.5, "lon": -149.6, "vehicle": "main"},
        ],
    }
    t_a = _ms("2026-07-28T00:00:00Z")
    t_b = _ms("2026-08-25T00:00:00Z")
    crossings = _lane_crossings(clock, t_a, t_b)
    assert crossings is not None
    assert "caribbean w" in crossings
    assert "n atlantic main" not in crossings
    leg = {
        "from": "Cayenne", "to": "Papeete",
        "antiShipping": {"score": 0.7, "lanes": ["N Atlantic main", "Caribbean W"]},
    }
    bits = review_sentences(leg, "fr", crossings=crossings)
    lane_sent = next(s for s in bits if "passe par" in s)
    assert "Caraïbe ouest" in lane_sent
    assert "Atlantique nord" not in lane_sent
    # sans trace (horloge muette), la revue reste entière — rien n'est perdu
    bits_all = review_sentences(leg, "fr", crossings=None)
    lane_all = next(s for s in bits_all if "passe par" in s)
    assert "Atlantique nord" in lane_all


def test_rc30_lane_sentence_anchored_at_crossing_not_arrival():
    """La phrase des bassins est ancrée au premier croisement : triée par
    ancre, elle se dit en route, jamais collée à l'arrivée."""
    from film_script import _append_review_sentences, _order_chapter_sentences

    clock = {
        "t0": "2026-07-28T08:00:00Z",
        "vertices": [
            {"iso": "2026-07-28T08:00:00Z", "lat": 4.9, "lon": -52.3, "vehicle": "main"},
            {"iso": "2026-08-02T08:00:00Z", "lat": 9.5, "lon": -79.9, "vehicle": "main"},
            {"iso": "2026-08-20T08:00:00Z", "lat": -17.5, "lon": -149.6, "vehicle": "main"},
        ],
    }
    t_a = _ms("2026-07-28T00:00:00Z")
    t_b = _ms("2026-08-25T00:00:00Z")
    window = {"clock": clock, "tA": t_a, "tB": t_b, "fromName": "Cayenne", "toName": "Papeete"}
    review = {"legs": [{
        "from": "Cayenne", "to": "Papeete",
        "antiShipping": {"score": 0.7, "lanes": ["Caribbean W"]},
    }]}
    bits = [
        "Le 28 juillet, Berry-Mappemonde quitte Cayenne.",
        "Le 15 août, les eaux de la Polynésie française.",
    ]
    anchored = [
        (bits[0], t_a, {"role": "depart"}),
        (bits[1], _ms("2026-08-15T08:00:00Z"), {"kind": "zee-enter"}),
    ]
    _append_review_sentences(bits, review, window, "fr", anchored)
    lane_idx = next(i for i, s in enumerate(bits) if "passe par" in s)
    assert anchored[lane_idx][1] == _ms("2026-08-02T08:00:00Z")
    _order_chapter_sentences(bits, anchored, [])
    lane_idx = next(i for i, s in enumerate(bits) if "passe par" in s)
    poly_idx = next(i for i, s in enumerate(bits) if "Polynésie" in s)
    assert lane_idx < poly_idx


def test_rc30_heading_ignores_plane_vertices_cayenne_papeete():
    """Le cap annoncé au départ d'une jambe est le cap initial de la TRACE —
    jamais celui du vol (Cayenne → Halifax plein nord)."""
    from film_script import _heading_deg_at, _leg_heading_deg

    depart = _ms("2026-07-28T08:00:00Z")
    clock = {
        "t0": "2026-07-10T08:00:00Z",
        "vertices": [
            # le vol, plein nord — jamais un cap de mer
            {"iso": "2026-07-12T08:00:00Z", "lat": 10.0, "lon": -53.0,
             "vehicle": "plane", "headingDeg": 356.0},
            {"iso": "2026-07-28T09:00:00Z", "lat": 4.94, "lon": -52.33,
             "vehicle": "main", "bearing": 300.0},
        ],
    }
    deg = _heading_deg_at(None, depart, clock=clock)
    assert deg == 300.0
    air_moment = {
        "t": "2026-07-28T07:00:00Z",
        "moment": {"leg": {"from": "Cayenne", "to": "Papeete",
                           "vehicle": "plane", "headingDeg": 356.0}},
    }
    deg = _leg_heading_deg([air_moment], depart, clock=clock)
    assert deg == 300.0
    assert "nord-ouest" in heading_phrase(deg, "fr")


def test_rc32_saint_martin_sint_maarten_distinguished():
    """Île partagée : les deux eaux se disent, distinguées —
    plus jamais « les eaux de Saint-Martin, puis celles de Saint-Martin »."""
    from film_script import zee_group_waters
    from toponyms import consecutive_homonyms

    members = [
        "Kittitian and Nevisian Exclusive Economic Zone",
        "Sint-Eustatius Exclusive Economic Zone",
        "Sint-Maarten Exclusive Economic Zone",
        "Saint-Martin Exclusive Economic Zone",
    ]
    fr = zee_group_waters(members, "fr")
    assert "Saint-Christophe-et-Niévès" in fr
    assert "Saint-Eustache" in fr
    assert "Sint Maarten (partie néerlandaise)" in fr
    assert "Saint-Martin (partie française)" in fr
    assert consecutive_homonyms(fr) == []
    en = zee_group_waters(members, "en")
    assert "Saint Kitts and Nevis" in en
    assert "Sint Eustatius" in en
    assert "Sint Maarten (Dutch side)" in en
    assert "Saint-Martin (French side)" in en
    assert consecutive_homonyms(en) == []
    # l'inverse : partie française puis néerlandaise, toujours deux formes
    fr2 = zee_group_waters(list(reversed(members[-2:])), "fr")
    assert "partie française" in fr2 and "partie néerlandaise" in fr2
    assert consecutive_homonyms(fr2) == []
    assert consecutive_homonyms(
        "les eaux de Saint-Martin, puis celles de Saint-Martin",
    )


def test_rc30_one_named_argo_per_leg():
    """Au plus un flotteur Argo par jambe, avec son identifiant — jamais six
    anonymes (transcription du porteur, 14 oct.)."""
    day = 86_400_000
    argos = [
        {"id": f"a{i}", "kind": "station", "score": 2, "tMs": (2 + 3 * i) * day,
         "title": f"Argo {6904210 + i}", "fact": f"Argo {6904210 + i} (4 nm)",
         "source": "argo", "nm": 4}
        for i in range(6)
    ]
    escale = {"id": "e", "kind": "escale", "score": 3, "tMs": 20 * day,
              "title": "Arrivée à Papeete", "fact": "x"}
    out = select_chapter_changes(argos + [escale], 0, 20 * day, budget=False, depart_ms=day)
    stations = [c for c in out if c.get("kind") == "station"]
    assert len(stations) == 1
    label = station_spoken_label(stations[0], "fr")
    assert label.startswith("le flotteur Argo ")
    assert re.search(r"\d{5,9}", label)


def test_rg11a_invented_number_falls_back_sentence_by_sentence():
    raw_text = (
        "Le 15 mai, Berry-Mappemonde quitte La Rochelle, cap au sud-ouest. "
        "Arrivée à Ajaccio le 26 mai."
    )
    chapter = {
        "id": "c0",
        "text": raw_text,
        "tA": "2026-05-15T08:00:00Z",
        "tB": "2026-05-26T12:00:00Z",
        "fromName": "La Rochelle",
        "toName": "Ajaccio (Corse)",
        "anchors": [
            {"charIdx": 0, "t": "2026-05-15T08:00:00Z"},
            {"charIdx": 70, "t": "2026-05-26T12:00:00Z"},
        ],
    }
    facts = chapter_structured_facts(chapter, lang="fr")
    written = (
        "Le 15 mai, Berry-Mappemonde quitte La Rochelle, cap au sud-ouest, 99 nœuds. "
        "Arrivée à Ajaccio le 26 mai."
    )
    guarded, rewritten, fallen = apply_written_guard(raw_text, written, facts, lang="fr")
    sents = [s for s in re.split(r"(?<=[.!?…])\s+", guarded) if s.strip()]
    raw_sents = [s for s in re.split(r"(?<=[.!?…])\s+", raw_text) if s.strip()]
    assert len(sents) == len(raw_sents)
    assert "99" not in guarded
    assert fallen >= 1
    assert rewritten >= 1
    assert sents[0] == raw_sents[0]


def test_rg11a_honest_write_has_increasing_anchors():
    raw_text = (
        "Le 15 mai, Berry-Mappemonde quitte La Rochelle, cap au sud-ouest. "
        "Arrivée à Ajaccio le 26 mai."
    )
    plan = {
        "chapters": [{
            "id": "c0",
            "text": raw_text,
            "tA": "2026-05-15T08:00:00Z",
            "tB": "2026-05-26T12:00:00Z",
            "fromName": "La Rochelle",
            "toName": "Ajaccio (Corse)",
            "anchors": [
                {"charIdx": 0, "t": "2026-05-15T08:00:00Z"},
                {"charIdx": 70, "t": "2026-05-26T12:00:00Z"},
            ],
        }],
        "targetSeconds": 150,
        "source": "rules",
    }

    async def fake_cascade(system, user, **kw):
        sents = _sentences_from_user(user)
        return " ".join(
            s.replace("quitte", "laisse", 1) if "quitte" in s else s for s in sents
        ), "nemotron-super"

    written, stats = asyncio.run(write_stored_plan(plan, lang="fr", cascade=fake_cascade))
    assert written is not None
    assert written["hasWritten"] is True
    assert written["source"] == WRITTEN_SOURCE
    assert stats["rewritten"] >= 1
    text = written["chapters"][0]["text"]
    raw_n = len([s for s in re.split(r"(?<=[.!?…])\s+", raw_text) if s.strip()])
    out_n = len([s for s in re.split(r"(?<=[.!?…])\s+", text) if s.strip()])
    assert out_n == raw_n
    assert "99" not in text
    anchors = written["chapters"][0]["anchors"]
    idxs = [int(a["charIdx"]) for a in anchors]
    assert idxs == sorted(idxs)
    assert len(set(idxs)) == len(idxs)
    assert "laisse" in text or "quitte" in text


def test_am1b_amp_enter_and_nearby_sentences():
    """Entrée → traverse ; nearby → près, à N milles. Circulation seulement si le stock l'a."""
    enter = {
        "kind": "amp", "event": "enter", "title": "Cabrera", "fact": "Cabrera",
        "t": "2026-05-25T12:00:00Z", "inside": True, "nm": 0,
    }
    fr = change_sentence(enter, "fr")
    en = change_sentence(enter, "en")
    assert "le bateau traverse l'aire marine protégée Cabrera" in fr
    assert "the boat crosses the marine protected area Cabrera" in en
    assert "circulation" not in fr
    assert "transit" not in en
    near = {
        "kind": "amp", "event": "nearby", "title": "Cabrera", "fact": "Cabrera (6 nm)",
        "t": "2026-05-25T12:00:00Z", "nm": 6,
    }
    nfr = change_sentence(near, "fr")
    nen = change_sentence(near, "en")
    assert "passe près de l'aire marine protégée Cabrera, à six milles" in nfr
    assert "passes near the marine protected area Cabrera, at six miles" in nen
    from film_script import CHANGE_PRIORITY
    assert CHANGE_PRIORITY["amp"] < CHANGE_PRIORITY["zee-enter"]


def test_am1b_two_inside_pearls_one_amp_sentence():
    """Deux perles dedans (même AMP) : une seule phrase."""
    from film_script import _usable_changes

    rows = _usable_changes([
        {
            "id": "a1", "kind": "amp", "event": "enter", "score": 2, "tMs": 1_000,
            "title": "Cabrera", "fact": "Cabrera", "siteId": "ES-CAB", "nm": 0, "inside": True,
        },
        {
            "id": "a2", "kind": "amp", "event": "enter", "score": 2, "tMs": 2_000,
            "title": "Cabrera", "fact": "Cabrera", "siteId": "ES-CAB", "nm": 0, "inside": True,
        },
    ])
    hits = [c for c in rows if "Cabrera" in str(c.get("title") or "")]
    assert len(hits) == 1
    assert change_sentence(hits[0], "fr").count("traverse") == 1


def test_phrase_for_ici_event_matches_film_zee():
    from film_script import event_sentence, phrase_for_ici_event

    t = "2026-05-26T08:00:00Z"
    film = event_sentence({
        "kind": "zee",
        "name": "Spanish Exclusive Economic Zone",
        "t": t,
        "entry": {"t": t, "name": "Spanish Exclusive Economic Zone"},
    }, "fr")
    ici = phrase_for_ici_event({
        "type": "zee-enter",
        "name": "Spanish Exclusive Economic Zone",
        "t": t,
        "payload": {"zee": {"name": "Spanish Exclusive Economic Zone", "mrgid": 5693}},
    }, "fr")
    assert ici == film
    assert ici
    assert "eaux" in ici.lower() or "espagn" in ici.lower()


def test_phrase_for_ici_event_matches_film_amp_enter():
    from film_script import event_sentence, phrase_for_ici_event

    t = "2026-06-02T08:00:00Z"
    film = event_sentence({
        "kind": "amp",
        "name": "Cabrera",
        "t": t,
        "entry": {"t": t, "name": "Cabrera", "event": "enter", "inside": True, "nm": 0, "facts": {"nm": 0}},
    }, "fr")
    ici = phrase_for_ici_event({
        "type": "amp-enter",
        "name": "Cabrera",
        "t": t,
        "payload": {"amp": {"name": "Cabrera", "site_id": "ES-CAB", "nm": 0}},
    }, "fr")
    assert ici == film
    assert "traverse l'aire marine protégée" in ici
    assert "Cabrera" in ici


def test_attach_ici_film_phrases_does_not_mutate_cache():
    from film_script import attach_ici_film_phrases

    bag = {
        "at": {"lat": 46.15, "lon": -1.16},
        "zee": {"name": "French Exclusive Economic Zone", "mrgid": 5677},
        "amp": [{"name": "Pertuis charentais", "site_id": "fr-pertuis", "nm": 8}],
        "poe": [{"name": "La Rochelle", "nm": 1.2}],
    }
    out = attach_ici_film_phrases(bag, t="2026-05-15T08:00:00Z")
    assert bag.get("filmPhrases") is None
    assert out is not bag
    assert out["filmPhrases"]["zee-enter"]["fr"]
    assert out["filmPhrases"]["zee-enter"]["en"]
    amp_fr = out["filmPhrases"]["amp-enter:fr-pertuis"]["fr"]
    assert "aire marine" in amp_fr.lower() or "Pertuis" in amp_fr
    assert out["filmPhrases"]["poe-ahead:La Rochelle"]["fr"]


# ---------------------------------------------------------------------------
# Eaux LR→Ajaccio dans l'ordre du voyage ; Papeete nomme le Pacifique
# (revue de nuit 15 oct. : Gascogne/Maroc absents, FR collé à la Corse).
# ---------------------------------------------------------------------------


def test_rc35_french_waters_biscay_not_merged_with_corsica():
    """Gascogne/Pertuis et Corse : deux phrases, deux ancres — pas une identité FR."""
    from film_script import _place_dedup_key, _usable_changes

    biscay = {
        "id": "fr-bis", "kind": "zee-enter", "score": 2,
        "title": "French Exclusive Economic Zone",
        "fact": "French Exclusive Economic Zone",
        "t": "2026-05-15T12:00:00Z", "tMs": _ms("2026-05-15T12:00:00Z"),
        "lat": 46.15, "lon": -1.16,
    }
    corse = {
        "id": "fr-med", "kind": "zee-enter", "score": 2,
        "title": "French Exclusive Economic Zone",
        "fact": "French Exclusive Economic Zone",
        "t": "2026-05-25T12:00:00Z", "tMs": _ms("2026-05-25T12:00:00Z"),
        "lat": 41.9, "lon": 8.7,
    }
    assert _place_dedup_key(biscay) != _place_dedup_key(corse)
    rows = _usable_changes([biscay, corse])
    assert len(rows) == 2
    assert {c["id"] for c in rows} == {"fr-bis", "fr-med"}


def test_rc35_spine_waters_kept_before_extra_amp_argo():
    """LR→Ajaccio : ES/PT/MA restent quand des AMP et des Argo surnuméraires
    se battent pour les fenêtres — horloge de jambe, pas un seed de stock."""
    t0 = _ms("2026-05-15T12:00:00Z")
    t_b = _ms("2026-05-26T12:00:00Z")
    day = 86_400_000
    waters = [
        {"id": "fr1", "kind": "zee-enter", "score": 2, "tMs": t0, "t": "2026-05-15T12:00:00Z",
         "title": "French Exclusive Economic Zone", "fact": "French Exclusive Economic Zone",
         "lat": 46.15, "lon": -1.16},
        {"id": "es", "kind": "zee-enter", "score": 2, "tMs": t0 + 1 * day, "t": "2026-05-16T12:00:00Z",
         "title": "Spanish Exclusive Economic Zone", "fact": "Spanish Exclusive Economic Zone",
         "lat": 43.0, "lon": -9.0},
        {"id": "pt", "kind": "zee-enter", "score": 2, "tMs": t0 + 3 * day, "t": "2026-05-18T12:00:00Z",
         "title": "Portuguese Exclusive Economic Zone", "fact": "Portuguese Exclusive Economic Zone",
         "lat": 39.0, "lon": -9.5},
        {"id": "ma", "kind": "zee-enter", "score": 2, "tMs": t0 + 6 * day, "t": "2026-05-21T12:00:00Z",
         "title": "Moroccan Exclusive Economic Zone", "fact": "Moroccan Exclusive Economic Zone",
         "lat": 35.6, "lon": -6.0},
        {"id": "fr2", "kind": "zee-enter", "score": 2, "tMs": t0 + 10 * day, "t": "2026-05-25T12:00:00Z",
         "title": "French Exclusive Economic Zone", "fact": "French Exclusive Economic Zone",
         "lat": 41.9, "lon": 8.7},
    ]
    extras = [
        {"id": f"amp{i}", "kind": "amp", "score": 2, "tMs": t0 + int(0.4 * i * day),
         "t": "2026-05-16T00:00:00Z", "title": f"Réserve {i}", "fact": f"Réserve {i} (4 nm)", "nm": 4}
        for i in range(8)
    ] + [
        {"id": f"a{i}", "kind": "station", "score": 2, "tMs": t0 + (2 + 2 * i) * day,
         "title": f"Argo {6904210 + i}", "fact": f"Argo {6904210 + i} (4 nm)",
         "source": "argo", "nm": 4}
        for i in range(4)
    ]
    picked = select_chapter_changes(
        waters + extras, t0, t_b, budget=False, depart_ms=t0 + 3_600_000,
    )
    blob = " ".join(change_sentence(c, "fr") for c in picked if c.get("kind") == "zee-enter")
    assert "françaises" in blob
    assert "espagnoles" in blob
    assert "portugaises" in blob
    assert "marocaines" in blob
    assert blob.find("espagnoles") < blob.find("portugaises") < blob.find("marocaines")


def test_rc35_gascogne_kept_when_gibraltar_already_named():
    """« La route passe par … » : Gibraltar déjà dit en côte n'efface pas Gascogne."""
    from film_script import _append_review_sentences, _order_chapter_sentences

    clock = {
        "t0": "2026-05-15T12:00:00Z",
        "vertices": [
            {"iso": "2026-05-15T12:00:00Z", "lat": 46.15, "lon": -1.16, "vehicle": "main"},
            {"iso": "2026-05-16T12:00:00Z", "lat": 43.2, "lon": -9.0, "vehicle": "main"},
            {"iso": "2026-05-21T12:00:00Z", "lat": 36.14, "lon": -5.35, "vehicle": "main"},
            {"iso": "2026-05-26T12:00:00Z", "lat": 41.9, "lon": 8.7, "vehicle": "main"},
        ],
    }
    t_a, t_b = _ms("2026-05-15T12:00:00Z"), _ms("2026-05-26T12:00:00Z")
    window = {"clock": clock, "tA": t_a, "tB": t_b, "fromName": "La Rochelle", "toName": "Ajaccio (Corse)"}
    review = {"legs": [{
        "from": "La Rochelle", "to": "Ajaccio (Corse)",
        "antiShipping": {"score": 0.4, "lanes": ["Bay of Biscay", "Gibraltar"]},
    }]}
    bits = [
        "Le 15 mai, Berry-Mappemonde quitte La Rochelle.",
        "Le 21 mai, le détroit de Gibraltar — Tanger, Algeciras.",
        "Arrivée à Ajaccio le 26 mai.",
    ]
    anchored = [
        (bits[0], t_a, {"role": "depart"}),
        (bits[1], _ms("2026-05-21T12:00:00Z"), {"kind": "coast", "place": "Gibraltar"}),
        (bits[2], t_b, {"role": "arrive", "place": "Ajaccio", "kind": "escale"}),
    ]
    _append_review_sentences(bits, review, window, "fr", anchored)
    lane = next(s for s in bits if "passe par" in s)
    assert "Gascogne" in lane
    assert "Gibraltar" not in lane
    _order_chapter_sentences(bits, anchored, [])
    blob = " ".join(bits)
    assert blob.find("Gascogne") < blob.find("Gibraltar")


def _rc35_lr_clock():
    return {
        "t0": "2026-05-15T08:00:00Z",
        "marks": [
            {"name": "Saint-Maur (Berry, Indre)", "nm": 0, "filmNm": 0, "iso": "2026-05-15T08:00:00Z",
             "holdHours": 0, "lat": 46.8, "lon": 1.6},
            {"name": "La Rochelle", "nm": 122, "filmNm": 122, "iso": "2026-05-15T12:00:00Z",
             "holdHours": 0, "lat": 46.15, "lon": -1.16},
            {"name": "Ajaccio (Corse)", "nm": 1820, "filmNm": 1942, "iso": "2026-05-26T12:00:00Z",
             "holdHours": 24, "lat": 41.9, "lon": 8.7},
        ],
        "vertices": [
            {"iso": "2026-05-15T12:00:00Z", "lat": 46.15, "lon": -1.16, "vehicle": "main"},
            {"iso": "2026-05-15T18:00:00Z", "lat": 45.5, "lon": -1.4, "vehicle": "main"},
            {"iso": "2026-05-16T12:00:00Z", "lat": 43.2, "lon": -9.0, "vehicle": "main"},
            {"iso": "2026-05-18T12:00:00Z", "lat": 38.7, "lon": -9.5, "vehicle": "main"},
            {"iso": "2026-05-21T08:00:00Z", "lat": 36.14, "lon": -5.35, "vehicle": "main"},
            {"iso": "2026-05-21T14:00:00Z", "lat": 35.7, "lon": -6.0, "vehicle": "main"},
            {"iso": "2026-05-24T12:00:00Z", "lat": 41.0, "lon": 8.4, "vehicle": "main"},
            {"iso": "2026-05-26T12:00:00Z", "lat": 41.9, "lon": 8.7, "vehicle": "main"},
        ],
    }


def test_rc35_lr_ajaccio_waters_in_voyage_order():
    """Moments + horloge de jambe : FR, Gascogne, ES, PT, Gibraltar, MA dans l'ordre."""
    clock = _rc35_lr_clock()

    def mom(seq, iso, lat, lon, changes, **here_zee):
        here = {"zee": here_zee} if here_zee.get("name") else {}
        return {
            "seq": seq, "t": iso, "signature": f"s{seq}", "legIdx": 0,
            "pos": {"lat": lat, "lon": lon},
            "changes": changes,
            "moment": {
                "leg": {"from": "La Rochelle", "to": "Ajaccio (Corse)", "headingDeg": 200.0},
                "here": here,
                "pos": {"lat": lat, "lon": lon},
            },
        }

    journal = {"moments": [
        mom(0, "2026-05-15T12:00:00Z", 46.15, -1.16, [
            {"kind": "amp", "score": 2, "title": "Lilleau-des-Niges",
             "fact": "Lilleau-des-Niges (4 nm)", "nm": 4},
        ], name="French Exclusive Economic Zone", mrgid=5677),
        mom(1, "2026-05-16T12:00:00Z", 43.2, -9.0, [
            {"kind": "zee-enter", "score": 2, "title": "Spanish Exclusive Economic Zone",
             "fact": "Spanish Exclusive Economic Zone"},
            {"kind": "amp", "score": 2, "title": "Réserve de Galice",
             "fact": "Réserve de Galice (5 nm)", "nm": 5},
        ]),
        mom(2, "2026-05-18T12:00:00Z", 38.7, -9.5, [
            {"kind": "zee-enter", "score": 2, "title": "Portuguese Exclusive Economic Zone",
             "fact": "Portuguese Exclusive Economic Zone"},
            {"kind": "station", "score": 2, "title": "Argo 6904210",
             "fact": "Argo 6904210 (4 nm)", "source": "argo", "nm": 4},
        ]),
        mom(3, "2026-05-21T08:00:00Z", 36.14, -5.35, [
            {"kind": "coast", "score": 2, "title": "Tanger", "fact": "Tanger (2 nm)"},
            {"kind": "coast", "score": 2, "title": "Algeciras", "fact": "Algeciras (3 nm)"},
        ]),
        mom(4, "2026-05-21T14:00:00Z", 35.7, -6.0, [
            {"kind": "zee-enter", "score": 2, "title": "Moroccan Exclusive Economic Zone",
             "fact": "Moroccan Exclusive Economic Zone"},
            {"kind": "amp", "score": 2, "title": "Parc du Détroit",
             "fact": "Parc du Détroit (6 nm)", "nm": 6},
            {"kind": "station", "score": 2, "title": "Argo 6904211",
             "fact": "Argo 6904211 (5 nm)", "source": "argo", "nm": 5},
        ]),
        mom(5, "2026-05-24T12:00:00Z", 41.0, 8.4, [
            {"kind": "zee-enter", "score": 2, "title": "Italian Exclusive Economic Zone",
             "fact": "Italian Exclusive Economic Zone"},
        ]),
        mom(6, "2026-05-25T12:00:00Z", 41.9, 8.7, [
            {"kind": "zee-enter", "score": 2, "title": "French Exclusive Economic Zone",
             "fact": "French Exclusive Economic Zone"},
        ]),
        mom(7, "2026-05-26T12:00:00Z", 41.9, 8.7, [
            {"kind": "escale", "score": 3, "title": "Arrivée à Ajaccio", "fact": "x"},
        ]),
    ], "latest": []}
    review = {"legs": [{
        "from": "La Rochelle", "to": "Ajaccio (Corse)",
        "antiShipping": {"score": 0.4, "lanes": ["Bay of Biscay", "Gibraltar"]},
    }]}
    live = {"filmNm": 1820, "sailNm": 1820, "iso": "2026-05-26T12:00:00Z",
            "status": "live", "atStop": "Ajaccio"}
    plan = build_raw_script(
        clock, clock["marks"], live, journal,
        lang="fr", seconds=0, now_ms=_ms("2026-05-27T08:00:00Z"), review=review,
    )
    ch = next(
        c for c in plan["chapters"]
        if re.search(r"rochelle", c.get("fromName") or "", re.I)
        and re.search(r"ajaccio", c.get("toName") or "", re.I)
    )
    text = ch["text"] or ""
    def at(pat):
        m = re.search(pat, text)
        assert m, f"{pat!r} absent de {text[:400]}"
        return m.start()
    i_fr = at(r"eaux françaises")
    i_gas = at(r"Gascogne")
    i_es = at(r"eaux espagnoles")
    i_pt = at(r"eaux portugaises")
    i_gi = at(r"Gibraltar")
    i_ma = at(r"eaux marocaines")
    assert i_fr < i_gas < i_es < i_pt < i_gi < i_ma, text
    # la Corse reste une seconde phrase d'eaux françaises, plus tard
    rest = text[i_ma + 1:]
    assert re.search(r"eaux françaises", rest) or "Corse" in text or "Ajaccio" in text


def test_rc35_papeete_names_pacific_not_north_atlantic():
    """Cayenne → Papeete : le bassin Pacifique vient de la TRACE (lon ≤ −80),
    pas d'une boîte AIS ; Atlantique nord n'est pas recollé."""
    clock = {
        "t0": "2026-05-15T08:00:00Z",
        "marks": [
            {"name": "Saint-Maur (Berry, Indre)", "nm": 0, "filmNm": 0, "iso": "2026-05-15T08:00:00Z",
             "holdHours": 0, "lat": 46.8, "lon": 1.6},
            {"name": "La Rochelle", "nm": 122, "filmNm": 122, "iso": "2026-05-15T12:00:00Z",
             "holdHours": 0, "lat": 46.15, "lon": -1.16},
            {"name": "Cayenne (Guyane)", "nm": 4000, "filmNm": 4000, "iso": "2026-07-28T08:00:00Z",
             "holdHours": 0, "lat": 4.9, "lon": -52.3},
            {"name": "Papeete", "nm": 9000, "filmNm": 9000, "iso": "2026-08-25T08:00:00Z",
             "holdHours": 0, "lat": -17.5, "lon": -149.6},
        ],
        "vertices": [
            {"iso": "2026-07-28T08:00:00Z", "lat": 4.9, "lon": -52.3, "vehicle": "main"},
            {"iso": "2026-08-02T08:00:00Z", "lat": 9.5, "lon": -79.9, "vehicle": "main"},
            {"iso": "2026-08-10T08:00:00Z", "lat": 5.0, "lon": -95.0, "vehicle": "main"},
            {"iso": "2026-08-25T08:00:00Z", "lat": -17.5, "lon": -149.6, "vehicle": "main"},
        ],
    }

    def mom(seq, iso, lat, lon, changes, **zee):
        here = {"zee": zee} if zee.get("name") else {}
        return {
            "seq": seq, "t": iso, "signature": f"s{seq}", "legIdx": 0,
            "pos": {"lat": lat, "lon": lon},
            "changes": changes,
            "moment": {
                "leg": {"from": "Cayenne (Guyane)", "to": "Papeete", "headingDeg": 250.0},
                "here": here,
                "pos": {"lat": lat, "lon": lon},
            },
        }

    journal = {"moments": [
        mom(0, "2026-07-28T08:00:00Z", 4.9, -52.3, [],
            name="French Exclusive Economic Zone", mrgid=4890),
        mom(1, "2026-08-15T08:00:00Z", -10.0, -140.0, [
            {"kind": "zee-enter", "score": 2,
             "title": "French Exclusive Economic Zone (French Polynesia)",
             "fact": "French Exclusive Economic Zone (French Polynesia)"},
        ]),
        mom(2, "2026-08-25T08:00:00Z", -17.5, -149.6, [
            {"kind": "escale", "score": 3, "title": "Arrivée à Papeete", "fact": "x"},
        ]),
    ], "latest": []}
    review = {"legs": [{
        "from": "Cayenne (Guyane)", "to": "Papeete",
        "antiShipping": {"score": 0.7, "lanes": ["N Atlantic main", "Caribbean W"]},
    }]}
    live = {"filmNm": 5000, "sailNm": 5000, "iso": "2026-08-25T08:00:00Z",
            "status": "live", "atStop": "Papeete"}
    plan = build_raw_script(
        clock, clock["marks"], live, journal,
        lang="fr", seconds=0, now_ms=_ms("2026-08-26T08:00:00Z"), review=review,
    )
    ch = next(
        c for c in plan["chapters"]
        if re.search(r"papeete", (c.get("toName") or "") + (c.get("fromName") or ""), re.I)
    )
    text = ch["text"] or ""
    assert re.search(r"Pacifique", text), text
    assert "Atlantique nord" not in text
    en = build_raw_script(
        clock, clock["marks"], live, journal,
        lang="en", seconds=0, now_ms=_ms("2026-08-26T08:00:00Z"), review=review,
    )
    en_ch = next(
        c for c in en["chapters"]
        if re.search(r"papeete", (c.get("toName") or "") + (c.get("fromName") or ""), re.I)
    )
    assert re.search(r"Pacific", en_ch["text"] or ""), en_ch["text"]


# ---------------------------------------------------------------------------
# Titres FR du journal (mai), pas les titres EN de RC35
# ---------------------------------------------------------------------------


def _rc48_official_lr_clock():
    """Horloge de jambe : marks et sommets aux coords du journal officiel."""
    return {
        "t0": "2026-05-15T08:00:00Z",
        "marks": [
            {"name": "Saint-Maur (Berry, Indre)", "nm": 0, "filmNm": 0, "iso": "2026-05-15T08:00:00Z",
             "holdHours": 0, "lat": 46.8075, "lon": 1.6358},
            {"name": "La Rochelle", "nm": 122.33, "filmNm": 122.33, "iso": "2026-05-15T08:00:00Z",
             "holdHours": 0, "lat": 46.1541, "lon": -1.167},
            {"name": "Ajaccio (Corse)", "nm": 1942.18, "filmNm": 1942.18, "iso": "2026-06-06T07:16:14Z",
             "holdHours": 72, "lat": 41.9192, "lon": 8.7386},
        ],
        "vertices": [
            {"iso": "2026-05-15T08:00:00Z", "lat": 46.1541, "lon": -1.167, "vehicle": "main"},
            {"iso": "2026-05-15T10:18:26Z", "lat": 46.239161, "lon": -1.261231, "vehicle": "main"},
            {"iso": "2026-05-17T00:00:00Z", "lat": 45.3181, "lon": -4.1169, "vehicle": "main"},
            {"iso": "2026-05-17T01:04:53Z", "lat": 45.11464017881787, "lon": -4.750805408333942, "vehicle": "main"},
            {"iso": "2026-05-19T12:00:00Z", "lat": 43.3921, "lon": -9.0658, "vehicle": "main"},
            {"iso": "2026-05-19T14:40:58Z", "lat": 41.707791602781406, "lon": -9.78584142520486, "vehicle": "main"},
            {"iso": "2026-05-22T04:34:29Z", "lat": 36.341937339755944, "lon": -7.362956453052497, "vehicle": "main"},
            {"iso": "2026-05-22T23:00:47Z", "lat": 36.0379444528699, "lon": -6.106613485343016, "vehicle": "main"},
            {"iso": "2026-05-23T03:00:47Z", "lat": 35.98357666916796, "lon": -5.8861529081988575, "vehicle": "main"},
            {"iso": "2026-05-23T06:29:00Z", "lat": 35.95662867435303, "lon": -5.610821085969859, "vehicle": "main"},
            {"iso": "2026-05-23T09:56:13Z", "lat": 36.02837986763812, "lon": -5.141219304185524, "vehicle": "main"},
            {"iso": "2026-05-30T05:23:46Z", "lat": 41.56043957568277, "lon": 8.42299638523112, "vehicle": "main"},
            {"iso": "2026-06-06T07:16:14Z", "lat": 41.9192, "lon": 8.7386, "vehicle": "main"},
        ],
    }


def test_rc48_official_journal_waters_in_voyage_order():
    """Moments au format officiel : titres FR des zee-enter de mai, coords du
    journal — FR, Gascogne, ES, PT, Gibraltar, MA dans cet ordre. Pas un seed
    de stock, pas les titres EN de RC35."""
    clock = _rc48_official_lr_clock()

    def mom(seq, iso, lat, lon, changes, **here_zee):
        here = {"zee": here_zee} if here_zee.get("name") else {}
        return {
            "seq": seq, "t": iso, "signature": f"s{seq}", "legIdx": 1,
            "pos": {"lat": lat, "lon": lon},
            "changes": changes,
            "moment": {
                "leg": {"from": "La Rochelle", "to": "Ajaccio (Corse)", "headingDeg": 200.0},
                "here": here,
                "pos": {"lat": lat, "lon": lon},
            },
        }

    journal = {"moments": [
        {"seq": 0, "t": "2026-05-15T08:00:00Z", "signature": "s0", "legIdx": 0,
         "pos": {"lat": 46.8075, "lon": 1.6358}, "changes": [],
         "moment": {"leg": {"from": "Saint-Maur (Berry, Indre)", "to": "La Rochelle", "vehicle": "land"}}},
        {"seq": 1, "t": "2026-05-15T08:00:00Z", "signature": "s1", "legIdx": 0,
         "pos": {"lat": 46.1541, "lon": -1.167},
         "changes": [{"kind": "escale", "score": 3, "title": "Arrivée à La Rochelle", "fact": "x"}],
         "moment": {"leg": {"from": "Saint-Maur (Berry, Indre)", "to": "La Rochelle", "vehicle": "land"}}},
        mom(2, "2026-05-15T10:18:26Z", 46.239161, -1.261231, [
            {"kind": "amp", "score": 2, "title": "Lilleau-des-Niges",
             "fact": "Lilleau-des-Niges (4.6 nm)", "nm": 4.6},
            {"kind": "station", "score": 2, "title": "Argo 6904210",
             "fact": "Argo 6904210 (4 nm)", "source": "argo", "nm": 4},
        ], name="Zone économique exclusive française (France métropolitaine)", mrgid=5677),
        mom(3, "2026-05-17T01:04:53Z", 45.11464017881787, -4.750805408333942, [
            {"kind": "zee-enter", "score": 2,
             "title": "Zone économique exclusive espagnole",
             "fact": "Zone économique exclusive espagnole"},
            {"kind": "station", "score": 2, "title": "Suivi stationnel Sabellaria",
             "fact": "Suivi stationnel Sabellaria (7 nm)", "nm": 7},
        ]),
        mom(4, "2026-05-19T14:40:58Z", 41.707791602781406, -9.78584142520486, [
            {"kind": "zee-enter", "score": 2,
             "title": "Zone économique exclusive portugaise",
             "fact": "Zone économique exclusive portugaise"},
            {"kind": "amp", "score": 2, "title": "Réserve de Galice",
             "fact": "Réserve de Galice (5 nm)", "nm": 5},
        ]),
        mom(5, "2026-05-22T23:00:47Z", 36.0379444528699, -6.106613485343016, [
            {"kind": "coast", "score": 2, "title": "Tanger", "fact": "Tanger (2 nm)"},
        ]),
        mom(6, "2026-05-23T03:00:47Z", 35.98357666916796, -5.8861529081988575, [
            {"kind": "coast", "score": 2, "title": "Algeciras", "fact": "Algeciras (3 nm)"},
        ]),
        mom(7, "2026-05-23T06:29:00Z", 35.95662867435303, -5.610821085969859, [
            {"kind": "zee-enter", "score": 2,
             "title": "Zone économique exclusive marocaine",
             "fact": "Zone économique exclusive marocaine"},
            {"kind": "station", "score": 2, "title": "Argo 6904211",
             "fact": "Argo 6904211 (5 nm)", "source": "argo", "nm": 5},
        ]),
        mom(8, "2026-06-06T07:16:14Z", 41.9192, 8.7386, [
            {"kind": "escale", "score": 3, "title": "Arrivée à Ajaccio", "fact": "x"},
        ]),
    ], "latest": []}
    review = {"legs": [{
        "from": "La Rochelle", "to": "Ajaccio (Corse)",
        "antiShipping": {"score": 0.4, "lanes": ["Bay of Biscay", "Gibraltar", "Western Med"]},
        "legNm": 1820,
    }]}
    live = {"filmNm": 1942, "sailNm": 1820, "iso": "2026-06-06T07:16:14Z",
            "status": "live", "atStop": "Ajaccio"}
    plan = build_raw_script(
        clock, clock["marks"], live, journal,
        lang="fr", seconds=0, now_ms=_ms("2026-06-07T08:00:00Z"), review=review,
    )
    ch = next(
        c for c in plan["chapters"]
        if re.search(r"rochelle", c.get("fromName") or "", re.I)
        and re.search(r"ajaccio", c.get("toName") or "", re.I)
    )
    text = ch["text"] or ""
    assert "Spanish Exclusive Economic Zone" not in text
    assert "Zone économique exclusive" not in text

    def at(pat):
        m = re.search(pat, text)
        assert m, f"{pat!r} absent de {text[:500]}"
        return m.start()

    i_fr = at(r"eaux françaises")
    i_gas = at(r"Gascogne")
    i_es = at(r"eaux espagnoles")
    i_pt = at(r"eaux portugaises")
    i_gi = at(r"Gibraltar")
    i_ma = at(r"eaux marocaines")
    assert i_fr < i_gas < i_es < i_pt < i_gi < i_ma, text


def test_rc48_prefer_journal_moments_keeps_fr_zee_enter():
    """Grille horloge du jour (grib) ne remplace pas le journal à zee-enter FR."""
    clock_grid = [{
        "seq": 0, "t": "2026-05-15T12:00:00Z", "changes": [{"kind": "grib", "title": "vent"}],
    }]
    journal = [{
        "seq": 1, "t": "2026-05-17T01:04:53Z",
        "changes": [{"kind": "zee-enter", "title": "Zone économique exclusive espagnole"}],
    }]
    picked = prefer_journal_moments(clock_grid, journal)
    assert picked == journal
    assert prefer_journal_moments(journal, clock_grid) == journal
    assert prefer_journal_moments([], clock_grid) == clock_grid


# ---------------------------------------------------------------------------
# Phrase mer lisible : pas de « ≥ », le seuil n'est pas répété
# ---------------------------------------------------------------------------

_DUP_METERS_RE = re.compile(r"(\d+)\s*m.+\1\s*m")


def test_rc41_sea_alert_sentence_no_ge_no_repeat():
    sea = {
        "kind": "alert-on",
        "title": "Mer",
        "fact": "Hs 3 m ≥ 3 m.",
        "t": "2026-05-18T12:00:00Z",
        "hs": 3.0,
    }
    fr = change_sentence(sea, "fr")
    en = change_sentence(sea, "en")
    assert "≥" not in fr and "≥" not in en
    assert "mer formée" in fr
    assert re.search(r"\b3\s*m\b", fr)
    assert not _DUP_METERS_RE.search(fr), fr
    assert "Hs" in en and re.search(r"\b3\s*m\b", en)
    assert not _DUP_METERS_RE.search(en), en
    assert "≥" not in change_sentence({**sea, "kind": "sea"}, "fr")


def test_rc41_chapter_with_hs_alert_is_readable():
    """Un chapitre qui porte l'alerte Hs : ni ≥, ni le même nombre de mètres deux fois."""
    from film_script import _sentences

    sea = {
        "kind": "alert-on",
        "title": "Mer",
        "fact": "Hs 3,4 m ≥ 3,0 m.",
        "t": "2026-05-18T12:00:00Z",
        "hs": 3.4,
    }
    text = " ".join((
        "Le 15 mai, départ vers Ajaccio.",
        change_sentence(sea, "fr"),
        "Arrivée à Ajaccio le 26 mai.",
    ))
    assert "≥" not in text
    assert not re.search(r"Hs \d+ m ≥", text)
    for sent in _sentences(text):
        assert not _DUP_METERS_RE.search(sent), sent


# ---------------------------------------------------------------------------
# Casse des noms d'eaux en anglais (pas de rebuild du film)
# ---------------------------------------------------------------------------

_RC53_LOWER_WATERS = (
    "french waters",
    "italian waters",
    "moroccan waters",
    "madeira waters",
    "martinique waters",
    "guadeloupe waters",
)


def _rc53_assert_en_waters_cased(blob: str) -> None:
    for low in _RC53_LOWER_WATERS:
        assert low not in blob, blob
    assert "French waters" in blob
    assert "Italian waters" in blob
    assert "Moroccan waters" in blob
    assert "Madeira waters" in blob
    assert "Martinique waters" in blob
    assert "Guadeloupe waters" in blob


def test_rc53_en_waters_title_case_on_ready_script():
    """Script anglais ready : plus de minuscule en tête de nom d'eau ;
    la forme capitale reste. Filet à la lecture, pas un bumper de rev."""
    from film_script import fix_en_waters_casing, speak_film_text

    mixed = (
        "On 15 May, French waters. Then, french waters. "
        "Then, italian waters. Then, moroccan waters. "
        "Then, madeira waters. Then, martinique waters. Then, guadeloupe waters."
    )
    fixed = fix_en_waters_casing(mixed)
    _rc53_assert_en_waters_cased(fixed)
    spoken = speak_film_text(mixed, "en")
    _rc53_assert_en_waters_cased(spoken)
    # FR inchangé (eaux françaises, pas « french waters »)
    assert "french waters" not in speak_film_text("Le 15 mai, les eaux françaises.", "fr")

    thinned = thin_chapter_dates([
        "On 15 May, French waters.",
        "On 16 May, Italian waters.",
        "On 18 May, Moroccan waters.",
        "On 20 May, Madeira waters.",
        "On 22 May, Martinique waters.",
        "On 24 May, Guadeloupe waters.",
        "Arrival at Ajaccio on 26 May.",
    ], "en")
    _rc53_assert_en_waters_cased(" ".join(thinned))

    clock = _rc35_lr_clock()

    def mom(seq, iso, lat, lon, changes, **here_zee):
        here = {"zee": here_zee} if here_zee.get("name") else {}
        return {
            "seq": seq, "t": iso, "signature": f"s{seq}", "legIdx": 0,
            "pos": {"lat": lat, "lon": lon},
            "changes": changes,
            "moment": {
                "leg": {"from": "La Rochelle", "to": "Ajaccio (Corse)", "headingDeg": 200.0},
                "here": here,
                "pos": {"lat": lat, "lon": lon},
            },
        }

    journal = {"moments": [
        mom(0, "2026-05-15T12:00:00Z", 46.15, -1.16, [
            {"kind": "zee-enter", "score": 2, "title": "French Exclusive Economic Zone",
             "fact": "French Exclusive Economic Zone"},
        ], name="French Exclusive Economic Zone", mrgid=5677),
        mom(1, "2026-05-16T12:00:00Z", 43.2, -9.0, [
            {"kind": "zee-enter", "score": 2, "title": "Spanish Exclusive Economic Zone",
             "fact": "Spanish Exclusive Economic Zone"},
        ]),
        mom(2, "2026-05-21T14:00:00Z", 35.7, -6.0, [
            {"kind": "zee-enter", "score": 2, "title": "Moroccan Exclusive Economic Zone",
             "fact": "Moroccan Exclusive Economic Zone"},
        ]),
        mom(3, "2026-05-24T12:00:00Z", 41.0, 8.4, [
            {"kind": "zee-enter", "score": 2, "title": "Italian Exclusive Economic Zone",
             "fact": "Italian Exclusive Economic Zone"},
        ]),
        mom(4, "2026-05-26T12:00:00Z", 41.9, 8.7, [
            {"kind": "escale", "score": 3, "title": "Arrival at Ajaccio", "fact": "x"},
        ]),
    ], "latest": []}
    live = {"filmNm": 1820, "sailNm": 1820, "iso": "2026-05-26T12:00:00Z",
            "status": "live", "atStop": "Ajaccio"}
    plan = build_raw_script(
        clock, clock["marks"], live, journal,
        lang="en", seconds=0, now_ms=_ms("2026-05-27T08:00:00Z"),
    )
    assert plan.get("source") == "rules"
    blob = " ".join(c.get("text") or "" for c in plan["chapters"])
    for low in _RC53_LOWER_WATERS:
        assert low not in blob, blob
    assert "French waters" in blob, blob
    assert "Italian waters" in blob, blob
    assert "Moroccan waters" in blob, blob


def _rc55_climo(iso, *, lat, lon, place_en, place_fr):
    return {
        "kind": "climo", "score": 2, "event": "se_trades", "regimeId": "se_trades",
        "title": "alizés de sud-est", "t": iso, "iso": iso,
        "placeEn": place_en, "placeFr": place_fr,
        "source": "atlas", "nature": "season", "windKnots": 11.0,
        "lat": lat, "lon": lon,
        "fact": f"On {iso[:10]}, {place_en}, the southeasterly trade winds set in: eleven seasonal knots.",
    }


def test_rc55_saint_pierre_chapter_omits_guiana_and_equator():
    """Le chapitre qui part de Saint-Pierre ne contient ni equator ni
    French Guiana. Marigot → Cayenne (Paramaribo) et Cayenne → Papeete
    (Balboa) gardent l'équateur."""
    marks = [
        {"name": "Saint-Maur (Berry, Indre)", "nm": 0, "filmNm": 0,
         "iso": OFFICIAL_T0, "holdHours": 0, "lat": 46.8, "lon": 1.6},
        {"name": "La Rochelle", "nm": 122, "filmNm": 122,
         "iso": "2026-05-15T12:00:00Z", "holdHours": 0, "lat": 46.15, "lon": -1.16},
        {"name": "Marigot (Saint-Martin)", "nm": 3500, "filmNm": 3500,
         "iso": "2026-07-09T08:00:00Z", "holdHours": 72, "lat": 18.07, "lon": -63.08},
        {"name": "Cayenne (Guyane)", "nm": 4000, "filmNm": 4000,
         "iso": "2026-07-19T08:00:00Z", "holdHours": 72, "lat": 4.93, "lon": -52.33},
        {"name": "Halifax (Nouvelle-Écosse)", "nm": 4000, "filmNm": 4080,
         "iso": "2026-07-22T08:00:00Z", "holdHours": 24, "lat": 44.65, "lon": -63.57, "kind": "hub"},
        {"name": "Saint-Pierre (Saint-Pierre-et-Miquelon)", "nm": 4400, "filmNm": 4480,
         "iso": "2026-07-25T08:00:00Z", "holdHours": 72, "lat": 46.78, "lon": -56.18},
        {"name": "Halifax (Nouvelle-Écosse)", "nm": 4800, "filmNm": 4880,
         "iso": "2026-07-29T08:00:00Z", "holdHours": 24, "lat": 44.65, "lon": -63.57, "kind": "hub"},
        {"name": "Cayenne (Guyane)", "nm": 4800, "filmNm": 4960,
         "iso": "2026-07-30T08:00:00Z", "holdHours": 0, "lat": 4.93, "lon": -52.33},
        {"name": "Papeete (Polynésie française)", "nm": 11000, "filmNm": 11100,
         "iso": "2026-09-08T08:00:00Z", "holdHours": 72, "lat": -17.5, "lon": -149.5},
    ]
    clock = {
        "t0": OFFICIAL_T0, "marks": marks, "vertices": [
            {"iso": "2026-07-12T12:00:00Z", "lat": 5.8, "lon": -55.2, "vehicle": "main"},
            {"iso": "2026-07-16T12:00:00Z", "lat": 0.4, "lon": -50.0, "vehicle": "main"},
            {"iso": "2026-07-19T08:00:00Z", "lat": 4.93, "lon": -52.33, "vehicle": "quay"},
            {"iso": "2026-07-22T08:00:00Z", "lat": 44.65, "lon": -63.57, "vehicle": "plane"},
            {"iso": "2026-07-23T08:00:00Z", "lat": 45.7, "lon": -60.0, "vehicle": "side"},
            {"iso": "2026-07-25T08:00:00Z", "lat": 46.78, "lon": -56.18, "vehicle": "side"},
            {"iso": "2026-07-27T12:00:00Z", "lat": 45.5, "lon": -60.0, "vehicle": "side"},
            {"iso": "2026-07-29T08:00:00Z", "lat": 44.65, "lon": -63.57, "vehicle": "side"},
            {"iso": "2026-07-30T08:00:00Z", "lat": 4.93, "lon": -52.33, "vehicle": "plane"},
            {"iso": "2026-08-10T12:00:00Z", "lat": 8.95, "lon": -79.57, "vehicle": "main"},
            {"iso": "2026-08-15T12:00:00Z", "lat": 0.2, "lon": -80.0, "vehicle": "main"},
        ],
    }
    live = {"filmNm": 12000, "sailNm": 11800, "iso": "2026-09-19T02:00:00Z", "status": "live"}
    guiana = {
        "kind": "zee-enter", "score": 2,
        "title": "French Guiana Exclusive Economic Zone",
        "fact": "French Guiana Exclusive Economic Zone",
        "lat": 4.93, "lon": -52.33,
    }
    equator_approach = _rc55_climo(
        "2026-07-16T12:00:00Z", lat=0.4, lon=-50.0,
        place_en="at the equator", place_fr="à l'équateur",
    )
    equator_pacific = _rc55_climo(
        "2026-08-15T12:00:00Z", lat=0.2, lon=-80.0,
        place_en="at the equator", place_fr="à l'équateur",
    )
    leak = _rc55_climo(
        "2026-07-27T12:00:00Z", lat=4.93, lon=-52.33,
        place_en="at the equator", place_fr="à l'équateur",
    )
    journal = {"moments": [
        {"seq": 0, "t": "2026-07-14T08:00:00Z", "changes": [
            {"kind": "coast", "score": 3, "title": "Paramaribo", "fact": "Paramaribo",
             "ports": ["Paramaribo"], "lat": 5.83, "lon": -55.17},
        ], "moment": {"leg": {"from": "Marigot (Saint-Martin)", "to": "Cayenne (Guyane)"},
                      "pos": {"lat": 5.83, "lon": -55.17}},
         "pos": {"lat": 5.83, "lon": -55.17}},
        {"seq": 1, "t": "2026-07-15T12:00:00Z", "changes": [guiana],
         "moment": {"leg": {"from": "Marigot (Saint-Martin)", "to": "Cayenne (Guyane)"},
                    "pos": {"lat": 4.93, "lon": -52.33}},
         "pos": {"lat": 4.93, "lon": -52.33}},
        {"seq": 2, "t": "2026-07-16T12:00:00Z", "changes": [equator_approach],
         "moment": {"leg": {"from": "Marigot (Saint-Martin)", "to": "Cayenne (Guyane)"},
                    "pos": {"lat": 0.4, "lon": -50.0}},
         "pos": {"lat": 0.4, "lon": -50.0}},
        {"seq": 3, "t": "2026-07-26T12:00:00Z", "changes": [
            {"kind": "zee-enter", "score": 2,
             "title": "Canadian Exclusive Economic Zone",
             "fact": "Canadian Exclusive Economic Zone",
             "lat": 45.7, "lon": -60.0},
        ], "moment": {"leg": {"from": "Saint-Pierre (Saint-Pierre-et-Miquelon)",
                              "to": "Halifax (Nouvelle-Écosse)", "vehicle": "side"},
                      "pos": {"lat": 45.7, "lon": -60.0}},
         "pos": {"lat": 45.7, "lon": -60.0}},
        # Fuite du constat (16 oct.) : Guyane + équateur datés dans la fenêtre
        # Saint-Pierre, alors que le catamaran est à quai à Cayenne.
        {"seq": 4, "t": "2026-07-27T12:00:00Z", "changes": [
            {**guiana, "t": "2026-07-27T12:00:00Z"}, leak,
        ], "moment": {"leg": {"from": "Marigot (Saint-Martin)", "to": "Cayenne (Guyane)"},
                      "pos": {"lat": 4.93, "lon": -52.33}},
         "pos": {"lat": 4.93, "lon": -52.33}},
        {"seq": 5, "t": "2026-08-10T12:00:00Z", "changes": [
            {"kind": "coast", "score": 3, "title": "Balboa", "fact": "Balboa",
             "ports": ["Balboa"], "lat": 8.95, "lon": -79.57},
        ], "moment": {"leg": {"from": "Cayenne (Guyane)", "to": "Papeete (Polynésie française)"},
                      "pos": {"lat": 8.95, "lon": -79.57}},
         "pos": {"lat": 8.95, "lon": -79.57}},
        {"seq": 6, "t": "2026-08-15T12:00:00Z", "changes": [equator_pacific],
         "moment": {"leg": {"from": "Cayenne (Guyane)", "to": "Papeete (Polynésie française)"},
                    "pos": {"lat": 0.2, "lon": -80.0}},
         "pos": {"lat": 0.2, "lon": -80.0}},
    ], "latest": []}
    plan = build_raw_script(
        clock, marks, live, journal, lang="en", seconds=0, now_ms=NOW_MS,
    )
    names = [(c.get("fromName") or "", c.get("toName") or "") for c in plan["chapters"]]
    spm_chs = [
        c for c in plan["chapters"]
        if "Saint-Pierre" in (c.get("fromName") or "")
    ]
    assert spm_chs, names
    for ch in spm_chs:
        text = ch.get("text") or ""
        assert not re.search(
            r"French Guiana waters|eaux de la Guyane|at the equator|à l['’]équateur",
            text, re.I,
        ), text
    marigot = next(
        c for c in plan["chapters"]
        if "Marigot" in (c.get("fromName") or "") and "Cayenne" in (c.get("toName") or "")
    )
    marigot_text = marigot.get("text") or ""
    assert re.search(r"equator|équateur", marigot_text, re.I), marigot_text
    assert re.search(r"French Guiana|Guyane", marigot_text, re.I), marigot_text
    pacific = next(
        c for c in plan["chapters"]
        if "Cayenne" in (c.get("fromName") or "") and "Papeete" in (c.get("toName") or "")
    )
    pacific_text = pacific.get("text") or ""
    assert re.search(r"equator|équateur", pacific_text, re.I), pacific_text
    assert re.search(r"Balboa", pacific_text, re.I), pacific_text


# ── DC1 : une aire, près ou traversée, circulation du stock, 2:30 ≤ 2250 ─────


def _amp_sentences(blob: str) -> list[str]:
    return [
        s.strip()
        for s in re.split(r"(?<=[.!?…])\s+", blob or "")
        if re.search(r"aire marine|marine protected area", s or "", re.I)
    ]


def test_dc1_amp_near_or_crossing_traffic_only_from_stock():
    """Près / traversée ; circulation si traffic ou codes entry/speed ; sinon silence."""
    enter = {
        "kind": "amp", "event": "enter", "title": "Cabrera", "fact": "Cabrera",
        "t": "2026-05-25T12:00:00Z", "inside": True, "nm": 0,
        "traffic": "regulated",
    }
    fr = change_sentence(enter, "fr")
    en = change_sentence(enter, "en")
    assert "traverse l'aire marine protégée Cabrera" in fr
    assert "circulation régulée" in fr
    assert "crosses the marine protected area Cabrera" in en
    assert "regulated transit" in en
    forbidden = {**enter, "traffic": "forbidden", "title": "Iroise", "fact": "Iroise"}
    assert "circulation interdite" in change_sentence(forbidden, "fr")
    assert "no transit" in change_sentence(forbidden, "en")
    from_codes = {
        "kind": "amp", "event": "enter", "title": "Scandola", "fact": "Scandola",
        "t": "2026-05-25T12:00:00Z", "inside": True, "nm": 0,
        "entry": 1, "speed": 3,
    }
    assert "circulation interdite" in change_sentence(from_codes, "fr")
    silent = {
        "kind": "amp", "event": "nearby", "title": "Cabrera", "fact": "Cabrera (6 nm)",
        "t": "2026-05-25T12:00:00Z", "nm": 6,
    }
    near = change_sentence(silent, "fr")
    assert "près de l'aire marine protégée Cabrera" in near
    assert "six milles" in near
    assert "circulation" not in near
    assert "interdit" not in near
    assert "régul" not in near
    unknown = {**enter, "traffic": "unknown"}
    assert "circulation" not in change_sentence(unknown, "fr")
    nested_event = {
        "kind": "amp", "title": "Cabrera", "fact": "Cabrera",
        "t": "2026-05-25T12:00:00Z",
        "entry": {"event": "enter", "inside": True, "nm": 0, "name": "Cabrera"},
    }
    nested_fr = change_sentence(nested_event, "fr")
    assert "traverse l'aire marine protégée Cabrera" in nested_fr
    assert "circulation" not in nested_fr


def test_dc1_one_amp_in_150_and_char_budget():
    """Une seconde aire dans le même 2:30 est refusée. film_char_budget(150) = 2250."""
    assert film_char_budget(150) == 2250
    journal = _rc22_rich_journal()
    journal["moments"] = list(journal["moments"]) + [{
        "seq": 204, "t": "2026-05-17T10:00:00Z", "signature": "amp-cabrera-dc1", "legIdx": 1,
        "changes": [{
            "kind": "amp", "score": 2, "title": "Cabrera",
            "fact": "Cabrera (6 nm)", "nm": 6, "event": "nearby",
        }],
        "moment": {"leg": {"from": "La Rochelle", "to": "Ajaccio (Corse)"}},
    }, {
        "seq": 205, "t": "2026-07-03T10:00:00Z", "signature": "amp-agoa-dc1", "legIdx": 3,
        "changes": [{
            "kind": "amp", "score": 2, "title": "Agoa",
            "fact": "Agoa", "nm": 0, "event": "enter", "inside": True,
        }],
        "moment": {"leg": {
            "from": "Fort-de-France (Martinique)", "to": "Nouméa (Nouvelle-Calédonie)",
        }},
    }]
    plan = build_raw_script(
        CLOCK, CLOCK["marks"], LIVE, journal,
        lang="fr", seconds=150, now_ms=NOW_MS,
    )
    blob = _script_blob(plan)
    amps = _amp_sentences(blob)
    assert len(amps) <= 1, amps
    assert plan["chars"] <= film_char_budget(150)
    assert plan["chars"] / 15 <= 150 * 1.1
    bag = dc_subject_candidates([
        {"kind": "amp", "event": "nearby", "title": "Cabrera", "fact": "Cabrera (6 nm)",
         "nm": 6, "t": "2026-05-17T10:00:00Z"},
        {"kind": "amp", "event": "enter", "title": "Agoa", "fact": "Agoa",
         "nm": 0, "inside": True, "t": "2026-07-03T10:00:00Z"},
    ], "fr")
    assert len(bag) == 1
    assert bag[0]["kind"] == "amp"
    assert bag[0]["oncePerFamilyOnLongLeg"] is True
    assert bag[0]["phrase"]
    assert bag[0]["relation"] == "crossing"
    stored = plan.get("dcSubjects") or []
    assert stored
    assert stored[0]["kind"] == "amp"
    assert stored[0]["oncePerFamilyOnLongLeg"] is True
    assert stored[0]["phrase"]


# ── DC2 : bouée, formalité, mouillage — sac, intégral, pas le 2:30 ───────────

_DC2_BUOY = re.compile(r"une bouée|a buoy", re.I)
_DC2_FORM = re.compile(
    r"formalit[ée]s d['’]entr[ée]e passent par|entry formalities go through",
    re.I,
)
_DC2_ANC = re.compile(r"\bmouillage\b|\banchorage\b", re.I)


def _dc2_family_hits(blob: str) -> dict[str, int]:
    sents = [s.strip() for s in re.split(r"(?<=[.!?…])\s+", blob or "") if s.strip()]
    return {
        "buoy": sum(1 for s in sents if _DC2_BUOY.search(s)),
        "poe": sum(1 for s in sents if _DC2_FORM.search(s)),
        "anchorage": sum(1 for s in sents if _DC2_ANC.search(s)),
    }


def _dc2_journal():
    journal = _rc22_rich_journal()
    extra = [
        {
            "seq": 310, "t": "2026-07-08T10:00:00Z", "signature": "buoy-dc2-a", "legIdx": 3,
            "changes": [{
                "kind": "station", "score": 2, "title": "Wave buoy 12",
                "fact": "Wave buoy 12 (4 nm)", "nm": 4,
            }],
            "moment": {"leg": {
                "from": "Fort-de-France (Martinique)", "to": "Nouméa (Nouvelle-Calédonie)",
            }},
        },
        {
            "seq": 311, "t": "2026-07-18T10:00:00Z", "signature": "buoy-dc2-b", "legIdx": 3,
            "changes": [{
                "kind": "station", "score": 2, "title": "PIRATA",
                "fact": "PIRATA (6 nm)", "nm": 6,
            }],
            "moment": {"leg": {
                "from": "Fort-de-France (Martinique)", "to": "Nouméa (Nouvelle-Calédonie)",
            }},
        },
        {
            "seq": 312, "t": "2026-07-12T10:00:00Z", "signature": "poe-dc2-a", "legIdx": 3,
            "changes": [{
                "kind": "poe", "score": 2, "title": "Papeete", "fact": "Papeete",
            }],
            "moment": {"leg": {
                "from": "Fort-de-France (Martinique)", "to": "Nouméa (Nouvelle-Calédonie)",
            }},
        },
        {
            "seq": 313, "t": "2026-07-22T10:00:00Z", "signature": "poe-dc2-b", "legIdx": 3,
            "changes": [{
                "kind": "poe", "score": 2, "title": "Nouméa", "fact": "Nouméa",
            }],
            "moment": {"leg": {
                "from": "Fort-de-France (Martinique)", "to": "Nouméa (Nouvelle-Calédonie)",
            }},
        },
        {
            "seq": 314, "t": "2026-07-14T10:00:00Z", "signature": "anc-dc2-a", "legIdx": 3,
            "changes": [{
                "kind": "anchorage", "score": 2, "title": "Mouillage des Minimes",
                "fact": "Mouillage des Minimes", "nm": 3,
            }],
            "moment": {"leg": {
                "from": "Fort-de-France (Martinique)", "to": "Nouméa (Nouvelle-Calédonie)",
            }},
        },
        {
            "seq": 315, "t": "2026-08-02T10:00:00Z", "signature": "anc-dc2-b", "legIdx": 3,
            "changes": [{
                "kind": "anchorage", "score": 2, "title": "Baie de Prony",
                "fact": "Baie de Prony", "nm": 5,
            }],
            "moment": {"leg": {
                "from": "Fort-de-France (Martinique)", "to": "Nouméa (Nouvelle-Calédonie)",
            }},
        },
    ]
    return {**journal, "moments": list(journal["moments"]) + extra}


def test_dc2_phrases_from_stock_only():
    """FR/EN depuis un fait du stock ; silence si le fait manque."""
    buoy = {
        "kind": "buoy", "title": "Wave buoy 12", "fact": "Wave buoy 12 (4 nm)",
        "t": "2026-07-08T10:00:00Z",
    }
    fr_b, en_b = change_sentence(buoy, "fr"), change_sentence(buoy, "en")
    assert "une bouée" in fr_b
    assert "a buoy" in en_b
    assert change_sentence({"kind": "buoy", "title": "Station croisée"}, "fr") == ""
    poe = {
        "kind": "poe", "title": "Papeete", "fact": "Papeete",
        "t": "2026-07-12T10:00:00Z",
    }
    fr_p, en_p = change_sentence(poe, "fr"), change_sentence(poe, "en")
    assert "les formalités d'entrée passent par Papeete" in fr_p
    assert "entry formalities go through Papeete" in en_p
    silent_poe = {
        "kind": "poe",
        "title": "Formalités d'entrée",
        "fact": "Aucun port d'entrée officiel n'est connu pour cette ZEE.",
    }
    assert change_sentence(silent_poe, "fr") == ""
    assert change_sentence(silent_poe, "en") == ""
    anc = {
        "kind": "anchorage", "title": "Mouillage des Minimes",
        "fact": "Mouillage des Minimes", "t": "2026-07-14T10:00:00Z",
    }
    fr_a, en_a = change_sentence(anc, "fr"), change_sentence(anc, "en")
    assert "mouillage Mouillage des Minimes" in fr_a
    assert "anchorage Mouillage des Minimes" in en_a
    assert change_sentence({"kind": "anchorage", "title": "anchorage"}, "fr") == ""
    assert change_sentence({"kind": "anchorage", "title": "mooring"}, "en") == ""
    port = {
        "kind": "port", "title": "La Rochelle", "fact": "La Rochelle",
        "t": "2026-05-15T12:00:00Z",
    }
    fr_port = change_sentence(port, "fr")
    assert "devant La Rochelle" in fr_port
    assert "formalités" not in fr_port
    assert all(r["kind"] != "poe" for r in dc_subject_candidates([port], "fr"))


def test_dc2_once_per_family_on_long_integral():
    """Intégral : une bouée, une formalité, un mouillage par longue jambe."""
    day = 86_400_000
    buoys = [
        {"id": "b1", "kind": "station", "score": 2, "tMs": 4 * day,
         "title": "Wave buoy 12", "fact": "Wave buoy 12 (4 nm)", "nm": 4,
         "t": "2026-07-08T10:00:00Z"},
        {"id": "b2", "kind": "station", "score": 2, "tMs": 14 * day,
         "title": "PIRATA", "fact": "PIRATA (6 nm)", "nm": 6,
         "t": "2026-07-18T10:00:00Z"},
    ]
    poes = [
        {"id": "p1", "kind": "poe", "score": 2, "tMs": 8 * day,
         "title": "Papeete", "fact": "Papeete", "t": "2026-07-12T10:00:00Z"},
        {"id": "p2", "kind": "poe", "score": 2, "tMs": 18 * day,
         "title": "Nouméa", "fact": "Nouméa", "t": "2026-07-22T10:00:00Z"},
    ]
    ancs = [
        {"id": "a1", "kind": "anchorage", "score": 2, "tMs": 10 * day,
         "title": "Mouillage des Minimes", "fact": "Mouillage des Minimes",
         "t": "2026-07-14T10:00:00Z"},
        {"id": "a2", "kind": "anchorage", "score": 2, "tMs": 20 * day,
         "title": "Baie de Prony", "fact": "Baie de Prony",
         "t": "2026-08-02T10:00:00Z"},
    ]
    long_span = 40 * day
    picked = dose_dc2_leg_changes(buoys + poes + ancs, long_span)
    kinds = [c["kind"] for c in picked]
    assert kinds.count("buoy") == 1
    assert kinds.count("poe") == 1
    assert kinds.count("anchorage") == 1
    assert dose_dc2_leg_changes(buoys + poes + ancs, 2 * day) == []
    plan = build_raw_script(
        CLOCK, CLOCK["marks"], LIVE, _dc2_journal(),
        lang="fr", seconds=0, now_ms=NOW_MS,
    )
    pacific = next(
        c for c in plan["chapters"]
        if "Fort-de-France" in (c.get("fromName") or "")
        and "Nouméa" in (c.get("toName") or "")
    )
    hits = _dc2_family_hits(pacific.get("text") or "")
    assert hits["buoy"] <= 1, pacific.get("text")
    assert hits["poe"] <= 1, pacific.get("text")
    assert hits["anchorage"] <= 1, pacific.get("text")
    assert hits["buoy"] == 1, pacific.get("text")
    assert hits["poe"] == 1, pacific.get("text")
    assert hits["anchorage"] == 1, pacific.get("text")
    blob = _script_blob(plan)
    assert "Wave buoy 12" not in blob
    assert "PIRATA" not in blob or "une bouée" in blob


def test_dc2_short_tier_omits_kinds_and_char_budget():
    """Le 2:30 n'empile pas bouée / formalité / mouillage. ≤ 2250 caractères."""
    assert film_char_budget(150) == 2250
    journal = _dc2_journal()
    short = build_raw_script(
        CLOCK, CLOCK["marks"], LIVE, journal,
        lang="fr", seconds=150, now_ms=NOW_MS,
    )
    blob = _script_blob(short)
    hits = _dc2_family_hits(blob)
    assert hits["buoy"] == 0, blob
    assert hits["poe"] == 0, blob
    assert hits["anchorage"] == 0, blob
    assert short["chars"] <= film_char_budget(150)
    assert short["chars"] / 15 <= 150 * 1.1
    picked_short = select_chapter_changes(
        [
            {"id": "b", "kind": "buoy", "score": 2, "tMs": 2, "title": "Wave buoy 12",
             "fact": "Wave buoy 12", "t": "2026-07-08T10:00:00Z"},
            {"id": "p", "kind": "poe", "score": 2, "tMs": 3, "title": "Papeete",
             "fact": "Papeete"},
            {"id": "a", "kind": "anchorage", "score": 2, "tMs": 4,
             "title": "Mouillage des Minimes", "fact": "Mouillage des Minimes"},
            {"id": "e", "kind": "escale", "score": 3, "tMs": 10,
             "title": "Arrivée à Nouméa", "fact": "x"},
        ],
        0, 10, budget=True, tier=film_priority_tier(150),
    )
    assert not any(c.get("kind") in {"buoy", "poe", "anchorage"} for c in picked_short)


def test_dc2_bag_for_vs1():
    """Sac dc_subject_candidates : une entrée par famille, oncePerFamilyOnLongLeg."""
    bag = dc_subject_candidates([
        {"kind": "amp", "event": "enter", "title": "Cabrera", "fact": "Cabrera",
         "nm": 0, "inside": True, "t": "2026-05-25T12:00:00Z"},
        {"kind": "station", "title": "Wave buoy 12", "fact": "Wave buoy 12 (4 nm)",
         "nm": 4, "t": "2026-07-08T10:00:00Z"},
        {"kind": "station", "title": "PIRATA", "fact": "PIRATA",
         "t": "2026-07-18T10:00:00Z"},
        {"kind": "poe", "title": "Papeete", "fact": "Papeete",
         "t": "2026-07-12T10:00:00Z"},
        {"kind": "poe", "title": "Nouméa", "fact": "Nouméa",
         "t": "2026-07-22T10:00:00Z"},
        {"kind": "anchorage", "title": "Mouillage des Minimes",
         "fact": "Mouillage des Minimes", "t": "2026-07-14T10:00:00Z"},
        {"kind": "anchorage", "title": "anchorage", "fact": "anchorage"},
    ], "fr")
    kinds = [r["kind"] for r in bag]
    assert kinds.count("amp") == 1
    assert kinds.count("buoy") == 1
    assert kinds.count("poe") == 1
    assert kinds.count("anchorage") == 1
    by_kind = {r["kind"]: r for r in bag}
    assert by_kind["buoy"]["oncePerFamilyOnLongLeg"] is True
    assert "une bouée" in by_kind["buoy"]["phrase"]
    assert by_kind["poe"]["oncePerFamilyOnLongLeg"] is True
    assert "Papeete" in by_kind["poe"]["phrase"]
    assert "formalités d'entrée passent par" in by_kind["poe"]["phrase"]
    assert by_kind["anchorage"]["oncePerFamilyOnLongLeg"] is True
    assert "Mouillage des Minimes" in by_kind["anchorage"]["phrase"]
    plan = build_raw_script(
        CLOCK, CLOCK["marks"], LIVE, _dc2_journal(),
        lang="fr", seconds=150, now_ms=NOW_MS,
    )
    stored_kinds = {r["kind"] for r in (plan.get("dcSubjects") or [])}
    assert {"buoy", "poe", "anchorage"} <= stored_kinds
    for rec in plan["dcSubjects"]:
        assert rec["oncePerFamilyOnLongLeg"] is True
        assert rec["phrase"]


# ── DC3 : balise, câble, profondeur, piraterie, satellite — sac, pas le 2:30 ─

_DC3_ATON = re.compile(r"\bbalise\b|\bbeacon\b", re.I)
_DC3_CABLE = re.compile(r"\bcâble\b|\bcable\b", re.I)
_DC3_DEPTH = re.compile(r"profondeur\s*:|depth\s*:", re.I)
_DC3_PIRACY = re.compile(r"Piraterie —|Piracy —")
_DC3_SAT_INVENTED = re.compile(
    r"image satellite au-dessus|satellite image above",
    re.I,
)


def _dc3_family_hits(blob: str) -> dict[str, int]:
    sents = [s.strip() for s in re.split(r"(?<=[.!?…])\s+", blob or "") if s.strip()]
    return {
        "aton": sum(1 for s in sents if _DC3_ATON.search(s)),
        "cable": sum(1 for s in sents if _DC3_CABLE.search(s)),
        "depth": sum(1 for s in sents if _DC3_DEPTH.search(s)),
        "piracy": sum(1 for s in sents if _DC3_PIRACY.search(s)),
        "sat_invented": sum(1 for s in sents if _DC3_SAT_INVENTED.search(s)),
    }


def _dc3_journal():
    journal = _rc22_rich_journal()
    extra = [
        {
            "seq": 410, "t": "2026-07-08T10:00:00Z", "signature": "aton-dc3-a", "legIdx": 3,
            "changes": [{
                "kind": "aton", "score": 2, "title": "Feu des Minimes",
                "fact": "Feu des Minimes", "name": "Feu des Minimes", "nm": 2,
            }],
            "moment": {"leg": {
                "from": "Fort-de-France (Martinique)", "to": "Nouméa (Nouvelle-Calédonie)",
            }},
        },
        {
            "seq": 411, "t": "2026-07-18T10:00:00Z", "signature": "aton-dc3-b", "legIdx": 3,
            "changes": [{
                "kind": "aton", "score": 2, "title": "Phare Amédée",
                "fact": "Phare Amédée", "name": "Phare Amédée", "nm": 5,
            }],
            "moment": {"leg": {
                "from": "Fort-de-France (Martinique)", "to": "Nouméa (Nouvelle-Calédonie)",
            }},
        },
        {
            "seq": 412, "t": "2026-07-12T10:00:00Z", "signature": "cable-dc3-a", "legIdx": 3,
            "changes": [{
                "kind": "cable", "score": 2, "title": "Honotua",
                "fact": "Honotua", "name": "Honotua",
            }],
            "moment": {"leg": {
                "from": "Fort-de-France (Martinique)", "to": "Nouméa (Nouvelle-Calédonie)",
            }},
        },
        {
            "seq": 413, "t": "2026-07-22T10:00:00Z", "signature": "cable-dc3-b", "legIdx": 3,
            "changes": [{
                "kind": "cable", "score": 2, "title": "Southern Cross",
                "fact": "Southern Cross", "name": "Southern Cross",
            }],
            "moment": {"leg": {
                "from": "Fort-de-France (Martinique)", "to": "Nouméa (Nouvelle-Calédonie)",
            }},
        },
        {
            "seq": 414, "t": "2026-07-14T10:00:00Z", "signature": "depth-dc3-a", "legIdx": 3,
            "changes": [{
                "kind": "depth", "score": 2, "depth_m": 18.4, "source": "emodnet",
                "title": "emodnet", "fact": "emodnet",
            }],
            "moment": {"leg": {
                "from": "Fort-de-France (Martinique)", "to": "Nouméa (Nouvelle-Calédonie)",
            }},
        },
        {
            "seq": 415, "t": "2026-08-02T10:00:00Z", "signature": "depth-dc3-b", "legIdx": 3,
            "changes": [{
                "kind": "depth", "score": 2, "depthOffshore": -3888.0, "source": "gebco",
                "title": "gebco", "fact": "gebco",
            }],
            "moment": {"leg": {
                "from": "Fort-de-France (Martinique)", "to": "Nouméa (Nouvelle-Calédonie)",
            }},
        },
        {
            "seq": 416, "t": "2026-07-16T10:00:00Z", "signature": "piracy-dc3-a", "legIdx": 3,
            "changes": [{
                "kind": "piracy", "score": 2, "title": "Horn of Africa / Gulf Aden",
                "name": "Horn of Africa / Gulf Aden", "level": "HIGH",
                "source": "IMB/UKMTO",
            }],
            "moment": {"leg": {
                "from": "Fort-de-France (Martinique)", "to": "Nouméa (Nouvelle-Calédonie)",
            }},
        },
        {
            "seq": 417, "t": "2026-08-10T10:00:00Z", "signature": "piracy-dc3-b", "legIdx": 3,
            "changes": [{
                "kind": "piracy", "score": 2, "title": "Strait of Malacca",
                "name": "Strait of Malacca", "level": "MEDIUM", "source": "ReCAAP",
            }],
            "moment": {"leg": {
                "from": "Fort-de-France (Martinique)", "to": "Nouméa (Nouvelle-Calédonie)",
            }},
        },
        {
            "seq": 418, "t": "2026-07-20T10:00:00Z", "signature": "sat-dc3-caption", "legIdx": 3,
            "changes": [{
                "kind": "satellite", "score": 2,
                "caption": "Panache sédimentaire au large de Cayenne",
                "title": "Panache sédimentaire au large de Cayenne",
            }],
            "moment": {"leg": {
                "from": "Fort-de-France (Martinique)", "to": "Nouméa (Nouvelle-Calédonie)",
            }},
        },
        {
            "seq": 419, "t": "2026-08-12T10:00:00Z", "signature": "sat-dc3-image", "legIdx": 3,
            "changes": [{
                "kind": "satellite", "score": 2, "title": "Image satellite",
                "fact": "sentinel-2-l2a · 2026-09-12",
                "scene": {
                    "id": "S2A_MSIL2A_20260912T000000",
                    "product": "sentinel-2-l2a",
                    "datetime": "2026-09-12T00:00:00Z",
                },
            }],
            "moment": {"leg": {
                "from": "Fort-de-France (Martinique)", "to": "Nouméa (Nouvelle-Calédonie)",
            }},
        },
    ]
    return {**journal, "moments": list(journal["moments"]) + extra}


def test_dc3_phrases_from_stock_only():
    """FR/EN depuis un champ du stock ; silence si le champ manque."""
    from film_script import _dc3_from_ici_bag

    aton = {
        "kind": "aton", "title": "Feu des Minimes", "name": "Feu des Minimes",
        "t": "2026-07-08T10:00:00Z",
    }
    fr_a, en_a = change_sentence(aton, "fr"), change_sentence(aton, "en")
    assert "balise Feu des Minimes" in fr_a
    assert "beacon Feu des Minimes" in en_a
    assert change_sentence({"kind": "aton", "title": "buoy_lateral"}, "fr") == ""
    assert change_sentence({"kind": "aton", "title": "balise"}, "fr") == ""

    cable = {"kind": "cable", "title": "Honotua", "name": "Honotua"}
    fr_c = change_sentence(cable, "fr")
    en_c = change_sentence(cable, "en")
    assert "Honotua" in fr_c and "câble" in fr_c.casefold()
    assert "Honotua" in en_c and "cable" in en_c.casefold()
    assert change_sentence({"kind": "cable", "title": "active"}, "fr") == ""
    assert change_sentence({"kind": "cable", "nearby": True}, "fr") == ""
    assert change_sentence({"kind": "cable", "title": "4", "name": "4"}, "fr") == ""
    assert change_sentence({
        "kind": "cable", "title": "CABLES DE TELEFONO OPERATIVOS",
        "name": "CABLES DE TELEFONO OPERATIVOS",
    }, "fr") == ""

    depth = {"kind": "depth", "depth_m": 18.4, "source": "emodnet"}
    assert "Profondeur : 18,4 m" in change_sentence(depth, "fr")
    assert "Depth: 18.4 m" in change_sentence(depth, "en")
    assert change_sentence({"kind": "depth", "title": "gebco"}, "fr") == ""

    pir = {
        "kind": "piracy", "name": "Horn of Africa / Gulf Aden",
        "level": "HIGH", "source": "IMB/UKMTO",
    }
    assert "Piraterie — Horn of Africa / Gulf Aden · HIGH · IMB/UKMTO" in change_sentence(pir, "fr")
    assert "Piracy — Horn of Africa / Gulf Aden · HIGH · IMB/UKMTO" in change_sentence(pir, "en")
    assert change_sentence({"kind": "piracy", "title": "piracy"}, "fr") == ""

    sat = {
        "kind": "satellite",
        "caption": "Panache sédimentaire au large de Cayenne",
    }
    assert "Panache sédimentaire au large de Cayenne" in change_sentence(sat, "fr")
    silent_sat = {
        "kind": "satellite", "title": "Image satellite",
        "scene": {"id": "S2A_x", "product": "sentinel-2-l2a", "datetime": "2026-09-12T00:00:00Z"},
    }
    assert change_sentence(silent_sat, "fr") == ""
    assert change_sentence(silent_sat, "en") == ""
    assert "image satellite au-dessus" not in change_sentence(silent_sat, "fr")
    bag = _dc3_from_ici_bag({
        "aton": {"nearby": [{"name": "buoy_lateral", "nm": 4.6}]},
        "emodnet": {"cables": {"nearby": True}, "bathy": None},
        "depthOffshore": None,
        "piracy": None,
        "satellites": {"scene": {"id": "S2A_x", "product": "sentinel-2-l2a"}},
        "amp": [],
    })
    assert all(c["kind"] != "satellite" for c in bag)
    assert all(c["kind"] != "aton" for c in bag)
    assert all(c["kind"] != "cable" for c in bag)


def test_dc3_once_per_family_on_long_integral():
    """Intégral : une phrase par famille DC3 sur une longue jambe."""
    day = 86_400_000
    long_span = 40 * day
    picked = dose_dc3_leg_changes([
        {"id": "a1", "kind": "aton", "score": 2, "tMs": 4 * day,
         "title": "Feu des Minimes", "name": "Feu des Minimes", "nm": 2,
         "t": "2026-07-08T10:00:00Z"},
        {"id": "a2", "kind": "aton", "score": 2, "tMs": 14 * day,
         "title": "Phare Amédée", "name": "Phare Amédée", "nm": 5,
         "t": "2026-07-18T10:00:00Z"},
        {"id": "c1", "kind": "cable", "score": 2, "tMs": 8 * day,
         "title": "Honotua", "name": "Honotua", "t": "2026-07-12T10:00:00Z"},
        {"id": "c2", "kind": "cable", "score": 2, "tMs": 18 * day,
         "title": "Southern Cross", "name": "Southern Cross"},
        {"id": "d1", "kind": "depth", "score": 2, "tMs": 10 * day,
         "depth_m": 18.4, "t": "2026-07-14T10:00:00Z"},
        {"id": "d2", "kind": "depth", "score": 2, "tMs": 20 * day,
         "depthOffshore": -3888.0},
        {"id": "p1", "kind": "piracy", "score": 2, "tMs": 12 * day,
         "name": "Horn of Africa / Gulf Aden", "level": "HIGH",
         "source": "IMB/UKMTO", "t": "2026-07-16T10:00:00Z"},
        {"id": "p2", "kind": "piracy", "score": 2, "tMs": 22 * day,
         "name": "Strait of Malacca", "level": "MEDIUM", "source": "ReCAAP"},
        {"id": "s1", "kind": "satellite", "score": 2, "tMs": 16 * day,
         "caption": "Panache sédimentaire au large de Cayenne",
         "t": "2026-07-20T10:00:00Z"},
        {"id": "s2", "kind": "satellite", "score": 2, "tMs": 24 * day,
         "title": "Image satellite", "scene": {"product": "sentinel-2-l2a"}},
    ], long_span)
    kinds = [c["kind"] for c in picked]
    assert kinds.count("aton") == 1
    assert kinds.count("cable") == 1
    assert kinds.count("depth") == 1
    assert kinds.count("piracy") == 1
    assert kinds.count("satellite") == 1
    assert dose_dc3_leg_changes(picked, 2 * day) == []
    plan = build_raw_script(
        CLOCK, CLOCK["marks"], LIVE, _dc3_journal(),
        lang="fr", seconds=0, now_ms=NOW_MS,
    )
    pacific = next(
        c for c in plan["chapters"]
        if "Fort-de-France" in (c.get("fromName") or "")
        and "Nouméa" in (c.get("toName") or "")
    )
    hits = _dc3_family_hits(pacific.get("text") or "")
    assert hits["aton"] <= 1, pacific.get("text")
    assert hits["cable"] <= 1, pacific.get("text")
    assert hits["depth"] <= 1, pacific.get("text")
    assert hits["piracy"] <= 1, pacific.get("text")
    assert hits["aton"] == 1, pacific.get("text")
    assert hits["cable"] == 1, pacific.get("text")
    assert hits["depth"] == 1, pacific.get("text")
    assert hits["piracy"] == 1, pacific.get("text")
    assert hits["sat_invented"] == 0, pacific.get("text")
    blob = _script_blob(plan)
    assert "image satellite au-dessus" not in blob
    assert "Phare Amédée" not in blob or blob.count("balise") <= 1


def test_dc3_short_tier_omits_kinds_and_char_budget():
    """Le 2:30 n'empile pas les familles DC3. ≤ 2250 caractères."""
    assert film_char_budget(150) == 2250
    journal = _dc3_journal()
    short = build_raw_script(
        CLOCK, CLOCK["marks"], LIVE, journal,
        lang="fr", seconds=150, now_ms=NOW_MS,
    )
    blob = _script_blob(short)
    hits = _dc3_family_hits(blob)
    assert hits["aton"] == 0, blob
    assert hits["cable"] == 0, blob
    assert hits["depth"] == 0, blob
    assert hits["piracy"] == 0, blob
    assert hits["sat_invented"] == 0, blob
    assert short["chars"] <= film_char_budget(150)
    assert short["chars"] / 15 <= 150 * 1.1
    picked_short = select_chapter_changes(
        [
            {"id": "a", "kind": "aton", "score": 2, "tMs": 2, "title": "Feu des Minimes",
             "name": "Feu des Minimes"},
            {"id": "c", "kind": "cable", "score": 2, "tMs": 3, "title": "Honotua",
             "name": "Honotua"},
            {"id": "d", "kind": "depth", "score": 2, "tMs": 4, "depth_m": 18.4},
            {"id": "p", "kind": "piracy", "score": 2, "tMs": 5,
             "name": "Horn of Africa / Gulf Aden", "level": "HIGH"},
            {"id": "s", "kind": "satellite", "score": 2, "tMs": 6,
             "caption": "Panache sédimentaire au large de Cayenne"},
            {"id": "e", "kind": "escale", "score": 3, "tMs": 10,
             "title": "Arrivée à Nouméa", "fact": "x"},
        ],
        0, 10, budget=True, tier=film_priority_tier(150),
    )
    assert not any(c.get("kind") in {
        "aton", "cable", "depth", "piracy", "satellite",
    } for c in picked_short)


def test_dc3_bag_for_vs1():
    """Sac dc_subject_candidates : une entrée par famille DC3, oncePerFamilyOnLongLeg."""
    bag = dc_subject_candidates([
        {"kind": "aton", "title": "Feu des Minimes", "name": "Feu des Minimes",
         "nm": 2, "t": "2026-07-08T10:00:00Z"},
        {"kind": "aton", "title": "buoy_lateral", "name": "buoy_lateral"},
        {"kind": "cable", "title": "Honotua", "name": "Honotua",
         "t": "2026-07-12T10:00:00Z"},
        {"kind": "cable", "title": "active", "name": "active"},
        {"kind": "depth", "depth_m": 18.4, "t": "2026-07-14T10:00:00Z"},
        {"kind": "depth", "title": "gebco"},
        {"kind": "piracy", "name": "Horn of Africa / Gulf Aden", "level": "HIGH",
         "source": "IMB/UKMTO", "t": "2026-07-16T10:00:00Z"},
        {"kind": "satellite", "caption": "Panache sédimentaire au large de Cayenne",
         "t": "2026-07-20T10:00:00Z"},
        {"kind": "satellite", "title": "Image satellite",
         "scene": {"product": "sentinel-2-l2a"}},
    ], "fr")
    kinds = [r["kind"] for r in bag]
    assert kinds.count("aton") == 1
    assert kinds.count("cable") == 1
    assert kinds.count("depth") == 1
    assert kinds.count("piracy") == 1
    assert kinds.count("satellite") == 1
    by_kind = {r["kind"]: r for r in bag}
    assert by_kind["aton"]["oncePerFamilyOnLongLeg"] is True
    assert "Feu des Minimes" in by_kind["aton"]["phrase"]
    assert "Honotua" in by_kind["cable"]["phrase"]
    assert "câble" in by_kind["cable"]["phrase"].casefold()
    assert "18,4" in by_kind["depth"]["phrase"] or "18.4" in by_kind["depth"]["phrase"]
    assert "profondeur" in by_kind["depth"]["phrase"].casefold()
    assert "Horn of Africa / Gulf Aden" in by_kind["piracy"]["phrase"]
    assert "Panache sédimentaire" in by_kind["satellite"]["phrase"]
    assert "image satellite au-dessus" not in by_kind["satellite"]["phrase"]
    plan = build_raw_script(
        CLOCK, CLOCK["marks"], LIVE, _dc3_journal(),
        lang="fr", seconds=150, now_ms=NOW_MS,
    )
    stored_kinds = {r["kind"] for r in (plan.get("dcSubjects") or [])}
    assert {"aton", "cable", "depth", "piracy", "satellite"} <= stored_kinds
    for rec in plan["dcSubjects"]:
        assert rec["oncePerFamilyOnLongLeg"] is True
        assert rec["phrase"]


def test_ed1_write_window_follows_budget_and_accepts_integral():
    assert film_char_budget(150) == 2250
    assert film_write_window(150) == (2025, 2475)
    assert film_write_window(180) == (2430, 2970)
    assert film_write_window(0) is None
    long = "Berry-Mappemonde quitte La Rochelle. " * 120
    assert len(long) >= 4000
    ok, _, dropped = written_is_valid(long, long, [], seconds=0)
    assert dropped == 0
    assert ok
    ok_short, _, _ = written_is_valid(long, long, [], seconds=150)
    assert ok_short is False


def test_ed1_judge_closed_serves_super_without_ultra(monkeypatch):
    monkeypatch.setenv("NAVIGUIDE_LLM_DAILY_TOKENS_JUDGE", "0")  # Ultra fermé : chemin Super seul
    monkeypatch.delenv("NAVIGUIDE_LLM_MODE", raising=False)
    assert film_ultra_open() is False
    plan = {
        "chapters": [{
            "id": "c0",
            "text": "Le 15 mai, Berry-Mappemonde quitte La Rochelle. Arrivée à Ajaccio le 26 mai.",
            "tA": "2026-05-15T08:00:00Z",
            "tB": "2026-05-26T12:00:00Z",
            "fromName": "La Rochelle",
            "toName": "Ajaccio (Corse)",
            "anchors": [{"charIdx": 0, "t": "2026-05-15T08:00:00Z"}],
        }],
        "targetSeconds": 150,
    }
    hops = []

    async def fake_cascade(system, user, **kw):
        hops.append((kw.get("tier"), system[:24]))
        if "already-written" in system:
            raise AssertionError("Ultra appelé alors que le juge est fermé")
        sents = _sentences_from_user(user)
        if sents:
            return " ".join(
                s.replace("quitte", "laisse", 1) if "quitte" in s else s for s in sents
            ), "nemotron-super"
        return "", "rules"

    fr, en, stats = asyncio.run(write_film_chain(plan, seconds=150, cascade=fake_cascade))
    assert fr is not None
    assert stats["super"] == 1
    assert stats["ultra_edit"] == 0
    assert stats["ultra_judge"] == 0
    assert stats["source"] == WRITTEN_SOURCE
    assert fr["source"] == WRITTEN_SOURCE
    assert fr["model"]
    assert "laisse" in (fr["chapters"][0]["text"] or "")
    assert all(tier != "judge" for tier, _sys in hops)


def test_write_film_chain_never_calls_translate_written_plan(monkeypatch):
    import film_script as fs

    async def _trap(*_a, **_k):
        raise AssertionError("translate_written_plan must not run in production chain")

    monkeypatch.setattr(fs, "translate_written_plan", _trap)
    monkeypatch.setattr(fs, "film_ultra_open", lambda: False)

    async def _fake_write(_plan, *, lang, cascade, seconds):
        text = (_plan.get("chapters") or [{}])[0].get("text") or "x"
        ch = {"id": "a", "text": text, "source": fs.WRITTEN_SOURCE}
        return (
            {"chapters": [ch], "source": fs.WRITTEN_SOURCE, "targetSeconds": 150},
            {"rewritten": 1, "source": fs.WRITTEN_SOURCE},
        )

    async def _ok_reread(*_a, **_k):
        return True, {"source": "rules"}

    monkeypatch.setattr(fs, "write_stored_plan", _fake_write)
    monkeypatch.setattr(fs, "reread_before_store", _ok_reread)

    fr_raw = {"targetSeconds": 150, "chapters": [{"id": "a", "text": "Le 1er juin, départ vers Ajaccio."}]}
    en_raw = {"targetSeconds": 150, "chapters": [{"id": "a", "text": "On June 1, departure for Ajaccio."}]}
    fr_plan, en_plan, stats = asyncio.run(
        fs.write_film_chain(fr_raw, seconds=150, en_raw=en_raw, cascade=lambda *_a, **_k: ""),
    )
    assert fr_plan and en_plan
    assert stats.get("lightning") == 1


def test_ed1_ultra_edits_then_judges_or_falls_to_super(monkeypatch):
    monkeypatch.setenv("NAVIGUIDE_LLM_DAILY_TOKENS_JUDGE", "80000")
    monkeypatch.delenv("NAVIGUIDE_LLM_MODE", raising=False)
    monkeypatch.delenv("NAVIGUIDE_LLM_BACKGROUND", raising=False)
    assert film_ultra_open() is True
    plan = {
        "chapters": [{
            "id": "c0",
            "text": "Le 15 mai, Berry-Mappemonde quitte La Rochelle. Arrivée à Ajaccio le 26 mai.",
            "tA": "2026-05-15T08:00:00Z",
            "tB": "2026-05-26T12:00:00Z",
            "fromName": "La Rochelle",
            "toName": "Ajaccio (Corse)",
            "anchors": [{"charIdx": 0, "t": "2026-05-15T08:00:00Z"}],
        }],
        "targetSeconds": 150,
    }
    hops = []

    async def accept(system, user, **kw):
        hops.append(system[:20])
        if "real stops" in system:
            return '{"ok": true, "faults": []}', "nemotron-super"
        if "judge an already-written" in system:
            return '{"ok": true, "reason": "ok"}', "nemotron-ultra"
        if "edit an already-written" in system:
            blob = (user or "").split("text=", 1)[-1]
            return blob.replace("quitte", "laisse", 1) if "quitte" in blob else blob, "nemotron-ultra"
        sents = _sentences_from_user(user)
        if sents:
            return " ".join(sents), "nemotron-super"
        return "", "rules"

    fr, _en, stats = asyncio.run(write_film_chain(plan, seconds=150, cascade=accept))
    assert stats["ultra_edit"] == 1
    assert stats["ultra_judge"] == 1
    assert stats["reviewed"] is True
    assert stats["source"] == WRITTEN_SOURCE
    assert fr["source"] == WRITTEN_SOURCE
    assert fr["reviewedBy"] == "nemotron-ultra"
    assert fr["model"]
    assert hops.count("You judge an already") == 1
    assert hops.count("You edit an already-") == 1

    hops.clear()

    async def refuse(system, user, **kw):
        hops.append(system[:20])
        if "judge an already-written" in system:
            return '{"ok": false, "reason": "invented"}', "nemotron-ultra"
        if "edit an already-written" in system:
            blob = (user or "").split("text=", 1)[-1]
            return blob, "nemotron-ultra"
        sents = _sentences_from_user(user)
        if sents:
            return " ".join(
                s.replace("quitte", "laisse", 1) if "quitte" in s else s for s in sents
            ), "nemotron-super"
        return "", "rules"

    fr2, _en2, stats2 = asyncio.run(write_film_chain(plan, seconds=150, cascade=refuse))
    assert stats2["ultra_edit"] == 1
    assert stats2["ultra_judge"] == 1
    assert stats2["reviewed"] is False
    assert fr2["source"] == WRITTEN_SOURCE
    assert not fr2.get("reviewedBy")
    assert "laisse" in (fr2["chapters"][0]["text"] or "")


def test_ed2_mixed_nim_chapters_keep_nim_when_last_is_super(monkeypatch):
    """Deux chapitres NIM puis un Super : la source servie reste le repli, pas nemotron-super."""
    monkeypatch.setenv("NAVIGUIDE_LLM_DAILY_TOKENS_JUDGE", "0")  # Ultra fermé : chemin Super seul
    monkeypatch.delenv("NAVIGUIDE_LLM_MODE", raising=False)
    assert film_ultra_open() is False
    plan = {
        "chapters": [
            {
                "id": "c0",
                "text": "Le 15 mai, Berry-Mappemonde quitte La Rochelle. Arrivée à Ajaccio le 26 mai.",
                "tA": "2026-05-15T08:00:00Z",
                "tB": "2026-05-26T12:00:00Z",
                "fromName": "La Rochelle",
                "toName": "Ajaccio (Corse)",
                "anchors": [{"charIdx": 0, "t": "2026-05-15T08:00:00Z"}],
            },
            {
                "id": "c1",
                "text": "Le 27 mai, Berry-Mappemonde quitte Ajaccio. Arrivée à Fort-de-France le 23 juin.",
                "tA": "2026-05-27T08:00:00Z",
                "tB": "2026-06-23T12:00:00Z",
                "fromName": "Ajaccio (Corse)",
                "toName": "Fort-de-France (Martinique)",
                "anchors": [{"charIdx": 0, "t": "2026-05-27T08:00:00Z"}],
            },
            {
                "id": "c2",
                "text": "Le 26 juin, Berry-Mappemonde quitte Fort-de-France. Arrivée à Nouméa le 17 septembre.",
                "tA": "2026-06-26T08:00:00Z",
                "tB": "2026-09-17T12:00:00Z",
                "fromName": "Fort-de-France (Martinique)",
                "toName": "Nouméa (Nouvelle-Calédonie)",
                "anchors": [{"charIdx": 0, "t": "2026-06-26T08:00:00Z"}],
            },
        ],
        "targetSeconds": 150,
    }
    seen = []

    async def mixed(system, user, **kw):
        if kw.get("tier") != "write":
            return "", "rules"
        n = len(seen) + 1
        seen.append(n)
        sents = _sentences_from_user(user)
        src = "nemotron-super" if n == 3 else "nvidia-gpt-oss-20b"
        text = " ".join(
            s.replace("quitte", "laisse", 1) if "quitte" in s else s for s in sents
        )
        return text, src

    en_raw = {
        "targetSeconds": 150,
        "chapters": [
            {**chapter, "text": "On May 15, Berry-Mappemonde leaves La Rochelle. Arrival in Ajaccio on May 26."}
            for chapter in plan["chapters"]
        ],
    }
    fr, en, stats = asyncio.run(
        write_film_chain(plan, seconds=150, cascade=mixed, en_raw=en_raw),
    )
    assert seen == [1, 2, 3, 4, 5, 6]
    assert fr is not None
    assert en is not None
    assert stats["source"] == "nvidia-gpt-oss-20b"
    assert fr["source"] == "nvidia-gpt-oss-20b"
    assert fr["source"] != "nemotron-super"
    assert fr["source"] != WRITTEN_SOURCE
    assert fr["model"] == "openai/gpt-oss-20b"
    assert fr["model"] != "nvidia-gpt-oss-20b"
    assert not fr.get("reviewedBy")
    assert all("laisse" in (ch.get("text") or "") for ch in fr["chapters"])


def test_ed2_ultra_open_nim_edit_is_not_reviewed_by_ultra(monkeypatch):
    """Ultra ouvert, mais l'édition et le juge viennent de NIM : pas de reviewedBy Ultra."""
    monkeypatch.setenv("NAVIGUIDE_LLM_DAILY_TOKENS_JUDGE", "80000")
    monkeypatch.delenv("NAVIGUIDE_LLM_MODE", raising=False)
    monkeypatch.delenv("NAVIGUIDE_LLM_BACKGROUND", raising=False)
    assert film_ultra_open() is True
    plan = {
        "chapters": [{
            "id": "c0",
            "text": "Le 15 mai, Berry-Mappemonde quitte La Rochelle. Arrivée à Ajaccio le 26 mai.",
            "tA": "2026-05-15T08:00:00Z",
            "tB": "2026-05-26T12:00:00Z",
            "fromName": "La Rochelle",
            "toName": "Ajaccio (Corse)",
            "anchors": [{"charIdx": 0, "t": "2026-05-15T08:00:00Z"}],
        }],
        "targetSeconds": 150,
    }
    hops = []

    async def nim_fallback(system, user, **kw):
        hops.append(system[:24])
        if "judge an already-written" in system:
            return '{"ok": true, "reason": "ok"}', "nvidia-gpt-oss-20b"
        if "edit an already-written" in system:
            blob = (user or "").split("text=", 1)[-1]
            edited = blob.replace("laisse", "abandonne", 1) if "laisse" in blob else blob
            return edited, "nvidia-gpt-oss-20b"
        sents = _sentences_from_user(user)
        if sents:
            return " ".join(
                s.replace("quitte", "laisse", 1) if "quitte" in s else s for s in sents
            ), "nemotron-super"
        return "", "rules"

    fr, _en, stats = asyncio.run(write_film_chain(plan, seconds=150, cascade=nim_fallback))
    assert stats["ultra_edit"] == 1
    assert stats["ultra_judge"] == 0
    assert stats["reviewed"] is False
    assert fr["source"] == WRITTEN_SOURCE
    assert not fr.get("reviewedBy")
    text = fr["chapters"][0]["text"] or ""
    assert "laisse" in text
    assert "abandonne" not in text
    assert not any(h.startswith("You judge an already") for h in hops)


# ── VS1 : VL propose des ids, Lightning retire, le repli s'arrête au budget ──


def _vs1_full_bag():
    """Neuf familles DC + id d'avis réservé."""
    return film_choice_bag(dc_subject_candidates([
        {"kind": "amp", "event": "enter", "title": "Cabrera", "fact": "Cabrera",
         "nm": 0, "inside": True, "t": "2026-05-25T12:00:00Z"},
        {"kind": "station", "title": "Wave buoy 12", "fact": "Wave buoy 12 (4 nm)",
         "nm": 4, "t": "2026-07-08T10:00:00Z"},
        {"kind": "poe", "title": "Papeete", "fact": "Papeete",
         "t": "2026-07-12T10:00:00Z"},
        {"kind": "anchorage", "title": "Mouillage des Minimes",
         "fact": "Mouillage des Minimes", "t": "2026-07-14T10:00:00Z"},
        {"kind": "aton", "title": "Feu des Minimes", "name": "Feu des Minimes",
         "nm": 2, "t": "2026-07-08T10:00:00Z"},
        {"kind": "cable", "title": "Honotua", "name": "Honotua",
         "t": "2026-07-12T10:00:00Z"},
        {"kind": "depth", "depth_m": 18.4, "t": "2026-07-14T10:00:00Z"},
        {"kind": "piracy", "name": "Horn of Africa / Gulf Aden", "level": "HIGH",
         "source": "IMB/UKMTO", "t": "2026-07-16T10:00:00Z"},
        {"kind": "satellite", "caption": "Panache sédimentaire au large de Cayenne",
         "t": "2026-07-20T10:00:00Z"},
    ], "fr"))


def _vs1_dc_kinds(ids, bag):
    by_id = {c["id"]: c for c in bag}
    return [by_id[i]["kind"] for i in ids if i in by_id and by_id[i]["kind"] in DC_FAMILY_KINDS]


def test_vs1_bag_is_the_input_and_reserves_watch():
    bag = _vs1_full_bag()
    kinds = [c["kind"] for c in bag]
    assert kinds.count(TV1_WATCH_KIND) == 1
    assert {c["id"] for c in bag if c["kind"] == TV1_WATCH_KIND} == {TV1_WATCH_ID}
    for kind in DC_FAMILY_KINDS:
        assert kinds.count(kind) == 1, kind
    packed = film_candidates(JOURNAL, CLOCK["marks"], CLOCK, LIVE, NOW_MS)
    snap = tour_snapshot(packed)
    assert snap["image"].startswith("<svg")
    assert snap["legs"]


def test_vs1_vl_keeps_only_bag_ids_drops_prose():
    bag = _vs1_full_bag()
    allowed = {c["id"] for c in bag}

    async def fake(system, user, **_kw):
        assert _kw.get("tier") == "nano"
        assert "tour" in user or "image" in user
        return json.dumps({
            "ids": ["dc:buoy", "invented-id", "dc:watch"],
            "reason": "a whole paragraph of free text",
            "script": "Berry-Mappemonde quitte La Rochelle sous 99 nœuds.",
        }), "nemotron-lightning"

    ids, _src = asyncio.run(select_ids_with_vl(bag, {"legs": [], "image": "<svg/>"}, cascade=fake))
    assert ids == ["dc:buoy", TV1_WATCH_ID]
    assert "invented-id" not in ids
    kept = parse_choice_ids(
        json.dumps({"ids": ["dc:poe"], "script": "texte libre"}), allowed,
    )
    assert kept == ["dc:poe"]
    assert parse_choice_ids("Berry leaves La Rochelle.", allowed) is None


def test_vs1_lightning_can_only_remove():
    bag = _vs1_full_bag()
    proposed = ["dc:amp", "dc:buoy", "dc:poe", TV1_WATCH_ID]

    async def fake(system, user, **_kw):
        assert _kw.get("tier") == "nano"
        assert "remove" in system.lower() or "Do not add" in system
        return json.dumps({
            "ids": ["dc:amp", "dc:buoy", "dc:aton", "invented"],
        }), "nemotron-lightning"

    ids, _src = asyncio.run(trim_ids_with_lightning(proposed, bag, 150, cascade=fake))
    assert "dc:aton" not in ids
    assert "invented" not in ids
    assert set(ids) <= set(proposed)
    assert "dc:amp" in ids
    assert "dc:buoy" in ids


def test_vs1_fallback_full_bag_stays_in_150_budget():
    """Sac avec les neuf familles DC : 2:30 ≤ 2250, pas l'avis, pas neuf phrases."""
    assert film_char_budget(150) == 2250
    bag = _vs1_full_bag()
    assert len([c for c in bag if c["kind"] in DC_FAMILY_KINDS]) == 9
    ids = fallback_choose_ids(bag, 150)
    assert TV1_WATCH_ID not in ids
    assert TV1_WATCH_KIND not in _vs1_dc_kinds(ids, bag)
    assert len(_vs1_dc_kinds(ids, bag)) < 9
    journal = _dc3_journal()
    plan = build_raw_script(
        CLOCK, CLOCK["marks"], LIVE, journal,
        lang="fr", seconds=150, now_ms=NOW_MS,
    )
    out = apply_chosen_subjects(plan, ids, bag, 150)
    assert out["chars"] <= film_char_budget(150)
    blob = _script_blob(out)
    hits = _dc2_family_hits(blob)
    hits3 = _dc3_family_hits(blob)
    spoken = sum(1 for n in (*hits.values(), hits3["aton"], hits3["cable"], hits3["depth"], hits3["piracy"]) if n)
    assert spoken < 9, blob
    assert hits3["sat_invented"] == 0


def test_vs1_fallback_180_stays_in_budget():
    assert film_char_budget(180) == 2700
    bag = _vs1_full_bag()
    ids = fallback_choose_ids(bag, 180)
    assert TV1_WATCH_ID not in ids
    plan = build_raw_script(
        CLOCK, CLOCK["marks"], LIVE, _dc3_journal(),
        lang="fr", seconds=180, now_ms=NOW_MS,
    )
    out = apply_chosen_subjects(plan, ids, bag, 180)
    assert out["chars"] <= film_char_budget(180)
    assert len(_vs1_dc_kinds(ids, bag)) < 9


def test_vs1_mode_off_does_not_call_cascade(monkeypatch):
    monkeypatch.setenv("NAVIGUIDE_LLM_MODE", "off")
    bag = _vs1_full_bag()
    calls = []

    async def boom(*_a, **_k):
        calls.append(1)
        raise AssertionError("appel Nebius en mode off")

    ids, src = asyncio.run(choose_film_ids(bag, {"legs": []}, 150, cascade=boom))
    assert calls == []
    assert src == "rules"
    assert TV1_WATCH_ID not in ids
    assert ids == fallback_choose_ids(bag, 150)


def test_vs1_choice_cached_once_per_film_not_per_visit():
    bag = _vs1_full_bag()
    tour = {"legs": [{"name": "La Rochelle", "iso": "2026-05-15T12:00:00Z"}]}
    calls = {"n": 0}

    async def fake(system, user, **_kw):
        calls["n"] += 1
        if "remove" in system.lower() or "Do not add" in system:
            return json.dumps({"ids": ["dc:buoy"]}), "nemotron-lightning"
        return json.dumps({"ids": ["dc:buoy", "dc:poe"]}), "nemotron-lightning"

    a, _ = asyncio.run(choose_film_ids(bag, tour, 150, cascade=fake, allow_llm=True))
    n1 = calls["n"]
    b, src = asyncio.run(choose_film_ids(bag, tour, 150, cascade=fake, allow_llm=True))
    assert a == b
    assert calls["n"] == n1
    assert src == "cache"
    assert set(a) <= {"dc:buoy", "dc:poe"}


def test_vs1_serve_film_does_not_choose(tmp_path, monkeypatch):
    """Ouvrir Suivre lit le stock : zéro appel de choix."""
    import official_store
    from official_store import DiskBackend, OfficialStore, FILM_SCRIPT_REV

    store = OfficialStore(DiskBackend(tmp_path / "disk"), now=lambda: datetime(2026, 9, 19, 2, 0, tzinfo=timezone.utc))
    voy = {"t0": OFFICIAL_T0, "points": [{"lat": 1, "lon": 2}], "marks": []}
    monkeypatch.setattr(official_store, "_INSTANCE", store)
    monkeypatch.setattr(official_store, "_load_official", lambda: voy)
    calls = {"n": 0}

    async def boom(*_a, **_k):
        calls["n"] += 1
        raise AssertionError("choix au chargement de Suivre")

    monkeypatch.setattr("film_script.choose_film_ids", boom)
    plan = {
        "chapters": [{"id": "c0", "text": "Berry-Mappemonde quitte La Rochelle.", "tA": OFFICIAL_T0, "tB": OFFICIAL_T0}],
        "source": "rules",
        "chars": 40,
        "targetSeconds": 150,
    }
    payload = {"fr": plan, "default": plan, "variants": {"fr": {"150": plan}}, "film_script_rev": FILM_SCRIPT_REV}
    store.put("film", payload, store.family_key("film", voy, datetime(2026, 9, 19, 2, 0, tzinfo=timezone.utc)))
    out = official_store.serve_film("fr", 150)
    assert out.get("status") == "ready"
    assert calls["n"] == 0
    assert "La Rochelle" in (out.get("chapters") or [{}])[0].get("text") or ""


TV1_PHRASE = "Travaux annoncés à la marina de Motu Uta"
TV1_URL = "https://www.portautonome.nc/avis"


def _tv1_plan():
    return {
        "chapters": [{
            "id": "c0",
            "text": (
                "Berry-Mappemonde quitte Saint-Maur. "
                "La côte bretonne s'éloigne sous un ciel clair. "
                "Un alizé régulier porte la nuit."
            ),
            "tA": OFFICIAL_T0,
            "tB": OFFICIAL_T0,
        }],
    }


def test_tv1_watch_absent_from_230_present_on_fiche():
    """Sans l'id VS1 : phrase absente du 2:30, présente pour la fiche."""
    import escale_watch

    bag = _vs1_full_bag()
    for rec in bag:
        if rec["id"] == TV1_WATCH_ID:
            rec["phrase"] = TV1_PHRASE
            rec["url"] = TV1_URL
    plan = _tv1_plan()
    ids = fallback_choose_ids(bag, 150)
    assert TV1_WATCH_ID not in ids
    out = apply_chosen_subjects(plan, ids, bag, 150)
    blob = _script_blob(out)
    assert TV1_PHRASE not in blob
    assert out["chars"] <= film_char_budget(150)
    entry = escale_watch.news_entry(
        {"name": "Nouméa", "lat": -22.27, "lon": 166.44},
        TV1_PHRASE, TV1_URL, datetime(2026, 9, 20, tzinfo=timezone.utc),
        question="travaux", rounds=1,
    )
    assert entry["text"] == TV1_PHRASE
    assert entry["url"] == TV1_URL
    bag_fiche = escale_watch.attach_cached_news({"news": [entry]})
    assert any(n.get("text") == TV1_PHRASE for n in bag_fiche["news"])


def test_tv1_vs1_keeps_id_phrase_replaces_slot_within_budget():
    bag = [{
        "id": TV1_WATCH_ID, "kind": TV1_WATCH_KIND, "phrase": TV1_PHRASE, "url": TV1_URL,
    }]
    out = apply_chosen_subjects(_tv1_plan(), [TV1_WATCH_ID], bag, 150)
    blob = _script_blob(out)
    assert TV1_PHRASE in blob
    assert blob.count(TV1_PHRASE) == 1
    assert out["chars"] <= film_char_budget(150)
    import escale_watch
    assert escale_watch.watch_in_film() is True


def test_tv1_models_off_230_does_not_take_watch(monkeypatch):
    monkeypatch.setenv("NAVIGUIDE_LLM_MODE", "off")
    bag = _vs1_full_bag()
    for rec in bag:
        if rec["id"] == TV1_WATCH_ID:
            rec["phrase"] = TV1_PHRASE
    ids, src = asyncio.run(choose_film_ids(bag, {"legs": []}, 150, cascade=None, allow_llm=False))
    assert src == "rules"
    assert TV1_WATCH_ID not in ids
    out = apply_chosen_subjects(_tv1_plan(), ids, bag, 150)
    assert TV1_PHRASE not in _script_blob(out)
    assert out["chars"] <= film_char_budget(150)


def _vb1_plan():
    return build_raw_script(
        CLOCK, CLOCK["marks"], LIVE, _dc3_journal(),
        lang="fr", seconds=150, now_ms=NOW_MS,
    )


def test_vb1_absent_cache_matches_today(monkeypatch):
    """Sans fichier de route : mêmes ids et le même 2:30 que le repli."""
    monkeypatch.setenv("NAVIGUIDE_LLM_MODE", "off")
    import vl_route
    from official_store import FILM_SCRIPT_REV

    assert FILM_SCRIPT_REV == "vs1-ed2"
    assert vl_route.load() is None
    bag = _vs1_full_bag()
    calls = []

    async def boom(*_a, **_k):
        calls.append(1)
        raise AssertionError("appel Nebius")

    ids, src = asyncio.run(choose_film_ids(bag, {"legs": []}, 150, cascade=boom))
    assert calls == []
    assert src == "rules"
    assert ids == fallback_choose_ids(bag, 150)
    plan = _vb1_plan()
    out = apply_chosen_subjects(plan, ids, bag, 150)
    bare = apply_chosen_subjects(plan, fallback_choose_ids(bag, 150), bag, 150)
    assert _script_blob(out) == _script_blob(bare)
    assert out["chars"] <= film_char_budget(150)
    assert out["chars"] == bare["chars"]


def test_vb1_cache_adds_only_bag_ids_and_keeps_budget(monkeypatch):
    """Cache présent : id du sac ajouté, id inconnu ignoré, 2:30 ≤ 2250."""
    monkeypatch.setenv("NAVIGUIDE_LLM_MODE", "off")
    import film_script
    import vl_route
    from official_store import FILM_SCRIPT_REV

    assert FILM_SCRIPT_REV == "vs1-ed2"
    assert film_char_budget(150) == 2250
    bag = _vs1_full_bag()
    by_id = {c["id"]: c for c in bag}
    base = fallback_choose_ids(bag, 150)
    used = sum(len(str(by_id[i].get("phrase") or "")) for i in base)
    extra_id = None
    for rec in bag:
        if rec["id"] in base or rec.get("kind") == TV1_WATCH_KIND:
            continue
        if used + len(str(rec.get("phrase") or "")) <= film_char_budget(150):
            extra_id = rec["id"]
            break
    assert extra_id
    poison = "ZEPHYR-INVENTÉ sous 99 nœuds."
    vl_route.save({
        "rev": vl_route.REV,
        "route": vl_route.route_stamp(),
        "job": vl_route.JOB,
        "ids": [extra_id, "not-in-bag", extra_id],
        "points": [{
            "callId": "e001-test",
            "ids": [extra_id, "not-in-bag"],
            "reasons": {extra_id: poison},
        }],
    })
    calls = []

    async def boom(*_a, **_k):
        calls.append(1)
        raise AssertionError("appel Nebius")

    ids, src = asyncio.run(choose_film_ids(
        bag, {"legs": [{"name": "vb1", "iso": "2026-05-01T00:00:00Z"}]}, 150, cascade=boom,
    ))
    assert calls == []
    assert src == "rules"
    assert extra_id in ids
    assert "not-in-bag" not in ids
    assert TV1_WATCH_ID not in ids
    assert ids == film_script._trim_ids_to_budget(
        film_script._append_route_ids(base, [extra_id], bag), bag, 150,
    )
    out = apply_chosen_subjects(_vb1_plan(), ids, bag, 150)
    assert out["chars"] <= film_char_budget(150)
    blob = _script_blob(out)
    assert poison not in blob
    assert "ZEPHYR-INVENTÉ" not in blob
    assert "not-in-bag" not in blob


def test_vb1_lightning_can_drop_the_route_id(monkeypatch):
    monkeypatch.setenv("NAVIGUIDE_LLM_MODE", "off")
    import film_script
    import vl_route

    bag = _vs1_full_bag()
    by_id = {c["id"]: c for c in bag}
    base = fallback_choose_ids(bag, 150)
    used = sum(len(str(by_id[i].get("phrase") or "")) for i in base)
    extra_id = next(
        rec["id"] for rec in bag
        if rec["id"] not in base
        and rec.get("kind") != TV1_WATCH_KIND
        and used + len(str(rec.get("phrase") or "")) <= film_char_budget(150)
    )
    vl_route.save({
        "rev": vl_route.REV,
        "route": vl_route.route_stamp(),
        "job": vl_route.JOB,
        "ids": [extra_id],
        "points": [],
    })
    kept = base[:1]

    async def fake(system, user, **_kw):
        if "remove" in system.lower() or "Do not add" in system:
            return json.dumps({"ids": kept + ["not-in-bag"]}), "nemotron-lightning"
        return json.dumps({"ids": base}), "nemotron-lightning"

    ids, _src = asyncio.run(choose_film_ids(
        bag,
        {"legs": [{"name": "vb1-trim", "iso": "2026-05-02T00:00:00Z"}]},
        150,
        cascade=fake,
        allow_llm=True,
    ))
    assert extra_id not in ids
    assert "not-in-bag" not in ids
    assert ids == film_script._trim_ids_to_budget(kept, bag, 150)
    out = apply_chosen_subjects(_vb1_plan(), ids, bag, 150)
    assert out["chars"] <= film_char_budget(150)


def test_fm1_short_variants_fit_char_budget():
    """2:30 et 3:00 tiennent dans film_char_budget. Une seule révision avec ED2."""
    from official_store import FILM_SCRIPT_REV

    assert FILM_SCRIPT_REV == "vs1-ed2"
    short = _rich_raw(150)
    mid = _rich_raw(180)
    assert short["chars"] > 0
    assert mid["chars"] > 0
    assert short["chars"] <= film_char_budget(150)
    assert mid["chars"] <= film_char_budget(180)
    assert short["targetSeconds"] == 150
    assert mid["targetSeconds"] == 180
    if mid["chars"] > film_char_budget(150):
        assert short["chars"] < mid["chars"]


def test_vb1_suffix_does_not_rerun_vl_select(monkeypatch):
    """Le suffixe du cache de route change trim_key, pas vl_key."""
    monkeypatch.setenv("NAVIGUIDE_LLM_MODE", "off")
    import film_script
    import vl_route

    bag = _vs1_full_bag()
    tour = {"legs": [{"name": "vb1-fp", "iso": "2026-06-01T00:00:00Z"}]}
    calls = {"select": 0, "trim": 0}

    async def fake(system, user, **_kw):
        if "remove" in system.lower() or "Do not add" in system:
            calls["trim"] += 1
            return json.dumps({"ids": ["dc:buoy"]}), "nemotron-lightning"
        calls["select"] += 1
        return json.dumps({"ids": ["dc:buoy", "dc:poe"]}), "nemotron-lightning"

    asyncio.run(choose_film_ids(bag, tour, 150, cascade=fake, allow_llm=True))
    assert calls == {"select": 1, "trim": 1}

    vl_route.save({
        "rev": vl_route.REV,
        "route": vl_route.route_stamp(),
        "job": vl_route.JOB,
        "ids": ["dc:amp"],
        "points": [],
    })
    assert film_script._vb1_extra_ids(bag) == ["dc:amp"]
    _ids, src = asyncio.run(choose_film_ids(bag, tour, 150, cascade=fake, allow_llm=True))
    assert calls["select"] == 1
    assert calls["trim"] == 2
    assert src != "cache"


def _reread_pacific_stops():
    return [
        {"name": "Cayenne (Guyane)", "nm": 4000},
        {"name": "Halifax (Nouvelle-Écosse)", "nm": 4100},
        {"name": "Papeete (Polynésie française)", "nm": 16205},
        {"name": "Mata-Utu (Wallis-et-Futuna)", "nm": 17847},
        {"name": "Nouméa (Nouvelle-Calédonie)", "nm": 19177},
        {"name": "Dzaoudzi (Mayotte)", "nm": 28329},
        {"name": "Tromelin (TAAF)", "nm": 28729},
        {"name": "Saint-Gilles (La Réunion)", "nm": 29575},
        {"name": "Europa (TAAF)", "nm": 31032},
        {"name": "La Rochelle", "nm": 122},
    ]


def test_reread_refuses_papeete_skip_and_the_short_upcoming_list():
    """Papeete → Dzaoudzi, 12 124 milles, liste sans Mata-Utu ni Nouméa : refusé."""
    from film_script import nemotron_reread_report

    text = (
        "Berry-Mappemonde leaves Papeete (French Polynesia), heading west for "
        "Dzaoudzi (Mayotte). 12,124 miles, 63 days at sea. "
        "Stops still to come: Dzaoudzi, Tromelin, Saint-Gilles, Europa, La Rochelle."
    )
    report = nemotron_reread_report(text, _reread_pacific_stops(), lang="en")
    assert report["ok"] is False
    assert report["source"] == "simulate"
    assert "skip" in report["faults"]
    assert "upcoming" in report["faults"]
    assert "distance" in report["faults"]


def test_reread_refuses_cap_sur_a_stop_that_is_not_next():
    from film_script import nemotron_reread_report

    jumped = nemotron_reread_report(
        "",
        _reread_pacific_stops(),
        lang="fr",
        chapters=[{
            "fromName": "Papeete (Polynésie française)",
            "toName": "Dzaoudzi (Mayotte)",
            "text": "Le 5 octobre, cap sur Dzaoudzi : 12 124 milles, 63 jours de mer.",
        }],
    )
    assert jumped["ok"] is False
    assert "skip" in jumped["faults"]
    assert "distance" in jumped["faults"]

    direct = nemotron_reread_report(
        "",
        [{"name": "La Rochelle", "nm": 122}, {"name": "Ajaccio (Corse)", "nm": 1942}],
        lang="fr",
        chapters=[{
            "fromName": "La Rochelle",
            "toName": "Ajaccio (Corse)",
            "text": "Le 15 mai, cap sur Ajaccio : 1 820 milles, une dizaine de jours de mer.",
        }],
    )
    assert direct["ok"] is True


def test_reread_refuses_monaco_and_keeps_halifax():
    from film_script import nemotron_reread_report

    stops = _reread_pacific_stops()
    monaco = nemotron_reread_report(
        "On 6 June, entry formalities go through Monaco - Port de la Condamine (Port Hercule).",
        stops,
        lang="en",
    )
    assert monaco["ok"] is False
    assert monaco["faults"] == ["absent"]

    halifax = nemotron_reread_report(
        "The crew flies from Cayenne to Halifax. Arrival at Halifax on 2 July.",
        stops,
        lang="en",
    )
    assert halifax["ok"] is True
    assert halifax["faults"] == []


def test_reread_refuses_a_date_that_goes_backward():
    from film_script import nemotron_reread_report

    stops = _reread_pacific_stops()
    back = nemotron_reread_report(
        "On 27 August, the boat is at sea. On 24 August, the boat skirts Halifax.",
        stops,
        lang="en",
    )
    assert back["ok"] is False
    assert "date" in back["faults"]

    forward = nemotron_reread_report(
        "On 24 August, the boat skirts Halifax. On 27 August, the boat is at sea.",
        stops,
        lang="en",
    )
    assert forward["ok"] is True

    same_day = nemotron_reread_report(
        "On 15 May, Berry-Mappemonde leaves Saint-Maur by road for La Rochelle. "
        "Arrival at La Rochelle on 15 May.",
        [{"name": "Saint-Maur (Berry, Indre)"}, {"name": "La Rochelle"}],
        lang="en",
    )
    assert "date" not in same_day["faults"]
    assert same_day["ok"] is True

    bar = nemotron_reread_report(
        "",
        stops,
        lang="en",
        chapters=[{
            "fromName": "Cayenne (Guyane)",
            "toName": "Papeete (Polynésie française)",
            "text": "On 29 September, the boat is at sea.",
            "anchors": [{"charIdx": 0, "t": "2026-10-01T00:00:00Z"}],
        }],
    )
    assert "date" in bar["faults"]


def test_reanchor_never_moves_the_bar_back_before_a_later_depart():
    """« Le 15 octobre » dit après un départ le 17 : défaut du texte, la barre ne recule pas."""
    from film_script import _dates_regress, reanchor_written_chapter

    text = (
        "Le 17 octobre, Berry-Mappemonde quitte Papeete (Polynésie française), cap à l'ouest. "
        "Le 15 octobre, à vingt-six milles, le projet Programme Animlagon en Nouvelle-Calédonie."
    )
    chapter = {
        "text": text,
        "tA": "2026-10-14T03:34:42Z",
        "tB": "2026-10-27T13:55:18Z",
        "anchors": [
            {"charIdx": 0, "t": "2026-10-17T00:00:00Z"},
            {"charIdx": text.index("Le 15 octobre"), "t": "2026-10-15T00:00:00Z"},
        ],
    }
    out = reanchor_written_chapter(chapter, text, "fr")
    ts = [a["t"] for a in out]
    assert ts == sorted(ts)
    assert _dates_regress(text, "fr")


def test_reanchor_keeps_the_year_of_the_chapter_for_spoken_dates():
    """« Le 9 février » d'un chapitre de 2027 reste en 2027 (pas 2026 par défaut)."""
    from film_script import reanchor_written_chapter

    text = (
        "Le 30 janvier, Berry-Mappemonde quitte Saint-Gilles (La Réunion), cap à l'ouest pour Europa (TAAF). "
        "Puis, les eaux malgaches. "
        "Le 9 février, à dix-neuf milles, le projet ISEO. "
        "Arrivée à Europa (TAAF) le 21 février."
    )
    chapter = {
        "text": text,
        "tA": "2027-01-27T07:32:22Z",
        "tB": "2027-02-21T14:02:26Z",
        "anchors": [
            {"charIdx": 0, "t": "2027-01-30T07:32:22Z"},
            {"charIdx": text.index("Puis"), "t": "2027-01-30T07:32:22Z"},
            {"charIdx": text.index("Le 9 février"), "t": "2027-02-05T00:00:00Z"},
            {"charIdx": text.index("Arrivée"), "t": "2027-02-21T14:02:26Z"},
        ],
    }
    out = reanchor_written_chapter(chapter, text, "fr")
    ts = [a["t"] for a in out]
    assert all(t.startswith("2027") for t in ts), ts
    assert ts == sorted(ts)
    assert any(t.startswith("2027-02-09") for t in ts), ts


def test_reread_refuses_a_later_stop_announced_on_the_wrong_leg():
    from film_script import nemotron_reread_report

    stops = _reread_pacific_stops()
    mata = nemotron_reread_report(
        "",
        stops,
        lang="en",
        chapters=[{
            "fromName": "Cayenne (Guyane)",
            "toName": "Papeete (Polynésie française)",
            "text": "On 5 October, the approach is by Mata-Utu.",
        }],
    )
    assert mata["ok"] is False
    assert "offleg" in mata["faults"]

    noumea = nemotron_reread_report(
        "",
        stops,
        lang="en",
        chapters=[{
            "fromName": "Papeete (Polynésie française)",
            "toName": "Mata-Utu (Wallis-et-Futuna)",
            "text": "On 14 October, the approach is by Nouméa. The boat skirts Noumea.",
        }],
    )
    assert "offleg" in noumea["faults"]


def test_scrambled_clock_keeps_mata_utu_before_dzaoudzi():
    """L'horloge recolle Mata-Utu en mai 2027 : la route réelle le garde avant Dzaoudzi.

    Sans la date du sommet au mille d'itinéraire, le chapitre dit
    « cap sur Dzaoudzi : 12 124 milles » et la liste à venir commence par Dzaoudzi.
    """
    t0 = "2026-05-15T08:00:00Z"
    clock = {
        "t0": t0,
        "vertices": [
            {"tHours": 0, "sailNm": 122, "lat": 46.15, "lon": -1.15, "vehicle": "main"},
            {"tHours": 3422, "sailNm": 16205, "lat": -17.5, "lon": -149.5, "vehicle": "main"},
            {"tHours": 3680, "sailNm": 17847, "lat": -13.28, "lon": -176.17, "vehicle": "main"},
            {"tHours": 3858, "sailNm": 19177, "lat": -22.2, "lon": 166.4, "vehicle": "main"},
            {"tHours": 5849, "sailNm": 28328, "lat": -12.8, "lon": 45.2, "vehicle": "main"},
        ],
        "marks": [
            {"name": "Mata-Utu (Wallis-et-Futuna)", "tHours": 8454, "filmNm": 38364,
             "iso": "2027-05-02T14:00:00Z", "lat": 28.1, "lon": -16.1},
            {"name": "Nouméa (Nouvelle-Calédonie)", "tHours": 9020, "filmNm": 39295,
             "iso": "2027-05-26T04:00:00Z", "lat": 42.9, "lon": -9.7},
        ],
    }
    marks = [
        {"name": "La Rochelle", "nm": 122, "filmNm": 122, "lat": 46.15, "lon": -1.15},
        {"name": "Papeete (Polynésie française)", "nm": 16205, "filmNm": 16365,
         "lat": -17.5, "lon": -149.5},
        {"name": "Mata-Utu (Wallis-et-Futuna)", "nm": 17847, "filmNm": 18007,
         "lat": -13.28, "lon": -176.17},
        {"name": "Nouméa (Nouvelle-Calédonie)", "nm": 19177, "filmNm": 19337,
         "lat": -22.2, "lon": 166.4},
        {"name": "Dzaoudzi (Mayotte)", "nm": 28328, "filmNm": 28488,
         "iso": "2027-01-14T00:00:00Z", "lat": -12.8, "lon": 45.2},
    ]
    stops = official_dated_stops(marks, clock)
    names = [s["name"] for s in stops]
    assert names.index("Mata-Utu (Wallis-et-Futuna)") < names.index("Nouméa (Nouvelle-Calédonie)")
    assert names.index("Nouméa (Nouvelle-Calédonie)") < names.index("Dzaoudzi (Mayotte)")
    mata = next(s for s in stops if "Mata-Utu" in s["name"])
    assert mata["iso"].startswith("2026-")
    assert not mata["iso"].startswith("2027-05")
    review = {
        "legs": [
            {"from": "Cayenne", "to": "Papeete", "legNm": 8000},
            {"from": "Papeete", "to": "Dzaoudzi", "legNm": 12124},
            {"from": "Dzaoudzi", "to": "La Rochelle", "legNm": 11000},
        ]
    }
    upcoming = upcoming_stop_names(review, "Papeete", arrived=True, route_stops=stops)
    assert upcoming.index("Mata-Utu") < upcoming.index("Nouméa") < upcoming.index("Dzaoudzi")
    assert upcoming[-1] == "La Rochelle"
    t_end = int(datetime(2026, 10, 20, tzinfo=timezone.utc).timestamp() * 1000)
    wins = _windows(stops, _ms(t0), t_end, clock)
    leg = next(w for w in wins if "Papeete" in str(w.get("fromName") or ""))
    assert "Mata-Utu" in str(leg.get("toName") or leg.get("destName") or "")
    assert "Dzaoudzi" not in str(leg.get("toName") or "")
    gap = chapter_metrics(leg, review).get("legNm")
    assert isinstance(gap, (int, float)) and gap < 3000


def test_upcoming_keeps_stops_a_review_leg_skipped():
    review = {
        "legs": [
            {"from": "Cayenne", "to": "Papeete", "legNm": 8000},
            {"from": "Papeete", "to": "Dzaoudzi", "legNm": 12124},
            {"from": "Dzaoudzi", "to": "Tromelin", "legNm": 400},
            {"from": "Tromelin", "to": "Saint-Gilles", "legNm": 500},
        ]
    }
    route = _reread_pacific_stops()
    skipped = upcoming_stop_names(review, "Papeete", arrived=True)
    assert skipped[:1] == ["Dzaoudzi"]
    assert "Mata-Utu" not in skipped
    names = upcoming_stop_names(review, "Papeete", arrived=True, route_stops=route)
    assert names.index("Mata-Utu") < names.index("Nouméa") < names.index("Dzaoudzi")
    assert "Halifax" not in names


def test_pacific_chapter_does_not_announce_mata_utu_or_noumea():
    marks = [
        {"name": "Saint-Maur (Berry, Indre)", "nm": 0, "filmNm": 0,
         "iso": "2026-05-15T08:00:00Z", "holdHours": 0, "lat": 46.8, "lon": 1.6},
        {"name": "La Rochelle", "nm": 122, "filmNm": 122,
         "iso": "2026-05-15T12:00:00Z", "holdHours": 72, "lat": 46.15, "lon": -1.16},
        {"name": "Cayenne (Guyane)", "nm": 4000, "filmNm": 4000,
         "iso": "2026-08-01T00:00:00Z", "holdHours": 24, "lat": 4.9, "lon": -52.3},
        {"name": "Halifax (Nouvelle-Écosse)", "nm": 4100, "filmNm": 4100,
         "iso": "2026-08-02T00:00:00Z", "holdHours": 24, "lat": 44.6, "lon": -63.6},
        {"name": "Papeete (Polynésie française)", "nm": 16205, "filmNm": 16205,
         "iso": "2026-10-01T00:00:00Z", "holdHours": 72, "lat": -17.5, "lon": -149.5},
        {"name": "Mata-Utu (Wallis-et-Futuna)", "nm": 17847, "filmNm": 17847,
         "iso": "2026-10-14T00:00:00Z", "holdHours": 48, "lat": -13.28, "lon": -176.17},
        {"name": "Nouméa (Nouvelle-Calédonie)", "nm": 19177, "filmNm": 19177,
         "iso": "2026-10-22T00:00:00Z", "holdHours": 72, "lat": -22.2, "lon": 166.4},
    ]
    clock = {"t0": "2026-05-15T08:00:00Z", "marks": marks}
    journal = {"moments": [
        {"seq": 1, "t": "2026-09-20T00:00:00Z", "signature": "ap-mata", "changes": [
            {"kind": "approche", "score": 3, "title": "Mata-Utu", "fact": "Mata-Utu"},
        ], "moment": {"leg": {"from": "Cayenne (Guyane)", "to": "Papeete (Polynésie française)"}}},
        {"seq": 2, "t": "2026-10-05T00:00:00Z", "signature": "ap-nou", "changes": [
            {"kind": "approche", "score": 3, "title": "Nouméa", "fact": "Nouméa"},
        ], "moment": {"leg": {"from": "Papeete (Polynésie française)", "to": "Mata-Utu (Wallis-et-Futuna)"}}},
    ]}
    now = int(datetime(2026, 10, 25, tzinfo=timezone.utc).timestamp() * 1000)
    live = {"filmNm": 19200, "sailNm": 19200, "iso": "2026-10-25T00:00:00Z", "status": "live"}
    plan = build_raw_script(clock, marks, live, journal, lang="en", seconds=0, now_ms=now)
    blob = _script_blob(plan)
    assert "approach is by Mata-Utu" not in blob
    assert "approach is by Nouméa" not in blob
    assert "leaves Papeete" in blob and "Mata-Utu" in blob


def test_write_chain_does_not_store_a_skipped_stop(monkeypatch):
    """Le contrôle local refuse avant l'appel de relecture."""
    monkeypatch.setenv("NAVIGUIDE_LLM_DAILY_TOKENS_JUDGE", "0")  # Ultra fermé : chemin Super seul
    monkeypatch.delenv("NAVIGUIDE_LLM_MODE", raising=False)
    from film_script import nemotron_reread_report

    plan = {
        "chapters": [{
            "id": "c0",
            "text": "Berry-Mappemonde quitte Papeete pour Dzaoudzi. 12 124 milles.",
            "tA": "2026-10-02T00:00:00Z",
            "tB": "2026-12-04T00:00:00Z",
            "fromName": "Papeete (Polynésie française)",
            "toName": "Dzaoudzi (Mayotte)",
        }],
        "targetSeconds": 0,
        "routeStops": _reread_pacific_stops(),
    }
    calls = {"reread": 0}

    async def echo(system, user, **_kw):
        if "real stops" in (system or ""):
            calls["reread"] += 1
            return '{"ok": true}', "nemotron-super"
        sents = _sentences_from_user(user)
        if sents:
            return " ".join(sents), "nemotron-super"
        return "", "rules"

    fr, en, stats = asyncio.run(write_film_chain(plan, seconds=0, cascade=echo))
    assert fr is None and en is None
    assert calls["reread"] == 0
    assert "skip" in (stats.get("faults") or [])
    preview = nemotron_reread_report(plan["chapters"][0]["text"], plan["routeStops"], lang="fr")
    assert preview["ok"] is False


def test_write_chain_stores_nothing_when_the_reread_says_no(monkeypatch):
    """Texte honnête, relecture simulée qui refuse : rien en stock, aucun appel réseau."""
    monkeypatch.setenv("NAVIGUIDE_LLM_DAILY_TOKENS_JUDGE", "0")  # Ultra fermé : chemin Super seul
    monkeypatch.delenv("NAVIGUIDE_LLM_MODE", raising=False)
    plan = {
        "chapters": [{
            "id": "c0",
            "text": "Le 15 mai, Berry-Mappemonde quitte La Rochelle. Arrivée à Ajaccio le 26 mai.",
            "tA": "2026-05-15T08:00:00Z",
            "tB": "2026-05-26T12:00:00Z",
            "fromName": "La Rochelle",
            "toName": "Ajaccio (Corse)",
            "anchors": [{"charIdx": 0, "t": "2026-05-15T08:00:00Z"}],
        }],
        "targetSeconds": 150,
        "routeStops": [
            {"name": "La Rochelle"},
            {"name": "Ajaccio (Corse)"},
        ],
    }

    async def fake(system, user, **_kw):
        if "real stops" in (system or ""):
            return '{"ok": false, "faults": ["skip"]}', "nemotron-super"
        sents = _sentences_from_user(user)
        if sents:
            return " ".join(
                s.replace("quitte", "laisse", 1) if "quitte" in s else s for s in sents
            ), "nemotron-super"
        return "", "rules"

    fr, en, stats = asyncio.run(write_film_chain(plan, seconds=150, cascade=fake))
    assert fr is None and en is None
    assert stats.get("faults") == ["skip"]
    assert stats.get("reread") == "fail"


def _halifax_hop_marks():
    """Halifax sans mille de mer : Saint-Pierre porte l'odomètre 9 160, pas la jambe."""
    return [
        {"name": "Saint-Maur (Berry, Indre)", "nm": 0, "filmNm": 0, "iso": "2026-05-15T08:00:00Z",
         "holdHours": 0, "lat": 46.8, "lon": 1.6},
        {"name": "La Rochelle", "nm": 122, "filmNm": 122, "iso": "2026-05-15T12:00:00Z",
         "holdHours": 0, "lat": 46.15, "lon": -1.16},
        {"name": "Cayenne (Guyane)", "nm": 8700.6263, "filmNm": 8700.6263, "iso": "2026-08-08T19:59:04Z",
         "holdHours": 72, "lat": 4.93, "lon": -52.33},
        {"name": "Halifax (Nouvelle-Écosse)", "nm": 0, "filmNm": 8780.6263, "iso": "2026-08-12T03:59:04Z",
         "holdHours": 24, "lat": 44.65, "lon": -63.57, "kind": "hub"},
        {"name": "Saint-Pierre (Saint-Pierre-et-Miquelon)", "nm": 9160.2308, "filmNm": 9160.2308,
         "iso": "2026-08-15T08:59:54Z", "holdHours": 72, "lat": 46.78, "lon": -56.18},
    ]


def test_halifax_saint_pierre_hop_not_voyage():
    """Le second bateau dit les milles et les jours de Halifax → Saint-Pierre.

    L'odomètre du voyage (9 160 milles, 48 jours) n'est pas cette jambe.
    Aucun appel payant : brut par les règles seulement.
    """
    from film_script import _opening_nm_label, spoken_sea_days

    marks = _halifax_hop_marks()
    clock = {
        "t0": OFFICIAL_T0,
        "marks": marks,
        "vertices": [
            {"iso": "2026-08-12T03:59:04Z", "lat": 44.65, "lon": -63.57, "vehicle": "plane", "filmNm": 8780.6263},
            {"iso": "2026-08-13T12:00:00Z", "lat": 45.5, "lon": -60.0, "vehicle": "side", "filmNm": 8900},
            {"iso": "2026-08-15T08:59:54Z", "lat": 46.78, "lon": -56.18, "vehicle": "side", "filmNm": 9160.2308},
        ],
    }
    live = {"iso": "2026-08-20T00:00:00Z", "filmNm": 9200, "sailNm": 9200}
    now_ms = int(datetime(2026, 8, 20, tzinfo=timezone.utc).timestamp() * 1000)
    leg_nm, leg_days = 497, 2.6
    review = {"legs": [{
        "from": "Halifax (Nouvelle-Écosse)",
        "to": "Saint-Pierre (Saint-Pierre-et-Miquelon)",
        "legNm": leg_nm,
        "daysAtSea": leg_days,
        "plannedKnots": 8,
    }]}
    hop_film_nm = 9160.2308 - 8780.6263

    def hop_chapter(plan):
        for chapter in plan["chapters"]:
            frm = chapter.get("fromName") or ""
            to = chapter.get("toName") or ""
            if "Halifax" in frm and "Saint-Pierre" in to:
                return chapter
        return None

    def refuse_voyage(text):
        assert "9,160" not in text
        assert "9160" not in text
        assert "9 160" not in text
        assert "48 days" not in text
        assert "48 jours" not in text

    bare = build_raw_script(
        clock, marks, live, None, lang="en", seconds=150, now_ms=now_ms,
    )
    reviewed = build_raw_script(
        clock, marks, live, None, lang="en", seconds=150, now_ms=now_ms, review=review,
    )
    fr = build_raw_script(
        clock, marks, live, None, lang="fr", seconds=150, now_ms=now_ms, review=review,
    )
    bare_ch = hop_chapter(bare)
    rev_ch = hop_chapter(reviewed)
    fr_ch = hop_chapter(fr)
    assert bare_ch and rev_ch and fr_ch
    assert bare_ch["tA"].startswith("2026-08-12")
    assert bare_ch["tB"].startswith("2026-08-15")
    for chapter in (bare_ch, rev_ch, fr_ch):
        refuse_voyage(chapter["text"] or "")
    bare_text = bare_ch["text"] or ""
    rev_text = rev_ch["text"] or ""
    assert _opening_nm_label(hop_film_nm, "en") in bare_text
    assert "three days at sea" in bare_text
    assert _opening_nm_label(leg_nm, "en") in rev_text
    assert spoken_sea_days(leg_days, "en") in rev_text
    assert _opening_nm_label(leg_nm, "fr") in (fr_ch["text"] or "")
    assert "trois jours" in (fr_ch["text"] or "")

    # Poste : Halifax n'a pas de mille de mer, Saint-Pierre porte l'odomètre voile
    # et un filmNm différent. L'écart mélangé (417 milles, deux jours) n'est pas la jambe.
    station = [
        {"name": "Saint-Maur (Berry, Indre)", "nm": 0, "filmNm": 0, "iso": "2026-05-15T08:00:00Z",
         "holdHours": 0, "lat": 46.8, "lon": 1.6},
        {"name": "La Rochelle", "nm": 122, "filmNm": 122, "iso": "2026-05-15T12:00:00Z",
         "holdHours": 0, "lat": 46.15, "lon": -1.16},
        {"name": "Cayenne (Guyane)", "nm": 8700.626337220001, "filmNm": 8700.6263,
         "iso": "2026-08-08T19:59:04Z", "holdHours": 72, "lat": 4.93, "lon": -52.33},
        {"name": "Halifax (Nouvelle-Écosse)", "filmNm": 8780.6263, "iso": "2026-08-12T03:59:04Z",
         "holdHours": 24, "lat": 44.65, "lon": -63.57, "kind": "hub"},
        {"name": "Saint-Pierre (Saint-Pierre-et-Miquelon)", "nm": 9197.415837873954,
         "filmNm": 9160.2308, "iso": "2026-08-15T08:59:54Z", "holdHours": 72,
         "lat": 46.78, "lon": -56.18},
    ]
    station_clock = {"t0": OFFICIAL_T0, "marks": station, "vertices": clock["vertices"]}
    station_bare = build_raw_script(
        station_clock, station, live, None, lang="en", seconds=150, now_ms=now_ms,
    )
    station_rev = build_raw_script(
        station_clock, station, live, None, lang="en", seconds=150, now_ms=now_ms, review=review,
    )
    station_bare_ch = hop_chapter(station_bare)
    station_rev_ch = hop_chapter(station_rev)
    assert station_bare_ch and station_rev_ch
    for chapter in (station_bare_ch, station_rev_ch):
        refuse_voyage(chapter["text"] or "")
        assert "417" not in (chapter["text"] or "")
        assert "two days" not in (chapter["text"] or "")
    assert _opening_nm_label(hop_film_nm, "en") in (station_bare_ch["text"] or "")
    assert "three days at sea" in (station_bare_ch["text"] or "")
    assert _opening_nm_label(leg_nm, "en") in (station_rev_ch["text"] or "")
    assert spoken_sea_days(leg_days, "en") in (station_rev_ch["text"] or "")
    from film_script import repair_side_hop_plan

    stale = {
        "chapters": [{
            "fromName": "Halifax (Nouvelle-Écosse)",
            "toName": "Saint-Pierre (Saint-Pierre-et-Miquelon)",
            "tA": "2026-08-12T03:59:04Z",
            "tB": "2026-08-15T08:59:54Z",
            "text": (
                "On 13 August, in Halifax (Nouvelle-Écosse), the crew boards a second sailing boat "
                "for Saint-Pierre (Saint-Pierre-et-Miquelon). 9,160 miles, 48 days at sea. "
                "Arrival on 15 August."
            ),
        }],
        "chars": 10,
        "targetSeconds": 150,
    }
    repaired = repair_side_hop_plan(
        stale, clock=station_clock, marks=station, review=review, lang="en",
    )
    repaired_text = repaired["chapters"][0]["text"]
    refuse_voyage(repaired_text)
    assert "417" not in repaired_text
    assert _opening_nm_label(leg_nm, "en") in repaired_text
    assert spoken_sea_days(leg_days, "en") in repaired_text
    assert "Arrival on 15 August." in repaired_text


def test_window_leg_distance_keeps_film_odometer_scale():
    from film_script import _window_leg_nm

    window = {
        "from": {"nm": 9658.68, "filmNm": 9818.68},
        "to": {"filmNm": 16286.06},
    }

    assert round(_window_leg_nm(window), 2) == 6467.38


def test_reread_reads_spelled_out_french_dates():
    """Nemotron écrit « le quinze octobre » : la relecture doit voir le recul de date."""
    from film_script import _dates_regress, _parse_spoken_date

    assert _parse_spoken_date("Le quinze octobre, une campagne.", "fr").day == 15
    assert _parse_spoken_date("Le trente et un décembre, arrivée.", "fr").day == 31
    text = (
        "Le 17 octobre, Berry-Mappemonde quitte Papeete (Polynésie française). "
        "Le quinze octobre, à vingt-six milles, le projet Animlagon."
    )
    assert _dates_regress(text, "fr")


# --- Lot PR #126 (2) : magasin désynchronisé, nombres épelés, verdicts tronqués, durée 150 s ---

def test_moments_follow_their_leg_not_a_desynced_clock():
    """Horloge et moments de deux simulations : Samoa (jambe Papeete → Mata-Utu)
    ne parle jamais dans Cayenne → Papeete, même si sa date tombe dans cette fenêtre."""
    from film_script import _align_moments_to_window

    samoa = {
        "t": "2026-10-01T15:00:00Z", "legIdx": 9, "changes": [],
        "moment": {"leg": {"from": "Papeete (Polynésie française)", "to": "Mata-Utu (Wallis-et-Futuna)"}},
    }
    pacific = {
        "t": "2026-09-01T00:00:00Z", "legIdx": 8, "changes": [],
        "moment": {"leg": {"from": "Cayenne (Guyane)", "to": "Papeete (Polynésie française)"}},
    }
    free = {"t": "2026-09-10T00:00:00Z", "changes": []}
    cay_pap = {
        "fromName": "Cayenne (Guyane)", "destName": "Papeete (Polynésie française)",
        "tA": _ms("2026-08-29T04:00:00Z"), "tB": _ms("2026-10-14T03:00:00Z"),
    }
    kept = _align_moments_to_window([samoa, pacific, free], cay_pap, None)
    legs = [((m.get("moment") or {}).get("leg") or {}).get("to") for m in kept]
    assert "Mata-Utu (Wallis-et-Futuna)" not in legs
    assert "Papeete (Polynésie française)" in legs
    assert free in kept
    pap_mat = {
        "fromName": "Papeete (Polynésie française)", "destName": "Mata-Utu (Wallis-et-Futuna)",
        "tA": _ms("2026-10-14T03:00:00Z"), "tB": _ms("2026-10-27T13:00:00Z"),
    }
    moved = [m for m in _align_moments_to_window([samoa], pap_mat, None) if m.get("tSim")]
    assert moved, "Samoa est reporté dans la fenêtre de SA jambe"
    t = _ms(moved[0]["t"])
    assert pap_mat["tA"] < t <= pap_mat["tB"]


def test_spelled_number_is_checked_like_a_digit():
    """173 épelé « cent soixante-dix-sept » (177) est un chiffre inventé."""
    from story_cascade import filter_numbers, spelled_numbers_to_digits

    assert spelled_numbers_to_digits("cent soixante-dix-sept milles") == "177 milles"
    assert spelled_numbers_to_digits("quatre-vingt-dix-sept") == "97"
    assert spelled_numbers_to_digits("vingt et un milles") == "21 milles"
    assert spelled_numbers_to_digits("un mille deux cents milles") == "1200 milles"
    assert spelled_numbers_to_digits("un bateau neuf") == "un bateau neuf"
    facts = "Gustavia à 173 milles. 1 200 milles."
    out, dropped = filter_numbers("Gustavia est à cent soixante-dix-sept milles.", facts, spelled=True)
    assert dropped == 1 and out == ""
    out, dropped = filter_numbers("Gustavia est à cent soixante-treize milles.", facts, spelled=True)
    assert dropped == 0
    out, dropped = filter_numbers("Un mille deux cents milles de mer.", facts, spelled=True)
    assert dropped == 0


def _one_chapter_plan():
    return {
        "chapters": [{
            "id": "c0",
            "text": "Le 15 mai, Berry-Mappemonde quitte La Rochelle. Arrivée à Ajaccio le 26 mai.",
            "tA": "2026-05-15T08:00:00Z", "tB": "2026-05-26T12:00:00Z",
            "fromName": "La Rochelle", "toName": "Ajaccio (Corse)", "destName": "Ajaccio (Corse)",
        }],
    }


def test_truncated_reread_verdict_is_never_a_pass():
    from film_script import reread_before_store

    stops = [{"name": "La Rochelle"}, {"name": "Ajaccio (Corse)"}]
    for cut in ('{"ok": true, "faults": [', "", "The user wants me to check"):
        async def fake(system, user, _cut=cut, **kw):
            return _cut, "nemotron-super"
        ok, rep = asyncio.run(reread_before_store(_one_chapter_plan(), stops, cascade=fake, lang="fr"))
        assert ok is False, cut
        assert rep["faults"] == ["verdict-illisible"]


def test_english_film_final_reread_uses_mocked_judge_tier(monkeypatch):
    import film_script as fs

    monkeypatch.setattr(fs, "film_ultra_open", lambda: True)
    monkeypatch.setattr(fs, "nemotron_reread_report", lambda *_a, **_k: {"ok": True, "faults": []})
    seen = []

    async def fake_cascade(_system, _user, **kw):
        seen.append(kw)
        return '{"ok": true, "faults": []}', "nemotron-ultra"

    plan = {
        "chapters": [{
            "id": "c0",
            "text": "On 15 May, Berry-Mappemonde leaves La Rochelle. Arrival in Ajaccio on 26 May.",
            "fromName": "La Rochelle", "toName": "Ajaccio (Corsica)",
        }],
    }
    stops = [{"name": "La Rochelle"}, {"name": "Ajaccio (Corsica)"}]
    ok, report = asyncio.run(fs.reread_before_store(plan, stops, cascade=fake_cascade, lang="en"))

    assert ok is True
    assert report["source"] == "nemotron-ultra"
    assert len(seen) == 1
    assert seen[0]["tier"] == "judge"
    assert seen[0]["max_tokens"] == fs.REREAD_MAX_TOKENS


def test_truncated_ultra_judge_verdict_is_never_a_pass():
    from film_script import judge_written_once

    async def cut(system, user, **kw):
        return '{"ok": tr', "nemotron-ultra"

    assert asyncio.run(judge_written_once(_one_chapter_plan(), cascade=cut)) is False

    seen = []

    async def full(system, user, **kw):
        seen.append(kw.get("max_tokens"))
        assert '"facts"' in user, "le juge lit les faits du chapitre"
        return '{"ok": true, "reason": "ok"}', "nemotron-ultra"

    assert asyncio.run(judge_written_once(_one_chapter_plan(), cascade=full, raw_plan=_one_chapter_plan())) is True
    assert seen and all(m >= 256 for m in seen)


def test_ultra_edit_is_per_chapter_and_keeps_super_when_cut():
    from film_script import edit_written_once

    plan = _one_chapter_plan()
    maxes = []

    async def cut(system, user, **kw):
        maxes.append(kw.get("max_tokens"))
        return "Le 15 mai, Berry-Mappemonde laisse La", "nemotron-ultra"

    assert asyncio.run(edit_written_once(plan, plan, cascade=cut)) is None
    assert maxes and maxes[0] > len(plan["chapters"][0]["text"])


def test_condensed_150_fits_the_measured_speech_rate():
    from film_script import FILM_ESTIMATE_CPS, condense_written_plan, film_spoken_char_cap

    sent = "Puis, les eaux d'un pays voisin, longées au large sous le vent."
    chapters = []
    for i in range(6):
        body = " ".join([sent] * 12)
        chapters.append({
            "id": f"c{i}",
            "text": f"Le {i + 1} juin, Berry-Mappemonde quitte Port{i}. {body} Arrivée à Port{i + 1} le {i + 2} juin.",
            "tA": f"2026-06-{i + 1:02d}T08:00:00Z", "tB": f"2026-06-{i + 2:02d}T08:00:00Z",
            "fromName": f"Port{i}", "destName": f"Port{i + 1}", "toName": f"Port{i + 1}",
        })
    out = condense_written_plan({"chapters": chapters}, 150, lang="fr")
    assert out["chars"] <= film_spoken_char_cap(150) < 150 * FILM_ESTIMATE_CPS
    assert out["estimatedSeconds"] <= 150
    for ch in out["chapters"]:
        assert "quitte" in ch["text"] and "Arrivée" in ch["text"]


def test_llm_date_fault_needs_the_local_date_check():
    """« date qui recule » du relecteur sur un texte aux dates en ordre : non retenue
    (écrite dans le rapport) ; une escale sautée reste un refus."""
    from film_script import reread_before_store

    stops = [{"name": "La Rochelle"}, {"name": "Ajaccio (Corse)"}]

    async def date_fault(system, user, **kw):
        return '{"ok": false, "faults": ["date: 26 mai vs 15 mai"]}', "nemotron-ultra"

    ok, rep = asyncio.run(reread_before_store(_one_chapter_plan(), stops, cascade=date_fault, lang="fr"))
    assert ok is True
    assert rep.get("unconfirmed") == ["date: 26 mai vs 15 mai"]

    async def skip_fault(system, user, **kw):
        return '{"ok": false, "faults": ["off-route: Rome", "date: x"]}', "nemotron-ultra"

    ok, rep = asyncio.run(reread_before_store(_one_chapter_plan(), stops, cascade=skip_fault, lang="fr"))
    assert ok is False and rep["faults"][0] == "off-route: Rome"


def test_llm_skip_fault_is_checked_against_the_text():
    from film_script import reread_before_store

    stops = [{"name": "La Rochelle"}, {"name": "Ajaccio (Corse)"}]

    async def named(system, user, **kw):
        return '{"ok": false, "faults": ["skip: Ajaccio"]}', "nemotron-ultra"

    ok, rep = asyncio.run(reread_before_store(_one_chapter_plan(), stops, cascade=named, lang="fr"))
    assert ok is True and rep.get("unconfirmed") == ["skip: Ajaccio"]
    plan = _one_chapter_plan()
    plan["chapters"][0]["text"] = "Le 15 mai, Berry-Mappemonde quitte La Rochelle. Le 26 mai, escale."
    ok, rep = asyncio.run(reread_before_store(plan, stops, cascade=named, lang="fr"))
    assert ok is False and rep["faults"] == ["skip: Ajaccio"]


def test_partial_grouped_number_is_not_a_fact():
    import story_cascade as sc
    facts = {"raw": "départ vers La Rochelle : 8 393 milles, 96 jours de mer."}
    out, dropped = sc.filter_numbers("Départ : 393 milles, 96 jours de mer.", facts, spelled=True)
    assert dropped == 1 and out == ""
    out, dropped = sc.filter_numbers("Départ : 8 393 milles, 96 jours de mer.", facts, spelled=True)
    assert dropped == 0


def test_super_spelled_numbers_become_digits_before_edit():
    import film_script as fs
    t = "Départ : huit mille trois cent quatre-vingt-treize milles, le trente et un mai 2026, un jour de mer."
    assert fs._digits_for_speech(t) == "Départ : 8 393 milles, le 31 mai 2026, un jour de mer."


def test_translation_never_mixes_french_fallback_sentences():
    import asyncio
    import film_script as fs
    raw_ch = {"id": "c1", "text": "Le 4 juin, départ vers Fort-de-France. Arrivée le 14 juillet.", "anchors": []}
    fr = {"chapters": [{**raw_ch, "text": "Le 4 juin, départ vers Fort-de-France. Arrivée le 14 juillet."}]}

    async def half(system, user, **kw):
        return "On June 4, departure for Fort-de-France.", "nemotron-lightning"

    async def full(system, user, **kw):
        return "On June 4, departure for Fort-de-France. Arrival on July 14.", "nemotron-lightning"

    assert asyncio.run(fs.translate_written_plan(fr, {"chapters": [raw_ch]}, cascade=half)) is None
    en = asyncio.run(fs.translate_written_plan(fr, {"chapters": [raw_ch]}, cascade=full))
    assert en and "juin" not in en["chapters"][0]["text"]


def test_english_exonyms_pass_but_invented_place_does_not():
    import film_script as fs
    got = fs._en_translation_names(
        "Arrival at Ajaccio (Corsica). Then Samoan waters. Then Rome.",
        "Arrivée à Ajaccio (Corse). Puis les eaux samoanes.",
    )
    assert {"corsica", "samoan"} <= got and "rome" not in got


def test_translation_keeps_an_english_exonym_sentence():
    import asyncio
    import film_script as fs
    raw_ch = {"id": "c1", "text": "Arrivée à Ajaccio (Corse).", "anchors": []}

    async def tr(system, user, **kw):
        return "Arrival at Ajaccio (Corsica).", "nemotron-lightning"

    en = asyncio.run(fs.translate_written_plan({"chapters": [raw_ch]}, {"chapters": [raw_ch]}, cascade=tr))
    assert en and en["chapters"][0]["text"] == "Arrival at Ajaccio (Corsica)."


def test_translation_retry_asks_differently_and_skips_raw_number_filter():
    import asyncio
    import story_cascade as sc
    import film_script as fs
    raw_ch = {"id": "c1", "text": "Trois jours d'escale.", "anchors": []}
    seen = []

    async def tr(system, user, **kw):
        seen.append((user, kw.get("facts")))
        if len(seen) == 1:
            return "Trois jours d'escale.", "nemotron-lightning"
        return "3 days of stopover.", "nemotron-lightning"

    en = asyncio.run(fs.translate_written_plan({"chapters": [raw_ch]}, {"chapters": [raw_ch]}, cascade=tr))
    assert seen[0][0] != seen[1][0]
    assert all(f is sc.NO_NUMBER_FILTER for _, f in seen)
    assert en and en["chapters"][0]["text"] == "3 days of stopover."


def test_english_translation_keeps_approximations_and_nationalities():
    import film_script as fs
    src = "Le 4 juin : 5 153 milles, une trentaine de jours de mer. Puis, les eaux espagnoles. Puis, L'ile Rousse."
    en = "On June 4: 5 153 miles, about thirty days at sea. Then, Spanish waters. Then, L'Île-Rousse."
    facts = {"raw": src, "en_names": sorted(n.title() for n in fs._en_translation_names(en, src)),
             "approx": fs._fr_approx_numbers(src)}
    _, rw, fb = fs.apply_written_guard(src, en, facts, lang="en")
    assert fb == 0 and rw == 3


def test_condense_150_drops_berth_and_repeated_region_before_cutting_facts():
    import film_script as fs
    chs = [{"id": f"c{i}", "fromName": "A", "toName": "Gustavia (Saint-Barthélemy)",
            "text": "Le 21 juillet, départ vers Gustavia : 173 milles nautiques, un jour de mer. "
                    "Arrivée à Gustavia (Saint-Barthélemy) le 23 juillet, à la marina de Gustavia. "
                    "Arrivée à Gustavia (Saint-Barthélemy) le 23 juillet, à la marina de Gustavia."}
           for i in range(20)]
    fs._condense_to_spoken_seconds(chs, 150)
    t = chs[0]["text"]
    assert "173 milles" in t and "23 juillet" in t and "marina" not in t
    assert t.count("Arrivée") == 1


def test_non_breaking_hyphen_in_a_name_is_not_an_unknown_place():
    import film_script as fs
    src = "Arrivée à Mata-Utu (Wallis-et-Futuna) le 27 octobre."
    out, rw, fb = fs.apply_written_guard(src, "Arrivée à Mata\u2011Utu (Wallis-et-Futuna) le 27 octobre.", {"raw": src})
    assert fb == 0 and "\u2011" not in out


def test_return_to_a_stop_is_not_a_skip():
    import film_script as fs
    rows = [{"name": n} for n in ("Marigot", "Cayenne (Guyane)", "Halifax (Nouvelle-Écosse)",
                                  "Saint-Pierre (Saint-Pierre-et-Miquelon)", "Halifax (Nouvelle-Écosse)",
                                  "Cayenne (Guyane)", "Papeete (Polynésie française)")]
    rows = fs._as_stop_rows(rows)
    assert fs._sea_between(rows, "Cayenne (Guyane)", "Papeete") == []
    t = "Then, the catamaran sets sail again, heading for Papeete (French Polynesia)."
    assert fs._cap_leg_faults(t, rows, "Cayenne (Guyane)", "Papeete (Polynésie française)") == []


def test_grouped_distance_fact_keeps_its_thousands():
    import film_script as fs
    facts = fs.chapter_structured_facts({"text": "Le 4 juin : 5 153 milles, à 8 nœuds."}, lang="fr")
    assert "5 153 milles" in facts["distances"] and "153 milles" not in facts["distances"]


def test_close_but_different_place_is_not_an_exonym():
    import film_script as fs
    got = fs._en_translation_names("The Focolari Movement project. Then Rochefort.", "Mouvement des Focolari. La Rochelle.")
    assert "movement" in got and "rochefort" not in got


def test_truncated_reread_is_asked_again_shorter():
    import asyncio
    import film_script as fs
    seen = []

    async def casc(system, user, **kw):
        seen.append(user)
        if len(seen) == 1:
            return '{"ok": false, "faults": ["date: a very long ramble that never', "nemotron-ultra"
        return '{"ok": true, "faults": []}', "nemotron-ultra"

    plan = {"chapters": [{"id": "c", "fromName": "A", "toName": "B", "text": "Départ de A. Arrivée à B."}]}
    stops = [{"name": "A"}, {"name": "B"}]
    ok, _ = asyncio.run(fs.reread_before_store(plan, stops, cascade=casc, lang="fr"))
    assert ok and len(seen) == 2 and seen[0] != seen[1]


def test_fortnight_only_translates_quinzaine():
    import asyncio
    import film_script as fs
    raw_ch = {"id": "c", "text": "Le 17 octobre, une dizaine de jours de mer.", "anchors": []}
    answers = iter(["On October 17, a fortnight at sea."] * 2)

    async def tr(system, user, **kw):
        return next(answers), "nemotron-lightning"

    en = asyncio.run(fs.translate_written_plan({"chapters": [raw_ch]}, {"chapters": [raw_ch]}, cascade=tr))
    assert en and "ten days" in en["chapters"][0]["text"]


def _fc2_side_plan() -> dict:
    """Deux jambes : La Rochelle → Ajaccio (mai) puis Halifax → Saint-Pierre (août)."""
    return {
        "chapters": [
            {
                "id": "leg-1", "tA": "2026-05-15T08:00:01Z", "tB": "2026-06-01T22:13:28Z",
                "fromName": "La Rochelle", "toName": "Ajaccio (Corse)",
                "text": "Le 15 mai, départ vers Ajaccio : 1 820 milles, une vingtaine de jours de mer. "
                        "Arrivée à Ajaccio (Corse) le 1er juin.",
            },
            {
                "id": "leg-8", "tA": "2026-08-19T04:28:25Z", "tB": "2026-08-21T18:34:56Z",
                "fromName": "Halifax (Nouvelle-Écosse)",
                "toName": "Saint-Pierre (Saint-Pierre-et-Miquelon)",
                "text": "Le 19 août, à Halifax (Nouvelle-Écosse), l'équipage embarque sur un second voilier "
                        "pour Saint-Pierre (Saint-Pierre-et-Miquelon). 497 milles, trois jours de mer. "
                        "Arrivée à Saint-Pierre (Saint-Pierre-et-Miquelon) le 21 août.",
            },
        ],
    }


def test_fc2_side_boat_opening_is_never_a_redite():
    """fc2 : l'ouverture du second bateau n'est ni remplacée ni coupée en premier."""
    from film_script import _trim_sentence_rank  # noqa: PLC0415

    for sent in (
        "Le 19 août, à Halifax (Nouvelle-Écosse), l'équipage embarque sur un second voilier pour Saint-Pierre.",
        "Puis, à Saint-Pierre, l'équipage reprend un second voilier pour Halifax.",
        "On 19 August, in Halifax, the crew boards a second sailing boat for Saint-Pierre.",
    ):
        assert _trim_sentence_rank(sent) == 0, sent


def test_fc2_dated_subject_stays_in_its_own_leg():
    """« Le 21 mai, une bouée » ne remplace pas une phrase de la jambe d'août."""
    bag = [{
        "id": "dc:buoy", "kind": "buoy", "phrase": "Le 21 mai, une bouée.",
        "name": "EMSO", "t": "2026-05-21T14:39:18Z",
    }]
    out = apply_chosen_subjects(_fc2_side_plan(), ["dc:buoy"], bag, 150)
    side = out["chapters"][1]["text"]
    assert "une bouée" not in side
    assert "embarque sur un second voilier" in side
    assert "497 milles" in side


def _fc2_side_plan_with_slots(leg1_slot: bool = True, leg8_slot: bool = True) -> dict:
    """Plan fc2 avec une phrase remplaçable (rang 2) dans chaque jambe voulue."""
    plan = _fc2_side_plan()
    if leg1_slot:
        plan["chapters"][0]["text"] += " La côte basque défile au loin."
    if leg8_slot:
        plan["chapters"][1]["text"] += " La houle se creuse au large."
    return plan


def test_fc2_dated_subject_goes_to_its_own_leg_slot_not_the_first_slot():
    """Règle de date (#137) : la bouée de mai prend l'emplacement de leg-1, pas celui d'août.

    Sans la règle, le premier emplacement libre est pris : on place la bouée
    dans leg-8 si leg-1 n'a pas d'emplacement ; ici on vérifie aussi l'ordre
    inverse (emplacement d'août en tête de liste) en mettant la bouée seule.
    """
    from film_script import _repeat_slots, _trim_sentence_rank  # noqa: PLC0415

    assert _trim_sentence_rank("La côte basque défile au loin.") >= 2
    assert _trim_sentence_rank("La houle se creuse au large.") >= 2
    bag = [{
        "id": "dc:buoy", "kind": "buoy", "phrase": "Le 21 mai, une bouée.",
        "name": "EMSO", "t": "2026-05-21T14:39:18Z",
    }]
    # Emplacement seulement dans leg-8 : sans la règle de date, la bouée de mai
    # irait remplacer la houle d'août.
    plan = _fc2_side_plan_with_slots(leg1_slot=False, leg8_slot=True)
    assert len(_repeat_slots(plan["chapters"])) == 1
    out = apply_chosen_subjects(plan, ["dc:buoy"], bag, 150)
    assert "une bouée" not in out["chapters"][1]["text"]
    assert "La houle se creuse au large." in out["chapters"][1]["text"]
    # Emplacements dans les deux jambes : la bouée va dans leg-1 uniquement.
    out = apply_chosen_subjects(_fc2_side_plan_with_slots(), ["dc:buoy"], bag, 150)
    assert "Le 21 mai, une bouée." in out["chapters"][0]["text"]
    assert "La côte basque" not in out["chapters"][0]["text"]
    assert "une bouée" not in out["chapters"][1]["text"]
    assert "La houle se creuse au large." in out["chapters"][1]["text"]


def test_integral_dated_subject_without_slot_is_said_once_and_nothing_repeated():
    """Intégral (seconds=0) : bouée datée sans emplacement + balise non datée.

    Contre-revue 136-137 P1-1 : ``remaining[used:]`` redisait la balise (placée)
    et perdait la bouée (sautée). Chaque sujet doit être dit exactement une fois,
    la bouée dans sa jambe (leg-1, mai).
    """
    bag = [
        {
            "id": "dc:buoy", "kind": "buoy", "phrase": "Le 21 mai, une bouée.",
            "name": "EMSO", "t": "2026-05-21T14:39:18Z",
        },
        {"id": "dc:aton", "kind": "aton", "phrase": "Une balise EMSO.", "name": "EMSO"},
    ]
    # Le seul emplacement est dans leg-8 (août) : la bouée de mai n'en a pas.
    plan = _fc2_side_plan_with_slots(leg1_slot=False, leg8_slot=True)
    out = apply_chosen_subjects(plan, ["dc:buoy", "dc:aton"], bag, 0)
    blob = " ".join(c["text"] for c in out["chapters"])
    assert blob.count("Une balise EMSO.") == 1, blob
    assert blob.count("Le 21 mai, une bouée.") == 1, blob
    assert "Le 21 mai, une bouée." in out["chapters"][0]["text"]
    assert "une bouée" not in out["chapters"][1]["text"]


def _rg6_long_chapters(lang: str = "fr") -> list[dict]:
    """Chapitres 3:00 bruts (gabarit RG6, tout au rang 0), comme le stock regelé 768f20e."""
    if lang == "en":
        one = ("On 4 June, Berry-Mappemonde leaves Ajaccio (Corse), heading northwest for the long "
               "crossing to Fort-de-France (Martinique). 5,153 miles, about forty days at sea, at 8 knots "
               "on average. Arrival at Fort-de-France (Martinique) on 14 July, moored at the port of "
               "Fort-de-France (Martinique).")
        hop = ("On 17 July, from island to island, Berry-Mappemonde leaves Fort-de-France (Martinique), "
               "heading west for Pointe-à-Pitre (Guadeloupe). 192 miles, one day at sea, at 8 knots on "
               "average. Arrival at Pointe-à-Pitre (Guadeloupe) on 18 July, moored at Port de Sainte-Rose.")
    else:
        one = ("Le 4 juin, Berry-Mappemonde quitte Ajaccio (Corse), cap au nord-ouest pour la longue "
               "traversée vers Fort-de-France (Martinique). 5 153 milles, une quarantaine de jours de mer, "
               "à 8 nœuds de moyenne. Arrivée à Fort-de-France (Martinique) le 14 juillet, amarré au port "
               "de Fort-de-France (Martinique).")
        hop = ("Le 17 juillet, d'île en île, Berry-Mappemonde quitte Fort-de-France (Martinique), cap à "
               "l'ouest pour Pointe-à-Pitre (Guadeloupe). 192 milles, un jour de mer, à 8 nœuds de "
               "moyenne. Arrivée à Pointe-à-Pitre (Guadeloupe) le 18 juillet, amarré à Port de Sainte-Rose.")
    return [{"id": f"leg-{i}", "text": one if i % 2 else hop} for i in range(1, 13)]


def test_film_180_raw_rank0_template_is_cut_to_char_budget():
    """3:00 brut : 3 448 car. pour 2 700 (stock regelé). On retire les incises, pas les faits."""
    import film_script as fs  # noqa: PLC0415
    from film_script import _film_apply_char_budget, _trim_sentence_rank, script_chars  # noqa: PLC0415

    for lang in ("fr", "en"):
        chapters = _rg6_long_chapters(lang)
        assert all(
            _trim_sentence_rank(s) == 0 for c in chapters for s in fs._sentences(c["text"])
        ), "jeu de test : tout au rang 0"
        assert script_chars(chapters) > film_char_budget(180)
        _film_apply_char_budget(chapters, 180)
        assert script_chars(chapters) <= film_char_budget(180), lang
        blob = " ".join(c["text"] for c in chapters)
        for fact in (("5 153 milles", "5,153 miles"), ("192 milles", "192 miles"),
                     ("le 14 juillet", "on 14 July"), ("Pointe-à-Pitre", "Pointe-à-Pitre")):
            assert fact[1 if lang == "en" else 0] in blob, (lang, fact)
        # Chaque chapitre garde départ, distance et arrivée (aucune phrase retirée).
        assert all(len(fs._sentences(c["text"])) == 3 for c in chapters), lang
        assert "  " not in blob and " ." not in blob and ",." not in blob


def test_film_150_and_integral_char_budget_unchanged_by_180_compaction():
    """Le raccourcissement des incises ne touche ni l'intégral ni un 3:00 déjà sous le plafond."""
    from film_script import _film_apply_char_budget  # noqa: PLC0415

    chapters = _rg6_long_chapters("fr")[:3]
    before = [c["text"] for c in chapters]
    _film_apply_char_budget(chapters, 180)
    assert [c["text"] for c in chapters] == before
    chapters = _rg6_long_chapters("fr")
    before = [c["text"] for c in chapters]
    _film_apply_char_budget(chapters, 0)
    assert [c["text"] for c in chapters] == before


def test_en_guard_tolerates_demonyms_added_by_136():
    """Contre-revue 136-137 P2-8 : « les eaux sri-lankaises » → « Sri Lankan waters » est toléré."""
    import film_script as fs  # noqa: PLC0415

    for en, fr, word in (
        ("the Sri Lankan waters", "les eaux sri-lankaises", "lankan"),
        ("the Omani waters", "les eaux omanaises", "omani"),
        ("the Thai waters", "les eaux thaïlandaises", "thai"),
        ("the Myanmar waters", "les eaux birmanes", "myanmar"),
        ("the Malaysian waters", "les eaux malaisiennes", "malaysian"),
        ("the Palauan waters", "les eaux palaosiennes", "palauan"),
        ("the Gambian waters", "les eaux gambiennes", "gambian"),
    ):
        assert word in fs._en_translation_names(en, fr), en
    # Une seule source : chaque démonyme anglais de la table est connu du garde-fou.
    import toponyms  # noqa: PLC0415

    for row in toponyms.territories():
        for w in re.findall(r"[^\W\d_]+", str(row.get("adj_en") or "")):
            assert w.casefold() in fs._EN_GEO_WORDS, w


def test_reanchor_edited_chapter_relocates_sentences_and_drops_removed_ones():
    import film_script as fs  # noqa: PLC0415

    old = "Departure sentence. Removed sentence. Arrival sentence."
    chapter = {
        "text": "Departure sentence. Arrival sentence.",
        "_anchorText": old,
        "tA": "2026-05-15T08:00:00Z",
        "tB": "2026-05-15T12:00:00Z",
        "anchors": [
            {"charIdx": 4, "t": "2026-05-15T09:00:00Z"},
            {"charIdx": 24, "t": "2026-05-15T10:00:00Z"},
            {"charIdx": 43, "t": "2026-05-15T11:00:00Z"},
        ],
    }
    fs._reanchor_edited_chapter(chapter, "en")
    assert chapter["_anchorText"] == chapter["text"]
    assert all(a["charIdx"] <= len(chapter["text"]) for a in chapter["anchors"])
    # The removed sentence's 10:00 anchor was dropped.
    assert "2026-05-15T10:00:00Z" not in {a["t"] for a in chapter["anchors"]}
    assert chapter["anchors"] == [
        {"charIdx": 0, "t": "2026-05-15T09:00:00Z"},
        {"charIdx": len("Departure sentence. "), "t": "2026-05-15T11:00:00Z"},
    ]


def test_rules_films_keep_anchors_in_text_and_sentence_times_moving():
    import film_script as fs  # noqa: PLC0415

    for lang in ("fr", "en"):
        for seconds in (150, 180):
            plan = build_raw_script(
                CLOCK, CLOCK["marks"], LIVE, JOURNAL,
                lang=lang, seconds=seconds, now_ms=NOW_MS,
            )
            for chapter in plan["chapters"]:
                text = chapter["text"]
                assert all(a["charIdx"] <= len(text) for a in chapter["anchors"]), (lang, seconds, chapter["id"])
                a, b = fs._ms(chapter["tA"]), fs._ms(chapter["tB"])
                if not text or a is None or b is None or b <= a:
                    continue
                anchors = [{"charIdx": 0, "t": a}]
                anchors.extend({"charIdx": p["charIdx"], "t": fs._ms(p["t"])} for p in chapter["anchors"])
                anchors.append({"charIdx": len(text), "t": b})
                starts = fs._sentences(text)
                offsets = []
                cursor = 0
                for sentence in starts:
                    offsets.append(text.find(sentence, cursor))
                    cursor = offsets[-1] + len(sentence)
                mapped = []
                for offset in offsets:
                    left = max((p for p in anchors if p["charIdx"] <= offset), key=lambda p: p["charIdx"])
                    right = min((p for p in anchors if p["charIdx"] >= offset), key=lambda p: p["charIdx"])
                    mapped_t = left["t"] if right["charIdx"] == left["charIdx"] else left["t"] + (right["t"] - left["t"]) * (offset - left["charIdx"]) / (right["charIdx"] - left["charIdx"])
                    mapped.append(round(mapped_t))
                run = 1
                for i in range(1, len(mapped)):
                    run = run + 1 if mapped[i] == mapped[i - 1] else 1
                    assert run < 3, (lang, seconds, chapter["id"], mapped)


def test_public_official_film_plan_strips_private_anchor_text():
    import film_script as fs  # noqa: PLC0415

    raw = build_raw_script(
        CLOCK, CLOCK["marks"], LIVE, JOURNAL,
        lang="en", seconds=150, now_ms=NOW_MS,
    )
    public = fs._public_plan(raw, "rules")
    assert public["chapters"]
    assert all("_anchorText" not in chapter for chapter in public["chapters"])


def test_reanchor_edited_chapter_drops_anchors_for_empty_or_rewritten_text():
    import film_script as fs  # noqa: PLC0415

    base = {
        "_anchorText": "Original sentence.",
        "tA": "2026-05-15T08:00:00Z",
        "tB": "2026-05-15T12:00:00Z",
        "anchors": [{"charIdx": 2, "t": "2026-05-15T09:00:00Z"}],
    }
    empty = {**base, "text": ""}
    fs._reanchor_edited_chapter(empty, "en")
    assert empty["anchors"] == []
    assert empty["_anchorText"] == ""

    rewritten = {**base, "text": "Completely rewritten sentence."}
    fs._reanchor_edited_chapter(rewritten, "en")
    assert rewritten["anchors"] == []
    assert rewritten["_anchorText"] == rewritten["text"]


def test_reanchor_edited_chapter_ignores_malformed_anchor_indices():
    import film_script as fs  # noqa: PLC0415

    chapter = {
        "text": "Original sentence.",
        "_anchorText": "Original sentence.",
        "tA": "2026-05-15T08:00:00Z",
        "tB": "2026-05-15T12:00:00Z",
        "anchors": [{"charIdx": "bad", "t": "2026-05-15T09:00:00Z"}],
    }
    fs._reanchor_edited_chapter(chapter, "en")
    assert chapter["anchors"] == []


def test_reanchor_edited_chapter_drops_anchors_without_source_text():
    import film_script as fs  # noqa: PLC0415

    chapter = {
        "text": "A rewritten chapter.",
        "tA": "2026-05-15T08:00:00Z",
        "tB": "2026-05-15T12:00:00Z",
        "anchors": [{"charIdx": 3, "t": "2026-05-15T09:00:00Z"}],
    }
    fs._reanchor_edited_chapter(chapter, "en")
    assert chapter["anchors"] == []
    assert chapter["_anchorText"] == chapter["text"]


def test_reanchor_edited_chapter_drops_ambiguous_boundary_and_duplicate_anchors():
    import film_script as fs  # noqa: PLC0415

    chapter = {
        "text": "Bay. Approach to harbor.",
        "_anchorText": "Bay. Approach to harbor. Approach to harbor.",
        "tA": "2026-05-15T08:00:00Z",
        "tB": "2026-05-15T12:00:00Z",
        "anchors": [
            {"charIdx": 0, "t": "2026-05-15T09:00:00Z"},
            {"charIdx": 15, "t": "2026-05-15T10:00:00Z"},
            {"charIdx": 34, "t": "2026-05-15T11:00:00Z"},
        ],
    }
    fs._reanchor_edited_chapter(chapter, "en")
    times = {anchor["t"] for anchor in chapter["anchors"]}
    assert "2026-05-15T09:00:00Z" not in times  # +12 would cross into the next sentence.
    assert "2026-05-15T10:00:00Z" not in times
    assert "2026-05-15T11:00:00Z" not in times  # Duplicate occurrence was removed ambiguously.


def test_reanchor_edited_chapter_drops_anchor_when_final_sentence_is_duplicated():
    import film_script as fs  # noqa: PLC0415

    chapter = {
        "text": "Unique sentence.",
        "_anchorText": "Unique sentence.",
        "tA": "2026-05-15T08:00:00Z",
        "tB": "2026-05-15T12:00:00Z",
        "anchors": [{"charIdx": 0, "t": "2026-05-15T09:00:00Z"}],
    }
    chapter["text"] = "Unique sentence. Unique sentence."
    fs._reanchor_edited_chapter(chapter, "en")
    assert chapter["anchors"] == []


def test_reanchor_edited_chapter_drops_reordered_duplicate_sentence_anchors():
    import film_script as fs  # noqa: PLC0415

    original = "Bay. Bay! Approach."
    chapter = {
        "text": original,
        "_anchorText": original,
        "tA": "2026-05-15T08:00:00Z",
        "tB": "2026-05-15T12:00:00Z",
        "anchors": [
            {"charIdx": 0, "t": "2026-05-15T09:00:00Z"},
            {"charIdx": 5, "t": "2026-05-15T10:00:00Z"},
            {"charIdx": 11, "t": "2026-05-15T11:00:00Z"},
        ],
    }
    chapter["text"] = "Bay! Approach. Bay."
    fs._reanchor_edited_chapter(chapter, "en")
    assert chapter["anchors"] == [
        {"charIdx": len("Bay! "), "t": "2026-05-15T11:00:00Z"},
    ]


def test_bubble_payload_uses_localized_event_text_and_never_reuses_french_in_english():
    import film_script as fs  # noqa: PLC0415

    entry = {
        "id": "project-1", "kind": "project", "name": "Aménagement côtier",
        "t": "2026-05-16T08:00:00Z", "fact": "Des navires arrivent au port.",
    }
    ev = {"id": "project-1", "kind": "project", "name": entry["name"], "t": entry["t"], "entry": entry, "bubbleScore": 1}
    previous = {"card": {"text": "Du 11 juin, des navires arrivent."}, "fact": "Du 11 juin, des navires arrivent."}

    en = fs._bubble_payload(ev, {"text": "On 16 May, project Aménagement côtier."}, "en", previous)
    assert en["fact"] == "On 16 May, project Aménagement côtier."
    assert en["card"]["text"] == en["fact"]

    entry["fact_en"] = "Ships arrive at the port."
    en_with_translation = fs._bubble_payload(ev, {"text": "On 16 May, project Aménagement côtier."}, "en")
    assert en_with_translation["card"]["text"] == "Ships arrive at the port."

    fr = fs._bubble_payload(ev, {"text": "Le 16 mai, le projet Aménagement côtier."}, "fr", previous)
    assert fr["card"]["text"] == previous["card"]["text"]


def test_free_moments_require_geographic_evidence_in_known_window():
    from film_script import _align_moments_to_window

    t = "2026-10-15T12:00:00Z"
    window = {
        "fromName": "Papeete", "destName": "Mata-Utu",
        "tA": _ms("2026-10-14T00:00:00Z"), "tB": _ms("2026-10-16T00:00:00Z"),
        "clock": {"vertices": [
            {"iso": t, "lat": -14, "lon": -171, "vehicle": "main"},
            {"iso": "2026-09-01T00:00:00Z", "lat": 14.6, "lon": -61},
            {"iso": t, "lat": 14.6, "lon": -61, "vehicle": "plane"},
        ]},
    }
    samoa = {"t": t, "moment": {"here": {"at": {"lat": -14, "lon": -171}}}}
    martinique = {"t": t, "lat": 14.6, "lon": -61}
    unknown = {"t": t}
    assigned = {**martinique, "moment": {"leg": {"from": "Papeete", "to": "Mata-Utu"}}}
    kept = _align_moments_to_window([samoa, martinique, unknown, assigned], window, None)
    assert samoa in kept
    assert martinique not in kept
    assert unknown not in kept
    assert any((m.get("moment") or {}).get("leg") for m in kept)
    endpoint_window = {"fromLat": -14, "fromLon": 179}
    across = {"t": t, "pos": {"lat": -14, "lon": -179}}
    assert _align_moments_to_window([across, martinique], endpoint_window, None) == [across]
    assert _align_moments_to_window([unknown], {}, None) == [unknown]
