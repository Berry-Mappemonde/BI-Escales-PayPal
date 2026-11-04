"""Non-régression garde de latence TF (contre-revue PR #153, P1-1, P1-2, P2).

R1 : un timeout Lightning relance Super VL (LT1).
R2 : providers par défaut + timeout TF → repli NIM par défaut.
R3 : le délai TF est une échéance totale, pas un délai entre deux lectures.
R4 : nano, file pleine → pas de second passage dans la même file.
R5 : un timeout HTTP est compté au budget du jour (estimation prudente).
"""
import asyncio, json, time
import httpx, pytest
import llm_budget, story_cascade
from story_cascade import cascade_text


def _ok(model):
    return {"choices": [{"message": {"content": "Récit court de la ZEE."}}], "model": model,
            "usage": {"prompt_tokens": 12, "completion_tokens": 8}}


def _run(handler, **kw):
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await cascade_text("sys", kw.pop("user", "La ZEE."), c, fallback="Phrase locale.", facts={}, **kw)
    return asyncio.run(go())


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("NEBIUS_API_KEY", "tf-test")
    monkeypatch.setenv("NAVIGUIDE_TF_MODEL_GUARD", "0")
    story_cascade.reset_runtime()
    yield
    story_cascade.reset_runtime()


def test_R1_fast_timeout_still_retries_super(monkeypatch):
    """LT1 : un timeout Lightning (fast) doit relancer Super VL (write)."""
    monkeypatch.setenv("NAVIGUIDE_LLM_PROVIDERS", "tokenfactory")
    seen = []
    def h(req):
        body = json.loads(req.read().decode())
        seen.append(body["model"])
        if "Lightning" in body["model"]:
            raise httpx.ReadTimeout("slow", request=req)
        return httpx.Response(200, json=_ok(body["model"]))
    text, source = _run(h, tier="fast")
    assert source == "nemotron-super-vl", f"LT1 perdu : source={source}, appels={seen}"
    assert len(seen) == 2 and "Lightning" in seen[0] and "Super" in seen[1], seen
    assert llm_budget.status()["retrySuper"] == 1


def test_R1b_queue_timeout_does_not_retry_super(monkeypatch):
    """Un timeout de file n'est pas relancé sur Super (même file partagée)."""
    exc = story_cascade.TokenFactoryTimeout("tokenfactory queue timeout", queue=True)
    assert story_cascade._tf_fast_super_retry(exc) is False
    assert story_cascade._tf_fast_super_retry(
        story_cascade.TokenFactoryTimeout("tokenfactory timeout after 25 s")) is True


@pytest.mark.parametrize("failure", ["5xx", "timeout"])
def test_R1c_selected_write_is_not_retried_as_super(monkeypatch, failure):
    """Fast routed to write must not issue the LT1 write call a second time."""
    monkeypatch.setenv("NAVIGUIDE_LLM_PROVIDERS", "tokenfactory")
    async def selected_write(_tier, _client):
        return "write"
    monkeypatch.setattr(story_cascade, "_guarded_tier", selected_write)
    seen = []
    def h(req):
        seen.append(json.loads(req.read().decode())["model"])
        if failure == "timeout":
            raise httpx.ReadTimeout("slow", request=req)
        return httpx.Response(503, json={"error": "busy"})
    _run(h, tier="fast")
    assert seen == [llm_budget.model_for("write")]


def _r2_handler(seen):
    def h(req):
        seen.append(str(req.url))
        if "tokenfactory" in str(req.url):
            raise httpx.ReadTimeout("slow", request=req)
        body = json.loads(req.read().decode())
        return httpx.Response(200, json=_ok(body["model"]))
    return h


def test_R2_timeout_default_providers_falls_back_to_nim(monkeypatch):
    """Providers par défaut : un timeout TF appelle NIM et retourne son résultat."""
    monkeypatch.delenv("NAVIGUIDE_LLM_PROVIDERS", raising=False)
    monkeypatch.delenv("NAVIGUIDE_LLM_TIMEOUT_FALLBACK", raising=False)
    monkeypatch.setenv("NVIDIA_API_KEY", "nv-test")
    seen = []
    res = _run(_r2_handler(seen), tier="write")
    assert res[1].startswith("nvidia-") and "gpt-oss" in res.model
    assert any("tokenfactory" in u for u in seen) and any("nvidia" in u for u in seen), seen


