import multiprocessing

import httpx
import llm_budget
import story_cascade


def _record_timeouts(voyage_dir):
    import os
    os.environ["NAVIGUIDE_VOYAGE_DIR"] = voyage_dir
    import pearl_store
    pearl_store.reset()
    for _ in range(50):
        llm_budget.record_latency_timeout("fast")
        llm_budget.record_latency("fast", 17)
        llm_budget.record("fast", 1, 2)


def _run_failure(failure):
    async def go():
        async def handler(_request):
            if isinstance(failure, BaseException):
                raise failure
            return failure
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await story_cascade.cascade_text(
                "sys", "La ZEE.", client, tier="fast", fallback="Phrase locale.", facts={},
            )
    import asyncio
    asyncio.run(go())


def test_failed_tokenfactory_attempts_are_separate_from_success_samples(monkeypatch):
    monkeypatch.setenv("NEBIUS_API_KEY", "tf-test")
    monkeypatch.setenv("NAVIGUIDE_LLM_PROVIDERS", "tokenfactory")
    monkeypatch.setenv("NAVIGUIDE_TF_MODEL_GUARD", "0")
    _run_failure(httpx.ConnectError("offline"))
    network_row = llm_budget.status()["latency"]["fast"]
    assert network_row["networkErrors"]["count"] == 1
    assert network_row["networkErrors"]["last"]["ms"] >= 0
    assert network_row["samples"] == 0


def test_http_errors_include_status_and_duration_without_success_samples(monkeypatch):
    monkeypatch.setenv("NEBIUS_API_KEY", "tf-test")
    monkeypatch.setenv("NAVIGUIDE_LLM_PROVIDERS", "tokenfactory")
    monkeypatch.setenv("NAVIGUIDE_TF_MODEL_GUARD", "0")
    _run_failure(httpx.Response(503, json={"error": "busy"}))
    row = llm_budget.status()["latency"]["fast"]
    assert row["httpErrors"]["count"] == 1
    assert row["httpErrors"]["last"]["status"] == 503
    assert row["httpErrors"]["last"]["ms"] >= 0
    assert row["samples"] == 0


def test_latency_counter_updates_are_atomic_across_processes(monkeypatch):
    import pearl_store
    shared_dir = pearl_store.db_path().parent
    monkeypatch.setenv("NAVIGUIDE_VOYAGE_DIR", str(shared_dir))
    pearl_store.reset()
    pearl_store.kv_get("atomic-test", "initialized")
    ctx = multiprocessing.get_context("spawn")
    workers = [ctx.Process(target=_record_timeouts, args=(str(shared_dir),)) for _ in range(4)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(20)
        assert worker.exitcode == 0
    assert llm_budget.latency_status()["fast"]["timeouts"] == 200
    usage = llm_budget.get_usage("fast")
    assert usage["calls"] == 200
    assert usage["tokens"] == 600
    latency = llm_budget.latency_status()["fast"]
    assert latency["calls"] == 200
    assert latency["samples"] == 51
