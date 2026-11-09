"""L-4: Captain cart/reply payment_mode matches GET /api/escales/pledges/mode."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.core.llm as llm
from app.escales.captain import chat, payment_mode_wording
from app.escales.pledges import reset_ledger
from app.routers.escales import router


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_VAULT_ENABLED", "1")
    monkeypatch.delenv("ESCALES_LLM_ENABLED", raising=False)
    monkeypatch.setattr(llm, "has_llm", lambda settings=None: False)
    reset_ledger()
    yield
    reset_ledger()


def _api_mode(client: TestClient, milestone_id: str, kind: str) -> str:
    response = client.get(
        "/api/escales/pledges/mode",
        params={"milestone_id": milestone_id, "kind": kind},
    )
    assert response.status_code == 200
    return response.json()["payment_mode"]


@pytest.mark.parametrize(
    "clock,message,lang,milestone,kind",
    [
        (
            "2026-11-19T08:00:00Z",
            "Je veux parrainer 10 milles près de Mayotte",
            "fr",
            "dep-dzaoudzi-mayotte",
            "mile",
        ),
        (
            "2026-11-19T08:00:00Z",
            "I'd like to sponsor 10 nautical miles near La Rochelle",
            "en",
            "dep-la-rochelle",
            "mile",
        ),
    ],
)
def test_captain_cart_and_reply_match_pledge_mode_preview(
    monkeypatch, clock, message, lang, milestone, kind,
):
    monkeypatch.setenv("ESCALES_CLOCK_NOW", clock)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    expected = _api_mode(client, milestone, kind)

    async def run():
        return await chat(message, lang=lang)

    result = asyncio.run(run())
    pledge = result["suggested_pledge"]
    cart = result["cart"]
    assert pledge is not None
    assert cart is not None
    assert pledge["payment_mode"] == expected
    assert pledge["intent"] == expected
    assert cart["payment_mode"] == expected
    assert cart["intent"] == expected
    for line in cart["lines"]:
        assert line.get("payment_mode") == expected
        assert line.get("intent") == expected

    wording = payment_mode_wording(expected, lang).casefold()
    assert wording[:40] in result["reply"].casefold() or expected.casefold() in result["reply"].casefold()
    if expected == "VAULT":
        assert "vault" in result["reply"].casefold() or "coffre" in result["reply"].casefold()
    else:
        assert "authoriz" in result["reply"].casefold() or "autorisation" in result["reply"].casefold()
