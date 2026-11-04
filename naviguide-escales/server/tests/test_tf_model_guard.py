"""Garde de disponibilité des modèles TF (C1-b) et latence par palier (C1-a)."""
import asyncio
import json
import time

import httpx
import pytest

import llm_budget
import story_cascade
import tf_catalog
from story_cascade import cascade_text

EU = "https://api.tokenfactory.nebius.com/v1"
US = "https://api.tokenfactory.us-central1.nebius.com/v1"

# Catalogues relevés en réel le 29/10/2026 (ids Nemotron seulement + un autre).
EU_IDS = [
    "moonshotai/Kimi-K3",
    "nvidia/Nemotron-3_5-Lightning",
    "nvidia/Nemotron-3-Ultra-550b-a55b",
    "nvidia/Nemotron-3.5-Super-VL",
]
US_IDS = [
    "Qwen/Qwen3.8-27B",
    "nvidia/Nemotron-3-Ultra-550b-a55b",
    "nvidia/Nemotron-3_5-Lightning",
]


def test_ultra_and_write_default_to_eu_token_factory(monkeypatch):
    monkeypatch.delenv("NAVIGUIDE_TF_BASE_ULTRA", raising=False)
    monkeypatch.delenv("NAVIGUIDE_TF_BASE_EU", raising=False)
    assert story_cascade._tf_url("deep") == f"{EU}/chat/completions"
    assert story_cascade._tf_url("judge") == f"{EU}/chat/completions"
    assert story_cascade._tf_url("write") == f"{EU}/chat/completions"


def _catalog(ids):
    return {"object": "list", "data": [{"id": i, "object": "model"} for i in ids]}


def _chat_ok(text, model):
    return {
        "choices": [{"message": {"content": text}}],
        "model": model,
        "usage": {"prompt_tokens": 12, "completion_tokens": 8},
    }


@pytest.fixture(autouse=True)
def _guard_on(monkeypatch):
    monkeypatch.setenv("NAVIGUIDE_TF_MODEL_GUARD", "1")
    monkeypatch.setenv("NEBIUS_API_KEY", "tf-test")
    monkeypatch.setenv("NAVIGUIDE_LLM_PROVIDERS", "tokenfactory")
    story_cascade.reset_runtime()
    tf_catalog.reset()
    yield
    story_cascade.reset_runtime()
    tf_catalog.reset()


def _handler(seen, catalogs, *, models_status=200):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        seen.append((request.method, url))
        if request.method == "GET" and url.endswith("/models"):
            base = url[: -len("/models")]
            if models_status != 200:
                return httpx.Response(models_status, json={"error": "x"})
            return httpx.Response(200, json=_catalog(catalogs.get(base, [])))
        body = json.loads(request.read().decode())
        return httpx.Response(200, json=_chat_ok("Récit court de la ZEE.", body["model"]))
    return handler


def _run(handler, *, tier="write", user="La ZEE.", fallback="Phrase locale."):
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await cascade_text("sys", user, client, tier=tier, fallback=fallback, facts={})
    return asyncio.run(go())


def _gets(seen):
    return [u for m, u in seen if m == "GET"]


def test_all_present_keeps_tier_and_reads_catalog_once():
    seen = []
    h = _handler(seen, {EU: EU_IDS, US: US_IDS})
    r1 = _run(h, user="Première ZEE.")
    r2 = _run(h, user="Deuxième ZEE.")
    assert r1[1] == "nemotron-super-vl" and r2[1] == "nemotron-super-vl"
    assert r1.model == "nvidia/Nemotron-3.5-Super-VL"
    assert _gets(seen) == [f"{EU}/models"], "catalogue en cache : un seul GET"
    st = llm_budget.status()["modelGuard"]
    assert st["enabled"] is True
    assert st["missing"] == {}
    assert st["catalogs"][EU]["ok"] is True and st["catalogs"][EU]["models"] == len(EU_IDS)


def test_write_pinned_to_eu_host(monkeypatch):
    """O4: write (Super-VL) est épinglé sur l'hôte UE, comme nano.
    Même si TOKENFACTORY_URL pointe vers US, write utilise l'hôte UE."""
    monkeypatch.setattr(story_cascade, "TOKENFACTORY_URL", f"{US}/chat/completions")
    seen = []
    h = _handler(seen, {EU: EU_IDS, US: US_IDS})
    res = _run(h, tier="write")
    text, source = res
    # write reste sur l'hôte UE et sert Super-VL (pas de repli silencieux)
    assert source == "nemotron-super-vl", "write épinglé UE"
    assert res.model == "nvidia/Nemotron-3.5-Super-VL"
    assert res.tier == "write"
    posts = [u for m, u in seen if m == "POST"]
    assert len(posts) == 1 and posts[0] == f"{EU}/chat/completions"
    missing = llm_budget.status()["modelGuard"]["missing"]
    assert missing == {}