def test_R2b_timeout_fallback_explicit_opt_out(monkeypatch):
    """Opt-out explicite : aucun appel NIM après le timeout TF."""
    monkeypatch.delenv("NAVIGUIDE_LLM_PROVIDERS", raising=False)
    monkeypatch.setenv("NAVIGUIDE_LLM_TIMEOUT_FALLBACK", "0")
    monkeypatch.setenv("NVIDIA_API_KEY", "nv-test")
    seen = []
    res = _run(_r2_handler(seen), tier="write")
    assert res[1] == "rules"
    assert not any("nvidia" in u for u in seen), seen


def test_R2c_non_timeout_failure_keeps_default_cascade(monkeypatch):
    """Un 5xx TF (pas un timeout) garde la cascade par défaut, inchangée."""
    monkeypatch.delenv("NAVIGUIDE_LLM_PROVIDERS", raising=False)
    monkeypatch.delenv("NAVIGUIDE_LLM_TIMEOUT_FALLBACK", raising=False)
    monkeypatch.setenv("NVIDIA_API_KEY", "nv-test")
    def h(req):
        if "tokenfactory" in str(req.url):
            return httpx.Response(503, json={"error": "busy"})
        body = json.loads(req.read().decode())
        return httpx.Response(200, json=_ok(body["model"]))
    res = _run(h, tier="write")
    assert res[1].startswith("nvidia-")


def test_queue_timeout_covers_ten_concurrent_tokenfactory_calls(monkeypatch):
    """A judge-sized burst waits for TF capacity instead of silently using NIM."""
    monkeypatch.delenv("NAVIGUIDE_LLM_PROVIDERS", raising=False)
    monkeypatch.delenv("NAVIGUIDE_LLM_TIMEOUT_FALLBACK", raising=False)
    monkeypatch.setenv("NAVIGUIDE_TF_PARALLEL", "4")
    monkeypatch.setenv("NVIDIA_API_KEY", "nv-test")
    assert story_cascade.TF_QUEUE_TIMEOUT_S == 10.0
    seen = []

    class SlowMockTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            seen.append(str(request.url))
            await asyncio.sleep(0.04)
            body = json.loads(request.content.decode())
            return httpx.Response(200, json=_ok(body["model"]), request=request)

    async def go():
        async with httpx.AsyncClient(transport=SlowMockTransport()) as client:
            results = await asyncio.gather(*(
                cascade_text("sys", f"Judge request {i}.", client,
                             fallback="Phrase locale.", facts={})
                for i in range(10)
            ))
            # Exercise the actual queue expiry: a held slot times out at the
            # configured queue budget, without sending a Token Factory POST.
            sema = story_cascade._tf_limiter()
            for _ in range(4):
                await sema.acquire()
            deadline_token = story_cascade._TF_DEADLINE.set(time.monotonic() + 20)
            try:
                with pytest.raises(story_cascade.TokenFactoryTimeout) as exc:
                    await story_cascade._call_tokenfactory("sys", "queued", "write", client)
                assert exc.value.queue
            finally:
                story_cascade._TF_DEADLINE.reset(deadline_token)
                for _ in range(4):
                    sema.release()
            return results

    results = asyncio.run(go())
    assert all(source.startswith("nemotron-") for _, source in results), results
    assert len(seen) == 10 and all("tokenfactory" in url for url in seen), seen


