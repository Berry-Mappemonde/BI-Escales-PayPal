import asyncio
import json
from pathlib import Path
import time
from urllib.parse import urlparse

import httpx
import pytest

from story_cascade import (
    CACHE_NS,
    DEFAULT_PROVIDERS,
    _PROMPT_LEAK_RE,
    _cache_get,
    _clean_text,
    _openai_text,
    build_prompt,
    cascade_text,
    filter_numbers,
    has_skipper_orders,
    need_page,
    providers,
    slim_event,
    story_tier,
    translate,
    write_story,
    TokenFactoryTimeout,
)

def _url_host_is(url: str, root: str) -> bool:
    """Hôte exact, ou sous-domaine. Jamais une sous-chaîne ailleurs dans l'URL."""
    host = (urlparse(str(url)).hostname or "").lower().rstrip(".")
    root = root.lower().strip(".")
    return bool(host) and (host == root or host.endswith("." + root))


def _eu_tf_host_is(url: str) -> bool:
    """Assert the request uses the fixed EU Token Factory host."""
    return _url_host_is(url, "api.tokenfactory.nebius.com")


# Capture PR #252 / revue du 22 sept. : fiche Pointe-à-Pitre servie depuis le cache.
CAPTURE_LEAK = (
    "Input: A large JSON object containing marina lists.\n"
    "- Task: Present a scale stop to a sailing crew arriving at Pointe-à-Pitre.\n"
    "What's for the boat, what's for the crew, what to know for formalities."
)


def test_story_tier_ultra_for_escales_and_alerts():
    assert story_tier({"type": "stop"}) == "deep"
    assert story_tier({"type": "wind-gale"}) == "deep"
    assert story_tier({"type": "zee-enter", "severity": "info"}) == "write"
    assert story_tier({"type": "zee-enter", "severity": "alert"}) == "deep"


def test_default_cascade_is_token_factory_not_tavily():
    src = Path(__file__).resolve().parents[1].joinpath("story_cascade.py").read_text()
    assert "api.tokenfactory.nebius.com" in src
    assert "Ultra default host is EU Token Factory" in src
    assert "NAVIGUIDE_LLM_PROVIDERS" in src
    assert "integrate.api.nvidia.com" in src  # NIM : 2e maillon
    assert "openrouter.ai" in src
    assert "api.anthropic.com" in src
    assert "tavily.com" not in src
    assert DEFAULT_PROVIDERS == ("tokenfactory", "nim", "openrouter", "claude")
    assert providers() == list(DEFAULT_PROVIDERS)  # ordre du porteur (20 sept.)


def test_missing_tokenfactory_key_skips_to_all_configured_providers(monkeypatch):
    """L'absence de TF est tracée et ne coupe pas NIM → OpenRouter → Claude."""
    import llm_budget
    import story_cascade

    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    monkeypatch.setenv("NAVIGUIDE_LLM_CACHE_TTL_S", "0")
    monkeypatch.setenv("NVIDIA_API_KEY", "nim-test")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "claude-test")
    calls = []

    async def forbidden_tf(*_args, **_kwargs):
        raise AssertionError("Token Factory doit être sauté sans clé")

    async def fail_nim(*_args, **_kwargs):
        calls.append("nim")
        raise RuntimeError("NIM indisponible")

    async def fail_openrouter(*_args, **_kwargs):
        calls.append("openrouter")
        raise RuntimeError("OpenRouter indisponible")

    async def fail_claude(*_args, **_kwargs):
        calls.append("claude")
        raise RuntimeError("Claude indisponible")

    monkeypatch.setattr(story_cascade, "_call_tokenfactory", forbidden_tf)
    monkeypatch.setattr(story_cascade, "_call_nim", fail_nim)
    monkeypatch.setattr(story_cascade, "_call_openrouter", fail_openrouter)
    monkeypatch.setattr(story_cascade, "_call_claude", fail_claude)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(500),
        )) as client:
            return await cascade_text(
                "sys", "local-replay-no-tf", client, tier="write",
                fallback="Phrase locale.", facts=None,
            )

    text, source = asyncio.run(run())
    assert (text, source) == ("Phrase locale.", "rules")
    assert calls == ["nim", "openrouter", "claude"]
    errors = llm_budget.last_errors()
    assert errors[0] == {
        "provider": "tokenfactory", "reason": "skipped: API key unavailable",
    }
    assert [item["provider"] for item in errors] == [
        "tokenfactory", "nim", "openrouter", "claude",
    ]


def test_missing_tokenfactory_key_labels_successful_nim_fallback(monkeypatch):
    import llm_budget
    import story_cascade

    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    monkeypatch.setenv("NAVIGUIDE_LLM_CACHE_TTL_S", "0")
    calls = []

    async def forbidden_tf(*_args, **_kwargs):
        raise AssertionError("Token Factory doit être sauté sans clé")

    async def nim_answer(*_args, **_kwargs):
        calls.append("nim")
        return "Réponse NIM locale.", f"nvidia-{story_cascade.NIM_MODEL}"

    monkeypatch.setattr(story_cascade, "_call_tokenfactory", forbidden_tf)
    monkeypatch.setattr(story_cascade, "_call_nim", nim_answer)

    async def run():
        async with httpx.AsyncClient() as client:
            return await cascade_text(
                "sys", "local-replay-nim", client, tier="write",
                fallback="Phrase locale.", facts=None,
            )

    text, source = asyncio.run(run())
    assert text == "Réponse NIM locale."
    assert source == f"nvidia-{story_cascade.NIM_MODEL}"
    assert calls == ["nim"]
    status = llm_budget.status()
    assert status["fallback"]["nim"] == 1
    assert status["lastSourceByTier"]["write"] == "nim"


def test_need_page_only_https_from_pack():
    assert need_page({"needPage": True, "pageUrl": "https://douane.gouv.fr/x"}) == (
        True, "https://douane.gouv.fr/x",
    )
    assert need_page({"needPage": False, "pageUrl": "https://douane.gouv.fr/x"})[0] is False
    assert need_page({"needPage": True, "pageUrl": "javascript:alert(1)"})[0] is False


def test_slim_event_keeps_tavily_null():
    out = slim_event({"event": "zee-enter", "tavily": "nope", "nvidia": None})
    assert out["tavily"] is None


def test_prompt_mentions_online_url_only_when_asked():
    system, user = build_prompt({"event": "zee-enter", "lang": "fr"}, None)
    assert "JSON" in user
    assert "monde" in system
    _, user2 = build_prompt({"event": "amp-ahead", "lang": "fr"}, "https://cabrera.es/v")
    assert "https://cabrera.es/v" in user2
    assert "Ne cherche pas le monde" in user2


SKIPPER = {
    "profile": "cruise",
    "profile_phrase": "Ordres Berry — croisière.",
    "comfort": "normal",
    "boat": {"name": "Leopard 46", "loaM": 14, "draftM": 1.4},
    "used": [
        {"id": "hsAlertM", "value": 3.5, "unit": "m", "source": "usage",
         "rule": "constante Croisière E1 3,5 m"},
    ],
}


def test_has_skipper_orders_needs_used_values():
    assert has_skipper_orders({"skipper": SKIPPER}) is True
    assert has_skipper_orders({"skipper": {"profile": "cruise", "used": []}}) is False
    assert has_skipper_orders({"skipper": None}) is False
    assert has_skipper_orders({}) is False
    assert has_skipper_orders(None) is False


def test_prompt_cites_the_skipper_thresholds_only_when_present():
    body = {"event": "hs-shift", "lang": "fr", "payload": {"hs": 3.6}, "skipper": SKIPPER}
    system, user = build_prompt(body, None)
    assert "skipper.used" in system
    assert "Aucun autre chiffre" in system
    assert "Thinking OFF" in system
    assert '"hsAlertM"' in user
    assert "3.5" in user
    assert "constante Croisière E1 3,5 m" in user

    system_en, _ = build_prompt({**body, "lang": "en"}, None)
    assert "skipper.used" in system_en

    plain, _ = build_prompt({"event": "hs-shift", "lang": "fr", "payload": {"hs": 3.6}}, None)
    assert "skipper.used" not in plain


def test_prompt_is_sober_one_or_two_sentences_no_machinery():
    """Revue du 19 sept. : le fait et sa source, rien sur le juge, l'identifiant, le bateau."""
    system, _ = build_prompt({"event": "depth-alert", "lang": "fr"}, None)
    assert "UNE ou DEUX phrases" in system
    for word in ("juge", "identifiant", "DOI", "tirant", "aucune information supplémentaire"):
        assert word in system  # listed as forbidden
    system_en, _ = build_prompt({"event": "depth-alert", "lang": "en"}, None)
    assert "ONE or TWO plain sentences" in system_en


