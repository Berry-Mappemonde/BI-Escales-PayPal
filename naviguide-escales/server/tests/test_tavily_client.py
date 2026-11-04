"""Client Tavily — faux serveur POST /extract et /search."""
import asyncio
import json

import httpx

import llm_budget
import tavily_client


def test_extract_posts_and_counts_one_credit(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, str(request.url)))
        assert request.method == "POST"
        assert str(request.url) == "https://api.tavily.com/extract"
        body = json.loads(request.read().decode())
        assert body["urls"] == ["https://douane.gouv.fr/x"]
        assert body["extract_depth"] == "basic"
        return httpx.Response(200, json={
            "results": [{
                "url": "https://douane.gouv.fr/x",
                "raw_content": "Fort-de-France est un port d'entrée officiel.",
            }],
            "failed_results": [],
        })

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await tavily_client.extract(
                ["https://douane.gouv.fr/x"], depth="basic", client=client,
            )

    out = asyncio.run(run())
    assert "Fort-de-France" in out["text"]
    assert seen == [("POST", "https://api.tavily.com/extract")]
    usage = llm_budget.tavily_usage()
    assert usage["credits"] == 1 and usage["calls"] == 1
    assert llm_budget.status()["tavily"]["credits"] == 1


def test_search_posts_and_counts_one_credit(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        assert request.method == "POST"
        assert str(request.url) == "https://api.tavily.com/search"
        body = json.loads(request.read().decode())
        assert body["query"] == "Fort-de-France port avis"
        assert body["topic"] == "news"
        assert body["days"] == 7
        assert body["max_results"] == 5
        assert body["include_domains"] == ["douane.gouv.fr"]
        return httpx.Response(200, json={
            "results": [{"title": "Avis", "url": "https://douane.gouv.fr/a", "content": "ok"}],
        })

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await tavily_client.search(
                "Fort-de-France port avis",
                topic="news",
                days=7,
                max_results=5,
                include_domains=["douane.gouv.fr"],
                client=client,
            )

    out = asyncio.run(run())
    assert out["results"][0]["title"] == "Avis"
    assert seen == ["https://api.tavily.com/search"]
    assert llm_budget.tavily_usage()["credits"] == 1


def test_no_key_makes_no_request(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"results": []})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            a = await tavily_client.extract(["https://douane.gouv.fr/x"], client=client)
            b = await tavily_client.search("Fort-de-France", client=client)
            return a, b

    a, b = asyncio.run(run())
    assert a["text"] == "" and a["credits"] == 0
    assert b["results"] == [] and b["credits"] == 0
    assert seen == []
    assert llm_budget.tavily_usage()["calls"] == 0