def test_ultra_missing_falls_to_super_vl_on_eu_host():
    """Ultra absent de l'hôte EU → repli sur Super-VL sur le même hôte EU."""
    seen = []
    eu_without_ultra = [i for i in EU_IDS if "Ultra" not in i]
    h = _handler(seen, {EU: eu_without_ultra})
    res = _run(h, tier="deep")
    assert res[1] == "nemotron-super-vl"
    assert res.model == "nvidia/Nemotron-3.5-Super-VL"
    assert llm_budget.status()["modelGuard"]["missing"]["deep"]["substituteTier"] == "write"


def test_no_substitute_goes_to_rules_and_is_counted():
    seen = []
    h = _handler(seen, {EU: ["moonshotai/Kimi-K3"], US: ["Qwen/Qwen3.8-27B"]})
    text, source = _run(h, tier="write")
    assert source == "rules"
    assert [m for m, _ in seen if m == "POST"] == [], "aucun appel payant vers un id absent"
    row = llm_budget.status()["modelGuard"]["missing"]["write"]
    assert row["substitute"] is None and row["count"] == 1
    errs = llm_budget.last_errors() or []
    assert any("missing from catalog" in e["reason"] for e in errs)


def test_unreadable_catalog_fails_open_and_backs_off():
    seen = []
    h = _handler(seen, {}, models_status=500)
    r1 = _run(h, user="Une ZEE.")
    r2 = _run(h, user="Deux ZEE.")
    assert r1[1] == "nemotron-super-vl" and r2[1] == "nemotron-super-vl"
    assert len(_gets(seen)) == 1, "échec mis en cache : pas de nouvel essai avant 10 min"
    cat = llm_budget.status()["modelGuard"]["catalogs"][EU]
    assert cat["ok"] is False and cat["reason"] == "HTTP 500"


def test_guard_off_sends_no_get(monkeypatch):
    monkeypatch.setenv("NAVIGUIDE_TF_MODEL_GUARD", "0")
    seen = []
    res = _run(_handler(seen, {EU: []}))
    assert res[1] == "nemotron-super-vl"
    assert _gets(seen) == []
    assert llm_budget.status()["modelGuard"]["enabled"] is False


def test_catalog_expires_after_ttl(monkeypatch):
    seen = []
    h = _handler(seen, {EU: EU_IDS})
    _run(h, user="Une ZEE.")
    real = time.time
    monkeypatch.setattr(tf_catalog.time, "time", lambda: real() + 6 * 3600 + 5)
    _run(h, user="Deux ZEE.")
    assert len(_gets(seen)) == 2


def test_budget_mode_off_never_reads_catalog(monkeypatch):
    monkeypatch.setenv("NAVIGUIDE_LLM_MODE", "off")
    seen = []
    text, source = _run(_handler(seen, {EU: EU_IDS}))
    assert source == "budget"
    assert seen == []


def test_parse_catalog_shapes():
    assert tf_catalog.parse_catalog(_catalog(["a/b"])) == ["a/b"]
    assert tf_catalog.parse_catalog({"choices": []}) is None
    assert tf_catalog.parse_catalog({"data": []}) == []
    assert tf_catalog.parse_catalog(None) is None
    assert tf_catalog.parse_catalog({"data": [{"object": "model"}]}) is None


def test_has_model_is_case_insensitive_and_unknown_is_none():
    assert tf_catalog.has_model(EU, "nvidia/Nemotron-3.5-Super-VL") is None
    tf_catalog._put(EU, {"ok": True, "ids": EU_IDS, "ts": time.time()})
    assert tf_catalog.has_model(EU, "NVIDIA/nemotron-3.5-super-vl") is True
    assert tf_catalog.has_model(EU, "nvidia/nemotron-3-super-120b-a12b") is False


def test_substitutes_stay_on_token_factory_tiers():
    for tier, alts in story_cascade.GUARD_SUBSTITUTES.items():
        assert tier in llm_budget.TIERS
        assert alts and all(a in llm_budget.TIERS and a != tier for a in alts)


# --- C1-a : latence par palier ------------------------------------------------

