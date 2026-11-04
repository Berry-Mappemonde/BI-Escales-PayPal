"""Récits préparés une fois : estimation sans appel, verrou, reprise, cache."""
import asyncio
import json
from pathlib import Path

import pytest

import ici_warm
import one_shot
import stories_once
import story_cache


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv(one_shot.ENV_DIR, str(tmp_path / "one-shot"))
    monkeypatch.setenv("NAVIGUIDE_LLM_MODE", "on-demand")
    monkeypatch.delenv("NAVIGUIDE_LLM_BACKGROUND", raising=False)
    monkeypatch.delenv("NAVIGUIDE_LLM_DAILY_USD", raising=False)
    monkeypatch.delenv("NAVIGUIDE_LLM_DAILY_TOKENS_JUDGE", raising=False)
    stories_once.set_inventory(None)
    stories_once.set_cascade(None)
    stories_once.reset_inventory_cache()
    yield
    stories_once.set_inventory(None)
    stories_once.set_cascade(None)
    stories_once.reset_inventory_cache()


def _story(name: str, mrgid: int = 1) -> dict:
    stable = f"poe-ahead:{mrgid}:{name}"
    return {
        "type": "poe-ahead",
        "stableKey": stable,
        "name": name,
        "rules": f"Devant {name}.",
        "event": {
            "type": "poe-ahead",
            "event": "poe-ahead",
            "stableKey": stable,
            "name": name,
            "payload": {"poe": {"name": name}, "zee": {"mrgid": mrgid}},
        },
    }


def _two() -> list[dict]:
    return [_story("Bilbao", 1), _story("Ajaccio", 2)]


def _sents(user: str) -> list:
    raw = user or ""
    mark = "sentences="
    idx = raw.find(mark)
    if idx < 0:
        return []
    try:
        data = json.loads(raw[idx + len(mark):])
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _fake(calls: list):
    async def cascade(system, user, **kw):
        calls.append(kw.get("tier"))
        if "judge an already-written" in (system or ""):
            return '{"ok": true, "reason": "ok"}', "nemotron-ultra"
        if "edit an already-written" in (system or ""):
            blob = (user or "").split("text=", 1)[-1]
            return blob, "nemotron-ultra"
        if kw.get("tier") == "fast":
            src = (user or "").split("French text:\n", 1)[-1]
            return src.replace("Devant", "The boat is off"), "nemotron-lightning"
        sents = _sents(user)
        if sents:
            return " ".join(sents), "nemotron-super"
        return "", "rules"

    return cascade


def test_events_are_stable_sorted_and_the_silent_exit_is_not_prepared():
    events = [
        {"kind": "poe", "event": "passed", "name": "Ajaccio", "mrgid": 2},
        {"kind": "zee", "event": "enter", "name": "eaux françaises", "mrgid": 1},
        {"kind": "zee", "event": "enter", "name": "eaux françaises", "mrgid": 1},
        {"kind": "zee", "event": "exit", "name": "eaux françaises", "mrgid": 1},
        {"kind": "amp", "event": "nearby", "name": "Cabrera", "siteId": "AMP1", "nm": 4},
        {"kind": "coast", "event": "passed", "name": "Hors récit"},
    ]
    rows = stories_once.stories_from_events(events)
    keys = [row["stableKey"] for row in rows]
    assert keys == sorted(keys)
    assert keys.count("zee-enter:1") == 1
    assert "zee-exit:high-seas" in keys
    assert all(not key.startswith("coast") for key in keys)
    kept = stories_once._with_rules(rows)
    assert [row["stableKey"] for row in kept] == sorted(row["stableKey"] for row in kept)
    assert all(row["stableKey"] != "zee-exit:high-seas" for row in kept)
    assert {row["type"] for row in kept} >= {"poe-ahead", "amp-ahead"}


def test_estimate_counts_the_chain_and_does_not_call(monkeypatch):
    def connect(self, address):
        raise AssertionError("réseau")

    monkeypatch.setattr("socket.socket.connect", connect)
    calls: list = []

    async def boom(*_a, **_k):
        calls.append("appel")
        raise AssertionError("appel")

    stories_once.set_cascade(boom)
    stories_once.set_inventory(_two())
    est = one_shot.build_estimate(stories_once.JOB)
    assert calls == []
    assert est["calls"] == 8
    assert est["calls"] != stories_once.BATCH_FIGURE
    assert [item["tier"] for item in est["items"]] == ["write", "judge", "judge", "write"] * 2
    extra = stories_once.estimate_extra()
    assert "stories: 2" in extra
    assert "batch_figure: 177" in extra
    assert "batch_figure_differs: yes" in extra
    assert "langs: fr en" in extra
    code = one_shot.main(["--job", stories_once.JOB, "--estimate"])
    assert code == 0
    assert calls == []


