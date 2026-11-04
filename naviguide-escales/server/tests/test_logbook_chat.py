"""Chatbot journal de bord : faits serveur, cascade, filtre des chiffres, consignation."""
import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

import admin_guard
import forecast_cube
import ici_engine
import logbook_chat
import saildocs
import story_cascade
import voyage_api
import voyage_journal as journal
import voyage_store
from tests.test_ici_engine import _handler
from tests.test_voyage_journal import PUBLIC, T0, _official
from voyage_clock import OFFICIAL_VOYAGE_ID

ADMIN = {"X-Naviguide-Admin": "s3cret", "X-Real-IP": "203.0.113.9", "X-Forwarded-For": "203.0.113.9"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NAVIGUIDE_FORECAST_BACKEND", "synthetic")
    monkeypatch.setenv("NAVIGUIDE_FORECAST_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("NAVIGUIDE_GRIB_DIR", str(tmp_path / "grib"))
    monkeypatch.setenv("NAVIGUIDE_GRIB_AUTO", "0")
    monkeypatch.setenv(admin_guard.ADMIN_ENV, "s3cret")
    forecast_cube.CACHE_DIR = tmp_path / "cache"
    saildocs.GRIB_DIR = tmp_path / "grib"
    journal.reset()
    admin_guard.reset_limiters()
    ici_engine.reset_caches()
    from main import app
    return TestClient(app)


def _llm_transport(answer: str):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "tokenfactory" in url or "integrate.api.nvidia.com" in url or "openrouter.ai" in url or "api.anthropic.com" in url:
            return httpx.Response(200, json={"choices": [{"message": {"content": answer}}]})
        return _handler(request)
    return httpx.MockTransport(handler)


KEYWORD_CASES = [
    ("Quel vent au bateau ?", "fact", "wind"),
    ("What wind at the boat?", "fact", "wind"),
    ("Quelle vitesse polaire par 15 nœuds ?", "fact", "polar"),
    ("Polar speed in 15 knots?", "fact", "polar"),
    ("Arrivée prévue à Madère ?", "fact", "eta"),
    ("Expected arrival in Madeira?", "fact", "eta"),
    ("Quel réglage de confort ?", "fact", "setting"),
    ("What comfort setting?", "fact", "setting"),
    ("Climatologie de septembre ici ?", "fact", "climo"),
    ("September climatology here?", "fact", "climo"),
    ("Faut-il partir demain ou attendre ?", "reason", None),
    ("Should we leave tomorrow or wait?", "reason", None),
]


def test_keyword_intent_twelve_fr_en_questions():
    for question, intent, quantity in KEYWORD_CASES:
        parsed = logbook_chat.keyword_intent(question)
        assert parsed["intent"] == intent, question
        if quantity:
            assert parsed["quantity"] == quantity, question
        if "madère" in question.lower() or "madeira" in question.lower():
            assert parsed.get("place")
        if "septembre" in question.lower() or "september" in question.lower():
            assert parsed.get("when") in {"9", "septembre", "September"}


def test_answer_fact_uses_rules_zero_write(monkeypatch):
    seen = []

    async def fake_cascade(system, user, client=None, **kw):
        seen.append(kw.get("tier"))
        return '{"intent":"fact","quantity":"wind","place":null,"when":null,"layer":null}', "nemotron-lightning"

    async def fake_ctx(*_a, **_k):
        return {"official": {"wind": {"windKnots": 14.2, "dirFromDeg": 250}}}

    monkeypatch.setattr(logbook_chat, "cascade_text", fake_cascade)
    monkeypatch.setattr(logbook_chat, "build_context", fake_ctx)
    out = asyncio.run(logbook_chat.answer_question("Quel vent ?", "fr", {}, datetime.now(timezone.utc)))
    assert "write" not in seen
    assert "judge" not in seen
    assert out["source"] == "rules"
    assert "14.2" in out["answer"]
    assert "250" in out["answer"]


def test_strip_raw_fields_drops_at_quay_leak():
    assert "atQuay" not in logbook_chat.strip_raw_fields("The boat is still (atQuay: true) at 0 kn.")
    assert logbook_chat.strip_raw_fields("The boat is still (atQuay: true) at 0 kn.") == "The boat is still at 0 kn."
    assert "atQuay" not in logbook_chat.strip_raw_fields("already underway (atQuay false, speed 0.5 knots).")


def test_strip_raw_fields_drops_formalities_zee_amp_line():
    raw = "Papeete is a port of entry. formalities: zee (zone), amp (protected)."
    out = logbook_chat.strip_raw_fields(raw)
    assert "formalities" not in out.lower()
    assert "zee" not in out.lower()
    assert "amp" not in out.lower()
    assert "Papeete is a port of entry." in out


def test_json_excuse_falls_back_to_missing_info(monkeypatch):
    async def fake_cascade(system, user, client=None, **kw):
        return "The JSON does not contain any information about Cape Horn.", "nemotron-ultra"

    async def fake_ctx(*_a, **_k):
        return {"journal": [{"kind": "zee", "name": "French EEZ"}]}

    monkeypatch.setattr(logbook_chat, "cascade_text", fake_cascade)
    monkeypatch.setattr(logbook_chat, "build_context", fake_ctx)
    out = asyncio.run(logbook_chat.answer_question(
        "Why Panama instead of Cape Horn?", "en", {}, datetime.now(timezone.utc),
    ))
    assert out["source"] == "rules"
    assert "JSON" not in (out["answer"] or "")
    assert out["answer"] == logbook_chat.missing_info("en")


def test_prompt_never_teaches_json_excuse():
    system, user = logbook_chat._prompt("Why Panama?", {"journal": []}, "en")
    assert "If the JSON does not" not in system
    assert "JSON does not" not in system
    assert "Never mention JSON" in system
    assert "Facts :" in user
    assert "JSON :" not in user


def test_stop_in_question_picks_named_official_mark():
    clock = {
        "marks": [
            {"name": "Mata-Utu (Wallis-et-Futuna)", "lat": -13.28, "lon": -176.17},
            {"name": "Papeete (Polynésie française)", "lat": -17.54, "lon": -149.57},
        ],
    }
    hit = logbook_chat.stop_in_question("Which AMP near Papeete?", clock)
    assert hit["name"].startswith("Papeete")
    lat, lon, basis = logbook_chat._around_point("Which AMP near Papeete?", clock, -13.28, -176.17)
    assert basis == "stop"
    assert lat == pytest.approx(-17.54)
    assert lon == pytest.approx(-149.57)


def test_answer_strips_raw_json_field_names(monkeypatch):
    async def fake_cascade(system, user, client=None, **kw):
        return "The boat is still (atQuay: true) at 0 kn.", "nemotron-ultra"

    async def fake_ctx(*_a, **_k):
        return {"official": {"speedKnots": 0, "atQuay": True}}

    monkeypatch.setattr(logbook_chat, "cascade_text", fake_cascade)
    monkeypatch.setattr(logbook_chat, "build_context", fake_ctx)
    out = asyncio.run(logbook_chat.answer_question(
        "Why is the boat slowing down?", "en", {}, datetime.now(timezone.utc), reason=True,
    ))
    assert "atQuay" not in (out["answer"] or "")
    assert "(atQuay" not in (out["answer"] or "")


def test_answer_leaked_prompt_falls_back_honestly(monkeypatch):
    """Une réponse-prompt du modèle (ou du cache) → phrase honnête, jamais le prompt."""

    async def fake_cascade(system, user, client=None, **kw):
        return (
            "Input: A large JSON object\n- Task: What's for the boat\n"
            "You are the logbook of the Berry-Mappemonde sailing expedition.",
            "nemotron-super",
        )

    async def fake_ctx(*_a, **_k):
        return {"official": {"speedKnots": 7.4}}

    monkeypatch.setattr(logbook_chat, "cascade_text", fake_cascade)
    monkeypatch.setattr(logbook_chat, "build_context", fake_ctx)
    out = asyncio.run(logbook_chat.answer_question(
        "À quelle vitesse va le bateau ?", "fr", {}, datetime.now(timezone.utc),
    ))
    assert out["status"] == "ready"
    assert out["source"] == "rules"
    assert "Input:" not in out["answer"]
    assert "Task:" not in out["answer"]
    assert "JSON" not in out["answer"]
    assert "7.4" in out["answer"]


def test_hard_question_without_judge_stays_on_rules(monkeypatch):
    seen = []

    async def fake_cascade(system, user, client=None, **kw):
        seen.append(kw.get("tier"))
        return '{"intent":"reason","quantity":"speed","place":null,"when":null,"layer":null}', "nemotron-lightning"

    async def fake_ctx(*_a, **_k):
        return {"official": {"atQuay": True, "speedKnots": 0}}

    monkeypatch.setattr(logbook_chat, "cascade_text", fake_cascade)
    monkeypatch.setattr(logbook_chat, "build_context", fake_ctx)
    import llm_budget
    monkeypatch.setattr(llm_budget, "allow", lambda tier: tier == "fast")
    out = asyncio.run(logbook_chat.answer_question(
        "Pourquoi ralentir ?", "fr", {}, datetime.now(timezone.utc),
    ))
    assert "judge" not in seen
    assert "write" not in seen
    assert out["source"] == "rules"
    assert "raisonnement" not in out["answer"].lower()
    assert "quai" in out["answer"]


def test_hard_question_with_judge_calls_ultra_once(monkeypatch):
    seen = []

    async def fake_cascade(system, user, client=None, **kw):
        seen.append(kw.get("tier"))
        if kw.get("tier") == "nano":
            return '{"intent":"reason","quantity":"speed","place":null,"when":null,"layer":null}', "nemotron-nano"
        return "Stay at the quay: speed is 0 kn.", "nemotron-ultra"

    async def fake_ctx(*_a, **_k):
        return {"official": {"atQuay": True, "speedKnots": 0}}

    monkeypatch.setattr(logbook_chat, "cascade_text", fake_cascade)
    monkeypatch.setattr(logbook_chat, "build_context", fake_ctx)
    import llm_budget
    monkeypatch.setattr(llm_budget, "allow", lambda tier: True)
    out = asyncio.run(logbook_chat.answer_question(
        "Pourquoi ralentir ?", "fr", {}, datetime.now(timezone.utc),
    ))
    assert seen.count("judge") == 1
    assert "write" not in seen
    assert out["source"] == "nemotron-ultra"
    assert "0" in out["answer"]


@pytest.mark.parametrize(
    ("cascade_source", "judge_allowed", "answer", "expected_records"),
    [
        ("nemotron-ultra", True, "Stay at the quay: speed is 0 kn.", 1),
        ("nemotron-super", True, "Stay at the quay: speed is 0 kn.", 0),
        ("rules", True, "Stay at the quay: speed is 0 kn.", 0),
        ("nemotron-ultra", False, "Stay at the quay: speed is 0 kn.", 0),
        ("nemotron-ultra", True, "The JSON does not contain any information.", 0),
    ],
)
def test_chat_ultra_counter_tracks_only_actual_ultra_responses(
    monkeypatch, cascade_source, judge_allowed, answer, expected_records,
):
    recorded = []

    async def fake_cascade(system, user, client=None, **kw):
        return answer, cascade_source

    async def fake_ctx(*_a, **_k):
        return {"official": {"atQuay": True, "speedKnots": 0}}

    monkeypatch.setattr(logbook_chat, "cascade_text", fake_cascade)
    monkeypatch.setattr(logbook_chat, "build_context", fake_ctx)
    import llm_budget
    monkeypatch.setattr(llm_budget, "allow", lambda tier: judge_allowed)
    monkeypatch.setattr(llm_budget, "record_chat_ultra", lambda: recorded.append(True))

    out = asyncio.run(logbook_chat.answer_question(
        "Pourquoi ralentir ?", "fr", {}, datetime.now(timezone.utc),
    ))

    assert out["status"] == "ready"
    assert len(recorded) == expected_records


def test_filter_numbers_drops_sentences_with_figures_absent_from_the_facts():
    ctx = {"official": {"wind": {"windKnots": 14.2, "dirFromDeg": 250}}, "nextStop": {"name": "Ajaccio", "eta": "2026-10-03T10:00:00Z"}}
    text, dropped = logbook_chat.filter_numbers(
        "Le vent est de 14,2 kn de 250°. Il fera 30 kn demain. Arrivée à Ajaccio le 3 octobre.", ctx,
    )
    assert "14,2" in text and "Ajaccio" in text
    assert "30 kn" not in text and dropped == 1


def test_summary_is_question_then_first_sentence():
    assert logbook_chat.summarize("Quel vent ?", "Vent 14 kn de OSO. Pression 1013 hPa.") == "Quel vent ? → Vent 14 kn de OSO."


def test_chat_answers_from_server_facts_and_logs_only_for_admin(client, monkeypatch):
    now = T0 + timedelta(days=3)
    monkeypatch.setattr(voyage_api, "_now", lambda: now)
    import llm_budget
    monkeypatch.setattr(llm_budget, "allow", lambda *_a, **_k: True)
    client.put("/voyage/official", json=_official(), headers=ADMIN)
    monkeypatch.setattr(story_cascade, "nebius_key", lambda: "test")
    monkeypatch.setattr(story_cascade, "nvidia_key", lambda: "test")
    transport = _llm_transport("Le bateau est en mer, dans French Exclusive Economic Zone. Le vent au bateau est de 99 kn. Prochaine escale Fort-de-France (Martinique).")
    real = logbook_chat.answer_question

    async def patched(question, lang, client_ctx, when, http=None, reason=False):
        async with httpx.AsyncClient(transport=transport) as c:
            return await real(question, lang, client_ctx, when, c, reason=reason)

    monkeypatch.setattr(logbook_chat, "answer_question", patched)

    # Public: an answer, not logged. Facts come from rules, never Super/Lightning prose.
    r = client.post("/logbook/chat", json={"question": "Où est le bateau ?", "lang": "fr", "context": {"view": "suivre"}}, headers=PUBLIC)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ready" and body["logged"] is False
    assert "99 kn" not in body["answer"], "a figure absent from the facts is dropped"
    assert body["source"] == "rules"
    assert body["engine"] == "rules"
    assert body["facts"]["official"]["basis"] == "clock"
    assert journal.latest(10, kinds=("chat",)) == []

    # Admin: the exchange is logged with its summary.
    r2 = client.post("/logbook/chat", json={"question": "Où est le bateau ?", "lang": "fr"}, headers=ADMIN)
    assert r2.json()["logged"] is True
    chats = journal.latest(10, kinds=("chat",))
    assert len(chats) == 1
    assert chats[0]["question"] == "Où est le bateau ?" and chats[0]["summary"].startswith("Où est le bateau ? →")
    assert chats[0]["basis"] == "human+llm"
    # The journal summary lists chats among the events; kinds advertise it.
    body = client.get("/voyage/official/journal?limit=5", headers=PUBLIC).json()
    assert "chat" in body["kinds"] and any(e["kind"] == "chat" for e in body["events"])
    # Guards.
    assert client.post("/logbook/chat", json={"question": "   "}, headers=PUBLIC).status_code == 400
    assert client.post("/logbook/chat", json={"question": "x" * 600}, headers=PUBLIC).status_code == 413


def test_build_context_at_quay_speed_zero(monkeypatch):
    now = datetime(2026, 9, 18, 12, tzinfo=timezone.utc)
    journal.reset()
    monkeypatch.setattr(
        voyage_store,
        "load_voyage",
        lambda *_a, **_k: {
            "clock": {
                "t0": T0.isoformat().replace("+00:00", "Z"),
                "vertices": [{"tHours": 0, "lat": -22.276, "lon": 166.458}],
                "marks": [],
            }
        },
    )

    def _sample(_clock, _when):
        return {
            "lat": -22.276,
            "lon": 166.458,
            "sailNm": 19055,
            "speedKnots": 0,
            "plannedKnots": 11.9,
            "atQuay": True,
            "status": "live",
            "vehicle": "quay",
            "regime": "hindcast",
        }

    monkeypatch.setattr("voyage_clock.sample_clock_at_time", _sample)

    ctx = asyncio.run(logbook_chat.build_context(
        {"view": "suivre", "boat": {"lat": -22.276, "lon": 166.458, "speedKnots": 7.2}},
        now,
    ))
    assert ctx["official"]["speedKnots"] == 0
    assert ctx["official"]["atQuay"] is True
    assert ctx["official"]["plannedKnots"] == 11.9
    assert ctx["official"]["basis"] == "clock"
    assert ctx["official"]["regime"] == "hindcast"
    assert ctx["boat"]["speedKnots"] == 0
    assert ctx["boat"]["regime"] == "hindcast"


def test_build_context_follow_uses_clock_speed(monkeypatch):
    now = datetime(2026, 7, 1, 12, tzinfo=timezone.utc)
    journal.reset()
    monkeypatch.setattr(
        voyage_store,
        "load_voyage",
        lambda *_a, **_k: {
            "clock": {
                "t0": T0.isoformat().replace("+00:00", "Z"),
                "vertices": [{"tHours": 0, "lat": 20.0, "lon": -40.0}],
                "marks": [],
            }
        },
    )

    def _sample(_clock, _when):
        return {
            "lat": 20.0,
            "lon": -40.0,
            "sailNm": 4000,
            "speedKnots": 11.9,
            "atQuay": False,
            "status": "live",
            "vehicle": "main",
            "regime": "hindcast",
            "kind": "hindcast",
        }

    monkeypatch.setattr("voyage_clock.sample_clock_at_time", _sample)

    ctx = asyncio.run(logbook_chat.build_context(
        {"view": "suivre", "boat": {"lat": 20.0, "lon": -40.0, "speedKnots": 7.4}},
        now,
    ))
    assert ctx["official"]["speedKnots"] == 11.9
    assert ctx["official"]["plannedKnots"] == 11.9
    assert ctx["official"]["basis"] == "clock"
    assert ctx["official"]["regime"] == "hindcast"
    assert ctx["official"]["atQuay"] is False
    assert ctx["boat"]["speedKnots"] == 11.9
    assert ctx["boat"]["regime"] == "hindcast"


def test_chat_without_llm_backend_answers_from_facts(client, monkeypatch):
    now = T0 + timedelta(days=3)
    monkeypatch.setattr(voyage_api, "_now", lambda: now)
    client.put("/voyage/official", json=_official(), headers=ADMIN)
    monkeypatch.setattr(story_cascade, "nebius_key", lambda: "")
    monkeypatch.setattr(story_cascade, "nvidia_key", lambda: "")
    monkeypatch.setattr(story_cascade, "openrouter_key", lambda: "")
    monkeypatch.setattr(story_cascade, "anthropic_key", lambda: "")
    r = client.post("/logbook/chat", json={"question": "Quel vent ?"}, headers=ADMIN)
    body = r.json()
    assert body["status"] == "ready"
    assert body["source"] in {"rules", "budget"}
    assert body["answer"]
    assert "aucun modèle" not in body["answer"]
    assert body["logged"] is True
    chats = journal.latest(10, kinds=("chat",))
    assert len(chats) == 1


def test_rules_answer_wind_from_context_fr_en():
    ctx = {"official": {"wind": {"windKnots": 14.2, "dirFromDeg": 250}}}
    fr = logbook_chat.rules_answer("Quel vent au bateau ?", ctx, "fr")
    assert "14.2" in fr and "250" in fr and "kn" in fr
    en = logbook_chat.rules_answer("What wind at the boat?", ctx, "en")
    assert "14.2" in en and "250" in en and "kn" in en
    kept, dropped = logbook_chat.filter_numbers(fr, ctx)
    assert dropped == 0 and "14.2" in kept


def test_rules_answer_speed_at_quay_and_next_stop():
    ctx = {
        "boat": {"speedKnots": 0, "atQuay": True},
        "nextStop": {"name": "Ajaccio", "eta": "2026-10-03T10:00:00Z"},
    }
    speed = logbook_chat.rules_answer("À quelle vitesse va le bateau ?", ctx, "fr")
    assert "à quai" in speed
    assert "14" not in speed
    stop = logbook_chat.rules_answer("Quelle est la prochaine escale ?", ctx, "fr")
    assert "Ajaccio" in stop


def test_rules_answer_unknown_question_stays_honest():
    ctx = {"official": {"wind": {"windKnots": 14.2, "dirFromDeg": 250}}}
    text = logbook_chat.rules_answer("Quel est le prix du gasoil ?", ctx, "fr")
    assert "pas cette information" in text
    assert "14.2" not in text
    assert "250" not in text


def test_answer_cascade_down_cites_exact_wind_from_context(monkeypatch):
    async def boom(*_a, **_k):
        raise RuntimeError("no backend")

    async def fake_ctx(*_a, **_k):
        return {"official": {"wind": {"windKnots": 14.2, "dirFromDeg": 250}}}

    monkeypatch.setattr(logbook_chat, "cascade_text", boom)
    monkeypatch.setattr(logbook_chat, "build_context", fake_ctx)
    out = asyncio.run(logbook_chat.answer_question(
        "Quel vent au bateau ?", "fr", {}, datetime.now(timezone.utc),
    ))
    assert out["status"] == "ready"
    assert out["source"] == "rules"
    assert "14.2" in out["answer"]
    assert "250" in out["answer"]
    assert out["answer"] is not None


def test_answer_cascade_down_unknown_question_is_honest(monkeypatch):
    async def boom(*_a, **_k):
        raise RuntimeError("no backend")

    async def fake_ctx(*_a, **_k):
        return {"official": {"wind": {"windKnots": 14.2, "dirFromDeg": 250}}}

    monkeypatch.setattr(logbook_chat, "cascade_text", boom)
    monkeypatch.setattr(logbook_chat, "build_context", fake_ctx)
    out = asyncio.run(logbook_chat.answer_question(
        "Quel est le prix du gasoil ?", "fr", {}, datetime.now(timezone.utc),
    ))
    assert out["status"] == "ready"
    assert out["source"] == "rules"
    assert "pas cette information" in out["answer"]
    assert "14.2" not in out["answer"]


def test_answer_failed_only_when_rules_fallback_impossible(monkeypatch):
    async def boom_cascade(*_a, **_k):
        raise RuntimeError("no backend")

    async def fake_ctx(*_a, **_k):
        return {"official": {"wind": {"windKnots": 12}}}

    def boom_rules(*_a, **_k):
        raise RuntimeError("unreadable")

    monkeypatch.setattr(logbook_chat, "cascade_text", boom_cascade)
    monkeypatch.setattr(logbook_chat, "build_context", fake_ctx)
    monkeypatch.setattr(logbook_chat, "rules_answer", boom_rules)
    out = asyncio.run(logbook_chat.answer_question(
        "Quel vent au bateau ?", "fr", {}, datetime.now(timezone.utc),
    ))
    assert out["status"] == "failed"
    assert out["answer"] is None
    assert out["source"] is None


WX_GALE = {
    "kind": "wx",
    "t": "2026-05-21T06:00:00Z",
    "event": "gale",
    "windKnots": 36.5,
    "maxWindKnots": 36.5,
    "dirFromDeg": 250,
    "hs": 2.0,
    "model": "GFS",
}


def test_wx_keyword_hits_cites_gale_above_threshold():
    hits = logbook_chat.wx_keyword_hits(
        "avons-nous déjà eu plus de 35 nœuds ?",
        [WX_GALE, {"kind": "wx", "event": "sea", "hs": 4.1, "windKnots": 20, "t": "2026-05-20T06:00:00Z"}],
    )
    assert len(hits) == 1
    assert hits[0]["windKnots"] == 36.5
    assert hits[0]["t"] == "2026-05-21T06:00:00Z"
    assert logbook_chat.wx_keyword_hits("avons-nous déjà eu plus de 35 nœuds ?", []) == []


def test_embeddings_skipped_when_keywords_hit(monkeypatch):
    called = []

    async def boom(*_a, **_k):
        called.append(1)
        return []

    monkeypatch.setattr(logbook_chat, "wx_embed_hits", boom)
    monkeypatch.setenv("NAVIGUIDE_EMBEDDINGS", "1")
    out = asyncio.run(logbook_chat.similar_wx("avons-nous déjà eu plus de 35 nœuds ?", [WX_GALE]))
    assert out and out[0]["windKnots"] == 36.5
    assert called == []


def test_embeddings_only_when_flag_and_no_keyword(monkeypatch):
    called = []

    async def fake_emb(question, entries, client=None):
        called.append(question)
        return [logbook_chat._slim_wx(WX_GALE)]

    monkeypatch.setattr(logbook_chat, "wx_embed_hits", fake_emb)
    monkeypatch.setenv("NAVIGUIDE_EMBEDDINGS", "1")
    q = "a-t-on déjà eu un temps pareil ?"
    out = asyncio.run(logbook_chat.similar_wx(q, [WX_GALE]))
    assert called == [q] and out[0]["windKnots"] == 36.5

    called.clear()
    monkeypatch.delenv("NAVIGUIDE_EMBEDDINGS", raising=False)
    assert logbook_chat.embeddings_enabled() is False
    out2 = asyncio.run(logbook_chat.similar_wx(q, [WX_GALE]))
    assert called == [] and out2 == []


def test_answer_cites_wx_memory_without_invented_figure(monkeypatch):
    async def fake_cascade(system, user, client=None, **kw):
        return '{"intent":"fact","quantity":"wind","place":null,"when":null,"layer":null}', "nemotron-lightning"

    async def fake_ctx(*_a, **_k):
        return {"official": {"speedKnots": 0}, "journal": []}

    monkeypatch.setattr(logbook_chat, "cascade_text", fake_cascade)
    monkeypatch.setattr(logbook_chat, "build_context", fake_ctx)
    monkeypatch.setattr(journal, "latest", lambda *_a, **_k: [WX_GALE])
    out = asyncio.run(logbook_chat.answer_question(
        "avons-nous déjà eu plus de 35 nœuds ?", "fr", {}, datetime.now(timezone.utc),
    ))
    assert out["source"] == "rules"
    assert "36,5" in out["answer"] or "36.5" in out["answer"]
    assert "99" not in out["answer"]
    assert out["context"]["memory"][0]["windKnots"] == 36.5


FACT_PACK = {
    "official": {"wind": {"windKnots": 14.2, "dirFromDeg": 250}, "lat": 32.7, "lon": -17.0, "speedKnots": 7.4},
    "boat": {"lat": 32.7, "lon": -17.0, "speedKnots": 7.4},
    "nextStop": {"name": "Madère", "eta": "2026-09-20T10:00:00Z"},
    "polar": {
        "unit": "kn", "source": "polar",
        "speedAtTws": {"10": 6.2, "15": 8.1, "20": 9.0, "25": 9.4},
        "vmgUpwind": {"twsKn": 15, "twaDeg": 42, "speedKn": 8.1, "vmgKn": 6.2},
    },
    "orders": {
        "source": "skipper", "profile": "cruise", "comfort": "normal",
        "knobs": {"horizonH": 36, "comfort": "normal"},
        "values": {"hsAlertM": 3.5, "planningKn": 7, "galeKt": 34},
    },
    "plan": {
        "source": "plan_review", "status": "ready", "n": 1, "unit": "ISO-8601",
        "legs": [{
            "from": "La Rochelle", "to": "Madère",
            "arriveIso": "2026-09-20T10:00:00Z",
            "p10": "2026-09-19T00:00:00Z", "p90": "2026-09-21T00:00:00Z",
            "flags": [{"kind": "formalities", "names": ["Portugal"]}],
        }],
    },
    "climo": {
        "unit": "kn", "hsUnit": "m", "month": 9, "source": "atlas", "status": "ready",
        "windMeanKn": 12.0, "dirFromDeg": 40, "gustKn": 18.0, "hsM": 1.4,
    },
    "layers": {"unit": "m", "source": "ici", "bathyM": 42.0, "cables": {"nearby": False}},
    "dcFamilies": [
        {"kind": "amp", "name": "Pertuis Charentais", "nm": 3.6},
        {"kind": "cable", "name": "Honotua"},
        {"kind": "depth", "depthM": 42.0},
    ],
    "around": {"zee": {"name": "Portuguese Exclusive Economic Zone"}, "depthM": 42.0, "projects": []},
    "journal": [],
}


def test_fact_pack_sections_present_and_bounded():
    ctx = logbook_chat.bound_facts(dict(FACT_PACK))
    for key in ("polar", "orders", "plan", "climo", "layers"):
        assert key in ctx and isinstance(ctx[key], dict)
    assert ctx["polar"]["speedAtTws"]["15"] == 8.1
    assert ctx["orders"]["comfort"] == "normal"
    assert ctx["plan"]["legs"][0]["to"] == "Madère"
    assert ctx["climo"]["month"] == 9
    assert any(r.get("kind") == "cable" and r.get("name") == "Honotua" for r in ctx["dcFamilies"])
    assert any(r.get("kind") == "amp" and r.get("nm") == 3.6 for r in ctx["dcFamilies"])
    assert logbook_chat.estimate_tokens(ctx) <= logbook_chat.FACT_TOKEN_CAP
    fat = dict(FACT_PACK)
    fat["journal"] = [{"kind": "note", "text": "x" * 80, "n": i} for i in range(200)]
    bounded = logbook_chat.bound_facts(fat)
    assert logbook_chat.estimate_tokens(bounded) <= logbook_chat.FACT_TOKEN_CAP
    assert bounded["polar"]["speedAtTws"]["15"] == 8.1
    assert any(r.get("nm") == 3.6 for r in bounded["dcFamilies"])


def test_rules_answer_copies_pack_numbers():
    polar = logbook_chat.rules_answer("Quelle vitesse polaire par 15 nœuds ?", FACT_PACK, "fr")
    assert "8.1" in polar and "15" in polar
    kept, dropped = logbook_chat.filter_numbers(polar, FACT_PACK)
    assert dropped == 0 and "8.1" in kept
    eta = logbook_chat.rules_answer("Arrivée prévue à Madère ?", FACT_PACK, "fr")
    assert "Madère" in eta
    assert "2026-09-20" in eta
    comfort = logbook_chat.rules_answer("Quel réglage de confort ?", FACT_PACK, "fr")
    assert "normal" in comfort
    climo = logbook_chat.rules_answer("Climatologie de septembre ici ?", FACT_PACK, "fr")
    assert "12" in climo and "9" in climo


OFFICIAL_12_PAIRS = [
    ("Saint-Maur (Berry, Indre)", "La Rochelle"),
    ("La Rochelle", "Ajaccio (Corse)"),
    ("Ajaccio (Corse)", "Fort-de-France (Martinique)"),
    ("Fort-de-France (Martinique)", "Pointe-à-Pitre (Guadeloupe)"),
    ("Pointe-à-Pitre (Guadeloupe)", "Gustavia (Saint-Barthélemy)"),
    ("Gustavia (Saint-Barthélemy)", "Marigot (Saint-Martin)"),
    ("Marigot (Saint-Martin)", "Cayenne (Guyane)"),
    ("Cayenne (Guyane)", "Saint-Pierre (Saint-Pierre-et-Miquelon)"),
    ("Saint-Pierre (Saint-Pierre-et-Miquelon)", "Papeete (Polynésie française)"),
    ("Papeete (Polynésie française)", "Mata-Utu (Wallis-et-Futuna)"),
    ("Mata-Utu (Wallis-et-Futuna)", "Nouméa (Nouvelle-Calédonie)"),
    ("Nouméa (Nouvelle-Calédonie)", "Dzaoudzi (Mayotte)"),
]


def _official_12_pack():
    """Itinéraire officiel (12 jambes, PLAN_LEGS_MAX) : pas de Madère."""
    assert len(OFFICIAL_12_PAIRS) == 12
    legs = []
    for i, (frm, to) in enumerate(OFFICIAL_12_PAIRS):
        if "Ajaccio" in to:
            arrive = "2026-09-01T10:00:00Z"
        elif "Nouméa" in to:
            arrive = "2026-10-16T10:00:00Z"
        else:
            arrive = f"2026-08-{i + 1:02d}T10:00:00Z"
        legs.append({"from": frm, "to": to, "arriveIso": arrive})
    pack = {
        **FACT_PACK,
        "nextStop": {"name": "Nouméa (Nouvelle-Calédonie)", "eta": "2026-10-16T10:00:00Z"},
        "plan": {
            "source": "plan_review", "status": "ready", "n": 12, "unit": "ISO-8601",
            "legs": legs,
        },
    }
    return pack


def test_eta_named_place_absent_is_missing_info():
    pack = _official_12_pack()
    blob = " ".join(f"{lg.get('from')} {lg.get('to')}" for lg in pack["plan"]["legs"])
    assert "Madère" not in blob and "Madeira" not in blob
    parsed = logbook_chat.keyword_intent("Arrivée prévue à Madère ?")
    assert parsed["quantity"] == "eta" and parsed.get("place")
    assert logbook_chat._leg_for_place(pack, parsed["place"]) is None
    fr = logbook_chat.rules_answer("Arrivée prévue à Madère ?", pack, "fr")
    assert fr == logbook_chat.missing_info("fr")
    assert "Nouméa" not in fr and "Noumea" not in fr
    assert "2026-10-16" not in fr
    en = logbook_chat.rules_answer("Expected arrival in Madeira?", pack, "en")
    assert en == logbook_chat.missing_info("en")
    assert "Nouméa" not in en and "Noumea" not in en
    assert "2026-10-16" not in en


def test_eta_unnamed_keeps_next_stop():
    pack = _official_12_pack()
    parsed = logbook_chat.keyword_intent("Arrivée prévue ?")
    assert parsed["quantity"] == "eta"
    assert not parsed.get("place")
    fr = logbook_chat.rules_answer("Arrivée prévue ?", pack, "fr")
    assert fr != logbook_chat.missing_info("fr")
    assert "Nouméa" in fr
    assert "2026-10-16" in fr


def test_eta_named_place_on_a_leg():
    pack = _official_12_pack()
    parsed = logbook_chat.keyword_intent("Arrivée prévue à Ajaccio ?")
    assert parsed["quantity"] == "eta" and parsed.get("place")
    fr = logbook_chat.rules_answer("Arrivée prévue à Ajaccio ?", pack, "fr")
    assert "Ajaccio" in fr
    assert "2026-09-01" in fr
    assert "Nouméa" not in fr
    assert "2026-10-16" not in fr
    assert fr != logbook_chat.missing_info("fr")


def test_hard_question_judge_denied_zero_write(monkeypatch):
    seen = []

    async def fake_cascade(system, user, client=None, **kw):
        seen.append(kw.get("tier"))
        return "Stay. Speed is 7.4 kn.", "nemotron-ultra"

    async def fake_ctx(*_a, **_k):
        return dict(FACT_PACK)

    monkeypatch.setattr(logbook_chat, "cascade_text", fake_cascade)
    monkeypatch.setattr(logbook_chat, "build_context", fake_ctx)
    import llm_budget
    monkeypatch.setattr(llm_budget, "allow", lambda tier: False)
    out = asyncio.run(logbook_chat.answer_question(
        "Pourquoi ralentir ?", "fr", {}, datetime.now(timezone.utc),
    ))
    assert seen == []
    assert "write" not in seen
    assert out["source"] == "rules"
    assert "7.4" in out["answer"]
    assert "plafond" not in out["answer"]


def test_mode_off_answers_by_rules(monkeypatch):
    seen = []

    async def fake_cascade(system, user, client=None, **kw):
        seen.append(kw.get("tier"))
        raise AssertionError("no LLM when mode off")

    async def fake_ctx(*_a, **_k):
        return dict(FACT_PACK)

    monkeypatch.setenv("NAVIGUIDE_LLM_MODE", "off")
    monkeypatch.setattr(logbook_chat, "cascade_text", fake_cascade)
    monkeypatch.setattr(logbook_chat, "build_context", fake_ctx)
    fact = asyncio.run(logbook_chat.answer_question(
        "Quel vent au bateau ?", "fr", {}, datetime.now(timezone.utc),
    ))
    assert fact["source"] == "rules"
    assert "14.2" in fact["answer"]
    hard = asyncio.run(logbook_chat.answer_question(
        "Pourquoi ralentir ?", "fr", {}, datetime.now(timezone.utc),
    ))
    assert hard["source"] == "rules"
    assert "7.4" in hard["answer"]
    assert "raisonnement" not in hard["answer"].lower()
    assert seen == []


def test_get_logbook_facts_endpoint(client, monkeypatch):
    async def fake_ctx(*_a, **_k):
        return dict(FACT_PACK)

    monkeypatch.setattr(logbook_chat, "build_context", fake_ctx)
    r = client.get("/logbook/facts", headers=PUBLIC)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ready"
    for key in ("polar", "orders", "plan", "climo", "layers", "dcFamilies"):
        assert key in body["facts"]
    assert body["tokens"] <= logbook_chat.FACT_TOKEN_CAP


def test_slim_journal_entry_uses_spoken_title_when_name_missing():
    row = logbook_chat._slim_journal_entry({
        "kind": "stop",
        "t": "2026-10-01T16:00:00Z",
        "event": "arrival",
        "title": {"fr": "arrivée à Papeete", "en": "arrival in Papeete"},
    })
    assert row["name"] == "arrivée à Papeete"
    assert row["event"] == "arrival"


def test_per_kind_tail_keeps_last_n_per_kind():
    rows = [{"kind": "amp", "t": f"2026-10-01T{i:02d}:00:00Z", "id": f"amp:{i}"} for i in range(20)]
    out = logbook_chat._per_kind_tail(rows, n=8)
    assert [r["id"] for r in out] == [f"amp:{i}" for i in range(12, 20)]


def test_journal_for_chat_reads_official_store_not_file_journal(monkeypatch):
    journal.reset()
    payload = {
        "status": "ready",
        "latest": [
            {"id": "pos:1", "kind": "position", "t": "2026-10-15T12:00:00Z"},
            {
                "id": "amp:ahi", "kind": "amp", "t": "2026-10-15T11:00:00Z",
                "name": "Ahi Marine Protected Area", "nm": 9.7,
            },
        ],
        "events": [
            {
                "id": "amp:ahi", "kind": "amp", "t": "2026-10-15T11:00:00Z",
                "name": "Ahi Marine Protected Area", "nm": 9.7,
            },
            {
                "id": "zee:pf", "kind": "zee", "t": "2026-10-10T08:00:00Z",
                "name": "French Polynesia", "event": "enter",
            },
            {
                "id": "stop:ppt", "kind": "stop", "t": "2026-10-01T16:00:00Z",
                "name": "Papeete", "event": "arrival",
            },
        ],
    }
    import official_store
    monkeypatch.setattr(official_store, "serve_journal", lambda *_a, **_k: payload)
    rows = logbook_chat.journal_for_chat()
    kinds = {r["kind"] for r in rows}
    assert kinds >= {"amp", "zee", "stop"}
    assert "position" not in kinds
    ahi = next(r for r in rows if r["kind"] == "amp")
    assert ahi["name"] == "Ahi Marine Protected Area"
    assert ahi["nm"] == 9.7


def test_journal_for_chat_falls_back_to_file_when_store_preparing(monkeypatch):
    journal.reset()
    journal._append([{
        "id": "stop:file",
        "kind": "stop",
        "t": "2026-05-16T12:00:00Z",
        "name": "La Rochelle",
        "event": "arrival",
    }])
    monkeypatch.setattr(logbook_chat, "_official_journal_rows", lambda *_a, **_k: [])
    rows = logbook_chat.journal_for_chat()
    assert any(r.get("name") == "La Rochelle" for r in rows)


def test_chat_tier_never_routes_to_write():
    assert logbook_chat.chat_tier("Quel vent au bateau ?") == "fast"
    assert logbook_chat.chat_tier("Pourquoi ralentir ?") == "judge"
    assert logbook_chat.chat_tier("How should we handle the next gale?") == "judge"
    long_q = "Peux-tu me dire en détail ce que le journal sait du bateau, du vent et de la route prévue pour les jours qui viennent ?"
    assert len(long_q) >= logbook_chat.FAST_QUESTION_MAX
    assert logbook_chat.chat_tier(long_q) == "judge"
    assert logbook_chat.is_hard_question("Pourquoi ralentir ?") is True
    assert logbook_chat.is_hard_question("Quel vent au bateau ?") is False


def test_keyword_intent_pourquoi_ralentir_is_reason_speed():
    parsed = logbook_chat.keyword_intent("Pourquoi ralentir ?")
    assert parsed["intent"] == "reason"
    assert parsed["quantity"] == "speed"


def test_understand_uses_keywords_when_fast_denied(monkeypatch):
    seen = []

    async def fake_cascade(system, user, client=None, **kw):
        seen.append(kw.get("tier"))
        raise AssertionError("Nano must stay silent when allow(nano) is false")

    monkeypatch.setattr(logbook_chat, "cascade_text", fake_cascade)
    import llm_budget
    monkeypatch.setattr(llm_budget, "allow", lambda tier: False)
    parsed = asyncio.run(logbook_chat.understand_question("Quel vent au bateau ?", "fr"))
    assert parsed["intent"] == "fact"
    assert parsed["quantity"] == "wind"
    assert seen == []


def test_understand_uses_nano_when_allowed(monkeypatch):
    seen = []

    async def fake_cascade(system, user, client=None, **kw):
        seen.append(kw.get("tier"))
        return '{"intent":"fact","quantity":"wind","place":null,"when":null,"layer":null}', "nemotron-nano"

    monkeypatch.setattr(logbook_chat, "cascade_text", fake_cascade)
    import llm_budget
    monkeypatch.setattr(llm_budget, "allow", lambda tier: tier == "nano")
    parsed = asyncio.run(logbook_chat.understand_question("Quel vent au bateau ?", "fr"))
    assert seen == ["nano"]
    assert parsed["intent"] == "fact"
    assert parsed["quantity"] == "wind"


def test_dc_facts_from_bag_never_invent_satellite(monkeypatch):
    monkeypatch.setattr(logbook_chat, "_dc_from_film_bag", lambda: [])
    bag = {
        "amp": [{"name": "Pertuis Charentais", "nm": 3.6}],
        "poe": [{"name": "La Rochelle"}],
        "aton": {"nearby": [{"name": "Phare des Baleines", "nm": 4.0}]},
        "nearby": {"anchorages": [{"name": "Anse de Minimes"}]},
        "emodnet": {
            "cables": {"name": "Honotua", "nearby": True},
            "bathy": {"depth_m": 42.0},
        },
        "piracy": {"name": "Golfe de Guinée", "level": "elevated"},
        "satellites": {"reason": "not_in_along_pearl"},
    }
    rows = logbook_chat._dc_from_ici_bag(bag)
    kinds = [r["kind"] for r in rows]
    assert "amp" in kinds and "poe" in kinds and "aton" in kinds
    assert "anchorage" in kinds and "cable" in kinds and "depth" in kinds
    assert "piracy" in kinds
    assert "satellite" not in kinds
    cable = next(r for r in rows if r["kind"] == "cable")
    assert cable["name"] == "Honotua"
    depth = next(r for r in rows if r["kind"] == "depth")
    assert depth["depthM"] == 42.0
    merged = logbook_chat._dc_facts(bag)
    assert any(r.get("nm") == 3.6 for r in merged)


def test_rules_answer_pourquoi_ralentir_copies_speed():
    text = logbook_chat.rules_answer("Pourquoi ralentir ?", FACT_PACK, "fr")
    assert "7.4" in text
    kept, dropped = logbook_chat.filter_numbers(text, FACT_PACK)
    assert dropped == 0 and "7.4" in kept


def test_facts_cache_key_changes_with_the_utc_day():
    a = logbook_chat.facts_cache_key(datetime(2026, 10, 18, 23, 30, tzinfo=timezone.utc), "fr")
    b = logbook_chat.facts_cache_key(datetime(2026, 10, 19, 0, 5, tzinfo=timezone.utc), "fr")
    c = logbook_chat.facts_cache_key(datetime(2026, 10, 18, 1, 0, tzinfo=timezone.utc), "en")
    assert a != b
    assert a.startswith("2026-10-18T23|fr|")
    assert c.startswith("2026-10-18T01|en|")


def test_facts_cache_key_changes_within_the_utc_day():
    """À 20 h, le chat ne redonne pas la position du bateau de 8 h."""
    morning = logbook_chat.facts_cache_key(datetime(2026, 10, 18, 8, 0, tzinfo=timezone.utc), "fr")
    evening = logbook_chat.facts_cache_key(datetime(2026, 10, 18, 20, 0, tzinfo=timezone.utc), "fr")
    same_hour = logbook_chat.facts_cache_key(datetime(2026, 10, 18, 8, 59, tzinfo=timezone.utc), "fr")
    assert morning != evening
    assert morning == same_hour


def test_logbook_facts_second_call_reuses_the_day_cache(client, monkeypatch):
    """Le GET /logbook/facts du même jour ne reconstruit pas le paquet."""
    calls = []

    async def fake_ctx(*_a, **_k):
        calls.append(1)
        return dict(FACT_PACK)

    monkeypatch.setattr(logbook_chat, "build_context", fake_ctx)
    logbook_chat.reset_facts_cache()
    first = client.get("/logbook/facts", headers=PUBLIC)
    second = client.get("/logbook/facts", headers=PUBLIC)
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["cached"] is False
    assert second.json()["cached"] is True
    assert calls == [1]
    assert second.json()["facts"]["polar"] == first.json()["facts"]["polar"]
    assert second.json()["tokens"] <= logbook_chat.FACT_TOKEN_CAP