def test_latency_recorded_per_called_tier():
    seen = []
    h = _handler(seen, {EU: EU_IDS})
    _run(h, user="Une ZEE.")
    lat = llm_budget.status()["latency"]
    assert set(lat) == {"write"}
    assert lat["write"]["calls"] == 1
    assert lat["write"]["lastMs"] >= 0 and lat["write"]["medianMs"] == lat["write"]["lastMs"]


def test_latency_median_and_window():
    for ms in (900, 100, 500):
        llm_budget.record_latency("fast", ms)
    st = llm_budget.latency_status()["fast"]
    assert st == {"lastMs": 500, "medianMs": 500, "calls": 3, "samples": 3}
    llm_budget.record_latency("fast", 300)
    assert llm_budget.latency_status()["fast"]["medianMs"] == 400
    for _ in range(llm_budget.LATENCY_SAMPLES + 10):
        llm_budget.record_latency("judge", 7)
    st = llm_budget.latency_status()["judge"]
    assert st["calls"] == llm_budget.LATENCY_SAMPLES + 10
    assert st["samples"] == llm_budget.LATENCY_SAMPLES
    assert len(llm_budget._latency_raw()["judge"]["samples"]) == llm_budget.LATENCY_SAMPLES


def test_latency_ignores_failed_http(monkeypatch):
    def handler(request):
        return httpx.Response(529, json={"error": "overloaded"})
    monkeypatch.setenv("NAVIGUIDE_TF_MODEL_GUARD", "0")
    _run(handler, tier="write")
    assert llm_budget.status()["latency"]["write"]["httpErrors"]["last"]["status"] == 529
    assert llm_budget.status()["latency"]["write"]["samples"] == 0


def test_status_has_no_prompt_and_no_key():
    seen = []
    _run(_handler(seen, {EU: EU_IDS}), user="Question secrète ZEE.")
    blob = json.dumps(llm_budget.status())
    assert "secrète" not in blob and "tf-test" not in blob


# --- tf_timeout and timeout handling ------------------------------------------

def test_tf_timeout_defaults_and_env(monkeypatch):
    # defaults
    assert story_cascade.tf_timeout("fast").read == 25.0
    assert story_cascade.tf_timeout("judge").read == 45.0
    # env override for non-deep/judge
    monkeypatch.setenv("NAVIGUIDE_TF_TIMEOUT_S", "3")
    assert story_cascade.tf_timeout("fast").read == 3.0
    assert story_cascade.tf_timeout("write").read == 3.0
    # invalid value -> default
    monkeypatch.setenv("NAVIGUIDE_TF_TIMEOUT_S", "0")
    assert story_cascade.tf_timeout("fast").read == 25.0
    monkeypatch.setenv("NAVIGUIDE_TF_TIMEOUT_S", "-5")
    assert story_cascade.tf_timeout("fast").read == 25.0
    monkeypatch.setenv("NAVIGUIDE_TF_TIMEOUT_S", "abc")
    assert story_cascade.tf_timeout("fast").read == 25.0
    monkeypatch.setenv("NAVIGUIDE_TF_TIMEOUT_S", "inf")
    assert story_cascade.tf_timeout("fast").read == 25.0


def test_catalog_empty_is_valid_and_has_no_models():
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"data": []}))) as client:
            return await tf_catalog.refresh(EU, "key", client)
    entry = asyncio.run(go())
    assert entry["ok"] is True and entry["ids"] == []
    assert tf_catalog.has_model(EU, "x") is False


def test_ensure_fresh_handles_cache_read_failure(monkeypatch):
    monkeypatch.setattr(tf_catalog, "_get", lambda _base: (_ for _ in ()).throw(RuntimeError("store down")))
    async def go():
        async with httpx.AsyncClient() as client:
            return await tf_catalog.ensure_fresh(EU, "key", client)
    assert asyncio.run(go()) is None


def test_model_missing_last_event_clears_substitute():
    llm_budget.record_model_missing("write", "model-a", "fast", "model-b")
    row = llm_budget.record_model_missing("write", "model-a")
    assert row["substitute"] is None and row["substituteTier"] is None
    assert row["count"] == 2


def test_nano_missing_models_does_not_post_tokenfactory(monkeypatch):
    seen = []
    monkeypatch.setenv("NVIDIA_API_KEY", "nv-test")
    monkeypatch.setenv("NAVIGUIDE_LLM_PROVIDERS", "tokenfactory,nim")
    def handler(request):
        seen.append((request.method, str(request.url)))
        if request.method == "GET":
            return httpx.Response(200, json={"data": []})
        if "tokenfactory" in str(request.url):
            pytest.fail("inadmissible Token Factory model was posted")
        return httpx.Response(200, json={"choices": [{"message": {"content": "NIM answer"}}], "model": "openai/gpt-oss-20b"})
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await cascade_text("sys", "nano missing test", client, tier="nano", fallback="rules", facts={})
    result = asyncio.run(go())
    assert result[1].startswith("nvidia-")
    assert not any(m == "POST" and "tokenfactory" in u for m, u in seen)