def test_expired_queue_still_walks_mocked_provider_cascade(monkeypatch):
    """A queue timeout enters NIM, then OpenRouter, then Claude in order."""
    monkeypatch.delenv("NAVIGUIDE_LLM_PROVIDERS", raising=False)
    monkeypatch.delenv("NAVIGUIDE_LLM_TIMEOUT_FALLBACK", raising=False)
    monkeypatch.setenv("NVIDIA_API_KEY", "nv-test")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "cl-test")
    monkeypatch.setattr(story_cascade, "TF_QUEUE_TIMEOUT_S", 0.02)
    seen = []

    async def tokenfactory(*args, **kwargs):
        seen.append("tokenfactory")
        raise story_cascade.TokenFactoryTimeout("mock queue timeout", queue=True)

    async def nim(*args, **kwargs):
        seen.append("nim")
        raise RuntimeError("mock unavailable")

    async def openrouter(*args, **kwargs):
        seen.append("openrouter")
        raise RuntimeError("mock unavailable")

    async def claude(*args, **kwargs):
        seen.append("claude")
        return "Récit court de la ZEE.", "claude"

    monkeypatch.setattr(story_cascade, "_call_tokenfactory", tokenfactory)
    monkeypatch.setattr(story_cascade, "_call_nim", nim)
    monkeypatch.setattr(story_cascade, "_call_openrouter", openrouter)
    monkeypatch.setattr(story_cascade, "_call_claude", claude)
    result = _run(lambda request: httpx.Response(500, request=request))
    assert result[1] == "claude", result
    assert seen == ["tokenfactory", "nim", "openrouter", "claude"], seen


def test_P2_402_pauses_tokenfactory_and_resumes(monkeypatch):
    """Quota 402 serves via NIM; TF is skipped briefly and retried after expiry."""
    import offline
    monkeypatch.setattr(offline, "enabled", lambda: False)
    monkeypatch.setattr(llm_budget, "llm_allowed_here", lambda _tier=None: True)
    monkeypatch.setattr(llm_budget, "allow", lambda _tier: True)
    monkeypatch.setenv("NAVIGUIDE_LLM_PROVIDERS", "tokenfactory,nim,openrouter,claude")
    monkeypatch.setenv("NAVIGUIDE_TF_QUOTA_PAUSE_S", "0.15")
    monkeypatch.setenv("NVIDIA_API_KEY", "nv-test")
    monkeypatch.setattr(llm_budget, "_tf_quota_until", 0.0)
    calls = {"tf": 0, "nim": 0}

    def handler(req):
        if "tokenfactory" in str(req.url):
            calls["tf"] += 1
            if calls["tf"] == 1:
                return httpx.Response(402, json={"error": {"type": "insufficient_quota", "message": "quota"}})
            body = json.loads(req.read().decode())
            return httpx.Response(200, json=_ok(body["model"]))
        if "nvidia" in str(req.url):
            calls["nim"] += 1
            body = json.loads(req.read().decode())
            return httpx.Response(200, json=_ok(body["model"]))
        return httpx.Response(503, json={"error": "unexpected"})

    first = _run(handler, user="quota first", tier="write")
    assert first[1].startswith("nvidia-")
    assert calls == {"tf": 1, "nim": 1}
    assert llm_budget.status()["tfQuota"]["state"] == "exhausted"
    import ici_warm
    assert ici_warm.status()["tfQuota"]["state"] == "exhausted"

    second = _run(handler, user="quota paused", tier="write")
    assert second[1].startswith("nvidia-")
    assert calls == {"tf": 1, "nim": 2}

    time.sleep(0.2)
    third = _run(handler, user="quota resumed", tier="write")
    assert third[1] == "nemotron-super-vl"
    assert calls == {"tf": 2, "nim": 2}
    assert llm_budget.status()["tfQuota"] == {"state": "ok", "until": None}