def test_tidy_story_keeps_the_fact_drops_the_machinery():
    from story_cascade import tidy_story

    verbose = (
        "**Briefing nautique – La Rochelle**\n\n"
        "Le port d’entrée officiel se situe à Porto-Vecchio, à 292,3 nm. "
        "L’évènement est classé comme poe-ahead et porte l’identifiant poe-ahead:5682. "
        "Il a été jugé now avec la raison playhead. "
        "Le navire, un Leopard 46 de 14 m et 1,4 m de tirant d’eau, est en croisière avec un confort normal. "
        "Aucune information supplémentaire sur la période ou un DOI n’est disponible."
    )
    assert tidy_story(verbose) == "Le port d’entrée officiel se situe à Porto-Vecchio, à 292,3 nm."

    depth = (
        "La situation est classée immédiate par le juge. "
        "On approche du plateau : 2,3 m sondés pour un seuil fixé à 15 m, source EMODnet. "
        "Ne convient pas à la navigation. "
        "Le skipper a indiqué ce seuil conformément aux règles de croisière."
    )
    assert tidy_story(depth) == (
        "On approche du plateau : 2,3 m sondés pour un seuil fixé à 15 m, source EMODnet. "
        "Ne convient pas à la navigation."
    )

    # Only machinery → the local phrase; nothing at all → "".
    only_meta = "L’événement zee-exit est classé info. La décision a été prise immédiatement (juge)."
    assert tidy_story(only_meta, "Retour en haute mer — plus de ZEE à déclarer.") == "Retour en haute mer — plus de ZEE à déclarer."
    assert tidy_story(only_meta) == ""
    assert tidy_story(None, "repli") == "repli"
    # Long text is cut on a word, never mid-figure.
    long = "Vent " + "très " * 120 + "fort."
    out = tidy_story(long)
    assert len(out) <= 322 and out.endswith("…")


def test_write_story_returns_tidy_text_and_flags_local_fallback(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_chat_ok(
            "La ZEE française a été quittée. L’évènement est classé info et jugé immédiat.",
        ))

    monkeypatch.setenv("NEBIUS_API_KEY", "tf-test")
    monkeypatch.setenv("NAVIGUIDE_LLM_CACHE_TTL_S", "0")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    async def run(text_handler):
        async with httpx.AsyncClient(transport=httpx.MockTransport(text_handler)) as client:
            return await write_story({
                "event": "zee-exit", "eventId": "zee-exit:1", "lang": "fr", "needPage": False,
                "phrase": "Retour en haute mer — plus de ZEE à déclarer.",
            }, client=client)

    out = asyncio.run(run(handler))
    assert out["status"] == "ready"
    assert out["text"] == "La ZEE française a été quittée."
    assert out["source"] == "nemotron-super-vl"
    assert "+local" not in out["engine"]

    def only_meta(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_chat_ok("Événement classé info, jugé immédiat par le juge."))

    out2 = asyncio.run(run(only_meta))
    assert out2["status"] == "ready"
    assert out2["text"] == "Retour en haute mer — plus de ZEE à déclarer."
    assert out2["engine"].endswith("+local")


def test_slim_event_keeps_skipper_used_and_tavily_null():
    out = slim_event({"event": "hs-shift", "tavily": "nope", "skipper": SKIPPER})
    assert out["tavily"] is None
    assert out["skipper"]["used"][0]["value"] == 3.5
    assert out["skipper"]["boat"]["name"] == "Leopard 46"


def _chat_ok(text="Récit court de la ZEE.", model="nvidia/Nemotron-3.5-Super-VL"):
    return {
        "choices": [{"message": {"content": text}}],
        "model": model,
        "usage": {"prompt_tokens": 12, "completion_tokens": 8},
    }


def _tf_body(system="sys", user="La ZEE 5677.", **kw):
    kw.setdefault("tier", "write")
    kw.setdefault("fallback", "Phrase locale.")
    kw.setdefault("facts", {"zee": {"mrgid": 5677}})
    return system, user, kw


def test_cascade_tokenfactory_write_is_nemotron_super(monkeypatch):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        assert _url_host_is(str(request.url), "api.tokenfactory.nebius.com")
        body = request.read().decode()
        assert "Nemotron-3.5-Super-VL" in body
        return httpx.Response(200, json=_chat_ok("Entrée dans la ZEE française."))

    monkeypatch.setenv("NEBIUS_API_KEY", "tf-test")

    async def run():
        system, user, kw = _tf_body()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await cascade_text(system, user, client, **kw)

    text, source = asyncio.run(run())
    assert source == "nemotron-super-vl"
    assert "ZEE" in text
    assert len(seen) == 1
    assert not any("openrouter" in u or "anthropic" in u or "nvidia.com" in u for u in seen)


def test_cascade_tokenfactory_429_falls_to_openrouter(monkeypatch):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if "tokenfactory" in str(request.url):
            return httpx.Response(429, json={"error": "rate"})
        if "openrouter.ai" in str(request.url):
            return httpx.Response(200, json=_chat_ok("Filet OpenRouter : ZEE 5677."))
        return httpx.Response(500, json={"error": "no"})

    monkeypatch.setenv("NEBIUS_API_KEY", "tf-x")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-x")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    async def run():
        system, user, kw = _tf_body()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await cascade_text(system, user, client, **kw)

    text, source = asyncio.run(run())
    assert source == "openrouter"
    assert "5677" in text
    assert any("tokenfactory" in u for u in seen)
    assert any("openrouter.ai" in u for u in seen)


def test_cascade_all_down_returns_rules(monkeypatch):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(503, json={"error": "down"})

    monkeypatch.setenv("NEBIUS_API_KEY", "tf-x")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x")

    async def run():
        system, user, kw = _tf_body()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await cascade_text(system, user, client, **kw)

    text, source = asyncio.run(run())
    assert source == "rules"
    assert text == "Phrase locale."
    assert any("tokenfactory" in u for u in seen)
    assert any("openrouter.ai" in u for u in seen)
    assert any("anthropic.com" in u for u in seen)


def test_cascade_budget_cap_makes_no_request(monkeypatch):
    import llm_budget

    monkeypatch.setenv("NEBIUS_API_KEY", "tf-x")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-x")
    monkeypatch.setenv("NAVIGUIDE_LLM_DAILY_TOKENS_WRITE", "10")
    llm_budget.record("write", 10, 0)
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json=_chat_ok("ne doit pas partir"))

    async def run():
        system, user, kw = _tf_body()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await cascade_text(system, user, client, **kw)

    text, source = asyncio.run(run())
    assert source == "budget"
    assert seen == []
    assert text == "Phrase locale."


def test_cascade_lock_one_call_for_two_identical_requests(monkeypatch):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json=_chat_ok("Un seul appel Token Factory, ZEE 5677."))

    monkeypatch.setenv("NEBIUS_API_KEY", "tf-test")

    async def run():
        system, user, kw = _tf_body()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            a, b = await asyncio.gather(
                cascade_text(system, user, client, **kw),
                cascade_text(system, user, client, **kw),
            )
            return a, b

    (t1, s1), (t2, s2) = asyncio.run(run())
    assert {s1, s2} <= {"nemotron-super", "nemotron-super-vl", "cache"}
    assert t1 == t2
    assert len(seen) == 1


def test_filter_numbers_always_applied_on_cascade(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_chat_ok(
            "La ZEE 5677 commence ici. Le vent sera de 99 kn demain.",
        ))

    monkeypatch.setenv("NEBIUS_API_KEY", "tf-test")

    async def run():
        system, user, kw = _tf_body()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await cascade_text(system, user, client, **kw)

    text, source = asyncio.run(run())
    assert source == "nemotron-super-vl"
    assert "5677" in text
    assert "99" not in text


def test_filter_numbers_drops_invented_figures():
    text, dropped = filter_numbers(
        "La ZEE 5677. Il fera 30 kn demain.",
        {"zee": {"mrgid": 5677}},
    )
    assert "5677" in text and "30" not in text and dropped == 1


def test_filter_numbers_preserves_sentence_and_number_behavior():
    text, dropped = filter_numbers(
        "Port 5677 est calme. 30 kn demain ! Latitude 48,5 au nord?",
        {"port": 5677, "latitude": 48.5},
    )
    assert text == "Port 5677 est calme. Latitude 48,5 au nord?"
    assert dropped == 1


def test_write_story_tokenfactory_first_without_page(monkeypatch):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if "tokenfactory" in str(request.url):
            return httpx.Response(200, json=_chat_ok())
        return httpx.Response(500, json={"error": "no"})

    monkeypatch.setenv("NEBIUS_API_KEY", "tf-test")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await write_story({
                "event": "zee-enter",
                "eventId": "zee-enter:1",
                "lang": "fr",
                "needPage": False,
                "tavily": None,
            }, client=client)

    out = asyncio.run(run())
    assert out["status"] == "ready"
    assert out["tavily"] is None
    assert out["cascade"] == "tokenfactory-openrouter-claude"
    assert out["source"] == "nemotron-super-vl"
    assert any("tokenfactory" in u for u in seen)
    assert not any("openrouter" in u or "anthropic" in u or "nvidia.com" in u for u in seen)