def test_cached_story_makes_no_call_and_a_second_run_is_refused():
    stories_once.set_inventory(_two())
    rows = stories_once.inventory()
    doc = stories_once._blank(stories_once.route_stamp(rows))
    for story in rows:
        row = stories_once._row(doc, story["stableKey"])
        stories_once._put_slot(row, "fr", story["rules"], "nemotron-super")
        stories_once._put_slot(row, "en", "Off " + story["name"] + ".", "nemotron-lightning")
    stories_once._save(doc)
    calls: list = []

    async def boom(*_a, **_k):
        calls.append("appel")
        raise AssertionError("appel")

    stories_once.set_cascade(boom)
    est = one_shot.build_estimate(stories_once.JOB)
    result = one_shot.run(stories_once.JOB, est["fingerprint"])
    assert calls == []
    assert len(result["completed"]) == 8
    with pytest.raises(one_shot.Refused) as refused:
        one_shot.run(stories_once.JOB, est["fingerprint"])
    assert refused.value.code == "locked"
    assert calls == []


def test_run_stops_at_the_cap_and_resumes_without_repaying(monkeypatch):
    from film_script import film_ultra_open

    # Porte Ultra du film ouverte par défaut (écart n° 44) : le job stories_once
    # garde ses propres freins (plafond, reprise sans repayer), indépendants d'elle.
    assert film_ultra_open() is True
    stories_once.set_inventory(_two())
    calls: list = []
    stories_once.set_cascade(_fake(calls))
    est = one_shot.build_estimate(stories_once.JOB)
    state = {"n": 0, "block": True}

    def allow(_tier):
        if not state["block"]:
            return True
        state["n"] += 1
        return state["n"] <= 2

    monkeypatch.setattr("llm_budget.allow", allow)
    with pytest.raises(one_shot.StoppedAtCap) as stopped:
        one_shot.run(stories_once.JOB, est["fingerprint"])
    assert len(stopped.value.completed) == 2
    assert calls == ["write", "judge"]
    state["block"] = False
    result = one_shot.run(stories_once.JOB, est["fingerprint"])
    assert result["completed"][0:2] == stopped.value.completed
    assert calls == ["write", "judge", "judge", "write", "judge", "judge"] * 2
    assert len(result["completed"]) == 8


def test_service_serves_the_prepared_text_or_the_on_demand_path():
    story = _story("Bilbao", 4)
    stories_once.set_inventory([story])
    doc = stories_once._blank(stories_once.route_stamp())
    row = stories_once._row(doc, story["stableKey"])
    stories_once._put_slot(row, "fr", "Devant Bilbao.", "nemotron-super")
    stories_once._put_slot(row, "en", "Off Bilbao.", "nemotron-lightning", reviewedBy="nemotron-ultra")
    stories_once._save(doc)
    body = dict(story["event"])
    body["lang"] = "fr"
    called: list = []

    async def writer(payload, client=None):
        called.append(payload.get("stableKey"))
        return {"status": "ready", "text": "Sur demande.", "source": "rules", "engine": "rules"}

    ready = asyncio.run(story_cache.story_through_cache(body, writer=writer))
    assert called == []
    assert ready["text"] == "Devant Bilbao."
    assert ready["cached"] is True
    en = asyncio.run(story_cache.story_through_cache({**body, "lang": "en"}, writer=writer))
    assert en["text"] == "Off Bilbao."
    assert called == []
    other = {**body, "stableKey": "poe-ahead:9:Marseille", "name": "Marseille"}
    missed = asyncio.run(story_cache.story_through_cache(other, writer=writer))
    assert called == ["poe-ahead:9:Marseille"]
    assert missed["text"] == "Sur demande."


def test_direct_english_write_does_not_copy_french_ultra_receipt(monkeypatch):
    import film_script

    story = _story("Bilbao", 4)
    row = {}
    stories_once._put_slot(row, "fr", "Le bateau quitte Bilbao.", "nemotron-super", reviewedBy="nemotron-ultra")

    async def direct_write(_plan, **_kwargs):
        return None, {"chapters": [{"text": "The boat leaves Bilbao."}], "source": "nemotron-super"}, {}

    monkeypatch.setattr(film_script, "write_film_chain", direct_write)
    monkeypatch.setattr(stories_once, "_run", lambda awaitable: asyncio.run(awaitable))
    monkeypatch.setattr(stories_once, "_cascade", lambda: object())
    stories_once._translate(story, row)
    assert row["en"]["text"] == "The boat leaves Bilbao."
    assert "reviewedBy" not in row["en"]


def test_warm_never_starts_the_job():
    text = Path(ici_warm.__file__).read_text(encoding="utf-8")
    assert "stories_177" not in text
    assert "stories_once" not in text
    assert ici_warm.stories_enabled() is False
