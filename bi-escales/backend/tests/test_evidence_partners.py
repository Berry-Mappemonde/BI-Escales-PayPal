"""Preuves d'escale optionnelles (Elastic, KERNEL, Channel3)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales.captain import review
from app.escales.evidence_elastic import build_evidence as elastic_evidence
from app.escales.evidence_kernel import build_evidence as kernel_evidence
from app.escales.milestones import record_evidence
from app.escales.pledges import reset_ledger


@pytest.fixture(autouse=True)
def memory_store(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.delenv("ESCALES_ELASTIC_ENABLED", raising=False)
    monkeypatch.delenv("ESCALES_KERNEL_ENABLED", raising=False)
    monkeypatch.delenv("ESCALES_CHANNEL3_ENABLED", raising=False)
    reset_ledger()
    yield
    reset_ledger()


def test_record_evidence_defaults_to_simulation():
    async def run():
        evidence = await record_evidence("dep-mayotte", met=True, facts={"port": "Mayotte"})
        assert evidence["provider"] == "NAVIGUIDE"
        assert evidence["flag"] == "simulation"

    asyncio.run(run())


def test_kernel_evidence_when_enabled(monkeypatch):
    monkeypatch.setenv("ESCALES_KERNEL_ENABLED", "1")

    async def run():
        direct = await kernel_evidence("dep-mayotte", True, {"boats": 1})
        assert direct["provider"] == "KERNEL"
        stored = await record_evidence("dep-mayotte", True, {"boats": 1})
        assert stored["provider"] == "KERNEL"

    asyncio.run(run())


def test_elastic_disabled_returns_none():
    async def run():
        assert await elastic_evidence("dep-mayotte", True, {}) is None

    asyncio.run(run())


def test_channel3_enriches_proposal_without_capture(monkeypatch):
    monkeypatch.setenv("ESCALES_CHANNEL3_ENABLED", "1")

    async def run():
        await record_evidence("dep-mayotte", met=True, facts={"port": "Mayotte"})
        proposal = await review("dep-mayotte", reader=None)
        assert proposal["proposal"] == "capture"
        assert proposal["channel3"]["status"] == "proposed"
        assert "départ" in proposal["channel3"]["note"].lower()
        assert "automatique" in proposal["channel3"]["note"].lower()

    asyncio.run(run())