def test_I5_catalogue_deadline_still_reaches_nim(monkeypatch):
    monkeypatch.delenv("NAVIGUIDE_LLM_PROVIDERS", raising=False)
    monkeypatch.setenv("NAVIGUIDE_LLM_TIMEOUT_FALLBACK", "1")
    monkeypatch.setenv("NAVIGUIDE_TF_MODEL_GUARD", "1")
    monkeypatch.setenv("NAVIGUIDE_TF_TIMEOUT_S", "0.03")
    monkeypatch.setenv("NVIDIA_API_KEY", "nv-test")
    seen = []

    async def handler(req):
        seen.append(str(req.url))
        if "tokenfactory" in str(req.url):
            await asyncio.sleep(0.08)  # catalogue GET expires within the shared TF budget
            return httpx.Response(200, json={"data": []})
        body = json.loads(req.read().decode())
        return httpx.Response(200, json=_ok(body.get("model", "nim")))

    res = _run(handler, tier="write")
    assert res[1].startswith("nvidia-")
    assert any("tokenfactory" in url for url in seen)
    assert any("nvidia" in url for url in seen)


def test_R3_timeout_is_a_total_deadline(monkeypatch):
    """httpx read=1 s mais un serveur qui égrène un octet / 0,4 s pendant ~3 s."""
    monkeypatch.setenv("NAVIGUIDE_LLM_PROVIDERS", "tokenfactory")
    monkeypatch.setenv("NAVIGUIDE_TF_TIMEOUT_S", "1")
    async def go():
        async def serve(reader, writer):
            await reader.readuntil(b"\r\n\r\n")
            await asyncio.sleep(0.05)
            body = json.dumps(_ok("nvidia/Nemotron-3.5-Super-VL")).encode()
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\n\r\n")
            await writer.drain()
            chunks = [body[i:i + max(1, len(body) // 8)] for i in range(0, len(body), max(1, len(body) // 8))]
            for c in chunks:
                writer.write(f"{len(c):x}\r\n".encode() + c + b"\r\n"); await writer.drain(); await asyncio.sleep(0.4)
            writer.write(b"0\r\n\r\n"); await writer.drain(); writer.close()
        srv = await asyncio.start_server(serve, "127.0.0.1", 0)
        port = srv.sockets[0].getsockname()[1]
        monkeypatch.setattr(story_cascade, "TOKENFACTORY_URL", f"http://127.0.0.1:{port}/v1/chat/completions")
        async with srv, httpx.AsyncClient() as c:
            t0 = time.monotonic()
            res = await cascade_text("sys", "La ZEE.", c, tier="write", fallback="Phrase locale.", facts={})
            return res, time.monotonic() - t0
    (text, source), dt = asyncio.run(go())
    assert dt < 2.0, f"échéance dépassée : {dt:.2f} s pour 1 s"
    assert source == "rules"


def test_R4_nano_queue_timeout_does_not_double(monkeypatch):
    """Nano : file pleine → timeout file, puis repli Lightning qui ré-attend la même file."""
    monkeypatch.setenv("NAVIGUIDE_LLM_PROVIDERS", "tokenfactory")
    monkeypatch.setenv("NAVIGUIDE_TF_PARALLEL", "1")
    monkeypatch.setenv("NAVIGUIDE_TF_TIMEOUT_S", "0.5")
    story_cascade.reset_runtime()
    async def go():
        sema = story_cascade._tf_limiter(); await sema.acquire()
        try:
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=_ok("x")))) as c:
                t0 = time.monotonic()
                res = await cascade_text("sys", "La ZEE.", c, tier="nano", fallback="Phrase locale.", facts={})
                return res, time.monotonic() - t0
        finally:
            sema.release()
    (text, source), dt = asyncio.run(go())
    lat = llm_budget.latency_status()
    assert source == "rules"
    assert dt < 0.9, f"file attendue deux fois : {dt:.2f} s"
    assert "fast" not in lat or not (lat.get("fast") or {}).get("timeouts")


def test_R5_http_timeout_counts_budget(monkeypatch):
    """Un timeout HTTP compte une estimation prudente au plafond du jour."""
    monkeypatch.setenv("NAVIGUIDE_LLM_PROVIDERS", "tokenfactory")
    before = int(llm_budget.get_usage("write")["tokens"])
    def h(req):
        raise httpx.ReadTimeout("slow", request=req)
    _run(h, tier="write")
    after = int(llm_budget.get_usage("write")["tokens"])
    assert after - before >= llm_budget.max_tokens_for("write")
