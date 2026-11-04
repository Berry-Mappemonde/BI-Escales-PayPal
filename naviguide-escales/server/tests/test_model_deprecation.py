"""Token Factory model ids must not stay on the November 2026 deprecation list."""

from __future__ import annotations

import llm_budget


def test_configured_models_not_on_deprecation_list():
    bad = {
        tier: model_id
        for tier, model_id in llm_budget.configured_models().items()
        if model_id in llm_budget.DEPRECATED_TOKEN_FACTORY_MODELS
    }
    assert bad == {}, f"deprecated models still configured: {bad}"


def test_deprecation_list_matches_nebius_november_2026():
    assert "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B" in llm_budget.DEPRECATED_TOKEN_FACTORY_MODELS
    assert "nvidia/nemotron-3-super-120b-a12b" in llm_budget.DEPRECATED_TOKEN_FACTORY_MODELS
    assert llm_budget.model_for("fast") not in llm_budget.DEPRECATED_TOKEN_FACTORY_MODELS
    assert llm_budget.model_for("write") not in llm_budget.DEPRECATED_TOKEN_FACTORY_MODELS
    assert llm_budget.model_for("deep") not in llm_budget.DEPRECATED_TOKEN_FACTORY_MODELS