def test_write_story_cache_returns_origin_and_cache_hit(monkeypatch):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json=_chat_ok("Le bateau entre dans la ZEE 5677."))

    monkeypatch.setenv("NEBIUS_API_KEY", "tf-test")
    monkeypatch.delenv("NAVIGUIDE_LLM_CACHE_TTL_S", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    body = {
        "event": "zee-enter",
        "eventId": "zee-enter:ed2-cache",
        "lang": "fr",
        "needPage": False,
        "payload": {"zee": {"mrgid": 5677, "name": "ED2"}},
    }

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            first = await write_story(body, client=client)
            second = await write_story(dict(body), client=client)
            return first, second

    first, second = asyncio.run(run())
    assert first["status"] == "ready" and first["source"] == "nemotron-super-vl"
    assert first["cache_hit"] is False
    assert second["status"] == "ready"
    assert second["source"] == "nemotron-super-vl"
    assert second["source"] != "cache"
    assert second["cache_hit"] is True
    assert len(seen) == 1


def test_write_story_need_page_still_reaches_openrouter_online(monkeypatch):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if "tokenfactory" in str(request.url):
            return httpx.Response(503, json={"error": "down"})
        body = request.read().decode()
        assert "cabrera.es" in body
        return httpx.Response(200, json=_chat_ok("Page officielle Cabrera : visiteurs."))

    monkeypatch.setenv("NEBIUS_API_KEY", "tf-x")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await write_story({
                "event": "amp-ahead",
                "eventId": "amp:1",
                "needPage": True,
                "pageUrl": "https://cabrera.es/v",
                "tavily": None,
            }, client=client)

    out = asyncio.run(run())
    assert out["status"] == "ready"
    assert out["source"] == "openrouter"
    assert out["tavily"] is None
    assert any("openrouter.ai" in u for u in seen)
    assert not any("tavily" in u for u in seen)


def test_write_story_falls_to_claude(monkeypatch):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if "anthropic.com" in str(request.url):
            return httpx.Response(200, json={
                "content": [{"type": "text", "text": "Filet Claude : ZEE."}],
            })
        return httpx.Response(503, json={"error": "down"})

    monkeypatch.setenv("NEBIUS_API_KEY", "tf-x")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await write_story({
                "event": "zee-enter",
                "eventId": "z",
                "needPage": False,
            }, client=client)

    out = asyncio.run(run())
    assert out["status"] == "ready"
    assert out["source"] == "claude"
    assert any("tokenfactory" in u for u in seen)
    assert any("openrouter.ai" in u for u in seen)
    assert any("anthropic.com" in u for u in seen)


def test_nim_still_available_behind_the_flag(monkeypatch):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if "nvidia.com" in str(request.url):
            return httpx.Response(200, json=_chat_ok("NIM : ZEE."))
        return httpx.Response(500, json={"error": "no"})

    monkeypatch.setenv("NAVIGUIDE_LLM_PROVIDERS", "nim,openrouter,claude")
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await cascade_text("s", "ZEE 1", client, fallback="x", facts={"n": 1})

    text, source = asyncio.run(run())
    assert "ZEE" in text
    assert any("nvidia.com" in u for u in seen)
    assert source.startswith("nvidia-")


FR_STORY = "Le 21 mai 2026 le bateau entre dans la ZEE française à La Rochelle, 36,5 kn [[ev:wx:gale]]."
EN_STORY = "On 21 May 2026 the boat entered the French EEZ at La Rochelle, 36.5 kn [[ev:wx:gale]]."


def test_translate_fr_is_noop():
    text, source = asyncio.run(translate("Déjà en français, ZEE 5677.", "fr"))
    assert text == "Déjà en français, ZEE 5677."
    assert source == "rules"


def test_translate_empty_is_rules():
    text, source = asyncio.run(translate("  ", "en"))
    assert text == "" and source == "rules"


def test_translate_en_keeps_numbers_names_dates(monkeypatch):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        body = request.read().decode()
        assert "Nemotron-3_5-Lightning" in body
        assert "36,5" in body and "La Rochelle" in body and "2026" in body
        return httpx.Response(200, json=_chat_ok(
            EN_STORY + " Tomorrow 99 kn.",
            model="nvidia/Nemotron-3_5-Lightning",
        ))

    monkeypatch.setenv("NEBIUS_API_KEY", "tf-test")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await translate(FR_STORY, "en", client)

    text, source = asyncio.run(run())
    assert source == "nemotron-lightning"
    assert "36.5" in text or "36,5" in text
    assert "La Rochelle" in text
    assert "2026" in text
    assert "[[ev:wx:gale]]" in text
    assert "99" not in text, "aucun chiffre nouveau"
    assert any("tokenfactory" in u for u in seen)


def test_translate_en_strips_bold(monkeypatch):
    """Le gras **…**, ***…*** et __…__ ne sort pas dans la traduction anglaise."""
    bold = "***On 21 May 2026*** the boat entered the French EEZ at __La Rochelle__, 36.5 kn [[ev:wx:gale]]."

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_chat_ok(bold, model="nvidia/Nemotron-3_5-Lightning"))

    monkeypatch.setenv("NEBIUS_API_KEY", "tf-test")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await translate(FR_STORY, "en", client)

    text, source = asyncio.run(run())
    assert source == "nemotron-lightning"
    assert "*" not in text
    assert "__" not in text
    assert "On 21 May 2026" in text
    assert "La Rochelle" in text
    assert "36.5" in text
    assert "[[ev:wx:gale]]" in text


def test_translate_cache_is_per_lang(monkeypatch):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json=_chat_ok(EN_STORY, model="nvidia/Nemotron-3_5-Lightning"))

    monkeypatch.setenv("NEBIUS_API_KEY", "tf-test")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            a = await translate(FR_STORY, "en", client)
            b = await translate(FR_STORY, "en", client)
            fr = await translate(FR_STORY, "fr", client)
            return a, b, fr

    a, b, fr = asyncio.run(run())
    (t1, s1), (t2, s2), (t3, s3) = a, b, fr
    assert t1 == t2 == EN_STORY.strip()
    assert {s1, s2} <= {"nemotron-lightning", "cache"}
    assert s1 == "nemotron-lightning" and s2 == "nemotron-lightning"
    assert getattr(b, "cache_hit", False) is True
    assert len(seen) == 1
    assert t3 == FR_STORY and s3 == "rules"


def test_write_story_en_translates_after_french_draft(monkeypatch):
    seen_models = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read().decode()
        if "Nemotron-3_5-Lightning" in body:
            seen_models.append("fast")
            return httpx.Response(200, json=_chat_ok(
                "The boat entered the French EEZ 5677.",
                model="nvidia/Nemotron-3_5-Lightning",
            ))
        seen_models.append("write")
        return httpx.Response(200, json=_chat_ok("Le bateau entre dans la ZEE française 5677."))

    monkeypatch.setenv("NEBIUS_API_KEY", "tf-test")
    monkeypatch.setenv("NAVIGUIDE_LLM_CACHE_TTL_S", "0")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await write_story({
                "event": "zee-enter", "eventId": "zee-enter:en", "lang": "en",
                "needPage": False, "payload": {"zee": {"mrgid": 5677}},
            }, client=client)

    out = asyncio.run(run())
    assert out["status"] == "ready"
    assert out["source"] == "nemotron-lightning"
    assert "5677" in out["text"]
    assert "99" not in out["text"]
    assert seen_models == ["write", "fast"]


def test_openai_text_strips_think_keeps_sentence():
    """Nemotron thinking stays out of the visitor text."""
    data = {
        "choices": [{
            "message": {
                "content": "<think>raisonnement…</think> La Rochelle est un port.",
                "reasoning_content": "Analyze User Input: Task: Translate…",
                "reasoning": "I need to answer using ONLY the JSON.",
            },
        }],
    }
    assert _openai_text(data) == "La Rochelle est un port."


def test_openai_text_ignores_nvidia_reasoning_field():
    """Une fuite de raisonnement ne devient pas le texte visiteur."""
    data = {
        "choices": [{
            "message": {
                "content": "",
                "reasoning": "I need to answer using ONLY the JSON. It lists:",
            },
        }],
    }
    assert _openai_text(data) == ""


def test_openai_text_reads_reasoning_when_content_is_empty():
    """content vide, finish=length : la phrase utile sort de reasoning ou reasoning_content."""
    leaked = "Analyze User Input: Task: Translate.\nLa Rochelle est un port."
    for field in ("reasoning", "reasoning_content"):
        data = {
            "choices": [{
                "finish_reason": "length",
                "message": {"content": "", field: leaked},
            }],
        }
        assert _openai_text(data, prompt="sys\nuser", lang="fr") == "La Rochelle est un port.", field
    english = {
        "choices": [{
            "finish_reason": "length",
            "message": {
                "content": None,
                "reasoning_content": "The swell reaches two metres off the quay.",
            },
        }],
    }
    assert _openai_text(english, prompt="sys\nuser", lang="en") == (
        "The swell reaches two metres off the quay."
    )
    assert _openai_text(english, prompt="sys\nuser", lang="fr") == ""


def test_openai_text_unclosed_think_is_cut():
    data = {"choices": [{"message": {"content": "<think>encore en train de réfléchir"}}]}
    assert _openai_text(data) == ""


def test_clean_text_strips_analyze_preamble():
    raw = (
        "**Analyze User Input: Task: Translate this paragraph.** "
        "Wait, let me re-read carefully. "
        "Saint-Maur is a quiet harbor on the Marne."
    )
    assert _clean_text(raw) == "Saint-Maur is a quiet harbor on the Marne."


def test_clean_text_removes_opening_and_closing_fences():
    assert _clean_text("```text\nA quiet harbor.\n```") == "A quiet harbor."
    assert _clean_text("Before.\n```json\nAfter.\n```") == "Before.\nAfter."


def test_long_whitespace_inputs_are_processed_quickly():
    spaces = " " * 50_000
    started = time.perf_counter()
    assert filter_numbers(spaces, {}) == ("", 0)
    assert _clean_text(spaces) == ""
    assert time.perf_counter() - started < 1.0