def test_explicit_model_not_found_invalidates_catalog():
    tf_catalog._put(EU, {"ok": True, "ids": ["stale/model"], "ts": time.time()})
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _req: httpx.Response(404, json={"error": "model not found"}))) as client:
            with pytest.raises(RuntimeError, match="HTTP 404"):
                await story_cascade._call_tokenfactory("sys", "user", "write", client)
    asyncio.run(go())
    assert tf_catalog.has_model(EU, "stale/model") is None


@pytest.mark.parametrize("status,error", [(422, {"code": "model_not_found", "param": "model"}), (400, {"message": "unknown model_id: stale/model"})])
def test_model_rejection_invalidates_then_next_call_rereads(monkeypatch, status, error):
    gets = []
    posts = 0
    def handler(req):
        nonlocal posts
        if req.method == "GET":
            gets.append(1)
            return httpx.Response(200, json=_catalog([llm_budget.model_for("write")]))
        posts += 1
        if posts == 1:
            return httpx.Response(status, json={"error": error})
        return httpx.Response(200, json=_chat_ok("ok", "stale/model"))
    monkeypatch.setenv("NAVIGUIDE_LLM_CACHE_TTL_S", "0")
    async def call():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await story_cascade._guarded_tier("write", client)
            try:
                await story_cascade._call_tokenfactory("sys", "user", "write", client)
            except RuntimeError:
                pass
            await story_cascade._guarded_tier("write", client)
            await story_cascade._call_tokenfactory("sys", "user", "write", client)
    asyncio.run(call())
    assert len(gets) == 2


def test_tf_call_never_without_timeout(monkeypatch):
    """httpx 0.28 : `timeout=None` coupe tout délai ; chaque POST TF en porte un."""
    captured = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/chat/completions"):
            captured.append(request.extensions.get("timeout") or {})
        body = json.loads(request.read().decode())
        return httpx.Response(200, json=_chat_ok("Récit court de la ZEE.", body["model"]))

    monkeypatch.setenv("NAVIGUIDE_TF_MODEL_GUARD", "0")
    _run(handler, tier="write", user="Une ZEE pour write.")
    _run(handler, tier="fast", user="Une ZEE pour fast.")
    _run(handler, tier="judge", user="Une ZEE pour judge.")
    assert all(0 < c.get("read", 0) <= expected for c, expected in zip(captured, [25.0, 25.0, 45.0]))
    assert all(c.get("connect") == 8.0 for c in captured)


def test_timeout_falls_back_to_rules_and_is_counted(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            raise httpx.ReadTimeout("slow", request=request)
        return httpx.Response(404)

    monkeypatch.setenv("NAVIGUIDE_TF_MODEL_GUARD", "0")
    text, source = _run(handler, tier="write")
    assert source == "rules"
    assert text == "Phrase locale."
    st = llm_budget.latency_status()["write"]
    assert st["timeouts"] == 1 and "medianMs" not in st
    assert "timeout" in json.dumps(llm_budget.status()).lower()


def test_full_limiter_queue_times_out_instead_of_waiting(monkeypatch):
    """Limiteur plein (appels lents en cours) : on n'attend pas sans fin."""
    monkeypatch.setenv("NAVIGUIDE_TF_MODEL_GUARD", "0")
    monkeypatch.setenv("NAVIGUIDE_TF_PARALLEL", "1")
    monkeypatch.setenv("NAVIGUIDE_TF_TIMEOUT_S", "0.2")
    story_cascade.reset_runtime()
    seen = []

    async def go():
        sema = story_cascade._tf_limiter()
        await sema.acquire()  # un appel lent occupe la seule place
        try:
            async with httpx.AsyncClient(transport=httpx.MockTransport(_handler(seen, {}))) as client:
                started = time.monotonic()
                res = await cascade_text("sys", "La ZEE.", client, tier="fast", fallback="Phrase locale.", facts={})
                return res, time.monotonic() - started
        finally:
            sema.release()

    (text, source), waited = asyncio.run(go())
    assert source == "rules" and text == "Phrase locale."
    assert waited < 5
    assert not [m for m, _ in seen if m == "POST"]
    assert llm_budget.latency_status()["fast"]["timeouts"] >= 1