def test_clean_text_prompt_leak_is_empty():
    leaked = (
        "You translate a sailing-log paragraph from French to English. "
        "Keep every number, unit, proper name."
    )
    assert _clean_text(leaked) == ""
    echoed = (
        "Request: Present a stop/escales to a sailing crew arriving at Saint-Maur. "
        "- Constraints: Max 3 sentences."
    )
    assert _clean_text(echoed) == ""
    assert _clean_text("Here's a thinking process: 1") == ""
    assert "Analyze User Input" not in _clean_text("**Analyze User Input:** Entity: REPHY")


def test_prompt_leak_re_covers_22_sept_forms():
    """Les formes de la capture (et leurs traductions) vident le texte."""
    forms = (
        "Input: A large JSON object containing marina lists.",
        "What's for the boat, what's for the crew.",
        "- Task: Present a scale stop to a sailing crew.",
        "Task: Present a scale stop at Pointe-à-Pitre.",
        "Entrée : Un grand objet JSON déjà collecté.",
        "Ce qu'il y a pour le bateau, ce qu'il y a pour l'équipage.",
        "- Tâche : Présente une escale à Pointe-à-Pitre.",
        "You are the logbook of the Berry-Mappemonde sailing expedition.",
        "Tu es le journal de bord de l'expédition à la voile.",
        "I need to answer using ONLY the JSON. It lists:",
        "The JSON does not contain any information about Cape Horn.",
        "JSON does not hold the answer.",
        CAPTURE_LEAK,
    )
    for form in forms:
        assert _PROMPT_LEAK_RE.search(form), form
        assert _clean_text(form) == "", form
    healthy = "Pointe-à-Pitre has a marina at Bas-du-Fort and a harbour master's office."
    assert not _PROMPT_LEAK_RE.search(healthy)
    assert _clean_text(healthy) == healthy
    # Un « task » sans deux-points (phrase réelle) n'est pas une fuite.
    real = "The harbour master's task is to assign a berth."
    assert _clean_text(real) == real


def test_llm_cache_leaked_entry_is_invalidated(monkeypatch):
    """Une perle llm-cache fuitée est droppée, jamais re-servie."""
    import pearl_store

    monkeypatch.delenv("NAVIGUIDE_LLM_CACHE_TTL_S", raising=False)
    key = "rb3-leak-capture"
    pearl_store.kv_put(CACHE_NS, key, {"text": CAPTURE_LEAK, "source": "nemotron-super"})
    assert pearl_store.kv_get(CACHE_NS, key) is not None
    assert _cache_get(key) is None
    assert pearl_store.kv_get(CACHE_NS, key) is None


def test_llm_cache_healthy_entry_is_served_unchanged(monkeypatch):
    import pearl_store

    monkeypatch.delenv("NAVIGUIDE_LLM_CACHE_TTL_S", raising=False)
    key = "rb3-healthy"
    text = "Pointe-à-Pitre has a marina at Bas-du-Fort."
    pearl_store.kv_put(CACHE_NS, key, {"text": text, "source": "nemotron-super"})
    hit = _cache_get(key)
    assert hit == (text, "nemotron-super")
    assert getattr(hit, "cache_hit", False) is True
    assert hit[1] != "cache"
    stored = (pearl_store.kv_get(CACHE_NS, key) or {}).get("value") or {}
    assert stored.get("text") == text
    assert stored.get("source") == "nemotron-super"


def test_cascade_think_block_keeps_final_sentence(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_chat_ok(
            "<think>raisonnement…</think> La Rochelle est un port.",
        ))

    monkeypatch.setenv("NEBIUS_API_KEY", "tf-test")
    monkeypatch.setenv("NAVIGUIDE_LLM_CACHE_TTL_S", "0")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await cascade_text(
                "sys", "La Rochelle.", client, fallback="Phrase locale.", facts="La Rochelle",
            )

    text, source = asyncio.run(run())
    assert text == "La Rochelle est un port."
    assert source == "nemotron-super-vl"


def test_cascade_reasoning_only_falls_to_rules(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_chat_ok(
            "<think>Wait, let me analyze the task. Analyze User Input.</think>",
        ))

    monkeypatch.setenv("NEBIUS_API_KEY", "tf-test")
    monkeypatch.setenv("NAVIGUIDE_LLM_CACHE_TTL_S", "0")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await cascade_text(
                "sys", "user", client, fallback="Phrase locale.", facts="user",
            )

    text, source = asyncio.run(run())
    assert source == "rules"
    assert text == "Phrase locale."


def test_tokenfactory_payload_disables_thinking(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if "tokenfactory" in str(request.url):
            seen.update(json.loads(request.content.decode()))
            return httpx.Response(200, json=_chat_ok("La Rochelle est un port."))
        return httpx.Response(500, json={"error": "no"})

    monkeypatch.setenv("NEBIUS_API_KEY", "tf-test")
    monkeypatch.setenv("NAVIGUIDE_LLM_CACHE_TTL_S", "0")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await cascade_text(
                "sys", "La Rochelle.", client, fallback="x", facts="La Rochelle",
            )

    text, source = asyncio.run(run())
    assert "port" in text
    assert source == "nemotron-super-vl"
    assert seen["chat_template_kwargs"]["enable_thinking"] is False
    assert "thinking" not in seen["chat_template_kwargs"]
    assert seen["reasoning_effort"] == "none"
    assert "extra_body" not in seen


def test_lightning_payload_includes_thinking_off_flags_at_json_root():
    """LT1 étape A confirmée (#432) : drapeaux au premier niveau du JSON, pas extra_body."""
    import llm_budget
    import story_cascade

    payload = story_cascade._tf_payload("sys", "user", "fast")
    assert set(payload) >= {
        "model", "messages", "max_tokens", "reasoning_effort", "chat_template_kwargs",
    }
    assert payload["reasoning_effort"] == "none"
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}
    assert "extra_body" not in payload
    nested = payload.get("extra_body")
    assert nested is None
    assert payload["max_tokens"] == llm_budget.max_tokens_for("fast")
    assert payload["max_tokens"] == 1024


def test_fast_nim_fallback_updates_status_by_tier(monkeypatch):
    import llm_budget

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "tokenfactory" in url:
            return httpx.Response(400, text='{"error":"fail"}')
        if "nvidia.com" in url:
            return httpx.Response(200, json=_chat_ok("NIM fallback text."))
        return httpx.Response(500)

    monkeypatch.setenv("NEBIUS_API_KEY", "tf-test")
    monkeypatch.setenv("NVIDIA_API_KEY", "nim-test")
    monkeypatch.setenv("NAVIGUIDE_LLM_CACHE_TTL_S", "0")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await cascade_text(
                "sys", "user", client, tier="fast", fallback="x", facts="user",
            )

    text, source = asyncio.run(run())
    assert "NIM" in text
    st = llm_budget.status()
    assert st["fallback"]["nim"] == 1
    assert st["lastSourceByTier"]["fast"] == "nim"
    assert st["lastSource"] == "nim"


def test_fast_tokenfactory_empty_retries_super(monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        calls.append(body.get("model"))
        if "Lightning" in (body.get("model") or ""):
            return httpx.Response(200, json={
                "choices": [{"message": {"content": ""}, "finish_reason": "length"}],
                "usage": {"completion_tokens": 60},
                "model": body["model"],
            })
        return httpx.Response(200, json=_chat_ok("Lightning failed, Super answers.", model=body["model"]))

    monkeypatch.setenv("NEBIUS_API_KEY", "tf-test")
    monkeypatch.setenv("NAVIGUIDE_LLM_CACHE_TTL_S", "0")
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await cascade_text(
                "sys", "user", client, tier="fast", fallback="x", facts="user",
            )

    text, source = asyncio.run(run())
    assert source == "nemotron-super-vl"
    assert "Super" in text
    assert len(calls) == 2
    assert any("Lightning" in m for m in calls)
    assert any("super" in m.lower() for m in calls)
    import llm_budget
    st = llm_budget.status()
    assert st["retrySuper"] == 1
    assert st["lastSourceByTier"]["fast"] == "nemotron-super-vl"


def test_fast_tokenfactory_success_clears_tier_errors(monkeypatch):
    import llm_budget

    llm_budget.remember_cascade_errors(
        [{"provider": "tokenfactory", "reason": "old fast error"}], tier="fast",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        return httpx.Response(200, json=_chat_ok("Lightning ok.", model=body.get("model")))

    monkeypatch.setenv("NEBIUS_API_KEY", "tf-test")
    monkeypatch.setenv("NAVIGUIDE_LLM_CACHE_TTL_S", "0")
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await cascade_text(
                "sys", "user", client, tier="fast", fallback="x", facts="user",
            )

    text, source = asyncio.run(run())
    assert source == "nemotron-lightning"
    assert llm_budget.last_errors() is None
    st = llm_budget.status()
    assert "lastErrors" not in st
    assert st["lastSourceByTier"]["fast"] == "nemotron-lightning"


def test_fast_tokenfactory_empty_then_super_empty_calls_nim(monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        body = json.loads(request.content.decode()) if request.content else {}
        calls.append(url)
        if "tokenfactory" in url:
            return httpx.Response(200, json={
                "choices": [{"message": {"content": ""}, "finish_reason": "length"}],
                "usage": {"completion_tokens": 0},
                "model": body.get("model") or "tf",
            })
        if "nvidia.com" in url:
            return httpx.Response(200, json=_chat_ok("NIM after double TF miss."))
        return httpx.Response(500, json={"error": "no"})

    monkeypatch.setenv("NEBIUS_API_KEY", "tf-test")
    monkeypatch.setenv("NVIDIA_API_KEY", "nim-test")
    monkeypatch.setenv("NAVIGUIDE_LLM_CACHE_TTL_S", "0")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await cascade_text(
                "sys", "user", client, tier="fast", fallback="x", facts="user",
            )

    text, source = asyncio.run(run())
    assert "NIM" in text
    assert source.startswith("nvidia-")
    assert sum("tokenfactory" in u for u in calls) == 2
    assert any("nvidia.com" in u for u in calls)


def test_ultra_payload_uses_cookbook_host_and_budget():
    import llm_budget
    import story_cascade

    payload = story_cascade._tf_payload("sys", "user", "deep")
    assert payload["reasoning_effort"] == "none"
    assert payload["chat_template_kwargs"]["enable_thinking"] is False
    assert "extra_body" not in payload
    assert payload["max_tokens"] == llm_budget.max_tokens_for("deep")
    assert payload["max_tokens"] == 2048
    assert _eu_tf_host_is(story_cascade._tf_url("deep"))
    assert _eu_tf_host_is(story_cascade._tf_url("fast"))
    assert _eu_tf_host_is(story_cascade._tf_url("write"))


def test_tokenfactory_http_error_includes_body():
    import story_cascade

    class Fake:
        status_code = 400
        text = '{"error":"max_tokens too small for thinking"}'

    err = story_cascade._http_error("tokenfactory", Fake())
    assert "400" in str(err)
    assert "max_tokens too small" in str(err)


def test_cascade_records_tokenfactory_failure(monkeypatch, caplog):
    import llm_budget
    import story_cascade

    def handler(request: httpx.Request) -> httpx.Response:
        if "tokenfactory" in str(request.url):
            return httpx.Response(422, text='{"error":"empty completion"}')
        return httpx.Response(500)

    monkeypatch.setenv("NEBIUS_API_KEY", "tf-test")
    monkeypatch.setenv("NAVIGUIDE_LLM_CACHE_TTL_S", "0")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    caplog.set_level("WARNING", logger="naviguide-simulator.story-cascade")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await cascade_text("sys", "user", client, fallback="Phrase locale.", facts="user")

    text, source = asyncio.run(run())
    assert source == "rules"
    assert text == "Phrase locale."
    hops = llm_budget.last_errors()
    assert hops and hops[0]["provider"] == "tokenfactory"
    assert "422" in hops[0]["reason"]
    assert "empty completion" in hops[0]["reason"]
    err = llm_budget.last_error()
    assert err["provider"] == "tokenfactory"
    assert any("tokenfactory" in r.message for r in caplog.records)
    assert {h["provider"] for h in hops} >= {"tokenfactory", "nim", "openrouter", "claude"}
    assert llm_budget.status()["lastError"]["reason"] == err["reason"]


def test_cascade_keeps_tokenfactory_error_when_nim_answers(monkeypatch):
    import llm_budget

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "tokenfactory" in url:
            return httpx.Response(400, text='{"error":"thinking not allowed"}')
        if "integrate.api.nvidia.com" in url:
            return httpx.Response(200, json=_chat_ok("The boat is at the quay."))
        return httpx.Response(500)

    monkeypatch.setenv("NEBIUS_API_KEY", "tf-test")
    monkeypatch.setenv("NVIDIA_API_KEY", "nim-test")
    monkeypatch.setenv("NAVIGUIDE_LLM_CACHE_TTL_S", "0")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await cascade_text("sys", "The boat.", client, fallback="x", facts="The boat")

    text, source = asyncio.run(run())
    assert "quay" in text
    assert source.startswith("nvidia-")
    err = llm_budget.last_error()
    assert err["provider"] == "tokenfactory"
    assert "400" in err["reason"]
    assert "thinking not allowed" in err["reason"]


def _empty_reasoning(body, reasoning, finish="length"):
    return {
        "choices": [{
            "message": {"content": "", "reasoning": reasoning},
            "finish_reason": finish,
        }],
        "usage": {"prompt_tokens": 8, "completion_tokens": 40},
        "model": body.get("model"),
    }


def test_empty_content_with_reasoning_stays_on_the_tier(monkeypatch):
    """content vide + reasoning utile + finish=length : texte et palier Nemotron, sans repli."""
    import llm_budget

    cases = (
        ("fast", "nvidia/Nemotron-3_5-Lightning", "nemotron-lightning", False),
        ("write", "nvidia/Nemotron-3.5-Super-VL", "nemotron-super-vl", False),
        ("deep", "nvidia/Nemotron-3-Ultra-550b-a55b", "nemotron-ultra", True),
        ("judge", "nvidia/Nemotron-3-Ultra-550b-a55b", "nemotron-ultra", True),
    )
    monkeypatch.setenv("NEBIUS_API_KEY", "tf-test")
    monkeypatch.setenv("NVIDIA_API_KEY", "nim-test")
    monkeypatch.setenv("NAVIGUIDE_LLM_CACHE_TTL_S", "0")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    for tier, model, source, ultra_host in cases:
        seen = []

        def handler(request: httpx.Request, _seen=seen) -> httpx.Response:
            body = json.loads(request.content.decode())
            url = str(request.url)
            _seen.append((url, body.get("model")))
            if "nvidia.com" in url:
                return httpx.Response(200, json=_chat_ok("Le quai reste calme.", model="openai/gpt-oss-20b"))
            if "openrouter" in url or "anthropic" in url:
                return httpx.Response(200, json=_chat_ok("Repli inutile."))
            return httpx.Response(200, json=_empty_reasoning(
                body,
                "Analyze User Input: Task: Translate.\nLa Rochelle est un port.",
            ))

        async def run(tier=tier):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                return await cascade_text(
                    "sys", f"user-{tier}", client, tier=tier, fallback="Phrase locale.", facts=None,
                )

        before = llm_budget.get_usage(tier)
        result = asyncio.run(run())
        text, got = result
        assert got == source, tier
        assert text == "La Rochelle est un port.", tier
        assert "Analyze" not in text, tier
        assert "Translate" not in text, tier
        assert result.model == model, tier
        assert result.tier == tier
        tf = [(url, asked) for url, asked in seen if "tokenfactory" in url]
        assert len(tf) == 1, tier
        assert tf[0][1] == model, tier
        assert _eu_tf_host_is(tf[0][0]), tier
        assert not any(
            _url_host_is(url, "nvidia.com")
            or _url_host_is(url, "openrouter.ai")
            or _url_host_is(url, "anthropic.com")
            for url, _asked in seen
        ), tier
        usage = llm_budget.get_usage(tier)
        assert usage["calls"] == before["calls"] + 1, tier
        assert usage["prompt_tokens"] == before["prompt_tokens"] + 8, tier
        assert usage["completion_tokens"] == before["completion_tokens"] + 40, tier
        st = llm_budget.status()
        assert "lastError" not in st, tier
        assert st["lastSourceByTier"][tier] == source, tier
        assert st["fallback"]["nim"] == 0, tier
        if tier == "fast":
            assert st["retrySuper"] == 0
            assert llm_budget.get_usage("write")["calls"] == 0


def test_empty_content_records_billed_reasoning_tokens(monkeypatch):
    """finish=length et content vide : les jetons facturés sont comptés, puis repli NIM."""
    import llm_budget

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        body = json.loads(request.content.decode())
        if "tokenfactory" in url:
            data = _empty_reasoning(body, "Je vais écrire une phrase sur la houle.")
            data["usage"] = {"prompt_tokens": 11, "completion_tokens": 37}
            return httpx.Response(200, json=data)
        if "nvidia.com" in url:
            return httpx.Response(200, json=_chat_ok("Le quai reste calme.", model="openai/gpt-oss-20b"))
        return httpx.Response(500, json={"error": "no"})

    monkeypatch.setenv("NEBIUS_API_KEY", "tf-test")
    monkeypatch.setenv("NVIDIA_API_KEY", "nim-test")
    monkeypatch.setenv("NAVIGUIDE_LLM_CACHE_TTL_S", "0")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await cascade_text(
                "sys", "user-billed", client, tier="write", fallback="Phrase locale.", facts=None,
            )

    result = asyncio.run(run())
    text, source = result
    assert source.startswith("nvidia-")
    assert "nemotron" not in source.lower()
    assert "quai reste calme" in text
    assert "écrire" not in text
    usage = llm_budget.get_usage("write")
    assert usage["calls"] == 1
    assert usage["prompt_tokens"] == 11
    assert usage["completion_tokens"] == 37
    assert llm_budget.last_source_by_tier().get("write") == "nim"


def test_fast_leak_reasoning_still_retries_super(monkeypatch):
    """Un raisonnement qui n'est qu'une fuite ne devient pas le texte : Super est appelé."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        calls.append(body.get("model"))
        if "Lightning" in (body.get("model") or ""):
            return httpx.Response(200, json=_empty_reasoning(
                body, "I need to answer using ONLY the JSON. It lists:",
            ))
        return httpx.Response(200, json=_chat_ok("Super écrit le port.", model=body["model"]))

    monkeypatch.setenv("NEBIUS_API_KEY", "tf-test")
    monkeypatch.setenv("NAVIGUIDE_LLM_CACHE_TTL_S", "0")
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await cascade_text("sys", "user", client, tier="fast", fallback="x", facts=None)

    result = asyncio.run(run())
    text, source = result
    assert source == "nemotron-super-vl"
    assert "port" in text
    assert "JSON" not in text
    assert len(calls) == 2
    assert "Lightning" in calls[0]
    assert "super" in calls[1].lower()
    assert result.model == "nvidia/Nemotron-3.5-Super-VL"
    assert result.tier == "write"


def test_write_story_keeps_exact_super_model_and_tier(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        assert body["model"] == "nvidia/Nemotron-3.5-Super-VL"
        return httpx.Response(200, json=_chat_ok("Entrée dans la ZEE.", model=body["model"]))

    monkeypatch.setenv("NEBIUS_API_KEY", "tf-test")
    monkeypatch.setenv("NAVIGUIDE_LLM_CACHE_TTL_S", "0")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await write_story({
                "event": "zee-enter", "eventId": "zee-enter:model", "lang": "fr", "needPage": False,
            }, client=client)

    out = asyncio.run(run())
    assert out["status"] == "ready"
    assert out["source"] == "nemotron-super-vl"
    assert out["tier"] == "write"
    assert out["model"] == "nvidia/Nemotron-3.5-Super-VL"
    assert out["ai_model"] == "nvidia/Nemotron-3.5-Super-VL"
    assert out["ai_generated"] is True
    assert "Token Factory" not in out["model"]


def test_fallback_model_is_not_labelled_token_factory(monkeypatch):
    """OpenRouter, Claude et NIM gardent leur modèle. Jamais un id Nemotron."""
    import llm_budget

    monkeypatch.setenv("NEBIUS_API_KEY", "tf-test")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x")
    monkeypatch.setenv("NVIDIA_API_KEY", "nim-test")
    monkeypatch.setenv("NAVIGUIDE_LLM_CACHE_TTL_S", "0")

    def openrouter_handler(request: httpx.Request) -> httpx.Response:
        if "tokenfactory" in str(request.url):
            return httpx.Response(503, json={"error": "down"})
        if "openrouter.ai" in str(request.url):
            return httpx.Response(200, json=_chat_ok("Filet OpenRouter : le port."))
        return httpx.Response(500, json={"error": "no"})

    async def run_or():
        async with httpx.AsyncClient(transport=httpx.MockTransport(openrouter_handler)) as client:
            return await write_story({
                "event": "zee-enter", "eventId": "zee-or", "lang": "fr", "needPage": False,
            }, client=client)

    opened = asyncio.run(run_or())
    assert opened["source"] == "openrouter"
    assert opened["model"] == "openai/gpt-4o-mini"
    assert opened["ai_model"] == "openai/gpt-4o-mini"
    assert opened["tier"] == "write"
    assert "nemotron" not in opened["model"].lower()
    assert "nemotron" not in opened["ai_model"].lower()

    def claude_handler(request: httpx.Request) -> httpx.Response:
        if "anthropic.com" in str(request.url):
            return httpx.Response(200, json={
                "model": "claude-haiku-4-5",
                "content": [{"type": "text", "text": "Filet Claude : le port."}],
            })
        return httpx.Response(503, json={"error": "down"})

    async def run_claude():
        async with httpx.AsyncClient(transport=httpx.MockTransport(claude_handler)) as client:
            return await write_story({
                "event": "zee-enter", "eventId": "zee-claude", "lang": "fr", "needPage": False,
            }, client=client)

    claude = asyncio.run(run_claude())
    assert claude["source"] == "claude"
    assert claude["model"] == "claude-haiku-4-5"
    assert claude["ai_model"] == "claude"
    assert "nemotron" not in claude["model"].lower()
    assert "Token Factory" not in claude["ai_model"]

    def nim_handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "tokenfactory" in url:
            body = json.loads(request.content.decode())
            return httpx.Response(200, json=_empty_reasoning(body, ""))
        if "nvidia.com" in url:
            return httpx.Response(200, json=_chat_ok("NIM : le port."))
        return httpx.Response(500, json={"error": "no"})

    async def run_nim():
        async with httpx.AsyncClient(transport=httpx.MockTransport(nim_handler)) as client:
            return await write_story({
                "event": "zee-enter", "eventId": "zee-nim", "lang": "fr", "needPage": False,
            }, client=client)

    nim = asyncio.run(run_nim())
    assert nim["source"].startswith("nvidia-")
    assert nim["model"] == "openai/gpt-oss-20b"
    assert nim["ai_model"] == "openai/gpt-oss-20b"
    assert "nemotron" not in nim["model"].lower()
    assert "Token Factory" not in nim["ai_model"]
    assert llm_budget.status()["lastSourceByTier"]["write"] == "nim"


def _nim_after_empty_reasoning(monkeypatch, reasoning, *, lang="fr", nim_text="Le port reste calme."):
    """Token Factory renvoie un raisonnement sans content. NIM répond ensuite."""
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        body = json.loads(request.content.decode()) if request.content else {}
        seen.append((url, body.get("model")))
        if "tokenfactory" in url:
            return httpx.Response(200, json=_empty_reasoning(body, reasoning))
        if "nvidia.com" in url:
            return httpx.Response(200, json=_chat_ok(nim_text, model="openai/gpt-oss-20b"))
        return httpx.Response(500, json={"error": "no"})

    monkeypatch.setenv("NEBIUS_API_KEY", "tf-test")
    monkeypatch.setenv("NVIDIA_API_KEY", "nim-test")
    monkeypatch.setenv("NAVIGUIDE_LLM_CACHE_TTL_S", "0")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return handler, seen


def test_reasoning_leak_falls_back_with_an_honest_label(monkeypatch):
    """Un content vide, même avec ces phrases dans le raisonnement, part en repli NIM."""
    import llm_budget

    leaks = (
        "The user wants one or two sentences about the swell. The JSON says the height is two metres.",
        "We need to produce a short French sentence about the harbour.",
        "Okay, so I should mention the quay and the swell.",
        "Maybe the wind is fresher tonight.",
        "Let's mention the swell.",
        "UNE ou DEUX phrases simples : le fait, le ou les chiffres du bulletin.",
        "The swell reaches two metres off the quay tonight.",
        "L'utilisateur demande une courte phrase sur la houle du jour.",
        "Nous devons produire une phrase courte.",
        "D'accord, je dois mentionner le quai.",
        "Peut-être que le vent fraîchit au large.",
    )
    for i, reasoning in enumerate(leaks):
        handler, seen = _nim_after_empty_reasoning(monkeypatch, reasoning)
        seen.clear()

        async def run(i=i, handler=handler):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                return await write_story({
                    "event": "zee-enter",
                    "eventId": f"zee-leak-{i}",
                    "lang": "fr",
                    "needPage": False,
                }, client=client)

        out = asyncio.run(run())
        text = out.get("text") or ""
        assert out["status"] == "ready", reasoning
        assert out["source"].startswith("nvidia-"), reasoning
        assert "nemotron" not in out["source"].lower(), reasoning
        assert out["model"] == "openai/gpt-oss-20b", reasoning
        assert out["ai_model"] == "openai/gpt-oss-20b", reasoning
        assert "Token Factory" not in out["ai_model"], reasoning
        assert "port reste calme" in text, reasoning
        for banned in (
            "The user", "We need", "Okay", "Maybe", "Let's", "JSON",
            "phrases simples", "The swell", "utilisateur", "Nous devons",
            "D'accord", "Peut-être", "bulletin",
        ):
            assert banned not in text, (banned, reasoning)
        assert llm_budget.status()["lastSourceByTier"]["write"] == "nim"
        assert any("tokenfactory" in url for url, _model in seen)
        assert any("nvidia.com" in url for url, _model in seen)


def test_plain_reasoning_sentence_stays_on_nemotron(monkeypatch):
    """Une phrase propre dans le raisonnement reste sur Super, sans repli NIM."""
    import llm_budget

    handler, seen = _nim_after_empty_reasoning(
        monkeypatch,
        "The user wants one or two sentences about the swell. "
        "La houle atteint deux mètres au large de La Rochelle.",
    )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await write_story({
                "event": "zee-enter", "eventId": "zee-plain-fr", "lang": "fr", "needPage": False,
            }, client=client)

    out = asyncio.run(run())
    text = out.get("text") or ""
    assert out["status"] == "ready"
    assert out["source"] == "nemotron-super-vl"
    assert out["tier"] == "write"
    assert out["model"] == "nvidia/Nemotron-3.5-Super-VL"
    assert out["ai_model"] == "nvidia/Nemotron-3.5-Super-VL"
    assert "houle" in text
    assert "Rochelle" in text
    assert "The user" not in text
    assert "JSON" not in text
    assert "port reste calme" not in text
    assert not any(_url_host_is(url, "nvidia.com") for url, _model in seen)
    assert llm_budget.status()["lastSourceByTier"]["write"] == "nemotron-super-vl"
    assert "lastError" not in llm_budget.status()


def test_english_reasoning_falls_back_to_nim(monkeypatch):
    """Une phrase anglaise propre reste sur Super. Une fuite ou la mauvaise langue part en NIM."""
    import llm_budget

    kept = "The swell reaches two metres off the quay."
    handler, seen = _nim_after_empty_reasoning(
        monkeypatch, kept, lang="en", nim_text="The harbour stays quiet.",
    )

    async def run_ok():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await cascade_text(
                "sys", "user-en-plain", client, tier="write", lang="en",
                fallback="Local phrase.", facts=None,
            )

    good = asyncio.run(run_ok())
    text, source = good
    assert source == "nemotron-super-vl"
    assert text == kept
    assert "harbour stays quiet" not in text
    assert good.model == "nvidia/Nemotron-3.5-Super-VL"
    assert good.tier == "write"
    assert llm_budget.last_source_by_tier().get("write") == "nemotron-super-vl"
    assert not any(_url_host_is(url, "nvidia.com") for url, _model in seen)
    assert "lastError" not in llm_budget.status()

    leaks = (
        "La houle atteint deux mètres au large du quai.",
        "We need to produce a short sentence about the swell.",
        "You write one card for a sailor from the facts already collected.",
    )
    for i, reasoning in enumerate(leaks):
        handler, _seen = _nim_after_empty_reasoning(
            monkeypatch, reasoning, nim_text="The quay stays calm.",
        )

        async def run(handler=handler, i=i):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                return await cascade_text(
                    "You write one card for a sailor from the facts already collected.",
                    f"user-en-leak-{i}",
                    client,
                    tier="write",
                    lang="en",
                    fallback="Local phrase.",
                    facts=None,
                )

        out_text, out_source = asyncio.run(run())
        assert out_source.startswith("nvidia-"), reasoning
        assert "quay stays calm" in out_text, reasoning
        assert "houle" not in out_text, reasoning
        assert "We need" not in out_text, reasoning
        assert "one card for a sailor" not in out_text, reasoning
        assert llm_budget.last_source_by_tier().get("write") == "nim"


_REASONING_LEAKS = (
    "Je vais écrire une phrase sur la houle.",
    "On me demande une courte phrase sur le quai.",
    "I will write a short sentence about the swell.",
    "I am asked for a sentence about the quay.",
    "Final answer: the swell reaches two metres.",
    "Réponse finale : la houle atteint deux mètres.",
    "Translation: the harbour is calm tonight.",
    "Traduction : le port est calme ce soir.",
    "Here is the translation of the French card.",
    "Voici la traduction de la carte.",
    "UNE ou DEUX phrases simples : le fait, le ou les chiffres du JSON, la source ou le modèle",
    "ONE or TWO plain sentences: the fact, the figure(s) from the JSON, the source or model",
)


@pytest.mark.parametrize("tier", ("write", "deep", "fast"))
@pytest.mark.parametrize("lang", ("fr", "en"))
@pytest.mark.parametrize("reasoning", _REASONING_LEAKS)
def test_reasoning_leak_is_a_labelled_nim_fallback(monkeypatch, tier, lang, reasoning):
    """Content vide : ces fuites (FR et EN) partent en repli NIM, jamais en Nemotron."""
    import llm_budget

    if reasoning.startswith("UNE ou DEUX"):
        system, _user = build_prompt({"event": "swell", "lang": "fr", "needPage": False})
        assert reasoning in system
    if reasoning.startswith("ONE or TWO"):
        system, _user = build_prompt({"event": "swell", "lang": "en", "needPage": False})
        assert reasoning in system

    nim_text = "The quay stays calm." if lang == "en" else "Le quai reste calme."
    handler, seen = _nim_after_empty_reasoning(
        monkeypatch, reasoning, lang=lang, nim_text=nim_text,
    )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await cascade_text(
                "sys",
                f"user-{tier}-{lang}",
                client,
                tier=tier,
                lang=lang,
                fallback="Phrase locale.",
                facts=None,
            )

    result = asyncio.run(run())
    text, source = result
    assert source.startswith("nvidia-"), (tier, lang, reasoning)
    assert "nemotron" not in source.lower(), (tier, lang, reasoning)
    assert result.model == "openai/gpt-oss-20b", (tier, lang, reasoning)
    assert result.tier == tier
    assert nim_text in text, (tier, lang, reasoning)
    assert reasoning not in text, (tier, lang, reasoning)
    assert llm_budget.last_source_by_tier().get(tier) == "nim"
    usage = llm_budget.get_usage(tier)
    assert usage["calls"] == 1
    assert usage["prompt_tokens"] == 8
    assert usage["completion_tokens"] == 40
    if tier == "fast":
        retry = llm_budget.get_usage("write")
        assert retry["calls"] == 1
        assert retry["completion_tokens"] == 40
    err = llm_budget.last_error()
    assert err["provider"] == "tokenfactory"
    assert err["reason"].startswith("tokenfactory empty")
    tf = [url for url, _model in seen if "tokenfactory" in url]
    assert any(_url_host_is(url, "nvidia.com") for url, _model in seen)
    if tier == "fast":
        assert len(tf) == 2
        assert all(_eu_tf_host_is(url) for url in tf)
    elif tier == "deep":
        assert len(tf) == 1 and _eu_tf_host_is(tf[0])
    else:
        assert len(tf) == 1 and _eu_tf_host_is(tf[0])


def test_lightning_reasoning_content_finish_length_stays_lightning(monkeypatch):
    """reasoning_content + finish=length : Lightning, pas un second essai Super ni un repli."""
    import llm_budget

    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        url = str(request.url)
        seen.append((url, body.get("model")))
        if (
            _url_host_is(url, "nvidia.com")
            or _url_host_is(url, "openrouter.ai")
            or _url_host_is(url, "anthropic.com")
        ):
            return httpx.Response(200, json=_chat_ok("Repli inutile.", model="openai/gpt-oss-20b"))
        data = _empty_reasoning(
            body,
            "Analyze User Input: Task: Translate.\nLe quai de La Rochelle est calme.",
        )
        data["choices"][0]["message"] = {
            "content": "",
            "reasoning_content": data["choices"][0]["message"]["reasoning"],
        }
        data["choices"][0]["finish_reason"] = "length"
        return httpx.Response(200, json=data)

    monkeypatch.setenv("NEBIUS_API_KEY", "tf-test")
    monkeypatch.setenv("NVIDIA_API_KEY", "nim-test")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x")
    monkeypatch.setenv("NAVIGUIDE_LLM_CACHE_TTL_S", "0")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await cascade_text(
                "sys", "user-rc", client, tier="fast", fallback="Phrase locale.", facts=None,
            )

    result = asyncio.run(run())
    text, source = result
    assert source == "nemotron-lightning"
    assert text == "Le quai de La Rochelle est calme."
    assert result.model == "nvidia/Nemotron-3_5-Lightning"
    assert result.tier == "fast"
    assert len(seen) == 1
    assert "Lightning" in seen[0][1]
    assert _eu_tf_host_is(seen[0][0])
    st = llm_budget.status()
    assert st["retrySuper"] == 0
    assert st["fallback"] == {"nim": 0, "openrouter": 0, "claude": 0}
    assert "lastError" not in st
    assert st["lastSourceByTier"]["fast"] == "nemotron-lightning"
    assert st["fast"]["calls"] == 1


def test_write_deep_judge_call_planned_token_factory_models(monkeypatch):
    """Rédaction, approfondissement et juge appellent Super 120B ou Ultra 550B, sans repli."""
    import llm_budget

    cases = (
        ("write", "nvidia/Nemotron-3.5-Super-VL", "nemotron-super-vl", False, "Le bateau entre dans la ZEE."),
        ("deep", "nvidia/Nemotron-3-Ultra-550b-a55b", "nemotron-ultra", True, "L'escale de La Rochelle est calme."),
        ("judge", "nvidia/Nemotron-3-Ultra-550b-a55b", "nemotron-ultra", True, "Le récit tient les faits du journal."),
    )
    monkeypatch.setenv("NEBIUS_API_KEY", "tf-test")
    monkeypatch.setenv("NVIDIA_API_KEY", "nim-test")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x")
    monkeypatch.setenv("NAVIGUIDE_LLM_CACHE_TTL_S", "0")

    for tier, model, source, ultra_host, sentence in cases:
        seen = []

        def handler(request: httpx.Request, _seen=seen, _sentence=sentence) -> httpx.Response:
            body = json.loads(request.content.decode())
            url = str(request.url)
            _seen.append((url, body.get("model"), body.get("max_tokens")))
            if "tokenfactory" not in url:
                return httpx.Response(200, json=_chat_ok("Repli inutile.", model="openai/gpt-4o-mini"))
            return httpx.Response(200, json=_chat_ok(_sentence, model=body.get("model")))

        async def run(tier=tier):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                return await cascade_text(
                    "sys", f"user-plan-{tier}", client, tier=tier, fallback="Phrase locale.", facts=None,
                )

        result = asyncio.run(run())
        text, got = result
        assert got == source, tier
        assert sentence in text, tier
        assert result.model == model, tier
        assert result.tier == tier
        assert len(seen) == 1, tier
        url, asked, max_tokens = seen[0]
        assert asked == model, tier
        assert _eu_tf_host_is(url), tier
        assert max_tokens == llm_budget.max_tokens_for(tier), tier
        st = llm_budget.status()
        assert st["lastSourceByTier"][tier] == source, tier
        assert st["fallback"] == {"nim": 0, "openrouter": 0, "claude": 0}, tier
        assert "lastError" not in st, tier


def test_write_story_calls_super_and_stop_calls_ultra(monkeypatch):
    """write_story : Super pour le récit, Ultra 550B pour une escale."""
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        seen.append((str(request.url), body.get("model")))
        return httpx.Response(200, json=_chat_ok("La Rochelle est un port calme.", model=body.get("model")))

    monkeypatch.setenv("NEBIUS_API_KEY", "tf-test")
    monkeypatch.setenv("NAVIGUIDE_LLM_CACHE_TTL_S", "0")
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            written = await write_story({
                "event": "zee-enter", "eventId": "zee-plan-write", "lang": "fr", "needPage": False,
            }, client=client)
            stopped = await write_story({
                "event": "stop", "eventId": "stop-plan-deep", "lang": "fr", "needPage": False,
            }, client=client)
            return written, stopped

    written, stopped = asyncio.run(run())
    assert written["status"] == "ready"
    assert written["source"] == "nemotron-super-vl"
    assert written["tier"] == "write"
    assert written["model"] == "nvidia/Nemotron-3.5-Super-VL"
    assert stopped["status"] == "ready"
    assert stopped["source"] == "nemotron-ultra"
    assert stopped["tier"] == "deep"
    assert stopped["model"] == "nvidia/Nemotron-3-Ultra-550b-a55b"
    assert len(seen) == 2
    assert seen[0][1] == "nvidia/Nemotron-3.5-Super-VL"
    assert _eu_tf_host_is(seen[0][0])
    assert seen[1][1] == "nvidia/Nemotron-3-Ultra-550b-a55b"
    assert _eu_tf_host_is(seen[1][0])


NANO_ID = "nvidia/Nemotron-3_5-Lightning"
LIGHTNING_ID = "nvidia/Nemotron-3_5-Lightning"
SUPER_VL_ID = "nvidia/Nemotron-3.5-Super-VL"


def test_nano_call_stays_on_eu_host(monkeypatch):
    """Nano parle à la base EU, avec l'id catalogue exact."""
    import story_cascade

    monkeypatch.setenv("NAVIGUIDE_TF_BASE_EU", "https://api.tokenfactory.nebius.com/v1")
    url = story_cascade._tf_url("nano")
    assert _url_host_is(url, "api.tokenfactory.nebius.com")
    assert _eu_tf_host_is(url)
    assert url.endswith("/chat/completions")
    assert _eu_tf_host_is(story_cascade._tf_url("deep"))

    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        seen.append((str(request.url), body.get("model")))
        return httpx.Response(200, json=_chat_ok("Le quai reste calme.", model=body.get("model")))

    monkeypatch.setenv("NEBIUS_API_KEY", "tf-test")
    monkeypatch.setenv("NAVIGUIDE_LLM_CACHE_TTL_S", "0")
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await cascade_text(
                "sys", "user-nano", client, tier="nano", fallback="Phrase locale.", facts="user-nano",
            )

    result = asyncio.run(run())
    text, source = result
    assert text == "Le quai reste calme."
    assert source == "nemotron-lightning"
    assert result.model == NANO_ID
    assert result.tier == "nano"
    assert len(seen) == 1
    assert seen[0][1] == NANO_ID
    assert _url_host_is(seen[0][0], "api.tokenfactory.nebius.com")
    assert not _url_host_is(seen[0][0], "api.tokenfactory.us-central1.nebius.com")


def test_nano_falls_back_to_lightning_with_its_label(monkeypatch):
    """Palier nano (Lightning id) en échec → repli fast Lightning, étiquette nemotron-lightning."""
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        url = str(request.url)
        model = body.get("model")
        seen.append((url, model))
        if len(seen) == 1:
            return httpx.Response(500, text='{"error":"nano down"}')
        if model == LIGHTNING_ID:
            return httpx.Response(200, json=_chat_ok("Le quai reste calme.", model=model))
        return httpx.Response(500, text="unexpected")

    monkeypatch.setenv("NAVIGUIDE_TF_BASE_EU", "https://api.tokenfactory.nebius.com/v1")
    monkeypatch.setenv("NEBIUS_API_KEY", "tf-test")
    monkeypatch.setenv("NVIDIA_API_KEY", "nim-test")
    monkeypatch.setenv("NAVIGUIDE_LLM_CACHE_TTL_S", "0")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await cascade_text(
                "sys", "user-nano-fb", client, tier="nano", fallback="Phrase locale.", facts="user-nano-fb",
            )

    result = asyncio.run(run())
    text, source = result
    assert "quai" in text
    assert source == "nemotron-lightning"
    assert result.model == LIGHTNING_ID
    assert [m for _u, m in seen] == [LIGHTNING_ID, LIGHTNING_ID]
    assert all(not _url_host_is(url, "api.tokenfactory.us-central1.nebius.com") for url, _m in seen)
    assert all(_url_host_is(url, "api.tokenfactory.nebius.com") for url, _m in seen)
    import llm_budget
    assert llm_budget.status()["lastSourceByTier"]["nano"] == "nemotron-lightning"


def test_nano_then_lightning_then_nim_keeps_nim_label(monkeypatch):
    """Nano et Lightning muets → NIM, source étiquetée nvidia- (pas Nano)."""
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        body = json.loads(request.content.decode()) if request.content else {}
        seen.append((url, body.get("model")))
        if "tokenfactory" in url:
            return httpx.Response(502, text='{"error":"down"}')
        if _url_host_is(url, "integrate.api.nvidia.com"):
            return httpx.Response(200, json=_chat_ok("The quay stays calm.", model="openai/gpt-oss-20b"))
        return httpx.Response(500, text="no")

    monkeypatch.setenv("NAVIGUIDE_TF_BASE_EU", "https://api.tokenfactory.nebius.com/v1")
    monkeypatch.setenv("NEBIUS_API_KEY", "tf-test")
    monkeypatch.setenv("NVIDIA_API_KEY", "nim-test")
    monkeypatch.setenv("NAVIGUIDE_LLM_CACHE_TTL_S", "0")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await cascade_text(
                "sys", "user-nano-nim", client, tier="nano", fallback="Phrase locale.", facts="user-nano-nim",
            )

    text, source = asyncio.run(run())
    assert "quay" in text
    assert source.startswith("nvidia-")
    assert source != "nemotron-nano"
    assert source != "nemotron-lightning"
    models = [m for url, m in seen if "tokenfactory" in url]
    assert models == [LIGHTNING_ID, LIGHTNING_ID]
    assert any(_url_host_is(url, "integrate.api.nvidia.com") for url, _m in seen)
    assert not any("openrouter" in url or "anthropic" in url for url, _m in seen)
    import llm_budget
    assert llm_budget.status()["lastSourceByTier"]["nano"] == "nim"


def test_timeout_tf_nim_called_openrouter_claude_skipped(monkeypatch):
    """R36: GPT-OSS via NIM n'est pas un modèle Nemotron et est sauté après timeout.

    Sans opt-in, après timeout TF la cascade ne peut pas traiter NIM comme
    Nemotron : elle retourne la phrase locale sans appeler NIM, OpenRouter ou Claude.
    """
    import llm_budget
    
    seen = []
    tf_timeout_count = 0
    nim_called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal tf_timeout_count, nim_called
        url = str(request.url)
        body = json.loads(request.content.decode()) if request.content else {}
        seen.append((url, body.get("model")))
        if "tokenfactory" in url:
            tf_timeout_count += 1
            # Simule un timeout TF
            raise TokenFactoryTimeout("tokenfactory timeout after 25 s")
        if _url_host_is(url, "integrate.api.nvidia.com"):
            nim_called = True
            return httpx.Response(200, json=_chat_ok("Le port reste calme.", model="openai/gpt-oss-20b"))
        if "openrouter" in url or "anthropic" in url:
            # Ne doit pas être appelé
            return httpx.Response(500, json={"error": "not expected"})
        return httpx.Response(500, json={"error": "no"})

    monkeypatch.setenv("NAVIGUIDE_TF_BASE_EU", "https://api.tokenfactory.nebius.com/v1")
    monkeypatch.setenv("NEBIUS_API_KEY", "tf-test")
    monkeypatch.setenv("NVIDIA_API_KEY", "nim-test")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ant-test")
    monkeypatch.setenv("NAVIGUIDE_LLM_CACHE_TTL_S", "0")
    monkeypatch.setenv("NAVIGUIDE_LLM_TIMEOUT_FALLBACK", "0")  # Désactive le fallback hors Nemotron

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await cascade_text(
                "sys", "user-timeout-test", client, tier="write", fallback="Phrase locale.", facts=None,
            )

    result = asyncio.run(run())
    text, source = result
    
    assert text == "Phrase locale."
    assert source == "rules"
    assert not nim_called, "NIM GPT-OSS n'est pas un repli Nemotron"
    assert tf_timeout_count == 1, f"Expected 1 TF call, got {tf_timeout_count}"
    
    # OpenRouter et Claude ne doivent PAS être appelés
    openrouter_called = any("openrouter" in url for url, _ in seen)
    claude_called = any("anthropic" in url for url, _ in seen)
    assert not openrouter_called, "OpenRouter ne doit pas être appelé après timeout TF"
    assert not claude_called, "Claude ne doit pas être appelé après timeout TF"
    
    errors = llm_budget.last_errors()
    assert any(e.get("provider") == "tokenfactory" for e in errors)
    assert llm_budget.fallback_usage().get("nim", 0) == 0
